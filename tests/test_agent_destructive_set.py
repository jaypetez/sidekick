"""Verify the DESTRUCTIVE_TOOLS constant covers all irreversible tools."""

from __future__ import annotations

from sidekick.agent import DESTRUCTIVE_TOOLS


def test_destructive_tools_membership() -> None:
    expected = {
        "delete_event",
        "delete_task_list",
        "delete_task_item",
        "clear_completed_items",
        "remove_reminder",
    }
    assert DESTRUCTIVE_TOOLS == expected


def test_destructive_tools_is_frozenset() -> None:
    assert isinstance(DESTRUCTIVE_TOOLS, frozenset)
