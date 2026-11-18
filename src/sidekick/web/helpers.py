"""Helpers shared across web handlers.

``run_sync`` was promoted to :mod:`sidekick.util` so the new services
layer can use it without taking a dependency on the web package. This
module remains as a thin re-export so existing handler imports keep
working.
"""

from __future__ import annotations

from ..util import run_sync

__all__ = ["run_sync"]
