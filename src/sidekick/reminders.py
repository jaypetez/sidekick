"""
Proactive reminder jobs using APScheduler.

Built-in jobs:
  1. morning_summary  — sends today's events each morning
  2. pre_event_check  — checks every 5 min for events about to start

Custom reminders can be added/removed/updated at runtime via chat
and are persisted to ~/.config/sidekick/reminders.json.
"""

import asyncio
import contextlib
import copy
import json
import logging
import os
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from mcp import ClientSession
from telegram import Bot

from . import runtime_config
from .telegram_format import escape_v2, send_markdown_v2, send_safe

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
    tz = runtime_config.timezone_name()
    reminder_chat_id = os.getenv("REMINDER_CHAT_ID")
    morning_time = _morning_time()
    pre_event_minutes = _pre_event_minutes()

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
            # Registered even in webhook mode (paused) so switching
            # PRE_EVENT_SOURCE back to "poll" in settings applies live.
            polling = runtime_config.pre_event_source() == "poll"
            scheduler.add_job(
                send_pre_event_reminders,
                IntervalTrigger(minutes=5),
                args=[bot, mcp_session, reminder_chat_id, pre_event_minutes],
                id="pre_event_check",
                name="Pre-event reminder check",
                **({} if polling else {"next_run_time": None}),
            )
            if polling:
                logger.info("Pre-event check every 5 min (%d min warning)", pre_event_minutes)
            else:
                logger.info(
                    "Pre-event reminders come from Chronary webhooks "
                    "(PRE_EVENT_SOURCE=webhook); polling job is paused"
                )
    else:
        logger.warning(
            "REMINDER_CHAT_ID not set — morning summary and pre-event reminders disabled. "
            "Send /get_id in your group chat to find the chat ID."
        )

    scheduler.start()
    return scheduler


def _morning_time() -> str:
    return runtime_config.get("MORNING_REMINDER_TIME") or "07:30"


def _pre_event_minutes() -> int:
    minutes = runtime_config.get_int("PRE_EVENT_REMINDER_MINUTES", 30)
    return 30 if minutes is None else minutes


def apply_builtin_settings(scheduler: AsyncIOScheduler) -> list[str]:
    """Push the current runtime settings into the live built-in jobs.

    Called after the settings page saves ``MORNING_REMINDER_TIME`` or
    ``PRE_EVENT_REMINDER_MINUTES`` so the change applies without a restart.
    Returns the keys that could *not* be applied live (the job was never
    registered at startup, e.g. minutes was 0 or REMINDER_CHAT_ID unset), so
    the caller can tell the user a restart is needed.
    """
    pending: list[str] = []
    tz = runtime_config.timezone_name()

    if scheduler.get_job("morning_summary") is not None:
        hour, minute = _morning_time().split(":")
        scheduler.reschedule_job(
            "morning_summary",
            trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=tz),
        )

    minutes = _pre_event_minutes()
    polling = minutes > 0 and runtime_config.pre_event_source() == "poll"
    job = scheduler.get_job("pre_event_check")
    if job is None:
        if polling:
            pending.append("PRE_EVENT_REMINDER_MINUTES")
    elif not polling:
        # Lead time 0, or Chronary webhooks deliver pre-event reminders now.
        scheduler.pause_job("pre_event_check")
    else:
        bot, mcp_session, chat_id = job.args[:3]
        scheduler.modify_job("pre_event_check", args=[bot, mcp_session, chat_id, minutes])
        if job.next_run_time is None:
            scheduler.resume_job("pre_event_check")
    return pending


# ------------------------------------------------------------------
# Custom reminder management (runtime, persisted to JSON)
# ------------------------------------------------------------------


class RemindersFileError(RuntimeError):
    """The reminders file exists but could not be read (permissions, I/O).

    Raised instead of returning ``[]`` so a read-modify-write never
    overwrites reminders it failed to load.
    """


# Serializes read-modify-write of reminders.json. Chat tool calls run on the
# event loop while the web dashboard calls in from executor threads, so
# without this two concurrent edits silently lose one of them.
_file_lock = threading.RLock()


