"""
WebArena-compatible evaluation for agent task completion.

Based on the WebArena benchmark's evaluation harness:
  https://github.com/web-arena-x/webarena/blob/main/evaluation_harness/evaluators.py
  https://github.com/web-arena-x/webarena/blob/main/evaluation_harness/helper_functions.py
"""

import collections
import html as html_module
import json
import os
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

# nltk is used by WebArena for tokenization in must_include checks
from nltk.tokenize import word_tokenize


# ---------------------------------------------------------------------------
# StringEvaluator — methods follow WebArena evaluators.py closely.
# ---------------------------------------------------------------------------

class StringEvaluator:
    """Check whether the answer is correct with:
    exact match: the answer is exactly the same as the reference answer
    must include: each phrase in the reference answer must be included in the answer
    fuzzy match: the answer is similar to the reference answer, using LLM judge
    """

    @staticmethod
    def clean_answer(answer: str) -> str:
        import re as _re
        answer = answer.strip()
        if answer.startswith("'") and answer.endswith("'"):
            answer = answer[1:-1]
        elif answer.startswith('"') and answer.endswith('"'):
            answer = answer[1:-1]
        answer = answer.lower()
        # Normalize multiplication-style separators between digits so size
        # strings written as "16x24", "16*24", "16×24" or "16 x 24" all
        # match. Applied symmetrically to ref and pred via must_include.
        answer = _re.sub(r"(\d)\s*[×x*]\s*(\d)", r"\1x\2", answer)
        # Collapse runs of whitespace to a single space so must_include
        # comparisons aren't broken by double-spacing in agent output.
        answer = _re.sub(r"\s+", " ", answer)
        return answer

    @staticmethod
    def exact_match(ref: str, pred: str) -> float:
        return float(
            StringEvaluator.clean_answer(pred)
            == StringEvaluator.clean_answer(ref)
        )

    @staticmethod
    def must_include(ref: str, pred: str, tokenize: bool = False) -> float:
        clean_ref = StringEvaluator.clean_answer(ref)
        clean_pred = StringEvaluator.clean_answer(pred)
        # tokenize the answer if the ref is a single word
        # prevent false positive (e.g, 0)
        if (
            tokenize
            and len(clean_ref) == 1
            and len(word_tokenize(clean_ref)) == 1
        ):
            tok_pred = word_tokenize(clean_pred)
            if clean_ref in tok_pred:
                return 1.0
            # Numeric tolerance: when the ref is a bare number like "0",
            # also accept tokens that are numerically equivalent (e.g.
            # "$0.00", "0.00", "$0", "0,00"). word_tokenize keeps decimals
            # in a single token, so the bare "0" check above misses them.
            try:
                ref_val = float(clean_ref)
                for tok in tok_pred:
                    stripped = tok.lstrip("$€£¥").replace(",", "").rstrip(".")
                    try:
                        if float(stripped) == ref_val:
                            return 1.0
                    except ValueError:
                        continue
            except ValueError:
                pass
            return 0.0
        else:
            return float(clean_ref in clean_pred)

    @staticmethod
    def fuzzy_match(ref: str, pred: str, intent: str) -> float:
        return llm_fuzzy_match(pred, ref, intent)

    @staticmethod
    def ua_match(ref: str, pred: str, intent: str) -> float:
        return llm_ua_match(pred, ref, intent)


import re as _re

def _extract_concise_answer(text: str) -> str:
    """Try to extract a concise answer from a verbose agent response.

    Looks for common patterns like:
      "Answer: Shawn Allen"
      "**Answer:** Shawn Allen"
      "The answer is Shawn Allen"
    Returns the extracted short answer (already lowercased/stripped),
    or the original text unchanged if no pattern matches.
    """
    patterns = [
        r"(?:^|\n)\s*\**\s*answer\s*[:：]\**\s*(.+?)(?:\n|$)",
        r"(?:^|\n)\s*\**\s*final\s+answer\s*[:：]\**\s*(.+?)(?:\n|$)",
        r"the\s+answer\s+is\s*[:：]?\s*(.+?)(?:\.|$)",
    ]
    for pat in patterns:
        m = _re.search(pat, text, _re.IGNORECASE)
        if m:
            return m.group(1).strip().rstrip(".")
    return text


