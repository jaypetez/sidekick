# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sidekick is a self-hosted chat bot that manages your calendar, task lists, and scheduled reminders through natural language. It runs on Telegram (always) and Slack (optional), uses Chronary.ai for the calendar backend, a local SQLite database for tasks/groceries, and either Anthropic Claude (default) or a local Ollama server for the LLM.

## Commands

```bash
# Install (editable, with dev deps)
pip install -e ".[dev]"

# First-time bootstrap (creates Chronary agent + calendar, prints the IDs to paste into .env)
sidekick-init

# Optional: Chronary push reminders (needs a public HTTPS URL)
sidekick-webhook register --url https://<host>/webhooks/chronary

# Run the bot
sidekick

# Lint + format check (CI gates merge on these)
ruff check .
ruff format --check .

# Strict type check (CI gates merge on this)
mypy src/sidekick

# Tests with the 80% coverage floor CI enforces
pytest                            # uses pyproject's --cov-fail-under=80
pytest --no-cov                   # skip coverage gate when iterating locally

# Single file / single test
pytest tests/test_storage_tasks.py -v
pytest tests/test_calendar_chronary.py::test_list_events_uses_timezone_for_boundaries -v

# Docker
docker compose up -d                      # Anthropic mode
docker compose --profile ollama up -d     # local-LLM mode

# Release (push a tag; everything else is automated)
git tag v0.2.0 && git push origin v0.2.0
```

## Releasing

The package version is **derived from the git tag** via `hatch-vcs` — `pyproject.toml`
declares `dynamic = ["version"]` and there is no hardcoded version. To cut a release,
tag a commit on `main` as `vX.Y.Z` and push the tag. `.github/workflows/release.yml`
then (1) creates the GitHub Release with auto-generated notes and (2) builds the
Dockerfile and pushes `ghcr.io/jaypetez/sidekick:{X.Y.Z, X.Y, latest}` to GHCR.

Because the Docker build context has no `.git`, the workflow passes the version into
the image via `--build-arg VERSION=` → `SETUPTOOLS_SCM_PRETEND_VERSION` (see Dockerfile).
At runtime `sidekick.__version__` reads the installed package metadata.

## Architecture

The bot runs three coordinated processes in a single asyncio event loop, plus an optional in-process web dashboard:

