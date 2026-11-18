# Sidekick Operator Security Guide

This document is the operator's security reference for self-hosting Sidekick.
For vulnerability reporting and policy, see
[`.github/SECURITY.md`](../.github/SECURITY.md).

## Threat model

Sidekick is a **single-tenant self-hosted chat bot**. The operator is the
only intended user. The threat model assumes:

- **Attackers** are anyone who:
  - Knows the bot's Telegram username and can DM it.
  - Is in a Slack workspace (or Telegram group) where the bot is installed.
  - Can reach the web dashboard's socket (`127.0.0.1:8080` by default —
    i.e., has shell access, or the operator deliberately exposed it).
  - Can reach the public Chronary webhook URL, if push reminders are on.
  - Has read access to the host filesystem (e.g., a backup, a leaked
    `.env`, or an exfiltrated config directory).
- **Trust boundary**: the operator and the LLM provider. The LLM itself is
  treated as semi-trusted: it can be coerced via prompt injection in tool
  output, so it must not be the only thing standing between a user and a
  destructive action. See "Known limitations".
- **What we do _not_ defend against**: a malicious operator, kernel-level
  attackers, a compromised LLM provider, or supply-chain attacks on
  dependencies (those are surfaced by `pip-audit` and CodeQL but not
  blocked at runtime).

## Surface-by-surface posture

### Telegram

- **Allowlist**: `TELEGRAM_ALLOWED_USER_IDS` (comma-separated numeric user
  IDs). It is **always closed by default**: unset or empty means every
  message is rejected, and a warning is logged at startup. Non-allowlisted
  users get a short "not on this bot's allowlist" reply; their message
  never reaches the agent. In a group, the allowlist still applies per
  user.
- **Rate limit**: per user, a token bucket of `SIDEKICK_RATE_LIMIT_MAX`
  messages (default 10) per `SIDEKICK_RATE_LIMIT_WINDOW_SECONDS` (default
  60), shared with Slack and web chat.
- **What's exposed**: full agent tool surface (calendar, tasks, reminders).
- **Logging**: denials and rate-limit hits log the user ID, username and
  chat ID so you can see who tried.
- Scheduled reminders are sent only to `REMINDER_CHAT_ID`.

### Slack

- **Allowlist**: `SLACK_ALLOWED_USER_IDS` (comma-separated Slack user IDs,
  e.g. `U01ABC`). Same closed-by-default model as Telegram, including the
  denial reply.
- **Channel allowlist** (optional): `SLACK_ALLOWED_CHANNELS`. When set, the
  bot silently ignores messages from any other channel.
- **Rate limit**: same per-user bucket as Telegram.
- **Transport**: Socket Mode — no public webhook URL to defend.
- **What's exposed**: same agent tool surface.

### Web dashboard

- **Bind**: `127.0.0.1:8080` by default (`SIDEKICK_WEB_HOST` /
  `SIDEKICK_WEB_PORT` to override). Loopback-only means even a host on
  the LAN cannot reach it without explicit configuration.
- **Authentication**: opt-in. With `SIDEKICK_WEB_AUTH_TOKEN` unset there
  is **no authentication** — anything that can reach the socket is the
  operator. The dashboard **refuses to start** on a non-loopback bind
  (e.g. `0.0.0.0`) without a token, and refuses a placeholder or
  <16-character token on any bind. With a token set, requests need
  `Authorization: Bearer <token>` or a session cookie from `/login`;
  unauthenticated browser GETs are redirected to `/login` (the `next`
  parameter is restricted to internal paths, so it can't be used as an
  open redirect).
- **Sessions**: an encrypted cookie (`HttpOnly`, `SameSite=Lax`) bound to
  the token — rotating the token logs everyone out — that expires after 7
  days. The cookie key comes from `SIDEKICK_WEB_SESSION_SECRET` (ignored,
  with an error log, if shorter than 32 bytes) or a generated
  `web_session.secret` file (0600) in the config dir.
