"""Chat service — convert agent conversation history to UI-friendly pairs and send."""

from __future__ import annotations

from typing import Any

from ..util import run_sync

# Fixed chat id for the local web/CLI chat surface. Keeps history out of
# Telegram / Slack channels and matches what the existing chat handler uses.
DEFAULT_CHAT_ID = "web:local"


async def send(agent: Any, text: str, *, chat_id: str = DEFAULT_CHAT_ID) -> str:
    """Run the user's message through the agent and return the reply text."""
    return str(await agent.process_message(chat_id, text))


async def reset(agent: Any, *, chat_id: str = DEFAULT_CHAT_ID) -> None:
    await run_sync(agent.clear_history, chat_id)


def history_pairs(agent: Any, *, chat_id: str = DEFAULT_CHAT_ID) -> list[dict[str, str]]:
    """Collapse the agent's raw conversation log into user/assistant text pairs.

    Same logic as the existing HTML chat handler — extracted here so both
    surfaces render the same view of history.
    """
    raw = agent.conversation_history.get(chat_id, [])
    pairs: list[dict[str, str]] = []
    current_user: str | None = None
    for msg in raw:
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            if isinstance(content, str):
                current_user = content
            # else: tool_result message — not user-visible
        elif role == "assistant":
            text = _extract_text(content)
            if text and current_user is not None:
                pairs.append({"user": current_user, "assistant": text})
                current_user = None
            elif text:
                pairs.append({"user": "", "assistant": text})
    return pairs


def _extract_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict):
            if block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        else:
            btype = getattr(block, "type", None)
            if btype == "text":
                parts.append(str(getattr(block, "text", "")))
    return "\n".join(p for p in parts if p).strip()
