"""CLI subcommand registry.

Each module exposes a ``register(subparsers)`` function that wires its
parsers into the top-level ``argparse`` instance built in ``main.py``.
"""

from . import chat, events, reminders, settings, tasks

ALL_GROUPS = (tasks, reminders, events, chat, settings)
