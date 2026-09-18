"""스케줄링 정책 — 큐 정렬(order) + 배치(place). 한 곳에서 모두 정의.

C++ 코어(mostallocated/compact/round_robin)와 SQUAD(SFQA/auto/PTR), 그리고
SOTA 베이스라인(Tiresias-LAS, Themis, Lucid, Sia, Gandiva, Optimus, Pollux,
EASY-backfill, Kueue)을 통일 인터페이스로 구현.

배치 규칙(place)은 commit=False면 fit만 검사(점유 안 함), 엔진이 점유를 직접 수행.
SOTA 중 탄력성이 본질인 것(Optimus/Pollux/Sia)은 고정요청 트레이스에서 degenerate됨을
주석에 명시(general-purpose 조사 결론). 단일 GPU타입에선 Sia≈Pollux, 2D-LAS≈1D-LAS.
"""
from __future__ import annotations

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from squad_algo import Server as AlgoServer, PendingJob, Params, Slot, reorder_queue, compute_r_table  # noqa: E402
from engine import speed_of  # noqa: E402  (이종 flavor-aware: 빠른 타입 우선 배치)


# ── 배치(node_pref) 헬퍼 — 엔진이 이 순서로 free GPU를 모아 멀티노드 gang 구성 ──────
# 이종 클러스터: 1차 키로 '빠른 타입 우선'(flavor-aware), 2차 키로 기존 정책 선호.
# 안정정렬이라 단일 타입에선 speed가 모두 같아 기존 순서 그대로(단일 결과 불변).
def _typed(job, nodes):
    """요청 타입과 호환되는 노드만(any는 모두)."""
    return [n for n in nodes if job.gpu_type in ("any", n.gpu_type) or n.gpu_type == "any"]


def pref_mostallocated(job, nodes):
    """C++ mostallocated: 빠른 타입 우선, 그 안에서 free 적은 노드 우선(단편화↓)."""
    return sorted(_typed(job, nodes), key=lambda n: (speed_of(n.gpu_type), n.free))


def pref_compact(job, nodes):
    """C++ compact: 빠른 타입 우선, 그 안에서 인덱스 순(앞 노드부터)."""
    return sorted(_typed(job, nodes), key=lambda n: speed_of(n.gpu_type))


def pref_bestfit_type(job, nodes):
    """이종 인지: 같은 타입 노드 먼저, 그 안에서 빠른 타입·mostallocated."""
    same = [n for n in nodes if n.gpu_type == job.gpu_type]
    rest = [n for n in nodes if n.gpu_type != job.gpu_type and n.gpu_type == "any"]
    return (sorted(same, key=lambda n: (speed_of(n.gpu_type), n.free)) +
            sorted(rest, key=lambda n: (speed_of(n.gpu_type), n.free)))


# ── 정책 베이스 ─────────────────────────────────────────────────────────────
class Policy:
    """order(cand_idx, age, ar, sim) → 배치 우선순위 인덱스 순서(numpy 또는 list).
    cand_idx: 도착했고 미배치인 잡의 인덱스(이미 도착순). age: cand_idx별 절대 누적 age 벡터.
    sim: SoA 배열(_arr_gpu/_arr_dur/_arr_arrival/_arr_attained/_arr_seq)·nodes·running 접근."""
    name = "base"
    blocking = False           # True면 order 선두가 안 들어가면 그 틱 배치 중단
    pref_fn = staticmethod(pref_mostallocated)

    def order(self, cand_idx, age, ar, sim):
        return cand_idx

    def node_pref(self, job, nodes):
        return self.pref_fn(job, nodes)


# ── 기본 큐 정책 ────────────────────────────────────────────────────────────
class FIFO(Policy):
    name = "fifo"; blocking = True
    def order(self, cand_idx, age, ar, sim):
        return cand_idx                                  # cand_idx는 이미 도착순


class SJF(Policy):
    name = "sjf"
    def order(self, cand_idx, age, ar, sim):
        return cand_idx[np.argsort(sim._arr_dur[cand_idx], kind="stable")]


