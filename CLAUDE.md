# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sidekick is a self-hosted chat bot that manages your calendar, task lists, and scheduled reminders through natural language. It runs on Telegram (always) and Slack (optional), uses Chronary.ai for the calendar backend, a local SQLite database for tasks/groceries, and either Anthropic Claude (default) or a local Ollama server for the LLM.

No Google services are in the loop.

## Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# First-time bootstrap (creates Chronary agent + calendar, prints the IDs to paste into .env)
sidekick-init

# Run the bot
sidekick

# All tests (currently 87)
pytest -v

# Single file / single test
pytest tests/test_storage_tasks.py -v
pytest tests/test_calendar_chronary.py::test_list_events_uses_timezone_for_boundaries -v

# Docker
docker compose up -d                      # Anthropic mode
docker compose --profile ollama up -d     # local-LLM mode
```

## Architecture

The bot runs three coordinated processes in a single asyncio event loop:

1. **Telegram bot** (`bot.py`) — python-telegram-bot v21 Application with async handlers. Entry point: `sidekick.bot:main`.
2. **Slack adapter** (`platforms/slack.py`, optional) — runs as a background task in `post_init` iff `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set. Uses `slack-bolt` async + socket mode.
3. **MCP subprocess** (`mcp_server.py`) — spawned via stdio transport. Exposes 12 tools (calendar + tasks). Inside, it delegates to the providers below.

### Provider abstractions

Each backend lives behind an ABC under `src/sidekick/`. Swapping a provider is a single-file change:

| ABC | Concrete | Notes |
|---|---|---|
| `calendar/base.py::CalendarProvider` | `calendar/chronary.py::ChronaryProvider` | Lazy-imports the `chronary` SDK |
| `storage/base.py::TaskStore` | `storage/sqlite_tasks.py::SQLiteTaskStore` | stdlib sqlite3, WAL + FK cascade |
| `llm/base.py::LLMClient` | `llm/anthropic.py::AnthropicClient` (default), `llm/ollama.py::OllamaClient` | Selected by `LLM_PROVIDER` env var via `llm/__init__.py::build_llm_client()` |
| `platforms/base.py::ChatPlatform` | `platforms/slack.py::SlackPlatform` (active), Telegram is still inline in `bot.py` (deferred extraction) | `IncomingMessage` dataclass wraps inbound messages |

### Tool routing (dual dispatch)

`agent.py` maintains a Claude tool-use loop that routes tools two ways:

- **MCP tools** (calendar + tasks, 12 tools) → forwarded to the MCP subprocess via `ClientSession.call_tool()`. The subprocess dispatches to the concrete provider.
- **Local reminder tools** (`list_reminders`, `add_reminder`, `update_reminder`, `remove_reminder`) → handled in-process by calling `reminders.py` functions directly, because they need access to the APScheduler instance running in the parent process.

The set `LOCAL_REMINDER_TOOLS` in `agent.py` determines routing.

### Startup sequence (`bot.py::post_init`)

1. Spawn MCP subprocess → wait for `session_ready` event
2. Create AsyncIOScheduler → register built-in jobs → load custom reminders from JSON → start scheduler
3. Create `FamilyAgent` with mcp_session, scheduler, bot, reminder_chat_id; calls `build_llm_client()` for the LLM
4. Load tool definitions (MCP tools + local reminder tool defs)
5. If `SLACK_BOT_TOKEN` set, start `_run_slack()` as a background task

### Reminders (`reminders.py`)

- **Built-in**: morning summary (CronTrigger) and pre-event check (IntervalTrigger). Can be paused/resumed but not removed.
- **Custom**: User-created via chat. Persisted to `~/.config/sidekick/reminders.json`. Restored on restart via `load_custom_reminders()`.
- `send_custom_reminder()` reads `REMINDER_CHAT_ID` from env at send time (not from the stored value).
- Reminders currently fire only on Telegram. Multi-platform support is a known follow-up.

### Conversation history

Per-chat history in `agent.py` (`conversation_history` dict). Keys are `int` for Telegram chat ids or `"sl:<channel>"` for Slack so platforms don't collide. Bounded to `MAX_HISTORY_TURNS = 20` pairs. On `anthropic.BadRequestError`, history is cleared for that chat.

## Key environment variables

| Variable | Default | Required |
|----------|---------|----------|
| `TELEGRAM_BOT_TOKEN` | — | Yes |
| `LLM_PROVIDER` | `anthropic` | No (`anthropic` \| `ollama`) |
| `ANTHROPIC_API_KEY` | — | Yes if `LLM_PROVIDER=anthropic` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | No |
| `OLLAMA_MODEL` | `llama3.1:8b` | No |
| `CHRONARY_API_KEY` | — | Yes |
| `CHRONARY_AGENT_ID` | — | Yes (set by `sidekick-init`) |
| `CHRONARY_CALENDAR_ID` | — | Yes (set by `sidekick-init`) |
| `SIDEKICK_DB_PATH` | `~/.config/sidekick/sidekick.db` | No |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | — | Only if Slack is enabled |
| `REMINDER_CHAT_ID` | — | No (disables reminders if unset) |
| `TIMEZONE` | `America/Chicago` | No |
| `CLAUDE_MODEL` | `claude-haiku-4-5-20251001` | No |

## Testing

Tests use `unittest.mock` — no live API calls. Notable conventions:

- `mock_scheduler` / `mock_bot` fixtures in `tests/conftest.py`
- `tmp_reminders_file` patches `REMINDERS_FILE` (always use this when testing reminder persistence)
- MCP server tests construct a server with `@patch("sidekick.mcp_server.Server")` to avoid starting the real MCP transport
- SQLite tests inject a `:memory:` connection via the `SQLiteTaskStore(conn=...)` constructor
- Ollama tests use a fake client and verify the format-translation helpers directly — no live ollama server

CI runs pytest on Python 3.11 and 3.12 via GitHub Actions.