def evaluate_string_match(pred: str, configs: dict) -> float:
    """
    Evaluate string_match — adapted from WebArena StringEvaluator.__call__
    with a local _extract_concise_answer fallback when exact_match fails.

    Args:
        pred: The agent's final text answer
        configs: The full WebArena task config dict (with 'eval' and 'intent' keys)

    Returns:
        Score: 1.0 if correct, 0.0 if incorrect
    """
    pred = StringEvaluator.clean_answer(pred)

    score = 1.0
    for approach, value in configs["eval"]["reference_answers"].items():
        match approach:
            case "exact_match":
                score = StringEvaluator.exact_match(ref=value, pred=pred)
                if score == 0.0:
                    extracted = _extract_concise_answer(pred)
                    if extracted != pred:
                        score = StringEvaluator.exact_match(ref=value, pred=extracted)

            case "must_include":
                assert isinstance(value, list)
                for must_value in value:
                    score *= StringEvaluator.must_include(
                        ref=must_value,
                        pred=pred,
                        tokenize=(len(value) == 1),
                    )
            case "fuzzy_match":
                intent = configs["intent"]
                if value == "N/A":
                    # if the instruction only asks the model to generate N/A when encountering
                    # an unachievable task without more concrete reasons
                    score *= StringEvaluator.exact_match(ref=value, pred=pred)
                    # if the instruction also asks the model to generate the reason why the task
                    # is unachievable — this should be the default as it will prevent false
                    # positive N/A
                    if score != 1:
                        score = 1.0 * StringEvaluator.ua_match(
                            intent=configs["intent"],
                            ref=configs["eval"]["string_note"],
                            pred=pred,
                        )
                else:
                    assert isinstance(value, list)
                    for reference in value:
                        score *= StringEvaluator.fuzzy_match(
                            ref=reference, pred=pred, intent=intent
                        )
    return score


# ---------------------------------------------------------------------------
# URLEvaluator — follows WebArena evaluators.py closely.
# ---------------------------------------------------------------------------

def evaluate_url_match(pred_url: str, configs: dict) -> float:
    """
    Evaluate url_match — follows WebArena URLEvaluator.__call__ closely.

    Args:
        pred_url: The browser's final URL after the agent completes the task
        configs: The full WebArena task config dict

    Returns:
        Score: 1.0 if correct, 0.0 if incorrect
    """

    def clean_url(url: str) -> str:
        url = str(url)
        url = url.rstrip("/")
        return url

    def _normalize_query_key(key: str) -> str:
        """Strip trailing [] from query param names so label_name[] matches label_name."""
        return key.rstrip("[]")

    def parse_url(url: str) -> tuple:
        """Parse a URL into its base, path, and query components."""
        parsed_url = urllib.parse.urlparse(url)
        base_path = parsed_url.netloc + parsed_url.path.rstrip("/")
        raw_query = urllib.parse.parse_qs(parsed_url.query)
        query = {_normalize_query_key(k): v for k, v in raw_query.items()}
        return base_path, query

    def parse_urls(urls: list) -> tuple:
        """Parse a list of URLs."""
        base_paths = []
        queries: dict = collections.defaultdict(set)
        for url in urls:
            base_path, query = parse_url(url)
            base_paths.append(base_path)
            for k, v in query.items():
                queries[k].update(v)
        return base_paths, queries

    pred = clean_url(pred_url)
    ref_urls = configs["eval"]["reference_url"].split(" |OR| ")
    ref_urls = [clean_url(url) for url in ref_urls]
    matching_rule = configs["eval"].get("url_note", "GOLD in PRED")

    if matching_rule == "GOLD in PRED":
        ref_base_paths, ref_queries = parse_urls(ref_urls)
        pred_base_paths, pred_query = parse_url(pred)

        base_score = float(
            any(
                [
                    ref_base_path in pred_base_paths
                    for ref_base_path in ref_base_paths
                ]
            )
        )
        query_score = 1.0
        for k, possible_values in ref_queries.items():
            query_score *= float(
                any(
                    possible_ref_value in pred_query.get(k, [])
                    for possible_ref_value in possible_values
                )
            )
        score = base_score * query_score

    else:
        raise ValueError(f"Unknown matching rule: {matching_rule}")

    return score


# ---------------------------------------------------------------------------
# DockerPageAdapter — wraps DockerComputer to provide the page interface
# expected by evaluate_html_content (same DOM access as QLLM)
# ---------------------------------------------------------------------------

