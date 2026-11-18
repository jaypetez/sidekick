# AGENTS.md

Guidance for AI coding agents (Claude Code, Copilot, Codex, …) working in this repository. `CLAUDE.md` and `.github/copilot-instructions.md` point here — edit this file, not those.

Human-facing docs: [`README.md`](README.md) (setup and operation), [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) (branch protection, review policy), [`docs/security.md`](docs/security.md) (web auth/CSRF/Host-check model and threat model).

## Project overview

Sidekick is a self-hosted chat bot that manages a calendar, task lists, and scheduled reminders through natural language. Chat surfaces: an in-process web UI (always available), Telegram (optional — with no `TELEGRAM_BOT_TOKEN` it runs in web-only mode), and Slack (optional). The calendar backend is Chronary.ai, tasks/groceries live in local SQLite, and the LLM is Anthropic Claude (default) or a local Ollama server.

## Commands

```bash
pip install -e ".[dev]"            # editable install with dev deps
pre-commit install                 # ruff + bandit on commit, pip-audit on push

sidekick-init                      # one-time: create Chronary agent + calendar, print IDs for .env
sidekick                           # run the bot (sidekick.bot:main)
sidekick-webhook register --url https://<host>/webhooks/chronary   # optional push reminders
sidekick-cli system status         # terminal client over the /api JSON layer

# Required CI gates — run all of them before pushing
ruff check . && ruff format --check .
mypy src/sidekick                  # strict
pytest                             # enforces the 80% coverage floor (--cov-fail-under in pyproject)

# Non-required but PR-failing security checks
bandit -r src/sidekick -ll -ii -c pyproject.toml

# Leaked-secret scan: gitleaks over all history + the real .env values (prints names only).
# Run it where the real .env lives; procedure in .claude/skills/secret-scan/SKILL.md
python scripts/scan_secrets.py

# Iterating
pytest --no-cov
pytest tests/test_storage_tasks.py
pytest tests/test_calendar_chronary.py::test_list_events_uses_timezone_for_boundaries
```

Docker: `docker compose up -d` (Anthropic), `docker compose --profile ollama up -d` (local LLM). The image's `ENTRYPOINT` is `sidekick`, so run other console scripts with `--entrypoint` (e.g. `docker compose run --rm --entrypoint sidekick-init sidekick`) or `docker compose exec sidekick <cmd>` against the running container.

## Architecture

One asyncio event loop in the main process runs the chat surfaces, the scheduler, and the web app; calendar and task tools run in a separate MCP subprocess.

