#!/usr/bin/env python3
"""
Plot utility, action, cost and token-usage charts for the 10 custom-website suites.

Outputs charts into analysis_output/<results_dir_name>/<model_name>/ per model.
Cross-model comparison plots go under analysis_output/<results_dir_name>/all_models/
and are produced automatically when 2+ model subdirs are present (skip silently with 1).
Default panels: ALL_MODELS_PANELS (Claude Sonnet 4.5/4.6, GPT-5.4). Override
with --all-models-include frag1,frag2. --all-models forces this on.
"""
import csv
import json
import re
from pathlib import Path
from collections import defaultdict
import matplotlib
matplotlib.use('Agg')  # Use non-interactive backend for generating files
import matplotlib.pyplot as plt
import numpy as np
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches

def _model_output_subdir(model_name: str) -> str:
    """Filesystem-safe directory name for per-model analysis_output subfolders."""
    s = str(model_name).strip()
    if not s:
        return "unknown_model"
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s).strip("_")
    return s or "unknown_model"


def _trusted_setting_label(trusted_setting: str | None, system_prompt: str | None = None) -> str:
    """Human-friendly label for trusted_setting (whether content is hidden)."""
    if trusted_setting == "untrusted_masked":
        return "Masking Defense"
    elif trusted_setting == "all_revealed" or trusted_setting == "no_security":
        return "Undefended"
    else:
        return trusted_setting or "unknown"

def _parse_run_path_parts(results_dir: Path, parts: tuple[str, ...]) -> tuple[str, str, str, str | None, str | None, str | None]:
    """
    Parse a results artifact path into (model, system_prompt, task, group, suite, trusted_setting).

    Supports:
      <results>/<model>/<prompt>/<trusted>/<task>/<run_*/>/file
      <results>/<model>/<prompt>/<trusted>/<group>/<task>/<run_*/>/file
      <results>/<model>/<prompt>/<trusted>/<suite>/<group>/<task>/<run_*/>/file
      <results>/<model>/<prompt>/<trusted>/<suite>/<task>/<run_*/>/file
    """
    base_idx = parts.index(results_dir.name)
    model = parts[base_idx + 1]
    system_prompt = parts[base_idx + 2]

    # Find run_* segment
    run_idx = None
    for i in range(base_idx + 3, len(parts)):
        if parts[i].startswith("run_"):
            run_idx = i
            break
    if run_idx is None or run_idx <= base_idx + 3:
        # Fallback to old assumption
        trusted_setting = parts[base_idx + 3] if len(parts) > base_idx + 3 else None
        return model, system_prompt, parts[base_idx + 4], None, None, trusted_setting

    trusted_idx = base_idx + 3
    trusted_setting = parts[trusted_idx] if len(parts) > trusted_idx else None
    segments = list(parts[trusted_idx + 1 : run_idx])  # between trusted_setting and run_*
    task = segments[-1] if segments else parts[base_idx + 4]

    group = None
    suite = None

    def _looks_like_group(s: str) -> bool:
        # current convention in tasks.py: "1_simple", "2_harder", etc.
        return bool(re.match(r"^\d+_", s))

    if len(segments) == 2:
        if _looks_like_group(segments[0]):
            group = segments[0]
        else:
            suite = segments[0]
    elif len(segments) >= 3:
        # Most common: suite/group/task
        if _looks_like_group(segments[-2]):
            suite = segments[-3]
            group = segments[-2]
        else:
            # If no obvious group, treat first as suite (best-effort)
            suite = segments[0]

    return model, system_prompt, task, group, suite, trusted_setting

def _mark_unsafe_required_task_ticks(ax, tasks):
    """
    Visually mark tasks that require opening unsafe content.
    Convention: task ids ending with '_conditional' or '_conditions'.
    """
    unsafe_suffixes = ("_conditional", "_conditions")
    for tick, task in zip(ax.get_xticklabels(), tasks):
        if isinstance(task, str) and task.endswith(unsafe_suffixes):
            tick.set_color("#c0392b")  # red
            tick.set_fontweight("bold")

def load_security_logs(results_dir: Path, allowed_suites=None, allowed_models=None):
    """Load all security logs from the results directory."""
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    # {model: {trusted_setting: {task: [runs]}}}
    
    # Find all security_log.json files
    for log_file in results_dir.rglob("security_log.json"):
        try:
            # Parse path (generic): <results_dir>/<model>/<system_prompt>/<trusted_setting>/<group>/<task>/<run_*/>/security_log.json
            parts = log_file.parts
            try:
                base_idx = parts.index(results_dir.name)
            except ValueError:
                # If results_dir is absolute and not part of parts list for some reason, skip.
                continue

            # Need at least: base + model + prompt + trusted + task + run_X + security_log.json
            # (or + group + task + run_X + security_log.json)
            if len(parts) < base_idx + 6:
                continue
            
            model, system_prompt, task, group, suite, trusted_setting = _parse_run_path_parts(results_dir, parts)

            # Filter by model early (before loading file)
            if allowed_models and model and not any(m in model for m in allowed_models):
                continue
            # Filter by suite early (before loading file)
            if allowed_suites and suite and suite not in allowed_suites:
                continue

            # Read the log file
            with open(log_file, 'r') as f:
                log_data = json.load(f)

            # Extract safe (trusted) and unsafe (untrusted) actions
            safe_actions = log_data.get('trustedRevealed', 0)
            unsafe_actions = log_data.get('untrustedRevealed', 0)
            
            # Group by (trusted_setting, system_prompt) composite key
            composite_key = f"{trusted_setting}|{system_prompt}"
            data[model][composite_key][task].append({
                'safe': safe_actions,
                'unsafe': unsafe_actions,
                'run_path': str(log_file),
                'run_dir': str(log_file.parent),
                'task_group': group,
                'task_suite': suite,
                'trusted_setting': trusted_setting,
                'system_prompt': system_prompt,
            })
            
        except Exception as e:
            print(f"Error processing {log_file}: {e}")
            continue
    
    return data

def load_action_counts(results_dir: Path, allowed_suites=None, allowed_models=None,
                       count_subactions: bool = False):
    """
    Load action counts from model_responses.jsonl files.
    We count ALL entries with {"type": "action", ...} including screenshots, clicks, types, scrolls, and quarantined_llm_analysis.

    Args:
      count_subactions: If False (default), count unique step numbers as actions
          (one step with multiple sub-actions = 1 action). If True, count every
          individual sub-action line separately.

    Returns: {model: {composite_key: {task: [ {"total_actions": int, "qllm_actions": int, ...} ]}}}
    """
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for log_file in results_dir.rglob("model_responses.jsonl"):
        try:
            parts = log_file.parts
            try:
                base_idx = parts.index(results_dir.name)
            except ValueError:
                continue

            # Expected: <results_dir>/<model>/<system_prompt>/<trusted_setting>/<group>/<task>/<run_*/>/model_responses.jsonl
            if len(parts) < base_idx + 6:
                continue

            model, system_prompt, task, group, suite, trusted_setting = _parse_run_path_parts(results_dir, parts)

            # Filter by model early (before loading file)
            if allowed_models and model and not any(m in model for m in allowed_models):
                continue
            # Filter by suite early (before loading file)
            if allowed_suites and suite and suite not in allowed_suites:
                continue

            total_actions = 1  # includes all actions (screenshots, clicks, types, scrolls, qllm, etc.)
            qllm_actions = 0  # only quarantined_llm_analysis actions
            seen_steps = set()
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if isinstance(obj, dict) and obj.get("type") == "action":
                        step_num = obj.get("step")
                        if count_subactions or step_num not in seen_steps:
                            total_actions += 1
                        seen_steps.add(step_num)
                        action_type = obj.get("action_type")
                        if action_type == "quarantined_llm_analysis":
                            qllm_actions += 1

            # Group by (trusted_setting, system_prompt) composite key
            # This allows distinguishing between different system prompts under the same trusted_setting
            composite_key = f"{trusted_setting}|{system_prompt}"
            data[model][composite_key][task].append({
                "trusted_setting": trusted_setting,
                "system_prompt": system_prompt,
                "total_actions": total_actions,
                "qllm_actions": qllm_actions,
                "run_path": str(log_file),
                "run_dir": str(log_file.parent),
                "task_group": group,
                "task_suite": suite,
                "system_prompt": system_prompt,
            })
        except Exception as e:
            print(f"Error processing {log_file}: {e}")
            continue

    return data


def load_success_rates(results_dir: Path, allowed_suites=None, allowed_models=None):
    """
    Load task success results.

    Preferred source (easy to read): per-run `success.json` written by `run_custom_websites.py`.
      - overall_success = success_json["success"] (bool)

    Fallback source: `model_responses.jsonl` (last {"type":"success_check", ...} entry).
      - overall_success = entry["success"]["success"]  (new format)
        or entry["success"] if it's already a bool (legacy fallback)

    Returns: {model: {trusted_setting: {task: [ {"success": 0/1, "run_path": str, "run_dir": str} ]}}}
    """
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    # 1) Preferred: success.json
    for success_file in results_dir.rglob("success.json"):
        try:
            parts = success_file.parts
            try:
                base_idx = parts.index(results_dir.name)
            except ValueError:
                continue

            # Expected: <results_dir>/<model>/<system_prompt>/<trusted_setting>/<group>/<task>/<run_*/>/success.json
            if len(parts) < base_idx + 6:
                continue

            model, system_prompt, task, group, suite, trusted_setting = _parse_run_path_parts(results_dir, parts)

            # Filter by model early (before loading file)
            if allowed_models and model and not any(m in model for m in allowed_models):
                continue
            # Filter by suite early (before loading file)
            if allowed_suites and suite and suite not in allowed_suites:
                continue

            with open(success_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict) or "success" not in payload:
                continue
            last_success = bool(payload.get("success", False))

            # Group by (trusted_setting, system_prompt) composite key
            composite_key = f"{trusted_setting}|{system_prompt}"
            data[model][composite_key][task].append(
                {
                    "success": 1 if last_success else 0,
                    "run_path": str(success_file),
                    "run_dir": str(success_file.parent),
                    "task_group": group,
                    "task_suite": suite,
                    "trusted_setting": trusted_setting,
                    "system_prompt": system_prompt,
                }
            )
        except Exception as e:
            print(f"Error processing {success_file}: {e}")
            continue

    # 2) Fallback: model_responses.jsonl (only if success.json is missing for that run_dir)
    # Build a quick set of run_dirs already covered by success.json.
    covered_run_dirs = set()
    for model, prompts in data.items():
        for prompt, tasks in prompts.items():
            for task, runs in tasks.items():
                for r in runs:
                    d = r.get("run_dir")
                    if d:
                        covered_run_dirs.add(d)

    for log_file in results_dir.rglob("model_responses.jsonl"):
        try:
            # Skip if this run already has success.json
            if str(log_file.parent) in covered_run_dirs:
                continue

            parts = log_file.parts
            try:
                base_idx = parts.index(results_dir.name)
            except ValueError:
                continue

            # Expected: <results_dir>/<model>/<system_prompt>/<trusted_setting>/<group>/<task>/<run_*/>/model_responses.jsonl
            if len(parts) < base_idx + 6:
                continue

            model, system_prompt, task, group, suite, trusted_setting = _parse_run_path_parts(results_dir, parts)

            # Filter by model early (before loading file) - FALLBACK SECTION
            if allowed_models and model and not any(m in model for m in allowed_models):
                continue
            # Filter by suite early (before loading file) - FALLBACK SECTION
            if allowed_suites and suite and suite not in allowed_suites:
                continue

            last_success = None
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    if obj.get("type") != "success_check":
                        continue

                    payload = obj.get("success")
                    # New format: {"task_id": ..., "success": bool, "website": ..., "model": ...}
                    if isinstance(payload, dict) and "success" in payload:
                        last_success = bool(payload.get("success", False))
                    elif isinstance(payload, bool):
                        last_success = bool(payload)
                    else:
                        # Unknown format; ignore.
                        continue

            if last_success is None:
                continue

            # Group by trusted_setting
            data[model][trusted_setting][task].append(
                {
                    "success": 1 if last_success else 0,
                    "run_path": str(log_file),
                    "run_dir": str(log_file.parent),
                    "task_group": group,
                    "task_suite": suite,
                    "system_prompt": system_prompt,
                }
            )
        except Exception as e:
            print(f"Error processing {log_file}: {e}")
            continue
    
    return data


# Prompt-caching-aware pricing (USD per 1M tokens).
MODEL_PRICING_USD_PER_MTOK = {
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0, "cache_write_5m": 3.75, "cache_write_1h": 6.0, "cache_read": 0.30},
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0, "cache_write_5m": 3.75, "cache_write_1h": 6.0, "cache_read": 0.30},
    "claude-opus-4-6": {"input": 5.0, "output": 25.0, "cache_write_5m": 6.25, "cache_write_1h": 10.0, "cache_read": 0.50},
    "claude-opus-4-5": {"input": 5.0, "output": 25.0, "cache_write_5m": 6.25, "cache_write_1h": 10.0, "cache_read": 0.50},
    # OpenAI gpt-5.4 (short-context): input $2.50, cached input $0.25, output $15.00.
    # OpenAI does not bill cache writes separately — caching is automatic and only
    # the cached READ gets discounted. So cache_write_* mirrors the input rate.
    "gpt-5.4": {"input": 2.50, "output": 15.0, "cache_write_5m": 2.50, "cache_write_1h": 2.50, "cache_read": 0.25},
}
DEFAULT_PRICING = MODEL_PRICING_USD_PER_MTOK["claude-sonnet-4-5"]


def _pricing_for_model(model_name: str) -> dict:
    m = (model_name or "").lower()
    for fragment, pricing in MODEL_PRICING_USD_PER_MTOK.items():
        if fragment in m:
            return pricing
    return DEFAULT_PRICING


def _estimate_cost_usd(model_name, input_uncached, output_tokens, cache_read_tokens,
                       cache_write_5m_tokens, cache_write_1h_tokens):
    p = _pricing_for_model(model_name)
    return (
        (input_uncached / 1e6) * p["input"] +
        (output_tokens / 1e6) * p["output"] +
        (cache_read_tokens / 1e6) * p["cache_read"] +
        (cache_write_5m_tokens / 1e6) * p["cache_write_5m"] +
        (cache_write_1h_tokens / 1e6) * p["cache_write_1h"]
    )


