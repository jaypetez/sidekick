from unittest.mock import MagicMock, patch

from sidekick.mcp_server import MCPServer


@patch("sidekick.mcp_server.Server")
def _make_server(mock_server_cls):
    """Create an MCPServer without starting a real MCP server."""
    server = MCPServer()
    return server


# -------------------------------------------------------------------
# _dispatch
# -------------------------------------------------------------------


def test_dispatch_unknown_tool():
    server = _make_server()
    result = server._dispatch("nonexistent_tool", {})
    assert result == {"error": "Unknown tool: nonexistent_tool"}


def test_dispatch_all_tools_registered():
    """Every advertised MCP tool name must resolve through _dispatch."""
    server = _make_server()
    expected_tools = [
        "list_events", "create_event", "update_event", "delete_event",
        "send_email",
        "list_task_lists", "list_tasks", "add_tasks", "complete_task",
        "delete_task", "clear_completed", "delete_task_list", "rename_task_list",
    ]
    for tool_name in expected_tools:
        handler = MagicMock(return_value={"ok": True})
        setattr(server, f"_{tool_name}", handler)

    for tool_name in expected_tools:
        result = server._dispatch(tool_name, {"test": True})
        assert result != {"error": f"Unknown tool: {tool_name}"}, f"{tool_name} not registered"
