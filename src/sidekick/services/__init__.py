"""Service layer.

Pure async functions that operate directly on stores, providers,
scheduler, agent, and runtime config. Service modules take their
dependencies as arguments (no ``aiohttp.web.Request`` in signatures)
so they can be reused by HTML handlers, ``/api/*`` JSON handlers, and
the CLI alike.
"""
