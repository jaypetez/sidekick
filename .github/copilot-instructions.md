# Copilot instructions for Sidekick

Sidekick is a self-hosted Python 3.11+ chat bot (Telegram + optional Slack + always-on web UI) that manages a Chronary.ai calendar, a local SQLite task store, and APScheduler reminders via a Claude or Ollama tool-use loop.

## Commands

```bash
pip install -e ".[dev]"                    # install with dev deps
sidekick-init                              # one-time Chronary bootstrap (prints IDs for .env)
sidekick                                   # run the bot

# CI gates (run all of these locally before pushing — they all gate merge):
ruff check . && ruff format --check .      # lint + format
mypy src/sidekick                          # strict type check
pytest                                     # full suite, enforces 80% coverage floor

# Iterating:
pytest --no-cov                            # skip the coverage gate
pytest tests/test_storage_tasks.py -v      # single file
pytest tests/test_calendar_chronary.py::test_list_events_uses_timezone_for_boundaries -v   # single test
```

Required CI status checks: `lint`, `typecheck`, `test (py3.11)`, `test (py3.12)`, `dependency-review`. `.pre-commit-config.yaml` mirrors the lint step; run `pre-commit install` after the dev install.

## Architecture

One asyncio event loop hosts three coordinated processes plus an in-process web app:

1. **Telegram bot** (`bot.py`) — `python-telegram-bot` v21 `Application`. Entry point `sidekick.bot:main`. Optional — runs in "web-only" mode when `TELEGRAM_BOT_TOKEN` is unset.
2. **Slack adapter** (`platforms/slack.py`) — background task started in `post_init` only if both `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set. `slack-bolt` async + socket mode.
3. **MCP subprocess** (`mcp_server.py`) — spawned via stdio transport, exposes 12 tools (calendar + tasks) that delegate to the concrete providers.
4. **Web dashboard** (`web/`) — aiohttp app on `127.0.0.1:8080` by default, started in `post_init` unless `SIDEKICK_WEB_ENABLED=false`. Shares the live scheduler / agent / MCP session by reference via `bot_data`; spins up **its own** `SQLiteTaskStore` and `ChronaryProvider` (do not reach into the MCP subprocess's state).

### Provider ABCs (single-file swaps)

| ABC | Concrete | Notes |
|---|---|---|
| `calendar/base.py::CalendarProvider` | `calendar/chronary.py::ChronaryProvider` | lazy-imports `chronary` SDK |
| `storage/base.py::TaskStore` | `storage/sqlite_tasks.py::SQLiteTaskStore` | stdlib `sqlite3`, WAL + FK cascade |
| `llm/base.py::LLMClient` | `llm/anthropic.py::AnthropicClient` (default), `llm/ollama.py::OllamaClient` | selected by `LLM_PROVIDER` via `llm/__init__.py::build_llm_client()` |
| `platforms/base.py::ChatPlatform` | `platforms/slack.py::SlackPlatform` (Telegram is still inline in `bot.py`) | `IncomingMessage` dataclass wraps inbound messages |

### Tool routing (dual dispatch)

`agent.py` routes Claude tool calls two ways:

- **MCP tools** (12 calendar + task tools) → forwarded via `ClientSession.call_tool()` to the MCP subprocess, which dispatches to the concrete provider.
- **Local reminder tools** (`list_reminders`, `add_reminder`, `update_reminder`, `remove_reminder`) → handled in-process by `reminders.py` functions because they need the APScheduler instance running in the parent process.

The set `LOCAL_REMINDER_TOOLS` in `agent.py` is the routing decision; add new local tools there *and* in `REMINDER_TOOL_DEFS`.

### Startup sequence (`bot.py::post_init`)

1. Spawn MCP subprocess → wait for `session_ready`
2. Create `AsyncIOScheduler` → register built-in jobs → `load_custom_reminders()` from JSON → start
3. Create `SidekickAgent` (calls `build_llm_client()`); pass `mcp_session`, `scheduler`, `bot`, `reminder_chat_id`
4. `agent.load_tools()` (MCP tools + local reminder defs)
5. Optionally start `_run_slack()` and `_run_web()` as background tasks

### Reminders (`reminders.py`)

- **Built-in** (`morning_summary`, `pre_event_check`): can be paused/resumed via `update_reminder`, **never removed**. `BUILTIN_IDS` enforces this.
- **Custom**: persisted to `~/.config/sidekick/reminders.json`; restored on restart via `load_custom_reminders()`.
- `send_custom_reminder()` reads `REMINDER_CHAT_ID` **at send time** (not from the stored value).
- Reminders deliver **only on Telegram** today — multi-platform delivery is a known follow-up.

### Conversation history

Per-chat dict in `agent.py` (`conversation_history`). Keys: `int` for Telegram, `"sl:<channel>"` for Slack — keep this prefix scheme when adding platforms so chat IDs don't collide. Bounded to `MAX_HISTORY_TURNS = 20` pairs. On `anthropic.BadRequestError` the chat's history is cleared and the user is told to repeat the message.

### Web dashboard

- Factory: `web/app.py::make_app()`. Tests pass a mocked `bot_data` dict and optionally mocked `task_store` / `calendar_provider`.
- Handlers live in `web/handlers/`. The calendar handler is `calendar_routes.py` — the stdlib `calendar` module would shadow `calendar.py`, so **do not rename it**.
- Sync provider calls are wrapped in `web.helpers.run_sync()` (`loop.run_in_executor`) — same pattern as `MCPServer._dispatch`. Never call sync provider methods directly from a handler.
- Templates: Jinja2 in `web/templates/`; htmx loaded from CDN in `base.html`. No build step.
- Localhost-only by default with no auth. In Docker, `127.0.0.1` is the container loopback — see README for the `SIDEKICK_WEB_HOST=0.0.0.0` trade-off.

## Conventions

- **`src/sidekick` is `mypy --strict` clean** — every new function needs full annotations, including `-> None` on async handlers. Module-level overrides for `chronary.*` and `apscheduler.*` are the only `ignore_missing_imports` allowances.
- **`pytest-asyncio` runs in strict mode** (`asyncio_mode = "strict"`) — every async test needs an explicit `@pytest.mark.asyncio` decorator.
- **No live API calls in tests.** Use `unittest.mock`. Standard fixtures live in `tests/conftest.py`:
  - `mock_scheduler`, `mock_bot`
  - `tmp_reminders_file` patches `sidekick.reminders.REMINDERS_FILE` — always use it when testing reminder persistence.
  - MCP server tests patch `@patch("sidekick.mcp_server.Server")` so the real transport never starts.
  - SQLite tests inject a `:memory:` connection via `SQLiteTaskStore(conn=...)`.
  - Ollama tests use a fake client and verify the format-translation helpers directly.
- **Coverage floor is 80%**, enforced by `--cov-fail-under=80` in `pyproject.toml`. Don't lower it.
- **Ruff config**: `target-version = "py311"`, `line-length = 100`, selects `E, F, I, B, UP, W`, ignores `E501`. Prefer `pathlib.Path` and modern `X | Y` unions (`UP` rules will flag otherwise).
- **Branching**: `feat/...`, `fix/...`, `docs/...`, `chore/...` off `main`. `main` is protected (linear history required, no force-push, CODEOWNERS review). Rebase, don't merge `main` into your branch. Squash-merge is the default.
- **Commit subject** in imperative mood, ≤~72 chars ("Add X", not "Added X").
- **New direct dependencies** require justification in the PR description — Dependabot owns updates.

## Config touchpoints

Env vars are loaded by `python-dotenv` at the top of `bot.py`. Anything read at startup (Chronary IDs, LLM provider, timezone) lives in `.env.example`; anything read at runtime (`REMINDER_CHAT_ID`, scheduler times) is read from `os.getenv` on each access so config can change without a restart. Provider IDs (`CHRONARY_AGENT_ID`, `CHRONARY_CALENDAR_ID`) are produced by `sidekick-init` and pasted into `.env` once.

The full source-of-truth env reference is in `README.md` ("Configuration" table) and `.env.example`.
