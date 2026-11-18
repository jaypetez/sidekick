"""HTTP client for the sidekick CLI.

Talks to the running bot's ``/api/*`` surface and unwraps the
``{data, error}`` envelope. Base URL resolution order:

1. ``--base-url`` flag (passed in from ``main.py``).
2. ``SIDEKICK_API_URL`` env var.
3. ``http://127.0.0.1:${SIDEKICK_WEB_PORT:-8080}``.
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx


class CliError(RuntimeError):
    """Raised on any HTTP / envelope error so ``main.py`` can render it cleanly."""

    def __init__(self, code: str, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def default_base_url() -> str:
    base = os.environ.get("SIDEKICK_API_URL")
    if base:
        return base.rstrip("/")
    port = os.environ.get("SIDEKICK_WEB_PORT", "8080")
    return f"http://127.0.0.1:{port}"


_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def default_token() -> str | None:
    """Bearer token for the API: ``SIDEKICK_API_TOKEN``, else the server's own token."""
    token = os.environ.get("SIDEKICK_API_TOKEN") or os.environ.get("SIDEKICK_WEB_AUTH_TOKEN")
    return token.strip() or None if token else None


class ApiClient:
    """Tiny synchronous wrapper around ``httpx.Client``.

    Synchronous keeps the CLI subcommands' code dead simple — no async
    runtime, no event loop to manage just to make one HTTP call.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        timeout: float = 15.0,
        token: str | None = None,
    ) -> None:
        self.base_url = (base_url or default_base_url()).rstrip("/")
        # A bearer token both authenticates and exempts us from CSRF. Without
        # one (the token-less loopback default) we fetch a CSRF token from
        # /_csrf instead; the client's cookie jar carries the session cookie.
        self._token = token if token is not None else default_token()
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, headers=headers)
        self._csrf: str | None = None

    def close(self) -> None:
        self._client.close()

    def _csrf_token(self) -> str:
        """Fetch (once) a CSRF token bound to this client's session cookie."""
        if self._csrf is None:
            response = self._client.get("/_csrf")
            if not response.is_success:
                raise CliError(
                    f"http_{response.status_code}",
                    "could not obtain a CSRF token from /_csrf "
                    "(set SIDEKICK_API_TOKEN if the dashboard requires auth)",
                    status=response.status_code,
                )
            self._csrf = str(response.json()["csrf"])
        return self._csrf

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: Any = None,
    ) -> Any:
        try:
            headers: dict[str, str] = {}
            if method.upper() not in _SAFE_METHODS and not self._token:
                headers["X-CSRF-Token"] = self._csrf_token()
            response = self._client.request(
                method,
                path,
                params=params,
                json=json_body if json_body is not None else None,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise CliError(
                "network_error",
                f"could not reach {self.base_url}{path}: {exc}",
            ) from exc

        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise CliError(
                "invalid_response",
                f"non-JSON response from {self.base_url}{path}: {response.text[:200]}",
                status=response.status_code,
            ) from exc

        if not response.is_success or (isinstance(payload, dict) and payload.get("error")):
            err: dict[str, Any] = {}
            if isinstance(payload, dict) and isinstance(payload.get("error"), dict):
                err = payload["error"]
            raise CliError(
                str(err.get("code") or f"http_{response.status_code}"),
                str(err.get("message") or response.reason_phrase or "request failed"),
                status=response.status_code,
            )
        return payload.get("data") if isinstance(payload, dict) else payload

    # Sugar
    def get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, *, json_body: Any = None) -> Any:
        return self.request("POST", path, json_body=json_body)

    def patch(self, path: str, *, json_body: Any = None) -> Any:
        return self.request("PATCH", path, json_body=json_body)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)
