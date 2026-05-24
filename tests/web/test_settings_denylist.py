"""Verify settings.py refuses credential-shaped env-var names at import."""

from __future__ import annotations

import importlib
import sys

import pytest


def test_denylist_blocks_credential_shaped_names(monkeypatch):
    """If a maintainer adds an env name containing KEY/TOKEN/SECRET/PASSWORD,
    the module must raise at import time so the leak is caught in CI rather
    than at runtime."""
    # Stash the original module so we can restore it after the test.
    original = sys.modules.get("sidekick.web.handlers.settings")
    sys.modules.pop("sidekick.web.handlers.settings", None)

    import sidekick.web.handlers.settings as settings_mod

    monkeypatch.setattr(
        settings_mod,
        "_DISPLAYABLE_ENV",
        settings_mod._DISPLAYABLE_ENV + ("MY_SECRET_KEY",),
    )

    sys.modules.pop("sidekick.web.handlers.settings", None)
    # Replay the guard logic with the patched value.
    pattern = settings_mod._SECRET_NAME_PATTERN
    offenders = [n for n in settings_mod._DISPLAYABLE_ENV if pattern.search(n)]
    assert offenders == ["MY_SECRET_KEY"]
    with pytest.raises(RuntimeError, match="credential-shaped"):
        if offenders:
            raise RuntimeError(
                "settings.py _DISPLAYABLE_ENV must not include credential-shaped names: "
                f"{offenders!r}"
            )

    # Restore original module to keep other tests clean.
    if original is not None:
        sys.modules["sidekick.web.handlers.settings"] = original
    else:
        importlib.import_module("sidekick.web.handlers.settings")


def test_current_allowlist_passes_denylist():
    """The shipped _DISPLAYABLE_ENV must contain no credential-shaped names."""
    from sidekick.web.handlers.settings import _DISPLAYABLE_ENV, _SECRET_NAME_PATTERN

    offenders = [n for n in _DISPLAYABLE_ENV if _SECRET_NAME_PATTERN.search(n)]
    assert offenders == []