- **DNS rebinding**: when auth is off, requests whose `Host` header isn't a
  loopback name (or listed in `SIDEKICK_WEB_ALLOWED_HOSTS`) get `421`, so a
  malicious page that rebinds its hostname to `127.0.0.1` can't drive the
  dashboard from your browser. With auth on, the check is skipped (the
  rebound origin has neither the cookie nor the token).
- **CSRF**: enforced on every `POST`/`PUT`/`PATCH`/`DELETE` (`X-CSRF-Token`
  header or `_csrf` form field). Exempt: requests with a valid bearer token
  (browsers never attach that header cross-site), `/static/`, `/health`,
  and the Chronary webhook route.
- **Rate limits**: `POST /chat` (the browser chat) uses the shared bucket,
  keyed by client address; failed logins are limited to 10 per 5 minutes
  per client address. `POST /api/chat` is **not** rate-limited (it needs
  the token whenever auth is on). `X-Forwarded-For` is ignored unless
  `SIDEKICK_WEB_TRUST_PROXY=true` — set it only behind a reverse proxy that
  overwrites the header.
- **Headers** on every response: a Content-Security-Policy
  (`default-src 'self'`, scripts from `'self'` and `https://unpkg.com`,
  `frame-ancestors 'none'`, `form-action 'self'`, `base-uri 'self'`),
  `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer` and a restrictive `Permissions-Policy`.
  HTML responses also get `Cache-Control: no-store, no-cache,
  must-revalidate`. The CSP still allows `'unsafe-inline'` scripts for a
  few small inline bootstraps.
- **htmx**: loaded from unpkg with a pinned SRI integrity hash so a
  compromised CDN cannot inject script.
- **`/health`**: unauthenticated callers (when auth is on) get only
  `{"status": "ok"}`; the per-component breakdown needs auth.
- **JSON API and CLI**: `/api/*` sits behind the same session, bearer,
  CSRF and Host-check middleware. `sidekick-cli` authenticates with
  `SIDEKICK_API_TOKEN` (falling back to `SIDEKICK_WEB_AUTH_TOKEN`) as a
  bearer token. The System page, `/api/system` and `/api/config` never
  return secret values — only set / not set — and mask credentials
  embedded in URLs.
- **In Docker**: `127.0.0.1` inside the container is _not_ the host's
  loopback, so the container must bind `SIDEKICK_WEB_HOST=0.0.0.0`, which
  makes `SIDEKICK_WEB_AUTH_TOKEN` mandatory. The bundled
  `docker-compose.yml` publishes the port only on the host's
  `127.0.0.1:8080`, so it is still not reachable from the LAN. Setting
  `SIDEKICK_WEB_ENABLED=false` turns the dashboard off — except in
  web-only mode (no Telegram token), where it is the only surface and is
  forced on.

### Chronary webhook (`POST /webhooks/chronary`)

Only present if you enable push reminders. This route is meant to be
reachable from the internet (through a tunnel or reverse proxy), so it
skips the session/bearer auth, CSRF and Host checks. Its protections:

- Returns `404` unless a signing secret is configured
  (`CHRONARY_WEBHOOK_SECRET`, or the 0600 `chronary_webhook.secret` file
  that `sidekick-webhook register` writes — the CLI never prints it).
- Every request must carry a valid HMAC-SHA256 signature from Chronary,
  with a 300-second timestamp tolerance against replays; anything else is
  `401`.
- Bodies over 64 KB are rejected.
- Deliveries are de-duplicated by delivery ID, and events for other
  calendars or other event types are ignored.

Expose **only this path** publicly (for example, a Cloudflare Tunnel route
with path `^/webhooks/chronary$`). Publishing the whole dashboard puts the
login form on the internet.

### MCP subprocess

