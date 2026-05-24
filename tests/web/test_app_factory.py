"""Tests for the make_app() factory."""

from __future__ import annotations

from sidekick.web import make_app


def test_make_app_registers_bot_data_by_reference():
    """Handlers must see the live bot_data dict, not a copy."""
    bot_data = {"agent": "live"}
    app = make_app(bot_data=bot_data)
    assert app["bot_data"] is bot_data


def test_make_app_registers_core_routes():
    """Skeleton routes must be wired up."""
    app = make_app(bot_data={})
    paths = {route.resource.canonical for route in app.router.routes() if route.resource}
    assert "/" in paths
    assert "/health" in paths


def test_make_app_serves_static_files():
    """Static asset route must be mounted under /static/."""
    app = make_app(bot_data={})
    static_routes = [
        route
        for route in app.router.routes()
        if route.resource and "/static" in route.resource.canonical
    ]
    assert static_routes, "static route should be registered"
