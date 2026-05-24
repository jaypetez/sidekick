from unittest.mock import MagicMock, patch

from sidekick.mcp_server import MCPServer


@patch("sidekick.mcp_server.Server")
def _make_server(mock_server_cls):
    """Create an MCPServer without starting a real MCP server."""
    server = MCPServer()
    return server


# -------------------------------------------------------------------
# _event_to_dict
# -------------------------------------------------------------------


def test_event_to_dict_full():
    server = _make_server()
    event = {
        "id": "abc123",
        "summary": "Team meeting",
        "start": {"dateTime": "2026-03-25T10:00:00-05:00"},
        "end": {"dateTime": "2026-03-25T11:00:00-05:00"},
        "description": "Weekly sync",
        "location": "Room 4B",
    }
    result = server._event_to_dict(event)
    assert result["id"] == "abc123"
    assert result["summary"] == "Team meeting"
    assert result["start"] == "2026-03-25T10:00:00-05:00"
    assert result["end"] == "2026-03-25T11:00:00-05:00"
    assert result["description"] == "Weekly sync"
    assert result["location"] == "Room 4B"


def test_event_to_dict_all_day():
    server = _make_server()
    event = {
        "id": "day1",
        "summary": "Holiday",
        "start": {"date": "2026-12-25"},
        "end": {"date": "2026-12-26"},
    }
    result = server._event_to_dict(event)
    assert result["start"] == "2026-12-25"
    assert result["end"] == "2026-12-26"


def test_event_to_dict_missing_fields():
    server = _make_server()
    event = {"id": "x"}
    result = server._event_to_dict(event)
    assert result["summary"] == "(no title)"
    assert result["description"] == ""
    assert result["location"] == ""
    assert result["start"] is None
    assert result["end"] is None


# -------------------------------------------------------------------
# _dispatch
# -------------------------------------------------------------------


def test_dispatch_unknown_tool():
    server = _make_server()
    result = server._dispatch("nonexistent_tool", {})
    assert result == {"error": "Unknown tool: nonexistent_tool"}


def test_dispatch_all_tools_registered():
    server = _make_server()
    expected_tools = [
        "list_events", "create_event", "update_event", "delete_event",
        "send_email",
        "list_task_lists", "list_tasks", "add_tasks", "complete_task",
        "delete_task", "clear_completed", "delete_task_list", "rename_task_list",
    ]
    for tool_name in expected_tools:
        # Mock the actual handler to avoid calling Google APIs
        handler = MagicMock(return_value={"ok": True})
        setattr(server, f"_{tool_name}", handler)

    # Patch the dispatch table to use our mocked handlers
    for tool_name in expected_tools:
        result = server._dispatch(tool_name, {"test": True})
        # Should not return "Unknown tool" error
        assert result != {"error": f"Unknown tool: {tool_name}"}, f"{tool_name} not registered"


# -------------------------------------------------------------------
# _find_task_list
# -------------------------------------------------------------------


def _make_server_with_tasklists(items):
    """Create a server with mocked tasklists().list() response."""
    server = _make_server()
    server.tasks = MagicMock()
    server.tasks.tasklists().list().execute.return_value = {"items": items}
    return server


def test_find_task_list_found():
    server = _make_server_with_tasklists([
        {"id": "id1", "title": "Costco"},
        {"id": "id2", "title": "To-Do"},
    ])
    assert server._find_task_list("costco") == "id1"
    assert server._find_task_list("COSTCO") == "id1"
    assert server._find_task_list("To-Do") == "id2"


def test_find_task_list_not_found():
    server = _make_server_with_tasklists([
        {"id": "id1", "title": "Costco"},
    ])
    assert server._find_task_list("Trader Joe's") is None


# -------------------------------------------------------------------
# _list_task_lists
# -------------------------------------------------------------------


def test_list_task_lists():
    server = _make_server_with_tasklists([
        {"id": "id1", "title": "Costco"},
        {"id": "id2", "title": "Home Renovation"},
    ])
    result = server._list_task_lists({})
    assert result == [
        {"title": "Costco", "id": "id1"},
        {"title": "Home Renovation", "id": "id2"},
    ]


def test_list_task_lists_empty():
    server = _make_server_with_tasklists([])
    result = server._list_task_lists({})
    assert result == []


# -------------------------------------------------------------------
# _delete_task_list
# -------------------------------------------------------------------


def test_delete_task_list_success():
    server = _make_server_with_tasklists([
        {"id": "id1", "title": "Costco"},
    ])
    result = server._delete_task_list({"list_name": "Costco"})
    assert result == {"status": "deleted", "list": "Costco"}
    server.tasks.tasklists().delete.assert_called()


def test_delete_task_list_not_found():
    server = _make_server_with_tasklists([])
    result = server._delete_task_list({"list_name": "Nope"})
    assert "error" in result


# -------------------------------------------------------------------
# _rename_task_list
# -------------------------------------------------------------------


def test_rename_task_list_success():
    server = _make_server_with_tasklists([
        {"id": "id1", "title": "Costco"},
    ])
    result = server._rename_task_list({"list_name": "Costco", "new_name": "Costco Weekly"})
    assert result == {"status": "renamed", "old_name": "Costco", "new_name": "Costco Weekly"}
    server.tasks.tasklists().patch.assert_called()


def test_rename_task_list_not_found():
    server = _make_server_with_tasklists([])
    result = server._rename_task_list({"list_name": "Nope", "new_name": "Still Nope"})
    assert "error" in result


# -------------------------------------------------------------------
# _list_events timezone boundaries
# -------------------------------------------------------------------


def test_list_events_uses_timezone_boundaries(monkeypatch):
    """Verify _list_events uses configured TIMEZONE for date boundaries, not UTC."""
    monkeypatch.setenv("TIMEZONE", "America/Los_Angeles")
    server = _make_server()
    server.timezone = "America/Los_Angeles"

    # Mock the Google Calendar API
    mock_events = MagicMock()
    mock_events.list.return_value.execute.return_value = {"items": []}
    server.service = MagicMock()
    server.service.events.return_value = mock_events

    server._list_events({"start_date": "2026-04-01", "end_date": "2026-04-01"})

    call_kwargs = mock_events.list.call_args[1]
    # Should use -07:00 offset (PDT), not Z (UTC)
    assert "2026-04-01T00:00:00-07:00" == call_kwargs["timeMin"]
    assert "2026-04-01T23:59:59-07:00" == call_kwargs["timeMax"]
