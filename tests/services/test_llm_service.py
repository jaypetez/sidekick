"""Tests for the LLM lifecycle service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from sidekick.services import llm as llm_service


@pytest.mark.asyncio
async def test_rebuild_client_swaps_agent_llm(monkeypatch):
    agent = MagicMock()
    new_client = MagicMock()
    new_client.model = "claude-haiku-4-5-20251001"
    monkeypatch.setattr(llm_service, "build_llm_client", lambda: new_client)
    ok = await llm_service.rebuild_client(agent)
    assert ok is True
    assert agent.llm is new_client


@pytest.mark.asyncio
async def test_rebuild_client_returns_false_on_construction_failure(monkeypatch):
    agent = MagicMock()
    original_llm = agent.llm

    def boom():
        raise RuntimeError("API key missing")

    monkeypatch.setattr(llm_service, "build_llm_client", boom)
    ok = await llm_service.rebuild_client(agent)
    assert ok is False
    # The agent keeps its previous client — we don't trash it on failure
    assert agent.llm is original_llm


@pytest.mark.asyncio
async def test_probe_returns_text_on_success():
    agent = MagicMock()
    agent.llm.model = "claude-test"
    response = SimpleNamespace(content=[SimpleNamespace(type="text", text="OK")])
    agent.llm.chat = AsyncMock(return_value=response)
    result = await llm_service.probe(agent)
    assert result["ok"] is True
    assert result["reply"] == "OK"
    assert result["model"] == "claude-test"


@pytest.mark.asyncio
async def test_probe_returns_error_on_exception():
    agent = MagicMock()
    agent.llm.chat = AsyncMock(side_effect=RuntimeError("connection refused"))
    result = await llm_service.probe(agent)
    assert result["ok"] is False
    assert "connection refused" in result["error"]
