#!/usr/bin/env python3
"""Generate `llm_labels.json` for one site.

Drives the per-site cleaning + prompt + LLM iteration loop. Site-specific behavior (HTML cleaning, prompt template, page set, fetch settings) lives in
sites/<site>/site.py.

Usage:
    python pipeline/analyze_untrusted_elements.py --site <site>
    python pipeline/analyze_untrusted_elements.py --site <site> --sanitize-only
"""
import argparse
import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from _site_loader import available_sites, load_site

LLM_MODEL = "claude-sonnet-4-5-20250929"


def _load_dotenv_from_repo():
    # .env lives at the repo root, three levels above this file.
    project_root = Path(__file__).resolve().parents[3]
    env_file = project_root / '.env'
    if env_file.exists():
        load_dotenv(env_file)
    else:
        load_dotenv()


def analyze_with_llm(html_contents, api_key, site, num_turns):
    """Run an iterative LLM conversation to propose CSS selectors."""
    client = Anthropic(api_key=api_key, timeout=600.0)

    html_content_str = ""
    for page_name, html in html_contents.items():
        html_content_str += f"\n\n=== {page_name.upper()} ===\n{html}\n"

    initial_prompt = site.INITIAL_PROMPT_TEMPLATE.format(
        num_pages=len(html_contents),
        html_content_str=html_content_str,
    )

    all_proposed = []
    messages = [{"role": "user", "content": initial_prompt}]

    for turn in range(1, num_turns + 1):
        try:
            if turn == 1:
                print(f"  Turn {turn}/{num_turns}: Initial proposal...")
            else:
                print(f"  Turn {turn}/{num_turns}: Asking for additional selectors...")

            response = client.messages.create(
                model=LLM_MODEL,
                max_tokens=8000,
                messages=messages,
            )
            original_content = response.content[0].text
            content = original_content.strip()

            start_idx = content.find('[')
            end_idx = content.rfind(']')
            if start_idx == -1 or end_idx == -1:
                raise ValueError("No JSON array found in response.")
            json_str = content[start_idx:end_idx + 1]

            try:
                new_selectors = json.loads(json_str)
            except json.JSONDecodeError as json_err:
                # Salvage: pull individual valid JSON objects out of the array body.
                objects = []
                obj_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
                for match in re.finditer(obj_pattern, json_str, re.DOTALL):
                    try:
                        objects.append(json.loads(match.group()))
                    except Exception:
                        pass
                if objects:
                    new_selectors = objects
                else:
                    raise json_err

            if not isinstance(new_selectors, list):
                raise ValueError("Response is not a list")

            seen = {s.get('css_selector') for s in all_proposed}
            new_count = 0
            for sel in new_selectors:
                key = sel.get('css_selector', '')
                if key and key not in seen:
                    all_proposed.append(sel)
                    seen.add(key)
                    new_count += 1
            print(f"    Received {len(new_selectors)} selectors, {new_count} new")

            messages.append({"role": "assistant", "content": original_content})

            if turn < num_turns:
                proposed_list = "\n".join([
                    f"- {s.get('css_selector')}: {s.get('description', 'N/A')}"
                    for s in all_proposed
                ])
                follow_up = site.FOLLOW_UP_PROMPT_TEMPLATE.format(
                    num_total=len(all_proposed),
                    proposed_list=proposed_list,
                )
                messages.append({"role": "user", "content": follow_up})

        except Exception as e:
            print(f"    Error in turn {turn}: {e}")
            traceback.print_exc()
            if turn == 1:
                raise
            break

    print(f"  Total unique selectors after {num_turns} turns: {len(all_proposed)}")
    return all_proposed


def generate_config(selectors, version_name):
    config = {
        'version': version_name,
        'generated_by': f'LLM analysis ({LLM_MODEL})',
        'untrusted_selectors': [],
    }
    for sel in selectors:
        if sel.get('confidence') == 'low':
            continue
        css_selector = sel.get('css_selector', '')
        tag_name = sel.get('tag_name', '')
        description = sel.get('description', '')
        confidence = sel.get('confidence', '')
        if not (css_selector and tag_name):
            continue
        css_selector = re.sub(r'\s+', ' ', css_selector).strip()
        config['untrusted_selectors'].append({
            'selector': css_selector,
            'tagName': tag_name,
            'description': description,
            'confidence': confidence,
        })
    return config


