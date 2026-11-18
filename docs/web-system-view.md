# Design: System view & configuration inspector for the web dashboard

Status: implemented · Scope: `src/sidekick/web`, `src/sidekick/services`, `sidekick-cli`

## Problem

The local dashboard (`http://127.0.0.1:8080`) already lets you work with the
*data* Sidekick manages (tasks, reminders, calendar, chat) and edit the twelve
runtime-editable settings. What it can't do is answer "how is this Sidekick
set up, and is it healthy?":

- The home page shows four tiles (scheduler, MCP, reminder count, tool count).
  There is no version, uptime, active LLM provider/model, platform status
  (Telegram / Slack), web bind / auth posture, webhook state, or file paths.
- None of the 28 environment variables that are *not* runtime-editable are
  visible anywhere, so checking a deployment means shelling in and reading `.env`.
- The Settings page shows effective values but not where they come from. A
  value could be a runtime override (`runtime.json`), an environment value
  (`.env`), or a built-in default, and the UI couldn't say which or offer a
  one-click "revert to `.env`/default".
- Health logic is duplicated between `web/handlers/health.py` and
  `web/api/health.py`, and setting metadata (labels, defaults, which keys
  are secret) is scattered across modules.

## Goals

1. A **System** page (`/system`) that shows runtime status and the complete
   effective configuration, grouped and annotated with each value's source.
2. Settings show **source badges** and a **Reset** action per field.
3. A richer **dashboard** home page (version, uptime, LLM, platforms).
4. Matching JSON (`GET /api/system`, `GET /api/config`) and CLI
   (`sidekick-cli system status|config`) surfaces.
5. **Secrets never leave the process.** No preview characters for non-editable
   secrets, and a defensive name-based rule for unknown secret-shaped keys.

Non-goals: making more keys runtime-editable (each new editable key needs
live-apply plumbing, which is a separate change); editing `.env`; remote
access (the dashboard stays loopback-only by default).

## Layering (separation of concerns)

```
            ┌─────────────── presentation ────────────────┐
 HTML       web/handlers/system.py + templates/system.html   (server-rendered, no JS)
            web/handlers/dashboard.py + dashboard.html
 JSON       web/api/system.py  → GET /api/system, /api/config
            web/api/settings.py → adds sources/defaults to GET /api/settings
 CLI        cli/commands/system.py → /api/system, /api/config
            ├────────────── application ──────────────────┤
            services/system.py   status(), overview(), config_report()
            ├────────────── domain / metadata ────────────┤
            config_catalog.py    SettingSpec catalog (pure data, no I/O)
            runtime_config.py    store + new source(key)
            └─────────────────────────────────────────────┘
```

- **`config_catalog.py`**: a declarative tuple of `SettingSpec(key, group,
  label, description, default, secret)`. It is the single place that documents
  every environment variable. Editability and restart semantics are *derived*
  from `runtime_config.EDITABLE_KEYS` / `RESTART_REQUIRED_KEYS` rather than
  duplicated, and tests assert that every editable key and every
  `runtime_config.SECRET_KEYS` member is catalogued and flagged correctly.
- **`runtime_config.source(key)`**: returns `"override" | "env" | "default"`,
  so the store stays the only code that knows about the overlay file.
- **`services/system.py`**: framework-free functions that take `bot_data`
  (plus the optional webhook log) and return plain dicts. Both health
  handlers, the dashboard, the System page, `/api/system`, and the CLI read
  from here, which removes the duplicated health code.
- **Presentation** layers only translate: aiohttp request → service call →
  Jinja context or JSON envelope.

## Data contracts

`services.system.status(bot_data, webhook_log)`: the health payload, unchanged
shape (`scheduler`, `mcp`, `reminders`, `tools`, `webhook{...}`).

`services.system.overview(bot_data, webhook_log)`:

```json
{
  "version": "0.1.17", "started_at": "…ISO…", "uptime_seconds": 3600,
  "status": { …status()… },
  "llm": {"provider": "anthropic", "model": "claude-…"},
  "platforms": {"telegram": "running|disabled", "slack": "running|stopped|disabled"},
  "web": {"host": "127.0.0.1", "port": 8080, "auth_enabled": false, "loopback": true},
  "reminders": {"chat_configured": true, "pre_event_source": "poll", "timezone": "America/Chicago"},
  "paths": {"config_dir": "…", "runtime_config": "…", "database": "…", "reminders_file": "…"}
}
```

`services.system.config_report()`: list of groups, each
`{"group", "settings": [{key, label, description, value, display, source,
default, editable, secret, restart_required}]}`. For secrets, `value` is always
`null` and `display` is `"set"` / `"not set"`.

`GET /api/settings` additionally returns `sources: {key: source}` and
`defaults: {key: default}` for the editable keys.

## Security

- Pages and endpoints inherit the existing middleware stack: Host check,
  session or bearer auth, CSRF (all new routes are GETs), security headers,
  and `no-store` on HTML.
- The `/health` minimal-payload rule for unauthenticated callers is kept.
- Secret redaction happens in the service layer, so no presentation layer can
  leak a secret by mistake. A key counts as secret if it is catalogued as one,
  is in `runtime_config.SECRET_KEYS`, or its name contains `KEY`, `TOKEN`,
  `SECRET` or `PASSWORD`. Tests check that a planted secret never appears in
  `/system`, `/api/config` or `/api/system` bodies.

## Testing

- Unit: catalog consistency, `source()`, `config_report()` redaction and
  sources, `overview()` platform/LLM/uptime derivation.
- Web: `/system` renders and redacts, nav link, `/api/system`, `/api/config`,
  `/api/settings` sources, dashboard tiles, both health endpoints unchanged.
- CLI: `system status` / `system config` against a mocked client.
- Manual: boot the web app against mocked `bot_data` and fetch every page.
