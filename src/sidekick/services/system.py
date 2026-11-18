"""System service — runtime status, deployment overview, configuration report.

Framework-free: every function takes the live ``bot_data`` dict (and the
optional webhook delivery log) and returns plain dicts, so the HTML
dashboard, the System page, ``/api/system``, ``/health`` and
``sidekick-cli`` all render the same facts.

Secret redaction happens *here*, not in presentation code: a secret's raw
value never appears in any dict this module returns.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .. import __version__, config_catalog, runtime_config
from ..util import is_loopback_host, run_sync, slack_configured, web_auth_token, web_bind
from ..webhooks import load_webhook_secret

_LLM_PROVIDER_BY_CLASS = {"AnthropicClient": "anthropic", "OllamaClient": "ollama"}


async def status(
    bot_data: dict[str, Any],
    *,
    webhook_log: Any | None = None,
    include_webhook: bool = True,
) -> dict[str, Any]:
    """Component health: scheduler, MCP subprocess, job + tool counts, webhooks.

    ``include_webhook=False`` skips the webhook block (and its secret-file
    read) for callers that don't report it, such as the plain ``/health``.
    """
    scheduler = bot_data.get("scheduler")
    agent = bot_data.get("agent")
    mcp_task = bot_data.get("mcp_task")

    reminder_count = 0
    if scheduler is not None:
        jobs = await run_sync(scheduler.get_jobs)
        reminder_count = len(jobs)

    result: dict[str, Any] = {
        "scheduler": bool(scheduler and getattr(scheduler, "running", False)),
        "mcp": bool(mcp_task and not mcp_task.done()),
        "reminders": reminder_count,
        "tools": len(agent.tools) if agent is not None else 0,
    }
    if include_webhook:
        # A webhook-mode install that never hears from Chronary (tunnel down,
        # endpoint deactivated) would otherwise fail silently.
        last_received = getattr(webhook_log, "last_received_at", None)
        result["webhook"] = {
            # May read the secret file — keep disk I/O off the event loop.
            "configured": await run_sync(load_webhook_secret) is not None,
            "pre_event_source": runtime_config.pre_event_source(),
            "last_received_at": last_received.isoformat() if last_received else None,
        }
    return result


def _llm_info(agent: Any | None) -> dict[str, Any]:
    """The LLM the agent is *actually* using (not just what config says)."""
    llm = getattr(agent, "llm", None) if agent is not None else None
    if llm is None:
        return {"provider": None, "model": None}
    cls = type(llm).__name__
    model = getattr(llm, "model", None)
    return {
        "provider": _LLM_PROVIDER_BY_CLASS.get(cls, cls),
        "model": model if isinstance(model, str) else None,
    }


def _slack_state(bot_data: dict[str, Any]) -> str:
    """``running`` / ``starting`` / ``stopped`` / ``disabled``.

    ``slack_task`` (``bot._run_slack``) finishes as soon as the platform has
    started, so liveness comes from the platform's own connection task.
    """
    platform = bot_data.get("slack_platform")
    if platform is not None:
        return "running" if getattr(platform, "is_running", False) else "stopped"
    if not slack_configured():
        return "disabled"
    task = bot_data.get("slack_task")
    return "starting" if task is not None and not task.done() else "stopped"


def _platforms(bot_data: dict[str, Any]) -> dict[str, str]:
    # Telegram polling health isn't observable from bot_data, so report only
    # whether the adapter was started — never claim it is "running".
    telegram = bot_data.get("telegram_enabled")
    return {
        "telegram": "unknown" if telegram is None else ("enabled" if telegram else "disabled"),
        "slack": _slack_state(bot_data),
    }


def _web_info() -> dict[str, Any]:
    try:
        host, port = web_bind()
        shown_port: int | str = port
    except ValueError:
        host = os.getenv("SIDEKICK_WEB_HOST", "127.0.0.1")
        shown_port = os.getenv("SIDEKICK_WEB_PORT", "")
    return {
        "host": host,
        "port": shown_port,
        "auth_enabled": web_auth_token() is not None,
        "loopback": is_loopback_host(host),
    }


def _paths() -> dict[str, str]:
    # Lazy: these modules pull in apscheduler / the LLM SDKs at import time.
    from ..agent import CONFIG_FILE
    from ..reminders import REMINDERS_FILE
    from ..storage.sqlite_tasks import default_db_path

    return {
        "config_dir": os.path.expanduser(os.getenv("SIDEKICK_CONFIG_DIR", "~/.config/sidekick")),
        "runtime_config": runtime_config.current_path(),
        "database": default_db_path(),
        "reminders_file": REMINDERS_FILE,
        "personality_file": CONFIG_FILE,
    }


def _uptime(started_at: Any, now: datetime) -> tuple[str | None, int | None]:
    if not isinstance(started_at, datetime):
        return None, None
    return started_at.isoformat(), max(0, int((now - started_at).total_seconds()))


async def overview(
    bot_data: dict[str, Any],
    *,
    webhook_log: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Everything the System page / dashboard needs about this deployment."""
    started_iso, uptime_seconds = _uptime(bot_data.get("started_at"), now or datetime.now(UTC))
    return {
        "version": __version__,
        "started_at": started_iso,
        "uptime_seconds": uptime_seconds,
        "status": await status(bot_data, webhook_log=webhook_log),
        "llm": _llm_info(bot_data.get("agent")),
        "platforms": _platforms(bot_data),
        "web": _web_info(),
        "reminders": {
            "chat_configured": bool(os.getenv("REMINDER_CHAT_ID", "").strip()),
            "pre_event_source": runtime_config.pre_event_source(),
            "timezone": runtime_config.timezone_name(),
        },
        "paths": _paths(),
    }