class DockerPageAdapter:
    """
    Adapts DockerComputer to the page interface expected by WebArena's
    HTMLContentEvaluator: .goto(), .content(), .evaluate(), .url

    Uses the same HTML retrieval mechanism as the QLLM tool
    (html-cache.js → /get-rendered-html endpoint).

    For JS locators (document.querySelector...), it runs JS inside the
    Docker container's Firefox using xdotool + the browser console,
    falling back to fetching the raw page via curl and searching the HTML.
    """

    def __init__(self, computer):
        self.computer = computer
        self._url = computer.get_current_url() or ""

    @property
    def url(self) -> str:
        return self._url

    def goto(self, target_url: str) -> None:
        """Navigate the Docker Firefox to the target URL."""
        print(f"  [PageAdapter] Navigating to: {target_url}")
        self.computer.goto(target_url)
        self._url = target_url
        time.sleep(5)  # Wait for page load + html-cache.js

    def content(self) -> str:
        """Get rendered HTML content (same mechanism as QLLM)."""
        try:
            html = self.computer.get_html()
            if html and len(html) > 100:
                print(f"  [PageAdapter] Got HTML content ({len(html)} chars)")
                return html
        except Exception as e:
            print(f"  [PageAdapter] get_html() failed: {e}")

        # Fallback: curl the page directly from inside the Docker container
        try:
            html = self.computer._exec(f"curl -s '{self._url}'")
            if html and len(html) > 100:
                print(f"  [PageAdapter] Got HTML via curl ({len(html)} chars)")
                return html
        except Exception as e:
            print(f"  [PageAdapter] curl fallback failed: {e}")

        return ""

    def evaluate(self, js_expr: str) -> str:
        """
        Evaluate a JS expression against the current page.

        Uses the html-cache.js eval mechanism: POST the JS to
        /eval-js endpoint, or fall back to parsing the HTML.
        """
        # The js_expr comes in as "() => document.querySelector(...)"
        # Strip the arrow function wrapper if present
        js_code = js_expr
        if js_code.startswith("() => "):
            js_code = js_code[6:]

        print(f"  [PageAdapter] Evaluating JS: {js_code[:100]}...")

        try:
            html = self.content()
            result = self._simulate_js_on_html(js_code, html)
            if result is not None:
                print(f"  [PageAdapter] JS result ({len(result)} chars): {result[:200]}")
                return result
        except Exception as e:
            print(f"  [PageAdapter] HTML simulation failed: {e}")

        print(f"  [PageAdapter] WARNING: Could not evaluate JS expression")
        return ""

    @staticmethod
    def _simulate_js_on_html(js_code: str, html: str) -> Optional[str]:
        """
        Simulate simple document.querySelector/querySelectorAll calls by parsing HTML.
        Handles common patterns from WebArena program_html locators.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return None

        soup = BeautifulSoup(html, "html.parser")

        import re

        # Pattern: document.querySelectorAll('selector')[index].property
        m_all = re.match(
            r"document\.querySelectorAll\(['\"](.+?)['\"]\)"
            r"\[(\d+)\]"
            r"\.(?:textContent|outerText|innerText|innerHTML|outerHTML)",
            js_code,
        )
        if m_all:
            selector = m_all.group(1)
            index = int(m_all.group(2))
            elements = soup.select(selector)
            if index >= len(elements):
                return ""
            el = elements[index]
            if "innerHTML" in js_code or "outerHTML" in js_code:
                return str(el)
            return el.get_text(strip=True)

        # Pattern: document.querySelector('selector').textContent / .outerText
        m = re.match(
            r"document\.querySelector\(['\"](.+?)['\"]\)"
            r"(?:\.(?:lastChild|lastElementChild|firstChild|firstElementChild))?"
            r"(?:\.querySelector\(['\"](.+?)['\"]\))?"
            r"\.(?:textContent|outerText|innerText|innerHTML|outerHTML)",
            js_code,
        )
        if m:
            selector = m.group(1)
            sub_selector = m.group(2)
            el = soup.select_one(selector)
            if el is None:
                return ""
            if ".lastElementChild" in js_code or ".lastChild" in js_code:
                children = [c for c in el.children if hasattr(c, "name") and c.name]
                el = children[-1] if children else el
            if sub_selector:
                el = el.select_one(sub_selector)
            if el is None:
                return ""
            if "innerHTML" in js_code or "outerHTML" in js_code:
                return str(el)
            return el.get_text(strip=True)

        # Pattern: just document.querySelector('selector') - return outerHTML
        m2 = re.match(r"document\.querySelector\(['\"](.+?)['\"]\)", js_code)
        if m2:
            el = soup.select_one(m2.group(1))
            return str(el) if el else ""

        return None


# ---------------------------------------------------------------------------
# Helper functions named the same as WebArena helper_functions.py (so the
# func:* locators in upstream task configs still resolve). Some of these are
# re-implemented to use BeautifulSoup HTML parsing instead of upstream's
# page.evaluate() JS — see e.g. gitlab_get_project_memeber_role.
# These are called via eval() in program_html locators like
#   "func:gitlab_get_project_memeber_role(__page__, 'username')"
# ---------------------------------------------------------------------------

# Module-level "current page" used by func:* call sites in WebArena task
# configs (which don't pass __page__) so they can still reach the live browser.
# Set by evaluate_html_content() / evaluate_url_match() right before eval().
_CURRENT_EVAL_PAGE = None

def _set_current_eval_page(page):
    global _CURRENT_EVAL_PAGE
    _CURRENT_EVAL_PAGE = page


def gitlab_get_project_memeber_role(page, account_name: str) -> str:
    """Get a project member's role from the members page. (WebArena typo preserved.)

    Original WebArena uses Playwright page.evaluate() with live DOM JS.
    This version falls back to HTML parsing when JS eval is unavailable.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return ""

    try:
        html = page.content()
        soup = BeautifulSoup(html, "html.parser")

        account_cells = soup.select("td[data-label='Account'] span.gl-avatar-labeled-sublabel")
        account_idx = -1
        for i, el in enumerate(account_cells):
            if el.get_text(strip=True) == f"@{account_name}":
                account_idx = i
                break

        if account_idx < 0:
            return ""

        role_cells = soup.select("td.col-max-role span")
        if account_idx < len(role_cells):
            role = role_cells[account_idx].get_text(strip=True)
        else:
            role = ""
    except Exception:
        role = ""

    return role


