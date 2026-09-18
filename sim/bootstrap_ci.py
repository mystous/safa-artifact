"""A3 — 변동성 구간(CI): 잡별 metric 부트스트랩 신뢰구간.

이 시뮬은 전체 트레이스 결정적 재생이라 시드 랜덤성이 없다(같은 입력→같은 출력).
따라서 정직한 변동성 추정은 '잡 모집단에 대한 부트스트랩'이다: 관측된 N개 잡의
metric 벡터에서 N개를 복원추출(B회) → 통계량 분포 → 95% CI(2.5/97.5 백분위).

방법(명시):
  1) 결정적 1회 실행의 <policy>_jobs.csv에서 잡별 (arrival, start, queue_sec)을 읽는다.
  2) 잡별 order-fairness score(per_job_score, 추월 기반)를 **전체 모집단에서 1회** 계산한다.
     (추월 score는 잡쌍 상호의존이라 리샘플 후 재계산하면 의미가 깨짐 → score는 잡 속성으로 고정.)
  3) (queue_sec 벡터, score 벡터)를 한 묶음으로 B=1000회 복원추출.
     각 리샘플에서 q_p50, fair_p1(=score의 1백분위)을 계산 → 분포.
  4) 95% CI = [2.5%, 97.5%] 백분위, 점추정 = 원본 전수 통계량.

핵심 구성: 512 single / 512 hetero. 주요 정책: fifo, las, sfqa, sfqa-auto, lucid.
출력: sweep_results/ci/bootstrap_ci.csv
"""
import csv
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from order_fairness import per_job_score   # noqa: E402

RAW = os.path.join(HERE, "sweep_results", "raw")
CONFIGS = [(512, "single"), (512, "hetero")]
POLS = ["fifo", "las", "sfqa", "sfqa-auto", "lucid"]
B = 1000
SEED = 12345


def load(d, pol):
    f = os.path.join(RAW, d, f"{pol}_jobs.csv")
    if not os.path.exists(f):
        return None
    rows = list(csv.DictReader(open(f)))
    if len(rows) < 100:
        return None
    arr = np.array([float(r["arrival_s"]) for r in rows])
    start = np.array([float(r["start_s"]) for r in rows])
    q = np.array([float(r["queue_sec"]) for r in rows])
    return arr, start, q


def main():
    rng = np.random.default_rng(SEED)
    out_rows = []
    for gpu, kind in CONFIGS:
        d = f"cmp{gpu}_{kind}"
        for pol in POLS:
            data = load(d, pol)
            if data is None:
                print(f"  skip {d}/{pol} (no data)")
                continue
            arr, start, q = data
            n = len(q)
            # 전체 모집단 잡별 fairness score(추월 기반) — 1회 계산, 잡 속성으로 고정.
            jb = [(arr[i], start[i], 0) for i in range(n)]
            score = np.array(per_job_score(jb))
            # 점추정(전수)
            q_p50_hat = float(np.percentile(q, 50))
            fp1_hat = float(np.percentile(score, 1))
            # 부트스트랩
            q50s = np.empty(B)
            fp1s = np.empty(B)
            for b in range(B):
                idx = rng.integers(0, n, n)
                q50s[b] = np.percentile(q[idx], 50)
                fp1s[b] = np.percentile(score[idx], 1)
            q50_lo, q50_hi = np.percentile(q50s, [2.5, 97.5])
            fp1_lo, fp1_hi = np.percentile(fp1s, [2.5, 97.5])
            out_rows.append(dict(gpu=gpu, kind=kind, policy=pol, n=n,
                                 q_p50=q_p50_hat, q_p50_lo=q50_lo, q_p50_hi=q50_hi,
                                 fair_p1=fp1_hat, fair_p1_lo=fp1_lo, fair_p1_hi=fp1_hi))
            print(f"  {d}/{pol:9}  q_p50={q_p50_hat:.0f} [{q50_lo:.0f},{q50_hi:.0f}]  "
                  f"fair_p1={fp1_hat:.1f} [{fp1_lo:.1f},{fp1_hi:.1f}]", flush=True)

    outdir = os.path.join(HERE, "sweep_results", "ci")
    os.makedirs(outdir, exist_ok=True)
    of = os.path.join(outdir, "bootstrap_ci.csv")
    with open(of, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gpu", "kind", "policy", "n", "q_p50", "q_p50_lo", "q_p50_hi",
                    "fair_p1", "fair_p1_lo", "fair_p1_hi"])
        for r in out_rows:
            w.writerow([r["gpu"], r["kind"], r["policy"], r["n"],
                        round(r["q_p50"]), round(r["q_p50_lo"]), round(r["q_p50_hi"]),
                        round(r["fair_p1"], 2), round(r["fair_p1_lo"], 2), round(r["fair_p1_hi"], 2)])
    print(f"\n→ {of}")


if __name__ == "__main__":
    main()
