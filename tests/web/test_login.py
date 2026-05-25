"""Browser-friendly login flow: ``/login`` form + session cookie.

Bearer-header auth is exercised by ``test_auth.py``; this file covers
the parallel session-cookie path that lets browsers reach the dashboard
without a header-injecting extension. The two paths share the same
``SIDEKICK_WEB_AUTH_TOKEN`` secret.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from sidekick.web import make_app


@pytest_asyncio.fixture
async def auth_client(aiohttp_client, bot_data, monkeypatch):
    """Dashboard with auth enabled. No CSRF auto-injection — the tests
    that POST drive the login form themselves, including the token."""
    monkeypatch.setenv("SIDEKICK_WEB_AUTH_TOKEN", "s3cret-token")
    app = make_app(bot_data=bot_data)
    return await aiohttp_client(app)


async def _csrf(client):
    """Pull the current session's CSRF token by scraping the login page.

    ``/_csrf`` requires auth, so we can't use it pre-login. The login
    page is reachable unauthenticated and embeds the same token via the
    ``meta`` tag + the hidden form input.
    """
    import re

    resp = await client.get("/login")
    assert resp.status == 200
    body = await resp.text()
    match = re.search(r'name="csrf-token" content="([^"]+)"', body)
    assert match, "CSRF meta tag missing from login page"
    return match.group(1)


# -------------------------------------------------------------------
# Behavior of the auth middleware (browser-vs-API discrimination)
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browser_html_get_redirects_to_login(auth_client):
    """A browser-shaped GET (``Accept: text/html``) without auth bounces
    to the login form — not a bare 401. This is the whole point of the
    login flow: ``WWW-Authenticate: Bearer`` doesn't trigger any native
    browser prompt, so we need a page they can actually log in from."""
    resp = await auth_client.get(
        "/",
        headers={"Accept": "text/html"},
        allow_redirects=False,
    )
    assert resp.status == 303
    location = resp.headers["Location"]
    assert location.startswith("/login")
    # The original target is preserved so we can bounce back after login.
    assert "next=%2F" in location or "next=/" in location


@pytest.mark.asyncio
async def test_browser_redirect_preserves_next_with_query(auth_client):
    """The ``next=`` param should round-trip the path + query string."""
    resp = await auth_client.get(
        "/tasks?filter=open",
        headers={"Accept": "text/html"},
        allow_redirects=False,
    )
    assert resp.status == 303
    assert "next=" in resp.headers["Location"]
    # Path was preserved (encoded or otherwise).
    assert "/tasks" in resp.headers["Location"]


@pytest.mark.asyncio
async def test_api_get_without_token_still_401(auth_client):
    """API clients (no ``text/html`` in Accept) keep the 401 contract."""
    resp = await auth_client.get("/")
    assert resp.status == 401
    assert "Bearer" in resp.headers.get("WWW-Authenticate", "")


@pytest.mark.asyncio
async def test_bad_bearer_still_401_even_for_browser(auth_client):
    """If the caller bothered to set ``Authorization`` and it's wrong,
    don't masquerade that as "please log in" — return 401 plainly. The
    redirect dance is only for callers who never tried to authenticate."""
    resp = await auth_client.get(
        "/",
        headers={"Authorization": "Bearer wrong", "Accept": "text/html"},
        allow_redirects=False,
    )
    assert resp.status == 401


# -------------------------------------------------------------------
# GET /login — render the form
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_form_renders_with_csrf(auth_client):
    resp = await auth_client.get("/login")
    assert resp.status == 200
    body = await resp.text()
    assert "<form" in body
    assert 'name="token"' in body
    assert 'name="_csrf"' in body
    assert 'name="next"' in body


@pytest.mark.asyncio
async def test_login_form_passes_next_through_to_hidden_field(auth_client):
    resp = await auth_client.get("/login?next=/tasks")
    body = await resp.text()
    assert 'value="/tasks"' in body


@pytest.mark.asyncio
async def test_login_form_rejects_unsafe_next(auth_client):
    """An attacker-supplied ``next=//evil.example`` must not survive."""
    resp = await auth_client.get("/login?next=//evil.example/")
    body = await resp.text()
    # Should fall back to "/" — never echo the hostile URL.
    assert "evil.example" not in body
    assert 'value="/"' in body


