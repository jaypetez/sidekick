"""Local SQLite TaskStore.

Replaces GoogleTasksStore. Stores task lists and tasks in a SQLite
database (default path: ~/.config/sidekick/sidekick.db, override via
SIDEKICK_DB_PATH).

stdlib sqlite3 is fine here: the MCP dispatch already shunts sync
provider calls onto a thread executor (see mcp_server._dispatch), so
adding aiosqlite would be unnecessary complexity.

Schema:
  task_lists(id, name)              UNIQUE name (case-insensitive via COLLATE NOCASE)
  tasks(id, list_id, title, status) status ∈ {incomplete, completed}, FK cascade
"""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .. import paths
from .base import TaskStore

SCHEMA = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS task_lists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    list_id INTEGER NOT NULL REFERENCES task_lists(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'incomplete'
        CHECK (status IN ('incomplete', 'completed')),
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_list_status
    ON tasks(list_id, status);
"""


def default_db_path() -> str:
    """Effective tasks database path (``SIDEKICK_DB_PATH`` or the default)."""
    return _default_db_path()


def _default_db_path() -> str:
    return paths.db_path()


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with foreign keys + WAL enabled.

    ``check_same_thread=False`` is required because the web layer constructs
    the store on the asyncio loop thread but dispatches every call through
    ``loop.run_in_executor``, which hands off to worker threads.

    That flag alone does **not** make sharing safe: transaction state is per
    *connection*, so without serialization one thread's ``commit()`` can
    commit another thread's half-finished write. :class:`SQLiteTaskStore`
    therefore guards every method with a lock and wraps writes in
    :meth:`SQLiteTaskStore._tx`. (WAL only helps *separate* connections —
    e.g. the MCP subprocess and the web process.)
    """
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class SQLiteTaskStore(TaskStore):
    def __init__(
        self, db_path: str | None = None, *, conn: sqlite3.Connection | None = None
    ) -> None:
        """Either pass an explicit `conn` (tests use ":memory:") or let it open
        a file connection from `db_path` / SIDEKICK_DB_PATH."""
        if conn is not None:
            self._conn = conn
            # Ensure schema exists on the injected connection.
            self._conn.executescript(SCHEMA)
            if self._conn.row_factory is None:
                self._conn.row_factory = sqlite3.Row
        else:
            self._conn = _connect(db_path or _default_db_path())
        # One connection is shared by every executor thread; see _connect().
        self._lock = threading.RLock()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        """Serialize access and run the block as one transaction.

        Commits on success and rolls back on *any* exception, so a failure
        part-way through a multi-row write (or a constraint violation) never
        leaves an open transaction for the next caller to commit by accident.
        """
        with self._lock, self._conn:
            yield self._conn

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def find_task_list(self, list_name: str) -> int | None:
        """Find a task list id by name (case-insensitive). Returns None if absent."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM task_lists WHERE name = ? COLLATE NOCASE",
                (list_name,),
            ).fetchone()
        return row["id"] if row else None

    def get_or_create_task_list(self, list_name: str) -> int:
        with self._tx():
            return self._get_or_create_locked(list_name)

    def _get_or_create_locked(self, list_name: str) -> int:
        """Caller holds the lock / transaction. Race-free via INSERT OR IGNORE."""
        self._conn.execute(
            "INSERT OR IGNORE INTO task_lists (name) VALUES (?)",
            (list_name,),
        )
        row = self._conn.execute(
            "SELECT id FROM task_lists WHERE name = ? COLLATE NOCASE",
            (list_name,),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    def _missing_list(self, list_name: str) -> dict[str, Any]:
        return {"error": f"Task list '{list_name}' not found"}

    def find_task_by_title(self, list_id: int, title: str) -> dict[str, Any] | None:
        """First incomplete task matching ``title`` exactly (case-insensitive).

        **Behavior change (PR #1 of security tier):** previously this used a
        ``LIKE %title%`` partial match, which the web UI relied on to map
        button clicks back to rows. The web layer now uses the ``*_by_id``
        variants below; the title-based methods retain only exact-match
        semantics so the chat-driven flow (where Claude echoes the exact
        item it just listed) stays predictable.
        """
        with self._lock:
            row = self._conn.execute(
                "SELECT id, title, status FROM tasks "
                "WHERE list_id = ? AND status = 'incomplete' "
                "AND title = ? COLLATE NOCASE LIMIT 1",
                (list_id, title),
            ).fetchone()
        return dict(row) if row else None

    def get_item_by_id(self, item_id: int) -> dict[str, Any] | None:
        """Return a task row by its primary key, or None if missing."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id, list_id, title, status FROM tasks WHERE id = ?",
                (item_id,),
            ).fetchone()
        return dict(row) if row else None

    def complete_item_by_id(self, item_id: int) -> dict[str, Any]:
        """Mark a task complete by primary key.

        Used by the web handlers — id-based ops sidestep the title-encoding
        and partial-match hazards that the original LIKE-based lookup
        introduced.
        """
        with self._tx() as conn:
            row = self.get_item_by_id(item_id)
            if not row:
                return {"error": f"No task with id {item_id}"}
            conn.execute(
                "UPDATE tasks SET status = 'completed', "
                "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (item_id,),
            )
        return {"status": "completed", "title": row["title"], "id": item_id}

    def delete_item_by_id(self, item_id: int) -> dict[str, Any]:
        """Delete a task by primary key. Returns error dict when missing."""
        with self._tx() as conn:
            row = self.get_item_by_id(item_id)
            if not row:
                return {"error": f"No task with id {item_id}"}
            conn.execute("DELETE FROM tasks WHERE id = ?", (item_id,))
        return {"status": "deleted", "title": row["title"], "id": item_id}

    # ------------------------------------------------------------------
    # TaskStore interface
    # ------------------------------------------------------------------

    def list_tasks(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        # Read-only: looking at a list that doesn't exist (a typo, "Costoc")
        # must not create it.
        list_id = self.find_task_list(args["list_name"])
        if list_id is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, title, status FROM tasks "
                "WHERE list_id = ? AND status = 'incomplete' ORDER BY id",
                (list_id,),
            ).fetchall()
        return [{"id": r["id"], "title": r["title"], "status": r["status"]} for r in rows]

    def add_tasks(self, args: dict[str, Any]) -> dict[str, Any]:
        items = args.get("items")
        # A bare string would be iterated character by character
        # ("milk" -> "m", "i", "l", "k").
        if isinstance(items, str) or not isinstance(items, list):
            return {"error": "items must be a list of task titles"}
        if not all(isinstance(item, str) and item.strip() for item in items):
            return {"error": "every item must be a non-empty string"}
        with self._tx() as conn:
            list_id = self._get_or_create_locked(args["list_name"])
            conn.executemany(
                "INSERT INTO tasks (list_id, title) VALUES (?, ?)",
                [(list_id, item) for item in items],
            )
        return {"status": "added", "items": list(items), "list": args["list_name"]}

    def complete_task(self, args: dict[str, Any]) -> dict[str, Any]:
        with self._tx() as conn:
            list_id = self.find_task_list(args["list_name"])
            if list_id is None:
                return self._missing_list(args["list_name"])
            task = self.find_task_by_title(list_id, args["task_title"])
            if not task:
                return {
                    "error": (
                        f"No task matching '{args['task_title']}' found in {args['list_name']}"
                    )
                }
            conn.execute(
                "UPDATE tasks SET status = 'completed', "
                "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (task["id"],),
            )
        return {"status": "completed", "title": task["title"]}

    def delete_task(self, args: dict[str, Any]) -> dict[str, Any]:
        with self._tx() as conn:
            list_id = self.find_task_list(args["list_name"])
            if list_id is None:
                return self._missing_list(args["list_name"])
            task = self.find_task_by_title(list_id, args["task_title"])
            if not task:
                return {
                    "error": (
                        f"No task matching '{args['task_title']}' found in {args['list_name']}"
                    )
                }
            conn.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))
        return {"status": "deleted", "title": task["title"]}

    def clear_completed(self, args: dict[str, Any]) -> dict[str, Any]:
        with self._tx() as conn:
            list_id = self.find_task_list(args["list_name"])
            if list_id is None:
                return self._missing_list(args["list_name"])
            conn.execute(
                "DELETE FROM tasks WHERE list_id = ? AND status = 'completed'",
                (list_id,),
            )
        return {"status": "cleared", "list": args["list_name"]}

    def list_task_lists(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT id, name FROM task_lists ORDER BY name").fetchall()
        return [{"title": r["name"], "id": str(r["id"])} for r in rows]

    def delete_task_list(self, args: dict[str, Any]) -> dict[str, Any]:
        with self._tx() as conn:
            list_id = self.find_task_list(args["list_name"])
            if list_id is None:
                return self._missing_list(args["list_name"])
            conn.execute("DELETE FROM task_lists WHERE id = ?", (list_id,))
        return {"status": "deleted", "list": args["list_name"]}

    def rename_task_list(self, args: dict[str, Any]) -> dict[str, Any]:
        try:
            with self._tx() as conn:
                list_id = self.find_task_list(args["list_name"])
                if list_id is None:
                    return self._missing_list(args["list_name"])
                conn.execute(
                    "UPDATE task_lists SET name = ? WHERE id = ?",
                    (args["new_name"], list_id),
                )
        except sqlite3.IntegrityError:
            # _tx() already rolled back — no transaction left open.
            return {"error": f"A task list named '{args['new_name']}' already exists"}
        return {
            "status": "renamed",
            "old_name": args["list_name"],
            "new_name": args["new_name"],
        }