class LAS(Policy):
    """Tiresias 2D-LAS: attained service(gpu_count×runtime) 작은 잡 우선.
    대기 잡은 attained=0이라 사실상 도착순. 선점 없으면 약함(조사 결론)."""
    name = "las"
    def order(self, cand_idx, age, ar, sim):
        return cand_idx[np.argsort(sim._arr_attained[cand_idx], kind="stable")]


class Themis(Policy):
    """finish-time fairness 근사: rho = (대기+잔여) / ideal. ideal=duration/fair_share.
    탄력·경매 생략(고정요청에선 ρ-우선 = 느린잡 우선). rho 큰 잡 우선."""
    name = "themis"
    def order(self, cand_idx, age, ar, sim):
        n = cand_idx.size
        fair = max(1.0, sim.total_gpu / max(1, n))
        gpu = sim._arr_gpu[cand_idx].astype(float)
        dur = sim._arr_dur[cand_idx]
        waited = sim.now - sim._arr_arrival[cand_idx]
        t_ideal = dur / np.minimum(fair, gpu) * gpu
        rho = (waited + dur) / np.maximum(t_ideal, 1.0)
        return cand_idx[np.argsort(-rho, kind="stable")]


class Lucid(Policy):
    """프로파일 기반 비선점 SJF + interference packing. 트레이스 재생이면 완벽 프로파일
    가정 → 정렬은 SJF, 배치는 compact(작은 서버부터 채워 단편화↓·collocation 유사)."""
    name = "lucid"; pref_fn = staticmethod(pref_compact)
    def order(self, wait, nodes, ar, sim):
        return sorted(wait, key=lambda j: j.duration)


class Sia(Policy):
    """이종 goodput 매칭(탄력 생략판): 타입 일치 best-fit 배치 + goodput 프록시 정렬.
    단일 타입이면 ≈ SJF(조사 결론). goodput∝1/duration 근사로 짧은·맞는 타입 우선."""
    name = "sia"; pref_fn = staticmethod(pref_bestfit_type)
    def order(self, wait, nodes, ar, sim):
        return sorted(wait, key=lambda j: j.duration)


# ── SQUAD ───────────────────────────────────────────────────────────────────
def _r_table_fast(nodes):
    """Resource suitability index R (저자 정의 — 서버마다 비교, 그 중 최댓값):
      각 서버 free에 대해: free ≥ req 면 1, 1개 부족할 때마다 0.1 감소(부족분 k → 1−0.1k).
      R[req-1] = max over servers (논문 line 10의 max{R_j, ...}).
    R[req-1], req=1..8."""
    R = [0.0] * 8
    for n in nodes:
        free = n.free
        for req in range(1, 9):
            short = req - free                       # 이 서버에서 req개에 부족한 수
            suit = 1.0 if short <= 0 else 1.0 - 0.1 * short
            if suit > R[req - 1]:
                R[req - 1] = suit                    # 서버 중 최댓값
    # floor 0
    return [x if x > 0 else 0.0 for x in R]


class SFQA(Policy):
    """고정 노브 SFQA: P*=P+α·A·R(AR≤β). 핫패스 최적화(객체 복사 제거, R 직접 계산).
    수식은 squad_algo.reorder_queue/C++ 원본과 동일.
    Algorithm 1: 큐 현재순서에서 P_i=1/2^i, P*_i=P_i+α·A_i·R. **P* 최댓값 잡 1개만**
    맨 앞으로 옮기고 나머지는 한 칸씩 뒤로(전체 정렬 아님, line 20-25).
    배치는 선두부터 못 넣으면 break(blocking=True, job_scheduler.cpp:19-21)."""
    name = "sfqa"; blocking = True
    def __init__(self, alpha=0.13889, beta=100.0):
        self.alpha = alpha; self.beta = beta
    def order(self, cand_idx, age, ar, sim):
        # cand_idx는 도착순. 미트리거(AR≥β)면 그대로.
        if cand_idx.size == 0 or ar >= self.beta:
            return cand_idx
        R = np.array(_r_table_fast(sim.nodes))
        gidx = np.clip(sim._arr_gpu[cand_idx].astype(int) - 1, 0, 7)
        n = cand_idx.size
        pos = np.arange(n)
        P = np.where(pos < 60, 1.0 / (2.0 ** np.minimum(pos, 60)), 0.0)
        pstar = P + self.alpha * age * R[gidx]        # P* = P + αA·R
        imax = int(np.argmax(pstar))                  # P* 최댓값 1개 (line 20)
        if imax == 0:
            return cand_idx
        return np.concatenate(([cand_idx[imax]], cand_idx[:imax], cand_idx[imax + 1:]))  # 단일승급


