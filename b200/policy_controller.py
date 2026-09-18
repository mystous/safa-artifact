"""다정책 gate 컨트롤러 — gate 해제 순서를 정책별로 바꿔 여러 스케줄러를 공정 비교한다.

동일 K8s 프레임워크(schedulingGate + 기본 kube-scheduler) 위에서 --policy 만 바꾸면
서로 다른 스케줄링 정책이 된다. baseline(gate 없음, 순수 default FIFO)과 별개로,
gate 기반 FIFO/SJF/Priority/LAS/SFQA 를 같은 오버헤드 조건에서 비교한다(리젝 ③ 대응).

정책:
  fifo      — pod 생성시각 순(오래된 것 먼저)
  sjf       — squad.io/duration 짧은 것 먼저 (JCT 최소화, starvation 유발)
  priority  — squad.io/priority 높은 것 먼저
  las       — least-attained-service(받은 GPU-time 적은 것 먼저, Tiresias 근사)
  themis    — finish-time fairness 근사 ρ=(대기+잔여)/ideal, ρ 큰 잡 우선(시뮬 Themis와 동일)
  sfqa      — P* = P + α·A·R (starvation 방지, 고정 노브)
  sfqa-auto — zero-knob v2(docs/ADAPTIVE_SFQA_DESIGN.md): min mean JCT s.t. BSLD≤σ*(t).
              σ*=1/(1−ρ̂) (PS-fair 한계), W*=σ*·max(s,τ)−s, u=대기/W*.
              2-tier: u≥1(제약 위반)은 u·R 내림차순 우선, 나머지는 SJF.
  easy      — EASY-backfilling(HPC 표준): FIFO + 선두 예약. 선두가 안 들어가면
              실행 중 잡의 예상 종료시각으로 예약 시점 T를 잡고, T 전에 끝나는
              뒤 잡만 backfill(예약 침해 금지). duration 추정을 쓰는 강한 베이스라인.

실행(호스트): /raid/squad/venv/bin/python policy_controller.py --policy sjf --period 5
"""
import argparse
import time
from datetime import datetime, timedelta, timezone

from kubernetes import client, config

from squad_algo import Server, PendingJob, Params, Slot, reorder_queue, compute_r_table

GPU = "nvidia.com/gpu"
GPU_PRODUCT = "nvidia.com/gpu.product"
GATE = "squad.io/sfqa"
FLAVOR_LBL = "squad.io/gpu-type"
DUR_LBL = "squad.io/duration"
EST_LBL = "squad.io/duration-est"  # f-모델 추정치(있으면 EASY 예약은 이것만 봄)
PRIO_LBL = "squad.io/priority"
AGE_ANNO = "squad.io/age"
AGE_UPDATED = "squad.io/age-updated"
AGE_STEP_MIN = 10


def load():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api()


def pod_gpu(p):
    t = 0
    for c in p.spec.containers:
        lim = (c.resources.limits or {}) if c.resources else {}
        if GPU in lim:
            t += int(str(lim[GPU]))
    return t


def has_gate(p):
    return any(g.name == GATE for g in (p.spec.scheduling_gates or []))


def lbl(p, k, d="0"):
    return (p.metadata.labels or {}).get(k, d)


def key(p):
    return f"{p.metadata.namespace}/{p.metadata.name}"


def build_servers(nodes, pods, flavor):
    used = {}
    for p in pods:
        if p.spec.node_name and p.status.phase not in ("Succeeded", "Failed"):
            used[p.spec.node_name] = used.get(p.spec.node_name, 0) + pod_gpu(p)
    servers = []
    for n in nodes:
        if (n.metadata.labels or {}).get(GPU_PRODUCT, "any") != flavor:
            continue
        total = min(8, int(str((n.status.allocatable or {}).get(GPU, "0"))))
        s = Server(name=n.metadata.name, gpu_type=flavor, total=total)
        u = used.get(n.metadata.name, 0)
        for j in range(total):
            s.slots[j] = Slot.FIXED if j < u else Slot.EMPTY
        servers.append(s)
    return servers


