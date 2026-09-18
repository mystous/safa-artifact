"""실측 결과 종합 분석기.

/raid/squad/runs 의 모든 run(jct.csv, metrics.csv)을 집계해 큐잉지연·JCT 통계와
그룹별 비교 표를 /raid/squad/analysis 에 저장한다(runs_summary.csv + tables.md).
실행: /raid/squad/venv/bin/python analyze.py
"""
import csv
import os

RUNS = "/raid/squad/runs"
OUT = "/raid/squad/analysis"

# 실험 그룹 (run-id → 라벨)
GROUPS = {
    "사내 (in-house, 20 job, 1.5×)": [("base", "default-FIFO"), ("sfqa", "SFQA")],
    "Alibaba v2023 (40 job, 2.2×)": [("a23_base", "default-FIFO"), ("a23_sfqa", "SFQA")],
    "Philly (40 job, 저부하)": [("ph_base", "default-FIFO"), ("ph_sfqa", "SFQA")],
    "다정책 비교 (Alibaba v2023, 40 job, 2.2×) [age버그 버전]": [
        ("m_base", "default-FIFO"), ("m_fifo", "gate-FIFO"), ("m_sjf", "SJF"),
        ("m_las", "LAS(≈FIFO)"), ("m_sfqa", "SFQA"),
    ],
    "★최종: Philly 1000 층화샘플 다정책 (age·β 수정, peak 3.6×)": [
        ("p_base", "default-FIFO"), ("p_fifo", "gate-FIFO"), ("p_sjf", "SJF"),
        ("p_las", "LAS"), ("p_sfqa", "SFQA"),
    ],
    "★sfqa-auto v2 + SOTA 베이스라인 (Philly 1000 동일조건, 2026-06-04)": [
        ("p_sfqa_auto", "SFQA-auto(τ=10)"), ("p_auto_t1", "SFQA-auto(τ=1)"),
        ("p_easy", "EASY-backfill"), ("p_kueue", "Kueue"),
    ],
    "κ=6000 적응성 (peak 5.4×, 무튜닝 적응 vs 고정 노브)": [
        ("p_sfqa_k6000", "SFQA 고정(κ3000 튜닝값)"), ("p_auto_k6000", "SFQA-auto(τ=1)"),
    ],
    "충실 duration (JCT≤2h, 윈도우 d51~65, S=360, cap 없음)": [
        ("f360_kueue", "Kueue"), ("f360_auto", "SFQA-auto(τ=10)"), ("f360_easy", "EASY(완벽추정)"),
        ("f360_easyf1", "EASY f=1"), ("f360_easyf3", "EASY f=3"),
    ],
}


def pctl(vals, p):
    if not vals:
        return 0.0
    s = sorted(vals)
    return s[min(len(s) - 1, int(len(s) * p))]


def stat(run):
    jp = os.path.join(RUNS, run, "jct.csv")
    if not os.path.exists(jp):
        return None
    qs, js = [], []
    with open(jp) as f:
        for r in csv.DictReader(f):
            if r.get("queue_sec"):
                qs.append(float(r["queue_sec"]))
            if r.get("jct_sec"):
                js.append(float(r["jct_sec"]))
    alloc = 0.0
    mp = os.path.join(RUNS, run, "metrics.csv")
    if os.path.exists(mp):
        with open(mp) as f:
            for r in csv.DictReader(f):
                try:
                    alloc = max(alloc, float(r["alloc_pct"]))
                except (ValueError, KeyError):
                    pass
    return {
        "n": len(js),
        "q_p50": pctl(qs, .5), "q_p90": pctl(qs, .9), "q_max": max(qs) if qs else 0,
        "j_p50": pctl(js, .5), "j_p90": pctl(js, .9), "j_max": max(js) if js else 0,
        "alloc_max": alloc,
    }


def main():
    os.makedirs(OUT, exist_ok=True)
    rows = []
    md = ["# SQUAD K8s 실측 — 자동 집계 표\n"]
    for group, runs in GROUPS.items():
        md.append(f"\n## {group}\n")
        md.append("| run | 정책 | n | 큐잉 p50/p90/max | JCT p50/p90/max | 할당률 max |")
        md.append("|---|---|---|---|---|---|")
        for run, label in runs:
            s = stat(run)
            if not s:
                md.append(f"| {run} | {label} | — | (결과 없음) | | |")
                continue
            md.append(f"| {run} | {label} | {s['n']} | "
                      f"{s['q_p50']:.0f}/{s['q_p90']:.0f}/{s['q_max']:.0f} | "
                      f"{s['j_p50']:.0f}/{s['j_p90']:.0f}/{s['j_max']:.0f} | {s['alloc_max']:.0f}% |")
            rows.append({"group": group, "run": run, "policy": label, **s})

    with open(os.path.join(OUT, "runs_summary.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["group", "run", "policy", "n",
                                          "q_p50", "q_p90", "q_max", "j_p50", "j_p90", "j_max", "alloc_max"])
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(OUT, "tables.md"), "w") as f:
        f.write("\n".join(md) + "\n")
    print(f"집계 완료: {len(rows)} run → {OUT}/runs_summary.csv, tables.md")
    print("\n".join(md))


if __name__ == "__main__":
    main()
