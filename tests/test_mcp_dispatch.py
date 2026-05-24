"""Tests for MCPServer._dispatch — every tool name routes to the right provider."""

from unittest.mock import MagicMock, patch

import pytest

from sidekick.mcp_server import MCPServer


@pytest.fixture
def server():
    with patch("sidekick.mcp_server.Server"):
        s = MCPServer()
    # Override lazy providers with mocks so we can assert routing.
    s._calendar = MagicMock()
    s._tasks_store = MagicMock()
    return s


def test_dispatch_unknown_tool_returns_error(server):
    result = server._dispatch("nope", {})
    assert result == {"error": "Unknown tool: nope"}


def test_dispatch_list_events(server):
    server._calendar.list_events.return_value = [{"id": "e1"}]
    assert server._dispatch("list_events", {"start_date": "x"}) == [{"id": "e1"}]
    server._calendar.list_events.assert_called_once_with({"start_date": "x"})


def test_dispatch_create_event(server):
    server._calendar.create_event.return_value = {"id": "new"}
    assert server._dispatch("create_event", {"summary": "t"}) == {"id": "new"}
    server._calendar.create_event.assert_called_once()


def test_dispatch_update_event(server):
    server._calendar.update_event.return_value = {"id": "u"}
    assert server._dispatch("update_event", {"event_id": "u"}) == {"id": "u"}
    server._calendar.update_event.assert_called_once()


def test_dispatch_delete_event(server):
    server._calendar.delete_event.return_value = {"status": "deleted"}
    assert server._dispatch("delete_event", {"event_id": "u"}) == {"status": "deleted"}


def test_dispatch_list_task_lists(server):
    server._tasks_store.list_task_lists.return_value = [{"title": "Costco"}]
    assert server._dispatch("list_task_lists", {}) == [{"title": "Costco"}]


def test_dispatch_list_tasks(server):
    server._tasks_store.list_tasks.return_value = [{"title": "milk"}]
    assert server._dispatch("list_tasks", {"list_name": "Costco"}) == [{"title": "milk"}]


def test_dispatch_add_tasks(server):
    server._tasks_store.add_tasks.return_value = {"status": "added"}
    result = server._dispatch("add_tasks", {"list_name": "Costco", "items": ["milk"]})
    assert result == {"status": "added"}
    server._tasks_store.add_tasks.assert_called_once()


def test_dispatch_complete_task(server):
    server._tasks_store.complete_task.return_value = {"status": "completed"}
    assert server._dispatch("complete_task", {}) == {"status": "completed"}


def test_dispatch_delete_task(server):
    server._tasks_store.delete_task.return_value = {"status": "deleted"}
    assert server._dispatch("delete_task", {}) == {"status": "deleted"}


def test_dispatch_clear_completed(server):
    server._tasks_store.clear_completed.return_value = {"status": "cleared"}
    assert server._dispatch("clear_completed", {"list_name": "Costco"}) == {"status": "cleared"}


def test_dispatch_delete_task_list(server):
    server._tasks_store.delete_task_list.return_value = {"status": "deleted"}
    assert server._dispatch("delete_task_list", {}) == {"status": "deleted"}


def test_dispatch_rename_task_list(server):
    server._tasks_store.rename_task_list.return_value = {"status": "renamed"}
    assert server._dispatch("rename_task_list", {}) == {"status": "renamed"}


def test_dispatch_helpers_passthrough(server):
    server._tasks_store.find_task_list.return_value = 7
    server._tasks_store.get_or_create_task_list.return_value = 7
    server._tasks_store.find_task_by_title.return_value = {"id": 1, "title": "milk"}
    assert server._find_task_list("Costco") == 7
    assert server._get_or_create_task_list("Costco") == 7
    assert server._find_task_by_title(7, "milk") == {"id": 1, "title": "milk"}


def test_calendar_property_lazy_init():
    """First access to .calendar should construct a ChronaryProvider."""
    with patch("sidekick.mcp_server.Server"):
        s = MCPServer()
    with patch("sidekick.mcp_server.ChronaryProvider") as provider_cls:
        provider_cls.return_value = MagicMock()
        _ = s.calendar  # triggers construction
        provider_cls.assert_called_once()
    # Second access uses the cached one — no new construction.
    with patch("sidekick.mcp_server.ChronaryProvider") as provider_cls:
        _ = s.calendar
        provider_cls.assert_not_called()


def test_tasks_store_property_lazy_init():
    with patch("sidekick.mcp_server.Server"):
        s = MCPServer()
    with patch("sidekick.mcp_server.SQLiteTaskStore") as store_cls:
        store_cls.return_value = MagicMock()
        _ = s.tasks_store
        store_cls.assert_called_once()
