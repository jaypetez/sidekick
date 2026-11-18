# Sidekick — Feature Roadmap

Ideas for future bot capabilities, roughly ordered by usefulness and ease of implementation.

---

## ~~🛒 Task Lists (Groceries, To-Do, and More)~~ ✅ Done

**Status:** Shipped — local SQLite store with unlimited named lists. Create store-specific grocery lists (Costco, Trader Joe's), project lists, to-do lists, or any topic-based list through natural language. Eight MCP tools: `list_task_lists`, `list_tasks`, `add_tasks`, `complete_task`, `delete_task`, `clear_completed`, `delete_task_list`, `rename_task_list`. Lists are auto-created when you add tasks to a new name.

---

## ~~⏰ Scheduled Reminders~~ ✅ Done

**Status:** Shipped — users can add, update, list, and remove recurring reminders through chat. Four local tools: `list_reminders`, `add_reminder`, `update_reminder`, `remove_reminder`. Custom reminders persist to `$SIDEKICK_CONFIG_DIR/reminders.json` (default `~/.config/sidekick`) and restore on restart. Built-in morning summary and pre-event alerts can be modified or paused via chat or the dashboard. Pre-event alerts can come from polling (every 5 minutes) or from Chronary `event.reminder` webhook pushes (`PRE_EVENT_SOURCE=webhook`, managed with `sidekick-webhook`).

---

## ~~📅 Calendar~~ ✅ Done — on Chronary.ai

**Status:** Shipped — calendar lives on Chronary.ai via the official Python SDK. Four MCP tools: `list_events`, `create_event`, `update_event`, `delete_event`. First-run bootstrap is `sidekick-init`.

Open follow-ups:
- **Recurring events.** Sidekick doesn't create recurring series; asked for "every X", it creates individual events. Instances of existing recurring series are listed with their series ID.
- **`location` and `attendees`.** Not first-class fields in Chronary — stashed in event `metadata`. Round-trips correctly on list/get.

---

## ~~💬 Multi-platform chat~~ ✅ Done — Web + Telegram + Slack

**Status:** Shipped — the in-browser chat is always available (and is the only surface in web-only mode, with no Telegram token). Telegram runs when `TELEGRAM_BOT_TOKEN` is set. The Slack adapter runs alongside when both `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set. Slack implements the `ChatPlatform` ABC, which is ready for a WhatsApp adapter; Telegram is still wired directly in `bot.py`.

Open follow-ups:
- **Reminders on Slack and web.** Morning summary, pre-event and custom reminders still fire only on Telegram. Multi-platform reminder delivery is the natural next step — extend `REMINDER_CHAT_ID` to a comma-separated list of platform-prefixed targets.

---

## ~~🤖 Local LLM (Ollama)~~ ✅ Done

**Status:** Shipped — set `LLM_PROVIDER=ollama` and the bot routes through a local Ollama server. Recommended tool-capable models: `qwen2.5:14b` (best tool use we tested at ≤16GB VRAM), `qwen2.5:7b`, `llama3.1:8b`. Provider, model and Ollama tuning can be switched live on the Settings page. Tool-use reliability is materially below Claude's on multi-tool plans — acceptable for hobby/offline use.

---

## ~~🐳 Docker self-hosting~~ ✅ Done

**Status:** Shipped — `docker compose up` brings up the bot. Ollama service is gated behind the `ollama` profile so users on the Anthropic path don't pull a 5GB image they won't run. NVIDIA GPU passthrough is an opt-in override file, `docker-compose.gpu.yml`. Published images are built from tags and pushed to GHCR.

---

## ~~🖥️ Web dashboard, JSON API and CLI~~ ✅ Done

**Status:** Shipped — an in-process aiohttp dashboard with Chat, Dashboard, Reminders, Tasks, Calendar, Settings and System pages. Settings edits persist to `runtime.json` and apply live (LLM, Ollama tuning, reminder times, pre-event source); the System page shows every setting with its effective value and source. Everything is also exposed as JSON under `/api/*`, and `sidekick-cli` drives it from the terminal.

---

## ~~🔒 Access control and hardening~~ ✅ Done

**Status:** Shipped — closed-by-default user allowlists for Telegram and Slack (plus an optional Slack channel allowlist), per-user chat rate limiting, an optional dashboard token with a sign-in form (required for non-loopback binds), CSRF and Host-header checks, security headers, secret redaction in logs, and a scoped environment for the MCP subprocess. See [docs/security.md](docs/security.md).

---

## 🌤️ Weather

**Status:** Planned
**Difficulty:** Easy
**Backend:** Open-Meteo API (free, no API key needed)

### What it does

One new MCP tool: `get_weather(date)` — calls the Open-Meteo API with lat/lon from `.env` and returns temperature, conditions, precipitation, and wind for that date.

Claude decides when weather is relevant. No separate "weather for event" tool needed — Claude sees a baseball game on the calendar and calls `get_weather` alongside `list_events` on its own.

### Example messages
- "What's the weather?" → today's forecast
- "What's the weather like for Saturday's game?" → combines calendar + weather
- "Will it rain this week?"
- "What should the kids wear tomorrow?"
- "Do I need to bring a jacket tonight?"

### How it works with calendar
When you ask about events, Claude automatically combines the answers:
> "Baseball practice is Saturday at 4:30pm. Weather looks good — 72°F, sunny, no rain. Light wind from the west."

### What changes

| File | Change |
|------|--------|
| `mcp_server.py` | Add `get_weather` tool — HTTP call to Open-Meteo API |
| `agent.py` | Update system prompt to tell Claude about weather |
| `.env.example` | Add `FAMILY_LATITUDE` and `FAMILY_LONGITUDE` |
| No new dependencies | `httpx` (already a dependency) handles the API call |

### Setup required
- Add two lines to `.env`:
  ```
  FAMILY_LATITUDE=32.7767
  FAMILY_LONGITUDE=-96.7970
  ```
- No API key needed — Open-Meteo is completely free
- Forecasts available 7 days out

---

## 🎂 Birthday & Anniversary Reminders
**Difficulty:** Easy
**Backend:** Chronary calendar (already connected)

A dedicated "Birthdays" calendar in Chronary that the bot monitors. Sends a morning reminder on the day and a heads-up a few days before.

**Example messages:**
- "When is mom's birthday?"
- "Add dad's birthday on April 15"
- "What family birthdays are coming up this month?"

**Implementation notes:**
- Create a second Chronary calendar named "Birthdays" — set `BIRTHDAY_CALENDAR_ID` in `.env`
- Existing `list_events` and `create_event` tools already handle this
- Add a new APScheduler job: weekly scan for birthdays in the next 7 days, send a heads-up
- No new tools needed — just scheduler logic

---

## 🍽️ Meal Planning
**Difficulty:** Medium
**Backend:** Local SQLite (extend the existing DB)

Plan what's for dinner each day of the week. Family can check the plan, suggest changes, and the bot can automatically build a grocery list from the meal plan.

**Example messages:**
- "What's for dinner tonight?"
- "Put tacos on Tuesday and pasta on Thursday"
- "Build a grocery list from this week's meals"
- "What are we having this week?"

**Implementation notes:**
- New tables in the existing `sidekick.db` — one row per (week_start, day_of_week, meal_name)
- Tools: `get_meal_plan`, `set_meal`, `generate_grocery_list_from_meals`
- The grocery list generation is a great Claude use case — it reasons about ingredients and writes into the existing task store

---

## 📍 Location Check-In
**Difficulty:** Easy
**Backend:** None (chat-native)

A status board. No GPS or tracking — people post their status as plain text and the bot remembers it. Anyone can ask where everyone is without scrolling back through the chat.

**Example messages:**
- "I'm leaving school now"
- "Heading to practice, back at 6"
- "Where's Alex?" → "Alex said he was leaving school — 22 minutes ago"
- "Where is everyone?" → Bot replies with each person's last check-in

**Implementation notes:**
- New SQLite table: `checkins(user_id, status, timestamp)`
- Bot watches for messages that look like check-ins (uses Claude to classify) vs regular conversation
- Or a `/checkin` command for explicit status updates
- Works on every chat surface (web, Telegram, Slack), since it only needs the incoming message

---

## 🔑 Quick Notes / Wiki
**Difficulty:** Easy
**Backend:** Local SQLite

A place to store frequently referenced info: wifi password, alarm code, vet's phone number, contact list, etc.

**Example messages:**
- "What's the wifi password?"
- "What's Dr. Smith's phone number?"
- "Save the new garage code as 4821"

**Implementation notes:**
- New `notes(key, value)` table in `sidekick.db`
- Tools: `lookup_note`, `save_note`, `list_notes`

---

## 📲 WhatsApp adapter
**Difficulty:** Medium
**Backend:** Twilio API for WhatsApp OR Meta WhatsApp Cloud API

The `ChatPlatform` abstraction is ready for a third adapter. Twilio is easier to set up; Meta Cloud is cheaper at scale. Pick when there's actual demand.

---

## Implementation priority

| # | Feature | Status |
|---|---------|--------|
| 1 | Task lists | ✅ Done |
| 2 | Scheduled reminders | ✅ Done |
| 3 | Calendar on Chronary | ✅ Done |
| 4 | Slack adapter | ✅ Done |
| 5 | Local LLM (Ollama) | ✅ Done |
| 6 | Docker self-hosting | ✅ Done |
| 7 | Web dashboard, `/api`, `sidekick-cli` | ✅ Done |
| 8 | Chronary push reminders (webhooks) | ✅ Done |
| 9 | Access control and hardening | ✅ Done |
| 10 | Multi-platform reminders | Next up — small follow-on to the Slack adapter |
| 11 | Weather | Planned — easy, high daily utility |
| 12 | Birthday reminders | Planned — reuses existing calendar tools |
| 13 | Quick notes / wiki | Planned |
| 14 | Meal planning | Planned |
| 15 | Location check-in | Planned |
| 16 | WhatsApp adapter | When demand justifies it |