class SFQAAuto(Policy):
    """SFQA(논문) 식·동작 그대로, 계수 α만 적응적으로 결정. **duration(사후값) 미사용.**
    P*(j)=1/base^pos + α·A·R, 단일 승급, 무조건 발동(트리거 없음). (age=신규 도착마다 +1.)

    적응(관측 가능값만 — age 통계·부하, 외부 상수 0개):
      **age는 절대 누적(engine 유지). order에서 큐 상대화**: age_rel = age − min(큐 age).
        dequeue(배치)로 큐 멤버가 바뀌면 min이 갱신돼 남은 잡들의 상대 age가 자동 재기준.
        과포화에서 절대 age가 무한 누적돼도, 상대 age는 '현재 큐 spread'로 제한돼 안정.
      A_ref = 큐 상대 age 평균(동적). α = 1 / (A_ref · R_min) → age_rel=A_ref인 '자리 맞는'
        (R=1) 잡의 보너스가 1/R_min배 증폭돼 base priority P(맨앞=1)를 넘는다.
      g(동적 게이트): S = max(age_rel)/A_ref, g=min(1,S).
    원리: 절대 age는 맨앞이 최대라 항상 no-op. 큐-상대 + R_min 정규화로 자리 맞는 잡의
      보너스를 증폭해 큐를 막는 큰 잡을 추월(starvation-free). 상수 0개, duration-free."""
    name = "sfqa-auto"; blocking = True
    def __init__(self, base=2.0):
        self.base = base
    def order(self, cand_idx, age, ar, sim):
        if cand_idx.size == 0:                                # 무조건 발동(트리거 없음)
            return cand_idx
        Rr = np.array(_r_table_fast(sim.nodes)); Rr[Rr <= 0] = 0.5
        gidx = np.clip(sim._arr_gpu[cand_idx].astype(int) - 1, 0, 7)
        rq = Rr[gidx]                                          # 큐 잡들의 자리적합
        rmin = max(0.1, float(rq.min()))                       # 최악 자리적합(가장 큰 잡), floor 0.1
        age_rel = age - age.min()                              # 큐 상대 age(dequeue 시 자동 재기준)
        aref = max(1.0, float(age_rel.mean()))                 # 상대 age 스케일(동적, 큐 기준)
        S = (float(age_rel.max()) / aref) if cand_idx.size else 0.0   # starvation 압력
        g = min(1.0, S)                                        # 동적 게이트
        alpha_eff = g / (aref * rmin)                          # α=1/(A_ref·R_min): R차등이 P 넘게
        n = cand_idx.size
        pos = np.arange(n)
        P = np.where(pos < 60, 1.0 / (self.base ** np.minimum(pos, 60)), 0.0)
        pstar = P + alpha_eff * age_rel * rq                   # P*, 큐상대+R_min로 자리맞는 잡 승급
        imax = int(np.argmax(pstar))                           # 단일 승급(Algorithm 1)
        if imax == 0:
            return cand_idx
        return np.concatenate(([cand_idx[imax]], cand_idx[:imax], cand_idx[imax + 1:]))


# ── EASY-backfilling ────────────────────────────────────────────────────────
class EASY(Policy):
    """FIFO + 선두 예약 + 예약 침해 없는 backfill. duration(추정) 사용.
    실측 EASY와 동일 알고리즘. est_noise는 별도 주입(시뮬은 완벽 추정 기본)."""
    name = "easy"; blocking = False   # order()가 이미 허용집합만 반환
    def order(self, cand_idx, age, ar, sim):
        gpu = sim._arr_gpu; dur = sim._arr_dur                 # cand_idx는 이미 도착순(=FIFO)
        free = sum(n.free for n in sim.nodes)
        ends = sorted((j.finish_time, j.gpu_count) for j in sim.running.values())  # 종료시각 예측
        out = []
        cl = cand_idx.tolist()
        for k in range(len(cl)):
            i = cl[k]
            if gpu[i] <= free:
                out.append(i); free -= int(gpu[i]); continue
            # 예약 시각 T: 종료 누적으로 head(i) 확보 시점
            avail, T = free, None
            for end, g in ends:
                avail += g
                if avail >= gpu[i]:
                    T = end; break
            for j in cl[k + 1:]:                               # 예약 침해 없는 backfill
                if gpu[j] <= free and (T is None or sim.now + dur[j] <= T):
                    out.append(j); free -= int(gpu[j])
            break
        return out                                            # 허용집합(idx 리스트)


