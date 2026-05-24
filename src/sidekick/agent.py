"""
Claude AI agent with MCP tools and local reminder management.

Maintains per-chat conversation history and runs the tool-use loop
so Claude can make multiple API calls per user message. Reminder
tools are handled locally (not via MCP subprocess) since they need
access to the in-process APScheduler instance.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from mcp import ClientSession
from telegram import Bot

from .llm import LLMClient
from .llm.anthropic import AnthropicClient
from .reminders import (
    add_reminder,
    get_all_reminders,
    remove_reminder,
    update_reminder,
)

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 20  # max user+assistant pairs to keep per chat

CONFIG_FILE = os.getenv(
    "CONFIG_FILE",
    os.path.join(os.path.expanduser("~/.config/sidekick"), "config.json"),
)

PERSONALITY_PRESETS = {
    "default": "",
    "snarky": "Respond with dry wit and playful sarcasm. Be helpful but never miss a chance for a clever quip.",
    "formal": "Respond in a polished, professional tone. Use proper grammar and avoid colloquialisms.",
    "pirate": "Respond as a pirate. Use nautical language, say 'arr' and 'matey', and refer to calendars as 'ship logs'.",
    "surfer": "Respond like a laid-back surfer. Use words like 'dude', 'gnarly', 'rad', and keep the vibe totally chill.",
    "butler": "Respond as a distinguished English butler. Be impeccably polite, understated, and supremely competent.",
}


def _read_config() -> dict:
    try:
        return json.loads(Path(CONFIG_FILE).read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _write_config(config: dict) -> None:
    path = Path(CONFIG_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2))


SYSTEM_PROMPT = """You are Sidekick, a friendly personal assistant bot that manages \
your calendar, task lists, and scheduled reminders. Today is {today}. The timezone \
is {timezone}.

You can manage multiple task lists for any purpose — groceries, project planning, \
store-specific shopping, or anything else. When the user mentions a specific list by \
name (e.g. "add milk to my Costco list"), use that name. If context is ambiguous, \
call list_task_lists to see what exists. New lists are created automatically when you \
add tasks to a name that doesn't exist yet. Users can also rename, delete, or list \
their task lists.

You can manage scheduled reminders. Users can ask you to create recurring reminders \
(e.g. "every Sunday at 5pm remind me to prep lunches"), change the morning summary \
time, or disable pre-event alerts. Use the reminder tools for these requests. When \
adding a reminder, choose the right hour/minute and day_of_week from the user's \
natural language description.

Help users view, add, edit, and delete calendar events using natural language. \
Keep responses concise and friendly.

