#!/usr/bin/env bash
set -euo pipefail

# Sweep WebArena GitLab tasks across both defenses (UCM + undefended baseline)
# in alternating order — n=1 defended, n=1 baseline, n=2 defended, ... —
# restarting GitLab between each run. Results land under
# results_webarena/<model>/...
#
# Prerequisites: see README.md#setup, then bring up the GitLab proxy
# (docker compose up -d vwa_gitlab_nginx). The proxy itself fronts a GitLab CE
# instance running on AWS — see environments/webarena/gitlab-setup/README.md.
#
# Default sweep: every template × 1 task each, with --allow-unsolvable.
#
# Multiple models in one go (each entry is provider:model, or plain model
# which uses PROVIDER from the env, default anthropic):
#   MODELS="anthropic:claude-sonnet-4-5-20250929 openai:gpt-5.4" \
#     RESULTS_DIR=my_run caffeinate -i bash runners/run_webarena.sh
#
# Single-model and override examples:
#   bash runners/run_webarena.sh                                       # all defaults
#   PROVIDER=openai MODEL=gpt-5.4 caffeinate -i bash runners/run_webarena.sh
#   BASE_ARGS="--template 600 332 328 299 --tasks-per-template 1" bash runners/run_webarena.sh
#   RESULTS_DIR=my_run bash runners/run_webarena.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

TRUSTED_PROMPT="${TRUSTED_PROMPT:-ucm_defense}"
UNTRUSTED_PROMPT="${UNTRUSTED_PROMPT:-no_security}"
BASE_ARGS="${BASE_ARGS:---tasks-per-template 1 --allow-unsolvable}"
MODEL="${MODEL:-}"
PROVIDER="${PROVIDER:-anthropic}"
INITIAL_PROVIDER="${PROVIDER}"
MODELS="${MODELS:-}"
RESULTS_DIR="${RESULTS_DIR:-results_webarena}"
WAIT_AFTER_RESTART_SECS="${WAIT_AFTER_RESTART_SECS:-8}"
N_VALUES="${N_VALUES:-1 2 3}"
FINAL_RESTART="${FINAL_RESTART:-1}"
RUN_MODES="${RUN_MODES:-both}" # both | trusted | untrusted
TIMEOUT_RESTARTS="${TIMEOUT_RESTARTS:-2}"

restart_gitlab_containers() {
  echo ""
  echo "=== Resetting GitLab via src/benchmarks/webarena/reset_gitlab.sh ==="
  "${REPO_ROOT}/src/benchmarks/webarena/reset_gitlab.sh"
  echo "Waiting ${WAIT_AFTER_RESTART_SECS}s for services to stabilize..."
  sleep "$WAIT_AFTER_RESTART_SECS"
}

run_one() {
  local mode_name="$1"
  local reveal_flag="$2"
  local prompt_name="$3"
  local n="$4"
  local run_args="${BASE_ARGS}"

  # Optional convenience: allow selecting model without rewriting BASE_ARGS.
  # If BASE_ARGS already provides a model, keep it as-is.
  if [[ -n "${MODEL}" ]]; then
    if [[ " ${run_args} " != *" -m "* && " ${run_args} " != *" --model "* ]]; then
      run_args="${run_args} -m ${MODEL}"
    fi
  fi

  # Optional convenience: allow selecting provider without rewriting BASE_ARGS.
  # If BASE_ARGS already provides a provider, keep it as-is.
  if [[ -n "${PROVIDER}" ]]; then
    if [[ " ${run_args} " != *" --provider "* ]]; then
      run_args="${run_args} --provider ${PROVIDER}"
    fi
  fi

  echo ""
  echo "############################################"
  echo "Mode: ${mode_name} (${reveal_flag}) | -n ${n}"
  echo "############################################"
  echo "Command: uv run src/benchmarks/webarena/run_webarena.py -p ${prompt_name} ${reveal_flag} ${run_args} --timeout-restarts ${TIMEOUT_RESTARTS} --results-dir ${RESULTS_DIR} -n ${n}"
  uv run src/benchmarks/webarena/run_webarena.py -p "${prompt_name}" "${reveal_flag}" ${run_args} --timeout-restarts "${TIMEOUT_RESTARTS}" --results-dir "${RESULTS_DIR}" -n "${n}"

  # Restart between runs.
  restart_gitlab_containers
}

echo "Starting sequence with:"
echo "  TRUSTED_PROMPT=${TRUSTED_PROMPT}"
echo "  UNTRUSTED_PROMPT=${UNTRUSTED_PROMPT}"
echo "  BASE_ARGS=${BASE_ARGS}"
if [[ -n "${MODELS}" ]]; then
  echo "  MODELS=${MODELS}"
else
  echo "  MODEL=${MODEL}"
  echo "  PROVIDER=${PROVIDER}"
fi
echo "  RESULTS_DIR=${RESULTS_DIR}"
echo "  WAIT_AFTER_RESTART_SECS=${WAIT_AFTER_RESTART_SECS}"
echo "  N_VALUES=${N_VALUES}"
echo "  RUN_MODES=${RUN_MODES}"
echo "  TIMEOUT_RESTARTS=${TIMEOUT_RESTARTS}"

run_all_modes_for_current_model() {
  case "${RUN_MODES}" in
    both)
      for n in ${N_VALUES}; do
        run_one "trusted-open" "--mask-untrusted" "${TRUSTED_PROMPT}" "${n}"
        run_one "untrusted-open" "--reveal-all" "${UNTRUSTED_PROMPT}" "${n}"
      done
      ;;
    trusted)
      for n in ${N_VALUES}; do
        run_one "trusted-open" "--mask-untrusted" "${TRUSTED_PROMPT}" "${n}"
      done
      ;;
    untrusted)
      for n in ${N_VALUES}; do
        run_one "untrusted-open" "--reveal-all" "${UNTRUSTED_PROMPT}" "${n}"
      done
      ;;
    *)
      echo "ERROR: Invalid RUN_MODES='${RUN_MODES}'. Use one of: both, trusted, untrusted."
      exit 2
      ;;
  esac
}

# Initial reset before the first run.
restart_gitlab_containers

if [[ -n "${MODELS}" ]]; then
  read -ra MODEL_SPECS <<< "${MODELS}"
  for spec in "${MODEL_SPECS[@]}"; do
    if [[ "${spec}" == *:* ]]; then
      PROVIDER="${spec%%:*}"
      MODEL="${spec#*:}"
    else
      PROVIDER="${INITIAL_PROVIDER}"
      MODEL="${spec}"
    fi
    echo ""
    echo "##################################################################"
    echo "# WebArena: provider=${PROVIDER}  model=${MODEL:-<provider default>}"
    echo "# RESULTS_DIR=${RESULTS_DIR}"
    echo "##################################################################"
    run_all_modes_for_current_model
  done
else
  run_all_modes_for_current_model
fi

if [[ "${FINAL_RESTART}" == "1" ]]; then
  echo ""
  echo "Running explicit final GitLab reset..."
  restart_gitlab_containers
fi

echo ""
echo "All runs completed."
