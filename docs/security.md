# Sidekick Operator Security Guide

This document is the operator's security reference for self-hosting Sidekick.
For vulnerability reporting and policy, see
[`.github/SECURITY.md`](../.github/SECURITY.md).

## Threat model

Sidekick is a **single-tenant self-hosted chat bot**. The operator is the
only intended user. The threat model assumes:

- **Attackers** are anyone who:
  - Knows the bot's Telegram username and can DM it.
  - Is in a Slack workspace where the bot is installed.
  - Can reach `127.0.0.1:8080` on the host (i.e., has shell access, or
    the operator deliberately exposed the dashboard).
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

- **Allowlist**: `TELEGRAM_ALLOWLIST` (comma-separated user IDs). When set,
  any message from an unlisted user ID is dropped before reaching the
  agent. The bot is closed-by-default in a typical deployment.
- **What's exposed**: full agent tool surface (calendar, tasks, reminders).
- **Mitigations in place**: closed allowlist, message logging by chat ID
  only, reminders sent only to `REMINDER_CHAT_ID`.

### Slack

- **Allowlist**: `SLACK_ALLOWLIST` (comma-separated Slack user IDs). Same
  closed-by-default model as Telegram.
- **Transport**: Socket Mode — no public webhook URL to defend.
- **What's exposed**: same agent tool surface.

### Web dashboard

- **Bind**: `127.0.0.1:8080` by default (`SIDEKICK_WEB_HOST` /
  `SIDEKICK_WEB_PORT` to override). Loopback-only means even a host on
  the LAN cannot reach it without explicit configuration.
- **Authentication**: shared-secret token issued at first start, required
  on every request.
- **CSRF**: enforced on every state-changing POST.
- **Headers**: `Cache-Control: no-store` on HTML responses,
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.
- **htmx**: loaded from CDN with a pinned SRI integrity hash so a
  compromised CDN cannot inject script.
- **In Docker**: `127.0.0.1` inside the container is _not_ the host's
  loopback. Either set `SIDEKICK_WEB_ENABLED=false`, exec into the
  container, or set `SIDEKICK_WEB_HOST=0.0.0.0` and accept the trade-off.

### MCP subprocess

- Spawned over stdio. No network listener.
- **Scoped environment**: the subprocess receives only the env vars it
  needs (Chronary credentials, DB path). API keys for Anthropic / Slack /
  Telegram are _not_ forwarded.

### LLM (Claude or Ollama)

- Tool calls are forwarded without per-tool user confirmation. The agent
  trusts the LLM's intent. See "Known limitations" below.
- Anthropic API key lives only in the parent process; never logged.
- Ollama runs locally — outbound network egress is constrained to your
  Anthropic endpoint when the Anthropic provider is selected.

## Operational checklist

- [ ] `chmod 600 .env` — the file contains every API key the bot uses.
      (Alternative: push secrets to Azure Key Vault and use
      `scripts/run-with-kv.ps1` so the file never holds tokens — see
      [`secrets-azure-keyvault.md`](secrets-azure-keyvault.md).)
- [ ] `chmod 700 ~/.config/sidekick` — contains the SQLite DB, the
      reminders JSON, the personality config, and the web dashboard token.
- [ ] Dashboard bound to `127.0.0.1` unless you've put it behind a
      reverse proxy with its own auth.
- [ ] Verify htmx SRI hash matches the version pinned in
      `src/sidekick/web/templates/base.html` after any htmx bump.
- [ ] CI: `pip-audit`, `bandit`, and CodeQL all green on `main`.
- [ ] `pre-commit install` locally so bandit catches obvious issues
      before push.
- [ ] Allowlists set: `TELEGRAM_ALLOWLIST` (if using Telegram),
      `SLACK_ALLOWLIST` (if using Slack).
- [ ] Periodically rotate: Telegram bot token, Slack tokens, Anthropic
      key, Chronary API key.

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
- **No end-to-end rate limit on Anthropic spend**. A flood of messages
  from an allowlisted user will translate into a proportionate Anthropic
  bill. Use Anthropic's account-level spend cap as the backstop.
- **Logs are unstructured**. The redaction filter in
  `src/sidekick/logging_setup.py` scrubs common secret patterns
  (`api_key=…`, `token: …`, `password=…`) but it is best-effort —
  arbitrary base64 blobs will not be redacted.

## Reporting vulnerabilities

See [`.github/SECURITY.md`](../.github/SECURITY.md).
