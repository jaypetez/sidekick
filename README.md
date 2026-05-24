<p align="center">
  <img src="docs/assets/sidekick-logo.svg" alt="Sidekick" width="400">
</p>

<p align="center">
  <strong>A self-hosted personal assistant — Telegram + Slack — powered by Claude or a local LLM.</strong>
</p>

<p align="center">
  <a href="#quickstart"><img src="https://img.shields.io/badge/Quickstart-blue?style=for-the-badge" alt="Quickstart"></a>
  <a href="FEATURES.md"><img src="https://img.shields.io/badge/Features-orange?style=for-the-badge" alt="Features"></a>
  <a href=".github/CONTRIBUTING.md"><img src="https://img.shields.io/badge/Contributing-purple?style=for-the-badge" alt="Contributing"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="MIT License"></a>
</p>

---

Sidekick is a chat bot that manages your calendar, task lists, and scheduled reminders — all through natural language. Talk to it on Telegram or Slack; it uses [Chronary.ai](https://chronary.ai) for calendars and a local SQLite store for tasks, so there's no Google account in the loop. The LLM can be Anthropic Claude (cloud) or a local Ollama model (offline).

Talk to it like you'd talk to a person:

**Calendar** *(Chronary)*
- "What's on the calendar this week?"
- "Add soccer practice tomorrow at 4:30pm"
- "Move Tuesday's dentist appointment to Thursday at 2pm"

**Task lists / groceries** *(local SQLite)*
- "Add milk and eggs to the Costco list"
- "What's on my Trader Joe's list?"
- "Add chicken to the grocery list" *(auto-creates a list named "grocery")*
- "Got the eggs" / "Mark eggs as done"
- "Rename my grocery list to Whole Foods"

**Scheduled reminders**
- "Remind me every Sunday at 5pm to prep lunches"
- "What reminders are set up?"
- "Change the morning summary to 6:30am"

**Personality**
- `/personality snarky` — dry wit and playful sarcasm
- `/personality pirate` — arr, matey!
- `/personality default` — back to normal

The bot also sends a **morning summary** of the day's events and **pre-event reminders** so you never miss anything.

---

## Architecture at a glance

| Layer | Backend | Module |
|---|---|---|
| LLM | Anthropic Claude *or* local Ollama (env switch) | `llm/anthropic.py`, `llm/ollama.py` |
| Calendar | Chronary.ai (REST + Python SDK) | `calendar/chronary.py` |
| Tasks / groceries | Local SQLite at `~/.config/sidekick/sidekick.db` | `storage/sqlite_tasks.py` |
| Chat platforms | Telegram (always) + Slack (optional, runs concurrently) | `platforms/slack.py`, `bot.py` |
| Reminders | APScheduler with JSON persistence | `reminders.py` |
| Tool surface | MCP subprocess exposes 12 tools to Claude | `mcp_server.py` |

Each backend sits behind an abstract base class (`CalendarProvider`, `TaskStore`, `LLMClient`, `ChatPlatform`), so swapping a provider is a single-file change.

---

## Quickstart

### Option A — Docker (recommended)

```bash
git clone https://github.com/jaypetez/sidekick.git
cd sidekick
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, CHRONARY_API_KEY (see below)

# One-time Chronary bootstrap (creates an agent + default calendar):
docker compose run --rm sidekick sidekick-init
# Paste the printed CHRONARY_AGENT_ID and CHRONARY_CALENDAR_ID into .env

docker compose up -d
docker compose logs -f sidekick
```

To run with a local LLM instead of Anthropic:

```bash
# .env: LLM_PROVIDER=ollama, OLLAMA_BASE_URL=http://ollama:11434, OLLAMA_MODEL=llama3.1:8b
docker compose --profile ollama up -d
docker exec sidekick-ollama ollama pull llama3.1:8b
```

### Option B — bare metal (Python 3.11+)

```bash
git clone https://github.com/jaypetez/sidekick.git
cd sidekick
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env
# Fill in the secrets — see "What you need" below

sidekick-init   # creates the Chronary agent + default calendar
# Paste the printed IDs into .env

sidekick        # starts the bot
```

---

## What you need

| Variable | Required when | Where to get it |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | always | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `ANTHROPIC_API_KEY` | `LLM_PROVIDER=anthropic` (default) | [console.anthropic.com](https://console.anthropic.com) |
| `CHRONARY_API_KEY` | always | [console.chronary.ai](https://console.chronary.ai) — org key recommended for first-time `sidekick-init` |
| `CHRONARY_AGENT_ID`, `CHRONARY_CALENDAR_ID` | always | Printed by `sidekick-init` on first run |
| `REMINDER_CHAT_ID` | morning summary + pre-event reminders | Send `/get_id` to the bot in the target chat |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | enabling the Slack adapter | Slack app config (see below) |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | `LLM_PROVIDER=ollama` | Local Ollama install or compose service |
| `TIMEZONE` | optional | IANA name, default `America/Chicago` |

Full reference: [`.env.example`](.env.example).

---

## Adding Slack

Telegram works out of the box. Slack is opt-in:

1. Create a Slack app at https://api.slack.com/apps
2. Enable **Socket Mode** → generate an `xapp-…` app-level token
3. Add Bot Token Scopes: `chat:write`, `app_mentions:read`, `im:history`, `im:read`, `im:write`
4. Install to a workspace → grab the `xoxb-…` bot user token
5. Set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env`, restart

The Slack and Telegram adapters run concurrently. Conversation history is kept separate per chat via `tg:` / `sl:` chat-id prefixes.

> Heads up: morning summaries and pre-event reminders currently fire only on Telegram. Multi-platform reminder delivery is a known follow-up.

---

## Local LLM (Ollama)

Set `LLM_PROVIDER=ollama` to route the bot through a local Ollama server instead of the Anthropic API.

Recommended tool-capable models:

- `llama3.1:8b` — best general balance, ~5GB
- `qwen2.5:7b` — slightly better at multi-tool plans, ~5GB

Smaller models will misfire on multi-tool plans. **Tool-use reliability is materially below Claude's on any local model.** For real production use, keep Anthropic; Ollama is for offline / cost-free / privacy-sensitive operation where the occasional missed tool call is acceptable.

---

## Known limitations

- **Recurring events** — Chronary doesn't document recurring-event support; the bot will create individual instances when asked for "every X". Revisit when Chronary publishes RRULE.
- **`location` and `attendees` on events** — stashed in Chronary's `metadata` field (no first-class support there). Round-trips correctly on list/get.
- **Reminders are Telegram-only for now.**
- **WhatsApp is not supported.** The `ChatPlatform` abstraction is ready for a third adapter; just not built.

---

## Development

```bash
pip install -e ".[dev]"
pytest -v                          # all tests (currently 87)
pytest tests/test_storage_tasks.py -v
```

Tests don't hit any live APIs — everything is mocked. CI runs on Ubuntu under Python 3.11 and 3.12.

See [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md) for branching/commit/review conventions and the live `main` branch protection rules.

---

## License

[MIT](LICENSE).
