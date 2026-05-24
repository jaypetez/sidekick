"""Settings service.

Sits on top of :mod:`sidekick.runtime_config` and the agent's personality
config. Mutations through this layer trigger downstream side effects
(rebuild the LLM client when LLM-related keys change). The on-change
hooks themselves are kept in :mod:`sidekick.services.llm` so this module
doesn't pull in the anthropic SDK at import time.
"""

from __future__ import annotations

import logging
from typing import Any

from .. import runtime_config
from ..util import run_sync

logger = logging.getLogger(__name__)

# Keys whose update should trigger an LLM client rebuild. The callable
# is wired up in services/llm.py; we look it up lazily so settings can
# be edited from contexts that don't have the agent (e.g. unit tests).
_LLM_AFFECTING_KEYS = frozenset(
    {
        "LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "CLAUDE_MODEL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "OLLAMA_NUM_CTX",
        "OLLAMA_NUM_GPU",
        "OLLAMA_KEEP_ALIVE",
    }
)


def snapshot(*, redacted: bool = True) -> dict[str, Any]:
    """Return the effective values of every editable key."""
    return runtime_config.as_dict(redacted=redacted)


async def update(
    changes: dict[str, str],
    *,
    agent: Any | None = None,
) -> dict[str, Any]:
    """Apply a batch of settings changes.

    Empty-string values are interpreted as "remove the override" (so a
    user can clear an API key from the UI by submitting an empty field).
    Returns ``{"applied": [...keys], "llm_reloaded": bool}``.
    """
    applied: list[str] = []
    needs_llm_reload = False
    for key, value in changes.items():
        if key not in runtime_config.EDITABLE_KEYS:
            raise runtime_config.ConfigError(f"{key} is not user-editable")
        if value == "":
            runtime_config.unset(key)
        else:
            runtime_config.set_value(key, value)
        applied.append(key)
        if key in _LLM_AFFECTING_KEYS:
            needs_llm_reload = True

    llm_reloaded = False
    if needs_llm_reload and agent is not None:
        from . import llm as llm_service

        llm_reloaded = await llm_service.rebuild_client(agent)

    return {"applied": applied, "llm_reloaded": llm_reloaded}


async def set_personality(agent: Any, style: str) -> str:
    """Apply a personality preset or freeform style. Returns the resolved label."""
    label = await run_sync(agent.set_personality, style)
    return str(label)


def personality(agent: Any) -> dict[str, Any]:
    """Return the agent's current personality and the available presets."""
    from ..agent import PERSONALITY_PRESETS

    return {
        "current": agent.personality or "",
        "presets": [k for k in PERSONALITY_PRESETS if k != "default"],
    }
