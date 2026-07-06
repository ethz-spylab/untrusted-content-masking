# Shell profile for Booking.com.
# Sourced by ../../pipeline/run_pipeline.sh — defines pages, URLs, and how to
# serve the cached HTML during evaluation.

SITE_LABEL="Booking.com"
SITE_URL="${SITE_URL:-https://www.booking.com}"
LOCAL_SERVER="${LOCAL_SERVER:-http://localhost:8001}"

# Evaluation hits saved HTML on a local http.server, not the live site.
USE_LOCAL_SERVER=true

# Booking pages are image-heavy; tell visualize_selectors to use the
# replaced-element (img/picture) treatment so highlights are visible.
SITE_IMG_REPLACED=true

ALL_PAGES="homepage search hotel"

# Map a page name to its path under SITE_URL. Used for the "remote URL" log
# line; pipeline evaluation actually targets the local-server URL.
get_page_url() {
    case "$1" in
        search)   echo "/searchresults.html?ss=Paris&dest_id=-1456928&dest_type=city&checkin=2025-07-01&checkout=2025-07-03" ;;
        hotel)    echo "/hotel/fr/pullman-paris-tour-eiffel.en-us.html?checkin=2025-07-01&checkout=2025-07-03" ;;
        homepage) echo "/index.html?lang=en-us&selected_currency=EUR" ;;
        *)        echo ""; return 1 ;;
    esac
}
