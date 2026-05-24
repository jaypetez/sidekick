# Example 01 — Local Ollama + Docker + Web Chat

Run Sidekick **without Telegram or a hosted LLM**. Everything runs in Docker, the LLM runs on your machine via Ollama, and you chat with the bot in your browser at <http://localhost:8080/chat>.

This is the fastest way to kick the tires before deciding whether to wire up Telegram, Slack, or Anthropic.

---

## What you'll have when it's running

- A local Sidekick container, no Telegram bot needed
- A local Ollama container running `qwen2.5:14b` (decent tool-use on commodity hardware)
- A web UI at <http://localhost:8080> with **Chat, Dashboard, Reminders, Tasks, Calendar, Settings** pages

## Prerequisites

- Docker Desktop or Docker Engine + Compose v2
- ~12GB free disk space (qwen2.5:14b is ~9GB plus image/data overhead)
- **GPU (recommended)** — 16GB VRAM fits qwen2.5:14b Q4 comfortably. CPU works but is slow (10–30s per turn).
- A **Chronary API key** (free tier at <https://console.chronary.ai>) — Chronary is the calendar backend; it's the one cloud dependency this example doesn't drop.

> **Why is Chronary still required?** Sidekick's calendar tools talk to Chronary. The bot will start without it, but `/events` will fail and the agent's calendar tools will return errors. Everything else (chat, tasks, reminders) works fine.

## 5-minute setup

```bash
# 1. From the repo root, drop in the example .env (overwrites the default).
cp examples/01-local-ollama-docker/.env.example .env

# 2. Generate a strong random token and paste it into SIDEKICK_WEB_AUTH_TOKEN.
#    The web UI is bound to 0.0.0.0 inside the container (so the host can
#    reach it via the published port) and the bot refuses to start a
#    non-loopback dashboard without one.
#      *nix:    python -c "import secrets; print(secrets.token_urlsafe(32))"
#      Windows: -join ((48..57)+(97..122)+(65..90) | Get-Random -Count 48 | %{[char]$_})

# 3. Open .env and paste your Chronary API key into CHRONARY_API_KEY.
#    Leave the AGENT_ID and CALENDAR_ID alone for the moment — the next step prints them.

# 4. Bootstrap Chronary. This creates an agent + calendar tied to your key
#    and prints the IDs to paste back into .env.
docker compose run --rm sidekick sidekick-init
#   → copy the printed CHRONARY_AGENT_ID and CHRONARY_CALENDAR_ID into .env

# 5. Bring up the stack with the ollama profile.
docker compose --profile ollama up -d

# 6. Pull the model into the ollama volume (~9GB, one-time download).
docker compose --profile ollama exec ollama ollama pull qwen2.5:14b

# 7. Open your browser. The dashboard requires the auth token on every
#    request — easiest path is a browser extension that sets the header:
#      Authorization: Bearer <your token>
#    Or hit it from the terminal:
#      curl -H "Authorization: Bearer $TOKEN" http://localhost:8080/chat
#    Chat:      http://localhost:8080/chat
#    Dashboard: http://localhost:8080/
```

Watch the logs as you click around:

```bash
docker compose logs -f sidekick
```

Stop everything (state persists in `./data/sidekick` and the `ollama_data` volume):

```bash
docker compose down
```

## Things to try in the chat

- *"add milk, eggs, and tortillas to groceries"* — exercises the tasks backend
- *"what's on my grocery list?"* — exercises read tools
- *"clear out the completed groceries"* — exercises mutation tools

Open the **Tasks** page in the dashboard while you do this and you'll see the same items live; the agent and the web UI share state through the same SQLite database.

## GPU passthrough (NVIDIA)

The default `docker-compose.yml` keeps GPU off so it works on machines without one. To use your GPU, uncomment the `deploy:` block in `docker-compose.yml` under the `ollama` service:

```yaml
deploy:
  resources:
    reservations:
      devices:
        - driver: nvidia
          count: all
          capabilities: [gpu]
```

Then bounce the stack: `docker compose --profile ollama down && docker compose --profile ollama up -d`.

Verify the GPU is in use:

```bash
docker compose exec ollama nvidia-smi
```

## Picking a different model

If 16GB VRAM is tight (or you don't have a GPU), edit `OLLAMA_MODEL` in `.env`:

| Model | VRAM (Q4) | Notes |
|---|---|---|
| `qwen2.5:14b` (default) | ~9GB | Best tool-use we tested at ≤16GB. |
| `qwen2.5:7b` | ~5GB | Smaller, often a hair better at tool-calling than llama3.1:8b. |
| `llama3.1:8b` | ~5GB | Solid baseline. Project default for the non-example path. |

Then re-pull: `docker compose exec ollama ollama pull <model>` and restart sidekick.

## Caveats specific to this example

- **Reminders won't fire.** The morning summary and pre-event reminders deliver via Telegram. With no Telegram token they're disabled — the scheduler still starts so the *Reminders* page works, but jobs that need a Bot are skipped.
- **Local LLM tool-use is meaningfully worse than Claude.** Multi-step plans sometimes misfire. If something doesn't work, try again with a slight rephrasing — and consider swapping to Anthropic if you need production reliability.
- **The web UI binds to `0.0.0.0` inside the container** so the host browser can reach it. The host port (`8080`) is published only on localhost by default, so this is not internet-exposed. If you change Docker's port publishing, mind the security implications.
- **No auth by default — example 01 enables it for you.** The bot's defense-in-depth check refuses to bind to a non-loopback host (`0.0.0.0` inside the container) without `SIDEKICK_WEB_AUTH_TOKEN`, so the example's `.env.example` makes this explicit. If you flip the host back to `127.0.0.1` (loopback) the token becomes optional, and anyone on your machine can chat with the bot. Don't expose this to a shared network without keeping the token in place.
