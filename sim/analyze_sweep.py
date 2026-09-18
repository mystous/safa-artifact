"""부하 스윕 종합·다각 분석 + 전 그래프 생성.

256·512·1024 GPU × 단일·이종 × 전 정책(engine8 + lucid, sia는 512/1024) 결과로:
  1) 부하곡선: q_p50 / q_max / 공정성 p1 / alloc평균  (단일·이종, 정책 라인)
  2) q–공정성 trade-off scatter (부하별)
  3) 단일 vs 이종 막대
  4) 정책별 종합 표(CSV)
order-fairness는 <pol>_jobs.csv(arrival·start)에서 per_job_score로 산출.
summary에 lucid 행이 없으면 _jobs/_alloc에서 보강 계산.
"""
import csv, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from order_fairness import per_job_score

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(_HERE, "sweep_results")
A = os.path.join(OUT, "raw")          # per-job/alloc 덤프 루트(gitignore)
SUM = OUT                              # summary.csv 루트(커밋)
GPUS = [256, 512, 1024]
KINDS = ["single", "hetero"]
POLS = ["fifo", "sjf", "las", "kueue", "easy", "themis", "fgd", "sfqa", "sfqa-auto", "lucid", "sia"]
COL = {"fifo": "#888", "sjf": "tab:orange", "las": "tab:green", "kueue": "tab:olive",
       "easy": "tab:brown", "themis": "tab:purple", "fgd": "tab:gray", "sfqa": "tab:cyan",
       "sfqa-auto": "tab:red", "lucid": "tab:blue", "sia": "tab:pink"}


def dname(g, k):
    return f"cmp{g}_{k}"


def pctl(a, x):
    a = sorted(a); return a[min(len(a) - 1, int(len(a) * x))] if a else 0


def load_jobs(d, pol):
    f = f"{A}/{d}/{pol}_jobs.csv"
    if not os.path.exists(f):
        return None
    rows = list(csv.DictReader(open(f)))
    if len(rows) < 100:
        return None
    return rows


def fairness_p1(rows):
    jb = [(float(r["arrival_s"]), float(r["start_s"]), 0) for r in rows]
    sc = sorted(per_job_score(jb))
    n = len(sc)
    return sum(sc) / n, sc[int(n * .01)], 100 * sum(1 for x in sc if x < 50) / n


BSLD_TAU = 10.0   # 초단기 작업 퇴화 방지 임계(논문 §V-D)


def bsld_stats(rows):
    """작업별 bounded slowdown = (queue+service)/max(service, τ). 낮을수록 공정."""
    b = []
    for r in rows:
        q = float(r["queue_sec"]); s = float(r["service_sec"])
        b.append((q + s) / max(s, BSLD_TAU))
    return pctl(b, .5), pctl(b, .99), max(b)


def makespan_days(rows):
    """makespan = max(start_s+service_sec) − min(arrival_s), 일(day) 단위."""
    ends = [float(r["start_s"]) + float(r["service_sec"]) for r in rows]
    arr = [float(r["arrival_s"]) for r in rows]
    return (max(ends) - min(arr)) / 86400.0


def alloc_avg(d, pol):
    f = f"{A}/{d}/{pol}_alloc.csv"
    if not os.path.exists(f):
        return None
    v = [float(r["alloc_pct"]) for r in csv.DictReader(open(f))]
    return sum(v) / len(v) if v else 0


# ── 데이터 수집(summary + _jobs 보강) ───────────────────────────────────────
data = {}   # (g,k,pol) -> dict(q_p50,q_max,alloc,fmean,fp1,flo)
for g in GPUS:
    for k in KINDS:
        d = dname(g, k)
        smap = {}
        sf = f"{SUM}/{d}/summary.csv"
        if os.path.exists(sf):
            for r in csv.DictReader(open(sf)):
                smap[r["policy"]] = r
        for pol in POLS:
            rows = load_jobs(d, pol)
            rec = {}
            if pol in smap:
                rec["q_p50"] = float(smap[pol]["q_p50"]); rec["q_max"] = float(smap[pol]["q_max"])
                rec["alloc"] = float(smap[pol]["alloc_avg"])
            elif rows:   # summary 없으나 _jobs 있으면 보강
                qs = [float(r["queue_sec"]) for r in rows]
                rec["q_p50"] = pctl(qs, .5); rec["q_max"] = max(qs)
                aa = alloc_avg(d, pol); rec["alloc"] = aa if aa is not None else 0
            else:
                continue
            if rows:
                rec["fmean"], rec["fp1"], rec["flo"] = fairness_p1(rows)
                rec["bsld_p50"], rec["bsld_p99"], rec["bsld_max"] = bsld_stats(rows)
                rec["makespan_days"] = makespan_days(rows)
            data[(g, k, pol)] = rec
        print(f"  {d}: {[p for p in POLS if (g,k,p) in data]}", flush=True)


def series(k, pol, key):
    xs, ys = [], []
    for g in GPUS:
        rec = data.get((g, k, pol))
        if rec and key in rec:
            xs.append(g); ys.append(rec[key])
    return xs, ys


