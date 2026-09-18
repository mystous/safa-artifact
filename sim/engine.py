"""이산사건 GPU 스케줄링 시뮬레이터 — 오버헤드 보정 하이브리드.

C++ 코어(gpu_scheuer/job_emulator.cpp step_foward 루프)를 이산사건으로 충실 포팅하되,
시간 진행을 분-단위 폴링이 아니라 이벤트 큐로 바꿔 전체 트레이스(111k)·멀티노드·이종을
wall-clock 없이 평가한다. 정책 로직은 policies.py 한 곳에서 정의(실측 컨트롤러와 동치).

보정 파라미터(실측): results/overheads/params.md
  sched_lat 0.5s, startup 1.5(단독)/3.5(경합)s, teardown 2.5s, PTR D(크기 의존).

매 스케줄 틱의 처리 순서(C++ step_foward 순서 보존):
  computing_forward(완료 처리) → update_wait_queue(도착) → adjust(정책 큐 재정렬)
  → defrag(PTR) → schedule(배치). 단 이벤트 구동이라 '틱'은 상태 변화 시점에만 발생.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Job:
    id: str
    arrival: float          # 초
    duration: float         # 초 (명목 실행시간)
    gpu_count: int
    gpu_type: str = "any"
    preemptible: bool = False
    vc: str = "default"     # 테넌트/virtual cluster (Kueue per-VC 쿼타 공정 공유용)
    # 동역학 상태
    place_time: float = -1.0
    finish_time: float = -1.0
    attained: float = 0.0   # LAS: 누적 GPU-시간
    age: int = 0
    arrival_seq: int = 0    # 도착 시점의 전역 도착 카운트(age = 현재카운트 − 이 값)
    downtime: float = 0.0   # PTR 이주로 누적된 다운타임
    alloc: list = field(default_factory=list)   # [(node, count)] 멀티노드 gang

    @property
    def queue_delay(self):
        return self.place_time - self.arrival if self.place_time >= 0 else None

    @property
    def jct(self):
        return self.finish_time - self.arrival if self.finish_time >= 0 else None


@dataclass
class Node:
    name: str
    gpu_type: str
    total: int
    free: int = 0

    def __post_init__(self):
        self.free = self.total


@dataclass
class Overheads:
    sched_lat: float = 0.5
    startup_solo: float = 1.5
    startup_busy: float = 3.5
    teardown: float = 2.5
    busy_threshold: int = 2   # 동시 배치 N개 이상이면 busy startup
    # PTR 다운타임 모델: D = ckpt_gib_per_gpu*(1/save_bw+1/load_bw) + teardown + sched_lat
    save_bw: float = 0.85     # GiB/s
    load_bw: float = 1.75
    bytes_per_param: int = 10
    enabled: bool = True

    def startup(self, batch_n):
        if not self.enabled:
            return 0.0
        return self.startup_busy if batch_n >= self.busy_threshold else self.startup_solo

    def place_cost(self, batch_n):
        if not self.enabled:
            return 0.0
        return self.sched_lat + self.startup(batch_n)

    def teardown_cost(self):
        return self.teardown if self.enabled else 0.0

    def ptr_downtime(self, job):
        """이주 잡의 다운타임 D(초). params.md의 샤딩 모델."""
        gpu = max(1, job.gpu_count)
        # job.duration이 params 수를 모르므로, 호출자가 params_B를 줄 수 없을 때의 근사:
        # gpu_count로 모델 크기 프록시(1GPU=7B,4=32B,8=70B) — sweep에서 override 가능.
        params_b = {1: 7.0, 2: 13.0, 4: 32.0, 8: 70.0}.get(gpu, 7.0 * gpu)
        ckpt_gib_per_gpu = (params_b * 1e9 / gpu) * self.bytes_per_param / 1024**3
        return ckpt_gib_per_gpu * (1 / self.save_bw + 1 / self.load_bw) + self.teardown + self.sched_lat


# GPU 타입별 상대 실행시간 계수(b200=1.0 기준). 같은 잡이라도 느린 타입에 배치되면
# duration이 이 배수만큼 늘어난다(이종 flavor-aware 모델). sia TYPE_PERF의 b_grad 비율과 정합
# (b200 0.010 / h100 0.014 / a100 0.020 / v100 0.040 → 처리량 역수 ≈ 1/1.4/2.0/4.0).
SPEED = {"b200": 1.0, "h200": 0.9, "h100": 1.4, "a100": 2.0, "a30": 2.8,
         "v100": 4.0, "l40": 2.2, "l4": 3.5, "any": 1.0}


def speed_of(gpu_type):
    return SPEED.get(gpu_type, 2.0)


# 이벤트 타입
ARRIVE, FINISH, TICK = 0, 1, 2


class Simulator:
    """이산사건 엔진. policy는 schedule()에서 호출되는 객체(policies.Policy)."""

    def __init__(self, jobs, nodes, policy, overheads=None, ptr=None, tick_interval=None,
                 progress=None, progress_every=2000, resched_min_gap=0.0):
        self.progress = progress           # fn(done, total, wait_len) 주기 호출
        self.progress_every = progress_every
        # 재정렬 throttle: 직전 재스케줄 후 이 시뮬-초 안에는 capacity 변화 없으면 재정렬 생략.
        # 고부하 깊은-큐에서 수만 사건을 한 번으로 묶어 O(events×queue) 폭주 방지.
        # (단 free 자리가 생겼는데 대기가 있으면 항상 재스케줄 — 배치 기회는 놓치지 않음)
        self.resched_min_gap = resched_min_gap
        self._last_sched = -1e18
        self._arrival_count = 0     # 전역 도착 카운트(age = 신규 도착마다 +1)
        self.jobs = {j.id: j for j in jobs}
        self.nodes = nodes
        self.policy = policy
        self.ovh = overheads or Overheads()
        self.ptr = ptr            # None 또는 PTRConfig
        self.now = 0.0
        self.events = []          # heap of (time, seq, type, payload)
        self._seq = 0
        self.running = {}         # job_id -> Job
        self.finished = []        # 완료 Job
        self.alloc_samples = []   # (time, used_gpu, total_gpu)
        self.total_gpu = sum(n.total for n in nodes)
        self.tick_interval = tick_interval  # None이면 이벤트 구동만, 값 있으면 주기 틱도
        # SoA(Structure-of-Arrays): 핫패스(대기큐 처리)를 numpy로 일괄 계산해 CAP 없이도 빠르게.
        # 잡 인덱스 = 도착순 순위. 불변 속성은 배열로, 동역학은 mask/배열로 관리.
        self.idx2job = sorted(self.jobs.values(), key=lambda x: x.arrival)
        for i, j in enumerate(self.idx2job):
            j._idx = i
        n = len(self.idx2job)
        self._arr_arrival = np.array([j.arrival for j in self.idx2job], dtype=float)
        self._arr_dur = np.array([j.duration for j in self.idx2job], dtype=float)
        self._arr_gpu = np.array([j.gpu_count for j in self.idx2job], dtype=np.int32)
        self._arr_vc = np.array([j.vc for j in self.idx2job], dtype=object)   # 잡별 VC(Kueue 쿼타용)
        self._arr_seq = np.zeros(n, dtype=float)        # 도착 시점의 전역 도착 카운트
        self._arrived = np.zeros(n, dtype=bool)         # 도착(큐 진입)했는가
        self._placed_arr = np.zeros(n, dtype=bool)      # 배치(running/완료)됐는가
        self._arr_attained = np.zeros(n, dtype=float)   # LAS: 누적 GPU-시간

    def _push(self, t, typ, payload=None):
        heapq.heappush(self.events, (t, self._seq, typ, payload))
        self._seq += 1

    def run(self):
        for j in sorted(self.jobs.values(), key=lambda x: x.arrival):
            self._push(j.arrival, ARRIVE, j.id)
        if self.tick_interval:
            self._push(0.0, TICK, None)
        last_sched_dirty = True

        while self.events:
            t, _, typ, payload = heapq.heappop(self.events)
            self.now = t
            if typ == ARRIVE:
                self._arrival_count += 1                       # 신규 요청마다 +1
                j = self.jobs[payload]
                j.arrival_seq = self._arrival_count
                self._arrived[j._idx] = True
                self._arr_seq[j._idx] = self._arrival_count
                last_sched_dirty = True
            elif typ == FINISH:
                self._on_finish(payload)
                last_sched_dirty = True
            elif typ == TICK:
                if self.tick_interval and self.events:
                    self._push(t + self.tick_interval, TICK, None)
                last_sched_dirty = True

            # 같은 시각의 이벤트를 모두 소진한 뒤 한 번만 스케줄
            if self.events and self.events[0][0] == t:
                continue
            if last_sched_dirty:
                self._adjust_and_schedule()
                last_sched_dirty = False
        return self._results()

    def _on_finish(self, job_id):
        job = self.running.pop(job_id)
        for node, cnt in job.alloc:
            node.free += cnt
        job.alloc = []
        self.finished.append(job)
        # 완료 시점도 allocation 변화점 → 드레인(대기 큐 소진 후 잔여 잡 종료) 구간 추세 포착.
        # (_adjust_and_schedule는 만석·빈큐일 때 조기 반환하므로 여기서 보강 샘플)
        self.alloc_samples.append((self.now, self._used(), self.total_gpu))
        if self.progress and len(self.finished) % self.progress_every == 0:
            waiting = int(np.count_nonzero(self._arrived & ~self._placed_arr))
            self.progress(len(self.finished), len(self.jobs), waiting)

    def _alloc(self, job):
        """갱 공간 불가분: 작업의 모든 GPU를 '한 노드'에 통째로 배치(노드 경계 단위, 쪼개기 금지).
        node_pref 순서로 free>=gpu_count인 첫 노드 선택. 없으면 None(단편화로 대기).
        노드 용량 초과 갱(멀티노드)은 '완전히 빈 노드'들로만 채운다(부분 노드 혼합 금지)."""
        cand = self.policy.node_pref(job, self.nodes)
        g = job.gpu_count
        for n in cand:                       # 단일 노드 co-location 우선
            if n.free >= g:
                return [(n, g)]
        if g > max((n.total for n in self.nodes), default=0):   # 멀티노드 갱: 빈 노드만
            need, plan = g, []
            for n in cand:
                if need <= 0:
                    break
                if n.free == n.total:        # 완전히 빈 노드만(불가분 유지)
                    take = min(n.total, need); plan.append((n, take)); need -= take
            return plan if need == 0 else None
        return None

    def _used(self):
        return self.total_gpu - sum(n.free for n in self.nodes)

    def _adjust_and_schedule(self):
        # 자리가 없으면(만석) 배치 불가 → 통째로 생략.
        free_total = sum(n.free for n in self.nodes)
        if free_total <= 0:
            return
        # 후보 = 도착했고 미배치인 잡(인덱스). 인덱스가 도착순 순위라 cand_idx는 자동 도착순.
        # np.nonzero로 전체 큐를 numpy 일괄 추출(CAP 없이 정확, 파이썬 루프 없이 빠름).
        cand_idx = np.nonzero(self._arrived & ~self._placed_arr)[0]
        if cand_idx.size == 0:
            return
        age = self._arrival_count - self._arr_seq[cand_idx]      # 절대 누적 age(벡터)
        if self.policy.name == "las":                            # 실행 중 잡 누적서비스 갱신
            for j in self.running.values():
                self._arr_attained[j._idx] = (self.now - j.place_time) * j.gpu_count

        if self.ptr and self.ptr.enabled:
            self.ptr.maybe_defrag(self)

        ar = self._used() / self.total_gpu * 100 if self.total_gpu else 0
        # 정책은 cand_idx(도착순 미배치)+age 벡터를 받아 배치 우선순위 인덱스 순서를 반환.
        ordered_idx = self.policy.order(cand_idx, age, ar, self)

        # 배치: 멀티노드 gang 계획 후 잠정 점유(같은 틱 내 후속 fit 정확히)
        to_place = []
        free_left = free_total
        for ii in ordered_idx:
            i = int(ii)
            gpu = int(self._arr_gpu[i])
            if free_left <= 0:             # 자리 소진 → 즉시 중단
                break
            if gpu > free_left:            # 이 잡은 못 들어감(비싼 _alloc 호출 회피)
                if self.policy.blocking:
                    break
                continue
            job = self.idx2job[i]
            plan = self._alloc(job)
            if plan is None:
                if self.policy.blocking:   # FIFO/예약류: 선두 막히면 중단
                    break
                continue
            for n, cnt in plan:
                n.free -= cnt
            free_left -= gpu
            job.alloc = plan
            self._placed_arr[i] = True
            to_place.append(job)

        batch_n = len(to_place)
        for job in to_place:
            cost = self.ovh.place_cost(batch_n)
            job.place_time = self.now + cost
            # 배치된 GPU 타입에 따라 실행시간 스케일(gang이 타입 섞이면 가장 느린 타입 기준).
            dur_eff = job.duration * max(speed_of(n.gpu_type) for n, _ in job.alloc)
            job.finish_time = job.place_time + dur_eff + job.downtime + self.ovh.teardown_cost()
            self.running[job.id] = job
            self._push(job.finish_time, FINISH, job.id)

        self.alloc_samples.append((self.now, self._used(), self.total_gpu))

    def per_job(self):
        """잡별 (queue, service, gpu) — fairness 분석(Gini/Jain/Themis/W&H-B)용."""
        return [(j.queue_delay, j.duration, j.gpu_count)
                for j in self.finished if j.queue_delay is not None]

    def _results(self):
        qs = sorted(j.queue_delay for j in self.finished if j.queue_delay is not None)
        js = sorted(j.jct for j in self.finished if j.jct is not None)
        bs = sorted((j.jct / max(j.jct - j.queue_delay, 10.0))
                    for j in self.finished if j.jct is not None)
        makespan = max((j.finish_time for j in self.finished), default=0) - \
            min((j.arrival for j in self.jobs.values()), default=0)

        def pct(a, p):
            return a[min(len(a) - 1, int(len(a) * p))] if a else 0.0
        amax = max((u / t * 100 for _, u, t in self.alloc_samples), default=0)
        aavg = (sum(u / t * 100 for _, u, t in self.alloc_samples) /
                len(self.alloc_samples)) if self.alloc_samples else 0
        return {
            "n": len(self.finished),
            "q_p50": pct(qs, .5), "q_p90": pct(qs, .9), "q_p99": pct(qs, .99),
            "q_max": qs[-1] if qs else 0,
            "j_p50": pct(js, .5), "j_p90": pct(js, .9), "j_max": js[-1] if js else 0,
            "bsld_p50": pct(bs, .5), "bsld_p90": pct(bs, .9), "bsld_max": bs[-1] if bs else 0,
            "alloc_max": amax, "alloc_avg": aavg, "makespan": makespan,
            "alloc_series": self.alloc_samples,
            "ptr_migrations": self.ptr.migrations if self.ptr else 0,
        }