def load_token_usage(results_dir: Path, allowed_suites=None, allowed_models=None):
    """
    Load cumulative token usage from token_usage.jsonl files.

    Returns: {model: {composite_key: {task: [ {token fields..., run_dir, task_group, task_suite, system_prompt} ]}}}
    """
    data = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for tu_file in results_dir.rglob("token_usage.jsonl"):
        try:
            parts = tu_file.parts
            try:
                base_idx = parts.index(results_dir.name)
            except ValueError:
                continue
            if len(parts) < base_idx + 6:
                continue

            model, system_prompt, task, group, suite, trusted_setting = _parse_run_path_parts(results_dir, parts)

            if allowed_models and model and not any(m in model for m in allowed_models):
                continue
            if allowed_suites and suite and suite not in allowed_suites:
                continue

            token_input_sum = 0.0
            token_output_sum = 0.0
            token_cache_read_sum = 0.0
            token_cache_write_5m_sum = 0.0
            token_cache_write_1h_sum = 0.0
            token_input_total_qllm_sum = 0.0
            token_output_qllm_sum = 0.0
            token_steps_input = []
            token_steps_output = []
            # QLLM-only accumulators (priced at sonnet-4-5 rate, since QLLM is always claude-sonnet-4-5 regardless of the agent under test)
            qllm_input_uncached = 0.0
            qllm_output = 0.0
            qllm_cache_read = 0.0
            qllm_cache_write_5m = 0.0
            qllm_cache_write_1h = 0.0

            with open(tu_file, "r", encoding="utf-8") as f:
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

                    # OpenAI-style usage (e.g. gpt-5.4): `input_tokens` is the
                    # TOTAL (uncached + cached) and the cached subset lives at
                    # `input_tokens_details.cached_tokens`. Anthropic's
                    # `input_tokens` is already uncached-only, so its
                    # input_tokens_details (when present) is unrelated. We
                    # detect the OpenAI shape by the presence of cached_tokens
                    # and the ABSENCE of Anthropic's cache_read_input_tokens.
                    in_tok_details = usage.get("input_tokens_details") or {}
                    openai_cached = in_tok_details.get("cached_tokens", 0)
                    if (isinstance(openai_cached, (int, float)) and openai_cached > 0
                            and not isinstance(cache_read_tok, (int, float))):
                        # cache_read_tok is missing/0 from Anthropic field;
                        # use the OpenAI cached portion.
                        cache_read_tok = float(openai_cached)
                        if isinstance(in_tok, (int, float)):
                            # Subtract cached so in_tok reflects only
                            # uncached input (matches Anthropic semantics).
                            in_tok = max(0.0, float(in_tok) - float(openai_cached))
                    elif (isinstance(openai_cached, (int, float)) and openai_cached > 0
                          and isinstance(cache_read_tok, (int, float))
                          and cache_read_tok == 0):
                        # Same case but cache_read_tok was explicitly 0.
                        cache_read_tok = float(openai_cached)
                        if isinstance(in_tok, (int, float)):
                            in_tok = max(0.0, float(in_tok) - float(openai_cached))

                    cache_creation_obj = usage.get("cache_creation", {})
                    if isinstance(cache_creation_obj, dict):
                        v5 = cache_creation_obj.get("ephemeral_5m_input_tokens", 0)
                        v1 = cache_creation_obj.get("ephemeral_1h_input_tokens", 0)
                        if isinstance(v5, (int, float)):
                            cache_creation_5m_tok = float(v5)
                        if isinstance(v1, (int, float)):
                            cache_creation_1h_tok = float(v1)

                    if isinstance(cache_creation_total_tok, (int, float)):
                        cache_creation_total_tok = float(cache_creation_total_tok)
                    else:
                        cache_creation_total_tok = 0.0
                    if cache_creation_total_tok > 0 and cache_creation_5m_tok == 0 and cache_creation_1h_tok == 0:
                        cache_creation_5m_tok = cache_creation_total_tok

                    total_input_step = (
                        float(in_tok) +
                        float(cache_read_tok if isinstance(cache_read_tok, (int, float)) else 0.0) +
                        cache_creation_5m_tok +
                        cache_creation_1h_tok
                    ) if isinstance(in_tok, (int, float)) else 0.0

                    if isinstance(in_tok, (int, float)) and isinstance(out_tok, (int, float)):
                        token_steps_input.append(float(in_tok))
                        token_steps_output.append(float(out_tok))
                        cr = float(cache_read_tok) if isinstance(cache_read_tok, (int, float)) else 0.0
                        token_cache_read_sum += cr
                        token_cache_write_5m_sum += cache_creation_5m_tok
                        token_cache_write_1h_sum += cache_creation_1h_tok
                        if obj.get("source") == "qllm":
                            token_input_total_qllm_sum += total_input_step
                            token_output_qllm_sum += float(out_tok)
                            qllm_input_uncached += float(in_tok)
                            qllm_output += float(out_tok)
                            qllm_cache_read += cr
                            qllm_cache_write_5m += cache_creation_5m_tok
                            qllm_cache_write_1h += cache_creation_1h_tok

            token_input_sum = float(np.sum(token_steps_input)) if token_steps_input else 0.0
            token_output_sum = float(np.sum(token_steps_output)) if token_steps_output else 0.0
            token_input_total_sum = (
                token_input_sum + token_cache_read_sum +
                token_cache_write_5m_sum + token_cache_write_1h_sum
            )

            # Cost: split QLLM (always sonnet-4-5) from main agent (model-specific).
            # Subtract QLLM components from totals to get main-agent-only counts.
            agent_input_uncached = max(0.0, token_input_sum - qllm_input_uncached)
            agent_output = max(0.0, token_output_sum - qllm_output)
            agent_cache_read = max(0.0, token_cache_read_sum - qllm_cache_read)
            agent_cache_write_5m = max(0.0, token_cache_write_5m_sum - qllm_cache_write_5m)
            agent_cache_write_1h = max(0.0, token_cache_write_1h_sum - qllm_cache_write_1h)

            cost_agent = _estimate_cost_usd(
                model_name=model,
                input_uncached=agent_input_uncached,
                output_tokens=agent_output,
                cache_read_tokens=agent_cache_read,
                cache_write_5m_tokens=agent_cache_write_5m,
                cache_write_1h_tokens=agent_cache_write_1h,
            )
            cost_qllm = _estimate_cost_usd(
                model_name="claude-sonnet-4-5",
                input_uncached=qllm_input_uncached,
                output_tokens=qllm_output,
                cache_read_tokens=qllm_cache_read,
                cache_write_5m_tokens=qllm_cache_write_5m,
                cache_write_1h_tokens=qllm_cache_write_1h,
            )
            estimated_cost = cost_agent + cost_qllm

            composite_key = f"{trusted_setting}|{system_prompt}"
            data[model][composite_key][task].append({
                "token_input_sum": token_input_sum,
                "token_output_sum": token_output_sum,
                "token_input_total_sum": token_input_total_sum,
                "token_input_total_qllm_sum": token_input_total_qllm_sum,
                "token_output_qllm_sum": token_output_qllm_sum,
                "token_cache_read_sum": token_cache_read_sum,
                "token_cache_write_5m_sum": token_cache_write_5m_sum,
                "token_cache_write_1h_sum": token_cache_write_1h_sum,
                "estimated_cost_usd": estimated_cost,
                "token_steps_input": token_steps_input,
                "token_steps_output": token_steps_output,
                "run_dir": str(tu_file.parent),
                "task_group": group,
                "task_suite": suite,
                "system_prompt": system_prompt,
                "trusted_setting": trusted_setting,
            })
        except Exception as e:
            print(f"Error processing {tu_file}: {e}")
            continue

    return data




def plot_token_usage_absolute_all_models(token_data, output_dir: Path,
                                         model_panels=None):
    """Two-panel grouped bar chart (Input tokens | Output tokens). For each
    model we render two bars — red = Undefended, blue = Masking Defense —
    where each bar's value is the MEDIAN across tasks of the per-task MEAN
    across runs. A "+NN%" label on top of the defended bar reports the
    relative increase over undefended (task-median % increase).

    Aggregation:
      per task: mean tokens across runs within each condition
      per model per condition: MEDIAN across tasks (for the bar height)
      per model: MEDIAN across per-task percent-increases (for the annotation)
    """
    if not token_data:
        return

    all_models = list(token_data.keys())
    if model_panels:
        ordered = []
        seen = set()
        for frag, title in model_panels:
            fl = frag.lower()
            for m in all_models:
                if fl in m.lower() and m not in seen:
                    ordered.append((m, title))
                    seen.add(m)
                    break
    else:
        ordered = [(m, _humanize_model_dir(m)) for m in sorted(all_models)]

    labels = []
    input_undef = []
    input_def = []
    output_undef = []
    output_def = []
    input_pct = []
    output_pct = []

    for model_name, title in ordered:
        by_task_undef = defaultdict(lambda: {"input": [], "output": []})
        by_task_defend = defaultdict(lambda: {"input": [], "output": []})

        for composite_key, tasks in token_data.get(model_name, {}).items():
            parts = composite_key.split("|", 1)
            trusted_setting = parts[0] if parts else composite_key
            system_prompt = parts[1] if len(parts) > 1 else None
            masking_label = _trusted_setting_label(trusted_setting,
                                                   system_prompt)
            if masking_label == "Undefended":
                bucket = by_task_undef
            elif masking_label == "Masking Defense":
                bucket = by_task_defend
            else:
                continue
            for task, runs in tasks.items():
                for r in runs:
                    bucket[task]["input"].append(
                        r.get("token_input_total_sum", 0.0))
                    bucket[task]["output"].append(
                        r.get("token_output_sum", 0.0))

        common = sorted(set(by_task_undef) & set(by_task_defend))
        if not common:
            continue

        in_u_list, in_d_list, out_u_list, out_d_list = [], [], [], []
        in_pcts, out_pcts = [], []
        for task in common:
            u_in = (float(np.mean(by_task_undef[task]["input"]))
                    if by_task_undef[task]["input"] else 0.0)
            d_in = (float(np.mean(by_task_defend[task]["input"]))
                    if by_task_defend[task]["input"] else 0.0)
            u_out = (float(np.mean(by_task_undef[task]["output"]))
                     if by_task_undef[task]["output"] else 0.0)
            d_out = (float(np.mean(by_task_defend[task]["output"]))
                     if by_task_defend[task]["output"] else 0.0)
            in_u_list.append(u_in)
            in_d_list.append(d_in)
            out_u_list.append(u_out)
            out_d_list.append(d_out)
            if u_in > 0:
                in_pcts.append(((d_in - u_in) / u_in) * 100.0)
            if u_out > 0:
                out_pcts.append(((d_out - u_out) / u_out) * 100.0)

        labels.append(title)
        input_undef.append(float(np.median(in_u_list)))
        input_def.append(float(np.median(in_d_list)))
        output_undef.append(float(np.median(out_u_list)))
        output_def.append(float(np.median(out_d_list)))
        input_pct.append(float(np.median(in_pcts)) if in_pcts else 0.0)
        output_pct.append(float(np.median(out_pcts)) if out_pcts else 0.0)

    if not labels:
        print("  plot_token_usage_absolute_all_models: "
              "no paired Undefended/Masking-Defense tasks — skipping")
        return

    # Layout
    n = len(labels)
    x = np.arange(n)
    bar_w = 0.35
    undef_color = "#DC3545"
    def_color = "#007BFF"

    fig, axes = plt.subplots(1, 2, figsize=(max(12, n * 3.4), 5.6))
    for ax, title, u_vals, d_vals, pct_vals, ylabel in [
        (axes[0], "Input tokens", input_undef, input_def, input_pct, "Input tokens"),
        (axes[1], "Output tokens", output_undef, output_def, output_pct, "Output tokens"),
    ]:
        ax.bar(x - bar_w / 2, u_vals, bar_w, color=undef_color,
               edgecolor="white", linewidth=0.5, label="Undefended")
        ax.bar(x + bar_w / 2, d_vals, bar_w, color=def_color,
               edgecolor="white", linewidth=0.5, label="Masking Defense")
        # Annotate ratio (defended / undefended bar heights) above the pair.
        ymax = max(d_vals + u_vals) if (d_vals or u_vals) else 1
        y_offset = ymax * 0.02
        for i, (u_val, d_val) in enumerate(zip(u_vals, d_vals)):
            if u_val > 0:
                ratio = d_val / u_val
                y_ann = max(u_val, d_val) + y_offset
                ax.text(x[i], y_ann, f"{ratio:.2f}x",
                        ha="center", va="bottom", fontsize=11,
                        fontweight="bold", color="black")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=13)
        ax.set_ylabel(ylabel, fontsize=13, fontweight="bold")
        ax.tick_params(axis="y", labelsize=10)
        # Format y-axis with k/M suffix
        def _fmt(y, _):
            if y >= 1_000_000:
                return f"{y / 1_000_000:.1f}M"
            if y >= 1000:
                return f"{int(y / 1000)}k"
            return f"{int(y)}"
        ax.yaxis.set_major_formatter(plt.FuncFormatter(_fmt))
        ax.grid(axis="y", alpha=0.25)
        ax.set_ylim(top=ymax * 1.30 if ymax > 0 else 1)

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 1.00), ncol=2,
               framealpha=0.9, fontsize=12, labels=["Undefended",
                                                     "Masking Defense"])
    stem = "token_usage_absolute_all_models"
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {stem}.png/pdf  (models: {labels})")


def plot_cost_levels_absolute_all_models(token_data, output_dir: Path,
                                         model_panels=None):
    """Two-panel grouped bar chart (Input cost USD | Output cost USD) per model.
    Mirrors plot_token_usage_absolute_all_models but converts token counts to
    USD using model-specific pricing. Bar heights are the median across tasks
    of the per-task mean cost across runs. Annotation above each pair is the
    ratio of defended vs undefended bar heights, formatted as 'Nx'.
    """
    if not token_data:
        return

    all_models = list(token_data.keys())
    if model_panels:
        ordered = []
        seen = set()
        for frag, title in model_panels:
            fl = frag.lower()
            for m in all_models:
                if fl in m.lower() and m not in seen:
                    ordered.append((m, title))
                    seen.add(m)
                    break
    else:
        ordered = [(m, _humanize_model_dir(m)) for m in sorted(all_models)]

    def _input_cost(r: dict, model_name: str) -> float:
        p = _pricing_for_model(model_name)
        return (
            float(r.get("token_input_sum", 0.0)) / 1e6 * p["input"] +
            float(r.get("token_cache_read_sum", 0.0)) / 1e6 * p["cache_read"] +
            float(r.get("token_cache_write_5m_sum", 0.0)) / 1e6 * p["cache_write_5m"] +
            float(r.get("token_cache_write_1h_sum", 0.0)) / 1e6 * p["cache_write_1h"]
        )

    def _output_cost(r: dict, model_name: str) -> float:
        p = _pricing_for_model(model_name)
        return float(r.get("token_output_sum", 0.0)) / 1e6 * p["output"]

    labels = []
    input_undef, input_def = [], []
    output_undef, output_def = [], []

    for model_name, title in ordered:
        by_task_undef = defaultdict(lambda: {"input": [], "output": []})
        by_task_defend = defaultdict(lambda: {"input": [], "output": []})

        for composite_key, tasks in token_data.get(model_name, {}).items():
            parts = composite_key.split("|", 1)
            trusted_setting = parts[0] if parts else composite_key
            system_prompt = parts[1] if len(parts) > 1 else None
            masking_label = _trusted_setting_label(trusted_setting,
                                                   system_prompt)
            if masking_label == "Undefended":
                bucket = by_task_undef
            elif masking_label == "Masking Defense":
                bucket = by_task_defend
            else:
                continue
            for task, runs in tasks.items():
                for r in runs:
                    bucket[task]["input"].append(_input_cost(r, model_name))
                    bucket[task]["output"].append(_output_cost(r, model_name))

        common = sorted(set(by_task_undef) & set(by_task_defend))
        if not common:
            continue

        in_u_list, in_d_list, out_u_list, out_d_list = [], [], [], []
        for task in common:
            u_in = (float(np.mean(by_task_undef[task]["input"]))
                    if by_task_undef[task]["input"] else 0.0)
            d_in = (float(np.mean(by_task_defend[task]["input"]))
                    if by_task_defend[task]["input"] else 0.0)
            u_out = (float(np.mean(by_task_undef[task]["output"]))
                     if by_task_undef[task]["output"] else 0.0)
            d_out = (float(np.mean(by_task_defend[task]["output"]))
                     if by_task_defend[task]["output"] else 0.0)
            in_u_list.append(u_in)
            in_d_list.append(d_in)
            out_u_list.append(u_out)
            out_d_list.append(d_out)

        labels.append(title)
        input_undef.append(float(np.median(in_u_list)))
        input_def.append(float(np.median(in_d_list)))
        output_undef.append(float(np.median(out_u_list)))
        output_def.append(float(np.median(out_d_list)))

    if not labels:
        print("  plot_cost_levels_absolute_all_models: "
              "no paired Undefended/Masking-Defense tasks — skipping")
        return

    n = len(labels)
    x = np.arange(n)
    bar_w = 0.35
    undef_color = "#DC3545"
    def_color = "#007BFF"

    fig, axes = plt.subplots(1, 2, figsize=(max(12, n * 3.4), 5.6))
    for ax, u_vals, d_vals, ylabel in [
        (axes[0], input_undef, input_def, "Input token cost per task (USD)"),
        (axes[1], output_undef, output_def, "Output token cost per task (USD)"),
    ]:
        ax.bar(x - bar_w / 2, u_vals, bar_w, color=undef_color,
               edgecolor="white", linewidth=0.5, label="Undefended")
        ax.bar(x + bar_w / 2, d_vals, bar_w, color=def_color,
               edgecolor="white", linewidth=0.5, label="Masking Defense")
        ymax = max(d_vals + u_vals) if (d_vals or u_vals) else 1
        y_offset = ymax * 0.02
        for i, (u_val, d_val) in enumerate(zip(u_vals, d_vals)):
            if u_val > 0:
                ratio = d_val / u_val
                y_ann = max(u_val, d_val) + y_offset
                ax.text(x[i], y_ann, f"{ratio:.2f}x",
                        ha="center", va="bottom", fontsize=11,
                        fontweight="bold", color="black")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=13)
        ax.set_ylabel(ylabel, fontsize=13, fontweight="bold")
        ax.tick_params(axis="y", labelsize=10)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"${y:.2f}"))
        ax.grid(axis="y", alpha=0.25)
        ax.set_ylim(top=ymax * 1.30 if ymax > 0 else 1)

    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.legend(loc="upper center", bbox_to_anchor=(0.5, 1.00), ncol=2,
               framealpha=0.9, fontsize=12, labels=["Undefended",
                                                     "Masking Defense"])
    stem = "cost_levels_absolute_all_models"
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {stem}.png/pdf  (models: {labels})")


def plot_total_cost_by_group_all_models(token_data, task_groups, output_dir: Path,
                                        model_panels=None, model_filter=None):
    """One figure per task group (1_simple, 2_harder). Single grouped bar chart
    per model showing TOTAL cost per task in USD (input + output, with QLLM
    tokens already priced at sonnet-4-5 in `estimated_cost_usd`). Annotation
    above each pair is the defended/undefended cost ratio.
    """
    if not token_data:
        return

    all_models = list(token_data.keys())
    if model_filter:
        ordered = [(model_filter, _humanize_model_dir(model_filter))]
    elif model_panels:
        ordered = []
        seen = set()
        for frag, title in model_panels:
            fl = frag.lower()
            for m in all_models:
                if fl in m.lower() and m not in seen:
                    ordered.append((m, title))
                    seen.add(m)
                    break
    else:
        ordered = [(m, _humanize_model_dir(m)) for m in sorted(all_models)]

    for group in ("1_simple", "2_harder"):
        labels = []
        undef_cost, def_cost = [], []

        for model_name, title in ordered:
            by_task_undef = defaultdict(list)
            by_task_defend = defaultdict(list)

            for composite_key, tasks in token_data.get(model_name, {}).items():
                parts = composite_key.split("|", 1)
                trusted_setting = parts[0] if parts else composite_key
                system_prompt = parts[1] if len(parts) > 1 else None
                masking_label = _trusted_setting_label(trusted_setting,
                                                       system_prompt)
                if masking_label == "Undefended":
                    bucket = by_task_undef
                elif masking_label == "Masking Defense":
                    bucket = by_task_defend
                else:
                    continue
                for task, runs in tasks.items():
                    for r in runs:
                        if (r.get("task_group") or task_groups.get(task)) != group:
                            continue
                        bucket[task].append(float(r.get("estimated_cost_usd", 0.0)))

            common = sorted(set(by_task_undef) & set(by_task_defend))
            if not common:
                continue

            u_list, d_list = [], []
            for task in common:
                u_list.append(float(np.mean(by_task_undef[task]))
                              if by_task_undef[task] else 0.0)
                d_list.append(float(np.mean(by_task_defend[task]))
                              if by_task_defend[task] else 0.0)

            labels.append(title)
            undef_cost.append(float(np.median(u_list)))
            def_cost.append(float(np.median(d_list)))

        if not labels:
            print(f"  plot_total_cost_by_group_all_models [{group}]: no data — skip")
            continue

        n = len(labels)
        x = np.arange(n)
        bar_w = 0.35
        undef_color = "#DC3545"
        def_color = "#007BFF"

        fig, ax = plt.subplots(figsize=(max(8, n * 2.4), 5.6))
        ax.bar(x - bar_w / 2, undef_cost, bar_w, color=undef_color,
               edgecolor="white", linewidth=0.5, label="Undefended")
        ax.bar(x + bar_w / 2, def_cost, bar_w, color=def_color,
               edgecolor="white", linewidth=0.5, label="Masking Defense")
        ymax = max(undef_cost + def_cost) if (undef_cost or def_cost) else 1
        y_offset = ymax * 0.02
        for i, (u_val, d_val) in enumerate(zip(undef_cost, def_cost)):
            if u_val > 0:
                ratio = d_val / u_val
                y_ann = max(u_val, d_val) + y_offset
                ax.text(x[i], y_ann, f"{ratio:.2f}x",
                        ha="center", va="bottom", fontsize=11,
                        fontweight="bold", color="black")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=13)
        ax.set_ylabel("Total cost per task (USD)", fontsize=13, fontweight="bold")
        ax.tick_params(axis="y", labelsize=10)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"${y:.2f}"))
        ax.grid(axis="y", alpha=0.25)
        # Fixed y-axis cap so 1_simple and 2_harder figures are comparable.
        ax.set_ylim(top=0.18)

        fig.tight_layout(rect=(0, 0, 1, 0.94))
        fig.legend(loc="upper center", bbox_to_anchor=(0.5, 1.00), ncol=2,
                   framealpha=0.9, fontsize=12,
                   labels=["Undefended", "Masking Defense"])
        stem = f"total_cost_absolute_{group}_all_models"
        fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
        fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {stem}.png/pdf  (models: {labels})")