# ---------------------------------------------------------------------------
# HTMLContentEvaluator — adapted from WebArena evaluators.py.
# Core control flow matches upstream. Local additions:
#   - alt_urls fallback when the primary URL returns 404 / file tree.
#   - Verbose per-check debug logging (page title, content length, locator).
# Requires browser page access (DockerPageAdapter); only used for program_html tasks.
# ---------------------------------------------------------------------------

def evaluate_html_content(page, configs: dict, final_url: str = "") -> dict:
    """
    Evaluate program_html — based on WebArena HTMLContentEvaluator.__call__

    Args:
        page: A browser page object with .goto(), .evaluate(), .content(), .url methods
        configs: The full WebArena task config dict

    Returns:
        Dict with 'score' (0.0 or 1.0) and 'check_results' (per-check details)
    """
    targets = configs["eval"]["program_html"]

    # Expose page to func:* helpers that don't take a page argument.
    _set_current_eval_page(page)

    score = 1.0
    check_results = []
    for i, target in enumerate(targets):
        check_info = {"check_index": i}
        target_url: str = target["url"]  # which url to check
        if target_url.startswith("func"):
            func = target_url.split("func:")[1]
            func = func.replace("__last_url__", page.url)
            target_url = eval(func)

        locator: str = target["locator"]  # js element locator
        check_info["resolved_url"] = target_url
        check_info["locator"] = locator[:100] if locator else "(full page)"

        print(f"  [program_html check {i+1}/{len(targets)}] URL: {target_url}")
        print(f"  [program_html check {i+1}/{len(targets)}] Locator: {locator[:100] if locator else '(empty = full page)'}")
        print(f"  [program_html check {i+1}/{len(targets)}] Required: {target['required_contents']}")

        # navigate to that url
        if target_url != "last":
            page.goto(target_url)
            time.sleep(3)
            # Task-specific: if alt_urls are defined and the primary URL
            # returned a file-tree or 404, try each alternate URL.
            alt_urls = target.get("alt_urls", [])
            if alt_urls:
                _peek = page.content() or ""
                if "<title>Files " in _peek or "could not be found" in _peek:
                    for alt in alt_urls:
                        print(f"  [program_html] Primary URL missed, trying alt_url: {alt}")
                        page.goto(alt)
                        time.sleep(3)
                        _peek = page.content() or ""
                        if "<title>Files " not in _peek and "could not be found" not in _peek:
                            check_info["resolved_url"] = alt
                            print(f"  [program_html] alt_url succeeded: {alt}")
                            break
        elif final_url:
            # "last" means use the page the agent ended on — don't re-navigate,
            # just read the current DOM. Re-navigating can cause 404s or auth issues.
            actual_browser_url = page.computer.get_current_url() if hasattr(page, 'computer') else page.url
            print(f"  [program_html check {i+1}/{len(targets)}] Using current page:")
            print(f"    final_url (from task runner) = {final_url}")
            print(f"    actual browser URL            = {actual_browser_url}")
            print(f"    page._url                     = {page.url}")

        # Log what page we're actually reading from
        try:
            _preview = page.content() or ""
            _title_start = _preview.find("<title>")
            _title_end = _preview.find("</title>")
            _page_title = _preview[_title_start+7:_title_end] if _title_start >= 0 and _title_end >= 0 else "(no title)"
            print(f"  [program_html check {i+1}/{len(targets)}] Page title: {_page_title}")
            print(f"  [program_html check {i+1}/{len(targets)}] Page content length: {len(_preview)} chars")
        except Exception:
            pass

        # empty, use the full page
        if not locator.strip():
            selected_element = page.content()
        # use JS to select the element
        elif locator.startswith("document.") or locator.startswith(
            "[...document."
        ):
            if "prep_actions" in target:
                try:
                    for prep_action in target["prep_actions"]:
                        page.evaluate(f"() => {prep_action}")
                except Exception:
                    pass
            try:
                selected_element = str(page.evaluate(f"() => {locator}"))
                if not selected_element:
                    selected_element = ""
            except Exception:
                # the page is wrong, return empty
                selected_element = ""
        # run program to call API
        elif locator.startswith("func:"):  # a helper function
            func = locator.split("func:")[1]
            func = func.replace("__page__", "page")
            selected_element = eval(func)
        else:
            raise ValueError(f"Unknown locator: {locator}")

        selected_element = html_module.unescape(selected_element)
        element_len = len(selected_element)
        element_preview = selected_element[:500].replace('\n', ' ')
        check_info["element_length"] = element_len
        check_info["element_preview"] = element_preview[:200]
        print(f"  [program_html check {i+1}/{len(targets)}] Got element ({element_len} chars): {element_preview}...")

        content_results = []
        if "exact_match" in target["required_contents"]:
            required_contents = target["required_contents"]["exact_match"]
            cur_score = StringEvaluator.exact_match(
                ref=required_contents, pred=selected_element
            )
            score *= float(cur_score)
            content_results.append({"type": "exact_match", "value": required_contents, "passed": bool(cur_score)})
            print(f"  [program_html check {i+1}/{len(targets)}] exact_match '{required_contents}' => {cur_score}")
        elif "must_include" in target["required_contents"]:
            required_contents = target["required_contents"]["must_include"]
            assert isinstance(required_contents, list)
            for content in required_contents:
                content_or = content.split(" |OR| ")
                cur_score = any(
                    [
                        StringEvaluator.must_include(
                            ref=c,
                            pred=selected_element,
                            tokenize=False,
                        )
                        for c in content_or
                    ]
                )
                score *= float(cur_score)
                content_results.append({"type": "must_include", "value": content, "passed": bool(cur_score)})
                print(f"  [program_html check {i+1}/{len(targets)}] must_include '{content}' => {cur_score}  (running score: {score})")
        elif "must_exclude" in target["required_contents"]:
            required_contents = target["required_contents"]["must_exclude"]
            assert isinstance(required_contents, list)
            for content in required_contents:
                cur_score = not StringEvaluator.must_include(
                    ref=content,
                    pred=selected_element,
                    tokenize=False,
                )
                score *= float(cur_score)
                content_results.append({"type": "must_exclude", "value": content, "passed": bool(cur_score)})
                print(f"  [program_html check {i+1}/{len(targets)}] must_exclude '{content}' => {cur_score}  (running score: {score})")
        else:
            raise ValueError(
                f"Unknown required_contents: {target['required_contents'].keys()}"
            )

        check_passed = all(r["passed"] for r in content_results)
        check_info["content_results"] = content_results
        check_info["passed"] = check_passed
        check_results.append(check_info)
        print(f"  [program_html check {i+1}/{len(targets)}] CHECK {'PASS' if check_passed else 'FAIL'} (score so far: {score})")

    return {"score": score, "check_results": check_results}


