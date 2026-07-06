#!/usr/bin/env python3
"""
Fetch old.reddit.com pages and preview hand-labeled selectors.

1. Loads each page in Playwright, saves rendered DOM HTML locally.
2. Re-opens the live URL, highlights hand_labels.json selectors, takes a full-page screenshot into preview/.

Usage:
    python fetch_and_preview.py
    python fetch_and_preview.py --fetch-only
    python fetch_and_preview.py --preview-only

Disclaimer: For academic research and reproducibility only. This script fetches a small number of pages from a live third-party site (old.reddit.com). Before running it, review and respect the site's Terms of Service and robots.txt. Do not run it at scale or for any commercial purpose.
"""

import json
import time
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright


SCRIPT_DIR = Path(__file__).parent

PAGES = {
    "subreddit": "/r/programming",
    "post":      "/r/programming/comments/1s3fj4b/the_gold_standard_of_optimization_a_look_under/",
    "user":      "/user/spez",
}

BASE_URL = "https://old.reddit.com"

WAIT_SELECTORS = {
    "subreddit": "#siteTable, .linklisting",
    "post":      ".commentarea, .nestedlisting",
    "user":      ".content, .side",
}


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
    print("Step 1: Fetching old.reddit.com pages (rendered DOM)")
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
        )
        page = context.new_page()

        for page_name, path in PAGES.items():
            url = f"{BASE_URL}{path}"
            out_file = SCRIPT_DIR / f"llm_input_original_{page_name}.html"

            print(f"\n  Fetching {page_name}: {url}")
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)

                wait_sel = WAIT_SELECTORS.get(page_name)
                if wait_sel:
                    try:
                        page.wait_for_selector(wait_sel, timeout=10000)
                    except Exception:
                        pass

                time.sleep(2)

                html = page.content()
                out_file.write_text(html, encoding="utf-8")
                print(f"    Saved: {out_file.name} ({len(html)} bytes)")

            except Exception as e:
                print(f"    ERROR fetching {page_name}: {e}")

        browser.close()


def preview_selectors():
    """Open the live URLs, highlight hand_labels.json selectors, screenshot."""
    print("\n" + "=" * 60)
    print("Step 2: Previewing hand_labels selectors")
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

            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            wait_sel = WAIT_SELECTORS.get(page_name)
            if wait_sel:
                try:
                    page.wait_for_selector(wait_sel, timeout=10000)
                except Exception:
                    pass
            time.sleep(2)

            page.add_style_tag(content=css)

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
