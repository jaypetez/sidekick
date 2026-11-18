"""JSON API surface for the web dashboard.

Mounted under ``/api/`` in :func:`sidekick.web.app.make_app`. Every
response uses the same envelope::

    {"data": <result> | None, "error": null | {"code": str, "message": str}}

so clients (the new JS frontend, the ``sidekick-cli`` HTTP client, and
any future surface) can branch on ``error`` without parsing per-route.
"""

from .app import make_api_app

__all__ = ["make_api_app"]
