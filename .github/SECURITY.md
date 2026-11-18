# Security Policy

## Reporting a vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Use GitHub's private vulnerability reporting feature instead:

1. Go to the [Security tab](https://github.com/jaypetez/sidekick/security) of this repository.
2. Click **Report a vulnerability**.
3. Fill in the details — please include a minimal reproduction, affected
   commit SHA or release tag, and your assessment of impact.

You can expect an initial response within 7 days. If the issue is confirmed,
we will work on a fix and coordinate disclosure with you.

## Scope

Sidekick is a self-hosted single-tenant chat bot. The threat model assumes
the operator runs it on their own machine or VPS for personal use. Reports
involving the following are in scope:

- **Credential / token leakage** through logs, error messages, API
  responses, or files the bot writes in its config dir
  (`$SIDEKICK_CONFIG_DIR`, default `~/.config/sidekick`): the SQLite
  database, `reminders.json`, `config.json`, `runtime.json`,
  `web_session.secret` and `chronary_webhook.secret`.
- **Unauthorized access** to the web dashboard, its JSON API, the Chronary
  webhook route, the MCP subprocess, or any chat surface (Telegram bot,
  Slack bot, web chat).
- **Tool-execution boundary** issues: anything that lets an unauthenticated
  caller invoke calendar / task / reminder tools, or that bypasses the
  configured chat allowlists.
- **Webhook forgery**: anything that gets an unsigned or replayed request
  accepted by `/webhooks/chronary`.
- **Prompt-injection** issues that result in real-world side effects (data
  exfiltration, destructive tool calls without confirmation) — though see
  "Known limitations" in [`docs/security.md`](../docs/security.md).
- **Container / file-permission** problems in the published Docker image
  and `docker-compose.yml`.

### Out of scope

- Vulnerabilities in upstream dependencies — please report those to the
  upstream maintainer. We do run `pip-audit` in CI, so transitive issues
  will surface on their own.
- Issues that require physical access to a victim's machine.
- Social engineering of users or maintainers.
- Denial-of-service via excessive LLM spend. Chat messages are
  rate-limited per user, but there is no spend cap — see
  `docs/security.md`.

## Exposed surfaces

| Surface             | Default state |
| ------------------- | ------------- |
| Telegram bot        | Closed allowlist (`TELEGRAM_ALLOWED_USER_IDS`; unset = everyone rejected), per-user rate limit |
| Slack bot           | Closed allowlist (`SLACK_ALLOWED_USER_IDS`, optional `SLACK_ALLOWED_CHANNELS`), Socket Mode, per-user rate limit |
| Web dashboard       | Loopback only (`127.0.0.1:8080`); `Host`-pinned when no token; `SIDEKICK_WEB_AUTH_TOKEN` required for any non-loopback bind; CSRF on state-changing requests |
| JSON API / `sidekick-cli` | Same middleware as the dashboard; bearer token when auth is on; secrets never returned |
| Chronary webhook    | Off (404) until a signing secret is configured; HMAC-signed, 300 s replay window, de-duplicated |
| MCP subprocess      | stdio only; scoped env (Chronary credentials and paths only — no LLM, chat or web secrets) |
| LLM (Claude/Ollama) | Tool calls executed without per-tool confirmation; see notes |

See [`docs/security.md`](../docs/security.md) for the full operator's
security guide.

## Supported versions

Sidekick is pre-1.0. Only the latest tagged release (`v0.1.x`, see
[Releases](https://github.com/jaypetez/sidekick/releases)) and the
matching `ghcr.io/jaypetez/sidekick:latest` image are supported. Fixes
land on `main` and ship in the next release; there are no backports.