- **Telegram** (`bot.py`) — python-telegram-bot v22 `Application`, inline in `bot.py` (not yet behind the `ChatPlatform` ABC). Entry point `sidekick.bot:main`; without a token, `main()` runs `_run_web_only()` instead.
- **Slack** (`platforms/slack.py`) — slack-bolt async + socket mode, started only when **both** `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set (`util.slack_configured()`).
- **MCP subprocess** (`mcp_server.py`) — spawned over stdio as `python -m sidekick.mcp_server` (never by script path: `src/sidekick/calendar/` would shadow the stdlib `calendar`). Exposes 12 tools (4 calendar, 8 task) and dispatches to the concrete providers. Its env is scoped by `bot.py::_build_mcp_env()`.
- **Web app** (`web/`) — aiohttp, default `127.0.0.1:8080`. Shares the live scheduler, agent and MCP session by reference via `bot_data`, but builds **its own** `SQLiteTaskStore` and `ChronaryProvider` (don't reach into the subprocess's state).

### Startup (`bot.py::_bootstrap_services`)

Shared by `post_init` (Telegram) and `_run_web_only()` (`bot=None`):

1. Spawn the MCP subprocess and wait up to 15 s for `session_ready`.
2. `reminders.setup_scheduler()` — registers built-in jobs and starts the scheduler.
3. Create `SidekickAgent` (calls `llm.build_llm_client()`), then `agent.load_tools()`.
4. `load_custom_reminders(scheduler, agent)` — after the agent exists.
5. Start Slack if configured; start the web app unless `SIDEKICK_WEB_ENABLED` is false — but web-only mode forces it on.

### Provider abstractions

| ABC | Concrete | Notes |
|---|---|---|
| `calendar/base.py::CalendarProvider` | `calendar/chronary.py::ChronaryProvider` | Lazy-imports the `chronary` SDK |
| `storage/base.py::TaskStore` | `storage/sqlite_tasks.py::SQLiteTaskStore` | stdlib sqlite3, WAL + FK cascade |
| `llm/base.py::LLMClient` | `llm/anthropic.py::AnthropicClient` (default), `llm/ollama.py::OllamaClient` | Chosen by `LLM_PROVIDER` in `llm/__init__.py::build_llm_client()` |
| `platforms/base.py::ChatPlatform` | `platforms/slack.py::SlackPlatform` | Telegram is still inline in `bot.py` |

### Tool routing (dual dispatch)

`agent.py` runs the tool-use loop and routes each call:

- **MCP tools** (calendar + tasks) → `ClientSession.call_tool()` on the subprocess.
- **Local reminder tools** (`list_reminders`, `add_reminder`, `update_reminder`, `remove_reminder`) → handled in-process via `reminders.py`, because they need the parent's APScheduler. A new local tool must be added to **both** `LOCAL_REMINDER_TOOLS` (routing) and `REMINDER_TOOL_DEFS` (schema).

`DESTRUCTIVE_TOOLS` in `agent.py` names the tools that get logged at INFO for auditing — keep it in sync with real tool names.

### Reminders (`reminders.py`)

- **Built-in** (`morning_summary`, `pre_event_check`; `BUILTIN_IDS`): can be paused/resumed, never removed.
- **Custom**: created via chat or the dashboard, persisted to `paths.reminders_file()` (`$SIDEKICK_CONFIG_DIR/reminders.json`), restored on startup.
- `send_custom_reminder()` reads `REMINDER_CHAT_ID` at send time. Reminders deliver only to Telegram today; in web-only mode they're stored but don't fire.
- **Pre-event source** (`runtime_config.pre_event_source()`): `poll` (default — `pre_event_check` every 5 min) or `webhook` (the job is registered paused; Chronary pushes `event.reminder`). Switching applies live via `apply_builtin_settings()`.

### Chronary webhooks (`webhooks.py`, `web/handlers/webhooks.py`, `webhook_cli.py`)

- `POST /webhooks/chronary` is in `web/auth.py::WEBHOOK_PATHS` (exact match), so it skips session/bearer auth, CSRF and the Host check — the HMAC signature (`chronary.webhook.verify_signature`, 300 s tolerance) is its only authentication. It returns 404 unless a secret is configured: `webhooks.load_webhook_secret()` reads `CHRONARY_WEBHOOK_SECRET`, else `$SIDEKICK_CONFIG_DIR/chronary_webhook.secret` (written 0600 by `register`; the CLI never prints it).
- Flow: verify → ignore other event types and other calendars (subscriptions are org-wide) → `DeliveryLog` (SQLite `webhook_deliveries`, keyed by `X-Delivery-Id`) drops retries → ack → deliver to Telegram in a tracked background task.
- `sidekick-webhook register|status|test|delete` uses the Chronary SDK directly and sets the calendar's `default_reminders`. Chronary rejects non-public URLs, so live testing needs a tunnel.
- Tests sign deliveries with `tests/webhook_helpers.py::signed()`.

### Web app (`web/`)

- `web/app.py::make_app()` is the factory; production wiring is `bot.py::_run_web()`. Tests pass a mocked `bot_data` and optionally mocked `task_store` / `calendar_provider`.
- Middleware (`web/middleware.py`): security headers, Host check (DNS-rebinding guard; only when auth is off), CSRF on state-changing requests (skipped for a valid bearer token), and auth when `SIDEKICK_WEB_AUTH_TOKEN` is set (session cookie from `/login` or `Authorization: Bearer`). `web/auth.py` holds the path lists and token rules — a non-loopback bind is refused without a token. Full model: `docs/security.md`.
- Handlers live in `web/handlers/`. The calendar module is `calendar_routes.py` — don't rename it; `calendar.py` would shadow the stdlib.
- Wrap sync provider calls with `sidekick.util.run_sync()` (`web/helpers.py` re-exports it) so they don't block the shared loop. Never call sync providers directly from a handler.
- Jinja2 templates in `web/templates/`; htmx from a CDN with SRI in `base.html`. No build step.
- `web/api/` is a sub-app mounted at `/api/` with a `{data, error}` envelope; the parent's middlewares still apply. Browser JS (`static/js/api.js`) sends `X-CSRF-Token` from the page's meta tag.
- `/system` (server-rendered), `/api/system` and `/api/config` all come from `services/system.py`, as do both health endpoints and `sidekick-cli system`.

### Settings, state files, services, CLI

- **State files** come from `paths.py` (`config_dir()`, `db_path()`, `reminders_file()`, `personality_file()`): the per-file env var wins, else `$SIDEKICK_CONFIG_DIR/<name>`. If the new location is missing but `~/.config/sidekick/<name>` exists, the legacy file is used with a warning. **Never hard-code `~/.config/sidekick`.**
- **Settings** go through `runtime_config.get()` / `timezone_name()`, **not** `os.getenv` — `runtime_config` layers editable overrides (`EDITABLE_KEYS`) from `runtime.json` over the environment, so `os.getenv` silently ignores settings-page edits. `validate()` gates writes; `SECRET_KEYS` are redacted; `RESTART_REQUIRED_KEYS` is currently `{"TIMEZONE"}`.
- **Every env var must be catalogued.** `config_catalog.py::CATALOG` is the single source of truth (group, label, default, secret). `tests/test_config_catalog.py` scans `src/` and fails on any uncatalogued `os.getenv("X")` / `runtime_config.get("X")`. Also add operator-facing vars to `.env.example`. Secrets are never returned by the System page or `/api/config`, not even a preview.
- `services/` holds framework-free business logic shared by HTML handlers, `/api`, and the CLI. `services/settings.update()` validates a whole batch, rebuilds the LLM client for LLM keys, re-applies built-in reminder jobs, and reports `restart_required`.
- `cli/` is `sidekick-cli`, a sync httpx client over `/api`. It sends `SIDEKICK_API_TOKEN` (falling back to `SIDEKICK_WEB_AUTH_TOKEN`) as a bearer, otherwise fetches `/_csrf` first.

### Other modules

- `allowlist.py` — Telegram/Slack user allowlists. **Closed by default**: an empty `TELEGRAM_ALLOWED_USER_IDS` / `SLACK_ALLOWED_USER_IDS` rejects everyone.
- `ratelimit.py` — token-bucket limiter (`SIDEKICK_RATE_LIMIT_*`), keyed per user on Telegram and Slack and per client address on web `POST /chat`.
- `logging_setup.py` — log filter that redacts tokens, keys and secrets.
- `telegram_format.py` — MarkdownV2 escaping with a plaintext fallback.
- `util.py` — `run_sync`, `watch_task` (logs crashes of background tasks), `slack_configured`, `is_loopback_host`.
- `init_cli.py` — `sidekick-init`; `webhook_cli.py` — `sidekick-webhook`.

### Conversation history

Per-chat history in `agent.py` (`conversation_history`), bounded to `MAX_HISTORY_TURNS = 20` pairs. Keys are the raw `int` chat id for Telegram, and prefixed strings elsewhere: `"sl:<channel>"` (Slack), `"web:local"` (web chat), `"cli:default"` (CLI). Use a new prefix for any new platform so ids can't collide. On `anthropic.BadRequestError` that chat's history is cleared.

## Testing

- No live API calls — everything uses `unittest.mock`.
- `pytest-asyncio` runs in strict mode: every async test needs `@pytest.mark.asyncio`.
- `src/sidekick` is `mypy --strict` clean; new code must be fully annotated. The only `ignore_missing_imports` overrides are `chronary.*` and `apscheduler.*`.
- Fixtures:
  - `tests/conftest.py`: autouse `isolated_runtime_config` (points `runtime_config` at a per-test `runtime.json`), `mock_scheduler`, `mock_bot`, and `tmp_reminders_file` (always use it when testing reminder persistence).
  - `tests/web/conftest.py`: `bot_data`, `app`, `client` (auto-injects CSRF on write verbs), `raw_client` (no CSRF — for CSRF tests).
  - `tests/cli/conftest.py`: `make_client` (an `ApiClient` over an httpx mock transport that answers `/_csrf` for you) plus `envelope_ok` / `envelope_err` helpers.
- MCP server tests patch `sidekick.mcp_server.Server` so no real transport starts. SQLite tests inject a `:memory:` connection via `SQLiteTaskStore(conn=...)`. Ollama tests use a fake client.
- `tests/test_security_docs.py` asserts required headings in `docs/security.md` and `.github/SECURITY.md`, and that the README links to both — keep them when editing those docs.

## CI

`.github/workflows/ci.yml` — required status checks for merging to `main`: `lint`, `typecheck`, `test (py3.11)`, `test (py3.12)`, `dependency-review` (PRs only).

Also run on every PR (not required, but a failure still needs fixing): `security.yml` (`pip-audit`, `bandit`) and `codeql.yml` (`Analyze (python)`, also weekly).

## Conventions

- Never push to `main`; it's protected. Branch as `feat/…`, `fix/…`, `docs/…` or `chore/…`, rebase on `main` (linear history; no merge commits), and land via squash-merge.
- PR titles become the squash commit subject — use Conventional Commits: `type(scope): imperative lowercase summary`, e.g. `fix(paths): honor SIDEKICK_CONFIG_DIR for every state file`.
- Ruff: `line-length = 100`, rules `E, F, I, B, UP, W` (`E501` ignored), target py311 — use `X | Y` unions and `pathlib`.
- New direct dependencies need a justification in the PR; Dependabot owns version bumps.
- `examples/01-local-ollama-docker/` is the user-facing "try it in 5 minutes" path — keep its README in sync with any change to local-LLM or web-dashboard setup.

## Releasing

The version comes from the git tag via `hatch-vcs` (`dynamic = ["version"]`; nothing is hard-coded). Tag a commit on `main` as `vX.Y.Z` and push the tag. `.github/workflows/release.yml` creates the GitHub Release with generated notes and pushes `ghcr.io/jaypetez/sidekick:{X.Y.Z, X.Y, latest}`. The Docker build context has no `.git`, so the workflow passes `--build-arg VERSION=` → `SETUPTOOLS_SCM_PRETEND_VERSION`. At runtime `sidekick.__version__` reads the installed package metadata.
