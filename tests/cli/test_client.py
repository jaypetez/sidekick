"""Tests for the CLI HTTP client and envelope handling."""

from __future__ import annotations

import httpx
import pytest

from sidekick.cli.client import ApiClient, CliError, default_base_url

from .conftest import envelope_err, envelope_ok


def test_default_base_url_respects_env(monkeypatch):
    monkeypatch.setenv("SIDEKICK_API_URL", "http://example.com:9000/")
    assert default_base_url() == "http://example.com:9000"


def test_default_base_url_uses_web_port(monkeypatch):
    monkeypatch.delenv("SIDEKICK_API_URL", raising=False)
    monkeypatch.setenv("SIDEKICK_WEB_PORT", "9999")
    assert default_base_url() == "http://127.0.0.1:9999"


def test_default_base_url_fallback(monkeypatch):
    monkeypatch.delenv("SIDEKICK_API_URL", raising=False)
    monkeypatch.delenv("SIDEKICK_WEB_PORT", raising=False)
    assert default_base_url() == "http://127.0.0.1:8080"


def test_get_unwraps_envelope_data(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=envelope_ok({"value": 42}))

    with make_client(handler) as client:
        result = client.get("/api/anything")
    assert result == {"value": 42}


def test_envelope_error_becomes_cli_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json=envelope_err("not_found", "missing"))

    with make_client(handler) as client, pytest.raises(CliError) as exc_info:
        client.get("/api/x")
    assert exc_info.value.code == "not_found"
    assert exc_info.value.status == 404
    assert "missing" in str(exc_info.value)


def test_non_json_response_becomes_cli_error(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"<html>boom</html>")

    with make_client(handler) as client, pytest.raises(CliError) as exc_info:
        client.get("/api/x")
    assert exc_info.value.code == "invalid_response"


def test_network_error_becomes_cli_error(monkeypatch):
    """If the bot isn't running, the CLI surfaces a friendly network_error."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    client = ApiClient(base_url="http://test")
    client._client.close()
    client._client = httpx.Client(base_url="http://test", transport=transport)
    with pytest.raises(CliError) as exc_info:
        client.get("/api/x")
    assert exc_info.value.code == "network_error"
    client.close()


def test_post_sends_json_body(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["content"] = request.content
        return httpx.Response(200, json=envelope_ok({"ok": True}))

    with make_client(handler) as client:
        client.post("/api/things", json_body={"x": 1})
    assert captured["method"] == "POST"
    assert b'"x":1' in captured["content"].replace(b" ", b"")


def test_delete_sends_no_body(make_client):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["content"] = request.content
        return httpx.Response(200, json=envelope_ok({"deleted": True}))

    with make_client(handler) as client:
        client.delete("/api/things/abc")
    assert captured["method"] == "DELETE"
    assert captured["content"] == b""


def test_write_without_token_sends_csrf_header(make_client):
    """Token-less (loopback) mode: writes carry the token fetched from /_csrf."""
    from .conftest import CSRF_TOKEN

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=envelope_ok({}))

    with make_client(handler) as client:
        client.get("/api/x")
        client.patch("/api/settings", json_body={"TIMEZONE": "UTC"})
        client.delete("/api/tasks/a")

    assert "X-CSRF-Token" not in seen[0].headers  # GET needs none
    assert seen[1].headers["X-CSRF-Token"] == CSRF_TOKEN
    assert seen[2].headers["X-CSRF-Token"] == CSRF_TOKEN


def test_bearer_token_skips_csrf_fetch(monkeypatch):
    """With a token, the client authenticates by bearer and never hits /_csrf."""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        assert request.headers["Authorization"] == "Bearer tok-123"
        return httpx.Response(200, json=envelope_ok({}))

    monkeypatch.setenv("SIDEKICK_API_TOKEN", "tok-123")
    client = ApiClient(base_url="http://test")
    headers = dict(client._client.headers)
    client._client.close()
    client._client = httpx.Client(
        base_url="http://test", transport=httpx.MockTransport(handler), headers=headers
    )
    client.post("/api/chat", json_body={"text": "hi"})
    client.close()
    assert paths == ["/api/chat"]


def test_csrf_fetch_failure_is_cli_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "auth"})

    monkeypatch.delenv("SIDEKICK_API_TOKEN", raising=False)
    monkeypatch.delenv("SIDEKICK_WEB_AUTH_TOKEN", raising=False)
    client = ApiClient(base_url="http://test")
    client._client.close()
    client._client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    with pytest.raises(CliError) as exc_info:
        client.post("/api/chat", json_body={"text": "hi"})
    assert exc_info.value.status == 401
    client.close()