# ---------------------------------------------------------------------------
# LLM Judge Functions — prompt text matches WebArena helper_functions.py.
# Local adaptation: a backend router supporting both OpenAI (upstream default)
# and Anthropic. Upstream only supports OpenAI.
# ---------------------------------------------------------------------------

# Module-level setting: "openai" or "anthropic"
LLM_JUDGE_BACKEND = os.environ.get("LLM_JUDGE_BACKEND", "anthropic")
LLM_JUDGE_MODEL_OPENAI = "gpt-4-1106-preview"
LLM_JUDGE_MODEL_ANTHROPIC = "claude-sonnet-4-20250514"


def _call_openai_chat(messages: list, model: str = LLM_JUDGE_MODEL_OPENAI) -> str:
    """Call OpenAI chat completion API."""
    try:
        import openai
    except ImportError:
        raise ImportError("OpenAI package required for fuzzy_match. Install with: pip install openai")

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY environment variable required for fuzzy_match evaluation")

    client = openai.OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=768,
        top_p=1.0,
    )
    return response.choices[0].message.content


def _call_anthropic_chat(messages: list, model: str = LLM_JUDGE_MODEL_ANTHROPIC) -> str:
    """Call Anthropic chat completion API with the same message format."""
    try:
        import anthropic
    except ImportError:
        raise ImportError("Anthropic package required for fuzzy_match. Install with: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY environment variable required for fuzzy_match evaluation")

    system_text = ""
    user_messages = []
    for msg in messages:
        if msg["role"] == "system":
            system_text = msg["content"]
        else:
            user_messages.append(msg)

    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        system=system_text,
        messages=user_messages,
        temperature=0,
        max_tokens=768,
    )
    return response.content[0].text


