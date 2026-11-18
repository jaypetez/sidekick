"""`sidekick-cli settings ...` — talks to /api/settings."""

from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient
from ..format import emit_json, emit_kv, emit_text


def register(parent: argparse._SubParsersAction[Any]) -> None:
    p = parent.add_parser("settings", help="read and edit runtime settings")
    sub = p.add_subparsers(dest="action", required=True)

    g = sub.add_parser("get", help="show current effective settings (secrets redacted)")
    g.set_defaults(handler=_get)

    s = sub.add_parser("set", help="set one editable key")
    s.add_argument("key")
    s.add_argument("value", help='use an empty string ("") to clear the override')
    s.set_defaults(handler=_set)

    t = sub.add_parser("test-llm", help="probe the current LLM config end-to-end")
    t.set_defaults(handler=_test_llm)


def _flatten(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Render the redacted snapshot as a flat string map for emit_kv."""
    out: dict[str, Any] = {}
    for key, val in snapshot.items():
        if isinstance(val, dict) and "set" in val:
            out[key] = f"set ({val.get('preview') or 'redacted'})" if val.get("set") else "(unset)"
        else:
            out[key] = val if val else "(unset)"
    return out


def _get(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.get("/api/settings")
    if args.json:
        emit_json(data)
        return
    emit_kv(_flatten(data.get("settings", {})))


def _set(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.patch("/api/settings", json_body={args.key: args.value})
    if args.json:
        emit_json(data)
        return
    summary = f"Saved {len(data.get('applied', []))} change(s)"
    if data.get("llm_reloaded"):
        summary += " · LLM reloaded"
    emit_text(summary)
    emit_kv(_flatten(data.get("settings", {})))


def _test_llm(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.post("/api/settings/test-llm", json_body={})
    if args.json:
        emit_json(data)
        return
    emit_text(
        f"OK · provider={data.get('provider')} · model={data.get('model')}\n"
        f"reply: {data.get('reply')}"
    )