def plot_total_cost_combined_groups_all_models(token_data, task_groups, output_dir: Path,
                                               model_panels=None, model_filter=None):
    """Single-panel version of plot_total_cost_by_group_all_models (Fig 2b).

    Per model, draws 4 bars: Undefended×{simple, harder} and Defended×{simple, harder}.
    Color (red/blue) encodes defense; hatch (solid vs '///') encodes task group
    — same convention as the box-plot variants in this file.
    """
    if not token_data:
        return

    all_models = list(token_data.keys())
    if model_filter:
        ordered = [(model_filter, _humanize_model_dir(model_filter))]
    elif model_panels:
        ordered = []
        seen = set()
        for frag, title in model_panels:
            fl = frag.lower()
            for m in all_models:
                if fl in m.lower() and m not in seen:
                    ordered.append((m, title))
                    seen.add(m)
                    break
    else:
        ordered = [(m, _humanize_model_dir(m)) for m in sorted(all_models)]

    GROUPS = ("1_simple", "2_harder")
    DEFENSES = ("Undefended", "Masking Defense")
    undef_color = "#DC3545"
    def_color = "#007BFF"

    # rows[(model_idx, defense, group)] = median per-task cost across tasks
    rows: dict[tuple[int, str, str], float] = {}
    labels: list[str] = []

    for mi, (model_name, title) in enumerate(ordered):
        by_task = {
            (defense, group): defaultdict(list)
            for defense in DEFENSES for group in GROUPS
        }
        for composite_key, tasks in token_data.get(model_name, {}).items():
            parts = composite_key.split("|", 1)
            trusted_setting = parts[0] if parts else composite_key
            system_prompt = parts[1] if len(parts) > 1 else None
            ml = _trusted_setting_label(trusted_setting, system_prompt)
            if ml not in DEFENSES:
                continue
            for task, runs in tasks.items():
                for r in runs:
                    g = r.get("task_group") or task_groups.get(task)
                    if g not in GROUPS:
                        continue
                    by_task[(ml, g)][task].append(float(r.get("estimated_cost_usd", 0.0)))

        # Per-model median of per-task means for each (defense, group)
        any_data = False
        for defense in DEFENSES:
            for group in GROUPS:
                vals = [
                    float(np.mean(v)) for v in by_task[(defense, group)].values() if v
                ]
                rows[(mi, defense, group)] = float(np.median(vals)) if vals else 0.0
                if vals:
                    any_data = True
        if any_data:
            labels.append(title)

    if not labels:
        print("  plot_total_cost_combined_groups_all_models: no data — skip")
        return

    n = len(labels)
    bar_w = 0.18
    gap_within_pair = 0.02   # space between Undefended and Defended within a group
    gap_between_pairs = 0.05  # space between simple-pair and harder-pair
    pair_stride = 2 * bar_w + gap_within_pair
    pair_center_simple = -(pair_stride + gap_between_pairs) / 2
    pair_center_harder =  (pair_stride + gap_between_pairs) / 2
    inner_offsets = [
        pair_center_simple - (bar_w + gap_within_pair) / 2,  # Undef · simple
        pair_center_simple + (bar_w + gap_within_pair) / 2,  # Def   · simple
        pair_center_harder - (bar_w + gap_within_pair) / 2,  # Undef · harder
        pair_center_harder + (bar_w + gap_within_pair) / 2,  # Def   · harder
    ]
    sub_specs = [
        ("Undefended",      "1_simple", undef_color, None),
        ("Masking Defense", "1_simple", def_color,   None),
        ("Undefended",      "2_harder", undef_color, "///"),
        ("Masking Defense", "2_harder", def_color,   "///"),
    ]

    # Darker shades for the hatch lines so the hatched bars stay visually red/blue.
    undef_hatch = "#7B1F2A"
    def_hatch   = "#003F7F"
    hatch_edge_color = {undef_color: undef_hatch, def_color: def_hatch}

    fig_w = max(7.6, 1.9 * n + 1.9)
    fig, ax = plt.subplots(figsize=(fig_w, 5.4))
    x = np.arange(n)
    bars_by_role: dict[tuple[str, str], list[float]] = {}
    bar_xs_by_role: dict[tuple[str, str], list[float]] = {}
    for off, (defense, group, color, hatch) in zip(inner_offsets, sub_specs):
        heights = [rows.get((mi, defense, group), 0.0) for mi in range(n)]
        if hatch:
            edge = hatch_edge_color[color]
            lw = 0.6
        else:
            edge = "white"
            lw = 0.5
        ax.bar(
            x + off, heights, bar_w,
            color=color, edgecolor=edge, linewidth=lw,
            hatch=hatch, alpha=0.95,
        )
        bars_by_role[(defense, group)] = heights
        bar_xs_by_role[(defense, group)] = list(x + off)

    # Multiplier annotation above each (Undef, Def) pair: Def/Undef ratio.
    ymax = max(
        max(bars_by_role.get(k, [0]), default=0)
        for k in bars_by_role
    ) or 0.18
    y_offset = ymax * 0.02
    for group in ("1_simple", "2_harder"):
        u = bars_by_role.get(("Undefended", group), [0] * n)
        d = bars_by_role.get(("Masking Defense", group), [0] * n)
        ux = bar_xs_by_role.get(("Undefended", group), [])
        dx = bar_xs_by_role.get(("Masking Defense", group), [])
        for i in range(n):
            if u[i] <= 0:
                continue
            ratio = d[i] / u[i]
            xc = (ux[i] + dx[i]) / 2
            yc = max(u[i], d[i]) + y_offset
            ax.text(
                xc, yc, f"{ratio:.2f}x",
                ha="center", va="bottom",
                fontsize=10, fontweight="bold", color="black",
            )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=13)
    ax.set_ylabel("Total cost per task (USD)", fontsize=13, fontweight="bold")
    ax.tick_params(axis="y", labelsize=10)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"${y:.2f}"))
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    ax.set_ylim(top=ymax * 1.30)

    legend_handles = [
        mpatches.Patch(facecolor=undef_color, edgecolor="white", linewidth=0.5,
                       label="Undefended"),
        mpatches.Patch(facecolor=def_color,   edgecolor="white", linewidth=0.5,
                       label="Masking Defense"),
        mpatches.Patch(facecolor="lightgray", edgecolor="black", linewidth=0.8,
                       label="Untrusted content not required"),
        mpatches.Patch(facecolor="lightgray", edgecolor="#222222", linewidth=0.8,
                       hatch="///", label="Untrusted content required"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper center", bbox_to_anchor=(0.5, 1.02),
        ncol=2, framealpha=0.92, fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))

    stem = "total_cost_absolute_combined_groups_all_models"
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight", pad_inches=0.2)
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    print(f"  Saved {stem}.png/pdf  (models: {labels})")


def plot_token_ratio_by_group(token_data, success_data, task_groups, task_suites,
                              output_dir: Path, model_panels=None, model_filter=None):
    """Two figures (1_simple, 2_harder). Each shows median input/output token
    ratio (masking / no-masking) per model across tasks in that group.

    Mirrors webarena_3models_qmodel_string/token_ratio_median_bars.png.
    Per task: mean tokens across runs in each mode → ratio = def/base.
    Bar height = MEDIAN of per-task ratios.
    If model_filter is set, only that single model is plotted (per-model output).
    """
    if not token_data:
        return
    all_models = list(token_data.keys())
    if model_filter:
        ordered = [(model_filter, _humanize_model_dir(model_filter))]
    elif model_panels:
        ordered = []
        seen = set()
        for frag, title in model_panels:
            fl = frag.lower()
            for m in all_models:
                if fl in m.lower() and m not in seen:
                    ordered.append((m, title)); seen.add(m); break
    else:
        ordered = [(m, _humanize_model_dir(m)) for m in sorted(all_models)]

    for group in ("1_simple", "2_harder"):
        labels, in_ratios, out_ratios = [], [], []
        for model_name, title in ordered:
            by_task_undef = defaultdict(lambda: {"input": [], "output": []})
            by_task_def = defaultdict(lambda: {"input": [], "output": []})
            for ck, tasks in token_data.get(model_name, {}).items():
                parts = ck.split("|", 1)
                trusted = parts[0] if parts else ck
                sysp = parts[1] if len(parts) > 1 else None
                lbl = _trusted_setting_label(trusted, sysp)
                if lbl == "Undefended":
                    bucket = by_task_undef
                elif lbl == "Masking Defense":
                    bucket = by_task_def
                else:
                    continue
                for task, runs in tasks.items():
                    if task_groups.get(task) and task_groups[task] != group:
                        continue
                    for r in runs:
                        if (r.get("task_group") or task_groups.get(task)) != group:
                            continue
                        bucket[task]["input"].append(r.get("token_input_total_sum", 0.0))
                        bucket[task]["output"].append(r.get("token_output_sum", 0.0))
            common = sorted(set(by_task_undef) & set(by_task_def))
            in_per_task, out_per_task = [], []
            for t in common:
                u_in = float(np.mean(by_task_undef[t]["input"])) if by_task_undef[t]["input"] else 0.0
                d_in = float(np.mean(by_task_def[t]["input"])) if by_task_def[t]["input"] else 0.0
                u_out = float(np.mean(by_task_undef[t]["output"])) if by_task_undef[t]["output"] else 0.0
                d_out = float(np.mean(by_task_def[t]["output"])) if by_task_def[t]["output"] else 0.0
                if u_in > 0:
                    in_per_task.append(d_in / u_in)
                if u_out > 0:
                    out_per_task.append(d_out / u_out)
            if not (in_per_task or out_per_task):
                continue
            labels.append(title)
            in_ratios.append(float(np.median(in_per_task)) if in_per_task else 0.0)
            out_ratios.append(float(np.median(out_per_task)) if out_per_task else 0.0)

        if not labels:
            print(f"  plot_token_ratio_by_group [{group}]: no paired tasks — skip")
            continue

        n = len(labels)
        x = np.arange(n)
        bar_w = 0.35
        fig, ax = plt.subplots(figsize=(max(7, n * 2.2), 5.6))
        b1 = ax.bar(x - bar_w / 2, in_ratios, bar_w, label="Input tokens", color="#4D77BB", edgecolor="black", linewidth=0.6)
        b2 = ax.bar(x + bar_w / 2, out_ratios, bar_w, label="Output tokens", color="#E97A38", edgecolor="black", linewidth=0.6)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, fontsize=11)
        ax.set_ylabel("Median token ratio (masking / no masking)", fontsize=12, fontweight="bold")
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.grid(axis="y", alpha=0.25)
        for bars in (b1, b2):
            for rect in bars:
                h = rect.get_height()
                ax.text(rect.get_x() + rect.get_width() / 2, h + 0.02,
                        f"{h:.2f}x", ha="center", va="bottom", fontsize=10, fontweight="bold")
        # Y-limit a bit above the tallest bar
        ymax = max(in_ratios + out_ratios) if (in_ratios or out_ratios) else 1.5
        ax.set_ylim(0, ymax * 1.15 + 0.1)
        ax.legend(loc="upper left", frameon=True, fontsize=11)
        stem = f"token_ratio_median_bars_{group}"
        fig.tight_layout()
        fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
        fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
        plt.close(fig)
        print(f"  Saved {stem}.png/pdf  (models: {labels})")


def _draw_paired_box(ax, undef_data, def_data, labels,
                     undef_color="#DC3545", def_color="#007BFF",
                     ylabel="Cost per task (USD)", currency=True):
    """Webarena-style paired box-and-whisker: red Undefended | blue Masking Defense
    side-by-side per model. Solid black median, colored whiskers/caps/fliers,
    white box edges, jittered scatter overlay."""
    n = len(labels)
    within_step = 0.7
    gap_size = 0.6
    x = []
    cur = 0.0
    for i in range(n):
        if i > 0:
            cur += gap_size
        x.append(cur)
        cur += within_step
    x = np.array(x)
    width = 0.30

    def _box(data, positions, color):
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

    _box(undef_data, x - width / 2, undef_color)
    _box(def_data, x + width / 2, def_color)

    rng = np.random.default_rng(0)
    for i, vals in enumerate(undef_data):
        if vals:
            jitter = rng.uniform(-width * 0.25, width * 0.25, size=len(vals))
            ax.scatter(np.full(len(vals), x[i] - width / 2) + jitter, vals,
                       s=10, color=undef_color, alpha=0.55, edgecolors="none", zorder=3)
    for i, vals in enumerate(def_data):
        if vals:
            jitter = rng.uniform(-width * 0.25, width * 0.25, size=len(vals))
            ax.scatter(np.full(len(vals), x[i] + width / 2) + jitter, vals,
                       s=10, color=def_color, alpha=0.55, edgecolors="none", zorder=3)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=13)
    ax.set_ylabel(ylabel, fontsize=15, fontweight="bold")
    ax.tick_params(axis="y", labelsize=11)
    if currency:
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:.2f}"))
    return x, width


def _save_paired_box_with_legend(fig, ax, output_dir: Path, stem: str,
                                 undef_color="#DC3545", def_color="#007BFF"):
    import matplotlib.patches as mpatches
    legend_handles = [
        mpatches.Patch(facecolor=undef_color, edgecolor="white", label="Undefended"),
        mpatches.Patch(facecolor=def_color, edgecolor="white", label="Masking Defense"),
    ]
    fig.legend(handles=legend_handles, loc="upper center",
               bbox_to_anchor=(0.5, 1.04), ncol=2, framealpha=0.9, fontsize=12)
    fig.tight_layout()
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_cost_box_by_group(token_data, task_groups, task_suites, output_dir: Path,
                           model_panels=None, model_filter=None):
    """Two figures (1_simple, 2_harder). Webarena-style paired box-and-whisker
    of per-RUN cost: Undefended vs Masking Defense, per model.

    If model_filter is provided (raw model dir name), only that model is included
    (used for per-model output folders).
    """
    if not token_data:
        return
    all_models = list(token_data.keys())
    if model_filter:
        ordered = [(model_filter, _humanize_model_dir(model_filter))]
    elif model_panels:
        ordered = []
        seen = set()
        for frag, title in model_panels:
            fl = frag.lower()
            for m in all_models:
                if fl in m.lower() and m not in seen:
                    ordered.append((m, title)); seen.add(m); break
    else:
        ordered = [(m, _humanize_model_dir(m)) for m in sorted(all_models)]

    for group in ("1_simple", "2_harder"):
        labels, undef_data, def_data = [], [], []
        for model_name, title in ordered:
            undef_vals, def_vals = [], []
            for ck, tasks in token_data.get(model_name, {}).items():
                parts = ck.split("|", 1)
                trusted = parts[0] if parts else ck
                sysp = parts[1] if len(parts) > 1 else None
                lbl = _trusted_setting_label(trusted, sysp)
                if lbl not in ("Undefended", "Masking Defense"):
                    continue
                for task, runs in tasks.items():
                    for r in runs:
                        if (r.get("task_group") or task_groups.get(task)) != group:
                            continue
                        cost = float(r.get("estimated_cost_usd", 0.0))
                        if lbl == "Undefended":
                            undef_vals.append(cost)
                        else:
                            def_vals.append(cost)
            if not undef_vals and not def_vals:
                continue
            labels.append(title)
            undef_data.append(undef_vals)
            def_data.append(def_vals)
        if not labels:
            print(f"  plot_cost_box_by_group [{group}]: no data — skip")
            continue
        fig, ax = plt.subplots(figsize=(max(8, len(labels) * 2.4), 5.8))
        _draw_paired_box(ax, undef_data, def_data, labels,
                         ylabel="Cost per task (USD)", currency=True)
        stem = f"cost_per_task_box_{group}"
        _save_paired_box_with_legend(fig, ax, output_dir, stem)
        print(f"  Saved {stem}.png/pdf  (models: {labels})")


