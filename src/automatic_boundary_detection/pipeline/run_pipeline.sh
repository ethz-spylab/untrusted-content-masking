#!/bin/bash
# Site-agnostic boundary-detection pipeline.
#
# Usage:
#   pipeline/run_pipeline.sh <site>                      # all pages
#   pipeline/run_pipeline.sh <site> <page>...            # specific pages
#   pipeline/run_pipeline.sh <site> --skip-llm           # reuse cached LLM config
#   pipeline/run_pipeline.sh <site> --skip-llm <page>    # both
#
# The site name selects sites/<site>/site.sh + sites/<site>/site.py. See those
# files for the per-site URL/page set, LLM prompt, and HTML cleaning rules.
#
# Prerequisites:
#   - ANTHROPIC_API_KEY in environment or .env file (unless --skip-llm)
#   - Python deps: playwright, anthropic, beautifulsoup4, python-dotenv, matplotlib
#   - Per-site prerequisites (e.g. gitlab needs the WebArena proxy on :8103,
#     booking/google_flights expect saved HTML alongside site.py).

set -e

if [ $# -lt 1 ]; then
    echo "Usage: $0 <site> [--skip-llm] [page]..."
    echo ""
    echo "Available sites:"
    ls -1 "$(dirname "$0")/../sites" 2>/dev/null | sed 's/^/  /'
    exit 1
fi

SITE="$1"
shift

PIPELINE_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "${PIPELINE_DIR}/.." && pwd)"
SITE_DIR="${ROOT_DIR}/sites/${SITE}"

if [ ! -d "${SITE_DIR}" ]; then
    echo "Unknown site: ${SITE}"
    echo "Available sites: $(ls -1 ${ROOT_DIR}/sites)"
    exit 1
fi

# Source the site profile — defines SITE_LABEL, SITE_URL, USE_LOCAL_SERVER,
# ALL_PAGES, get_page_url(), and optionally
# set_compare_extra_args_for_page() (which populates COMPARE_EXTRA_ARGS[]).
LOCAL_SERVER=""
COMPARE_EXTRA_ARGS=()
set_compare_extra_args_for_page() { COMPARE_EXTRA_ARGS=(); }
# shellcheck source=/dev/null
source "${SITE_DIR}/site.sh"

RESULTS_DIR="${RESULTS_DIR:-${ROOT_DIR}/results/${SITE}}"
HAND_CONFIG="${SITE_DIR}/hand_labels.json"
LLM_CONFIG="${SITE_DIR}/llm_labels.json"

# ── Parse remaining arguments ────────────────────────────────────────
SKIP_LLM=false
SELECTED_PAGES=""

for arg in "$@"; do
    case "$arg" in
        --skip-llm) SKIP_LLM=true ;;
        *)
            # Validate against ALL_PAGES
            if [[ " ${ALL_PAGES} " == *" ${arg} "* ]]; then
                SELECTED_PAGES="${SELECTED_PAGES} ${arg}"
            else
                echo "Unknown page for ${SITE}: ${arg}"
                echo "Available pages: ${ALL_PAGES}"
                exit 1
            fi
            ;;
    esac
done

if [ -z "$SELECTED_PAGES" ]; then
    SELECTED_PAGES="$ALL_PAGES"
fi
SELECTED_PAGES="$(echo "$SELECTED_PAGES" | xargs)"
NUM_PAGES=$(echo "$SELECTED_PAGES" | wc -w | xargs)

echo "=========================================="
echo "${SITE_LABEL} LLM Label Detection Pipeline"
echo "=========================================="
echo "Site URL:   ${SITE_URL}"
[ -n "$LOCAL_SERVER" ] && echo "Local URL:  ${LOCAL_SERVER}"
echo "Pages:      ${SELECTED_PAGES}"
echo "Skip LLM:   ${SKIP_LLM}"
echo "Results:    ${RESULTS_DIR}"
echo ""

mkdir -p "${RESULTS_DIR}"

# ── Step 1: Ground-truth config ─────────────────────────────────────
if [ -f "${HAND_CONFIG}" ]; then
    echo "Step 1: Hand config exists: ${HAND_CONFIG}"
else
    echo "Step 1: ERROR - Hand config missing for ${SITE}."
    echo "        Expected: ${HAND_CONFIG}"
    exit 1
fi
echo ""

# ── Step 2: LLM analysis ────────────────────────────────────────────
if [ "$SKIP_LLM" = false ]; then
    echo "Step 2: Running LLM analysis (all pages)..."
    python "${PIPELINE_DIR}/analyze_untrusted_elements.py" --site "${SITE}"
    echo ""
else
    echo "Step 2: Skipping LLM analysis (--skip-llm), reusing: ${LLM_CONFIG}"
    if [ ! -f "${LLM_CONFIG}" ]; then
        echo "Error: LLM config not found: ${LLM_CONFIG}"
        echo "Run without --skip-llm first to generate it."
        exit 1
    fi
    echo ""
fi

