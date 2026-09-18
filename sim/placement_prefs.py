"""배치(node placement) pref 함수 — C++ 코어 4종 배치 스케줄러를 pref_fn 인터페이스로 포팅.

SAFA(=SFQA)는 큐 **재정렬** 전처리기로, 그 아래 코어 GPU **배치** 스케줄러와 무관하게
동작한다고 주장한다. 배치는 정책 인스턴스의 `pref_fn`(노드 정렬 함수)로 주입되며, 엔진의
`_alloc`이 그 순서대로 free GPU를 모아 멀티노드 gang을 구성한다(policies.py 21~44행 참조).

본 모듈은 policies.py에 이미 있는 pref_mostallocated/pref_compact에 더해 C++ 원본의
round_robin(scheduler_round_robin.cpp)·mcts(scheduler_mcts.cpp)를 충실히 포팅한다.
모두 1차 키로 speed_of(빠른 타입 우선, 이종 정합)를 유지해 단일 타입에선 기존과 동일.

포팅 충실도:
  round_robin: C++는 current_server_index를 라운드로빈 회전시켜 '다음 적합 서버'를 고른다.
    pref_fn은 상태없는 순수 정렬이라 인덱스 회전을 직접 재현할 수 없으나, 라운드로빈의
    **취지(잡을 고르게 분산 = 빈자리 많은 노드 우선)**를 free 내림차순으로 구현한다.
    이는 most-allocated(free 적은 노드 우선=단편화↓)의 정반대로, 분산 정책 축을 형성한다.
    추가로 호출마다 시작 오프셋을 회전시켜(상태 보존) 동일 free 노드 간에도 순환 분산을 흉내낸다.
  mcts: C++ scheduler_mcts.cpp의 본질 = '후보 서버마다, 남은 대기 잡을 무작위 서버에 배정하는
    롤아웃을 simulation_count회 돌려 달성 할당률(max allocation ratio)을 보상으로 서버 평가'.
    이를 pref_fn에 맞게 포팅: 후보 노드(free>=gpu_count)마다 그 노드에 잡을 가정 배치한 뒤
    남은 대기 잡(현재 큐, 깊이 캡)을 무작위 노드에 배정하는 롤아웃을 N회 돌려 최대 달성
    할당률을 점수로 매기고, 노드를 점수 내림차순 정렬. UCB 트리는 생략하되 '롤아웃 기반
    할당률 추정으로 서버를 고른다'는 MCTS 본질을 보존. 반복·롤아웃·큐깊이 모두 캡(아래 상수).
"""
from __future__ import annotations

import random

from engine import speed_of


def _typed(job, nodes):
    """요청 타입과 호환되는 노드만(any는 모두)."""
    return [n for n in nodes if job.gpu_type in ("any", n.gpu_type) or n.gpu_type == "any"]


# ── round_robin: 빈자리 많은 노드 우선(분산) + 호출 오프셋 회전(라운드로빈 흉내) ──────
class RoundRobinPref:
    """상태 보존형 round_robin pref. free 많은 노드 우선(분산), 동률은 회전 오프셋으로 순환.

    C++ scheduler_round_robin은 current_server_index를 매 배치마다 ++해 다음 적합 서버를 쓴다.
    pref_fn은 순수 함수가 기대되지만, 라운드로빈 본질(순환 분산)을 살리려 인스턴스가
    호출 카운터를 들고 동률 노드 사이에서 시작점을 회전시킨다. 1차 키는 빠른 타입 우선."""

    def __init__(self):
        self._tick = 0

    def __call__(self, job, nodes):
        cand = _typed(job, nodes)
        self._tick += 1
        off = self._tick % max(1, len(cand))
        # free 많은 노드 우선(분산); 같은 (speed, -free)면 회전 오프셋으로 시작점 순환
        rotated = cand[off:] + cand[:off]
        return sorted(rotated, key=lambda n: (speed_of(n.gpu_type), -n.free))


def pref_round_robin(job, nodes):
    """무상태 round_robin: free 많은 노드 우선(분산). most-allocated의 정반대."""
    return sorted(_typed(job, nodes), key=lambda n: (speed_of(n.gpu_type), -n.free))


# ── mcts: 롤아웃 기반 할당률 추정으로 서버(노드) 점수화 → 내림차순 정렬 ─────────────
# 비용 캡(125k 잡에서도 끝나게): C++ simulation_count=100, 반복=20*(max_job+1).
# pref_fn은 잡마다 호출되므로 보수적으로 축소.
MCTS_ROLLOUTS = 8        # 후보 노드당 롤아웃 횟수(C++ simulation_count=100 → 8로 캡)
MCTS_QUEUE_DEPTH = 16    # 롤아웃에 포함할 남은 대기 잡 수 상한(C++는 전 큐, 여기선 캡)
MCTS_MAX_CAND = 12       # 점수화할 후보 노드 수 상한(나머지는 most-allocated 순으로 뒤에)
_mcts_rng = random.Random(20240611)