def _read_reminders_file() -> list[dict[str, Any]]:
    """Read reminders from the JSON file. Returns ``[]`` if it doesn't exist.

    A file that exists but doesn't parse is moved aside to
    ``reminders.json.corrupt-<ts>`` (and logged) rather than treated as
    empty-and-overwritable, so a crash mid-write can never silently erase
    every saved reminder. Unreadable files raise :class:`RemindersFileError`.
    """
    path = Path(REMINDERS_FILE)
    with _file_lock:
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise RemindersFileError(f"cannot read {path}: {exc}") from exc
        try:
            data: Any = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = None
        if isinstance(data, list):
            return data
        quarantine = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
        try:
            path.replace(quarantine)
        except OSError:
            logger.exception("Could not move aside corrupt reminders file %s", path)
            raise RemindersFileError(f"{path} is corrupt and could not be moved aside") from None
        logger.error("Reminders file %s was corrupt; moved it to %s", path, quarantine)
        return []


def _write_reminders_file(reminders: list[dict[str, Any]]) -> None:
    """Atomically write the reminders list, owner-only (0600) from creation.

    Writes a temp file in the same directory and ``os.replace``s it over the
    real one, so readers see either the old or the new list — never a
    truncated file.
    """
    path = Path(REMINDERS_FILE)
    with _file_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".reminders-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(json.dumps(reminders, indent=2))
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                logger.debug("Could not chmod %s — non-POSIX filesystem?", tmp)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


_REMINDER_REQUIRED_KEYS = {"id", "message", "schedule"}
_REMINDER_ALLOWED_KEYS = _REMINDER_REQUIRED_KEYS | {"chat_id", "enabled"}


def _validate_reminder(payload: Any) -> dict[str, Any] | None:
    """Return a sanitized reminder dict, or None if the payload is invalid.

    Drops unknown top-level keys so we don't silently round-trip attacker
    data through the file. Logs a warning describing the rejection rather
    than raising — load_custom_reminders is called at startup and a single
    bad entry must not bring the bot down.
    """
    if not isinstance(payload, dict):
        logger.warning("Reminder entry is not an object: %r", payload)
        return None
    missing = _REMINDER_REQUIRED_KEYS - payload.keys()
    if missing:
        logger.warning("Reminder %r missing required keys: %s", payload.get("id"), sorted(missing))
        return None
    if not isinstance(payload["id"], str) or not payload["id"]:
        logger.warning("Reminder has non-string or empty id: %r", payload.get("id"))
        return None
    if not isinstance(payload["message"], str):
        logger.warning("Reminder %s has non-string message", payload["id"])
        return None
    schedule = payload["schedule"]
    if not isinstance(schedule, dict) or "type" not in schedule:
        logger.warning("Reminder %s has invalid schedule", payload["id"])
        return None
    try:
        _build_trigger(schedule, "UTC")
    except (ValueError, TypeError, KeyError) as exc:
        logger.warning("Reminder %s has invalid schedule: %s", payload["id"], exc)
        return None
    unknown = payload.keys() - _REMINDER_ALLOWED_KEYS
    if unknown:
        logger.warning("Reminder %s has unknown keys (dropped): %s", payload["id"], sorted(unknown))
    return {k: payload[k] for k in payload.keys() & _REMINDER_ALLOWED_KEYS}


def load_custom_reminders(scheduler: AsyncIOScheduler, agent: "SidekickAgent") -> None:
    """Load saved custom reminders and register them with the scheduler."""
    try:
        reminders = _read_reminders_file()
    except RemindersFileError:
        logger.exception("Custom reminders not loaded")
        return
    tz = runtime_config.timezone_name()
    for raw in reminders:
        r = _validate_reminder(raw)
        if r is None:
            continue
        if not r.get("enabled", True):
            continue
        try:
            _register_job(scheduler, agent, r, tz)
            logger.info("Restored custom reminder: %s", r["id"])
        except Exception:
            logger.exception("Failed to restore reminder %s", r.get("id"))


