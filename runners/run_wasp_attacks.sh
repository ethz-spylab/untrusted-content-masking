#!/usr/bin/env bash
set -euo pipefail

# Run the WASP prompt-injection attack benchmark end-to-end against WebArena
# Results land under results_wasp_attacks_<mode>/<model>/...
#
# Prerequisites: see README.md#setup, then bring up the GitLab proxy
# (docker compose up -d vwa_gitlab_nginx). The proxy fronts a GitLab CE
# instance on AWS — see environments/webarena/gitlab-setup/README.md.
#
# Two attack variants (select via MODE):
#   MODE=strengthened  (default)    
#   MODE=original                 4 original WASP formats, no rewrites.
#
# Usage:
#   bash runners/run_wasp_attacks.sh                          # strengthened (default)
#   MODE=original bash runners/run_wasp_attacks.sh            # original WASP
#
# Override defaults via env vars (honored under either MODE):
#   INJECTION_FORMATS="goal_hijacking_plain_text" bash runners/run_wasp_attacks.sh
#   N_VALUES="1 2 3" bash runners/run_wasp_attacks.sh
#   USER_GOAL_IDX=2 SYSTEM_PROMPT=wasp_defense bash runners/run_wasp_attacks.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "$REPO_ROOT"

# Load .env so GITLAB_BACKEND_HOST etc. are available to this script + the
# Python tools it invokes via uv.
if [[ -f "${REPO_ROOT}/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "${REPO_ROOT}/.env"
    set +a
fi

MODE="${MODE:-strengthened}"

case "${MODE}" in
  strengthened)
    DEFAULT_FORMATS="important_instructions"
    DEFAULT_CONFIG="src/benchmarks/wasp/configs/wasp_gitlab_attacks_strengthened.json"
    DEFAULT_RESULTS_DIR="results_wasp_attacks_strengthened"
    ;;
  original)
    DEFAULT_FORMATS="goal_hijacking_plain_text goal_hijacking_url_injection generic_plain_text generic_url_injection"
    DEFAULT_CONFIG="src/benchmarks/wasp/configs/wasp_gitlab_attacks.json"
    DEFAULT_RESULTS_DIR="results_wasp_attacks_original"
    ;;
  *)
    echo "ERROR: Unknown MODE='${MODE}'. Use one of: strengthened, original."
    exit 2
    ;;
esac

# GITLAB_URL is where wasp_inject.py talks to GitLab over the API.  Default
# to GITLAB_BACKEND_HOST set in .env, on port 8023 (the GitLab port baked
# into the WebArena pre-populated AMI).
: "${GITLAB_BACKEND_HOST:?GITLAB_BACKEND_HOST is not set — see .env_example}"
GITLAB_URL="${GITLAB_URL:-http://${GITLAB_BACKEND_HOST}:8023}"
MODEL="${MODEL:-claude-sonnet-4-20250514}"
INJECTION_FORMATS="${INJECTION_FORMATS:-${DEFAULT_FORMATS}}"
USER_GOAL_IDX="${USER_GOAL_IDX:-0}"
N_VALUES="${N_VALUES:-1}"
RESULTS_DIR="${RESULTS_DIR:-${DEFAULT_RESULTS_DIR}}"
MAX_STEPS="${MAX_STEPS:-100}"
WAIT_AFTER_RESTART_SECS="${WAIT_AFTER_RESTART_SECS:-60}"
TIMEOUT_RESTARTS="${TIMEOUT_RESTARTS:-1}"
SYSTEM_PROMPT="${SYSTEM_PROMPT:-no_security}"
REVEAL_MODE="${REVEAL_MODE:-all}"
AGENT_DOMAIN="${AGENT_DOMAIN:-http://gitlab-vwa.com}"
ATTACKS_CONFIG="${ATTACKS_CONFIG:-${DEFAULT_CONFIG}}"
TASK_IDS="${TASK_IDS:-}"
ATTACK_IN_DESCRIPTION="${ATTACK_IN_DESCRIPTION:-1}" # 1=inject payload into description, 0=clean description
# 1 = pass --llm-judge-attack to run_webarena.py (needs ANTHROPIC_API_KEY)
LLM_JUDGE_ATTACK="${LLM_JUDGE_ATTACK:-0}"
LLM_JUDGE_ATTACK_MODEL="${LLM_JUDGE_ATTACK_MODEL:-}"

