"""LLM client abstraction.

Defines the contract every provider (Anthropic, Ollama, ...) implements.
The response type is intentionally `Any` for now: the Anthropic SDK's
response object is consumed directly by the tool-use loop in agent.py.
When Ollama lands in step 7 we'll normalize to a typed LLMResponse.
"""

from abc import ABC, abstractmethod
from typing import Any


class LLMClient(ABC):
    """Provider-neutral LLM chat surface."""

    model: str

    @abstractmethod
    async def chat(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> Any:
        """Run one LLM round-trip and return the provider's raw response.

        Callers inspect `.stop_reason` and iterate `.content` blocks.
        """
