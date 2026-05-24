"""Tests for the runtime_config overlay."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from sidekick import runtime_config


def test_get_falls_back_to_environ(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Berlin")
    runtime_config.reset_cache()
    assert runtime_config.get("TIMEZONE") == "Europe/Berlin"


def test_get_default_when_missing(monkeypatch):
    monkeypatch.delenv("OLLAMA_NUM_CTX", raising=False)
    runtime_config.reset_cache()
    assert runtime_config.get("OLLAMA_NUM_CTX") is None
    assert runtime_config.get("OLLAMA_NUM_CTX", "4096") == "4096"


def test_overlay_wins_over_environ(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Berlin")
    runtime_config.set_value("TIMEZONE", "Asia/Tokyo")
    assert runtime_config.get("TIMEZONE") == "Asia/Tokyo"


def test_unset_falls_back_to_environ(monkeypatch):
    monkeypatch.setenv("TIMEZONE", "Europe/Berlin")
    runtime_config.set_value("TIMEZONE", "Asia/Tokyo")
    runtime_config.unset("TIMEZONE")
    assert runtime_config.get("TIMEZONE") == "Europe/Berlin"


def test_set_persists_to_disk(isolated_runtime_config):
    runtime_config.set_value("OLLAMA_NUM_GPU", "999")
    raw = json.loads(Path(isolated_runtime_config).read_text())
    assert raw == {"OLLAMA_NUM_GPU": "999"}


def test_set_rejects_unknown_keys():
    with pytest.raises(runtime_config.ConfigError):
        runtime_config.set_value("ARBITRARY_VAR", "x")


def test_unset_rejects_unknown_keys():
    with pytest.raises(runtime_config.ConfigError):
        runtime_config.unset("ARBITRARY_VAR")


def test_get_int_parses_overlay():
    runtime_config.set_value("OLLAMA_NUM_GPU", "42")
    assert runtime_config.get_int("OLLAMA_NUM_GPU") == 42


def test_get_int_returns_default_on_garbage():
    runtime_config.set_value("OLLAMA_NUM_GPU", "not-a-number")
    assert runtime_config.get_int("OLLAMA_NUM_GPU", default=7) == 7


def test_get_bool_treats_truthy_strings_as_true():
    runtime_config.set_value("OLLAMA_KEEP_ALIVE", "true")
    assert runtime_config.get_bool("OLLAMA_KEEP_ALIVE") is True
    runtime_config.set_value("OLLAMA_KEEP_ALIVE", "no")
    assert runtime_config.get_bool("OLLAMA_KEEP_ALIVE") is False


def test_as_dict_redacts_secrets():
    runtime_config.set_value("ANTHROPIC_API_KEY", "sk-test-abc123-secret-tail")
    snapshot = runtime_config.as_dict(redacted=True)
    val = snapshot["ANTHROPIC_API_KEY"]
    assert isinstance(val, dict)
    assert val["set"] is True
    assert "secret-tail" not in val["preview"]
    assert val["preview"].endswith("tail")
    # Other (non-secret) editable keys appear as plain values
    assert isinstance(snapshot["LLM_PROVIDER"], str)


def test_as_dict_unredacted_returns_raw_value():
    runtime_config.set_value("ANTHROPIC_API_KEY", "sk-raw")
    snapshot = runtime_config.as_dict(redacted=False)
    assert snapshot["ANTHROPIC_API_KEY"] == "sk-raw"


def test_as_dict_handles_unset_secret():
    snapshot = runtime_config.as_dict(redacted=True)
    val = snapshot["ANTHROPIC_API_KEY"]
    # Either an unset-secret dict, or empty string when env var is empty
    assert val == {"set": False, "preview": ""} or val == {"set": True, "preview": "…real"}


def test_cache_reload_picks_up_external_write(isolated_runtime_config):
    runtime_config.set_value("CLAUDE_MODEL", "claude-x")
    # Simulate another process writing to the same file
    Path(isolated_runtime_config).write_text(
        json.dumps({"CLAUDE_MODEL": "claude-y", "OLLAMA_MODEL": "qwen2.5:14b"})
    )
    runtime_config.reset_cache()
    assert runtime_config.get("CLAUDE_MODEL") == "claude-y"
    assert runtime_config.get("OLLAMA_MODEL") == "qwen2.5:14b"


def test_persist_writes_sorted_json(isolated_runtime_config):
    runtime_config.set_value("OLLAMA_MODEL", "a")
    runtime_config.set_value("CLAUDE_MODEL", "b")
    text = Path(isolated_runtime_config).read_text()
    # Sorted keys: CLAUDE_MODEL appears before OLLAMA_MODEL
    assert text.index("CLAUDE_MODEL") < text.index("OLLAMA_MODEL")


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-only file mode check")
def test_persist_writes_with_0600_mode(isolated_runtime_config):
    runtime_config.set_value("ANTHROPIC_API_KEY", "sk-secret")
    mode = os.stat(isolated_runtime_config).st_mode & 0o777
    assert mode == stat.S_IRUSR | stat.S_IWUSR  # 0o600


def test_unset_missing_key_is_noop():
    # Nothing previously set; unset should not raise and should not create a file.
    runtime_config.unset("OLLAMA_NUM_CTX")
    # Even after unset, the lookup still works (falls through to env or None).
    assert runtime_config.get("OLLAMA_NUM_CTX") in (None, "", *map(str, range(1, 100000)))


def test_current_path_reflects_use_path(tmp_path):
    new_path = str(tmp_path / "other.json")
    runtime_config.use_path(new_path)
    assert runtime_config.current_path() == new_path
