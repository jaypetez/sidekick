<p align="center">
  <img src="docs/assets/sidekick-logo.svg" alt="Sidekick" width="420">
</p>

<p align="center">
  <strong>The AI assistant you text like a friend.</strong><br>
  Calendar, lists, and reminders — in your browser, on Telegram, or on Slack. Powered by Claude or a local LLM. Self-hosted.
</p>

<p align="center">
  <a href="examples/01-local-ollama-docker/"><img src="https://img.shields.io/badge/Try%20it%20locally-5b21b6?style=for-the-badge&logo=docker&logoColor=white" alt="Try it locally"></a>
  <a href="FEATURES.md"><img src="https://img.shields.io/badge/Features-db2777?style=for-the-badge" alt="Features"></a>
  <a href=".github/CONTRIBUTING.md"><img src="https://img.shields.io/badge/Contributing-0891b2?style=for-the-badge" alt="Contributing"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-16a34a?style=for-the-badge" alt="MIT License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/tests-87%20passing-22c55e" alt="87 tests">
  <img src="https://img.shields.io/badge/calendar-Chronary.ai-8b5cf6" alt="Chronary">
  <img src="https://img.shields.io/badge/LLM-Claude%20%7C%20Ollama-f59e0b" alt="LLM">
  <img src="https://img.shields.io/badge/chat-Web%20%7C%20Telegram%20%7C%20Slack-0ea5e9" alt="Chat">
</p>

---

## Try it locally in 5 minutes

The fastest way to see Sidekick is **without** Telegram or an Anthropic key. Run everything in Docker, with a local LLM on your machine, and chat with it in your browser:

```bash
cp examples/01-local-ollama-docker/.env.example .env   # then paste your Chronary key
docker compose run --rm sidekick sidekick-init         # one-time Chronary bootstrap
docker compose --profile ollama up -d
docker compose exec ollama ollama pull qwen2.5:14b
# open http://localhost:8080/chat
```

