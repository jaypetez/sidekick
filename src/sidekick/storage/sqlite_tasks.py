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

import os
import sqlite3
from pathlib import Path

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


def _default_db_path() -> str:
    return os.getenv(
        "SIDEKICK_DB_PATH",
        os.path.expanduser("~/.config/sidekick/sidekick.db"),
    )


def _connect(db_path: str) -> sqlite3.Connection:
    """Open a connection with foreign keys + WAL enabled."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


class SQLiteTaskStore(TaskStore):
    def __init__(self, db_path: str | None = None, *, conn: sqlite3.Connection | None = None) -> None:
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

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def find_task_list(self, list_name: str) -> int | None:
        """Find a task list id by name (case-insensitive). Returns None if absent."""
        row = self._conn.execute(
            "SELECT id FROM task_lists WHERE name = ? COLLATE NOCASE",
            (list_name,),
        ).fetchone()
        return row["id"] if row else None

    def get_or_create_task_list(self, list_name: str) -> int:
        list_id = self.find_task_list(list_name)
        if list_id is not None:
            return list_id
        cursor = self._conn.execute(
            "INSERT INTO task_lists (name) VALUES (?)", (list_name,)
        )
        self._conn.commit()
        return cursor.lastrowid

    def find_task_by_title(self, list_id: int, title: str) -> dict | None:
        """First incomplete task matching title (case-insensitive partial match)."""
        row = self._conn.execute(
            "SELECT id, title, status FROM tasks "
            "WHERE list_id = ? AND status = 'incomplete' "
            "AND title LIKE ? COLLATE NOCASE LIMIT 1",
            (list_id, f"%{title}%"),
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # TaskStore interface
    # ------------------------------------------------------------------

    def list_tasks(self, args: dict) -> list[dict]:
        list_id = self.get_or_create_task_list(args["list_name"])
        rows = self._conn.execute(
            "SELECT title, status FROM tasks "
            "WHERE list_id = ? AND status = 'incomplete' ORDER BY id",
            (list_id,),
        ).fetchall()
        return [{"title": r["title"], "status": r["status"]} for r in rows]

    def add_tasks(self, args: dict) -> dict:
        list_id = self.get_or_create_task_list(args["list_name"])
        added = []
        for item in args["items"]:
            self._conn.execute(
                "INSERT INTO tasks (list_id, title) VALUES (?, ?)",
                (list_id, item),
            )
            added.append(item)
        self._conn.commit()
        return {"status": "added", "items": added, "list": args["list_name"]}

    def complete_task(self, args: dict) -> dict:
        list_id = self.get_or_create_task_list(args["list_name"])
        task = self.find_task_by_title(list_id, args["task_title"])
        if not task:
            return {"error": f"No task matching '{args['task_title']}' found in {args['list_name']}"}
        self._conn.execute(
            "UPDATE tasks SET status = 'completed', "
            "completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (task["id"],),
        )
        self._conn.commit()
        return {"status": "completed", "title": task["title"]}

    def delete_task(self, args: dict) -> dict:
        list_id = self.get_or_create_task_list(args["list_name"])
        task = self.find_task_by_title(list_id, args["task_title"])
        if not task:
            return {"error": f"No task matching '{args['task_title']}' found in {args['list_name']}"}
        self._conn.execute("DELETE FROM tasks WHERE id = ?", (task["id"],))
        self._conn.commit()
        return {"status": "deleted", "title": task["title"]}

    def clear_completed(self, args: dict) -> dict:
        list_id = self.get_or_create_task_list(args["list_name"])
        self._conn.execute(
            "DELETE FROM tasks WHERE list_id = ? AND status = 'completed'",
            (list_id,),
        )
        self._conn.commit()
        return {"status": "cleared", "list": args["list_name"]}

    def list_task_lists(self, args: dict) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, name FROM task_lists ORDER BY name"
        ).fetchall()
        return [{"title": r["name"], "id": str(r["id"])} for r in rows]

    def delete_task_list(self, args: dict) -> dict:
        list_id = self.find_task_list(args["list_name"])
        if list_id is None:
            return {"error": f"Task list '{args['list_name']}' not found"}
        self._conn.execute("DELETE FROM task_lists WHERE id = ?", (list_id,))
        self._conn.commit()
        return {"status": "deleted", "list": args["list_name"]}

    def rename_task_list(self, args: dict) -> dict:
        list_id = self.find_task_list(args["list_name"])
        if list_id is None:
            return {"error": f"Task list '{args['list_name']}' not found"}
        try:
            self._conn.execute(
                "UPDATE task_lists SET name = ? WHERE id = ?",
                (args["new_name"], list_id),
            )
            self._conn.commit()
        except sqlite3.IntegrityError:
            return {"error": f"A task list named '{args['new_name']}' already exists"}
        return {
            "status": "renamed",
            "old_name": args["list_name"],
            "new_name": args["new_name"],
        }
