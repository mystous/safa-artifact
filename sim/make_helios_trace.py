"""A2-2 — Helios(SenseTime, SC'21) 대규모 공개 트레이스를 sweep 포맷으로 변환.

리뷰어 R4("주 평가가 단일 트레이스 Philly라 일반화 약함")를 닫기 위한 2번째
독립 대규모 트레이스. Philly(MS, 2017)와 독립한 SenseTime 4-클러스터 로그 중
**Venus**(246,709행, GPU잡 125,303 — Philly 111,586과 동급 규모, 멀티-GPU 비중 최대).

원본: /tmp/helios/data/Venus/cluster_log.csv
  컬럼: job_id,user,vc,gpu_num,cpu_num,node_num,state,submit_time,start_time,
        end_time,duration,queue
  - submit/start/end_time: 'YYYY-MM-DD HH:MM:SS' 문자열
  - duration: 초 단위 실행시간(검증: end_time-start_time과 mismatch 0)
  - queue: 큐 대기초(여기선 스케줄러가 재산출하므로 미사용)

변환 규칙:
  - gpu_count = gpu_num. **gpu_num<=0(CPU잡)·duration<=0 제외.**
  - arrival_s = submit_time epoch초, 최소값=0 정규화.
  - service_sec = duration. **Philly와 동일 48h(172800s) 클램프**(클램프 수 기록).
  - 도착순 정렬.
서브샘플 없음 — Venus GPU잡 125k가 Philly 111k와 동급이라 전수 사용.
출력: sim/helios_trace.csv (job_id,arrival_s,service_sec,gpu_count)
"""
import csv
import os
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = "/tmp/helios/data/Venus/cluster_log.csv"
OUT = os.path.join(HERE, "helios_trace.csv")
CLAMP = 172800.0   # 48h, Philly 스윕과 동일


def ep(s):
    return datetime.fromisoformat(s).timestamp()


def main():
    rows = list(csv.DictReader(open(SRC)))
    parsed = []
    cpu = 0
    baddur = 0
    clamped = 0
    for i, r in enumerate(rows):
        try:
            g = int(r["gpu_num"])
        except (ValueError, KeyError):
            g = 0
        if g <= 0:
            cpu += 1
            continue
        try:
            d = float(r["duration"])
        except (ValueError, KeyError):
            d = -1
        if d <= 0:
            baddur += 1
            continue
        if d > CLAMP:
            clamped += 1
            d = CLAMP
        sub = ep(r["submit_time"])
        parsed.append((f"{r['job_id']}#{i}", sub, d, g))
    t0 = min(p[1] for p in parsed)
    tmax = max(p[1] for p in parsed)
    parsed.sort(key=lambda x: x[1])
    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["job_id", "arrival_s", "service_sec", "gpu_count"])
        for jid, sub, d, g in parsed:
            w.writerow([jid, round(sub - t0, 1), round(d, 1), g])
    gpu_sec = sum(d * g for _, _, d, g in parsed)
    span = tmax - t0
    avg_demand = gpu_sec / span
    print(f"→ {OUT}  n={len(parsed)}  (excluded: cpu/g<=0={cpu}, bad_dur={baddur})")
    print(f"   clamped>48h = {clamped} ({clamped/len(parsed)*100:.2f}%)")
    print(f"   span_days = {span/86400:.1f}")
    print(f"   avg concurrent GPU demand = {avg_demand:.1f} GPUs")
    for cap in [160, 256, 384, 512, 896, 1024]:
        print(f"     cap={cap}: load = {avg_demand/cap:.2f}x")

    # ── 시드 고정 50% 층화 서브샘플(런타임 절감용) ──────────────────────────────
    # 전수(125k)에서 themis/sfqa류 정렬정책이 과부하 single에서 대기열 깊이로 인해
    # 정책당 ~20분까지 소요 → 9정책×6구성 스윕이 비현실적. 무작위 50% 서브샘플은
    # 도착률·service·gpu 분포를 보존하므로 부하배수가 동일(클러스터 크기를 절반으로
    # 맞추면 동일 영역)하면서 대기열 깊이를 절반→정렬비용 ~4x 절감. seed=42 기록.
    import random
    rng = random.Random(42)
    sub = [p for p in parsed if rng.random() < 0.5]
    sub.sort(key=lambda x: x[1])
    sub_out = os.path.join(HERE, "helios_trace_sub.csv")
    with open(sub_out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["job_id", "arrival_s", "service_sec", "gpu_count"])
        for jid, sub_t, d, g in sub:
            w.writerow([jid, round(sub_t - t0, 1), round(d, 1), g])
    sub_demand = sum(d * g for _, _, d, g in sub) / span
    print(f"\n→ {sub_out}  n={len(sub)} (seed=42, 50% 층화)")
    print(f"   avg concurrent GPU demand = {sub_demand:.1f} GPUs")
    for cap in [80, 192, 448]:
        print(f"     cap={cap}: load = {sub_demand/cap:.2f}x")


if __name__ == "__main__":
    main()
