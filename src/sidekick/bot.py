"""
Sidekick — chat bot with optional Telegram + Slack + always-on web UI.

Entry point. Wires together:
  - Telegram bot (python-telegram-bot v21), optional — only when
    ``TELEGRAM_BOT_TOKEN`` is set
  - Slack adapter (optional), enabled when both Slack tokens are set
  - In-process aiohttp web dashboard + chat UI (default on)
  - mcp_server.py (subprocess MCP server for calendar + tasks)
  - SidekickAgent (Claude / Ollama tool-use loop)
  - APScheduler (morning summary + pre-event reminders, Telegram-only)

When ``TELEGRAM_BOT_TOKEN`` is blank/missing, the bot starts in
"web-only" mode — no Telegram polling, web UI becomes the only chat
surface (open ``http://127.0.0.1:8080/chat``).

Run:
    python -m sidekick.bot     # or: sidekick
"""

import asyncio
import logging
import os
import sys
from typing import Any, TypeAlias

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from telegram import Bot, Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

from .agent import PERSONALITY_PRESETS, SidekickAgent  # noqa: E402
from .platforms.base import IncomingMessage  # noqa: E402
from .reminders import load_custom_reminders, setup_scheduler  # noqa: E402
from .web import make_app as make_web_app  # noqa: E402

# python-telegram-bot's Application is generic over (bot, context, user_data,
# chat_data, bot_data, job_queue). We don't customize any of them — alias to Any
# everywhere so we don't have to repeat the full parameter list per usage.
AppT: TypeAlias = Application[Any, Any, Any, Any, Any, Any]

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telegram handlers
# ---------------------------------------------------------------------------


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    await update.message.reply_text(
        "Hi! I'm Sidekick, your personal assistant.\n\n"
        "Just talk to me naturally — try things like:\n"
        '• "What\'s on the calendar this week?"\n'
        '• "Add soccer practice tomorrow at 4:30pm"\n'
        '• "Move Tuesday\'s dentist to Thursday at 2pm"\n'
        '• "Delete the PTA meeting on Friday"\n\n'
        "Use /reset to clear our conversation history.\n"
        "Use /get_id to see this chat's ID (useful for setting up reminders).\n"
        "Use /personality to change my tone (try: snarky, pirate, formal, butler)."
    )


