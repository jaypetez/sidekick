"""Regression tests for the web security-hardening pass.

Covers: Host-header pinning (DNS rebinding), ``next`` open redirects,
token-bound expiring sessions, session-secret handling, auth-token
strength, and login throttling.
"""

from __future__ import annotations

import hashlib
import re
import stat
import sys
import time

import pytest
import pytest_asyncio

from sidekick.web import auth, make_app
from sidekick.web.handlers import login as login_handlers

TOKEN = "s3cret-token-long-enough"


# --- Host header / DNS rebinding -------------------------------------------


@pytest.mark.asyncio
async def test_unknown_host_rejected_when_auth_disabled(aiohttp_client, bot_data, monkeypatch):
    """A rebinding page reaches 127.0.0.1 but still sends its own Host."""
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    client = await aiohttp_client(make_app(bot_data=bot_data))
    resp = await client.get("/_csrf", headers={"Host": "evil.example:8080"})
    assert resp.status == 421


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["localhost:8080", "127.0.0.1:8080", "[::1]:8080", "LOCALHOST"])
async def test_loopback_hosts_allowed_when_auth_disabled(
    aiohttp_client, bot_data, monkeypatch, host
):
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    client = await aiohttp_client(make_app(bot_data=bot_data))
    resp = await client.get("/health", headers={"Host": host})
    assert resp.status == 200


@pytest.mark.asyncio
async def test_extra_allowed_hosts_env(aiohttp_client, bot_data, monkeypatch):
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SIDEKICK_WEB_ALLOWED_HOSTS", "sidekick.lan, box.tail1234.ts.net")
    client = await aiohttp_client(make_app(bot_data=bot_data))
    resp = await client.get("/health", headers={"Host": "box.tail1234.ts.net"})
    assert resp.status == 200


@pytest.mark.asyncio
async def test_host_check_skipped_when_auth_enabled(aiohttp_client, bot_data, monkeypatch):
    """With a token the rebound origin has no credentials; proxies may send any Host."""
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", TOKEN)
    client = await aiohttp_client(make_app(bot_data=bot_data))
    resp = await client.get("/health", headers={"Host": "sidekick.example.com"})
    assert resp.status == 200


# --- open redirect ---------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["/\t/evil.com", "/\n/evil.com", "/ /evil.com", "//evil.com", "/\\evil.com", "/a\x7fb"],
)
def test_safe_next_url_rejects_control_and_whitespace(value):
    assert auth.safe_next_url(value) == "/"


def test_safe_next_url_keeps_normal_paths():
    assert auth.safe_next_url("/tasks/Costco?x=1") == "/tasks/Costco?x=1"


# --- sessions --------------------------------------------------------------


def test_session_marker_bound_to_current_token(monkeypatch):
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", TOKEN)
    session: dict[str, object] = {}
    auth.mark_session_authenticated(session)
    assert auth.is_session_authenticated(session)

    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", TOKEN + "-rotated")
    assert not auth.is_session_authenticated(session)


def test_session_marker_expires(monkeypatch):
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", TOKEN)
    session: dict[str, object] = {}
    auth.mark_session_authenticated(session)
    marker = session[auth.SESSION_AUTH_KEY]
    assert isinstance(marker, dict)
    marker["at"] = time.time() - auth.SESSION_MAX_AGE_SECONDS - 1
    assert not auth.is_session_authenticated(session)


@pytest.mark.parametrize("marker", [True, "yes", {"fp": "x"}, {"at": 1}])
def test_legacy_or_forged_markers_rejected(monkeypatch, marker):
    """Pre-fingerprint ``True`` cookies (or hand-forged ones) don't authenticate."""
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", TOKEN)
    assert not auth.is_session_authenticated({auth.SESSION_AUTH_KEY: marker})


def test_no_session_auth_when_token_unset(monkeypatch):
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    session: dict[str, object] = {}
    auth.mark_session_authenticated(session)
    assert session == {}
    assert not auth.is_session_authenticated(session)


@pytest.mark.asyncio
async def test_session_cookie_flags(aiohttp_client, bot_data, monkeypatch):
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    client = await aiohttp_client(make_app(bot_data=bot_data))
    resp = await client.get("/_csrf")
    cookie = resp.headers.get("Set-Cookie", "")
    assert "SIDEKICK_SESSION=" in cookie
    assert "HttpOnly" in cookie
    assert re.search(r"SameSite=Lax", cookie, re.IGNORECASE)
    assert f"Max-Age={auth.SESSION_MAX_AGE_SECONDS}" in cookie


# --- session secret --------------------------------------------------------


def test_short_env_session_secret_is_ignored(monkeypatch, tmp_path):
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("SIDEKICK_WEB_SESSION_SECRET", "abc")
    secret = auth.load_or_create_session_secret()
    assert b"abcabc" not in secret
    assert (tmp_path / "web_session.secret").exists()


def test_long_env_session_secret_is_hashed(monkeypatch):
    value = "x" * 20 + "y" * 20
    monkeypatch.setenv("SIDEKICK_WEB_SESSION_SECRET", value)
    assert auth.load_or_create_session_secret() == hashlib.sha256(value.encode()).digest()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
def test_generated_secret_file_is_private(monkeypatch, tmp_path):
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("SIDEKICK_WEB_SESSION_SECRET", raising=False)
    auth.load_or_create_session_secret()
    mode = stat.S_IMODE((tmp_path / "web_session.secret").stat().st_mode)
    assert mode == 0o600


# --- auth token strength ---------------------------------------------------


@pytest.mark.parametrize(
    ("token", "problem"),
    [
        ("replace_me_with_a_strong_random_string", "placeholder"),
        ("short", "shorter"),
        ("a-perfectly-fine-random-token", None),
    ],
)
def test_auth_token_problem(token, problem):
    result = auth.auth_token_problem(token)
    if problem is None:
        assert result is None
    else:
        assert result is not None and problem in result


# --- login throttling ------------------------------------------------------


@pytest_asyncio.fixture
async def login_client(aiohttp_client, bot_data, monkeypatch):
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", TOKEN)
    login_handlers.reset_login_limiter()
    client = await aiohttp_client(make_app(bot_data=bot_data))
    yield client
    login_handlers.reset_login_limiter()


async def _login_csrf(client) -> str:
    resp = await client.get("/login")
    match = re.search(r'name="_csrf" value="([^"]+)"', await resp.text())
    assert match
    return match.group(1)


@pytest.mark.asyncio
async def test_login_throttled_after_repeated_failures(login_client):
    csrf = await _login_csrf(login_client)
    statuses = []
    for _ in range(11):
        resp = await login_client.post(
            "/login", data={"_csrf": csrf, "token": "wrong"}, allow_redirects=False
        )
        statuses.append(resp.status)
    assert statuses[:10] == [401] * 10
    assert statuses[10] == 429


@pytest.mark.asyncio
async def test_successful_login_not_throttled(login_client):
    csrf = await _login_csrf(login_client)
    for _ in range(12):
        resp = await login_client.post(
            "/login", data={"_csrf": csrf, "token": TOKEN}, allow_redirects=False
        )
        assert resp.status == 303
