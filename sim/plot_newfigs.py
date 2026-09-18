#!/usr/bin/env python3
"""새 실험(ablation grid / sensitivity / Helios / placement) 결과 그래프 생성.
출력: paper/Pic/fig_ablation_grid.pdf, fig_sensitivity.pdf, fig_helios.pdf, fig_placement.pdf
라벨은 폰트 안전을 위해 영문."""
import csv, os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
SR = os.path.join(HERE, "sweep_results")
OUT = os.path.abspath(os.path.join(HERE, "..", "paper", "Pic"))
os.makedirs(OUT, exist_ok=True)

DISP = {"fifo": "FIFO", "sjf": "SJF", "las": "LAS", "kueue": "Kueue", "easy": "EASY",
        "themis": "Themis", "fgd": "FGD", "sfqa": "SAFA-fix", "sfqa-auto": "SAFA",
        "lucid": "Lucid"}
ORDER = ["fifo", "sjf", "las", "kueue", "easy", "themis", "fgd", "lucid", "sfqa", "sfqa-auto"]
plt.rcParams.update({"font.size": 9, "axes.grid": True, "grid.alpha": 0.3,
                     "figure.dpi": 150, "savefig.bbox": "tight"})


def load(path):
    with open(path) as f:
        return list(csv.DictReader(f))


