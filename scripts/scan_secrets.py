"""Check that no secrets have leaked into this git repository.

Three passes, each reporting *where* a problem is, never the secret itself:

1. **Pattern scan** with gitleaks (if it's on PATH): every commit on every
   branch, plus uncommitted changes. Known test fixtures are listed in
   ``.gitleaksignore``.
2. **Known-value scan:** every real-looking value in your env files
   (``.env`` by default) is searched for in tracked files and in the full
   history. This catches leaks that no generic pattern would flag, such as a
   token pasted into a doc. Only the variable *name* is printed.
3. **Tracked-file check:** files that should never be committed (``.env``,
   ``*.secret``, SQLite DBs, compose overrides, key files).

Run it wherever the real ``.env`` lives, e.g. on the server that hosts the bot:

    python scripts/scan_secrets.py                 # uses ./.env
    python scripts/scan_secrets.py --env /path/to/other.env --env ~/tunnel.env

Exit status is 0 when clean, 1 when anything needs a look.
"""

from __future__ import annotations

import argparse
import fnmatch
import shutil
import subprocess  # nosec B404 - runs git/gitleaks with fixed argument lists
import sys
from pathlib import Path

# Values shorter than this are too likely to match by accident ("true", ports).
MIN_VALUE_LEN = 12

# Values that are placeholders or ordinary settings, not secrets.
PLACEHOLDER_HINTS = (
    "your_",
    "_here",
    "replace",
    "example",
    "changeme",
    "placeholder",
    "xxxxxxxx",
)
NON_SECRET_KEYS = {
    "TIMEZONE",
    "LLM_PROVIDER",
    "CLAUDE_MODEL",
    "OLLAMA_MODEL",
    "OLLAMA_BASE_URL",
    "SIDEKICK_WEB_HOST",
    "SIDEKICK_API_URL",
    "SIDEKICK_CONFIG_DIR",
    "SIDEKICK_DB_PATH",
    "SIDEKICK_HOST_CONFIG",
}

FORBIDDEN_TRACKED = (
    ".env",
    ".env.*",
    "*.secret",
    "*.db",
    "*.sqlite",
    "*.pem",
    "*.key",
    "id_rsa*",
    "id_ed25519*",
    "credentials.json",
    "token.json",
    "runtime.json",
    "docker-compose.override.yml",
    "tunnel.env",
)
ALLOWED_TRACKED = {".env.example"}


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607 - fixed git invocation
        ["git", *args], capture_output=True, text=True, encoding="utf-8", errors="replace"
    )


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.removeprefix("export ").strip()
        value = value.strip().strip("'\"")
        if value:
            values[key] = value
    return values


def _looks_secret(key: str, value: str) -> bool:
    if key in NON_SECRET_KEYS or len(value) < MIN_VALUE_LEN:
        return False
    lowered = value.lower()
    return not any(hint in lowered for hint in PLACEHOLDER_HINTS)


def gitleaks_scan() -> int:
    exe = shutil.which("gitleaks")
    if exe is None:
        print("[1/3] gitleaks not installed - pattern scan SKIPPED.")
        print("      Install: https://github.com/gitleaks/gitleaks#installing")
        return 0
    problems = 0
    for label, extra in (("history", []), ("uncommitted", ["--pre-commit"])):
        result = subprocess.run(  # nosec B603 - fixed gitleaks invocation
            [exe, "git", "--redact", "--no-banner", "--log-level", "warn", *extra, "."],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode == 0:
            print(f"[1/3] gitleaks {label}: clean")
        else:
            problems += 1
            print(f"[1/3] gitleaks {label}: FINDINGS (values redacted)")
            print(result.stdout or result.stderr)
    return problems


def known_value_scan(env_files: list[Path]) -> int:
    candidates: dict[str, str] = {}
    for env_file in env_files:
        if not env_file.is_file():
            print(f"[2/3] {env_file}: not found, skipped")
            continue
        for key, value in _parse_env(env_file).items():
            if _looks_secret(key, value):
                candidates[f"{env_file.name}:{key}"] = value
    if not candidates:
        print("[2/3] known-value scan: no real-looking values to check")
        return 0
    problems = 0
    for label, value in sorted(candidates.items()):
        tracked = _git("grep", "-l", "-F", "-e", value).stdout.split()
        commits = _git("log", "--all", "--format=%h", "-S", value).stdout.split()
        if tracked or commits:
            problems += 1
            where = ", ".join(tracked) or "-"
            print(
                f"[2/3] LEAK: value of {label} found - tracked files: {where}; "
                f"commits: {', '.join(commits[:10]) or '-'}"
            )
    if not problems:
        print(f"[2/3] known-value scan: {len(candidates)} values checked, none in git")
    return problems


def tracked_file_scan() -> int:
    problems = 0
    for path in _git("ls-files").stdout.splitlines():
        name = Path(path).name
        if name in ALLOWED_TRACKED:
            continue
        if any(fnmatch.fnmatch(name, pattern) for pattern in FORBIDDEN_TRACKED):
            problems += 1
            print(f"[3/3] TRACKED FILE SHOULD NOT BE COMMITTED: {path}")
    if not problems:
        print("[3/3] tracked-file check: clean")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--env",
        action="append",
        type=Path,
        help="env file whose values must never appear in git (repeatable; default: .env)",
    )
    args = parser.parse_args(argv)
    if _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        print("Run this from inside the git repository.", file=sys.stderr)
        return 2
    problems = gitleaks_scan()
    problems += known_value_scan(args.env or [Path(".env")])
    problems += tracked_file_scan()
    print("RESULT:", "clean" if problems == 0 else f"{problems} problem(s) - see above")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
