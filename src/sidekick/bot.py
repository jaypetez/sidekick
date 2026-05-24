"""
Sidekick — Family Telegram Calendar Bot

Entry point. Wires together:
  - Telegram bot (python-telegram-bot v21)
  - mcp_server.py (subprocess MCP server for Google Calendar, Gmail, Tasks)
  - FamilyAgent (Claude Haiku + tool-use loop)
  - APScheduler (morning summary + pre-event reminders)

Run:
    python bot.py
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

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

from .agent import PERSONALITY_PRESETS, FamilyAgent
from .platforms.base import IncomingMessage
from .reminders import load_custom_reminders, setup_scheduler

logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Telegram handlers
# ---------------------------------------------------------------------------


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
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
    agent: FamilyAgent = context.bot_data["agent"]
    agent.clear_history(update.effective_chat.id)
    await update.message.reply_text("Conversation history cleared!")


async def handle_get_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"This chat's ID is: `{chat_id}`\n\n"
        "Set `REMINDER_CHAT_ID={chat_id}` in your `.env` file to enable "
        "morning summaries and pre-event reminders here.",
        parse_mode=ParseMode.MARKDOWN,
    )


async def handle_personality(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    agent: FamilyAgent = context.bot_data["agent"]
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
    if not update.message or not update.message.text:
        return

    chat_id = update.effective_chat.id
    user_text = update.message.text
    agent: FamilyAgent = context.bot_data["agent"]

    await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)

    try:
        reply = await agent.process_message(chat_id, user_text)
    except Exception:
        logger.exception("Agent error for chat %d", chat_id)
        await update.message.reply_text(
            "Sorry, something went wrong. Please try again."
        )
        return

    await update.message.reply_text(reply, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Startup / shutdown hooks
# ---------------------------------------------------------------------------


async def _run_mcp_subprocess(
    params: StdioServerParameters,
    session_ready: asyncio.Event,
    shutdown_event: asyncio.Event,
    application: Application,
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


async def post_init(application: Application) -> None:
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
    agent = FamilyAgent(
        mcp_session,
        scheduler=scheduler,
        bot=application.bot,
        reminder_chat_id=int(reminder_chat_id) if reminder_chat_id else None,
    )
    await agent.load_tools()
    application.bot_data["agent"] = agent
    logger.info("FamilyAgent ready with %d tools", len(agent.tools))

    # Load custom reminders now that the agent exists — reminders are
    # processed through the agent so Claude can call tools when they fire
    load_custom_reminders(scheduler, agent)

    # Optional: also run a Slack adapter alongside Telegram if configured.
    if os.getenv("SLACK_BOT_TOKEN") and os.getenv("SLACK_APP_TOKEN"):
        slack_task = asyncio.create_task(_run_slack(application, agent))
        application.bot_data["slack_task"] = slack_task
        logger.info("Slack adapter enabled")

    logger.info("Sidekick is ready!")


async def _run_slack(application: Application, agent: FamilyAgent) -> None:
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
                f"Current personality: {current}\n"
                f"Usage: /personality <style>\n"
                f"Presets: {presets}"
            )
        label = agent.set_personality(" ".join(args))
        return f"Personality set to: {label}"

    platform.register_default_handler(slack_default)
    platform.register_command("reset", slack_reset)
    platform.register_command("get_id", slack_get_id)
    platform.register_command("personality", slack_personality)

    await platform.start()


async def post_shutdown(application: Application) -> None:
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

    # Signal the MCP subprocess task to exit cleanly
    shutdown_event = application.bot_data.get("shutdown_event")
    if shutdown_event:
        shutdown_event.set()

    mcp_task = application.bot_data.get("mcp_task")
    if mcp_task and not mcp_task.done():
        try:
            await asyncio.wait_for(mcp_task, timeout=5.0)
        except (asyncio.TimeoutError, Exception):
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
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    application.add_handler(CommandHandler("start", handle_start))
    application.add_handler(CommandHandler("reset", handle_reset))
    application.add_handler(CommandHandler("get_id", handle_get_id))
    application.add_handler(CommandHandler("personality", handle_personality))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    logger.info("Starting polling...")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
