"""Tests for SQLiteTaskStore using an in-memory database."""

import asyncio
import sqlite3
import threading

import pytest

from sidekick.storage.sqlite_tasks import SQLiteTaskStore


@pytest.fixture
def store():
    conn = sqlite3.connect(":memory:")
    return SQLiteTaskStore(conn=conn)


@pytest.fixture
def file_store(tmp_path):
    """A file-backed store, like production. Exercises the _connect path."""
    db_path = tmp_path / "test.db"
    return SQLiteTaskStore(db_path=str(db_path))


def test_file_backed_store_works_across_threads(file_store):
    """The web layer constructs the store on the asyncio loop thread but
    every call hops to a ThreadPoolExecutor worker. Without
    ``check_same_thread=False`` in _connect, sqlite3 raises
    ProgrammingError on the first cross-thread call.
    """
    file_store.add_tasks({"list_name": "Costco", "items": ["milk"]})

    result: dict = {}

    def worker() -> None:
        try:
            result["lists"] = file_store.list_task_lists({})
            result["items"] = file_store.list_tasks({"list_name": "Costco"})
        except Exception as exc:
            result["error"] = exc

    t = threading.Thread(target=worker)
    t.start()
    t.join(timeout=5)
    assert "error" not in result, f"Cross-thread call raised: {result.get('error')}"
    assert [r["title"] for r in result["lists"]] == ["Costco"]
    assert [r["title"] for r in result["items"]] == ["milk"]


def test_file_backed_store_works_from_executor(file_store):
    """End-to-end: mirror the exact flow the web layer uses (loop.run_in_executor)."""

    async def runner() -> list:
        loop = asyncio.get_running_loop()
        file_store.add_tasks({"list_name": "Home", "items": ["paint"]})
        return await loop.run_in_executor(None, file_store.list_task_lists, {})

    lists = asyncio.run(runner())
    assert any(row["title"] == "Home" for row in lists)


# -------------------------------------------------------------------
# Lists
# -------------------------------------------------------------------


def test_list_task_lists_empty(store):
    assert store.list_task_lists({}) == []


def test_add_tasks_auto_creates_list(store):
    result = store.add_tasks({"list_name": "Costco", "items": ["milk", "eggs"]})
    assert result["status"] == "added"
    assert result["items"] == ["milk", "eggs"]

    lists = store.list_task_lists({})
    assert len(lists) == 1
    assert lists[0]["title"] == "Costco"


def test_list_task_lists_sorts_alphabetically(store):
    store.add_tasks({"list_name": "Zebra", "items": ["a"]})
    store.add_tasks({"list_name": "Apple", "items": ["a"]})
    store.add_tasks({"list_name": "Mango", "items": ["a"]})

    titles = [r["title"] for r in store.list_task_lists({})]
    assert titles == ["Apple", "Mango", "Zebra"]


# -------------------------------------------------------------------
# find_task_list — case-insensitive
# -------------------------------------------------------------------


def test_find_task_list_case_insensitive(store):
    store.add_tasks({"list_name": "Costco", "items": ["x"]})
    assert store.find_task_list("costco") is not None
    assert store.find_task_list("COSTCO") is not None
    assert store.find_task_list("Trader Joe's") is None


def test_get_or_create_returns_existing(store):
    id1 = store.get_or_create_task_list("Costco")
    id2 = store.get_or_create_task_list("costco")  # case-insensitive
    assert id1 == id2


# -------------------------------------------------------------------
# Tasks
# -------------------------------------------------------------------


def test_list_tasks_only_incomplete(store):
    store.add_tasks({"list_name": "X", "items": ["a", "b", "c"]})
    store.complete_task({"list_name": "X", "task_title": "b"})

    titles = [t["title"] for t in store.list_tasks({"list_name": "X"})]
    assert titles == ["a", "c"]


def test_complete_task_partial_match_case_insensitive(store):
    store.add_tasks({"list_name": "X", "items": ["Buy organic MILK"]})
    result = store.complete_task({"list_name": "X", "task_title": "milk"})
    assert result["status"] == "completed"
    assert "MILK" in result["title"]


def test_complete_task_not_found(store):
    store.add_tasks({"list_name": "X", "items": ["a"]})
    result = store.complete_task({"list_name": "X", "task_title": "nonexistent"})
    assert "error" in result


def test_delete_task_removes_row(store):
    store.add_tasks({"list_name": "X", "items": ["a", "b"]})
    store.delete_task({"list_name": "X", "task_title": "a"})

    titles = [t["title"] for t in store.list_tasks({"list_name": "X"})]
    assert titles == ["b"]


def test_delete_task_not_found(store):
    store.add_tasks({"list_name": "X", "items": ["a"]})
    result = store.delete_task({"list_name": "X", "task_title": "nonexistent"})
    assert "error" in result


def test_clear_completed_removes_only_completed(store):
    store.add_tasks({"list_name": "X", "items": ["a", "b", "c"]})
    store.complete_task({"list_name": "X", "task_title": "a"})
    store.complete_task({"list_name": "X", "task_title": "c"})

    store.clear_completed({"list_name": "X"})

    # Should not affect incomplete tasks
    titles = [t["title"] for t in store.list_tasks({"list_name": "X"})]
    assert titles == ["b"]


# -------------------------------------------------------------------
# List management
# -------------------------------------------------------------------


def test_delete_task_list_cascades(store):
    store.add_tasks({"list_name": "X", "items": ["a", "b"]})
    list_id = store.find_task_list("X")
    assert list_id is not None

    store.delete_task_list({"list_name": "X"})

    # List gone
    assert store.find_task_list("X") is None
    # Tasks cascade-deleted too (foreign key)
    rows = store._conn.execute("SELECT * FROM tasks").fetchall()
    assert rows == []


def test_delete_task_list_not_found(store):
    result = store.delete_task_list({"list_name": "Nope"})
    assert "error" in result


def test_rename_task_list_changes_name(store):
    store.add_tasks({"list_name": "Costco", "items": ["a"]})
    result = store.rename_task_list({"list_name": "Costco", "new_name": "Costco Weekly"})
    assert result == {"status": "renamed", "old_name": "Costco", "new_name": "Costco Weekly"}
    assert store.find_task_list("Costco Weekly") is not None
    assert store.find_task_list("Costco") is None


def test_rename_task_list_not_found(store):
    result = store.rename_task_list({"list_name": "Nope", "new_name": "Still Nope"})
    assert "error" in result


def test_rename_to_existing_name_returns_error(store):
    store.add_tasks({"list_name": "A", "items": ["x"]})
    store.add_tasks({"list_name": "B", "items": ["y"]})
    result = store.rename_task_list({"list_name": "A", "new_name": "B"})
    assert "error" in result


# -------------------------------------------------------------------
# Schema integrity
# -------------------------------------------------------------------


def test_status_check_constraint_rejects_invalid_value(store):
    """Schema CHECK constraint must reject statuses other than the enum."""
    store.add_tasks({"list_name": "X", "items": ["a"]})
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("UPDATE tasks SET status = 'bogus' WHERE title = 'a'")
        store._conn.commit()


def test_unique_list_name_constraint(store):
    """task_lists.name has a UNIQUE constraint (case-insensitive)."""
    store.add_tasks({"list_name": "X", "items": ["a"]})
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute("INSERT INTO task_lists (name) VALUES ('X')")
        store._conn.commit()