class Kueue(Policy):
    """충실 Kueue: per-VC(테넌트) 쿼타 기반 공정 공유 + 유휴 시 빌려쓰기(borrowing).

    실제 Kueue는 ClusterQueue를 VC(virtual cluster)별로 두고 nominalQuota를 정해, 각 VC가
    자기 몫을 보장받되 유휴 용량은 다른 VC가 빌려 쓴다(BestEffortFIFO admission + cohort
    borrowing). 본 구현은 이를 SoA 트레이스에 충실히 특수화한다:

      쿼타: VC v의 nominalQuota = (VC v의 총 GPU-수요 비율)×클러스터 총 GPU.
            = clusterGPU · Σ_{j∈v} gpu_j / Σ_all gpu_j.  전 잡 vc·gpu로 한 번 계산해 캐시.
      공정 공유 순서: 매 패스에서 (a) 실행 중 잡의 VC별 GPU 사용량 집계,
            (b) usage/quota(쿼타 대비 사용률)가 낮은 under-served VC의 잡 우선,
            (c) 같은 VC 내에선 도착순. 쿼타 초과 VC 잡도 유휴 용량 있으면 배치(borrowing)
                — blocking=False라 후순위로 backfill 허용.
      VC 정보가 전부 'default'면 단일 VC → usage/quota가 모두 동률이라 도착순으로 graceful
      degrade(기존 BestEffortFIFO와 동일).

    주의: 쿼타 공정 공유는 다중 VC가 용량을 경합할 때 발현된다. 단일/동종이라도 VC가 여럿이면
    효과가 나타난다(테넌트별 보장). VC가 1개뿐인 트레이스에선 LAS/FIFO와 사실상 동치다."""
    name = "kueue"

    def __init__(self):
        self._quota = None          # {vc: nominalQuota(GPU)} 캐시

    def _ensure_quota(self, sim):
        if self._quota is not None:
            return
        # 전 잡 VC별 총 GPU-수요 → 비례 배분. SoA(_arr_vc/_arr_gpu)로 일괄 합산.
        vcs = sim._arr_vc
        gpus = sim._arr_gpu.astype(float)
        demand = {}
        for v, g in zip(vcs, gpus):
            demand[v] = demand.get(v, 0.0) + g
        total_demand = sum(demand.values()) or 1.0
        cap = float(sim.total_gpu)
        # 각 VC 쿼타 = 수요 비율 × 클러스터 용량(최소 1로 floor → 0-나눗셈 방지).
        self._quota = {v: max(1.0, cap * d / total_demand) for v, d in demand.items()}

    def order(self, cand_idx, age, ar, sim):
        if cand_idx.size == 0:
            return cand_idx
        self._ensure_quota(sim)
        # (a) 실행 중 잡의 VC별 GPU 사용량 집계.
        usage = {}
        for j in sim.running.values():
            usage[j.vc] = usage.get(j.vc, 0.0) + j.gpu_count
        # (b) 후보별 usage/quota(쿼타 대비 사용률) 키. under-served(낮은 값) 우선.
        cand_vc = sim._arr_vc[cand_idx]
        ratio = np.array([usage.get(v, 0.0) / self._quota.get(v, 1.0) for v in cand_vc], dtype=float)
        # 단일 VC면 ratio 전부 동률 → argsort stable이 도착순(cand_idx) 보존(graceful degrade).
        # (c) 같은 VC 내 도착순: cand_idx가 이미 도착순이라 stable 정렬로 자동 보장.
        return cand_idx[np.argsort(ratio, kind="stable")]


