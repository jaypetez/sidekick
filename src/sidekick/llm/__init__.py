"""LLM client surface.

Use `build_llm_client()` to get a configured `LLMClient` for the
current environment — anthropic by default, ollama when
`LLM_PROVIDER=ollama` is set.
"""

import os

from .base import LLMClient


def build_llm_client() -> LLMClient:
    """Construct the configured LLM client.

    Selection: `LLM_PROVIDER=anthropic` (default) | `ollama`.
    """
    provider = os.getenv("LLM_PROVIDER", "anthropic").lower()
    if provider == "ollama":
        from .ollama import OllamaClient

        return OllamaClient()
    # Default and explicit "anthropic".
    from .anthropic import AnthropicClient

    return AnthropicClient()


__all__ = ["LLMClient", "build_llm_client"]
