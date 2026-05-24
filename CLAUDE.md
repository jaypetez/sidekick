# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sidekick is a Telegram bot that manages Google Calendar, Gmail, Google Tasks, and scheduled reminders through natural language. It uses Claude AI via the Anthropic API and connects to Google APIs through the Model Context Protocol (MCP).

## Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# Run bot
sidekick

# Run all tests
pytest -v

# Run a single test file
pytest tests/test_mcp_server.py -v

# Run a single test
pytest tests/test_reminders.py::test_add_reminder_cron -v
```

## Architecture

The bot runs two processes in one event loop:

1. **Telegram bot** (`bot.py`) — PTB v21 Application with async handlers. Entry point is `sidekick.bot:main`.
2. **MCP subprocess** (`mcp_server.py`) — Spawned as a child process using stdio transport. Wraps Google Calendar, Gmail, and Tasks APIs as MCP tools.

### Tool Routing (Dual Dispatch)

`agent.py` maintains a Claude tool-use loop that routes tools two ways:

- **MCP tools** (calendar, email, tasks) → forwarded to the MCP subprocess via `ClientSession.call_tool()`
- **Local reminder tools** (`list_reminders`, `add_reminder`, `update_reminder`, `remove_reminder`) → handled in-process by calling `reminders.py` functions directly, because they need access to the APScheduler instance running in the parent process

The set `LOCAL_REMINDER_TOOLS` in `agent.py` determines routing.

### Startup Sequence (`bot.py:post_init`)

1. Spawn MCP subprocess → wait for `session_ready` event
2. Create AsyncIOScheduler → register built-in jobs → load custom reminders from JSON → start scheduler
3. Create FamilyAgent with mcp_session, scheduler, bot, and reminder_chat_id
4. Load tool definitions (MCP tools + local reminder tool defs)

### Reminders (`reminders.py`)

- **Built-in**: morning summary (CronTrigger) and pre-event check (IntervalTrigger). Can be paused/resumed but not removed.
- **Custom**: User-created via chat. Persisted to `~/.config/sidekick/reminders.json`. Restored on restart via `load_custom_reminders()`.
- `send_custom_reminder()` reads `REMINDER_CHAT_ID` from env at send time (not from stored value).

### Conversation History

Per-chat history in `agent.py` (`conversation_history` dict keyed by Telegram chat_id). Bounded to `MAX_HISTORY_TURNS = 20` pairs. On `BadRequestError`, history is cleared for that chat.

## Key Environment Variables

| Variable | Default | Required |
|----------|---------|----------|
| `TELEGRAM_BOT_TOKEN` | — | Yes |
| `ANTHROPIC_API_KEY` | — | Yes |
| `GOOGLE_TOKEN_FILE` | `token.json` | No |
| `REMINDER_CHAT_ID` | — | No (disables reminders if unset) |
| `TIMEZONE` | `America/Chicago` | No |
| `CLAUDE_MODEL` | `claude-haiku-4-5-20251001` | No |

## Testing

Tests use `unittest.mock` — no live API calls. Key fixtures in `conftest.py`:
- `mock_scheduler` / `mock_bot` — MagicMock objects
- `tmp_reminders_file` — patches `REMINDERS_FILE` to a temp path (always use this when testing reminder persistence)

MCP server tests use `_make_server()` which patches the MCP `Server` class to avoid startup.

CI runs pytest on Python 3.11 and 3.12 via GitHub Actions.