def fetch_pages(base_url, pages, site, max_retries=3):
    """Fetch pages with Playwright using the site's fetch settings."""
    html_contents = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"),
            locale="en-US",
        )
        page = context.new_page()

        for page_name, path in pages.items():
            url = f"{base_url}{path}"
            html_contents[page_name] = None

            for attempt in range(1, max_retries + 1):
                try:
                    if attempt > 1:
                        print(f"  Retry {attempt}/{max_retries}...")
                    else:
                        print(f"Fetching {page_name} with browser: {url}")
                    page.goto(url, wait_until=site.FETCH_WAIT_UNTIL, timeout=60000)
                    try:
                        page.wait_for_selector(site.FETCH_WAIT_SELECTOR, timeout=15000)
                    except Exception:
                        pass
                    time.sleep(site.FETCH_EXTRA_SLEEP_SECONDS)
                    html_contents[page_name] = page.content()
                    print(f"  Success: {len(html_contents[page_name])} bytes")
                    break
                except Exception as e:
                    if attempt < max_retries:
                        print(f"  Attempt {attempt} failed: {e}")
                        time.sleep(2)
                    else:
                        print(f"  Error fetching {page_name} after {max_retries} attempts: {e}")
                        html_contents[page_name] = None
        browser.close()
    return html_contents


def load_saved_html(site_dir, pages):
    """Load cached llm_input_original_<basename>.html files."""
    page_file_map = {name: name.replace('_page', '') for name in pages}
    html_contents = {}
    for page_name, file_key in page_file_map.items():
        html_file = site_dir / f'llm_input_original_{file_key}.html'
        if html_file.exists():
            html = html_file.read_text(encoding='utf-8')
            html_contents[page_name] = html
            print(f"  Loaded {html_file.name}: {len(html)} bytes")
        else:
            print(f"  WARNING: {html_file.name} not found")
            html_contents[page_name] = None
    return html_contents


