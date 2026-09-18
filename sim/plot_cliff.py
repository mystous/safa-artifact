#!/usr/bin/env python3
"""Figure 2 (부하--공정성 절벽) 생성 — legend는 그래프 아래(외부) 배치.
데이터: sim/sweep_results/fixed_sweep_table.csv (single, fair_p1 = Fairness)."""
import csv
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
matplotlib.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42})

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
r = {(x['gpu'], x['kind'], x['policy']): float(x['fair_p1'])
     for x in csv.DictReader(open(os.path.join(ROOT, "sim/sweep_results/fixed_sweep_table.csv")))}
STY = [("fifo", "FIFO", "black", "s", "-", 1.6), ("sjf", "SJF", "tab:orange", "v", "-", 1.1),
       ("las", "LAS", "tab:green", "^", "-", 1.1), ("kueue", "Kueue", "tab:purple", "P", "-", 1.1),
       ("easy", "EASY", "tab:brown", "X", "-", 1.1), ("themis", "Themis", "tab:pink", "d", "-", 1.1),
       ("lucid", "Lucid", "tab:olive", "<", "-", 1.1), ("sfqa", "SAFA(fixed α)", "#5aa0ef", "s", "--", 2.0),
       ("sfqa-auto", "SAFA", "#1a4fd0", "o", "-", 3.0)]
xs = [0, 1, 2]
gpus = ["1024", "512", "256"]
plt.rcParams.update({"font.size": 10})
fig, a = plt.subplots(figsize=(5.2, 4.2))
for pol, name, c, m, ls, lw in STY:
    ys = [r.get((g, "single", pol), 0) for g in gpus]
    a.plot(xs, ys, marker=m, ls=ls, color=c, lw=lw, ms=(9 if pol == "sfqa-auto" else 5),
           zorder=6 if pol == "sfqa-auto" else (5 if pol == "sfqa" else 3), label=name)
a.axhspan(0, 5, color="red", alpha=0.06)
a.set_ylim(-3, 106)
a.grid(alpha=0.3)
a.set_ylabel("Fairness")
a.set_xlim(-0.15, 2.15)
a.set_xticks(xs)
a.set_xticklabels(["0.9×\n1024", "1.8×\n512", "3.6×\n256"])
a.set_xlabel("load (overload →)")
# legend를 그래프 아래(축 외부)로 — 그래프를 가리지 않음
a.legend(loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=5,
         fontsize=8, framealpha=0.9, columnspacing=1.0, handletextpad=0.5)
fig.tight_layout()
fig.savefig(os.path.join(ROOT, "paper/Pic/Fig_cliff.pdf"), bbox_inches="tight")
print("Fig_cliff: legend below graph, ok")
