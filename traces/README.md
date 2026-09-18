# Traces

Three public traces back the results. Two are redistributed here under their original
license; the third must be downloaded and converted because its owner declares no license.

| File | Source | Original license | Shipped here |
|---|---|---|---|
| `sweep_trace.csv`, `sweep_trace_vc.csv` | Philly, [msr-fiddle/philly-traces](https://github.com/msr-fiddle/philly-traces) | CC BY 4.0 | yes |
| `helios_trace_sub.csv` | Helios Venus, [S-Lab-System-Group/HeliosData](https://github.com/S-Lab-System-Group/HeliosData) | CC BY 4.0 | yes |
| `alibaba_trace.csv` | Alibaba PAI, [alibaba/clusterdata](https://github.com/alibaba/clusterdata) | none declared | **no — build it yourself** |

Columns are `job_id, arrival_s, service_sec, gpu_count`.

## Scope of use

Using a trace and redistributing it are separate acts, and the three sources grant them
differently. What each permits, and what this repository therefore does:

| | Research use | Publishing results | Redistributing the data |
|---|---|---|---|
| Philly (CC BY 4.0) | yes | yes | yes, with attribution — **shipped here** |
| Helios (CC BY 4.0) | yes | yes | yes, with attribution — **shipped here** |
| Alibaba (no license) | yes, stated by the owner | yes | not granted — **not shipped** |

### Alibaba: use is permitted, redistribution is not addressed

The `alibaba/clusterdata` repository carries no LICENSE file, but its README grants research
use in plain terms:

> We encourage anyone to use the traces for study or research purposes.
>
> You may use trace however you want as long as it is for reseach or study purpose.

Running experiments on the trace and publishing the resulting measurements is therefore
squarely within what the owner invites. What the README does not address is redistribution,
and no license file supplies it. Because permission to use and permission to distribute are
distinct, we treat the absence as withholding the latter and ship the conversion script rather
than the data.

The same README asks to be told when a publication using the trace appears, and we will do so.

### Philly and Helios

Both are CC BY 4.0, which permits redistribution of the data and of derived works provided the
source is attributed. The attributions are the citations at the end of this file. The files
here are derived: converted to a four-column schema, clamped at 48 h of service time, and in
the Helios case subsampled.

### What you may do with this repository

The code is Apache-2.0 (see the root `LICENSE`). The traces are not ours to relicense and keep
the terms above, so the Apache grant covers the code only. If you redistribute the Philly or
Helios files, carry the attributions with them.

## Rebuilding the Alibaba trace

Download `pai_task_table.csv` from the `cluster-trace-gpu-v2020` directory of
[alibaba/clusterdata](https://github.com/alibaba/clusterdata), then:

```bash
cd sim
python3 make_alibaba_trace.py --input /path/to/pai_task_table.csv --out ../traces/alibaba_trace.csv
```

The script keeps only `Terminated` jobs with valid timestamps, converts Alibaba's
percentage-encoded GPU plans to whole GPUs, multiplies by `inst_num` for the gang size, clamps
service time at 48 h, and takes a seed-42 16.4% subsample. The result should be 120,105 jobs
with

```
sha256  691ac84cea74bf12e07149fa5238cd7fd5313f1c13eded5c9d39a5a6c1747594
```

If your checksum differs, the upstream trace has changed since our run and the Alibaba column
of Table 6 will not reproduce exactly.

## Verifying the shipped traces

```bash
cd traces && sha256sum -c SHA256SUMS
```

## Citations

Philly:

> M. Jeon, S. Venkataraman, A. Phanishayee, J. Qian, W. Xiao, and F. Yang, "Analysis of
> large-scale multi-tenant GPU clusters for DNN training workloads," in *USENIX ATC*, 2019.

Helios:

> Q. Hu, P. Sun, S. Yan, Y. Wen, and T. Zhang, "Characterization and prediction of deep
> learning workloads in large-scale GPU datacenters," in *SC*, 2021.

Alibaba:

> Q. Weng, W. Xiao, Y. Yu, W. Wang, C. Wang, J. He, Y. Li, L. Zhang, W. Lin, and Y. Ding,
> "MLaaS in the wild: Workload analysis and scheduling in large-scale heterogeneous GPU
> clusters," in *USENIX NSDI*, 2022.
