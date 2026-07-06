#!/usr/bin/env bash
set -euo pipefail

# Sweep the 10 custom-website task suites across both defenses (UCM + undefended
# baseline) and write per-task results under results_custom/<model>/...
#
# Prerequisites: see README.md#setup (Docker running, ANTHROPIC_API_KEY /
# OPENAI_API_KEY exported, `uv sync` done).
#
# Default sweep: 5 suites (email, banking, forum, webshop, calendar) × 3
# iterations × both task groups, with --allow-unsolvable.
#
# Multiple models in one go (each entry is provider:model, or plain model
# which uses PROVIDER from the env, default anthropic):
#   MODELS="anthropic:claude-sonnet-4-5-20250929 openai:gpt-5.4" \
#     bash runners/run_custom_websites.sh
#
# Single-model and override examples:
#   bash runners/run_custom_websites.sh                                # all defaults
#   MODEL=gpt-5.4 PROVIDER=openai bash runners/run_custom_websites.sh
#   SUITE=banking GROUP=1_simple RUN_MODES=defended bash runners/run_custom_websites.sh
#   TASKS="banking_find_highest_transaction" bash runners/run_custom_websites.sh
#   RESULTS_DIR=my_run bash runners/run_custom_websites.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

# ── Configurable via environment variables ────────────────────────────
MODEL="${MODEL:-}"                                          # empty = provider default
PROVIDER="${PROVIDER:-anthropic}"                           # anthropic | openai
INITIAL_PROVIDER="${PROVIDER}"
MODELS="${MODELS:-}"                                        # space-separated; see header
DEFENDED_PROMPT="${DEFENDED_PROMPT:-ucm_defense}"
BASELINE_PROMPT="${BASELINE_PROMPT:-no_security}"
RESULTS_DIR="${RESULTS_DIR:-results_custom}"
N_VALUES="${N_VALUES:-3}"                                   # space-separated iteration indices
RUN_MODES="${RUN_MODES:-both}"                              # both | defended | baseline
TASKS="${TASKS:-}"                                          # specific task IDs, empty = all
SUITE="${SUITE:-email banking forum webshop calendar support jobboard restaurant travel wiki}"      # default suites (10 custom websites)
GROUP="${GROUP:-both}"                                      # 1_simple | 2_harder | both | all
MAX_STEPS="${MAX_STEPS:-150}"
TIMEOUT_RESTARTS="${TIMEOUT_RESTARTS:-1}"

# ── Helpers ───────────────────────────────────────────────────────────

run_one() {
  local mode_name="$1"
  local reveal_flag="$2"
  local prompt_name="$3"
  local n="$4"

  local cmd="uv run src/benchmarks/custom_websites/run_custom_websites.py"
  cmd+=" -p ${prompt_name}"
  cmd+=" --provider ${PROVIDER}"
  cmd+=" ${reveal_flag}"
  # cmd+=" --allow-unsolvable"
  cmd+=" --max-steps ${MAX_STEPS}"
  cmd+=" --timeout-restarts ${TIMEOUT_RESTARTS}"
  cmd+=" --results-dir ${RESULTS_DIR}"
  cmd+=" -n ${n}"

  if [[ -n "${MODEL}" ]]; then
    cmd+=" -m ${MODEL}"
  fi

  if [[ -n "${SUITE}" ]]; then
    cmd+=" --suite ${SUITE}"
  fi

  if [[ -n "${GROUP}" ]]; then
    cmd+=" --group ${GROUP}"
  fi

  if [[ -n "${TASKS}" ]]; then
    cmd+=" -t ${TASKS}"
  fi

  echo ""
  echo "############################################"
  echo "Mode: ${mode_name} (${reveal_flag}) | prompt=${prompt_name} | -n ${n}"
  echo "############################################"
  echo "Command: ${cmd}"
  eval "${cmd}"
}

run_all_run_modes() {
  case "${RUN_MODES}" in
    both)
      for n in ${N_VALUES}; do
        run_one "defended" "--mask-untrusted" "${DEFENDED_PROMPT}" "${n}"
        run_one "baseline" "--reveal-all" "${BASELINE_PROMPT}" "${n}"
      done
      ;;
    defended)
      for n in ${N_VALUES}; do
        run_one "defended" "--mask-untrusted" "${DEFENDED_PROMPT}" "${n}"
      done
      ;;
    baseline)
      for n in ${N_VALUES}; do
        run_one "baseline" "--reveal-all" "${BASELINE_PROMPT}" "${n}"
      done
      ;;
    *)
      echo "ERROR: Invalid RUN_MODES='${RUN_MODES}'. Use one of: both, defended, baseline."
      exit 2
      ;;
  esac
}

# ── Main ──────────────────────────────────────────────────────────────

echo "Starting custom website runs with:"
if [[ -n "${MODELS}" ]]; then
  echo "  MODELS=${MODELS}"
else
  echo "  PROVIDER=${PROVIDER}"
  echo "  MODEL=${MODEL:-<provider default>}"
fi
echo "  DEFENDED_PROMPT=${DEFENDED_PROMPT}"
echo "  BASELINE_PROMPT=${BASELINE_PROMPT}"
echo "  RESULTS_DIR=${RESULTS_DIR}"
echo "  SUITE=${SUITE}"
echo "  GROUP=${GROUP}"
echo "  N_VALUES=${N_VALUES}"
echo "  RUN_MODES=${RUN_MODES}"
echo "  MAX_STEPS=${MAX_STEPS}"
echo "  TIMEOUT_RESTARTS=${TIMEOUT_RESTARTS}"
if [[ -n "${TASKS}" ]]; then
  echo "  TASKS=${TASKS}"
fi
echo ""

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
    echo "# Provider=${PROVIDER}  Model=${MODEL:-<provider default>}"
    echo "# RESULTS_DIR=${RESULTS_DIR}"
    echo "##################################################################"
    run_all_run_modes
  done
else
  run_all_run_modes
fi

echo ""
echo "All runs completed."
