# Traces

Three public traces back the results. Two are redistributed here under their original
license; the third must be downloaded and converted because its owner declares no license.

| File | Source | Original license | Shipped here |
|---|---|---|---|
| `sweep_trace.csv`, `sweep_trace_vc.csv` | Philly, [msr-fiddle/philly-traces](https://github.com/msr-fiddle/philly-traces) | CC BY 4.0 | yes |
| `helios_trace_sub.csv` | Helios Venus, [S-Lab-System-Group/HeliosData](https://github.com/S-Lab-System-Group/HeliosData) | CC BY 4.0 | yes |
| `alibaba_trace.csv` | Alibaba PAI, [alibaba/clusterdata](https://github.com/alibaba/clusterdata) | none declared | **no — build it yourself** |

Columns are `job_id, arrival_s, service_sec, gpu_count`.

## Why Alibaba is not included

The `alibaba/clusterdata` repository declares no license. Absent an explicit grant we have no
basis to redistribute the data or a work derived from it, so this repository ships the
conversion script instead. Philly and Helios are both CC BY 4.0, which permits redistribution
with attribution, and the attributions are the citations below.

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
