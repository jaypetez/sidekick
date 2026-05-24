"""Verify the logging redaction filter scrubs common secret patterns."""

from __future__ import annotations

import logging

import pytest

from sidekick.logging_setup import install_redaction_filter, safe_repr


@pytest.fixture
def redacted_root(caplog: pytest.LogCaptureFixture) -> logging.Logger:
    from sidekick.logging_setup import RedactionFilter

    install_redaction_filter()
    # caplog uses its own handler — attach the filter to it explicitly so
    # captured records reflect what real handlers would emit.
    caplog.handler.addFilter(RedactionFilter())
    return logging.getLogger()


def test_filter_redacts_api_key_in_message(
    caplog: pytest.LogCaptureFixture, redacted_root: logging.Logger
) -> None:
    caplog.set_level(logging.INFO)
    logger = logging.getLogger("sidekick.test.redact")
    logger.info("api_key=secret123 should not appear")
    blob = caplog.text
    assert "secret123" not in blob
    assert "[REDACTED]" in blob


def test_filter_redacts_token_in_arg(
    caplog: pytest.LogCaptureFixture, redacted_root: logging.Logger
) -> None:
    caplog.set_level(logging.INFO)
    logger = logging.getLogger("sidekick.test.redact")
    logger.info("payload: %s", "token=abc.def.ghi")
    blob = caplog.text
    assert "abc.def.ghi" not in blob
    assert "[REDACTED]" in blob


def test_install_is_idempotent() -> None:
    install_redaction_filter()
    install_redaction_filter()
    root = logging.getLogger()
    from sidekick.logging_setup import RedactionFilter

    assert sum(isinstance(f, RedactionFilter) for f in root.filters) == 1


def test_safe_repr_truncates_long_strings() -> None:
    s = "x" * 500
    out = safe_repr(s)
    assert len(out) < len(s)
    assert "truncated" in out


def test_safe_repr_redacts() -> None:
    out = safe_repr("password=hunter2")
    assert "hunter2" not in out
    assert "[REDACTED]" in out