# ── 1) 부하곡선: q_p50 / q_max / 공정성 p1 / alloc ──────────────────────────
def loadcurve(key, ylabel, logy, fname, title):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5), sharey=True)
    for ax, k in zip(axes, KINDS):
        for pol in POLS:
            xs, ys = series(k, pol, key)
            if len(xs) >= 2:
                ax.plot(xs, ys, "o-", color=COL[pol], label=pol, lw=1.8, ms=5,
                        alpha=0.9 if pol in ("sfqa-auto", "fifo") else 0.6)
        ax.set_title(f"{k}"); ax.set_xlabel("GPU (load: 256=3.6x, 512=1.8x, 1024=0.9x)")
        ax.set_xscale("log"); ax.set_xticks(GPUS); ax.set_xticklabels(GPUS)
        if logy:
            ax.set_yscale("log")
        ax.grid(alpha=0.3, which="both")
    axes[0].set_ylabel(ylabel); axes[1].legend(ncol=2, fontsize=8)
    fig.suptitle(title, fontsize=13)
    fig.tight_layout(); fig.savefig(f"{OUT}/{fname}", dpi=130); plt.close(fig)
    print(f"→ {OUT}/{fname}")


loadcurve("q_p50", "queue delay p50 (s)", True, "curve_q_p50.png",
          "Load curve: median queue delay (lower=better)")
loadcurve("q_max", "queue delay max (s)", True, "curve_q_max.png",
          "Load curve: worst-case queue delay (starvation)")
loadcurve("fp1", "order-fairness p1 (100=fair)", False, "curve_fairness_p1.png",
          "Load curve: worst-1% order-fairness (higher=fairer)")
loadcurve("alloc", "GPU allocation avg (%)", False, "curve_alloc.png",
          "Load curve: average GPU allocation")

# ── 2) q–공정성 trade-off scatter (부하별 패널) ─────────────────────────────
fig, axes = plt.subplots(2, 3, figsize=(15, 9))
for ci, g in enumerate(GPUS):
    for ri, k in enumerate(KINDS):
        ax = axes[ri][ci]
        for pol in POLS:
            rec = data.get((g, k, pol))
            if rec and "q_p50" in rec and "fp1" in rec:
                ax.scatter(rec["q_p50"], rec["fp1"], color=COL[pol], s=70,
                           edgecolor="k", lw=0.5, zorder=3)
                ax.annotate(pol, (rec["q_p50"], rec["fp1"]), fontsize=7,
                            xytext=(3, 3), textcoords="offset points")
        ax.set_xscale("log"); ax.set_title(f"{g} GPU {k}", fontsize=10)
        ax.set_xlabel("q_p50 (s, log) ←빠름"); ax.set_ylabel("fairness p1 ↑공정")
        ax.grid(alpha=0.3)
fig.suptitle("q–fairness trade-off (좌상단=빠르고 공정; sfqa-auto 목표)", fontsize=13)
fig.tight_layout(); fig.savefig(f"{OUT}/tradeoff_scatter.png", dpi=130); plt.close(fig)
print(f"→ {OUT}/tradeoff_scatter.png")

# ── 3) 종합 표 CSV ──────────────────────────────────────────────────────────
with open(f"{OUT}/sweep_table.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["gpu", "kind", "policy", "q_p50", "q_max", "alloc_avg", "fair_mean", "fair_p1", "lt50_pct", "makespan_days"])
    for g in GPUS:
        for k in KINDS:
            for pol in POLS:
                rec = data.get((g, k, pol))
                if rec:
                    w.writerow([g, k, pol, round(rec.get("q_p50", 0)), round(rec.get("q_max", 0)),
                                round(rec.get("alloc", 0), 1), round(rec.get("fmean", 0), 1),
                                round(rec.get("fp1", 0), 1), round(rec.get("flo", 0), 2),
                                round(rec.get("makespan_days", 0), 2)])
print(f"→ {OUT}/sweep_table.csv")

# ── 4) BSLD(slowdown 공정성) 표 CSV + 512 콘솔 출력 ─────────────────────────
with open(f"{OUT}/bsld_table.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["gpu", "kind", "policy", "bsld_p50", "bsld_p99", "bsld_max"])
    for g in GPUS:
        for k in KINDS:
            for pol in POLS:
                rec = data.get((g, k, pol))
                if rec and "bsld_p50" in rec:
                    w.writerow([g, k, pol, round(rec["bsld_p50"], 2),
                                round(rec["bsld_p99"], 2), round(rec["bsld_max"], 2)])
print(f"→ {OUT}/bsld_table.csv")

# 512 단일/이종 BSLD 표 콘솔 출력(논문용 숫자)
for k in KINDS:
    print(f"\n=== BSLD @ 512 GPU / {k} (낮을수록 slowdown 공정) ===")
    print(f"{'policy':<11}{'p50':>9}{'p99':>11}{'max':>13}")
    for pol in POLS:
        rec = data.get((512, k, pol))
        if rec and "bsld_p50" in rec:
            print(f"{pol:<11}{rec['bsld_p50']:>9.2f}{rec['bsld_p99']:>11.2f}{rec['bsld_max']:>13.2f}")

# 512 단일/이종 makespan(wall time) 표 콘솔 출력(논문용 숫자)
for k in KINDS:
    print(f"\n=== makespan @ 512 GPU / {k} (days, 낮을수록 효율) ===")
    print(f"{'policy':<11}{'makespan_days':>15}")
    for pol in POLS:
        rec = data.get((512, k, pol))
        if rec and "makespan_days" in rec:
            print(f"{pol:<11}{rec['makespan_days']:>15.2f}")
print("DONE")
