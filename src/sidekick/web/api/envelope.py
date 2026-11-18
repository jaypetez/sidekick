"""JSON envelope helpers.

Standardises response shape so every ``/api/*`` handler returns the
same ``{data, error}`` structure. The middleware in :mod:`.app`
catches :class:`aiohttp.web.HTTPException` and unhandled errors and
turns them into the same envelope.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web


def ok(data: Any, *, status: int = 200) -> web.Response:
    """Wrap a successful result."""
    return web.json_response({"data": data, "error": None}, status=status)


def error(code: str, message: str, *, status: int = 400) -> web.Response:
    """Wrap a failure. ``code`` is a stable short string clients can branch on."""
    return web.json_response(
        {"data": None, "error": {"code": code, "message": message}},
        status=status,
    )
