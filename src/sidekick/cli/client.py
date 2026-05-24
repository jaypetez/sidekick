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


class ApiClient:
    """Tiny synchronous wrapper around ``httpx.Client``.

    Synchronous keeps the CLI subcommands' code dead simple — no async
    runtime, no event loop to manage just to make one HTTP call.
    """

    def __init__(self, *, base_url: str | None = None, timeout: float = 15.0) -> None:
        self.base_url = (base_url or default_base_url()).rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    def close(self) -> None:
        self._client.close()

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
            response = self._client.request(
                method, path, params=params, json=json_body if json_body is not None else None
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
