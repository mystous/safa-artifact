"""공정성 지표 — 스케줄링 fairness 문헌의 정식 지표를 우리 데이터에 계산.

입력: 잡별 (queue_sec, service_sec, gpu_count). 실측 jct.csv 또는 시뮬 per-job CSV.
지표(출처):
  - Gini(slowdown)          : 분포 불평등(0=공정). 헤드라인. (Lorenz/Gini 표준)
  - p99.9 / max slowdown    : 최악(Rawlsian). 낮을수록 공정.
  - Jain on 1/slowdown      : Jain·Chiu·Hawe 1984. 1=공정.
  - Themis ρ (max, SI율)    : Mahajan NSDI'20. ρ=JCT/T_ideal, ρ≤1 비율↑=공정.
  - W&H-B 크기별 slowdown   : Wierman·Harchol-Balter SIGMETRICS'03. 1/(1−load) 선 이하면 공정.
slowdown = JCT / max(service, τ=10).  (Feitelson bounded slowdown)
"""
import csv
import math


def slowdowns(jobs, tau=10.0):
    return [max((q + s) / max(s, tau), 1.0) for q, s, g in jobs]


def gini(vals):
    v = sorted(vals); n = len(v)
    if n == 0 or sum(v) == 0:
        return 0.0
    cum = sum((i + 1) * x for i, x in enumerate(v))
    return (2 * cum) / (n * sum(v)) - (n + 1) / n


def jain(vals):
    if not vals:
        return 0.0
    s = sum(vals); s2 = sum(x * x for x in vals)
    return s * s / (len(vals) * s2) if s2 else 1.0


def pct(vals, p):
    if not vals:
        return 0.0
    v = sorted(vals)
    return v[min(len(v) - 1, int(len(v) * p))]


def themis_rho(jobs, total_gpu):
    """ρ_i = JCT_i / T_ideal. T_ideal = service if g≤fair else service·g/fair. fair=C/N."""
    n = max(1, len(jobs))
    fair = max(1.0, total_gpu / n)
    rhos = []
    for q, s, g in jobs:
        t_id = s if g <= fair else s * g / fair
        rhos.append((q + s) / max(t_id, 1e-9))
    si = sum(1 for r in rhos if r <= 1.0) / len(rhos) * 100
    return max(rhos), si


def whb_size_check(jobs, load, tau=10.0, nbins=10):
    """크기(service) 분위 bin별 평균 slowdown vs 1/(1−load). worst_ratio>1이면 일부 크기 불공정."""
    bound = 1.0 / (1.0 - min(load, 0.999))
    js = sorted(jobs, key=lambda x: x[1])
    n = len(js)
    worst = 0.0; big_bin_sd = 0.0
    for b in range(nbins):
        seg = js[b * n // nbins:(b + 1) * n // nbins]
        if not seg:
            continue
        sd = sum(max((q + s) / max(s, tau), 1.0) for q, s, g in seg) / len(seg)
        worst = max(worst, sd / bound)
        if b == nbins - 1:
            big_bin_sd = sd
    return bound, worst, big_bin_sd


def analyze(jobs, total_gpu, load):
    S = slowdowns(jobs)
    mrho, si = themis_rho(jobs, total_gpu)
    bound, worst, big = whb_size_check(jobs, load)
    mean_s = sum(S) / len(S)
    cov = (sum((x - mean_s) ** 2 for x in S) / len(S)) ** 0.5 / mean_s if mean_s else 0
    return {
        "n": len(jobs),
        "gini_sd": gini(S),
        "cov_sd": cov,
        "sd_p50": pct(S, .5), "sd_p99": pct(S, .99), "sd_p999": pct(S, .999), "sd_max": max(S),
        "jain_inv_sd": jain([1.0 / x for x in S]),
        "themis_rho_max": mrho, "si_rate_pct": si,
        "whb_bound": bound, "whb_worst_ratio": worst, "whb_bigjob_sd": big,
    }


def load_jct(path):
    """실측 jct.csv: pod, queue_sec, jct_sec → (q, s, g). g는 미기록이면 1."""
    jobs = []
    with open(path) as f:
        for r in csv.DictReader(f):
            if not r.get("jct_sec") or not r.get("queue_sec"):
                continue
            q, jct = float(r["queue_sec"]), float(r["jct_sec"])
            jobs.append((q, max(jct - q, 0.1), int(r.get("gpu_count", 1) or 1)))
    return jobs


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", help="run-id 또는 jct.csv 경로")
    ap.add_argument("--runs-dir", default="/raid/squad/runs")
    ap.add_argument("--total-gpu", type=int, default=8)
    ap.add_argument("--load", type=float, default=1.0, help="W&H-B용 부하 ρ 추정")
    args = ap.parse_args()
    import os
    hdr = (f"{'run':16} {'n':>5} {'Gini↓':>6} {'CoV↓':>6} {'sd_p50':>6} {'sd_p99':>7} "
           f"{'sd_max':>8} {'Jain↑':>6} {'ρmax↓':>8} {'SI%↑':>5} {'WHB✓':>6}")
    print(hdr); print("-" * len(hdr))
    for r in args.runs:
        path = r if r.endswith(".csv") else f"{args.runs_dir}/{r}/jct.csv"
        if not os.path.exists(path):
            print(f"{r:16} (없음)"); continue
        a = analyze(load_jct(path), args.total_gpu, args.load)
        print(f"{r:16} {a['n']:>5} {a['gini_sd']:>6.3f} {a['cov_sd']:>6.2f} {a['sd_p50']:>6.1f} "
              f"{a['sd_p99']:>7.1f} {a['sd_max']:>8.1f} {a['jain_inv_sd']:>6.3f} "
              f"{a['themis_rho_max']:>8.1f} {a['si_rate_pct']:>5.0f} {a['whb_worst_ratio']:>6.2f}")