class PolicyCtrl:
    def __init__(self, v1, policy, params, period, age_unit, tau=10.0,
                 release="blocking", age_mode="counter"):
        self.v1 = v1
        self.policy = policy
        self.params = params
        self.period = period
        self.age_unit = age_unit  # age 1 증가에 필요한 대기 초(실측 스케일에 맞춤)
        # 해제 규율: blocking(권장 — 선두 fit 불가 시 패스 중단, p1 보존) | greedy(기존 재현용)
        self.release = release
        # 나이 의미론: counter(권장 — 도착 순번 기반, 시뮬과 동일) | wall(기존 재현용)
        self.age_mode = age_mode
        self.seen_pods = {}       # key -> 도착 순번(creationTimestamp 순위로 결정적 재구성)
        self.attained = {}  # LAS: job_key -> 누적 GPU-second
        # sfqa-auto(v2) 상태 — 전부 측정값에서 유도, 튜닝 노브 없음
        self.tau = tau            # BSLD floor(Feitelson 관례 10s) — 노브 아닌 문헌 상수
        self.rho_ewma = {}        # flavor -> EWMA(점유 GPU/전체)
        self.jct_sum = 0.0        # 완료 잡 JCT 합 (EWMA half-life 자기 스케일링용)
        self.jct_n = 0
        self.jct_seen = set()
        self.running_info = []    # easy: [(예상 종료시각, gpu)] — reconcile에서 갱신

    def age_of(self, p):
        """age = pending 대기 시간(now - creationTimestamp) / age_unit.
        대기 중인 동안 자동 증가하고, 스케줄되면 pending 집합에서 빠지며 자연 리셋된다.
        (원래 'AGE_STEP_MIN=10분=+1'은 원본 트레이스의 실제 시간 스케일이라, 시간압축한
        실측에선 큐잉이 초~분 단위여서 age 가 0 에 머무는 버그였다. → 실측 대기시간 기반으로 수정.)"""
        created = p.metadata.creation_timestamp
        if created is None:
            return 0
        wait = (datetime.now(timezone.utc) - created).total_seconds()
        return int(wait / self.age_unit)

    # ── sfqa-auto(v2) 유도량 — docs/ADAPTIVE_SFQA_DESIGN.md §2 ──────────────
    def _observe_completion(self, p):
        """완료 pod JCT 관측 → EWMA half-life 자기 스케일링 + Laplace 분모."""
        k = key(p)
        if k in self.jct_seen or not p.status.container_statuses:
            return
        term = p.status.container_statuses[0].state.terminated
        if term and term.finished_at and p.metadata.creation_timestamp:
            self.jct_seen.add(k)
            self.jct_sum += (term.finished_at - p.metadata.creation_timestamp).total_seconds()
            self.jct_n += 1

    def _update_rho(self, flavor, used, total):
        if total <= 0:
            return
        now = used / total
        half = max(self.jct_sum / self.jct_n if self.jct_n else 60.0, self.period)
        w = 0.5 ** (self.period / half)
        self.rho_ewma[flavor] = w * self.rho_ewma.get(flavor, now) + (1 - w) * now

    def sigma_star(self, flavor):
        """PS-fair slowdown 한계 σ*=1/(1−ρ̂). ρ̂는 Laplace 평활로 1 미만 보장."""
        rho = min(self.rho_ewma.get(flavor, 0.0), 1.0 - 1.0 / (self.jct_n + 2))
        return 1.0 / (1.0 - rho)

    def order(self, gated, servers, ar, flavor):
        """정책별 gate 해제 순서(앞이 먼저)."""
        if self.policy == "sfqa-auto":
            # 논문 알고리즘(sim SFQAAuto)의 충실 이식 — zero-knob 단일 승격.
            # α_eff = g/(A_ref·R_min), age_rel=age−min(age)(큐 상대, 스케일 불변),
            # P*=P+α_eff·age_rel·R. duration·σ*·SJF 전혀 쓰지 않음(부차 정보 無).
            # 이전 σ*-2-tier 구현은 tier2가 SJF라 불공정했음 → 폐기(B200 lt50 28.6 회귀).
            base = 2.0
            R = compute_r_table(servers, flavor)
            now = datetime.now(timezone.utc)
            # FIFO 기준(오래된 것이 position 0 = 기저 우선) 위에서 1건만 승격.
            fifo = sorted(gated, key=lambda p: p.metadata.creation_timestamp)
            n = len(fifo)
            if n <= 1:
                return fifo
            if self.age_mode == "counter":
                # 도착-카운터 나이(시뮬 의미론): age_i = (지금까지 도착한 총 잡 수) - (자기 순번).
                # 순번은 creationTimestamp 순위에서 유도 → 컨트롤러 재시작에도 결정적.
                for p in fifo:
                    k = key(p)
                    if k not in self.seen_pods:
                        self.seen_pods[k] = len(self.seen_pods)
                total_seen = len(self.seen_pods)
                ages = [float(total_seen - self.seen_pods[key(p)]) for p in fifo]
            else:
                ages = [(now - p.metadata.creation_timestamp).total_seconds() for p in fifo]
            rq = []
            for p in fifo:
                k = max(1, min(8, pod_gpu(p)))
                r = R[k - 1] if R[k - 1] > 0 else 0.5
                rq.append(r)
            amin = min(ages)
            age_rel = [a - amin for a in ages]
            aref = max(1.0, sum(age_rel) / n)
            rmin = max(0.1, min(rq))
            g = min(1.0, max(age_rel) / aref)
            alpha_eff = g / (aref * rmin)
            best_i, best_v = 0, None
            for i in range(n):
                P = 1.0 / (base ** i) if i < 60 else 0.0
                v = P + alpha_eff * age_rel[i] * rq[i]
                if best_v is None or v > best_v:
                    best_v, best_i = v, i
            if best_i == 0:
                return fifo
            return [fifo[best_i]] + fifo[:best_i] + fifo[best_i + 1:]
        if self.policy == "easy":
            # EASY-backfilling: FIFO 순서, 선두 예약 시점 T를 침해하지 않는 잡만 통과.
            # 반환 = ungate 허용 집합(순서 포함) — reconcile 의 capacity 루프가 그대로 적용.
            fifo = sorted(gated, key=lambda p: p.metadata.creation_timestamp)
            free = sum(s.available() for s in servers)
            now = datetime.now(timezone.utc)
            out = []
            for i, p in enumerate(fifo):
                g = pod_gpu(p)
                if g <= free:
                    out.append(p)
                    free -= g
                    continue
                # 선두 막힘 → 예약 시점 T: 실행 중 잡 종료 누적으로 g 확보되는 시각
                avail, T = free, None
                for end, rg in sorted(self.running_info):
                    avail += rg
                    if avail >= g:
                        T = end
                        break
                for q in fifo[i + 1:]:   # T 전에 끝나는 잡만 backfill (추정 기준)
                    gq = pod_gpu(q)
                    dq = float(lbl(q, EST_LBL, lbl(q, DUR_LBL, "0")))
                    if gq <= free and (T is None or now + timedelta(seconds=dq) <= T):
                        out.append(q)
                        free -= gq
                break
            return out
        if self.policy == "sfqa":
            by_key = {key(p): p for p in gated}
            jobs = [PendingJob(key(p), pod_gpu(p), flavor, age=self.age_of(p))
                    for p in gated]
            ordered = reorder_queue(jobs, servers, flavor, self.params, ar)
            return [by_key[j.id] for j in ordered]
        if self.policy == "sjf":
            return sorted(gated, key=lambda p: int(lbl(p, DUR_LBL)))
        if self.policy == "priority":
            return sorted(gated, key=lambda p: -int(lbl(p, PRIO_LBL)))
        if self.policy == "las":
            return sorted(gated, key=lambda p: self.attained.get(key(p), 0.0))
        if self.policy == "themis":
            # finish-time fairness 근사(시뮬 Themis와 동일): ρ=(대기+잔여)/ideal,
            # ideal=dur/min(fair,gpu)·gpu, fair=총GPU/대기수. ρ 큰(가장 불공정한) 잡 우선.
            now = datetime.now(timezone.utc)
            total = sum(s.total for s in servers) or 8
            fair = max(1.0, total / max(1, len(gated)))

            def _rho(p):
                g = max(1, pod_gpu(p))
                dur = max(1.0, float(lbl(p, DUR_LBL, "1")))
                waited = (now - p.metadata.creation_timestamp).total_seconds()
                t_ideal = dur / min(fair, g) * g
                return (waited + dur) / max(t_ideal, 1.0)
            return sorted(gated, key=lambda p: -_rho(p))
        # fifo (기본): 생성시각 순
        return sorted(gated, key=lambda p: p.metadata.creation_timestamp)

    def ungate(self, p):
        keep = [{"name": g.name} for g in (p.spec.scheduling_gates or []) if g.name != GATE]
        op = ([{"op": "replace", "path": "/spec/schedulingGates", "value": keep}] if keep
              else [{"op": "remove", "path": "/spec/schedulingGates"}])
        try:
            self.v1.patch_namespaced_pod(p.metadata.name, p.metadata.namespace, op)
        except client.ApiException:
            pass

    def _patch(self, p, body):
        try:
            self.v1.patch_namespaced_pod(p.metadata.name, p.metadata.namespace, body)
        except client.ApiException:
            pass

    def reconcile(self):
        nodes = self.v1.list_node().items
        pods = self.v1.list_pod_for_all_namespaces().items

        alloc, used = {}, {}
        node_flavor = {}
        for n in nodes:
            f = (n.metadata.labels or {}).get(GPU_PRODUCT, "any")
            node_flavor[n.metadata.name] = f
            alloc[f] = alloc.get(f, 0) + int(str((n.status.allocatable or {}).get(GPU, "0")))

        pending = {}
        self.running_info = []
        for p in pods:
            g = pod_gpu(p)
            if g == 0:
                continue
            if p.spec.node_name and p.status.phase == "Running":
                f = node_flavor.get(p.spec.node_name, "any")
                used[f] = used.get(f, 0) + g
                self.attained[key(p)] = self.attained.get(key(p), 0.0) + self.period * g  # LAS 누적
                st = p.status.start_time or p.metadata.creation_timestamp
                if st:  # easy: 예상 종료시각(시작 + duration *추정* — est 라벨 있으면 그것)
                    dur = float(lbl(p, EST_LBL, lbl(p, DUR_LBL, "0")))
                    self.running_info.append((st + timedelta(seconds=dur), g))
            elif has_gate(p) and p.status.phase == "Pending":
                f = lbl(p, FLAVOR_LBL, "any")
                pending.setdefault(f, []).append(p)
            elif p.status.phase == "Succeeded":
                self._observe_completion(p)  # sfqa-auto: JCT 관측(half-life·Laplace)

        for f in alloc:
            self._update_rho(f, used.get(f, 0), alloc[f])  # sfqa-auto: ρ EWMA

        for f, gated in pending.items():
            total = alloc.get(f, 0)
            ar = (used.get(f, 0) / total * 100) if total else 0.0
            servers = build_servers(nodes, pods, f)
            ordered = self.order(gated, servers, ar, f)
            free = max(0, total - used.get(f, 0))
            blocking = (self.release == "blocking" and self.policy in ("sfqa", "sfqa-auto", "fifo"))
            for p in ordered:
                g = pod_gpu(p)
                if g <= free:
                    self.ungate(p)
                    free -= g
                elif blocking:
                    break  # 선두 보존: greedy 스킵은 p1 붕괴(논문 §SAFA:k8s 측정). wedge는 정적 검사로 사전 격리 전제.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--policy", default="sfqa",
                    choices=["fifo", "sjf", "priority", "las", "themis", "sfqa", "sfqa-auto", "easy"])
    ap.add_argument("--period", type=float, default=5.0)
    ap.add_argument("--alpha", type=float, default=0.13889)
    ap.add_argument("--beta", type=float, default=80.0)
    ap.add_argument("--age-unit", type=float, default=10.0,
                    help="age 1 증가에 필요한 대기 초. 실측 큐잉 스케일에 맞춤(기본 10s)")
    ap.add_argument("--tau", type=float, default=10.0,
                    help="sfqa-auto BSLD floor(초). Feitelson 관례 10s — 노브 아닌 문헌 상수")
    ap.add_argument("--release", default="blocking", choices=["blocking", "greedy"],
                    help="게이트 해제 규율. blocking=선두 보존(권장, p1 유지), greedy=기존 재현")
    ap.add_argument("--age-mode", default="counter", choices=["counter", "wall"],
                    help="나이 의미론. counter=도착 순번(권장, 시뮬 동일), wall=기존 재현")
    args = ap.parse_args()
    v1 = load()
    ctrl = PolicyCtrl(v1, args.policy, Params(alpha=args.alpha, beta=args.beta, prevent_starv=True),
                      args.period, args.age_unit, tau=args.tau,
                      release=args.release, age_mode=args.age_mode)
    print(f"[policy:{args.policy}] start period={args.period}s", flush=True)
    while True:
        try:
            ctrl.reconcile()
        except Exception as e:  # noqa
            print(f"[policy] err: {e}", flush=True)
        time.sleep(args.period)


if __name__ == "__main__":
    main()
