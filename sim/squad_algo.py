"""SQUAD 알고리즘 (SFQA·PTR) — 검증된 Go 코어(k8s/pkg/squad)와 동일 로직의 Python 포팅.

Go 빌드가 방화벽으로 막혀 컨트롤러를 Python으로 구현하므로, 알고리즘도 Python으로 포팅한다.
로직은 Go 버전과 1:1 동일(같은 C++ 원본: gpu_scheuer/job_emulator.cpp, adjusting_server.cpp)이며
같은 단위테스트로 검증한다. 하드웨어 비종속(GPU 타입·노드 수 일반).
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from enum import IntEnum

ACCEL_PER_SERVER_MAX = 8
DEFAULT_AGE_WEIGHT = 0.13889       # α
DEFAULT_STARVATION_UPPER = 80.0    # β (%)
DEFAULT_DP_EXECUTION_MAX = 100000  # δ
DEFAULT_DEFRAG_CRITERIA = 20       # ω
ANY = "any"


class Slot(IntEnum):
    NONE = 0
    EMPTY = 1
    FIXED = 2
    FLOATING = 3
    ADJUSTED = 4


@dataclass
class Params:
    alpha: float = DEFAULT_AGE_WEIGHT
    beta: float = DEFAULT_STARVATION_UPPER
    dp_max: int = DEFAULT_DP_EXECUTION_MAX
    omega: int = DEFAULT_DEFRAG_CRITERIA
    prevent_starv: bool = True
    use_preemption: bool = True


@dataclass
class Server:
    name: str
    gpu_type: str
    total: int
    slots: list = field(default_factory=lambda: [Slot.NONE] * ACCEL_PER_SERVER_MAX)
    job_ids: list = field(default_factory=lambda: [""] * ACCEL_PER_SERVER_MAX)

    def available(self) -> int:
        return sum(1 for i in range(self.total) if self.slots[i] == Slot.EMPTY)


@dataclass
class PendingJob:
    id: str
    gpu_count: int
    gpu_type: str
    age: int = 0
    pstar: float = 0.0


@dataclass
class RunningJob:
    id: str
    gpu_count: int
    gpu_type: str
    server_index: int
    target_index: int = -1
    preemptible: bool = True


# ── SFQA (C++ job_emulator.cpp::adjust_wait_queue 410-478) ──────────────────
def compute_r_table(servers, gpu_type):
    """Resource suitability index R (저자 정의 — 서버마다 비교, 최댓값):
    서버 free ≥ req 면 1, 1개 부족할 때마다 0.1 감소(부족분 k → 1−0.1k). R[req-1]=max over servers."""
    R = [0.0] * ACCEL_PER_SERVER_MAX
    for s in servers:
        if gpu_type != ANY and s.gpu_type != gpu_type:
            continue
        free = s.available()
        for req in range(1, ACCEL_PER_SERVER_MAX + 1):
            short = req - free
            suit = 1.0 if short <= 0 else 1.0 - 0.1 * short
            if suit > R[req - 1]:
                R[req - 1] = suit
    return [x if x > 0 else 0.0 for x in R]


def pstar(pos, age, gpu_count, alpha, R):
    priority = 1.0 / (2 ** pos)
    k = max(1, min(ACCEL_PER_SERVER_MAX, gpu_count))
    return priority + age * alpha * R[k - 1]


def reorder_queue(jobs, servers, gpu_type, params: Params, allocation_rate_pct):
    """Algorithm 1: P* 최댓값 잡 1개만 맨 앞으로(단일 승급, line 20-25). 전체 정렬 아님.
    트리거 β > AR(미트리거=AR≥β면 원순서)."""
    out = [replace(j) for j in jobs]
    active = params.prevent_starv and allocation_rate_pct < params.beta
    if not active or len(out) < 2:
        return out
    R = compute_r_table(servers, gpu_type)
    pvals = [pstar(i, j.age, j.gpu_count, params.alpha, R) for i, j in enumerate(out)]
    imax = max(range(len(pvals)), key=lambda k: pvals[k])   # P* 최댓값 1개
    if imax == 0:
        return out
    return [out[imax]] + out[:imax] + out[imax + 1:]         # 그 잡만 front, 나머지 shift


# ── PTR (C++ adjusting_server.cpp DP 146-191) ───────────────────────────────
class Defrag:
    def __init__(self, servers, jobs, dp_max=DEFAULT_DP_EXECUTION_MAX):
        self.servers = servers
        self.jobs = jobs
        self.dp_max = dp_max
        self.exec_count = 0
        self.memo = {}
        self.best = []
        self.targets = [i for i, s in enumerate(servers) if 0 < s.available() < s.total]
        self.targets.sort(key=lambda i: servers[i].available())

    def run(self):
        before = self._calc_full_empty()
        mx = [0]
        after = self._dp(0, mx)
        if before < after:
            return True, self.best, before, after
        return False, [], before, after

    def _dp(self, rc, mx):
        if self.exec_count > self.dp_max:
            return mx[0]
        self.exec_count += 1
        key = self._state_key(rc)
        if key in self.memo:
            return self.memo[key]
        if rc == 0:
            self.memo = {key: mx[0]}
            mx[0] = self._calc_full_empty()
        if rc == len(self.jobs):
            return mx[0]
        job = self.jobs[rc]
        for ti in self.targets:
            if job.server_index == ti:
                continue
            srv = self.servers[ti]
            if srv.gpu_type != job.gpu_type:  # 이종 가드: 동일 타입만 이주
                continue
            if srv.available() < job.gpu_count:
                continue
            if self._rearrange(ti, job, False):
                full = self._calc_full_empty()
                if full > mx[0]:
                    mx[0] = full
                    self.memo[key] = full
                    self._snapshot()
                mx[0] = self._dp(rc + 1, mx)
                self._rearrange(ti, job, True)
        mx[0] = self._dp(rc + 1, mx)
        return mx[0]

    def _rearrange(self, server_idx, job, reverse):
        if not reverse:
            srv = self.servers[server_idx]
            if job.gpu_count > srv.total:
                return False
            if self._empty_slots(server_idx) < job.gpu_count:
                return False
            self._switch(server_idx, job.gpu_count, Slot.EMPTY, Slot.ADJUSTED)
            self._switch(job.server_index, job.gpu_count, Slot.FLOATING, Slot.EMPTY)
            job.target_index = server_idx
            return True
        self._switch(server_idx, job.gpu_count, Slot.ADJUSTED, Slot.EMPTY)
        self._switch(job.server_index, job.gpu_count, Slot.EMPTY, Slot.FLOATING)
        job.target_index = -1
        return True

    def _switch(self, server_idx, count, prev, after):
        srv = self.servers[server_idx]
        for i in range(ACCEL_PER_SERVER_MAX):
            if count == 0:
                break
            if srv.slots[i] == Slot.NONE:
                break
            if srv.slots[i] == prev:
                srv.slots[i] = after
                count -= 1

    def _calc_full_empty(self):
        return sum(1 for i, s in enumerate(self.servers) if self._empty_slots(i) == s.total)

    def _empty_slots(self, server_idx):
        s = self.servers[server_idx]
        return sum(1 for i in range(ACCEL_PER_SERVER_MAX) if s.slots[i] == Slot.EMPTY)

    def _state_key(self, rc):
        return f"{rc}-" + ";".join(f"{ti}:{self._empty_slots(ti)}" for ti in self.targets)

    def _snapshot(self):
        self.best = [replace(j) for j in self.jobs]