LLM_JUDGE_ARGS=()
if [[ "${LLM_JUDGE_ATTACK}" == "1" ]]; then
  LLM_JUDGE_ARGS=(--llm-judge-attack)
  if [[ -n "${LLM_JUDGE_ATTACK_MODEL}" ]]; then
    LLM_JUDGE_ARGS+=(--llm-judge-attack-model "${LLM_JUDGE_ATTACK_MODEL}")
  fi
fi

echo "Starting WASP attack testing with:"
echo "  MODE=${MODE}"
echo "  GITLAB_URL=${GITLAB_URL}"
echo "  MODEL=${MODEL}"
echo "  INJECTION_FORMATS=${INJECTION_FORMATS}"
echo "  USER_GOAL_IDX=${USER_GOAL_IDX}"
echo "  N_VALUES=${N_VALUES}"
echo "  RESULTS_DIR=${RESULTS_DIR}"
echo "  MAX_STEPS=${MAX_STEPS}"
echo "  SYSTEM_PROMPT=${SYSTEM_PROMPT}"
echo "  REVEAL_MODE=${REVEAL_MODE}"
echo "  ATTACKS_CONFIG=${ATTACKS_CONFIG}"
echo "  TASK_IDS=${TASK_IDS:-all}"
echo "  ATTACK_IN_DESCRIPTION=${ATTACK_IN_DESCRIPTION}"
echo "  LLM_JUDGE_ATTACK=${LLM_JUDGE_ATTACK}"

for FORMAT in ${INJECTION_FORMATS}; do
  for N in ${N_VALUES}; do
    echo ""
    echo "############################################"
    echo "# Format: ${FORMAT} | Iteration: ${N}"
    echo "############################################"

    # 1. Reset GitLab to pristine state
    echo ""
    echo "=== Resetting GitLab ==="
    "${REPO_ROOT}/src/benchmarks/webarena/reset_gitlab.sh"
    echo "Waiting ${WAIT_AFTER_RESTART_SECS}s for GitLab to come up..."
    sleep "${WAIT_AFTER_RESTART_SECS}"

    # 2. Inject attacks and generate task file
    TASKS_FILE="/tmp/wasp_tasks_${MODE}_${FORMAT}_n${N}.json"
    echo ""
    echo "=== Injecting attacks (format: ${FORMAT}) ==="
    uv run python src/benchmarks/wasp/wasp_inject.py \
      --gitlab-url "${GITLAB_URL}" \
      --format "${FORMAT}" \
      --user-goal-idx "${USER_GOAL_IDX}" \
      --output "${TASKS_FILE}" \
      --config "${ATTACKS_CONFIG}" \
      --agent-domain "${AGENT_DOMAIN}" \
      $( [[ "${ATTACK_IN_DESCRIPTION}" == "0" ]] && echo "--no-attack-description" )

    # 3. Run agent on injected tasks
    echo ""
    echo "=== Running agent on injected tasks ==="
    TASK_ID_ARGS=""
    if [[ -n "${TASK_IDS}" ]]; then
      TASK_ID_ARGS="--task-id ${TASK_IDS}"
    fi
    REVEAL_FLAG="--reveal-all"
    if [[ "${REVEAL_MODE}" == "trusted" ]]; then
      REVEAL_FLAG="--mask-untrusted"
    elif [[ "${REVEAL_MODE}" == "none" ]]; then
      REVEAL_FLAG=""
    fi
    uv run src/benchmarks/webarena/run_webarena.py \
      --tasks-file "${TASKS_FILE}" \
      -p "${SYSTEM_PROMPT}" \
      ${REVEAL_FLAG} \
      -m "${MODEL}" \
      --max-steps "${MAX_STEPS}" \
      -n "${N}" \
      --results-dir "${RESULTS_DIR}/${FORMAT}" \
      --timeout-restarts "${TIMEOUT_RESTARTS}" \
      ${TASK_ID_ARGS} \
      ${LLM_JUDGE_ARGS[@]+"${LLM_JUDGE_ARGS[@]}"}

  done
done

echo ""
echo "############################################"
echo "# All WASP attack runs completed."
echo "# Results in: ${RESULTS_DIR}/"
echo "############################################"
