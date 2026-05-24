"""Capture screenshots of the web UI for the README.

Requires Playwright + Chromium:

    pip install playwright
    playwright install chromium

Then start Sidekick (any mode — web-only is easiest) and run:

    python scripts/capture_screenshots.py

Output: docs/screenshots/{chat,dashboard,tasks}.png
"""

from __future__ import annotations

import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
BASE_URL = "http://127.0.0.1:8080"
PAGES = [
    ("/chat", "chat.png", 1280, 900),
    ("/", "dashboard.png", 1280, 700),
    ("/tasks", "tasks.png", 1280, 700),
]


def main() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.stderr.write(
            "Playwright not installed. Run:\n"
            "  pip install playwright\n"
            "  playwright install chromium\n"
        )
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for path, filename, w, h in PAGES:
            page = browser.new_page(viewport={"width": w, "height": h})
            page.goto(f"{BASE_URL}{path}")
            page.wait_for_load_state("networkidle")
            out = OUTPUT_DIR / filename
            page.screenshot(path=str(out), full_page=False)
            print(f"wrote {out}")
            page.close()
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
