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

import hashlib
import hmac
import logging
import os
import secrets
import stat
import time
from pathlib import Path

from ..util import LOOPBACK_HOSTS as LOOPBACK_HOSTS  # re-export: middleware imports it here
from ..util import is_loopback_host as is_loopback_host
from ..util import web_auth_token
from ..webhooks import WEBHOOK_PATH

logger = logging.getLogger(__name__)

# Paths that never require auth: liveness probe + static assets. ``/health``
# is matched exactly; ``/static/`` as a prefix.
PUBLIC_EXACT_PATHS = frozenset({"/health"})
PUBLIC_PATH_PREFIXES = ("/static/",)

# A login stays valid this long; the token fingerprint check (below) also
# revokes every session when SIDEKICK_WEB_AUTH_TOKEN is rotated.
SESSION_MAX_AGE_SECONDS = 7 * 24 * 3600

MIN_SESSION_KEY_MATERIAL_BYTES = 32
MIN_AUTH_TOKEN_LENGTH = 16

# Example values shipped in .env.example files. Anyone who copies the
# example without editing it would otherwise have a publicly known password.
_PLACEHOLDER_TOKENS = frozenset(
    {
        "replace_me_with_a_strong_random_string",
        "changeme",
        "change_me",
        "your_token_here",
    }
)

# Paths that handle the login flow itself — auth_middleware lets these
# through unconditionally so users can render the form and submit it.
LOGIN_PATHS = frozenset({"/login", "/logout"})

# Inbound webhooks authenticate by HMAC signature (checked in the handler),
# not by session/bearer, and are sent by servers that have neither a CSRF
# token nor our Host name. Matched exactly — never as a prefix.
WEBHOOK_PATHS = frozenset({WEBHOOK_PATH})

# Session-storage key set when a user has authenticated via the login form.
SESSION_AUTH_KEY = "_authenticated"


def _config_dir() -> Path:
    """Return the resolved config directory (mirrors sidekick.reminders)."""
    return Path(os.path.expanduser(os.getenv("SIDEKICK_CONFIG_DIR", "~/.config/sidekick")))


def get_auth_token() -> str | None:
    """Return the configured bearer token, or ``None`` if auth is disabled."""
    return web_auth_token()


def constant_time_equals(a: str, b: str) -> bool:
    """Constant-time string compare (wraps :func:`hmac.compare_digest`)."""
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


def load_or_create_session_secret() -> bytes:
    """Return a 32-byte session secret.

    Order of resolution:

    1. ``SIDEKICK_WEB_SESSION_SECRET`` env var (at least 32 bytes). The key
       is the SHA-256 of the full value, so every byte contributes.
    2. Existing ``${SIDEKICK_CONFIG_DIR}/web_session.secret`` file.
    3. A freshly generated value, written to the file with mode 0600.

    A too-short env secret is *ignored* (with an error log) rather than
    padded: repeating ``abc`` to 32 bytes keeps its 3 bytes of entropy, and
    the session cookie key is what stands between an attacker and a forged
    "authenticated" cookie.
    """
    env_secret = os.getenv("SIDEKICK_WEB_SESSION_SECRET", "").strip()
    if env_secret:
        raw = env_secret.encode("utf-8")
        if len(raw) >= MIN_SESSION_KEY_MATERIAL_BYTES:
            return hashlib.sha256(raw).digest()
        logger.error(
            "SIDEKICK_WEB_SESSION_SECRET is shorter than %d bytes and was ignored; "
            "using the generated secret in web_session.secret instead.",
            MIN_SESSION_KEY_MATERIAL_BYTES,
        )

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
    write_private_file(secret_path, new_secret)
    logger.info("Generated new web session secret at %s", secret_path)
    return new_secret[:32]


def write_private_file(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` with mode 0600 *from creation*.

    ``write_bytes`` + ``chmod`` leaves a window where the file exists with
    umask-default permissions; opening with an explicit mode closes it.
    Windows ignores the POSIX bits — best effort there.
    """
    if path.exists():
        path.unlink()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def auth_token_problem(token: str) -> str | None:
    """Return why ``token`` is unacceptable as the dashboard password, or None."""
    if token.strip().lower() in _PLACEHOLDER_TOKENS:
        return "it is the placeholder value from .env.example"
    if len(token) < MIN_AUTH_TOKEN_LENGTH:
        return f"it is shorter than {MIN_AUTH_TOKEN_LENGTH} characters"
    return None


def is_public_path(path: str) -> bool:
    """True when ``path`` should bypass token auth."""
    return path in PUBLIC_EXACT_PATHS or path.startswith(PUBLIC_PATH_PREFIXES)


def extract_bearer(authorization_header: str | None) -> str | None:
    """Return the bearer token from an ``Authorization`` header, or None."""
    if not authorization_header:
        return None
    parts = authorization_header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def is_webhook_path(path: str) -> bool:
    """True for signature-authenticated webhook endpoints."""
    return path in WEBHOOK_PATHS


def is_login_path(path: str) -> bool:
    """True when ``path`` is part of the login flow itself."""
    return path in LOGIN_PATHS


def _token_fingerprint(token: str) -> str:
    """Short, non-reversible tag of the auth token a session was issued under."""
    return hashlib.sha256(b"sidekick-session:" + token.encode("utf-8")).hexdigest()[:32]


def is_session_authenticated(session: object) -> bool:
    """True when the session was authenticated under the *current* token.

    Sessions are stateless encrypted cookies, so this is the only place a
    login can be revoked: the stored fingerprint must match the configured
    token (rotating ``SIDEKICK_WEB_AUTH_TOKEN`` logs everyone out) and the
    login must be younger than :data:`SESSION_MAX_AGE_SECONDS`.
    """
    token = get_auth_token()
    if token is None:
        return False
    try:
        marker = session[SESSION_AUTH_KEY]  # type: ignore[index]
    except (KeyError, TypeError):
        return False
    if not isinstance(marker, dict):
        return False  # legacy ``True`` marker from before fingerprinting
    fingerprint = marker.get("fp")
    issued_at = marker.get("at")
    if not isinstance(fingerprint, str) or not isinstance(issued_at, int | float):
        return False
    if not constant_time_equals(fingerprint, _token_fingerprint(token)):
        return False
    return 0 <= time.time() - issued_at <= SESSION_MAX_AGE_SECONDS


def mark_session_authenticated(session: object) -> None:
    """Record that the user authenticated under the current token."""
    token = get_auth_token()
    if token is None:
        return
    session[SESSION_AUTH_KEY] = {  # type: ignore[index]
        "fp": _token_fingerprint(token),
        "at": int(time.time()),
    }


def clear_session_authentication(session: object) -> None:
    """Remove the session authentication flag (logout)."""
    try:
        del session[SESSION_AUTH_KEY]  # type: ignore[attr-defined]
    except (KeyError, TypeError):
        pass


def safe_next_url(value: str | None, *, default: str = "/") -> str:
    """Return ``value`` if it is a safe internal path, else ``default``.

    Rejects values that don't start with ``/``, that start with ``//`` or
    ``/\\``, that contain ``\\``, or that contain whitespace / control
    characters. This prevents open-redirect attacks via a crafted
    ``?next=//evil.example/`` query parameter — including ``/\\t/evil.com``,
    which yarl collapses to ``//evil.com`` when it builds the Location header.
    """
    if not value:
        return default
    if any(ch.isspace() or ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        return default
    if not value.startswith("/"):
        return default
    if value.startswith("//") or value.startswith("/\\"):
        return default
    if "\\" in value:
        return default
    return value
