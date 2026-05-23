# Security Policy

## Reporting a vulnerability

**Please do not open public GitHub issues for security vulnerabilities.**

Use GitHub's private vulnerability reporting feature instead:

1. Go to the [Security tab](https://github.com/jaypetez/sidekick/security) of this repository.
2. Click **Report a vulnerability**.
3. Fill in the details.

You can expect an initial response within 7 days. If the issue is confirmed, we will work on a fix and coordinate disclosure with you.

## Scope

This project handles sensitive credentials (API tokens, OAuth tokens for connected services). Reports involving credential leakage, token exfiltration, or unauthorized access paths are especially welcome.

Out of scope:
- Vulnerabilities in upstream dependencies (please report to the upstream maintainer).
- Issues that require physical access to a victim's machine.
- Social engineering of users or maintainers.

## Supported versions

Only the latest release on `main` is supported. There are no backports.
