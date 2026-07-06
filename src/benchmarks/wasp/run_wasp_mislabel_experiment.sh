#!/usr/bin/env bash
set -euo pipefail

# WASP Ultimate 12 attack with UCM defense + MISLABELED issue description.
#
# Simulates a labeling error where the issue description is NOT marked as
# untrusted. The agent still gets the full ucm_defense system prompt
# and other untrusted elements remain masked — only the issue description
# (where WASP injects its payload) is visible.
#
# Usage:
#   bash run_wasp_mislabel_experiment.sh
# Default: 3 iterations (run_1, run_2, run_3); each iteration resets GitLab and re-injects tasks.
#
# Override defaults via env vars:
#   INJECTION_FORMATS="context_blending system_message" bash run_wasp_mislabel_experiment.sh
#   N_VALUES="1" bash run_wasp_mislabel_experiment.sh   # single run only

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
cd "$REPO_ROOT"

MARKER_DIR="environments/webarena/gitlab-setup/nginx-files"
ORIGINAL="${MARKER_DIR}/gitlab-marker.js"
MISLABEL="${MARKER_DIR}/gitlab-marker-mislabel-desc.js"
BACKUP="${MARKER_DIR}/gitlab-marker.js.bak"

# Ensure the mislabel variant exists
if [[ ! -f "${MISLABEL}" ]]; then
  echo "ERROR: ${MISLABEL} not found. Create it first."
  exit 1
fi

# Restore original on exit (even on error/Ctrl-C)
cleanup() {
  echo ""
  echo "=== Restoring original gitlab-marker.js ==="
  if [[ -f "${BACKUP}" ]]; then
    cp "${BACKUP}" "${ORIGINAL}"
    rm -f "${BACKUP}"
    echo "  Restored."
  else
    echo "  No backup found — original should still be in place."
  fi
}
trap cleanup EXIT

# Swap in the mislabeled version
echo "=== Swapping gitlab-marker.js → mislabel variant ==="
cp "${ORIGINAL}" "${BACKUP}"
cp "${MISLABEL}" "${ORIGINAL}"
echo "  Done. Issue descriptions will NOT be masked."

# Run the WASP attack experiment with UCM defense
MODEL="${MODEL:-claude-sonnet-4-20250514}" \
SYSTEM_PROMPT="${SYSTEM_PROMPT:-ucm_defense}" \
REVEAL_MODE="${REVEAL_MODE:-trusted}" \
ATTACKS_CONFIG="${ATTACKS_CONFIG:-src/benchmarks/wasp/configs/wasp_gitlab_attacks_strengthened.json}" \
USER_GOAL_IDX="${USER_GOAL_IDX:-2}" \
INJECTION_FORMATS="${INJECTION_FORMATS:-important_instructions}" \
RESULTS_DIR="${RESULTS_DIR:-results_wasp_mislabel_description}" \
N_VALUES="${N_VALUES:-1 2 3}" \
MAX_STEPS="${MAX_STEPS:-100}" \
bash runners/run_wasp_attacks.sh

echo ""
echo "############################################"
echo "# Mislabel experiment completed."
echo "# Results in: ${RESULTS_DIR:-results_wasp_mislabel_description}/"
echo "############################################"
