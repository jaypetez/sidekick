<p align="center">
  <img src="docs/assets/sidekick-logo.svg" alt="Sidekick" width="400">
</p>

<p align="center">
  <strong>A personal Telegram assistant powered by Claude AI.</strong>
</p>

<p align="center">
  <a href="#setup"><img src="https://img.shields.io/badge/Setup_Guide-blue?style=for-the-badge" alt="Setup Guide"></a>
  <a href="FEATURES.md"><img src="https://img.shields.io/badge/Feature_Roadmap-orange?style=for-the-badge" alt="Feature Roadmap"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green?style=for-the-badge" alt="MIT License"></a>
</p>

---

A Telegram bot that manages your Google Calendar, sends email, tracks task lists, and handles scheduled reminders — all through natural language. Powered by Claude AI and the Model Context Protocol (MCP).

Just text the bot like you'd text a person:

**Calendar**
- "What's on the calendar this week?"
- "Add soccer practice tomorrow at 4:30pm"
- "Move Tuesday's dentist appointment to Thursday at 2pm"

**Email**
- "Email grandma that the kids have a recital on Saturday"

**Task lists** *(Google Tasks)*
- "Add milk and eggs to the Costco list"
- "What's on my Trader Joe's list?"
- "What lists do I have?"
- "Add chicken to the grocery list" *(auto-creates a list named "grocery")*
- "Got the eggs" / "Mark eggs as done"
- "Rename my grocery list to Whole Foods"

**Scheduled reminders**
- "Remind me every Sunday at 5pm to prep lunches"
- "What reminders are set up?"
- "Change the morning summary to 6:30am"
- "Disable pre-event reminders"

**Personality**
- `/personality snarky` — dry wit and playful sarcasm
- `/personality pirate` — arr, matey!
- `/personality formal` — polished and professional
- `/personality default` — back to normal

The bot also sends a **morning summary** of the day's events and **pre-event reminders** so you never miss anything. Built for families, small teams, or anyone who wants a personal AI assistant in Telegram.

---

## Quickstart

If you're comfortable with Google Cloud, OAuth, and Telegram bots, here's the short version:

```bash
# 1. Clone and install
git clone https://github.com/jaypetez/sidekick.git && cd sidekick
python -m venv .venv && source .venv/bin/activate
pip install -e .

# 2. Set up secrets (outside the repo)
mkdir -p ~/.config/sidekick && chmod 700 ~/.config/sidekick
cp .env.example ~/.config/sidekick/.env
# Edit ~/.config/sidekick/.env with your Telegram bot token, Anthropic API key, etc.

# 3. Google OAuth (needs a browser — run on your laptop if server is headless)
# Enable Calendar API + Gmail API + Tasks API in Google Cloud Console
# Create OAuth Desktop credentials, download as credentials.json
python auth.py
mv token.json ~/.config/sidekick/token.json

# 4. Run
export $(cat ~/.config/sidekick/.env | grep -v '#' | xargs)
sidekick
```

Send `/get_id` in your Telegram group to get the chat ID for reminders, add it to `.env`, and restart.

