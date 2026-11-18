"""The README logo and the dashboard's static logo are the same file.

``docs/assets/sidekick-logo.svg`` (README, GitHub) and
``src/sidekick/web/static/sidekick-logo.svg`` (dashboard header, favicon)
are deliberate copies — the package can't reach outside ``src/`` at
runtime. Nothing else keeps them in sync, so a fix to one (dark-mode
wordmark, reduced-motion handling) silently missing from the other is
caught here.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
README_LOGO = REPO_ROOT / "docs" / "assets" / "sidekick-logo.svg"
STATIC_LOGO = REPO_ROOT / "src" / "sidekick" / "web" / "static" / "sidekick-logo.svg"


def test_logo_copies_are_identical() -> None:
    assert README_LOGO.read_bytes() == STATIC_LOGO.read_bytes(), (
        "docs/assets/sidekick-logo.svg and src/sidekick/web/static/sidekick-logo.svg "
        "have diverged — copy the edited one over the other."
    )


def test_logo_honours_dark_mode_and_reduced_motion() -> None:
    svg = README_LOGO.read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in svg
    assert "prefers-reduced-motion: reduce" in svg
    # SMIL animations can't be switched off from CSS, so motion must stay in CSS.
    assert "<animate" not in svg