def plot_cost_box_both_groups_combined(token_data, task_groups, output_dir: Path,
                                       model_panels=None, model_filter=None):
    """Single figure: per-model 4-box cluster
    [Undef-1_simple | Def-1_simple | Undef-2_harder | Def-2_harder].
    Colors: red=Undefended, blue=Masking Defense (same as the existing per-group
    box plot). 2_harder boxes are hatched to distinguish them from 1_simple.
    """
    if not token_data:
        return
    all_models = list(token_data.keys())
    if model_filter:
        ordered = [(model_filter, _humanize_model_dir(model_filter))]
    elif model_panels:
        ordered = []
        seen = set()
        for frag, title in model_panels:
            fl = frag.lower()
            for m in all_models:
                if fl in m.lower() and m not in seen:
                    ordered.append((m, title)); seen.add(m); break
    else:
        ordered = [(m, _humanize_model_dir(m)) for m in sorted(all_models)]

    labels = []
    # Per-model: 4 lists in this order: undef_simple, def_simple, undef_harder, def_harder
    data_simple_undef, data_simple_def = [], []
    data_harder_undef, data_harder_def = [], []

    for model_name, title in ordered:
        per_mode = {
            ("1_simple", "Undefended"): [],
            ("1_simple", "Masking Defense"): [],
            ("2_harder", "Undefended"): [],
            ("2_harder", "Masking Defense"): [],
        }
        for ck, tasks in token_data.get(model_name, {}).items():
            parts = ck.split("|", 1)
            trusted = parts[0] if parts else ck
            sysp = parts[1] if len(parts) > 1 else None
            lbl = _trusted_setting_label(trusted, sysp)
            if lbl not in ("Undefended", "Masking Defense"):
                continue
            for task, runs in tasks.items():
                for r in runs:
                    grp = r.get("task_group") or task_groups.get(task)
                    if grp not in ("1_simple", "2_harder"):
                        continue
                    cost = float(r.get("estimated_cost_usd", 0.0))
                    per_mode[(grp, lbl)].append(cost)

        if not any(per_mode.values()):
            continue
        labels.append(title)
        data_simple_undef.append(per_mode[("1_simple", "Undefended")])
        data_simple_def.append(per_mode[("1_simple", "Masking Defense")])
        data_harder_undef.append(per_mode[("2_harder", "Undefended")])
        data_harder_def.append(per_mode[("2_harder", "Masking Defense")])

    if not labels:
        print("  plot_cost_box_both_groups_combined: no data — skip")
        return

    n = len(labels)
    undef_color = "#DC3545"
    def_color = "#007BFF"

    # Layout: per model, 4 boxes clustered with a small gap between
    # the simple-pair and the harder-pair. Center tick on the cluster.
    box_w = 0.22
    inner_gap = 0.05    # between paired (undef|def) within a group
    group_gap = 0.18    # between simple-cluster and harder-cluster
    cluster_gap = 0.85  # between models
    # Positions for one model's 4 boxes (relative to cluster center 0)
    half = (2 * box_w + inner_gap) / 2 + group_gap / 2
    rel = [
        -half - box_w / 2 - inner_gap / 2,           # undef simple
        -half + box_w / 2 + inner_gap / 2,           # def simple
        +half - box_w / 2 - inner_gap / 2,           # undef harder
        +half + box_w / 2 + inner_gap / 2,           # def harder
    ]
    cluster_centers = []
    cur = 0.0
    for i in range(n):
        if i > 0:
            cur += cluster_gap + (rel[-1] - rel[0])
        cluster_centers.append(cur)
    cluster_centers = np.array(cluster_centers)

    fig, ax = plt.subplots(figsize=(max(10, n * 3.6), 6.0))

    def _box(ax, data_lists, positions, color, hatch=None):
        bp = ax.boxplot(
            data_lists, positions=positions, widths=box_w,
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
            if hatch:
                patch.set_hatch(hatch)
                patch.set_edgecolor("black")
        return bp

    pos_simple_undef = cluster_centers + rel[0]
    pos_simple_def = cluster_centers + rel[1]
    pos_harder_undef = cluster_centers + rel[2]
    pos_harder_def = cluster_centers + rel[3]

    _box(ax, data_simple_undef, pos_simple_undef, undef_color)
    _box(ax, data_simple_def, pos_simple_def, def_color)
    _box(ax, data_harder_undef, pos_harder_undef, undef_color, hatch="///")
    _box(ax, data_harder_def, pos_harder_def, def_color, hatch="///")

    rng = np.random.default_rng(0)
    for vals_set, positions, color in [
        (data_simple_undef, pos_simple_undef, undef_color),
        (data_simple_def, pos_simple_def, def_color),
        (data_harder_undef, pos_harder_undef, undef_color),
        (data_harder_def, pos_harder_def, def_color),
    ]:
        for i, vals in enumerate(vals_set):
            if vals:
                jitter = rng.uniform(-box_w * 0.25, box_w * 0.25, size=len(vals))
                ax.scatter(np.full(len(vals), positions[i]) + jitter, vals,
                           s=10, color=color, alpha=0.55, edgecolors="none", zorder=3)

    ax.set_xticks(cluster_centers)
    ax.set_xticklabels(labels, fontsize=13)
    ax.set_ylabel("Cost per task (USD)", fontsize=15, fontweight="bold")
    ax.tick_params(axis="y", labelsize=11)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:.2f}"))
    ax.grid(axis="y", alpha=0.25)

    # No sub-cluster labels — the legend's solid/hatched markers carry that info.

    import matplotlib.patches as mpatches
    legend_handles = [
        mpatches.Patch(facecolor=undef_color, edgecolor="white", label="Undefended"),
        mpatches.Patch(facecolor=def_color, edgecolor="white", label="Masking Defense"),
        mpatches.Patch(facecolor="white", edgecolor="black",
                       label=r"Untrusted content $\bf{not\ required}$ to solve the task"),
        mpatches.Patch(facecolor="white", edgecolor="black", hatch="///",
                       label=r"Untrusted content $\bf{required}$ to solve the task"),
    ]
    # Place legend just above the axes (close to plot, no overlap with data).
    ax.legend(handles=legend_handles, loc="lower center",
              bbox_to_anchor=(0.5, 1.02), ncol=2, framealpha=0.95, fontsize=11)
    fig.tight_layout()
    stem = "cost_per_task_box_both_groups"
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {stem}.png/pdf  (models: {labels})")


def plot_token_ratio_combined_by_group_all_models(token_data, task_groups,
                                                   output_dir: Path,
                                                   model_panels=None,
                                                   model_filter=None):
    """One figure: x-axis = models, 2 bars per model (1_simple, 2_harder).
    Bar height = MEDIAN across tasks of combined (input+output) token ratio
    (masking / no-masking). Annotation above each bar is the ratio in 'Nx'.
    """
    if not token_data:
        return
    all_models = list(token_data.keys())
    if model_filter:
        ordered = [(model_filter, _humanize_model_dir(model_filter))]
    elif model_panels:
        ordered = []
        seen = set()
        for frag, title in model_panels:
            fl = frag.lower()
            for m in all_models:
                if fl in m.lower() and m not in seen:
                    ordered.append((m, title)); seen.add(m); break
    else:
        ordered = [(m, _humanize_model_dir(m)) for m in sorted(all_models)]

    labels, simple_ratios, harder_ratios = [], [], []
    for model_name, title in ordered:
        per_group_ratio = {}
        for group in ("1_simple", "2_harder"):
            by_task_undef = defaultdict(list)  # combined input+output
            by_task_def = defaultdict(list)
            for ck, tasks in token_data.get(model_name, {}).items():
                parts = ck.split("|", 1)
                trusted = parts[0] if parts else ck
                sysp = parts[1] if len(parts) > 1 else None
                lbl = _trusted_setting_label(trusted, sysp)
                if lbl == "Undefended":
                    bucket = by_task_undef
                elif lbl == "Masking Defense":
                    bucket = by_task_def
                else:
                    continue
                for task, runs in tasks.items():
                    for r in runs:
                        if (r.get("task_group") or task_groups.get(task)) != group:
                            continue
                        combined = (float(r.get("token_input_total_sum", 0.0))
                                    + float(r.get("token_output_sum", 0.0)))
                        bucket[task].append(combined)
            common = sorted(set(by_task_undef) & set(by_task_def))
            ratios = []
            for t in common:
                u = float(np.mean(by_task_undef[t])) if by_task_undef[t] else 0.0
                d = float(np.mean(by_task_def[t])) if by_task_def[t] else 0.0
                if u > 0:
                    ratios.append(d / u)
            per_group_ratio[group] = float(np.median(ratios)) if ratios else 0.0

        if per_group_ratio.get("1_simple") == 0 and per_group_ratio.get("2_harder") == 0:
            continue
        labels.append(title)
        simple_ratios.append(per_group_ratio["1_simple"])
        harder_ratios.append(per_group_ratio["2_harder"])

    if not labels:
        print("  plot_token_ratio_combined_by_group_all_models: no data — skip")
        return

    n = len(labels)
    x = np.arange(n)
    bar_w = 0.35
    fig, ax = plt.subplots(figsize=(max(7, n * 2.2), 5.6))
    b1 = ax.bar(x - bar_w / 2, simple_ratios, bar_w,
                label=r"Untrusted content $\bf{not\ required}$ to solve the task",
                color="#4D77BB", edgecolor="black", linewidth=0.6)
    b2 = ax.bar(x + bar_w / 2, harder_ratios, bar_w,
                label=r"Untrusted content $\bf{required}$ to solve the task",
                color="#E97A38", edgecolor="black", linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=12)
    ax.set_ylabel("Median token ratio (masking / no masking)",
                  fontsize=12, fontweight="bold")
    ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.grid(axis="y", alpha=0.25)
    for bars in (b1, b2):
        for rect in bars:
            h = rect.get_height()
            ax.text(rect.get_x() + rect.get_width() / 2, h + 0.02,
                    f"{h:.2f}x", ha="center", va="bottom",
                    fontsize=10, fontweight="bold")
    ymax = max(simple_ratios + harder_ratios) if (simple_ratios or harder_ratios) else 1.5
    ax.set_ylim(0, ymax * 1.18 + 0.1)
    ax.legend(loc="upper left", frameon=True, fontsize=10)
    stem = "token_ratio_combined_bars_both_groups"
    fig.tight_layout()
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {stem}.png/pdf  (models: {labels})")


def plot_token_ratio_combined_by_suite_per_model(token_data, task_groups, task_suites,
                                                 output_dir: Path,
                                                 model_filter, model_label=None):
    """Per model: one figure with x-axis = suite, two bars per suite
    (1_simple, 2_harder), bar height = MEDIAN per-task combined (input+output)
    token ratio (masking / no-masking) across tasks in that (suite, group).
    """
    if not token_data or model_filter not in token_data:
        return
    model_label = model_label or _humanize_model_dir(model_filter)

    # (suite, group) -> {task: {"undef": [..], "def": [..]}}
    by_sg = defaultdict(lambda: defaultdict(lambda: {"undef": [], "def": []}))
    for ck, tasks in token_data[model_filter].items():
        parts = ck.split("|", 1)
        trusted = parts[0] if parts else ck
        sysp = parts[1] if len(parts) > 1 else None
        lbl = _trusted_setting_label(trusted, sysp)
        if lbl == "Undefended":
            mkey = "undef"
        elif lbl == "Masking Defense":
            mkey = "def"
        else:
            continue
        for task, runs in tasks.items():
            for r in runs:
                suite = r.get("task_suite") or task_suites.get(task)
                group = r.get("task_group") or task_groups.get(task)
                if not suite or group not in ("1_simple", "2_harder"):
                    continue
                combined = (float(r.get("token_input_total_sum", 0.0))
                            + float(r.get("token_output_sum", 0.0)))
                by_sg[(suite, group)][task][mkey].append(combined)

    # Collect ordered suites
    suites = sorted({s for (s, _g) in by_sg.keys()})
    if not suites:
        print(f"  plot_token_ratio_combined_by_suite_per_model[{model_filter}]: no data — skip")
        return

    simple_ratios, harder_ratios = [], []
    for suite in suites:
        for group, out_list in (("1_simple", simple_ratios), ("2_harder", harder_ratios)):
            tasks_dict = by_sg.get((suite, group), {})
            ratios = []
            for task, modes in tasks_dict.items():
                u = float(np.mean(modes["undef"])) if modes["undef"] else 0.0
                d = float(np.mean(modes["def"])) if modes["def"] else 0.0
                if u > 0 and modes["undef"] and modes["def"]:
                    ratios.append(d / u)
            out_list.append(float(np.median(ratios)) if ratios else float("nan"))

    n = len(suites)
    x = np.arange(n)
    bar_w = 0.35
    fig, ax = plt.subplots(figsize=(max(9, n * 1.4), 5.6))
    b1 = ax.bar(x - bar_w / 2, simple_ratios, bar_w,
                label=r"Untrusted content $\bf{not\ required}$ to solve the task",
                color="#4D77BB", edgecolor="black", linewidth=0.6)
    b2 = ax.bar(x + bar_w / 2, harder_ratios, bar_w,
                label=r"Untrusted content $\bf{required}$ to solve the task",
                color="#E97A38", edgecolor="black", linewidth=0.6)
    ax.set_xticks(x)
    ax.set_xticklabels([s.replace("-", "\n") for s in suites], fontsize=10)
    ax.set_ylabel("Median token ratio (masking / no masking)",
                  fontsize=11, fontweight="bold")
    ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
    ax.grid(axis="y", alpha=0.25)
    finite = [v for v in (simple_ratios + harder_ratios)
              if isinstance(v, (int, float)) and not (v != v)]
    ymax = max(finite) if finite else 1.5
    for bars in (b1, b2):
        for rect in bars:
            h = rect.get_height()
            if isinstance(h, (int, float)) and h == h and h > 0:
                ax.text(rect.get_x() + rect.get_width() / 2, h + ymax * 0.015,
                        f"{h:.2f}x", ha="center", va="bottom",
                        fontsize=8.5, fontweight="bold")
    ax.set_ylim(0, ymax * 1.20 + 0.1)
    ax.legend(loc="upper left", frameon=True, fontsize=10)
    stem = f"token_ratio_combined_by_suite_{_model_output_subdir(model_filter)}"
    fig.tight_layout()
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)
    print(f"  Saved {stem}.png/pdf  (suites: {suites})")


def plot_token_ratio_by_task(token_data, task_groups, task_suites, output_dir: Path,
                             model_filter, model_label=None):
    """Per-model: for each (suite, group) combination, write a chart with
    one bar pair per task showing input/output token ratio (masking/no-masking).

    Mirrors the per-task utility chart layout (utility_by_task_<suite>_<group>_<model>).
    Output naming: token_ratio_by_task_<suite>_<group>_<model>.png
    """
    if not token_data or model_filter not in token_data:
        return
    model_label = model_label or _humanize_model_dir(model_filter)

    # Group data by (suite, group, task) → mean tokens per mode
    by_suite_group = defaultdict(lambda: defaultdict(lambda: {
        "undef": {"input": [], "output": []},
        "def":   {"input": [], "output": []},
    }))  # (suite, group) -> {task: {undef/def: {input, output}}}

    for ck, tasks in token_data[model_filter].items():
        parts = ck.split("|", 1)
        trusted = parts[0] if parts else ck
        sysp = parts[1] if len(parts) > 1 else None
        lbl = _trusted_setting_label(trusted, sysp)
        if lbl == "Undefended":
            mkey = "undef"
        elif lbl == "Masking Defense":
            mkey = "def"
        else:
            continue
        for task, runs in tasks.items():
            for r in runs:
                suite = r.get("task_suite") or task_suites.get(task) or ""
                group = r.get("task_group") or task_groups.get(task) or ""
                if not suite or not group:
                    continue
                by_suite_group[(suite, group)][task][mkey]["input"].append(
                    r.get("token_input_total_sum", 0.0))
                by_suite_group[(suite, group)][task][mkey]["output"].append(
                    r.get("token_output_sum", 0.0))

    n_charts = 0
    for (suite, group), task_map in sorted(by_suite_group.items()):
        # Build per-task ratios
        tasks_sorted = sorted(task_map.keys())
        in_ratios = []
        out_ratios = []
        kept_tasks = []
        for t in tasks_sorted:
            d = task_map[t]
            u_in = float(np.mean(d["undef"]["input"])) if d["undef"]["input"] else 0.0
            d_in = float(np.mean(d["def"]["input"])) if d["def"]["input"] else 0.0
            u_out = float(np.mean(d["undef"]["output"])) if d["undef"]["output"] else 0.0
            d_out = float(np.mean(d["def"]["output"])) if d["def"]["output"] else 0.0
            if u_in <= 0 and u_out <= 0:
                continue
            in_ratios.append(d_in / u_in if u_in > 0 else 0.0)
            out_ratios.append(d_out / u_out if u_out > 0 else 0.0)
            kept_tasks.append(t)
        if not kept_tasks:
            continue

        n = len(kept_tasks)
        x = np.arange(n)
        bar_w = 0.35
        fig, ax = plt.subplots(figsize=(7.0, 5.0))
        b1 = ax.bar(x - bar_w / 2, in_ratios, bar_w, label="Input tokens",
                    color="#4D77BB", edgecolor="black", linewidth=0.6)
        b2 = ax.bar(x + bar_w / 2, out_ratios, bar_w, label="Output tokens",
                    color="#E97A38", edgecolor="black", linewidth=0.6)
        ax.set_xticks(x)
        # Strip suite prefix and wrap long labels onto two lines so they fit
        # uniformly with shorter labels in other suites.
        prefix = f"{suite}_"
        def _shorten(t: str) -> str:
            s = t[len(prefix):] if t.startswith(prefix) else t
            if len(s) <= 18:
                return s
            parts = s.split("_")
            mid = len(parts) // 2
            best, best_diff = mid, 10**9
            for i in range(1, len(parts)):
                left = len("_".join(parts[:i]))
                right = len("_".join(parts[i:]))
                diff = abs(left - right)
                if diff < best_diff:
                    best_diff, best = diff, i
            return "_".join(parts[:best]) + "\n" + "_".join(parts[best:])
        display_labels = [_shorten(t) for t in kept_tasks]
        ax.set_xticklabels(display_labels, rotation=30, ha="right", fontsize=10)
        ax.set_xlim(-0.6, n - 0.4)
        ax.set_ylabel("Token ratio (masking / no masking)", fontsize=11, fontweight="bold")
        ax.axhline(1.0, color="gray", linestyle="--", linewidth=0.8, alpha=0.6)
        ax.grid(axis="y", alpha=0.25)
        # Annotate values
        for bars, vals in ((b1, in_ratios), (b2, out_ratios)):
            for rect, v in zip(bars, vals):
                ax.text(rect.get_x() + rect.get_width() / 2, v + 0.03,
                        f"{v:.2f}x", ha="center", va="bottom", fontsize=8)
        ax.set_ylim(0, 3.5)
        ax.legend(loc="upper left", frameon=True, fontsize=10)
        stem = f"token_ratio_by_task_{suite}_{group}_{model_filter}"
        fig.tight_layout()
        fig.savefig(output_dir / f"{stem}.png", dpi=300)
        fig.savefig(output_dir / f"{stem}.pdf")
        plt.close(fig)
        n_charts += 1
    if n_charts:
        print(f"  Saved {n_charts} per-task token-ratio charts for {model_label}")


