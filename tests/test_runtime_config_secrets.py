"""Guard rails: credential-shaped settings must never leave the process raw.

Replaces the old ``_DISPLAYABLE_ENV`` denylist test from the pre-runtime_config
settings page. The invariant is the same: anything that looks like a credential
is redacted whenever settings are rendered or returned over the API.
"""

from __future__ import annotations

import re

from sidekick import runtime_config

_CREDENTIAL_NAME = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD)", re.IGNORECASE)


def test_credential_shaped_editable_keys_are_secret():
    offenders = sorted(
        key
        for key in runtime_config.EDITABLE_KEYS
        if _CREDENTIAL_NAME.search(key) and key not in runtime_config.SECRET_KEYS
    )
    assert offenders == [], f"add these to SECRET_KEYS so they are redacted: {offenders}"


def test_redacted_snapshot_never_contains_secret_values(monkeypatch):
    # The autouse ``isolated_runtime_config`` fixture points the overlay at tmp.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-very-secret-value-1234")
    snapshot = runtime_config.as_dict(redacted=True)
    assert "sk-ant-very-secret-value-1234" not in repr(snapshot)
    assert snapshot["ANTHROPIC_API_KEY"] == {"set": True, "preview": "…1234"}
