# Shell profile for Reddit (old.reddit.com).
# Sourced by ../../pipeline/run_pipeline.sh — defines pages and URLs.

SITE_LABEL="Reddit"
SITE_URL="${SITE_URL:-https://old.reddit.com}"
LOCAL_SERVER="${LOCAL_SERVER:-http://localhost:8001}"

# Evaluation hits saved HTML on a local http.server, not the live site.
USE_LOCAL_SERVER=true

ALL_PAGES="subreddit post user"

get_page_url() {
    case "$1" in
        subreddit) echo "/r/programming" ;;
        post)      echo "/r/programming/comments/1s3fj4b/the_gold_standard_of_optimization_a_look_under/" ;;
        user)      echo "/user/spez" ;;
        *)         echo ""; return 1 ;;
    esac
}
