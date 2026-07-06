"""
Claude-specific QLLM provider implementation.

This module provides:
- ClaudeQLLMCaller: Calls Claude API for quarantined analysis
- Logging utilities for security monitoring
"""

import json
import requests
from datetime import datetime


class ClaudeQLLMCaller:
    """
    Calls Claude API for quarantined LLM analysis.
    
    This is a thin wrapper around the Anthropic Claude API that:
    1. Takes system and user prompts
    2. Calls Claude with appropriate settings
    3. Returns the raw text response
    """
    
    def __init__(self, anthropic_client, model: str = "claude-sonnet-4-5-20250929", debug: bool = False):
        """
        Initialize Claude QLLM caller.
        
        Args:
            anthropic_client: Initialized anthropic.Anthropic() client
            model: Claude model to use for quarantined analysis
            debug: Enable debug logging
        """
        self.client = anthropic_client
        self.model = model
        self.debug = debug
    
    def call(self, system_prompt: str, user_prompt: str) -> tuple:
        """
        Call Claude API and return raw text response with token usage.

        Args:
            system_prompt: System instruction for the QLLM
            user_prompt: User question/prompt with content to analyze

        Returns:
            Tuple of (text_response, usage_dict) where usage_dict contains
            input_tokens, output_tokens, and optional cache token fields.

        Raises:
            Exception: If API call fails
        """
        if self.debug:
            print(f"[ClaudeQLLMCaller] Calling model: {self.model}")
            print(f"[ClaudeQLLMCaller] System prompt length: {len(system_prompt)} chars")
            print(f"[ClaudeQLLMCaller] User prompt length: {len(user_prompt)} chars")

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=500,
                cache_control={"type": "ephemeral"},
                system=system_prompt,
                messages=[{
                    "role": "user",
                    "content": [{"type": "text", "text": user_prompt}]
                }]
            )

            # Extract text from response
            result_text = ""
            for block in response.content:
                if block.type == "text":
                    result_text += block.text + "\n"

            # Extract token usage
            usage = {}
            if response.usage:
                usage["input_tokens"] = response.usage.input_tokens
                usage["output_tokens"] = response.usage.output_tokens
                for field in ("cache_creation_input_tokens", "cache_read_input_tokens"):
                    val = getattr(response.usage, field, None)
                    if val is not None:
                        usage[field] = val

            return result_text.strip(), usage

        except Exception as e:
            if self.debug:
                print(f"[ClaudeQLLMCaller] API call failed: {e}")
            raise


def log_quarantined_llm_usage(
    query: str,
    result: str,
    url: str = None,
    target: dict = None,
    return_type: str = "bool",
    debug: bool = False
):
    """
    Log quarantined LLM usage to security log servers.
    
    This sends a log entry to various security log endpoints to track
    when the quarantined LLM tool is used. This helps monitor for potential
    abuse or prompt injection attempts.
    
    Args:
        query: The query sent to QLLM
        result: The result returned by QLLM
        url: Current page URL
        target: Target element specification
        return_type: Type of result requested
        debug: Enable debug logging
    """
    try:
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "quarantinedLlmUsage": True,
            "quarantinedLlmQuery": query,
            "quarantinedLlmResult": result,
            "quarantinedLlmReturnType": return_type,
            "quarantinedLlmUrl": url or "",
            "quarantinedLlmTarget": target or {},
            "quarantinedLlmTimestamp": datetime.now().isoformat()
        }
        
        # Try to send to various log servers
        log_urls = [
            "http://ecommerce-search.com/logs/write",
            "http://calendar.com/logs/write",
            "http://banking.com/logs/write",
            "http://support.com/logs/write",
            "http://webmail.com/logs/write",
            "http://jobs.com/logs/write",
            "http://restaurant.com/logs/write",
            "http://travel.com/logs/write",
            "http://wiki.com/logs/write",
            "http://forum.com/logs/write",
        ]
        
        for log_url in log_urls:
            try:
                response = requests.post(
                    log_url,
                    json=log_entry,
                    headers={"Content-Type": "application/json"},
                    timeout=1
                )
                if response.status_code == 200:
                    if debug:
                        print(f"[Security Log] Logged quarantined LLM usage to {log_url}")
                    break
            except Exception:
                # Silently fail - log server might not be available for all sites
                pass
    
    except Exception as e:
        if debug:
            print(f"[Security Log] Could not log quarantined LLM usage: {e}")
