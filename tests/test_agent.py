import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sidekick.agent import PERSONALITY_PRESETS, SidekickAgent


def _make_agent(scheduler=None, bot=None):
    """Create a SidekickAgent with mocked dependencies."""
    session = MagicMock()
    return SidekickAgent(
        mcp_session=session,
        scheduler=scheduler,
        bot=bot,
        reminder_chat_id=-100123,
    )


# -------------------------------------------------------------------
# _extract_text
# -------------------------------------------------------------------


def test_extract_text_single_block():
    agent = _make_agent()
    blocks = [SimpleNamespace(type="text", text="Hello world")]
    assert agent._extract_text(blocks) == "Hello world"


def test_extract_text_mixed_blocks():
    agent = _make_agent()
    blocks = [
        SimpleNamespace(type="text", text="Before"),
        SimpleNamespace(type="tool_use", id="t1", name="list_events", input={}),
        SimpleNamespace(type="text", text="After"),
    ]
    assert agent._extract_text(blocks) == "Before\nAfter"


def test_extract_text_no_text():
    agent = _make_agent()
    blocks = [SimpleNamespace(type="tool_use", id="t1", name="list_events", input={})]
    assert agent._extract_text(blocks) == ""


# -------------------------------------------------------------------
# _trim_history
# -------------------------------------------------------------------


def test_trim_history_under_limit():
    agent = _make_agent()
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    agent._trim_history(history)
    assert len(history) == 2


def test_trim_history_over_limit():
    agent = _make_agent()
    history = []
    for i in range(25):
        history.append({"role": "user", "content": f"msg {i}"})
        history.append({"role": "assistant", "content": f"reply {i}"})

    agent._trim_history(history)
    user_count = sum(1 for m in history if m["role"] == "user")
    assert user_count == 20


def test_trim_history_preserves_structure():
    agent = _make_agent()
    history = []
    for i in range(25):
        history.append({"role": "user", "content": f"msg {i}"})
        history.append({"role": "assistant", "content": f"reply {i}"})

    agent._trim_history(history)
    assert history[0]["role"] == "user"


# -------------------------------------------------------------------
# _handle_reminder_tool
# -------------------------------------------------------------------


def test_handle_reminder_tool_no_scheduler():
    agent = _make_agent(scheduler=None)
    result = agent._handle_reminder_tool("list_reminders", {})
    assert "error" in result


@patch("sidekick.agent.get_all_reminders")
def test_handle_reminder_tool_list(mock_get):
    mock_get.return_value = [{"id": "morning_summary"}]
    agent = _make_agent(scheduler=MagicMock(), bot=MagicMock())
    result = agent._handle_reminder_tool("list_reminders", {})
    mock_get.assert_called_once()
    assert result == [{"id": "morning_summary"}]


@patch("sidekick.agent.add_reminder")
def test_handle_reminder_tool_add(mock_add):
    mock_add.return_value = {"status": "created", "id": "r1"}
    agent = _make_agent(scheduler=MagicMock(), bot=MagicMock())
    result = agent._handle_reminder_tool(
        "add_reminder",
        {
            "message": "Test",
            "hour": 9,
            "minute": 0,
        },
    )
    mock_add.assert_called_once()
    assert result["status"] == "created"


@patch("sidekick.agent.update_reminder")
def test_handle_reminder_tool_update(mock_update):
    mock_update.return_value = {"status": "updated", "id": "r1"}
    agent = _make_agent(scheduler=MagicMock(), bot=MagicMock())
    result = agent._handle_reminder_tool(
        "update_reminder",
        {
            "reminder_id": "r1",
            "hour": 10,
        },
    )
    mock_update.assert_called_once()
    assert result["status"] == "updated"


@patch("sidekick.agent.remove_reminder")
def test_handle_reminder_tool_remove(mock_remove):
    mock_remove.return_value = {"status": "removed", "id": "r1"}
    agent = _make_agent(scheduler=MagicMock(), bot=MagicMock())
    result = agent._handle_reminder_tool("remove_reminder", {"reminder_id": "r1"})
    mock_remove.assert_called_once()
    assert result["status"] == "removed"


def test_handle_reminder_tool_unknown():
    agent = _make_agent(scheduler=MagicMock(), bot=MagicMock())
    result = agent._handle_reminder_tool("unknown_tool", {})
    assert "error" in result


# -------------------------------------------------------------------
# Personality
# -------------------------------------------------------------------


def test_set_personality_preset(tmp_path, monkeypatch):
    monkeypatch.setattr("sidekick.agent.CONFIG_FILE", str(tmp_path / "config.json"))
    agent = _make_agent()
    label = agent.set_personality("snarky")
    assert label == "snarky"
    assert agent.personality == PERSONALITY_PRESETS["snarky"]


def test_set_personality_freeform(tmp_path, monkeypatch):
    monkeypatch.setattr("sidekick.agent.CONFIG_FILE", str(tmp_path / "config.json"))
    agent = _make_agent()
    label = agent.set_personality("Talk like a 1920s gangster")
    assert label == "custom"
    assert agent.personality == "Talk like a 1920s gangster"


def test_set_personality_default_clears(tmp_path, monkeypatch):
    monkeypatch.setattr("sidekick.agent.CONFIG_FILE", str(tmp_path / "config.json"))
    agent = _make_agent()
    agent.set_personality("snarky")
    label = agent.set_personality("default")
    assert label == "default (friendly assistant)"
    assert agent.personality == ""


def test_personality_persists_to_config(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("sidekick.agent.CONFIG_FILE", str(config_path))
    agent = _make_agent()
    agent.set_personality("pirate")
    saved = json.loads(config_path.read_text())
    assert saved["personality"] == PERSONALITY_PRESETS["pirate"]


def test_personality_loaded_on_init(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"personality": "Be extremely dramatic."}))
    monkeypatch.setattr("sidekick.agent.CONFIG_FILE", str(config_path))
    agent = _make_agent()
    assert agent.personality == "Be extremely dramatic."