def plot_action_box_by_group(action_data, task_groups, task_suites, output_dir: Path,
                             model_panels=None, model_filter=None):
    """Two figures (1_simple, 2_harder). Box-and-whisker of per-RUN total action
    count, Undefended vs Masking Defense, per model.

    Lower median in 'Masking Defense' = defense made the agent faster (e.g.
    forced filter use instead of brute-scrolling)."""
    if not action_data:
        return
    all_models = list(action_data.keys())
    if model_filter:
        ordered = [(model_filter, _humanize_model_dir(model_filter))]
    elif model_panels:
        ordered = []
        seen = set()
        for frag, title in model_panels:
            fl = frag.lower()
            for m in all_models:
                if fl in m.lower() and m not in seen:
                    ordered.append((m, title)); seen.add(m); break
    else:
        ordered = [(m, _humanize_model_dir(m)) for m in sorted(all_models)]

    for group in ("1_simple", "2_harder"):
        labels, undef_data, def_data = [], [], []
        for model_name, title in ordered:
            undef_vals, def_vals = [], []
            for ck, tasks in action_data.get(model_name, {}).items():
                parts = ck.split("|", 1)
                trusted = parts[0] if parts else ck
                sysp = parts[1] if len(parts) > 1 else None
                lbl = _trusted_setting_label(trusted, sysp)
                if lbl not in ("Undefended", "Masking Defense"):
                    continue
                for task, runs in tasks.items():
                    for r in runs:
                        if (r.get("task_group") or task_groups.get(task)) != group:
                            continue
                        n_act = r.get("total_actions") or r.get("n_actions") or r.get("actions_total") or 0
                        try:
                            n_act = float(n_act)
                        except Exception:
                            continue
                        if lbl == "Undefended":
                            undef_vals.append(n_act)
                        else:
                            def_vals.append(n_act)
            if not undef_vals and not def_vals:
                continue
            labels.append(title)
            undef_data.append(undef_vals)
            def_data.append(def_vals)
        if not labels:
            print(f"  plot_action_box_by_group [{group}]: no data — skip")
            continue
        fig, ax = plt.subplots(figsize=(max(8, len(labels) * 2.4), 5.8))
        _draw_paired_box(ax, undef_data, def_data, labels,
                         ylabel="Actions per task", currency=False)
        stem = f"actions_per_task_box_{group}"
        _save_paired_box_with_legend(fig, ax, output_dir, stem)
        print(f"  Saved {stem}.png/pdf  (models: {labels})")


def calculate_averages(data):
    """Calculate average safe and unsafe actions per task and per trusted_setting."""
    # Return per-model structures:
    # task_averages[model][trusted_setting][task] = stats
    # trusted_setting_avgs[model][trusted_setting] = stats
    # task_groups[model][task] = group (e.g., "1_simple", "2_harder")
    # task_suites[model][task] = suite (e.g., "banking", "calendar")
    task_averages = defaultdict(lambda: defaultdict(dict))
    trusted_setting_avgs = defaultdict(dict)
    task_groups = defaultdict(dict)  # Track group per task
    task_suites = defaultdict(dict)  # Track suite per task

    for model, trusted_settings in data.items():
        task_averages_for_model = defaultdict(dict)
        trusted_setting_averages_accum = defaultdict(lambda: {'safe': [], 'unsafe': []})

        for composite_key, tasks in trusted_settings.items():
            # Extract trusted_setting from composite key
            parts = composite_key.split("|", 1)
            trusted_setting_name = parts[0] if parts else composite_key
            
            for task, runs in tasks.items():
                if not runs:
                    continue
                
                safe_values = [r['safe'] for r in runs]
                unsafe_values = [r['unsafe'] for r in runs]
                
                avg_safe = sum(safe_values) / len(safe_values) if safe_values else 0
                avg_unsafe = sum(unsafe_values) / len(unsafe_values) if unsafe_values else 0
                min_safe = min(safe_values) if safe_values else 0
                max_safe = max(safe_values) if safe_values else 0
                min_unsafe = min(unsafe_values) if unsafe_values else 0
                max_unsafe = max(unsafe_values) if unsafe_values else 0
                
                task_averages_for_model[composite_key][task] = {
                    'avg_safe': avg_safe,
                    'avg_unsafe': avg_unsafe,
                    'min_safe': min_safe,
                    'max_safe': max_safe,
                    'min_unsafe': min_unsafe,
                    'max_unsafe': max_unsafe,
                    'num_runs': len(runs)
                }
                
                # Track group and suite from first run (all runs for a task should have same group/suite)
                if task not in task_groups[model] and runs:
                    task_groups[model][task] = runs[0].get('task_group') or 'ungrouped'
                if task not in task_suites[model] and runs:
                    task_suites[model][task] = runs[0].get('task_suite') or 'unspecified'

                trusted_setting_averages_accum[composite_key]['safe'].extend(safe_values)
                trusted_setting_averages_accum[composite_key]['unsafe'].extend(unsafe_values)

        # Calculate trusted_setting-level averages for this model
        trusted_setting_avgs_for_model = {}
        for ts, values in trusted_setting_averages_accum.items():
            safe_vals = values['safe']
            unsafe_vals = values['unsafe']
            trusted_setting_avgs_for_model[ts] = {
                'avg_safe': sum(safe_vals) / len(safe_vals) if safe_vals else 0,
                'avg_unsafe': sum(unsafe_vals) / len(unsafe_vals) if unsafe_vals else 0,
                'min_safe': min(safe_vals) if safe_vals else 0,
                'max_safe': max(safe_vals) if safe_vals else 0,
                'min_unsafe': min(unsafe_vals) if unsafe_vals else 0,
                'max_unsafe': max(unsafe_vals) if unsafe_vals else 0,
                'num_runs': len(safe_vals)
            }
    
        task_averages[model] = task_averages_for_model
        trusted_setting_avgs[model] = trusted_setting_avgs_for_model

    return task_averages, trusted_setting_avgs, task_groups, task_suites

def _plot_grouped_by_task_and_prompt_with_errorbars(
    task_stats_for_model,
    output_dir: Path,
    model_name: str,
    *,
    value_key: str,
    min_key: str,
    max_key: str,
    filename_prefix: str,
    ylabel: str,
    title: str,
    task_groups: dict = None,
    task_suites: dict = None,
    exclude_trusted_settings: list = None,
):
    """
    Grouped bar chart with subplots by group:
    - X axis: tasks
    - Sub-bars: trusted_settings (hiding vs no hiding)
    - Y: avg metric per run
    - Two subplots: one for group 1_simple, one for group 2_harder
    - Colors based on trusted_setting (whether content is hidden)
    Includes min/max error bars (across runs).
    """
    # Collect all tasks/trusted_settings present
    all_tasks = set()
    all_trusted_settings = sorted(task_stats_for_model.keys())
    # Filter out excluded trusted_settings
    if exclude_trusted_settings:
        all_trusted_settings = [ts for ts in all_trusted_settings if ts not in exclude_trusted_settings]
    for ts in all_trusted_settings:
        all_tasks.update(task_stats_for_model[ts].keys())
    tasks = sorted(all_tasks)

    if not tasks or not all_trusted_settings:
        return

    # Group tasks by suite and group
    tasks_by_suite_and_group = defaultdict(lambda: defaultdict(list))
    for task in tasks:
        group = (task_groups or {}).get(task, 'ungrouped')
        suite = (task_suites or {}).get(task, 'unspecified')
        tasks_by_suite_and_group[suite][group].append(task)
    
    # Sort groups: 1_simple first, then 2_harder, then others
    group_order = ['1_simple', '2_harder', 'ungrouped']
    
    # Generate a separate graph for each suite-group combination
    for suite in sorted(tasks_by_suite_and_group.keys()):
        for group in sorted(tasks_by_suite_and_group[suite].keys(), 
                           key=lambda g: (group_order.index(g) if g in group_order else 999, g)):
            group_tasks = sorted(tasks_by_suite_and_group[suite][group])
            if not group_tasks:
                continue
            
            # Create single plot for this suite-group combination
            fig, ax = plt.subplots(1, 1, figsize=(max(12, 0.8 * len(group_tasks)), 6))
            
            x = np.arange(len(group_tasks))
            group_width = 0.85
            bar_width = group_width / max(1, len(all_trusted_settings))
            
            # Color map matching aggregation function
            color_map = {
                "Undefended": "#DC3545",  # Red
                "Masking Defense": "#007BFF",  # Blue
            }
            default_color = "#1f77b4"
            
            for i, composite_key in enumerate(all_trusted_settings):
                vals = []
                err_low = []
                err_high = []
                # Extract trusted_setting and system_prompt from composite key
                parts = composite_key.split("|", 1)
                trusted_setting = parts[0] if parts else composite_key
                system_prompt = parts[1] if len(parts) > 1 else None
                masking_label = _trusted_setting_label(trusted_setting, system_prompt)
                
                for task in group_tasks:
                    stats = task_stats_for_model.get(composite_key, {}).get(task)
                    if stats:
                        v = stats.get(value_key, 0) or 0
                        mn = stats.get(min_key, v) if stats.get(min_key, None) is not None else v
                        mx = stats.get(max_key, v) if stats.get(max_key, None) is not None else v
                    else:
                        v = 0
                        mn = 0
                        mx = 0
                    vals.append(v)
                    err_low.append(max(0, v - mn))
                    err_high.append(max(0, mx - v))

                offset = (i - (len(all_trusted_settings) - 1) / 2) * bar_width
                
                # Use consistent colors matching aggregation
                color = color_map.get(masking_label, default_color)
                
                ax.bar(
                    x + offset,
                    vals,
                    bar_width,
                    label=masking_label,
                    alpha=0.85,
                    yerr=[err_low, err_high],
                    capsize=4,
                    error_kw={"elinewidth": 1.5, "capthick": 1.5},
                    color=color,
                )

            ax.set_xlabel('Task', fontsize=12)
            ax.set_ylabel("Utility", fontsize=16, fontweight='bold')
            ax.tick_params(axis='y', labelsize=14)
            
            # Format group and suite labels
            group_label = group.replace('_', ' ').title() if group != 'ungrouped' else 'Other'
            suite_label = suite.replace('_', ' ').title() if suite != 'unspecified' else ''
            # Match aggregation title format
            if group == '1_simple':
                group_label = 'Group I'
            elif group == '2_harder':
                group_label = 'Group II'
            
            ax.set_xticks(x)
            ax.set_xticklabels(group_tasks, rotation=35, ha='right', color='black')
            _mark_unsafe_required_task_ticks(ax, group_tasks)
            ax.grid(axis='y', alpha=0.25)
            
            # Set y-axis limits for utility/success graphs to always be 0-1
            if 'success' in ylabel.lower() or 'utility' in ylabel.lower():
                ax.set_ylim([0, 1.0])
            
            # Get unique labels for legend
            handles, labels_list = ax.get_legend_handles_labels()
            unique_labels = []
            unique_handles = []
            for handle, label in zip(handles, labels_list):
                if label not in unique_labels:
                    unique_labels.append(label)
                    unique_handles.append(handle)
            
            # Create legend matching aggregation format
            fig.legend(handles=unique_handles, labels=unique_labels,
                      loc='upper center', bbox_to_anchor=(0.5, 1.01), ncol=2,
                      framealpha=0.9, fontsize=14, handlelength=1.5, columnspacing=1.2)

            # No title for per-task graphs
            plt.tight_layout(rect=[0, 0, 1, 0.92])
            plt.subplots_adjust(top=0.90)
            
            # Generate filename with suite and group
            suite_suffix = f"_{suite}" if suite != 'unspecified' else ""
            group_suffix = f"_{group}" if group != 'ungrouped' else ""
            output_file = output_dir / f'{filename_prefix}{suite_suffix}{group_suffix}_{model_name}.png'
            plt.savefig(output_file, dpi=300, bbox_inches='tight')
            print(f"Saved: {output_file}")
            output_file_pdf = output_dir / f'{filename_prefix}{suite_suffix}{group_suffix}_{model_name}.pdf'
            plt.savefig(output_file_pdf, bbox_inches='tight')
            print(f"Saved: {output_file_pdf}")
            plt.close()

