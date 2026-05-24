"""Tests for OllamaClient format-translation helpers.

We don't hit a real Ollama server — verifying the bidirectional
mapping between Anthropic-shape and Ollama-shape is what matters for
keeping agent.py's tool-use loop functional.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sidekick.llm.ollama import (
    OllamaClient,
    _messages_anthropic_to_ollama,
    _response_ollama_to_anthropic,
    _tool_anthropic_to_ollama,
)

# -------------------------------------------------------------------
# Tool format conversion
# -------------------------------------------------------------------


def test_tool_anthropic_to_ollama():
    tool = {
        "name": "list_events",
        "description": "List events",
        "input_schema": {"type": "object", "properties": {"start": {"type": "string"}}},
    }
    out = _tool_anthropic_to_ollama(tool)
    assert out == {
        "type": "function",
        "function": {
            "name": "list_events",
            "description": "List events",
            "parameters": {"type": "object", "properties": {"start": {"type": "string"}}},
        },
    }


def test_tool_anthropic_to_ollama_missing_schema():
    """Tools without input_schema get a permissive default."""
    out = _tool_anthropic_to_ollama({"name": "noop"})
    assert out["function"]["parameters"] == {"type": "object", "properties": {}}


# -------------------------------------------------------------------
# Messages conversion
# -------------------------------------------------------------------


def test_messages_passthrough_string_content():
    msgs = [{"role": "user", "content": "hi"}]
    assert _messages_anthropic_to_ollama(msgs) == [{"role": "user", "content": "hi"}]


def test_messages_assistant_text_block():
    msgs = [
        {
            "role": "assistant",
            "content": [SimpleNamespace(type="text", text="hello")],
        }
    ]
    out = _messages_anthropic_to_ollama(msgs)
    assert out == [{"role": "assistant", "content": "hello"}]


def test_messages_assistant_tool_use():
    msgs = [
        {
            "role": "assistant",
            "content": [
                SimpleNamespace(type="text", text="ok"),
                SimpleNamespace(type="tool_use", id="t1", name="list_events", input={"x": 1}),
            ],
        }
    ]
    out = _messages_anthropic_to_ollama(msgs)
    assert out[0]["role"] == "assistant"
    assert out[0]["content"] == "ok"
    assert out[0]["tool_calls"] == [
        {
            "id": "t1",
            "type": "function",
            "function": {"name": "list_events", "arguments": {"x": 1}},
        }
    ]


def test_messages_user_tool_result():
    """User messages carrying tool_result blocks map to role='tool' entries."""
    msgs = [
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "result text"}],
        }
    ]
    out = _messages_anthropic_to_ollama(msgs)
    assert out == [
        {
            "role": "tool",
            "tool_call_id": "t1",
            "content": "result text",
        }
    ]


# -------------------------------------------------------------------
# Response conversion
# -------------------------------------------------------------------


def test_response_text_only_yields_end_turn():
    response = {"message": {"role": "assistant", "content": "Just text."}}
    result = _response_ollama_to_anthropic(response)
    assert result.stop_reason == "end_turn"
    assert len(result.content) == 1
    assert result.content[0].type == "text"
    assert result.content[0].text == "Just text."


def test_response_tool_call_yields_tool_use():
    response = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "list_events", "arguments": {"x": 1}},
                }
            ],
        }
    }
    result = _response_ollama_to_anthropic(response)
    assert result.stop_reason == "tool_use"
    blocks = result.content
    # Only the tool_use block (no text since content is empty).
    tool_blocks = [b for b in blocks if b.type == "tool_use"]
    assert len(tool_blocks) == 1
    assert tool_blocks[0].name == "list_events"
    assert tool_blocks[0].input == {"x": 1}
    assert tool_blocks[0].id == "call_1"


def test_response_tool_arguments_string_decoded():
    """Some Ollama models return arguments as a JSON string; we parse it."""
    response = {
        "message": {
            "content": "",
            "tool_calls": [{"function": {"name": "f", "arguments": '{"a": 2}'}}],
        }
    }
    result = _response_ollama_to_anthropic(response)
    tool_blocks = [b for b in result.content if b.type == "tool_use"]
    assert tool_blocks[0].input == {"a": 2}


def test_response_generates_id_when_missing():
    """If Ollama omits a call id, we synthesize one so the agent's loop has
    something to refer to in subsequent tool_result blocks."""
    response = {
        "message": {
            "content": "",
            "tool_calls": [{"function": {"name": "f", "arguments": {}}}],
        }
    }
    result = _response_ollama_to_anthropic(response)
    tool_blocks = [b for b in result.content if b.type == "tool_use"]
    assert tool_blocks[0].id.startswith("call_")


# -------------------------------------------------------------------
# Client wiring
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_passes_translated_messages_and_tools():
    """chat() must hand Ollama-shaped tools and messages to the SDK."""
    fake_client = SimpleNamespace(
        chat=AsyncMock(return_value={"message": {"role": "assistant", "content": "hi"}})
    )
    llm = OllamaClient(model="llama3.1:8b", client=fake_client)

    await llm.chat(
        system="you are a bot",
        messages=[{"role": "user", "content": "ping"}],
        tools=[{"name": "noop", "description": "n", "input_schema": {}}],
    )

    args = fake_client.chat.call_args
    assert args.kwargs["model"] == "llama3.1:8b"
    # System message prepended, user message preserved.
    assert args.kwargs["messages"][0] == {"role": "system", "content": "you are a bot"}
    assert args.kwargs["messages"][1] == {"role": "user", "content": "ping"}
    # Tool converted to OpenAI shape.
    assert args.kwargs["tools"][0]["type"] == "function"
    assert args.kwargs["tools"][0]["function"]["name"] == "noop"


@pytest.mark.asyncio
async def test_chat_wraps_connection_error_in_runtime_error():
    """A network failure to ollama should surface as a clear RuntimeError
    that the agent's existing exception handler can show to the user."""
    fake_client = SimpleNamespace(chat=AsyncMock(side_effect=ConnectionRefusedError("nope")))
    llm = OllamaClient(model="qwen2.5:14b", client=fake_client, base_url="http://ollama:11434")

    with pytest.raises(RuntimeError, match="Ollama call failed"):
        await llm.chat(system="x", messages=[], tools=[])


@pytest.mark.asyncio
async def test_chat_wraps_timeout_in_runtime_error():
    """TimeoutError must be re-raised as a clearer RuntimeError."""
    fake_client = SimpleNamespace(chat=AsyncMock(side_effect=TimeoutError()))
    llm = OllamaClient(model="qwen2.5:14b", client=fake_client)

    with pytest.raises(RuntimeError, match="Ollama request timed out"):
        await llm.chat(system="x", messages=[], tools=[])