# ── Per-page evaluation ─────────────────────────────────────────────
for page in ${SELECTED_PAGES}; do
    PAGE_PATH="$(get_page_url "$page")"
    REMOTE_URL="${SITE_URL}${PAGE_PATH}"

    # Decide which URL the evaluator actually hits.
    if [ "${USE_LOCAL_SERVER}" = "true" ]; then
        LOCAL_HTML="${SITE_DIR}/llm_input_original_${page}.html"
        if [ -f "${LOCAL_HTML}" ]; then
            EVAL_URL="${LOCAL_SERVER}/llm_input_original_${page}.html"
        else
            EVAL_URL="${REMOTE_URL}"
        fi
    else
        EVAL_URL="${REMOTE_URL}"
    fi

    PAGE_DIR="${RESULTS_DIR}/${page}"
    mkdir -p "${PAGE_DIR}"
    cp "${HAND_CONFIG}" "${PAGE_DIR}/"
    cp "${LLM_CONFIG}" "${PAGE_DIR}/"

    echo "=========================================="
    echo "Processing page: ${page}"
    echo "  Remote URL: ${REMOTE_URL}"
    echo "  Eval URL:   ${EVAL_URL}"
    echo "  Dir:        ${PAGE_DIR}"
    echo "=========================================="
    echo ""

    echo "  Step 3: Evaluating hand selectors on ${page}..."
    python "${PIPELINE_DIR}/analyze_selectors.py" "${EVAL_URL}" \
        --site "${SITE}" \
        --config "${HAND_CONFIG}" \
        --output "${PAGE_DIR}/hand_results.json"
    echo ""

    echo "  Step 4: Evaluating LLM selectors on ${page}..."
    python "${PIPELINE_DIR}/analyze_selectors.py" "${EVAL_URL}" \
        --site "${SITE}" \
        --config "${LLM_CONFIG}" \
        --output "${PAGE_DIR}/llm_results.json"
    echo ""

    echo "  Step 5: Comparing hand vs LLM selectors..."
    set_compare_extra_args_for_page "$page"
    python "${PIPELINE_DIR}/compare_selector_results.py" \
        "${PAGE_DIR}/hand_results.json" \
        "${PAGE_DIR}/llm_results.json" \
        --output "${PAGE_DIR}/comparison_metrics.json" \
        "${COMPARE_EXTRA_ARGS[@]}"
    echo ""

    echo "  Step 6: Generating plots..."
    python "${PIPELINE_DIR}/plot_comparison_metrics.py" \
        "${PAGE_DIR}/comparison_metrics.json" \
        --output "${PAGE_DIR}/plot_metrics"
    echo ""

    echo "  Step 7: Generating visual comparison..."
    VIZ_EXTRA=""
    if [ "${IMG_REPLACED_HANDLING:-${SITE_IMG_REPLACED:-false}}" = "true" ]; then
        VIZ_EXTRA="--img-replaced-handling"
    fi
    # Set SKIP_VIZ=1 to skip screenshots entirely (useful for fast metric
    # sweeps;).
    if [ "${SKIP_VIZ:-0}" = "1" ]; then
        echo "  Step 7: SKIPPED (SKIP_VIZ=1)"
    else
        python "${PIPELINE_DIR}/visualize_selectors.py" \
            --url "${EVAL_URL}" \
            --hand "${HAND_CONFIG}" \
            --llm "${LLM_CONFIG}" \
            --output "${PAGE_DIR}/" \
            --metrics "${PAGE_DIR}/comparison_metrics.json" \
            --parent-aware ${VIZ_EXTRA} || echo "  WARNING: visualize step failed (screenshots may be missing), continuing"
    fi
    echo ""
done

# ── Merge metrics across pages ──────────────────────────────────────
if [ "$NUM_PAGES" -gt 1 ]; then
    echo "=========================================="
    echo "Merging metrics across ${NUM_PAGES} pages"
    echo "=========================================="
    echo ""

    MERGE_INPUTS=()
    for page in ${SELECTED_PAGES}; do
        MERGE_INPUTS+=("${RESULTS_DIR}/${page}/comparison_metrics.json")
    done
    python "${PIPELINE_DIR}/plot_comparison_metrics.py" \
        "${MERGE_INPUTS[@]}" \
        --merged-output "${RESULTS_DIR}/merged_metrics.json" \
        --output "${RESULTS_DIR}/merged_plot_metrics"
    echo ""
fi

# ── Per-page summary JSON ───────────────────────────────────────────
echo "=========================================="
echo "Generating per-page summary JSON"
echo "=========================================="
echo ""

SUMMARY_ARGS=()
for page in ${SELECTED_PAGES}; do
    SUMMARY_ARGS+=("${page}:${RESULTS_DIR}/${page}/comparison_metrics.json")
done
if [ "$NUM_PAGES" -gt 1 ] && [ -f "${RESULTS_DIR}/merged_metrics.json" ]; then
    SUMMARY_ARGS+=(--merged "${RESULTS_DIR}/merged_metrics.json")
fi
python "${PIPELINE_DIR}/generate_summary.py" \
    "${SUMMARY_ARGS[@]}" \
    --output "${RESULTS_DIR}/summary_all_pages.json"
echo ""

# ── Done ────────────────────────────────────────────────────────────
echo "=========================================="
echo "PIPELINE COMPLETE!"
echo "=========================================="
echo ""
echo "Results saved in: ${RESULTS_DIR}/"
for page in ${SELECTED_PAGES}; do
    echo "  ${page}/  (hand_results, llm_results, comparison_metrics, plots, screenshots)"
done
if [ "$NUM_PAGES" -gt 1 ]; then
    echo "  merged_metrics.json              (aggregated across all pages)"
    echo "  merged_plot_metrics.png/pdf       (aggregated plots)"
fi
echo "  summary_all_pages.json           (per-page metrics for plotting)"
echo ""
