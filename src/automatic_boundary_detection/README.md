# Automatic Boundary Detection

This folder contains the end-to-end pipeline for the paper's automatic
boundary-detection experiment. For each of three target sites —
**Booking.com**, **Reddit**, and **GitLab** — the LLM is given a sanitized
copy of the page HTML and asked to produce CSS selectors that identify the
untrusted, user-generated regions of the page. The generated selectors are
then evaluated against hand-labelled ground truth on the live (or cached)
page and scored using signature-F1.

## What you get

After running the pipeline, `results/<site>/run_N/` contains everything you
need to inspect a single trial:

```
results/booking/run_1/
├── homepage/
│   ├── hand_labels.json              # hand-edited ground truth selectors
│   ├── llm_labels.json               # what the LLM proposed for this trial
│   ├── hand_results.json             # elements the hand selectors matched on the page
│   ├── llm_results.json              # elements the LLM selectors matched on the page
│   ├── comparison_metrics.json       # TP / FP / FN broken down by selector + signature
│   ├── plot_metrics.{png,pdf}        # bar chart of per-selector hits
│   ├── plot_metrics_group.{png,pdf}  # bar chart aggregated by tag.class signature
│   ├── screenshot_hand.png           # full-page screenshot, hand selectors highlighted
│   ├── screenshot_llm.png            # full-page screenshot, LLM selectors highlighted
│   └── screenshot_overlay.png        # both overlaid (green = TP, red = FP, etc.)
├── search/  ... same structure
├── hotel/   ... same structure
├── merged_metrics.json               # F1 / precision / recall across all 3 pages
├── merged_plot_metrics.{png,pdf}     # bar chart across all pages
└── summary_all_pages.json            # per-page TP/FP/FN in one flat file
```

## Current results (in `results/`)

We ship our own runs of the pipeline under `results/<site>/run_{1,2,3}/`:

| Site | run 1 | run 2 | run 3 | F1 mean ± std |
|---|---:|---:|---:|---:|
| Booking | 0.9057 | 0.8571 | 0.8727 | 0.8785 ± 0.0202 |
| Reddit  | 1.0000 | 0.9953 | 0.9944 | 0.9966 ± 0.0025 |
| GitLab  | 0.8473 | 0.8426 | 0.8290 | 0.8396 ± 0.0078 |