# ── FGD: Fragmentation Gradient Descent (Weng et al., USENIX ATC '23) ─────────
class FGD(Policy):
    """Fragmentation Gradient Descent — 단편화 인지 *배치* 휴리스틱.

    원논문(Weng et al. 2023)은 부분(fractional) GPU 공유 단편화를 대상으로, 노드의
    통계적 단편화를 '대상 워크로드에서 무작위 추출한 태스크가 쓸 수 없는 기대 GPU량'으로
    정의하고, 배치 시 단편화 증가(gradient)가 최소인 노드를 고른다. 본 구현은 동일한
    측도를 통째(whole) GPU gang 스케줄링에 충실히 특수화한 것이다:

      노드 n의 단편화  F_n = free_n · P(task_size > free_n)
        - P(·)는 트레이스의 GPU-수 분포 M (set_dist로 주입). free_n개 빈 GPU가
          '들어올 태스크가 못 쓸 확률'만큼 낭비로 계산 — 원논문 정의의 whole-GPU 형태.
      잡 g 배치의 단편화 기울기  ΔF_n = F(free_n − g) − F(free_n)
      → 실현 가능 노드 중 ΔF_n 최소(단편화를 가장 적게 늘리는) 노드 선택.

    큐 순서는 원논문(Kubernetes 기본 스케줄러 + FGD 스코어링 플러그인)대로 FCFS이며,
    부적합 잡은 보류하되 후속 잡 배치는 막지 않는다(kube-scheduler 동작, blocking=False).
    즉 FGD는 baseline FIFO와 *배치(node_pref)에서만* 다르므로 단편화 인지 배치의 순효과를
    분리 측정한다. (SQUAD의 SFQA는 큐를, PTR는 실행 중 이주를 다루는 직교 축.)"""
    name = "fgd"

    def __init__(self, size_dist=None):
        self.pdist = size_dist or {1: 1.0}

    def set_dist(self, gpu_counts):
        from collections import Counter
        c = Counter(int(g) for g in gpu_counts)
        tot = sum(c.values()) or 1
        self.pdist = {g: c[g] / tot for g in c}

    def _tail(self, x):                       # P(task_size > x)
        return sum(p for g, p in self.pdist.items() if g > x)

    def _frag(self, free):                    # F = free · P(size > free)
        return free * self._tail(free) if free > 0 else 0.0

    def order(self, cand_idx, age, ar, sim):
        return cand_idx                        # FCFS(도착순), 비차단 backfill

    def node_pref(self, job, nodes):
        g = job.gpu_count
        cand = _typed(job, nodes)

        def key(n):
            dF = (self._frag(n.free - g) - self._frag(n.free)) if n.free >= g else 1e18
            return (speed_of(n.gpu_type), dF, n.free)  # 빠른타입 우선(이종 정합), 그 안 ΔF 최소
        return sorted(cand, key=key)


# ── KAI Scheduler (NVIDIA, github.com/NVIDIA/KAI-Scheduler) 배치 포팅 ──────────
def pref_kai_binpack(job, nodes):
    """KAI nodeplacement 기본 전략 = **binpack**(GPU). 충실 포팅.
    원본(pkg/scheduler/plugins/nodeplacement/pack.go) 노드 스코어:
      score = MaxHighDensity·(1 − (free − min)/(max − min))   (fitting 노드의 free 범위로 정규화)
      → free(NonAllocatedResource)가 가장 작은(가장 꽉 찬) 노드가 최고점 = consolidate.
    스코어가 free에 단조 감소이므로 순위 = free 오름차순. KAI는 GPU 타입 speed-tier를 하지 않음
    (순수 binpack) → typed(요청 호환) 필터 후 free로만 정렬. 빈 노드를 큰 gang용으로 남긴다."""
    return sorted(_typed(job, nodes), key=lambda n: n.free)


def pref_kai_spread(job, nodes):
    """KAI nodeplacement spread 전략(spread.go::nodeResourceSpread). 충실 포팅.
    binpack과 반대로 미할당 GPU가 가장 '많은' 노드에 높은 점수 → 부하를 분산(distribute).
    순위 = free 내림차순. KAI는 여기서도 speed-tier 안 함(순수 spread)."""
    return sorted(_typed(job, nodes), key=lambda n: -n.free)


