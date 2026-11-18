"""Consistency guards for sidekick.config_catalog.

The catalog documents every setting; these tests fail when someone adds an
editable key, a secret, or a new env var read without cataloguing it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sidekick import config_catalog, runtime_config
from sidekick.config_catalog import CATALOG, GROUPS, get_spec, is_secret

SRC = Path(__file__).resolve().parents[1] / "src" / "sidekick"

_ENV_READ = re.compile(
    r'(?:getenv|environ\.get|runtime_config\.get(?:_int|_bool)?|_env_int)\(\s*"([A-Z][A-Z0-9_]+)"'
    r'|environ\[\s*"([A-Z][A-Z0-9_]+)"\s*\]'
    r'|_ENV\s*=\s*"([A-Z][A-Z0-9_]+)"'
)


def test_keys_are_unique():
    keys = [spec.key for spec in CATALOG]
    assert len(keys) == len(set(keys))


def test_every_group_is_known():
    assert {spec.group for spec in CATALOG} <= set(GROUPS)


def test_every_editable_key_is_catalogued():
    missing = runtime_config.EDITABLE_KEYS - {spec.key for spec in CATALOG}
    assert not missing


def test_runtime_secret_keys_are_flagged_secret():
    for key in runtime_config.SECRET_KEYS:
        spec = get_spec(key)
        assert spec is not None, key
        assert spec.secret, key


def test_every_env_var_read_in_source_is_catalogued():
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        for match in _ENV_READ.finditer(path.read_text(encoding="utf-8")):
            found.add(next(group for group in match.groups() if group))
    missing = found - {spec.key for spec in CATALOG}
    assert not missing, f"add these to config_catalog.CATALOG: {sorted(missing)}"


def test_editable_and_restart_are_derived_from_runtime_config():
    tz = get_spec("TIMEZONE")
    assert tz is not None and tz.editable and tz.restart_required
    token = get_spec("TELEGRAM_BOT_TOKEN")
    assert token is not None and not token.editable and not token.restart_required


def test_get_spec_unknown_returns_none():
    assert get_spec("NOT_A_SETTING") is None


@pytest.mark.parametrize(
    "key",
    ["ANTHROPIC_API_KEY", "SIDEKICK_WEB_SESSION_SECRET", "SOME_NEW_TOKEN", "DB_PASSWORD"],
)
def test_is_secret_true(key):
    assert is_secret(key)


@pytest.mark.parametrize("key", ["TIMEZONE", "CLAUDE_MODEL", "SIDEKICK_WEB_HOST"])
def test_is_secret_false(key):
    assert not is_secret(key)


def test_defaults_match_runtime_config_default_timezone():
    spec = config_catalog.get_spec("TIMEZONE")
    assert spec is not None
    assert spec.default == runtime_config.DEFAULT_TIMEZONE
