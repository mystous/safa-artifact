# SAFA — research artifact

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Traces: CC BY 4.0](https://img.shields.io/badge/Traces-CC_BY_4.0-lightgrey.svg)](traces/README.md)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776ab.svg)](requirements.txt)

Code, traces, and results for

> **SAFA: Resolving Head-of-Line Blocking in GPU Cluster Job Queues with Prediction-Free Reordering**
> Kyunam Cho, YoungHwan Jin, Heonchang Yu — manuscript under review

SAFA is a pre-placement reordering layer. It changes only the Order stage of a GPU cluster
scheduler and reads four quantities the scheduling instant already provides: queue position,
GPU demand, relative age, and per-server free slots. It predicts nothing, profiles nothing,
and solves nothing.

`docs/MAPPING.md` maps every table and figure in the paper to the script that produces it,
and translates between the paper's metric names and the column names in the code.

## Layout

```
sim/            discrete-event simulator, the 11 policies, and the reproduction scripts
traces/         the four job traces the paper replays
results/tables/ the aggregated CSVs behind Tables 4-7
results/b200/   real-cluster measurement logs and summary (Section VI-F)
b200/           Kubernetes controller used for the B200 measurement
alpha_search/   C++ grid search behind Table 3, with the eight synthetic distributions
docs/           paper-to-artifact map
```

## Traces

| File | Jobs | Span | Used for | Shipped |
|---|---:|---:|---|---|
| `sweep_trace.csv` | 111,586 | 136.9 d | Philly, Tables 4-7 | yes |
| `sweep_trace_vc.csv` | 111,586 | 136.9 d | same, with the 15 virtual clusters Kueue needs | yes |
| `helios_trace_sub.csv` | 62,735 | 186.3 d | Helios Venus, seed-42 50% subsample (Table 6) | yes |
| `alibaba_trace.csv` | 120,105 | 63.9 d | Alibaba PAI, seed-42 16.4% subsample (Table 6) | no |

Columns are `job_id, arrival_s, service_sec, gpu_count`.

Philly and Helios are CC BY 4.0 and are redistributed here with attribution. The Alibaba
repository declares no license, so we ship `sim/make_alibaba_trace.py` and the exact command
to rebuild that trace rather than the data. `traces/README.md` gives the download location,
the conversion command, and the checksum the result should match. Verify the shipped traces
with `cd traces && sha256sum -c SHA256SUMS`.

## Environment

Python 3.10 or later.

```bash
pip install -r requirements.txt     # numpy, matplotlib
```

The C++ core needs `g++` with C++20. Nothing else is required; the simulator has no solver
dependency.

## Verify the simulator first

The engine is checked against closed-form solutions for three analytically tractable cases,
a saturated D/D/1 queue, gang co-scheduling on a multi-GPU node, and the lifecycle-overhead
accounting.

```bash
cd sim && python3 fidelity_check.py
# OVERALL MAX ABS ERR = 0.00e+00  (PASS — within fp precision)
```

## Reproduce

Runtimes are for a single core. The sweeps parallelize across configurations.

### Table 4 — main results

```bash
cd sim
python3 run_sweep.py --gpus 256,512,1024 --kinds single \
    --policies fifo,sjf,las,kueue,easy,themis,lucid,sfqa,sfqa-auto
python3 build_fixed_table.py
```

A single low-load cell finishes in about two minutes and is the fastest way to confirm the
pipeline works:

```bash
python3 run_sweep.py --gpus 1024 --kinds single --policies fifo,sjf,sfqa-auto \
    --out /tmp/raw --summary-out /tmp/out
```

### Table 5 — grid-searched fixed α versus the tuning-free coefficient

```bash
cd sim && python3 ablation_alpha.py
```

Sweeps α over 16 points from 0.01 to 2.0 at each configuration and compares the best fixed
value against `alpha_eff`.

### Table 6 — generalization to Helios and Alibaba

Both traces contain jobs larger than the cluster under test. Those jobs are excluded so that
every policy is compared on one population; blocking policies would otherwise stall on jobs no
policy can place, and the populations would differ between policies.

```bash
cd sim
python3 rerun_le_cells.py --trace ../traces/helios_trace_sub.csv --cap 80  --gpu 80  --kind single \
    --policies fifo,sjf,las,kueue,easy,themis,fgd,lucid,sfqa,sfqa-auto \
    --outdir sweep_results/helios_le80/cmp80_single
python3 rerun_le_cells.py --trace ../traces/alibaba_trace.csv --cap 256 --gpu 256 --kind single \
    --policies fifo,sjf,las,kueue,easy,themis,fgd,lucid,sfqa,sfqa-auto \
    --outdir sweep_results/alibaba_le256/cmp256_single
```

Check that `n` is identical across policies in the resulting `summary_le.csv`: 62,069 for
Helios and 120,079 for Alibaba.

### Table 7 — placement composability

```bash
cd sim && python3 placement_axis.py
```

Runs each of the seven placement policies under FIFO and then under SAFA.

### Figures 2 and 3

```bash
cd sim
python3 plot_cliff.py      # fairness cliff
python3 plot_tradeoff.py   # utilization-fairness trade-off
```

### Table 3 — optimal α by distribution

```bash
cd alpha_search && make
./experiment_gpu traces/all_normal_gen.csv server.csv config.set
```

Repeat for each of the eight distributions. This is the only experiment that uses the C++ core
rather than the Python simulator.

## Real-cluster measurement (Section VI-F)

`b200/` holds the controller that produced the B200×8 measurement. It gates pending pods and
releases them in policy order, leaving binding to the stock kube-scheduler.

These scripts carry absolute paths from the measurement host (`/raid/squad`, `/home/mystous`)
and a kubeconfig location. They are kept as they ran rather than generalized, since the
measurement cannot be reproduced without an equivalent cluster. Edit the paths at the top of
`run_one.sh` and `run_experiment.py` before use.

Measured output is in `results/b200/`: `b200_burst_summary.csv` for the six runs and
`runs/` for the per-run pod logs.

## What is not included

Per-job raw dumps from the sweeps total roughly 350 MB and are omitted. Every number in the
paper is reproducible from the traces and scripts here; the dumps only shorten re-analysis.

Baselines are our implementations. For Tiresias, Kueue, FGD, KAI, and Lucid we cross-checked
against the authors' released code, and Section VI-B of the paper states where our version departs
from the original.

## License

Code in this repository is Apache-2.0; see `LICENSE`.

The traces are not ours and carry their own terms. Philly and Helios are CC BY 4.0, and the
required attributions are the citations in `traces/README.md`. The Alibaba trace is not
redistributed here for the reason given in that file.

## Contact

Kyunam Cho, mystous@korea.ac.kr. Corresponding author: Heonchang Yu, yuhc@korea.ac.kr.