def _rollout_alloc(node_free, rest_gpu, total_gpu, rng):
    """남은 잡(rest_gpu 리스트)을 무작위 노드에 배정하는 1회 롤아웃의 달성 할당률.
    node_free: 현재(가정배치 후) 노드별 free 리스트(복사본). C++ simulate의 무작위 배정 루프."""
    free = list(node_free)
    nN = len(free)
    used0 = total_gpu - sum(free)
    used = used0
    for g in rest_gpu:
        # C++: 무작위 서버에 배정, 안 들어가면 repeat_count<(...) 재시도 후 포기
        placed = False
        for _ in range(min(nN, 6)):              # 재시도 캡(C++ (cnt-depth+1)*3 → 소수로 축소)
            s = rng.randrange(nN)
            if free[s] >= g:
                free[s] -= g; used += g; placed = True; break
        if not placed:
            break                                # 더 못 넣음 → 롤아웃 종료(C++ break)
    return used / total_gpu if total_gpu else 0.0


class MCTSPref:
    """롤아웃 기반 mcts pref. 인스턴스가 sim 참조(현재 대기 큐 접근)를 주입받는다.

    placement_axis 하니스가 매 run마다 self.sim과 rollout 캡을 설정한다.
    sim이 없으면(=대기 큐 모르면) most-allocated로 graceful degrade(여전히 유효한 배치)."""

    def __init__(self, rollouts=MCTS_ROLLOUTS, depth=MCTS_QUEUE_DEPTH, max_cand=MCTS_MAX_CAND,
                 seed=20240611):
        self.rollouts = rollouts
        self.depth = depth
        self.max_cand = max_cand
        self.rng = random.Random(seed)
        self.sim = None              # 하니스가 주입(현재 대기 잡 gpu_count 추출용)
        self.calls = 0               # 호출수(비용 측정)
        self.scored = 0              # 실제 롤아웃 수행 횟수(비용 측정)

    def _rest_gpu(self, job):
        """현재 대기(도착·미배치) 잡들의 gpu_count(깊이 캡). 자기 자신·이미배치 제외."""
        sim = self.sim
        if sim is None:
            return []
        import numpy as np
        cand_idx = np.nonzero(sim._arrived & ~sim._placed_arr)[0]
        out = []
        for i in cand_idx[: self.depth]:
            jid = sim.idx2job[int(i)].id
            if jid == job.id:
                continue
            out.append(int(sim._arr_gpu[int(i)]))
            if len(out) >= self.depth:
                break
        return out

    def __call__(self, job, nodes):
        self.calls += 1
        cand = _typed(job, nodes)
        # most-allocated 기준 정렬(빠른타입·free적은순)을 기본 골격으로
        base = sorted(cand, key=lambda n: (speed_of(n.gpu_type), n.free))
        feasible = [n for n in base if n.free >= job.gpu_count]
        if len(feasible) <= 1:
            return base                          # 후보 0/1 → 트리탐색 불필요(C++ can_be_scheduled 분기)
        rest = self._rest_gpu(job)
        total = sum(n.total for n in nodes)
        free_now = [n.free for n in nodes]
        # 후보 노드 상한: 너무 많으면 most-allocated 상위 max_cand만 점수화(나머지 뒤에 붙임)
        scoring = feasible[: self.max_cand]
        node_index = {id(n): k for k, n in enumerate(nodes)}
        scores = {}
        for n in scoring:
            k = node_index[id(n)]
            best = 0.0
            for _ in range(self.rollouts):
                self.scored += 1
                fcopy = list(free_now)
                fcopy[k] -= job.gpu_count         # 이 노드에 잡 가정 배치
                a = _rollout_alloc(fcopy, rest, total, self.rng)
                if a > best:
                    best = a                      # C++: max allocation ratio
            scores[id(n)] = best
        # 점수 내림차순(동률은 most-allocated 순 보존: base 안정정렬), 비점수 후보는 뒤에
        scored_sorted = sorted(scoring, key=lambda n: -scores[id(n)])
        scoring_ids = {id(n) for n in scoring}
        rest_nodes = [n for n in base if id(n) not in scoring_ids]
        return scored_sorted + rest_nodes
