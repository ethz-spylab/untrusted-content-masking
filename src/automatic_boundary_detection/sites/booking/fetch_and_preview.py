#!/usr/bin/env python3
"""
Fetch Booking.com pages and preview hand-labeled selectors.

1. Loads each page in Playwright, saves rendered DOM HTML locally.
2. Re-opens saved HTML, highlights hand config selectors, takes screenshots.

Usage:
    python fetch_and_preview.py
    python fetch_and_preview.py --fetch-only
    python fetch_and_preview.py --preview-only

DISCLAIMER: For academic research and reproducibility only. This script fetches
a small number of pages from a live third-party site (Booking.com). Before
running it, review and respect the site's Terms of Service and robots.txt. Do
not run it at scale or for any commercial purpose.
"""

import json
import time
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright


SCRIPT_DIR = Path(__file__).parent

PAGES = {
    "search": "/searchresults.html?ss=Paris&dest_id=-1456928&dest_type=city&checkin=2025-07-01&checkout=2025-07-03&group_adults=2&no_rooms=1&selected_currency=EUR&lang=en-us",
    "hotel": "/hotel/fr/pullman-paris-tour-eiffel.en-us.html?checkin=2025-07-01&checkout=2025-07-03&selected_currency=EUR",
    "homepage": "/index.html?lang=en-us&selected_currency=EUR",
}

BASE_URL = "https://www.booking.com"

WAIT_SELECTORS = {
    "search": "[data-testid='property-card'], .sr_property_block",
    "hotel": "[data-testid='property-section--content'], #hotelTm498",
    "homepage": "[data-testid='property-card'], [data-testid='deals-container'], .bui-card",
}


def dismiss_consent(page):
    """Dismiss Booking.com GDPR cookie consent popup if present."""
    try:
        accept_btn = page.locator("button#onetrust-accept-btn-handler")
        if accept_btn.is_visible(timeout=3000):
            accept_btn.click()
            time.sleep(1)
            print("    Dismissed cookie consent")
    except Exception:
        pass

    # Also try alternative consent patterns
    try:
        accept_btn = page.locator("[data-testid='accept-btn']")
        if accept_btn.first.is_visible(timeout=2000):
            accept_btn.first.click()
            time.sleep(1)
    except Exception:
        pass

    # Dismiss Genius "Sign in, save money" popup
    try:
        close_btn = page.locator("button[aria-label='Dismiss sign-in info.']")
        if close_btn.is_visible(timeout=2000):
            close_btn.click()
            time.sleep(1)
            print("    Dismissed Genius popup")
    except Exception:
        pass

    # Fallback: remove blocking overlays via JS
    try:
        page.evaluate("""
            () => {
                document.querySelectorAll('.dc7e768484, .bbe73dce14').forEach(el => el.remove());
            }
        """)
    except Exception:
        pass


def build_highlight_css(config):
    """Build CSS that highlights all elements matching selectors in the config."""
    rules = []
    for item in config.get("untrusted_selectors", []):
        selector = item.get("selector", "")
        if not selector:
            continue
        rules.append(
            f'{selector} {{\n'
            f'  outline: 3px solid #00b400 !important;\n'
            f'  background-color: rgba(0, 200, 0, 0.15) !important;\n'
            f'  outline-offset: 1px;\n'
            f'}}'
        )
    return "\n".join(rules)


