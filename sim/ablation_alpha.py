"""A1 — Ablation: 워크로드별 최적 고정-α vs 무튜닝 SAFA(sfqa-auto).

6개 구성(single/hetero × 256/512/1024) 각각에서 고정 SFQA를 α 그리드로 스윕하여
'그 구성에서 q_p50와 fair_p1의 균형이 가장 좋은 최적 고정-α'를 찾고, 무튜닝 sfqa-auto와
동일 구성에서 비교한다.

목적함수(명시): "공정성 하한(fair_p1)을 sfqa-auto 수준 이상으로 지키면서 q_p50를 최소화."
  구체: 각 구성에서 sfqa-auto의 fair_p1을 기준선 p1*로 둔다. 고정-α 후보 중
        fair_p1 >= p1* 를 만족하는 것들 가운데 q_p50 최소인 α를 '제약-최적 고정-α'로 택한다.
  보조: 그런 α가 없으면(어떤 고정-α도 auto의 p1에 못 미치면) "auto 우위"로 기록하고,
        참고로 fair_p1 최대인 α(=고정으로 도달 가능한 최선의 공정성)를 함께 보고한다.

병렬: (구성, α) 조합을 프로세스풀로 분산. 각 워커가 q_p50·fair_p1·lt50 계산.
출력: sweep_results/ablation/alpha_grid.csv  (구성별 전 α점)
"""
import csv
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for p in (HERE, os.path.join(ROOT, "squad_ctrl"), os.path.join(ROOT, "k8s_replay")):
    sys.path.insert(0, p)

from engine import Job, Node, Overheads, Simulator   # noqa: E402
import policies as P                                   # noqa: E402
from order_fairness import per_job_score               # noqa: E402

TRACE = os.path.join(HERE, "sweep_trace.csv")
GPUS = [256, 512, 1024]
KINDS = ["single", "hetero"]
# α 그리드: 0.01~2.0, 로그+선형 혼합 16점
ALPHAS = [0.01, 0.02, 0.05, 0.1, 0.13889, 0.2, 0.3, 0.5,
          0.7, 0.9, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]


def load_trace():
    out = []
    for r in csv.DictReader(open(TRACE)):
        out.append((r["job_id"], float(r["arrival_s"]),
                    max(1.0, float(r["service_sec"])), int(r["gpu_count"])))
    return out


def build_nodes(gpu, kind):
    n_nodes = gpu // 8
    if kind == "single":
        return [("b200", 8) for _ in range(n_nodes)]
    base = n_nodes // 3
    rem = n_nodes - base * 3
    counts = [base + (1 if i < rem else 0) for i in range(3)]
    types = ["b200", "h100", "a100"]
    out = []
    for t, c in zip(types, counts):
        out += [(t, 8)] * c
    return out


def pctl(a, x):
    a = sorted(a)
    return a[min(len(a) - 1, int(len(a) * x))] if a else 0.0


def metrics_from_jr(jr):
    """jr: [(id, arrival, start, queue, dur, gpu)] → q_p50, fair_p1, lt50_pct."""
    qs = [x[3] for x in jr]
    jb = [(x[1], x[2], 0) for x in jr]   # (arrival, start, finish-unused)
    sc = sorted(per_job_score(jb))
    n = len(sc)
    fair_p1 = sc[int(n * .01)] if n else 0.0
    lt50 = 100.0 * sum(1 for x in sc if x < 50) / n if n else 0.0
    return pctl(qs, .5), fair_p1, lt50


_TRACE = None


def _get_trace():
    global _TRACE
    if _TRACE is None:
        _TRACE = load_trace()
    return _TRACE


def run_one(gpu, kind, policy_name, alpha=None):
    trace = _get_trace()
    nodes = [Node(name=f"{t}-{i}", gpu_type=t, total=tot)
             for i, (t, tot) in enumerate(build_nodes(gpu, kind))]
    if policy_name == "sfqa":
        pol = P.SFQA(alpha=alpha, beta=100.0)
    elif policy_name == "sfqa-auto":
        pol = P.SFQAAuto()
    else:
        raise ValueError(policy_name)
    jobs = [Job(id=i, arrival=a, duration=d, gpu_count=g, gpu_type="any")
            for i, a, d, g in trace]
    sim = Simulator(jobs, nodes, pol, overheads=Overheads(enabled=True))
    sim.run()
    jr = [(j.id, j.arrival, j.place_time, j.queue_delay, j.duration, j.gpu_count)
          for j in sim.finished if j.queue_delay is not None]
    q50, fp1, lt50 = metrics_from_jr(jr)
    return dict(gpu=gpu, kind=kind, policy=policy_name,
                alpha=alpha if alpha is not None else "",
                q_p50=q50, fair_p1=fp1, lt50_pct=lt50, n=len(jr))


def _task(args):
    return run_one(*args)


def main():
    tasks = []
    for gpu in GPUS:
        for kind in KINDS:
            for a in ALPHAS:
                tasks.append((gpu, kind, "sfqa", a))
            tasks.append((gpu, kind, "sfqa-auto", None))
    print(f"total tasks: {len(tasks)}  (workers up to {min(20, len(tasks))})", flush=True)
    results = []
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=20) as ex:
        futs = {ex.submit(_task, t): t for t in tasks}
        done = 0
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            done += 1
            print(f"  [{done}/{len(tasks)}] {r['gpu']} {r['kind']} {r['policy']} "
                  f"a={r['alpha']}  q50={r['q_p50']:.0f} p1={r['fair_p1']:.1f} "
                  f"lt50={r['lt50_pct']:.2f}  ({time.time()-t0:.0f}s)", flush=True)

    outdir = os.path.join(HERE, "sweep_results", "ablation")
    os.makedirs(outdir, exist_ok=True)
    out = os.path.join(outdir, "alpha_grid.csv")
    results.sort(key=lambda r: (r["gpu"], r["kind"], r["policy"], r["alpha"] if r["alpha"] != "" else -1))
    with open(out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gpu", "kind", "policy", "alpha", "q_p50", "fair_p1", "lt50_pct", "n"])
        for r in results:
            w.writerow([r["gpu"], r["kind"], r["policy"], r["alpha"],
                        round(r["q_p50"]), round(r["fair_p1"], 2),
                        round(r["lt50_pct"], 3), r["n"]])
    print(f"\n→ {out}  ({time.time()-t0:.0f}s total)", flush=True)


if __name__ == "__main__":
    main()
