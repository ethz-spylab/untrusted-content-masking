# Shell profile for GitLab (WebArena instance).
# Sourced by ../../pipeline/run_pipeline.sh — defines pages and URLs.

SITE_LABEL="GitLab"
# GitLab reads from GITLAB_URL.
SITE_URL="${GITLAB_URL:-http://localhost:8103}"

# GitLab evaluates against the live page (no local server, no cached HTML).
USE_LOCAL_SERVER=false

# Comparison reads per-page exclusions from the hand config. Populates the array used by run_pipeline.sh.
set_compare_extra_args_for_page() {
    local page="$1"
    COMPARE_EXTRA_ARGS=(--gt-exclude "${HAND_CONFIG}" --page "${page}")
}

ALL_PAGES="project issue user"

get_page_url() {
    case "$1" in
        project) echo "/byteblaze/a11y-syntax-highlighting" ;;
        issue)   echo "/byteblaze/a11y-syntax-highlighting/-/issues/1" ;;
        user)    echo "/byteblaze" ;;
        *)       echo ""; return 1 ;;
    esac
}