def _build_trigger(schedule: dict[str, Any], tz: str) -> CronTrigger | IntervalTrigger:
    """Build (and thereby validate) the trigger for a schedule dict.

    Raises ``ValueError`` for anything out of range — hour 0-23, minute
    0-59, a day_of_week APScheduler can't parse, interval < 1 minute — so
    callers can validate *before* touching the file or the scheduler.
    """
    stype = schedule.get("type")
    if stype == "cron":
        hour, minute = schedule.get("hour"), schedule.get("minute")
        if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
            raise ValueError(f"hour must be an integer 0-23, got {hour!r}")
        if not isinstance(minute, int) or isinstance(minute, bool) or not 0 <= minute <= 59:
            raise ValueError(f"minute must be an integer 0-59, got {minute!r}")
        return CronTrigger(
            hour=hour,
            minute=minute,
            day_of_week=schedule.get("day_of_week"),
            timezone=tz,
        )
    if stype == "interval":
        minutes = schedule.get("interval_minutes")
        if not isinstance(minutes, int) or isinstance(minutes, bool) or minutes < 1:
            raise ValueError(f"interval_minutes must be a positive integer, got {minutes!r}")
        return IntervalTrigger(minutes=minutes)
    raise ValueError(f"Unknown schedule type: {stype!r}")


def _register_job(
    scheduler: AsyncIOScheduler,
    agent: "SidekickAgent",
    reminder: dict[str, Any],
    tz: str,
) -> None:
    """Register (or replace) a single custom reminder as an APScheduler job."""
    scheduler.add_job(
        send_custom_reminder,
        _build_trigger(reminder["schedule"], tz),
        args=[agent, reminder["message"]],
        id=reminder["id"],
        name=reminder.get("message", "Custom reminder"),
        replace_existing=True,
        misfire_grace_time=300,
    )


# Internal chat_id used for processing reminders through the agent.
# Keeps reminder tool calls out of real user conversation history. Using a
# non-numeric sentinel prevents collisions with real Telegram chat ids
# (Telegram ids are always ints, often negative for groups).
_REMINDER_CHAT_ID: str = "__sidekick_reminder__"


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
    # A fresh history key per run: two reminders firing at the same minute
    # must not share (and interleave) one conversation.
    run_chat_id = f"{_REMINDER_CHAT_ID}:{uuid.uuid4().hex}"
    try:
        response = await agent.process_message(run_chat_id, message)
        # Same escaping as normal chat replies: legacy "Markdown" rejected
        # many free-form LLM replies, dropping the answer for the bare
        # fallback text.
        await send_safe(bot, chat_id, response)
    except Exception:
        logger.exception("Agent failed to process reminder, sending raw message")
        try:
            await bot.send_message(chat_id=chat_id, text=f"Reminder: {message}")
        except Exception:
            logger.exception("Failed to send fallback reminder to chat %s", chat_id)
    finally:
        agent.clear_history(run_chat_id)


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
    """Add a new custom reminder. Returns the reminder dict.

    Raises ``ValueError`` (before anything is saved) for an invalid schedule.
    """
    # uuid, not int(time.time()): two reminders created in the same second
    # ("remind me at 8 and at 5") used to share an id, so the second job
    # replaced the first in the scheduler.
    reminder_id = f"reminder_{uuid.uuid4().hex[:12]}"
    tz = runtime_config.timezone_name()

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

    with _file_lock:
        _register_job(scheduler, agent, reminder, tz)  # validates first
        try:
            reminders = _read_reminders_file()
            reminders.append(reminder)
            _write_reminders_file(reminders)
        except Exception:
            # Don't leave a scheduled job that won't survive a restart.
            with contextlib.suppress(Exception):
                scheduler.remove_job(reminder_id)
            raise

    logger.info("Added custom reminder: %s", reminder_id)
    return reminder


