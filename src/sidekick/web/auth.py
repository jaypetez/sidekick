"""Token + session secret helpers for the web dashboard.

Two unrelated secrets:

* ``SIDEKICK_WEB_AUTH_TOKEN`` — opt-in bearer token. When set, every
  request (except ``/static/`` and ``/health``) must carry
  ``Authorization: Bearer <token>``. Required when binding to a
  non-loopback interface.
* Session secret — used to sign the session cookie. Auto-generated to
  ``${SIDEKICK_CONFIG_DIR}/web_session.secret`` with mode 0600 if not
  provided via ``SIDEKICK_WEB_SESSION_SECRET``.

All comparisons use :func:`hmac.compare_digest` so an attacker can't
time-side-channel us into leaking either secret.
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

# Loopback addresses we consider "safe" for token-less operation.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Paths that never require auth: liveness probe + static assets.
PUBLIC_PATH_PREFIXES = ("/health", "/static/")

# Paths that handle the login flow itself — auth_middleware lets these
# through unconditionally so users can render the form and submit it.
LOGIN_PATHS = frozenset({"/login", "/logout"})

# Session-storage key set when a user has authenticated via the login form.
SESSION_AUTH_KEY = "_authenticated"


def _config_dir() -> Path:
    """Return the resolved config directory (mirrors sidekick.reminders)."""
    return Path(os.path.expanduser(os.getenv("SIDEKICK_CONFIG_DIR", "~/.config/sidekick")))


def get_auth_token() -> str | None:
    """Return the configured bearer token, or ``None`` if auth is disabled."""
    token = os.getenv("SIDEKICK_WEB_AUTH_TOKEN", "").strip()
    return token or None


def is_loopback_host(host: str) -> bool:
    """True when ``host`` is a loopback address we don't require a token for."""
    return host.strip().lower() in LOOPBACK_HOSTS


def constant_time_equals(a: str, b: str) -> bool:
    """Constant-time string compare (wraps :func:`hmac.compare_digest`)."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def load_or_create_session_secret() -> bytes:
    """Return a 32-byte session secret.

    Order of resolution:

    1. ``SIDEKICK_WEB_SESSION_SECRET`` env var (must be at least 32 chars).
    2. Existing ``${SIDEKICK_CONFIG_DIR}/web_session.secret`` file.
    3. A freshly generated value, written to the file with mode 0600.
    """
    env_secret = os.getenv("SIDEKICK_WEB_SESSION_SECRET", "").strip()
    if env_secret:
        raw = env_secret.encode("utf-8")
        if len(raw) < 32:
            # Pad/expand short secrets deterministically rather than reject —
            # users may have set a short hand-crafted value and we want to
            # avoid hard-crashing the dashboard at startup.
            raw = (raw * ((32 // len(raw)) + 1))[:32]
        return raw[:32]

    secret_path = _config_dir() / "web_session.secret"
    try:
        existing = secret_path.read_bytes().strip()
        if len(existing) >= 32:
            return existing[:32]
    except FileNotFoundError:
        pass
    except OSError as exc:
        logger.warning("Could not read web_session.secret (%s); regenerating", exc)

    secret_path.parent.mkdir(parents=True, exist_ok=True)
    new_secret = secrets.token_urlsafe(48).encode("utf-8")
    secret_path.write_bytes(new_secret)
    try:
        secret_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        # Windows doesn't honor POSIX mode bits — best effort.
        pass
    logger.info("Generated new web session secret at %s", secret_path)
    return new_secret[:32]


def is_public_path(path: str) -> bool:
    """True when ``path`` should bypass token auth."""
    return any(path == p or path.startswith(p) for p in PUBLIC_PATH_PREFIXES)


def extract_bearer(authorization_header: str | None) -> str | None:
    """Return the bearer token from an ``Authorization`` header, or None."""
    if not authorization_header:
        return None
    parts = authorization_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def is_login_path(path: str) -> bool:
    """True when ``path`` is part of the login flow itself."""
    return path in LOGIN_PATHS


def is_session_authenticated(session: object) -> bool:
    """True when the session has been marked as authenticated."""
    try:
        return bool(session[SESSION_AUTH_KEY])  # type: ignore[index]
    except (KeyError, TypeError):
        return False


def mark_session_authenticated(session: object) -> None:
    """Set the session flag indicating the user has authenticated."""
    session[SESSION_AUTH_KEY] = True  # type: ignore[index]


def clear_session_authentication(session: object) -> None:
    """Remove the session authentication flag (logout)."""
    try:
        del session[SESSION_AUTH_KEY]  # type: ignore[attr-defined]
    except (KeyError, TypeError):
        pass


def safe_next_url(value: str | None, *, default: str = "/") -> str:
    """Return ``value`` if it is a safe internal path, else ``default``.

    Rejects values that don't start with ``/``, that start with ``//`` or
    ``/\\``, or that contain ``\\``. This prevents open-redirect attacks
    via a crafted ``?next=//evil.example/`` query parameter.
    """
    if not value:
        return default
    if not value.startswith("/"):
        return default
    if value.startswith("//") or value.startswith("/\\"):
        return default
    if "\\" in value:
        return default
    return value
