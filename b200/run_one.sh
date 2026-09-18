#!/bin/bash
# 단일 정책 run 러너 (run_philly1000.sh 일반화).
# 사용: run_one.sh <policy> <run_id> "<ctrl_extra>" "<exp_extra>"
#   예: run_one.sh sfqa-auto p_sfqa_auto "" ""
#       run_one.sh sfqa-auto p_auto_k1500 "" "--kappa 1500"
#       run_one.sh sfqa p_sfqa_s7 "--beta 100 --age-unit 10" "--seed 7"
set -u
POLICY=$1; RUNID=$2; CTRL_EXTRA=${3:-}; EXP_EXTRA=${4:-}
VENV=/raid/squad/venv/bin/python
RE=/home/mystous/gpu_scheduler/squad_ctrl/run_experiment.py
CTRL=/home/mystous/gpu_scheduler/squad_ctrl/policy_controller.py
export KUBECONFIG=/home/mystous/.kube/config
PH=/raid/squad/traces/philly/repo/trace-data/cluster_job_log
LOG=/raid/squad/runs/run_${RUNID}.log
: > "$LOG"
COMMON="--trace philly --input $PH --sample 1000 --seed 42 --kappa 3000 --min-dur 6 --max-dur 8 --submit-clamp 0 --gpu-types NVIDIA-B200 --timeout 7200"

kubectl delete jobs --all -n squad >/dev/null 2>&1
kubectl delete pods --all -n squad >/dev/null 2>&1
sleep 6

echo "[$(date '+%T')] policy=$POLICY run=$RUNID extra='$EXP_EXTRA'" | tee -a "$LOG"
CPID=""
if [ "$POLICY" != "none" ] && [ "$POLICY" != "kueue" ]; then
  $VENV $CTRL --policy "$POLICY" --period 5 $CTRL_EXTRA > /raid/squad/runs/${RUNID}_ctrl.log 2>&1 &
  CPID=$!
  sleep 3
fi
$VENV $RE $COMMON --policy "$POLICY" --run-id "$RUNID" $EXP_EXTRA >> "$LOG" 2>&1
RC=$?
[ -n "$CPID" ] && kill "$CPID" 2>/dev/null
echo "[$(date '+%T')] DONE rc=$RC" | tee -a "$LOG"
exit $RC