@pytest.mark.asyncio
async def test_login_redirects_when_auth_disabled(aiohttp_client, bot_data, monkeypatch):
    """Without a token configured there's nothing to log into — bounce."""
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    app = make_app(bot_data=bot_data)
    client = await aiohttp_client(app)
    resp = await client.get("/login", allow_redirects=False)
    assert resp.status == 303
    assert resp.headers["Location"] == "/"


# -------------------------------------------------------------------
# POST /login — happy and sad paths
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_with_correct_token_sets_session_and_redirects(auth_client):
    csrf = await _csrf(auth_client)
    resp = await auth_client.post(
        "/login",
        data={"_csrf": csrf, "token": "s3cret-token", "next": "/tasks"},
        allow_redirects=False,
    )
    assert resp.status == 303
    assert resp.headers["Location"] == "/tasks"

    # Subsequent navigation in the same session no longer needs a Bearer.
    follow = await auth_client.get("/", headers={"Accept": "text/html"})
    assert follow.status == 200


@pytest.mark.asyncio
async def test_login_with_wrong_token_renders_error_at_401(auth_client):
    csrf = await _csrf(auth_client)
    resp = await auth_client.post(
        "/login",
        data={"_csrf": csrf, "token": "nope", "next": "/"},
        allow_redirects=False,
    )
    assert resp.status == 401
    body = await resp.text()
    assert "Invalid token" in body
    # The form is re-rendered so the user can retry without losing context.
    assert "<form" in body


@pytest.mark.asyncio
async def test_login_with_blank_token_rejects(auth_client):
    csrf = await _csrf(auth_client)
    resp = await auth_client.post(
        "/login",
        data={"_csrf": csrf, "token": "", "next": "/"},
        allow_redirects=False,
    )
    assert resp.status == 401


@pytest.mark.asyncio
async def test_login_unsafe_next_falls_back_to_root(auth_client):
    """A hostile ``next=`` payload must redirect to ``/``, never off-site."""
    csrf = await _csrf(auth_client)
    resp = await auth_client.post(
        "/login",
        data={
            "_csrf": csrf,
            "token": "s3cret-token",
            "next": "https://evil.example/steal",
        },
        allow_redirects=False,
    )
    assert resp.status == 303
    assert resp.headers["Location"] == "/"


@pytest.mark.asyncio
async def test_login_requires_csrf_token(auth_client):
    """POST /login without a valid CSRF token gets 403, not 401 —
    proves CSRF middleware still runs even on the login route."""
    resp = await auth_client.post(
        "/login",
        data={"token": "s3cret-token", "next": "/"},
        allow_redirects=False,
    )
    assert resp.status == 403


# -------------------------------------------------------------------
# POST /logout
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_logout_clears_session(auth_client):
    csrf = await _csrf(auth_client)
    await auth_client.post(
        "/login",
        data={"_csrf": csrf, "token": "s3cret-token", "next": "/"},
        allow_redirects=False,
    )
    # Authenticated check: dashboard is reachable now.
    pre = await auth_client.get("/", headers={"Accept": "text/html"})
    assert pre.status == 200

    csrf_after = await _csrf(auth_client)
    out = await auth_client.post(
        "/logout",
        data={"_csrf": csrf_after},
        allow_redirects=False,
    )
    assert out.status == 303
    assert out.headers["Location"] == "/login"

    # Session no longer authenticated.
    post = await auth_client.get("/", headers={"Accept": "text/html"}, allow_redirects=False)
    assert post.status == 303
    assert post.headers["Location"].startswith("/login")


# -------------------------------------------------------------------
# Bearer keeps working alongside the new session path
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_still_authenticates_after_login_added(auth_client):
    resp = await auth_client.get("/", headers={"Authorization": "Bearer s3cret-token"})
    assert resp.status == 200