Full walkthrough — including GPU passthrough, smaller-model alternatives, and what to try first — in [**examples/01-local-ollama-docker/**](examples/01-local-ollama-docker/).

---

## Screenshots

<p align="center">
  <img src="docs/screenshots/chat.png" alt="Web chat UI" width="720"><br>
  <em>The in-browser chat — same agent, no Telegram needed.</em>
</p>

<p align="center">
  <img src="docs/screenshots/dashboard.png" alt="Admin dashboard" width="720"><br>
  <em>Dashboard health tiles and personality at a glance.</em>
</p>

<p align="center">
  <img src="docs/screenshots/tasks.png" alt="Tasks page" width="720"><br>
  <em>Tasks are shared state — the agent and the dashboard read/write the same SQLite db.</em>
</p>

> Capturing the screenshots above: start the stack (e.g. via [examples/01](examples/01-local-ollama-docker/)), then `pip install playwright && playwright install chromium && python scripts/capture_screenshots.py` against the running app.

---

## What it's like to use

Sidekick lives wherever you want to chat with it — the web UI, Telegram, or Slack. Talk to it the way you'd ping a roommate — no slash commands required, no special grammar.

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

> Want the fully-local "no Telegram, no Anthropic key" path? Use the [Try it locally in 5 minutes](#try-it-locally-in-5-minutes) box above (or [examples/01-local-ollama-docker/](examples/01-local-ollama-docker/) for the full walkthrough). The Quickstart below is for the production path with Telegram + Anthropic.

### Option A — Docker (recommended)

```bash
git clone https://github.com/jaypetez/sidekick.git
cd sidekick
cp .env.example .env
# Fill in TELEGRAM_BOT_TOKEN (or leave blank for web-only mode),
# ANTHROPIC_API_KEY, CHRONARY_API_KEY

# One-time Chronary bootstrap — creates an agent + default calendar:
docker compose run --rm sidekick sidekick-init
# Paste the printed CHRONARY_AGENT_ID and CHRONARY_CALENDAR_ID into .env

docker compose up -d
docker compose logs -f sidekick
```

To run with a **local LLM** instead of Anthropic:

```bash
# In .env: LLM_PROVIDER=ollama, OLLAMA_BASE_URL=http://ollama:11434, OLLAMA_MODEL=qwen2.5:14b
docker compose --profile ollama up -d
docker compose exec ollama ollama pull qwen2.5:14b
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
| `TELEGRAM_BOT_TOKEN` | only when you want Telegram (leave blank for web-only mode) | [@BotFather](https://t.me/BotFather) → `/newbot` |
| `TELEGRAM_ALLOWED_USER_IDS` | whenever Telegram is enabled — **closed-by-default: unset = every message rejected** | CSV of numeric user IDs; find yours via [@userinfobot](https://t.me/userinfobot) |
| `LLM_PROVIDER` | optional, default `anthropic` | `anthropic` \| `ollama` |
| `ANTHROPIC_API_KEY` | `LLM_PROVIDER=anthropic` | [console.anthropic.com](https://console.anthropic.com) |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | `LLM_PROVIDER=ollama` | local install (or compose `ollama` service) |
| `CHRONARY_API_KEY` | always | [console.chronary.ai](https://console.chronary.ai) — org key for first-time `sidekick-init` |
| `CHRONARY_AGENT_ID`, `CHRONARY_CALENDAR_ID` | always | printed by `sidekick-init` on first run |
| `SIDEKICK_DB_PATH` | optional | default `~/.config/sidekick/sidekick.db` |
| `REMINDER_CHAT_ID` | enables morning summary + pre-event alerts | send `/get_id` to the bot in the target chat |
| `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` | enabling the Slack adapter | Slack app config (below) |
| `SIDEKICK_WEB_ENABLED` | optional, default `true` | set `false` to skip the admin dashboard |
| `SIDEKICK_WEB_HOST`, `SIDEKICK_WEB_PORT` | optional | bind interface/port for the dashboard (default `127.0.0.1:8080`) |
| `TIMEZONE` | optional | IANA name, default `America/Chicago` |

Full reference: [`.env.example`](.env.example).

---

## Admin dashboard

Sidekick ships an in-process web UI at **http://127.0.0.1:8080** for the operator. It runs alongside the Telegram/Slack adapters on the same event loop — and when no Telegram token is set, it stands alone as the only chat surface. The pages:

- **Chat** — converse with the agent right in the browser; uses the same `SidekickAgent` as Telegram/Slack
- **Dashboard** — at-a-glance health tiles (scheduler, MCP, reminder count, tool count) + active personality
- **Reminders** — create, pause, resume, or delete; built-in jobs (morning summary, pre-event check) can be paused but not removed
- **Tasks** — browse every list, add/complete/delete items, clear completed, drop a whole list
- **Calendar** — view upcoming events in a configurable window, create / edit / delete events
- **Settings** — switch personality (same presets the `/personality` chat command exposes) and view a read-only env summary (tokens are excluded)
- **Health** — JSON `/health` endpoint reports scheduler + MCP subprocess liveness for monitoring

The dashboard is enabled by default and binds to localhost only — no auth, no remote exposure. To reach it remotely, SSH-tunnel (`ssh -L 8080:127.0.0.1:8080 …`) or use Tailscale/WireGuard.

**Docker caveat:** inside a container `127.0.0.1` is the container's loopback, not the host's. Either set `SIDEKICK_WEB_ENABLED=false`, `docker exec` into the container to reach it, or override `SIDEKICK_WEB_HOST=0.0.0.0` and map the port — be aware that exposes it to anyone who can reach the host network.

---

## Setting up Telegram

Telegram is the default chat surface. Two env vars get you running: a bot token and an allowlist.

1. **Create the bot.** Message [@BotFather](https://t.me/BotFather), send `/newbot`, and follow the prompts (pick a display name, then a username ending in `bot`). BotFather replies with a token like `123456:ABC-DEF…` — put it in `.env` as `TELEGRAM_BOT_TOKEN`.
2. **Find your user ID.** Message [@userinfobot](https://t.me/userinfobot); it replies with your numeric Telegram user ID.
3. **Allow yourself in.** Set `TELEGRAM_ALLOWED_USER_IDS` to that ID (CSV for multiple people, e.g. `12345678,98765432`). **This is closed-by-default — if it's unset or empty, the bot rejects every message,** so this step is not optional. Restart after editing.
4. **Start chatting.** Open your bot in Telegram (search its `@username`) and send `/start`. Talk to it naturally — no slash commands required.

**Built-in commands:** `/start` (intro), `/reset` (clear conversation history), `/get_id` (print this chat's ID), `/personality <style>` (change tone).

> The allowlist is keyed on **user** ID, while `REMINDER_CHAT_ID` (below) wants a **chat** ID. In a 1:1 DM with the bot the two are identical, so `/get_id` in your DM gives you the value for both. They diverge only in group chats.

### Using it in a group chat

You can run Sidekick in a group instead of (or alongside) a 1:1 DM — handy for a household or team. Two extra things matter:

1. **Add the bot to the group.** Open the group → *Add members* → search your bot's `@username` and add it.
2. **Decide on group privacy mode.** By default, BotFather bots join with **privacy mode ON**: the bot only sees messages that @mention it, reply to one of its messages, or are commands (`/get_id`, `/start`). When you add it, Telegram shows a *"the bot has no access to messages"* note — that's this setting, and it's expected.
   - **Leave it ON** to have the bot respond only when explicitly addressed (`@yourbot what's on my calendar?`). Recommended for busy groups.
   - **Turn it OFF** to have the bot act on *every* message in the group. Sidekick has no mention-gate, so with privacy off it will try to respond to everything an allowlisted user posts. To disable: message [@BotFather](https://t.me/BotFather) → `/setprivacy` → pick your bot → **Disable**. ⚠️ The change only applies to groups the bot joins *after* the switch, so **remove the bot from the group and re-add it** for it to take effect.
3. **The allowlist still applies per user.** `TELEGRAM_ALLOWED_USER_IDS` gates *who* may command the bot even in a group — add each person's numeric user ID, comma-separated. Everyone else is ignored.
4. **Point reminders at the group.** Set `REMINDER_CHAT_ID` to the group's chat ID — a **negative** number for groups. Get it with `/get_id` in the group, or via the API tip below.

> **Tip — grab user & chat IDs without running the bot.** Once `TELEGRAM_BOT_TOKEN` is set and the bot is in the chat, post a message there, then ask Telegram's API directly:
> ```bash
> curl -s "https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates" | python -m json.tool
> ```
> In each update, `message.from.id` is a **user ID** (for `TELEGRAM_ALLOWED_USER_IDS`) and `message.chat.id` is the **chat ID** (negative for groups; use it for `REMINDER_CHAT_ID`). Telegram only retains updates briefly, so send a fresh message right before you call this.

### Enabling reminders (optional)

Morning summaries and pre-event alerts need a destination chat. Send `/get_id` to the bot in the chat you want them delivered to, then set `REMINDER_CHAT_ID` to the value it prints and restart. Leave it unset to skip reminders entirely.

---

## Adding Slack

Telegram works out of the box once allowlisted (above). Slack is opt-in and runs concurrently — same bot, two front doors.

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

| Model | VRAM (Q4) | Notes |
|---|---|---|
| `qwen2.5:14b` | ~9GB | **Best tool-use we tested at ≤16GB VRAM.** Default in [examples/01](examples/01-local-ollama-docker/). |
| `qwen2.5:7b` | ~5GB | Smaller GPUs or CPU-only. Slightly better at function-calling than llama3.1:8b. |
| `llama3.1:8b` | ~5GB | Project's historical baseline. Solid general balance. |

> ⚠️ Tool-use reliability on any local model is **materially lower** than Claude's. For day-to-day production, keep Anthropic. Ollama is for offline / cost-free / privacy-sensitive operation where the occasional missed tool call is acceptable.

---

## Deployment posture

Sane defaults out of the box, but you own the host. A few specifics worth knowing:

- **Web dashboard binds to `127.0.0.1` only** inside the container. Docker publishes it back to the host loopback via the `127.0.0.1:8080:8080` mapping in `docker-compose.yml`, so it is never reachable from the LAN unless you change `SIDEKICK_WEB_HOST`.
- **Ollama port is loopback-only.** The compose file binds the `ollama` service to `127.0.0.1:11434`, so a misconfigured firewall doesn't accidentally expose your local model server to the network.
- **`.env` should be `chmod 0600`.** The file holds bot tokens, Chronary keys, and Anthropic credentials.
- **Persisted state files (`reminders.json`, `config.json`) are written with mode `0600`** so other users on the host can't read your reminder schedule.
- **MCP subprocess env is scoped** — only Chronary, SQLite, and timezone vars propagate. Telegram / Slack / Anthropic / web-auth tokens are withheld.
- Full hardening guide and the dashboard auth token requirement live in `docs/security.md`.

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
pytest                                     # full suite with the 80% coverage gate
pytest --no-cov                            # faster when iterating locally
pytest tests/test_storage_tasks.py -v      # one file
ruff check . && ruff format --check .      # lint + format check (CI gates these)
mypy src/sidekick                          # strict type check (CI gates this)
```

No live API calls in tests — everything is mocked. CI runs lint + typecheck + tests on Python 3.11 and 3.12 plus a dependency-review step; all five jobs must pass before a PR can merge.

Branching, commit, and PR conventions live in [`.github/CONTRIBUTING.md`](.github/CONTRIBUTING.md). `main` is protected (CODEOWNERS review, linear history, no force-push) — work happens on `feat/`, `fix/`, `chore/` branches and lands via PR.

---

## License

[MIT](LICENSE).

---

## Security

Sidekick is a single-tenant self-hosted bot. Defaults are closed: Telegram and Slack require explicit user allowlists, the web dashboard binds to `127.0.0.1:8080`, and CI runs `pip-audit`, `bandit`, and CodeQL on every PR.

- Policy and how to report a vulnerability: [`.github/SECURITY.md`](.github/SECURITY.md)
- Operator's guide (threat model, surface posture, checklist, known limitations): [`docs/security.md`](docs/security.md)
