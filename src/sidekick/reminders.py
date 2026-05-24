"""
Proactive reminder jobs using APScheduler.

Built-in jobs:
  1. morning_summary  — sends today's events each morning
  2. pre_event_check  — checks every 5 min for events about to start

Custom reminders can be added/removed/updated at runtime via chat
and are persisted to ~/.config/sidekick/reminders.json.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from mcp import ClientSession
from telegram import Bot

from .telegram_format import send_safe

if TYPE_CHECKING:
    from .agent import SidekickAgent

logger = logging.getLogger(__name__)

REMINDERS_FILE = os.getenv(
    "REMINDERS_FILE",
    os.path.expanduser("~/.config/sidekick/reminders.json"),
)

BUILTIN_IDS = {"morning_summary", "pre_event_check"}


def setup_scheduler(bot: Bot | None, mcp_session: ClientSession) -> AsyncIOScheduler:
    """Create, configure, and start the scheduler. Returns the running scheduler.

    ``bot`` may be ``None`` in web-only mode (no Telegram). In that case the
    built-in jobs that need a Telegram ``Bot`` to deliver messages are skipped;
    the scheduler still runs for custom reminders that don't need delivery.
    """
    tz = os.getenv("TIMEZONE", "America/Chicago")
    reminder_chat_id = os.getenv("REMINDER_CHAT_ID")
    morning_time = os.getenv("MORNING_REMINDER_TIME", "07:30")
    pre_event_minutes = int(os.getenv("PRE_EVENT_REMINDER_MINUTES", "30"))

    scheduler = AsyncIOScheduler(timezone=tz)

    if bot is None:
        logger.warning(
            "No Telegram bot attached — built-in morning summary and pre-event "
            "reminders are disabled. Custom reminders still run but cannot deliver "
            "messages until a Bot is wired up."
        )
    elif reminder_chat_id:
        hour, minute = morning_time.split(":")
        scheduler.add_job(
            send_morning_summary,
            CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
            args=[bot, mcp_session, reminder_chat_id],
            id="morning_summary",
            name="Morning calendar summary",
            misfire_grace_time=300,
        )
        logger.info("Morning summary scheduled at %s %s", morning_time, tz)

        if pre_event_minutes > 0:
            scheduler.add_job(
                send_pre_event_reminders,
                IntervalTrigger(minutes=5),
                args=[bot, mcp_session, reminder_chat_id, pre_event_minutes],
                id="pre_event_check",
                name="Pre-event reminder check",
            )
            logger.info("Pre-event check every 5 min (%d min warning)", pre_event_minutes)
    else:
        logger.warning(
            "REMINDER_CHAT_ID not set — morning summary and pre-event reminders disabled. "
            "Send /get_id in your group chat to find the chat ID."
        )

    scheduler.start()
    return scheduler


# ------------------------------------------------------------------
# Custom reminder management (runtime, persisted to JSON)
# ------------------------------------------------------------------


def _read_reminders_file() -> list[dict[str, Any]]:
    """Read reminders from JSON file. Returns empty list if not found."""
    path = Path(REMINDERS_FILE)
    if not path.exists():
        return []
    try:
        data: Any = json.loads(path.read_text())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        logger.exception("Failed to read reminders file")
        return []


def _write_reminders_file(reminders: list[dict[str, Any]]) -> None:
    """Write reminders list to JSON file."""
    path = Path(REMINDERS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reminders, indent=2))


def load_custom_reminders(scheduler: AsyncIOScheduler, agent: "SidekickAgent") -> None:
    """Load saved custom reminders and register them with the scheduler."""
    reminders = _read_reminders_file()
    tz = os.getenv("TIMEZONE", "America/Chicago")
    for r in reminders:
        if not r.get("enabled", True):
            continue
        try:
            _register_job(scheduler, agent, r, tz)
            logger.info("Restored custom reminder: %s", r["id"])
        except Exception:
            logger.exception("Failed to restore reminder %s", r.get("id"))


def _register_job(
    scheduler: AsyncIOScheduler,
    agent: "SidekickAgent",
    reminder: dict[str, Any],
    tz: str,
) -> None:
    """Register a single custom reminder as an APScheduler job."""
    schedule = reminder["schedule"]
    trigger: CronTrigger | IntervalTrigger
    if schedule["type"] == "cron":
        trigger = CronTrigger(
            hour=schedule["hour"],
            minute=schedule["minute"],
            day_of_week=schedule.get("day_of_week"),
            timezone=tz,
        )
    elif schedule["type"] == "interval":
        trigger = IntervalTrigger(minutes=schedule["interval_minutes"])
    else:
        raise ValueError(f"Unknown schedule type: {schedule['type']}")

    scheduler.add_job(
        send_custom_reminder,
        trigger,
        args=[agent, reminder["message"]],
        id=reminder["id"],
        name=reminder.get("message", "Custom reminder"),
        replace_existing=True,
        misfire_grace_time=300,
    )


# Internal chat_id used for processing reminders through the agent.
# Keeps reminder tool calls out of real user conversation history.
_REMINDER_CHAT_ID = -1


async def send_custom_reminder(agent: "SidekickAgent", message: str) -> None:
    """Process a reminder through the agent so Claude can call tools.

    The message is sent to Claude as if a user said it, so Claude can call
    tools (e.g. list_events) and return a real answer. The response is sent
    to REMINDER_CHAT_ID. Falls back to sending the raw message if agent
    processing fails.
    """
    chat_id_str = os.getenv("REMINDER_CHAT_ID")
    if not chat_id_str:
        logger.warning("REMINDER_CHAT_ID not set — skipping custom reminder: %s", message)
        return
    chat_id = int(chat_id_str)
    bot = agent.bot
    if bot is None:
        logger.warning("Agent has no bot attached — skipping reminder: %s", message)
        return
    try:
        response = await agent.process_message(_REMINDER_CHAT_ID, message)
        await send_safe(bot, chat_id, response)
    except Exception:
        logger.exception("Agent failed to process reminder, sending raw message")
        try:
            await bot.send_message(chat_id=chat_id, text=f"Reminder: {message}")
        except Exception:
            logger.exception("Failed to send fallback reminder to chat %s", chat_id)
    finally:
        agent.clear_history(_REMINDER_CHAT_ID)


def add_reminder(
    scheduler: AsyncIOScheduler,
    agent: "SidekickAgent",
    message: str,
    hour: int,
    minute: int,
    chat_id: int,
    day_of_week: str | None = None,
    interval_minutes: int | None = None,
) -> dict[str, Any]:
    """Add a new custom reminder. Returns the reminder dict."""
    reminder_id = f"reminder_{int(time.time())}"
    tz = os.getenv("TIMEZONE", "America/Chicago")

    schedule: dict[str, Any]
    if interval_minutes:
        schedule = {"type": "interval", "interval_minutes": interval_minutes}
    else:
        schedule = {"type": "cron", "hour": hour, "minute": minute}
        if day_of_week:
            schedule["day_of_week"] = day_of_week

    reminder: dict[str, Any] = {
        "id": reminder_id,
        "chat_id": chat_id,
        "message": message,
        "schedule": schedule,
        "enabled": True,
    }

    _register_job(scheduler, agent, reminder, tz)

    reminders = _read_reminders_file()
    reminders.append(reminder)
    _write_reminders_file(reminders)

    logger.info("Added custom reminder: %s", reminder_id)
    return reminder


def update_reminder(
    scheduler: AsyncIOScheduler,
    agent: "SidekickAgent",
    reminder_id: str,
    message: str | None = None,
    hour: int | None = None,
    minute: int | None = None,
    day_of_week: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Update an existing reminder (built-in or custom). Returns updated info."""
    tz = os.getenv("TIMEZONE", "America/Chicago")

    # Handle built-in reminders
    if reminder_id in BUILTIN_IDS:
        job = scheduler.get_job(reminder_id)
        if not job:
            return {"error": f"Built-in reminder '{reminder_id}' is not active"}
        if enabled is False:
            scheduler.pause_job(reminder_id)
            return {"status": "paused", "id": reminder_id}
        if enabled is True:
            scheduler.resume_job(reminder_id)
        if hour is not None or minute is not None:
            old_trigger = job.trigger
            new_hour = hour if hour is not None else old_trigger.fields[5].expressions[0].first  # noqa: E501
            new_minute = (
                minute if minute is not None else old_trigger.fields[6].expressions[0].first
            )  # noqa: E501
            scheduler.reschedule_job(
                reminder_id,
                trigger=CronTrigger(hour=new_hour, minute=new_minute, timezone=tz),
            )
        return {"status": "updated", "id": reminder_id}

    # Handle custom reminders
    reminders = _read_reminders_file()
    target = None
    for r in reminders:
        if r["id"] == reminder_id:
            target = r
            break
    if not target:
        return {"error": f"Reminder '{reminder_id}' not found"}

    if message is not None:
        target["message"] = message
    if hour is not None:
        target["schedule"]["hour"] = hour
    if minute is not None:
        target["schedule"]["minute"] = minute
    if day_of_week is not None:
        target["schedule"]["day_of_week"] = day_of_week
    if enabled is not None:
        target["enabled"] = enabled

    _write_reminders_file(reminders)

    # Re-register or remove from scheduler
    try:
        scheduler.remove_job(reminder_id)
    except Exception:
        pass
    if target.get("enabled", True):
        _register_job(scheduler, agent, target, tz)

    logger.info("Updated custom reminder: %s", reminder_id)
    return {"status": "updated", "id": reminder_id}


