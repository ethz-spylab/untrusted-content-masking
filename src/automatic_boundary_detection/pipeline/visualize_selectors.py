#!/usr/bin/env python3
"""
Visualize selector configs on a live web page.

Takes two config files (hand-labeled ground truth and LLM-generated), loads the page twice with different CSS highlights, takes full-page screenshots, and generates a side-by-side HTML comparison page.

Pass --img-replaced-handling for pages with image-heavy layouts (Booking.com): outline/box-shadow CSS doesn't render on replaced elements like <img>/<picture>, so we switch them to a desaturated border + opacity treatment instead.

Usage:
    python pipeline/visualize_selectors.py \\
        --url <PAGE_URL> \\
        --hand <PATH>/hand_labels.json \\
        --llm <PATH>/llm_labels.json \\
        --output <RESULTS_DIR>/
"""

import json
import argparse
import time
import base64
from pathlib import Path
from urllib.parse import urlparse, urlencode, urlunparse, parse_qs
import requests
from playwright.sync_api import sync_playwright


def set_reveal_mode(page_url, mode):
    """Toggle the real hiding system: 'all' (disable hiding), 'trusted' (enable hiding)."""
    parsed = urlparse(page_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    try:
        resp = requests.post(f"{base_url}/set-reveal-mode?mode={mode}", timeout=5)
        print(f"  Set reveal mode to '{mode}': {resp.status_code}")
    except Exception as e:
        print(f"  Warning: Could not set reveal mode to '{mode}': {e}")


def add_reveal_all_param(url):
    """Append ?reveal_all=true to URL as client-side backup to disable hiding."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    params['reveal_all'] = ['true']
    new_query = urlencode(params, doseq=True)
    return urlunparse(parsed._replace(query=new_query))


def wait_for_page_ready(page, timeout=60):
    """Wait for auto-login redirect chain to complete and page content to load."""
    # Wait for auto-login to complete (nginx injects auto-login.js which may
    # redirect to /users/sign_in, fill the form, submit, then redirect back)
    for i in range(timeout // 2):
        current_url = page.url
        if '/users/sign_in' not in current_url:
            break
        time.sleep(2)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except:
            pass
    else:
        print(f"    Warning: Still on login page after {timeout}s")

    # Wait for GitLab content
    try:
        page.wait_for_selector(
            '#content-body, .project-home-panel, .issuable-list, .file-content, .user-profile',
            timeout=15000
        )
    except:
        pass

    # Wait for async Vue.js content (file tree, commit info) to load
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except:
        pass

    # Also wait for file tree rows to appear (they load via API)
    try:
        page.wait_for_selector(
            '.tree-item .tree-item-file-name, .commit-row-message, .committer',
            timeout=15000
        )
    except:
        pass

    time.sleep(3)


def build_highlight_css(config, color, border_color, img_replaced=False):
    """Build CSS that highlights all elements matching selectors in the config."""
    rules = []
    for item in config.get('untrusted_selectors', []):
        selector = item.get('selector', '')
        if not selector:
            continue
        rules.append(
            f'{selector} {{ '
            f'outline: 3px solid {border_color} !important; '
            f'background-color: {color} !important; '
            f'outline-offset: 1px; '
            f'}}'
        )
        if img_replaced:
            # outline/box-shadow don't render on replaced elements (img/picture);
            # use a desaturated border + opacity treatment instead.
            rules.append(
                f'{selector}:is(img, picture) {{ '
                f'outline: none !important; '
                f'border: 6px solid {border_color} !important; '
                f'box-sizing: border-box !important; '
                f'opacity: 0.85 !important; '
                f'filter: saturate(0.5) !important; '
                f'}}'
            )
    return '\n'.join(rules)


def take_screenshot(url, config, css_color, css_border, output_path, label,
                    img_replaced=False):
    """Load page, inject highlight CSS, take full-page screenshot."""
    print(f"  Taking screenshot: {label}...")

    # Disable real hiding system so we see raw page content
    set_reveal_mode(url, "all")
    load_url = add_reveal_all_param(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        # Load page — GitLab may redirect (auto-login, etc.) so retry
        for attempt in range(3):
            try:
                page.goto(load_url, wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as e:
                if attempt < 2:
                    print(f"    Page load attempt {attempt + 1} failed, retrying...")
                    time.sleep(2)
                else:
                    print(f"    Warning: Page load failed after 3 attempts: {e}")

        wait_for_page_ready(page)

        # Inject highlight CSS with retries
        css = build_highlight_css(config, css_color, css_border, img_replaced=img_replaced)
        for attempt in range(3):
            try:
                page.add_style_tag(content=css)
                break
            except Exception as e:
                if attempt < 2:
                    print(f"    CSS injection attempt {attempt + 1} failed, waiting for navigation to settle...")
                    time.sleep(3)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except:
                        pass
                else:
                    # Last resort: inject via evaluate
                    print(f"    add_style_tag failed, injecting CSS via evaluate...")
                    escaped_css = css.replace('\\', '\\\\').replace('`', '\\`')
                    page.evaluate(f"""
                        () => {{
                            const style = document.createElement('style');
                            style.textContent = `{escaped_css}`;
                            document.head.appendChild(style);
                        }}
                    """)

        # Add a label banner at the top
        try:
            page.evaluate(f"""
                () => {{
                    const banner = document.createElement('div');
                    banner.textContent = '{label}';
                    banner.style.cssText = 'position:fixed; top:0; left:0; right:0; z-index:99999; ' +
                        'background:{css_border}; color:white; padding:8px 16px; font-size:18px; ' +
                        'font-weight:bold; text-align:center; font-family:sans-serif;';
                    document.body.prepend(banner);
                    document.body.style.paddingTop = '40px';
                }}
            """)
        except Exception as e:
            print(f"    Warning: Could not add banner: {e}")

        time.sleep(1)

        page.screenshot(path=str(output_path), full_page=True, timeout=60000)
        print(f"    Saved: {output_path}")

        browser.close()

    # Restore hiding
    set_reveal_mode(url, "trusted")


def build_hiding_js(config, img_replaced=False):
    """Build JavaScript that hides elements and shows labeled placeholders, like reveal.js."""
    # Build the selectors array as JSON for the JS code
    selectors_json = json.dumps([
        {"selector": item.get("selector", ""), "tagName": item.get("tagName", "element")}
        for item in config.get("untrusted_selectors", [])
        if item.get("selector")
    ])

    # Replaced elements (<img>/<picture>) can't host ::before pseudo-elements or have their children hidden; we wrap them so the placeholder lives on a
    # block-level container instead. Only injected when --img-replaced-handling.
    img_replaced_branch = """
                    if (el.tagName === 'IMG' || el.tagName === 'PICTURE') {
                        const wrapper = document.createElement('div');
                        wrapper.style.cssText = 'position:relative; display:inline-block; overflow:hidden;';
                        wrapper.setAttribute('data-reveal-placeholder', 'id: ' + qllmId);
                        wrapper.setAttribute('data-tag-name', tag);
                        wrapper.setAttribute('data-untrusted-element', 'true');
                        wrapper.classList.add('reveal-hidden');
                        el.parentNode.insertBefore(wrapper, el);
                        wrapper.appendChild(el);
                        return;
                    }
    """ if img_replaced else ""

    return """
    (function() {
        const selectors = """ + selectors_json + """;
        const tagCounters = {};

        selectors.forEach(function(cfg) {
            try {
                const elements = document.querySelectorAll(cfg.selector);
                elements.forEach(function(el) {
                    // Skip if already processed
                    if (el.hasAttribute('data-viz-hidden')) return;
                    el.setAttribute('data-viz-hidden', 'true');

                    // Assign unique ID: tagName-N
                    const tag = cfg.tagName || 'element';
                    if (!(tag in tagCounters)) tagCounters[tag] = 0;
                    const qllmId = tag + '-' + tagCounters[tag]++;
                    el.setAttribute('data-reveal-placeholder', 'id: ' + qllmId);
                    el.setAttribute('data-tag-name', tag);
""" + img_replaced_branch + """
                    // Wrap bare text nodes in spans so CSS > * rule can hide them
                    Array.from(el.childNodes).forEach(function(node) {
                        if (node.nodeType === Node.TEXT_NODE && node.textContent.trim()) {
                            const wrapper = document.createElement('span');
                            wrapper.className = 'reveal-text-wrap';
                            node.parentNode.insertBefore(wrapper, node);
                            wrapper.appendChild(node);
                        }
                    });

                    // Mark as hidden
                    el.classList.add('reveal-hidden');
                    el.setAttribute('data-untrusted-element', 'true');
                });
            } catch(e) {
                // Invalid selector, skip
            }
        });
    })();
    """


HIDING_CSS = """
/* Hide children of marked elements */
[data-untrusted-element].reveal-hidden {
    position: relative;
    visibility: visible;
    opacity: 1;
    overflow: hidden;
}
[data-untrusted-element].reveal-hidden > * {
    display: none !important;
}
/* Prevent nested double-hiding */
[data-untrusted-element].reveal-hidden [data-untrusted-element].reveal-hidden {
    display: none !important;
    visibility: hidden !important;
    min-height: 0 !important;
    min-width: 0 !important;
}
[data-untrusted-element].reveal-hidden [data-untrusted-element].reveal-hidden::before {
    display: none !important;
}
/* Placeholder box */
[data-untrusted-element].reveal-hidden[data-reveal-placeholder] {
    position: relative;
    min-height: 30px;
    min-width: 120px;
    display: inline-block !important;
}
[data-untrusted-element].reveal-hidden[data-reveal-placeholder]::before {
    content: attr(data-reveal-placeholder);
    display: flex !important;
    align-items: center;
    justify-content: center;
    visibility: visible !important;
    opacity: 1 !important;
    padding: 8px 12px;
    background-color: #ecf0f1;
    border: 2px dashed #e74c3c;
    border-radius: 2px;
    text-align: center;
    color: #7f8c8d;
    font-style: italic;
    position: absolute;
    top: 0; left: 0; right: 0; bottom: 0;
    z-index: 10;
    min-height: 30px;
    min-width: 120px;
    font-size: 0.85em;
    line-height: 1.3;
    white-space: nowrap;
    overflow: visible;
}
/* Smaller placeholder for avatar-sized elements */
[data-untrusted-element].reveal-hidden[data-tag-name*="avatar"][data-reveal-placeholder] {
    min-height: 36px !important;
    min-width: 36px !important;
}
[data-untrusted-element].reveal-hidden[data-tag-name*="avatar"][data-reveal-placeholder]::before {
    min-height: 36px !important;
    min-width: 36px !important;
    font-size: 0.7em !important;
    padding: 4px !important;
    border-radius: 50%;
}
"""


def take_hidden_screenshot(url, config, output_path, label, img_replaced=False):
    """Load page, hide elements matching config selectors with labeled placeholders."""
    print(f"  Taking hidden screenshot: {label}...")

    # Disable real hiding system so we start from a clean page
    set_reveal_mode(url, "all")
    load_url = add_reveal_all_param(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
        )
        page = context.new_page()

        for attempt in range(3):
            try:
                page.goto(load_url, wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as e:
                if attempt < 2:
                    print(f"    Page load attempt {attempt + 1} failed, retrying...")
                    time.sleep(2)
                else:
                    print(f"    Warning: Page load failed after 3 attempts: {e}")

        wait_for_page_ready(page)

        # Inject hiding CSS
        for attempt in range(3):
            try:
                page.add_style_tag(content=HIDING_CSS)
                break
            except Exception:
                if attempt < 2:
                    time.sleep(3)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except:
                        pass
                else:
                    page.evaluate("""
                        () => {
                            const style = document.createElement('style');
                            style.textContent = """ + json.dumps(HIDING_CSS) + """;
                            document.head.appendChild(style);
                        }
                    """)

        # Inject hiding JS
        hiding_js = build_hiding_js(config, img_replaced=img_replaced)
        for attempt in range(3):
            try:
                page.evaluate(hiding_js)
                break
            except Exception as e:
                if attempt < 2:
                    print(f"    JS injection attempt {attempt + 1} failed, retrying...")
                    time.sleep(3)
                else:
                    print(f"    Warning: Could not inject hiding JS: {e}")

        # Add banner
        try:
            page.evaluate(f"""
                () => {{
                    const banner = document.createElement('div');
                    banner.textContent = '{label}';
                    banner.style.cssText = 'position:fixed; top:0; left:0; right:0; z-index:99999; ' +
                        'background:#e74c3c; color:white; padding:8px 16px; font-size:18px; ' +
                        'font-weight:bold; text-align:center; font-family:sans-serif;';
                    document.body.prepend(banner);
                    document.body.style.paddingTop = '40px';
                }}
            """)
        except Exception as e:
            print(f"    Warning: Could not add banner: {e}")

        time.sleep(1)

        page.screenshot(path=str(output_path), full_page=True, timeout=60000)
        print(f"    Saved: {output_path}")

        browser.close()

    # Restore hiding
    set_reveal_mode(url, "trusted")


def build_overlay_js(hand_config, llm_config, parent_aware=False):
    """Build JS that tags elements as TP/FN/FP based on both configs."""
    hand_selectors = [item.get('selector', '') for item in hand_config.get('untrusted_selectors', []) if item.get('selector')]
    llm_selectors = [item.get('selector', '') for item in llm_config.get('untrusted_selectors', []) if item.get('selector')]

    return """
    (function() {
        const handSelectors = """ + json.dumps(hand_selectors) + """;
        const llmSelectors = """ + json.dumps(llm_selectors) + """;

        // Tag elements matched by hand (ground truth)
        handSelectors.forEach(function(sel) {
            try {
                document.querySelectorAll(sel).forEach(function(el) {
                    el.setAttribute('data-viz-hand', 'true');
                });
            } catch(e) {}
        });

        // Tag elements matched by LLM
        llmSelectors.forEach(function(sel) {
            try {
                document.querySelectorAll(sel).forEach(function(el) {
                    el.setAttribute('data-viz-llm', 'true');
                });
            } catch(e) {}
        });

        // Classify: TP (both), FN (hand only), FP (LLM only)
        var tp = 0, fn = 0, fp = 0;
        document.querySelectorAll('[data-viz-hand]').forEach(function(el) {
            if (el.hasAttribute('data-viz-llm')) {
                el.setAttribute('data-viz-class', 'tp');
                tp++;
            } else {
                el.setAttribute('data-viz-class', 'fn');
                fn++;
            }
        });
        document.querySelectorAll('[data-viz-llm]:not([data-viz-hand])').forEach(function(el) {
            el.setAttribute('data-viz-class', 'fp');
            fp++;
        });

""" + ("""
        // Reclassify FN: if a hand-only element has an LLM-matched ancestor -> TP
        document.querySelectorAll('[data-viz-class="fn"]').forEach(function(el) {
            var p = el.parentElement;
            while (p) {
                if (p.hasAttribute('data-viz-llm')) {
                    el.setAttribute('data-viz-class', 'tp');
                    fn--; tp++;
                    break;
                }
                p = p.parentElement;
            }
        });

        // Reclassify FN: if a hand-only element has an LLM-matched descendant -> TP
        document.querySelectorAll('[data-viz-class="fn"]').forEach(function(el) {
            if (el.querySelector('[data-viz-llm]')) {
                el.setAttribute('data-viz-class', 'tp');
                fn--; tp++;
            }
        });

        // Reclassify FP: if an LLM-only element has a hand-matched ancestor -> TP
        document.querySelectorAll('[data-viz-class="fp"]').forEach(function(el) {
            var p = el.parentElement;
            while (p) {
                if (p.hasAttribute('data-viz-hand')) {
                    el.setAttribute('data-viz-class', 'tp');
                    fp--; tp++;
                    break;
                }
                p = p.parentElement;
            }
        });

        // Reclassify FP: if an LLM-only element has a hand-matched descendant -> TP
        document.querySelectorAll('[data-viz-class="fp"]').forEach(function(el) {
            if (el.querySelector('[data-viz-hand]')) {
                el.setAttribute('data-viz-class', 'tp');
                fp--; tp++;
            }
        });
""" if parent_aware else "") + """
        console.log('Overlay: TP=' + tp + ' FN=' + fn + ' FP=' + fp);
    })();
    """


OVERLAY_CSS = """
/* TP: correctly matched by both (green) */
[data-viz-class="tp"] {
    outline: 3px solid #28a745 !important;
    background-color: rgba(40, 167, 69, 0.15) !important;
    outline-offset: 1px;
}
/* FN: missed by LLM, only in ground truth (red) */
[data-viz-class="fn"] {
    outline: 3px solid #dc3545 !important;
    background-color: rgba(220, 53, 69, 0.15) !important;
    outline-offset: 1px;
}
/* FP: over-hidden by LLM, not in ground truth (blue) */
[data-viz-class="fp"] {
    outline: 3px solid #0064dc !important;
    background-color: rgba(0, 100, 220, 0.15) !important;
    outline-offset: 1px;
}
"""

# Replaced-element variants for image-heavy pages (Booking.com): outline/box-shadow
# don't render on <img>/<picture>, so use a desaturated border + opacity instead.
OVERLAY_CSS_IMG_REPLACED = """
[data-viz-class="tp"]:is(img, picture) {
    outline: none !important;
    border: 6px solid #28a745 !important;
    box-sizing: border-box !important;
    opacity: 0.85 !important;
    filter: saturate(0.5) !important;
}
[data-viz-class="fn"]:is(img, picture) {
    outline: none !important;
    border: 6px solid #dc3545 !important;
    box-sizing: border-box !important;
    opacity: 0.85 !important;
    filter: saturate(0.5) !important;
}
[data-viz-class="fp"]:is(img, picture) {
    outline: none !important;
    border: 6px solid #0064dc !important;
    box-sizing: border-box !important;
    opacity: 0.85 !important;
    filter: saturate(0.5) !important;
}
"""


def take_overlay_screenshot(url, hand_config, llm_config, output_path,
                            parent_aware=False, img_replaced=False):
    """Load page once, classify elements as TP/FN/FP, take single screenshot."""
    print(f"  Taking overlay screenshot...")

    set_reveal_mode(url, "all")
    load_url = add_reveal_all_param(url)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080})
        page = context.new_page()

        for attempt in range(3):
            try:
                page.goto(load_url, wait_until="domcontentloaded", timeout=60000)
                break
            except Exception as e:
                if attempt < 2:
                    print(f"    Page load attempt {attempt + 1} failed, retrying...")
                    time.sleep(2)
                else:
                    print(f"    Warning: Page load failed after 3 attempts: {e}")

        wait_for_page_ready(page)

        # Inject classification JS
        overlay_js = build_overlay_js(hand_config, llm_config, parent_aware=parent_aware)
        for attempt in range(3):
            try:
                page.evaluate(overlay_js)
                break
            except Exception as e:
                if attempt < 2:
                    time.sleep(3)
                else:
                    print(f"    Warning: Could not inject overlay JS: {e}")

        # Inject overlay CSS
        overlay_css = OVERLAY_CSS + (OVERLAY_CSS_IMG_REPLACED if img_replaced else "")
        for attempt in range(3):
            try:
                page.add_style_tag(content=overlay_css)
                break
            except Exception:
                if attempt < 2:
                    time.sleep(3)
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except:
                        pass
                else:
                    escaped = overlay_css.replace('\\', '\\\\').replace('`', '\\`')
                    page.evaluate(f"""
                        () => {{
                            const style = document.createElement('style');
                            style.textContent = `{escaped}`;
                            document.head.appendChild(style);
                        }}
                    """)

        # Add legend banner
        try:
            page.evaluate("""
                () => {
                    const banner = document.createElement('div');
                    banner.innerHTML = '<span style="color:#28a745">■</span> Correct (TP) &nbsp;&nbsp; ' +
                        '<span style="color:#dc3545">■</span> Missed by LLM (FN) &nbsp;&nbsp; ' +
                        '<span style="color:#0064dc">■</span> Over-hidden by LLM (FP)';
                    banner.style.cssText = 'position:fixed; top:0; left:0; right:0; z-index:99999; ' +
                        'background:#2d2d2d; color:white; padding:10px 16px; font-size:16px; ' +
                        'font-weight:bold; text-align:center; font-family:sans-serif;';
                    document.body.prepend(banner);
                    document.body.style.paddingTop = '40px';
                }
            """)
        except Exception as e:
            print(f"    Warning: Could not add legend: {e}")

        time.sleep(1)
        page.screenshot(path=str(output_path), full_page=True, timeout=60000)
        print(f"    Saved: {output_path}")
        browser.close()

    set_reveal_mode(url, "trusted")


def generate_comparison_html(hand_img, llm_img, output_path, metrics_file=None):
    """Generate an HTML page showing both screenshots side by side."""

    # Read metrics if available
    metrics_html = ""
    if metrics_file and Path(metrics_file).exists():
        with open(metrics_file, 'r') as f:
            metrics = json.load(f)
        m = metrics.get('metrics', {})
        metrics_html = f"""
        <div style="text-align:center; margin:20px 0; font-family:sans-serif;">
            <b>Precision:</b> {m.get('precision', 0):.1%} &nbsp;|&nbsp;
            <b>Recall:</b> {m.get('recall', 0):.1%} &nbsp;|&nbsp;
            <b>F1:</b> {m.get('f1_score', 0):.1%} &nbsp;|&nbsp;
            <b>TP:</b> {m.get('tp_count', 0)} &nbsp;
            <b>FP:</b> {m.get('fp_count', 0)} &nbsp;
            <b>FN:</b> {m.get('fn_count', 0)}
        </div>"""

    # Encode images as base64 so HTML is self-contained
    hand_b64 = base64.b64encode(Path(hand_img).read_bytes()).decode()
    llm_b64 = base64.b64encode(Path(llm_img).read_bytes()).decode()

    html = f"""<!DOCTYPE html>
<html>
<head>
<title>Selector Comparison: Hand vs LLM</title>
<style>
    body {{ margin: 0; padding: 0; background: #1a1a1a; color: white; font-family: sans-serif; }}
    h1 {{ text-align: center; padding: 20px 0 5px; margin: 0; font-size: 24px; }}
    .container {{ display: flex; gap: 4px; padding: 10px; height: calc(100vh - 100px); }}
    .panel {{ flex: 1; overflow: auto; border: 2px solid #444; border-radius: 4px; }}
    .panel img {{ width: 100%; display: block; }}
    .panel-header {{ text-align: center; padding: 8px; font-weight: bold; font-size: 16px; position: sticky; top: 0; z-index: 1; }}
    .hand-header {{ background: rgba(0,180,0,0.9); }}
    .llm-header {{ background: rgba(0,100,220,0.9); }}
    .sync-scroll {{ overflow-y: auto; }}
</style>
</head>
<body>
    <h1>Selector Comparison: Ground Truth vs LLM (Scraped)</h1>
    {metrics_html}
    <div class="container">
        <div class="panel" id="left">
            <div class="panel-header hand-header">Hand-Labeled Ground Truth (green)</div>
            <img src="data:image/png;base64,{hand_b64}" alt="Hand selectors">
        </div>
        <div class="panel" id="right">
            <div class="panel-header llm-header">LLM-Generated from Scraped HTML (blue)</div>
            <img src="data:image/png;base64,{llm_b64}" alt="LLM selectors">
        </div>
    </div>
    <script>
        // Sync scrolling between panels
        const left = document.getElementById('left');
        const right = document.getElementById('right');
        let syncing = false;
        left.addEventListener('scroll', () => {{
            if (syncing) return;
            syncing = true;
            right.scrollTop = left.scrollTop;
            syncing = false;
        }});
        right.addEventListener('scroll', () => {{
            if (syncing) return;
            syncing = true;
            left.scrollTop = right.scrollTop;
            syncing = false;
        }});
    </script>
</body>
</html>"""

    with open(output_path, 'w') as f:
        f.write(html)
    print(f"  Comparison HTML: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Visualize hand vs LLM selectors side by side'
    )
    parser.add_argument('--url', default='http://localhost:8103/byteblaze/a11y-syntax-highlighting',
                        help='GitLab page URL')
    parser.add_argument('--hand', default='hand_labels.json',
                        help='Hand-labeled config JSON')
    parser.add_argument('--llm', required=True,
                        help='LLM-generated config JSON')
    parser.add_argument('--output', '-o', required=True,
                        help='Output directory for screenshots and HTML')
    parser.add_argument('--metrics', default=None,
                        help='Path to comparison_metrics.json (optional, for showing stats)')
    parser.add_argument('--hide', action='store_true',
                        help='Hide mode: replace matched elements with labeled placeholders (like reveal.js)')
    parser.add_argument('--side-by-side', action='store_true',
                        help='Side-by-side mode: two separate screenshots')
    parser.add_argument('--parent-aware', action='store_true',
                        help='Reclassify FN/FP elements covered by an ancestor (matches metrics logic)')
    parser.add_argument('--img-replaced-handling', action='store_true',
                        help='Use desaturated borders for <img>/<picture> (replaced elements). '
                             'Set this for image-heavy pages like Booking.com.')

    args = parser.parse_args()
    img_replaced = args.img_replaced_handling

    # Resolve paths relative to script directory
    script_dir = Path(__file__).parent
    llm_path = script_dir / args.llm if not Path(args.llm).is_absolute() else Path(args.llm)
    output_dir = script_dir / args.output if not Path(args.output).is_absolute() else Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(llm_path, 'r') as f:
        llm_config = json.load(f)

    hand_path = script_dir / args.hand if not Path(args.hand).is_absolute() else Path(args.hand)
    with open(hand_path, 'r') as f:
        hand_config = json.load(f)

    print(f"Hand config: {len(hand_config.get('untrusted_selectors', []))} selectors")
    print(f"LLM config:  {len(llm_config.get('untrusted_selectors', []))} selectors")
    print(f"URL: {args.url}")

    if args.hide:
        # Hide mode: replace matched elements with labeled placeholders
        print(f"Mode: HIDE (placeholder labels)")
        print()

        hidden_img = output_dir / 'screenshot_llm_hidden.png'
        take_hidden_screenshot(
            args.url, llm_config,
            output_path=hidden_img,
            label='LLM-Generated Hiding (Scraped HTML)',
            img_replaced=img_replaced,
        )
        print()
        print(f"Hidden screenshot: {hidden_img}")

    elif args.side_by_side:
        # Side-by-side: two separate screenshots
        print(f"Mode: SIDE-BY-SIDE")
        print()

        hand_img = output_dir / 'screenshot_hand.png'
        llm_img = output_dir / 'screenshot_llm.png'

        take_screenshot(
            args.url, hand_config,
            css_color='rgba(0, 200, 0, 0.15)',
            css_border='#00b400',
            output_path=hand_img,
            label='Ground Truth (Hand-Labeled)',
            img_replaced=img_replaced,
        )

        take_screenshot(
            args.url, llm_config,
            css_color='rgba(0, 100, 220, 0.15)',
            css_border='#0064dc',
            output_path=llm_img,
            label='LLM-Generated (Scraped HTML)',
            img_replaced=img_replaced,
        )

        metrics_file = args.metrics
        if not metrics_file:
            candidate = output_dir / 'comparison_metrics.json'
            if candidate.exists():
                metrics_file = str(candidate)

        print()
        generate_comparison_html(hand_img, llm_img, output_dir / 'comparison.html', metrics_file)

        print()
        print(f"Open in browser: {output_dir / 'comparison.html'}")

    else:
        # Default: overlay + individual highlight screenshots
        print(f"Mode: OVERLAY + HIGHLIGHTS")
        print()

        overlay_img = output_dir / 'screenshot_overlay.png'
        hand_img = output_dir / 'screenshot_hand.png'
        llm_img = output_dir / 'screenshot_llm.png'

        take_overlay_screenshot(
            args.url, hand_config, llm_config,
            output_path=overlay_img,
            parent_aware=args.parent_aware,
            img_replaced=img_replaced,
        )

        take_screenshot(
            args.url, hand_config,
            css_color='rgba(0, 200, 0, 0.15)',
            css_border='#00b400',
            output_path=hand_img,
            label='Ground Truth (Hand-Labeled)',
            img_replaced=img_replaced,
        )

        take_screenshot(
            args.url, llm_config,
            css_color='rgba(0, 100, 220, 0.15)',
            css_border='#0064dc',
            output_path=llm_img,
            label='LLM-Generated (Scraped HTML)',
            img_replaced=img_replaced,
        )

        print()
        print(f"Overlay:   {overlay_img}")
        print(f"Hand:      {hand_img}")
        print(f"LLM:       {llm_img}")


if __name__ == '__main__':
    main()
