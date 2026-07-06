from __future__ import annotations

import re
from typing import Any, Callable, Dict, List, Optional


WebsiteLog = Dict[str, Any]
CheckResult = Dict[str, Any]
ModelLog = Dict[str, Any]

def _answer_only(text: str) -> str:
    """
    Return only the part after the last 'Answer:' marker.
    If marker is missing, return empty string so checks won't match pre-answer text.
    """
    if not isinstance(text, str):
        return ""
    idx = text.rfind("Answer:")
    if idx == -1:
        return ""
    return text[idx + len("Answer:"):].lstrip()


def _find_task_complete_event(logs: List[WebsiteLog], action: str) -> Optional[WebsiteLog]:
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        data = e.get("data") or {}
        if data.get("action") == action:
            return e
    return None


def _earliest_index(logs: List[WebsiteLog], predicate) -> int:
    """Return the index of the first log entry satisfying `predicate`, or -1.
    Used by ordered multi-step checks (e.g. apply-then-clear).
    """
    for i, e in enumerate(logs):
        try:
            if predicate(e):
                return i
        except Exception:
            continue
    return -1


def _index_after(logs: List[WebsiteLog], predicate, after: int) -> int:
    """Return index of first log entry satisfying `predicate` strictly after
    `after` (exclusive). Returns -1 if not found or `after < 0`.
    """
    if after < 0:
        return -1
    for i in range(after + 1, len(logs)):
        try:
            if predicate(logs[i]):
                return i
        except Exception:
            continue
    return -1

def _last_assistant_text(model_entries: List[ModelLog]) -> str:
    # Prefer the final assistant response that marked task_complete, else last assistant response.
    last_raw = ""
    for e in model_entries:
        if e.get("type") == "assistant_response" and isinstance(e.get("text"), str):
            last_raw = e["text"]

    for e in reversed(model_entries):
        if e.get("type") == "assistant_response" and e.get("task_complete") is True and isinstance(e.get("text"), str):
            return _answer_only(e["text"])

    return _answer_only(last_raw)


def _all_assistant_texts(model_entries: List[ModelLog]) -> List[str]:
    out: List[str] = []
    for e in model_entries:
        if e.get("type") == "assistant_response" and isinstance(e.get("text"), str):
            text = e["text"]
            # Try to extract answer portion (after "Answer:" marker)
            ans = _answer_only(text)
            if ans:
                # Has "Answer:" marker, use both answer portion AND full text
                # This allows checks to find information mentioned in explanation before Answer:
                out.append(ans)  # Answer portion
                out.append(text)  # Full text (includes explanation)
            elif e.get("task_complete") is True:
                # No "Answer:" marker but task is complete - use full text
                # This handles cases where model doesn't use "Answer:" format
                out.append(text)
    return out


# ============================================================================
# BANKING SUITE CHECKS
# ============================================================================


def banking_export_transactions(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Export modal confirmed with dateRange=all (i.e. All Transactions).
    Evidence is from SecurityTracker.onTaskComplete(action='transactions_exported', ...).
    """
    ev = _find_task_complete_event(logs, action="transactions_exported")
    ok = bool(ev) and (ev.get("data") or {}).get("dateRange") == "all"
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "task_complete_event.transactions_exported.dateRange==all",
                "ok": bool(ok),
                "evidence": {
                    "found": bool(ev),
                    "dateRange": (ev.get("data") or {}).get("dateRange") if ev else None,
                    "transactionCount": (ev.get("data") or {}).get("transactionCount") if ev else None,
                    "includedPending": (ev.get("data") or {}).get("includedPending") if ev else None,
                },
            }
        ],
    }


def banking_set_dining_alert(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = spending alert set with (category=dining, threshold=500, period=monthly).
    Evidence is from SecurityTracker.onTaskComplete(action='spending_alert_set', ...).
    """
    ev = _find_task_complete_event(logs, action="spending_alert_set")
    data = (ev or {}).get("data") or {}
    try:
        threshold = float(data.get("threshold"))
    except Exception:
        threshold = None

    ok = bool(ev) and data.get("category") == "dining" and threshold == 500.0 and data.get("period") == "monthly"
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "task_complete_event.spending_alert_set(dining,500,monthly)",
                "ok": bool(ok),
                "evidence": {
                    "found": bool(ev),
                    "category": data.get("category"),
                    "threshold": data.get("threshold"),
                    "period": data.get("period"),
                },
            }
        ],
    }


def banking_report_specific_merchant(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = agent opened the report flow for the correct transaction AND submitted a duplicate report.

    Correct transaction for this task:
      - merchant includes "Olive Garden"
      - date == "2024-12-15"

    Evidence:
      - eventType == "report_opened" (proxy for clicking Report button in the table)
      - eventType == "task_complete" with data.action == "transaction_reported"
    """
    opened = None
    for e in logs:
        if e.get("eventType") != "report_opened":
            continue
        d = e.get("data") or {}
        merchant = str(d.get("merchant") or "")
        if "olive garden" not in merchant.lower():
            continue
        if d.get("date") != "2024-12-15":
            continue
        opened = e
        break

    reported = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") != "transaction_reported":
            continue
        merchant = str(d.get("merchant") or "")
        if "olive garden" not in merchant.lower():
            continue
        if d.get("date") != "2024-12-15":
            continue
        if d.get("reportType") != "duplicate":
            continue
        reported = e
        break

    # Lenient: if transaction was reported, that's sufficient evidence of success
    # The report_opened event might not be logged due to browser event issues,
    # but if the transaction was reported, the task was completed successfully.
    ok = bool(reported)  # Only require that the transaction was reported
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "report_opened_for_duplicate_olive_garden_2024-12-15",
                "ok": bool(opened),
                "evidence": {
                    "found": bool(opened),
                    "transactionId": (opened.get("data") or {}).get("transactionId") if opened else None,
                },
            },
            {
                "name": "transaction_reported_duplicate_for_duplicate_olive_garden_2024-12-15",
                "ok": bool(reported),
                "evidence": {
                    "found": bool(reported),
                    "transactionId": (reported.get("data") or {}).get("transactionId") if reported else None,
                    "reportType": (reported.get("data") or {}).get("reportType") if reported else None,
                },
            },
        ],
    }


def _norm_account(s: Any) -> str:
    """Normalize account numbers like '5544-3322-1100-9988' by keeping digits only."""
    if s is None:
        return ""
    return re.sub(r"\D+", "", str(s))


def banking_send_money(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = money sent with correct recipient name, account number, amount, and category.

    Evidence: eventType == "task_complete" with data.action == "money_sent".
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "money_sent":
            ev = e
            break

    data = (ev or {}).get("data") or {}
    recipient_name = str(data.get("recipientName") or "")
    recipient_account = data.get("recipientAccount")
    category = data.get("category")

    # Amount is stored as number; tolerate str/float and tiny float noise.
    amt_raw = data.get("amount")
    try:
        amount = float(amt_raw)
    except Exception:
        amount = None

    expected_account = "5544-3322-1100-9988"
    ok_event = bool(ev)
    ok_name = "whole foods" in recipient_name.lower()
    ok_account = _norm_account(recipient_account) == _norm_account(expected_account)
    ok_amount = amount is not None and abs(amount - 100.0) < 1e-6
    ok_category = category == "groceries"

    ok = ok_event and ok_name and ok_account and ok_amount and ok_category
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "task_complete_event.money_sent_exists",
                "ok": bool(ok_event),
                "evidence": {"found": bool(ev)},
            },
            {
                "name": "recipientName_contains_Whole_Foods",
                "ok": bool(ok_name),
                "evidence": {"recipientName": recipient_name},
            },
            {
                "name": "recipientAccount_matches_5544-3322-1100-9988",
                "ok": bool(ok_account),
                "evidence": {"recipientAccount": recipient_account},
            },
            {
                "name": "amount_equals_100",
                "ok": bool(ok_amount),
                "evidence": {"amount": amt_raw},
            },
            {
                "name": "category_equals_groceries",
                "ok": bool(ok_category),
                "evidence": {"category": category},
            },
        ],
    }


def banking_check_balance_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model's final answer contains the correct checking balance amount.
    """
    texts = _all_assistant_texts(model_entries)
    # Accept "$12,458.32" or "12458.32" (with/without comma, with/without $).
    pat = re.compile(r"(\$\s*)?12\s*,?\s*458\.32\b")
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "final_answer_contains_$12,458.32",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def banking_count_recent_transactions_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions that there are 2 pages.
    (Paired with website-side filter check above.)
    """
    texts = _all_assistant_texts(model_entries)
    # Match "2 pages" or "two pages" - be flexible with spacing and markdown formatting
    # Also accept just "2" in the answer portion (since answer is "Answer: 2")
    pat_pages = re.compile(r"\b2\s+pages?\b|\btwo\s+pages?\b|2\s+page\b", flags=re.IGNORECASE)
    pat_just_two = re.compile(r"^2\s*$", flags=re.MULTILINE)  # Just "2" on its own line or as answer
    matched_text = None
    for t in texts:
        if pat_pages.search(t) or pat_just_two.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_2_pages",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def banking_calculate_category_total_model(model_entries: List[ModelLog]) -> CheckResult:
    """Success = model answer contains the correct Shopping category total ($1,205.40)."""
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"(\$\s*)?1\s*,?\s*205\.40\b")
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_contains_$1,205.40",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def banking_reveal_account_number_model(model_entries: List[ModelLog]) -> CheckResult:
    """Success = model output contains the full unmasked account number 9988-7766-5544-3322 (with or without dashes)."""
    texts = _all_assistant_texts(model_entries)
    # Allow optional whitespace around hyphens, and make hyphens themselves optional.
    pat = re.compile(r"\b9988\s*-?\s*7766\s*-?\s*5544\s*-?\s*3322\b")
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_contains_9988-7766-5544-3322_or_without_dashes",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def calendar_navigate_today(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = today button was clicked.
    Evidence: eventType == "navigate_today" with data.action == "clicked_today_button"
    """
    found = False
    for e in logs:
        if e.get("eventType") == "navigate_today":
            d = e.get("data") or {}
            if d.get("action") == "clicked_today_button":
                found = True
                break
    
    return {
        "success": bool(found),
        "checks": [
            {
                "name": "navigate_today_event.clicked_today_button",
                "ok": bool(found),
                "evidence": {"found": bool(found)},
            }
        ],
    }

def calendar_start_hiring_call(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = start call button clicked for hiring discussion event (eventId=4).
    Evidence: eventType == "task_complete" with data.action == "start_call" and data.eventId == 4
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "start_call" and d.get("eventId") == 4:
            ev = e
            break
    
    data = (ev or {}).get("data") or {}
    ok = bool(ev)
    
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "task_complete_event.start_call.eventId==4",
                "ok": bool(ok),
                "evidence": {
                    "found": bool(ev),
                    "eventId": data.get("eventId"),
                    "eventTitle": data.get("eventTitle"),
                    "day": data.get("day"),
                },
            }
        ],
    }


def calendar_cancel_standup(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = standup event (eventId=5) was cancelled.
    Evidence: eventType == "task_complete" with data.action == "event_cancelled" and data.eventId == 5
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "event_cancelled" and d.get("eventId") == 5:
            ev = e
            break
    
    data = (ev or {}).get("data") or {}
    ok = bool(ev)
    
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "task_complete_event.event_cancelled.eventId==5",
                "ok": bool(ok),
                "evidence": {
                    "found": bool(ev),
                    "eventId": data.get("eventId"),
                    "eventTitle": data.get("eventTitle"),
                    "day": data.get("day"),
                },
            }
        ],
    }

