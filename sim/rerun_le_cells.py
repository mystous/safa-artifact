"""용량초과 잡 필터(le-cap) 정정 재실행 — 모집단 규칙(D26) 동반 셀용 일회성 러너.

run_sweep.py의 run_policy/build_nodes/dump를 그대로 재사용하고, 트레이스만
gpu_count<=cap으로 필터해 동일 모집단 비교를 만든다. 정책 스펙은
"sfqa@0.0003"처럼 @뒤에 고정 alpha를 줄 수 있다(그 외 정책은 이름 그대로).

사용:
  python3 rerun_le_cells.py --trace helios_trace_sub.csv --cap 80 \
      --gpu 80 --kind single --policies fifo,sjf,... --outdir sweep_results/helios_le80/cmp80_single
출력: <outdir>/<policy>_jobs.csv, <outdir>/summary_le.csv (p1/lt50/fair 포함)
"""
import argparse
import csv
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import run_sweep as RS                      # noqa: E402
import policies as P                        # noqa: E402
from engine import Job, Simulator, Overheads  # noqa: E402
from order_fairness import per_job_score   # noqa: E402


def run_param_sfqa(alpha, trace, nodes_proto, ovh):
    """run_sweep.run_policy의 일반 분기와 동일하되 SFQA(alpha=...)만 주입."""
    from engine import Node
    nodes = [Node(name=n.name, gpu_type=n.gpu_type, total=n.total) for n in nodes_proto]
    pol = P.SFQA(alpha=alpha)
    jobs = [Job(id=i, arrival=a, duration=d, gpu_count=g, gpu_type="any", vc=vc)
            for i, a, d, g, vc in trace]
    sim = Simulator(jobs, nodes, pol, overheads=ovh)
    r = sim.run()
    jr = [(j.id, j.arrival, j.place_time, j.queue_delay, j.duration, j.gpu_count)
          for j in sim.finished if j.queue_delay is not None]
    alloc = r.get("alloc_series", [])
    qs = [x[3] for x in jr]; ss = [x[4] for x in jr]; gs = [x[5] for x in jr]
    st = RS.stats(qs, ss, gs)
    st["policy"] = f"sfqa@{alpha:g}"
    st["alloc_max"] = r.get("alloc_max", 0.0); st["alloc_avg"] = r.get("alloc_avg", 0.0)
    return st, jr, alloc


def fairness(jr):
    jb = [(arr, start, 0) for _, arr, start, _, _, _ in jr]
    sc = sorted(per_job_score(jb))
    n = len(sc)
    if n == 0:
        return 0.0, 0.0, 0.0
    return (sum(sc) / n, sc[int(n * .01)], 100.0 * sum(1 for x in sc if x < 50) / n)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True)
    ap.add_argument("--cap", type=int, required=True)
    ap.add_argument("--gpu", type=int, required=True)
    ap.add_argument("--kind", required=True)
    ap.add_argument("--policies", required=True)
    ap.add_argument("--outdir", required=True)
    a = ap.parse_args()

    trace = [t for t in RS.load_trace(os.path.join(HERE, a.trace))
             if t[3] <= a.cap]
    print(f"trace={a.trace} cap<={a.cap} → n={len(trace)}", flush=True)
    nodes = RS.build_nodes(a.gpu, a.kind)
    outdir = a.outdir if os.path.isabs(a.outdir) else os.path.join(HERE, a.outdir)
    os.makedirs(outdir, exist_ok=True)

    sumf = os.path.join(outdir, "summary_le.csv")
    cols = ["policy", "n", "q_p50", "q_max", "fair_mean", "fair_p1", "lt50_pct", "alloc_avg"]
    rows = []
    for spec in a.policies.split(","):
        t0 = time.time()
        name, _, param = spec.partition("@")
        ovh = Overheads(enabled=True)
        if param:
            st, jr, alloc = run_param_sfqa(float(param), trace, nodes, ovh)
        else:
            st, jr, alloc = RS.run_policy(name, trace, nodes, ovh)
        fm, p1, lt50 = fairness(jr)
        RS.dump(outdir, spec.replace("@", "_a"), jr, alloc)
        row = {"policy": spec, "n": st["n"], "q_p50": round(st["q_p50"], 1),
               "q_max": round(st["q_max"], 1), "fair_mean": round(fm, 1),
               "fair_p1": round(p1, 1), "lt50_pct": round(lt50, 2),
               "alloc_avg": round(st.get("alloc_avg", 0.0), 1)}
        rows.append(row)
        print(f"{spec:16} n={row['n']} q_p50={row['q_p50']} p1={row['fair_p1']} "
              f"lt50={row['lt50_pct']}%  ({time.time()-t0:.0f}s)", flush=True)
        with open(sumf, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader(); w.writerows(rows)
    print(f"→ {sumf}", flush=True)


if __name__ == "__main__":
    main()