async def handle_reset(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_chat is not None and update.message is not None
    agent: SidekickAgent = context.bot_data["agent"]
    agent.clear_history(update.effective_chat.id)
    await update.message.reply_text("Conversation history cleared!")


async def handle_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.effective_chat is not None and update.message is not None
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"This chat's ID is: `{chat_id}`\n\n"
        "Set `REMINDER_CHAT_ID={chat_id}` in your `.env` file to enable "
        "morning summaries and pre-event reminders here.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_personality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    assert update.message is not None
    agent: SidekickAgent = context.bot_data["agent"]
    args = " ".join(context.args) if context.args else ""

    if not args:
        current = agent.personality or "default (friendly assistant)"
        presets = ", ".join(k for k in PERSONALITY_PRESETS if k != "default")
        await update.message.reply_text(
            f"Current personality: {current}\n\n"
            f"Usage: /personality <style>\n"
            f"Presets: {presets}\n"
            f"Or use any freeform description."
        )
        return

    label = agent.set_personality(args)
    await update.message.reply_text(f"Personality set to: {label}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.message or not update.message.text or not update.effective_chat:
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text
    agent: SidekickAgent = context.bot_data["agent"]

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        reply = await agent.process_message(chat_id, user_text)
    except Exception:
        logger.exception("Agent error for chat %d", chat_id)
        await update.message.reply_text("Sorry, something went wrong. Please try again.")
        return

    await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Shared bootstrap (used by both Telegram and web-only entry paths)
# ---------------------------------------------------------------------------


async def _run_mcp_subprocess(
    params: StdioServerParameters,
    session_ready: asyncio.Event,
    shutdown_event: asyncio.Event,
    bot_data: dict[str, Any],
) -> None:
    """Keep the MCP subprocess alive for the bot's lifetime.

    Runs as a background task. stdio_client's anyio cancel scope must
    be entered and exited within the same task, so we hold it open here
    and signal readiness via session_ready.
    """
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            bot_data["mcp_session"] = session
            session_ready.set()
            await shutdown_event.wait()


async def _bootstrap_services(bot_data: dict[str, Any], bot: Bot | None) -> None:
    """Wire MCP + scheduler + agent + optional Slack + web into ``bot_data``.

    Used by both the Telegram entry (``post_init`` passes the PTB Bot) and the
    web-only entry (``bot=None``). When ``bot`` is None the scheduler still
    starts but the built-in delivery jobs that need a Telegram Bot are skipped.
    """
    logger.info("Starting Sidekick (%s mode)", "telegram" if bot else "web-only")

    # IMPORTANT: launch the MCP server via `-m sidekick.mcp_server`, not by
    # passing the script path. Running the .py file directly prepends
    # src/sidekick/ to sys.path, which makes our `sidekick/calendar/` package
    # shadow the stdlib `calendar` module — httpx → http.cookiejar →
    # calendar.timegm then explodes with a cryptic ImportError.
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "sidekick.mcp_server"],
        env=dict(os.environ),
    )

    session_ready = asyncio.Event()
    shutdown_event = bot_data.setdefault("shutdown_event", asyncio.Event())

    mcp_task = asyncio.create_task(
        _run_mcp_subprocess(params, session_ready, shutdown_event, bot_data)
    )
    bot_data["mcp_task"] = mcp_task

    # If the MCP subprocess crashes during startup, session_ready will never
    # be set — bound the wait so we surface the underlying error instead of
    # hanging the whole bot.
    try:
        await asyncio.wait_for(session_ready.wait(), timeout=15.0)
    except TimeoutError as wait_err:
        if mcp_task.done():
            exc = mcp_task.exception()
            if exc is not None:
                raise RuntimeError(f"MCP subprocess failed to start: {exc}") from exc
        raise RuntimeError("MCP subprocess did not become ready within 15s") from wait_err
    mcp_session = bot_data["mcp_session"]
    logger.info("MCP calendar server ready")

    scheduler = setup_scheduler(bot, mcp_session)
    bot_data["scheduler"] = scheduler

    reminder_chat_id = os.getenv("REMINDER_CHAT_ID")
    agent = SidekickAgent(
        mcp_session,
        scheduler=scheduler,
        bot=bot,
        reminder_chat_id=int(reminder_chat_id) if reminder_chat_id else None,
    )
    await agent.load_tools()
    bot_data["agent"] = agent
    logger.info("SidekickAgent ready with %d tools", len(agent.tools))

    load_custom_reminders(scheduler, agent)

    if os.getenv("SLACK_BOT_TOKEN") and os.getenv("SLACK_APP_TOKEN"):
        slack_task = asyncio.create_task(_run_slack(bot_data, agent))
        bot_data["slack_task"] = slack_task
        logger.info("Slack adapter enabled")

    # Web dashboard. Default on, but if we're in web-only mode it's the only
    # chat surface — force it on even if the env var says otherwise.
    web_disabled_via_env = os.getenv("SIDEKICK_WEB_ENABLED", "true").lower() in {
        "0",
        "false",
        "no",
    }
    if bot is None and web_disabled_via_env:
        logger.warning(
            "SIDEKICK_WEB_ENABLED is off but Telegram is also off — forcing web on "
            "(otherwise there would be no chat interface at all)."
        )
        web_enabled = True
    else:
        web_enabled = not web_disabled_via_env

    if web_enabled:
        web_task = asyncio.create_task(_run_web(bot_data))
        bot_data["web_task"] = web_task
        logger.info("Web dashboard enabled")

    logger.info("Sidekick is ready!")


async def _shutdown_services(bot_data: dict[str, Any]) -> None:
    """Tear down everything bootstrapped by ``_bootstrap_services``."""
    scheduler = bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)

    slack_platform = bot_data.get("slack_platform")
    if slack_platform is not None:
        try:
            await slack_platform.stop()
        except Exception:
            logger.exception("Error stopping Slack platform")

    web_task = bot_data.get("web_task")
    if web_task is not None and not web_task.done():
        web_task.cancel()
        try:
            await web_task
        except (asyncio.CancelledError, Exception):
            pass

    shutdown_event = bot_data.get("shutdown_event")
    if shutdown_event:
        shutdown_event.set()

    mcp_task = bot_data.get("mcp_task")
    if mcp_task and not mcp_task.done():
        try:
            await asyncio.wait_for(mcp_task, timeout=5.0)
        except (TimeoutError, Exception):
            mcp_task.cancel()

    logger.info("Sidekick shut down cleanly")


