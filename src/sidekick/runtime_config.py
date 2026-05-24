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

import json
import logging
import os
import stat
from pathlib import Path
from threading import RLock
from typing import Any, Final

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


def _default_path() -> str:
    return os.getenv(
        "SIDEKICK_RUNTIME_CONFIG",
        os.path.join(os.path.expanduser("~/.config/sidekick"), "runtime.json"),
    )


_lock = RLock()
_path: str = _default_path()
_overlay: dict[str, str] | None = None  # lazy-loaded; None means "not yet read"


def _load() -> dict[str, str]:
    global _overlay
    with _lock:
        if _overlay is None:
            try:
                raw: Any = json.loads(Path(_path).read_text())
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


def set_value(key: str, value: str, *, persist: bool = True) -> None:
    """Set an editable key. Raises :class:`ConfigError` for non-whitelisted keys."""
    if key not in EDITABLE_KEYS:
        raise ConfigError(f"{key} is not user-editable")
    with _lock:
        overlay = _load()
        overlay[key] = value
        if persist:
            _persist(overlay)


def unset(key: str, *, persist: bool = True) -> None:
    """Remove an overlay entry. Subsequent reads fall back to ``os.environ``."""
    if key not in EDITABLE_KEYS:
        raise ConfigError(f"{key} is not user-editable")
    with _lock:
        overlay = _load()
        if overlay.pop(key, None) is not None and persist:
            _persist(overlay)


def _persist(overlay: dict[str, str]) -> None:
    path = Path(_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlay, indent=2, sort_keys=True))
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        logger.debug("Could not chmod %s — non-POSIX filesystem?", path)


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


def use_path(new_path: str) -> None:
    """Swap the persistence path and drop the cache. Test helper."""
    global _path, _overlay
    with _lock:
        _path = new_path
        _overlay = None


def current_path() -> str:
    """Return the path the overlay is being read from / persisted to."""
    return _path
