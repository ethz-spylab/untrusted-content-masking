import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from src.agent.agent_base import AgentBase
from src.agent.qllm import QLLMTool

load_dotenv()

try:
    from openai import OpenAI
except ImportError as e:
    raise ImportError(
        "OpenAI agent requires a recent openai package. Install with: pip install -U openai"
    ) from e


class AgentGPT54OpenAIClient(AgentBase):
    """
    GPT-5.4 Computer Use client.

    This implementation follows the OpenAI built-in computer tool loop:
      1. Send the task with tools=[{"type": "computer_use_preview", ...}]
      2. Read computer_call item(s) from the response output
      3. Execute action(s)
      4. Send back a computer_call_output containing a screenshot
      5. Repeat until no computer_call remains

    GPT-5.4 uses the same Responses API surface as computer-use-preview but
    is a general-purpose model with native CUA training.

    The QLLM component uses Claude independently of the main agent model.
    """

    ACTION_TYPE_MAP = {
        "click": "click",
        "double_click": "double_click",
        "scroll": "scroll",
        "type": "type",
        "keypress": "keypress",
        "wait": "wait",
        "drag": "drag",
        "screenshot": "screenshot",
        "move": "move",
    }

    # Whitelist of parameters we forward to the computer abstraction per action type.
    # Prevents unexpected kwargs from crashing the underlying computer driver.
    PARAM_WHITELIST: Dict[str, List[str]] = {
        "click": ["x", "y", "button"],
        "double_click": ["x", "y", "button"],
        "move": ["x", "y"],
        "scroll": ["x", "y", "scroll_x", "scroll_y"],
        "type": ["text"],
        "keypress": ["keys"],
        "wait": ["ms"],
        "drag": ["path"],
        "screenshot": [],
    }

    def __init__(
        self,
        computer,
        model: str = "gpt-5.4",
        debug: bool = False,
        system_prompt: Optional[str] = None,
        results_dir: str = "results",
        run_metadata: Optional[Dict[str, Any]] = None,
        max_steps: int = 120,
        system_prompt_name: Optional[str] = None,
        auto_user_input: Optional[str] = None,
        display_width: int = 1024,
        display_height: int = 768,
        environment: str = "browser",
        reasoning_effort: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(
            computer=computer,
            model=model,
            debug=debug,
            system_prompt=system_prompt,
            results_dir=results_dir,
            run_metadata=run_metadata,
            max_steps=max_steps,
            system_prompt_name=system_prompt_name,
            auto_user_input=auto_user_input,
            **kwargs,
        )

        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.display_width = display_width
        self.display_height = display_height
        self.environment = environment
        self.request_timeout_s = float(os.getenv("OPENAI_RESPONSE_TIMEOUT_SECS", "120"))
        self.reasoning_effort = reasoning_effort or os.getenv("OPENAI_GPT54_REASONING_EFFORT", "medium")
        self.previous_response_id: Optional[str] = None

        print("[AGENT INIT] GPT-5.4 OpenAI client initialized")
        print(f"[AGENT INIT] Model: {self.model}")
        print(f"[AGENT INIT] Display: {self.display_width}x{self.display_height}")
        print(f"[AGENT INIT] Environment: {self.environment}")
        print(f"[AGENT INIT] Reasoning effort: {self.reasoning_effort}")
        print(f"[AGENT INIT] OpenAI request timeout: {self.request_timeout_s:.0f}s")

    # ------------------------------------------------------------------
    # Tool configuration
    # ------------------------------------------------------------------

    def _build_tools(self, allow_string: bool = False) -> List[Dict[str, Any]]:
        """Build the tools list for the Responses API request.

        GPT-5.4 uses the ``computer`` tool type (not ``computer_use_preview``).

        When ``allow_string`` is True (only after the second-chance intercept
        fires on TASK UNSOLVABLE), the qLLM schema gains a ``"string"`` return
        type.
        """
        tools: List[Dict[str, Any]] = [
            {
                "type": "computer",
            }
        ]
        if self.system_prompt_name == "ucm_defense" and self.qllm_executor:
            tools.append(QLLMTool.get_openai_responses_format(allow_string=allow_string))
        return tools

    def _base_request_kwargs(self) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "tools": self._build_tools(allow_string=self._second_chance_unlocked),
            "truncation": "auto",
        }
        if self.reasoning_effort and self.reasoning_effort != "none":
            kwargs["reasoning"] = {
                "effort": self.reasoning_effort,
                "summary": "auto",
            }
        return kwargs

    # ------------------------------------------------------------------
    # Response parsing helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _obj_get(item: Any, key: str, default=None):
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)

    @classmethod
    def _normalize_action(cls, action: Any) -> Dict[str, Any]:
        if action is None:
            return {}
        if isinstance(action, dict):
            raw = dict(action)
        elif hasattr(action, "__dict__"):
            raw = {k: v for k, v in vars(action).items() if not k.startswith("_")}
        else:
            raw = {}

        action_type = cls.ACTION_TYPE_MAP.get(raw.get("type", ""), raw.get("type", ""))
        result: Dict[str, Any] = {"type": action_type}

        if action_type in ("click", "double_click", "move"):
            result["x"] = raw.get("x")
            result["y"] = raw.get("y")
            if action_type in ("click", "double_click"):
                result["button"] = raw.get("button", "left")
        elif action_type == "scroll":
            result["x"] = raw.get("x", 0)
            result["y"] = raw.get("y", 0)
            result["scroll_x"] = raw.get("scroll_x", raw.get("scrollX", 0))
            result["scroll_y"] = raw.get("scroll_y", raw.get("scrollY", 0))
        elif action_type == "type":
            result["text"] = raw.get("text", "")
        elif action_type == "keypress":
            result["keys"] = raw.get("keys", [])
        elif action_type == "wait":
            result["ms"] = raw.get("ms", 2000)
        elif action_type == "drag":
            result["path"] = cls._normalize_drag_path(raw.get("path", []) or [])
        return result

    @staticmethod
    def _normalize_drag_path(raw_path: List[Any]) -> List[Dict[str, int]]:
        path: List[Dict[str, int]] = []
        for point in raw_path:
            if hasattr(point, "x") and hasattr(point, "y"):
                path.append({"x": int(point.x), "y": int(point.y)})
            elif isinstance(point, dict) and "x" in point and "y" in point:
                path.append({"x": int(point["x"]), "y": int(point["y"])})
            elif isinstance(point, (list, tuple)) and len(point) >= 2:
                path.append({"x": int(point[0]), "y": int(point[1])})
            elif hasattr(point, "__dict__"):
                p = vars(point)
                if "x" in p and "y" in p:
                    path.append({"x": int(p["x"]), "y": int(p["y"])})
        return path

    def _extract_computer_calls(self, response: Any) -> List[Dict[str, Any]]:
        """Extract computer_call items from the response output.

        The API returns a single ``action`` object per computer_call.
        We also defensively check for ``actions`` (plural) in case the
        API surface evolves.
        """
        calls: List[Dict[str, Any]] = []
        for item in getattr(response, "output", []) or []:
            if self._obj_get(item, "type") != "computer_call":
                continue

            # Prefer actions[] batch if present; fall back to single action
            actions = self._obj_get(item, "actions")
            if not actions:
                legacy_action = self._obj_get(item, "action")
                actions = [legacy_action] if legacy_action else []

            # Collect pending safety checks so we can acknowledge them
            pending_safety_checks = self._obj_get(item, "pending_safety_checks") or []

            calls.append(
                {
                    "call_id": self._obj_get(item, "call_id"),
                    "actions": [self._normalize_action(a) for a in (actions or [])],
                    "status": self._obj_get(item, "status"),
                    "pending_safety_checks": pending_safety_checks,
                }
            )
        return calls

    def _extract_function_calls(self, response: Any) -> List[Dict[str, Any]]:
        calls: List[Dict[str, Any]] = []
        for item in getattr(response, "output", []) or []:
            if self._obj_get(item, "type") != "function_call":
                continue
            calls.append(
                {
                    "type": "function_call",
                    "call_id": self._obj_get(item, "call_id"),
                    "name": self._obj_get(item, "name", ""),
                    "arguments": self._obj_get(item, "arguments", "{}"),
                }
            )
        return calls

    def _extract_text_and_phase(self, response: Any) -> Tuple[List[str], Optional[str]]:
        texts: List[str] = []
        latest_phase: Optional[str] = None

        for item in getattr(response, "output", []) or []:
            item_type = self._obj_get(item, "type")

            if item_type == "message":
                phase = self._obj_get(item, "phase")
                if isinstance(phase, str) or phase is None:
                    latest_phase = phase

                content = self._obj_get(item, "content", []) or []
                for content_item in content:
                    c_type = self._obj_get(content_item, "type")
                    if c_type in ("output_text", "text"):
                        text = self._obj_get(content_item, "text", "")
                        if text:
                            texts.append(text)

            elif item_type == "text":
                text = self._obj_get(item, "text", "")
                if text:
                    texts.append(text)

            elif item_type == "reasoning":
                for summary_item in self._obj_get(item, "summary", []) or []:
                    text = self._obj_get(summary_item, "text")
                    if text:
                        texts.append(f"[Reasoning] {text}")

        return texts, latest_phase

    def _function_call_to_action(self, function_call: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        name = function_call.get("name", "")
        arguments = function_call.get("arguments", "{}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        if name == "quarantined_llm_analysis":
            raw_queries = arguments.get("queries", []) or []
            queries = [
                {
                    "query": q.get("query", ""),
                    "return_type": q.get("return_type", "bool"),
                    "return_constraints": q.get("return_constraints") or {},
                    "target": q.get("target") or {},
                }
                for q in raw_queries
            ]
            return {"type": "quarantined_llm_analysis", "queries": queries}
        return None

    # ------------------------------------------------------------------
    # Action execution
    # ------------------------------------------------------------------

    def handle_model_action(self, action: Dict[str, Any], call_id=None, pending_safety_checks=None):
        action_type = action.get("type")
        if action_type in (None, "quarantined_llm_analysis", "screenshot"):
            return

        if self._is_blocked_type_action(action):
            return

        action_args = {k: v for k, v in action.items() if k != "type"}
        allowed = self.PARAM_WHITELIST.get(action_type, [])
        action_args = {k: v for k, v in action_args.items() if k in allowed}

        if action_type == "scroll":
            action_args.setdefault("scroll_x", 0)
            action_args.setdefault("scroll_y", 0)
            action_args.setdefault("x", self.display_width // 2)
            action_args.setdefault("y", self.display_height // 2)

        if action_type == "keypress":
            key_map = {
                "ENTER": "Return",
                "RETURN": "Return",
                "SPACE": "space",
                "TAB": "Tab",
                "ESCAPE": "Escape",
                "ESC": "Escape",
                "BACKSPACE": "BackSpace",
                "DELETE": "Delete",
            }
            keys = action_args.get("keys", []) or []
            action_args["keys"] = [
                key_map.get(k.upper(), k) if isinstance(k, str) else str(k)
                for k in keys
            ]

        method = getattr(self.computer, action_type, None)
        if method is None:
            print(f"Unknown action type: {action_type}")
            return

        try:
            method(**action_args)
        except Exception as e:
            print(f"Error executing action {action_type}: {e}")

    @staticmethod
    def _get_click_coords(action: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
        if action.get("type") in ("click", "double_click", "move"):
            return action.get("x"), action.get("y")
        return None, None

    def _execute_action_batch(self, actions: List[Dict[str, Any]], step: int, log_entry: Dict[str, Any]) -> None:
        self._current_step = step  # Track for blocked-action logging
        for batch_idx, action in enumerate(actions, start=1):
            action_type = action.get("type")
            click_x, click_y = self._get_click_coords(action)

            print(f"Action {batch_idx}/{len(actions)}: {action_type}({action})")
            self.log_action(step, action_type, action)

            pre_screenshot = self.take_screenshot_b64()
            suffix = action_type if len(actions) == 1 else f"{action_type}_{batch_idx}"
            self.save_screenshot(pre_screenshot, step, suffix, click_x=click_x, click_y=click_y)

            if action_type != "screenshot":
                self.handle_model_action(action)
                self.post_action_stabilize(action_type)

            log_entry.setdefault("actions", []).append(
                {
                    "type": action_type,
                    "details": action,
                    "click_coords": {"x": click_x, "y": click_y} if click_x is not None else None,
                }
            )

    # ------------------------------------------------------------------
    # Request helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        name = exc.__class__.__name__.lower()
        msg = str(exc).lower()
        return (
            "timeout" in name
            or "timed out" in msg
            or "deadline exceeded" in msg
            or "request timeout" in msg
        )

    @staticmethod
    def _is_retryable_error(exc: Exception) -> bool:
        name = exc.__class__.__name__.lower()
        msg = str(exc).lower()
        if ("timeout" in name or "timed out" in msg or "deadline exceeded" in msg or "request timeout" in msg):
            return True
        if "rate" in msg and "limit" in msg:
            return True
        if "429" in msg or "ratelimit" in name:
            return True
        if any(code in msg for code in ("500", "502", "503", "504", "overloaded", "server error")):
            return True
        if any(kw in msg for kw in ("connection", "connect", "eof", "reset", "temporarily unavailable")):
            return True
        return False

    def _responses_create(self, max_retries: int = 3, **kwargs):
        retry_count = 0
        while retry_count < max_retries:
            try:
                return self.client.responses.create(**kwargs)
            except Exception as e:
                if self._is_retryable_error(e):
                    retry_count += 1
                    if retry_count < max_retries:
                        wait = 2 ** retry_count
                        print(f"  OpenAI API error (attempt {retry_count}/{max_retries}): {e}")
                        print(f"  Retrying in {wait}s...")
                        time.sleep(wait)
                        continue
                    if self._is_timeout_error(e):
                        raise TimeoutError(
                            f"OpenAI Responses API timeout after {max_retries} retries"
                        ) from e
                raise
        raise RuntimeError("Failed to get response from OpenAI API after retries")

    def _make_initial_request(self, task_prompt: str, screenshot_base64: Optional[str] = None):
        api_input: List[Dict[str, Any]] = []
        if self.system_prompt:
            api_input.append(
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": self.system_prompt}],
                }
            )

        # Include an initial screenshot so the model sees the browser state
        initial_screenshot = screenshot_base64 or self.take_screenshot_b64()
        user_content: List[Dict[str, Any]] = [
            {"type": "input_text", "text": task_prompt},
            {
                "type": "input_image",
                "image_url": f"data:image/png;base64,{initial_screenshot}",
            },
        ]
        api_input.append({"role": "user", "content": user_content})

        kwargs = self._base_request_kwargs()
        kwargs["input"] = api_input
        response = self._responses_create(**kwargs)
        self._last_api_input = api_input
        return response

    def _make_user_prompt_request(self, prompt_text: str):
        api_input = [
            {
                "role": "user",
                "content": [{"type": "input_text", "text": prompt_text}],
            }
        ]
        kwargs = self._base_request_kwargs()
        kwargs["previous_response_id"] = self.previous_response_id
        kwargs["input"] = api_input
        response = self._responses_create(**kwargs)
        self._last_api_input = api_input
        return response

    def _make_computer_output_request(
        self,
        call_id: str,
        screenshot_base64: str,
        pending_safety_checks: Optional[List[Any]] = None,
    ):
        """Send a computer_call_output back to the model.

        Acknowledges any pending safety checks returned on the computer_call.
        Uses ``computer_screenshot`` output type per the documented CUA loop.
        """
        # Acknowledge pending safety checks
        acknowledged: List[Dict[str, str]] = []
        if pending_safety_checks:
            for sc in pending_safety_checks:
                sc_id = sc.get("id") if isinstance(sc, dict) else getattr(sc, "id", None)
                sc_code = sc.get("code", "") if isinstance(sc, dict) else getattr(sc, "code", "")
                sc_message = sc.get("message", "") if isinstance(sc, dict) else getattr(sc, "message", "")
                if sc_id:
                    acknowledged.append({"id": sc_id, "code": sc_code, "message": sc_message})
            if acknowledged:
                print(f"  Acknowledging safety checks: {acknowledged}")

        output_payload: Dict[str, Any] = {
            "type": "computer_call_output",
            "call_id": call_id,
            "output": {
                "type": "computer_screenshot",
                "image_url": f"data:image/png;base64,{screenshot_base64}",
                "detail": "original",
            },
        }
        if acknowledged:
            output_payload["acknowledged_safety_checks"] = acknowledged

        api_input = [output_payload]
        kwargs = self._base_request_kwargs()
        kwargs["previous_response_id"] = self.previous_response_id
        kwargs["input"] = api_input
        response = self._responses_create(**kwargs)
        self._last_api_input = api_input
        return response

    def _make_function_output_request(self, outputs: List[Dict[str, Any]]):
        kwargs = self._base_request_kwargs()
        kwargs["previous_response_id"] = self.previous_response_id
        kwargs["input"] = outputs
        response = self._responses_create(**kwargs)
        self._last_api_input = outputs
        return response

    # ------------------------------------------------------------------
    # Completion helpers
    # ------------------------------------------------------------------

    def _get_user_input(self) -> str:
        """Get user input, using auto_user_input if configured."""
        if self.auto_user_input is not None:
            print(f"> {self.auto_user_input}")
            return self.auto_user_input
        try:
            return input("> ")
        except EOFError:
            fallback = ("Solve this task on your own. If you believe the task "
                        "is completed, output TASK COMPLETE.")
            print(f"> {fallback}")
            return fallback

    def _is_asking_confirmation(self, text_blocks: List[str]) -> bool:
        all_text = "\n".join(text_blocks).lower() if text_blocks else ""
        phrases = [
            "would you like",
            "do you want",
            "shall i",
            "should i",
            "can i proceed",
            "ready to proceed",
            "let me know",
            "please confirm",
            "want me to",
        ]
        return any(p in all_text for p in phrases)

    def _should_finish(self, combined_text: str, latest_phase: Optional[str], has_tool_calls: bool) -> bool:
        if has_tool_calls:
            return False
        # "TASK UNSOLVABLE" is NOT completion — let the dedicated unsolvable
        # branch (which arms the second-chance intercept) handle it.
        if self.allow_unsolvable and self.check_task_unsolvable(combined_text):
            return False
        if self.check_task_complete(combined_text):
            return True
        if latest_phase == "final_answer" and combined_text.strip():
            return True
        return False

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_base64(data: Any) -> Any:
        """Recursively replace base64 image data with a short placeholder
        to keep log dumps human-readable."""
        if isinstance(data, str):
            if len(data) > 200 and data.startswith("data:image"):
                return data[:40] + "...<base64 truncated>"
            return data
        if isinstance(data, list):
            return [AgentGPT54OpenAIClient._strip_base64(item) for item in data]
        if isinstance(data, dict):
            return {k: AgentGPT54OpenAIClient._strip_base64(v) for k, v in data.items()}
        return data

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self, initial_user_message):
        initial_screenshot = self.take_screenshot_b64()
        self.save_screenshot(initial_screenshot, 0, "initial")

        task_prompt = ""
        for block in initial_user_message.get("content", []):
            if isinstance(block, dict) and block.get("type") == "input_text":
                task_prompt = block.get("text", "")
                break
            if isinstance(block, str):
                task_prompt = block
                break

        step = 1
        consecutive_no_action = 0
        max_consecutive_no_action = 3

        print(f"\n=== Step {step} (Initial Request) ===")
        try:
            response = self._make_initial_request(task_prompt, screenshot_base64=initial_screenshot)
            self.previous_response_id = response.id
        except Exception as e:
            self.log_thoughts({"step": step, "timestamp": datetime.now().isoformat(), "type": "error", "error": str(e)})
            raise

        self._log_raw_openai_response(response, step)
        self._log_openai_io_dump(step, response)

        while True:
            if step > self.max_steps:
                print(f"\n⚠ Maximum step limit ({self.max_steps}) reached.")
                self.hit_max_steps = True
                self.log_task_end(step, "max_steps_reached", max_steps=self.max_steps)
                break

            warning_text = self.maybe_step_limit_warning_text(step)
            if warning_text:
                print(f"\n⚠ Step-limit warning emitted at step {step}.")
                response = self._make_user_prompt_request(warning_text)
                self.previous_response_id = response.id
                self._log_raw_openai_response(response, step)
                self._log_openai_io_dump(step, response)

            log_entry: Dict[str, Any] = {
                "step": step,
                "timestamp": datetime.now().isoformat(),
                "response_id": self.previous_response_id,
            }

            text_blocks, latest_phase = self._extract_text_and_phase(response)
            function_calls = self._extract_function_calls(response)
            computer_calls = self._extract_computer_calls(response)
            has_tool_calls = bool(function_calls or computer_calls)

            if text_blocks:
                combined_text = "\n".join(text_blocks)
                task_complete = self._should_finish(combined_text, latest_phase, has_tool_calls)
                self.log_assistant_response(step, combined_text, "end_turn", task_complete)
                for text in text_blocks:
                    print(f"Assistant: {text}")
                if task_complete:
                    print("\n✓ Model indicated task is complete!")
                    final_ss = self.take_screenshot_b64()
                    self.save_screenshot(final_ss, step, "final")
                    log_entry["task_complete"] = True
                    log_entry["phase"] = latest_phase
                    self.log_thoughts(log_entry)
                    self.close_log_file()
                    return response

                if self.allow_unsolvable and self.check_task_unsolvable(combined_text):
                    # Second-chance intercept: if ask-user is armed, unlock the
                    # qLLM string return_type (each call is user-gated) instead
                    # of terminating.
                    if self._arm_second_chance():
                        log_entry["second_chance_armed"] = True
                        self.log_thoughts(log_entry)
                        # Send the second-chance instruction as a user turn;
                        # next iteration will receive the unlocked tool schema
                        # because _base_request_kwargs checks
                        # _second_chance_unlocked when building tools.
                        response = self._make_user_prompt_request(
                            self.SECOND_CHANCE_PROMPT)
                        self.previous_response_id = response.id
                        self._log_raw_openai_response(response, step)
                        self._log_openai_io_dump(step, response)
                        step += 1
                        continue

                    print("\n⚠ Model declared task unsolvable (QLLM limitation).")
                    self.hit_task_unsolvable = True
                    final_ss = self.take_screenshot_b64()
                    self.save_screenshot(final_ss, step, "final")
                    log_entry["task_unsolvable"] = True
                    self.log_thoughts(log_entry)
                    self.log_task_end(step, "task_unsolvable")
                    self.close_log_file()
                    return response

            # ── QLLM function calls ──────────────────────────────────
            if function_calls and self.qllm_executor:
                consecutive_no_action = 0
                outputs: List[Dict[str, Any]] = []
                for function_call in function_calls:
                    call_id = function_call.get("call_id")
                    action = self._function_call_to_action(function_call)
                    if action and action.get("type") == "quarantined_llm_analysis":
                        print(f"\n=== Step {step} (QLLM Analysis, call_id={call_id}) ===")
                        print(f"Action: quarantined_llm_analysis({action})")
                        self.log_action(step, "quarantined_llm_analysis", action)
                        result_text = self.execute_qllm_queries(action, log_entry, step)
                    else:
                        result_text = json.dumps({"error": "unknown function"})
                    outputs.append({"type": "function_call_output", "call_id": call_id, "output": result_text})

                response = self._make_function_output_request(outputs)
                self.previous_response_id = response.id
                self._log_raw_openai_response(response, step)
                self._log_openai_io_dump(step, response)
                self.log_thoughts(log_entry)
                step += 1
                continue

            # ── Computer calls ────────────────────────────────────────
            if computer_calls:
                consecutive_no_action = 0
                # Process each computer_call; each one expects a screenshot back.
                for idx, computer_call in enumerate(computer_calls, start=1):
                    call_id = computer_call.get("call_id")
                    actions = computer_call.get("actions", [])
                    pending_safety_checks = computer_call.get("pending_safety_checks", [])
                    print(f"\n=== Step {step} (computer call {idx}/{len(computer_calls)}) ===")
                    print(f"Computer call id: {call_id}")
                    log_entry.setdefault("computer_calls", []).append(
                        {"call_id": call_id, "actions": actions, "status": computer_call.get("status")}
                    )
                    if actions:
                        self._execute_action_batch(actions, step, log_entry)
                    else:
                        print("Computer call had no actions; sending fresh screenshot anyway.")

                    screenshot_base64 = self.take_screenshot_b64()
                    response = self._make_computer_output_request(
                        call_id, screenshot_base64,
                        pending_safety_checks=pending_safety_checks,
                    )
                    self.previous_response_id = response.id
                    self._log_raw_openai_response(response, step)
                    self._log_openai_io_dump(step, response)

                self.log_thoughts(log_entry)
                step += 1
                continue

            # ── No tool call: confirmation or idle ────────────────────
            is_asking = self._is_asking_confirmation(text_blocks)
            if is_asking:
                prompt = (
                    "Yes, proceed immediately. Do NOT ask for confirmation again. "
                    "Complete the task now and output:\n"
                    "Answer: <r>\nTASK COMPLETE"
                )
            else:
                consecutive_no_action += 1
                print(
                    f"No tool call found (attempt {consecutive_no_action}/{max_consecutive_no_action}, phase={latest_phase})"
                )
                if consecutive_no_action >= max_consecutive_no_action:
                    print("Max consecutive no-action responses reached. Ending.")
                    self.log_task_end(step, "max_no_action_prompts")
                    self.log_thoughts(log_entry)
                    break
                prompt = self._get_user_input()

            print(f"Prompting model: {prompt[:80]}...")
            log_entry["reason"] = "prompting_model"
            log_entry["phase"] = latest_phase
            log_entry["is_confirmation_request"] = is_asking
            self.log_thoughts(log_entry)
            response = self._make_user_prompt_request(prompt)
            self.previous_response_id = response.id
            self._log_raw_openai_response(response, step)
            self._log_openai_io_dump(step, response)
            step += 1
            continue

        self.close_log_file()
        return response

    # ------------------------------------------------------------------
    # Logging helpers
    # ------------------------------------------------------------------

    def _log_raw_openai_response(self, response, step: int):
        try:
            def _ser(v):
                if v is None or isinstance(v, (str, int, float, bool)):
                    return v
                if isinstance(v, (list, tuple)):
                    return [_ser(x) for x in v]
                if isinstance(v, dict):
                    return {k: _ser(val) for k, val in v.items()}
                if hasattr(v, "__dict__"):
                    return {k: _ser(val) for k, val in vars(v).items() if not k.startswith("_")}
                return str(v)

            items = []
            for item in getattr(response, "output", []) or []:
                d = {}
                for attr in ("type", "id", "call_id", "name", "arguments", "actions", "action", "status", "phase", "content", "summary"):
                    if hasattr(item, attr):
                        d[attr] = _ser(getattr(item, attr))
                items.append(d)

            self.log_raw_api(
                {
                    "step": step,
                    "timestamp": datetime.now().isoformat(),
                    "type": "raw_api_response",
                    "model": self.model,
                    "response": {
                        "id": getattr(response, "id", None),
                        "output": items,
                    },
                }
            )
        except Exception as e:
            print(f"Warning: Could not log raw response: {e}")

        self._log_openai_token_usage(response, step)

    @staticmethod
    def _usage_details_to_dict(details) -> Dict[str, Any]:
        if details is None:
            return {}
        if isinstance(details, dict):
            return details
        if hasattr(details, "__dict__"):
            return {k: v for k, v in vars(details).items() if not k.startswith("_") and v is not None}
        return {}

    def _log_openai_token_usage(self, response, step: int):
        usage: Dict[str, Any] = {}
        resp_usage = getattr(response, "usage", None)
        if resp_usage:
            usage["input_tokens"] = getattr(resp_usage, "input_tokens", None)
            usage["output_tokens"] = getattr(resp_usage, "output_tokens", None)
            usage["total_tokens"] = getattr(resp_usage, "total_tokens", None)
            input_details = self._usage_details_to_dict(getattr(resp_usage, "input_tokens_details", None))
            if input_details:
                usage["input_tokens_details"] = input_details
            output_details = self._usage_details_to_dict(getattr(resp_usage, "output_tokens_details", None))
            if output_details:
                usage["output_tokens_details"] = output_details

        output_text, _ = self._extract_text_and_phase(response)
        output_tool_calls = []
        for function_call in self._extract_function_calls(response):
            output_tool_calls.append({
                "name": function_call.get("name"),
                "arguments": function_call.get("arguments"),
            })
        for computer_call in self._extract_computer_calls(response):
            output_tool_calls.append({
                "name": "computer",
                "call_id": computer_call.get("call_id"),
                "actions": computer_call.get("actions", []),
            })

        self.log_token_usage(
            {
                "step": step,
                "timestamp": datetime.now().isoformat(),
                "model": self.model,
                "usage": usage,
                "output": {
                    "text": output_text,
                    "tool_calls": output_tool_calls,
                },
            }
        )

    def _log_openai_io_dump(self, step: int, response):
        try:
            def _ser(v):
                if v is None or isinstance(v, (str, int, float, bool)):
                    return v
                if isinstance(v, (list, tuple)):
                    return [_ser(x) for x in v]
                if isinstance(v, dict):
                    return {k: _ser(val) for k, val in v.items()}
                if hasattr(v, "__dict__"):
                    return {k: _ser(val) for k, val in vars(v).items() if not k.startswith("_")}
                return str(v)

            raw_input = getattr(self, "_last_api_input", None) or []
            request_data = {
                "model": self.model,
                "previous_response_id": self.previous_response_id,
                "input": self._strip_base64(raw_input),
                "tools": self._build_tools(allow_string=self._second_chance_unlocked),
                "reasoning": {"effort": self.reasoning_effort, "summary": "auto"} if self.reasoning_effort else None,
            }

            response_data = {
                "id": getattr(response, "id", None),
                "output": [],
            }
            resp_usage = getattr(response, "usage", None)
            if resp_usage:
                response_data["usage"] = _ser(resp_usage)
            for item in getattr(response, "output", []) or []:
                d = {}
                for attr in ("type", "id", "call_id", "name", "arguments", "actions", "action", "content", "summary", "status", "phase"):
                    if hasattr(item, attr):
                        d[attr] = _ser(getattr(item, attr))
                response_data["output"].append(d)

            self.log_api_io(
                {
                    "step": step,
                    "timestamp": datetime.now().isoformat(),
                    "model": self.model,
                    "request": request_data,
                    "response": response_data,
                }
            )
        except Exception as e:
            print(f"Warning: Could not log IO dump: {e}")