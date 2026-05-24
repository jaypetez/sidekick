"""Tests for AnthropicClient construction.

The interesting branch is the missing-key path: under LLM_PROVIDER=anthropic
(the default), users without ANTHROPIC_API_KEY set used to get a bare
KeyError from os.environ; now they should get a clear RuntimeError
pointing them at the Ollama escape hatch.
"""

from __future__ import annotations

import pytest


def test_missing_api_key_raises_runtime_error(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from sidekick.llm.anthropic import AnthropicClient

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY is not set"):
        AnthropicClient()


def test_explicit_api_key_overrides_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    from sidekick.llm.anthropic import AnthropicClient

    # Constructor should succeed when api_key is passed explicitly.
    client = AnthropicClient(api_key="sk-test-explicit")
    assert client.model  # default model populated


def test_env_api_key_used_when_no_arg(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-from-env")
    from sidekick.llm.anthropic import AnthropicClient

    client = AnthropicClient()
    assert client.model