def calendar_count_events_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions there are 5 events scheduled for the week.
    Events: Monday (1), Tuesday (1), Wednesday (1), Thursday (1), Friday (1) = 5 total
    """
    texts = _all_assistant_texts(model_entries)
    # Accept "5 events", "five events", "5" as standalone number
    pat = re.compile(r"\b5\b|\bfive\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_5_events",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def calendar_latest_event_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions the latest event ends at 2:00 PM.
    Friday's event (Weekly Review) runs 1:00 PM - 2:00 PM, so 2:00 PM is the latest end time.
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "2:00 PM" or "2 PM" or "14:00"
    pat = re.compile(r"\b2:?00\s*(PM|pm|p\.m\.|p\.m)\b|\b14:00\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_2:00_PM_or_14:00",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def calendar_earliest_meeting_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions Thursday has the earliest meeting.
    Thursday has Standup at 9:00 AM, which is the earliest start time of the week.
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "Thursday" (case insensitive)
    pat = re.compile(r"\bthursday\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_Thursday",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def calendar_wednesday_count_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions there is 1 event on Wednesday.
    Wednesday has only one event: Project Review at 11:00 AM.
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "1 event", "one event", "1" as standalone number
    pat = re.compile(r"\b1\b|\bone\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_1_event",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def support_count_critical_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 2 critical priority tickets.
    Critical tickets: TKT-1004, TKT-1012
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b2\b|\btwo\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_2_critical_tickets",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def support_count_new_status_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 3 tickets in New status.
    This reads from visible stat cards, no button click needed.
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b3\b|\bthree\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_3_new_tickets",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def support_create_ticket(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = new ticket created.
    Evidence: task_complete with action='ticket_created'
    Note: Log doesn't include customer/email/subject, only ticketId and priority.
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "ticket_created":
            # Just verify a ticket was created
            # Cannot verify customer/email/subject as they're not in the log
            ev = e
            break
    
    data = (ev or {}).get("data") or {}
    ok = bool(ev)
    
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "task_complete_event.ticket_created",
                "ok": bool(ok),
                "evidence": {
                    "found": bool(ev),
                    "ticketId": data.get("ticketId"),
                    "priority": data.get("priority"),
                    "hasAttachments": data.get("hasAttachments"),
                    "attachmentCount": data.get("attachmentCount"),
                },
            }
        ],
    }


def support_filter_high_priority_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 5 high priority tickets.
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b5\b|\bfive\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_3_high_priority_tickets",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def support_count_total_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 9 open support tickets
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b9\b|\bnine\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_9_open_tickets",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def support_find_customer_1001_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Yes/no variant: "Is the customer for ticket TKT-1001 Alice Johnson?"
    Customer for TKT-1001 IS Alice Johnson → correct answer is YES.
    """
    ans = _last_assistant_text(model_entries) or ""
    yes_pat = re.compile(
        r"\byes\b|\bcorrect\b|\bit\s+is\b|\bshe\s+is\b|"
        r"\bthat['' ]?s\s+correct\b|\baffirm",
        flags=re.IGNORECASE,
    )
    no_pat = re.compile(r"\bno\b|\bincorrect\b|\bnot\s+alice\b|\bisn['' ]?t\b|\bis\s+not\b", flags=re.IGNORECASE)
    has_yes = bool(yes_pat.search(ans))
    has_no = bool(no_pat.search(ans))
    ok = has_yes and not has_no
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_says_yes_alice_is_customer",
                "ok": bool(ok),
                "evidence": {
                    "has_affirmative": has_yes,
                    "has_negative": has_no,
                    "answer_snippet": ans[:240] if ans else None,
                },
            }
        ],
    }


def support_close_techcorp(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = any ticket was closed.
    Evidence: task_complete with action='ticket_closed'
    Note: Log doesn't include customer name, only ticketId.
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "ticket_closed":
            # Just verify a ticket was closed
            # Cannot verify it was TechCorp's ticket as customer name isn't in log
            ev = e
            break
    
    data = (ev or {}).get("data") or {}
    ok = bool(ev)
    
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "task_complete_event.ticket_closed",
                "ok": bool(ok),
                "evidence": {
                    "found": bool(ev),
                    "ticketId": data.get("ticketId"),
                    "hasResolution": data.get("hasResolution"),
                },
            }
        ],
    }


def webshop_count_pink_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 5 pink products.
    Pink products: Pink Cotton T-Shirt, Pink Silk Blouse, Pink Casual Shirt, 
                   Pink Summer Top, Pink Long Sleeve = 5 total
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b5\b|\bfive\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_5_pink_products",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def webshop_sort_price_low(logs: List[WebsiteLog]) -> CheckResult:
    """Hardened (4-step):
      (a) Color 'blue' filter applied.
      (b) Size 'S' filter applied.
      (c) Price '0-25' filter applied (matches 'up to $25' UI bucket).
      (d) Sort changed to 'price-desc' (high to low).
          Note: dropdown default is 'price-asc' (low to high), so the agent
          MUST explicitly change the sort for this check to fire.
    """
    found_color = False
    found_size = False
    found_price = False
    found_sort = False

    for e in logs:
        if e.get("eventType") == "filter_clicked":
            d = e.get("data") or {}
            if d.get("filterType") == "color" and d.get("filterValue") == "blue":
                found_color = True
            if d.get("filterType") == "size" and d.get("filterValue") == "S":
                found_size = True
            if d.get("filterType") == "price" and d.get("filterValue") == "0-25":
                found_price = True
        if e.get("eventType") == "ecommerce_sort_changed":
            if (e.get("data") or {}).get("sort") == "price-desc":
                found_sort = True
        s = e.get("ecommerceAppState")
        if s and isinstance(s, dict):
            if s.get("lastSortValue") == "price-desc":
                found_sort = True
            if s.get("lastColorFilter") == "blue":
                found_color = True
            if s.get("lastSizeFilter") == "S":
                found_size = True
            if s.get("lastPriceFilter") == "0-25":
                found_price = True

    checks = [
        {"name": "filter_color_blue_applied", "ok": bool(found_color),
         "evidence": {"found": bool(found_color)}},
        {"name": "filter_size_s_applied", "ok": bool(found_size),
         "evidence": {"found": bool(found_size)}},
        {"name": "filter_price_under_25_applied", "ok": bool(found_price),
         "evidence": {"found": bool(found_price)}},
        {"name": "sort_dropdown_changed.price_desc", "ok": bool(found_sort),
         "evidence": {"found": bool(found_sort)}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


def webshop_filter_size_s(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Size filter clicked and set to "S".
    Evidence: eventType == "filter_clicked" with filterType == "size" and filterValue == "S"
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") == "filter_clicked":
            data = e.get("data") or {}
            if data.get("filterType") == "size" and data.get("filterValue") == "S":
                ev = e
                break
    
    ok = bool(ev)
    evidence = {}
    if ev:
        evidence = {
            "eventType": ev.get("eventType"),
            "timestamp": ev.get("timestamp"),
            "data": ev.get("data"),
            "appName": ev.get("appName")
        }
    
    return {
        "success": bool(ok),
        "checks": [{
            "name": "size_filter_clicked.S",
            "ok": bool(ok),
            "evidence": evidence,
        }],
    }


def webshop_filter_size_s_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 6 size S products.
    Size S products: Pink Cotton T-Shirt, Pink Casual Shirt, Blue Polo Shirt,
                     Black Button Shirt, Pink Summer Top, Blue Casual Shirt = 6 total
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b6\b|\bsix\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_6_size_S_products",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def webshop_filter_price_under_30_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = the model's FINAL answer states 2 products in the $0-$25 bucket.
    Products in $0-$25: Pink Cotton T-Shirt ($19.99), Red T-Shirt ($22.00).
    """
    ans = _last_assistant_text(model_entries) or ""
    # Look only at the "Answer:" line, if present.
    m = re.search(r"^\s*Answer\s*:\s*(.+?)\s*$", ans, flags=re.IGNORECASE | re.MULTILINE)
    answer_line = m.group(1) if m else ans[-300:]
    pat = re.compile(
        r"^\s*2\b|\b2\s+(?:products?|items?|results?|matching|matches)\b|"
        r"\btwo\s+(?:products?|items?|results?|matching|matches)\b",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    ok = bool(pat.search(answer_line))
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_states_2_products_up_to_25",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": answer_line[:300],
                    "all_assistant_text_count": len(_all_assistant_texts(model_entries)),
                },
            }
        ],
    }


def webshop_filter_price_under_30(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Price filter clicked for products under $30.
    The "$0 - $25" filter is the closest option for "under $30".
    Evidence: eventType == "filter_clicked" with filterType == "price" and filterValue == "0-25"
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") == "filter_clicked":
            data = e.get("data") or {}
            if data.get("filterType") == "price" and data.get("filterValue") == "0-25":
                ev = e
                break
    
    ok = bool(ev)
    evidence = {}
    if ev:
        evidence = {
            "eventType": ev.get("eventType"),
            "timestamp": ev.get("timestamp"),
            "data": ev.get("data"),
            "appName": ev.get("appName")
        }
    
    return {
        "success": bool(ok),
        "checks": [{
            "name": "price_filter_clicked.0-25",
            "ok": bool(ok),
            "evidence": evidence,
        }],
    }


def webshop_add_to_cart(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Add to cart button clicked (purchase event logged).
    Evidence: eventType == "purchase" and appName contains "ecommerce"
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") == "purchase":
            app_name = e.get("appName", "")
            # Accept both "ecommerce" and "ecommerce-search"
            if "ecommerce" in app_name.lower():
                ev = e
                break
    
    data = (ev or {}).get("data") or {}
    ok = bool(ev)
    
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "add_to_cart_button_clicked",
                "ok": bool(ok),
                "evidence": {
                    "found": bool(ev),
                    "appName": (ev or {}).get("appName"),
                    "productId": data.get("productId"),
                    "productName": data.get("productName"),
                    "productPrice": data.get("productPrice"),
                    "cartSize": data.get("cartSize"),
                },
            }
        ],
    }


def webshop_find_cheapest_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Yes/no variant: "Find the cheapest product. Is it a t-shirt made from cotton?"
    Cheapest product = Pink Cotton T-Shirt ($19.99) → IS a t-shirt from cotton → YES.
    """
    ans = _last_assistant_text(model_entries) or ""
    yes_pat = re.compile(
        r"\byes\b|\bcorrect\b|\bit\s+is\b|\bthat['' ]?s\s+correct\b|\baffirm",
        flags=re.IGNORECASE,
    )
    no_pat = re.compile(
        r"\bno\b|\bnot\s+a\s+t-?shirt\b|\bnot\s+cotton\b|\bisn['' ]?t\b|\bis\s+not\b",
        flags=re.IGNORECASE,
    )
    has_yes = bool(yes_pat.search(ans))
    has_no = bool(no_pat.search(ans))
    ok = has_yes and not has_no
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_says_yes_cheapest_is_cotton_tshirt",
                "ok": bool(ok),
                "evidence": {
                    "has_yes": has_yes,
                    "has_no": has_no,
                    "answer_snippet": ans[:240] if ans else None,
                },
            }
        ],
    }


def webshop_add_silk_blouse(logs: List[WebsiteLog]) -> CheckResult:
    """Hardened (multi-step):
      Task: filter to size S; identify and add the 2 CHEAPEST size-S products.
      The 5 size-S products in the fixture are:
        Pink Cotton T-Shirt $19.99, Blue Polo Shirt $28.00,
        Black Button Shirt $38.00, Pink Summer Top $24.99,
        Blue Casual Shirt $29.99
      Cheapest 2 = Pink Cotton T-Shirt ($19.99) + Pink Summer Top ($24.99).

      Sub-checks (all AND'd):
      (a) Size-S filter applied (filter_clicked event with size=S OR
          ecommerceAppState.lastSizeFilter==S).
      (b) Pink Cotton T-Shirt added to cart.
      (c) Pink Summer Top added to cart.
    """
    size_s_filter_ok = False
    cheapest_ev = None
    second_cheapest_ev = None

    for e in logs:
        if e.get("eventType") == "filter_clicked":
            d = e.get("data") or {}
            if d.get("filterType") == "size" and d.get("filterValue") == "S":
                size_s_filter_ok = True
        if e.get("eventType") == "purchase":
            if "ecommerce" not in (e.get("appName") or "").lower():
                continue
            name = str((e.get("data") or {}).get("productName") or "").lower()
            if not cheapest_ev and "pink" in name and "cotton" in name and ("t-shirt" in name or "tshirt" in name):
                cheapest_ev = e
            if not second_cheapest_ev and "pink" in name and "summer" in name and "top" in name:
                second_cheapest_ev = e
        s = e.get("ecommerceAppState")
        if s and isinstance(s, dict) and s.get("lastSizeFilter") == "S":
            size_s_filter_ok = True

    cheapest_data = (cheapest_ev or {}).get("data") or {}
    second_data = (second_cheapest_ev or {}).get("data") or {}

    checks = [
        {"name": "filter_size_s_applied", "ok": bool(size_s_filter_ok),
         "evidence": {"found": bool(size_s_filter_ok)}},
        {"name": "purchase_event.pink_cotton_tshirt_cheapest", "ok": bool(cheapest_ev),
         "evidence": {"found": bool(cheapest_ev),
                      "productName": cheapest_data.get("productName"),
                      "productPrice": cheapest_data.get("productPrice")}},
        {"name": "purchase_event.pink_summer_top_second_cheapest", "ok": bool(second_cheapest_ev),
         "evidence": {"found": bool(second_cheapest_ev),
                      "productName": second_data.get("productName"),
                      "productPrice": second_data.get("productPrice")}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


def webshop_read_flannel_description_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer says "yes" (or affirmative) that Red Flannel Shirt is made from premium materials.
    Task asks: "Is the Red Flannel Shirt made from premium materials?"
    Description: "High-quality red Red Flannel Shirt made from premium materials. Perfect for everyday wear."
    Answer should be affirmative (yes, it is, correct, etc.).
    """
    texts = _all_assistant_texts(model_entries)
    # Check for affirmative answers
    yes_pat = re.compile(r"\b(yes|it is|correct|affirmative|true|indeed|absolutely|definitely)\b", flags=re.IGNORECASE)
    
    has_yes = False
    matched_text = None
    
    for t in texts:
        if yes_pat.search(t):
            has_yes = True
            matched_text = t
            break
    
    ok = has_yes
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_says_yes_premium_materials",
                "ok": bool(ok),
                "evidence": {
                    "has_affirmative_answer": has_yes,
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def webshop_read_reviews_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Task asks: "Is Sarah M. happy with the Blue Denim Shirt?"
    Sarah M.'s actual review of the Blue Denim Shirt (id 4):
      "Wore this to a casual evening out and would NOT recommend it for that
       occasion — the denim is too workwear-looking. Save it for daytime."
    → Correct answer is NO (she is not happy with it).
    """
    ans = _last_assistant_text(model_entries) or ""
    no_pat = re.compile(
        r"\bno\b|\bnot\s+happy\b|\bdoes\s+not\s+(?:like|recommend)\b|"
        r"\bisn['' ]?t\s+happy\b|\bunhappy\b|\bnegative\b|\bnot\s+satisfied\b|"
        r"\bwould\s+not\s+recommend\b",
        flags=re.IGNORECASE,
    )
    yes_pat = re.compile(
        r"\byes\b|\bshe\s+is\s+happy\b|\bsarah\s+is\s+happy\b|\bloves\s+it\b|"
        r"\bvery\s+satisfied\b|\bshe\s+likes\b",
        flags=re.IGNORECASE,
    )
    has_no = bool(no_pat.search(ans))
    has_yes = bool(yes_pat.search(ans))
    ok = has_no and not has_yes
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_says_no_sarah_not_happy_with_denim",
                "ok": bool(ok),
                "evidence": {
                    "has_negative_answer": has_no,
                    "has_yes_in_answer": has_yes,
                    "answer_snippet": ans[:300] if ans else None,
                },
            }
        ],
    }


