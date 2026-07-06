#!/usr/bin/env python3
"""Evaluate a selector config on a page using Playwright.

Site-specific page-load behavior (which content to wait for, how to probe DOM stability) comes from sites/<site>/site.py via the PAGE_READY dict.

Usage:
    python pipeline/analyze_selectors.py <url> --site <site> \\
        --config <config.json> --output <results.json>
"""
import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

from playwright.sync_api import sync_playwright

from _site_loader import available_sites, load_site


def wait_for_page_ready(page, url: str, profile: dict) -> bool:
    """Drive Playwright through a site-specific load sequence."""
    label = profile.get("content_label", "content elements")
    try:
        print(f"Loading page: {url}")
        is_local = ('localhost' in url or '127.0.0.1' in url
                    or url.startswith('file://'))
        wait_strategy = (profile["local_wait_until"] if is_local
                         else profile["remote_wait_until"])

        try:
            page.goto(url, wait_until=wait_strategy, timeout=60000)
            print(f"  Page loaded ({wait_strategy})")
        except Exception:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                print("  Page loaded (fallback to domcontentloaded)")
            except Exception as e2:
                print(f"  Warning: Page load timeout, continuing anyway: {e2}")

        try:
            page.wait_for_selector(profile["content_selector"], timeout=15000)
            print(f"  {label} detected")
        except Exception:
            print(f"  Warning: {label} not found (continuing)")

        time.sleep(profile.get("extra_sleep_seconds", 2))

        print("  Waiting for DOM stability...")
        stable_count = 0
        last_signature = None
        max_stable_checks = 2
        probe = profile["stability_probe_js"]
        keys = profile["stability_signature_keys"]
        log_fmt = profile.get("stability_log_format")

        for attempt in range(6):
            if attempt > 0:
                time.sleep(2)
            try:
                counts = page.evaluate(probe)
                signature = tuple(counts.get(k, 0) for k in keys)
                if signature == last_signature:
                    stable_count += 1
                    if stable_count >= max_stable_checks:
                        print(f"  DOM stable after {attempt + 1} checks")
                        if log_fmt:
                            try:
                                print(f"    {log_fmt.format(**counts)}")
                            except Exception:
                                pass
                        break
                else:
                    stable_count = 0
                    last_signature = signature
            except Exception as e:
                print(f"  Warning: Error checking DOM stability: {e}")
                stable_count = 0

        if stable_count < max_stable_checks:
            print("  Warning: DOM may not be fully stable")

        print("  Page ready for analysis")
        return True
    except Exception as e:
        print(f"  Error loading page: {e}")
        return False


GET_ELEMENTS_JS = """
(selector) => {
    const elements = Array.from(document.querySelectorAll(selector));
    function getXPath(element) {
        if (element.id !== '') {
            return '//*[@id="' + element.id + '"]';
        }
        if (element === document.body) return '/html/body';
        if (element === document.documentElement) return '/html';
        if (!element.parentNode) return null;
        let ix = 0;
        const siblings = element.parentNode.childNodes;
        for (let i = 0; i < siblings.length; i++) {
            const sibling = siblings[i];
            if (sibling === element) {
                const parentPath = getXPath(element.parentNode);
                if (!parentPath) return null;
                return parentPath + '/' + element.tagName.toLowerCase() +
                       '[' + (ix + 1) + ']';
            }
            if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
                ix++;
            }
        }
        return null;
    }
    return elements.map(el => {
        try {
            return {
                xpath: getXPath(el),
                tagName: el.tagName.toLowerCase(),
                id: el.id || '',
                className: el.className || '',
                textPreview: (el.textContent || '').trim().substring(0, 100),
            };
        } catch (e) {
            return { xpath: null, error: e.toString() };
        }
    });
}
"""


def get_elements_with_ids(page, selector: str) -> List[Dict]:
    try:
        elements_data = page.evaluate(GET_ELEMENTS_JS, selector)
    except Exception:
        return []
    return [
        {
            "xpath": elem.get("xpath"),
            "tagName": elem.get("tagName", ""),
            "id": elem.get("id", ""),
            "className": elem.get("className", ""),
            "textPreview": elem.get("textPreview", ""),
        }
        for elem in elements_data
    ]


