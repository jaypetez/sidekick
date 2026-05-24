"""Ollama LLMClient.

Lets sidekick run against a local Ollama server instead of Anthropic.

The agent.py tool-use loop is written against the Anthropic response
shape (`.stop_reason`, `.content` with `.type` / `.text` / `.id` /
`.name` / `.input` blocks). Rather than refactor the loop, this client
adapts the Ollama response into the same shape so agent.py stays
untouched.

Tools and messages also need format translation:
- Anthropic tools: {name, description, input_schema}
- Ollama tools:    {type: "function", function: {name, description, parameters}}
- Anthropic messages may have list-of-blocks content (tool_use,
  tool_result). Ollama uses {role: "tool", tool_call_id, content}.

Model recommendation: `llama3.1:8b` or `qwen2.5:7b` — both have
usable function-calling. Smaller models will misfire on multi-tool
plans, and tool-use reliability is materially below Claude's
regardless of model.
"""

import json
import logging
import os
import uuid
from types import SimpleNamespace
from typing import Any

from .base import LLMClient

logger = logging.getLogger(__name__)


class OllamaClient(LLMClient):
    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        client: Any = None,
    ) -> None:
        self.model = model or os.getenv("OLLAMA_MODEL") or "llama3.1:8b"
        self._base_url = base_url or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434"
        self._client = client  # lazily constructed when actually used

    async def chat(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 1024,
    ) -> Any:
        client = self._get_client()

        oll_messages = [{"role": "system", "content": system}]
        oll_messages.extend(_messages_anthropic_to_ollama(messages))
        oll_tools = [_tool_anthropic_to_ollama(t) for t in tools]

        try:
            response = await client.chat(
                model=self.model,
                messages=oll_messages,
                tools=oll_tools or None,
                options={"num_predict": max_tokens},
            )
        except TimeoutError as exc:
            raise RuntimeError(
                f"Ollama request timed out talking to {self._base_url} "
                f"(model {self.model}). Is the server reachable and the model pulled?"
            ) from exc
        except Exception as exc:
            # ollama.ResponseError, httpx.ConnectError, etc. — Ollama's exception
            # hierarchy isn't part of our public surface, so catch broadly and
            # re-raise with a clear message the agent layer can surface to the user.
            raise RuntimeError(
                f"Ollama call failed against {self._base_url} (model {self.model}): {exc}"
            ) from exc

        return _response_ollama_to_anthropic(response)

    def _get_client(self) -> Any:
        if self._client is None:
            import ollama

            self._client = ollama.AsyncClient(host=self._base_url)
        return self._client


# ----------------------------------------------------------------------
# Format translation
# ----------------------------------------------------------------------


def _tool_anthropic_to_ollama(tool: dict[str, Any]) -> dict[str, Any]:
    """Translate a single Anthropic-style tool def to Ollama/OpenAI shape."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        },
    }


def _messages_anthropic_to_ollama(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten Anthropic messages (which may have list-of-block content) to
    the role/content/tool_calls shape Ollama expects."""
    out: list[dict[str, Any]] = []
    for msg in messages:
        role = msg["role"]
        content = msg["content"]

        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue

        # content is a list of blocks
        if role == "assistant":
            text_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            for block in content:
                btype = _block_attr(block, "type")
                if btype == "text":
                    text_parts.append(_block_attr(block, "text", ""))
                elif btype == "tool_use":
                    tool_calls.append(
                        {
                            "id": _block_attr(block, "id"),
                            "type": "function",
                            "function": {
                                "name": _block_attr(block, "name"),
                                "arguments": _block_attr(block, "input", {}),
                            },
                        }
                    )
            entry: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts)}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            out.append(entry)
            continue

        if role == "user":
            # User messages may carry tool_result blocks from the prior turn.
            for block in content:
                btype = _block_attr(block, "type")
                if btype == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": _block_attr(block, "tool_use_id"),
                            "content": _block_attr(block, "content", ""),
                        }
                    )
                elif btype == "text":
                    out.append({"role": "user", "content": _block_attr(block, "text", "")})
            continue

        # Unknown role/shape — pass through best-effort.
        out.append({"role": role, "content": str(content)})

    return out


def _response_ollama_to_anthropic(response: Any) -> SimpleNamespace:
    """Wrap an Ollama response so the agent's tool-use loop reads it like
    an Anthropic response (`.stop_reason`, `.content[*].{type,text,id,name,input}`)."""
    msg = response["message"] if isinstance(response, dict) else response.message
    tool_calls = (
        msg.get("tool_calls") if isinstance(msg, dict) else getattr(msg, "tool_calls", None)
    ) or []
    text = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")

    blocks: list[Any] = []
    if text:
        blocks.append(SimpleNamespace(type="text", text=text))

    for call in tool_calls:
        fn = call["function"] if isinstance(call, dict) else call.function
        fn_name = fn["name"] if isinstance(fn, dict) else fn.name
        fn_args = fn["arguments"] if isinstance(fn, dict) else fn.arguments
        if isinstance(fn_args, str):
            try:
                fn_args = json.loads(fn_args)
            except json.JSONDecodeError:
                fn_args = {}
        call_id = call.get("id") if isinstance(call, dict) else getattr(call, "id", None)
        blocks.append(
            SimpleNamespace(
                type="tool_use",
                id=call_id or f"call_{uuid.uuid4().hex[:8]}",
                name=fn_name,
                input=fn_args or {},
            )
        )

    stop_reason = "tool_use" if tool_calls else "end_turn"
    return SimpleNamespace(stop_reason=stop_reason, content=blocks)


def _block_attr(block: Any, name: str, default: Any = None) -> Any:
    if isinstance(block, dict):
        return block.get(name, default)
    return getattr(block, name, default)