def _update_builtin(
    scheduler: AsyncIOScheduler,
    reminder_id: str,
    hour: int | None,
    minute: int | None,
    enabled: bool | None,
    tz: str,
) -> dict[str, Any]:
    job = scheduler.get_job(reminder_id)
    if not job:
        return {"error": f"Built-in reminder '{reminder_id}' is not active"}

    new_trigger: CronTrigger | None = None
    if hour is not None or minute is not None:
        if not isinstance(job.trigger, CronTrigger):
            raise ValueError(
                f"'{reminder_id}' runs on an interval, not at a time of day; "
                "change PRE_EVENT_REMINDER_MINUTES in settings instead"
            )
        fields = {f.name: f for f in job.trigger.fields}
        new_hour = hour if hour is not None else int(str(fields["hour"]))
        new_minute = minute if minute is not None else int(str(fields["minute"]))
        trigger = _build_trigger({"type": "cron", "hour": new_hour, "minute": new_minute}, tz)
        assert isinstance(trigger, CronTrigger)
        new_trigger = trigger

    if enabled is False:
        scheduler.pause_job(reminder_id)
        return {"status": "paused", "id": reminder_id}
    if new_trigger is not None:
        scheduler.reschedule_job(reminder_id, trigger=new_trigger)
    if enabled is True:
        scheduler.resume_job(reminder_id)
    return {"status": "updated", "id": reminder_id}


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
    """Update an existing reminder (built-in or custom).

    Returns ``{"status": ...}`` or ``{"error": ...}`` when the id is unknown.
    Raises ``ValueError`` for an invalid new schedule — validated *before*
    the file or the live job is touched, so a bad edit can no longer delete
    the reminder.
    """
    tz = runtime_config.timezone_name()

    if reminder_id in BUILTIN_IDS:
        return _update_builtin(scheduler, reminder_id, hour, minute, enabled, tz)

    with _file_lock:
        reminders = _read_reminders_file()
        index = next(
            (
                i
                for i, r in enumerate(reminders)
                if isinstance(r, dict) and r.get("id") == reminder_id
            ),
            None,
        )
        if index is None:
            return {"error": f"Reminder '{reminder_id}' not found"}

        updated = copy.deepcopy(reminders[index])
        if message is not None:
            updated["message"] = message
        schedule = updated.setdefault("schedule", {})
        if hour is not None:
            schedule["hour"] = hour
        if minute is not None:
            schedule["minute"] = minute
        if day_of_week is not None:
            schedule["day_of_week"] = day_of_week
        if enabled is not None:
            updated["enabled"] = enabled

        _build_trigger(schedule, tz)  # raises ValueError before any change

        reminders[index] = updated
        _write_reminders_file(reminders)

        if updated.get("enabled", True):
            _register_job(scheduler, agent, updated, tz)  # replace_existing
        elif scheduler.get_job(reminder_id) is not None:
            scheduler.remove_job(reminder_id)

    logger.info("Updated custom reminder: %s", reminder_id)
    return {"status": "updated", "id": reminder_id}


def remove_reminder(scheduler: AsyncIOScheduler, reminder_id: str) -> dict[str, Any]:
    """Remove a custom reminder by exact id.

    Built-in reminders cannot be removed (disable instead). There is
    deliberately no fuzzy fallback: matching "a" against message text used
    to delete an arbitrary reminder.
    """
    if reminder_id in BUILTIN_IDS:
        return {
            "error": f"Cannot remove built-in reminder '{reminder_id}'. "
            "Use update_reminder with enabled=false to disable it."
        }

    with _file_lock:
        reminders = _read_reminders_file()
        kept = [r for r in reminders if not (isinstance(r, dict) and r.get("id") == reminder_id)]
        if len(kept) == len(reminders):
            return {"error": f"Reminder '{reminder_id}' not found"}
        _write_reminders_file(kept)
        if scheduler.get_job(reminder_id) is not None:
            scheduler.remove_job(reminder_id)

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
    try:
        file_reminders = _read_reminders_file()
    except RemindersFileError:
        logger.exception("Could not list disabled reminders")
        file_reminders = []
    active_ids = {j.id for j in jobs}
    for raw in file_reminders:
        r = _validate_reminder(raw)
        if r is not None and r["id"] not in active_ids:
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


# A hung Chronary call must not wedge the job: APScheduler won't start the
# next 5-minute check while the previous run is still in flight.
MCP_CALL_TIMEOUT_SECONDS = 30


