"""Tests for sidekick-init bootstrap CLI."""

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sidekick import init_cli


def test_main_exits_without_api_key(monkeypatch, capsys):
    monkeypatch.delenv("CHRONARY_API_KEY", raising=False)
    with pytest.raises(SystemExit) as exc:
        init_cli.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "CHRONARY_API_KEY" in err


def test_main_exits_when_chronary_not_installed(monkeypatch, capsys):
    monkeypatch.setenv("CHRONARY_API_KEY", "chr_sk_test")
    # Force the in-function `from chronary import Chronary` to fail.
    monkeypatch.setitem(sys.modules, "chronary", None)
    with pytest.raises(SystemExit) as exc:
        init_cli.main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "chronary" in err.lower()


def test_main_creates_agent_and_calendar(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CHRONARY_API_KEY", "chr_sk_test")
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path))

    fake_agent = SimpleNamespace(id="agent_123")
    fake_calendar = SimpleNamespace(id="cal_456")

    fake_client = MagicMock()
    fake_client.agents.create.return_value = fake_agent
    fake_client.agents.calendars.create.return_value = fake_calendar

    fake_chronary_module = SimpleNamespace(Chronary=lambda api_key: fake_client)
    monkeypatch.setitem(sys.modules, "chronary", fake_chronary_module)

    init_cli.main()

    fake_client.agents.create.assert_called_once_with(name="sidekick", type="ai")
    fake_client.agents.calendars.create.assert_called_once()
    # The calendar call gets the agent_id positionally.
    pos_args, kw_args = fake_client.agents.calendars.create.call_args
    assert pos_args == ("agent_123",)
    assert kw_args["name"] == "Sidekick"

    config_path = tmp_path / "config.json"
    assert config_path.exists()
    saved = json.loads(config_path.read_text())
    assert saved["chronary_agent_id"] == "agent_123"
    assert saved["chronary_calendar_id"] == "cal_456"

    out = capsys.readouterr().out
    assert "CHRONARY_AGENT_ID=agent_123" in out
    assert "CHRONARY_CALENDAR_ID=cal_456" in out


def test_main_handles_dict_response_shape(monkeypatch, tmp_path):
    """Chronary SDK objects may be dicts in some versions; tolerate both."""
    monkeypatch.setenv("CHRONARY_API_KEY", "chr_sk_test")
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path))

    fake_client = MagicMock()
    fake_client.agents.create.return_value = {"id": "agent_dict"}
    fake_client.agents.calendars.create.return_value = {"id": "cal_dict"}

    fake_chronary_module = SimpleNamespace(Chronary=lambda api_key: fake_client)
    monkeypatch.setitem(sys.modules, "chronary", fake_chronary_module)

    init_cli.main()

    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["chronary_agent_id"] == "agent_dict"
    assert saved["chronary_calendar_id"] == "cal_dict"


def test_main_merges_with_existing_config(monkeypatch, tmp_path):
    monkeypatch.setenv("CHRONARY_API_KEY", "chr_sk_test")
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path))
    (tmp_path / "config.json").write_text(json.dumps({"personality": "snarky"}))

    fake_client = MagicMock()
    fake_client.agents.create.return_value = SimpleNamespace(id="agent_new")
    fake_client.agents.calendars.create.return_value = SimpleNamespace(id="cal_new")
    monkeypatch.setitem(
        sys.modules, "chronary", SimpleNamespace(Chronary=lambda api_key: fake_client)
    )

    init_cli.main()

    saved = json.loads((tmp_path / "config.json").read_text())
    # Existing keys preserved.
    assert saved["personality"] == "snarky"
    assert saved["chronary_agent_id"] == "agent_new"
