"""Where Sidekick keeps its state on disk.

The single place that resolves file locations. Every state file lives in the
config directory (``SIDEKICK_CONFIG_DIR``, default ``~/.config/sidekick``)
unless its own variable points somewhere else:

=====================  ======================  ==================
File                   Override variable       Default name
=====================  ======================  ==================
tasks database         ``SIDEKICK_DB_PATH``    ``sidekick.db``
custom reminders       ``REMINDERS_FILE``      ``reminders.json``
personality / IDs      ``CONFIG_FILE``         ``config.json``
=====================  ======================  ==================

Values are ``~``-expanded, and an empty variable counts as unset.

**Legacy fallback.** Before this module existed, those three files ignored
``SIDEKICK_CONFIG_DIR`` and always lived in ``~/.config/sidekick``. An install
that set a custom config dir therefore has its data in the old place. When the
new location has no file but the legacy one does, the legacy file is used (and
a warning says how to move it) so no reminders, tasks or personality vanish
on upgrade.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Final

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR: Final = "~/.config/sidekick"

_warned: set[str] = set()


def _env_path(key: str) -> str | None:
    """``key``'s value, ``~``-expanded; ``None`` when unset or blank."""
    raw = os.getenv(key, "").strip()
    return os.path.expanduser(raw) if raw else None


def config_dir() -> Path:
    """The state directory: ``SIDEKICK_CONFIG_DIR`` or ``~/.config/sidekick``."""
    return Path(_env_path("SIDEKICK_CONFIG_DIR") or os.path.expanduser(DEFAULT_CONFIG_DIR))


def _state_file(override_key: str, filename: str) -> str:
    explicit = _env_path(override_key)
    if explicit:
        return explicit
    path = config_dir() / filename
    legacy = Path(os.path.expanduser(DEFAULT_CONFIG_DIR)) / filename
    if path != legacy and not path.exists() and legacy.exists():
        if filename not in _warned:
            _warned.add(filename)
            logger.warning(
                "Using legacy %s because %s does not exist yet. Older versions ignored "
                "SIDEKICK_CONFIG_DIR for this file; move it there to silence this warning.",
                legacy,
                path,
            )
        return str(legacy)
    return str(path)


def db_path() -> str:
    """Tasks SQLite database."""
    return _state_file("SIDEKICK_DB_PATH", "sidekick.db")


def reminders_file() -> str:
    """Custom reminders JSON."""
    return _state_file("REMINDERS_FILE", "reminders.json")


def personality_file() -> str:
    """Personality + Chronary IDs JSON (shared by the agent and ``sidekick-init``)."""
    return _state_file("CONFIG_FILE", "config.json")
