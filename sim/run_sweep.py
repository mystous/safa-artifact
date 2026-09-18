"""부하 스윕 재현 러너 — 256/512/1024 GPU × 단일/이종 × 전 정책(FGD 포함).

이 스크립트는 부하 스윕을 완전 재현 가능하게 만든다(원 스윕은 커맨드가 커밋되지 않았음).
- 트레이스: sim/sweep_trace.csv (job_id,arrival_s,service_sec,gpu_count). Philly 전체 111,586잡,
  JCT 48h 클램프. cmp*/fifo_jobs.csv에서 복원한 정규본(단일/이종 전 구성이 동일 트레이스 공유 검증).
- 노드 스펙(명시·고정):
    single : b200:8 × (gpu/8)
    hetero : b200/h100/a100 균등 3분할(가능한 한 균등). 예) 512=22/21/21 노드.
  단일 구성은 커밋된 결과와 일치 검증됨(fifo q_p50 1216806 ≈ 1216821.5, 0.1s 덤프 반올림차).
  이종 원본 믹스는 커밋되지 않아 균등 3분할로 재정의 → 전 정책을 함께 재실행하여 내부 일관성 보장.
- 정책: 빠른 엔진 정책(fifo/sjf/las/kueue/easy/themis/sfqa/sfqa-auto) + FGD + lucid.
  sia는 계산비용(256 고부하 ~2h)으로 재실행 제외 — 커밋된 결과를 분석에서 그대로 사용.

출력(구성별 <out>/cmp<gpu>_<kind>/):
  summary.csv, <pol>_jobs.csv, <pol>_alloc.csv  (analyze_sweep.py가 소비)

사용:
  python3 sim/run_sweep.py                      # 전 구성·전 정책
  python3 sim/run_sweep.py --gpus 512 --kinds hetero --policies fgd   # 부분
"""
import argparse
import csv
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "squad_ctrl"))
sys.path.insert(0, os.path.join(ROOT, "k8s_replay"))

from engine import Job, Node, Overheads, Simulator   # noqa: E402
import policies as P                                   # noqa: E402
from lucid_sim import LJob, LucidSim                   # noqa: E402

FAST_POLS = ["fifo", "sjf", "las", "kueue", "easy", "themis", "sfqa", "sfqa-auto", "fgd"]


def load_trace(path):
    """트레이스 로드. vc 컬럼이 있으면 읽고, 없으면 'default'(하위호환).
    반환: (job_id, arrival_s, service_sec, gpu_count, vc) 5-튜플."""
    out = []
    for r in csv.DictReader(open(path)):
        vc = r.get("vc") or "default"
        out.append((r["job_id"], float(r["arrival_s"]), max(1.0, float(r["service_sec"])),
                    int(r["gpu_count"]), vc))
    return out


def build_nodes(gpu, kind):
    """single=b200 전부, hetero=b200/h100/a100 균등 3분할(노드 단위 8 GPU)."""
    n_nodes = gpu // 8
    if kind == "single":
        return [Node(name=f"b200-{i}", gpu_type="b200", total=8) for i in range(n_nodes)]
    # hetero: 가능한 한 균등 3분할
    base = n_nodes // 3
    rem = n_nodes - base * 3
    counts = [base + (1 if i < rem else 0) for i in range(3)]  # b200 ≥ h100 ≥ a100
    types = ["b200", "h100", "a100"]
    nodes, idx = [], 0
    for t, c in zip(types, counts):
        for _ in range(c):
            nodes.append(Node(name=f"{t}-{idx}", gpu_type=t, total=8)); idx += 1
    return nodes


def stats(qs, ss, gs):
    qss = sorted(qs)
    S = sorted(max((q + s) / max(s, 10), 1.0) for q, s in zip(qs, ss))

    def p(a, x):
        return a[min(len(a) - 1, int(len(a) * x))] if a else 0
    return dict(n=len(qss), q_p50=p(qss, .5), q_p90=p(qss, .9), q_p99=p(qss, .99),
                q_max=qss[-1] if qss else 0, sd_p50=p(S, .5), sd_p90=p(S, .9),
                sd_max=S[-1] if S else 0)


