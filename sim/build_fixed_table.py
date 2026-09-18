#!/usr/bin/env python3
"""raw_fixed/cmp*/<pol>_jobs.csv + _alloc.csv → 주 결과와 동일 7지표 sweep_table.
지표 정의는 placement_axis(=검증된 주 결과 정의)와 동일."""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from order_fairness import per_job_score      # noqa: E402
from fairness import gini                      # noqa: E402

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sweep_results", "raw_fixed")
POLS = ["fifo", "sjf", "las", "kueue", "easy", "themis", "sfqa", "sfqa-auto", "fgd", "lucid"]
CFGS = [("256", "single"), ("256", "hetero"), ("512", "single"),
        ("512", "hetero"), ("1024", "single"), ("1024", "hetero")]


SUMM = "/tmp/sweepjunk"   # run_sweep --summary-out 태스크별 디렉토리(엔진 alloc_avg 보유)


def engine_alloc(g, k, pol):
    """엔진이 계산한 alloc_avg(드레인 제외) — summary.csv에서 읽음."""
    p = os.path.join(SUMM, f"{g}_{k}_{pol}", f"cmp{g}_{k}", "summary.csv")
    if not os.path.exists(p):
        return 0.0
    for r in csv.DictReader(open(p)):
        if r["policy"] == pol:
            return float(r["alloc_avg"])
    return 0.0


def main():
    out = []
    for g, k in CFGS:
        d = os.path.join(RAW, f"cmp{g}_{k}")
        for pol in POLS:
            jf = os.path.join(d, f"{pol}_jobs.csv"); af = os.path.join(d, f"{pol}_alloc.csv")
            if not os.path.exists(jf):
                continue
            rows = list(csv.DictReader(open(jf)))
            qs = sorted(float(r["queue_sec"]) for r in rows); n = len(qs)
            if n < 100:
                continue
            q_p50 = qs[int(n * .5)]; q_p99 = qs[int(n * .99)]; q_max = qs[-1]
            jb = [(float(r["arrival_s"]), float(r["start_s"]), 0) for r in rows]
            sc = sorted(per_job_score(jb))
            p1 = sc[int(n * .01)]; lt50 = 100.0 * sum(1 for x in sc if x < 50) / n
            gw = gini(qs); pr = q_p99 / q_p50 if q_p50 else 0.0
            aa = engine_alloc(g, k, pol)
            out.append(dict(gpu=g, kind=k, policy=pol, q_p50=round(q_p50), q_max=round(q_max),
                            fair_p1=round(p1, 1), lt50_pct=round(lt50, 3), alloc_avg=round(aa, 1),
                            gini_wait=round(gw, 4), p99_p50=round(pr, 2)))
            print(f"{g:>4} {k:6} {pol:10} q_p50={q_p50/1e6:6.2f}M  p1={p1:5.1f}  lt50={lt50:5.2f}  "
                  f"alloc={aa:5.1f}  gini={gw:.3f}  p99/50={pr:.2f}", flush=True)
    of = os.path.join(os.path.dirname(RAW), "fixed_sweep_table.csv")
    with open(of, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["gpu", "kind", "policy", "q_p50", "q_max",
                                          "fair_p1", "lt50_pct", "alloc_avg", "gini_wait", "p99_p50"])
        w.writeheader(); w.writerows(out)
    print(f"\n→ {of}  ({len(out)} rows)")


if __name__ == "__main__":
    main()
