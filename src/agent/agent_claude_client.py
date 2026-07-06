import anthropic
import os
import time
import base64
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.agent.agent_base import AgentBase
from src.agent.qllm import QLLMTool, QLLMExecutor, ClaudeQLLMCaller


class AgentClaudeClient(AgentBase):
    """
    Claude API client that transforms Claude's tool_use format into actions.

    Claude API format:
    - Uses messages.create() instead of responses.create()
    - Returns content blocks: [{"type": "text", ...}, {"type": "tool_use", ...}]
    - Tool results are sent back as: {"type": "tool_result", "tool_use_id": "...", ...}
    """

    def __init__(
        self,
        computer,
        model="claude-sonnet-4-5-20250929",
        debug=False,
        system_prompt=None,
        results_dir="results",
        run_metadata=None,
        max_steps=120,
        system_prompt_name=None,
        auto_user_input: str | None = None,
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

        self.client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.messages: List[Dict] = []

        # qLLM string return_type is locked until a second chance is armed after
        # TASK UNSOLVABLE.
        self.tools = self._build_tools(allow_string=False)

        print(f"[AGENT INIT] Total tools available: {len(self.tools)}")
        for tool in self.tools:
            print(f"[AGENT INIT]   - {tool['name']}")

    def _build_tools(self, allow_string: bool = False) -> List[Dict]:
        tools = [self._computer_use_tool_def()]
        if self.system_prompt_name.startswith("ucm_defense") and self.qllm_executor:
            tools.append(QLLMTool.get_claude_format(allow_string=allow_string))
        return tools

    # ------------------------------------------------------------------
    # QLLM: reuse the same Anthropic client for QLLM
    # ------------------------------------------------------------------

    def _init_qllm(self):
        """Override: use the shared Anthropic client and current model."""
        print(f"[AGENT INIT] System prompt name is '{self.system_prompt_name}', "
              f"adding quarantined_llm_analysis tool")
        claude_api_key = os.getenv("ANTHROPIC_API_KEY")
        if not claude_api_key:
            print("WARNING: ANTHROPIC_API_KEY not set. "
                  "Quarantined LLM analysis will not work.")
            return
        client = anthropic.Anthropic(api_key=claude_api_key)
        qllm_caller = ClaudeQLLMCaller(client, model=self.QLLM_MODEL, debug=self.debug)
        self.qllm_executor = QLLMExecutor(qllm_caller, debug=self.debug)

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    @staticmethod
    def _computer_use_tool_def() -> Dict:
        return {
            "name": "computer_use",
            "description": "Control the computer by performing actions like clicking, "
                           "typing, scrolling, etc. Always include a screenshot in the response.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "object",
                        "description": "The computer action to perform",
                        "properties": {
                            "type": {
                                "type": "string",
                                "enum": ["click", "double_click", "scroll", "type",
                                         "keypress", "wait", "move", "drag",
                                         "screenshot", "goto"],
                                "description": "The type of action to perform",
                            },
                            "x": {"type": "integer", "description": "X coordinate"},
                            "y": {"type": "integer", "description": "Y coordinate"},
                            "button": {"type": "string",
                                       "description": "Mouse button: left, right, middle, back, forward, wheel"},
                            "text": {"type": "string", "description": "Text to type"},
                            "keys": {"type": "array", "items": {"type": "string"},
                                     "description": "Keys to press"},
                            "scroll_x": {"type": "integer", "description": "Horizontal scroll amount"},
                            "scroll_y": {"type": "integer", "description": "Vertical scroll amount"},
                            "ms": {"type": "integer", "description": "Milliseconds to wait"},
                            "path": {"type": "array", "description": "Path for drag operation"},
                            "url": {"type": "string", "description": "URL to navigate to"},
                        },
                        "required": ["type"],
                    }
                },
                "required": ["action"],
            },
        }

    # ------------------------------------------------------------------
    # Action parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _tool_use_input_as_dict(input_data) -> Dict[str, Any]:
        """Normalize Anthropic tool_use.input (dict or SDK object) to a plain dict."""
        if input_data is None:
            return {}
        if isinstance(input_data, dict):
            return input_data
        if hasattr(input_data, "model_dump"):
            try:
                return dict(input_data.model_dump())
            except Exception:
                pass
        try:
            from collections.abc import Mapping

            if isinstance(input_data, Mapping):
                return dict(input_data)
        except Exception:
            pass
        try:
            return dict(vars(input_data))
        except Exception:
            return {}

    def _claude_tool_use_to_action(self, tool_use) -> Optional[Dict[str, Any]]:
        """Transform Claude's tool_use format into our action format."""
        if hasattr(tool_use, 'name'):
            name = tool_use.name
            raw_input = tool_use.input if hasattr(tool_use, 'input') else {}
        else:
            name = tool_use.get("name")
            raw_input = tool_use.get("input", {})

        input_data = self._tool_use_input_as_dict(raw_input)

        if name == "computer_use":
            action = input_data.get("action", {})
            if not isinstance(action, dict):
                obj = action
                action = {}
                if obj is not None and hasattr(obj, "model_dump"):
                    try:
                        action = dict(obj.model_dump())
                    except Exception:
                        action = {}
                elif hasattr(obj, "__dict__"):
                    action = dict(obj.__dict__)
            return action

        if name == "quarantined_llm_analysis":
            raw_queries = input_data.get("queries", [])
            queries = [
                {
                    "query": q.get("query", "") if isinstance(q, dict) else getattr(q, "query", ""),
                    "return_type": q.get("return_type", "bool") if isinstance(q, dict) else getattr(q, "return_type", "bool"),
                    "return_constraints": (q.get("return_constraints") or {}) if isinstance(q, dict) else (getattr(q, "return_constraints", None) or {}),
                    "target": (q.get("target") or {}) if isinstance(q, dict) else (getattr(q, "target", None) or {}),
                }
                for q in (raw_queries or [])
            ]
            return {"type": "quarantined_llm_analysis", "queries": queries}

        return None

    # ------------------------------------------------------------------
    # Message conversion
    # ------------------------------------------------------------------

    def _convert_to_claude_message_with_screenshot(
        self, message: Dict[str, Any], screenshot_base64: str
    ) -> Dict[str, Any]:
        """Convert our message format to Claude's format, including screenshot."""
        role = message.get("role", "user")
        content = message.get("content", [])

        claude_content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": screenshot_base64,
                },
            }
        ]
        for block in content:
            if block.get("type") == "input_text":
                claude_content.append({"type": "text", "text": block.get("text", "")})

        return {"role": role, "content": claude_content}

    # ------------------------------------------------------------------
    # Main run loop
    # ------------------------------------------------------------------

    def run(self, initial_user_message):
        screenshot_base64 = self.take_screenshot_b64()
        self.save_screenshot(screenshot_base64, 0, "initial")

        claude_message = self._convert_to_claude_message_with_screenshot(
            initial_user_message, screenshot_base64
        )
        self.messages.append(claude_message)

        step = 1
        while True:
            if step > self.max_steps:
                print(f"\n⚠ Maximum step limit ({self.max_steps}) reached. Stopping run.")
                self.hit_max_steps = True
                self.log_task_end(step, "max_steps_reached", max_steps=self.max_steps)
                break

            warning_text = self.maybe_step_limit_warning_text(step)
            if warning_text:
                print(f"\n⚠ Step-limit warning emitted at step {step}.")
                self.messages.append({
                    "role": "user",
                    "content": [{"type": "text", "text": warning_text}],
                })

            print(f"\n=== Step {step} ===")

            log_entry = {
                "step": step,
                "timestamp": datetime.now().isoformat(),
                "messages_in_history": len(self.messages),
            }

            # ---- Call Claude API with retry ----
            api_kwargs = {
                "model": self.model,
                "max_tokens": 4096,
                "messages": self.messages,
                "tools": self.tools,
                "cache_control": {"type": "ephemeral"},
            }
            if self.system_prompt:
                api_kwargs["system"] = self.system_prompt

            response = self._call_api_with_retry(api_kwargs, log_entry)

            # Log raw API response
            self._log_raw_claude_response(response, step)
            self._log_claude_io_dump(step, api_kwargs, response)

            log_entry["response"] = {
                "stop_reason": response.stop_reason,
                "content_blocks_count": len(response.content),
            }

            # ---- Process response blocks ----
            tool_uses = []
            text_blocks = []
            response_content = []

            for block in response.content:
                if block.type == "text":
                    text_blocks.append(block.text)
                    response_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    tool_uses.append(block)
                    response_content.append({
                        "type": "tool_use", "name": block.name,
                        "id": block.id, "input": block.input,
                    })

            log_entry["response"]["content"] = response_content

            # ---- Handle text blocks ----
            if text_blocks:
                combined_text = "\n".join(text_blocks)
                task_complete = self.check_task_complete(combined_text)

                self.log_assistant_response(
                    step, combined_text, response.stop_reason, task_complete)

                for text in text_blocks:
                    print(f"Assistant: {text}")

                if task_complete:
                    print("\n✓ Model indicated task is complete!")
                    final_ss = self.take_screenshot_b64()
                    self.save_screenshot(final_ss, step, "final")
                    log_entry["task_complete"] = True
                    self.log_thoughts(log_entry)
                    return response

                if self.allow_unsolvable and self.check_task_unsolvable(combined_text):
                    # If ask-user is enabled and we haven't armed second chance yet,
                    # unlock the qLLM string return_type and inject a user message
                    # instead of terminating.
                    if self._arm_second_chance():
                        self.tools = self._build_tools(allow_string=True)
                        # Preserve the assistant turn.
                        self.messages.append({
                            "role": "assistant",
                            "content": [{"type": "text", "text": t} for t in text_blocks],
                        })
                        self.messages.append({
                            "role": "user",
                            "content": [{"type": "text", "text": self.SECOND_CHANCE_PROMPT}],
                        })
                        log_entry["second_chance_armed"] = True
                        self.log_thoughts(log_entry)
                        step += 1
                        continue

                    print("\n⚠ Model declared task unsolvable (QLLM limitation).")
                    self.hit_task_unsolvable = True
                    final_ss = self.take_screenshot_b64()
                    self.save_screenshot(final_ss, step, "final")
                    log_entry["task_unsolvable"] = True
                    self.log_thoughts(log_entry)
                    self.log_task_end(step, "task_unsolvable")
                    return response

            # ---- No tool uses: wait for user input ----
            if not tool_uses and response.stop_reason == "end_turn":
                log_entry["waiting_for_user_input"] = True
                self.log_thoughts(log_entry)
                self.log_waiting_for_user_input(step, response.stop_reason)

                user_input = self._get_user_input()
                screenshot_base64 = self.take_screenshot_b64()
                self.save_screenshot(screenshot_base64, step, "user_input")

                user_message = {"role": "user",
                                "content": [{"type": "input_text", "text": user_input}]}
                claude_message = self._convert_to_claude_message_with_screenshot(
                    user_message, screenshot_base64)
                self.messages.append(claude_message)
                step += 1
                continue

            # ---- Process tool uses ----
            if tool_uses:
                # Add assistant's response to conversation
                assistant_content = []
                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({"type": "text", "text": block.text})
                    elif block.type == "tool_use":
                        assistant_content.append({
                            "type": "tool_use", "id": block.id,
                            "name": block.name, "input": block.input,
                        })
                self.messages.append({"role": "assistant", "content": assistant_content})

                tool_use = tool_uses[0]
                tool_use_id = tool_use.id if hasattr(tool_use, 'id') else tool_use.get('id')
                tool_name = tool_use.name if hasattr(tool_use, 'name') \
                    else tool_use.get('name', 'unknown')

                action = self._claude_tool_use_to_action(tool_use)
                # IMPORTANT: empty dict {} is falsy but is still a `computer_use` parse result;
                # only None means the tool name is not handled.
                if action is None:
                    print(f"Unknown tool: {tool_name}")
                    self.messages.append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_use_id,
                                     "content": f"Error: Unknown tool {tool_name}"}],
                    })
                    step += 1
                    continue

                if tool_name == "computer_use" and not (
                    isinstance(action, dict) and action.get("type")
                ):
                    print(
                        "Malformed computer_use tool call: missing input.action.type "
                        f"(got {action!r})"
                    )
                    self.messages.append({
                        "role": "user",
                        "content": [{"type": "tool_result", "tool_use_id": tool_use_id,
                                     "content": (
                                         "Error: computer_use requires "
                                         '{"action": {"type": "click|type|scroll|...", ...}} '
                                         "with a non-empty action.type."
                                     )}],
                    })
                    step += 1
                    continue

                action_type = action.get("type")
                print(f"Action: {action_type}({action})")

                log_entry["action"] = {"type": action_type, "details": action}
                self.log_action(step, action_type, action)

                # ---- QLLM handling ----
                if action_type == "quarantined_llm_analysis":
                    results_text = self.execute_qllm_queries(action, log_entry, step)
                    tool_result_content = [{"type": "text", "text": results_text}]
                else:
                    # ---- Computer action ----
                    click_x, click_y = self._get_click_coords(action)

                    pre_screenshot = self.take_screenshot_b64()
                    self.save_screenshot(pre_screenshot, step, action_type,
                                        click_x=click_x, click_y=click_y)

                    self.handle_model_action(action)
                    self.post_action_stabilize(action_type)

                    post_screenshot = self.take_screenshot_b64()
                    log_entry["screenshot"] = {
                        "step": step, "filename": f"{step}.png",
                        "action_type": action_type,
                        "click_coords": {"x": click_x, "y": click_y}
                        if click_x is not None else None,
                    }
                    tool_result_content = [
                        {"type": "image", "source": {
                            "type": "base64", "media_type": "image/png",
                            "data": post_screenshot}},
                        {"type": "text",
                         "text": f"Action {action_type} completed successfully."},
                    ]

                self.messages.append({
                    "role": "user",
                    "content": [{"type": "tool_result",
                                 "tool_use_id": tool_use_id,
                                 "content": tool_result_content}],
                })
                self.log_thoughts(log_entry)
                step += 1
            else:
                log_entry["task_complete"] = False
                log_entry["reason"] = "no_more_actions"
                self.log_thoughts(log_entry)
                self.log_task_end(step, "no_more_actions")
                break

        self.close_log_file()
        return response

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_click_coords(action: Dict) -> tuple:
        action_type = action.get("type")
        if action_type in ("click", "double_click", "move"):
            return action.get("x"), action.get("y")
        return None, None

    def _get_user_input(self) -> str:
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

    def _call_api_with_retry(self, api_kwargs: Dict, log_entry: Dict,
                             max_retries: int = 3):
        retry_count = 0
        while retry_count < max_retries:
            try:
                return self.client.messages.create(**api_kwargs)
            except Exception as e:
                error_str = str(e)
                if any(kw in error_str.lower()
                       for kw in ("timeout", "timed out", "interrupted")):
                    retry_count += 1
                    if retry_count < max_retries:
                        wait = 2 ** retry_count
                        print(f"  API timeout (attempt {retry_count}/{max_retries}), "
                              f"retrying in {wait}s...")
                        time.sleep(wait)
                        continue
                    else:
                        print(f"  API timeout after {max_retries} attempts.")
                        log_entry["error"] = f"Timeout after {max_retries} retries"
                        self.log_thoughts(log_entry)
                        raise
                else:
                    print(f"  API error: {error_str}")
                    log_entry["error"] = error_str
                    self.log_thoughts(log_entry)
                    raise
        raise Exception("Failed to get response from API after retries")

    def _log_raw_claude_response(self, response, step: int):
        raw_entry = {
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "type": "raw_api_response",
            "model": self.model,
            "response": {
                "id": response.id,
                "type": response.type,
                "role": response.role,
                "content": [
                    {"type": b.type,
                     "text": b.text if hasattr(b, "text") else None,
                     "id": b.id if hasattr(b, "id") else None,
                     "name": b.name if hasattr(b, "name") else None,
                     "input": b.input if hasattr(b, "input") else None}
                    for b in response.content
                ],
                "model": response.model,
                "stop_reason": response.stop_reason,
                "stop_sequence": response.stop_sequence,
                "usage": {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                } if response.usage else None,
            },
        }
        self.log_raw_api(raw_entry)

        # Token usage logging
        self._log_claude_token_usage(response, step)

    def _log_claude_token_usage(self, response, step: int):
        usage = {}
        if response.usage:
            usage["input_tokens"] = response.usage.input_tokens
            usage["output_tokens"] = response.usage.output_tokens
            for field in ("cache_creation_input_tokens", "cache_read_input_tokens"):
                val = getattr(response.usage, field, None)
                if val is not None:
                    usage[field] = val

        output_text = []
        output_tool_calls = []
        for block in response.content:
            if block.type == "text":
                output_text.append(block.text)
            elif block.type == "tool_use":
                output_tool_calls.append({
                    "name": block.name,
                    "input": block.input,
                })

        self.log_token_usage({
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "model": self.model,
            "usage": usage,
            "output": {
                "text": output_text,
                "tool_calls": output_tool_calls,
            },
        })

    def _log_claude_io_dump(self, step: int, api_kwargs: dict, response):
        request_data = self._strip_base64({
            "model": api_kwargs.get("model"),
            "max_tokens": api_kwargs.get("max_tokens"),
            "system": api_kwargs.get("system"),
            "messages": api_kwargs.get("messages", []),
            "num_tools": len(api_kwargs.get("tools", [])),
        })

        try:
            response_data = response.model_dump()
        except Exception:
            response_data = {
                "id": response.id,
                "model": response.model,
                "stop_reason": response.stop_reason,
                "stop_sequence": response.stop_sequence,
                "content": [],
            }
            for block in response.content:
                if block.type == "text":
                    response_data["content"].append(
                        {"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    response_data["content"].append({
                        "type": "tool_use", "id": block.id,
                        "name": block.name, "input": block.input,
                    })
            if response.usage:
                response_data["usage"] = {
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }

        self.log_api_io({
            "step": step,
            "timestamp": datetime.now().isoformat(),
            "model": self.model,
            "request": request_data,
            "response": response_data,
        })
