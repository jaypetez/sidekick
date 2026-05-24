# Sidekick — Feature Roadmap

Ideas for future bot capabilities, roughly ordered by usefulness and ease of implementation.

---

## ~~🛒 Task Lists (Groceries, To-Do, and More)~~ ✅ Done

**Status:** Shipped — Google Tasks integration with unlimited named lists. Create store-specific grocery lists (Costco, Trader Joe's), project lists, to-do lists, or any topic-based list through natural language. Eight MCP tools: `list_task_lists`, `list_tasks`, `add_tasks`, `complete_task`, `delete_task`, `clear_completed`, `delete_task_list`, `rename_task_list`. Lists are auto-created when you add tasks to a new name.

---

## ~~⏰ Scheduled Reminders~~ ✅ Done

**Status:** Shipped — Users can add, update, list, and remove recurring reminders through chat. Four local tools: `list_reminders`, `add_reminder`, `update_reminder`, `remove_reminder`. Custom reminders persist to `~/.config/sidekick/reminders.json` and restore on restart. Built-in morning summary and pre-event alerts can be modified or disabled via chat.

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

### Future enhancements (not in initial build)
- Morning summary auto-includes weather for outdoor-sounding events (sport, game, practice, park, etc.)
- Hourly forecasts for specific event times (initial build is daily high/low/conditions)

---

## 🎂 Birthday & Anniversary Reminders
**Difficulty:** Easy
**Backend:** Google Calendar (already connected)

A dedicated "Birthdays" calendar (or labels in the main calendar) that the bot monitors. Sends a morning reminder on the day and a heads-up a few days before.

**Example messages:**
- "When is mom's birthday?"
- "Add dad's birthday on April 15"
- "What family birthdays are coming up this month?"

**Implementation notes:**
- Could use a separate Google Calendar named "Birthdays" — set `BIRTHDAY_CALENDAR_ID` in `.env`
- Existing `list_events` and `create_event` tools already handle this
- Add a new APScheduler job: weekly scan for birthdays in the next 7 days, send a heads-up
- No new tools needed — just scheduler logic

---

## 🍽️ Meal Planning
**Difficulty:** Medium
**Backend:** Google Sheets

Plan what's for dinner each day of the week. Family can check the plan, suggest changes, and the bot can automatically build a grocery list from the meal plan.

**Example messages:**
- "What's for dinner tonight?"
- "Put tacos on Tuesday and pasta on Thursday"
- "Build a grocery list from this week's meals"
- "What are we having this week?"

**Implementation notes:**
- Google Sheets as the backend — one sheet per week, columns for each day
- Needs Google Sheets API enabled + `spreadsheets` scope added to `auth.py`
- Tools: `get_meal_plan`, `set_meal`, `generate_grocery_list_from_meals`
- The grocery list generation is a great Claude use case — it reasons about ingredients

---

## 📍 Location Check-In
**Difficulty:** Easy
**Backend:** None (Telegram-native)

A status board. No GPS or tracking — people post their status as plain text and the bot remembers it. Anyone can ask where everyone is without scrolling back through the chat.

**Example messages:**
- "I'm leaving school now"
- "Heading to practice, back at 6"
- "Running 20 min late"
- "Where's Alex?" → "Alex said he was leaving school — 22 minutes ago"
- "Where is everyone?" → Bot replies with each person's last check-in and timestamp

**Optional: Telegram native location sharing**
If someone shares their live location in the chat, the bot can log it as a check-in ("Alex is near the school"). Opt-in only — no automatic tracking.

**Optional: Expected check-in alerts**
Set a deadline for someone to check in: "remind me if Alex hasn't checked in by 3:30pm." The bot pings the group if the check-in never comes.

**Implementation notes:**
- In-memory dict keyed by Telegram username: `{name: {status, timestamp}}`
- Bot watches for messages that look like check-ins (uses Claude to classify) vs regular conversation
- Or a `/checkin` command for explicit status updates
- No external API needed — pure bot logic
- Statuses reset on bot restart (acceptable)

---

## 💰 Budget Tracker
**Difficulty:** Medium
**Backend:** Google Sheets

Log expenses by category and get summaries. Useful for tracking how much is being spent on groceries, gas, activities, etc.

**Example messages:**
- "Log $47 at Costco under groceries"
- "How much have we spent on groceries this month?"
- "Show me this month's spending by category"
- "We spent $120 on baseball gear"

**Implementation notes:**
- Google Sheets as the ledger — one row per expense, columns for date/amount/category/note
- Tools: `log_expense`, `get_spending_summary`, `get_expenses_by_category`
- Needs Google Sheets API + scope (same as meal planning)

---

## 📬 Broadcast Messages
**Difficulty:** Easy
**Backend:** Telegram (already connected)

Send an announcement to the whole group from any member via the bot, with a consistent format so it's clear it's an "official" notice.

**Example messages:**
- "Announce that dinner is at 6:30 tonight"
- "Send a reminder that grandma's visit is this weekend"

**Implementation notes:**
- No new API needed — bot already sends to `REMINDER_CHAT_ID`
- Just a new bot command or Claude tool: format the message prominently and post it
- Could include a `/announce` command as a shortcut

---

## 🔑 Quick Notes / Wiki
**Difficulty:** Easy
**Backend:** Google Docs or a Google Sheet

A place to store frequently referenced info: wifi password, alarm code, vet's phone number, contact list, etc. Ask the bot and it looks it up.

**Example messages:**
- "What's the wifi password?"
- "What's Dr. Smith's phone number?"
- "Save the new garage code as 4821"

**Implementation notes:**
- A single Google Sheet with two columns: key and value
- Tools: `lookup_note`, `save_note`, `list_notes`
- Simple but surprisingly useful

---

## Implementation Priority

| # | Feature | Status |
|---|---------|--------|
| 1 | Task lists (groceries, to-do, and more) | ✅ Done |
| 2 | Scheduled reminders | ✅ Done |
| 3 | Weather | 🔜 Next |
| 4 | Birthday reminders | Planned — reuses existing calendar tools |
| 5 | Quick notes / wiki | Planned — simple, high daily utility |
| 6 | Meal planning | Planned — medium effort, unlocks grocery list generation |
| 7 | Budget tracker | Planned — needs Sheets API |
| 8 | Broadcast messages | Planned — trivial to add |
| 9 | Location check-in | Planned — nice to have, no external API |