# ── Fig 1: ablation α-grid — fixed-α p1 vs α, with tuning-free SAFA line ──────
def fig_ablation_grid():
    rows = load(os.path.join(SR, "ablation", "alpha_grid.csv"))
    configs = [("single", 256), ("single", 512), ("single", 1024),
               ("hetero", 256), ("hetero", 512), ("hetero", 1024)]
    fig, axes = plt.subplots(2, 3, figsize=(7.1, 3.8), sharex=True)
    for ax, (kind, gpu) in zip(axes.flat, configs):
        fixed = sorted([r for r in rows if r["kind"] == kind and int(r["gpu"]) == gpu
                        and r["policy"] == "sfqa" and r["alpha"]],
                       key=lambda r: float(r["alpha"]))
        xs = [float(r["alpha"]) for r in fixed]
        ys = [float(r["fair_p1"]) for r in fixed]
        auto = [r for r in rows if r["kind"] == kind and int(r["gpu"]) == gpu
                and r["policy"] == "sfqa-auto"]
        ax.plot(xs, ys, "o-", color="#d9534f", ms=2.5, lw=1.0, label="fixed $\\alpha$")
        if auto:
            ya = float(auto[0]["fair_p1"])
            ax.axhline(ya, ls="--", color="#2c7fb8", lw=1.3, label="SAFA (tuning-free)")
            if ya - max(ys) > 2:
                ax.annotate("", xy=(xs[len(xs)//2], ya), xytext=(xs[len(xs)//2], max(ys)),
                            arrowprops=dict(arrowstyle="<->", color="gray", lw=0.7))
        ax.set_xscale("log")
        ax.set_title(f"{kind} {gpu} GPU", fontsize=8)
        ax.set_ylim(-3, 105)
    for ax in axes[1]:
        ax.set_xlabel("fixed age-weight $\\alpha$ (log)")
    for ax in axes[:, 0]:
        ax.set_ylabel("order-fairness $p_1$")
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.tight_layout()
    fig.legend(h, l, loc="lower center", bbox_to_anchor=(0.5, 1.0),
               ncol=2, fontsize=8, frameon=False)
    fig.savefig(os.path.join(OUT, "fig_ablation_grid.pdf"))
    plt.close(fig)
    print("wrote fig_ablation_grid.pdf")


# ── Fig 2: sensitivity ±50% — p1 per policy, range across perturbations ───────
def fig_sensitivity():
    rows = [r for r in load(os.path.join(SR, "sensitivity", "sensitivity_full.csv"))
            if r["kind"] == "hetero" and int(r["gpu"]) == 512]
    pols = [p for p in ORDER if any(r["policy"] == p for r in rows)]
    base, lo, hi = [], [], []
    for p in pols:
        vs = [float(r["fair_p1"]) for r in rows if r["policy"] == p]
        b = [float(r["fair_p1"]) for r in rows if r["policy"] == p and r["scenario"] == "baseline"]
        base.append(b[0] if b else sum(vs)/len(vs)); lo.append(min(vs)); hi.append(max(vs))
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    xs = range(len(pols))
    colors = ["#2c7fb8" if p == "sfqa-auto" else "#7bccc4" if p == "sfqa"
              else "#bdbdbd" for p in pols]
    ax.bar(xs, base, color=colors, width=0.7,
           yerr=[[b-l for b, l in zip(base, lo)], [h-b for h, b in zip(hi, base)]],
           capsize=2, ecolor="#d9534f", error_kw={"lw": 0.8})
    ax.set_xticks(list(xs)); ax.set_xticklabels([DISP[p] for p in pols], rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("order-fairness $p_1$"); ax.set_ylim(0, 105)
    ax.set_title("512 hetero", fontsize=8)
    fig.savefig(os.path.join(OUT, "fig_sensitivity.pdf"))
    plt.close(fig)
    print("wrote fig_sensitivity.pdf")


# ── Fig 3: Helios — speed (q_p50) vs starvation (lt50%) trade-off, overload ────
def fig_helios():
    # 동일 모집단(62,069) 정정 후 데이터 — 표 tab:helios와 일치(모집단 버그 정정 전 helios/는 쓰지 않음).
    rows = [r for r in load(os.path.join(SR, "helios_le80", "sweep_table.csv"))
            if r["policy"] in DISP]
    fig, ax = plt.subplots(figsize=(3.7, 3.0))
    # x = lt50(추월당한 작업 비율, 낮을수록 공정 ←), y = fair(평균 순서 공정성, 높을수록 공정 ↑).
    groups = {}
    for r in rows:
        key = (round(float(r["lt50"]), 2), round(float(r["fair"]), 1))
        groups.setdefault(key, []).append(r["policy"])
    for (x, y), pols_here in groups.items():
        lead = "sfqa-auto" if "sfqa-auto" in pols_here else ("fifo" if "fifo" in pols_here else pols_here[0])
        col = ("tab:blue" if lead == "sfqa-auto" else "tab:cyan" if lead == "sfqa"
               else "black" if lead == "fifo" else "0.55")
        mk = "*" if lead == "sfqa-auto" else ("s" if lead == "fifo" else "D" if lead == "sfqa" else "o")
        sz = 240 if lead == "sfqa-auto" else (90 if lead in ("fifo", "sfqa") else 45)
        ax.scatter(x, y, s=sz, marker=mk, color=col, zorder=3, edgecolor="k", linewidth=0.6)
        lab = "/".join(DISP[p] for p in pols_here)
        # x축 반전(오른쪽=공정): 공정한 점(낮은 lt50, 우측)은 라벨을 왼쪽으로, 불공정 점은 오른쪽으로.
        if x > 15:            # 좌측(불공정): 라벨 오른쪽
            ax.annotate(lab, (x, y), textcoords="offset points", xytext=(8, 6), fontsize=6.8, ha="left")
        elif x < 5:           # 우측(공정): 라벨 왼쪽, FIFO/SAFA는 상하로 분리
            dy = 7 if lead == "fifo" else (-9 if lead == "sfqa-auto" else -2)
            ax.annotate(lab, (x, y), textcoords="offset points", xytext=(-8, dy),
                        fontsize=7.2 if lead in ("fifo", "sfqa-auto") else 6.8, ha="right",
                        fontweight="bold" if lead in ("fifo", "sfqa-auto") else "normal")
        else:                 # 중앙
            ax.annotate(lab, (x, y), textcoords="offset points", xytext=(8, 5), fontsize=6.8, ha="left")
    ax.set_xlabel("overtaken-jobs share (\\%) $-$ fairer $\\rightarrow$", fontsize=8)
    ax.set_ylabel("mean order-fairness $-$ fairer $\\uparrow$", fontsize=8)
    ax.set_title("Helios (independent trace): top-right $=$ fairest", fontsize=8.5)
    ax.set_xlim(-2.5, 25); ax.set_ylim(73, 103)
    ax.invert_xaxis()  # 오른쪽이 더 좋은(공정한) 수치 — lt50 낮을수록 우측
    ax.grid(alpha=0.3)
    ax.axhspan(96, 103, xmin=0.84, xmax=1.0, color="green", alpha=0.07, zorder=0)
    ax.annotate("ideal", (-2.3, 102.5), fontsize=7, color="green", ha="right", va="top")
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, "fig_helios.pdf"))
    plt.close(fig)
    print("wrote fig_helios.pdf")


# ── Fig 4: placement-agnostic — SAFA p1 across 4 core placements ──────────────
def fig_placement():
    rows = load(os.path.join(SR, "placement", "placement_table.csv"))
    placements = ["mostallocated", "compact", "round_robin", "mcts", "fgd"]
    plabel = {"mostallocated": "most-alloc", "compact": "compact",
              "round_robin": "round-robin", "mcts": "MCTS", "fgd": "FGD"}
    configs = [("256:single", "256 sgl"), ("256:hetero", "256 het"),
               ("512:single", "512 sgl"), ("512:hetero", "512 het")]
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    w = 0.2
    for ci, (cfg, clab) in enumerate(configs):
        ys = []
        for pl in placements:
            m = [r for r in rows if r["config"] == cfg and r["placement"] == pl
                 and r["policy"] == "sfqa-auto"]
            ys.append(float(m[0]["fair_p1"]) if m else 0)
        xs = [j + ci*w for j in range(len(placements))]
        ax.bar(xs, ys, width=w, label=clab)
    ax.axhline(50, ls=":", color="gray", lw=0.8)
    ax.text(0.02, 51, "$p_1$=50", fontsize=6.5, color="gray")
    ax.set_xticks([j + 1.5*w for j in range(len(placements))])
    ax.set_xticklabels([plabel[p] for p in placements], rotation=20, ha="right", fontsize=7)
    ax.set_ylabel("SAFA order-fairness $p_1$"); ax.set_ylim(0, 78)
    ax.set_title("SAFA $p_1$ by core placement", fontsize=8)
    ax.legend(fontsize=6.5, ncol=4, loc="upper center", columnspacing=0.8)
    fig.savefig(os.path.join(OUT, "fig_placement.pdf"))
    plt.close(fig)
    print("wrote fig_placement.pdf")


if __name__ == "__main__":
    fig_ablation_grid()
    fig_sensitivity()
    fig_helios()
    fig_placement()
    print("done →", OUT)