def _redact_url_credentials(value: str) -> str:
    """Mask ``user:pass@`` in URL-shaped values (e.g. an authenticated Ollama URL)."""
    if "://" not in value or "@" not in value:
        return value
    try:
        parts = urlsplit(value)
    except ValueError:
        return value
    if not (parts.username or parts.password):
        return value
    host = parts.hostname or ""
    if parts.port is not None:
        host = f"{host}:{parts.port}"
    return urlunsplit(parts._replace(netloc=f"***@{host}"))


def _secret_state(key: str, value: str | None) -> tuple[bool, str | None]:
    """``(is_set, source_override)`` for secrets that can come from elsewhere."""
    if value:
        return True, None
    if key == "CHRONARY_WEBHOOK_SECRET" and load_webhook_secret() is not None:
        return True, "file"
    return False, None


def _setting_entry(spec: config_catalog.SettingSpec) -> dict[str, Any]:
    value = runtime_config.get(spec.key)
    source = runtime_config.source(spec.key)
    secret = config_catalog.is_secret(spec.key)
    shown: str | None
    if secret:
        shown = None
        is_set, alt_source = _secret_state(spec.key, value)
        if alt_source is not None:
            source = alt_source
        display = "set" if is_set else (spec.unset_display or "not set")
    elif not value:
        # Unset *or* empty: callers use ``get(...) or default``, so the
        # built-in default is what actually applies.
        shown = value
        if spec.default is not None:
            display = spec.default
        elif value == "":
            display = "(empty)"
        else:
            display = spec.unset_display or "not set"
    else:
        shown = _redact_url_credentials(value)
        display = shown
    return {
        "key": spec.key,
        "label": spec.label,
        "description": spec.description,
        "value": shown,
        "display": display,
        "source": source,
        "default": spec.default,
        "editable": spec.editable,
        "secret": secret,
        "restart_required": spec.restart_required,
    }


def config_report() -> list[dict[str, Any]]:
    """Every catalogued setting, grouped in display order, secrets redacted.

    Synchronous and may read the webhook secret file: async callers should
    wrap it in :func:`sidekick.util.run_sync`.
    """
    grouped: dict[str, list[dict[str, Any]]] = {group: [] for group in config_catalog.GROUPS}
    for spec in config_catalog.CATALOG:
        grouped.setdefault(spec.group, []).append(_setting_entry(spec))
    return [{"group": group, "settings": items} for group, items in grouped.items() if items]


def format_uptime(seconds: int | None) -> str:
    """Human-readable uptime (``3d 4h``, ``5h 12m``, ``42s``)."""
    if seconds is None:
        return "unknown"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, secs = divmod(rem, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {secs}s"
    return f"{secs}s"