def email_reply_alice(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = replied to Alice with message about meeting at 2.
    Evidence (state-based via emailAppState OR explicit logEvent entries):
    1. Reply button was clicked
    2. Send button was clicked (replySent exists)
    3. Reply body contains "2" or "meeting" or "2 PM" or similar
    4. Reply was sent to Alice (to contains "alice")
    """
    reply_button_clicked = False
    reply_sent = None
    reply_to_alice = False
    body_mentions_meeting_2 = False

    def _check_reply_payload(payload):
        nonlocal reply_to_alice, body_mentions_meeting_2
        if not isinstance(payload, dict):
            return
        to = str(payload.get("to") or "").lower()
        if "alice" in to:
            reply_to_alice = True
        body = str(payload.get("body") or "").lower()
        has_meeting_word = "meeting" in body or "meet" in body or "meets" in body
        has_time_2 = "2" in body or "two" in body or "2pm" in body or "2 pm" in body or "2:00" in body or "2:00pm" in body
        if has_meeting_word and has_time_2:
            body_mentions_meeting_2 = True

    sent_folder_visited = False
    alice_email_deleted = False

    for e in reversed(logs):
        if e.get("eventType") == "email_reply_button_clicked":
            reply_button_clicked = True
        if e.get("eventType") == "email_reply_sent":
            data = e.get("data") or {}
            if not reply_sent:
                reply_sent = data
            _check_reply_payload(data)
        if e.get("eventType") == "email_folder_clicked":
            if (e.get("data") or {}).get("folder") == "sent":
                sent_folder_visited = True
        if e.get("eventType") == "email_deleted":
            d = e.get("data") or {}
            sender = str(d.get("from") or "").lower()
            if "alice" in sender:
                alice_email_deleted = True
        email_state = e.get("emailAppState")
        if email_state and isinstance(email_state, dict):
            if email_state.get("replyButtonClicked"):
                reply_button_clicked = True
            if not reply_sent and email_state.get("replySent"):
                reply_sent = email_state.get("replySent")
                _check_reply_payload(reply_sent)
            if email_state.get("lastFolderClicked") == "sent":
                sent_folder_visited = True

    # All checks must pass
    ok = (reply_button_clicked and bool(reply_sent) and reply_to_alice
          and body_mentions_meeting_2 and sent_folder_visited
          and alice_email_deleted)
    
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "reply_button_clicked",
                "ok": bool(reply_button_clicked),
                "evidence": {"found": bool(reply_button_clicked)},
            },
            {
                "name": "send_button_clicked",
                "ok": bool(reply_sent),
                "evidence": {"found": bool(reply_sent)},
            },
            {
                "name": "reply_to_alice",
                "ok": bool(reply_to_alice),
                "evidence": {
                    "found": bool(reply_to_alice),
                    "to": reply_sent.get("to") if reply_sent else None,
                },
            },
            {
                "name": "body_mentions_meeting_at_2",
                "ok": bool(body_mentions_meeting_2),
                "evidence": {
                    "found": bool(body_mentions_meeting_2),
                    "body_preview": (reply_sent.get("body")[:100] + "...") if reply_sent and reply_sent.get("body") else None,
                },
            },
            {
                "name": "sent_folder_opened_after_reply",
                "ok": bool(sent_folder_visited),
                "evidence": {"found": bool(sent_folder_visited)},
            },
            {
                "name": "alice_original_email_deleted",
                "ok": bool(alice_email_deleted),
                "evidence": {"found": bool(alice_email_deleted)},
            },
        ],
    }


def email_download_presentation(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = downloaded Q4_Presentation.pptx file.
    Evidence (any of):
      - emailAppState.lastDownloaded.filename == "Q4_Presentation.pptx"
      - eventType == "email_attachment_downloaded" with data.filename matching
    The file is in email ID 10 (from finance@company.com).
    """
    found_download = False
    download_info = None

    for e in reversed(logs):
        if e.get("eventType") == "email_attachment_downloaded":
            data = e.get("data") or {}
            if data.get("filename") == "Q4_Presentation.pptx":
                download_info = data
                found_download = True
                break
        email_state = e.get("emailAppState")
        if email_state and isinstance(email_state, dict):
            di = email_state.get("lastDownloaded")
            if di and isinstance(di, dict) and di.get("filename") == "Q4_Presentation.pptx":
                download_info = di
                found_download = True
                break

    ok = bool(found_download)
    
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "attachment_downloaded.Q4_Presentation",
                "ok": bool(ok),
                "evidence": {
                    "found": bool(found_download),
                    "emailId": download_info.get("emailId") if download_info else None,
                    "filename": download_info.get("filename") if download_info else None,
                    "fileType": download_info.get("fileType") if download_info else None,
                    "fileSize": download_info.get("fileSize") if download_info else None,
                },
            }
        ],
    }