Everything — metrics, screenshots, and per-page breakdowns — is already in
`results/`, so you can inspect our runs without running anything. To reproduce
them or run fresh trials on the same three sites, see
[Running it yourself](#running-it-yourself); to evaluate a brand-new site, see
[Adding a new site](#adding-a-new-site).

## Running it yourself

### Prerequisites

**Base setup (one-time).** Python dependencies, Chromium for Playwright, and
the `ANTHROPIC_API_KEY` all come from the
[project root README — Setup](../../README.md#setup). Make sure you have run
`uv sync` and `uv run playwright install chromium` before invoking the
pipeline.

**Booking and Reddit** need their page snapshots fetched and then served
locally — the repo does not ship them:

1. **Fetch the cached HTML.** Snapshots (`llm_input_original_<page>.html`) are
   not included; recreate them from the live site with the per-site fetch
   script:

   ```bash
   python sites/booking/fetch_and_preview.py
   python sites/reddit/fetch_and_preview.py
   ```

   Each script opens Playwright, navigates to the live URLs declared in
   `PAGES`, waits for the page-ready selectors, and saves the rendered DOM as
   `sites/<site>/llm_input_original_<page>.html` (plus a preview PNG showing
   what the hand-labels currently match).

2. **Serve the snapshots.** The pipeline reads them over HTTP, so start a local
   server in a separate terminal before running:

   ```bash
   python -m http.server 8001 --directory sites/booking   # for booking runs
   python -m http.server 8001 --directory sites/reddit    # for reddit runs
   ```

**GitLab** ships no cached HTML — it evaluates directly against the live
WebArena GitLab proxy, which must be running at `http://localhost:8103`
(`docker compose up vwa_gitlab_nginx`). No fetch or `http.server` step needed.

### Run the pipeline

```bash
cd src/automatic_boundary_detection

# All pages of one site (LLM is called once, evaluates 3 pages):
bash pipeline/run_pipeline.sh booking
bash pipeline/run_pipeline.sh reddit
bash pipeline/run_pipeline.sh gitlab

# One page only:
bash pipeline/run_pipeline.sh booking search
```

Outputs land in `results/<site>/<page>/` by default, overwriting our shipped
copies. Point a run elsewhere with `RESULTS_DIR` to keep ours intact:

```bash
RESULTS_DIR=$PWD/results_mine bash pipeline/run_pipeline.sh booking
```

### Variations

**Reuse our cached LLM output** (`--skip-llm`) — re-score against the hand
labels using the cached `sites/<site>/llm_labels.json` instead of calling the
LLM again:

```bash
bash pipeline/run_pipeline.sh booking --skip-llm
bash pipeline/run_pipeline.sh booking --skip-llm search
```

**Skip the screenshots** (`SKIP_VIZ=1`) — for fast, metric-only sweeps:

```bash
SKIP_VIZ=1 bash pipeline/run_pipeline.sh booking
```

### How sanitization works

The LLM never sees the page text — only the structure. Before any HTML reaches
the LLM, `sites/<site>/site.py:sanitize_html_content` replaces every text node
with `[text:length:N]` (an opaque length-tagged placeholder) and anonymizes
URLs, image sources, titles, and long `data-*` attribute values. The LLM cannot
read review bodies, hotel names, or comment text — it can only infer "this
`<span>` would hold user content" from the surrounding HTML structure. The
sanitized HTML used on each run is also written to disk as
`sites/<site>/llm_input_sanitized_<page>.html`, so you can inspect exactly what
the LLM saw.

## Adding a new site

Create `sites/<name>/` with these files:

**1. `site.sh`** — pages, URLs, `get_page_url()`. For example:

```bash
SITE_LABEL="My Site"
SITE_URL="https://example.com"
LOCAL_SERVER="http://localhost:8001"
USE_LOCAL_SERVER=true       # false → hit SITE_URL live (like gitlab proxy)
ALL_PAGES="page_a page_b"

get_page_url() {
    case "$1" in
        page_a) echo "/path/to/a" ;;
        page_b) echo "/path/to/b" ;;
    esac
}
```

If your site is hosted under a WebArena-style instance (like our GitLab), set
`USE_LOCAL_SERVER=false` and point `SITE_URL` at the local proxy URL — the
pipeline will evaluate against the live proxy and no fetch step is needed.

**2. `site.py`** — Python module the pipeline imports by name. Must define:

- `clean_html_for_llm(html)` — strip framework noise (Booking's `data-bui-*`,
  GitLab's `data-v-*` Vue markers, Reddit's promoted-content wrappers) so the
  LLM reasons about meaningful structure.
- `sanitize_html_content(html)` — replace every text node with `[text:length:N]`
  and anonymize URLs/titles/`data-*` values, so the LLM sees structure only, not
  the live text (see [How sanitization works](#how-sanitization-works)).
- `INITIAL_PROMPT_TEMPLATE` / `FOLLOW_UP_PROMPT_TEMPLATE` — what to ask the LLM;
  the follow-up nudges it to find selectors it missed.
- `PAGES`, `NUM_LLM_TURNS`, `PAGE_READY`, and a few size constants
  (`CLEAN_HTML_MAX_SIZE`, etc.).

See any existing `site.py` for the exact shapes.

**3. `hand_labels.json`** — you need to provide your own hand-edited ground
truth for the new site. Schema:

```json
{
  "version": "hand",
  "untrusted_selectors": [
    { "selector": ".some-css", "tagName": "name", "description": "...", "confidence": "high" }
  ]
}
```

**4. `fetch_and_preview.py`** *(only if `USE_LOCAL_SERVER=true`)* — small
Playwright script that fetches each page in `PAGES` and saves the rendered
DOM to `llm_input_original_<page>.html`. CLI flags: `--fetch-only`,
`--preview-only`.

**5. Run it:**

```bash
python sites/<name>/fetch_and_preview.py --fetch-only    # only if cached HTML
bash pipeline/run_pipeline.sh <name>
```

The pipeline auto-discovers the new site by name via
`pipeline/_site_loader.py`. No edits to anything under `pipeline/` needed.

## Layout (code structure)

```
automatic_boundary_detection/
├── README.md
├── pipeline/                       site-agnostic code
│   ├── run_pipeline.sh                entry point: pipeline/run_pipeline.sh <site>
│   ├── analyze_untrusted_elements.py  LLM loop: HTML → CSS selectors (uses site.py for prompts)
│   ├── analyze_selectors.py           evaluate a config on a page → hand_results / llm_results
│   ├── compare_selector_results.py    diff hand vs LLM → comparison_metrics.json (TP/FP/FN)
│   ├── plot_comparison_metrics.py     bar charts of TP/FP/FN
│   ├── visualize_selectors.py         render the live page, overlay each config, screenshot
│   ├── generate_summary.py            roll per-page metrics into summary_all_pages.json
│   └── _site_loader.py                imports sites/<site>/site.py by name
│
├── sites/                          per-site config — everything site-specific lives here
│   ├── booking/
│   │   ├── site.sh                    pages, URLs, get_page_url()
│   │   ├── site.py                    HTML cleaning, text sanitization, LLM prompt
│   │   ├── hand_labels.json           the ground-truth selectors (hand-edited)
│   │   ├── llm_labels.json            cached LLM output (used by --skip-llm)
│   │   ├── llm_input_original_*.html  cached HTML snapshots of homepage / search / hotel
│   │   └── fetch_and_preview.py       refresh the cached snapshots from the live site
│   ├── reddit/                     same structure (subreddit / post / user)
│   └── gitlab/                     same structure, but no cached HTML —
│                                   gitlab evaluates against a live WebArena proxy
│
└── results/
```