def plot_aggregated_summary(
    action_type_task_stats: dict,
    unsafe_task_stats: dict,
    success_task_stats: dict,
    output_dir: Path,
    model_name: str,
    task_groups: dict = None,
    task_group_filter: str = None,
    task_suites: dict = None,
    action_data: dict = None,
    success_data: dict = None,
    use_average: bool = False,
    group_by_task_group: bool = False,
):
    """
    Creates two separate summary figures aggregating metrics across tasks in a specific group:
    1. Utility (success rate)
    2. Number of Actions (agent actions = click + type + qllm, with Q-LLM calls overlaid as separate metric)
    
    Args:
        task_group_filter: If provided, only aggregate tasks from this group (e.g., "1_simple", "2_harder")
        task_suites: Dict mapping task to suite name. If multiple suites are present, data will be grouped by suite.
    """
    # Get all composite keys (trusted_setting|system_prompt)
    all_keys = set()
    all_keys.update(action_type_task_stats.keys())
    all_keys.update(unsafe_task_stats.keys())
    all_keys.update(success_task_stats.keys())
    # Also include keys from action_data and success_data if available
    if action_data and model_name in action_data:
        all_keys.update(action_data[model_name].keys())
    if success_data and model_name in success_data:
        all_keys.update(success_data[model_name].keys())
    composite_keys = sorted(all_keys)
    
    if not composite_keys:
        return
    
    # Check if we have multiple suites and should group by suite
    suites_present = set()
    if task_suites:
        # task_suites is a dict mapping task -> suite
        suites_present = {s for s in task_suites.values() if s and s != 'unspecified'}
    group_by_suite = len(suites_present) > 1 and not group_by_task_group
    
    # Aggregate across tasks (filtered by group if specified) for each metric
    # If grouping by task group (single suite case), aggregate per task group and per masking setting
    if group_by_task_group:
        # Collect action values - similar to suite grouping but by task_group
        group_aggregated = defaultdict(lambda: defaultdict(lambda: {"base_actions": [], "qllm_actions": []}))
        
        if action_data:
            for ck in composite_keys:
                parts = ck.split("|", 1)
                trusted_setting = parts[0] if parts else ck
                system_prompt = parts[1] if len(parts) > 1 else None
                masking_label = _trusted_setting_label(trusted_setting, system_prompt)
                
                if ck in action_data:
                    for task, runs in action_data[ck].items():
                        task_group = task_groups.get(task) if task_groups else None
                        if not task_group or task_group == 'ungrouped':
                            continue
                        
                        # Always aggregate per-task first, then collect one value per task.
                        # For average: mean across runs; for median: median across runs.
                        task_base_actions = []
                        task_qllm_actions = []
                        for run in runs:
                            total_actions = run.get("total_actions", 0)
                            qllm_actions = run.get("qllm_actions", 0)
                            task_base_actions.append(total_actions)
                            task_qllm_actions.append(qllm_actions)

                        task_base_val = sum(task_base_actions) / len(task_base_actions) if task_base_actions else 0
                        task_qllm_val = sum(task_qllm_actions) / len(task_qllm_actions) if task_qllm_actions else 0
                        group_aggregated[task_group][masking_label]["base_actions"].append(task_base_val)
                        group_aggregated[task_group][masking_label]["qllm_actions"].append(task_qllm_val)
        
        # Collect success values
        group_success = defaultdict(lambda: defaultdict(list))
        if success_data:
            for ck in composite_keys:
                parts = ck.split("|", 1)
                trusted_setting = parts[0] if parts else ck
                system_prompt = parts[1] if len(parts) > 1 else None
                masking_label = _trusted_setting_label(trusted_setting, system_prompt)
                
                if ck in success_data:
                    for task, runs in success_data[ck].items():
                        task_group = task_groups.get(task) if task_groups else None
                        if not task_group or task_group == 'ungrouped':
                            continue
                        task_succ = []
                        for run in runs:
                            success_val = run.get("success", 0) if isinstance(run.get("success"), (int, float)) else (1.0 if run.get("success") else 0.0)
                            task_succ.append(float(success_val))
                        if task_succ:
                            # Utility: always mean success across runs per task; group bar = mean/median across tasks
                            group_success[task_group][masking_label].append(sum(task_succ) / len(task_succ))

        # Calculate averages/medians
        aggregated_by_group = {}
        group_order = sorted([g for g in group_aggregated.keys() if g != 'ungrouped'])
        expected_masking_labels = ["Undefended", "Masking Defense"]
        
        for group in group_order:
            for masking_label in expected_masking_labels:
                data = group_aggregated[group][masking_label]
                has_actions = len(data["base_actions"]) > 0 or len(data["qllm_actions"]) > 0
                has_success = len(group_success[group][masking_label]) > 0
                
                if has_actions or has_success:
                    key = f"{group}|{masking_label}"
                    base_value = sum(data["base_actions"]) / len(data["base_actions"]) if data["base_actions"] else 0
                    qllm_value = sum(data["qllm_actions"]) / len(data["qllm_actions"]) if data["qllm_actions"] else 0

                    sl = group_success[group][masking_label]
                    success_avg = sum(sl) / len(sl) if sl else 0

                    aggregated_by_group[key] = {
                        "avg_click": 0,
                        "avg_type": 0,
                        "avg_qllm": qllm_value,
                        "avg_base": base_value,
                        "avg_success": success_avg,
                        "group": group,
                        "masking_label": masking_label,
                    }
        
        # Create ordered list
        ordered_keys = []
        for group in group_order:
            for masking_label in expected_masking_labels:
                key = f"{group}|{masking_label}"
                if key in aggregated_by_group:
                    ordered_keys.append(key)
        
        aggregated = aggregated_by_group
        composite_keys = ordered_keys
        group_by_suite = True  # Use same plotting logic as suite grouping
        suite_order = group_order  # Reuse suite_order variable for group names
    # If grouping by suite, aggregate per suite and per masking setting
    elif group_by_suite:
        # Collect action values - either all raw values (for median) or task-level averages (for average)
        # Use nested defaultdict to handle any masking label dynamically
        suite_aggregated = defaultdict(lambda: defaultdict(lambda: {"base_actions": [], "qllm_actions": []}))
        
        # action_data is already filtered by model, so it's structured as {composite_key: {task: [runs]}}
        # We don't need to look up by model_name - action_data is already the model-specific data
        if action_data:
            for ck in composite_keys:
                parts = ck.split("|", 1)
                trusted_setting = parts[0] if parts else ck
                system_prompt = parts[1] if len(parts) > 1 else None
                masking_label = _trusted_setting_label(trusted_setting, system_prompt)
                
                # Get raw runs from action_data (already filtered by model)
                if ck in action_data:
                    for task, runs in action_data[ck].items():
                        # Filter by group if specified
                        if task_group_filter and task_groups:
                            task_group = task_groups.get(task)
                            if task_group != task_group_filter:
                                continue
                        
                        suite = task_suites.get(task) if task_suites else None
                        if not suite or suite == 'unspecified':
                            continue
                        
                        # Always aggregate per-task first, then collect one value per task.
                        task_base_actions = []
                        task_qllm_actions = []
                        for run in runs:
                            total_actions = run.get("total_actions", 0)
                            qllm_actions = run.get("qllm_actions", 0)
                            task_base_actions.append(total_actions)
                            task_qllm_actions.append(qllm_actions)

                        task_base_val = sum(task_base_actions) / len(task_base_actions) if task_base_actions else 0
                        task_qllm_val = sum(task_qllm_actions) / len(task_qllm_actions) if task_qllm_actions else 0
                        suite_aggregated[suite][masking_label]["base_actions"].append(task_base_val)
                        suite_aggregated[suite][masking_label]["qllm_actions"].append(task_qllm_val)
        
        # Collect success values from raw data for utility plot
        suite_success = defaultdict(lambda: defaultdict(list))
        # success_data is already filtered by model, so it's structured as {composite_key: {task: [runs]}}
        if success_data:
            for ck in composite_keys:
                parts = ck.split("|", 1)
                trusted_setting = parts[0] if parts else ck
                system_prompt = parts[1] if len(parts) > 1 else None
                masking_label = _trusted_setting_label(trusted_setting, system_prompt)
                
                if ck in success_data:
                    for task, runs in success_data[ck].items():
                        if task_group_filter and task_groups:
                            if task_groups.get(task) != task_group_filter:
                                continue
                        
                        suite = task_suites.get(task) if task_suites else None
                        if not suite or suite == 'unspecified':
                            continue
                        
                        # One value per task: always mean over runs; suite bar = mean (--) or median (default) across tasks.
                        task_succ = []
                        for run in runs:
                            success_val = run.get("success", 0) if isinstance(run.get("success"), (int, float)) else (1.0 if run.get("success") else 0.0)
                            task_succ.append(float(success_val))
                        if task_succ:
                            suite_success[suite][masking_label].append(sum(task_succ) / len(task_succ))
        else:
            # Fallback: use success_task_stats
            for ck in composite_keys:
                parts = ck.split("|", 1)
                trusted_setting = parts[0] if parts else ck
                system_prompt = parts[1] if len(parts) > 1 else None
                masking_label = _trusted_setting_label(trusted_setting, system_prompt)
                
                for task, stats in success_task_stats.get(ck, {}).items():
                    if task_group_filter and task_groups:
                        if task_groups.get(task) != task_group_filter:
                            continue
                    
                    suite = task_suites.get(task) if task_suites else None
                    if not suite or suite == 'unspecified':
                        continue
                    
                    # Use task-level average as a single value (fallback)
                    success_val = stats.get("avg_success", 0)
                    suite_success[suite][masking_label].append(success_val)
        
        # Calculate averages from combined lists
        aggregated_by_suite = {}
        suite_order = sorted(suites_present)
        
        # For suite grouping, only use the expected labels (plotting assumes exactly these two)
        expected_masking_labels = ["Undefended", "Masking Defense"]
        
        for suite in suite_order:
            for masking_label in expected_masking_labels:
                data = suite_aggregated[suite][masking_label]
                # Include suite if it has actions OR success data
                has_actions = len(data["base_actions"]) > 0 or len(data["qllm_actions"]) > 0
                has_success = len(suite_success[suite][masking_label]) > 0
                
                if has_actions or has_success:
                    key = f"{suite}|{masking_label}"
                    base_value = sum(data["base_actions"]) / len(data["base_actions"]) if data["base_actions"] else 0
                    qllm_value = sum(data["qllm_actions"]) / len(data["qllm_actions"]) if data["qllm_actions"] else 0
                    succ_list = suite_success[suite][masking_label]
                    success_avg = sum(succ_list) / len(succ_list) if succ_list else 0

                    aggregated_by_suite[key] = {
                        "avg_click": 0,  # Not used separately anymore
                        "avg_type": 0,  # Not used separately anymore
                        "avg_qllm": qllm_value,
                        "avg_base": base_value,  # Base actions (click + type + scroll + etc.)
                        "avg_success": success_avg,
                        "suite": suite,
                        "masking_label": masking_label,
                    }
        
        # Create ordered list: suite1 (labels...), suite2 (labels...), ...
        ordered_keys = []
        for suite in suite_order:
            for masking_label in expected_masking_labels:
                key = f"{suite}|{masking_label}"
                if key in aggregated_by_suite:
                    ordered_keys.append(key)
        
        aggregated = aggregated_by_suite
        composite_keys = ordered_keys
    else:
        # Original logic: aggregate across all tasks - collect ALL raw values from all runs
        # action_data and success_data are already filtered by model, structured as {composite_key: {task: [runs]}}
        aggregated = {}
        for ck in composite_keys:
            base_actions_all = []  # All base action values from all runs
            qllm_actions_all = []  # All qllm action values from all runs
            success_vals_all = []  # For utility plot only
            
            # Collect values from action_data (already filtered by model)
            if action_data and ck in action_data:
                for task, runs in action_data[ck].items():
                    # Filter by group if specified
                    if task_group_filter and task_groups:
                        if task_groups.get(task) != task_group_filter:
                            continue
                    
                    # Always aggregate per-task first, then collect one value per task.
                    task_base_actions = []
                    task_qllm_actions = []
                    for run in runs:
                        total_actions = run.get("total_actions", 0)
                        qllm_actions = run.get("qllm_actions", 0)
                        task_base_actions.append(total_actions)
                        task_qllm_actions.append(qllm_actions)

                    task_base_val = sum(task_base_actions) / len(task_base_actions) if task_base_actions else 0
                    task_qllm_val = sum(task_qllm_actions) / len(task_qllm_actions) if task_qllm_actions else 0
                    base_actions_all.append(task_base_val)
                    qllm_actions_all.append(task_qllm_val)
            
            # Success rate (for utility plot): one value per task (mean/median over runs), then like actions
            if success_data and ck in success_data:
                for task, runs in success_data[ck].items():
                    if task_group_filter and task_groups:
                        if task_groups.get(task) != task_group_filter:
                            continue
                    task_succ = []
                    for run in runs:
                        success_val = run.get("success", 0) if isinstance(run.get("success"), (int, float)) else (1.0 if run.get("success") else 0.0)
                        task_succ.append(float(success_val))
                    if task_succ:
                        success_vals_all.append(sum(task_succ) / len(task_succ))

            base_value = sum(base_actions_all) / len(base_actions_all) if base_actions_all else 0
            qllm_value = sum(qllm_actions_all) / len(qllm_actions_all) if qllm_actions_all else 0
            success_avg = sum(success_vals_all) / len(success_vals_all) if success_vals_all else 0

            aggregated[ck] = {
                "avg_click": 0,  # Not used separately
                "avg_type": 0,  # Not used separately
                "avg_qllm": qllm_value,
                "avg_base": base_value,  # Base actions (click + type + scroll + etc.)
                "avg_unsafe": 0,  # Not used
                "avg_success": success_avg,
            }
    
    # Calculate bar positions
    if group_by_suite:
        # Grouped bars: 2 bars per suite (undefended first, then masking defense)
        num_suites = len(suite_order)
        x = np.arange(num_suites)
        bar_width = 0.35  # Width of each bar within a group
        x_undefended = x - bar_width / 2  # Undefended on the left
        x_masking = x + bar_width / 2     # Masking defense on the right
    else:
        x = np.arange(len(composite_keys))
        bar_width = 0.6
    
    # Extract labels and assign colors based on them
    labels = []
    colors = []
    color_map = {
        "Undefended": "#DC3545",  # Red
        "Masking Defense": "#007BFF",      # Blue
    }
    default_color = "#1f77b4"  # Blue fallback
    
    if group_by_suite:
        # Labels will be suite names or group names, with two bars per suite/group
        if group_by_task_group:
            # For task groups, show "Group I", "Group II", etc.
            def to_roman(s):
                if s.startswith('1'):
                    return 'I'
                elif s.startswith('2'):
                    return 'II'
                else:
                    return s[0]
            suite_labels = [f"Group {to_roman(s)}" if s.startswith(('1', '2')) else s.replace('_', ' ').title() for s in suite_order]
        else:
            suite_labels = [s.replace('_', ' ').title() for s in suite_order]
    else:
        for ck in composite_keys:
            parts = ck.split("|", 1)
            trusted_setting = parts[0] if parts else ck
            system_prompt = parts[1] if len(parts) > 1 else None
            label = _trusted_setting_label(trusted_setting, system_prompt)
            labels.append(label)
            # Assign color based on label
            colors.append(color_map.get(label, default_color))
    
    # Graph 1: Utility (Success rate)
    fig1, ax1 = plt.subplots(1, 1, figsize=(8, 6))
    
    if group_by_suite:
        masking_success = []
        undefended_success = []
        
        for suite in suite_order:
            masking_key = f"{suite}|Masking Defense"
            undefended_key = f"{suite}|Undefended"
            
            masking_success.append(aggregated.get(masking_key, {}).get("avg_success", 0))
            undefended_success.append(aggregated.get(undefended_key, {}).get("avg_success", 0))
        
        # Plot undefended first (left), then masking defense (right)
        ax1.bar(x_undefended, undefended_success, bar_width, color=color_map["Undefended"], alpha=0.85, label="Undefended")
        ax1.bar(x_masking, masking_success, bar_width, color=color_map["Masking Defense"], alpha=0.85, label="Masking Defense")
        
        ax1.set_xticks(x)
        # Show labels if grouping by task group OR if there are multiple suites
        if group_by_task_group or len(suite_order) > 1:
            ax1.set_xticklabels(suite_labels, rotation=25, ha="right", fontsize=14)
        else:
            ax1.tick_params(labelbottom=False)  # Hide tick labels when only one suite
    else:
        success = [aggregated[ck]["avg_success"] for ck in composite_keys]
        ax1.bar(x, success, bar_width, color=colors, alpha=0.85)
        ax1.set_xticks(x)
        # Hide x-axis labels as they're redundant with legend
        ax1.tick_params(labelbottom=False)
    
    ax1.set_ylabel("Utility", fontsize=16, fontweight='bold')
    ax1.tick_params(axis='y', labelsize=14)
    ax1.set_ylim([0, 1.0])
    ax1.grid(axis="y", alpha=0.25)
    
    # Create legend for utility graph
    if group_by_suite:
        undefended_patch = mpatches.Patch(color=color_map["Undefended"], alpha=0.85, label="Undefended")
        masking_patch = mpatches.Patch(color=color_map["Masking Defense"], alpha=0.85, label="Masking Defense")
        fig1.legend(handles=[undefended_patch, masking_patch], loc='upper center', 
                   bbox_to_anchor=(0.5, 1.01), ncol=2, framealpha=0.9, fontsize=14)
    else:
        unique_labels = list(set(labels))
        handles = []
        for label in unique_labels:
            color = color_map.get(label, default_color)
            handles.append(mpatches.Patch(color=color, alpha=0.85, label=label))
        if handles:
            fig1.legend(handles=handles, loc='upper center', 
                       bbox_to_anchor=(0.5, 1.01), ncol=len(handles), framealpha=0.9, fontsize=14)
    
    # File suffix based on group
    if group_by_task_group:
        group_suffix = "_by_group"
    else:
        group_suffix = f"_{task_group_filter}" if task_group_filter else "_all"
    plt.tight_layout(rect=[0, 0, 1, 0.92])  # Leave space at top for legend
    plt.subplots_adjust(top=0.90)  # Top margin
    output_file = output_dir / f"aggregated_utility{group_suffix}_{model_name}.png"
    plt.savefig(output_file, dpi=300, bbox_inches="tight")
    print(f"Saved: {output_file}")
    output_file_pdf = output_dir / f"aggregated_utility{group_suffix}_{model_name}.pdf"
    plt.savefig(output_file_pdf, bbox_inches="tight")
    print(f"Saved: {output_file_pdf}")
    plt.close(fig1)
    
MODEL_COLORS = ["#DC3545", "#007BFF", "#28A745", "#FF8C00", "#6F42C1", "#20C997"]

# --all-models subplot order and titles: (results folder name substring, title above each panel).
# Only models whose directory name contains the substring (case-insensitive) are included; others omitted.
ALL_MODELS_PANELS: list[tuple[str, str]] = [
    ("claude-sonnet-4-5", "Claude Sonnet 4.5"),
    ("claude-sonnet-4-6", "Claude Sonnet 4.6"),
    ("gpt-5.4", "GPT-5.4"),
]


def _humanize_model_dir(name: str) -> str:
    """Fallback subplot title from results folder name."""
    n = name.strip()
    if n.lower().startswith("gpt"):
        return n.upper().replace("_", "-")
    return n.replace("_", " ").replace("-", " ").title()


def _title_for_include_fragment(frag: str, matched_model: str) -> str:
    fl = frag.lower()
    for f, t in ALL_MODELS_PANELS:
        if fl == f.lower() or fl in f.lower() or f.lower() in fl:
            return t
    return _humanize_model_dir(matched_model)


def build_all_models_panels(
    discovered: set[str],
    include_fragments: list[str] | None,
) -> list[tuple[str, str]]:
    """
    Build ordered [(model_dir_key, subplot_title), ...] for multi-model figures.
    include_fragments: from --all-models-include; if None, use ALL_MODELS_PANELS.
    If ALL_MODELS_PANELS matches fewer than two models, fall back to all discovered (sorted) with humanized titles.
    """
    if not discovered:
        return []

    used: set[str] = set()

    def take_match(fragment: str) -> str | None:
        fl = fragment.lower()
        for m in sorted(discovered):
            if m in used:
                continue
            if fl in m.lower():
                return m
        return None

    if include_fragments:
        out: list[tuple[str, str]] = []
        for frag in include_fragments:
            m = take_match(frag)
            if not m:
                print(f"  ⚠ --all-models-include: no model matched fragment {frag!r}")
                continue
            used.add(m)
            out.append((m, _title_for_include_fragment(frag, m)))
        return out

    if ALL_MODELS_PANELS:
        out = []
        for frag, title in ALL_MODELS_PANELS:
            m = take_match(frag)
            if m:
                used.add(m)
                out.append((m, title))
        if len(out) >= 2:
            return out
        if len(out) == 1:
            print(
                "  ⚠ ALL_MODELS_PANELS matched only one model; need 2+ for --all-models. "
                f"Matched: {out[0][0]!r}. Falling back to all models in results."
            )

    return [(m, _humanize_model_dir(m)) for m in sorted(discovered)]


def _collect_suites_all_models(
    model_names: list[str],
    task_suites: dict,
    task_groups: dict,
    task_group_filter: str | None,
) -> list[str]:
    suites: set[str] = set()
    for model in model_names:
        ts = task_suites.get(model, {}) or {}
        m_tg = task_groups.get(model, {}) or {}
        for task, suite in ts.items():
            if task_group_filter and m_tg.get(task) != task_group_filter:
                continue
            if suite and suite != "unspecified":
                suites.add(suite)
    return sorted(suites)


def _collect_suites_union_all_tasks(model_names: list[str], task_suites: dict) -> list[str]:
    """All suite labels appearing on any task (matches legacy all-models x-axis)."""
    suites: set[str] = set()
    for model in model_names:
        for suite in (task_suites.get(model, {}) or {}).values():
            if suite and suite != "unspecified":
                suites.add(suite)
    return sorted(suites)


