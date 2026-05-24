"""
Sidekick — Telegram + Slack chat bot.

Entry point. Wires together:
  - Telegram bot (python-telegram-bot v21)
  - mcp_server.py (subprocess MCP server for calendar + tasks)
  - SidekickAgent (Claude tool-use loop)
  - APScheduler (morning summary + pre-event reminders)

Run:
    python bot.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Any, TypeAlias

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from telegram import Update
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
# Startup / shutdown hooks
# ---------------------------------------------------------------------------


async def _run_mcp_subprocess(
    params: StdioServerParameters,
    session_ready: asyncio.Event,
    shutdown_event: asyncio.Event,
    application: AppT,
) -> None:
    """Keep the MCP subprocess alive for the bot's lifetime.

    Runs as a background task. stdio_client's anyio cancel scope must
    be entered and exited within the same task, so we hold it open here
    and signal readiness via session_ready.
    """
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            application.bot_data["mcp_session"] = session
            session_ready.set()
            await shutdown_event.wait()


async def post_init(application: AppT) -> None:
    """Called by PTB after the event loop starts — wire up all components."""
    logger.info("Starting Sidekick...")

    server_path = Path(__file__).parent / "mcp_server.py"
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(server_path)],
        env=dict(os.environ),
    )

    session_ready = asyncio.Event()
    shutdown_event = asyncio.Event()
    application.bot_data["shutdown_event"] = shutdown_event

    mcp_task = asyncio.create_task(
        _run_mcp_subprocess(params, session_ready, shutdown_event, application)
    )
    application.bot_data["mcp_task"] = mcp_task

    await session_ready.wait()
    mcp_session = application.bot_data["mcp_session"]
    logger.info("MCP calendar server ready")

    # Start the reminder scheduler (built-in jobs only — custom reminders
    # are loaded after the agent is created so they can process through Claude)
    scheduler = setup_scheduler(application.bot, mcp_session)
    application.bot_data["scheduler"] = scheduler

    # Create and configure the agent with scheduler access for reminder tools
    reminder_chat_id = os.getenv("REMINDER_CHAT_ID")
    agent = SidekickAgent(
        mcp_session,
        scheduler=scheduler,
        bot=application.bot,
        reminder_chat_id=int(reminder_chat_id) if reminder_chat_id else None,
    )
    await agent.load_tools()
    application.bot_data["agent"] = agent
    logger.info("SidekickAgent ready with %d tools", len(agent.tools))

    # Load custom reminders now that the agent exists — reminders are
    # processed through the agent so Claude can call tools when they fire
    load_custom_reminders(scheduler, agent)

    # Optional: also run a Slack adapter alongside Telegram if configured.
    if os.getenv("SLACK_BOT_TOKEN") and os.getenv("SLACK_APP_TOKEN"):
        slack_task = asyncio.create_task(_run_slack(application, agent))
        application.bot_data["slack_task"] = slack_task
        logger.info("Slack adapter enabled")

    # Web admin dashboard — enabled by default, binds 127.0.0.1 only.
    if os.getenv("SIDEKICK_WEB_ENABLED", "true").lower() not in {"0", "false", "no"}:
        web_task = asyncio.create_task(_run_web(application))
        application.bot_data["web_task"] = web_task
        logger.info("Web dashboard enabled")

    logger.info("Sidekick is ready!")


async def _run_web(application: AppT) -> None:
    """Run the in-process admin dashboard.

    Builds an aiohttp app sharing PTB's ``bot_data`` and serves it on the
    configured host/port (defaults to localhost:8080). Stays alive until the
    task is cancelled in ``post_shutdown``.
    """
    from aiohttp import web as aiohttp_web

    host = os.getenv("SIDEKICK_WEB_HOST", "127.0.0.1")
    port = int(os.getenv("SIDEKICK_WEB_PORT", "8080"))

    app = make_web_app(bot_data=application.bot_data)
    runner = aiohttp_web.AppRunner(app)
    await runner.setup()
    application.bot_data["web_runner"] = runner

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


async def _run_slack(application: AppT, agent: SidekickAgent) -> None:
    """Spin up the Slack platform and route messages through the same agent."""
    from .platforms.slack import SlackPlatform

    platform = SlackPlatform()
    application.bot_data["slack_platform"] = platform

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


async def post_shutdown(application: AppT) -> None:
    """Clean up on shutdown."""
    scheduler = application.bot_data.get("scheduler")
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)

    # Stop the Slack adapter if it was running.
    slack_platform = application.bot_data.get("slack_platform")
    if slack_platform is not None:
        try:
            await slack_platform.stop()
        except Exception:
            logger.exception("Error stopping Slack platform")

    # Stop the web dashboard if it was running.
    web_task = application.bot_data.get("web_task")
    if web_task is not None and not web_task.done():
        web_task.cancel()
        try:
            await web_task
        except (asyncio.CancelledError, Exception):
            pass

    # Signal the MCP subprocess task to exit cleanly
    shutdown_event = application.bot_data.get("shutdown_event")
    if shutdown_event:
        shutdown_event.set()

    mcp_task = application.bot_data.get("mcp_task")
    if mcp_task and not mcp_task.done():
        try:
            await asyncio.wait_for(mcp_task, timeout=5.0)
        except (TimeoutError, Exception):
            mcp_task.cancel()

    logger.info("Sidekick shut down cleanly")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env")

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
