"""Capture the README screenshots of the web dashboard.

By default this needs **no keys, no Chronary account and no LLM**: it builds
the dashboard in-process with :func:`sidekick.web.make_app`, backed by an
in-memory task store, a canned calendar and a stub agent seeded with
obviously-fictional demo data, serves it on a free loopback port, and drives
headless Chromium over it. Your real config dir and ``.env`` are never read —
``SIDEKICK_CONFIG_DIR`` points at a throwaway temp directory and every
setting Sidekick knows about is cleared from the environment first.

Requires Playwright + Chromium (deliberately not a project dependency):

    pip install playwright
    playwright install chromium

Then:

    python scripts/capture_screenshots.py            # demo data (README images)
    python scripts/capture_screenshots.py --url http://127.0.0.1:8080
    python scripts/capture_screenshots.py --url ... --token "$SIDEKICK_WEB_AUTH_TOKEN"

With ``--url`` it photographs a running instance instead — real data, so
don't commit those. ``--token`` signs in through the ``/login`` form; a
bearer header is never sent, because the browser would also attach it to
the htmx request that goes to unpkg.com.

Output: docs/screenshots/{dashboard,chat,tasks,calendar,system}.png
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sqlite3
import subprocess  # nosec B404 - fixed git argv, no shell
import sys
import threading
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = REPO_ROOT / "docs" / "screenshots"
VIEWPORT = {"width": 1280, "height": 800}

# (path, filename, full_page)
PAGES = [
    ("/", "dashboard.png", False),
    ("/chat", "chat.png", False),
    ("/tasks/Groceries", "tasks.png", False),
    ("/events", "calendar.png", False),
    ("/system", "system.png", False),
]

DEMO_TZ = "America/Los_Angeles"


# --------------------------------------------------------------------------
# Demo backend
# --------------------------------------------------------------------------


# What a Docker install shows. Nothing here exists on the capturing machine,
# and nothing is written to it (the session secret comes from the env), so
# the demo can neither read the operator's real state files nor print their
# home-directory paths into a committed image.
DEMO_CONFIG_DIR = "/home/app/.config/sidekick"


def _isolate_environment() -> None:
    """Forget the operator's settings and install demo ones.

    Must run before anything under ``sidekick`` reads the environment —
    several modules resolve state-file paths at import time. Every state file
    gets an explicit path so ``paths.py``'s legacy ``~/.config/sidekick``
    fallback can't pick up the operator's real files.
    """
    from sidekick import config_catalog

    for key in [spec.key for spec in config_catalog.CATALOG]:
        os.environ.pop(key, None)

    # Secrets get obvious dummies: the System page only ever shows "set".
    os.environ.update(
        {
            "SIDEKICK_CONFIG_DIR": DEMO_CONFIG_DIR,
            "SIDEKICK_DB_PATH": f"{DEMO_CONFIG_DIR}/sidekick.db",
            "REMINDERS_FILE": f"{DEMO_CONFIG_DIR}/reminders.json",
            "CONFIG_FILE": f"{DEMO_CONFIG_DIR}/config.json",
            "SIDEKICK_RUNTIME_CONFIG": f"{DEMO_CONFIG_DIR}/runtime.json",
            "SIDEKICK_WEB_SESSION_SECRET": "screenshot-demo-session-secret-not-for-real-use",
            "TELEGRAM_BOT_TOKEN": "demo",
            "TELEGRAM_ALLOWED_USER_IDS": "1111111111",
            "REMINDER_CHAT_ID": "-1000000000000",
            "LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "demo",
            "CLAUDE_MODEL": "claude-haiku-4-5-20251001",
            "CHRONARY_API_KEY": "demo",
            "CHRONARY_AGENT_ID": "agt_demo",
            "CHRONARY_CALENDAR_ID": "cal_demo",
            "TIMEZONE": DEMO_TZ,
            "MORNING_REMINDER_TIME": "07:30",
            "PRE_EVENT_REMINDER_MINUTES": "30",
            "SIDEKICK_WEB_HOST": "127.0.0.1",
        }
    )


class _AnthropicClient:
    """Stand-in LLM. Named like the real class so the System page labels it."""

    model = "claude-haiku-4-5-20251001"


_AnthropicClient.__name__ = "AnthropicClient"


class _DemoJob:
    def __init__(self, job_id: str, name: str, trigger: str, next_run: datetime) -> None:
        self.id = job_id
        self.name = name
        self.trigger = trigger
        self.next_run_time = next_run
        self.kwargs: dict[str, Any] = {}
        self.args: tuple[Any, ...] = ()


class _DemoScheduler:
    running = True

    def __init__(self, tz: ZoneInfo) -> None:
        now = datetime.now(tz)
        tomorrow_730 = (now + timedelta(days=1)).replace(hour=7, minute=30, second=0)
        sunday = now + timedelta(days=(6 - now.weekday()) % 7 or 7)
        self._jobs = [
            _DemoJob(
                "morning_summary", "Morning summary", "cron[hour='7', minute='30']", tomorrow_730
            ),
            _DemoJob(
                "pre_event_check",
                "Pre-event check",
                "interval[0:05:00]",
                now + timedelta(minutes=4),
            ),
            _DemoJob(
                "reminder_demo",
                "Prep lunches for the week",
                "cron[day_of_week='sun', hour='17']",
                sunday.replace(hour=17, minute=0, second=0),
            ),
        ]

    def get_jobs(self) -> list[_DemoJob]:
        return list(self._jobs)

    def get_job(self, job_id: str) -> _DemoJob | None:
        return next((j for j in self._jobs if j.id == job_id), None)


class _DemoMcpTask:
    def done(self) -> bool:
        return False


CHAT_EXCHANGE = [
    (
        "add milk, eggs, and tortillas to costco",
        "Added to Costco: milk, eggs, tortillas.",
    ),
    (
        "move tuesday's dentist to thursday 2pm",
        "Done — Dentist is now Thursday at 2:00 PM. Want a reminder the morning of?",
    ),
    (
        "anything on my calendar tomorrow?",
        "Two things, both before noon:\n• 9:00 AM — Team standup\n• 11:30 AM — Lunch with Sam",
    ),
]


class _DemoAgent:
    personality = "snarky"

    def __init__(self) -> None:
        self.llm = _AnthropicClient()
        self.tools = [{"name": f"tool_{i}"} for i in range(16)]
        history: list[dict[str, Any]] = []
        for user, assistant in CHAT_EXCHANGE:
            history.append({"role": "user", "content": user})
            history.append({"role": "assistant", "content": [{"type": "text", "text": assistant}]})
        self.conversation_history: dict[Any, list[dict[str, Any]]] = {"web:local": history}

    async def process_message(self, chat_id: Any, text: str) -> str:
        return "This is a screenshot demo — nothing is connected."

    def clear_history(self, chat_id: Any) -> None:
        self.conversation_history.pop(chat_id, None)

    def set_personality(self, style: str) -> str:
        self.personality = style
        return style


class _DemoCalendar:
    """Implements just enough of ``CalendarProvider`` for the /events page."""

    def __init__(self, tz: ZoneInfo) -> None:
        today = date.today()

        def at(days: int, hour: int, minute: int = 0) -> datetime:
            d = today + timedelta(days=days)
            return datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz)

        rows = [
            (1, 9, 0, 30, "Team standup", "Video call"),
            (1, 11, 30, 60, "Lunch with Sam", "Corner Café"),
            (2, 16, 30, 90, "Soccer practice", "Riverside Park"),
            (3, 14, 0, 60, "Dentist", "Main St Dental"),
            (5, 10, 0, 120, "Farmers market", "Town square"),
            (8, 18, 30, 120, "Book club", "Library, room B"),
        ]
        self._events = [
            {
                "id": f"evt_demo_{n}",
                "summary": summary,
                "start": at(days, h, m).isoformat(),
                "end": (at(days, h, m) + timedelta(minutes=dur)).isoformat(),
                "location": location,
            }
            for n, (days, h, m, dur, summary, location) in enumerate(rows, start=1)
        ]

    def list_events(self, args: dict[str, Any]) -> list[dict[str, Any]]:
        return list(self._events)

    def create_event(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"error": "demo calendar is read-only"}

    update_event = create_event
    delete_event = create_event


def _demo_task_store() -> Any:
    from sidekick.storage.sqlite_tasks import SQLiteTaskStore

    conn = sqlite3.connect(":memory:", check_same_thread=False)
    store = SQLiteTaskStore(conn=conn)
    store.add_tasks(
        {
            "list_name": "Groceries",
            "items": ["Oat milk", "Eggs", "Tortillas", "Avocados", "Coffee beans", "Basil"],
        }
    )
    store.complete_task({"list_name": "Groceries", "task_title": "Coffee beans"})
    store.add_tasks({"list_name": "Costco", "items": ["Paper towels", "Olive oil"]})
    store.add_tasks(
        {"list_name": "Weekend", "items": ["Fix the bike tire", "Return library books"]}
    )
    return store


def _release_version(fallback: str) -> str:
    """The newest ``vX.Y.Z`` tag (without the ``v``), else ``fallback``."""
    try:
        out = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return fallback
    return out.removeprefix("v") or fallback


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _start_demo_server() -> tuple[str, threading.Event]:
    """Serve the demo app on a background thread; return (base_url, stop)."""
    from aiohttp import web

    from sidekick.services import system
    from sidekick.web import make_app

    # ``paths`` returns pathlib-joined strings, which use backslashes when this
    # runs on Windows; show the POSIX paths a real (Docker) install has.
    real_paths = system._paths
    system._paths = lambda: {k: v.replace("\\", "/") for k, v in real_paths().items()}  # type: ignore[assignment]
    # A dev checkout reports e.g. "0.1.18.dev15+g77d3e3f"; show the release.
    system.__version__ = _release_version(system.__version__)  # type: ignore[attr-defined]

    tz = ZoneInfo(DEMO_TZ)
    bot_data: dict[str, Any] = {
        "scheduler": _DemoScheduler(tz),
        "agent": _DemoAgent(),
        "mcp_task": _DemoMcpTask(),
        "telegram_enabled": True,
        "started_at": datetime.now(UTC) - timedelta(days=3, hours=4, minutes=12),
    }
    app = make_app(
        bot_data=bot_data,
        task_store=_demo_task_store(),
        calendar_provider=_DemoCalendar(tz),  # type: ignore[arg-type]
    )
    port = _free_port()
    ready = threading.Event()
    stop = threading.Event()

    def run() -> None:
        loop = asyncio.new_event_loop()
        runner = web.AppRunner(app)
        loop.run_until_complete(runner.setup())
        loop.run_until_complete(web.TCPSite(runner, "127.0.0.1", port).start())
        ready.set()
        while not stop.is_set():
            loop.run_until_complete(asyncio.sleep(0.1))
        loop.run_until_complete(runner.cleanup())
        loop.close()

    threading.Thread(target=run, daemon=True).start()
    if not ready.wait(timeout=15):
        raise RuntimeError("demo server did not start")
    return f"http://127.0.0.1:{port}", stop


# --------------------------------------------------------------------------
# Capture
# --------------------------------------------------------------------------


def _capture(base_url: str, token: str | None, out_dir: Path) -> None:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
        page = context.new_page()
        if token:
            page.goto(f"{base_url}/login")
            page.fill("input[name=token]", token)
            page.click("button[type=submit]")
            page.wait_for_load_state("networkidle")
        for path, filename, full_page in PAGES:
            page.goto(f"{base_url}{path}")
            page.wait_for_load_state("networkidle")
            if "/login" in page.url:
                raise RuntimeError(
                    f"{path} redirected to /login — pass --token for an instance with auth on"
                )
            out = out_dir / filename
            page.screenshot(path=str(out), full_page=full_page)
            print(f"wrote {out}")
        browser.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--url", help="photograph a running instance instead of the demo")
    parser.add_argument("--token", help="SIDEKICK_WEB_AUTH_TOKEN, used via the /login form")
    parser.add_argument("--out", type=Path, default=OUTPUT_DIR, help="output directory")
    args = parser.parse_args(argv)

    try:
        import playwright  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "Playwright not installed. Run:\n  pip install playwright\n  playwright install chromium\n"
        )
        return 1

    if args.url:
        _capture(args.url.rstrip("/"), args.token, args.out)
        return 0

    _isolate_environment()
    base_url, stop = _start_demo_server()
    try:
        _capture(base_url, None, args.out)
    finally:
        stop.set()
    return 0


if __name__ == "__main__":
    sys.exit(main())
