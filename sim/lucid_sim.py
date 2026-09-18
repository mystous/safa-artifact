"""Lucid (ASPLOS'23) 충실 구현 — 전용 이산사건 시뮬레이터.

논문 핵심(general-purpose 조사 + 논문 Alg.1/2):
  1. 큐 정렬키 = gpu_count × predicted_duration 오름차순  (SJF 아님 — GPU 가중)
  2. Sharing Score SS∈{0,1,2}(Tiny/Medium/Jumbo), GPU util 기반 분류
  3. Indolent Packing: G_SS=2 capacity. 두 잡 collocate 조건:
       - SS_a + SS_b ≤ G_SS
       - **동일 gpu_count** (rule 2, straggler 방지)
       - 최대 2잡/GPU (rule 3)
       - 분산(멀티노드) 잡은 packing 안 함 (rule 5)
       - 메모리 OOM 방지 (rule 1)
  4. 비선점. collocation 시 두 잡 모두 진행속도 저하(SS쌍별 0.85~1.0).
  5. 동적: 저부하 시 G_SS 1로(apathetic) — 본 구현은 부하 임계로 토글.

진행속도 모델(논문 2.3절 RTX3090 특성, 조사 표):
  (0,0)=1.0  (0,1)=0.95  (1,1)=0.90  (0,2)=0.85  (1,2)/(2,2)=불허(SS합>2)
collocation은 같은 GPU 집합을 공유 → 자원 점유는 1잡분(packing 이득), 둘 다 느려짐.

predicted_duration: 트레이스 재생이라 oracle(실제 duration). 옵션 노이즈로 GA²M 오차 모사 가능.
출력: 잡별 (queue_sec, service_sec=실제 점유시간, gpu_count) — fairness 분석 호환.
"""
from __future__ import annotations
import heapq
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dataclasses import dataclass, field
from engine import speed_of  # noqa: E402  (이종 flavor-aware: 배치된 타입에 따라 진행속도)

# SS 쌍 → 각 잡 진행속도 (SS합 ≤ G_SS 인 쌍만 등장)
SS_SPEED = {(0, 0): 1.00, (0, 1): 0.95, (1, 0): 0.95,
            (1, 1): 0.90, (0, 2): 0.85, (2, 0): 0.85}


@dataclass
class LJob:
    id: str
    arrival: float
    duration: float            # 실제 연산시간(명목)
    gpu_count: int
    gpu_type: str = "any"
    util: float = 0.5          # GPU 활용률(0..1) — SS 분류용. 트레이스에 없으면 추정
    # 동역학
    ss: int = 0
    place_time: float = -1.0
    finish_time: float = -1.0
    remaining: float = 0.0     # 남은 연산량(초, 명목 — b200 기준)
    partner: object = None     # collocate 상대 LJob
    alloc: list = field(default_factory=list)   # [(node, count)]
    last_update: float = 0.0
    speed: float = 1.0         # 배치된 GPU 타입 실행시간 계수(느릴수록 큼)


def sharing_score(util):
    if util > 0.85:
        return 2      # Jumbo
    if util > 0.40:
        return 1      # Medium
    return 0          # Tiny


ARRIVE, FINISH = 0, 1