def remove_reminder(scheduler: AsyncIOScheduler, reminder_id: str) -> dict[str, Any]:
    """Remove a custom reminder. Built-in reminders cannot be removed (disable instead)."""
    if reminder_id in BUILTIN_IDS:
        return {
            "error": f"Cannot remove built-in reminder '{reminder_id}'. "
            "Use update_reminder with enabled=false to disable it."
        }

    reminders = _read_reminders_file()
    found = False
    reminders = [r for r in reminders if r["id"] != reminder_id or not (found := True)]  # noqa: F841
    if not found:
        # Try matching by message substring
        for r in _read_reminders_file():
            if reminder_id.lower() in r.get("message", "").lower():
                reminder_id = r["id"]
                reminders = [x for x in _read_reminders_file() if x["id"] != reminder_id]
                found = True
                break
    if not found:
        return {"error": f"Reminder '{reminder_id}' not found"}

    _write_reminders_file(reminders)
    try:
        scheduler.remove_job(reminder_id)
    except Exception:
        pass

    logger.info("Removed custom reminder: %s", reminder_id)
    return {"status": "removed", "id": reminder_id}


def get_all_reminders(scheduler: AsyncIOScheduler) -> list[dict[str, Any]]:
    """Return info about all active scheduled jobs."""
    jobs = scheduler.get_jobs()
    result: list[dict[str, Any]] = []
    for job in jobs:
        info: dict[str, Any] = {
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "paused": job.next_run_time is None,
        }
        # Extract schedule details from trigger
        if isinstance(job.trigger, CronTrigger):
            info["type"] = "cron"
        elif isinstance(job.trigger, IntervalTrigger):
            info["type"] = "interval"
            info["interval_seconds"] = int(job.trigger.interval.total_seconds())
        result.append(info)

    # Also include disabled custom reminders from the file
    file_reminders = _read_reminders_file()
    active_ids = {j.id for j in jobs}
    for r in file_reminders:
        if r["id"] not in active_ids:
            result.append(
                {
                    "id": r["id"],
                    "name": r.get("message", ""),
                    "next_run": None,
                    "paused": True,
                    "type": r["schedule"]["type"],
                }
            )

    return result


