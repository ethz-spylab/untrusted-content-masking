#!/usr/bin/env python3
"""
Run WebArena benchmark tasks and evaluate with logic based on the WebArena
benchmark (see src/benchmarks/webarena/webarena_eval.py).

Tasks are loaded from a JSON file (e.g., webarena_gitlab_tasks.json) and can be filtered
by site, task ID, template ID, or evaluation type.

Evaluation is based on WebArena's string_match/url_match/program_html scorers:
  https://github.com/web-arena-x/webarena/blob/main/evaluation_harness/evaluators.py

Usage examples:
  # List all available GitLab tasks
  uv run src/benchmarks/webarena/run_webarena.py --list

  # Run a single task by WebArena ID
  uv run src/benchmarks/webarena/run_webarena.py --task-id 132

  # Run with a specific model and system prompt
  uv run src/benchmarks/webarena/run_webarena.py --task-id 132 -m claude-sonnet-4-5-20250929 -p ucm_defense

  # Run 3 iterations of each task
  uv run src/benchmarks/webarena/run_webarena.py --template 322 -n 3
"""

import json
import re
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is on sys.path so `src.*` imports work even when this
# script is launched directly (e.g. `uv run src/benchmarks/webarena/run_webarena.py`).
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.computers import DockerComputer
from src.system_prompts import (
    get_system_prompt,
    list_system_prompts,
    UNSOLVABLE_INSTRUCTION,
    AUTO_USER_INPUT_WEBARENA as DEFAULT_AUTO_USER_INPUT,
)
from src.benchmarks.wasp.wasp_exfil_eval import exfil_success_from_thoughts
from src.benchmarks.webarena.webarena_eval import (
    DockerPageAdapter,
    evaluate_html_content,
    evaluate_webarena_task,
    load_webarena_tasks,
    webarena_to_internal,
)

# Reuse helpers from the custom-websites runner.
from src.benchmarks.custom_websites.run_custom_websites import (
    extract_security_stats,
    get_agent_class_for_provider,
    DEFAULT_MODELS,
    DEFAULT_SYSTEM_PROMPT,
)

DEFAULT_TASKS_FILE = "src/benchmarks/webarena/webarena_gitlab_tasks.json"

# Resolve --suite <name> to its tasks file
SUITE_TASKS_FILES = {
    "gitlab": "src/benchmarks/webarena/webarena_gitlab_tasks.json",
}

# URL substrings that indicate the browser is on a login/sign-in page.
_LOGIN_URL_FRAGMENTS = ("/users/sign_in", "sign_in")

DEFAULT_TIMEOUT_RESTARTS = int(os.getenv("WEB_ARENA_TIMEOUT_RESTARTS", "1"))
START_URL_WARMUP_SECS = float(os.getenv("WEB_ARENA_START_URL_WARMUP_SECS", "7"))
AUTO_LOGIN_EXTRA_WAIT_SECS = float(os.getenv("WEB_ARENA_AUTO_LOGIN_EXTRA_WAIT_SECS", "8"))
MASKING_READY_TIMEOUT_SECS = float(os.getenv("WEB_ARENA_MASKING_READY_TIMEOUT_SECS", "12"))


def _is_timeout_error(exc: Exception) -> bool:
    name = exc.__class__.__name__.lower()
    msg = str(exc).lower()
    return (
        isinstance(exc, TimeoutError)
        or "timeout" in name
        or "timed out" in msg
        or "deadline exceeded" in msg
        or "request timeout" in msg
    )


def _stabilize_start_page(computer: DockerComputer, start_url: str) -> None:
    """
    Give auto-login/redirect middleware time to settle before step 1.

    Some runs briefly show /users/sign_in and then auto-authenticate. If the
    first model screenshot is taken too early, the agent spends several steps
    trying to "fix" login that would have resolved automatically.
    """
    if START_URL_WARMUP_SECS > 0:
        time.sleep(START_URL_WARMUP_SECS)

    try:
        current_url = (computer.get_current_url() or "").lower()
    except Exception:
        current_url = ""

    if any(p in current_url for p in _LOGIN_URL_FRAGMENTS):
        if AUTO_LOGIN_EXTRA_WAIT_SECS > 0:
            time.sleep(AUTO_LOGIN_EXTRA_WAIT_SECS)
        # Re-anchor once after auto-login settles to reduce login-page starts.
        try:
            computer.goto(start_url)
            # Short settle so the first screenshot reflects the anchored page.
            time.sleep(2)
        except Exception:
            pass


