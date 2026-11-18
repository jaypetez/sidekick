"""Tests that the Ollama client forwards GPU / context runtime options."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sidekick import runtime_config
from sidekick.llm.ollama import OllamaClient


def _fake_response() -> SimpleNamespace:
    return SimpleNamespace(message=SimpleNamespace(content="hi", tool_calls=None))


@pytest.mark.asyncio
async def test_chat_passes_only_num_predict_by_default():
    fake = AsyncMock()
    fake.chat = AsyncMock(return_value=_fake_response())
    client = OllamaClient(client=fake)
    await client.chat(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    kwargs = fake.chat.call_args.kwargs
    assert kwargs["options"] == {"num_predict": 1024}
    assert "keep_alive" not in kwargs


@pytest.mark.asyncio
async def test_chat_forwards_num_gpu_and_num_ctx_from_runtime_config():
    runtime_config.set_value("OLLAMA_NUM_GPU", "999")
    runtime_config.set_value("OLLAMA_NUM_CTX", "8192")
    fake = AsyncMock()
    fake.chat = AsyncMock(return_value=_fake_response())
    client = OllamaClient(client=fake)
    await client.chat(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    kwargs = fake.chat.call_args.kwargs
    assert kwargs["options"]["num_gpu"] == 999
    assert kwargs["options"]["num_ctx"] == 8192
    assert kwargs["options"]["num_predict"] == 1024


@pytest.mark.asyncio
async def test_chat_forwards_keep_alive_when_set():
    runtime_config.set_value("OLLAMA_KEEP_ALIVE", "10m")
    fake = AsyncMock()
    fake.chat = AsyncMock(return_value=_fake_response())
    client = OllamaClient(client=fake)
    await client.chat(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert fake.chat.call_args.kwargs["keep_alive"] == "10m"


@pytest.mark.asyncio
async def test_chat_ignores_invalid_num_gpu(monkeypatch):
    # set_value() rejects garbage now, but a hand-edited .env can still carry it.
    monkeypatch.setenv("OLLAMA_NUM_GPU", "not-an-int")
    fake = AsyncMock()
    fake.chat = AsyncMock(return_value=_fake_response())
    client = OllamaClient(client=fake)
    await client.chat(system="s", messages=[{"role": "user", "content": "hi"}], tools=[])
    assert "num_gpu" not in fake.chat.call_args.kwargs["options"]
