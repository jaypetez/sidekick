"""Tests for the SidekickAgent tool-use loop and reminder dispatch."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import anthropic
import pytest

from sidekick.agent import SidekickAgent


def _make_agent(*, scheduler=None, bot=None, llm=None):
    return SidekickAgent(
        mcp_session=MagicMock(),
        scheduler=scheduler,
        bot=bot,
        reminder_chat_id=-100123,
        llm=llm,
    )


def _text_response(text: str) -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=text)],
    )


def _tool_use_response(tool_name: str, args: dict, *, call_id: str = "t1") -> SimpleNamespace:
    return SimpleNamespace(
        stop_reason="tool_use",
        content=[SimpleNamespace(type="tool_use", id=call_id, name=tool_name, input=args)],
    )


# -------------------------------------------------------------------
# _run_tool_loop / process_message
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_process_message_end_turn_returns_text():
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=_text_response("Hello!"))
    agent = _make_agent(llm=llm)
    reply = await agent.process_message(42, "hi")
    assert reply == "Hello!"
    assert llm.chat.await_count == 1


@pytest.mark.asyncio
async def test_process_message_routes_mcp_tool_to_session():
    """Tool name not in LOCAL_REMINDER_TOOLS gets forwarded to MCP."""
    llm = MagicMock()
    llm.chat = AsyncMock(
        side_effect=[
            _tool_use_response("list_events", {"start_date": "2026-05-01"}),
            _text_response("You have 2 events."),
        ]
    )
    agent = _make_agent(llm=llm)
    agent.session.call_tool = AsyncMock(
        return_value=SimpleNamespace(content=[SimpleNamespace(text='[{"summary": "Dentist"}]')])
    )

    reply = await agent.process_message(42, "what's tomorrow?")

    assert reply == "You have 2 events."
    agent.session.call_tool.assert_awaited_once_with("list_events", {"start_date": "2026-05-01"})
    # Two LLM round trips: one tool_use, one end_turn.
    assert llm.chat.await_count == 2


@pytest.mark.asyncio
async def test_process_message_routes_local_reminder_tool():
    """A tool name in LOCAL_REMINDER_TOOLS is handled in-process, not via MCP."""
    llm = MagicMock()
    llm.chat = AsyncMock(
        side_effect=[
            _tool_use_response("list_reminders", {}),
            _text_response("You have 3 reminders."),
        ]
    )
    scheduler = MagicMock()
    scheduler.get_jobs.return_value = []
    agent = _make_agent(llm=llm, scheduler=scheduler, bot=MagicMock())
    agent.session.call_tool = AsyncMock()

    reply = await agent.process_message(42, "list reminders")

    assert reply == "You have 3 reminders."
    # MCP must NOT be called for reminder tools.
    agent.session.call_tool.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_message_mcp_empty_content_emits_no_result():
    """When MCP returns no content blocks, the loop substitutes an error string."""
    llm = MagicMock()
    captured: list[list[dict]] = []

    async def fake_chat(*, system, messages, tools, max_tokens):
        captured.append([dict(m) for m in messages])
        if len(captured) == 1:
            return _tool_use_response("list_events", {})
        return _text_response("done")

    llm.chat = fake_chat
    agent = _make_agent(llm=llm)
    agent.session.call_tool = AsyncMock(return_value=SimpleNamespace(content=[]))

    reply = await agent.process_message(42, "go")
    assert reply == "done"

    # On the second turn the tool_result should carry the error.
    tool_results_message = captured[1][-1]
    assert tool_results_message["role"] == "user"
    assert json.loads(tool_results_message["content"][0]["content"]) == {"error": "no result"}


@pytest.mark.asyncio
async def test_process_message_clears_history_on_bad_request():
    llm = MagicMock()
    llm.chat = AsyncMock(
        side_effect=anthropic.BadRequestError(
            message="bad",
            response=MagicMock(),
            body={"error": {"message": "bad"}},
        )
    )
    agent = _make_agent(llm=llm)
    # Seed some history so we can verify it gets cleared.
    agent.conversation_history[42] = [{"role": "user", "content": "prior"}]
    reply = await agent.process_message(42, "hi")
    assert "reset" in reply.lower()
    assert 42 not in agent.conversation_history


@pytest.mark.asyncio
async def test_process_message_restores_history_on_unknown_error():
    llm = MagicMock()
    llm.chat = AsyncMock(side_effect=RuntimeError("boom"))
    agent = _make_agent(llm=llm)
    agent.conversation_history[42] = [{"role": "user", "content": "prior"}]
    with pytest.raises(RuntimeError):
        await agent.process_message(42, "hi")
    # History restored to the snapshot from before the failed call.
    assert agent.conversation_history[42] == [{"role": "user", "content": "prior"}]


@pytest.mark.asyncio
async def test_process_message_unexpected_stop_reason_returns_text():
    llm = MagicMock()
    llm.chat = AsyncMock(
        return_value=SimpleNamespace(
            stop_reason="max_tokens",
            content=[SimpleNamespace(type="text", text="Truncated reply.")],
        )
    )
    agent = _make_agent(llm=llm)
    reply = await agent.process_message(42, "hi")
    assert reply == "Truncated reply."


@pytest.mark.asyncio
async def test_process_message_unexpected_stop_reason_with_no_text():
    llm = MagicMock()
    llm.chat = AsyncMock(return_value=SimpleNamespace(stop_reason="max_tokens", content=[]))
    agent = _make_agent(llm=llm)
    reply = await agent.process_message(42, "hi")
    assert reply == "(no response)"


@pytest.mark.asyncio
async def test_mcp_tool_failure_becomes_tool_result_with_is_error():
    """When session.call_tool raises, the loop must surface an error
    tool_result back to the LLM rather than aborting the whole turn."""
    llm = MagicMock()
    captured_messages: list[list[dict]] = []

    async def fake_chat(*, system, messages, tools, max_tokens):
        captured_messages.append([dict(m) for m in messages])
        if len(captured_messages) == 1:
            return _tool_use_response("list_events", {})
        return _text_response("Recovered.")

    llm.chat = fake_chat
    agent = _make_agent(llm=llm)
    agent.session.call_tool = AsyncMock(side_effect=RuntimeError("mcp transport gone"))

    reply = await agent.process_message(42, "go")
    assert reply == "Recovered."

    # On the recovery turn the user message must contain a tool_result with
    # is_error=True so the LLM knows the call failed.
    follow_up = captured_messages[1][-1]
    assert follow_up["role"] == "user"
    block = follow_up["content"][0]
    assert block["type"] == "tool_result"
    assert block.get("is_error") is True
    payload = json.loads(block["content"])
    assert "mcp transport gone" in payload["error"]


@pytest.mark.asyncio
async def test_local_reminder_tool_failure_becomes_tool_result_with_is_error():
    """Local reminder tool exceptions are also captured into tool_result, not raised."""
    llm = MagicMock()
    captured_messages: list[list[dict]] = []

    async def fake_chat(*, system, messages, tools, max_tokens):
        captured_messages.append([dict(m) for m in messages])
        if len(captured_messages) == 1:
            return _tool_use_response("list_reminders", {})
        return _text_response("Handled.")

    llm.chat = fake_chat
    scheduler = MagicMock()
    agent = _make_agent(llm=llm, scheduler=scheduler, bot=MagicMock())
    with patch("sidekick.agent.get_all_reminders", side_effect=RuntimeError("scheduler crashed")):
        reply = await agent.process_message(42, "list")

    assert reply == "Handled."
    follow_up = captured_messages[1][-1]
    block = follow_up["content"][0]
    assert block.get("is_error") is True
    assert "scheduler crashed" in json.loads(block["content"])["error"]


# -------------------------------------------------------------------
# _handle_reminder_tool dispatch
# -------------------------------------------------------------------


def test_handle_reminder_tool_no_scheduler_returns_error():
    agent = _make_agent(scheduler=None, bot=None)
    result = agent._handle_reminder_tool("list_reminders", {})
    assert result == {"error": "Reminder system not available"}


def test_handle_reminder_tool_list_reminders_calls_helper():
    scheduler = MagicMock()
    bot = MagicMock()
    agent = _make_agent(scheduler=scheduler, bot=bot)
    with patch("sidekick.agent.get_all_reminders", return_value=[{"id": "morning"}]) as helper:
        result = agent._handle_reminder_tool("list_reminders", {})
    helper.assert_called_once_with(scheduler)
    assert result == [{"id": "morning"}]


def test_handle_reminder_tool_add_reminder_passes_through():
    scheduler = MagicMock()
    bot = MagicMock()
    agent = _make_agent(scheduler=scheduler, bot=bot)
    with patch("sidekick.agent.add_reminder", return_value={"id": "r1"}) as helper:
        result = agent._handle_reminder_tool(
            "add_reminder",
            {"message": "prep lunches", "hour": 17, "minute": 0, "day_of_week": "sun"},
        )
    helper.assert_called_once()
    kwargs = helper.call_args.kwargs
    assert kwargs["message"] == "prep lunches"
    assert kwargs["hour"] == 17
    assert kwargs["minute"] == 0
    assert kwargs["day_of_week"] == "sun"
    assert result == {"id": "r1"}


def test_handle_reminder_tool_update_reminder_passes_through():
    scheduler = MagicMock()
    agent = _make_agent(scheduler=scheduler, bot=MagicMock())
    with patch("sidekick.agent.update_reminder", return_value={"status": "updated"}) as helper:
        result = agent._handle_reminder_tool(
            "update_reminder",
            {"reminder_id": "morning_summary", "enabled": False},
        )
    helper.assert_called_once()
    assert helper.call_args.kwargs["reminder_id"] == "morning_summary"
    assert helper.call_args.kwargs["enabled"] is False
    assert result == {"status": "updated"}


def test_handle_reminder_tool_remove_reminder_passes_through():
    scheduler = MagicMock()
    agent = _make_agent(scheduler=scheduler, bot=MagicMock())
    with patch("sidekick.agent.remove_reminder", return_value={"status": "removed"}) as helper:
        result = agent._handle_reminder_tool("remove_reminder", {"reminder_id": "r1"})
    helper.assert_called_once_with(scheduler, "r1")
    assert result == {"status": "removed"}


def test_handle_reminder_tool_unknown_name_returns_error():
    agent = _make_agent(scheduler=MagicMock(), bot=MagicMock())
    result = agent._handle_reminder_tool("nope", {})
    assert result == {"error": "Unknown reminder tool: nope"}