def _call_llm_judge(messages: list) -> str:
    """Route to the configured LLM judge backend."""
    if LLM_JUDGE_BACKEND == "anthropic":
        return _call_anthropic_chat(messages)
    else:
        return _call_openai_chat(messages)


def llm_fuzzy_match(pred: str, reference: str, question: str) -> float:
    """
    Check whether the prediction matches the reference with an LLM judge.
    The prompt text is taken from WebArena helper_functions.py.
    """
    message = (
        "Help a teacher to grade the answer of a student given a question. "
        "Keep in mind that the student may use different phrasing or wording "
        "to answer the question. The goal is to evaluate whether the answer is "
        "semantically equivalent to the reference answer.\n"
    )
    message += f"question: {question}\n"
    message += f"reference answer: {reference}\n"
    message += "all the string 'N/A' that you see is a special sequence that means 'not achievable'\n"
    message += f"student answer: {pred}\n"
    message += "Conclude the judgement by correct/incorrect/partially correct."
    messages = [
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": message},
    ]

    response = _call_llm_judge(messages).lower()
    if "partially correct" in response or "incorrect" in response:
        return 0.0
    else:
        if "correct" not in response:
            print(f"  [LLM Judge] Unexpected response: {response}")
            return 0.0
        return 1.0


def llm_ua_match(pred: str, reference: str, question: str) -> float:
    """
    Check whether the prediction matches the reference with an LLM judge.
    Used for N/A (unachievable) tasks.
    The prompt text is taken from WebArena helper_functions.py.
    """
    message = ""
    message += f"task: {question}\n"
    message += f"actual unachievable reason: {reference}\n"
    message += f"reported unachievable reason: {pred}\n"
    message += (
        "The task described above is inherently unachievable due to the reason "
        "specified under 'actual unachievable reason'. "
        "An individual previously attempted this task and was unable to complete it. "
        "They provided a reason for their failure, "
        "which is listed under 'reported unachievable reason'. "
        "Your role is to review both the actual and reported reasons. "
        "Determine if the reported reason aligns with the actual reason, even if implicitly. "
        "If the stated reason is in line with the actual reason, respond with 'same'. "
        "Otherwise, respond with 'different'."
    )
    messages = [
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": message},
    ]

    response = _call_llm_judge(messages).lower()
    if "different" in response:
        return 0.0
    else:
        if "same" not in response:
            print(f"  [LLM Judge] Unexpected response: {response}")
            return 0.0
        return 1.0


# ---------------------------------------------------------------------------
# Combined Evaluator Router — same logic as WebArena EvaluatorComb
# Scores are MULTIPLIED across eval types (all must pass).
# ---------------------------------------------------------------------------