1. **Telegram bot** (`bot.py`) — python-telegram-bot v21 Application with async handlers. Entry point: `sidekick.bot:main`.
2. **Slack adapter** (`platforms/slack.py`, optional) — runs as a background task in `post_init` iff `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set. Uses `slack-bolt` async + socket mode.
3. **MCP subprocess** (`mcp_server.py`) — spawned via stdio transport. Exposes 12 tools (calendar + tasks). Inside, it delegates to the providers below.
4. **Web dashboard** (`web/`, default on) — aiohttp app spawned as a background task in `post_init` when `SIDEKICK_WEB_ENABLED` isn't false. Binds `127.0.0.1:8080` by default. Shares the live scheduler, agent, and MCP session by reference via `bot_data`; spins up its own `SQLiteTaskStore` and `ChronaryProvider` to avoid wedging into the MCP subprocess's state.

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
3. Create `SidekickAgent` with mcp_session, scheduler, bot, reminder_chat_id; calls `build_llm_client()` for the LLM
4. Load tool definitions (MCP tools + local reminder tool defs)
5. If `SLACK_BOT_TOKEN` set, start `_run_slack()` as a background task
6. If `SIDEKICK_WEB_ENABLED` isn't false, start `_run_web()` as a background task — builds the aiohttp app via `web.make_app(bot_data=..., task_store=..., calendar_provider=...)` and serves on `SIDEKICK_WEB_HOST:SIDEKICK_WEB_PORT`

### Reminders (`reminders.py`)

- **Built-in**: morning summary (CronTrigger) and pre-event check (IntervalTrigger). Can be paused/resumed but not removed.
- **Custom**: User-created via chat. Persisted to `~/.config/sidekick/reminders.json`. Restored on restart via `load_custom_reminders()`.
- `send_custom_reminder()` reads `REMINDER_CHAT_ID` from env at send time (not from the stored value).
- Reminders currently fire only on Telegram. Multi-platform support is a known follow-up.
- **Pre-event source** (`PRE_EVENT_SOURCE`, via `runtime_config.pre_event_source()`): `poll` (default — `pre_event_check` runs every 5 min) or `webhook` (the job is registered paused; Chronary pushes `event.reminder`). Switching applies live through `apply_builtin_settings()`.

### Chronary webhooks (`webhooks.py`, `web/handlers/webhooks.py`, `webhook_cli.py`)

- `POST /webhooks/chronary` receives `event.reminder` pushes. It is in `web/auth.py::WEBHOOK_PATHS` (exact match), so it skips session/bearer auth, CSRF and the Host check — the HMAC signature (`chronary.webhook.verify_signature`, 300 s tolerance) is the only authentication. Returns 404 unless a secret is configured: `webhooks.load_webhook_secret()` reads `CHRONARY_WEBHOOK_SECRET`, else `$SIDEKICK_CONFIG_DIR/chronary_webhook.secret` (written 0600 by `register` — the CLI never prints the secret).
- Flow: verify → ignore other event types / other calendars (subscriptions are org-wide) → `DeliveryLog` (SQLite `webhook_deliveries`, keyed by `X-Delivery-Id`) drops retries → ack 200 → deliver to Telegram in a tracked background task.
- `sidekick-webhook register|status|test|delete` manages the subscription with the Chronary SDK directly and sets the calendar's `default_reminders`. Chronary rejects non-public URLs, so live testing needs a tunnel.
- Tests sign deliveries with `tests/webhook_helpers.py::signed()` (parity with the SDK signer is asserted).

### Web dashboard (`web/`)

- `web/app.py::make_app()` is the factory. Tests pass a mocked `bot_data` dict and (optionally) a mocked `task_store` / `calendar_provider`; production wiring lives in `bot.py::_run_web()`.
- Handlers live in `web/handlers/`. Calendar's handler module is `calendar_routes.py` (the stdlib `calendar` module would shadow it).
- Sync provider calls (`SQLiteTaskStore`, `ChronaryProvider`) are wrapped in `web.helpers.run_sync()` so they don't block the shared event loop — same `loop.run_in_executor` pattern `MCPServer._dispatch` uses.
- Templates are Jinja2 (`web/templates/`); htmx is loaded from CDN in `base.html`. No build step.
- Dashboard is **localhost-only by default**. In Docker the container's `127.0.0.1` is not the host's — either set `SIDEKICK_WEB_ENABLED=false`, exec into the container, or override `SIDEKICK_WEB_HOST=0.0.0.0` with the security trade-off that implies.

### Runtime settings, services, `/api`, and the CLI

- `runtime_config.py` layers editable overrides (`EDITABLE_KEYS`) from `runtime.json` (in `SIDEKICK_CONFIG_DIR`) over `os.environ`. Read settings through `runtime_config.get()` / `timezone_name()` — **not** `os.getenv` — or settings-page edits silently won't apply. `validate()` gates every write; `SECRET_KEYS` are redacted in `as_dict(redacted=True)`.
- `services/` holds the framework-free business logic shared by the HTML handlers, `/api`, and the CLI. `services/settings.update()` validates a whole batch before writing, rebuilds the LLM client for LLM keys, re-applies built-in reminder jobs via `reminders.apply_builtin_settings()`, and reports `restart_required` (currently `TIMEZONE`).
- `web/api/` is a sub-app mounted at `/api/` with a `{data, error}` envelope; the parent app's session/CSRF/auth middlewares still apply. A request with a valid `Authorization: Bearer` token skips CSRF (not an ambient credential); browser JS (`static/js/api.js`) sends `X-CSRF-Token` from the page's `csrf-token` meta tag.
- `cli/` is `sidekick-cli` — a sync httpx client over `/api`. Uses `SIDEKICK_API_TOKEN` as a bearer when set, otherwise fetches `/_csrf` first.

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
| `MORNING_REMINDER_TIME` | `07:30` | No (HH:MM 24-hour) |
| `PRE_EVENT_REMINDER_MINUTES` | `30` | No (lead time for pre-event alerts) |
| `SIDEKICK_CONFIG_DIR` | `~/.config/sidekick` | No (relocates reminders.json, DB, and personality state) |
| `SIDEKICK_WEB_ENABLED` | `true` | No (set to `false` to skip the dashboard) |
| `SIDEKICK_WEB_HOST` | `127.0.0.1` | No (bind interface for the dashboard) |
| `SIDEKICK_WEB_PORT` | `8080` | No (bind port for the dashboard) |
| `SIDEKICK_WEB_AUTH_TOKEN` | — | Required for non-loopback binds; ≥16 chars, placeholder refused |
| `SIDEKICK_WEB_ALLOWED_HOSTS` | — | No (extra `Host` names accepted when auth is off; DNS-rebinding guard) |
| `SIDEKICK_WEB_TRUST_PROXY` | `false` | No (honor `X-Forwarded-For` — only behind a proxy that sets it) |
| `TIMEZONE` | `America/Chicago` | No |
| `CLAUDE_MODEL` | `claude-haiku-4-5-20251001` | No |
| `SIDEKICK_RUNTIME_CONFIG` | `$SIDEKICK_CONFIG_DIR/runtime.json` | No (settings-page overrides; wins over env) |
| `SIDEKICK_API_URL` | `http://127.0.0.1:$SIDEKICK_WEB_PORT` | No (`sidekick-cli` target) |
| `SIDEKICK_API_TOKEN` | falls back to `SIDEKICK_WEB_AUTH_TOKEN` | No (`sidekick-cli` bearer token) |
| `PRE_EVENT_SOURCE` | `poll` | No (`poll` \| `webhook`; editable in settings) |
| `CHRONARY_WEBHOOK_ID` | — | Only for push reminders (printed by `sidekick-webhook register`) |
| `CHRONARY_WEBHOOK_SECRET` | — | No (overrides the secret file `register` writes) |

