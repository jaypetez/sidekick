"""LLM lifecycle service.

Rebuilds the agent's LLM client when settings change, and runs a
small probe prompt against the current configuration for the
"Test LLM" button in the settings UI.
"""

from __future__ import annotations

import logging
from typing import Any

from ..llm import build_llm_client

logger = logging.getLogger(__name__)


async def rebuild_client(agent: Any) -> bool:
    """Rebuild :attr:`agent.llm` from current :mod:`runtime_config` values.

    Returns ``True`` on success, ``False`` if construction failed (e.g.
    the Anthropic key is now missing). Failures are logged but never
    raised: the caller is a settings save and we don't want to lose the
    persisted change just because the client can't connect yet.
    """
    try:
        agent.llm = build_llm_client()
    except Exception:
        logger.exception("LLM client rebuild failed; agent keeps its previous client")
        return False
    logger.info(
        "LLM client rebuilt (provider=%s, model=%s)", type(agent.llm).__name__, agent.llm.model
    )
    return True


async def probe(agent: Any, *, prompt: str = "Reply with the single word OK.") -> dict[str, Any]:
    """Send a tiny prompt to verify the current LLM config actually responds."""
    try:
        response = await agent.llm.chat(
            system="You are a connectivity test. Reply tersely.",
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            max_tokens=32,
        )
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    text_parts: list[str] = []
    for block in getattr(response, "content", []) or []:
        if getattr(block, "type", None) == "text":
            text_parts.append(str(getattr(block, "text", "")))
    return {
        "ok": True,
        "model": agent.llm.model,
        "provider": type(agent.llm).__name__,
        "reply": "\n".join(text_parts).strip() or "(no text)",
    }
