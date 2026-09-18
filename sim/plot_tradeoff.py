#!/usr/bin/env python3
"""Figure 3 (이용률×공정성 트레이드오프) — 4사분면 배경 산점도.
사분면: 공정성(50 기준) × 활용도(94 기준, x축 정중앙). baseline 정책 vs SAFA.
데이터: sim/sweep_results/fixed_sweep_table.csv (256 single)."""
import csv
import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
matplotlib.rcParams.update({"pdf.fonttype": 42, "ps.fonttype": 42})

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
r = {x['policy']: x for x in csv.DictReader(open(os.path.join(ROOT, "sim/sweep_results/fixed_sweep_table.csv")))
     if x['gpu'] == '256' and x['kind'] == 'single'}


def pt(p):
    return float(r[p]['alloc_avg']), float(r[p]['fair_p1'])


STY = [("fifo", "FIFO", "black", "s", 170),
       ("sjf", "SJF", "tab:orange", "v", 110),
       ("las", "LAS", "tab:green", "^", 110),
       ("kueue", "Kueue", "tab:purple", "P", 120),
       ("easy", "EASY", "tab:brown", "X", 110),
       ("themis", "Themis", "tab:pink", "d", 110),
       ("lucid", "Lucid", "tab:olive", "<", 110),
       ("sfqa-auto", "SAFA", "#1a4fd0", "*", 260)]

XHI = 100.4
YLO, YHI = -5, 105
XM, YM = 94.0, 50.0        # 사분면 분할선(활용도 94, 공정성 50)
XLO = 2 * XM - XHI          # 분할선이 x축 정중앙에 오도록 시작값 조정 → 87.6

fig, ax = plt.subplots(figsize=(7.0, 5.2))

# 4사분면 배경(흐리게)
ax.add_patch(plt.Rectangle((XM, YM), XHI - XM, YHI - YM, color="#2ca02c", alpha=0.10, zorder=0))
ax.add_patch(plt.Rectangle((XLO, YM), XM - XLO, YHI - YM, color="#f0b429", alpha=0.10, zorder=0))
ax.add_patch(plt.Rectangle((XM, YLO), XHI - XM, YM - YLO, color="#d64545", alpha=0.10, zorder=0))
ax.add_patch(plt.Rectangle((XLO, YLO), XM - XLO, YM - YLO, color="0.5", alpha=0.10, zorder=0))
ax.axvline(XM, color="0.6", lw=0.8, alpha=0.6, zorder=1)
ax.axhline(YM, color="0.6", lw=0.8, alpha=0.6, zorder=1)

# 사분면 설명(코너 라벨)
ax.text(XHI - 0.2, YHI - 3, "IDEAL: fair + high util", ha="right", va="top",
        color="darkgreen", fontsize=9.5, fontweight="bold", zorder=2)
ax.text(XLO + 0.2, YM + 3, "fair, but low util (HOL waste)", ha="left", va="bottom",
        color="#8a6d00", fontsize=9.5, fontweight="bold", zorder=2)
ax.text(XHI - 0.2, YM - 3, "baselines: high util, but starving (Fairness=0)", ha="right", va="top",
        color="darkred", fontsize=9.5, fontweight="bold", zorder=2)
ax.text(XLO + 0.2, YM - 3, "low util + starving", ha="left", va="top",
        color="0.4", fontsize=9.5, fontweight="bold", zorder=2)

handles = []
for p, nm, c, m, s in STY:
    u, f = pt(p)
    ec = "black" if p in ("fifo", "sfqa-auto") else "0.25"
    z = 8 if p == "sfqa-auto" else (6 if p == "fifo" else 4)
    ax.scatter(u, f, c=c, s=s, marker=m, edgecolors=ec, linewidths=.8, zorder=z)
    handles.append(Line2D([0], [0], marker=m, color="w", markerfacecolor=c, markeredgecolor=ec,
                          markersize=(11 if p == "sfqa-auto" else 9), label=nm, linestyle="none"))

ax.set_xlabel("Utilization (%)   —   HOL recovered →", fontsize=11)
ax.set_ylabel("Fairness   —   no starvation ↑", fontsize=11)
ax.set_xlim(XLO, XHI)
ax.set_ylim(YLO, YHI)
ax.grid(alpha=0.2)
fig.legend(handles=handles, loc="lower center", bbox_to_anchor=(0.54, -0.02),
           ncol=8, fontsize=8.5, framealpha=0.9, columnspacing=0.8, handletextpad=0.3)
fig.subplots_adjust(left=0.10, right=0.98, top=0.97, bottom=0.16)
fig.savefig(os.path.join(ROOT, "paper/Pic/Fig_tradeoff.pdf"), bbox_inches="tight")
print("Fig_tradeoff: 4사분면 배경 + 사분면 설명 라벨")
