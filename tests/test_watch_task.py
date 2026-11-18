"""watch_task surfaces background-task crashes immediately."""

from __future__ import annotations

import asyncio
import logging

import pytest

from sidekick.util import watch_task


@pytest.mark.asyncio
async def test_crash_is_logged_when_it_happens(caplog):
    async def boom() -> None:
        raise OSError("address already in use")

    with caplog.at_level(logging.ERROR, logger="sidekick.util"):
        task = watch_task(asyncio.create_task(boom()), "web-dashboard")
        await asyncio.wait([task])
        await asyncio.sleep(0)  # let the done-callback run

    assert "web-dashboard" in caplog.text
    assert "address already in use" in caplog.text


@pytest.mark.asyncio
async def test_clean_exit_and_cancel_are_silent(caplog):
    async def fine() -> int:
        return 1

    async def forever() -> None:
        await asyncio.sleep(3600)

    with caplog.at_level(logging.ERROR, logger="sidekick.util"):
        ok = watch_task(asyncio.create_task(fine()), "ok")
        stuck = watch_task(asyncio.create_task(forever()), "stuck")
        await ok
        stuck.cancel()
        await asyncio.wait([stuck])
        await asyncio.sleep(0)

    assert caplog.text == ""
