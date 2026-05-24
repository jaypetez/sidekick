import os
from unittest.mock import MagicMock

import pytest

# Set dummy env vars before any sidekick imports
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("TIMEZONE", "America/Chicago")


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
