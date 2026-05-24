"""Web chat handler — converse with the agent from the browser.

Uses a fixed chat id (``web:local``) so example 01 works with no auth /
no session machinery. Multiple users on the same dashboard will see the
same conversation history; for production use, swap in a per-cookie id.

Form submissions arrive either as a full POST (fallback when JS / htmx
fails to load) or as an htmx swap that appends a single new pair to the
``#messages`` container. Both render the same ``chat_message.html``
partial so the rendering stays single-sourced.
"""

from __future__ import annotations

import logging
from typing import Any

import aiohttp_jinja2
from aiohttp import web

from ..helpers import run_sync

logger = logging.getLogger(__name__)

CHAT_ID = "web:local"


def _agent(request: web.Request) -> Any:
    agent = request.app["bot_data"].get("agent")
    if agent is None:
        raise web.HTTPServiceUnavailable(reason="agent not ready")
    return agent


def _history_pairs(agent: Any) -> list[dict[str, str]]:
    """Collapse the agent's raw conversation log into user/assistant text pairs.

    The agent stores Anthropic-shaped messages — assistant turns may include
    tool_use blocks alongside text, and user turns may contain tool_result
    blocks. For the UI we only want the human-readable bits.
    """
    raw = agent.conversation_history.get(CHAT_ID, [])
    pairs: list[dict[str, str]] = []
    current_user: str | None = None
    for msg in raw:
        role = msg.get("role")
        content = msg.get("content")
        if role == "user":
            if isinstance(content, str):
                current_user = content
            else:
                # tool_result message — ignore, not user-visible
                continue
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
                parts.append(block.get("text", ""))
        else:
            btype = getattr(block, "type", None)
            if btype == "text":
                parts.append(getattr(block, "text", ""))
    return "\n".join(p for p in parts if p).strip()


@aiohttp_jinja2.template("chat.html")
async def index(request: web.Request) -> dict[str, Any]:
    agent = _agent(request)
    return {"messages": _history_pairs(agent), "chat_id": CHAT_ID}


async def send(request: web.Request) -> web.Response:
    agent = _agent(request)
    form = await request.post()
    text = str(form.get("message", "")).strip()
    if not text:
        raise web.HTTPSeeOther(location="/chat")

    try:
        reply = await agent.process_message(CHAT_ID, text)
    except Exception as exc:
        logger.exception("Agent failed for web chat")
        reply = f"Sorry, something went wrong: {exc}"

    if request.headers.get("HX-Request"):
        # htmx swap — return just the new message pair so it appends to #messages.
        return aiohttp_jinja2.render_template(
            "partials/chat_message.html",
            request,
            {"pair": {"user": text, "assistant": reply}},
        )
    raise web.HTTPSeeOther(location="/chat")


async def reset(request: web.Request) -> web.Response:
    agent = _agent(request)
    await run_sync(agent.clear_history, CHAT_ID)
    raise web.HTTPSeeOther(location="/chat")
