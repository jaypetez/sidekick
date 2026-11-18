"""Regression tests for the data-layer review fixes.

* SQLiteTaskStore: transactional writes, thread safety, no accidental list
  creation on reads, string-vs-list ``items``.
* ChronaryProvider.list_events: follows pages instead of truncating.
* Ollama translation: tool results carry ``tool_name``.
"""

from __future__ import annotations

import sqlite3
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sidekick.calendar.chronary import MAX_EVENTS, ChronaryProvider
from sidekick.llm.ollama import _messages_anthropic_to_ollama
from sidekick.storage.sqlite_tasks import SQLiteTaskStore


@pytest.fixture
def store():
    return SQLiteTaskStore(conn=sqlite3.connect(":memory:", check_same_thread=False))


def _titles(store: SQLiteTaskStore, name: str) -> list[str]:
    return [t["title"] for t in store.list_tasks({"list_name": name})]


# --- SQLiteTaskStore -------------------------------------------------------------


def test_failed_add_rolls_back_completely(store):
    """Regression: a bad item mid-loop left earlier rows in an open
    transaction; the LLM's retry then committed duplicates."""
    result = store.add_tasks({"list_name": "Groceries", "items": ["milk", "eggs", {"x": 1}]})
    assert "error" in result
    assert store.find_task_list("Groceries") is None
    assert not store._conn.in_transaction

    store.add_tasks({"list_name": "Groceries", "items": ["milk", "eggs", "bread"]})
    assert _titles(store, "Groceries") == ["milk", "eggs", "bread"]


def test_string_items_rejected_not_split_into_characters(store):
    result = store.add_tasks({"list_name": "Groceries", "items": "milk"})
    assert "error" in result
    assert store.list_task_lists({}) == []


def test_reads_do_not_create_lists(store):
    """Regression: "show my Costoc list" created an empty "Costoc" list."""
    assert store.list_tasks({"list_name": "Costoc"}) == []
    assert "error" in store.complete_task({"list_name": "Costoc", "task_title": "x"})
    assert "error" in store.delete_task({"list_name": "Costoc", "task_title": "x"})
    assert "error" in store.clear_completed({"list_name": "Costoc"})
    assert store.list_task_lists({}) == []


def test_failed_rename_leaves_no_open_transaction(store):
    store.add_tasks({"list_name": "A", "items": ["1"]})
    store.add_tasks({"list_name": "B", "items": ["2"]})
    result = store.rename_task_list({"list_name": "A", "new_name": "B"})
    assert "error" in result
    assert not store._conn.in_transaction


def test_get_or_create_is_idempotent(store):
    first = store.get_or_create_task_list("Home")
    assert store.get_or_create_task_list("home") == first  # NOCASE
    assert len(store.list_task_lists({})) == 1


def test_concurrent_adds_on_shared_connection(tmp_path):
    """One connection shared by executor threads: no lost rows, no UNIQUE
    errors when two threads create the same new list."""
    store = SQLiteTaskStore(db_path=str(tmp_path / "t.db"))
    errors: list[object] = []

    def worker(i: int) -> None:
        result = store.add_tasks({"list_name": "Shared", "items": [f"item-{i}"]})
        if "error" in result:
            errors.append(result)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    assert sorted(_titles(store, "Shared")) == sorted(f"item-{i}" for i in range(30))


# --- ChronaryProvider pagination ---------------------------------------------------


def _event(i: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"evt_{i}",
        title=f"Event {i}",
        start_time="2026-04-01T09:00:00Z",
        end_time="2026-04-01T10:00:00Z",
        description="",
        metadata=None,
        status="confirmed",
        all_day=False,
        recurring_event_id=None,
    )


def _paging_client(total: int) -> MagicMock:
    events = [_event(i) for i in range(total)]
    client = MagicMock()

    def list_page(calendar_id, *, start_after, start_before, limit, offset=None):
        start = offset or 0
        return SimpleNamespace(data=events[start : start + limit], total=total)

    client.events.list.side_effect = list_page
    return client


def _provider(client) -> ChronaryProvider:
    return ChronaryProvider(client=client, agent_id="a", calendar_id="c", timezone="UTC")


def test_list_events_follows_pages():
    """Regression: only the first page was returned, so 'this month' with 35
    events silently showed 20."""
    client = _paging_client(135)
    events = _provider(client).list_events(
        {"start_date": "2026-04-01", "end_date": "2026-04-30", "max_results": 200}
    )
    assert [e["id"] for e in events] == [f"evt_{i}" for i in range(135)]
    assert client.events.list.call_count == 2


def test_list_events_respects_max_results_and_cap():
    client = _paging_client(400)
    events = _provider(client).list_events(
        {"start_date": "2026-04-01", "end_date": "2026-04-30", "max_results": 10_000}
    )
    assert len(events) == MAX_EVENTS

    client = _paging_client(400)
    assert (
        len(
            _provider(client).list_events(
                {"start_date": "2026-04-01", "end_date": "2026-04-01", "max_results": 7}
            )
        )
        == 7
    )


def test_list_events_exposes_status_and_recurrence():
    client = MagicMock()
    client.events.list.return_value = SimpleNamespace(
        data=[
            SimpleNamespace(
                id="e1",
                title="Hold",
                start_time="2026-04-01",
                end_time="2026-04-02",
                description="",
                metadata={},
                status="tentative",
                all_day=True,
                recurring_event_id="series_1",
            )
        ],
        total=1,
    )
    (event,) = _provider(client).list_events({"start_date": "2026-04-01", "end_date": "2026-04-01"})
    assert event["status"] == "tentative"
    assert event["all_day"] is True
    assert event["recurring_event_id"] == "series_1"


# --- Ollama translation --------------------------------------------------------------


def test_tool_results_carry_tool_name():
    msgs = [
        {"role": "user", "content": "groceries + calendar?"},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "t1", "name": "list_tasks", "input": {}},
                {"type": "tool_use", "id": "t2", "name": "list_events", "input": {}},
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "t2", "content": "[]"},
                {"type": "tool_result", "tool_use_id": "t1", "content": "[milk]"},
            ],
        },
    ]
    out = _messages_anthropic_to_ollama(msgs)
    tool_msgs = [m for m in out if m["role"] == "tool"]
    assert [(m["tool_name"], m["content"]) for m in tool_msgs] == [
        ("list_events", "[]"),
        ("list_tasks", "[milk]"),
    ]
