# Paper element → artifact map

Every table and figure in the paper, with the script that produces it and the data it reads.
Section numbers follow the submitted manuscript.

| Paper element | Produced by | Reads | Shipped result |
|---|---|---|---|
| Table 1 (taxonomy) | — (literature survey) | — | — |
| Table 2 (per-job lifecycle overhead) | measured on B200×8, see `b200/` | K8s pod timestamps | `results/table2_overhead.md` |
| Table 3 (optimal α by distribution) | `alpha_search/` (C++ grid search) | `alpha_search/traces/all_*.csv` | values inlined in paper |
| Table 4 (main results, 256/512/1024) | `sim/run_sweep.py` → `sim/build_fixed_table.py` | `traces/sweep_trace_vc.csv` | `results/tables/table4_main_philly.csv` |
| Table 5 (grid-searched fixed α vs tuning-free) | `sim/ablation_alpha.py` | `traces/sweep_trace_vc.csv` | `results/tables/table5_alpha_grid.csv` |
| Table 6 (Philly / Helios / Alibaba) | `sim/rerun_le_cells.py` | `traces/helios_trace_sub.csv`, `traces/alibaba_trace.csv` | `results/tables/table6_*.csv` |
| Table 7 (placement composability) | `sim/placement_axis.py` | `traces/sweep_trace_vc.csv` | `results/tables/table7_placement.csv` |
| Fig. 1 (fragmentation and HOL blocking) | conceptual diagram | — | — |
| Fig. 2 (fairness cliff) | `sim/plot_cliff.py` | `results/tables/table4_main_philly.csv` | — |
| Fig. 3 (utilization–fairness trade-off) | `sim/plot_tradeoff.py` | `results/tables/table4_main_philly.csv` | — |
| Fig. 4 (HOL recovery across placements) | see note below | `results/tables/table7_placement.csv` | — |
| §VI-F (B200 real-cluster validation) | `b200/run_one.sh` → `b200/analyze.py` | live K8s cluster | `results/b200/` |

## Metric names

The code and the paper use different identifiers for the same quantity.

| Paper | Code column | Definition |
|---|---|---|
| Fairness | `fair_p1` | 1st percentile of the per-job order-fairness score `F_k` (Eq. 10) |
| Overtaken | `lt50_pct` | share of jobs with `F_k < 50` |
| MedianWait | `q_p50` | median queue wait, seconds |
| MaxWait | `q_max` | maximum queue wait, seconds |
| Utilization | `alloc_avg` | mean GPU allocation rate, percent |
| Gini | `gini_wait` | Gini coefficient of the wait-time distribution (Eq. 11) |
| TailRatio | `p99_p50` | 99th-percentile wait divided by the median |

`fair_mean` also appears in the raw summaries. It is the population mean of `F_k` and is **not**
the Fairness column of any table in the paper.

## Notes

- **Fig. 4** has no generating script in this repository. `sim/plot_newfigs.py` emits a related
  placement figure (`fig_placement.pdf`); the submitted figure was assembled from the same data.
- **Table 3** is the only element produced by the C++ core rather than the Python simulator. The
  two share the SFQA formulation but not an implementation.
