"""A5 — 시뮬 충실도 검증: 해석해를 아는 toy 케이스 vs 엔진 출력.

이산사건 코어가 큐 지연·완료시각을 옳게 계산하는지 손계산과 대조한다.
오버헤드는 끈다(enabled=False) — 순수 큐잉 동역학만 검증.

CASE 1 — 결정적 D/D/1 (단일 1-GPU 노드, FIFO).
  노드: 1 GPU. 잡 N개, 각 1 GPU·서비스 S초. 도착 간격 I초(I < S → 포화 누적).
  잡 k(0-base)는 k·I에 도착, 서버는 직전 잡 완료 후에야 시작.
    start_0 = 0,  start_k = max(k·I, start_{k-1}+S) = k·I 가 작으면 (k)·S 누적.
  I < S 이면 start_k = k·S (완전 포화), queue_k = k·S − k·I = k·(S−I).
  해석 q_max = (N−1)(S−I). 엔진 per-job queue_delay와 정확히 일치해야 함.

CASE 2 — 다중 GPU gang + 동시성 (2 GPU 노드, 1-GPU 잡 2개 동시 + 2-GPU 잡).
  노드 1개 total=2 GPU. t=0에 1-GPU 잡 2개 도착 → 둘 다 즉시 시작(queue=0).
  t=0에 2-GPU 잡 1개도 도착 → 자리 없어 대기. 1-GPU 잡 둘이 S후 완료되면 시작.
  해석: 2-GPU 잡 queue = S. (FIFO blocking: 2-GPU가 선두면 1-GPU도 막힘 → 순서 주의)
  여기선 1-GPU 둘을 먼저 도착(arrival 약간 빠르게)시켜 동시 배치 후 2-GPU가 대기하는
  케이스로 구성. queue(2-GPU)=S, 나머지=0.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, os.path.join(ROOT, "squad_ctrl"), os.path.join(ROOT, "k8s_replay")):
    sys.path.insert(0, p)

from engine import Job, Node, Overheads, Simulator   # noqa: E402
import policies as P                                   # noqa: E402

NO_OVH = Overheads(enabled=False)


def case1():
    N, S, I = 20, 100.0, 30.0      # I<S → 포화
    nodes = [Node(name="n0", gpu_type="b200", total=1)]
    jobs = [Job(id=str(k), arrival=k * I, duration=S, gpu_count=1, gpu_type="any")
            for k in range(N)]
    sim = Simulator(jobs, nodes, P.FIFO(), overheads=NO_OVH)
    sim.run()
    byid = {j.id: j for j in sim.finished}
    print("=== CASE 1: D/D/1 saturated FIFO (N=20, S=100, I=30) ===")
    max_err = 0.0
    for k in range(N):
        j = byid[str(k)]
        analytic_q = k * (S - I)        # k·(S−I)
        err = abs(j.queue_delay - analytic_q)
        max_err = max(max_err, err)
        if k in (0, 1, 5, 19):
            print(f"  job {k:2d}: engine q={j.queue_delay:8.3f}  analytic={analytic_q:8.3f}  err={err:.2e}")
    print(f"  analytic q_max=(N-1)(S-I)={(N-1)*(S-I):.1f}   MAX ABS ERR={max_err:.2e}")
    return max_err


def case2():
    S = 100.0
    nodes = [Node(name="n0", gpu_type="b200", total=2)]
    # 1-GPU 잡 2개 먼저(arrival 0), 2-GPU 잡 1개 살짝 뒤(arrival 1e-6 → 같은 틱이지만 도착순 뒤)
    jobs = [
        Job(id="a", arrival=0.0, duration=S, gpu_count=1, gpu_type="any"),
        Job(id="b", arrival=0.0, duration=S, gpu_count=1, gpu_type="any"),
        Job(id="c", arrival=0.0, duration=S, gpu_count=2, gpu_type="any"),
    ]
    sim = Simulator(jobs, nodes, P.FIFO(), overheads=NO_OVH)
    sim.run()
    byid = {j.id: j for j in sim.finished}
    print("\n=== CASE 2: 2-GPU node, two 1-GPU jobs + one 2-GPU job (FIFO) ===")
    # FIFO blocking: a,b 먼저 도착해 2 GPU 점유 → c는 자리 없어 대기, S후 시작.
    exp = {"a": 0.0, "b": 0.0, "c": S}
    max_err = 0.0
    for jid in ("a", "b", "c"):
        j = byid[jid]
        err = abs(j.queue_delay - exp[jid])
        max_err = max(max_err, err)
        print(f"  job {jid}: engine q={j.queue_delay:8.3f}  analytic={exp[jid]:8.3f}  err={err:.2e}")
    print(f"  MAX ABS ERR={max_err:.2e}")
    return max_err


def case3():
    """CASE 3 — 오버헤드 모델 검증: place_cost·teardown이 완료시각에 정확히 반영되는가.
    단일 1-GPU 잡 1개. enabled=True, solo startup. 완료시각 = arrival + sched_lat + startup_solo
       + duration + teardown."""
    ovh = Overheads(enabled=True)
    nodes = [Node(name="n0", gpu_type="b200", total=1)]
    S = 100.0
    jobs = [Job(id="x", arrival=10.0, duration=S, gpu_count=1, gpu_type="any")]
    sim = Simulator(jobs, nodes, P.FIFO(), overheads=ovh)
    sim.run()
    j = sim.finished[0]
    exp_place = 10.0 + ovh.sched_lat + ovh.startup_solo
    exp_finish = exp_place + S + ovh.teardown
    print("\n=== CASE 3: overhead-laden single job (solo startup) ===")
    print(f"  place_time engine={j.place_time:.3f} analytic={exp_place:.3f} err={abs(j.place_time-exp_place):.2e}")
    print(f"  finish_time engine={j.finish_time:.3f} analytic={exp_finish:.3f} err={abs(j.finish_time-exp_finish):.2e}")
    return max(abs(j.place_time - exp_place), abs(j.finish_time - exp_finish))


if __name__ == "__main__":
    e1 = case1()
    e2 = case2()
    e3 = case3()
    print(f"\nOVERALL MAX ABS ERR = {max(e1, e2, e3):.2e}  "
          f"({'PASS — within fp precision' if max(e1,e2,e3) < 1e-6 else 'CHECK'})")
