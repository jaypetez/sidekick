"""`sidekick-cli reminders ...` — talks to /api/reminders."""

from __future__ import annotations

import argparse
from typing import Any
from urllib.parse import quote

from ..client import ApiClient
from ..format import emit_json, emit_kv, emit_table


def register(parent: argparse._SubParsersAction[Any]) -> None:
    p = parent.add_parser("reminders", help="manage scheduled reminders")
    sub = p.add_subparsers(dest="action", required=True)

    sub.add_parser("list", help="list active and disabled reminders").set_defaults(handler=_list)

    add = sub.add_parser("add", help="add a new recurring reminder")
    add.add_argument("--message", required=True)
    add.add_argument("--hour", type=int, required=True)
    add.add_argument("--minute", type=int, required=True)
    add.add_argument(
        "--day-of-week",
        dest="day_of_week",
        help="e.g. 'mon,wed,fri' or 'sun'. Omit for daily.",
    )
    add.add_argument("--chat-id", type=int, default=0, dest="chat_id")
    add.set_defaults(handler=_add)

    rm = sub.add_parser("rm", help="remove a custom reminder")
    rm.add_argument("reminder_id")
    rm.set_defaults(handler=_rm)


def _list(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.get("/api/reminders")
    if args.json:
        emit_json(data)
        return
    emit_table(data.get("reminders", []), ["id", "name", "type", "paused", "next_run"])


def _add(client: ApiClient, args: argparse.Namespace) -> None:
    body = {
        "message": args.message,
        "hour": args.hour,
        "minute": args.minute,
        "chat_id": args.chat_id,
    }
    if args.day_of_week:
        body["day_of_week"] = args.day_of_week
    data = client.post("/api/reminders", json_body=body)
    if args.json:
        emit_json(data)
        return
    emit_kv(data)


def _rm(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.delete(f"/api/reminders/{quote(args.reminder_id)}")
    if args.json:
        emit_json(data)
        return
    emit_kv(data)