class LucidSim:
    def __init__(self, jobs, nodes, overheads, gss=2, low_load_gss1=0.3, predict_noise=0.0):
        self.jobs = {j.id: j for j in jobs}
        self.nodes = nodes
        self.ovh = overheads
        self.gss = gss
        self.low_load_gss1 = low_load_gss1
        self.now = 0.0
        self.events = []
        self._seq = 0
        self.wait = []
        self.running = {}        # id -> LJob (solo 또는 collocated)
        self._solo = {}          # gpu_count -> set(solo 단일노드 running job id) — 파트너 탐색 색인
        self._placed = set()     # 지연삭제: 배치됐으나 wait에 남은 잡 id
        self.finished = []
        self.total_gpu = sum(n.total for n in nodes)
        self.alloc_samples = []
        for j in jobs:
            j.ss = sharing_score(j.util)
            j.remaining = j.duration

    def _push(self, t, typ, payload):
        heapq.heappush(self.events, (t, self._seq, typ, payload)); self._seq += 1

    def _used(self):
        return self.total_gpu - sum(n.free for n in self.nodes)

    def _cur_gss(self):
        # 동적: 저부하면 packing 약화(G_SS=1). 부하=할당률.
        load = self._used() / self.total_gpu if self.total_gpu else 0
        return 1 if load < self.low_load_gss1 else self.gss

    def run(self):
        for j in sorted(self.jobs.values(), key=lambda x: x.arrival):
            self._push(j.arrival, ARRIVE, j.id)
        while self.events:
            t, _, typ, pid = heapq.heappop(self.events)
            self.now = t
            if typ == ARRIVE:
                self.wait.append(self.jobs[pid])
                self._wait_dirty = True            # 신규 도착 → 다음 스케줄 때 재정렬
            elif typ == FINISH:
                self._on_finish(pid)
            if self.events and self.events[0][0] == t:
                continue
            self._schedule()
            self.alloc_samples.append((self.now, self._used(), self.total_gpu))
        return self._results()

    def _advance(self, job):
        """job의 remaining을 경과시간×진행속도만큼 감소(collocation 반영)."""
        dt = self.now - job.last_update
        if dt <= 0:
            return
        if job.partner is not None:
            rate = SS_SPEED.get((job.ss, job.partner.ss), 0.85)
        else:
            rate = 1.0
        job.remaining -= dt * rate / job.speed       # 느린 타입(speed↑)일수록 진행 느림
        job.last_update = self.now

    def _eta(self, job):
        rate = 1.0 if job.partner is None else SS_SPEED.get((job.ss, job.partner.ss), 0.85)
        return self.now + max(0.0, job.remaining) * job.speed / rate + self.ovh.teardown_cost()

    def _reschedule_finish(self, job):
        job.finish_time = self._eta(job)
        self._push(job.finish_time, FINISH, job.id)

    def _on_finish(self, jid):
        job = self.running.get(jid)
        if job is None:
            return
        self._advance(job)
        if job.remaining > 1e-6:          # collocation 변화로 아직 안 끝남(stale 이벤트)
            return
        job.finish_time = self.now        # 실제 종료 확정 시각(단독 배치 경로 finish_time 미설정 버그 수정)
        self._solo_remove(job)
        p = job.partner
        if p is not None and p.id in self.running:
            # 파트너 아직 실행 중 → GPU 반납하지 않고 소유권 이전(같은 GPU 공유 중)
            self._advance(p)
            p.partner = None
            if not p.alloc and job.alloc:        # job이 소유자였으면 alloc을 p에게 넘김
                p.alloc = job.alloc
            del self.running[jid]
            self.finished.append(job)
            self._solo_add(p)                    # p는 이제 solo → 색인 복귀
            self._reschedule_finish(p)           # 속도 복원
            return
        # solo로 끝남 → 자원 반납
        for node, cnt in job.alloc:
            node.free += cnt
        del self.running[jid]
        self.finished.append(job)

    def _alloc(self, job, nodes):
        """갱 공간 불가분: gpu_count를 '한 노드'에 통째 배치(노드 경계 단위, 쪼개기 금지).
        free 적은 노드부터(best-fit) free>=gpu_count인 첫 노드 선택. 없으면 None(단편화 대기).
        노드 용량 초과 갱(멀티노드)은 완전히 빈 노드들로만 채운다."""
        cand = sorted([n for n in nodes if job.gpu_type in ("any", n.gpu_type) or n.gpu_type == "any"],
                      key=lambda n: n.free)
        g = job.gpu_count
        for n in cand:
            if n.free >= g:
                return [(n, g)]
        if g > max((n.total for n in cand), default=0):
            need, plan = g, []
            for n in cand:
                if need <= 0:
                    break
                if n.free == n.total:
                    take = min(n.total, need); plan.append((n, take)); need -= take
            return plan if need == 0 else None
        return None

    def _find_partner(self, job, gss):
        """collocate 가능한 running solo 잡: 동일 gpu_count, SS합≤gss, 단일노드, 미packed.
        _solo[gpu_count] 인덱스로 O(버킷) — 전체 running 순회 안 함."""
        bucket = self._solo.get(job.gpu_count)
        if not bucket:
            return None
        for rid in bucket:
            r = self.running.get(rid)
            if r is None or r.partner is not None or len(r.alloc) > 1:
                continue
            if job.ss + r.ss <= gss:
                return r
        return None

    def _solo_add(self, job):
        if len(job.alloc) <= 1:                      # 단일노드 solo만 색인
            self._solo.setdefault(job.gpu_count, set()).add(job.id)

    def _solo_remove(self, job):
        b = self._solo.get(job.gpu_count)
        if b:
            b.discard(job.id)

    def _schedule(self):
        # 만석 + collocation 여지 없으면 스케줄 생략(고부하 O(n²) 차단).
        free = sum(n.free for n in self.nodes)
        gss = self._cur_gss()
        if free <= 0 and not (gss > 0 and self._solo):
            return
        # Lucid 정렬키 gpu_count×duration은 정적 → 신규 도착(dirty) 때만 재정렬.
        if getattr(self, "_wait_dirty", True):
            self.wait.sort(key=lambda j: j.gpu_count * j.duration)
            self._wait_dirty = False
        # 지연삭제: 배치된 잡은 _placed로 표시, 앞에서 미배치 CAP개만 후보(O(CAP))
        cand_list = []
        for j in self.wait:
            if j.id in self._placed:
                continue
            cand_list.append(j)
            if len(cand_list) >= 3000:
                break
        maxtot = max(n.total for n in self.nodes)
        placed = []
        for job in cand_list:
            # 1) collocation 시도 (단일노드·packing 허용 시)
            if gss > 0 and job.gpu_count <= maxtot:
                p = self._find_partner(job, gss)
                if p is not None:
                    # 같은 GPU 집합 공유 → 추가 자원 점유 없음. 둘 다 느려짐.
                    self._advance(p)
                    self._solo_remove(p)             # p는 더 이상 solo 아님
                    job.partner = p; p.partner = job
                    job.place_time = self.now; job.last_update = self.now
                    job.speed = p.speed              # 같은 노드 공유 → 파트너와 동일 타입계수
                    job.alloc = []                   # collocated 잡은 자원 반납 안 함(파트너 보유)
                    self.running[job.id] = job
                    self._reschedule_finish(job)
                    self._reschedule_finish(p)
                    placed.append(job)
                    continue                          # collocate 성공 → 다음 잡
            # 2) 단독 배치
            plan = self._alloc(job, self.nodes)
            if plan is None:
                continue                              # 비선점·non-blocking: 자리 없으면 대기
            for n, cnt in plan:
                n.free -= cnt
            job.alloc = plan; job.partner = None
            job.speed = max(speed_of(n.gpu_type) for n, _ in plan)   # 배치 타입 계수
            job.place_time = self.now + self.ovh.place_cost(1)
            job.last_update = job.place_time
            job.remaining = job.duration
            self.running[job.id] = job
            self._solo_add(job)                       # 단독 배치 → solo 색인
            self._push(self._eta(job), FINISH, job.id)
            placed.append(job)
        if placed:
            for j in placed:
                self._placed.add(j.id)
            if len(self._placed) > 4096:              # 지연삭제 주기 compact (균등분산 O(n))
                self.wait = [j for j in self.wait if j.id not in self._placed]
                self._placed.clear()

    def _results(self):
        qs = sorted(j.place_time - j.arrival for j in self.finished if j.place_time >= 0)
        rows = [(j.place_time - j.arrival, max(j.finish_time - j.place_time, 0.1), j.gpu_count)
                for j in self.finished if j.place_time >= 0]
        p = lambda a, x: a[min(len(a) - 1, int(len(a) * x))] if a else 0
        amax = max((u / t * 100 for _, u, t in self.alloc_samples), default=0)
        aavg = (sum(u / t * 100 for _, u, t in self.alloc_samples) /
                len(self.alloc_samples)) if self.alloc_samples else 0
        return {"n": len(self.finished),
                "q_p50": p(qs, .5), "q_p90": p(qs, .9), "q_p99": p(qs, .99),
                "q_max": qs[-1] if qs else 0, "alloc_max": amax, "alloc_avg": aavg,
                "alloc_series": self.alloc_samples, "rows": rows}