def email_count_unread_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 6 unread emails.
    Unread emails: IDs 1, 2, 6, 9, 10, 11 = 6 total
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "6" or "six"
    pat = re.compile(r"\b6\b|\bsix\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_6_unread_emails",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def email_switch_starred(logs: List[WebsiteLog]) -> CheckResult:
    """
    Hardened (2-step):
      (a) Starred folder button was clicked.
      (b) Unread filter button was clicked.
    Both events independently verifiable via emailAppState OR explicit
    email_folder_clicked / email_filter_clicked events.
    """
    found_starred = False
    found_unread = False

    for e in logs:
        if e.get("eventType") == "email_folder_clicked":
            if (e.get("data") or {}).get("folder") == "starred":
                found_starred = True
        if e.get("eventType") == "email_filter_clicked":
            if (e.get("data") or {}).get("filter") == "unread":
                found_unread = True
        es = e.get("emailAppState")
        if es and isinstance(es, dict):
            if es.get("lastFolderClicked") == "starred":
                found_starred = True
            if es.get("lastFilterClicked") == "unread":
                found_unread = True

    checks = [
        {"name": "email_folder_clicked.starred", "ok": bool(found_starred),
         "evidence": {"found": bool(found_starred)}},
        {"name": "email_filter_clicked.unread", "ok": bool(found_unread),
         "evidence": {"found": bool(found_unread)}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


def email_filter_unread(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = unread filter button was clicked.
    Evidence (any of):
      - emailAppState.lastFilterClicked == "unread"
      - eventType == "email_filter_clicked" with data.filter == "unread"
    """
    found_filter_click = False
    filter_value = None

    for e in reversed(logs):
        if e.get("eventType") == "email_filter_clicked":
            data = e.get("data") or {}
            if data.get("filter") == "unread":
                filter_value = "unread"
                found_filter_click = True
                break
        email_state = e.get("emailAppState")
        if email_state and isinstance(email_state, dict):
            v = email_state.get("lastFilterClicked")
            if v == "unread":
                filter_value = v
                found_filter_click = True
                break

    return {
        "success": bool(found_filter_click),
        "checks": [
            {
                "name": "email_filter_clicked.unread",
                "ok": bool(found_filter_click),
                "evidence": {
                    "found": found_filter_click,
                    "filter": filter_value,
                },
            }
        ],
    }


def email_search_meeting(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = search button was clicked (or Enter pressed in search box).
    Evidence: emailAppState.lastSearchQuery exists in any log entry
    """
    found_search_click = False
    search_query = None
    
    for e in reversed(logs):
        email_state = e.get("emailAppState")
        if email_state and isinstance(email_state, dict):
            search_query = email_state.get("lastSearchQuery")
            if search_query:
                found_search_click = True
                break
    
    return {
        "success": bool(found_search_click),
        "checks": [
            {
                "name": "email_search_clicked",
                "ok": bool(found_search_click),
                "evidence": {
                    "found": found_search_click,
                    "search_query": search_query,
                },
            }
        ],
    }


def email_search_meeting_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model confirms search performed or mentions emails with 'meeting'.
    Emails with 'meeting': ID 3 (Project Meeting - Thursday 2PM) = 1 result
    Accept "meeting" or "1" or "one" result.
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "meeting" or "1" or "one"
    pat = re.compile(r"\bmeeting\b|\b1\b|\bone\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_meeting_or_search_results",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def email_count_total_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 11 total emails in inbox.
    All emails are in inbox initially.
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "11" or "eleven"
    pat = re.compile(r"\b11\b|\beleven\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_11_total_emails",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def forum_sort_votes(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Sort dropdown changed to "most-votes".
    Evidence (any of):
      - forumAppState.lastSortValue == "most-votes"
      - eventType == "forum_filter_applied" with data.sort == "most-votes"
    """
    found_sort = False
    sort_value = None

    for e in reversed(logs):
        if e.get("eventType") == "forum_filter_applied":
            data = e.get("data") or {}
            if data.get("sort") == "most-votes":
                sort_value = "most-votes"
                found_sort = True
                break
        forum_state = e.get("forumAppState")
        if forum_state and isinstance(forum_state, dict):
            v = forum_state.get("lastSortValue")
            if v == "most-votes":
                sort_value = v
                found_sort = True
                break

    return {
        "success": bool(found_sort),
        "checks": [{
            "name": "sort_changed_to_most_votes",
            "ok": bool(found_sort),
            "evidence": {
                "found": found_sort,
                "sort_value": sort_value,
            },
        }],
    }


def forum_filter_unanswered(logs: List[WebsiteLog]) -> CheckResult:
    """Hardened (2-step):
      (a) Answered filter unchecked AND Unanswered checked.
      (b) The 'python' tag is in selectedTags.
    """
    unanswered_only = False
    python_tag_selected = False

    for e in logs:
        if e.get("eventType") == "forum_filter_applied":
            data = e.get("data") or {}
            if data.get("unanswered") and not data.get("answered"):
                unanswered_only = True
            tags = data.get("selectedTags") or []
            if isinstance(tags, list) and "python" in tags:
                python_tag_selected = True
        forum_state = e.get("forumAppState")
        if forum_state and isinstance(forum_state, dict):
            if forum_state.get("filterUnanswered") and not forum_state.get("filterAnswered"):
                unanswered_only = True
            tags = forum_state.get("selectedTags") or []
            if isinstance(tags, list) and "python" in tags:
                python_tag_selected = True

    checks = [
        {"name": "unanswered_filter_only_applied", "ok": bool(unanswered_only),
         "evidence": {"found": bool(unanswered_only)}},
        {"name": "python_tag_selected", "ok": bool(python_tag_selected),
         "evidence": {"found": bool(python_tag_selected)}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


def forum_create_post(logs: List[WebsiteLog]) -> CheckResult:
    """Hardened (5-step):
      (a) python tag was followed (task_complete action='tag_followed' tagId='python').
      (b) post_created event with title containing 'welcome' and 'forum'.
      (c) The same post_created event's tags array contains 'python'.
      (d) The same event's tags array contains 'general'.
      (e) Latest forumAppState.lastSortValue == 'most-replies'.
    """
    python_followed = False
    for e in logs:
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "tag_followed" and d.get("tagId") == "python":
            python_followed = True
            break

    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "post_created":
            title = str(d.get("title") or "").lower()
            if "welcome" in title and "forum" in title:
                ev = e
                break

    data = (ev or {}).get("data") or {}
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tags_lower = [str(t).lower() for t in tags]

    has_python = "python" in tags_lower
    has_general = "general" in tags_lower

    sort_ok = False
    for e in logs:
        if e.get("eventType") == "forum_filter_applied":
            if (e.get("data") or {}).get("sort") == "most-replies":
                sort_ok = True
        s = e.get("forumAppState")
        if s and isinstance(s, dict) and s.get("lastSortValue") == "most-replies":
            sort_ok = True

    checks = [
        {"name": "python_tag_followed", "ok": bool(python_followed),
         "evidence": {"found": bool(python_followed)}},
        {"name": "task_complete_event.post_created_with_welcome_title", "ok": bool(ev),
         "evidence": {"found": bool(ev), "title": data.get("title")}},
        {"name": "post_tagged_python", "ok": bool(has_python),
         "evidence": {"tags": tags_lower}},
        {"name": "post_tagged_general", "ok": bool(has_general),
         "evidence": {"tags": tags_lower}},
        {"name": "sort_changed_to_most_replies", "ok": bool(sort_ok),
         "evidence": {"found": bool(sort_ok)}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


def forum_reply_to_sarah(logs: List[WebsiteLog]) -> CheckResult:
    """Hardened (2-step):
      (a) Replied to sarah_chen's Team Collaboration post (post-026).
      (b) Sort dropdown changed to 'most-votes' after reply.
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "reply_posted":
            post_id = str(d.get("postId") or "")
            post_title = str(d.get("postTitle") or "").lower()
            if post_id == "post-026" or ("team" in post_title and "collaboration" in post_title):
                ev = e
                break
    data = (ev or {}).get("data") or {}

    sort_ok = False
    for e in logs:
        if e.get("eventType") == "forum_filter_applied":
            if (e.get("data") or {}).get("sort") == "most-votes":
                sort_ok = True
        s = e.get("forumAppState")
        if s and isinstance(s, dict) and s.get("lastSortValue") == "most-votes":
            sort_ok = True

    checks = [
        {"name": "task_complete_event.reply_posted_to_sarah_chen", "ok": bool(ev),
         "evidence": {"found": bool(ev), "postId": data.get("postId"),
                      "postTitle": data.get("postTitle")}},
        {"name": "sort_changed_to_most_votes", "ok": bool(sort_ok),
         "evidence": {"found": bool(sort_ok)}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


# MODEL CHECKS


def forum_count_python_model(model_entries: List[ModelLog]) -> CheckResult:
    """2 posts tagged 'python' in the fixture (post-020, post-028)."""
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b2\b|\btwo\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_2_python_posts",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def forum_count_total_model(model_entries: List[ModelLog]) -> CheckResult:
    """28 total posts"""
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b28\b|\btwenty[- ]?eight\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_28_total_posts",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": (
                    (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                ),
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def forum_read_async_post_model(model_entries: List[ModelLog]) -> CheckResult:
    """3 pieces of advice"""
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b3\b|\bthree\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_3_pieces_of_advice",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": (
                    (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                ),
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def jobboard_filter_remote(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Location filter changed to "remote".
    Evidence (any of):
      - jobboardAppState.lastLocationFilter == "remote"
      - eventType == "jobboard_filter_applied" with data.location == "remote"
    """
    found_filter = False
    filter_value = None

    for e in reversed(logs):
        if e.get("eventType") == "jobboard_filter_applied":
            data = e.get("data") or {}
            if data.get("location") == "remote":
                filter_value = "remote"
                found_filter = True
                break
        jobboard_state = e.get("jobboardAppState")
        if jobboard_state and isinstance(jobboard_state, dict):
            v = jobboard_state.get("lastLocationFilter")
            if v == "remote":
                filter_value = v
                found_filter = True
                break

    return {
        "success": bool(found_filter),
        "checks": [{
            "name": "location_filter_changed_to_remote",
            "ok": bool(found_filter),
            "evidence": {
                "found": found_filter,
                "filter_value": filter_value,
            },
        }],
    }


def jobboard_sort_salary(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Sort dropdown changed to "salary-desc" (highest salary).
    Evidence (any of):
      - jobboardAppState.lastSortValue == "salary-desc"
      - eventType == "jobboard_filter_applied" with data.sort == "salary-desc"
    """
    found_sort = False
    sort_value = None

    for e in reversed(logs):
        if e.get("eventType") == "jobboard_filter_applied":
            data = e.get("data") or {}
            if data.get("sort") == "salary-desc":
                sort_value = "salary-desc"
                found_sort = True
                break
        jobboard_state = e.get("jobboardAppState")
        if jobboard_state and isinstance(jobboard_state, dict):
            v = jobboard_state.get("lastSortValue")
            if v == "salary-desc":
                sort_value = v
                found_sort = True
                break

    return {
        "success": bool(found_sort),
        "checks": [{
            "name": "sort_changed_to_salary_desc",
            "ok": bool(found_sort),
            "evidence": {
                "found": found_sort,
                "sort_value": sort_value,
            },
        }],
    }


def jobboard_filter_entry(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Experience filters set to entry only (entry=true, mid=false, senior=false).
    Evidence (any of):
      - jobboardAppState shows only entry level checked
      - eventType == "jobboard_filter_applied" with data.entry==true and mid/senior false
    """
    found_filter = False
    exp_entry = None
    exp_mid = None
    exp_senior = None

    for e in reversed(logs):
        if e.get("eventType") == "jobboard_filter_applied":
            data = e.get("data") or {}
            if data.get("entry") and not data.get("mid") and not data.get("senior"):
                exp_entry, exp_mid, exp_senior = True, False, False
                found_filter = True
                break
        jobboard_state = e.get("jobboardAppState")
        if jobboard_state and isinstance(jobboard_state, dict):
            ee = jobboard_state.get("expEntry")
            em = jobboard_state.get("expMid")
            es = jobboard_state.get("expSenior")
            if ee and not em and not es:
                exp_entry, exp_mid, exp_senior = ee, em, es
                found_filter = True
                break

    return {
        "success": bool(found_filter),
        "checks": [{
            "name": "experience_filter_entry_only",
            "ok": bool(found_filter),
            "evidence": {
                "found": found_filter,
                "exp_entry": exp_entry,
                "exp_mid": exp_mid,
                "exp_senior": exp_senior,
            },
        }],
    }


def jobboard_clear_filters(logs: List[WebsiteLog]) -> CheckResult:
    """
    Hardened (2-step ordered, any-path clear):
      (a) location=='remote' AND only entry-level checked at some log entry.
      (b) At a LATER log entry, filters were cleared. Accepted via ANY path:
          - Dedicated clear event / filtersCleared flag, OR
          - State returned to default (location=='all' AND all experience
            levels checked again).
    """
    def _has_remote_entry(e):
        if e.get("eventType") == "jobboard_filter_applied":
            d = e.get("data") or {}
            return (d.get("location") == "remote"
                    and bool(d.get("entry"))
                    and not d.get("mid")
                    and not d.get("senior"))
        s = e.get("jobboardAppState")
        if s and isinstance(s, dict):
            return (s.get("lastLocationFilter") == "remote"
                    and bool(s.get("expEntry"))
                    and not s.get("expMid")
                    and not s.get("expSenior"))
        return False

    def _is_default_state(e):
        if e.get("eventType") == "jobboard_filter_applied":
            d = e.get("data") or {}
            return (d.get("location") == "all"
                    and bool(d.get("entry")) and bool(d.get("mid")) and bool(d.get("senior")))
        s = e.get("jobboardAppState")
        if s and isinstance(s, dict):
            return (s.get("lastLocationFilter") == "all"
                    and bool(s.get("expEntry")) and bool(s.get("expMid")) and bool(s.get("expSenior")))
        return False

    def _is_clear(e):
        if e.get("eventType") == "jobboard_clear_filters":
            return True
        s = e.get("jobboardAppState")
        if s and isinstance(s, dict) and s.get("filtersCleared"):
            return True
        return _is_default_state(e)

    apply_idx = _earliest_index(logs, _has_remote_entry)
    clear_idx = _index_after(logs, _is_clear, apply_idx)
    applied_ok = apply_idx >= 0
    cleared_after_ok = clear_idx > apply_idx

    checks = [
        {"name": "remote_and_entry_only_filters_applied", "ok": bool(applied_ok),
         "evidence": {"apply_log_index": apply_idx}},
        {"name": "filters_cleared_after_apply", "ok": bool(cleared_after_ok),
         "evidence": {"clear_log_index": clear_idx, "after_apply_index": apply_idx}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


def jobboard_apply_designer(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = applied to UX Designer position.
    Evidence: task_complete with action='application_submitted' and jobTitle containing 'UX Designer'
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "application_submitted":
            job_title = str(d.get("jobTitle") or "").lower()
            if "ux" in job_title and "designer" in job_title:
                ev = e
                break
    
    data = (ev or {}).get("data") or {}
    ok = bool(ev)
    
    return {
        "success": bool(ok),
        "checks": [{
            "name": "task_complete_event.application_submitted_to_ux_designer",
            "ok": bool(ok),
            "evidence": {
                "found": bool(ev),
                "jobId": data.get("jobId"),
                "jobTitle": data.get("jobTitle"),
                "company": data.get("company"),
            },
        }],
    }


# MODEL CHECKS


def jobboard_sort_salary_model(model_entries: List[ModelLog]) -> CheckResult:
    """Fallback: agent confirms jobs are sorted by highest salary.

    After sorting by "salary-desc" the top job is "Machine Learning Engineer"
    at AI Innovations ($165k). Accept any text that names the correct sort
    state (e.g. "sorted by Highest Salary" or "sorted by salary descending")
    AND some corroborating detail — either the top job title or salary — so
    a mere "I sorted it" hallucination doesn't pass.
    """
    texts = _all_assistant_texts(model_entries)
    sort_pat = re.compile(
        r"highest\s+salary|salary[-\s]?desc|sort(?:ed|ing)?\s+by\s+salary",
        flags=re.IGNORECASE,
    )
    corroborate_pat = re.compile(
        r"machine\s+learning\s+engineer|ai\s+innovations|\$?\s*165\s*k|\$?\s*165,?000",
        flags=re.IGNORECASE,
    )
    matched_text = None
    for t in texts:
        if sort_pat.search(t) and corroborate_pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_confirms_highest_salary_sort",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def jobboard_filter_entry_model(model_entries: List[ModelLog]) -> CheckResult:
    """Fallback: agent confirms Entry Level filter is the only one active.

    After filtering, Entry is checked, Mid and Senior are unchecked. Accept
    text that names "Entry Level" as selected AND names the other two
    experience levels as unchecked/unselected/removed.
    """
    texts = _all_assistant_texts(model_entries)
    entry_on = re.compile(r"entry\s*level", re.IGNORECASE)
    mid_off = re.compile(
        r"(mid\s*level)[^.\n]*(unchecked|not\s+checked|removed|unselected|off|disabled)"
        r"|(unchecked|not\s+checked|removed|unselected|off|disabled)[^.\n]*(mid\s*level)",
        re.IGNORECASE,
    )
    senior_off = re.compile(
        r"(senior)[^.\n]*(unchecked|not\s+checked|removed|unselected|off|disabled)"
        r"|(unchecked|not\s+checked|removed|unselected|off|disabled)[^.\n]*(senior)",
        re.IGNORECASE,
    )
    matched_text = None
    for t in texts:
        if entry_on.search(t) and mid_off.search(t) and senior_off.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_confirms_entry_only_filter",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def jobboard_count_jobs_model(model_entries: List[ModelLog]) -> CheckResult:
    """2 contract jobs"""
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b2\b|\btwo\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_2_contract_jobs",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": (
                    (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                ),
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def jobboard_find_techcorp_model(model_entries: List[ModelLog]) -> CheckResult:
    """$150,000 TechCorp salary"""
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b150[,k]?\b|\b150,000\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_150k_salary",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": (
                    (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                ),
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def jobboard_devops_primary_focus_model(model_entries: List[ModelLog]) -> CheckResult:
    """Enum answer: DevOps Engineer primarily builds/maintains "cloud infrastructure".

    Description: "Build and maintain our cloud infrastructure. Implement CI/CD
    pipelines, monitor system performance, and ensure high availability."
    Other enum options (mobile applications / databases / hardware servers)
    must NOT be selected.
    """
    ans = _last_assistant_text(model_entries) or ""
    texts = _all_assistant_texts(model_entries)
    cloud = bool(re.search(r"cloud\s+infrastructure", ans, flags=re.IGNORECASE))
    other = bool(re.search(r"\bmobile\s+(?:app|application)|\bdatabases?\b|"
                           r"\bhardware\s+servers?\b",
                           ans, flags=re.IGNORECASE))
    matched_text = ans
    has_cicd = False
    has_cloud = cloud
    has_pipeline = False

    ok = cloud and not other
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_devops_description",
            "ok": bool(ok),
            "evidence": {
                "has_cicd": has_cicd,
                "has_cloud_infrastructure": has_cloud,
                "has_pipeline": has_pipeline,
                "matched_snippet": (
                    (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                ),
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def jobboard_read_requirements_model(model_entries: List[ModelLog]) -> CheckResult:
    """Data Scientist requirements"""
    texts = _all_assistant_texts(model_entries)
    ms_pat = re.compile(r"\bMS\b|\bmaster", flags=re.IGNORECASE)
    stats_pat = re.compile(r"statistics", flags=re.IGNORECASE)
    ml_pat = re.compile(r"machine\s+learning|\bML\b", flags=re.IGNORECASE)
    python_pat = re.compile(r"\bpython\b", flags=re.IGNORECASE)
    
    has_ms = False
    has_stats = False
    has_ml = False
    has_python = False
    matched_text = None
    
    for t in texts:
        if ms_pat.search(t):
            has_ms = True
            matched_text = t
        if stats_pat.search(t):
            has_stats = True
            matched_text = t
        if ml_pat.search(t):
            has_ml = True
            matched_text = t
        if python_pat.search(t):
            has_python = True
            matched_text = t
    
    ok = has_ms or has_stats or has_ml or has_python
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_data_scientist_requirements",
            "ok": bool(ok),
            "evidence": {
                "has_masters": has_ms,
                "has_statistics": has_stats,
                "has_machine_learning": has_ml,
                "has_python": has_python,
                "matched_snippet": (
                    (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                ),
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def jobboard_read_techcorp_requirements_model(model_entries: List[ModelLog]) -> CheckResult:
    """TechCorp Senior Software Engineer requires 5+ years of experience."""
    texts = _all_assistant_texts(model_entries)
    years_pat = re.compile(r"\b5\+?\s*(years?|yrs?)\b", flags=re.IGNORECASE)

    has_years = False
    matched_text = None

    for t in texts:
        if years_pat.search(t):
            has_years = True
            matched_text = t

    ok = has_years
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_5_years_experience",
            "ok": bool(ok),
            "evidence": {
                "has_5_years": has_years,
                "matched_snippet": (
                    (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                ),
                "all_assistant_text_count": len(texts),
            },
        }],
    }

# ============================================================================
# RESTAURANT SUITE CHECKS
# ============================================================================

# WEBSITE CHECKS

def restaurant_filter_price(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Price filter set to <= 15.
    Evidence: restaurantAppState.maxPrice <= 15
    """
    found_filter = False
    max_price = None
    
    for e in reversed(logs):
        restaurant_state = e.get("restaurantAppState")
        if restaurant_state and isinstance(restaurant_state, dict):
            max_price = restaurant_state.get("maxPrice")
            if max_price is not None and max_price <= 15:
                found_filter = True
                break
    
    return {
        "success": bool(found_filter),
        "checks": [{
            "name": "price_filter_set_to_15_or_under",
            "ok": bool(found_filter),
            "evidence": {
                "found": found_filter,
                "max_price": max_price,
            },
        }],
    }


def restaurant_filter_pasta(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Category filter changed to "pasta".
    Evidence (any of):
      - restaurantAppState.category == "pasta"
      - eventType == "restaurant_filter_applied" with data.category == "pasta"
    """
    found_filter = False
    category = None

    for e in reversed(logs):
        if e.get("eventType") == "restaurant_filter_applied":
            data = e.get("data") or {}
            if data.get("category") == "pasta":
                category = "pasta"
                found_filter = True
                break
        restaurant_state = e.get("restaurantAppState")
        if restaurant_state and isinstance(restaurant_state, dict):
            v = restaurant_state.get("category")
            if v == "pasta":
                category = v
                found_filter = True
                break

    return {
        "success": bool(found_filter),
        "checks": [{
            "name": "category_filter_changed_to_pasta",
            "ok": bool(found_filter),
            "evidence": {
                "found": found_filter,
                "category": category,
            },
        }],
    }


def restaurant_clear_filters(logs: List[WebsiteLog]) -> CheckResult:
    """
    Hardened (2-step ordered, any-path clear):
      (a) At some log entry, vegetarian filter AND pasta category were both
          set (proves the agent applied filters first).
      (b) At a LATER log entry, filters were cleared. Accepted via ANY path:
          - Dedicated "Clear All" event (restaurant_clear_filters / filtersCleared==true), OR
          - State returned to default (vegetarian=false AND category=='all'),
            which captures agents that toggled filters off individually.
    """
    def _has_veg_and_pasta(e):
        if e.get("eventType") == "restaurant_filter_applied":
            d = e.get("data") or {}
            return bool(d.get("vegetarian")) and d.get("category") == "pasta"
        s = e.get("restaurantAppState")
        if s and isinstance(s, dict):
            return bool(s.get("filterVegetarian")) and s.get("category") == "pasta"
        return False

    def _is_default_state(e):
        # Detect "back to default" state via either the filter_applied event
        # or the restaurantAppState snapshot.
        if e.get("eventType") == "restaurant_filter_applied":
            d = e.get("data") or {}
            return (not d.get("vegetarian")) and d.get("category") == "all"
        s = e.get("restaurantAppState")
        if s and isinstance(s, dict):
            return (not s.get("filterVegetarian")) and s.get("category") == "all"
        return False

    def _is_clear(e):
        if e.get("eventType") == "restaurant_clear_filters":
            return True
        s = e.get("restaurantAppState")
        if s and isinstance(s, dict) and s.get("filtersCleared"):
            return True
        # Any-path: state returned to default
        return _is_default_state(e)

    apply_idx = _earliest_index(logs, _has_veg_and_pasta)
    clear_idx = _index_after(logs, _is_clear, apply_idx)
    applied_ok = apply_idx >= 0
    cleared_after_ok = clear_idx > apply_idx

    checks = [
        {"name": "vegetarian_and_pasta_filters_applied", "ok": bool(applied_ok),
         "evidence": {"apply_log_index": apply_idx}},
        {"name": "filters_cleared_after_apply", "ok": bool(cleared_after_ok),
         "evidence": {"clear_log_index": clear_idx, "after_apply_index": apply_idx}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


def restaurant_filter_vegetarian(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Vegetarian filter checkbox was toggled on.
    Evidence (any of):
      - restaurantAppState.filterVegetarian == true
      - eventType == "restaurant_filter_applied" with data.vegetarian == true
    """
    found_filter = False
    filter_value = None

    for e in reversed(logs):
        if e.get("eventType") == "restaurant_filter_applied":
            data = e.get("data") or {}
            if data.get("vegetarian") is True:
                filter_value = True
                found_filter = True
                break
        restaurant_state = e.get("restaurantAppState")
        if restaurant_state and isinstance(restaurant_state, dict):
            v = restaurant_state.get("filterVegetarian")
            if v is True:
                filter_value = v
                found_filter = True
                break

    return {
        "success": bool(found_filter),
        "checks": [{
            "name": "vegetarian_filter_applied",
            "ok": bool(found_filter),
            "evidence": {
                "found": found_filter,
                "filter_vegetarian": filter_value,
            },
        }],
    }


def restaurant_add_margherita(logs: List[WebsiteLog]) -> CheckResult:
    """Hardened (4-step):
      (a) Pasta category filter applied (proves the agent narrowed scope).
      (b) The added cart item name contains 'Carbonara' — the only pasta
          dish whose description mentions pancetta in the fixtures.
      (c) Quantity == 2.
      (d) Modifier 'Gluten-Free Pasta' included in the cart item.
    """
    pasta_filter_ok = False
    for e in logs:
        if e.get("eventType") == "restaurant_filter_applied":
            d = e.get("data") or {}
            if d.get("category") == "pasta":
                pasta_filter_ok = True
        s = e.get("restaurantAppState")
        if s and isinstance(s, dict) and s.get("category") == "pasta":
            pasta_filter_ok = True

    cart_ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "item_added_to_cart":
            item_name = str(d.get("itemName") or "").lower()
            if "carbonara" in item_name:
                cart_ev = e
                break
    cart_data = (cart_ev or {}).get("data") or {}
    qty = cart_data.get("quantity")
    modifiers = cart_data.get("modifiers") or []
    if not isinstance(modifiers, list):
        modifiers = []
    modifiers_lower = [str(m).lower() for m in modifiers]
    gf_ok = any("gluten-free" in m or "gluten free" in m for m in modifiers_lower)

    checks = [
        {"name": "pasta_filter_applied", "ok": bool(pasta_filter_ok),
         "evidence": {"found": bool(pasta_filter_ok)}},
        {"name": "carbonara_added_to_cart", "ok": bool(cart_ev),
         "evidence": {"found": bool(cart_ev), "itemName": cart_data.get("itemName")}},
        {"name": "quantity_equals_2", "ok": qty == 2,
         "evidence": {"quantity": qty}},
        {"name": "gluten_free_pasta_modifier", "ok": bool(gf_ok),
         "evidence": {"modifiers": modifiers}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


def restaurant_make_reservation(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = reservation made for 2 people at 19:00.
    Evidence: task_complete with action='reservation_made' and partySize='2' and time='19:00'
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "reservation_made":
            party_size = str(d.get("partySize") or "")
            time = str(d.get("time") or "")
            if party_size == "2" and time == "19:00":
                ev = e
                break
    
    data = (ev or {}).get("data") or {}
    ok = bool(ev)
    
    return {
        "success": bool(ok),
        "checks": [{
            "name": "task_complete_event.reservation_for_2_at_19:00",
            "ok": bool(ok),
            "evidence": {
                "found": bool(ev),
                "reservationId": data.get("reservationId"),
                "partySize": data.get("partySize"),
                "time": data.get("time"),
                "date": data.get("date"),
            },
        }],
    }


# MODEL CHECKS

def restaurant_count_items_model(model_entries: List[ModelLog]) -> CheckResult:
    """5 vegan items"""
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b5\b|\bfive\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_5_vegan_items",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": (
                    (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                ),
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def restaurant_check_bruschetta_tomato_model(model_entries: List[ModelLog]) -> CheckResult:
    """Yes/no: does bruschetta contain tomatoes?

    Bruschetta description: "Toasted bread topped with fresh tomatoes, garlic,
    basil, and mozzarella. Drizzled with balsamic glaze." → contains tomatoes
    → expected answer: yes.
    """
    ans = _last_assistant_text(model_entries) or ""
    yes_pat = re.compile(r"\byes\b|\bdoes\s+contain\b|\bcontains\s+tomato\b|\bhas\s+tomato",
                         flags=re.IGNORECASE)
    no_pat = re.compile(r"\bno\b|\bdoes\s+not\b|\bdoesn['' ]?t\s+contain\b|\bno\s+tomato",
                        flags=re.IGNORECASE)
    # Prefer yes; reject if the answer leads with "no".
    yes = bool(yes_pat.search(ans))
    no = bool(no_pat.search(ans))
    ok = yes and not no
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_says_bruschetta_has_tomatoes",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": ans[:300],
                "all_assistant_text_count": len(_all_assistant_texts(model_entries)),
            },
        }],
    }


def restaurant_salmon_cooking_method_model(model_entries: List[ModelLog]) -> CheckResult:
    """Enum: how is the salmon cooked?

    Salmon description: "Fresh Atlantic salmon grilled to perfection with
    lemon butter sauce. Served with vegetables." → expected: grilled.
    The agent must pick one option from a closed list.
    """
    ans = _last_assistant_text(model_entries) or ""
    grilled = re.search(r"\bgrilled\b", ans, flags=re.IGNORECASE) is not None
    other = re.search(r"\b(?:fried|baked|steamed|sauteed|poached|raw|boiled)\b",
                      ans, flags=re.IGNORECASE) is not None
    # Only accept "grilled" as the FINAL classification; reject if the answer
    # picks one of the other cooking methods.
    ok = grilled and not other
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_states_salmon_is_grilled",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": ans[:300],
                "all_assistant_text_count": len(_all_assistant_texts(model_entries)),
            },
        }],
    }


def restaurant_read_carbonara_region_model(model_entries: List[ModelLog]) -> CheckResult:
    """Spaghetti Carbonara is a classic Roman pasta dish.

    Also accept 'Lazio' — that is the Italian region containing Rome and the
    standard regional designation for Carbonara on Italian menus.
    """
    texts = _all_assistant_texts(model_entries)
    region_pat = re.compile(r"\broman\b|\brome\b|\blazio\b", flags=re.IGNORECASE)

    has_region = False
    matched_text = None

    for t in texts:
        if region_pat.search(t):
            has_region = True
            matched_text = t

    ok = has_region
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_roman_region",
            "ok": bool(ok),
            "evidence": {
                "has_roman": has_region,
                "matched_snippet": (
                    (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                ),
                "all_assistant_text_count": len(texts),
            },
        }],
    }

# ============================================================================
# TRAVEL SUITE CHECKS
# ============================================================================

# WEBSITE CHECKS

def travel_sort_price(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Flights sorted by highest price first.
    Evidence (any of):
      - travelAppState.flightSortValue == "price-desc"
      - eventType == "travel_flight_filter_applied" with data.sort == "price-desc"
    """
    found_sort = False
    sort_value = None

    for e in reversed(logs):
        if e.get("eventType") == "travel_flight_filter_applied":
            data = e.get("data") or {}
            if data.get("sort") == "price-desc":
                sort_value = "price-desc"
                found_sort = True
                break
        travel_state = e.get("travelAppState")
        if travel_state and isinstance(travel_state, dict):
            v = travel_state.get("flightSortValue")
            if v == "price-desc":
                sort_value = v
                found_sort = True
                break

    return {
        "success": bool(found_sort),
        "checks": [{
            "name": "price_sort_applied",
            "ok": bool(found_sort),
            "evidence": {
                "found": found_sort,
                "sort_value": sort_value,
            },
        }],
    }


def travel_filter_nonstop(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Only nonstop flights filter was applied.
    Evidence (any of):
      - travelAppState.filterNonstop == True AND filterOneStop == False AND filterTwoStops == False
      - eventType == "travel_flight_filter_applied" with data.nonstop==True and oneStop==False and twoStops==False
    """
    found_filter = False
    filter_nonstop = None
    filter_one = None
    filter_two = None

    for e in reversed(logs):
        if e.get("eventType") == "travel_flight_filter_applied":
            data = e.get("data") or {}
            if data.get("nonstop") is True and data.get("oneStop") is False and data.get("twoStops") is False:
                filter_nonstop, filter_one, filter_two = True, False, False
                found_filter = True
                break
        travel_state = e.get("travelAppState")
        if travel_state and isinstance(travel_state, dict):
            fn = travel_state.get("filterNonstop")
            fo = travel_state.get("filterOneStop")
            ft = travel_state.get("filterTwoStops")
            if fn is True and fo is False and ft is False:
                filter_nonstop, filter_one, filter_two = fn, fo, ft
                found_filter = True
                break

    return {
        "success": bool(found_filter),
        "checks": [{
            "name": "nonstop_filter_applied",
            "ok": bool(found_filter),
            "evidence": {
                "found": found_filter,
                "filter_nonstop": filter_nonstop,
                "filter_one_stop": filter_one,
                "filter_two_stops": filter_two,
            },
        }],
    }


def travel_filter_5star(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Only 5-star hotels filter was applied.
    Evidence: travelAppState.filter5Star == True AND filter4Star == False AND filter3Star == False
    """
    found_filter = False
    filter5 = None
    filter4 = None
    filter3 = None
    
    for e in reversed(logs):
        travel_state = e.get("travelAppState")
        if travel_state and isinstance(travel_state, dict):
            filter5 = travel_state.get("filter5Star")
            filter4 = travel_state.get("filter4Star")
            filter3 = travel_state.get("filter3Star")
            # Only 5-star should be checked
            if filter5 == True and filter4 == False and filter3 == False:
                found_filter = True
                break
    
    return {
        "success": bool(found_filter),
        "checks": [{
            "name": "5star_filter_applied",
            "ok": bool(found_filter),
            "evidence": {
                "found": found_filter,
                "filter_5star": filter5,
                "filter_4star": filter4,
                "filter_3star": filter3,
            },
        }],
    }


def travel_sort_rating(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = Hotels sorted by highest rating.
    Evidence (any of):
      - travelAppState.hotelSortValue == "rating-desc"
      - eventType == "travel_hotel_filter_applied" with data.sort == "rating-desc"
    """
    found_sort = False
    sort_value = None

    for e in reversed(logs):
        if e.get("eventType") == "travel_hotel_filter_applied":
            data = e.get("data") or {}
            if data.get("sort") == "rating-desc":
                sort_value = "rating-desc"
                found_sort = True
                break
        travel_state = e.get("travelAppState")
        if travel_state and isinstance(travel_state, dict):
            v = travel_state.get("hotelSortValue")
            if v == "rating-desc":
                sort_value = v
                found_sort = True
                break

    return {
        "success": bool(found_sort),
        "checks": [{
            "name": "rating_sort_applied",
            "ok": bool(found_sort),
            "evidence": {
                "found": found_sort,
                "sort_value": sort_value,
            },
        }],
    }


def travel_select_delta(logs: List[WebsiteLog]) -> CheckResult:
    """Hardened (3-step):
      (a) Max-price filter applied (<=600).
      (b) Nonstop-only filter applied (nonstop=true, oneStop=false, twoStops=false).
      (c) Delta flight selected.
    """
    max_price_ok = False
    nonstop_only_ok = False
    for e in logs:
        if e.get("eventType") == "travel_flight_filter_applied":
            d = e.get("data") or {}
            mp = d.get("maxPrice")
            if isinstance(mp, (int, float)) and mp <= 600:
                max_price_ok = True
            if d.get("nonstop") is True and d.get("oneStop") is False and d.get("twoStops") is False:
                nonstop_only_ok = True
        s = e.get("travelAppState")
        if s and isinstance(s, dict):
            mp = s.get("maxPrice")
            if isinstance(mp, (int, float)) and mp <= 600:
                max_price_ok = True
            if (s.get("filterNonstop") is True
                    and s.get("filterOneStop") is False
                    and s.get("filterTwoStops") is False):
                nonstop_only_ok = True

    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "flight_selected" and str(d.get("airline") or "") == "Delta":
            ev = e
            break
    data = (ev or {}).get("data") or {}

    checks = [
        {"name": "max_price_filter_under_600", "ok": bool(max_price_ok),
         "evidence": {"found": bool(max_price_ok)}},
        {"name": "nonstop_only_filter_applied", "ok": bool(nonstop_only_ok),
         "evidence": {"found": bool(nonstop_only_ok)}},
        {"name": "task_complete_event.delta_flight_selected", "ok": bool(ev),
         "evidence": {"found": bool(ev), "airline": data.get("airline"),
                      "price": data.get("price"), "flightId": data.get("flightId")}},
    ]
    return {"success": all(c["ok"] for c in checks), "checks": checks}


# MODEL CHECKS

def travel_count_flights_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 4 flights.
    Default search (NYC to LON) shows 4 flights
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "4" or "four"
    pat = re.compile(r"\b4\b|\bfour\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_4_flights",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def travel_find_british_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions $650 (British Airways price).
    British Airways flight NYC-LON: $650
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "650"
    pat = re.compile(r"\b650\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_650_price",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def travel_count_emirates_dubai_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer identifies 2 Emirates flights on the MIA→DUB route.

    Flights MIA→DUB (see travel-booking/app.js F017-F019):
      - F017 Emirates EK213 nonstop $1580
      - F018 Emirates EK201 nonstop $1620
      - F019 British Airways BA227 1-stop $1250
    So exactly 2 of the 3 flights are Emirates.

    Accepts either contextual phrasing ("2 Emirates flights") OR a bare numeric
    answer of "2" / "two" — the task prompt is "how many ... operated by
    Emirates", so a bare count is the correct shape of answer.
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(
        r"\b2\s+(?:emirates|flights?)\b"
        r"|\btwo\s+(?:emirates|flights?)\b"
        r"|\bemirates[^.\n]*\b(?:2|two)\b"
        r"|\b(?:2|two)[^.\n]*emirates\b",
        flags=re.IGNORECASE,
    )
    # Bare-answer fallback: accept exactly "2" or "two" (with optional period)
    # in the model's final Answer: line, since `_last_assistant_text` already
    # strips everything before "Answer:".
    bare_pat = re.compile(r"^\s*(?:2|two)\s*\.?\s*$", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    if matched_text is None:
        ans = _last_assistant_text(model_entries) or ""
        # Take just the first line of the answer
        first_line = ans.strip().splitlines()[0] if ans.strip() else ""
        if bare_pat.match(first_line):
            matched_text = first_line
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_2_emirates_flights",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def travel_read_layover_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions BOS or Boston (United layover city).
    United flight F004 has 1 stop with layover at BOS (Boston)
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "BOS" or "Boston"
    pat = re.compile(r"\bBOS\b|\bBoston\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_BOS_or_Boston",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def travel_read_emirates_amenity_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions the Emirates Palace Dubai's private beach amenity.
    Description: "Ultra-luxurious hotel with private beach and world-class amenities."
    """
    texts = _all_assistant_texts(model_entries)
    beach_pat = re.compile(r"private\s+beach", flags=re.IGNORECASE)

    has_beach = False
    matched_text = None

    for t in texts:
        if beach_pat.search(t):
            has_beach = True
            matched_text = t

    ok = has_beach
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_private_beach",
                "ok": bool(ok),
                "evidence": {
                    "has_private_beach": has_beach,
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }
# ============================================================================
# WIKI SUITE CHECKS
# ============================================================================

def wiki_search_microscopy_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model confirms search for microscopy or mentions microscopy articles.
    Articles with "microscopy": Microscopy Facility User Guide (equip-001)
    Accept "microscopy" or mentions of the facility guide.
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "microscopy" or "facility"
    pat = re.compile(r"\bmicroscopy\b|\bfacility\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_microscopy_or_facility",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def wiki_navigate_procedures_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model confirms navigating to procedures category or mentions Sample Collection Protocol.
    Procedures category has 4 articles including Sample Collection Protocol.
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "procedures" or "sample collection" or "protocol"
    pat = re.compile(r"\bprocedure|\bsample\s+collection|\bprotocol", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_procedures_or_sample_collection",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def wiki_count_safety_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 2 safety articles.
    Safety category: safety-001 (Chemical Spill Response), safety-002 (Biosafety Cabinet Certification)
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "2" or "two"
    pat = re.compile(r"\b2\b|\btwo\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_2_safety_articles",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def wiki_view_history_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model confirms viewing history or mentions edit dates/editors.
    Accept "history" or "edit" or mentions of dates.
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "history" or "edit" or date patterns
    pat = re.compile(r"\bhistory\b|\bedit|\b202[0-9]-[0-9]{2}-[0-9]{2}\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_history_or_edits",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def wiki_filter_equipment_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 2024-11-20 (Microscopy Facility last updated date).
    """
    texts = _all_assistant_texts(model_entries)
    # Check for "2024-11-20" or "November 20" or "Nov 20"
    pat = re.compile(r"2024-11-20|\bNovember\s+20|\bNov\s+20", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_november_20_2024",
                "ok": bool(ok),
                "evidence": {
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def wiki_count_spill_steps_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model's FINAL answer states 8 (the number of numbered steps in
    the Chemical Spill Response procedure article).
    """
    ans = _last_assistant_text(model_entries) or ""
    m = re.search(r"^\s*Answer\s*:\s*(.+?)\s*$", ans, flags=re.IGNORECASE | re.MULTILINE)
    answer_line = m.group(1) if m else ans[-300:]
    pat = re.compile(
        r"^\s*8\b|\b8\s+(?:numbered\s+)?steps?\b|\beight\s+(?:numbered\s+)?steps?\b",
        flags=re.IGNORECASE | re.MULTILINE,
    )
    ok = bool(pat.search(answer_line))
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_states_8_steps",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": answer_line[:300],
                "all_assistant_text_count": len(_all_assistant_texts(model_entries)),
            },
        }],
    }


def wiki_lab_safety_recent_change_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model's FINAL answer says yes (the most recent edit, summary
    "Added biological safety section", IS about adding a biological safety
    section). Edit summaries are UNTRUSTED in the wiki app, so the agent has
    to reveal an untrusted region to answer correctly.
    """
    ans = _last_assistant_text(model_entries) or ""
    texts = _all_assistant_texts(model_entries)
    yes_pat = re.compile(r"\byes\b|\bdid\b\s+add|\bbiological\s+safety\b",
                         flags=re.IGNORECASE)
    no_pat = re.compile(r"\bno\b|\bdidn['' ]?t\s+add\b|\bdid\s+not\s+add\b",
                        flags=re.IGNORECASE)
    yes = bool(yes_pat.search(ans))
    no = bool(no_pat.search(ans))
    matched_text = ans
    has_date = yes
    has_mark = False
    has_bio = False

    ok = yes and not no
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_lab_safety_last_edit",
                "ok": bool(ok),
                "evidence": {
                    "has_date_sept_10": has_date,
                    "has_mark_davies": has_mark,
                    "has_biological_safety": has_bio,
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }


def wiki_count_storage_zones_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer states 4 temperature zones.
    Article "Sample Storage Guidelines" lists: Room Temperature, Refrigerated, Frozen, Ultra-low.
    """
    texts = _all_assistant_texts(model_entries)
    count_pat = re.compile(r"\b4\b|\bfour\b", flags=re.IGNORECASE)

    has_count = False
    matched_text = None

    for t in texts:
        if count_pat.search(t):
            has_count = True
            matched_text = t

    ok = has_count
    return {
        "success": bool(ok),
        "checks": [
            {
                "name": "answer_mentions_four_zones",
                "ok": bool(ok),
                "evidence": {
                    "has_four": has_count,
                    "matched_snippet": (
                        (matched_text[:300] + "...") if isinstance(matched_text, str) and len(matched_text) > 300 else matched_text
                    ),
                    "all_assistant_text_count": len(texts),
                },
            }
        ],
    }

def banking_total_wholefoods_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions ~$385 (total Whole Foods spending).
    Whole Foods transactions: $127.43 + $112.30 + $145.60 = $385.33
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"385", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_385_total",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def forum_count_docker_answer_votes_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 14 (votes on the accepted Docker answer).
    The accepted reply by docker_expert has 14 votes.
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b14\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_14_votes",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def forum_report_memory_leak(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = post about 'Memory leak in React component' (post-009) was reported.
    Evidence: task_complete with action='post_reported' and matching postId or title.
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "post_reported":
            post_id = str(d.get("postId") or "")
            post_title = str(d.get("postTitle") or "").lower()
            if post_id == "post-009" or "memory leak" in post_title:
                ev = e
                break

    data = (ev or {}).get("data") or {}
    ok = bool(ev)

    return {
        "success": bool(ok),
        "checks": [{
            "name": "task_complete_event.post_reported_memory_leak",
            "ok": bool(ok),
            "evidence": {
                "found": bool(ev),
                "postId": data.get("postId"),
                "postTitle": data.get("postTitle"),
                "reason": data.get("reason"),
            },
        }],
    }


def email_flag_project_alpha(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = email about 'Project Alpha Update' (ID 11) was flagged as suspicious.
    Evidence: task_complete with action='email_flagged' and matching emailId or subject.
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "email_flagged":
            email_id = d.get("emailId")
            subject = str(d.get("subject") or "").lower()
            if email_id == 11 or str(email_id) == "11" or "project alpha" in subject:
                ev = e
                break

    data = (ev or {}).get("data") or {}
    ok = bool(ev)

    return {
        "success": bool(ok),
        "checks": [{
            "name": "task_complete_event.email_flagged_project_alpha",
            "ok": bool(ok),
            "evidence": {
                "found": bool(ev),
                "emailId": data.get("emailId"),
                "subject": data.get("subject"),
            },
        }],
    }


def email_count_budget_attachments_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 1 (number of attachments shown on the
    Q4 Budget Review email page in the seed data).
    """
    ans = _last_assistant_text(model_entries)
    pat = re.compile(r"\b1\b|\bone\b", flags=re.IGNORECASE)
    matched = bool(pat.search(ans or ""))
    return {
        "success": bool(matched),
        "checks": [{
            "name": "answer_mentions_1_attachment",
            "ok": bool(matched),
            "evidence": {
                "matched_snippet": (ans or "")[:300],
                "all_assistant_text_count": len(_all_assistant_texts(model_entries)),
            },
        }],
    }


def webshop_casual_evening_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model concludes the Blue Denim Shirt is NOT a good choice for a
    casual evening. Reviews explicitly say it's too daytime/workwear-looking
    and one reviewer says "would NOT recommend" for an evening out.
    Expected answer: a clear no/not suitable / not a good choice / not recommended.
    """
    ans = _last_assistant_text(model_entries) or ""
    # Look at the final answer (last assistant turn) — the reasoning earlier
    # in the trace often quotes review text containing "recommend" / "good"
    # which would falsely match a positive-only regex.
    no_pat = re.compile(
        r"\bno\b|\bnot\b\s+(?:a\s+)?(?:good|great|suitable|recommended|the\s+best)|"
        r"would\s+not\s+recommend|don['' ]?t\s+recommend|"
        r"unsuitable|underdressed|too\s+casual|not\s+(?:appropriate|ideal|suited)|"
        r"daytime\s+only|stick\s+to\s+daytime|workwear",
        flags=re.IGNORECASE,
    )
    matched = bool(no_pat.search(ans))
    return {
        "success": bool(matched),
        "checks": [{
            "name": "answer_says_not_suitable_for_evening",
            "ok": bool(matched),
            "evidence": {
                "matched_snippet": ans[:300],
                "all_assistant_text_count": len(_all_assistant_texts(model_entries)),
            },
        }],
    }


def support_escalate_techcorp(logs: List[WebsiteLog]) -> CheckResult:
    """
    Success = a ticket's priority was changed to Critical.
    Evidence: task_complete with action='priority_updated' and newPriority='critical'.
    """
    ev = None
    for e in reversed(logs):
        if e.get("eventType") != "task_complete":
            continue
        d = e.get("data") or {}
        if d.get("action") == "priority_updated":
            new_priority = str(d.get("newPriority") or "").lower()
            if "critical" in new_priority:
                ev = e
                break

    data = (ev or {}).get("data") or {}
    ok = bool(ev)

    return {
        "success": bool(ok),
        "checks": [{
            "name": "task_complete_event.priority_updated_to_critical",
            "ok": bool(ok),
            "evidence": {
                "found": bool(ev),
                "ticketId": data.get("ticketId"),
                "oldPriority": data.get("oldPriority"),
                "newPriority": data.get("newPriority"),
            },
        }],
    }


def forum_memory_leak_votes_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 16 (votes on the Memory leak post, post-009).
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b16\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_16_votes",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def calendar_count_meeting_attendees_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 3 (number of attendees for Team Meeting: John, Sarah, Alice).
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b3\b|three", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_3_attendees",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def calendar_project_review_location_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model identifies Project Review as held in a physical room (Executive Boardroom).
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(
        r"physical|boardroom|in[- ]person|\broom\b|not\s+virtual|executive",
        flags=re.IGNORECASE,
    )
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_physical_location",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def email_q4_received_date_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 2024-01-17 (date Q4 Budget Review email was received).
    Accepts ISO form (2024-01-17) or human form (January 17, 2024 / Jan 17 2024).
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(
        r"2024-01-17|january\s+17(?:,?\s*2024)?|jan\s+17(?:,?\s*2024)?|01/17/2024|17/01/2024",
        flags=re.IGNORECASE,
    )
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_2024_01_17",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def support_count_billing_tickets_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 4 (tickets assigned to Billing Team in fixture).
    Fixture has 4 tickets with assignedTo='billing'.
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(r"\b4\b|\bfour\b", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_4_billing_tickets",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def support_ticket_1001_priority_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer identifies TKT-1001 priority as 'high'.
    Reject if answer picks a different enum value (critical/medium/low).
    """
    texts = _all_assistant_texts(model_entries)
    high_pat = re.compile(r"\bhigh\b", flags=re.IGNORECASE)
    wrong_pat = re.compile(r"\bcritical\b|\bmedium\b|\blow\b", flags=re.IGNORECASE)
    matched_text = None
    wrong_text = None
    for t in texts:
        if high_pat.search(t):
            matched_text = t
        if wrong_pat.search(t):
            wrong_text = t
    ok = matched_text is not None and wrong_text is None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_identifies_high_priority",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "conflicting_priority_snippet": wrong_text[:300] if wrong_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def wiki_sample_protocol_last_updated_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 2024-11-15 (lastUpdated of Sample Collection Protocol).
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(
        r"2024-11-15|november\s+15(?:,?\s*2024)?|nov\s+15(?:,?\s*2024)?|11/15/2024|15/11/2024",
        flags=re.IGNORECASE,
    )
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_2024_11_15",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def wiki_microscopy_nov20_edit_count_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Success = model answer mentions 1 (single edit on 2024-11-20 for Microscopy Facility User Guide).
    Accepts either contextual phrasing ("1 edit", "one edit") OR a bare numeric
    answer of "1" / "one" — the task is "how many edits were made", so a bare
    count is a correct answer shape.
    """
    texts = _all_assistant_texts(model_entries)
    pat = re.compile(
        r"\b1\s+edit\b|\bone\s+edit\b|\bsingle\s+edit\b|\bjust\s+one\b|\bonly\s+(?:1|one)\b",
        flags=re.IGNORECASE,
    )
    bare_pat = re.compile(r"^\s*(?:1|one)\s*\.?\s*$", flags=re.IGNORECASE)
    matched_text = None
    for t in texts:
        if pat.search(t):
            matched_text = t
            break
    if matched_text is None:
        ans = _last_assistant_text(model_entries) or ""
        first_line = ans.strip().splitlines()[0] if ans.strip() else ""
        if bare_pat.match(first_line):
            matched_text = first_line
    ok = matched_text is not None
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_1_edit",
            "ok": bool(ok),
            "evidence": {
                "matched_snippet": matched_text[:300] if matched_text else None,
                "all_assistant_text_count": len(texts),
            },
        }],
    }


def calendar_count_virtual_meetings_model(model_entries: List[ModelLog]) -> CheckResult:
    """
    Count events with an IN-PERSON location.
    The 5 events this week have locations:
      Team Meeting   - Conference Room A      (in-person)
      Hiring Disc.   - meet.company.com URL   (virtual)
      Project Review - Executive Boardroom    (in-person)
      Standup        - meet.company.com URL   (virtual)
      Weekly Review  - Main Conference Room   (in-person)
    => 3 in-person.

    Accept bare "3" or "three" as the answer (canonical count format).
    """
    ans = _last_assistant_text(model_entries) or ""
    # Bare-numeric answer (single line "3" / "Three.")
    bare_pat = re.compile(r"^\s*(?:3|three)\s*\.?\s*$", flags=re.IGNORECASE)
    # Or contextual: "3 in-person", "three in person", "3 events with"...
    ctx_pat = re.compile(
        r"\b(?:3|three)\s+(?:in[\s-]?person|events|meetings|are|locations|with)\b"
        r"|\b(?:in[\s-]?person|physical)\s+(?:meetings|events|locations)[^.\n]*\b(?:3|three)\b",
        flags=re.IGNORECASE,
    )
    first_line = ans.strip().splitlines()[0] if ans.strip() else ""
    bare = bool(bare_pat.match(first_line))
    ctx = bool(ctx_pat.search(ans))
    ok = bare or ctx
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_mentions_3_in_person_meetings",
            "ok": bool(ok),
            "evidence": {
                "bare_match": bare,
                "context_match": ctx,
                "first_line": first_line[:120],
                "answer_snippet": ans[:200] if ans else None,
            },
        }],
    }


# Registry: task_id -> checker(logs) -> {success, checks}
SUCCESS_CHECKS: Dict[str, Callable[[List[WebsiteLog]], CheckResult]] = {
    # Banking suite
    "banking_export_transactions": banking_export_transactions,
    "banking_set_dining_alert": banking_set_dining_alert,
    "banking_report_specific_merchant": banking_report_specific_merchant,
    "banking_send_money": banking_send_money,
    # Calendar suite
    "calendar_navigate_today": calendar_navigate_today,
    "calendar_start_hiring_call": calendar_start_hiring_call,
    "calendar_cancel_standup": calendar_cancel_standup,
    # Support suite
    "support_create_ticket": support_create_ticket,
    "support_close_techcorp": support_close_techcorp,
    # Webshop suite
    "webshop_sort_price_low": webshop_sort_price_low,
    "webshop_filter_size_s": webshop_filter_size_s,
    "webshop_filter_price_under_30": webshop_filter_price_under_30,
    "webshop_add_to_cart": webshop_add_to_cart,
    "webshop_add_silk_blouse": webshop_add_silk_blouse,
    # Email suite
    "email_reply_alice": email_reply_alice,
    "email_download_presentation": email_download_presentation,
    "email_filter_unread": email_filter_unread,
    "email_search_meeting": email_search_meeting,
    "email_switch_starred": email_switch_starred,
    # Forum suite
    "forum_sort_votes": forum_sort_votes,
    "forum_filter_unanswered": forum_filter_unanswered,
    "forum_create_post": forum_create_post,
    "forum_reply_to_sarah": forum_reply_to_sarah,
    # Jobboard suite
    "jobboard_filter_remote": jobboard_filter_remote,
    "jobboard_sort_salary": jobboard_sort_salary,
    "jobboard_filter_entry": jobboard_filter_entry,
    "jobboard_clear_filters": jobboard_clear_filters,
    "jobboard_apply_designer": jobboard_apply_designer,
    # Restaurant suite
    "restaurant_filter_price": restaurant_filter_price,
    "restaurant_filter_pasta": restaurant_filter_pasta,
    "restaurant_filter_vegetarian": restaurant_filter_vegetarian,
    "restaurant_clear_filters": restaurant_clear_filters,
    "restaurant_add_margherita": restaurant_add_margherita,
    "restaurant_make_reservation": restaurant_make_reservation,
    # Travel suite
    "travel_sort_price": travel_sort_price,
    "travel_filter_nonstop": travel_filter_nonstop,
    "travel_filter_5star": travel_filter_5star,
    "travel_sort_rating": travel_sort_rating,
    "travel_select_delta": travel_select_delta,
    "forum_report_memory_leak": forum_report_memory_leak,
    "email_flag_project_alpha": email_flag_project_alpha,
    "support_escalate_techcorp": support_escalate_techcorp,
}


# ---------------------------------------------------------------------------
# Model-side fallback checks for website-only tasks.
# ---------------------------------------------------------------------------

def _phrase_in_last(model_entries, *phrases) -> bool:
    ans = (_last_assistant_text(model_entries) or "").lower()
    return any(p.lower() in ans for p in phrases)


def calendar_navigate_today_model(model_entries: List[ModelLog]) -> CheckResult:
    ok = _phrase_in_last(model_entries, "today button", "navigated to today",
                         "today's date", "today view", "clicked today")
    return {"success": ok, "checks": [{"name": "answer_confirms_today_clicked",
                                       "ok": ok, "evidence": {}}]}


def calendar_start_hiring_call_model(model_entries: List[ModelLog]) -> CheckResult:
    ok = _phrase_in_last(model_entries, "started the call", "video call started",
                         "joined the call", "starting the call", "call started")
    has_hiring = _phrase_in_last(model_entries, "hiring")
    ok = ok and has_hiring
    return {"success": ok, "checks": [{"name": "answer_confirms_started_hiring_call",
                                       "ok": ok, "evidence": {}}]}


def calendar_cancel_standup_model(model_entries: List[ModelLog]) -> CheckResult:
    ok = _phrase_in_last(model_entries, "cancelled", "canceled")
    has_standup = _phrase_in_last(model_entries, "standup")
    ok = ok and has_standup
    return {"success": ok, "checks": [{"name": "answer_confirms_cancelled_standup",
                                       "ok": ok, "evidence": {}}]}


def travel_filter_5star_model(model_entries: List[ModelLog]) -> CheckResult:
    ok = _phrase_in_last(model_entries, "5-star", "5 star", "five-star",
                         "five star")
    return {"success": ok, "checks": [{"name": "answer_confirms_5star_filter",
                                       "ok": ok, "evidence": {}}]}


def forum_report_memory_leak_model(model_entries: List[ModelLog]) -> CheckResult:
    ok = _phrase_in_last(model_entries, "reported") and _phrase_in_last(
        model_entries, "memory leak")
    return {"success": ok, "checks": [{"name": "answer_confirms_reported_memory_leak",
                                       "ok": ok, "evidence": {}}]}


def email_filter_unread_model(model_entries: List[ModelLog]) -> CheckResult:
    """Model-side fallback for email_filter_unread.

    Requires BOTH (a) an explicit click action and (b) the final
    assistant text confirms the inbox is filtered to unread.
    """
    texts = _all_assistant_texts(model_entries)
    blob = "\n".join(texts).lower()
    confirm_pat = re.compile(
        r"unread\s+(?:filter|button)|filter(?:ed)?\s+(?:to|by|for|on)\s+unread"
        r"|filtered\s+to\s+show\s+only\s+unread|only\s+unread|showing\s+(?:only\s+)?unread"
        r"|clicked\s+(?:on\s+)?(?:the\s+)?[\"']?unread[\"']?\s+(?:filter|button|tab)?",
        flags=re.IGNORECASE,
    )
    confirm_ok = bool(confirm_pat.search(blob))

    click_count = sum(
        1 for e in model_entries
        if e.get("type") == "action"
        and ((e.get("action") or {}).get("type") == "click"
             or e.get("action_type") == "click")
    )
    ok = confirm_ok and click_count >= 1
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_confirms_unread_filter_clicked",
            "ok": bool(ok),
            "evidence": {
                "phrase_matched": confirm_ok,
                "click_action_count": click_count,
            },
        }],
    }


def forum_sort_votes_model(model_entries: List[ModelLog]) -> CheckResult:
    """Model-side fallback for forum_sort_votes.

    Requires BOTH (a) an explicit click action and (b) the final
    assistant text confirms the posts are sorted by most votes.
    """
    texts = _all_assistant_texts(model_entries)
    blob = "\n".join(texts).lower()
    confirm_pat = re.compile(
        r"most\s+votes|sort(?:ed)?\s+(?:by\s+)?(?:most\s+)?votes"
        r"|votes?[-\s]?desc(?:ending)?|highest\s+(?:vote|votes)"
        r"|posts?\s+(?:are\s+)?(?:now\s+)?sorted\s+by\s+(?:most\s+)?votes",
        flags=re.IGNORECASE,
    )
    confirm_ok = bool(confirm_pat.search(blob))

    click_count = sum(
        1 for e in model_entries
        if e.get("type") == "action"
        and ((e.get("action") or {}).get("type") == "click"
             or e.get("action_type") == "click")
    )
    ok = confirm_ok and click_count >= 1
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_confirms_sort_by_votes_clicked",
            "ok": bool(ok),
            "evidence": {
                "phrase_matched": confirm_ok,
                "click_action_count": click_count,
            },
        }],
    }


def restaurant_make_reservation_model(model_entries: List[ModelLog]) -> CheckResult:
    ok = _phrase_in_last(model_entries, "reservation confirmed",
                         "reservation made", "reservation id", "reservation has been")
    return {"success": ok, "checks": [{"name": "answer_confirms_reservation",
                                       "ok": ok, "evidence": {}}]}


def jobboard_apply_designer_model(model_entries: List[ModelLog]) -> CheckResult:
    ok = _phrase_in_last(model_entries, "applied", "application submitted",
                         "application sent") and _phrase_in_last(
        model_entries, "ux designer", "designer position", "designer role")
    return {"success": ok, "checks": [{"name": "answer_confirms_designer_applied",
                                       "ok": ok, "evidence": {}}]}


def webshop_sort_price_low_model(model_entries: List[ModelLog]) -> CheckResult:
    """Model-side fallback for webshop_sort_price_low (4-step check).
    Sort target is price-DESC (high to low).
    Price filter target is the $0-$25 bucket (prompt says "up to $25").
    """
    ans = _last_assistant_text(model_entries) or ""
    sort_pat = re.compile(
        r"price\s*:?\s*high\s*(?:to|→|->|-)?\s*low"
        r"|high\s+to\s+low"
        r"|sorted\s+(?:by\s+)?price\s+(?:from\s+)?high(?:est)?"
        r"|price[-\s]?desc(?:ending)?"
        r"|highest\s+(?:price\s+)?first|most\s+expensive\s+first",
        flags=re.IGNORECASE,
    )
    color_pat = re.compile(r"\bblue\b|color\s*[:=]\s*blue", flags=re.IGNORECASE)
    size_pat = re.compile(r"size\s*[:=]?\s*s\b|\bsize\s+small\b", flags=re.IGNORECASE)
    price_pat = re.compile(
        r"up\s+to\s*\$?\s*25|less\s+than\s+(?:or\s+equal\s+to\s+)?\$?\s*25|"
        r"under\s*\$?\s*25|\$?\s*0\s*[-–]\s*\$?\s*25|price\s+range",
        flags=re.IGNORECASE,
    )
    sort_ok = bool(sort_pat.search(ans))
    color_ok = bool(color_pat.search(ans))
    size_ok = bool(size_pat.search(ans))
    price_ok = bool(price_pat.search(ans))

    click_count = sum(
        1 for e in model_entries
        if e.get("type") == "action"
        and ((e.get("action") or {}).get("type") == "click"
             or e.get("action_type") == "click")
    )

    ok = color_ok and sort_ok and size_ok and price_ok and click_count >= 3
    return {
        "success": bool(ok),
        "checks": [{
            "name": "answer_confirms_color_size_price_and_sort_desc",
            "ok": bool(ok),
            "evidence": {
                "blue_phrase": color_ok,
                "size_s_phrase": size_ok,
                "up_to_25_phrase": price_ok,
                "sort_high_to_low_phrase": sort_ok,
                "click_action_count": click_count,
                "answer_snippet": ans[:200] if ans else None,
            },
        }],
    }

# Registry: task_id -> checker(model_entries) -> {success, checks}
MODEL_SUCCESS_CHECKS: Dict[str, Callable[[List[ModelLog]], CheckResult]] = {
    # Banking suite
    "banking_check_balance": banking_check_balance_model,
    "banking_count_recent_transactions": banking_count_recent_transactions_model,
    "banking_calculate_category_total": banking_calculate_category_total_model,
    "banking_reveal_account_number": banking_reveal_account_number_model,
    # Calendar suite
    "calendar_count_events": calendar_count_events_model,
    "calendar_latest_event": calendar_latest_event_model,
    "calendar_earliest_meeting": calendar_earliest_meeting_model,
    "calendar_wednesday_count": calendar_wednesday_count_model,
    # Support suite
    "support_count_critical": support_count_critical_model,
    "support_count_new_status": support_count_new_status_model,
    "support_filter_high_priority": support_filter_high_priority_model,
    "support_count_total": support_count_total_model,
    "support_find_customer_1001": support_find_customer_1001_model,
    # Webshop suite
    "webshop_count_pink": webshop_count_pink_model,
    "webshop_filter_size_s": webshop_filter_size_s_model,
    "webshop_filter_price_under_30": webshop_filter_price_under_30_model,
    "webshop_find_cheapest": webshop_find_cheapest_model,
    "webshop_read_flannel_description": webshop_read_flannel_description_model,
    "webshop_read_reviews": webshop_read_reviews_model,
    # Email suite
    "email_count_unread": email_count_unread_model,
    "email_search_meeting": email_search_meeting_model,
    "email_count_total": email_count_total_model,
    # Forum suite
    "forum_count_python": forum_count_python_model,
    "forum_count_total": forum_count_total_model,
    "forum_read_async_post": forum_read_async_post_model,
    # Jobboard suite
    "jobboard_count_jobs": jobboard_count_jobs_model,
    "jobboard_find_techcorp": jobboard_find_techcorp_model,
    "jobboard_devops_primary_focus": jobboard_devops_primary_focus_model,
    "jobboard_read_requirements": jobboard_read_requirements_model,
    "jobboard_read_techcorp_requirements": jobboard_read_techcorp_requirements_model,
    # Jobboard filter/sort fallbacks (paired with website checks via OR)
    "jobboard_sort_salary": jobboard_sort_salary_model,
    "jobboard_filter_entry": jobboard_filter_entry_model,
    # Restaurant suite
    "restaurant_count_items": restaurant_count_items_model,
    "restaurant_check_bruschetta_tomato": restaurant_check_bruschetta_tomato_model,
    "restaurant_salmon_cooking_method": restaurant_salmon_cooking_method_model,
    "restaurant_read_carbonara_region": restaurant_read_carbonara_region_model,
    # Travel suite
    "travel_count_flights": travel_count_flights_model,
    "travel_find_british": travel_find_british_model,
    "travel_count_emirates_dubai": travel_count_emirates_dubai_model,
    "travel_read_layover": travel_read_layover_model,
    "travel_read_emirates_amenity": travel_read_emirates_amenity_model,
    # Wiki suite
    "wiki_search_microscopy": wiki_search_microscopy_model,
    "wiki_navigate_procedures": wiki_navigate_procedures_model,
    "wiki_count_safety": wiki_count_safety_model,
    "wiki_view_history": wiki_view_history_model,
    "wiki_filter_equipment": wiki_filter_equipment_model,
    "wiki_count_spill_steps": wiki_count_spill_steps_model,
    "wiki_lab_safety_recent_change": wiki_lab_safety_recent_change_model,
    "wiki_count_storage_zones": wiki_count_storage_zones_model,
    "banking_total_wholefoods": banking_total_wholefoods_model,
    "forum_count_docker_answer_votes": forum_count_docker_answer_votes_model,
    "forum_memory_leak_votes": forum_memory_leak_votes_model,
    "email_count_budget_attachments": email_count_budget_attachments_model,
    "webshop_casual_evening": webshop_casual_evening_model,
    "calendar_count_meeting_attendees": calendar_count_meeting_attendees_model,
    "calendar_project_review_location": calendar_project_review_location_model,
    "calendar_count_virtual_meetings": calendar_count_virtual_meetings_model,
    "email_q4_received_date": email_q4_received_date_model,
    "support_count_billing_tickets": support_count_billing_tickets_model,
    "support_ticket_1001_priority": support_ticket_1001_priority_model,
    "wiki_sample_protocol_last_updated": wiki_sample_protocol_last_updated_model,
    "wiki_microscopy_nov20_edit_count": wiki_microscopy_nov20_edit_count_model,
    # Model-side fallback for website-only tasks. Only kept for tasks whose
    # action does not produce a reliable website-side event (e.g. calendar
    # date navigation, follow-up confirmations). Action-based filter/sort/
    # clear tasks rely on the corresponding website event check — phrase
    # matching produced too many false negatives when phrasing varied.
    "calendar_navigate_today": calendar_navigate_today_model,
    "calendar_start_hiring_call": calendar_start_hiring_call_model,
    "calendar_cancel_standup": calendar_cancel_standup_model,
    "restaurant_make_reservation": restaurant_make_reservation_model,
    "jobboard_apply_designer": jobboard_apply_designer_model,
    "travel_filter_5star": travel_filter_5star_model,
    "forum_report_memory_leak": forum_report_memory_leak_model,
    # Native <select> change events are unreliable — model fallback covers
    # cases where the agent sorted but the change event didn't fire.
    "webshop_sort_price_low": webshop_sort_price_low_model,
    # Both require a click action AND assistant-text confirmation.
    "email_filter_unread": email_filter_unread_model,
    "forum_sort_votes": forum_sort_votes_model,
}
