"""Verify the DESTRUCTIVE_TOOLS constant covers all irreversible tools."""

from __future__ import annotations

import pytest
from mcp import types

from sidekick.agent import DESTRUCTIVE_TOOLS, LOCAL_REMINDER_TOOLS
from sidekick.mcp_server import MCPServer


def test_destructive_tools_membership() -> None:
    expected = {
        "delete_event",
        "delete_task_list",
        "delete_task",
        "clear_completed",
        "remove_reminder",
    }
    assert DESTRUCTIVE_TOOLS == expected


def test_destructive_tools_is_frozenset() -> None:
    assert isinstance(DESTRUCTIVE_TOOLS, frozenset)


@pytest.mark.asyncio
async def test_destructive_tools_are_real_tool_names() -> None:
    """Every entry must name a tool the agent can actually call.

    A misspelt name never matches, so the destructive-call log line would
    silently stop firing for that tool.
    """
    server = MCPServer()
    handler = server.server.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest(method="tools/list"))
    mcp_names = {tool.name for tool in result.root.tools}  # type: ignore[union-attr]
    known = mcp_names | set(LOCAL_REMINDER_TOOLS)
    assert DESTRUCTIVE_TOOLS <= known, DESTRUCTIVE_TOOLS - known
