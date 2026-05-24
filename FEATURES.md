# Sidekick — Feature Roadmap

Ideas for future bot capabilities, roughly ordered by usefulness and ease of implementation.

---

## ~~🛒 Task Lists (Groceries, To-Do, and More)~~ ✅ Done

**Status:** Shipped — local SQLite store with unlimited named lists. Create store-specific grocery lists (Costco, Trader Joe's), project lists, to-do lists, or any topic-based list through natural language. Eight MCP tools: `list_task_lists`, `list_tasks`, `add_tasks`, `complete_task`, `delete_task`, `clear_completed`, `delete_task_list`, `rename_task_list`. Lists are auto-created when you add tasks to a new name.

---

## ~~⏰ Scheduled Reminders~~ ✅ Done

**Status:** Shipped — users can add, update, list, and remove recurring reminders through chat. Four local tools: `list_reminders`, `add_reminder`, `update_reminder`, `remove_reminder`. Custom reminders persist to `~/.config/sidekick/reminders.json` and restore on restart. Built-in morning summary and pre-event alerts can be modified or disabled via chat.

---

## ~~📅 Calendar~~ ✅ Done — on Chronary.ai

**Status:** Shipped — calendar lives on Chronary.ai via the official Python SDK. Four MCP tools: `list_events`, `create_event`, `update_event`, `delete_event`. First-run bootstrap is `sidekick-init`.

Open follow-ups:
- **Recurring events.** Chronary's REST surface doesn't document RRULE; the bot creates individual instances when asked for "every X".
- **`location` and `attendees`.** Not first-class fields in Chronary — stashed in event `metadata`. Round-trips correctly on list/get.

---

## ~~💬 Multi-platform chat~~ ✅ Done — Telegram + Slack

**Status:** Shipped — Slack adapter runs concurrently with Telegram when `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` are set. `ChatPlatform` ABC ready for a WhatsApp adapter when needed.

Open follow-ups:
- **Reminders on Slack.** Morning summary and pre-event check still fire only on Telegram. Multi-platform reminder delivery is the natural next step — extend `REMINDER_CHAT_ID` to a comma-separated `tg:…,sl:…` list.

---

## ~~🤖 Local LLM (Ollama)~~ ✅ Done

**Status:** Shipped — set `LLM_PROVIDER=ollama` and the bot routes through a local Ollama server. Recommended tool-capable models: `llama3.1:8b`, `qwen2.5:7b`. Tool-use reliability is materially below Claude's on multi-tool plans — acceptable for hobby/offline use.

---

## ~~🐳 Docker self-hosting~~ ✅ Done

**Status:** Shipped — `docker compose up` brings up the bot. Ollama service is gated behind the `ollama` profile so users on the Anthropic path don't pull a 5GB image they won't run. NVIDIA GPU passthrough scaffolded as commented config.

---

## 🌤️ Weather

**Status:** Next up
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
| No new dependencies | `urllib` from stdlib handles the API call |

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
- Works across both Telegram and Slack now that platforms are abstracted

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
| 7 | Multi-platform reminders | Next up — small follow-on to Slack adapter |
| 8 | Weather | Planned — easy, high daily utility |
| 9 | Birthday reminders | Planned — reuses existing calendar tools |
| 10 | Quick notes / wiki | Planned |
| 11 | Meal planning | Planned |
| 12 | Location check-in | Planned |
| 13 | WhatsApp adapter | When demand justifies it |