- Spawned over stdio. No network listener.
- **Scoped environment**: the subprocess receives only process basics
  (`PATH`, `HOME`, locale, temp dirs) plus what it needs for Chronary and
  SQLite: `CHRONARY_API_KEY`, `CHRONARY_AGENT_ID`, `CHRONARY_CALENDAR_ID`,
  `TIMEZONE`, `SIDEKICK_DB_PATH` and `SIDEKICK_CONFIG_DIR`. The Anthropic
  key, Telegram and Slack tokens and the web auth token are _not_
  forwarded.

### LLM (Claude or Ollama)

- Tool calls are forwarded without per-tool user confirmation. The agent
  trusts the LLM's intent. See "Known limitations" below.
- The Anthropic API key stays in the parent process and is never logged.
  If you set it on the settings page, it is saved to `runtime.json`
  (0600) in the config dir, and the UI only ever shows its last 4
  characters.
- With `LLM_PROVIDER=ollama`, prompts and tool results go to whatever
  `OLLAMA_BASE_URL` points at. Keep it on loopback or a network you trust;
  the bundled compose file binds Ollama to `127.0.0.1:11434`.

## Operational checklist

- [ ] `chmod 600 .env` — the file contains every API key the bot uses.
- [ ] `chmod 700` the config dir (`$SIDEKICK_CONFIG_DIR`, default
      `~/.config/sidekick`). It holds the SQLite DB, `reminders.json`,
      `config.json`, `runtime.json` (which may contain an API key set from
      the settings page), `web_session.secret` and, if you use push
      reminders, `chronary_webhook.secret`.
- [ ] Dashboard bound to `127.0.0.1`, or set `SIDEKICK_WEB_AUTH_TOKEN`
      (generate it with `python -c "import secrets;
      print(secrets.token_urlsafe(32))"`) before exposing it.
- [ ] If push reminders are on, only `/webhooks/chronary` is reachable
      from the internet.
- [ ] Verify htmx SRI hash matches the version pinned in
      `src/sidekick/web/templates/base.html` after any htmx bump.
- [ ] CI: `pip-audit`, `bandit`, and CodeQL all green on `main`.
- [ ] `pre-commit install` locally so bandit (and `pip-audit`, on push)
      catch obvious issues early.
- [ ] Allowlists set: `TELEGRAM_ALLOWED_USER_IDS` (if using Telegram),
      `SLACK_ALLOWED_USER_IDS` and optionally `SLACK_ALLOWED_CHANNELS` (if
      using Slack).
- [ ] Periodically rotate: Telegram bot token, Slack tokens, Anthropic
      key, Chronary API key, web auth token.

## Known limitations

These are accepted gaps. Open an issue (or a PR) if any of them blocks
your use case.

- **Prompt injection through tool result text**. Calendar event titles,
  task names, and reminder messages flow back to the LLM verbatim. A
  hostile string in one of those fields could in principle convince the
  LLM to invoke a destructive tool. Since the bot is single-tenant and
  all input is operator-supplied, this is a documented gap rather than a
  fixable bug in v1. Mitigations: destructive tools are marked in
  `agent.DESTRUCTIVE_TOOLS` and their calls are logged at `INFO` so the
  operator can audit them.
- **No per-tool RBAC / confirmation**. The agent executes any tool the
  LLM asks for. A future revision may gate `DESTRUCTIVE_TOOLS` behind an
  explicit "yes" prompt for the user.
- **No cap on LLM spend**. Chat messages are rate-limited per user, but
  an allowlisted user (or anyone holding the web token, via the
  un-limited `POST /api/chat`) can still run up a proportionate Anthropic
  bill. Use Anthropic's account-level spend cap as the backstop.
- **CSP allows inline scripts**. `'unsafe-inline'` remains in
  `script-src` until the inline bootstraps are moved to files or pinned.
- **Logs are unstructured**. The redaction filter in
  `src/sidekick/logging_setup.py` scrubs values after common secret
  keywords (`api_key`, `token`, `secret`, `password`, `authorization`,
  `bearer`) and bare Telegram bot tokens, but it is best-effort —
  arbitrary base64 blobs will not be redacted.

## Reporting vulnerabilities

See [`.github/SECURITY.md`](../.github/SECURITY.md).
