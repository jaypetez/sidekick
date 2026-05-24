"""Anthropic concrete LLMClient.

Thin wrapper around `anthropic.AsyncAnthropic`. Pre-existing tool-use loop
in agent.py consumes the raw response, so this passes through.
"""

import os
from typing import Any

import anthropic

from .base import LLMClient


class AnthropicClient(LLMClient):
    def __init__(self, *, model: str | None = None, api_key: str | None = None) -> None:
        self.model = model or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        self._client = anthropic.AsyncAnthropic(
            api_key=api_key or os.environ["ANTHROPIC_API_KEY"]
        )

    async def chat(
        self,
        *,
        system: str,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int = 1024,
    ) -> Any:
        return await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