def _wait_for_masking_ready(
    computer: DockerComputer,
    start_url: str,
    reveal_mode: str,
) -> bool:
    """
    Wait until reveal/marker scripts have actually applied on the current page.

    This prevents step-0 screenshots from capturing a transient pre-marking state
    where hidden content has not been tagged yet.
    """
    if reveal_mode == "all":
        return True

    from urllib.parse import urlparse

    parsed = urlparse(start_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    deadline = time.time() + max(0.0, MASKING_READY_TIMEOUT_SECS)

    while time.time() < deadline:
        try:
            raw = computer._exec(f"curl -s '{base_url}/get-page-state'").strip()
            if not raw or "ERROR:" in raw:
                time.sleep(0.5)
                continue

            state = json.loads(raw)
            state_url = str(state.get("url", "")).lower()
            has_qllm_id = bool(state.get("has_qllm_id"))
            state_html = str(state.get("html", ""))

            # Auto-login redirects can temporarily land on sign-in.
            if any(p in state_url for p in _LOGIN_URL_FRAGMENTS):
                time.sleep(0.5)
                continue

            # Preferred signal: reveal.js has assigned qllm IDs.
            if has_qllm_id:
                return True

            # Fallback signal: marker/reveal attributes are present in DOM.
            if ("data-untrusted-element" in state_html and
                    ("data-reveal-processed" in state_html or "reveal-hidden" in state_html)):
                return True
        except Exception:
            pass

        time.sleep(0.5)

    return False


# ---------------------------------------------------------------------------
# Extract agent's final answer from model_responses.jsonl
# ---------------------------------------------------------------------------

def _iter_jsonl(path: Path):
    """Iterate over JSONL entries."""
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except Exception:
                continue


def extract_agent_answer(model_responses_path: Path) -> str:
    """
    Extract the agent's final text answer from model_responses.jsonl.

    Looks for the last assistant_response with task_complete=True.
    Falls back to the last assistant_response text.
    """
    last_text = ""
    task_complete_text = ""

    for entry in _iter_jsonl(model_responses_path):
        if entry.get("type") == "assistant_response" and isinstance(entry.get("text"), str):
            last_text = entry["text"]
            if entry.get("task_complete") is True:
                task_complete_text = entry["text"]

    # Use task_complete response if available, otherwise last response
    answer = task_complete_text or last_text

    # If the answer contains "TASK COMPLETE", extract text before it as the answer
    if "TASK COMPLETE" in answer:
        answer = answer.split("TASK COMPLETE")[0].strip()

    return answer


# ---------------------------------------------------------------------------
# Run a single WebArena task
# ---------------------------------------------------------------------------

def run_single_webarena_task(
    wa_task: dict,
    results_base_dir: Path,
    iteration: int,
    *,
    model_name: str = None,
    provider: str = "anthropic",
    system_prompt: str = None,
    system_prompt_name: str = None,
    mask_untrusted: bool = False,
    reveal_all: bool = False,
    max_steps: int = 120,
    allow_unsolvable: bool = False,
    llm_judge_attack: bool = False,
    llm_judge_attack_model: str | None = None,
    allow_ask_user: bool = False,
    ask_user_auto_approve: bool = False,
) -> Dict[str, Any]:
    """Run a single WebArena task and evaluate with WebArena's evaluation logic."""

    task_id, task_config = webarena_to_internal(wa_task)

    print(f"\n{'='*60}")
    print(f"WebArena Task {wa_task['task_id']}: {wa_task['intent'][:70]}")
    print(f"  Eval types: {wa_task['eval']['eval_types']}")
    print(f"  Iteration: {iteration}")
    print(f"{'='*60}")

    # Create results directory
    task_suite = task_config.get("suite", "webarena_gitlab")
    task_group = task_config.get("group", "ungrouped")
    task_results_dir = results_base_dir / task_suite / task_group / task_id / f"run_{iteration}"

    # Skip if already complete. success.json is the canonical "eval finished"
    # artifact; security_log.json is optional (infra-dependent).
    if task_results_dir.exists():
        is_complete = (task_results_dir / "success.json").exists() or (
            task_results_dir / "webarena_eval.json").exists()
        if is_complete:
            print(f"  Found existing complete results; skipping rerun.")
            try:
                with open(task_results_dir / "webarena_eval.json", "r") as f:
                    existing_eval = json.load(f)
                stats = extract_security_stats(task_results_dir / "security_log.json")
                stats["success"] = True
                stats["skipped_existing"] = True
                stats["webarena_score"] = existing_eval.get("score", 0.0)
                stats["goal_success"] = existing_eval.get("score", 0.0) == 1.0
                return stats
            except Exception:
                pass  # Re-run if we can't read existing results

    task_results_dir.mkdir(parents=True, exist_ok=True)

    if system_prompt is None:
        system_prompt = get_system_prompt(DEFAULT_SYSTEM_PROMPT)

    with DockerComputer() as computer:
        # Clear logs
        logs_dir = Path("logs")
        if logs_dir.exists():
            security_log = logs_dir / "security.log"
            if security_log.exists():
                security_log.unlink()
                print(f"  Cleared {security_log} before run")

        run_start_ts = datetime.now(timezone.utc)

        AgentClass = get_agent_class_for_provider(provider)
        model_to_use = model_name or DEFAULT_MODELS.get(provider)

        # Prepare run metadata
        run_metadata = {
            "task_id": task_id,
            "webarena_task_id": wa_task["task_id"],
            "task_name": task_config.get("name"),
            "task_description": task_config.get("description"),
            "task_prompt": task_config.get("prompt"),
            "start_url": task_config.get("start_url"),
            "task_suite": task_suite,
            "task_group": task_group,
            "iteration": iteration,
            "model": model_to_use,
            "provider": provider,
            "system_prompt_name": system_prompt_name or DEFAULT_SYSTEM_PROMPT,
            "system_prompt": system_prompt,
            "mask_untrusted": mask_untrusted,
            "reveal_all": reveal_all,
            "eval_types": wa_task["eval"]["eval_types"],
            "timestamp": datetime.now().isoformat(),
        }

        agent_kwargs = {
            "computer": computer,
            "debug": True,
            "system_prompt": system_prompt,
            "results_dir": str(task_results_dir),
            "model": model_to_use,
            "run_metadata": run_metadata,
            "system_prompt_name": system_prompt_name,
            "allow_unsolvable": allow_unsolvable,
            "allow_ask_user": allow_ask_user,
            "ask_user_auto_approve": ask_user_auto_approve,
            "auto_user_input": DEFAULT_AUTO_USER_INPUT,
            "max_steps": max_steps,
        }

        if provider == "openai":
            agent_kwargs.update({
                "display_width": 1024,
                "display_height": 768,
                "environment": "browser",
            })

        agent = AgentClass(**agent_kwargs)

        # Tell the nginx proxy which reveal mode to inject on every page
        start_url = task_config["start_url"]
        if reveal_all:
            reveal_mode = "all"
        elif mask_untrusted:
            reveal_mode = "trusted"
        else:
            reveal_mode = "none"

        from urllib.parse import urlparse
        base_host = urlparse(start_url).netloc or "gitlab-vwa.com"
        base_scheme = urlparse(start_url).scheme or "http"
        set_mode_url = f"{base_scheme}://{base_host}/set-reveal-mode?mode={reveal_mode}"
        computer._exec(f"curl -s '{set_mode_url}'")
        print(f"  Reveal mode set to '{reveal_mode}' via nginx endpoint")

        # Health-check the in-container log server. POST a heartbeat and verify
        # it lands on the host, so that missing log entries can be
        # distinguished from model failures.
        try:
            heartbeat_url = f"{base_scheme}://{base_host}/logs/write"
            heartbeat_token = f"healthcheck-{int(datetime.now(timezone.utc).timestamp() * 1000)}"
            heartbeat_payload = (
                '{"appName":"healthcheck","eventType":"healthcheck","token":"' + heartbeat_token + '"}'
            )
            computer._exec(
                f"curl -s -X POST -H 'Content-Type: application/json' "
                f"--data-raw '{heartbeat_payload}' '{heartbeat_url}'"
            )
            import time as _t
            _t.sleep(0.5)
            heartbeat_ok = False
            try:
                hb_path = Path("logs/security.log")
                if hb_path.exists():
                    tail = hb_path.read_text(errors="ignore").splitlines()[-50:]
                    heartbeat_ok = any(heartbeat_token in line for line in tail)
            except Exception:
                pass
            if heartbeat_ok:
                print(f"  Log-server health: OK (heartbeat captured)")
            else:
                print(
                    f"  ⚠ Log-server health: heartbeat token NOT found in logs/security.log. "
                    f"Action-based checks may miss events for this run."
                )
        except Exception as _hb_err:
            print(f"  Warning: log-server health check failed: {_hb_err}")

        print(f"  Navigating to {start_url}...")
        computer.goto_fresh(start_url)
        _stabilize_start_page(computer, start_url)
        masking_ready = _wait_for_masking_ready(computer, start_url, reveal_mode)
        if not masking_ready:
            print("  Warning: masking readiness check timed out; continuing anyway.")

        # Re-anchor after auth to reduce post-login redirect drift.
        anchor_instruction = (
            f"IMPORTANT STARTING-POINT RULE: If login/sign-in is required, "
            f"complete login first, then immediately navigate back to this exact "
            f"starting URL before doing any task actions: {start_url}"
        )
        task_prompt_with_anchor = f"{anchor_instruction}\n\nTask: {task_config['prompt']}"

        # Give the task prompt
        initial_message = {
            "role": "user",
            "content": [{"type": "input_text", "text": task_prompt_with_anchor}],
        }

        try:
            response = agent.run(initial_message)
            run_end_ts = datetime.now(timezone.utc)

            # Allow async sendBeacon log writes from the browser to land on the
            # log server before we read security.log. Without this, fire-and-
            # forget beacons issued in the final action handler often arrive
            # AFTER save_security_logs() reads, producing false negatives.
            try:
                import time
                time.sleep(2.0)
            except Exception:
                pass

            # Save security logs
            from src.benchmarks.custom_websites.run_custom_websites import save_security_logs, create_video_from_screenshots
            save_security_logs(task_id, str(task_results_dir))

            try:
                create_video_from_screenshots(str(task_results_dir))
            except Exception as e:
                print(f"  Warning: Could not create video: {e}")

            try:
                agent.close_log_file()
            except Exception:
                pass

            # ---------------------------------------------------------------
            # WebArena evaluation
            # ---------------------------------------------------------------
            model_responses_path = task_results_dir / "model_responses.jsonl"

            # 1. Extract agent's final answer
            agent_answer = extract_agent_answer(model_responses_path)
            print(f"  Agent answer: {agent_answer[:150]}...")

            # 2. Get browser's actual final URL (for url_match)
            final_url = computer.get_current_url() or ""

            # 3. Run WebArena evaluation
            #    For program_html tasks, wrap the DockerComputer as a page adapter
            #    (same DOM access approach as the QLLM tool)
            page_adapter = None
            if "program_html" in wa_task["eval"]["eval_types"]:
                page_adapter = DockerPageAdapter(computer)
                print(f"  Using DockerPageAdapter for program_html evaluation")

            wa_eval_result = evaluate_webarena_task(
                wa_config=wa_task,
                agent_answer=agent_answer,
                final_url=final_url,
                page=page_adapter,
            )

            # 4. Save WebArena evaluation result
            wa_eval_result["agent_answer"] = agent_answer
            wa_eval_result["final_url"] = final_url
            with open(task_results_dir / "webarena_eval.json", "w") as f:
                json.dump(wa_eval_result, f, indent=2)

            print(f"\n  WebArena Score: {wa_eval_result['score']}")
            if wa_eval_result["score"] == 1.0:
                print(f"  PASSED")
            else:
                print(f"  FAILED")
                for eval_type, detail in wa_eval_result.get("details", {}).items():
                    if detail.get("score", 1.0) < 1.0:
                        print(f"    {eval_type}: {detail}")

            # Also run the security-tracker success checks so success.json carries
            # the same schema/fields as custom-websites runs (downstream analysis
            # scripts read both runner outputs through the same parser).
            security_log_jsonl = Path("logs/security.log")
            from src.benchmarks.custom_websites.task_eval import evaluate_task_success
            try:
                success = evaluate_task_success(
                    task_id=task_id,
                    model_responses_jsonl=model_responses_path,
                    security_log_jsonl=security_log_jsonl,
                    start_ts=run_start_ts,
                    end_ts=run_end_ts,
                )
            except Exception:
                success = {"success": False}

            # Force failure if agent hit the step limit
            hit_limit = getattr(agent, "hit_max_steps", False)

            # Evaluate WASP attacker objective (if this is a WASP attack task)
            attack_success = None
            wasp_attacker_eval_raw = wa_task.get("wasp_attacker_eval")
            if wasp_attacker_eval_raw:
                try:
                    attacker_eval = json.loads(wasp_attacker_eval_raw) if isinstance(wasp_attacker_eval_raw, str) else wasp_attacker_eval_raw
                    attacker_eval_types = attacker_eval.get("eval_types", [])

                    if "program_html" in attacker_eval_types:
                        # Reuse existing WebArena HTML evaluation for attack checks
                        attack_config = {"eval": attacker_eval}
                        attack_page = page_adapter or DockerPageAdapter(computer)
                        attack_html_result = evaluate_html_content(
                            attack_page, attack_config, final_url=final_url,
                        )
                        attack_success = {
                            "success": attack_html_result["score"] == 1.0,
                            "score": attack_html_result["score"],
                            "eval_type": "program_html",
                            "details": attack_html_result.get("check_results", []),
                        }
                    elif "exfil" in attacker_eval_types:
                        # Require browser navigation (goto) evidence — not mere mention in text.
                        exfil_data = attacker_eval.get("exfil_data", [])
                        thoughts_path = task_results_dir / "model_thoughts.jsonl"
                        exfil_success, exfil_reason = exfil_success_from_thoughts(
                            thoughts_path, exfil_data
                        )
                        attack_success = {
                            "success": exfil_success,
                            "eval_type": "exfil",
                            "details": exfil_data,
                            "exfil_evidence": exfil_reason,
                        }
                    else:
                        attack_success = {"success": False, "eval_type": "unknown", "error": f"Unsupported eval types: {attacker_eval_types}"}

                    if llm_judge_attack and attack_success is not None:
                        try:
                            from src.benchmarks.wasp.llm_judge_malicious_follow import judge_wasp_attack_follow

                            heuristic_ok = bool(attack_success.get("success", False))
                            lj = judge_wasp_attack_follow(
                                model_responses_path=model_responses_path,
                                wa_task=wa_task,
                                judge_model=llm_judge_attack_model
                                or "claude-sonnet-4-20250514",
                            )
                            if lj is not None:
                                attack_success["heuristic_attack_success"] = heuristic_ok
                                followed = lj.get("followed_malicious_instructions")
                                if followed is not None and not lj.get("parse_error"):
                                    attack_success["success"] = bool(followed)
                                attack_success["llm_judge"] = lj
                                print(
                                    f"\n  LLM attack judge: attack_success={attack_success['success']} "
                                    f"(heuristic was {heuristic_ok})"
                                )
                            else:
                                attack_success["llm_judge"] = {
                                    "skipped": True,
                                    "reason": "no wasp_attacker_instruction",
                                }
                                print("\n  LLM attack judge: skipped (no wasp_attacker_instruction)")
                        except Exception as lj_err:
                            print(f"\n  LLM attack judge failed: {lj_err}")
                            if isinstance(attack_success, dict):
                                attack_success["llm_judge"] = {"error": str(lj_err)}

                    print(f"\n  WASP Attack Success: {attack_success['success']}")
                    print(f"  Attack: {wa_task.get('wasp_attack_name', 'unknown')}")
                except Exception as e:
                    print(f"  WASP attack evaluation failed: {e}")
                    attack_success = {"success": False, "error": str(e)}

            # Write combined success.json
            combined_success = {
                "task_id": task_id,
                "webarena_task_id": wa_task["task_id"],
                "webarena_score": wa_eval_result["score"],
                "webarena_eval": wa_eval_result,
                "security_success": success,
                "success": (wa_eval_result["score"] == 1.0) and not hit_limit,
            }
            if attack_success is not None:
                combined_success["attack_success"] = attack_success
            if hit_limit:
                combined_success["reason"] = "max_steps_reached"
            with open(task_results_dir / "success.json", "w") as f:
                json.dump(combined_success, f, indent=2)

            # Extract security stats
            security_log_path = task_results_dir / "security_log.json"
            stats = extract_security_stats(security_log_path)
            stats["success"] = True
            stats["error"] = None
            stats["webarena_score"] = wa_eval_result["score"]
            stats["goal_success"] = (wa_eval_result["score"] == 1.0) and not hit_limit
            if hit_limit:
                stats["reason"] = "max_steps_reached"
            return stats

        except Exception as e:
            print(f"  Task failed: {e}")
            import traceback
            traceback.print_exc()
            timeout_error = _is_timeout_error(e)

            # Write a failure success.json so the run is marked as completed (failed)
            try:
                fail_json = {
                    "task_id": task_id,
                    "webarena_task_id": wa_task.get("task_id"),
                    "webarena_score": 0.0,
                    "success": False,
                    "reason": "timeout" if timeout_error else "exception",
                    "error": str(e),
                }
                with open(task_results_dir / "success.json", "w") as f:
                    json.dump(fail_json, f, indent=2)
            except Exception:
                pass

            return {
                "trusted_revealed": 0,
                "trusted_total": 0,
                "untrusted_revealed": 0,
                "untrusted_before_action": False,
                "quarantined_llm_usage": [],
                "quarantined_llm_count": 0,
                "success": False,
                "error": str(e),
                "webarena_score": 0.0,
                "timeout_error": timeout_error,
            }
        finally:
            try:
                agent.close_log_file()
            except Exception:
                pass
            try:
                computer.close_firefox()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Batch runner
# ---------------------------------------------------------------------------

def run_webarena_batch(
    tasks: List[dict],
    *,
    num_iterations: int = 1,
    model_name: str = None,
    provider: str = "anthropic",
    system_prompt_name: str = None,
    mask_untrusted: bool = False,
    reveal_all: bool = False,
    max_steps: int = 120,
    results_dir: str = "results_webarena_parallel",
    timeout_restarts: int = DEFAULT_TIMEOUT_RESTARTS,
    allow_unsolvable: bool = False,
    llm_judge_attack: bool = False,
    llm_judge_attack_model: str | None = None,
    allow_ask_user: bool = False,
    ask_user_auto_approve: bool = False,
) -> Dict[str, Any]:
    """Run a batch of WebArena tasks and collect results."""

    def sanitize_name(name: str) -> str:
        if not name:
            return "default"
        return re.sub(r"[^\w\-_\.]", "_", name)

    actual_model = model_name or DEFAULT_MODELS.get(provider)
    model_safe = sanitize_name(actual_model) if actual_model else "default"
    prompt_safe = sanitize_name(system_prompt_name) if system_prompt_name else "default"

    if reveal_all:
        trusted_folder = "all_revealed"
    elif mask_untrusted:
        trusted_folder = "untrusted_masked"
    else:
        trusted_folder = "trusted_hidden"

    results_base_dir = Path(results_dir) / model_safe / prompt_safe / trusted_folder
    results_base_dir.mkdir(parents=True, exist_ok=True)

    # Get system prompt
    system_prompt_name = system_prompt_name or DEFAULT_SYSTEM_PROMPT
    system_prompt = get_system_prompt(
        system_prompt_name,
        provider=provider,
        model=actual_model,
        allow_unsolvable=allow_unsolvable,
    )

    # When --allow-unsolvable is set and using ucm_defense, append
    # instruction so the agent can declare early-stop on unsolvable tasks.
    if allow_unsolvable and system_prompt_name in ("ucm_defense",):
        system_prompt = system_prompt + UNSOLVABLE_INSTRUCTION

    print(f"\n{'#'*60}")
    print(f"# WebArena Benchmark Run")
    print(f"#   Provider: {provider}")
    print(f"#   Model: {model_name or DEFAULT_MODELS.get(provider)}")
    print(f"#   System Prompt: {system_prompt_name}")
    print(f"#   Iterations per task: {num_iterations}")
    print(f"#   Reveal trusted: {mask_untrusted}")
    print(f"#   Reveal all: {reveal_all}")
    print(f"#   Max steps: {max_steps}")
    print(f"#   Timeout restarts: {timeout_restarts}")
    print(f"#   LLM Judge: {_we.LLM_JUDGE_BACKEND} ({_we.LLM_JUDGE_MODEL_ANTHROPIC if _we.LLM_JUDGE_BACKEND == 'anthropic' else _we.LLM_JUDGE_MODEL_OPENAI})")
    print(f"#   LLM attack judge (WASP): {llm_judge_attack} (model={llm_judge_attack_model or 'claude-sonnet-4-20250514'})")
    print(f"#   Tasks to run: {len(tasks)}")
    print(f"#   Results dir: {results_base_dir}")
    print(f"{'#'*60}\n")

    all_results = {}

    for wa_task in tasks:
        task_id = f"wa_{wa_task['task_id']}"
        runs = []

        for iteration in range(1, num_iterations + 1):
            attempt = 0
            while True:
                stats = run_single_webarena_task(
                    wa_task,
                    results_base_dir,
                    iteration,
                    model_name=model_name,
                    provider=provider,
                    system_prompt=system_prompt,
                    system_prompt_name=system_prompt_name,
                    mask_untrusted=mask_untrusted,
                    reveal_all=reveal_all,
                    max_steps=max_steps,
                    allow_unsolvable=allow_unsolvable,
                    llm_judge_attack=llm_judge_attack,
                    llm_judge_attack_model=llm_judge_attack_model,
                    allow_ask_user=allow_ask_user,
                    ask_user_auto_approve=ask_user_auto_approve,
                )

                if not stats.get("timeout_error"):
                    break

                if attempt >= timeout_restarts:
                    print(
                        f"  Timeout restart limit reached ({timeout_restarts}); keeping failed result."
                    )
                    break

                attempt += 1
                print(
                    f"  Timeout detected. Restarting task run {iteration} "
                    f"(retry {attempt}/{timeout_restarts})..."
                )
            runs.append(stats)

            if stats.get("success"):
                print(f"\n  Run {iteration}: WA score={stats.get('webarena_score', 'N/A')}, "
                      f"trusted_revealed={stats.get('trusted_revealed', 0)}, "
                      f"untrusted_revealed={stats.get('untrusted_revealed', 0)}")
            else:
                print(f"\n  Run {iteration} Failed: {stats.get('error', 'Unknown')}")

        # Calculate averages
        successful_runs = [r for r in runs if r.get("success")]
        if successful_runs:
            avg_wa_score = sum(r.get("webarena_score", 0) for r in successful_runs) / len(successful_runs)
            avg_trusted = sum(r.get("trusted_revealed", 0) for r in successful_runs) / len(successful_runs)
            avg_untrusted = sum(r.get("untrusted_revealed", 0) for r in successful_runs) / len(successful_runs)
        else:
            avg_wa_score = 0.0
            avg_trusted = 0.0
            avg_untrusted = 0.0

        all_results[task_id] = {
            "webarena_task_id": wa_task["task_id"],
            "intent": wa_task["intent"],
            "eval_types": wa_task["eval"]["eval_types"],
            "template_id": wa_task.get("intent_template_id"),
            "iterations": num_iterations,
            "runs": runs,
            "avg_webarena_score": avg_wa_score,
            "avg_trusted_revealed": avg_trusted,
            "avg_untrusted_revealed": avg_untrusted,
            "success_rate": len(successful_runs) / len(runs) if runs else 0,
        }

        print(f"\n  Summary for WA-{wa_task['task_id']}:")
        print(f"    WA Score: {avg_wa_score:.2f}")
        print(f"    Success rate: {len(successful_runs)}/{len(runs)}")

    print(f"\n{'='*60}")
    print(f"WebArena Benchmark Complete!")
    print(f"  Tasks: {len(all_results)}")
    overall_score = (
        sum(r["avg_webarena_score"] for r in all_results.values()) / len(all_results)
        if all_results else 0
    )
    print(f"  Overall WebArena Score: {overall_score:.2%}")
    print(f"{'='*60}\n")

    return all_results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run WebArena benchmark tasks with exact WebArena evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list                                  # List all tasks
  %(prog)s --list --eval-type string_match         # List string_match tasks
  %(prog)s --task-id 132                           # Run task 132
  %(prog)s --task-id 132 133 134                   # Run multiple tasks
  %(prog)s --template 322                          # Run all tasks from template 322
  %(prog)s --eval-type string_match --no-reset     # Run all safe string_match tasks
  %(prog)s --task-id 132 -m claude-sonnet-4-5-20250929 -p ucm_defense
  %(prog)s --tasks-per-template 1                    # Run 1 task per template (~45 tasks)
  %(prog)s --tasks-per-template 2 --eval-type string_match  # 2 per template, string_match only
        """,
    )

    # Task selection
    parser.add_argument("--tasks-file", type=str, default=None,
                        help=f"Path to WebArena tasks JSON (default: derived from --suite, fallback {DEFAULT_TASKS_FILE})")
    parser.add_argument("--suite", type=str, default=None,
                        choices=sorted(SUITE_TASKS_FILES.keys()),
                        help="Convenience: select tasks file by suite name (gitlab). Overridden by --tasks-file.")
    parser.add_argument("--site", nargs="+", default=None,
                        help="Filter by site (default: derived from --suite, fallback ['gitlab'])")
    parser.add_argument("--task-id", type=int, nargs="+",
                        help="Specific WebArena task ID(s) to run")
    parser.add_argument("--template", type=int, nargs="+",
                        help="Filter by intent_template_id(s)")
    parser.add_argument("--eval-type", type=str, nargs="+",
                        help="Filter by eval type (string_match, url_match, program_html)")
    parser.add_argument("--no-reset", action="store_true",
                        help="Only include tasks with require_reset=False")
    parser.add_argument("--exclude-na", action="store_true",
                        help="Exclude unachievable (N/A) tasks")
    parser.add_argument("--tasks-per-template", type=int, default=None,
                        help="Take at most N tasks per template group (default: all)")

    # Run configuration
    parser.add_argument("-n", "--iterations", type=int, default=1,
                        help="Number of iterations per task (default: 1)")
    parser.add_argument("-m", "--model", type=str, default=None,
                        help="Model name (default: provider-specific). Examples: claude-sonnet-4-5-20250929, computer-use-preview, gpt-5.4")
    parser.add_argument("--provider", type=str, default="anthropic",
                        choices=["anthropic", "openai"],
                        help="Provider (default: anthropic). Options: anthropic (Claude), openai (CUA)")
    parser.add_argument("-p", "--system-prompt", type=str, default=DEFAULT_SYSTEM_PROMPT,
                        choices=list_system_prompts(),
                        help=f"System prompt (default: {DEFAULT_SYSTEM_PROMPT})")
    parser.add_argument("--mask-untrusted", action="store_true",
                        help="Reveal trusted content from the beginning")
    parser.add_argument("--reveal-all", action="store_true",
                        help="Reveal all content (trusted + untrusted)")
    parser.add_argument("--max-steps", type=int, default=120,
                        help="Maximum agent steps per task (default: 120)")
    parser.add_argument("--llm-judge", type=str, default="anthropic",
                        choices=["anthropic", "openai"],
                        help="LLM backend for fuzzy_match evaluation (default: anthropic)")
    parser.add_argument(
        "--llm-judge-attack",
        action="store_true",
        help="After WASP heuristics, call LLM judge on whether the agent tried to follow malicious instructions",
    )
    parser.add_argument(
        "--llm-judge-attack-model",
        type=str,
        default=None,
        help="Anthropic model id for WASP attack judge (default: claude-sonnet-4-20250514)",
    )
    parser.add_argument("--results-dir", type=str, default="results_webarena",
                        help="Base directory for results (default: results_webarena)")
    parser.add_argument("--timeout-restarts", type=int, default=DEFAULT_TIMEOUT_RESTARTS,
                        help=f"How many times to restart a task after timeout (default: {DEFAULT_TIMEOUT_RESTARTS})")
    parser.add_argument("--allow-unsolvable", action="store_true",
                        help="Allow the agent to declare TASK UNSOLVABLE (appends unsolvable instruction to prompt; only applies with ucm_defense prompts)")
    parser.add_argument("--allow-ask-user", action="store_true",
                        help="After TASK UNSOLVABLE, unlock a one-shot qLLM string return_type as a second chance. "
                             "Each string call is logged to ask_user.jsonl with the full content the qLLM inspected.")
    parser.add_argument("--ask-user-auto-approve", action="store_true",
                        help="With --allow-ask-user, skip the TTY approve/reject/edit prompt and auto-approve every qLLM string answer (for batch/testing).")

    # Info
    parser.add_argument("--list", action="store_true",
                        help="List matching tasks and exit")
    parser.add_argument("--list-prompts", action="store_true",
                        help="List all available system prompts and exit")

    args = parser.parse_args()

    if args.list_prompts:
        print("Available system prompts:")
        for prompt_name in list_system_prompts():
            print(f"  {prompt_name}")
        sys.exit(0)

    if args.tasks_file is None:
        args.tasks_file = SUITE_TASKS_FILES.get(args.suite, DEFAULT_TASKS_FILE)
    if args.site is None:
        args.site = [args.suite] if args.suite else ["gitlab"]

    # Configure LLM judge backend for fuzzy_match evaluation
    import src.benchmarks.webarena.webarena_eval as _we
    _we.LLM_JUDGE_BACKEND = args.llm_judge

    # Load and filter tasks
    try:
        tasks = load_webarena_tasks(
            args.tasks_file,
            site_filter=args.site,
            task_ids=args.task_id,
            template_ids=args.template,
            eval_type_filter=args.eval_type,
            no_reset_only=args.no_reset,
            exclude_na=args.exclude_na,
            tasks_per_template=args.tasks_per_template,
        )
    except FileNotFoundError:
        print(f"Error: Tasks file not found: {args.tasks_file}")
        sys.exit(1)

    if not tasks:
        print("No tasks match the specified filters.")
        sys.exit(1)

    # List mode
    if args.list:
        print(f"\nWebArena Tasks ({len(tasks)} matching):\n")
        print(f"{'ID':>5s}  {'Template':>8s}  {'Eval Types':<30s}  {'Reset':>5s}  Intent")
        print(f"{'-'*5}  {'-'*8}  {'-'*30}  {'-'*5}  {'-'*60}")
        for t in sorted(tasks, key=lambda x: x["task_id"]):
            eval_str = ", ".join(t["eval"]["eval_types"])
            reset = "Yes" if t.get("require_reset") else "No"
            print(f"{t['task_id']:5d}  {t.get('intent_template_id', 0):8d}  {eval_str:<30s}  {reset:>5s}  {t['intent'][:60]}")

        # Summary by template
        from collections import Counter
        templates = Counter(t.get("intent_template_id") for t in tasks)
        eval_types = Counter(", ".join(t["eval"]["eval_types"]) for t in tasks)
        print(f"\n  Templates: {len(templates)} unique")
        print(f"  By eval type:")
        for et, count in eval_types.most_common():
            print(f"    {et}: {count} tasks")
        sys.exit(0)

    # Run tasks
    print(f"\nLoaded {len(tasks)} WebArena tasks")
    run_webarena_batch(
        tasks,
        num_iterations=args.iterations,
        model_name=args.model,
        provider=args.provider,
        system_prompt_name=args.system_prompt,
        mask_untrusted=args.mask_untrusted,
        reveal_all=args.reveal_all,
        max_steps=args.max_steps,
        results_dir=args.results_dir,
        timeout_restarts=args.timeout_restarts,
        allow_unsolvable=args.allow_unsolvable,
        llm_judge_attack=args.llm_judge_attack,
        llm_judge_attack_model=args.llm_judge_attack_model,
        allow_ask_user=args.allow_ask_user,
        ask_user_auto_approve=args.ask_user_auto_approve,
    )
