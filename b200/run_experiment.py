"""실측 오케스트레이터: 한 번 실행으로 워크로드 제출→메트릭 수집→완료 대기→JCT/큐잉 추출.

baseline(gate 없음, default-scheduler FIFO) vs SFQA(--sfqa, gate+컨트롤러)를 같은 트레이스로 비교.
SFQA 모드는 사전에 sfqa_controller.py 가 떠 있어야 한다(이 스크립트는 워크로드/측정만 담당).

예)
  # baseline
  python run_experiment.py --trace inhouse --input <csv> --limit 24 --kappa 400 --min-dur 30 \
      --run-id base
  # SFQA (별도 터미널에서 sfqa_controller.py 먼저 실행)
  python run_experiment.py ... --sfqa --run-id sfqa
"""
import argparse
import csv
import os
import random
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone

K8S_REPLAY = "/home/mystous/gpu_scheduler/k8s_replay"
sys.path.insert(0, K8S_REPLAY)
from ingest import INGESTERS                       # noqa: E402
from normalize import NormalizeConfig, normalize, peak_demand  # noqa: E402
from model_assign import assign                    # noqa: E402
from emit import job_manifest                      # noqa: E402

from kubernetes import client, config              # noqa: E402

NS = "squad"
GPU = "nvidia.com/gpu"


def k8s():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    return client.CoreV1Api(), client.BatchV1Api()


def stratified_sample(jobs, n, seed=42):
    """전체 GPU 요청 개수 분포를 보존하며 n개 샘플.
    gpu_count 층별로 전체 비율대로 배분, 각 층 내 무작위 → duration(JCT) 분포도 자동 보존."""
    random.seed(seed)
    by = defaultdict(list)
    for j in jobs:
        by[j.gpu_count].append(j)
    tot = len(jobs)
    out = []
    for g, grp in by.items():
        k = max(1, round(n * len(grp) / tot))
        out.extend(random.sample(grp, min(k, len(grp))))
    random.shuffle(out)
    return out[:n]


