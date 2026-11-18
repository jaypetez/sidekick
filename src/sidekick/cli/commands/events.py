"""`sidekick-cli events ...` — talks to /api/events."""

from __future__ import annotations

import argparse
from typing import Any
from urllib.parse import quote

from ..client import ApiClient
from ..format import emit_json, emit_kv, emit_table


def register(parent: argparse._SubParsersAction[Any]) -> None:
    p = parent.add_parser("events", help="manage calendar events")
    sub = p.add_subparsers(dest="action", required=True)

    listp = sub.add_parser("list", help="list upcoming events")
    listp.add_argument("--days", type=int, default=14, help="window in days (1..90)")
    listp.set_defaults(handler=_list)

    add = sub.add_parser("add", help="add a new event")
    add.add_argument("--summary", required=True)
    add.add_argument("--start", required=True, help="ISO 8601 datetime")
    add.add_argument("--end", required=True, help="ISO 8601 datetime")
    add.add_argument("--description")
    add.add_argument("--location")
    add.set_defaults(handler=_add)

    rm = sub.add_parser("rm", help="delete an event by id")
    rm.add_argument("event_id")
    rm.set_defaults(handler=_rm)


def _list(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.get("/api/events", params={"days": args.days})
    if args.json:
        emit_json(data)
        return
    emit_table(data.get("events", []), ["id", "summary", "start", "end", "location"])


def _add(client: ApiClient, args: argparse.Namespace) -> None:
    body: dict[str, Any] = {
        "summary": args.summary,
        "start_datetime": args.start,
        "end_datetime": args.end,
    }
    if args.description:
        body["description"] = args.description
    if args.location:
        body["location"] = args.location
    data = client.post("/api/events", json_body=body)
    if args.json:
        emit_json(data)
        return
    emit_kv(data)


def _rm(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.delete(f"/api/events/{quote(args.event_id)}")
    if args.json:
        emit_json(data)
        return
    emit_kv(data)
