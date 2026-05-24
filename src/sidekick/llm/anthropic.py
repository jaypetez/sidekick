"""Anthropic concrete LLMClient.

Thin wrapper around `anthropic.AsyncAnthropic`. Pre-existing tool-use loop
in agent.py consumes the raw response, so this passes through.
"""

from typing import Any

import anthropic

from .. import runtime_config
from .base import LLMClient


class AnthropicClient(LLMClient):
    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or runtime_config.get("CLAUDE_MODEL") or "claude-haiku-4-5-20251001"
        resolved_key = api_key or runtime_config.get("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set — set it in your environment "
                "or switch to a local model with LLM_PROVIDER=ollama."
            )
        self._client = anthropic.AsyncAnthropic(api_key=resolved_key)

    async def chat(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> Any:
        return await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,  # type: ignore[arg-type]
            tools=tools,  # type: ignore[arg-type]
        )
