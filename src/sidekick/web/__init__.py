"""In-process web admin dashboard for sidekick.

Runs as a background task alongside the Telegram/Slack adapters. Reads
live state (scheduler, agent, MCP session) from the shared ``bot_data``
dict that PTB's ``Application`` exposes.
"""

from .app import make_app

__all__ = ["make_app"]
