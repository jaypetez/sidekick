"""Tests for sidekick.announce (post-deploy version announcements)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from sidekick import announce


@pytest.fixture(autouse=True)
def _config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SIDEKICK_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("SIDEKICK_ANNOUNCE_UPDATES", raising=False)
    monkeypatch.delenv("SIDEKICK_UPDATE_REPO", raising=False)
    return tmp_path


def _bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


def _github(commits: list[str], *, status: int = 200, seen: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        payload = {"status": "ahead", "commits": [{"commit": {"message": m}} for m in commits]}
        return httpx.Response(status, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- version_ref


@pytest.mark.parametrize(
    ("version", "ref"),
    [
        ("0.2.1", "v0.2.1"),
        ("0.1.17.post24+gc58d293", "c58d293"),
        ("0.2.2.dev3+gabc1234.d20261119", "abc1234"),
        ("0.0.0", None),
        ("0.2.1.post3", None),
        ("garbage", None),
    ],
)
def test_version_ref(version, ref):
    assert announce.version_ref(version) == ref


# ---------------------------------------------------------------- summarizing


def test_summarize_commits_highlights_features_and_fixes():
    summary = announce.summarize_commits(
        [
            "fix(calendar): show event times in the user's timezone, not UTC (#170)",
            "feat(bot): announce new versions in chat (#171)",
            "chore(deps): bump httpx (#156)",
            "docs(readme): typo",
        ]
    )
    assert summary.highlights == [
        "fix(calendar): show event times in the user's timezone, not UTC (#170)",
        "feat(bot): announce new versions in chat (#171)",
    ]
    assert summary.other_count == 2


def test_build_message_lists_changes():
    changes = announce.ChangeSummary(
        highlights=["fix(calendar): local times (#170)"], other_count=1
    )
    text = announce.build_message("0.2.2", "0.2.1", changes)
    assert text.startswith("🚀 Sidekick updated to 0.2.2 (from 0.2.1).")
    assert "• fix(calendar): local times (#170)" in text
    assert "Plus 1 maintenance change" in text


def test_build_message_caps_long_lists():
    changes = announce.ChangeSummary(highlights=[f"fix: thing {i}" for i in range(15)])
    text = announce.build_message("0.3.0", "0.2.0", changes)
    assert "• fix: thing 11" in text
    assert "• fix: thing 12" not in text
    assert "…and 3 more" in text


def test_build_message_without_changes_links_release_notes():
    text = announce.build_message("0.2.2", "0.2.1", None)
    assert "releases/tag/v0.2.2" in text


def test_build_message_first_run():
    assert announce.build_message("0.2.2", None, None) == "🚀 Sidekick 0.2.2 is up and running."


# ---------------------------------------------------------------- announce_if_updated


@pytest.mark.asyncio
async def test_announces_new_version_with_changes_and_records_it(_config_dir):
    announce.write_last_announced("0.2.0")
    seen: list[str] = []
    bot = _bot()
    async with _github(["fix(calendar): local times (#170)"], seen=seen) as client:
        sent = await announce.announce_if_updated(bot, -100, current="0.2.2", client=client)

    assert sent is True
    assert seen == ["https://api.github.com/repos/jaypetez/sidekick/compare/v0.2.0...v0.2.2"]
    text = bot.send_message.await_args.kwargs["text"]
    assert "updated to 0.2.2 (from 0.2.0)" in text
    assert "fix(calendar): local times (#170)" in text
    assert announce.read_last_announced() == "0.2.2"


@pytest.mark.asyncio
async def test_same_version_stays_quiet(_config_dir):
    announce.write_last_announced("0.2.2")
    bot = _bot()
    assert await announce.announce_if_updated(bot, -100, current="0.2.2") is False
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_github_failure_still_announces_version(_config_dir):
    announce.write_last_announced("0.2.0")
    bot = _bot()
    async with _github([], status=503) as client:
        assert await announce.announce_if_updated(bot, -100, current="0.2.2", client=client)
    text = bot.send_message.await_args.kwargs["text"]
    assert "updated to 0.2.2 (from 0.2.0)" in text
    assert "releases/tag/v0.2.2" in text


@pytest.fixture
def _no_sleep(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(announce.asyncio, "sleep", fake_sleep)
    return sleeps


@pytest.mark.asyncio
async def test_transient_send_failure_is_retried_in_process(_config_dir, _no_sleep):
    """Telegram timing out right after a deploy must not lose the notice."""
    announce.write_last_announced("0.2.0")
    bot = _bot()
    bot.send_message.side_effect = [RuntimeError("timed out"), RuntimeError("timed out"), None]
    async with _github([]) as client:
        assert await announce.announce_if_updated(bot, -100, current="0.2.2", client=client)
    assert bot.send_message.await_count == 3
    assert _no_sleep == [30, 60]
    assert announce.read_last_announced() == "0.2.2"


@pytest.mark.asyncio
async def test_failed_send_does_not_record_so_it_retries(_config_dir, _no_sleep):
    announce.write_last_announced("0.2.0")
    bot = _bot()
    bot.send_message.side_effect = RuntimeError("telegram down")
    async with _github([]) as client:
        assert not await announce.announce_if_updated(bot, -100, current="0.2.2", client=client)
    assert bot.send_message.await_count == len(announce.SEND_RETRY_DELAYS_SECONDS) + 1
    assert announce.read_last_announced() == "0.2.0"


@pytest.mark.asyncio
async def test_disabled_by_setting(_config_dir, monkeypatch):
    monkeypatch.setenv("SIDEKICK_ANNOUNCE_UPDATES", "false")
    bot = _bot()
    assert await announce.announce_if_updated(bot, -100, current="0.2.2") is False
    bot.send_message.assert_not_awaited()
    assert announce.read_last_announced() is None


@pytest.mark.asyncio
async def test_unknown_previous_skips_github(_config_dir):
    """First run: nothing to compare against, so no network call."""
    seen: list[str] = []
    bot = _bot()
    async with _github([], seen=seen) as client:
        assert await announce.announce_if_updated(bot, -100, current="0.2.2", client=client)
    assert seen == []
    assert bot.send_message.await_args.kwargs["text"] == "🚀 Sidekick 0.2.2 is up and running."


@pytest.mark.asyncio
async def test_local_build_compares_commits(_config_dir):
    announce.write_last_announced("0.2.1")
    seen: list[str] = []
    async with _github(["feat: x"], seen=seen) as client:
        await announce.announce_if_updated(
            _bot(), -100, current="0.2.1.post2+gdeadbee", client=client
        )
    assert seen[0].endswith("/compare/v0.2.1...deadbee")
