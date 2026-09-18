"""배치 축 실험 하니스 — SAFA(SFQA)의 순서 공정성 이점이 4개 배치 전부에서 유지되는가?

SAFA는 큐 **재정렬** 전처리기로, 그 아래 코어 GPU **배치** 스케줄러와 무관하게 동작한다고
주장한다. 본 하니스는 배치를 most-allocated / compact / round_robin / mcts 4종으로 바꿔도
SAFA의 p1(worst-1% order-fairness) 이점이 유지됨을 실증한다.

배치 교체: 정책 인스턴스의 pref_fn(또는 node_pref 콜러블)을 해당 함수로 주입.
측정: 각 (배치, 정책, 구성)에서 q_p50(중앙 큐 지연), fair_p1(order-fairness worst-1%),
      그리고 mcts 비용(wall-clock, 롤아웃 호출수).

사용:
  python3 sim/placement_axis.py                 # 전 조합(병렬, 워커 6)
  python3 sim/placement_axis.py --workers 6 --subsample 30000
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "squad_ctrl"))

from engine import Job, Node, Overheads, Simulator           # noqa: E402
import policies as P                                          # noqa: E402
import placement_prefs as PP                                  # noqa: E402
from order_fairness import per_job_score                      # noqa: E402
from fairness import gini                                      # noqa: E402

OUT = os.path.join(HERE, "sweep_results", "placement")

# 배치: 코어 4종 + FGD + KAI 2전략(binpack/spread) + 이종 best-fit. mcts는 인스턴스(상태/sim 주입).
PLACEMENTS = ["mostallocated", "compact", "round_robin", "mcts", "fgd",
              "kai_binpack", "kai_spread", "bestfit_type"]
# 정책: 핵심 SAFA(sfqa-auto) + 베이스라인. 여유 시 sfqa(고정)·las 추가.
POLICIES = ["sfqa-auto", "fifo", "sjf", "sfqa", "las"]


def load_trace(path, subsample=0, seed=7):
    rows = []
    for r in csv.DictReader(open(path)):
        vc = r.get("vc") or "default"
        rows.append((r["job_id"], float(r["arrival_s"]), max(1.0, float(r["service_sec"])),
                     int(r["gpu_count"]), vc))
    if subsample and subsample < len(rows):
        # 도착시각 정렬 후 균등 stride 서브샘플(시간 구조·부하 곡선 보존). 모든 배치가 동일 샘플.
        rows.sort(key=lambda x: x[1])
        stride = len(rows) / subsample
        rows = [rows[int(i * stride)] for i in range(subsample)]
    return rows


def build_nodes(gpu, kind):
    n_nodes = gpu // 8
    if kind == "single":
        return [Node(name=f"b200-{i}", gpu_type="b200", total=8) for i in range(n_nodes)]
    base = n_nodes // 3
    rem = n_nodes - base * 3
    counts = [base + (1 if i < rem else 0) for i in range(3)]
    types = ["b200", "h100", "a100"]
    nodes, idx = [], 0
    for t, c in zip(types, counts):
        for _ in range(c):
            nodes.append(Node(name=f"{t}-{idx}", gpu_type=t, total=8)); idx += 1
    return nodes


def make_pref(placement, trace=None):
    """배치 이름 → (pref_fn 콜러블, mcts_instance 또는 None)."""
    if placement == "mostallocated":
        return P.pref_mostallocated, None
    if placement == "compact":
        return P.pref_compact, None
    if placement == "round_robin":
        return PP.RoundRobinPref(), None      # 상태 보존(회전)
    if placement == "mcts":
        m = PP.MCTSPref()
        return m, m
    if placement == "fgd":                    # 단편화 인지 배치(ΔF 최소 노드) 위에 SAFA 순서
        f = P.FGD()
        if trace is not None:
            f.set_dist([g for _, _, _, g, _ in trace])
        return f.node_pref, None
    if placement == "kai_binpack":            # KAI 기본 binpack(consolidate, free 적은 노드 우선)
        return P.pref_kai_binpack, None
    if placement == "kai_spread":             # KAI spread(분산, free 많은 노드 우선)
        return P.pref_kai_spread, None
    if placement == "bestfit_type":           # 이종 타입-인지 best-fit(같은 타입·빠른 타입 우선)
        return P.pref_bestfit_type, None
    raise ValueError(placement)


def fair_p1(jr):
    """order-fairness: (mean, worst-1% p1, lt50%) — analyze_sweep/run_kai 동일 정의."""
    jb = [(arr, start, 0) for _, arr, start, q, s, g in jr]
    if len(jb) < 100:
        return 0.0, 0.0, 0.0
    sc = sorted(per_job_score(jb))
    n = len(sc)
    lt50 = 100.0 * sum(1 for x in sc if x < 50) / n
    return sum(sc) / n, sc[int(n * .01)], lt50      # (mean, p1, lt50)


def run_one(placement, policy, gpu, kind, trace, no_overhead):
    nodes = build_nodes(gpu, kind)
    pol = P.make(policy)
    pref, mcts_inst = make_pref(placement, trace)
    pol.pref_fn = pref                          # 배치 주입(인스턴스 속성)
    if policy == "fgd":
        pol.set_dist([g for _, _, _, g, _ in trace])
    jobs = [Job(id=i, arrival=a, duration=d, gpu_count=g, gpu_type="any", vc=vc)
            for i, a, d, g, vc in trace]
    ovh = Overheads(enabled=not no_overhead)
    sim = Simulator(jobs, nodes, pol, overheads=ovh)
    if mcts_inst is not None:
        mcts_inst.sim = sim                     # mcts: 현재 대기 큐 접근 주입
        # node_pref가 pref_fn(=mcts_inst) 호출 시 sim을 통해 대기 잡 추출
    t0 = time.time()
    r = sim.run()
    wall = time.time() - t0
    jr = [(j.id, j.arrival, j.place_time, j.queue_delay, j.duration, j.gpu_count)
          for j in sim.finished if j.queue_delay is not None]
    qs = sorted(x[3] for x in jr)
    q_p50 = qs[min(len(qs) - 1, int(len(qs) * .5))] if qs else 0.0
    q_p99 = qs[min(len(qs) - 1, int(len(qs) * .99))] if qs else 0.0
    q_max = qs[-1] if qs else 0.0
    fmean, fp1, lt50 = fair_p1(jr)
    gini_wait = gini(qs)                          # 대기시간 분배 불평등(주 결과 동일)
    p99p50 = (q_p99 / q_p50) if q_p50 else 0.0     # 꼬리비(=주 결과 p99/p50)
    out = dict(placement=placement, policy=policy, gpu=gpu, kind=kind,
               n=len(jr), q_p50=round(q_p50, 1), q_p99=round(q_p99, 1),
               q_max=round(q_max, 1), lt50_pct=round(lt50, 3),
               fair_mean=round(fmean, 2), fair_p1=round(fp1, 2),
               gini_wait=round(gini_wait, 4), p99_p50=round(p99p50, 2),
               alloc_avg=round(r.get("alloc_avg", 0.0), 1), wall_s=round(wall, 2),
               mcts_calls=(mcts_inst.calls if mcts_inst else 0),
               mcts_rollouts=(mcts_inst.scored if mcts_inst else 0))
    return out


def _job(args):
    placement, policy, gpu, kind, trace, no_ovh = args
    try:
        return run_one(placement, policy, gpu, kind, trace, no_ovh)
    except Exception as e:
        import traceback
        return dict(placement=placement, policy=policy, gpu=gpu, kind=kind,
                    error=f"{e}\n{traceback.format_exc()[:400]}")


def main():
    ap = argparse.ArgumentParser()
    _vc = os.path.join(HERE, "sweep_trace_vc.csv")
    ap.add_argument("--trace", default=_vc if os.path.exists(_vc) else os.path.join(HERE, "sweep_trace.csv"))
    ap.add_argument("--configs", default="512:single,512:hetero,256:hetero")
    ap.add_argument("--placements", default=",".join(PLACEMENTS))
    ap.add_argument("--policies", default=",".join(POLICIES))
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--subsample", type=int, default=0,
                    help="0=전체. mcts 구성만 별도 서브샘플하려면 --mcts-subsample 사용")
    ap.add_argument("--mcts-subsample", type=int, default=30000,
                    help="mcts 배치 한정 서브샘플(공정비교 위해 같은 샘플을 다른 배치에도 적용)")
    ap.add_argument("--no-overhead", action="store_true")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    placements = a.placements.split(",")
    policies = a.policies.split(",")
    configs = []
    for c in a.configs.split(","):
        g, k = c.split(":")
        configs.append((int(g), k))

    full = load_trace(a.trace, subsample=a.subsample)
    # mcts가 full 트레이스(111k)에서도 256:hetero ~66s로 현실적이라 서브샘플 불필요.
    # 모든 배치를 동일 full 트레이스로 돌려 완전 공정 비교(서브샘플로 인한 부하 밀도 왜곡 회피).
    scope = "full" if not a.subsample else f"sub{a.subsample}"
    print(f"trace n={len(full)}, "
          f"placements={placements}, policies={policies}, configs={configs}, workers={a.workers}",
          flush=True)

    tasks = []
    for g, k in configs:
        for pl in placements:
            for po in policies:
                tasks.append((pl, po, g, k, full, a.no_overhead, scope))

    rows = []
    fields = ["scope", "config", "placement", "policy", "gpu", "kind", "n",
              "q_p50", "q_p99", "q_max", "lt50_pct", "fair_mean", "fair_p1",
              "gini_wait", "p99_p50", "alloc_avg",
              "wall_s", "mcts_calls", "mcts_rollouts", "error"]
    t_all = time.time()
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = {ex.submit(_job, t[:6]): t[6] for t in tasks}
        done = 0
        for fu in as_completed(futs):
            scope = futs[fu]
            res = fu.result()
            res["scope"] = scope
            res["config"] = f"{res['gpu']}:{res['kind']}"
            rows.append(res)
            done += 1
            if "error" in res and res["error"]:
                print(f"  [{done}/{len(tasks)}] ERROR {scope} {res['placement']}/{res['policy']} "
                      f"{res['config']}: {res['error'][:120]}", flush=True)
            else:
                tag = ""
                if res["placement"] == "mcts":
                    tag = f" mcts[{res['mcts_calls']}c/{res['mcts_rollouts']}r {res['wall_s']}s]"
                print(f"  [{done}/{len(tasks)}] {scope} {res['placement']:13}/{res['policy']:10} "
                      f"{res['config']:11} q_p50={res['q_p50']:>10} p1={res['fair_p1']:>6}"
                      f"{tag}", flush=True)

    # CSV 덤프
    table = os.path.join(OUT, "placement_table.csv")
    with open(table, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x.get("scope", ""), x.get("config", ""),
                                             x.get("policy", ""), x.get("placement", ""))):
            w.writerow({k: r.get(k, "") for k in fields})
    print(f"\n→ {table}  ({len(rows)} rows, {time.time()-t_all:.1f}s)", flush=True)


if __name__ == "__main__":
    main()
