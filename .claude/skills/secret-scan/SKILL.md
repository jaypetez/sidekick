---
name: secret-scan
description: Scan the Sidekick repo (full git history, uncommitted changes, tracked files) for leaked secrets - API keys, bot tokens, tunnel tokens, webhook secrets - and check that the real values in .env never reached git. Use when the user asks to check for leaked secrets/credentials, before a release or making something public, or after editing docs with real deployment details.
---

# Secret scan

Goal: prove that nothing secret is in git (any branch, any commit) and that nothing
will be once the working tree is committed. Report *locations* only; never print a
secret value into the conversation, a PR, an issue or a commit.

## 1. Run the scanner where the real `.env` lives

`scripts/scan_secrets.py` does three passes: gitleaks over all history plus
uncommitted changes (fixtures allowed by `.gitleaksignore`), a search for every
real-looking value from the given env files across history and tracked files
(prints the variable name only), and a check for files that must never be tracked.

```bash
python scripts/scan_secrets.py                       # this checkout, ./.env
```

The developer PC usually only holds placeholders, so also run it on the host that
runs the bot, against its real env files (the bot's `.env` plus anything else that
holds secrets, such as a cloudflared `TUNNEL_TOKEN` env file). Substitute the host's
ssh alias and paths:

```bash
scp scripts/scan_secrets.py <host>:/tmp/ && ssh <host> 'cd <repo> && \
  python3 /tmp/scan_secrets.py --env .env --env <tunnel.env>; rm /tmp/scan_secrets.py'
```

If gitleaks is missing the pattern pass is skipped. Install it
(`go install github.com/zricethezav/gitleaks/v8@latest`, or a release binary) on at least
the machine you scan from.

## 2. GitHub-side checks

```bash
gh api repos/{owner}/{repo} --jq .security_and_analysis        # secret scanning + push protection on?
gh api repos/{owner}/{repo}/secret-scanning/alerts --jq 'length' # open alerts
```

Both `secret_scanning` and `secret_scanning_push_protection` should be `enabled`.

## 3. Things the scanner can't see

- **Built images:** `.dockerignore` must keep excluding `.env`, `data`, `.git`.
  To spot-check an image:
  `docker run --rm --entrypoint sh sidekick:latest -c 'find / -name .env -not -path "/proc/*" 2>/dev/null'`
- **Deployment identifiers** that aren't secrets but are private (chat IDs, user IDs,
  LAN IPs, tunnel IDs, private hostnames): docs and examples must use generic
  placeholders (`hooks.example.com`, `12345678`). Add such values to a local,
  untracked env file and pass it with `--env` so the known-value pass covers them.
  Never write the real values into this skill or any tracked file.

## 4. Triage findings

- **Test fixture or obviously fake value:** confirm by reading the line (mask it
  when quoting), then add its fingerprint from gitleaks' JSON report
  (`gitleaks git --redact -f json -r <scratch>/r.json .`) to `.gitleaksignore`
  with a comment.
- **Real secret in an unpushed commit:** remove it and rewrite the local commit
  before pushing.
- **Real secret already pushed:** rotate it first (BotFather `/revoke`, Anthropic
  console, Chronary console, `sidekick-webhook delete` + `register`, Cloudflare
  tunnel token refresh). Rewriting history doesn't help once it's public, because
  forks, caches and clones may already have it. Tell the user plainly what leaked,
  where, and since when.

## 5. Report

Give per-pass results (clean / N findings with file:line and commit), the GitHub
settings, and any rotation the user must do. Values stay masked.