def evaluate_webarena_task(
    *,
    wa_config: dict,
    agent_answer: str,
    final_url: str = "",
    page: Any = None,
) -> Dict[str, Any]:
    """
    Evaluate a WebArena task. Score is the multiplied product of the
    string_match / url_match / program_html scorers declared in the task
    config — matches WebArena's EvaluatorComb routing.

    Args:
        wa_config: Full WebArena task config dict (from webarena_gitlab_tasks.json)
        agent_answer: The agent's final text answer
        final_url: The browser's final URL (needed for url_match)
        page: Browser page object (needed for program_html; can be None)

    Returns:
        Dict with 'score' (0.0 or 1.0), per-type scores, and evaluation details
    """
    eval_types = wa_config["eval"]["eval_types"]
    overall_score = 1.0
    details = {}

    for eval_type in eval_types:
        match eval_type:
            case "string_match":
                if wa_config["eval"].get("reference_answers") is None:
                    type_score = 0.0
                    details["string_match"] = {
                        "score": type_score,
                        "error": "No reference_answers defined",
                    }
                else:
                    type_score = evaluate_string_match(agent_answer, wa_config)
                    sm_detail = {
                        "score": type_score,
                        "agent_answer": agent_answer,
                        "reference_answers": wa_config["eval"]["reference_answers"],
                    }
                    if "fuzzy_match" in wa_config["eval"]["reference_answers"]:
                        sm_detail["llm_judge"] = f"{LLM_JUDGE_BACKEND} ({LLM_JUDGE_MODEL_ANTHROPIC if LLM_JUDGE_BACKEND == 'anthropic' else LLM_JUDGE_MODEL_OPENAI})"
                    details["string_match"] = sm_detail
                overall_score *= type_score

            case "url_match":
                if not final_url:
                    type_score = 0.0
                    details["url_match"] = {
                        "score": type_score,
                        "error": "No final_url provided",
                    }
                else:
                    type_score = evaluate_url_match(final_url, wa_config)
                    details["url_match"] = {
                        "score": type_score,
                        "pred_url": final_url,
                        "reference_url": wa_config["eval"].get("reference_url", ""),
                    }
                overall_score *= type_score

            case "program_html":
                if page is None:
                    type_score = 0.0
                    details["program_html"] = {
                        "score": type_score,
                        "error": "No browser page provided; program_html evaluation skipped",
                    }
                else:
                    eval_result = evaluate_html_content(page, wa_config, final_url=final_url)
                    type_score = eval_result["score"]
                    details["program_html"] = {
                        "score": type_score,
                        "check_results": eval_result["check_results"],
                        "page_url": getattr(page, 'url', ''),
                    }
                overall_score *= type_score

            case _:
                raise ValueError(f"eval_type '{eval_type}' is not supported")

    return {
        "score": overall_score,
        "eval_types": eval_types,
        "details": details,
        "task_id": wa_config.get("task_id"),
        "intent": wa_config.get("intent"),
    }


# ---------------------------------------------------------------------------
# Task loading & URL replacement utilities
# ---------------------------------------------------------------------------

# URL placeholders used in WebArena task configs
SITE_URL_MAP = {
    "__GITLAB__": "http://gitlab-vwa.com",
    # Add other sites if expanding:
    # "__REDDIT__": "http://reddit-vwa.com",
    # "__WIKIPEDIA__": "http://wikipedia-vwa.com",
    # "__MAP__": "http://map-vwa.com",
}

# The original WebArena SSH hostname used in reference answers (e.g., SSH
# clone commands).  Replace with the actual GitLab server hostname so that
# exact_match evaluation works correctly in our environment.  The actual
# hostname is sourced from GITLAB_PUBLIC_HOST in .env.  Empty string ⇒ the
# replacement at line below is a no-op, which is fine when this module is
# imported outside a configured WebArena run.
GITLAB_SSH_HOST_ORIGINAL = "metis.lti.cs.cmu.edu"
GITLAB_SSH_HOST_ACTUAL = os.environ.get("GITLAB_PUBLIC_HOST", "")


def replace_url_placeholders(url: str) -> str:
    """Replace WebArena URL placeholders with actual Docker network URLs."""
    for placeholder, actual in SITE_URL_MAP.items():
        url = url.replace(placeholder, actual)
    return url


def replace_reference_hostnames(text: str) -> str:
    """Replace the original WebArena hostnames in reference answers."""
    return text.replace(GITLAB_SSH_HOST_ORIGINAL, GITLAB_SSH_HOST_ACTUAL)