def analyze_selectors(config_file: str, url: str, profile: dict,
                     output_file: str = None):
    with open(config_file, 'r') as f:
        config = json.load(f)

    if 'untrusted_selectors' not in config:
        print("Error: Config file must have 'untrusted_selectors' array",
              file=sys.stderr)
        sys.exit(1)

    selectors = config['untrusted_selectors']
    print(f"Analyzing {len(selectors)} selectors on: {url}\n")

    results = []
    total_elements = 0
    selectors_with_matches = 0
    all_unique_element_ids = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        )
        page = context.new_page()

        if not wait_for_page_ready(page, url, profile):
            print("Error loading page", file=sys.stderr)
            browser.close()
            sys.exit(1)
        print()

        for idx, item in enumerate(selectors, 1):
            selector = item.get('selector', '')
            tag_name = item.get('tagName', 'unknown')
            description = item.get('description', '')
            try:
                count = page.locator(selector).count()
                total_elements += count
                if count > 0:
                    selectors_with_matches += 1

                elements_with_ids = get_elements_with_ids(page, selector)

                previews = []
                for i, elem in enumerate(elements_with_ids[:5]):
                    text_preview = elem.get('textPreview', '')[:100].strip()
                    previews.append({
                        "index": i + 1,
                        "text_preview": text_preview or "(empty)",
                    })

                all_element_ids = [
                    elem.get('xpath') for elem in elements_with_ids
                    if elem.get('xpath')
                ]

                element_info = {}
                for elem in elements_with_ids:
                    xpath = elem.get('xpath')
                    if xpath:
                        element_info[xpath] = {
                            "tagName": elem.get('tagName', ''),
                            "className": elem.get('className', ''),
                            "id": elem.get('id', ''),
                            "textPreview": elem.get('textPreview', ''),
                        }

                all_unique_element_ids.update(all_element_ids)

                results.append({
                    "index": idx,
                    "selector": selector,
                    "tagName": tag_name,
                    "description": description,
                    "count": count,
                    "element_ids": all_element_ids,
                    "element_info": element_info,
                    "previews": previews,
                })

                status = "Y" if count > 0 else "N"
                print(f"{status} [{idx:3d}] {selector}")
                print(f"      Tag: {tag_name} | Matches: {count}")
                if 0 < count <= 5:
                    for preview in previews:
                        print(f"      [{preview['index']}] \"{preview['text_preview']}\"")
                print()

            except Exception as e:
                results.append({
                    "index": idx,
                    "selector": selector,
                    "tagName": tag_name,
                    "description": description,
                    "count": 0,
                    "element_ids": [],
                    "previews": [],
                    "error": str(e),
                })
                print(f"N [{idx:3d}] {selector} - ERROR: {e}\n")

        browser.close()

    summary = {
        "totalSelectors": len(selectors),
        "selectorsWithMatches": selectors_with_matches,
        "totalElements": total_elements,
        "uniqueElements": len(all_unique_element_ids),
        "url": url,
        "configFile": config_file,
        "configVersion": config.get('version', 'unknown'),
        "configGeneratedBy": config.get('generated_by', 'unknown'),
    }
    output_data = {"summary": summary, "results": results}

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total Selectors:         {summary['totalSelectors']}")
    print(f"Selectors with Matches:  {summary['selectorsWithMatches']}")
    print(f"Total Element Matches:   {summary['totalElements']}")
    print(f"Unique Elements:         {summary['uniqueElements']}")
    print(f"Config Version:          {summary['configVersion']}")
    print(f"Page URL:                {summary['url']}")
    print("=" * 60 + "\n")

    if output_file:
        with open(output_file, 'w') as f:
            json.dump(output_data, f, indent=2)
        print(f"Results saved to: {output_file}\n")
    return output_data


def main():
    parser = argparse.ArgumentParser(
        description='Evaluate a selector config on a page (site-aware).'
    )
    parser.add_argument('url', help='URL to analyze')
    parser.add_argument('--site', required=True,
                        help=f'Site profile to use. Available: '
                             f'{", ".join(available_sites())}')
    parser.add_argument('--config', '-c', required=True,
                        help='Path to config JSON file')
    parser.add_argument('--output', '-o', help='Output JSON file')
    args = parser.parse_args()

    if not Path(args.config).exists():
        print(f"Error: Config file not found: {args.config}", file=sys.stderr)
        sys.exit(1)

    site = load_site(args.site)
    analyze_selectors(args.config, args.url, site.PAGE_READY, args.output)


if __name__ == '__main__':
    main()