class KAIonly(Policy):
    """KAI-only = KAI 네이티브: FIFO admission(gang 예약/pipelining) + binpack 배치.
    KAI allocate action은 큐 순서로 PopNextJob 후 안 맞는 gang을 pipeline(자원 예약)해
    굶주림을 막음 → head-of-line 예약. 엔진 blocking=True FIFO가 이 head 예약의 충실 근사
    (pipelining의 예약-존중 backfill은 미모델 — KAI-only 처리량을 과소평가할 뿐, 공정성엔 보수적)."""
    name = "kai"; blocking = True
    pref_fn = staticmethod(pref_kai_binpack)

    def order(self, cand_idx, age, ar, sim):
        return cand_idx                                  # FIFO 순서(=KAI 큐 순서, gang 예약)


class SAFA_KAI(SFQAAuto):
    """SAFA + KAI = SAFA(zero-knob) 큐 재정렬 order × KAI binpack 배치.
    order는 SFQAAuto(P*=1/base^pos + α_eff·age_rel·R, 단일승급) 그대로 상속,
    배치만 KAI binpack으로 교체 → SAFA 순서 기여를 동일 KAI 배치 위에서 분리 측정."""
    name = "safa-kai"
    pref_fn = staticmethod(pref_kai_binpack)


# 주의: sfqa-auto-rsv(v3)는 EASY식 예약이 duration(사후값)에 의존해 SQUAD 철학 위반 → 제거.
# SQUAD에서 자리 비우기는 PTR(디프래그)이 담당. SFQA 라인은 duration-free만 유지.
POLICIES = {p.name: p for p in [FIFO, SJF, LAS, Themis, SFQA, SFQAAuto, EASY, Kueue, FGD,
                                KAIonly, SAFA_KAI]}


class SafaWrap(Policy):
    """기존 정책의 순서 위에 SAFA-Auto의 나이×적합도 단일 승급을 얹는 기아-방지 전처리.
    base 순서(예: SJF=duration)를 position priority P로 삼고, 굶주린 '자리 맞는' 잡 1개를
    맨 앞으로 승급. base의 blocking을 상속(SJF/LAS=비차단 → 백필 속도 유지하며 승급)."""
    def __init__(self, base, label):
        self.base = base; self.name = label; self.blocking = base.blocking
    def order(self, cand_idx, age, ar, sim):
        if cand_idx.size == 0:
            return cand_idx
        bo = self.base.order(cand_idx, age, ar, sim)         # base 순서
        Rr = np.array(_r_table_fast(sim.nodes)); Rr[Rr <= 0] = 0.5
        gidx = np.clip(sim._arr_gpu[bo].astype(int) - 1, 0, 7)
        rq = Rr[gidx]; rmin = max(0.1, float(rq.min()))
        age_bo = sim._arrival_count - sim._arr_seq[bo]       # bo에 정렬된 age
        age_rel = age_bo - age_bo.min()
        aref = max(1.0, float(age_rel.mean()))
        S = (float(age_rel.max()) / aref) if cand_idx.size else 0.0
        g = min(1.0, S); alpha_eff = g / (aref * rmin)
        n = bo.size; pos = np.arange(n)
        P = np.where(pos < 60, 1.0 / (2.0 ** np.minimum(pos, 60)), 0.0)   # base 순서 위치=priority
        pstar = P + alpha_eff * age_rel * rq
        imax = int(np.argmax(pstar))
        if imax == 0:
            return bo
        return np.concatenate(([bo[imax]], bo[:imax], bo[imax + 1:]))


def make(name, **kw):
    if name.endswith("+safa"):
        return SafaWrap(make(name[:-5]), name)
    if name in ("sfqa",):
        return SFQA(**kw)
    if name in ("sfqa-auto",):
        return SFQAAuto(**kw)
    if name == "fgd":
        return FGD(**kw)
    if name == "kai":
        return KAIonly()
    if name == "safa-kai":
        return SAFA_KAI(**kw)
    cls = {p.name: p for p in [FIFO, SJF, LAS, Themis, EASY, Kueue]}.get(name)
    if cls is None:
        raise ValueError(f"unknown policy: {name}")
    return cls()