When listing events, format them clearly with day, date, time, and title.
When creating events, confirm the details back to the user after saving.
When you're unsure about a date or time, ask for clarification before acting.
If an operation fails, explain what went wrong in plain English.\
{personality}"""

# Tool names handled locally (not forwarded to MCP subprocess)
LOCAL_REMINDER_TOOLS = {
    "list_reminders", "add_reminder", "update_reminder", "remove_reminder"
}

REMINDER_TOOL_DEFS = [
    {
        "name": "list_reminders",
        "description": "List all active scheduled reminders, including the built-in morning summary and pre-event alerts.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "add_reminder",
        "description": "Create a new recurring scheduled reminder. The reminder will send a message to the chat at the specified time.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "The reminder message to send",
                },
                "hour": {
                    "type": "integer",
                    "description": "Hour of day (0-23) to send the reminder",
                },
                "minute": {
                    "type": "integer",
                    "description": "Minute of hour (0-59) to send the reminder",
                },
                "day_of_week": {
                    "type": "string",
                    "description": "Days to send (e.g. 'mon,wed,fri' or 'sun'). Omit for every day.",
                },
            },
            "required": ["message", "hour", "minute"],
        },
    },
    {
        "name": "update_reminder",
        "description": "Update an existing reminder's schedule, message, or enabled status. Works on built-in reminders too (morning_summary, pre_event_check).",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The reminder ID to update",
                },
                "message": {"type": "string"},
                "hour": {"type": "integer"},
                "minute": {"type": "integer"},
                "day_of_week": {"type": "string"},
                "enabled": {
                    "type": "boolean",
                    "description": "Set to false to disable, true to re-enable",
                },
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "remove_reminder",
        "description": "Remove a custom reminder. Built-in reminders (morning_summary, pre_event_check) cannot be removed — disable them with update_reminder instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The reminder ID to remove",
                },
            },
            "required": ["reminder_id"],
        },
    },
]


class FamilyAgent:
    def __init__(
        self,
        mcp_session: ClientSession,
        scheduler: AsyncIOScheduler | None = None,
        bot: Bot | None = None,
        reminder_chat_id: int | None = None,
        llm: LLMClient | None = None,
    ):
        self.session = mcp_session
        self.llm: LLMClient = llm or AnthropicClient()
        self.timezone = os.getenv("TIMEZONE", "America/Chicago")
        self.conversation_history: dict[int, list[dict]] = {}
        self.tools: list[dict] = []
        self.personality = _read_config().get("personality", "")
        self.scheduler = scheduler
        self.bot = bot
        self.reminder_chat_id = reminder_chat_id

    async def load_tools(self) -> None:
        """Fetch tool definitions from the MCP server and add local reminder tools."""
        result = await self.session.list_tools()
        self.tools = [
            {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in result.tools
        ]
        # Add local reminder tools
        self.tools.extend(REMINDER_TOOL_DEFS)
        logger.info("Loaded %d tools (%d MCP + %d local)", len(self.tools),
                     len(self.tools) - len(REMINDER_TOOL_DEFS), len(REMINDER_TOOL_DEFS))

    def clear_history(self, chat_id: int) -> None:
        self.conversation_history.pop(chat_id, None)

    def set_personality(self, style: str) -> str:
        """Set personality. Accepts a preset name or freeform text. Returns label."""
        style = style.strip()
        if not style or style.lower() == "default":
            self.personality = ""
            label = "default (friendly assistant)"
        elif style.lower() in PERSONALITY_PRESETS:
            self.personality = PERSONALITY_PRESETS[style.lower()]
            label = style.lower()
        else:
            self.personality = style
            label = "custom"
        config = _read_config()
        config["personality"] = self.personality
        _write_config(config)
        return label

    async def process_message(self, chat_id: int, user_text: str) -> str:
        """Main entry point — append user message to history, run tool loop, return reply."""
        history = self.conversation_history.setdefault(chat_id, [])

        # Snapshot length BEFORE adding anything so we can fully restore on error
        snapshot_len = len(history)

        history.append({"role": "user", "content": user_text})
        self._trim_history(history)

        try:
            reply = await self._run_tool_loop(chat_id)
        except anthropic.BadRequestError as e:
            # History is corrupted (mismatched tool_use/tool_result). Clear it
            # entirely and tell the user so they can just repeat their message.
            logger.error("Corrupted history for chat %d, clearing: %s", chat_id, e)
            self.clear_history(chat_id)
            return (
                "I hit a conversation error and had to reset. "
                "Sorry about that — please send your message again."
            )
        except Exception:
            logger.exception("Error in tool loop for chat %d", chat_id)
            # Restore history to exactly where it was before this request
            del history[snapshot_len:]
            raise

        return reply

    async def _run_tool_loop(self, chat_id: int) -> str:
        """Run the Claude tool-use loop until end_turn, return final text."""
        history = self.conversation_history[chat_id]
        today = datetime.now(ZoneInfo(self.timezone)).date().isoformat()
        personality_block = (
            f"\n\nPersonality and tone: {self.personality}" if self.personality else ""
        )
        system = SYSTEM_PROMPT.format(
            today=today,
            timezone=self.timezone,
            personality=personality_block,
        )

        while True:
            response = await self.llm.chat(
                system=system,
                messages=history,
                tools=self.tools,
                max_tokens=1024,
            )

            if response.stop_reason == "end_turn":
                # Extract text from the response and save to history
                text = self._extract_text(response.content)
                history.append(
                    {"role": "assistant", "content": response.content}
                )
                return text

            if response.stop_reason == "tool_use":
                # Append the full assistant message (text + tool_use blocks)
                history.append(
                    {"role": "assistant", "content": response.content}
                )

                # Execute every tool call and collect results
                tool_results = []
                for block in response.content:
                    if block.type != "tool_use":
                        continue
                    logger.info("Calling tool %s with args %s", block.name, block.input)

                    if block.name in LOCAL_REMINDER_TOOLS:
                        # Handle reminder tools locally
                        result_text = json.dumps(
                            self._handle_reminder_tool(block.name, block.input)
                        )
                    else:
                        # Forward to MCP subprocess
                        mcp_result = await self.session.call_tool(block.name, block.input)
                        result_text = (
                            mcp_result.content[0].text
                            if mcp_result.content
                            else '{"error": "no result"}'
                        )

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": result_text,
                        }
                    )

                # All tool results go back in a single user message
                history.append({"role": "user", "content": tool_results})
                continue

            # Unexpected stop reason — return whatever text we have
            return self._extract_text(response.content) or "(no response)"

    def _handle_reminder_tool(self, name: str, args: dict) -> dict | list:
        """Dispatch local reminder tool calls."""
        if not self.scheduler or not self.bot:
            return {"error": "Reminder system not available"}

        chat_id = self.reminder_chat_id or 0

        if name == "list_reminders":
            return get_all_reminders(self.scheduler)
        elif name == "add_reminder":
            return add_reminder(
                scheduler=self.scheduler,
                agent=self,
                message=args["message"],
                hour=args["hour"],
                minute=args["minute"],
                chat_id=chat_id,
                day_of_week=args.get("day_of_week"),
            )
        elif name == "update_reminder":
            return update_reminder(
                scheduler=self.scheduler,
                agent=self,
                reminder_id=args["reminder_id"],
                message=args.get("message"),
                hour=args.get("hour"),
                minute=args.get("minute"),
                day_of_week=args.get("day_of_week"),
                enabled=args.get("enabled"),
            )
        elif name == "remove_reminder":
            return remove_reminder(self.scheduler, args["reminder_id"])
        else:
            return {"error": f"Unknown reminder tool: {name}"}

    def _extract_text(self, content: list) -> str:
        parts = [block.text for block in content if hasattr(block, "text")]
        return "\n".join(parts).strip()

    def _trim_history(self, history: list) -> None:
        """Keep history within MAX_HISTORY_TURNS pairs to avoid unbounded growth."""
        # Count user messages as a proxy for turns
        user_count = sum(1 for m in history if m["role"] == "user")
        while user_count > MAX_HISTORY_TURNS and len(history) >= 2:
            # Remove the oldest user+assistant pair
            history.pop(0)
            if history and history[0]["role"] == "assistant":
                history.pop(0)
            user_count -= 1