def run_policy(name, trace, nodes_proto, ovh):
    nodes = [Node(name=n.name, gpu_type=n.gpu_type, total=n.total) for n in nodes_proto]
    if name == "lucid":
        import random
        rng = random.Random(42)
        jobs = [LJob(id=i, arrival=a, duration=d, gpu_count=g,
                     util=min(0.99, max(0.05, rng.gauss(0.6, 0.2)))) for i, a, d, g, vc in trace]
        sim = LucidSim(jobs, nodes, ovh, gss=2); r = sim.run()
        jr = [(j.id, j.arrival, j.place_time, j.place_time - j.arrival,
               max(j.finish_time - j.place_time, 0.1), j.gpu_count)
              for j in sim.finished if j.place_time >= 0]
        alloc = r.get("alloc_series", [])
    else:
        pol = P.make(name)
        if name == "fgd":
            pol.set_dist([g for _, _, _, g, _ in trace])
        jobs = [Job(id=i, arrival=a, duration=d, gpu_count=g, gpu_type="any", vc=vc)
                for i, a, d, g, vc in trace]
        sim = Simulator(jobs, nodes, pol, overheads=ovh); r = sim.run()
        jr = [(j.id, j.arrival, j.place_time, j.queue_delay, j.duration, j.gpu_count)
              for j in sim.finished if j.queue_delay is not None]
        alloc = r.get("alloc_series", [])
    qs = [x[3] for x in jr]; ss = [x[4] for x in jr]; gs = [x[5] for x in jr]
    st = stats(qs, ss, gs); st["policy"] = name
    st["alloc_max"] = r.get("alloc_max", 0.0); st["alloc_avg"] = r.get("alloc_avg", 0.0)
    return st, jr, alloc


def dump(outdir, name, jr, alloc):
    os.makedirs(outdir, exist_ok=True)
    with open(f"{outdir}/{name}_jobs.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["job_id", "arrival_s", "start_s", "queue_sec", "service_sec", "gpu_count"])
        for jid, arr, start, q, s, g in jr:
            w.writerow([jid, round(arr, 1), round(start, 1), round(q, 1), round(s, 1), g])
    with open(f"{outdir}/{name}_alloc.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["time_s", "used_gpu", "total_gpu", "alloc_pct"])
        for t, u, tot in alloc:
            w.writerow([round(t, 1), u, tot, round(u / tot * 100, 2) if tot else 0])


def main():
    ap = argparse.ArgumentParser()
    # 기본 트레이스: vc 버전이 있으면 사용(Kueue per-VC 쿼타), 없으면 4컬럼 트레이스(하위호환).
    _traces = os.path.join(os.path.dirname(HERE), "traces")
    _vc_trace = os.path.join(_traces, "sweep_trace_vc.csv")
    _def_trace = _vc_trace if os.path.exists(_vc_trace) else os.path.join(_traces, "sweep_trace.csv")
    ap.add_argument("--trace", default=_def_trace)
    ap.add_argument("--out", default=os.path.join(HERE, "sweep_results", "raw"))
    ap.add_argument("--summary-out", default=os.path.join(HERE, "sweep_results"))
    ap.add_argument("--gpus", default="256,512,1024")
    ap.add_argument("--kinds", default="single,hetero")
    ap.add_argument("--policies", default=",".join(FAST_POLS + ["lucid"]))
    ap.add_argument("--no-overhead", action="store_true")
    a = ap.parse_args()

    trace = load_trace(a.trace)
    gpus = [int(x) for x in a.gpus.split(",")]
    kinds = a.kinds.split(",")
    pols = a.policies.split(",")
    ovh = Overheads(enabled=not a.no_overhead)
    print(f"trace n={len(trace)}, gpus={gpus}, kinds={kinds}, policies={pols}", flush=True)

    for gpu in gpus:
        for kind in kinds:
            nodes = build_nodes(gpu, kind)
            comp = {}
            for n in nodes:
                comp[n.gpu_type] = comp.get(n.gpu_type, 0) + 1
            d = f"cmp{gpu}_{kind}"
            outdir = os.path.join(a.out, d)
            print(f"\n== {d}  nodes={comp} ({gpu} GPU) ==", flush=True)
            # 기존 summary 로드(있으면) → sia 등 미실행 정책 보존
            sfile = os.path.join(a.summary_out, d, "summary.csv")
            existing = {}
            if os.path.exists(sfile):
                for r in csv.DictReader(open(sfile)):
                    existing[r["policy"]] = r
            results = {}
            for name in pols:
                t0 = time.time()
                st, jr, alloc = run_policy(name, trace, nodes, ovh)
                dump(outdir, name, jr, alloc)
                results[name] = st
                print(f"  ✓ {name:11} q p50/p90/max={st['q_p50']:.0f}/{st['q_p90']:.0f}/{st['q_max']:.0f}"
                      f"  alloc avg={st['alloc_avg']:.1f}%  ({time.time()-t0:.1f}s)", flush=True)
            # summary.csv 갱신: 새 결과 + 기존(미실행) 정책 보존
            fields = ["policy", "n", "q_p50", "q_p90", "q_p99", "q_max",
                      "sd_p50", "sd_p90", "sd_max", "alloc_max", "alloc_avg"]
            os.makedirs(os.path.join(a.summary_out, d), exist_ok=True)
            order = ["fifo", "sjf", "las", "kueue", "easy", "themis", "sfqa", "sfqa-auto", "fgd", "lucid", "sia"]
            with open(sfile, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
                for name in order:
                    if name in results:
                        w.writerow({k: results[name].get(k, "") for k in fields})
                    elif name in existing:
                        w.writerow({k: existing[name].get(k, "") for k in fields})
            print(f"  → {sfile}", flush=True)


if __name__ == "__main__":
    main()
