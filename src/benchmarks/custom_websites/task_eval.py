import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .task_eval_templates import MODEL_SUCCESS_CHECKS, SUCCESS_CHECKS

def _extract_suite_from_task_id(task_id: str) -> str:
    parts = task_id.split('_')
    if parts:
        return parts[0]
    return "unknown"

def _suite_to_app_name(suite: str) -> str:
    """
    Map suite name to actual appName used in logs.
    Service names in docker-compose.yml are the appNames logged to SecurityTracker.
    """
    # Suite name → Docker service name (appName in logs).
    # Only listed when they differ; everything else falls through unchanged.
    mapping = {
        "webshop": "ecommerce-search",
        "jobboard": "job-board",
        "travel": "travel-booking",
    }
    return mapping.get(suite, suite)

def _parse_iso(ts: str) -> Optional[datetime]:
    if not isinstance(ts, str) or not ts:
        return None
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
        # If a timestamp is missing tzinfo, assume UTC to keep comparisons consistent.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj


def _window_logs(
    log_path: Path,
    *,
    app_name: str,
    start_ts: datetime,
    end_ts: datetime,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in _iter_jsonl(log_path):
        if e.get("appName") != app_name:
            continue
        # Time filtering removed: logs are cleared before each run, so all entries are from current run
        out.append(e)
    return out


def _assistant_indicated_task_complete(model_responses_jsonl: Path) -> bool:
    for e in _iter_jsonl(model_responses_jsonl):
        if e.get("type") == "assistant_response" and e.get("task_complete") is True:
            return True
    return False


def _load_model_entries(model_responses_jsonl: Path) -> List[Dict[str, Any]]:
    return list(_iter_jsonl(model_responses_jsonl))


def evaluate_success_from_website_logs(
    *,
    task_id: str,
    security_log_jsonl: Path,
    start_ts: datetime,
    end_ts: datetime,
) -> Dict[str, Any]:
    """
    Website-side success checks for specific tasks based on SecurityTracker logs
    written to logs/security.log (JSONL).
    """
    suite = _extract_suite_from_task_id(task_id)
    app_name = _suite_to_app_name(suite)
    
    logs = _window_logs(security_log_jsonl, app_name=app_name, start_ts=start_ts, end_ts=end_ts)
    checker = SUCCESS_CHECKS.get(task_id)
    if not checker:
        return {
            "success": False,
            "checks": [{"name": "no_website_success_check_defined", "ok": False, "evidence": {"task_id": task_id}}],
            "source": "website_logs",
        }

    result = checker(logs)
    return {
        "success": bool(result.get("success", False)),
        "checks": result.get("checks", []),
        "source": "website_logs",
    }


def evaluate_success_from_model_output(*, task_id: str, model_responses_jsonl: Path) -> Dict[str, Any]:
    checker = MODEL_SUCCESS_CHECKS.get(task_id)
    if not checker:
        return {
            "success": False,
            "checks": [{"name": "no_model_success_check_defined", "ok": False, "evidence": {"task_id": task_id}}],
            "source": "model_output",
        }
    entries = _load_model_entries(model_responses_jsonl)
    result = checker(entries)
    return {
        "success": bool(result.get("success", False)),
        "checks": result.get("checks", []),
        "source": "model_output",
    }


def evaluate_task_success(
    *,
    task_id: str,
    model_responses_jsonl: Path,
    security_log_jsonl: Path,
    start_ts: datetime,
    end_ts: datetime,
) -> Dict[str, Any]:
    """
    Combine website-side checks and model-output checks (when defined).
    Overall success is:
      - if both check types exist: OR (either path counts). Success if either
        the website event fired or the agent's text evidence confirms the
        correct action was performed.
      - if only one exists: that one
    """
    website_defined = task_id in SUCCESS_CHECKS
    model_defined = task_id in MODEL_SUCCESS_CHECKS

    website = evaluate_success_from_website_logs(
        task_id=task_id, security_log_jsonl=security_log_jsonl, start_ts=start_ts, end_ts=end_ts
    ) if website_defined else None

    model = evaluate_success_from_model_output(task_id=task_id, model_responses_jsonl=model_responses_jsonl) if model_defined else None

    if website_defined and model_defined:
        overall = bool(website["success"]) or bool(model["success"])
    elif website_defined:
        overall = bool(website["success"])
    elif model_defined:
        overall = bool(model["success"])
    else:
        overall = False

    return {
        "task_id": task_id,
        "success": overall,
        "website": website,
        "model": model,
    }


def append_success_check(model_responses_jsonl: Path, payload: Dict[str, Any]) -> None:
    entry = {
        "type": "success_check",
        "timestamp": datetime.now().isoformat(),
        **payload,
    }
    model_responses_jsonl.parent.mkdir(parents=True, exist_ok=True)
    with open(model_responses_jsonl, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


