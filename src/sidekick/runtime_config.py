"""Runtime configuration overlay.

At process start ``dotenv`` has loaded ``.env`` into ``os.environ``.
This module layers runtime overrides on top: values written through
``set_value()`` are persisted to ``~/.config/sidekick/runtime.json``
and win over the environment when ``get()`` is called.

Only an explicit whitelist of keys is editable through this layer.
Secrets (API tokens) are stored verbatim in that JSON file — the file
is chmod'd to 0600 on POSIX (best-effort on Windows) and is never
returned in full from ``as_dict(redacted=True)``.

The personality JSON managed by ``agent.py`` lives in a separate file
(``config.json`` in the same directory) so the two concerns don't
collide.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import stat
import tempfile
from pathlib import Path
from threading import RLock
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)

EDITABLE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "CLAUDE_MODEL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "OLLAMA_NUM_CTX",
        "OLLAMA_NUM_GPU",
        "OLLAMA_KEEP_ALIVE",
        "TIMEZONE",
        "MORNING_REMINDER_TIME",
        "PRE_EVENT_REMINDER_MINUTES",
    }
)

SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "TELEGRAM_BOT_TOKEN",
        "CHRONARY_API_KEY",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
    }
)


class ConfigError(ValueError):
    """Raised on attempts to set non-whitelisted keys."""


DEFAULT_TIMEZONE: Final = "America/Chicago"

# Keys whose new value only takes effect after a process restart (the MCP
# subprocess and already-registered cron triggers capture them at startup).
RESTART_REQUIRED_KEYS: Final[frozenset[str]] = frozenset({"TIMEZONE"})

_HHMM_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def _default_path() -> str:
    explicit = os.getenv("SIDEKICK_RUNTIME_CONFIG")
    if explicit:
        return explicit
    config_dir = os.path.expanduser(os.getenv("SIDEKICK_CONFIG_DIR", "~/.config/sidekick"))
    return os.path.join(config_dir, "runtime.json")


_lock = RLock()
# Resolved lazily (see current_path) so a SIDEKICK_CONFIG_DIR loaded from
# .env after this module is imported is still honored. use_path() pins it.
_path: str | None = None
_overlay: dict[str, str] | None = None  # lazy-loaded; None means "not yet read"


def _load() -> dict[str, str]:
    global _overlay
    with _lock:
        if _overlay is None:
            try:
                raw: Any = json.loads(Path(current_path()).read_text())
                if isinstance(raw, dict):
                    _overlay = {str(k): str(v) for k, v in raw.items() if isinstance(k, str)}
                else:
                    _overlay = {}
            except (FileNotFoundError, json.JSONDecodeError, OSError):
                _overlay = {}
        return _overlay


def get(key: str, default: str | None = None) -> str | None:
    """Return the effective value: overlay wins, then ``os.environ``, then default."""
    overlay = _load()
    if key in overlay:
        return overlay[key]
    return os.environ.get(key, default)


def get_bool(key: str, default: bool = False) -> bool:
    raw = get(key)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def get_int(key: str, default: int | None = None) -> int | None:
    raw = get(key)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("runtime_config: %s=%r is not an int; returning default", key, raw)
        return default


def timezone_name() -> str:
    """Effective IANA timezone name (overlay → env → America/Chicago)."""
    return get("TIMEZONE") or DEFAULT_TIMEZONE


def validate(key: str, value: str) -> None:
    """Raise :class:`ConfigError` if ``value`` is not acceptable for ``key``.

    An empty string is always valid: it means "remove the override".
    """
    if key not in EDITABLE_KEYS:
        raise ConfigError(f"{key} is not user-editable")
    if value == "":
        return
    if key == "TIMEZONE":
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ConfigError(f"TIMEZONE: unknown timezone {value!r}") from exc
    elif key == "MORNING_REMINDER_TIME":
        if not _HHMM_RE.match(value):
            raise ConfigError("MORNING_REMINDER_TIME must be HH:MM (24-hour)")
    elif key == "PRE_EVENT_REMINDER_MINUTES":
        if not value.isdigit():
            raise ConfigError("PRE_EVENT_REMINDER_MINUTES must be a whole number ≥ 0")
    elif key in {"OLLAMA_NUM_CTX", "OLLAMA_NUM_GPU"}:
        try:
            int(value)
        except ValueError as exc:
            raise ConfigError(f"{key} must be an integer") from exc
    elif key == "LLM_PROVIDER" and value.lower() not in {"anthropic", "ollama"}:
        raise ConfigError("LLM_PROVIDER must be 'anthropic' or 'ollama'")


def set_value(key: str, value: str, *, persist: bool = True) -> None:
    """Set an editable key. Raises :class:`ConfigError` for non-whitelisted keys."""
    validate(key, value)
    with _lock:
        overlay = _load()
        overlay[key] = value
        if persist:
            _persist(overlay)


def unset(key: str, *, persist: bool = True) -> None:
    """Remove an overlay entry. Subsequent reads fall back to ``os.environ``."""
    validate(key, "")
    with _lock:
        overlay = _load()
        if overlay.pop(key, None) is not None and persist:
            _persist(overlay)


def _persist(overlay: dict[str, str]) -> None:
    """Atomically write the overlay, owner-only from the moment it exists.

    The file can hold API keys, so it is created 0600 (``mkstemp``) rather
    than written then chmod'd, and swapped in with ``os.replace`` so a crash
    mid-write can never leave a truncated file that would drop every override.
    """
    path = Path(current_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".runtime-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(overlay, indent=2, sort_keys=True))
        try:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            logger.debug("Could not chmod %s — non-POSIX filesystem?", tmp)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _preview(value: str) -> str:
    """Short, opaque hint for the UI — never enough to reconstruct the value."""
    if len(value) <= 4:
        return "set"
    return f"…{value[-4:]}"


def as_dict(*, redacted: bool) -> dict[str, Any]:
    """Return effective values for every editable key.

    With ``redacted=True``, secret keys return
    ``{"set": bool, "preview": "...abcd"}`` instead of the raw value.
    With ``redacted=False``, raw values are returned — only use this in
    trusted code paths (never on a response that leaves the process).
    """
    out: dict[str, Any] = {}
    for key in sorted(EDITABLE_KEYS):
        value = get(key)
        if key in SECRET_KEYS and redacted:
            if value:
                out[key] = {"set": True, "preview": _preview(value)}
            else:
                out[key] = {"set": False, "preview": ""}
            continue
        out[key] = value or ""
    return out


# ---------------------------------------------------------------------------
# Test / runtime hooks
# ---------------------------------------------------------------------------


def reset_cache() -> None:
    """Force the next ``get()`` to re-read the file from disk.

    Intended for tests and for tools that mutate ``runtime.json`` out-of-band.
    """
    global _overlay
    with _lock:
        _overlay = None


def use_path(new_path: str | None) -> None:
    """Swap the persistence path and drop the cache. Test helper.

    ``None`` restores lazy resolution from the environment.
    """
    global _path, _overlay
    with _lock:
        _path = new_path
        _overlay = None


def current_path() -> str:
    """Return the path the overlay is being read from / persisted to."""
    return _path if _path is not None else _default_path()
