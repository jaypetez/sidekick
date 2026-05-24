<p align="center">
  <img src="docs/assets/sidekick-logo.svg" alt="Sidekick" width="420">
</p>

<p align="center">
  <strong>The AI assistant you text like a friend.</strong><br>
  Calendar, lists, and reminders — on Telegram or Slack, powered by Claude or a local LLM. Self-hosted.
</p>

<p align="center">
  <a href="#quickstart"><img src="https://img.shields.io/badge/Quickstart-5b21b6?style=for-the-badge&logo=docker&logoColor=white" alt="Quickstart"></a>
  <a href="FEATURES.md"><img src="https://img.shields.io/badge/Features-db2777?style=for-the-badge" alt="Features"></a>
  <a href=".github/CONTRIBUTING.md"><img src="https://img.shields.io/badge/Contributing-0891b2?style=for-the-badge" alt="Contributing"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-16a34a?style=for-the-badge" alt="MIT License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/tests-87%20passing-22c55e" alt="87 tests">
  <img src="https://img.shields.io/badge/calendar-Chronary.ai-8b5cf6" alt="Chronary">
  <img src="https://img.shields.io/badge/LLM-Claude%20%7C%20Ollama-f59e0b" alt="LLM">
  <img src="https://img.shields.io/badge/chat-Telegram%20%7C%20Slack-0ea5e9" alt="Chat">
</p>

---

## What it's like to use

Sidekick lives in your chat. Talk to it the way you'd ping a roommate — no slash commands required, no special grammar.

```text
you   add milk, eggs, and tortillas to costco
bot   Added to Costco: milk, eggs, tortillas.

you   move tuesday's dentist to thursday 2pm
bot   Done — Dentist is now Thursday at 2:00 PM. Want me to remind you the morning of?

you   what reminders do i have?
bot   Three:
      • morning_summary — every day 7:30 AM
      • pre_event_check — every 5 min (30-min lead)
      • reminder_174… — every Sunday 5:00 PM ("prep lunches")

you   /personality snarky
bot   Personality set to: snarky.

you   anything on my calendar tomorrow?
bot   Two things, both before noon. Look at you, going full morning-person.
      • 9:00 AM — Dentist
      • 11:30 AM — Lunch with Sarah
```

Behind the scenes Claude (or your local model) is calling tools to read Chronary, write to a local SQLite db, and schedule jobs. You just chat.

---

## What it can do

