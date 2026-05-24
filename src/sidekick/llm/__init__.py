"""LLM client surface.

Use `build_llm_client()` to get a configured `LLMClient` for the
current environment — anthropic by default, ollama when
`LLM_PROVIDER=ollama` is set.

Reads through :mod:`sidekick.runtime_config` so values set via the
web settings UI / CLI take effect on the next ``build_llm_client()``
call without a process restart.
"""

from .. import runtime_config
from .base import LLMClient


def build_llm_client() -> LLMClient:
    """Construct the configured LLM client.

    Selection: ``LLM_PROVIDER=anthropic`` (default) | ``ollama``.
    """
    provider = (runtime_config.get("LLM_PROVIDER") or "anthropic").lower()
    if provider == "ollama":
        from .ollama import OllamaClient

        return OllamaClient()
    # Default and explicit "anthropic".
    from .anthropic import AnthropicClient

    return AnthropicClient()


__all__ = ["LLMClient", "build_llm_client"]
