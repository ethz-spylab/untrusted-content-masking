#!/usr/bin/env python3
"""
Analyze WebArena GitLab task results and produce accuracy plots.

Outputs charts into analysis_output/<results_dir_name>/ (override with --output):
  1. Overall utility bar (one bar per experiment condition)
  2. Utility grouped by task category:
     - Open-Ended: string_match-only tasks (agent answers a question)
     - Navigation: url_match tasks (agent navigates to correct page)
     - Environment Action: program_html tasks (agent creates/modifies state)
  3. Per-template accuracy heatmap
  4. Step count distribution
  5. Action counts by category

Per-model plot sets and cross-model comparisons are produced automatically when
2+ model subdirs are present, and skipped cleanly with a single model.

Usage:
  python src/plot/plot_webarena.py <results_dir>
  python src/plot/plot_webarena.py <results_dir> --run latest
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import numpy as np


# ---------------------------------------------------------------------------
# Color palette — matches plot_custom_websites.py
# ---------------------------------------------------------------------------
CONDITION_COLOR_MAP = {
    "Undefended": "#DC3545",
    "Masking Defense": "#007BFF",
    "Masking Defense (no guess)": "#28A745",
}
DEFAULT_COLOR = "#1f77b4"
QLLM_TOKEN_COLOR = "#0B3D91"  # Dark blue for small stacked QLLM segment visibility

CATEGORY_COLORS = {
    "Open-Ended": "#3498db",
    "Navigation": "#2ecc71",
    "Environment Action": "#e67e22",
}

# Overlay mode: color = defense type (same red/blue), solid fill, no hatching.

_MODEL_DISPLAY_NAMES = {
    "claude-sonnet-4-5-20250929": "Claude Sonnet 4.5",
    "claude-sonnet-4-5": "Claude Sonnet 4.5",
    "claude-sonnet-4-6": "Claude Sonnet 4.6",
    "claude-sonnet-4-20250514": "Claude Sonnet 4",
    "claude-haiku-4-5-20251001": "Claude Haiku 4.5",
    "claude-opus-4-6": "Claude Opus 4.6",
    "gpt-5.4": "GPT-5.4",
    "computer-use-preview": "GPT-4 CUA",
}


def _pretty_model_name(m: str) -> str:
    """Short display name for axis/legend. Falls back to the raw key."""
    return _MODEL_DISPLAY_NAMES.get(m, m)


def _overlay_bar_style(model: str, defense_label: str, all_models: list[str]) -> dict:
    """Color from defense type (red/blue), solid fill — like reference figure."""
    is_masking = defense_label.startswith("Masking")
    color = CONDITION_COLOR_MAP.get("Masking Defense" if is_masking else "Undefended",
                                    DEFAULT_COLOR)
    return {"color": color, "hatch": "", "edgecolor": "white"}


def _overlay_legend_handles(models_ordered: list[str]) -> list:
    """Simple legend: just the two defense-type colors."""
    return [
        mpatches.Patch(facecolor=CONDITION_COLOR_MAP["Undefended"],
                       alpha=0.85, label="Undefended"),
        mpatches.Patch(facecolor=CONDITION_COLOR_MAP["Masking Defense"],
                       alpha=0.85, label="Masking Defense"),
    ]


def _sort_conditions_for_overlay(conditions: list[str]) -> list[str]:
    """Sort overlay conditions grouped by model, then Undefended before Masking."""
    def _key(c):
        base, model = _split_condition_and_model(c)
        base_label = _base_condition_label(base)
        defense_order = 0 if base_label.startswith("Undefended") else 1
        return (model or "", defense_order)
    return sorted(conditions, key=_key)

# Prompt-caching-aware pricing (USD per 1M tokens).
# Source: Anthropic prompt caching pricing table.
MODEL_PRICING_USD_PER_MTOK = {
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_write_5m": 3.75,
        "cache_write_1h": 6.0,
        "cache_read": 0.30,
    },
    "claude-sonnet-4-5": {
        "input": 3.0,
        "output": 15.0,
        "cache_write_5m": 3.75,
        "cache_write_1h": 6.0,
        "cache_read": 0.30,
    },
    "claude-opus-4-6": {
        "input": 5.0,
        "output": 25.0,
        "cache_write_5m": 6.25,
        "cache_write_1h": 10.0,
        "cache_read": 0.50,
    },
    "claude-opus-4-5": {
        "input": 5.0,
        "output": 25.0,
        "cache_write_5m": 6.25,
        "cache_write_1h": 10.0,
        "cache_read": 0.50,
    },
    # OpenAI rates: short-context tier. Long-context (>128k prompt) is 2x and
    # is not applied here. cache_write_* buckets are unused for
    # OpenAI runs (no cache-write surcharge); set equal to input for safety.
    # NOTE: order matters — _pricing_for_model does substring matching in dict
    # order, so longer/more-specific names (mini, nano) must precede shorter
    # ones (gpt-5.4) to avoid mis-routing.
    "gpt-5.4-mini": {
        "input": 0.75,
        "output": 4.50,
        "cache_write_5m": 0.75,
        "cache_write_1h": 0.75,
        "cache_read": 0.075,
    },
    "gpt-5.4-nano": {
        "input": 0.20,
        "output": 1.25,
        "cache_write_5m": 0.20,
        "cache_write_1h": 0.20,
        "cache_read": 0.02,
    },
    "gpt-5.4": {
        "input": 2.50,
        "output": 15.00,
        "cache_write_5m": 2.50,
        "cache_write_1h": 2.50,
        "cache_read": 0.25,
    },
    "gpt-5.5": {
        "input": 5.00,
        "output": 30.00,
        "cache_write_5m": 5.00,
        "cache_write_1h": 5.00,
        "cache_read": 0.50,
    },
}

DEFAULT_PRICING_USD_PER_MTOK = MODEL_PRICING_USD_PER_MTOK["claude-sonnet-4-5"]

TASK_CATEGORIES = {
    "Open-Ended": lambda et: "string_match" in et and "url_match" not in et and "program_html" not in et,
    "Navigation": lambda et: "url_match" in et and "program_html" not in et,
    "Environment Action": lambda et: "program_html" in et,
}


def categorize_task(eval_types: list[str]) -> str:
    for cat, test_fn in TASK_CATEGORIES.items():
        if test_fn(eval_types):
            return cat
    return "Other"


def _pricing_for_model(model_name: str) -> dict:
    """Return pricing table for a model; fallback to Sonnet 4.5 defaults."""
    m = (model_name or "").lower()
    for fragment, pricing in MODEL_PRICING_USD_PER_MTOK.items():
        if fragment in m:
            return pricing
    return DEFAULT_PRICING_USD_PER_MTOK


def _estimate_cost_usd(model_name: str,
                       input_uncached: float,
                       output_tokens: float,
                       cache_read_tokens: float,
                       cache_write_5m_tokens: float,
                       cache_write_1h_tokens: float) -> float:
    """Estimate USD cost with prompt-caching token buckets."""
    p = _pricing_for_model(model_name)
    return (
        (input_uncached / 1_000_000.0) * p["input"] +
        (output_tokens / 1_000_000.0) * p["output"] +
        (cache_read_tokens / 1_000_000.0) * p["cache_read"] +
        (cache_write_5m_tokens / 1_000_000.0) * p["cache_write_5m"] +
        (cache_write_1h_tokens / 1_000_000.0) * p["cache_write_1h"]
    )


CONDITION_ORDER = [
    "no_security/all_revealed",
    "no_security/untrusted_masked",
    "green_open_tags/untrusted_masked",
    "ucm_defense/untrusted_masked",
    "green_open_tags_tool_no_guess/untrusted_masked",
]


def _split_condition_and_model(condition: str) -> tuple[str, str | None]:
    """Parse condition key that may be encoded as '<base_condition>|<model>'."""
    if "|" in condition:
        base, model = condition.split("|", 1)
        return base, model
    return condition, None


def _base_condition_label(condition: str) -> str:
    mapping = {
        "no_security/all_revealed": "Undefended",
        "ucm_defense/untrusted_masked": "Masking Defense",
        "green_open_tags_tool_no_guess/untrusted_masked": "Masking Defense (no guess)",
        "green_open_tags/untrusted_masked": "Masking Defense",
        "no_security/untrusted_masked": "Undefended",
    }
    return mapping.get(condition, condition.replace("/", "\n"))


def _sort_conditions(conditions: list[str]) -> list[str]:
    """Sort conditions: Undefended first, then Masking Defense."""
    parsed = [(_split_condition_and_model(c), c) for c in conditions]
    has_models = any(model is not None for (_, model), _ in parsed)
    if has_models:
        # Overlay-mode ordering: keep per-model pairs together
        # (Undefended, Defended) then next model.
        def _key_overlay(c):
            base_cond, model = _split_condition_and_model(c)
            try:
                base_idx = CONDITION_ORDER.index(base_cond)
            except ValueError:
                base_idx = len(CONDITION_ORDER)
            return (model or "", base_idx)
        return sorted(conditions, key=_key_overlay)

    def _key(c):
        base_cond, _ = _split_condition_and_model(c)
        try:
            return CONDITION_ORDER.index(base_cond)
        except ValueError:
            return len(CONDITION_ORDER)
    return sorted(conditions, key=_key)


def _condition_label(condition: str) -> str:
    """Map condition strings to labels matching plot_custom_websites.py."""
    base_cond, model = _split_condition_and_model(condition)
    label = _base_condition_label(base_cond)
    if model:
        return f"{label}\n({model})"
    return label


def _tint_hex(color: str, factor: float) -> str:
    """Lighten/darken a color by multiplying RGB with factor."""
    rgb = np.array(mcolors.to_rgb(color))
    tinted = np.clip(rgb * factor, 0.0, 1.0)
    return mcolors.to_hex(tinted)


def _condition_color(condition: str) -> str:
    base_cond, model = _split_condition_and_model(condition)
    base_label = _base_condition_label(base_cond)
    base_color = CONDITION_COLOR_MAP.get(base_label, DEFAULT_COLOR)
    return base_color


def _overlay_models_into_condition(rows):
    """Encode model name into condition so plots render one set of bars per model."""
    out = []
    for r in rows:
        rr = dict(r)
        rr["condition"] = f"{r['condition']}|{r['model']}"
        out.append(rr)
    return out



def _filter_common_tasks_across_models_and_conditions(rows):
    """
    Keep only task_ids that are available for every selected model
    and for every base condition (defended/undefended).
    """
    models = sorted({r["model"] for r in rows})
    if len(models) < 2:
        return rows

    base_conditions = sorted({r["condition"] for r in rows})
    present = set((r["model"], r["condition"], r["task_id"]) for r in rows)
    valid_task_ids = []
    for task_id in sorted({r["task_id"] for r in rows}):
        ok = True
        for m in models:
            for c in base_conditions:
                if (m, c, task_id) not in present:
                    ok = False
                    break
            if not ok:
                break
        if ok:
            valid_task_ids.append(task_id)

    valid_set = set(valid_task_ids)
    return [r for r in rows if r["task_id"] in valid_set]


def _std_error(values: list[float]) -> float:
    """Standard error of the mean (SEM). Returns 0 for n <= 1."""
    n = len(values)
    if n <= 1:
        return 0.0
    return float(np.std(values, ddof=1) / np.sqrt(n))


def _median_pct_increase_per_task(rows_undef: list[dict],
                                  rows_def: list[dict],
                                  value_key: str) -> tuple[float | None, int]:
    """
    Compute median per-task percent increase:
      1) average selected metric across runs within each task+model for each condition
      2) compute % increase per task: (def - undef) / undef
      3) take the median across paired tasks
    Returns (median_pct, n_paired_tasks). median_pct is None if no valid pairs.
    """
    by_task_undef = defaultdict(list)
    by_task_def = defaultdict(list)

    for r in rows_undef:
        key = (r.get("model"), r.get("task_id"))
        by_task_undef[key].append(float(r.get(value_key, 0.0)))
    for r in rows_def:
        key = (r.get("model"), r.get("task_id"))
        by_task_def[key].append(float(r.get(value_key, 0.0)))

    common_keys = set(by_task_undef.keys()) & set(by_task_def.keys())
    pct_values = []
    for key in common_keys:
        u = float(np.mean(by_task_undef[key])) if by_task_undef[key] else 0.0
        d = float(np.mean(by_task_def[key])) if by_task_def[key] else 0.0
        if u > 0:
            pct_values.append(((d - u) / u) * 100.0)

    if not pct_values:
        return None, 0
    return float(np.median(pct_values)), len(pct_values)


def _median_abs_delta_per_task(rows_undef: list[dict],
                               rows_def: list[dict],
                               value_key: str) -> tuple[float | None, int]:
    """
    Like _median_pct_increase_per_task but returns the median absolute delta
    (def - undef) per task instead of the % increase. Baseline-size free.
    """
    by_task_undef = defaultdict(list)
    by_task_def = defaultdict(list)
    for r in rows_undef:
        by_task_undef[(r.get("model"), r.get("task_id"))].append(float(r.get(value_key, 0.0)))
    for r in rows_def:
        by_task_def[(r.get("model"), r.get("task_id"))].append(float(r.get(value_key, 0.0)))
    deltas = []
    for key in set(by_task_undef.keys()) & set(by_task_def.keys()):
        u = float(np.mean(by_task_undef[key])) if by_task_undef[key] else 0.0
        d = float(np.mean(by_task_def[key])) if by_task_def[key] else 0.0
        deltas.append(d - u)
    if not deltas:
        return None, 0
    return float(np.median(deltas)), len(deltas)


def _per_task_pct_increase_map(rows_undef: list[dict],
                               rows_def: list[dict],
                               value_key: str) -> dict[tuple[str, str], float]:
    """Return per-task % increase map keyed by (model, task_id)."""
    by_task_undef = defaultdict(list)
    by_task_def = defaultdict(list)
    for r in rows_undef:
        by_task_undef[(r.get("model"), r.get("task_id"))].append(float(r.get(value_key, 0.0)))
    for r in rows_def:
        by_task_def[(r.get("model"), r.get("task_id"))].append(float(r.get(value_key, 0.0)))

    out = {}
    for key in sorted(set(by_task_undef.keys()) & set(by_task_def.keys()),
                      key=lambda k: (k[0] or "", k[1] or "")):
        u = float(np.mean(by_task_undef[key])) if by_task_undef[key] else 0.0
        d = float(np.mean(by_task_def[key])) if by_task_def[key] else 0.0
        if u > 0:
            out[key] = ((d - u) / u) * 100.0
    return out


def _parse_run_numbers(run_selector: str) -> set[int]:
    """
    Parse run selectors like:
      "1"
      "1,2"
      "1-3"
      "1,3-5"
    """
    runs: set[int] = set()
    for raw_part in run_selector.split(","):
        part = raw_part.strip()
        if not part:
            continue

        if "-" in part:
            bounds = [p.strip() for p in part.split("-", 1)]
            if len(bounds) != 2 or not bounds[0].isdigit() or not bounds[1].isdigit():
                raise ValueError(f"Invalid run range: {part}")
            start = int(bounds[0])
            end = int(bounds[1])
            if start <= 0 or end <= 0:
                raise ValueError(f"Run numbers must be positive: {part}")
            lo, hi = (start, end) if start <= end else (end, start)
            runs.update(range(lo, hi + 1))
        else:
            if not part.isdigit():
                raise ValueError(f"Invalid run value: {part}")
            run_num = int(part)
            if run_num <= 0:
                raise ValueError(f"Run number must be positive: {part}")
            runs.add(run_num)

    if not runs:
        raise ValueError("No valid run numbers parsed")
    return runs


def collect_results(results_dir: Path, run_selector: str = "latest",
                    count_subactions: bool = False):
    """
    Walk the results directory and collect per-task scores.

    Directory layout:
      results_dir/<model>/<prompt>/<trusted_setting>/webarena_gitlab/<template_X>/<wa_Y>/run_Z/success.json

    Args:
      count_subactions: If False (default), count unique step numbers as actions
          (one step with multiple sub-actions = 1 action). If True, count every
          individual sub-action line separately.

    Returns:
      list of dicts with keys: model, prompt, trusted, template, task_id, wa_id, run,
                                score, eval_types, category, num_steps, details
    """
    rows = []

    for success_file in sorted(results_dir.rglob("success.json")):
        try:
            with open(success_file) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        wa_eval = data.get("webarena_eval")
        if not wa_eval:
            continue

        parts = success_file.relative_to(results_dir).parts
        if len(parts) < 7:
            continue

        if any(p.endswith("_old") for p in parts):
            continue

        model = parts[0]
        prompt = parts[1]
        trusted = parts[2]
        template = parts[4] if len(parts) > 4 else "unknown"
        task_id = parts[5] if len(parts) > 5 else "unknown"
        run_dir = parts[6] if len(parts) > 6 else "run_1"
        run_num = int(run_dir.split("_")[-1]) if run_dir.startswith("run_") else 1

        eval_types = wa_eval.get("eval_types", [])
        category = categorize_task(eval_types)

        num_steps = 0
        num_qllm = 0
        num_clicks = 0
        seen_steps = set()
        token_steps_idx = []
        token_steps_input = []
        token_steps_output = []
        agent_declared_unsolvable = False
        model_resp_file = success_file.parent / "model_responses.jsonl"
        if model_resp_file.exists():
            with open(model_resp_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "action":
                            step_num = obj.get("step")
                            if count_subactions or step_num not in seen_steps:
                                num_steps += 1
                            seen_steps.add(step_num)
                            atype = obj.get("action_type", "")
                            if atype == "quarantined_llm_analysis":
                                num_qllm += 1
                            elif atype == "click":
                                num_clicks += 1
                        if (obj.get("type") == "task_end"
                                and obj.get("reason") == "task_unsolvable"):
                            agent_declared_unsolvable = True
                    except json.JSONDecodeError:
                        pass

        token_usage_file = success_file.parent / "token_usage.jsonl"
        token_cache_read_sum = 0.0
        token_cache_write_5m_sum = 0.0
        token_cache_write_1h_sum = 0.0
        token_input_total_qllm_sum = 0.0
        token_output_qllm_sum = 0.0
        if token_usage_file.exists():
            with open(token_usage_file) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    usage = obj.get("usage", {})
                    in_tok = usage.get("input_tokens", 0)
                    out_tok = usage.get("output_tokens", 0)
                    cache_read_tok = usage.get("cache_read_input_tokens", 0)
                    cache_creation_total_tok = usage.get("cache_creation_input_tokens", 0)
                    cache_creation_5m_tok = 0.0
                    cache_creation_1h_tok = 0.0

                    cache_creation_obj = usage.get("cache_creation", {})
                    if isinstance(cache_creation_obj, dict):
                        v5 = cache_creation_obj.get("ephemeral_5m_input_tokens", 0)
                        v1 = cache_creation_obj.get("ephemeral_1h_input_tokens", 0)
                        if isinstance(v5, (int, float)):
                            cache_creation_5m_tok = float(v5)
                        if isinstance(v1, (int, float)):
                            cache_creation_1h_tok = float(v1)

                    # OpenAI shape: input_tokens is the TOTAL (including cached),
                    # and the cached subset lives in input_tokens_details.cached_tokens.
                    # Treat that subset as cache_read for cost purposes; subtract it
                    # from the uncached input so we don't double-count.
                    input_details = usage.get("input_tokens_details", {})
                    if isinstance(input_details, dict):
                        openai_cached = input_details.get("cached_tokens", 0)
                        if (isinstance(openai_cached, (int, float))
                                and openai_cached > 0
                                and (not isinstance(cache_read_tok, (int, float))
                                     or cache_read_tok == 0)):
                            cache_read_tok = float(openai_cached)
                            if isinstance(in_tok, (int, float)):
                                in_tok = max(0.0, float(in_tok) - float(openai_cached))

                    if isinstance(cache_creation_total_tok, (int, float)):
                        cache_creation_total_tok = float(cache_creation_total_tok)
                    else:
                        cache_creation_total_tok = 0.0
                    if cache_creation_total_tok > 0 and cache_creation_5m_tok == 0 and cache_creation_1h_tok == 0:
                        # Backward-compatible bucket when split fields are absent.
                        cache_creation_5m_tok = cache_creation_total_tok
                    total_input_step = (
                        float(in_tok) +
                        float(cache_read_tok if isinstance(cache_read_tok, (int, float)) else 0.0) +
                        cache_creation_5m_tok +
                        cache_creation_1h_tok
                    ) if isinstance(in_tok, (int, float)) else 0.0

                    if isinstance(in_tok, (int, float)) and isinstance(out_tok, (int, float)):
                        step_idx = obj.get("step")
                        if not isinstance(step_idx, int):
                            step_idx = len(token_steps_idx) + 1
                        token_steps_idx.append(step_idx)
                        token_steps_input.append(float(in_tok))
                        token_steps_output.append(float(out_tok))
                        if isinstance(cache_read_tok, (int, float)):
                            token_cache_read_sum += float(cache_read_tok)
                        token_cache_write_5m_sum += cache_creation_5m_tok
                        token_cache_write_1h_sum += cache_creation_1h_tok
                        if obj.get("source") == "qllm":
                            token_input_total_qllm_sum += total_input_step
                            token_output_qllm_sum += float(out_tok)

        token_input_last = token_steps_input[-1] if token_steps_input else 0.0
        token_input_sum = float(np.sum(token_steps_input)) if token_steps_input else 0.0
        token_output_sum = float(np.sum(token_steps_output)) if token_steps_output else 0.0
        token_input_total_sum = (
            token_input_sum + token_cache_read_sum +
            token_cache_write_5m_sum + token_cache_write_1h_sum
        )
        token_input_total_agent_sum = max(0.0, token_input_total_sum - token_input_total_qllm_sum)
        token_output_agent_sum = max(0.0, token_output_sum - token_output_qllm_sum)
        estimated_cost_usd = _estimate_cost_usd(
            model_name=model,
            input_uncached=token_input_sum,
            output_tokens=token_output_sum,
            cache_read_tokens=token_cache_read_sum,
            cache_write_5m_tokens=token_cache_write_5m_sum,
            cache_write_1h_tokens=token_cache_write_1h_sum,
        )

        rows.append({
            "model": model,
            "prompt": prompt,
            "trusted": trusted,
            "condition": f"{prompt}/{trusted}",
            "template": template,
            "task_id": task_id,
            "wa_id": data.get("webarena_task_id", task_id),
            "run": run_num,
            "score": wa_eval.get("score", 0.0),
            "eval_types": eval_types,
            "category": category,
            "num_steps": num_steps,
            "num_qllm": num_qllm,
            "num_clicks": num_clicks,
            "token_input_last": token_input_last,
            "token_input_sum": token_input_sum,
            "token_input_total_sum": token_input_total_sum,
            "token_input_total_agent_sum": token_input_total_agent_sum,
            "token_input_total_qllm_sum": token_input_total_qllm_sum,
            "token_output_sum": token_output_sum,
            "token_output_agent_sum": token_output_agent_sum,
            "token_output_qllm_sum": token_output_qllm_sum,
            "token_cache_read_sum": token_cache_read_sum,
            "token_cache_write_5m_sum": token_cache_write_5m_sum,
            "token_cache_write_1h_sum": token_cache_write_1h_sum,
            "estimated_cost_usd": estimated_cost_usd,
            "token_steps_idx": token_steps_idx,
            "token_steps_input": token_steps_input,
            "token_steps_output": token_steps_output,
            "intent": wa_eval.get("intent", ""),
            "agent_declared_unsolvable": agent_declared_unsolvable,
        })

    if run_selector == "latest":
        best = {}
        for r in rows:
            key = (r["model"], r["condition"], r["task_id"])
            if key not in best or r["run"] > best[key]["run"]:
                best[key] = r
        rows = list(best.values())
    elif run_selector == "best":
        best = {}
        for r in rows:
            key = (r["model"], r["condition"], r["task_id"])
            if key not in best or r["score"] > best[key]["score"]:
                best[key] = r
        rows = list(best.values())
    elif run_selector != "all":
        selected_runs = _parse_run_numbers(run_selector)
        rows = [r for r in rows if r["run"] in selected_runs]

    return rows


# ---------------------------------------------------------------------------
# User-help (second-chance) results merging
# ---------------------------------------------------------------------------

def collect_user_help_rows(user_help_dir: Path, run_selector: str = "all",
                           count_subactions: bool = False) -> list[dict]:
    """Collect rows from a retry/user-help results dir and mark which runs
    actually used the ask-user (string-type qLLM) second-chance path.

    A run is considered to have used user help if its `ask_user.jsonl`
    file exists and contains at least one non-empty line.
    """
    rows = collect_results(user_help_dir, run_selector=run_selector,
                           count_subactions=count_subactions)
    for r in rows:
        run_dir = (user_help_dir / r["model"] / r["prompt"] / r["trusted"]
                   / "webarena_gitlab" / r["template"] / r["task_id"]
                   / f"run_{r['run']}")
        ask_user_file = run_dir / "ask_user.jsonl"
        has_entries = False
        if ask_user_file.exists():
            try:
                for line in ask_user_file.read_text().splitlines():
                    if line.strip():
                        has_entries = True
                        break
            except Exception:
                pass
        r["user_help_used"] = has_entries
    return rows


def merge_main_with_user_help(main_rows: list[dict],
                              help_rows: list[dict]) -> list[dict]:
    """Override main rows with user-help rows, keyed by (model, condition, task_id).

    Semantics (per user spec):
      - retry row with ask_user.jsonl entries wins and is marked user_help_used=True
      - retry row without ask_user entries still overrides the main outcome but
        is marked user_help_used=False (plain rerun)
      - tasks absent from retry keep their main-dataset row; user_help_used=False
    """
    help_by_key = {}
    for h in help_rows:
        key = (h["model"], h["condition"], h["task_id"])
        # If several retry rows collide on the same key, prefer one that used help.
        if key not in help_by_key or (
            h.get("user_help_used") and not help_by_key[key].get("user_help_used")
        ):
            help_by_key[key] = h
    merged = []
    seen = set()
    for m in main_rows:
        key = (m["model"], m["condition"], m["task_id"])
        if key in help_by_key:
            merged.append(help_by_key[key])
        else:
            mm = dict(m)
            mm.setdefault("user_help_used", False)
            merged.append(mm)
        seen.add(key)
    for k, h in help_by_key.items():
        if k not in seen:
            merged.append(h)
    return merged


def _aggregate_rows_by_task(rows):
    """
    Average metrics within each (model, condition, task_id) across selected runs.
    This avoids double-counting tasks when --run selects multiple runs.
    """
    by_key = defaultdict(list)
    for r in rows:
        key = (r["model"], r["condition"], r["task_id"])
        by_key[key].append(r)

    agg = []
    for _, items in by_key.items():
        base = dict(items[0])
        base["score"] = float(np.mean([x.get("score", 0.0) for x in items]))
        base["num_steps"] = float(np.mean([x.get("num_steps", 0.0) for x in items]))
        base["num_qllm"] = float(np.mean([x.get("num_qllm", 0.0) for x in items]))
        base["num_clicks"] = float(np.mean([x.get("num_clicks", 0.0) for x in items]))
        # If any run across the selection used the user-help second chance,
        # classify the aggregated task outcome as user-help.
        base["user_help_used"] = any(x.get("user_help_used", False) for x in items)
        agg.append(base)
    return agg


# ---------------------------------------------------------------------------
# Plot 1: Overall Utility
# ---------------------------------------------------------------------------

def plot_overall_accuracy(rows, output_dir: Path,
                          rows_overall: list[dict] | None = None):
    """Bar chart: overall utility per condition.

    If any row has ``user_help_used=True`` (populated by merging a retry dir
    with ``collect_user_help_rows`` + ``merge_main_with_user_help``), each bar
    is split into:
      - solid-color "standalone" segment (bottom) = tasks solved without user help
      - shaded segment (top, lighter tint) = tasks rescued by the ask-user path
    Total bar height = combined accuracy.
    """
    rows = _aggregate_rows_by_task(rows)
    rows_overall = _aggregate_rows_by_task(rows_overall) if rows_overall is not None else rows

    user_help_mode = any(r.get("user_help_used", False) for r in rows_overall)

    by_condition = defaultdict(list)
    by_condition_solvable = defaultdict(list)
    by_condition_unsolvable = defaultdict(list)
    for r in rows_overall:
        by_condition[r["condition"]].append(r["score"])
        if user_help_mode:
            # Top (shaded) segment = user-help rescues; bottom = standalone.
            if r.get("user_help_used", False):
                by_condition_unsolvable[r["condition"]].append(r["score"])
            else:
                by_condition_solvable[r["condition"]].append(r["score"])
        else:
            by_condition_solvable[r["condition"]].append(r["score"])

    conditions = _sort_conditions(list(by_condition.keys()))
    overlay_mode = any(_split_condition_and_model(c)[1] is not None for c in conditions)
    if overlay_mode:
        conditions = _sort_conditions_for_overlay(conditions)
        models_ordered = list(dict.fromkeys(
            _split_condition_and_model(c)[1] for c in conditions
            if _split_condition_and_model(c)[1] is not None))
    means = []
    sems = []
    means_solvable_component = []
    means_unsolvable_component = []
    for c in conditions:
        all_scores = by_condition[c]
        solv_scores = by_condition_solvable.get(c, [])
        uns_scores = by_condition_unsolvable.get(c, [])
        if uns_scores:
            n_s = len(solv_scores)
            n_u = len(uns_scores)
            n_t = n_s + n_u
            mean_s = float(np.mean(solv_scores)) if n_s else 0.0
            mean_u = float(np.mean(uns_scores)) if n_u else 0.0
            solv_component = mean_s * (n_s / n_t) if n_t else 0.0
            uns_component = mean_u * (n_u / n_t) if n_t else 0.0
            means_solvable_component.append(solv_component)
            means_unsolvable_component.append(uns_component)
            means.append(solv_component + uns_component)
            sems.append(_std_error(all_scores))
        else:
            mean_all = float(np.mean(all_scores)) if all_scores else 0.0
            means_solvable_component.append(mean_all)
            means_unsolvable_component.append(0.0)
            means.append(mean_all)
            sems.append(_std_error(all_scores))

    counts = [len(by_condition[c]) for c in conditions]
    labels = [_condition_label(c) for c in conditions]

    if overlay_mode:
        styles = [_overlay_bar_style(_split_condition_and_model(c)[1],
                                     _base_condition_label(_split_condition_and_model(c)[0]),
                                     models_ordered) for c in conditions]
        colors = [s["color"] for s in styles]
        defense_hatches = [s["hatch"] for s in styles]
    else:
        colors = [_condition_color(c) for c in conditions]
        defense_hatches = [""] * len(conditions)

    x_pos = []
    within_step = 0.7 if overlay_mode else 1.0
    gap_size = 0.6 if overlay_mode else 0.8
    cur = 0.0
    prev_model = None
    for cond in conditions:
        _, model = _split_condition_and_model(cond)
        if prev_model is not None and model != prev_model:
            cur += gap_size
        x_pos.append(cur)
        cur += within_step
        prev_model = model

    n_models_for_width = len(models_ordered) if overlay_mode else len(conditions)
    fig, ax = plt.subplots(
        figsize=(max(8, n_models_for_width * 2.4), 5.8))
    for i in range(len(conditions)):
        ax.bar(x_pos[i], means_solvable_component[i], color=colors[i], edgecolor="white",
               width=0.6, alpha=0.85, hatch=defense_hatches[i], linewidth=0.5)
    light_colors = [_tint_hex(c, 1.45) for c in colors]
    for i in range(len(conditions)):
        if means_unsolvable_component[i] > 0:
            ax.bar(x_pos[i], means_unsolvable_component[i], color=light_colors[i],
                   edgecolor="white", linewidth=0.6, width=0.6, alpha=0.40,
                   bottom=means_solvable_component[i])
    # Error bar at the top of the full bar (includes Q-Model string-output shading
    # when present). Only one bar is drawn so the chart is not visually cluttered
    # by two stacked error bars on the same column.
    ax.errorbar(x_pos, means, yerr=sems, fmt="none", ecolor="black",
                elinewidth=1.5, capsize=4, capthick=1.5)

    if overlay_mode:
        # One label per model, centered under its pair of bars.
        by_model = defaultdict(list)
        for xp, c in zip(x_pos, conditions):
            _, model = _split_condition_and_model(c)
            by_model[model].append(xp)
        group_centers = [float(np.mean(by_model[m])) for m in models_ordered]
        ax.set_xticks(group_centers)
        ax.set_xticklabels([_pretty_model_name(m) for m in models_ordered], fontsize=13)
    else:
        ax.set_xticks(x_pos)
        ax.set_xticklabels(labels, fontsize=14)
    ax.set_ylabel("Utility", fontsize=15, fontweight="bold")
    ax.tick_params(axis="y", labelsize=11)
    ax.set_ylim(0, 1.05)
    ax.yaxis.set_major_locator(plt.MultipleLocator(0.2))
    ax.yaxis.set_minor_locator(plt.MultipleLocator(0.1))
    ax.grid(axis="y", which="major", alpha=0.3)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))

    legend_handles = []
    if overlay_mode:
        legend_handles = _overlay_legend_handles(models_ordered)
    if user_help_mode and any(v > 0 for v in means_unsolvable_component):
        legend_handles.append(
            mpatches.Patch(facecolor="#ADD8E6", edgecolor="white", linewidth=0.6,
                           alpha=0.60, label="Q-Model string output allowed"))
    if legend_handles:
        fig.legend(handles=legend_handles, loc="upper center",
                   bbox_to_anchor=(0.5, 1.05),
                   ncol=min(len(legend_handles), 5),
                   framealpha=0.9, fontsize=12)

    fig.tight_layout()
    fig.savefig(output_dir / "overall_accuracy.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / "overall_accuracy.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved overall_accuracy.png/pdf")


# ---------------------------------------------------------------------------
# Plot: token-usage increase when Q-Model string output is allowed
# ---------------------------------------------------------------------------



def plot_token_ratio_distribution_per_model(rows: list[dict], output_dir: Path):
    """Per-model histogram (input | output) of the per-task ratio
    `tokens_with_masking / tokens_without_masking`, computed by:
      1) pairing same-run-index defended/undefended runs for each task
         (run_1 def vs run_1 undef, etc.); skip a run if undef has 0 tokens;
      2) averaging those per-run ratios within a task;
      3) plotting the distribution across tasks on a log-x histogram with
         a red vertical line at the median.
    Style matches CaMeL Figure 13.
    """
    def _is_undef(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("no_security")

    def _is_def(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("ucm_defense")

    # by_model[model][task_id][run] = {"undef": row, "def": row}
    by_model: dict[str, dict] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict)))
    for r in rows:
        cond = r.get("condition", "")
        side = "undef" if _is_undef(cond) else ("def" if _is_def(cond) else None)
        if side is None:
            continue
        model = r.get("model")
        task_id = r.get("task_id")
        run = r.get("run")
        by_model[model][task_id][run][side] = r

    for model in sorted(by_model.keys(),
                        key=lambda m: (_pretty_model_name(m) or "")):
        in_ratios: list[float] = []
        out_ratios: list[float] = []
        for task_id, runs in by_model[model].items():
            in_per_run: list[float] = []
            out_per_run: list[float] = []
            for run, sides in runs.items():
                u = sides.get("undef")
                d = sides.get("def")
                if u is None or d is None:
                    continue
                u_in = float(u.get("token_input_total_sum", 0.0))
                d_in = float(d.get("token_input_total_sum", 0.0))
                u_out = float(u.get("token_output_sum", 0.0))
                d_out = float(d.get("token_output_sum", 0.0))
                if u_in > 0:
                    in_per_run.append(d_in / u_in)
                if u_out > 0:
                    out_per_run.append(d_out / u_out)
            if in_per_run:
                in_ratios.append(float(np.mean(in_per_run)))
            if out_per_run:
                out_ratios.append(float(np.mean(out_per_run)))

        if not in_ratios and not out_ratios:
            continue

        # Log-spaced bins covering 0.1x .. 100x.
        bins = np.logspace(np.log10(0.1), np.log10(100.0), 30)
        fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
        for ax, vals, label in [
            (axes[0], in_ratios, "input tokens, per task"),
            (axes[1], out_ratios, "output tokens, per task"),
        ]:
            if not vals:
                ax.text(0.5, 0.5, "no data", ha="center", va="center",
                        transform=ax.transAxes)
                continue
            ax.hist(vals, bins=bins, color="#4C78A8", edgecolor="white",
                    linewidth=0.5)
            median = float(np.median(vals))
            ax.axvline(median, color="red", linewidth=1.8)
            ax.set_xscale("log")
            ax.set_xticks([0.1, 1.0, 2.0, 10.0, 100.0])
            ax.set_xticklabels(["0.1x", "1x", "2.0x", "10x", "100x"])
            ax.set_xlabel(
                f"tokens with masking / tokens without masking\n({label})",
                fontsize=12)
            ax.set_title(f"median = {median:.2f}x", fontsize=11)
            ax.grid(axis="y", alpha=0.3)
            ax.grid(axis="x", which="major", alpha=0.3)

        fig.suptitle(_pretty_model_name(model), fontsize=14, fontweight="bold")
        fig.tight_layout()
        safe_model = (model or "unknown").replace("/", "_")
        out_png = output_dir / f"token_ratio_dist_{safe_model}.png"
        out_pdf = output_dir / f"token_ratio_dist_{safe_model}.pdf"
        fig.savefig(out_png, dpi=300, bbox_inches="tight")
        fig.savefig(out_pdf, bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved token_ratio_dist_{safe_model}.png/pdf")


# ---------------------------------------------------------------------------
# Plot: Token Usage Ratio — Median Bars per Model
# ---------------------------------------------------------------------------

def plot_token_ratio_median_bars(rows: list[dict], output_dir: Path):
    """Grouped bar chart per model showing the median per-task ratio
    `tokens_with_masking / tokens_without_masking`. Aggregation matches
    plot_token_ratio_distribution_per_model: pair runs by index, average
    per-run ratios within a task, then take the median across tasks.
    Two bars per model: input ratio and output ratio.
    """
    def _is_undef(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("no_security")

    def _is_def(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("ucm_defense")

    by_model: dict[str, dict] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(dict)))
    for r in rows:
        cond = r.get("condition", "")
        side = "undef" if _is_undef(cond) else ("def" if _is_def(cond) else None)
        if side is None:
            continue
        model = r.get("model")
        task_id = r.get("task_id")
        run = r.get("run")
        by_model[model][task_id][run][side] = r

    models_present: list[str] = []
    input_medians: list[float] = []
    output_medians: list[float] = []
    for model in sorted(by_model.keys(),
                        key=lambda m: (_pretty_model_name(m) or "")):
        in_ratios: list[float] = []
        out_ratios: list[float] = []
        for task_id, runs in by_model[model].items():
            in_per_run: list[float] = []
            out_per_run: list[float] = []
            for run, sides in runs.items():
                u = sides.get("undef")
                d = sides.get("def")
                if u is None or d is None:
                    continue
                u_in = float(u.get("token_input_total_sum", 0.0))
                d_in = float(d.get("token_input_total_sum", 0.0))
                u_out = float(u.get("token_output_sum", 0.0))
                d_out = float(d.get("token_output_sum", 0.0))
                if u_in > 0:
                    in_per_run.append(d_in / u_in)
                if u_out > 0:
                    out_per_run.append(d_out / u_out)
            if in_per_run:
                in_ratios.append(float(np.mean(in_per_run)))
            if out_per_run:
                out_ratios.append(float(np.mean(out_per_run)))
        if not in_ratios and not out_ratios:
            continue
        models_present.append(model)
        input_medians.append(float(np.median(in_ratios)) if in_ratios else 0.0)
        output_medians.append(float(np.median(out_ratios)) if out_ratios else 0.0)

    if not models_present:
        print("  plot_token_ratio_median_bars: no paired runs — skipping")
        return

    labels = [_pretty_model_name(m) for m in models_present]
    within_step = 0.7
    gap_size = 0.6
    x = []
    cur = 0.0
    for i in range(len(models_present)):
        if i > 0:
            cur += gap_size
        x.append(cur)
        cur += within_step
    x = np.array(x)
    width = 0.30

    fig, ax = plt.subplots(figsize=(max(7, len(models_present) * 1.8), 5.8))
    in_color = "#4C78A8"
    out_color = "#F58518"
    ax.bar(x - width / 2, input_medians, width, color=in_color,
           edgecolor="white", linewidth=0.5, label="Input tokens")
    ax.bar(x + width / 2, output_medians, width, color=out_color,
           edgecolor="white", linewidth=0.5, label="Output tokens")

    y_top = max(input_medians + output_medians + [1.0]) * 1.15
    pad = y_top * 0.01
    for i, (vi, vo) in enumerate(zip(input_medians, output_medians)):
        for offset, val in [(-width / 2, vi), (width / 2, vo)]:
            ax.text(x[i] + offset, val + pad, f"{val:.2f}x",
                    ha="center", va="bottom", fontsize=10, color="black")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=14)
    ax.set_ylabel("Median token ratio (masking / no masking)",
                  fontsize=14, fontweight="bold")
    ax.tick_params(axis="y", labelsize=11)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.1f}x"))
    ax.set_ylim(0, y_top)
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 1.06),
               ncol=2, framealpha=0.9, fontsize=12)
    fig.tight_layout()
    fig.savefig(output_dir / "token_ratio_median_bars.png",
                dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / "token_ratio_median_bars.pdf",
                bbox_inches="tight")
    plt.close(fig)
    print("  Saved token_ratio_median_bars.png/pdf")


# ---------------------------------------------------------------------------
# Plot: Token Usage — Absolute Levels (Median)
# ---------------------------------------------------------------------------

def plot_token_usage_levels_median(rows: list[dict], output_dir: Path):
    """Side-by-side subplots (Input | Output) showing absolute token levels
    per model for undefended vs defended. Aggregation matches the % and
    absolute-delta plots: per-task mean across runs, then median across tasks.
    """
    def _is_undef(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("no_security")

    def _is_def(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("ucm_defense")

    def _median_per_task_mean(rows_sub, key):
        """Per-task mean across runs, then median of those per-task values."""
        by_task = defaultdict(list)
        for r in rows_sub:
            by_task[(r.get("model"), r.get("task_id"))].append(
                float(r.get(key, 0.0)))
        per_task = [float(np.mean(v)) for v in by_task.values() if v]
        return float(np.median(per_task)) if per_task else 0.0

    by_model: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {"undef": [], "def": []})
    for r in rows:
        cond = r.get("condition", "")
        m = r.get("model")
        if _is_undef(cond):
            by_model[m]["undef"].append(r)
        elif _is_def(cond):
            by_model[m]["def"].append(r)

    models_present = [
        m for m in sorted(by_model.keys(),
                          key=lambda x: (_pretty_model_name(x) or ""))
        if by_model[m]["undef"] and by_model[m]["def"]
    ]
    if not models_present:
        print("  plot_token_usage_levels_median: no paired tasks — skipping")
        return

    labels = [_pretty_model_name(m) for m in models_present]
    in_undef, in_def, out_undef, out_def = [], [], [], []
    for m in models_present:
        in_undef.append(_median_per_task_mean(by_model[m]["undef"], "token_input_total_sum"))
        in_def.append(_median_per_task_mean(by_model[m]["def"], "token_input_total_sum"))
        out_undef.append(_median_per_task_mean(by_model[m]["undef"], "token_output_sum"))
        out_def.append(_median_per_task_mean(by_model[m]["def"], "token_output_sum"))

    # Layout: x positions per model using the same within-group / inter-group
    # spacing as the % / absolute plots so all three sit visually aligned.
    within_step = 0.7
    gap_size = 0.6
    x = []
    cur = 0.0
    for i in range(len(models_present)):
        if i > 0:
            cur += gap_size
        x.append(cur)
        cur += within_step
    x = np.array(x)
    width = 0.30

    undef_color = CONDITION_COLOR_MAP["Undefended"]         # standard red
    def_color = CONDITION_COLOR_MAP["Masking Defense"]      # standard blue

    fig, (ax_in, ax_out) = plt.subplots(
        1, 2, figsize=(max(12, len(models_present) * 3.2), 5.8))

    for ax, vals_u, vals_d, title, unit_fmt in [
        (ax_in, in_undef, in_def, "Input tokens",
         lambda y, _: f"{y / 1000:.0f}k"),
        (ax_out, out_undef, out_def, "Output tokens",
         lambda y, _: f"{int(y)}"),
    ]:
        ax.bar(x - width / 2, vals_u, width, color=undef_color,
               edgecolor="white", linewidth=0.5, label="Undefended")
        ax.bar(x + width / 2, vals_d, width, color=def_color,
               edgecolor="white", linewidth=0.5, label="Masking Defense")

        # Single label per (undef, def) pair: the % increase, placed above
        # the taller bar in the couple. Bars without a paired undef baseline
        # get no label.
        top = max(vals_u + vals_d) if (vals_u + vals_d) else 1
        pad = top * 0.02
        for i, (vu, vd) in enumerate(zip(vals_u, vals_d)):
            if vu > 0:
                ratio = vd / vu
                y_ann = max(vu, vd) + pad
                # Centered between the two bars in the couple.
                ax.text(x[i], y_ann, f"{ratio:.2f}x",
                        ha="center", va="bottom", fontsize=11,
                        fontweight="bold", color="black")

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=13)
        ax.set_ylabel(title, fontsize=15, fontweight="bold")
        ax.tick_params(axis="y", labelsize=11)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(unit_fmt))
        ax.set_ylim(top=top * 1.18)

    # Shared legend on top.
    handles, legend_labels = ax_in.get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper center",
               bbox_to_anchor=(0.5, 1.04),
               ncol=2, framealpha=0.9, fontsize=12)
    fig.tight_layout()
    fig.savefig(output_dir / "token_usage_levels_median.png",
                dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / "token_usage_levels_median.pdf",
                bbox_inches="tight")
    plt.close(fig)
    print("  Saved token_usage_levels_median.png/pdf")


# ---------------------------------------------------------------------------
# Plot: Cost — Absolute Levels (Median)
# ---------------------------------------------------------------------------

def plot_cost_levels_median(rows: list[dict], output_dir: Path):
    """Side-by-side subplots (Input cost | Output cost) showing absolute
    USD per task, per model, undefended vs defended. Aggregation matches
    plot_token_usage_levels_median: per-task mean across runs of each cost
    component, then median across tasks.
    """
    def _is_undef(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("no_security")

    def _is_def(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("ucm_defense")

    def _row_input_cost(r: dict) -> float:
        p = _pricing_for_model(r.get("model", ""))
        return (
            float(r.get("token_input_sum", 0.0)) / 1e6 * p["input"] +
            float(r.get("token_cache_read_sum", 0.0)) / 1e6 * p["cache_read"] +
            float(r.get("token_cache_write_5m_sum", 0.0)) / 1e6 * p["cache_write_5m"] +
            float(r.get("token_cache_write_1h_sum", 0.0)) / 1e6 * p["cache_write_1h"]
        )

    def _row_output_cost(r: dict) -> float:
        p = _pricing_for_model(r.get("model", ""))
        return float(r.get("token_output_sum", 0.0)) / 1e6 * p["output"]

    def _median_per_task_mean(rows_sub, fn):
        by_task = defaultdict(list)
        for r in rows_sub:
            by_task[(r.get("model"), r.get("task_id"))].append(fn(r))
        per_task = [float(np.mean(v)) for v in by_task.values() if v]
        return float(np.median(per_task)) if per_task else 0.0

    by_model: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {"undef": [], "def": []})
    for r in rows:
        cond = r.get("condition", "")
        m = r.get("model")
        if _is_undef(cond):
            by_model[m]["undef"].append(r)
        elif _is_def(cond):
            by_model[m]["def"].append(r)

    models_present = [
        m for m in sorted(by_model.keys(),
                          key=lambda x: (_pretty_model_name(x) or ""))
        if by_model[m]["undef"] and by_model[m]["def"]
    ]
    if not models_present:
        print("  plot_cost_levels_median: no paired tasks — skipping")
        return

    labels = [_pretty_model_name(m) for m in models_present]
    in_undef, in_def, out_undef, out_def = [], [], [], []
    for m in models_present:
        in_undef.append(_median_per_task_mean(by_model[m]["undef"], _row_input_cost))
        in_def.append(_median_per_task_mean(by_model[m]["def"], _row_input_cost))
        out_undef.append(_median_per_task_mean(by_model[m]["undef"], _row_output_cost))
        out_def.append(_median_per_task_mean(by_model[m]["def"], _row_output_cost))

    within_step = 0.7
    gap_size = 0.6
    x = []
    cur = 0.0
    for i in range(len(models_present)):
        if i > 0:
            cur += gap_size
        x.append(cur)
        cur += within_step
    x = np.array(x)
    width = 0.30

    undef_color = CONDITION_COLOR_MAP["Undefended"]
    def_color = CONDITION_COLOR_MAP["Masking Defense"]

    fig, (ax_in, ax_out) = plt.subplots(
        1, 2, figsize=(max(12, len(models_present) * 3.2), 5.8))

    money_fmt = lambda y, _: f"${y:.2f}"
    for ax, vals_u, vals_d, title in [
        (ax_in, in_undef, in_def, "Input token cost per task (USD)"),
        (ax_out, out_undef, out_def, "Output token cost per task (USD)"),
    ]:
        ax.bar(x - width / 2, vals_u, width, color=undef_color,
               edgecolor="white", linewidth=0.5, label="Undefended")
        ax.bar(x + width / 2, vals_d, width, color=def_color,
               edgecolor="white", linewidth=0.5, label="Masking Defense")

        top = max(vals_u + vals_d) if (vals_u + vals_d) else 1
        pad = top * 0.02
        for i, (vu, vd) in enumerate(zip(vals_u, vals_d)):
            if vu > 0:
                ratio = vd / vu
                y_ann = max(vu, vd) + pad
                ax.text(x[i], y_ann, f"{ratio:.2f}x",
                        ha="center", va="bottom", fontsize=11,
                        fontweight="bold", color="black")

        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=13)
        ax.set_ylabel(title, fontsize=15, fontweight="bold")
        ax.tick_params(axis="y", labelsize=11)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(money_fmt))
        ax.set_ylim(top=top * 1.18 if top > 0 else 1)

    handles, legend_labels = ax_in.get_legend_handles_labels()
    fig.legend(handles, legend_labels, loc="upper center",
               bbox_to_anchor=(0.5, 1.04),
               ncol=2, framealpha=0.9, fontsize=12)
    fig.tight_layout()
    fig.savefig(output_dir / "cost_levels_median.png",
                dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / "cost_levels_median.pdf",
                bbox_inches="tight")
    plt.close(fig)
    print("  Saved cost_levels_median.png/pdf")


# ---------------------------------------------------------------------------
# Plot: Cost — Total per Task (Median)
# ---------------------------------------------------------------------------

def plot_cost_total_levels_median(rows: list[dict], output_dir: Path):
    """Single-panel grouped bar chart of TOTAL USD per task (input + output)
    per model: Undefended (red) vs Masking Defense (blue). Bar height is the
    median across tasks of the per-task mean total cost across runs.
    Annotation above each pair is the ratio of bar heights, formatted as 'Nx'.
    Mirrors plot_cost_levels_median but collapses the two cost panels into
    one total-cost panel.
    """
    def _is_undef(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("no_security")

    def _is_def(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("ucm_defense")

    def _row_total_cost(r: dict) -> float:
        p = _pricing_for_model(r.get("model", ""))
        return (
            float(r.get("token_input_sum", 0.0)) / 1e6 * p["input"] +
            float(r.get("token_cache_read_sum", 0.0)) / 1e6 * p["cache_read"] +
            float(r.get("token_cache_write_5m_sum", 0.0)) / 1e6 * p["cache_write_5m"] +
            float(r.get("token_cache_write_1h_sum", 0.0)) / 1e6 * p["cache_write_1h"] +
            float(r.get("token_output_sum", 0.0)) / 1e6 * p["output"]
        )

    def _median_per_task_mean(rows_sub, fn):
        by_task = defaultdict(list)
        for r in rows_sub:
            by_task[(r.get("model"), r.get("task_id"))].append(fn(r))
        per_task = [float(np.mean(v)) for v in by_task.values() if v]
        return float(np.median(per_task)) if per_task else 0.0

    by_model: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {"undef": [], "def": []})
    for r in rows:
        cond = r.get("condition", "")
        m = r.get("model")
        if _is_undef(cond):
            by_model[m]["undef"].append(r)
        elif _is_def(cond):
            by_model[m]["def"].append(r)

    models_present = [
        m for m in sorted(by_model.keys(),
                          key=lambda x: (_pretty_model_name(x) or ""))
        if by_model[m]["undef"] and by_model[m]["def"]
    ]
    if not models_present:
        print("  plot_cost_total_levels_median: no paired tasks — skipping")
        return

    labels = [_pretty_model_name(m) for m in models_present]
    undef_vals, def_vals = [], []
    for m in models_present:
        undef_vals.append(_median_per_task_mean(by_model[m]["undef"], _row_total_cost))
        def_vals.append(_median_per_task_mean(by_model[m]["def"], _row_total_cost))

    n = len(models_present)
    x = np.arange(n)
    bar_w = 0.35
    undef_color = CONDITION_COLOR_MAP["Undefended"]
    def_color = CONDITION_COLOR_MAP["Masking Defense"]

    fig, ax = plt.subplots(figsize=(max(8, n * 2.4), 5.8))
    ax.bar(x - bar_w / 2, undef_vals, bar_w, color=undef_color,
           edgecolor="white", linewidth=0.5, label="Undefended")
    ax.bar(x + bar_w / 2, def_vals, bar_w, color=def_color,
           edgecolor="white", linewidth=0.5, label="Masking Defense")

    ymax = max(undef_vals + def_vals) if (undef_vals or def_vals) else 1
    y_offset = ymax * 0.02
    for i, (vu, vd) in enumerate(zip(undef_vals, def_vals)):
        if vu > 0:
            ratio = vd / vu
            y_ann = max(vu, vd) + y_offset
            ax.text(x[i], y_ann, f"{ratio:.2f}x",
                    ha="center", va="bottom", fontsize=12,
                    fontweight="bold", color="black")

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=14)
    ax.set_ylabel("Total cost per task (USD)", fontsize=14, fontweight="bold")
    ax.tick_params(axis="y", labelsize=11)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"${y:.2f}"))
    ax.grid(axis="y", alpha=0.25)
    ax.set_ylim(top=ymax * 1.30 if ymax > 0 else 1)

    fig.tight_layout()
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 1.05), ncol=2,
               framealpha=0.9, fontsize=12)
    fig.savefig(output_dir / "cost_total_levels_median.png",
                dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / "cost_total_levels_median.pdf",
                bbox_inches="tight")
    plt.close(fig)
    print("  Saved cost_total_levels_median.png/pdf")


# ---------------------------------------------------------------------------
# Plot: Token Usage — Total Distribution (Box-and-Whisker)
# ---------------------------------------------------------------------------

def plot_token_usage_total_whisker(rows: list[dict], output_dir: Path):
    """Single-axis box-and-whisker plot of total tokens (input+output) per task,
    with one pair of boxes per model (undefended vs defended). Each per-task
    value is the mean across runs of (token_input_total_sum + token_output_sum),
    matching the aggregation used by the median bar plot.
    """
    def _is_undef(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("no_security")

    def _is_def(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("ucm_defense")

    def _per_task_totals(rows_sub):
        """Per-task mean across runs of (input_total + output).

        Returns parallel lists: values, task_ids, intents, run_counts.
        """
        by_task = defaultdict(list)
        intents = {}
        for r in rows_sub:
            total = (float(r.get("token_input_total_sum", 0.0)) +
                     float(r.get("token_output_sum", 0.0)))
            key = (r.get("model"), r.get("task_id"))
            by_task[key].append(total)
            if key not in intents and r.get("intent"):
                intents[key] = r.get("intent")
        values, tids, ins, ns = [], [], [], []
        for key, v in by_task.items():
            if not v:
                continue
            values.append(float(np.mean(v)))
            tids.append(key[1])
            ins.append(intents.get(key, ""))
            ns.append(len(v))
        return values, tids, ins, ns

    by_model: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {"undef": [], "def": []})
    for r in rows:
        cond = r.get("condition", "")
        m = r.get("model")
        if _is_undef(cond):
            by_model[m]["undef"].append(r)
        elif _is_def(cond):
            by_model[m]["def"].append(r)

    models_present = [
        m for m in sorted(by_model.keys(),
                          key=lambda x: (_pretty_model_name(x) or ""))
        if by_model[m]["undef"] and by_model[m]["def"]
    ]
    if not models_present:
        print("  plot_token_usage_total_whisker: no paired tasks — skipping")
        return

    labels = [_pretty_model_name(m) for m in models_present]
    undef_full, def_full = [], []
    undef_data, def_data = [], []
    for m in models_present:
        u = _per_task_totals(by_model[m]["undef"])
        d = _per_task_totals(by_model[m]["def"])
        undef_full.append(u)
        def_full.append(d)
        undef_data.append(u[0])
        def_data.append(d[0])

    within_step = 0.7
    gap_size = 0.6
    x = []
    cur = 0.0
    for i in range(len(models_present)):
        if i > 0:
            cur += gap_size
        x.append(cur)
        cur += within_step
    x = np.array(x)
    width = 0.30

    undef_color = CONDITION_COLOR_MAP["Undefended"]
    def_color = CONDITION_COLOR_MAP["Masking Defense"]

    fig, ax = plt.subplots(figsize=(max(8, len(models_present) * 2.4), 5.8))

    def _box(ax, data, positions, color):
        bp = ax.boxplot(
            data, positions=positions, widths=width,
            patch_artist=True, manage_ticks=False, showfliers=True,
            medianprops=dict(color="black", linewidth=1.5),
            flierprops=dict(marker="o", markerfacecolor=color,
                            markeredgecolor=color, markersize=3, alpha=0.6),
            whiskerprops=dict(color=color, linewidth=1.0),
            capprops=dict(color=color, linewidth=1.0),
        )
        for patch in bp["boxes"]:
            patch.set_facecolor(color)
            patch.set_edgecolor("white")
            patch.set_alpha(0.85)
            patch.set_linewidth(0.5)
        return bp

    _box(ax, undef_data, x - width / 2, undef_color)
    _box(ax, def_data, x + width / 2, def_color)

    # Overlay individual task points so the per-task spread is visible.
    rng = np.random.default_rng(0)
    for i, vals in enumerate(undef_data):
        if vals:
            jitter = rng.uniform(-width * 0.25, width * 0.25, size=len(vals))
            ax.scatter(np.full(len(vals), x[i] - width / 2) + jitter, vals,
                       s=10, color=undef_color, alpha=0.55,
                       edgecolors="none", zorder=3)
    for i, vals in enumerate(def_data):
        if vals:
            jitter = rng.uniform(-width * 0.25, width * 0.25, size=len(vals))
            ax.scatter(np.full(len(vals), x[i] + width / 2) + jitter, vals,
                       s=10, color=def_color, alpha=0.55,
                       edgecolors="none", zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=13)
    ax.set_ylabel("Total tokens (input + output) per task",
                  fontsize=15, fontweight="bold")
    ax.tick_params(axis="y", labelsize=11)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda y, _: f"{y / 1000:.0f}k"))

    legend_handles = [
        mpatches.Patch(facecolor=undef_color, edgecolor="white",
                       label="Undefended"),
        mpatches.Patch(facecolor=def_color, edgecolor="white",
                       label="Masking Defense"),
    ]
    fig.legend(handles=legend_handles, loc="upper center",
               bbox_to_anchor=(0.5, 1.04),
               ncol=2, framealpha=0.9, fontsize=12)
    fig.tight_layout()
    fig.savefig(output_dir / "token_usage_total_whisker.png",
                dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / "token_usage_total_whisker.pdf",
                bbox_inches="tight")
    plt.close(fig)
    print("  Saved token_usage_total_whisker.png/pdf")

    # Dump outlier tasks (above Q3 + 1.5*IQR) and the top-10 highest-token
    # tasks per (model, condition) so blow-ups are easy to track down.
    outlier_csv = output_dir / "token_usage_total_whisker_outliers.csv"
    with open(outlier_csv, "w", encoding="utf-8") as fh:
        fh.write("model,condition,kind,task_id,total_tokens,n_runs,intent\n")
        print("  Outlier tasks (Tukey: > Q3 + 1.5*IQR) and top-10 by total tokens:")
        for m, m_label, u_full, d_full in zip(
                models_present, labels, undef_full, def_full):
            for cond_label, (vals, tids, ins, ns) in (
                    ("Undefended", u_full), ("Masking Defense", d_full)):
                if not vals:
                    continue
                arr = np.array(vals)
                q1, q3 = np.percentile(arr, [25, 75])
                iqr = q3 - q1
                hi = q3 + 1.5 * iqr
                order = np.argsort(arr)[::-1]
                outlier_idx = [i for i in order if arr[i] > hi]
                top_idx = list(order[:10])
                shown = set()
                print(f"    {m_label} / {cond_label}: "
                      f"Q3={q3/1000:.0f}k, hi={hi/1000:.0f}k, "
                      f"max={arr.max()/1000:.0f}k")
                for kind, idxs in (("outlier", outlier_idx), ("top10", top_idx)):
                    for i in idxs:
                        key = (kind, tids[i])
                        if key in shown:
                            continue
                        shown.add(key)
                        intent_clean = (ins[i] or "").replace("\n", " ").replace('"', "'")
                        fh.write(f'{m},{cond_label},{kind},{tids[i]},'
                                 f'{vals[i]:.0f},{ns[i]},"{intent_clean}"\n')
                        if kind == "outlier":
                            print(f"      OUTLIER task_id={tids[i]} "
                                  f"total={vals[i]/1000:.0f}k runs={ns[i]} "
                                  f"intent={intent_clean[:80]!r}")
    print(f"  Saved {outlier_csv.name}")


# ---------------------------------------------------------------------------
# Plot: Cost — Total Distribution (Box-and-Whisker)
# ---------------------------------------------------------------------------

def plot_cost_total_whisker(rows: list[dict], output_dir: Path):
    """Single-axis box-and-whisker plot of estimated cost in USD per task,
    with one pair of boxes per model (undefended vs defended). Each per-task
    value is the mean across runs of estimated_cost_usd (which already reflects
    input + output and the model's pricing).
    """
    def _is_undef(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("no_security")

    def _is_def(cond: str) -> bool:
        base = cond.split("|")[0] if "|" in cond else cond
        return base.startswith("ucm_defense")

    def _per_task_costs(rows_sub):
        """Per-task mean across runs of estimated_cost_usd.

        Returns parallel lists: values, task_ids, intents, run_counts, solved.
        `solved` is True iff every run for the task had score > 0.
        """
        by_task = defaultdict(list)
        by_task_scores = defaultdict(list)
        intents = {}
        for r in rows_sub:
            cost = float(r.get("estimated_cost_usd", 0.0) or 0.0)
            key = (r.get("model"), r.get("task_id"))
            by_task[key].append(cost)
            by_task_scores[key].append(float(r.get("score", 0.0) or 0.0))
            if key not in intents and r.get("intent"):
                intents[key] = r.get("intent")
        values, tids, ins, ns, solved = [], [], [], [], []
        for key, v in by_task.items():
            if not v:
                continue
            values.append(float(np.mean(v)))
            tids.append(key[1])
            ins.append(intents.get(key, ""))
            ns.append(len(v))
            solved.append(all(s > 0 for s in by_task_scores[key]))
        return values, tids, ins, ns, solved

    by_model: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {"undef": [], "def": []})
    for r in rows:
        cond = r.get("condition", "")
        m = r.get("model")
        if _is_undef(cond):
            by_model[m]["undef"].append(r)
        elif _is_def(cond):
            by_model[m]["def"].append(r)

    models_present = [
        m for m in sorted(by_model.keys(),
                          key=lambda x: (_pretty_model_name(x) or ""))
        if by_model[m]["undef"] and by_model[m]["def"]
    ]
    if not models_present:
        print("  plot_cost_total_whisker: no paired tasks — skipping")
        return

    labels = [_pretty_model_name(m) for m in models_present]
    undef_full, def_full = [], []
    undef_data, def_data = [], []
    undef_solved, def_solved = [], []
    for m in models_present:
        u = _per_task_costs(by_model[m]["undef"])
        d = _per_task_costs(by_model[m]["def"])
        undef_full.append(u)
        def_full.append(d)
        undef_data.append(u[0])
        def_data.append(d[0])
        undef_solved.append(u[4])
        def_solved.append(d[4])

    within_step = 0.7
    gap_size = 0.6
    x = []
    cur = 0.0
    for i in range(len(models_present)):
        if i > 0:
            cur += gap_size
        x.append(cur)
        cur += within_step
    x = np.array(x)
    width = 0.30

    undef_color = CONDITION_COLOR_MAP["Undefended"]
    def_color = CONDITION_COLOR_MAP["Masking Defense"]

    fig, ax = plt.subplots(figsize=(max(10, len(models_present) * 2.4), 5.8))

    def _box(ax, data, positions, color):
        bp = ax.boxplot(
            data, positions=positions, widths=width,
            patch_artist=True, manage_ticks=False, showfliers=False,
            medianprops=dict(color="black", linewidth=1.5),
            whiskerprops=dict(color=color, linewidth=1.0),
            capprops=dict(color=color, linewidth=1.0),
        )
        for patch in bp["boxes"]:
            patch.set_facecolor(color)
            patch.set_edgecolor("white")
            patch.set_alpha(0.85)
            patch.set_linewidth(0.5)
        return bp

    _box(ax, undef_data, x - width / 2, undef_color)
    _box(ax, def_data, x + width / 2, def_color)

    rng = np.random.default_rng(0)

    def _scatter_with_outliers(vals, solved, x_pos, color):
        if not vals:
            return
        arr = np.array(vals, dtype=float)
        solved_arr = np.array(solved, dtype=bool)
        if len(arr) > 1:
            q1, q3 = np.percentile(arr, [25, 75])
            hi = q3 + 1.5 * (q3 - q1)
        else:
            hi = float("inf")
        is_unsolved_outlier = (arr > hi) & (~solved_arr)
        jitter = rng.uniform(-width * 0.25, width * 0.25, size=len(arr))
        xs = np.full(len(arr), x_pos) + jitter
        filled = ~is_unsolved_outlier
        if filled.any():
            ax.scatter(xs[filled], arr[filled], s=10, color=color, alpha=0.55,
                       edgecolors="none", zorder=3)
        if is_unsolved_outlier.any():
            ax.scatter(xs[is_unsolved_outlier], arr[is_unsolved_outlier],
                       s=22, facecolors="none", edgecolors=color,
                       linewidths=1.1, alpha=0.95, zorder=4)

    for i, vals in enumerate(undef_data):
        _scatter_with_outliers(vals, undef_solved[i], x[i] - width / 2, undef_color)
    for i, vals in enumerate(def_data):
        _scatter_with_outliers(vals, def_solved[i], x[i] + width / 2, def_color)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=19)
    ax.set_ylabel("Cost per task (USD)",
                  fontsize=15, fontweight="bold")
    ax.tick_params(axis="y", labelsize=11)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda y, _: f"${y:.2f}"))
    ax.set_ylim(top=5.0)

    legend_handles = [
        mpatches.Patch(facecolor=undef_color, edgecolor="white",
                       label="Undefended"),
        mpatches.Patch(facecolor=def_color, edgecolor="white",
                       label="Masking Defense"),
    ]
    fig.legend(handles=legend_handles, loc="upper center",
               bbox_to_anchor=(0.5, 0.90),
               ncol=2, framealpha=0.9, fontsize=17)
    fig.subplots_adjust(top=0.80, bottom=0.12, left=0.10, right=0.97)
    fig.savefig(output_dir / "cost_total_whisker.png",
                dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / "cost_total_whisker.pdf",
                bbox_inches="tight")
    plt.close(fig)
    print("  Saved cost_total_whisker.png/pdf")

    outlier_csv = output_dir / "cost_total_whisker_outliers.csv"
    with open(outlier_csv, "w", encoding="utf-8") as fh:
        fh.write("model,condition,kind,task_id,cost_usd,n_runs,intent\n")
        print("  Outlier tasks by cost (Tukey: > Q3 + 1.5*IQR) and top-10 by cost:")
        for m, m_label, u_full, d_full in zip(
                models_present, labels, undef_full, def_full):
            for cond_label, (vals, tids, ins, ns, _solved) in (
                    ("Undefended", u_full), ("Masking Defense", d_full)):
                if not vals:
                    continue
                arr = np.array(vals)
                q1, q3 = np.percentile(arr, [25, 75])
                iqr = q3 - q1
                hi = q3 + 1.5 * iqr
                order = np.argsort(arr)[::-1]
                outlier_idx = [i for i in order if arr[i] > hi]
                top_idx = list(order[:10])
                shown = set()
                print(f"    {m_label} / {cond_label}: "
                      f"Q3=${q3:.2f}, hi=${hi:.2f}, max=${arr.max():.2f}")
                for kind, idxs in (("outlier", outlier_idx), ("top10", top_idx)):
                    for i in idxs:
                        key = (kind, tids[i])
                        if key in shown:
                            continue
                        shown.add(key)
                        intent_clean = (ins[i] or "").replace("\n", " ").replace('"', "'")
                        fh.write(f'{m},{cond_label},{kind},{tids[i]},'
                                 f'{vals[i]:.4f},{ns[i]},"{intent_clean}"\n')
                        if kind == "outlier":
                            print(f"      OUTLIER task_id={tids[i]} "
                                  f"cost=${vals[i]:.2f} runs={ns[i]} "
                                  f"intent={intent_clean[:80]!r}")
    print(f"  Saved {outlier_csv.name}")


# ---------------------------------------------------------------------------
# Plot 2: Number of Actions by Task Category
# ---------------------------------------------------------------------------

def plot_action_counts(rows, output_dir: Path):
    """Grouped stacked bar chart of actions by category."""
    rows = _aggregate_rows_by_task(rows)
    by_cond_cat = defaultdict(lambda: defaultdict(lambda: {"steps": [], "qllm": []}))
    for r in rows:
        if r["num_steps"] > 0:
            d = by_cond_cat[r["condition"]][r["category"]]
            d["steps"].append(r["num_steps"])
            d["qllm"].append(r.get("num_qllm", 0))

    conditions = _sort_conditions(list(by_cond_cat.keys()))
    categories = ["Open-Ended", "Navigation", "Environment Action"]
    n_cat = len(categories)

    if not conditions:
        return

    overlay_mode = any(_split_condition_and_model(c)[1] is not None for c in conditions)
    if overlay_mode:
        conditions = _sort_conditions_for_overlay(conditions)
        models_ordered = list(dict.fromkeys(
            _split_condition_and_model(c)[1] for c in conditions
            if _split_condition_and_model(c)[1] is not None))
    n_cond = len(conditions)

    plt.rcParams["hatch.linewidth"] = 1.8

    fig, ax = plt.subplots(figsize=(max(8, n_cond * 2.2), 6))
    bar_width = 0.7 / max(n_cond, 1)
    x = np.arange(n_cat)

    for i, cond in enumerate(conditions):
        base_cond, model = _split_condition_and_model(cond)
        defense_label = _base_condition_label(base_cond)

        if overlay_mode:
            style = _overlay_bar_style(model, defense_label, models_ordered)
        else:
            style = {"color": _condition_color(cond), "hatch": "", "edgecolor": "white"}

        agent_means, qllm_means = [], []
        total_sems = []
        for cat in categories:
            d = by_cond_cat[cond].get(cat, {"steps": [], "qllm": []})
            avg_total = np.mean(d["steps"]) if d["steps"] else 0
            avg_qllm = np.mean(d["qllm"]) if d["qllm"] else 0
            agent_means.append(max(0, avg_total - avg_qllm))
            qllm_means.append(avg_qllm)
            total_sems.append(_std_error(d["steps"]) if d["steps"] else 0.0)

        offset = (i - (n_cond - 1) / 2) * bar_width
        xpos = x + offset

        ax.bar(xpos, agent_means, bar_width * 0.9, color=style["color"], alpha=0.85,
               hatch=style["hatch"], edgecolor=style["edgecolor"], linewidth=0.5)
        ax.bar(xpos, qllm_means, bar_width * 0.9, bottom=agent_means,
               color=style["color"], alpha=0.85, hatch='ooo')
        total_top = [agent_means[j] + qllm_means[j] for j in range(n_cat)]
        ax.errorbar(xpos, total_top, yerr=total_sems, fmt="none",
                    ecolor="black", elinewidth=1.5, capsize=4, capthick=1.5, alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(categories, fontsize=14)
    ax.set_ylabel("Number of Actions", fontsize=16, fontweight="bold")
    ax.tick_params(axis="y", labelsize=14)
    ax.grid(axis="y", alpha=0.25)

    legend_handles = []
    if overlay_mode:
        legend_handles = _overlay_legend_handles(models_ordered)
    else:
        for c in conditions:
            legend_handles.append(mpatches.Patch(
                color=_condition_color(c), alpha=0.85, label=_condition_label(c)))
    legend_handles.append(mpatches.Patch(facecolor='gray', alpha=0.85, hatch='ooo', label="Q-Model Call"))
    fig.legend(handles=legend_handles,
               loc="upper center", bbox_to_anchor=(0.5, 1.01),
               ncol=min(len(legend_handles), 6),
               framealpha=0.9, fontsize=11, handlelength=1.5, columnspacing=1.0)

    plt.tight_layout(rect=[0, 0, 1, 0.92])
    plt.subplots_adjust(top=0.90)
    fig.savefig(output_dir / "actions_by_category.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / "actions_by_category.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved actions_by_category.png/pdf")


# ---------------------------------------------------------------------------
# Plot 3: Per-Template Accuracy
# ---------------------------------------------------------------------------

def plot_template_accuracy(rows, output_dir: Path):
    """Horizontal bar chart: accuracy per template, colored by category."""
    by_template = defaultdict(lambda: {"scores": [], "category": "", "intent": ""})
    for r in rows:
        tmpl = r["template"]
        by_template[tmpl]["scores"].append(r["score"])
        by_template[tmpl]["category"] = r["category"]
        if not by_template[tmpl]["intent"]:
            by_template[tmpl]["intent"] = r["intent"][:60]

    templates = sorted(by_template.keys(),
                       key=lambda t: np.mean(by_template[t]["scores"]), reverse=True)
    means = [np.mean(by_template[t]["scores"]) for t in templates]
    cats = [by_template[t]["category"] for t in templates]
    colors = [CATEGORY_COLORS.get(c, "#95a5a6") for c in cats]
    labels = [f"{t.replace('template_', 'T')}" for t in templates]

    fig, ax = plt.subplots(figsize=(10, max(6, len(templates) * 0.35)))
    y = np.arange(len(templates))
    bars = ax.barh(y, means, color=colors, edgecolor="white", height=0.7, alpha=0.85)

    for i, (bar, mean, tmpl) in enumerate(zip(bars, means, templates)):
        count = len(by_template[tmpl]["scores"])
        intent = by_template[tmpl]["intent"][:45]
        ax.text(bar.get_width() + 0.01, bar.get_y() + bar.get_height() / 2,
                f"{mean:.0%} (n={count}) {intent}", va="center", fontsize=7)

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=7)
    ax.set_xlabel("Utility", fontsize=16, fontweight="bold")
    ax.tick_params(axis="x", labelsize=14)
    ax.set_xlim(0, 1.4)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0%}"))
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.25)

    legend_handles = [mpatches.Patch(facecolor=CATEGORY_COLORS[c], alpha=0.85, label=c)
                      for c in CATEGORY_COLORS]
    ax.legend(handles=legend_handles, fontsize=10, loc="lower right",
              framealpha=0.9)

    fig.tight_layout()
    fig.savefig(output_dir / "template_accuracy.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / "template_accuracy.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved template_accuracy.png/pdf")


# ---------------------------------------------------------------------------
# Plot 4: Per-Template Accuracy Comparison (Defended vs Undefended)
# ---------------------------------------------------------------------------

def _draw_comparison_figure(templates, title, title_color, output_dir, filename,
                            *, conditions, by_tmpl_cond, tmpl_category, tmpl_intent,
                            separator_idx=None, sub_labels=None):
    """Draw one comparison figure for a bucket of templates.

    separator_idx: if set, draw a dashed line between y[separator_idx-1] and y[separator_idx]
    sub_labels: (top_label, bottom_label, top_count, bottom_count) for the two halves
    """
    if not templates:
        return

    def _stats(t, c):
        scores = by_tmpl_cond[t].get(c, [])
        if not scores:
            return 0.0, 0.0
        return float(np.mean(scores)), _std_error(scores)

    CAT_COLORS = {"Open-Ended": "#3498db", "Navigation": "#2ecc71",
                  "Environment Action": "#e67e22"}
    CAT_SHORT = {"Open-Ended": "OE", "Navigation": "Nav",
                 "Environment Action": "Env"}

    n_tmpl = len(templates)
    n_cond = len(conditions)
    bar_h = 0.55 / max(n_cond, 1)
    bar_max = 0.25

    has_sep = separator_idx is not None and 0 < separator_idx < n_tmpl
    gap = 0.8 if has_sep else 0
    y_positions = []
    for i in range(n_tmpl):
        extra = gap if has_sep and i >= separator_idx else 0
        y_positions.append(i + extra)
    y = np.array(y_positions)

    fig_h = max(3, (y[-1] + 1) * 0.50 + 1.2)
    fig, ax = plt.subplots(figsize=(14, fig_h))

    overlay_comp = any(_split_condition_and_model(c)[1] is not None for c in conditions)
    if overlay_comp:
        models_comp = list(dict.fromkeys(
            _split_condition_and_model(c)[1] for c in conditions
            if _split_condition_and_model(c)[1] is not None))

    for i, cond in enumerate(conditions):
        base_cond, model = _split_condition_and_model(cond)
        defense = _base_condition_label(base_cond)
        if overlay_comp:
            style = _overlay_bar_style(model, defense, models_comp)
            color, hatch = style["color"], style["hatch"]
        else:
            color = _condition_color(cond)
            hatch = ""
        means_raw = []
        sems_raw = []
        for t in templates:
            m, se = _stats(t, cond)
            means_raw.append(min(m, 1.0))
            sems_raw.append(se)
        means = [m * bar_max for m in means_raw]
        sems = [se * bar_max for se in sems_raw]
        offset = (i - (n_cond - 1) / 2) * bar_h
        ax.barh(y + offset, means, bar_h * 0.9,
                color=color, alpha=0.85, edgecolor="white", hatch=hatch,
                linewidth=0.5,
                xerr=sems, ecolor="black",
                error_kw={"elinewidth": 1.0, "capthick": 1.0, "capsize": 2})

    if has_sep:
        sep_y = (y[separator_idx - 1] + y[separator_idx]) / 2
        ax.axhline(sep_y, color="#aaaaaa", linewidth=1.2, linestyle="--")

    

    for t_idx, t in enumerate(templates):
        cat = tmpl_category.get(t, "")
        cat_color = CAT_COLORS.get(cat, "#666666")
        cat_short = CAT_SHORT.get(cat, "?")
        t_label = t.replace("template_", "T")
        ax.text(-0.01, y[t_idx], f"{t_label} [{cat_short}]",
                va="center", ha="right", fontsize=9, color=cat_color,
                fontweight="bold")
        intent = tmpl_intent.get(t, "")[:120]
        ax.text(bar_max + 0.015, y[t_idx], intent,
                va="center", fontsize=9.5, color="#222222", fontweight="bold")

    ax.set_yticks([])
    ax.set_xlim(-0.005, 1.0)
    ax.set_xticks([0, bar_max])
    ax.set_xticklabels(["0%", "100%"], fontsize=10)
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.2)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.set_title(f"{title}  ({n_tmpl} templates)", fontsize=14,
                 fontweight="bold", color=title_color, pad=12)

    if overlay_comp:
        legend_handles = _overlay_legend_handles(models_comp)
    else:
        legend_handles = [mpatches.Patch(color=_condition_color(c), alpha=0.85,
                                         label=_condition_label(c))
                          for c in conditions]
    cat_handles = [mpatches.Patch(color=CAT_COLORS[c], alpha=0.85, label=c)
                   for c in ["Open-Ended", "Navigation", "Environment Action"]]
    all_handles = legend_handles + [mpatches.Patch(color="none", label="")] + cat_handles
    ax.legend(handles=all_handles, fontsize=9, loc="lower right",
              framealpha=0.9, ncol=2)

    fig.tight_layout()
    fig.savefig(output_dir / f"{filename}.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / f"{filename}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {filename}.png/pdf")


def plot_template_comparison(rows, output_dir: Path):
    """Three separate figures: both solved, only one solved, neither solved.

    Bucket definitions are run-aware:
    - both: each condition solved at least once across selected runs
    - only_def / only_undef: exactly one condition solved at least once
    - neither: neither condition solved in any selected run
    """
    conditions_present = _sort_conditions(list({r["condition"] for r in rows}))
    if len(conditions_present) != 2:
        print(f"  Skipped template_comparison (needs exactly 2 conditions, found {len(conditions_present)})")
        return

    undef_cond = conditions_present[0]
    def_cond = conditions_present[-1]

    by_tmpl_cond = defaultdict(lambda: defaultdict(list))
    tmpl_category = {}
    tmpl_intent = {}
    for r in rows:
        t = r["template"]
        by_tmpl_cond[t][r["condition"]].append(r["score"])
        tmpl_category[t] = r["category"]
        if t not in tmpl_intent:
            tmpl_intent[t] = r["intent"][:120]

    def _ever_solved(t, c):
        scores = by_tmpl_cond[t].get(c, [])
        return any(s > 0 for s in scores)

    buckets = {"both": [], "only_undef": [], "only_def": [], "neither": []}
    for t in by_tmpl_cond:
        u = _ever_solved(t, undef_cond)
        d = _ever_solved(t, def_cond)
        if u and d:
            buckets["both"].append(t)
        elif u:
            buckets["only_undef"].append(t)
        elif d:
            buckets["only_def"].append(t)
        else:
            buckets["neither"].append(t)

    cat_order = {"Open-Ended": 0, "Navigation": 1, "Environment Action": 2}
    for bk in buckets:
        buckets[bk].sort(key=lambda t: (cat_order.get(tmpl_category.get(t, ""), 9), t))

    only_one_templates = buckets["only_def"] + buckets["only_undef"]
    only_one_separator = len(buckets["only_def"]) if buckets["only_def"] else None

    figures = [
        ("both",    "Both Solved",    "#2ecc71", "comparison_both_solved"),
        ("neither", "Neither Solved",  "#95a5a6", "comparison_neither_solved"),
    ]
    for key, title, color, filename in figures:
        _draw_comparison_figure(
            buckets[key], title, color, output_dir, filename,
            conditions=conditions_present, by_tmpl_cond=by_tmpl_cond,
            tmpl_category=tmpl_category, tmpl_intent=tmpl_intent,
        )

    _draw_comparison_figure(
        only_one_templates, "Only One Solved", "#e67e22", output_dir,
        "comparison_only_one_solved",
        conditions=conditions_present, by_tmpl_cond=by_tmpl_cond,
        tmpl_category=tmpl_category, tmpl_intent=tmpl_intent,
        separator_idx=only_one_separator,
        sub_labels=("Only Defended Solved", "Only Undefended Solved",
                    len(buckets["only_def"]), len(buckets["only_undef"])),
    )


# ---------------------------------------------------------------------------
# Text Summary
# ---------------------------------------------------------------------------

def print_summary(rows):
    """Print a text summary of the results."""
    rows = _aggregate_rows_by_task(rows)
    if not rows:
        print("No results found.")
        return

    print(f"\n{'='*70}")
    print(f"WebArena GitLab Results Summary")
    print(f"{'='*70}")

    by_condition = defaultdict(list)
    for r in rows:
        by_condition[r["condition"]].append(r)

    for cond in sorted(by_condition.keys()):
        cond_rows = by_condition[cond]
        scores = [r["score"] for r in cond_rows]
        label = _condition_label(cond)
        print(f"\n  {label} ({cond})")
        print(f"    Tasks: {len(scores)}, Utility: {np.mean(scores):.1%} ({sum(s == 1.0 for s in scores)}/{len(scores)})")

        by_cat = defaultdict(list)
        for r in cond_rows:
            by_cat[r["category"]].append(r["score"])
        for cat in ["Open-Ended", "Navigation", "Environment Action"]:
            if cat in by_cat:
                s = by_cat[cat]
                print(f"      {cat}: {np.mean(s):.1%} ({sum(x == 1.0 for x in s)}/{len(s)})")

        steps = [r["num_steps"] for r in cond_rows if r["num_steps"] > 0]
        if steps:
            qllm = [r.get("num_qllm", 0) for r in cond_rows if r["num_steps"] > 0]
            clicks = [r.get("num_clicks", 0) for r in cond_rows if r["num_steps"] > 0]
            print(f"    Actions: mean={np.mean(steps):.1f}, median={np.median(steps):.0f}, max={max(steps)}"
                  f"  (clicks={np.mean(clicks):.1f}, Q-LLM={np.mean(qllm):.1f})")

    print(f"\n{'='*70}\n")


# ---------------------------------------------------------------------------
# Plot orchestration / model comparison helpers
# ---------------------------------------------------------------------------

def generate_all_plots(rows, output_dir: Path,
                       rows_for_overall: list[dict] | None = None,
                       rows_for_template_comparison: list[dict] | None = None):
    """Generate the full analysis plot set into output_dir."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plot_overall_accuracy(
        rows,
        output_dir,
        rows_overall=rows_for_overall,
    )
    plot_action_counts(rows, output_dir)
    plot_template_accuracy(rows, output_dir)
    plot_template_comparison(rows_for_template_comparison or rows, output_dir)



# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="plot_webarena.py",
        description=(
            "Plot utility, action, cost and token-usage charts for the "
            "WebArena GitLab benchmark. Reads a results directory and writes "
            "PNG/PDF plots to analysis_output/<results_dir_name>/ (or "
            "--output)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("results_dir", type=str, help="Path to results directory")
    parser.add_argument("--run", type=str, default="all",
                        help="Which run to use per task: latest, best, all, single number (1), list (1,2), or range (1-3) (default: all)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output directory (default: analysis_output/<results_dir_name>/).")
    parser.add_argument("--models", type=str, nargs="+", default=None,
                        help="Optional model folder name(s) to include (e.g., claude-sonnet-4-5-20250929 computer-use-preview)")
    parser.add_argument("--overlay-models", action="store_true",
                        help="Overlay selected models in the same plots by adding model-specific condition bars/curves")
    parser.add_argument("--count-subactions", action="store_true",
                        help="Count every sub-action line as a separate action. "
                             "Default: count unique steps (one step with multiple sub-actions = 1 action)")
    parser.add_argument("--conditions", type=str, nargs="+", default=None,
                        help="Filter to specific condition folder names (prompt part). "
                             "E.g.: --conditions ucm_defense no_security")
    parser.add_argument("--user-help-dir", type=str, default=None,
                        help="Path to a retry/user-help results directory (e.g. "
                             "results_webareana_unsolvable_retry). For each task "
                             "present there, the retry outcome overrides the main "
                             "one; when the run's ask_user.jsonl has entries, the "
                             "task is credited as solved 'with user help' and the "
                             "overall_accuracy plot shades that portion of the bar.")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Also produce the breakdown/ subfolder and per-model "
                             "plots. Default: only the two main paper figures "
                             "(Fig 3a = overall_accuracy, Fig 3b = cost_total_whisker).")
    args = parser.parse_args()

    results_dir = Path(args.results_dir)
    if not results_dir.exists():
        print(f"Error: {results_dir} does not exist")
        sys.exit(1)

    output_dir = Path(args.output) if args.output else Path("analysis_output") / results_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Collecting results from {results_dir}...")
    print(f"  Action counting: {'all sub-actions' if args.count_subactions else 'unique steps (default)'}")
    try:
        rows = collect_results(results_dir, run_selector=args.run,
                               count_subactions=args.count_subactions)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    print(f"  Found {len(rows)} task results")

    if not rows:
        print("No results to analyze.")
        sys.exit(0)

    if args.models:
        wanted = set(args.models)
        rows = [r for r in rows if r["model"] in wanted]
        print(f"  After model filtering: {len(rows)} results")
        if not rows:
            print("No results left after model filtering.")
            sys.exit(0)

    if args.conditions:
        wanted_conds = set(args.conditions)
        rows = [r for r in rows if r["condition"].split("/")[0] in wanted_conds]
        print(f"  After condition filtering ({', '.join(args.conditions)}): {len(rows)} results")
        if not rows:
            print("No results left after condition filtering.")
            sys.exit(0)

    user_help_main_snapshot: list[dict] | None = None
    user_help_rows_snapshot: list[dict] | None = None
    if args.user_help_dir:
        user_help_dir = Path(args.user_help_dir)
        if not user_help_dir.exists():
            print(f"Warning: --user-help-dir {user_help_dir} does not exist; ignoring.")
        else:
            print(f"Collecting user-help (retry) results from {user_help_dir}...")
            help_rows = collect_user_help_rows(user_help_dir, run_selector=args.run,
                                               count_subactions=args.count_subactions)
            if args.models:
                help_rows = [r for r in help_rows if r["model"] in set(args.models)]
            if args.conditions:
                help_rows = [r for r in help_rows
                             if r["condition"].split("/")[0] in set(args.conditions)]
            n_used = sum(1 for r in help_rows if r.get("user_help_used"))
            print(f"  Retry rows: {len(help_rows)} total, {n_used} used ask-user")
            # Snapshot BEFORE merge so the token-increase plot can compute
            # retry-vs-main deltas per (model, task) pair.
            user_help_main_snapshot = list(rows)
            user_help_rows_snapshot = list(help_rows)
            rows = merge_main_with_user_help(rows, help_rows)
            print(f"  After merging with user-help: {len(rows)} rows")

    rows_for_overall = list(rows)

    def _overall_accuracy_rows(rs, rs_overall):
        """If we have more than one model and the rows aren't already
        overlay-encoded, encode the model into the condition so
        `plot_overall_accuracy` draws one pair of bars per model — matching
        the per-model grouping used by `plot_cost_total_whisker`."""
        if not rs_overall:
            return rs, rs_overall
        already_overlay = any("|" in r["condition"] for r in rs_overall)
        models_present = {r["model"] for r in rs_overall}
        if already_overlay or len(models_present) <= 1:
            return rs, rs_overall
        return (_overlay_models_into_condition(rs),
                _overlay_models_into_condition(rs_overall))

    if args.overlay_models:
        rows = _filter_common_tasks_across_models_and_conditions(rows)
        rows_for_overall = _filter_common_tasks_across_models_and_conditions(rows_for_overall)
        print(f"  After common-task filtering across models+conditions: {len(rows)} results")
        if not rows:
            print("No results left after common-task filtering.")
            sys.exit(0)

        rows = _overlay_models_into_condition(rows)
        rows_for_overall = _overlay_models_into_condition(rows_for_overall)
        print(f"  Overlay mode enabled: plotting model+condition as separate series")

    discovered = {r["model"] for r in rows}
    if args.models:
        models = [m for m in args.models if m in discovered]
        for m in sorted(discovered):
            if m not in models:
                models.append(m)
    else:
        models = sorted(discovered)

    if len(models) >= 2:
        print(f"Generating per-model plots for side-by-side comparison: {' | '.join(models)}")
        for m in models:
            model_rows = [r for r in rows if r["model"] == m]
            model_rows_for_overall = [r for r in rows_for_overall if r["model"] == m]
            model_out = output_dir / m
            if args.verbose:
                print(f"\nModel summary: {m}")
                print_summary(model_rows)
                print(f"Generating plots for {m}...")
                generate_all_plots(
                    model_rows,
                    model_out,
                    rows_for_overall=model_rows_for_overall,
                    rows_for_template_comparison=model_rows_for_overall,
                )

        oa_rows, oa_rows_overall = _overall_accuracy_rows(rows, rows_for_overall)
        plot_overall_accuracy(oa_rows, output_dir, rows_overall=oa_rows_overall)
        plot_cost_total_whisker(rows_for_overall, output_dir)

        if args.verbose:
            breakdown_dir = output_dir / "breakdown"
            breakdown_dir.mkdir(parents=True, exist_ok=True)
            plot_token_ratio_distribution_per_model(rows_for_overall, breakdown_dir)
            plot_token_ratio_median_bars(rows_for_overall, breakdown_dir)
            plot_token_usage_levels_median(rows_for_overall, breakdown_dir)
            plot_cost_levels_median(rows_for_overall, breakdown_dir)
            plot_cost_total_levels_median(rows_for_overall, breakdown_dir)
            plot_token_usage_total_whisker(rows_for_overall, breakdown_dir)
            print(f"\nAll plots saved to {output_dir}/")
        else:
            print(f"\n✓ Two main figures (Fig 3a + Fig 3b) at: {output_dir}/")
            print("  Pass --verbose to also produce breakdown/ and per-model dirs.")
    else:
        oa_rows, oa_rows_overall = _overall_accuracy_rows(rows, rows_for_overall)
        plot_overall_accuracy(oa_rows, output_dir, rows_overall=oa_rows_overall)
        plot_cost_total_whisker(rows_for_overall, output_dir)

        if args.verbose:
            print_summary(rows)
            print("Generating plots...")
            breakdown_dir = output_dir / "breakdown"
            breakdown_dir.mkdir(parents=True, exist_ok=True)
            plot_action_counts(rows, breakdown_dir)
            plot_template_accuracy(rows, breakdown_dir)
            plot_template_comparison(rows_for_overall or rows, breakdown_dir)
            plot_token_ratio_distribution_per_model(rows_for_overall, breakdown_dir)
            plot_token_ratio_median_bars(rows_for_overall, breakdown_dir)
            plot_token_usage_levels_median(rows_for_overall, breakdown_dir)
            plot_cost_levels_median(rows_for_overall, breakdown_dir)
            plot_cost_total_levels_median(rows_for_overall, breakdown_dir)
            plot_token_usage_total_whisker(rows_for_overall, breakdown_dir)
            print(f"\nAll plots saved to {output_dir}/")
        else:
            print(f"\n✓ Two main figures (Fig 3a + Fig 3b) at: {output_dir}/")
            print("  Pass --verbose to also produce breakdown/.")


if __name__ == "__main__":
    main()