# ------------------------------------------------------------------
# Built-in reminder functions
# ------------------------------------------------------------------


async def send_morning_summary(bot: Bot, mcp_session: ClientSession, chat_id: str) -> None:
    """Fetch today's events and send a morning briefing."""
    tz = os.getenv("TIMEZONE", "America/Chicago")
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    try:
        result = await mcp_session.call_tool(
            "list_events", {"start_date": today, "end_date": today}
        )
        events = _events_from_tool_result(result.content)
    except Exception:
        logger.exception("Failed to fetch events for morning summary")
        return

    if not events:
        text = f"Good morning! No events on the calendar for today ({today})."
    else:
        lines = [f"Good morning! Here's what's on the calendar today ({today}):\n"]
        for e in events:
            start = _format_time(e.get("start", ""))
            lines.append(f"• {e['summary']} — {start}")
        text = "\n".join(lines)

    try:
        await bot.send_message(chat_id=int(chat_id), text=text)
    except Exception:
        logger.exception("Failed to send morning summary to chat %s", chat_id)


# In-memory set to avoid sending duplicate pre-event reminders
_reminded_event_ids: set[str] = set()


async def send_pre_event_reminders(
    bot: Bot, mcp_session: ClientSession, chat_id: str, minutes_before: int
) -> None:
    """Check for events starting within `minutes_before` minutes and notify once."""
    tz_name = os.getenv("TIMEZONE", "America/Chicago")
    now = datetime.now(tz=ZoneInfo(tz_name))
    window_end = now + timedelta(minutes=minutes_before + 5)

    today = now.date().isoformat()
    try:
        result = await mcp_session.call_tool(
            "list_events",
            {"start_date": today, "end_date": today, "max_results": 50},
        )
        events = _events_from_tool_result(result.content)
    except Exception:
        logger.exception("Failed to fetch events for pre-event check")
        return

    for event in events:
        event_id = event.get("id")
        if not event_id or event_id in _reminded_event_ids:
            continue

        start_str = event.get("start", "")
        if not start_str or "T" not in start_str:
            continue  # skip all-day events

        try:
            start_dt = datetime.fromisoformat(start_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=ZoneInfo(tz_name))
        except ValueError:
            continue

        if now <= start_dt <= window_end:
            mins_away = int((start_dt - now).total_seconds() / 60)
            text = f"Reminder: *{event['summary']}* starts in {mins_away} minutes!"
            try:
                await send_safe(bot, int(chat_id), text)
                _reminded_event_ids.add(event_id)
                logger.info("Sent pre-event reminder for event %s", event_id)
            except Exception:
                logger.exception("Failed to send pre-event reminder")

    # Prune event IDs for events that have already passed to keep the set small
    _reminded_event_ids.difference_update(
        eid for eid in list(_reminded_event_ids) if eid not in {e.get("id") for e in events}
    )


def _events_from_tool_result(content: list[Any]) -> list[dict[str, Any]]:
    """Pull the JSON-encoded event list out of an MCP tool-call result.

    MCP content blocks come in several shapes (TextContent, ImageContent, etc.);
    list_events always returns TextContent, but mypy can't narrow without the check.
    """
    if not content:
        return []
    first = content[0]
    text = getattr(first, "text", None)
    if not text:
        return []
    parsed: Any = json.loads(text)
    return parsed if isinstance(parsed, list) else []


def _format_time(iso_str: str) -> str:
    """Format an ISO datetime string to a human-readable time."""
    if not iso_str:
        return "unknown time"
    if "T" not in iso_str:
        return iso_str  # all-day event, return date as-is
    try:
        dt = datetime.fromisoformat(iso_str)
        # %-I (no leading zero) is GNU-only; lstrip handles Windows portability.
        return dt.strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return iso_str