| Capability | How to ask | Backend |
|---|---|---|
| **Calendar** — list, add, move, delete events | *"add soccer practice tomorrow 4:30pm"* | [Chronary.ai](https://chronary.ai) |
| **Task lists & groceries** — unlimited named lists, partial-title matching | *"add chicken to the grocery list"* / *"got the eggs"* | Local SQLite at `~/.config/sidekick/sidekick.db` |
| **Scheduled reminders** — recurring, cron-style, persisted across restarts | *"remind me every Sunday 5pm to prep lunches"* | APScheduler + JSON |
| **Morning summary** — daily briefing of the day's events | configured in `.env`, time tunable via chat | Chronary + scheduler |
| **Pre-event alerts** — heads-up before events start | every 5 min, configurable lead time | Chronary + scheduler |
| **Personality presets** — snarky, pirate, formal, butler, or freeform | `/personality snarky` | persisted to local config |

---

## How it's built

```
                ┌────────────────────────────────┐
                │            Chat in             │
                │   Telegram  ┊        ┊  Slack  │
                └──────┬─────────────────┬───────┘
                       │                 │
                       ▼                 ▼
              ┌─────────────────────────────┐
              │      SidekickAgent          │
              │   (tool-use loop, history)  │
              └───┬────────────┬────────┬───┘
                  │            │        │
            ┌─────▼────┐ ┌─────▼────┐   │
            │ LLMClient│ │   MCP    │   │
            │ Anthropic│ │subprocess│   │
            │ /Ollama  │ │          │   │
            └──────────┘ └─┬──────┬─┘   │
                           │      │     │
                  ┌────────▼──┐ ┌─▼─────▼──────┐
                  │ Calendar  │ │ TaskStore +  │
                  │ Chronary  │ │ APScheduler  │
                  └───────────┘ └──────────────┘
```

Every backend sits behind an abstract base class (`CalendarProvider`, `TaskStore`, `LLMClient`, `ChatPlatform`), so swapping any of them is a single-file change. The provider table:

| Layer | Default | Alternative | Files |
|---|---|---|---|
| LLM | Anthropic Claude | local Ollama (`LLM_PROVIDER=ollama`) | `llm/anthropic.py`, `llm/ollama.py` |
| Calendar | Chronary.ai | — *(write your own)* | `calendar/chronary.py` |
| Tasks | Local SQLite | — *(write your own)* | `storage/sqlite_tasks.py` |
| Chat platforms | Telegram (always) + Slack (opt-in) | WhatsApp-ready ABC, not built | `bot.py`, `platforms/slack.py` |

---

## Quickstart

### Option A — Docker (recommended)

```bash
git clone https://github.com/jaypetez/sidekick.git
cd sidekick
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, CHRONARY_API_KEY

# One-time Chronary bootstrap — creates an agent + default calendar:
docker compose run --rm sidekick sidekick-init
# Paste the printed CHRONARY_AGENT_ID and CHRONARY_CALENDAR_ID into .env

docker compose up -d
docker compose logs -f sidekick
```

To run with a **local LLM** instead of Anthropic:

```bash
# In .env: LLM_PROVIDER=ollama, OLLAMA_BASE_URL=http://ollama:11434, OLLAMA_MODEL=llama3.1:8b
docker compose --profile ollama up -d
docker exec sidekick-ollama ollama pull llama3.1:8b
```

### Option B — bare metal (Python 3.11+)

```bash
git clone https://github.com/jaypetez/sidekick.git
cd sidekick
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                  # fill it in — see config below

sidekick-init      # creates the Chronary agent + default calendar
sidekick           # starts the bot
```

---

## Configuration

| Variable | Required when | Where to get it |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | always | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `LLM_PROVIDER` | optional, default `anthropic` | `anthropic` \| `ollama` |
| `ANTHROPIC_API_KEY` | `LLM_PROVIDER=anthropic` | [console.anthropic.com](https://console.anthropic.com) |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | `LLM_PROVIDER=ollama` | local install (or compose `ollama` service) |
| `CHRONARY_API_KEY` | always | [console.chronary.ai](https://console.chronary.ai) — org key for first-time `sidekick-init` |
| `CHRONARY_AGENT_ID`, `CHRONARY_CALENDAR_ID` | always | printed by `sidekick-init` on first run |
| `SIDEKICK_DB_PATH` | optional | default `~/.config/sidekick/sidekick.db` |
| `REMINDER_CHAT_ID` | enables morning summary + pre-event alerts | send `/get_id` to the bot in the target chat |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | enabling the Slack adapter | Slack app config (below) |
| `TIMEZONE` | optional | IANA name, default `America/Chicago` |

Full reference: [`.env.example`](.env.example).

---

## Adding Slack

Telegram works out of the box. Slack is opt-in and runs concurrently — same bot, two front doors.

1. Create a Slack app at https://api.slack.com/apps
2. Enable **Socket Mode** → generate an `xapp-…` app-level token
3. Add Bot Token Scopes: `chat:write`, `app_mentions:read`, `im:history`, `im:read`, `im:write`
4. Install to your workspace → grab the `xoxb-…` bot user token
5. Set `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` in `.env`, restart

Conversation history is kept separate per chat via `tg:` / `sl:` prefixes on the chat-id.

> Heads up: morning summaries and pre-event reminders currently fire only on Telegram. Multi-platform reminder delivery is a tracked follow-up.

---

## Local LLM (Ollama)

Set `LLM_PROVIDER=ollama` to route the bot through a local Ollama server instead of Anthropic.

**Recommended tool-capable models:**

- `llama3.1:8b` — best general balance, ~5GB
- `qwen2.5:7b` — slightly better at multi-tool plans, ~5GB

> ⚠️ Tool-use reliability on any local model is **materially lower** than Claude's. For day-to-day production, keep Anthropic. Ollama is for offline / cost-free / privacy-sensitive operation where the occasional missed tool call is acceptable.

---

## Known limitations

- **Recurring events** — Chronary doesn't document recurring-event support; the bot creates individual instances when asked for *"every X"*. Revisit when Chronary publishes RRULE.
- **`location` and `attendees` on events** — stashed in Chronary's `metadata` field (no first-class support). Round-trips correctly on list/get.
- **Reminders are Telegram-only** for now.
- **WhatsApp is not built.** The `ChatPlatform` abstraction is ready for a third adapter; just no implementation yet.

---

## Development

```bash
pip install -e ".[dev]"
pytest -v                                  # 87 tests
pytest tests/test_storage_tasks.py -v      # one file
```

No live API calls in tests — everything is mocked. CI runs on Ubuntu under Python 3.11 and 3.12.

Branching, commit, and PR conventions live in [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md). `main` is protected (CODEOWNERS review, linear history, no force-push) — work happens on `feat/`, `fix/`, `chore/` branches and lands via PR.

---

## License

[MIT](LICENSE).