def main():
    parser = argparse.ArgumentParser(
        description='Run the LLM untrusted-element detector for one site.'
    )
    parser.add_argument('--site', required=True,
                        help=f'Site profile. Available: '
                             f'{", ".join(available_sites())}')
    parser.add_argument('--sanitize-only', action='store_true',
                        help='Only clean and strip text from HTML, skip LLM.')
    args = parser.parse_args()

    _load_dotenv_from_repo()
    site = load_site(args.site)

    base_url = os.getenv(site.BASE_URL_ENV, site.BASE_URL_DEFAULT)
    api_key = os.getenv('ANTHROPIC_API_KEY')

    if not args.sanitize_only and not api_key:
        print("Error: ANTHROPIC_API_KEY not found in .env file or environment",
              file=sys.stderr)
        sys.exit(1)

    pages = site.PAGES
    site_dir = site.SITE_DIR

    print("=" * 80)
    print(f"{site.SITE_LABEL} Untrusted Element Detection (Sanitized HTML)")
    print(f"Pages: {len(pages)}")
    for name, path in pages.items():
        print(f"  {name}: {base_url}{path}")
    if args.sanitize_only:
        print("  Mode: --sanitize-only (clean + strip text, skip LLM)")
    print("=" * 80)
    print()

    # Step 1: Load HTML — saved if available + supported, otherwise live fetch.
    print("Step 1: Loading HTML...")
    saved_files_exist = site.USE_SAVED_HTML_FALLBACK and any(
        (site_dir / f'llm_input_original_{name.replace("_page", "")}.html').exists()
        for name in pages
    )
    if saved_files_exist:
        print("  Using saved HTML files:")
        html_contents = load_saved_html(site_dir, pages)
    else:
        print("  Fetching live pages...")
        html_contents = fetch_pages(base_url, pages, site)
        for page_name, html in html_contents.items():
            if html:
                print(f"  {page_name}: {len(html)} bytes")
                with open(site_dir / f'llm_input_original_{page_name}.html', 'w',
                          encoding='utf-8') as f:
                    f.write(html)

    failed = [name for name, html in html_contents.items() if not html]
    if len(failed) == len(pages):
        print("Error: Failed to load all pages", file=sys.stderr)
        sys.exit(1)
    if failed:
        print(f"  Warning: Failed to load: {', '.join(failed)}")

    # Step 2: Clean and sanitize
    print()
    print("Step 2: Cleaning and sanitizing HTML...")
    sanitized_contents = {}
    for page_name, html in html_contents.items():
        if not html:
            continue
        cleaned = site.clean_html_for_llm(html, max_size=site.CLEAN_HTML_MAX_SIZE)
        sanitized = site.sanitize_html_content(cleaned)
        sanitized_contents[page_name] = sanitized
        print(f"  {page_name}: {len(html)} -> {len(cleaned)} -> {len(sanitized)} bytes")
        with open(site_dir / f'llm_input_sanitized_{page_name}.html', 'w',
                  encoding='utf-8') as f:
            f.write(f"<!-- SANITIZED HTML ({page_name}) - text replaced with [text:length:N] -->\n")
            f.write(sanitized)

    if args.sanitize_only:
        print()
        print("Sanitize-only mode complete. Saved sanitized HTML files:")
        for page_name in sanitized_contents:
            print(f"  llm_input_sanitized_{page_name}.html")
        return

    # Step 3: Analyze each page with the LLM
    per_page_selectors = {}
    for page_name, sanitized_html in sanitized_contents.items():
        print()
        print("=" * 80)
        print(f"Step 3: Analyzing {page_name} with LLM "
              f"({site.NUM_LLM_TURNS} iterative turns)")
        print("=" * 80)
        try:
            page_selectors = analyze_with_llm(
                {page_name: sanitized_html}, api_key, site, site.NUM_LLM_TURNS
            )
            per_page_selectors[page_name] = page_selectors
            print(f"  {page_name}: {len(page_selectors)} unique CSS selectors")
        except Exception as e:
            print(f"  Error analyzing {page_name}: {e}")
            traceback.print_exc()
            per_page_selectors[page_name] = []

    all_selectors = []
    seen_selectors = set()
    for page_sels in per_page_selectors.values():
        for sel in page_sels:
            key = sel.get('css_selector', '')
            if key and key not in seen_selectors:
                all_selectors.append(sel)
                seen_selectors.add(key)

    print(f"\n  Combined: {len(all_selectors)} unique selectors from "
          f"{len(per_page_selectors)} pages")
    for page_name, page_sels in per_page_selectors.items():
        print(f"    {page_name}: {len(page_sels)} selectors")

    # Display results
    print()
    print("=" * 80)
    print("RESULTS")
    print("=" * 80)
    high = [s for s in all_selectors if s.get('confidence') == 'high']
    medium = [s for s in all_selectors if s.get('confidence') == 'medium']
    print(f"Total: {len(all_selectors)} (High: {len(high)}, Medium: {len(medium)})")
    for s in all_selectors:
        print(f"  [{s.get('confidence', '?'):6}] "
              f"{s.get('css_selector', ''):50} | {s.get('description', '')}")

    pages_analyzed = {name: path for name, path in pages.items() if html_contents.get(name)}
    with open(site_dir / 'llm_analysis_results.json', 'w') as f:
        json.dump({
            'pages_analyzed': pages_analyzed,
            'methodology': {
                'version': 'sanitized',
                'num_llm_turns': site.NUM_LLM_TURNS,
                'num_pages': len(sanitized_contents),
                'per_page_analysis': True,
                'description': (
                    f'Iterative {site.NUM_LLM_TURNS}-turn approach per page on '
                    f'sanitized HTML (text removed), then union'
                ),
            },
            'per_page_counts': {name: len(sels) for name, sels in per_page_selectors.items()},
            'selectors': all_selectors,
            'num_unique': len(all_selectors),
        }, f, indent=2)

    # Step 4: Generate the config
    print()
    print("Step 4: Generating config file...")
    config = generate_config(all_selectors, "sanitized")
    config_file = site_dir / 'llm_labels.json'
    with open(config_file, 'w') as f:
        json.dump(config, f, indent=2)
    print(f"  Config saved: {config_file}")
    print(f"  Contains {len(config['untrusted_selectors'])} selectors")
    print()
    print(f"Done! Evaluate this config against the pages:")
    print(f"  src/automatic_boundary_detection/pipeline/run_pipeline.sh {args.site} --skip-llm")


if __name__ == '__main__':
    main()