def _aggregate_all_models_for_filter(
    action_data: dict,
    success_data: dict,
    task_groups: dict,
    task_suites: dict,
    model_names: list[str],
    task_group_filter: str | None,
    use_average: bool,
):
    agg = defaultdict(lambda: defaultdict(lambda: defaultdict(
        lambda: {"base_actions": [], "qllm_actions": [], "success": []})))

    for model in model_names:
        model_action = action_data.get(model, {})
        model_success = success_data.get(model, {})
        model_tg = task_groups.get(model, {})
        model_ts = task_suites.get(model, {})

        for ck, tasks in model_action.items():
            parts = ck.split("|", 1)
            trusted_setting = parts[0] if parts else ck
            system_prompt = parts[1] if len(parts) > 1 else None
            defense = _trusted_setting_label(trusted_setting, system_prompt)

            for task, runs in tasks.items():
                if task_group_filter and model_tg.get(task) != task_group_filter:
                    continue
                suite = model_ts.get(task)
                if not suite or suite == "unspecified":
                    continue

                vals_base, vals_qllm = [], []
                for r in runs:
                    vals_base.append(r.get("total_actions", 0))
                    vals_qllm.append(r.get("qllm_actions", 0))

                tb = sum(vals_base) / len(vals_base) if vals_base else 0
                tq = sum(vals_qllm) / len(vals_qllm) if vals_qllm else 0
                agg[model][suite][defense]["base_actions"].append(tb)
                agg[model][suite][defense]["qllm_actions"].append(tq)

        for ck, tasks in model_success.items():
            parts = ck.split("|", 1)
            trusted_setting = parts[0] if parts else ck
            system_prompt = parts[1] if len(parts) > 1 else None
            defense = _trusted_setting_label(trusted_setting, system_prompt)

            for task, runs in tasks.items():
                if task_group_filter and model_tg.get(task) != task_group_filter:
                    continue
                suite = model_ts.get(task)
                if not suite or suite == "unspecified":
                    continue
                run_succ = []
                for r in runs:
                    sv = r.get("success", 0)
                    if not isinstance(sv, (int, float)):
                        sv = 1.0 if sv else 0.0
                    run_succ.append(float(sv))
                if run_succ:
                    agg[model][suite][defense]["success"].append(sum(run_succ) / len(run_succ))

    return agg


def _pool_per_task_mean_success_by_defense(
    success_data: dict,
    task_groups: dict,
    task_suites: dict,
    model_names: list[str],
    task_group_filter: str,
):
    """
    Merge all suites: per model and defense, list of per-task mean success (mean over runs), 0–1.
    """
    out = defaultdict(lambda: defaultdict(list))
    for model in model_names:
        model_success = success_data.get(model, {})
        model_tg = task_groups.get(model, {})
        model_ts = task_suites.get(model, {})
        for ck, tasks in model_success.items():
            parts = ck.split("|", 1)
            trusted_setting = parts[0] if parts else ck
            system_prompt = parts[1] if len(parts) > 1 else None
            defense = _trusted_setting_label(trusted_setting, system_prompt)

            for task, runs in tasks.items():
                if model_tg.get(task) != task_group_filter:
                    continue
                suite = model_ts.get(task)
                if not suite or suite == "unspecified":
                    continue
                run_succ = []
                for r in runs:
                    sv = r.get("success", 0)
                    if not isinstance(sv, (int, float)):
                        sv = 1.0 if sv else 0.0
                    run_succ.append(float(sv))
                if run_succ:
                    out[model][defense].append(sum(run_succ) / len(run_succ))
    return out


def _mean_sem_median(vals: list[float]) -> tuple[float, float, float, int]:
    """Return (mean, sem across tasks, median, n). sem uses ddof=1, 0 if n<2."""
    if not vals:
        return 0.0, 0.0, 0.0, 0
    n = len(vals)
    arr = np.asarray(vals, dtype=float)
    mu = float(np.mean(arr))
    med = float(np.median(arr))
    sem = float(np.std(arr, ddof=1) / np.sqrt(n)) if n > 1 else 0.0
    return mu, sem, med, n


def plot_aggregated_utility_combined_groups_all_models(
    success_data: dict,
    task_groups: dict,
    task_suites: dict,
    output_dir: Path,
    model_panels: list[tuple[str, str]] | None = None,
):
    """Utility version of plot_total_cost_combined_groups_all_models (Fig 2a).

    Per model, draws 4 bars: Undefended×{simple, harder} and Defended×{simple, harder}.
    Color (red/blue) encodes defense; hatch (solid vs '///') encodes task group.
    Bar height = mean per-task success; error bars = SEM across tasks.
    """
    import csv

    discovered = set(success_data.keys())
    if model_panels is None:
        model_panels = [(m, _humanize_model_dir(m)) for m in sorted(discovered)]
    model_panels = [(k, t) for k, t in model_panels if k in discovered]
    if not model_panels:
        return
    model_names = [k for k, _ in model_panels]
    panel_title = dict(model_panels)

    GROUPS = ("1_simple", "2_harder")
    DEFENSES = ("Undefended", "Masking Defense")
    undef_color = "#DC3545"
    def_color = "#007BFF"

    vals: dict[tuple[str, str, str], list[float]] = {}
    for group in GROUPS:
        per_group = _pool_per_task_mean_success_by_defense(
            success_data, task_groups, task_suites, model_names, group,
        )
        for m in model_names:
            for d in DEFENSES:
                vals[(m, d, group)] = list(per_group.get(m, {}).get(d, []))

    labels: list[str] = [panel_title.get(m, m) for m in model_names]

    n = len(model_names)
    bar_w = 0.18
    gap_within_pair = 0.02
    gap_between_pairs = 0.05
    pair_stride = 2 * bar_w + gap_within_pair
    pair_center_simple = -(pair_stride + gap_between_pairs) / 2
    pair_center_harder = (pair_stride + gap_between_pairs) / 2
    inner_offsets = [
        pair_center_simple - (bar_w + gap_within_pair) / 2,
        pair_center_simple + (bar_w + gap_within_pair) / 2,
        pair_center_harder - (bar_w + gap_within_pair) / 2,
        pair_center_harder + (bar_w + gap_within_pair) / 2,
    ]
    sub_specs = [
        ("Undefended",      "1_simple", undef_color, None),
        ("Masking Defense", "1_simple", def_color,   None),
        ("Undefended",      "2_harder", undef_color, "///"),
        ("Masking Defense", "2_harder", def_color,   "///"),
    ]

    undef_hatch = "#7B1F2A"
    def_hatch = "#003F7F"
    hatch_edge_color = {undef_color: undef_hatch, def_color: def_hatch}

    fig_w = max(7.6, 1.9 * n + 1.9)
    fig, ax = plt.subplots(figsize=(fig_w, 5.4))
    x = np.arange(n)

    csv_rows: list[list] = []
    for off, (defense, group, color, hatch) in zip(inner_offsets, sub_specs):
        heights = []
        yerr = []
        for mi, m in enumerate(model_names):
            mu, sem, med, n_tasks = _mean_sem_median(vals[(m, defense, group)])
            heights.append(mu)
            yerr.append(sem)
            csv_rows.append([
                m, panel_title.get(m, m), defense, group,
                f"{mu:.6f}", f"{sem:.6f}", f"{med:.6f}", n_tasks,
            ])
        if hatch:
            edge = hatch_edge_color[color]
            lw = 0.6
        else:
            edge = "white"
            lw = 0.5
        ax.bar(
            x + off, heights, bar_w,
            yerr=yerr,
            color=color, edgecolor=edge, linewidth=lw,
            hatch=hatch, alpha=0.95,
            capsize=3, error_kw={"elinewidth": 1.1, "ecolor": "#222222"},
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=13)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("Utility", fontsize=13, fontweight="bold")
    ax.tick_params(axis="y", labelsize=10)
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{int(y * 100)}%"))
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)

    legend_handles = [
        mpatches.Patch(facecolor=undef_color, edgecolor="white", linewidth=0.5,
                       label="Undefended"),
        mpatches.Patch(facecolor=def_color, edgecolor="white", linewidth=0.5,
                       label="Masking Defense"),
        mpatches.Patch(facecolor="lightgray", edgecolor="black", linewidth=0.8,
                       label="Untrusted content not required"),
        mpatches.Patch(facecolor="lightgray", edgecolor="#222222", linewidth=0.8,
                       hatch="///", label="Untrusted content required"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="upper center", bbox_to_anchor=(0.5, 1.02),
        ncol=2, framealpha=0.92, fontsize=11,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.92))

    csv_path = output_dir / "utility_combined_groups.csv"
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "model_dir", "model_title", "defense", "task_group",
            "mean_per_task_success", "sem_across_tasks",
            "median_per_task_success", "n_tasks",
        ])
        w.writerows(csv_rows)
    print(f"  Wrote combined-groups utility table: {csv_path.resolve()}")

    stem = "aggregated_utility_combined_groups_all_models"
    fig.savefig(output_dir / f"{stem}.png", dpi=300, bbox_inches="tight", pad_inches=0.2)
    fig.savefig(output_dir / f"{stem}.pdf", bbox_inches="tight", pad_inches=0.2)
    plt.close(fig)
    print(f"  Saved {stem}.png/pdf  (models: {labels})")


def _draw_all_models_utility_axis(
    ax,
    model: str,
    agg,
    suite_order: list[str],
    use_average: bool,
    panel_title: dict[str, str],
    show_ylabel: bool,
    show_xticklabels: bool = True,
    x_tick_pad: float = 6.0,
    title_fontsize: int = 12,
    title_pad: float = 6.0,
):
    bar_width = 0.36
    gap_within_suite = 0.08
    gap_between_suites = 0.85
    defense_order = ["Undefended", "Masking Defense"]
    defense_color = {"Undefended": "#DC3545", "Masking Defense": "#007BFF"}

    def _val(m, suite, defense, metric):
        vals = agg[m][suite][defense][metric]
        return sum(vals) / len(vals) if vals else 0.0

    group_stride = (
        len(defense_order) * bar_width
        + (len(defense_order) - 1) * gap_within_suite
        + gap_between_suites
    )
    suite_tick_x = []
    for si in range(len(suite_order)):
        x0 = si * group_stride
        suite_tick_x.append(x0 + bar_width + gap_within_suite / 2)

    for si, suite in enumerate(suite_order):
        x0 = si * group_stride
        for di, defense in enumerate(defense_order):
            xpos = x0 + di * (bar_width + gap_within_suite)
            val = _val(model, suite, defense, "success")
            c = defense_color[defense]
            ax.bar(
                xpos,
                val,
                bar_width,
                color=c,
                alpha=0.88,
                edgecolor="white",
                linewidth=0.5,
            )
    ax.set_xticks(suite_tick_x)
    if show_xticklabels:
        ax.set_xticklabels(
            [s.replace("_", " ").title() for s in suite_order],
            rotation=30,
            ha="right",
            fontsize=10,
        )
        ax.tick_params(axis="x", pad=x_tick_pad)
    else:
        ax.tick_params(axis="x", labelbottom=False)
    ax.set_ylim([0, 1.0])
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(axis="y", labelsize=11)
    ax.set_title(
        panel_title.get(model, model),
        fontsize=title_fontsize,
        fontweight="bold",
        pad=title_pad,
    )
    if show_ylabel:
        ax.set_ylabel("Utility", fontsize=14, fontweight="bold")



def plot_aggregated_summary_all_models(
    action_data: dict,
    success_data: dict,
    task_groups: dict,
    task_suites: dict,
    output_dir: Path,
    use_average: bool = False,
    task_group_filter: str = None,
    model_panels: list[tuple[str, str]] | None = None,
):
    """
    Multi-model comparison: one subplot per model (horizontal row).

    X-axis: suites. Within each suite: Undefended vs Masking Defense (red / blue).
    Shared figure legend; each panel titled with display name from model_panels.

    Produces two figures: Utility (success rate) and Number of Actions (stacked Q-Model).
    """
    discovered = set(action_data.keys()) | set(success_data.keys())
    if model_panels is None:
        model_panels = [(m, _humanize_model_dir(m)) for m in sorted(discovered)]
    model_panels = [(k, t) for k, t in model_panels if k in discovered]
    if len(model_panels) < 2:
        return
    model_names = [k for k, _ in model_panels]
    panel_title = dict(model_panels)

    suite_order = _collect_suites_union_all_tasks(model_names, task_suites)
    if not suite_order:
        return

    agg = _aggregate_all_models_for_filter(
        action_data, success_data, task_groups, task_suites,
        model_names, task_group_filter, use_average,
    )

    n_models = len(model_names)
    bar_width = 0.36
    gap_within_suite = 0.08
    gap_between_suites = 0.85
    defense_order = ["Undefended", "Masking Defense"]
    defense_color = {"Undefended": "#DC3545", "Masking Defense": "#007BFF"}
    qllm_stack_color = "#0B3D91"

    # ── Helper: get aggregated scalar (mean across tasks) ──────────
    def _val(model, suite, defense, metric):
        vals = agg[model][suite][defense][metric]
        return sum(vals) / len(vals) if vals else 0.0

    def _suite_x_positions():
        """Left edge of each suite group and x-position for suite tick label (between the two bars)."""
        group_stride = (
            len(defense_order) * bar_width
            + (len(defense_order) - 1) * gap_within_suite
            + gap_between_suites
        )
        lefts = []
        centers = []
        for si in range(len(suite_order)):
            x0 = si * group_stride
            lefts.append(x0)
            centers.append(x0 + bar_width + gap_within_suite / 2)
        return lefts, centers

    suite_lefts, suite_tick_x = _suite_x_positions()

    def _draw_actions_panel(ax, model: str, show_ylabel: bool):
        for si, suite in enumerate(suite_order):
            x0 = suite_lefts[si]
            for di, defense in enumerate(defense_order):
                xpos = x0 + di * (bar_width + gap_within_suite)
                total = _val(model, suite, defense, "base_actions")
                qllm = _val(model, suite, defense, "qllm_actions")
                agent_only = max(0, total - qllm)
                c = defense_color[defense]
                hatch = "///" if defense == "Masking Defense" else ""
                ax.bar(
                    xpos,
                    agent_only,
                    bar_width,
                    color=c,
                    alpha=0.88,
                    hatch=hatch,
                    edgecolor="white" if not hatch else c,
                    linewidth=0.5,
                )
                if qllm > 0:
                    ax.bar(
                        xpos,
                        qllm,
                        bar_width,
                        bottom=agent_only,
                        color=qllm_stack_color,
                        alpha=0.92,
                        hatch="ooo" + hatch,
                        edgecolor=qllm_stack_color,
                        linewidth=0.5,
                    )
        ax.set_xticks(suite_tick_x)
        ax.set_xticklabels(
            [s.replace("_", " ").title() for s in suite_order],
            rotation=22,
            ha="right",
            fontsize=11,
        )
        ax.set_ylim([0, 40])
        ax.grid(axis="y", alpha=0.25)
        ax.tick_params(axis="y", labelsize=11)
        ax.set_title(panel_title.get(model, model), fontsize=12, fontweight="bold", pad=8)
        if show_ylabel:
            ax.set_ylabel("Number of Actions", fontsize=14, fontweight="bold")

    suffix = f"_{task_group_filter}" if task_group_filter else "_all"
    panel_w = max(3.4, min(5.2, 1.15 * len(suite_order) + 1.5))

    # ── Figure 1: Utility — one subplot per model ─────────────────
    fig1, axes1 = plt.subplots(1, n_models, figsize=(panel_w * n_models, 5.8), sharey=True)
    if n_models == 1:
        axes1 = np.array([axes1])
    for mi, model in enumerate(model_names):
        _draw_all_models_utility_axis(
            axes1[mi],
            model,
            agg,
            suite_order,
            use_average,
            panel_title,
            show_ylabel=(mi == 0),
            show_xticklabels=True,
        )

    handles_leg = [
        mpatches.Patch(facecolor=defense_color["Undefended"], alpha=0.88, edgecolor="white", linewidth=0.5, label="Undefended"),
        mpatches.Patch(
            facecolor=defense_color["Masking Defense"],
            alpha=0.88,
            edgecolor="white",
            linewidth=0.5,
            label="Masking Defense",
        ),
    ]
    fig1.legend(
        handles=handles_leg,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=2,
        framealpha=0.95,
        fontsize=11,
        handlelength=1.6,
        columnspacing=1.4,
    )
    fig1.tight_layout(rect=[0, 0, 1, 0.93])
    fig1.subplots_adjust(top=0.88, wspace=0.22)
    for ext in ("png", "pdf"):
        out = output_dir / f"aggregated_utility_all_models{suffix}.{ext}"
        fig1.savefig(out, dpi=300 if ext == "png" else None, bbox_inches="tight")
        print(f"Saved: {out}")
    plt.close(fig1)

    # ── Figure 2: Actions — one subplot per model ─────────────────
    fig2, axes2 = plt.subplots(1, n_models, figsize=(panel_w * n_models, 5.8), sharey=True)
    if n_models == 1:
        axes2 = np.array([axes2])
    for mi, model in enumerate(model_names):
        _draw_actions_panel(axes2[mi], model, show_ylabel=(mi == 0))

    handles2 = [
        mpatches.Patch(facecolor=defense_color["Undefended"], alpha=0.88, edgecolor="white", linewidth=0.5, label="Undefended"),
        mpatches.Patch(
            facecolor=defense_color["Masking Defense"],
            alpha=0.88,
            hatch="///",
            edgecolor=defense_color["Masking Defense"],
            linewidth=0.5,
            label="Masking Defense",
        ),
        mpatches.Patch(
            facecolor=qllm_stack_color,
            alpha=0.92,
            hatch="ooo",
            edgecolor=qllm_stack_color,
            linewidth=0.5,
            label="Q-Model (stacked)",
        ),
    ]
    fig2.legend(
        handles=handles2,
        loc="upper center",
        bbox_to_anchor=(0.5, 1.02),
        ncol=3,
        framealpha=0.95,
        fontsize=11,
        handlelength=1.6,
        columnspacing=1.2,
    )
    fig2.tight_layout(rect=[0, 0, 1, 0.93])
    fig2.subplots_adjust(top=0.88, wspace=0.22)
    for ext in ("png", "pdf"):
        out = output_dir / f"aggregated_actions_all_models{suffix}.{ext}"
        fig2.savefig(out, dpi=300 if ext == "png" else None, bbox_inches="tight")
        print(f"Saved: {out}")
    plt.close(fig2)


