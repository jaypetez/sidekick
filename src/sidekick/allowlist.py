"""Closed-by-default user/channel allowlists for chat surfaces.

Each chat surface (Telegram, Slack) parses a CSV env var into a frozenset
of allowed identifiers at startup. Telegram IDs are integers; Slack IDs
are opaque strings like ``U01ABC``. The semantics are deliberately
**closed-by-default**: if the env var is unset or empty, every user is
denied. Operators must explicitly opt people in.

Usage::

    from sidekick.allowlist import parse_int_csv, parse_str_csv, is_allowed

    ALLOWED = parse_int_csv(os.getenv("TELEGRAM_ALLOWED_USER_IDS"))
    if not is_allowed(user_id, ALLOWED):
        return  # reject

The denial reply text is centralized as :data:`DENIED_MESSAGE` so all
surfaces are consistent.
"""

from __future__ import annotations

import logging
from typing import TypeVar

logger = logging.getLogger(__name__)

DENIED_MESSAGE = "Sorry — you're not on this bot's allowlist."

T = TypeVar("T", int, str)


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [chunk.strip() for chunk in raw.split(",") if chunk.strip()]


def parse_int_csv(raw: str | None) -> frozenset[int]:
    """Parse a CSV of integer IDs (Telegram chat/user ids).

    Non-numeric entries are skipped with a warning rather than raising —
    we don't want one typo in an env var to wedge startup.
    """
    out: set[int] = set()
    for token in _split_csv(raw):
        try:
            out.add(int(token))
        except ValueError:
            logger.warning("Ignoring non-integer entry in allowlist: %r", token)
    return frozenset(out)


def parse_str_csv(raw: str | None) -> frozenset[str]:
    """Parse a CSV of string IDs (Slack user/channel ids like ``U01XYZ``)."""
    return frozenset(_split_csv(raw))


def is_allowed(identifier: T | None, allowlist: frozenset[T]) -> bool:
    """Return True iff ``identifier`` is explicitly in ``allowlist``.

    An empty allowlist denies everyone (closed-by-default).
    """
    if identifier is None:
        return False
    return identifier in allowlist


def warn_if_empty(allowlist: frozenset[object], env_var: str) -> None:
    """Emit a single startup warning when an allowlist is unset/empty.

    Highlights the closed-by-default behaviour so operators don't think
    the bot is broken when no messages get through.
    """
    if not allowlist:
        logger.warning(
            "%s is unset — bot will reject every message until configured",
            env_var,
        )
