"""Declarative catalog of every setting Sidekick reads.

Pure metadata — no I/O and no reads of the environment. This is the one
place that documents each environment variable (group, label, default,
whether it is a secret) so presentation layers (the System page, the
settings UI, ``sidekick-cli``) never hard-code that knowledge.

Editability and restart semantics are *derived* from
:mod:`sidekick.runtime_config` instead of being duplicated here; tests
assert the two stay consistent (every editable key and every
``runtime_config.SECRET_KEYS`` member must be catalogued, secrets flagged).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from . import runtime_config

# Display order of groups on the System page.
GROUPS: Final[tuple[str, ...]] = (
    "LLM",
    "Calendar",
    "Reminders",
    "Telegram",
    "Slack",
    "Web dashboard",
    "Storage",
    "Limits",
    "CLI",
)

# Name fragments that mark a key as secret even when it isn't catalogued —
# defense in depth so an unknown credential-shaped key is never displayed.
_SECRET_MARKERS: Final[tuple[str, ...]] = ("KEY", "TOKEN", "SECRET", "PASSWORD")


@dataclass(frozen=True)
class SettingSpec:
    """Static description of one setting."""

    key: str
    group: str
    label: str
    description: str
    default: str | None = None
    secret: bool = False
    # Shown instead of "not set" when the value is absent but something else
    # covers it (e.g. a generated secret file, a fallback key).
    unset_display: str | None = None

    @property
    def editable(self) -> bool:
        return self.key in runtime_config.EDITABLE_KEYS

    @property
    def restart_required(self) -> bool:
        return self.key in runtime_config.RESTART_REQUIRED_KEYS


_CFG = "~/.config/sidekick"
_IN_CFG = "$SIDEKICK_CONFIG_DIR"  # state files default to this dir (see paths.py)

CATALOG: Final[tuple[SettingSpec, ...]] = (
    # --- LLM ---------------------------------------------------------------
    SettingSpec("LLM_PROVIDER", "LLM", "Provider", "anthropic or ollama.", "anthropic"),
    SettingSpec(
        "ANTHROPIC_API_KEY",
        "LLM",
        "Anthropic API key",
        "Used when the provider is anthropic.",
        secret=True,
    ),
    SettingSpec(
        "CLAUDE_MODEL", "LLM", "Claude model", "Anthropic model id.", "claude-haiku-4-5-20251001"
    ),
    SettingSpec(
        "OLLAMA_BASE_URL", "LLM", "Ollama URL", "Ollama server address.", "http://localhost:11434"
    ),
    SettingSpec("OLLAMA_MODEL", "LLM", "Ollama model", "Model tag to run.", "llama3.1:8b"),
    SettingSpec(
        "OLLAMA_NUM_CTX",
        "LLM",
        "Ollama context",
        "Context window (num_ctx); blank = model default.",
    ),
    SettingSpec(
        "OLLAMA_NUM_GPU", "LLM", "Ollama GPU layers", "num_gpu; blank = auto, 0 = CPU only."
    ),
    SettingSpec(
        "OLLAMA_KEEP_ALIVE", "LLM", "Ollama keep-alive", "How long the model stays loaded."
    ),
    # --- Calendar ----------------------------------------------------------
    SettingSpec(
        "CHRONARY_API_KEY",
        "Calendar",
        "Chronary API key",
        "Calendar backend credential.",
        secret=True,
    ),
    SettingSpec("CHRONARY_AGENT_ID", "Calendar", "Agent id", "Set by sidekick-init."),
    SettingSpec("CHRONARY_CALENDAR_ID", "Calendar", "Calendar id", "Set by sidekick-init."),
    SettingSpec(
        "CHRONARY_WEBHOOK_ID", "Calendar", "Webhook id", "Printed by sidekick-webhook register."
    ),
    SettingSpec(
        "CHRONARY_WEBHOOK_SECRET",
        "Calendar",
        "Webhook secret",
        "Overrides the secret file written by sidekick-webhook register.",
        secret=True,
    ),
    # --- Reminders ---------------------------------------------------------
    SettingSpec(
        "TIMEZONE",
        "Reminders",
        "Timezone",
        "IANA zone for schedules and calendar days.",
        runtime_config.DEFAULT_TIMEZONE,
    ),
    SettingSpec(
        "REMINDER_CHAT_ID",
        "Reminders",
        "Reminder chat",
        "Telegram chat that receives reminders; unset disables delivery.",
    ),
    SettingSpec(
        "SIDEKICK_ANNOUNCE_UPDATES",
        "Reminders",
        "Announce updates",
        "Post the new version and its changes to the reminder chat after a deploy.",
        "true",
    ),
    SettingSpec(
        "SIDEKICK_UPDATE_REPO",
        "Reminders",
        "Update notes repo",
        "GitHub owner/repo whose commits list what changed between versions.",
        "jaypetez/sidekick",
    ),
    SettingSpec(
        "MORNING_REMINDER_TIME", "Reminders", "Morning summary", "HH:MM, 24-hour.", "07:30"
    ),
    SettingSpec(
        "PRE_EVENT_REMINDER_MINUTES",
        "Reminders",
        "Pre-event lead",
        "Minutes before an event; 0 turns it off.",
        "30",
    ),
    SettingSpec("PRE_EVENT_SOURCE", "Reminders", "Pre-event source", "poll or webhook.", "poll"),
    # --- Telegram ----------------------------------------------------------
    SettingSpec(
        "TELEGRAM_BOT_TOKEN",
        "Telegram",
        "Bot token",
        "Unset runs Sidekick in web-only mode.",
        secret=True,
    ),
    SettingSpec(
        "TELEGRAM_ALLOWED_USER_IDS",
        "Telegram",
        "Allowed users",
        "Comma-separated user ids allowed to talk to the bot.",
    ),
    # --- Slack -------------------------------------------------------------
    SettingSpec("SLACK_BOT_TOKEN", "Slack", "Bot token", "xoxb- token.", secret=True),
    SettingSpec("SLACK_APP_TOKEN", "Slack", "App token", "xapp- socket-mode token.", secret=True),
    SettingSpec(
        "SLACK_ALLOWED_USER_IDS", "Slack", "Allowed users", "Comma-separated Slack user ids."
    ),
    SettingSpec(
        "SLACK_ALLOWED_CHANNELS", "Slack", "Allowed channels", "Comma-separated channel ids."
    ),
    # --- Web dashboard -----------------------------------------------------
    SettingSpec("SIDEKICK_WEB_ENABLED", "Web dashboard", "Enabled", "false skips it.", "true"),
    SettingSpec("SIDEKICK_WEB_HOST", "Web dashboard", "Bind host", "Interface.", "127.0.0.1"),
    SettingSpec("SIDEKICK_WEB_PORT", "Web dashboard", "Bind port", "TCP port.", "8080"),
    SettingSpec(
        "SIDEKICK_WEB_AUTH_TOKEN",
        "Web dashboard",
        "Auth token",
        "Required for non-loopback binds.",
        secret=True,
    ),
    SettingSpec(
        "SIDEKICK_WEB_SESSION_SECRET",
        "Web dashboard",
        "Session secret",
        "Cookie encryption key; generated and stored when unset.",
        secret=True,
        unset_display="auto-generated (web_session.secret)",
    ),
    SettingSpec(
        "SIDEKICK_WEB_ALLOWED_HOSTS",
        "Web dashboard",
        "Allowed hosts",
        "Extra Host header names accepted (DNS-rebinding guard).",
    ),
    SettingSpec(
        "SIDEKICK_WEB_TRUST_PROXY",
        "Web dashboard",
        "Trust proxy",
        "Honor X-Forwarded-For.",
        "false",
    ),
    # --- Storage -----------------------------------------------------------
    SettingSpec("SIDEKICK_CONFIG_DIR", "Storage", "Config dir", "State directory.", _CFG),
    SettingSpec(
        "SIDEKICK_DB_PATH", "Storage", "Database", "Tasks SQLite file.", f"{_IN_CFG}/sidekick.db"
    ),
    SettingSpec(
        "SIDEKICK_RUNTIME_CONFIG",
        "Storage",
        "Runtime overrides",
        "Settings-page overrides file.",
        f"{_IN_CFG}/runtime.json",
    ),
    SettingSpec(
        "REMINDERS_FILE",
        "Storage",
        "Reminders file",
        "Custom reminders.",
        f"{_IN_CFG}/reminders.json",
    ),
    SettingSpec(
        "CONFIG_FILE", "Storage", "Personality file", "Personality state.", f"{_IN_CFG}/config.json"
    ),
    # --- Limits ------------------------------------------------------------
    SettingSpec(
        "SIDEKICK_RATE_LIMIT_MAX", "Limits", "Messages per window", "Per-chat rate limit.", "10"
    ),
    SettingSpec(
        "SIDEKICK_RATE_LIMIT_WINDOW_SECONDS", "Limits", "Window (s)", "Rate-limit window.", "60"
    ),
    # --- CLI ---------------------------------------------------------------
    SettingSpec(
        "SIDEKICK_API_URL",
        "CLI",
        "API URL",
        "sidekick-cli target.",
        "http://127.0.0.1:$SIDEKICK_WEB_PORT",
    ),
    SettingSpec(
        "SIDEKICK_API_TOKEN",
        "CLI",
        "API token",
        "sidekick-cli bearer; falls back to the web auth token.",
        secret=True,
        unset_display="falls back to the web auth token",
    ),
)

_BY_KEY: Final[dict[str, SettingSpec]] = {spec.key: spec for spec in CATALOG}


def get_spec(key: str) -> SettingSpec | None:
    """Return the catalog entry for ``key``, or ``None`` if uncatalogued."""
    return _BY_KEY.get(key)


def is_secret(key: str) -> bool:
    """True if ``key``'s value must never be displayed.

    Catalogued secrets, ``runtime_config.SECRET_KEYS``, and — defensively —
    any key whose name looks like a credential.
    """
    spec = _BY_KEY.get(key)
    if spec is not None and spec.secret:
        return True
    if key in runtime_config.SECRET_KEYS:
        return True
    upper = key.upper()
    return any(marker in upper for marker in _SECRET_MARKERS)