# ---------------------------------------------------------------------------
# Telegram startup / shutdown hooks
# ---------------------------------------------------------------------------


async def post_init(application: AppT) -> None:
    """Called by PTB after the event loop starts — wire up all components."""
    await _bootstrap_services(application.bot_data, application.bot)


async def post_shutdown(application: AppT) -> None:
    """Clean up on shutdown."""
    await _shutdown_services(application.bot_data)


async def _run_web(bot_data: dict[str, Any]) -> None:
    """Run the in-process admin dashboard + chat UI.

    Builds an aiohttp app sharing ``bot_data`` and serves it on the configured
    host/port (defaults to localhost:8080). Stays alive until the task is
    cancelled in ``_shutdown_services``.
    """
    from aiohttp import web as aiohttp_web

    from .calendar.chronary import ChronaryProvider
    from .storage.sqlite_tasks import SQLiteTaskStore

    host = os.getenv("SIDEKICK_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("SIDEKICK_WEB_PORT", "8080"))

    # Web layer gets its own provider instances so the MCP subprocess's
    # store/provider stay isolated. SQLite WAL handles the concurrency.
    task_store = SQLiteTaskStore()
    try:
        calendar_provider: ChronaryProvider | None = ChronaryProvider()
    except KeyError:
        # CHRONARY_* env vars not configured — calendar routes will 503.
        calendar_provider = None
        logger.warning("CHRONARY_* env vars missing; calendar dashboard routes disabled")

    app = make_web_app(
        bot_data=bot_data,
        task_store=task_store,
        calendar_provider=calendar_provider,
    )
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    bot_data["web_runner"] = runner

    site = aiohttp_web.TCPSite(runner, host, port)
    await site.start()
    logger.info("Web dashboard listening on http://%s:%d", host, port)

    # Keep the task alive until shutdown cancels us.
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        await runner.cleanup()
        raise


async def _run_slack(bot_data: dict[str, Any], agent: SidekickAgent) -> None:
    """Spin up the Slack platform and route messages through the same agent."""
    from .platforms.slack import SlackPlatform

    platform = SlackPlatform()
    bot_data["slack_platform"] = platform

    async def slack_default(msg: IncomingMessage) -> str | None:
        try:
            return await agent.process_message(msg.chat_id, msg.text)
        except Exception:
            logger.exception("Slack agent error for chat %s", msg.chat_id)
            return "Sorry, something went wrong. Please try again."

    async def slack_reset(msg: IncomingMessage, args: list[str]) -> str:
        agent.clear_history(msg.chat_id)
        return "Conversation history cleared!"

    async def slack_get_id(msg: IncomingMessage, args: list[str]) -> str:
        return f"This chat's ID is: `{msg.chat_id}`"

    async def slack_personality(msg: IncomingMessage, args: list[str]) -> str:
        if not args:
            current = agent.personality or "default (friendly assistant)"
            presets = ", ".join(k for k in PERSONALITY_PRESETS if k != "default")
            return (
                f"Current personality: {current}\nUsage: /personality <style>\nPresets: {presets}"
            )
        label = agent.set_personality(" ".join(args))
        return f"Personality set to: {label}"

    platform.register_default_handler(slack_default)
    platform.register_command("reset", slack_reset)
    platform.register_command("get_id", slack_get_id)
    platform.register_command("personality", slack_personality)

    await platform.start()


# ---------------------------------------------------------------------------
# Web-only entry path (no Telegram token configured)
# ---------------------------------------------------------------------------


async def _run_web_only() -> None:
    """Run Sidekick without Telegram. The web UI is the only chat surface."""
    bot_data: dict[str, Any] = {}
    try:
        await _bootstrap_services(bot_data, bot=None)
        # Block forever — services run as background tasks. Ctrl-C raises
        # KeyboardInterrupt into asyncio.run() which surfaces as CancelledError.
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("Shutdown requested")
    finally:
        await _shutdown_services(bot_data)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        logger.info("TELEGRAM_BOT_TOKEN not set — starting in web-only mode")
        try:
            asyncio.run(_run_web_only())
        except KeyboardInterrupt:
            logger.info("Sidekick stopped")
        return

    application = (
        Application.builder().token(token).post_init(post_init).post_shutdown(post_shutdown).build()
    )

    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("reset", handle_reset))
    application.add_handler(CommandHandler("get_id", handle_get_id))
    application.add_handler(CommandHandler("personality", handle_personality))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting polling...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
