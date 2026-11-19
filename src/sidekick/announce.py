"""Announce a newly deployed version in the reminder chat.

On startup, if the running version differs from the last one announced, post
it to ``REMINDER_CHAT_ID`` with the changes since the previous version. The
image carries no git history, so the change list comes from GitHub's public
compare API (``SIDEKICK_UPDATE_REPO``). When that is unreachable, or a version
can't be mapped to a git ref (e.g. a ``0.0.0`` local build), the message still
names the version and just leaves the list out.

The last announced version lives in ``$SIDEKICK_CONFIG_DIR/announced_version``.
It's written only after a successful send, so a failed send retries on the
next start, and a plain restart (same version) stays quiet.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from telegram import Bot

from . import __version__, paths, runtime_config

logger = logging.getLogger(__name__)

STATE_FILENAME = "announced_version"
DEFAULT_REPO = "jaypetez/sidekick"
COMPARE_TIMEOUT_SECONDS = 10.0
MAX_LISTED_CHANGES = 12

# Conventional-commit types worth calling out; the rest are summarized as a count.
_HIGHLIGHT = re.compile(r"^(feat|fix|perf|security)(\([^)]*\))?!?:", re.IGNORECASE)
_RELEASE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
_LOCAL_SHA = re.compile(r"\+g([0-9a-f]{7,40})(?:\.|$)")


@dataclass
class ChangeSummary:
    highlights: list[str] = field(default_factory=list)
    other_count: int = 0


def state_file() -> Path:
    return paths.config_dir() / STATE_FILENAME


def enabled() -> bool:
    raw = runtime_config.get("SIDEKICK_ANNOUNCE_UPDATES", "true") or "true"
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def repo() -> str:
    return (runtime_config.get("SIDEKICK_UPDATE_REPO", DEFAULT_REPO) or DEFAULT_REPO).strip()


def version_ref(version: str) -> str | None:
    """The git ref a version was built from, or ``None`` if it can't be known.

    ``0.2.1`` → ``v0.2.1`` (a release tag); ``0.2.1.post3+gabc1234`` or
    ``0.2.2.dev3+gabc1234`` → ``abc1234`` (a local build's commit).
    """
    version = version.strip()
    if _RELEASE.match(version):
        return None if version == "0.0.0" else f"v{version}"
    match = _LOCAL_SHA.search(version)
    return match.group(1) if match else None


def read_last_announced() -> str | None:
    try:
        text = state_file().read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text or None


def write_last_announced(version: str) -> None:
    path = state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(version + "\n", encoding="utf-8")


def summarize_commits(subjects: list[str]) -> ChangeSummary:
    summary = ChangeSummary()
    for subject in subjects:
        if _HIGHLIGHT.match(subject):
            summary.highlights.append(subject)
        else:
            summary.other_count += 1
    return summary


async def fetch_changes(
    base: str, head: str, *, client: httpx.AsyncClient | None = None
) -> ChangeSummary | None:
    """Commits in ``base...head`` from GitHub, or ``None`` if unavailable."""
    url = f"https://api.github.com/repos/{repo()}/compare/{base}...{head}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "sidekick-update-notes"}
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=COMPARE_TIMEOUT_SECONDS) as own:
                response = await own.get(url, headers=headers)
        else:
            response = await client.get(url, headers=headers)
        response.raise_for_status()
        data: Any = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Couldn't fetch changes %s...%s: %s", base, head, exc)
        return None
    commits = data.get("commits") if isinstance(data, dict) else None
    if not isinstance(commits, list):
        return None
    subjects = [
        str(c.get("commit", {}).get("message", "")).splitlines()[0]
        for c in commits
        if isinstance(c, dict) and c.get("commit", {}).get("message")
    ]
    return summarize_commits(subjects)


def build_message(current: str, previous: str | None, changes: ChangeSummary | None) -> str:
    if previous is None:
        return f"🚀 Sidekick {current} is up and running."
    lines = [f"🚀 Sidekick updated to {current} (from {previous})."]
    if changes is not None and (changes.highlights or changes.other_count):
        if changes.highlights:
            lines.append("")
            lines.append("What's new:")
            shown = changes.highlights[:MAX_LISTED_CHANGES]
            lines.extend(f"• {subject}" for subject in shown)
            hidden = len(changes.highlights) - len(shown)
            if hidden:
                lines.append(f"• …and {hidden} more")
        if changes.other_count:
            noun = "change" if changes.other_count == 1 else "changes"
            lines.append(f"Plus {changes.other_count} maintenance {noun} (dependencies, docs, CI).")
    elif changes is None:
        ref = version_ref(current)
        if ref is not None and ref.startswith("v"):
            lines.append(f"Release notes: https://github.com/{repo()}/releases/tag/{ref}")
    return "\n".join(lines)


async def announce_if_updated(
    bot: Bot,
    chat_id: int,
    *,
    current: str = __version__,
    client: httpx.AsyncClient | None = None,
) -> bool:
    """Post the update notice if the version changed. Returns True if one was sent."""
    if not enabled():
        return False
    previous = read_last_announced()
    if previous == current:
        return False

    changes: ChangeSummary | None = None
    base = version_ref(previous) if previous else None
    head = version_ref(current)
    if base and head and base != head:
        changes = await fetch_changes(base, head, client=client)

    text = build_message(current, previous, changes)
    try:
        await bot.send_message(chat_id=chat_id, text=text, disable_web_page_preview=True)
    except Exception:
        logger.exception("Failed to send the update announcement; will retry next start")
        return False
    write_last_announced(current)
    logger.info("Announced version %s (previous %s)", current, previous)
    return True
