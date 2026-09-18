"""A2-3 — Alibaba PAI GPU 트레이스("MLaaS in the Wild", NSDI'22,
cluster-trace-gpu-v2020)를 sweep 포맷으로 변환.

리뷰어 R4("일반화 약함")를 닫기 위한 **3번째** 독립 대규모 트레이스.
Philly(MS, 2017) · Helios(SenseTime, 2020)에 이어 Alibaba PAI(2020)로 핵심
경향(과부하·이종에서 정보-우위 그리디의 순서 불공정 ↑, SAFA/sfqa-auto의 추월
불공정 억제)이 재현되는지 검증한다.

원본: /tmp/alibaba/pai_task_table.csv (헤더 없음, 1,261,050행)
  컬럼 순서(공식): job_name,task_name,inst_num,status,start_time,end_time,
                   plan_cpu,plan_mem,plan_gpu,gpu_type
  - start_time/end_time: 초 단위 epoch(상대), 일부 행은 빈 값(Running/Waiting)
  - plan_gpu: **분수 GPU를 백분율로** 표기. 100=1 GPU, 50=0.5, 25=0.25, 200=2 GPU.
              (분포 확인: 100=442k, 25=272k, 50=137k, 10=117k, 200=16k …)
  - inst_num: 인스턴스(병렬/gang) 수. 대부분 1, 일부 2~100+.
  - status: Terminated(885k, 완료) / Failed / Running / Waiting.

변환 규칙(명시):
  - **Terminated만** 사용(완료 잡). Failed/Running/Waiting 제외.
  - duration = end_time − start_time, **>0만**.
  - per-instance GPU = plan_gpu>=100 이면 round(plan_gpu/100), 즉 whole-GPU 정수.
    plan_gpu<100(분수 GPU 단독 공유, 예 25·50) 은 정수 엔진 제약상 **1로 올림**.
    → gang 총 GPU = inst_num × per_instance_gpu.
  - gpu_count >= 1 만(plan_gpu 빈 값/0 제외).
  - arrival_s = start_time, 최소값=0 정규화. (PAI는 submit 컬럼이 task table에
    없어 start_time을 도착으로 사용 — Helios start 사용과 동일 관행.)
  - service_sec = duration, **Philly·Helios와 동일 48h(172800s) 클램프**.
  - 도착순 정렬.

서브샘플: 전수 732,691 GPU잡은 Philly(111k)·Helios(125k)의 ~6배 → 정렬계열
정책(themis/sfqa/lucid) 스윕이 비현실적. **seed=42 무작위 16.4% 서브샘플**로
~120k(Philly·Helios급)에 맞춘다. 무작위 샘플은 도착률·service·gpu 분포를
보존하므로 동일 클러스터 규모에서 부하배수가 비례 유지된다.
달성 부하(서브샘플): 동시수요≈943 GPU →
  256 GPU=3.69x(과부하) / 512=1.84x(중부하) / 1024=0.92x(저부하)
→ Philly 스윕(3.6/1.8/0.9x)과 거의 동일 영역. 같은 256/512/1024 규모 사용.

출력: sim/alibaba_trace.csv (job_id,arrival_s,service_sec,gpu_count) — 서브샘플본.
"""
import csv
import math
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = "/tmp/alibaba/pai_task_table.csv"
OUT = os.path.join(HERE, "alibaba_trace.csv")
CLAMP = 172800.0          # 48h, Philly·Helios 스윕과 동일
SUB_RATE = 0.164          # seed=42 → ~120k (Philly·Helios급)
SEED = 42


def per_instance_gpu(plan_gpu):
    """plan_gpu(백분율) → per-instance whole-GPU 정수.
    >=100: round(pg/100).  <100(분수 공유): 1로 올림(정수 엔진 제약)."""
    if plan_gpu >= 100:
        return max(1, round(plan_gpu / 100.0))
    return 1


def main():
    rng = random.Random(SEED)
    parsed = []
    excl_status = excl_time = excl_gpu = 0
    clamped = 0
    frac_jobs = 0            # plan_gpu<100 (분수→1로 올림)된 잡 수
    total_terminated = 0
    for i, r in enumerate(open(SRC)):
        f = r.rstrip("\n").split(",")
        if len(f) != 10:
            continue
        job, task, inst, st, s, e, cpu, mem, pg, gt = f
        if st != "Terminated":
            excl_status += 1
            continue
        total_terminated += 1
        try:
            s = float(s); e = float(e); inst = int(float(inst)); pgv = float(pg)
        except ValueError:
            excl_time += 1
            continue
        d = e - s
        if d <= 0:
            excl_time += 1
            continue
        if pgv <= 0:
            excl_gpu += 1
            continue
        per = per_instance_gpu(pgv)
        if pgv < 100:
            frac_jobs += 1
        g = inst * per
        if g < 1:
            excl_gpu += 1
            continue
        if rng.random() >= SUB_RATE:
            continue
        if d > CLAMP:
            clamped += 1
            d = CLAMP
        parsed.append((f"ali-{job}-{task}#{i}", s, d, g))

    t0 = min(p[1] for p in parsed)
    tmax = max(p[1] for p in parsed)
    parsed.sort(key=lambda x: x[1])
    with open(OUT, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["job_id", "arrival_s", "service_sec", "gpu_count"])
        for jid, sub, d, g in parsed:
            w.writerow([jid, round(sub - t0, 1), round(d, 1), g])

    n = len(parsed)
    gpu_sec = sum(d * g for _, _, d, g in parsed)
    span = tmax - t0
    demand = gpu_sec / span
    durs = sorted(d for _, _, d, _ in parsed)
    gps = sorted(g for _, _, _, g in parsed)

    def pc(a, x):
        return a[min(len(a) - 1, int(len(a) * x))]

    multi = sum(1 for _, _, _, g in parsed if g > 1)
    print(f"→ {OUT}  n={n}")
    print(f"   원본 Terminated={total_terminated}  제외: status={excl_status}, "
          f"time<=0={excl_time}, gpu(empty/0)={excl_gpu}")
    print(f"   분수 plan_gpu<100 → 1로 올림된 잡: {frac_jobs} "
          f"(서브샘플 후 비율 별도)")
    print(f"   clamped>48h = {clamped} ({clamped/n*100:.2f}%)")
    print(f"   span_days = {span/86400:.1f}")
    print(f"   duration p50/p90/p99 = {pc(durs,.5):.0f}/{pc(durs,.9):.0f}/{pc(durs,.99):.0f}s")
    print(f"   gpu_count p50/p90/p99/max = {pc(gps,.5)}/{pc(gps,.9)}/{pc(gps,.99)}/{gps[-1]}")
    print(f"   multi-GPU(>1) 비중 = {multi/n*100:.1f}%")
    print(f"   avg concurrent GPU demand = {demand:.0f} GPUs")
    for cap in [256, 512, 1024]:
        print(f"     cap={cap}: load = {demand/cap:.2f}x  ({cap//8} nodes)")


if __name__ == "__main__":
    main()
