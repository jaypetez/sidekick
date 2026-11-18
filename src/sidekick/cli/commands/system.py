"""`sidekick-cli system ...` — talks to /api/system and /api/config."""

from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient
from ..format import emit_json, emit_kv, emit_table, emit_text


def register(parent: argparse._SubParsersAction[Any]) -> None:
    p = parent.add_parser("system", help="inspect the running bot's status and configuration")
    sub = p.add_subparsers(dest="action", required=True)

    s = sub.add_parser("status", help="version, uptime, components, LLM, platforms")
    s.set_defaults(handler=_status)

    c = sub.add_parser("config", help="every known setting with its source (secrets redacted)")
    c.add_argument("--group", help="only show one group (e.g. LLM, Reminders)")
    c.set_defaults(handler=_config)


def _status(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.get("/api/system")
    if args.json:
        emit_json(data)
        return
    status = data.get("status", {})
    llm = data.get("llm", {})
    platforms = data.get("platforms", {})
    web = data.get("web", {})
    emit_kv(
        {
            "version": data.get("version"),
            "uptime_seconds": data.get("uptime_seconds"),
            "scheduler": "running" if status.get("scheduler") else "stopped",
            "mcp": "up" if status.get("mcp") else "down",
            "jobs": status.get("reminders"),
            "tools": status.get("tools"),
            "llm": f"{llm.get('provider') or '-'} · {llm.get('model') or '-'}",
            "telegram": platforms.get("telegram"),
            "slack": platforms.get("slack"),
            "web": f"{web.get('host')}:{web.get('port')}"
            + (" (auth)" if web.get("auth_enabled") else ""),
        }
    )


def _config(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.get("/api/config")
    groups = data.get("groups", [])
    if args.group:
        wanted = args.group.lower()
        groups = [g for g in groups if str(g.get("group", "")).lower() == wanted]
    if args.json:
        emit_json({"groups": groups})
        return
    if not groups:
        emit_text("(no matching group)")
        return
    rows = [
        {
            "group": g.get("group"),
            "key": s.get("key"),
            "value": s.get("display"),
            "source": s.get("source"),
            "editable": s.get("editable"),
        }
        for g in groups
        for s in g.get("settings", [])
    ]
    emit_table(rows, ["group", "key", "value", "source", "editable"])
