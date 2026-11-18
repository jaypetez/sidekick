"""Tests for sidekick.paths — state file locations and the legacy fallback."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from sidekick import paths

_VARS = ("SIDEKICK_CONFIG_DIR", "SIDEKICK_DB_PATH", "REMINDERS_FILE", "CONFIG_FILE")


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Fake $HOME so ~/.config/sidekick (the legacy location) is a temp dir."""
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    for var in _VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(paths, "_warned", set())
    return fake_home


def _legacy(home: Path) -> Path:
    return home / ".config" / "sidekick"


def test_defaults_live_in_home_config(home):
    base = _legacy(home)
    assert paths.config_dir() == base
    assert paths.db_path() == str(base / "sidekick.db")
    assert paths.reminders_file() == str(base / "reminders.json")
    assert paths.personality_file() == str(base / "config.json")


def test_config_dir_relocates_every_state_file(home, tmp_path, monkeypatch):
    custom = tmp_path / "state"
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(custom))
    assert paths.config_dir() == custom
    assert paths.db_path() == str(custom / "sidekick.db")
    assert paths.reminders_file() == str(custom / "reminders.json")
    assert paths.personality_file() == str(custom / "config.json")


def test_blank_config_dir_means_default_not_cwd(home, monkeypatch):
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", "   ")
    assert paths.config_dir() == _legacy(home)


def test_tilde_is_expanded(home, monkeypatch):
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", "~/sk")
    monkeypatch.setenv("SIDEKICK_DB_PATH", "~/data/tasks.db")
    assert paths.config_dir() == home / "sk"
    assert paths.db_path() == str(home / "data" / "tasks.db")
    assert "~" not in paths.reminders_file()


@pytest.mark.parametrize(
    ("var", "fn"),
    [
        ("SIDEKICK_DB_PATH", paths.db_path),
        ("REMINDERS_FILE", paths.reminders_file),
        ("CONFIG_FILE", paths.personality_file),
    ],
)
def test_explicit_variable_wins_over_config_dir(home, tmp_path, monkeypatch, var, fn):
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path / "state"))
    monkeypatch.setenv(var, str(tmp_path / "elsewhere" / "file"))
    assert fn() == str(tmp_path / "elsewhere" / "file")


def test_legacy_file_used_when_new_location_is_empty(home, tmp_path, monkeypatch, caplog):
    legacy = _legacy(home)
    legacy.mkdir(parents=True)
    (legacy / "reminders.json").write_text("{}")
    custom = tmp_path / "state"
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(custom))

    with caplog.at_level(logging.WARNING, logger="sidekick.paths"):
        assert paths.reminders_file() == str(legacy / "reminders.json")
        assert paths.reminders_file() == str(legacy / "reminders.json")
    assert len([r for r in caplog.records if "reminders.json" in r.getMessage()]) == 1
    # Files that don't exist in the legacy dir resolve to the new location.
    assert paths.db_path() == str(custom / "sidekick.db")


def test_new_location_wins_once_file_is_moved(home, tmp_path, monkeypatch):
    legacy = _legacy(home)
    legacy.mkdir(parents=True)
    (legacy / "config.json").write_text("{}")
    custom = tmp_path / "state"
    custom.mkdir()
    (custom / "config.json").write_text("{}")
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(custom))
    assert paths.personality_file() == str(custom / "config.json")


def test_providers_use_paths(home, tmp_path, monkeypatch):
    """Every module that touches state resolves through sidekick.paths."""
    from sidekick import runtime_config, webhooks
    from sidekick.storage import sqlite_tasks
    from sidekick.web import auth

    custom = tmp_path / "state"
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(custom))
    monkeypatch.delenv("SIDEKICK_RUNTIME_CONFIG", raising=False)
    runtime_config.use_path(None)
    assert sqlite_tasks.default_db_path() == str(custom / "sidekick.db")
    assert webhooks.secret_file_path() == custom / "chronary_webhook.secret"
    assert auth._config_dir() == custom
    assert runtime_config.current_path() == str(custom / "runtime.json")


def test_runtime_config_explicit_path_is_expanded(home, monkeypatch):
    from sidekick import runtime_config

    monkeypatch.setenv("SIDEKICK_RUNTIME_CONFIG", "~/rt.json")
    runtime_config.use_path(None)
    assert runtime_config.current_path() == str(home / "rt.json")


def test_delivery_log_defaults_to_tasks_db(home, tmp_path, monkeypatch):
    from sidekick import webhooks

    custom = tmp_path / "state"
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(custom))
    log = webhooks.DeliveryLog()
    try:
        assert log.record("probe") is True
    finally:
        log._conn.close()
    assert (custom / "sidekick.db").exists()


def test_no_module_hard_codes_the_config_dir():
    """Path resolution belongs in sidekick.paths; a stray literal reintroduces the bug."""
    src = Path(__file__).resolve().parents[1] / "src" / "sidekick"
    offenders = [
        str(path.relative_to(src))
        for path in src.rglob("*.py")
        if path.name != "paths.py"
        and 'expanduser("~/.config/sidekick' in path.read_text(encoding="utf-8")
    ]
    assert not offenders
