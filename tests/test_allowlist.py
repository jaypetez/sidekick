"""Tests for the closed-by-default allowlist helpers."""

from __future__ import annotations

import logging

from sidekick.allowlist import (
    DENIED_MESSAGE,
    is_allowed,
    parse_int_csv,
    parse_str_csv,
    warn_if_empty,
)


def test_denied_message_is_friendly():
    assert "allowlist" in DENIED_MESSAGE.lower()


def test_parse_int_csv_empty_returns_empty_frozenset():
    assert parse_int_csv(None) == frozenset()
    assert parse_int_csv("") == frozenset()
    assert parse_int_csv("   ") == frozenset()


def test_parse_int_csv_single_user():
    assert parse_int_csv("42") == frozenset({42})


def test_parse_int_csv_multi_user_csv_with_whitespace():
    assert parse_int_csv("1, 2 ,3,  4") == frozenset({1, 2, 3, 4})


def test_parse_int_csv_skips_non_numeric(caplog):
    with caplog.at_level(logging.WARNING, logger="sidekick.allowlist"):
        result = parse_int_csv("1,oops,2")
    assert result == frozenset({1, 2})
    assert any("oops" in rec.message for rec in caplog.records)


def test_parse_str_csv_keeps_opaque_ids():
    # Slack IDs are not integers.
    assert parse_str_csv("U01ABC,U02DEF") == frozenset({"U01ABC", "U02DEF"})


def test_parse_str_csv_empty_returns_empty():
    assert parse_str_csv(None) == frozenset()


def test_is_allowed_empty_allowlist_denies_all():
    empty: frozenset[int] = frozenset()
    assert is_allowed(1, empty) is False
    assert is_allowed(999999, empty) is False


def test_is_allowed_explicit_member_passes():
    allow = frozenset({1, 2, 3})
    assert is_allowed(2, allow) is True
    assert is_allowed(4, allow) is False


def test_is_allowed_none_identifier_is_denied():
    assert is_allowed(None, frozenset({1})) is False


def test_is_allowed_string_ids():
    assert is_allowed("U01ABC", frozenset({"U01ABC"})) is True
    assert is_allowed("U99ZZZ", frozenset({"U01ABC"})) is False


def test_warn_if_empty_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="sidekick.allowlist"):
        warn_if_empty(frozenset(), "TELEGRAM_ALLOWED_USER_IDS")
    assert any(
        "TELEGRAM_ALLOWED_USER_IDS" in rec.message and "reject" in rec.message
        for rec in caplog.records
    )


def test_warn_if_empty_quiet_when_populated(caplog):
    with caplog.at_level(logging.WARNING, logger="sidekick.allowlist"):
        warn_if_empty(frozenset({1}), "TELEGRAM_ALLOWED_USER_IDS")
    assert not any("reject" in rec.message for rec in caplog.records)