def load_webarena_tasks(
    tasks_file: str = "src/benchmarks/webarena/webarena_gitlab_tasks.json",
    *,
    site_filter: Optional[List[str]] = None,
    task_ids: Optional[List[int]] = None,
    template_ids: Optional[List[int]] = None,
    eval_type_filter: Optional[List[str]] = None,
    no_reset_only: bool = False,
    exclude_na: bool = False,
    tasks_per_template: Optional[int] = None,
) -> List[dict]:
    """
    Load WebArena tasks from JSON and apply filters.

    Args:
        tasks_file: Path to the JSON file with WebArena tasks
        site_filter: Only include tasks for these sites (e.g., ["gitlab"])
        task_ids: Only include these specific task IDs
        template_ids: Only include tasks from these template families
        eval_type_filter: Only include tasks with these eval types (e.g., ["string_match"])
        no_reset_only: If True, only include tasks with require_reset=False
        exclude_na: If True, exclude unachievable tasks (fuzzy_match=N/A)
        tasks_per_template: If set, take at most N tasks per template group

    Returns:
        List of WebArena task config dicts with URLs replaced
    """
    with open(tasks_file, "r") as f:
        raw = json.load(f)
    all_tasks = raw["tasks"] if isinstance(raw, dict) else raw

    filtered = all_tasks

    if site_filter:
        site_set = set(s.lower() for s in site_filter)
        filtered = [
            t for t in filtered
            if all(s.lower() in site_set for s in t.get("sites", []))
        ]

    if task_ids is not None:
        id_set = set(task_ids)
        filtered = [t for t in filtered if t["task_id"] in id_set]

    if template_ids is not None:
        tmpl_set = set(template_ids)
        filtered = [t for t in filtered if t.get("intent_template_id") in tmpl_set]

    if eval_type_filter:
        eval_set = set(e.lower() for e in eval_type_filter)
        filtered = [
            t for t in filtered
            if eval_set.issubset(set(e.lower() for e in t["eval"]["eval_types"]))
        ]

    if no_reset_only:
        filtered = [t for t in filtered if not t.get("require_reset", False)]

    if exclude_na:
        def _is_na_task(t):
            ref = (t["eval"].get("reference_answers") or {})
            return ref.get("fuzzy_match") == "N/A" or ref.get("exact_match") == "N/A"
        filtered = [t for t in filtered if not _is_na_task(t)]

    if tasks_per_template is not None:
        by_template: dict = collections.defaultdict(list)
        for t in filtered:
            by_template[t.get("intent_template_id")].append(t)
        filtered = []
        for tmpl_id in sorted(by_template.keys()):
            filtered.extend(by_template[tmpl_id][:tasks_per_template])

    # Replace URL placeholders
    for task in filtered:
        task["start_url"] = replace_url_placeholders(task["start_url"])
        if task["eval"].get("reference_url"):
            task["eval"]["reference_url"] = replace_url_placeholders(
                task["eval"]["reference_url"]
            )
        # Also replace URLs inside program_html targets
        for target in task["eval"].get("program_html", []):
            if "url" in target:
                target["url"] = replace_url_placeholders(target["url"])
            if "alt_urls" in target:
                target["alt_urls"] = [replace_url_placeholders(u) for u in target["alt_urls"]]

        # Replace original WebArena hostnames in reference answers
        # (e.g., SSH clone commands use metis.lti.cs.cmu.edu)
        ref_answers = task["eval"].get("reference_answers")
        if ref_answers:
            for key in ("exact_match", "must_include"):
                val = ref_answers.get(key)
                if isinstance(val, str):
                    ref_answers[key] = replace_reference_hostnames(val)
                elif isinstance(val, list):
                    ref_answers[key] = [
                        replace_reference_hostnames(v) if isinstance(v, str) else v
                        for v in val
                    ]

    return filtered


def webarena_to_internal(wa_task: dict) -> tuple:
    """
    Convert a WebArena task config to our internal (task_id, task_config) format.

    Returns:
        (task_id_str, task_config_dict) compatible with run_single_task()
    """
    task_id = f"wa_{wa_task['task_id']}"

    sites = wa_task.get("sites", [])
    if "gitlab" in sites:
        suite = "webarena_gitlab"
    else:
        suite = f"webarena_{'_'.join(sites)}" if sites else "webarena_unknown"

    return task_id, {
        "name": f"WA-{wa_task['task_id']}: {wa_task['intent'][:60]}",
        "start_url": wa_task["start_url"],
        "suite": suite,
        "prompt": wa_task["intent"],
        "description": wa_task.get("intent_template", ""),
        "group": f"template_{wa_task['intent_template_id']}",
        "webarena_eval": wa_task["eval"],
        "webarena_task_id": wa_task["task_id"],
        "webarena_config": wa_task,
    }
