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


# Keys the built-in reminder jobs read; saving one re-applies them live.
_REMINDER_KEYS = frozenset(
    {"MORNING_REMINDER_TIME", "PRE_EVENT_REMINDER_MINUTES", "PRE_EVENT_SOURCE"}
)


async def update(
    changes: dict[str, str],
    *,
    agent: Any | None = None,
    scheduler: Any | None = None,
) -> dict[str, Any]:
    """Apply a batch of settings changes.

    Every value is validated *before* anything is written, so a bad key or
    value rejects the whole batch instead of leaving it half-applied.
    Empty-string values mean "remove the override" (so a user can clear an
    API key from the UI by submitting an empty field).

    Returns ``{"applied": [...], "llm_reloaded": bool, "restart_required": [...]}``.
    """
    for key, value in changes.items():
        runtime_config.validate(key, value)

    applied: list[str] = []
    for key, value in changes.items():
        if value == "":
            runtime_config.unset(key)
        else:
            runtime_config.set_value(key, value)
        applied.append(key)

    llm_reloaded = False
    if agent is not None and _LLM_AFFECTING_KEYS & changes.keys():
        from . import llm as llm_service

        llm_reloaded = await llm_service.rebuild_client(agent)

    restart_required = sorted(runtime_config.RESTART_REQUIRED_KEYS & changes.keys())
    if scheduler is not None and _REMINDER_KEYS & changes.keys():
        from ..reminders import apply_builtin_settings

        restart_required = sorted(set(restart_required) | set(apply_builtin_settings(scheduler)))

    return {
        "applied": applied,
        "llm_reloaded": llm_reloaded,
        "restart_required": restart_required,
    }


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
