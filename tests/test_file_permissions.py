"""Persisted state files (reminders.json, config.json) must be 0600 on POSIX."""

import json
import os
import sys

import pytest

from sidekick import agent as agent_module
from sidekick.reminders import _write_reminders_file

POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows file permission model differs; chmod bits not enforced.",
)


@POSIX_ONLY
def test_reminders_file_is_0600(tmp_reminders_file):
    _write_reminders_file(
        [{"id": "r1", "message": "hi", "schedule": {"type": "cron", "hour": 8, "minute": 0}}]
    )
    mode = os.stat(tmp_reminders_file).st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


@POSIX_ONLY
def test_personality_config_is_0600(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    monkeypatch.setattr(agent_module, "CONFIG_FILE", str(cfg))
    agent_module._write_config({"personality": "snarky"})
    assert cfg.exists()
    mode = os.stat(cfg).st_mode & 0o777
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"
    # Sanity: file is still valid JSON we can read back
    assert json.loads(cfg.read_text())["personality"] == "snarky"