def main():
    import argparse
    parser = argparse.ArgumentParser(
        prog="plot_custom_websites.py",
        description=(
            "Plot utility, action, cost and token-usage charts for the 10 "
            "custom-website suites. Reads a results directory and writes PNG/PDF "
            "plots to analysis_output/<results_dir_name>/<model>/ (per model) "
            "and analysis_output/<results_dir_name>/all_models/ (cross-model)."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "results_dir", type=Path,
        help="Path to a results tree (e.g. renamed_new_results_custom_all/).",
    )
    parser.add_argument(
        "--suites", nargs="+", default=None,
        help="Filter to these suites (e.g. banking forum). Default: all suites.",
    )
    parser.add_argument(
        "--models", nargs="+", default=None,
        help="Filter to these model directory fragments. Default: all models.",
    )
    parser.add_argument(
        "--all-models", action="store_true",
        help="Force cross-model comparison plots under all_models/ (auto-enabled when 2+ models are present).",
    )
    parser.add_argument(
        "--all-models-include", default=None,
        metavar="FRAG1,FRAG2,...",
        help="Comma-separated model directory fragments to include in the "
             "cross-model panels (default: every discovered model).",
    )
    parser.add_argument(
        "--count-subactions", action="store_true",
        help="Count every sub-action line as a separate action (default: count "
             "unique steps, treating one step with multiple sub-actions = 1).",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Also produce the breakdown/ subfolder and per-model plots. "
             "Default: only the two main paper figures (Fig 2a + Fig 2b + CSV).",
    )
    args = parser.parse_args()

    results_dir: Path = args.results_dir
    allowed_suites = args.suites
    allowed_models = args.models
    all_models_mode = args.all_models
    all_models_include = (
        [x.strip() for x in args.all_models_include.split(",") if x.strip()]
        if args.all_models_include else None
    )
    count_subactions = args.count_subactions
    verbose = args.verbose
    use_average = False  # legacy flag, no longer exposed

    if allowed_suites:
        print(f"Filtering by suites: {allowed_suites}")
    if allowed_models:
        print(f"Filtering by models: {allowed_models}")
    print(f"Action counting: {'all sub-actions' if count_subactions else 'unique steps (default)'}")

    if not results_dir.exists():
        print(f"Error: {results_dir} does not exist!")
        return
    
    print(f"Loading security logs from {results_dir}...")
    security_data = load_security_logs(results_dir, allowed_suites=allowed_suites, allowed_models=allowed_models)
    action_data = load_action_counts(results_dir, allowed_suites=allowed_suites, allowed_models=allowed_models,
                                     count_subactions=count_subactions)
    success_data = load_success_rates(results_dir, allowed_suites=allowed_suites, allowed_models=allowed_models)
    token_data = load_token_usage(results_dir, allowed_suites=allowed_suites, allowed_models=allowed_models)

    print("Calculating averages...")
    task_averages, _trusted_setting_avgs, task_groups, task_suites = calculate_averages(security_data)

    # Extract task_groups and task_suites from action_data and success_data as well (merge with existing)
    for model, trusted_settings in action_data.items():
        if model not in task_groups:
            task_groups[model] = {}
        if model not in task_suites:
            task_suites[model] = {}
        for trusted_setting, tasks in trusted_settings.items():
            for task, runs in tasks.items():
                if not runs:
                    continue
                # Get group and suite from first run (all runs for a task should have same group/suite)
                if task not in task_groups[model] and runs:
                    task_groups[model][task] = runs[0].get('task_group') or 'ungrouped'
                if task not in task_suites[model] and runs:
                    task_suites[model][task] = runs[0].get('task_suite') or 'unspecified'

    for model, trusted_settings in success_data.items():
        if model not in task_groups:
            task_groups[model] = {}
        if model not in task_suites:
            task_suites[model] = {}
        for trusted_setting, tasks in trusted_settings.items():
            for task, runs in tasks.items():
                if not runs:
                    continue
                # Get group and suite from first run (all runs for a task should have same group/suite)
                if task not in task_groups[model] and runs:
                    task_groups[model][task] = runs[0].get('task_group') or 'ungrouped'
                if task not in task_suites[model] and runs:
                    task_suites[model][task] = runs[0].get('task_suite') or 'unspecified'

    # Calculate total-actions stats (avg/min/max) per model/trusted_setting/task
    action_task_averages = defaultdict(lambda: defaultdict(dict))
    click_qllm_task_averages = defaultdict(lambda: defaultdict(dict))
    for model, trusted_settings in action_data.items():
        for trusted_setting, tasks in trusted_settings.items():
            for task, runs in tasks.items():
                if not runs:
                    continue
                vals = [r.get("total_actions", 0) for r in runs]
                system_prompt = runs[0].get("system_prompt") if runs else None
                action_task_averages[model][trusted_setting][task] = {
                    "system_prompt": system_prompt,
                    "avg_total_actions": sum(vals) / len(vals) if vals else 0,
                    "min_total_actions": min(vals) if vals else 0,
                    "max_total_actions": max(vals) if vals else 0,
                    "num_runs": len(vals),
                }

                cq_vals = [r.get("click_and_qllm_actions", 0) for r in runs]
                qllm_vals = [r.get("qllm_actions", 0) for r in runs]
                click_qllm_task_averages[model][trusted_setting][task] = {
                    "avg_click_and_qllm_actions": sum(cq_vals) / len(cq_vals) if cq_vals else 0,
                    "min_click_and_qllm_actions": min(cq_vals) if cq_vals else 0,
                    "max_click_and_qllm_actions": max(cq_vals) if cq_vals else 0,
                    "avg_qllm_actions": sum(qllm_vals) / len(qllm_vals) if qllm_vals else 0,
                    "num_runs": len(cq_vals),
                }

    # Calculate action-type breakdown stats (avg/min/max) per model/trusted_setting/task
    action_type_task_averages = defaultdict(lambda: defaultdict(dict))
    for model, trusted_settings in action_data.items():
        for trusted_setting, tasks in trusted_settings.items():
            for task, runs in tasks.items():
                if not runs:
                    continue
                click_vals = [r.get("click_actions", 0) for r in runs]
                type_vals = [r.get("type_actions", 0) for r in runs]
                qllm_vals = [r.get("qllm_actions", 0) for r in runs]
                system_prompt = runs[0].get("system_prompt") if runs else None
                action_type_task_averages[model][trusted_setting][task] = {
                    "system_prompt": system_prompt,
                    "avg_click_actions": sum(click_vals) / len(click_vals) if click_vals else 0,
                    "min_click_actions": min(click_vals) if click_vals else 0,
                    "max_click_actions": max(click_vals) if click_vals else 0,
                    "avg_type_actions": sum(type_vals) / len(type_vals) if type_vals else 0,
                    "min_type_actions": min(type_vals) if type_vals else 0,
                    "max_type_actions": max(type_vals) if type_vals else 0,
                    "avg_qllm_actions": sum(qllm_vals) / len(qllm_vals) if qllm_vals else 0,
                    "min_qllm_actions": min(qllm_vals) if qllm_vals else 0,
                    "max_qllm_actions": max(qllm_vals) if qllm_vals else 0,
                    "num_runs": len(click_vals),
                }

    # Calculate success-rate stats (avg/min/max) per model/trusted_setting/task
    success_task_averages = defaultdict(lambda: defaultdict(dict))
    for model, trusted_settings in success_data.items():
        for trusted_setting, tasks in trusted_settings.items():
            for task, runs in tasks.items():
                if not runs:
                    continue
                vals = [r.get("success", 0) for r in runs]  # 0/1
                success_task_averages[model][trusted_setting][task] = {
                    "avg_success": sum(vals) / len(vals) if vals else 0,
                    "min_success": min(vals) if vals else 0,
                    "max_success": max(vals) if vals else 0,
                    "num_runs": len(vals),
                }

    # Calculate ratios: safe/total and unsafe/total per run, then avg/min/max per model/trusted_setting/task
    ratio_task_averages = defaultdict(lambda: defaultdict(dict))
    for model, trusted_settings in security_data.items():
        for trusted_setting, tasks in trusted_settings.items():
            for task, sec_runs in tasks.items():
                # Map run_dir -> security counts
                sec_by_dir = {r.get("run_dir"): r for r in sec_runs if r.get("run_dir")}
                act_runs = action_data.get(model, {}).get(trusted_setting, {}).get(task, [])
                act_by_dir = {r.get("run_dir"): r for r in act_runs if r.get("run_dir")}

                common_dirs = sorted(set(sec_by_dir.keys()) & set(act_by_dir.keys()))
                if not common_dirs:
                    continue

                safe_ratios = []
                unsafe_ratios = []
                for d in common_dirs:
                    safe = float(sec_by_dir[d].get("safe", 0) or 0)
                    unsafe = float(sec_by_dir[d].get("unsafe", 0) or 0)
                    total = float(act_by_dir[d].get("total_actions", 0) or 0)
                    if total <= 0:
                        continue
                    safe_ratios.append(safe / total)
                    unsafe_ratios.append(unsafe / total)

                if not safe_ratios or not unsafe_ratios:
                    continue

                ratio_task_averages[model][trusted_setting][task] = {
                    "avg_safe_ratio": sum(safe_ratios) / len(safe_ratios),
                    "min_safe_ratio": min(safe_ratios),
                    "max_safe_ratio": max(safe_ratios),
                    "avg_unsafe_ratio": sum(unsafe_ratios) / len(unsafe_ratios),
                    "min_unsafe_ratio": min(unsafe_ratios),
                    "max_unsafe_ratio": max(unsafe_ratios),
                    "num_runs": len(safe_ratios),
                }
    
    # Create output directory based on results directory name; per-model charts go in subfolders.
    output_dir = Path("analysis_output") / results_dir.name
    output_dir.mkdir(parents=True, exist_ok=True)

    def _plot_dir_for_model(model_name: str) -> Path:
        d = output_dir / _model_output_subdir(model_name)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # All per-model plots below are gated behind --verbose. By default we only
    # emit the two main figures (Fig 2a + Fig 2b) under all_models/.
    if verbose:
      print("Generating per-model grouped charts...")

      # Success/utility rate (avg success per run) grouped by task/prompt (with error bars)
      if not success_task_averages:
          print("⚠ No success_check records found (model_responses.jsonl). Cannot plot utility/success rate.")
      else:
          for model_name, task_avgs_for_model in success_task_averages.items():
              model_task_groups = task_groups.get(model_name, {})
              model_task_suites = task_suites.get(model_name, {})
              plot_dir = _plot_dir_for_model(model_name)
              _plot_grouped_by_task_and_prompt_with_errorbars(
                  task_avgs_for_model,
                  plot_dir,
                  model_name,
                  value_key="avg_success",
                  min_key="min_success",
                  max_key="max_success",
                  filename_prefix="utility_by_task",
                  ylabel="Avg Success Rate per Run",
                  title="Utility (Success) Rate",
                  task_groups=model_task_groups,
                  task_suites=model_task_suites,
              )

      # Aggregated summary (per-model utility chart, optionally split by group)
      if action_type_task_averages and task_averages and success_task_averages:
        for model_name in action_type_task_averages.keys():
            model_task_groups = task_groups.get(model_name, {})
            model_task_suites = task_suites.get(model_name, {})
            plot_dir = _plot_dir_for_model(model_name)

            # Check if we have only one suite
            suites_present = set()
            if model_task_suites:
                suites_present = {s for s in model_task_suites.values() if s and s != 'unspecified'}
            single_suite = len(suites_present) == 1

            # All tasks combined
            plot_aggregated_summary(
                action_type_task_averages[model_name],
                task_averages[model_name],
                success_task_averages[model_name],
                plot_dir,
                model_name,
                task_groups=None,
                task_group_filter=None,
                task_suites=model_task_suites,
                action_data=action_data.get(model_name) if action_data else None,
                success_data=success_data.get(model_name) if success_data else None,
                use_average=use_average,
            )
            
            if single_suite:
                # For single suite: combine both groups on one graph with group-by-group bars
                plot_aggregated_summary(
                    action_type_task_averages[model_name],
                    task_averages[model_name],
                    success_task_averages[model_name],
                    plot_dir,
                    model_name,
                    task_groups=model_task_groups,
                    task_group_filter=None,  # Don't filter, show both groups
                    task_suites=model_task_suites,
                    action_data=action_data.get(model_name) if action_data else None,
                    success_data=success_data.get(model_name) if success_data else None,
                    use_average=use_average,
                    group_by_task_group=True,  # New parameter to enable grouping by task group
                )
            else:
                # For multiple suites: separate graphs per group as before
                # Simple tasks
                plot_aggregated_summary(
                    action_type_task_averages[model_name],
                    task_averages[model_name],
                    success_task_averages[model_name],
                    plot_dir,
                    model_name,
                    task_groups=model_task_groups,
                    task_group_filter="1_simple",
                    task_suites=model_task_suites,
                    action_data=action_data.get(model_name) if action_data else None,
                    success_data=success_data.get(model_name) if success_data else None,
                    use_average=use_average,
                )

                # Harder tasks
                plot_aggregated_summary(
                    action_type_task_averages[model_name],
                    task_averages[model_name],
                    success_task_averages[model_name],
                    plot_dir,
                    model_name,
                    task_groups=model_task_groups,
                    task_group_filter="2_harder",
                    task_suites=model_task_suites,
                    action_data=action_data.get(model_name) if action_data else None,
                    success_data=success_data.get(model_name) if success_data else None,
                    use_average=use_average,
                )
    
    if not token_data:
        print("⚠ No token_usage.jsonl files found.")

    # Multi-model comparison plots (--all-models)
    discovered_models = set(action_data.keys()) | set(success_data.keys())
    all_models_panels = build_all_models_panels(discovered_models, all_models_include)
    if len(all_models_panels) >= 2:
        all_models_dir = output_dir / "all_models"
        all_models_dir.mkdir(parents=True, exist_ok=True)
        print("Generating multi-model comparison plots...")
        print(f"  Panels ({len(all_models_panels)}): " + ", ".join(f"{k} → {t}" for k, t in all_models_panels))

        # Always-on: the two main paper figures.
        if token_data:
            # Fig 2b
            plot_total_cost_combined_groups_all_models(
                token_data, task_groups, all_models_dir,
                model_panels=all_models_panels,
            )
            # Fig 2a
            plot_aggregated_utility_combined_groups_all_models(
                success_data, task_groups, task_suites, all_models_dir,
                model_panels=all_models_panels,
            )

        # Verbose-only: everything else goes under all_models/breakdown/ + per-model dirs.
        if verbose:
            breakdown_dir = all_models_dir / "breakdown"
            breakdown_dir.mkdir(parents=True, exist_ok=True)
            # All tasks
            plot_aggregated_summary_all_models(
                action_data, success_data, task_groups, task_suites,
                breakdown_dir, use_average=use_average,
                model_panels=all_models_panels,
            )
            # Simple tasks
            plot_aggregated_summary_all_models(
                action_data, success_data, task_groups, task_suites,
                breakdown_dir, use_average=use_average, task_group_filter="1_simple",
                model_panels=all_models_panels,
            )
            # Harder tasks
            plot_aggregated_summary_all_models(
                action_data, success_data, task_groups, task_suites,
                breakdown_dir, use_average=use_average, task_group_filter="2_harder",
                model_panels=all_models_panels,
            )
            if token_data:
                # Absolute tokens with Nx labels.
                plot_token_usage_absolute_all_models(
                    token_data, breakdown_dir, model_panels=all_models_panels,
                )
                # Absolute USD cost (input | output).
                plot_cost_levels_absolute_all_models(
                    token_data, breakdown_dir, model_panels=all_models_panels,
                )
                # Total cost split by task group.
                plot_total_cost_by_group_all_models(
                    token_data, task_groups, breakdown_dir,
                    model_panels=all_models_panels,
                )
                # Combined input+output token ratio.
                plot_token_ratio_combined_by_group_all_models(
                    token_data, task_groups, breakdown_dir,
                    model_panels=all_models_panels,
                )
                # Combined cost box (both groups, hatched 2_harder).
                plot_cost_box_both_groups_combined(
                    token_data, task_groups, breakdown_dir,
                    model_panels=all_models_panels,
                )
                # Per-group token ratio + per-group cost box plots.
                plot_token_ratio_by_group(
                    token_data, success_data, task_groups, task_suites,
                    breakdown_dir, model_panels=all_models_panels,
                )
                plot_cost_box_by_group(
                    token_data, task_groups, task_suites,
                    breakdown_dir, model_panels=all_models_panels,
                )
            if action_data:
                plot_action_box_by_group(
                    action_data, task_groups, task_suites,
                    breakdown_dir, model_panels=all_models_panels,
                )

        # Per-model versions: verbose only.
        if not verbose:
            print(f"\n✓ Two main figures (Fig 2a + Fig 2b) at: {all_models_dir}/")
            print("  Pass --verbose to also produce all_models/breakdown/ and per-model dirs.")
            return
        print("\nGenerating per-model token/cost/action plots...")
        for model_dir, model_label in all_models_panels:
            # Resolve full model dir name from fragment
            matched = next((m for m in success_data if model_dir.lower() in m.lower()), None)
            if not matched:
                continue
            per_model_dir = output_dir / _model_output_subdir(matched)
            per_model_dir.mkdir(parents=True, exist_ok=True)
            if token_data:
                plot_token_ratio_by_group(
                    token_data, success_data, task_groups, task_suites,
                    per_model_dir, model_filter=matched,
                )
                plot_cost_box_by_group(
                    token_data, task_groups, task_suites,
                    per_model_dir, model_filter=matched,
                )
                plot_cost_box_both_groups_combined(
                    token_data, task_groups, per_model_dir,
                    model_filter=matched,
                )
                # Per-suite combined token ratio (one figure per model with
                # both groups side-by-side per suite)
                plot_token_ratio_combined_by_suite_per_model(
                    token_data, task_groups, task_suites,
                    per_model_dir, model_filter=matched, model_label=model_label,
                )
                # Per-task ratio chart per (suite, group)
                plot_token_ratio_by_task(
                    token_data, task_groups, task_suites,
                    per_model_dir, model_filter=matched, model_label=model_label,
                )
    elif all_models_mode:
        print(
            "⚠ --all-models was set but fewer than 2 models matched ALL_MODELS_PANELS / --all-models-include. "
            f"Discovered: {sorted(discovered_models)}; panels: {all_models_panels}"
        )

    print(f"\n✓ Analysis complete! Per-model charts: {output_dir}/<model>/")
    if len(all_models_panels) >= 2:
        print(f"  Multi-model comparison: {output_dir}/all_models/")

if __name__ == "__main__":
    main()