def fetch_pages():
    """Fetch each page with Playwright and save the rendered DOM HTML."""
    print("=" * 60)
    print("Step 1: Scraping Booking.com pages (rendered DOM)")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-US",
        )
        page = context.new_page()

        for page_name, path in PAGES.items():
            url = f"{BASE_URL}{path}"
            out_file = SCRIPT_DIR / f"llm_input_original_{page_name}.html"

            print(f"\n  Fetching {page_name}: {url}")
            try:
                page.goto(url, wait_until="networkidle", timeout=60000)

                # Dismiss GDPR cookie consent
                dismiss_consent(page)

                # For search page: Booking.com ignores URL params in headless mode,
                # so we need to actually type in the search box and submit
                if page_name == "search":
                    print("    Performing interactive search for 'Paris'...")
                    try:
                        # First dismiss the Genius sign-in popup that blocks the search
                        try:
                            close_btn = page.locator("button[aria-label='Dismiss sign-in info.'], [data-testid='dismissible-banner'] button, .dc7e768484 button").first
                            close_btn.click(timeout=5000)
                            print("    Dismissed Genius popup")
                            time.sleep(1)
                        except Exception:
                            # Try clicking the X button on any modal
                            try:
                                page.evaluate("""
                                    () => {
                                        // Remove any overlay/modal blocking the search
                                        document.querySelectorAll('.dc7e768484, .bbe73dce14, [role="dialog"]').forEach(el => el.remove());
                                    }
                                """)
                                print("    Removed blocking overlays via JS")
                                time.sleep(1)
                            except Exception:
                                pass

                        # Click the search input and type destination
                        search_input = page.locator("input[name='ss']").first
                        search_input.click(timeout=5000)
                        time.sleep(1)
                        search_input.fill("Paris")
                        time.sleep(2)

                        # Wait for autocomplete and select first suggestion
                        try:
                            suggestion = page.locator("[data-testid='autocomplete-result']").first
                            suggestion.wait_for(timeout=5000)
                            suggestion.click()
                            time.sleep(1)
                        except Exception:
                            print("    No autocomplete, pressing Enter")
                            search_input.press("Enter")
                            time.sleep(1)

                        # Click search button
                        search_btn = page.locator("button[type='submit']").first
                        search_btn.click()

                        # Wait for search results to load
                        page.wait_for_load_state("networkidle", timeout=30000)
                        try:
                            page.wait_for_selector(
                                "[data-testid='property-card'], [data-testid='web-core-property-card']",
                                timeout=15000,
                            )
                            print("    Search results loaded!")
                        except Exception:
                            print("    Warning: Property cards not found after search")

                        # Dismiss any post-search popups
                        dismiss_consent(page)
                        time.sleep(3)

                    except Exception as e:
                        print(f"    Warning: Interactive search failed: {e}")
                        print("    Falling back to direct URL")

                # Wait for content-specific selectors
                wait_sel = WAIT_SELECTORS.get(page_name)
                if wait_sel:
                    try:
                        page.wait_for_selector(wait_sel, timeout=15000)
                    except Exception:
                        print(f"    Warning: Wait selector not found, continuing")

                # Extra time for SPA rendering
                time.sleep(3)

                html = page.content()
                out_file.write_text(html, encoding="utf-8")
                print(f"    Saved: {out_file.name} ({len(html)} bytes)")

            except Exception as e:
                print(f"    ERROR fetching {page_name}: {e}")

        browser.close()


def preview_selectors():
    """Open saved HTML files, highlight hand config selectors, take screenshots."""
    print("\n" + "=" * 60)
    print("Step 2: Previewing hand config selectors")
    print("=" * 60)

    config_path = SCRIPT_DIR / "hand_labels.json"
    if not config_path.exists():
        print(f"  ERROR: {config_path} not found")
        return

    with open(config_path) as f:
        config = json.load(f)

    css = build_highlight_css(config)
    n_selectors = len(config.get("untrusted_selectors", []))
    print(f"  Config has {n_selectors} selectors")

    preview_dir = SCRIPT_DIR / "preview"
    preview_dir.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for page_name in PAGES:
            out_png = preview_dir / f"{page_name}.png"
            url = f"{BASE_URL}{PAGES[page_name]}"

            print(f"\n  Previewing {page_name}: {url}")

            page.goto(url, wait_until="networkidle", timeout=60000)
            dismiss_consent(page)

            wait_sel = WAIT_SELECTORS.get(page_name)
            if wait_sel:
                try:
                    page.wait_for_selector(wait_sel, timeout=15000)
                except Exception:
                    pass
            time.sleep(3)

            # Inject highlight CSS
            page.add_style_tag(content=css)

            # Add a legend banner
            page.evaluate(f"""
                () => {{
                    const banner = document.createElement('div');
                    banner.innerHTML = '<b>Hand Config Preview — {page_name}</b> | ' +
                        '{n_selectors} selectors highlighted (green)';
                    banner.style.cssText = 'position:fixed; top:0; left:0; right:0; z-index:99999; ' +
                        'background:#00b400; color:white; padding:10px 16px; font-size:16px; ' +
                        'font-weight:bold; text-align:center; font-family:sans-serif;';
                    document.body.prepend(banner);
                    document.body.style.paddingTop = '44px';
                }}
            """)

            # Count how many elements matched
            match_count = page.evaluate("""
                () => {
                    let count = 0;
                    """ + " ".join([
                        f'count += document.querySelectorAll("{item["selector"].replace(chr(34), chr(92)+chr(34))}").length;'
                        for item in config.get("untrusted_selectors", [])
                        if item.get("selector")
                    ]) + """
                    return count;
                }
            """)
            print(f"    Elements matched: {match_count}")

            time.sleep(0.5)
            page.screenshot(path=str(out_png), full_page=True, timeout=60000)
            print(f"    Saved: {out_png}")

        browser.close()

    print(f"\n  All previews saved to: {preview_dir}/")


if __name__ == "__main__":
    if "--preview-only" in sys.argv:
        preview_selectors()
    elif "--fetch-only" in sys.argv:
        fetch_pages()
    else:
        fetch_pages()
        preview_selectors()
    print("\nDone!")
