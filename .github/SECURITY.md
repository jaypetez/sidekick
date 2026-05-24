# Security Policy

## Reporting a vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Use GitHub's private vulnerability reporting feature instead:

1. Go to the [Security tab](https://github.com/jaypetez/sidekick/security) of this repository.
2. Click **Report a vulnerability**.
3. Fill in the details — please include a minimal reproduction, affected
   commit SHA, and your assessment of impact.

You can expect an initial response within 7 days. If the issue is confirmed,
we will work on a fix and coordinate disclosure with you.

## Scope

Sidekick is a self-hosted single-tenant chat bot. The threat model assumes
the operator runs it on their own machine or VPS for personal use. Reports
involving the following are in scope:

- **Credential / token leakage** through logs, error messages, or files
  the bot writes (`~/.config/sidekick/*`, the SQLite database, the
  reminders JSON file).
- **Unauthorized access** to the web dashboard, MCP subprocess, or any
  exposed surface (Telegram bot, Slack bot, local web server).
- **Tool-execution boundary** issues: anything that lets an unauthenticated
  caller invoke calendar / task / reminder tools, or that bypasses the
  configured chat allowlists.
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
- Denial-of-service via excessive LLM spend (the bot does not currently
  rate-limit Anthropic calls — see `docs/security.md`).

## Exposed surfaces

| Surface           | Default state                            |
| ----------------- | ---------------------------------------- |
| Telegram bot      | Closed allowlist (`TELEGRAM_ALLOWLIST`)  |
| Slack bot         | Closed allowlist (`SLACK_ALLOWLIST`)     |
| Web dashboard     | Loopback only (`127.0.0.1:8080`), token-gated, CSRF on POSTs |
| MCP subprocess    | stdio only, scoped env (no secrets)      |
| LLM (Claude/Ollama) | Tool calls executed without per-tool confirmation; see notes |

See [`docs/security.md`](../docs/security.md) for the full operator's
security guide.

## Supported versions

Only the latest release on `main` is supported. There are no backports.