If any of that is unfamiliar, the [detailed setup guide](#setup) below walks through every step.

---

## What you'll need

Before you start, make sure you have the following:

| What | Why | Cost |
|------|-----|------|
| **A Linux server or Raspberry Pi** | The bot needs to run 24/7. Any always-on machine with SSH works: a home server, a Raspberry Pi, a $5/mo VPS (DigitalOcean, Linode, etc.) | Free if you have spare hardware, ~$5/mo for a VPS |
| **Python 3.11+** | The bot is written in Python | Free |
| **A Google account** | For Calendar and Gmail access. We recommend creating a **dedicated Google account** for Sidekick (e.g., `sidekick.yourfamily@gmail.com`) so the bot has its own calendar and inbox, separate from your personal account. Share your family calendar with this account. | Free |
| **An Anthropic API key** | The bot uses Claude AI to understand your messages. Get one at [console.anthropic.com](https://console.anthropic.com). We use **Claude Haiku** which is the cheapest model — a typical family will spend **less than $1/month** on API calls. | ~$1/mo |
| **A Telegram account** | Your family chats with the bot through Telegram. Everyone in the family needs the free Telegram app on their phone. | Free |
| **A computer with a browser** (one-time only) | For the initial Google authorization step. Your laptop or phone works. You only need this once during setup. | You already have one |

---

## Setup

> **Security note:** All secrets (API keys, credentials, tokens) are stored **outside the repo**
> in `~/.config/sidekick/`. They can never accidentally be committed to git, even if you
> run `git add .` by mistake.

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd sidekick
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Create a secrets directory outside the repo

```bash
mkdir -p ~/.config/sidekick
chmod 700 ~/.config/sidekick
```

All sensitive files go here — never inside the repo folder.

### 3. Create a Telegram bot

1. Open Telegram and message **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the bot token (looks like `123456789:ABCdef...`)

### 4. Enable Google APIs

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and create a new project (e.g., "Sidekick")
2. Navigate to **APIs & Services → Library**, search for **Google Calendar API**, and enable it
3. In the same Library, search for **Gmail API** and enable it
4. In the same Library, search for **Tasks API** and enable it
5. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
6. Set application type to **Desktop app**, give it any name, then click **Create**
7. Click the download icon to download the JSON file
8. Save it to your secrets directory — **not inside the repo**:
   ```bash
   mv ~/Downloads/client_secret_*.json ~/.config/sidekick/credentials.json
   ```
9. Go to **APIs & Services → OAuth consent screen**:
   - If using a personal Google account: set to **External**, add your email as a test user
   - If using Google Workspace: set to **Internal**
10. **Important:** After setting up the consent screen, click **Publish App** on the same page. If you skip this, Google will expire your login token every 7 days and you'll have to re-authorize weekly. Publishing just removes that limit — your app is still private and only accessible to the test users you added. You do not need Google's verification for a personal app.

### 5. Configure environment

Create your `.env` file in the secrets directory:

```bash
cp .env.example ~/.config/sidekick/.env
```

Edit `~/.config/sidekick/.env` and fill in:
- `TELEGRAM_BOT_TOKEN` — from BotFather
- `ANTHROPIC_API_KEY` — from [console.anthropic.com](https://console.anthropic.com)
- `TIMEZONE` — your family's IANA timezone (e.g., `America/Chicago`). Used for morning summaries, event date boundaries, and all scheduled reminders. **Must match your actual timezone** or events will appear on the wrong day.
- Point the credential paths to your secrets directory:
  ```
  GOOGLE_CREDENTIALS_FILE=/home/YOUR_USERNAME/.config/sidekick/credentials.json
  GOOGLE_TOKEN_FILE=/home/YOUR_USERNAME/.config/sidekick/token.json
  ```
- Leave `REMINDER_CHAT_ID` blank for now (see step 7)

### 6. Authorize Google (one-time setup)

Google OAuth requires a browser to sign in. If your server has a desktop environment with a browser, you can run `auth.py` directly on it. If your server is headless (SSH-only, no GUI), you'll generate the token on any computer that has a browser and then copy it to the server.

#### Option A: Server has a desktop / browser

If you're running the bot on a machine with a graphical desktop (Ubuntu Desktop, macOS, Windows, etc.):

```bash
cd sidekick
source .venv/bin/activate
python auth.py
```

- It will ask for the path to your `credentials.json`
- A browser opens — sign in with the Google account that owns the family calendar
- Click through any "unverified app" warnings → Allow
- Move the generated `token.json` to your secrets directory:
  ```bash
  mv token.json ~/.config/sidekick/token.json
  ```

#### Option B: Server is headless (SSH-only, no browser)

If you SSH into your server (e.g., a Raspberry Pi, a VPS, PuTTY from Windows), the browser can't open there. Instead, run `auth.py` on any computer that has a browser — your Windows laptop, Mac, Linux desktop, whatever — and then copy the token to the server.

**On the computer with a browser:**

```bash
pip install google-auth-oauthlib
python auth.py
```

- Point it to your `credentials.json` (the file you downloaded from Google Cloud)
- A browser opens — sign in and authorize
- `token.json` is saved in the current folder

**Copy it to the server:**

```bash
scp token.json youruser@yourserver:~/.config/sidekick/token.json
```

Replace `youruser@yourserver` with your actual SSH login (e.g., `pi@192.168.1.50`).

---

The token auto-refreshes silently — you'll never need to do this again unless you revoke access in your Google account settings.

### 7. Get your group chat ID (for reminders)

1. Add your bot to your family Telegram group chat
2. Send `/get_id` in the group chat
3. The bot will reply with the chat ID (a negative number like `-1001234567890`)
4. Add it to `~/.config/sidekick/.env` as `REMINDER_CHAT_ID`
5. Restart the bot

---

## Running

```bash
cd sidekick
source .venv/bin/activate
export $(cat ~/.config/sidekick/.env | grep -v '#' | xargs)
sidekick
```

### Running in production (systemd)

Create `/etc/systemd/system/sidekick.service`:

```ini
[Unit]
Description=Sidekick Telegram Bot
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/sidekick
EnvironmentFile=/home/your-username/.config/sidekick/.env
ExecStart=/path/to/sidekick/.venv/bin/sidekick
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

The `EnvironmentFile` line loads secrets directly from `~/.config/sidekick/.env` without
touching the repo at all.

Then:
```bash
sudo systemctl enable --now sidekick
sudo journalctl -u sidekick -f   # view logs
```

---

## Bot commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and usage examples |
| `/reset` | Clear conversation history for this chat |
| `/get_id` | Show the current chat's ID (for `REMINDER_CHAT_ID`) |
| `/personality` | Change the bot's tone (snarky, pirate, formal, butler, surfer, or any freeform style) |

Everything else is natural language — just talk to the bot.

### What the bot can do

| Feature | How it works |
|---------|-------------|
| **Calendar** | View, add, edit, delete Google Calendar events |
| **Email** | Send emails via Gmail |
| **Task lists** | Create and manage multiple named lists (groceries, to-do, projects, store-specific shopping, etc.) via Google Tasks |
| **Scheduled reminders** | Create, update, and remove recurring reminders through chat — reminders are processed by the AI agent so they can call tools (e.g. fetch upcoming calendar events) |
| **Morning summary** | Automatic daily briefing of today's calendar events |
| **Pre-event alerts** | Heads-up notification before events start |
| **Personality** | Configurable tone via `/personality` — presets (snarky, pirate, formal, butler, surfer) or any custom style |

---

## Troubleshooting

### Google Auth

**Token stops working every 7 days**
This happens when your OAuth app is still in "Testing" mode. Google limits refresh tokens to 7 days in testing mode. Fix it permanently:
1. Google Cloud Console → **APIs & Services → OAuth consent screen**
2. Click **Publish App** and confirm
3. Re-run `auth.py` on your laptop and SCP a fresh `token.json` to the server — this is the last time you'll need to do it

**"Token has been expired or revoked"**
Re-run `auth.py` on your laptop and SCP the new `token.json` to the server:
```bash
python auth.py
scp token.json youruser@yourserver:~/.config/sidekick/token.json
```

**"token.json not found"**
You need to run `auth.py` on a computer with a browser first — see step 6 above.

**"credentials.json not found"**
Check that `GOOGLE_CREDENTIALS_FILE` in your `.env` points to the correct absolute path (e.g., `/home/youruser/.config/sidekick/credentials.json`).

**Bot says "there's a technical issue with the calendar" or can't read/write events**
The Google Calendar API is probably not enabled in your Google Cloud project:
1. Go to Google Cloud Console → **APIs & Services → Library**
2. Search for **Google Calendar API** → click it → click **Enable**
3. Wait 30 seconds and try again

If it's already enabled, your token.json may have been generated before the API was enabled. Re-run `auth.py` on your laptop to get a fresh token:
```bash
python auth.py
scp token.json youruser@yourserver:~/.config/sidekick/token.json
```

**"This app isn't verified" warning on the Google auth page**
This is normal for private apps. Click **Advanced → Go to Sidekick (unsafe)** to proceed. It just means Google hasn't reviewed the app — it's your own app so this is fine.

---

### Telegram

**Bot doesn't respond in the group chat**
- Make sure the bot is actually running (`sidekick` in a terminal or systemd service active)
- Disable privacy mode in BotFather: `/mybots` → your bot → Bot Settings → Group Privacy → Turn off
- Remove the bot from the group and re-add it after changing privacy mode
- Try the command with your bot's username: `/get_id@YourBotName`

**Bot doesn't respond at all**
Check that `TELEGRAM_BOT_TOKEN` in `.env` is correct and the bot isn't already running in another terminal.

---

### Calendar

**"Quota exceeded"**
The Google Calendar API has a free quota of 1 million requests/day — more than enough for a family bot. If you hit this something is looping; check the logs.

**Reminders not sending**
Make sure `REMINDER_CHAT_ID` is set to a negative number (group chats always have negative IDs). Send `/get_id` in the group to confirm the correct value.

**Calendar changes going to the wrong calendar**
Set `GOOGLE_CALENDAR_ID` in `.env` to the specific calendar ID. Find it in Google Calendar → click the calendar → Settings → scroll down to "Calendar ID".

---

### Email

**Bot can't send email / says Gmail isn't set up**
Two things to check:
1. Gmail API must be enabled: Google Cloud Console → **APIs & Services → Library → Gmail API → Enable**
2. Your token.json must include the Gmail scope — re-run `auth.py` on your laptop (it will ask you to approve Gmail Send permission) and SCP the new token to the server:
   ```bash
   python auth.py
   scp token.json youruser@yourserver:~/.config/sidekick/token.json
   ```

**Adding Gmail to an existing setup (already had Calendar working)**
If you set up Calendar first and are adding Gmail now, you must re-authorize even if you already have a token.json — the old token doesn't have Gmail scope. Follow the two steps above.