async def _list_events_today(
    mcp_session: ClientSession, today: str, **extra: Any
) -> list[dict[str, Any]]:
    result = await asyncio.wait_for(
        mcp_session.call_tool("list_events", {"start_date": today, "end_date": today, **extra}),
        MCP_CALL_TIMEOUT_SECONDS,
    )
    return _events_from_tool_result(result.content)


async def send_morning_summary(bot: Bot, mcp_session: ClientSession, chat_id: str) -> None:
    """Fetch today's events and send a morning briefing."""
    tz = runtime_config.timezone_name()
    today = datetime.now(ZoneInfo(tz)).date().isoformat()
    try:
        events = await _list_events_today(mcp_session, today)
    except Exception:
        logger.exception("Failed to fetch events for morning summary")
        return

    if not events:
        text = f"Good morning! No events on the calendar for today ({today})."
    else:
        lines = [f"Good morning! Here's what's on the calendar today ({today}):\n"]
        for e in events:
            start = _format_time(e.get("start", ""))
            lines.append(f"• {e.get('summary') or '(untitled)'} — {start}")
        text = "\n".join(lines)

    try:
        await bot.send_message(chat_id=int(chat_id), text=text)
    except Exception:
        logger.exception("Failed to send morning summary to chat %s", chat_id)


# Pre-event reminders already sent: "<event id>@<start>" → start time. Keyed
# on the start too, so an event moved to a new time gets a fresh reminder.
# Entries are dropped only once the event has started — never because a
# fetch failed or returned a truncated list (which used to empty the set and
# re-send every reminder still inside the window).
_reminded_events: dict[str, datetime] = {}


async def send_pre_event_reminders(
    bot: Bot, mcp_session: ClientSession, chat_id: str, minutes_before: int
) -> None:
    """Check for events starting within `minutes_before` minutes and notify once."""
    tz_name = runtime_config.timezone_name()
    now = datetime.now(tz=ZoneInfo(tz_name))
    window_end = now + timedelta(minutes=minutes_before + 5)

    for key in [k for k, start in _reminded_events.items() if start < now]:
        del _reminded_events[key]

    try:
        events = await _list_events_today(mcp_session, now.date().isoformat(), max_results=50)
    except Exception:
        logger.exception("Failed to fetch events for pre-event check")
        return

    for event in events:
        event_id = event.get("id")
        start_str = event.get("start", "")
        if not event_id or not start_str or "T" not in start_str:
            continue  # no id, or an all-day event

        try:
            start_dt = datetime.fromisoformat(start_str)
            if start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=ZoneInfo(tz_name))
        except ValueError:
            continue

        key = f"{event_id}@{start_dt.isoformat()}"
        if key in _reminded_events or not now <= start_dt <= window_end:
            continue

        mins_away = int((start_dt - now).total_seconds() / 60)
        title = str(event.get("summary") or "(untitled)")
        try:
            # Escape the title: a "_" or "*" in it used to make Telegram
            # reject the message, so the reminder was never delivered and
            # was retried (and failed) every 5 minutes.
            await send_markdown_v2(
                bot,
                int(chat_id),
                f"Reminder: *{escape_v2(title)}* starts in {mins_away} minutes\\!",
                plain_text=f"Reminder: {title} starts in {mins_away} minutes!",
            )
        except Exception:
            logger.exception("Failed to send pre-event reminder for event %s", event_id)
            continue
        _reminded_events[key] = start_dt
        logger.info("Sent pre-event reminder for event %s", event_id)


def _events_from_tool_result(content: list[Any]) -> list[dict[str, Any]]:
    """Pull the JSON-encoded event list out of an MCP tool-call result.

    Raises ``ValueError`` when the server reported an error (it returns
    ``{"error": ...}`` as ordinary text rather than failing the call) or
    sent anything other than a list — callers must not mistake a failed
    fetch for "no events today".
    """
    if not content:
        return []
    first = content[0]
    text = getattr(first, "text", None)
    if not text:
        return []
    parsed: Any = json.loads(text)
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict) and "error" in parsed:
        raise ValueError(f"list_events failed: {parsed['error']}")
    raise ValueError(f"list_events returned {type(parsed).__name__}, expected a list")


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
