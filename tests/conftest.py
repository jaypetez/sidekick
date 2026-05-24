import os
from unittest.mock import MagicMock

import pytest

# Set dummy env vars before any sidekick imports
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("TIMEZONE", "America/Chicago")


@pytest.fixture(autouse=True)
def isolated_runtime_config(tmp_path, monkeypatch):
    """Point :mod:`sidekick.runtime_config` at a per-test tmp file.

    Auto-applied to every test so writes through ``runtime_config.set_value``
    can't leak across tests or onto the developer's real ``~/.config``.
    """
    from sidekick import runtime_config

    path = str(tmp_path / "runtime.json")
    runtime_config.use_path(path)
    yield path
    runtime_config.use_path(runtime_config._default_path())
    runtime_config.reset_cache()


@pytest.fixture
def mock_scheduler():
    scheduler = MagicMock()
    scheduler.get_jobs.return_value = []
    return scheduler


@pytest.fixture
def mock_bot():
    return MagicMock()


@pytest.fixture
def tmp_reminders_file(tmp_path, monkeypatch):
    """Patch REMINDERS_FILE to an isolated temp file."""
    path = str(tmp_path / "reminders.json")
    monkeypatch.setattr("sidekick.reminders.REMINDERS_FILE", path)
    return path
