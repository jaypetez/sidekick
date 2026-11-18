"""Smoke-test the web-only mode without Docker.

Spins up `python -m sidekick.bot` with TELEGRAM_BOT_TOKEN blank, hits every
page in the new web UI, and reports HTTP statuses. Useful for verifying the
new chat route and the optional-Telegram refactor without standing up the
full Docker stack.

Placeholder Chronary env vars are injected — ChronaryProvider __init__ reads
them at construction but won't call Chronary unless you exercise calendar
routes, so the bot starts fine.

The run is isolated from your real install: every state file (DB, reminders,
runtime.json overrides, session secret) lives in a throwaway temp directory,
and the dashboard auth token is forced off. The bot calls ``load_dotenv()``,
which never overrides a variable that is already set — even to "" — so the
values below win over anything in ``.env``.

Run:
    python scripts/smoke_test_web_only.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8080"

ROUTES = [
    ("/", "Dashboard"),
    ("/chat", "Chat"),
    ("/health", "Health"),
    ("/reminders", "Reminders"),
    ("/tasks", "Tasks"),
    ("/settings", "Settings"),
    ("/system", "System"),
]


def _try_get(url: str, *, timeout: float = 15.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, resp.read(2048).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read(2048).decode("utf-8", errors="replace") if hasattr(exc, "read") else ""
        return exc.code, body
    except (TimeoutError, urllib.error.URLError) as exc:
        # Status 0 = no HTTP response at all (e.g. the Chronary stub hanging).
        return 0, str(exc)


def main() -> int:
    # ignore_cleanup_errors: on Windows the bot's MCP grandchild can still hold
    # sidekick.db open for a moment after the bot itself exits.
    with tempfile.TemporaryDirectory(
        prefix="sidekick-smoke-", ignore_cleanup_errors=True
    ) as config_dir:
        return _run(config_dir)


def _run(config_dir: str) -> int:
    env = os.environ.copy()
    env["TELEGRAM_BOT_TOKEN"] = ""
    env["CHRONARY_API_KEY"] = "smoke-test-placeholder"
    env["CHRONARY_AGENT_ID"] = "agt_smoke_placeholder"
    env["CHRONARY_CALENDAR_ID"] = "cal_smoke_placeholder"
    env["LLM_PROVIDER"] = "ollama"  # avoids the Anthropic key check
    env["OLLAMA_BASE_URL"] = "http://localhost:1"  # nothing listens here
    env["SIDEKICK_WEB_ENABLED"] = "true"
    env["SIDEKICK_WEB_HOST"] = "127.0.0.1"
    env["SIDEKICK_WEB_PORT"] = "8080"
    env.pop("REMINDER_CHAT_ID", None)
    env.pop("SLACK_BOT_TOKEN", None)
    env.pop("SLACK_APP_TOKEN", None)
    # Unauthenticated GETs below; a token from .env would turn them into 401s.
    env["SIDEKICK_WEB_AUTH_TOKEN"] = ""
    # Keep the operator's runtime.json (which wins over env) and state files
    # out of it: explicit paths also bypass paths.py's legacy ~/.config fallback.
    env["SIDEKICK_CONFIG_DIR"] = config_dir
    for key, name in (
        ("CONFIG_FILE", "config.json"),
        ("REMINDERS_FILE", "reminders.json"),
        ("SIDEKICK_DB_PATH", "sidekick.db"),
        ("SIDEKICK_RUNTIME_CONFIG", "runtime.json"),
    ):
        env[key] = os.path.join(config_dir, name)

    proc = subprocess.Popen(
        [sys.executable, "-m", "sidekick.bot"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Wait for the dashboard to come up — try /health every 0.5s for 30s.
    ready = False
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{BASE_URL}/health", timeout=1.0):
                ready = True
                break
        except Exception:
            time.sleep(0.5)
        if proc.poll() is not None:
            break

    failures: list[str] = []
    if not ready:
        out = proc.stdout.read().decode("utf-8", errors="replace") if proc.stdout else ""
        print("Bot failed to come up. Recent logs:\n" + out[-3000:])
        proc.kill()
        return 1

    try:
        print(f"{'STATUS':>6}  {'ROUTE':<20}  CHECK")
        print("-" * 60)
        for path, label in ROUTES:
            status, body = _try_get(f"{BASE_URL}{path}")
            check = "PASS" if 200 <= status < 400 else f"FAIL (got {status})"
            if status != 200:
                failures.append(f"{path}: HTTP {status}")
            else:
                # quick sanity check that the navigation is present.
                if "Sidekick" not in body and path != "/health":
                    failures.append(f"{path}: body missing brand")
                    check = "FAIL (no brand)"
                if path == "/chat" and "chat-window" not in body:
                    failures.append("/chat: chat-window not in body")
                    check = "FAIL (no chat-window)"
            print(f"{status:>6}  {path:<20}  {check}  ({label})")

        # Calendar will 502/500/200-with-banner because Chronary key is bogus —
        # we just want to confirm it doesn't crash the process.
        status, body = _try_get(f"{BASE_URL}/events")
        check = "PASS" if status == 200 else f"degraded {status}"
        print(f"{status:>6}  /events                {check}  (Calendar — Chronary stub)")

        # POST /chat is exercised by tests/web/test_chat.py against a mocked
        # agent — no smoke equivalent here since we don't have a live LLM.

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nAll checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