def build(args):
    jobs = INGESTERS[args.trace](args.input, limit=args.limit)
    if args.drop_over > 0:  # 초장기 잡 제거 (주의: 장기 잡은 multi-GPU 비중↑ → 구성 왜곡)
        before = len(jobs)
        jobs = [j for j in jobs if j.duration <= args.drop_over]
        print(f"[run:{args.run_id}] duration>{args.drop_over/86400:.0f}일 제거: "
              f"{before - len(jobs)}건({(before-len(jobs))/before*100:.2f}%)", flush=True)
    if args.clamp_over > 0:  # 초장기 잡 절단(잡 유지 → GPU 분포 보존, 사용자 결정 2026-06-05)
        nc = sum(1 for j in jobs if j.duration > args.clamp_over)
        for j in jobs:
            if j.duration > args.clamp_over:
                j.duration = args.clamp_over
        print(f"[run:{args.run_id}] duration>{args.clamp_over/86400:.0f}일 절단: "
              f"{nc}건({nc/len(jobs)*100:.2f}%)", flush=True)
    if args.window_days > 0:  # 연속 윈도우로 한정(arrival 버스트 보존) + 재영점
        t0 = min(j.arrival_time for j in jobs)
        ws = t0 + args.window_start_day * 86400
        we = ws + args.window_days * 86400
        jobs = [j for j in jobs if ws <= j.arrival_time < we]
        rebase = min(j.arrival_time for j in jobs)  # 윈도우 시작을 t=0으로 재영점
        for j in jobs:
            j.arrival_time -= rebase
        print(f"[run:{args.run_id}] 윈도우 day {args.window_start_day}~"
              f"{args.window_start_day + args.window_days}: {len(jobs)}건", flush=True)
    if args.sample > 0:
        before = len(jobs)
        jobs = stratified_sample(jobs, args.sample, args.seed)
        print(f"[run:{args.run_id}] 층화 샘플 {len(jobs)}/{before} (GPU·duration 분포 보존)", flush=True)
    cfg = NormalizeConfig(cluster_gpu_types=args.gpu_types.split(","),
                          kappa=args.kappa, min_duration_sec=args.min_dur,
                          max_duration_sec=args.max_dur)
    jobs = normalize(jobs, cfg)
    peak, _ = peak_demand(jobs)
    print(f"[run:{args.run_id}] {len(jobs)} jobs, peak {peak} GPU "
          f"({peak/args.total_gpu:.1f}× capacity)", flush=True)
    est_rng = random.Random(args.seed + 1)  # f-모델 노이즈(재현 가능)
    out = []
    for j in jobs:
        spec = assign(j, run_mode="holder")
        m = job_manifest(j, spec, "default-scheduler", namespace=NS,
                         sfqa_gate=(args.policy not in ("none", "kueue")))
        if args.est_noise_f > 0:
            # Mu'alem & Feitelson(TPDS'01) f-모델: 추정 = 실제 × (1+u), u~U[0,f].
            # holder는 실제 duration 그대로 실행, 컨트롤러(EASY 예약)만 추정 라벨을 봄.
            est = j.duration * (1.0 + est_rng.uniform(0.0, args.est_noise_f))
            m["spec"]["template"]["metadata"]["labels"]["squad.io/duration-est"] = str(int(est))
        if args.policy == "kueue":  # Kueue: Job 라벨로 LocalQueue 제출(웹훅이 suspend 관리)
            m["metadata"].setdefault("labels", {})["kueue.x-k8s.io/queue-name"] = "squad-lq"
        out.append((j.arrival_time, m))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--trace", required=True, choices=list(INGESTERS))
    ap.add_argument("--input", required=True)
    ap.add_argument("--limit", type=int, default=0, help="앞 N개(0=무제한). 보통 --sample 사용")
    ap.add_argument("--sample", type=int, default=0, help="전체에서 분포보존 층화 샘플 N개")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--kappa", type=float, default=400.0)
    ap.add_argument("--min-dur", type=float, default=30.0)
    ap.add_argument("--max-dur", type=float, default=90.0, help="압축 후 duration 상한(초). 실험 시간 제한")
    ap.add_argument("--drop-over", type=float, default=0.0,
                    help="원본 duration이 이 값(초)을 넘는 잡을 샘플링 전에 제거(0=off). 단 장기 잡 제거는 GPU 구성 왜곡 — clamp 권장")
    ap.add_argument("--clamp-over", type=float, default=0.0,
                    help="원본 duration이 이 값(초)을 넘으면 이 값으로 절단(0=off). 잡을 버리지 않아 GPU 분포 보존")
    ap.add_argument("--window-start-day", type=float, default=0.0, help="트레이스 시작 기준 윈도우 시작(일)")
    ap.add_argument("--window-days", type=float, default=0.0, help="연속 윈도우 길이(일). 0=전체")
    ap.add_argument("--est-noise-f", type=float, default=0.0,
                    help="duration 추정 오차 f-모델(Mu'alem&Feitelson TPDS'01): est=dur×(1+U[0,f]). 0=완벽 추정")
    ap.add_argument("--gpu-types", default="NVIDIA-B200")
    ap.add_argument("--total-gpu", type=int, default=8)
    ap.add_argument("--policy", default="none",
                    choices=["none", "fifo", "sjf", "priority", "las", "themis", "sfqa", "sfqa-auto",
                             "easy", "kueue"],
                    help="none=gate 없음(순수 default FIFO). kueue=Kueue LocalQueue 제출"
                         "(gate·컨트롤러 없음). 나머지는 gate+policy_controller 필요")
    ap.add_argument("--run-id", default="run")
    ap.add_argument("--timeout", type=float, default=1800)
    ap.add_argument("--submit-clamp", type=float, default=5.0,
                    help="제출 간 최대 대기(초). 0=클램프 없음(arrival 충실 재현, 버스트 경합 보존)")
    args = ap.parse_args()

    outdir = f"/raid/squad/runs/{args.run_id}"
    os.makedirs(outdir, exist_ok=True)
    v1, batch = k8s()
    manifests = build(args)

    # 메트릭 수집기 시작
    mc = subprocess.Popen(
        ["/raid/squad/venv/bin/python",
         "/home/mystous/gpu_scheduler/squad_ctrl/metrics_collector.py",
         "--out", f"{outdir}/metrics.csv", "--period", "3", "--total-gpu", str(args.total_gpu)],
        env={**os.environ, "KUBECONFIG": "/home/mystous/.kube/config"})

    # arrival 타이밍대로 제출
    t0 = time.time()
    submit_log = open(f"{outdir}/submit_log.csv", "w", newline="")
    sw = csv.writer(submit_log); sw.writerow(["job", "arrival", "wall"])
    names = []
    for at, m in manifests:
        wait = at - (time.time() - t0)
        if wait > 0:
            time.sleep(wait if args.submit_clamp <= 0 else min(wait, args.submit_clamp))
        try:
            batch.create_namespaced_job(NS, m)
            names.append(m["metadata"]["name"])
            sw.writerow([m["metadata"]["name"], round(at, 1), round(time.time() - t0, 1)])
            submit_log.flush()
        except client.ApiException as e:
            print(f"  제출 실패 {m['metadata']['name']}: {e.status}", flush=True)
    print(f"[run:{args.run_id}] {len(names)} jobs 제출 완료, 완료 대기...", flush=True)

    # 모든 Job 완료 대기
    deadline = time.time() + args.timeout
    while time.time() < deadline:
        jl = batch.list_namespaced_job(NS).items
        active = [j for j in jl if (j.status.succeeded or 0) + (j.status.failed or 0) == 0]
        if not active:
            break
        time.sleep(5)
    print(f"[run:{args.run_id}] 완료. JCT/큐잉 추출...", flush=True)
    mc.terminate()

    # pod lifecycle → JCT·큐잉
    # Kueue 는 admission 전까지 Job suspend(pod 미생성) → 대기가 Job 레벨에서 발생.
    # 공정 비교 위해 kueue 정책은 created 를 Job 생성시각으로 치환(gate 방식은 pod≈Job 생성).
    job_created = {}
    if args.policy == "kueue":
        for j in batch.list_namespaced_job(NS).items:
            job_created[j.metadata.name] = j.metadata.creation_timestamp
    rows = []
    for p in v1.list_namespaced_pod(NS).items:
        created = p.metadata.creation_timestamp
        if args.policy == "kueue":
            jn = (p.metadata.labels or {}).get("job-name")
            created = job_created.get(jn, created)
        started = p.status.start_time
        finished = None
        if p.status.container_statuses:
            term = p.status.container_statuses[0].state.terminated
            if term:
                finished = term.finished_at
        if not created:
            continue
        queue = (started - created).total_seconds() if started else None
        jct = (finished - created).total_seconds() if finished else None
        rows.append([p.metadata.name, queue, jct])
    with open(f"{outdir}/jct.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["pod", "queue_sec", "jct_sec"])
        w.writerows(rows)

    qs = sorted(r[1] for r in rows if r[1] is not None)
    js = sorted(r[2] for r in rows if r[2] is not None)

    def pct(a, p):
        return a[min(len(a) - 1, int(len(a) * p))] if a else 0

    print(f"\n===== {args.run_id} (policy={args.policy}) =====")
    print(f"  jobs={len(rows)} 완료={len(js)}")
    print(f"  큐잉지연(s) p50={pct(qs,.5):.1f} p90={pct(qs,.9):.1f} max={qs[-1] if qs else 0:.1f}")
    print(f"  JCT(s)      p50={pct(js,.5):.1f} p90={pct(js,.9):.1f} max={js[-1] if js else 0:.1f}")
    print(f"  결과: {outdir}/", flush=True)


if __name__ == "__main__":
    main()