## Testing

Tests use `unittest.mock` — no live API calls. Notable conventions:

- `mock_scheduler` / `mock_bot` fixtures in `tests/conftest.py`
- `tmp_reminders_file` patches `REMINDERS_FILE` (always use this when testing reminder persistence)
- MCP server tests construct a server with `@patch("sidekick.mcp_server.Server")` to avoid starting the real MCP transport
- SQLite tests inject a `:memory:` connection via the `SQLiteTaskStore(conn=...)` constructor
- Ollama tests use a fake client and verify the format-translation helpers directly — no live ollama server

`src/sidekick` is fully annotated and `mypy --strict` clean — new code must conform. Coverage floor is 80% (enforced via `--cov-fail-under` in pyproject); the suite currently collects ~500 tests.

`pytest-asyncio` runs in strict mode (`asyncio_mode = "strict"` in pyproject.toml) — every async test must carry an explicit `@pytest.mark.asyncio` decorator.

## CI gates (`.github/workflows/ci.yml`)

Five required status checks gate every PR to `main`:

| Job | What it runs |
|---|---|
| `lint` | `ruff check .` + `ruff format --check .` |
| `typecheck` | `mypy src/sidekick` (strict mode) |
| `test (py3.11)` | `pytest` with `--cov-fail-under=80` on Python 3.11 |
| `test (py3.12)` | same, on Python 3.12 |
| `dependency-review` | GitHub's `dependency-review-action`, PRs only |

Run the full set locally before pushing — they all match the commands above.

`.pre-commit-config.yaml` runs ruff lint + format on every commit. Activate with `pre-commit install` after `pip install -e ".[dev]"`.

## Contribution conventions

Full rules in `.github/CONTRIBUTING.md`; the load-bearing ones for code changes:

- **Never push directly to `main`** — it's protected and requires PR + passing CI. Branch from `main` with kebab-case names prefixed `feat/`, `fix/`, `docs/`, or `chore/`.
- **Linear history is enforced.** Rebase your branch on `main` rather than merging `main` in. Merge commits are disabled; squash-and-merge is the default.
- Commit subjects: imperative mood, under ~72 chars ("Add X", not "Added X").

## Examples

`examples/01-local-ollama-docker/` is the user-facing "try it in 5 minutes" path — Docker compose with Ollama + the web chat UI, no Telegram or Anthropic key required. Treat its README as the canonical onboarding flow; keep it in sync with any change that affects local-LLM or web-dashboard setup.
