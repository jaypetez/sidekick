"""`sidekick-cli tasks ...` — talks to /api/tasks."""

from __future__ import annotations

import argparse
from typing import Any
from urllib.parse import quote

from ..client import ApiClient
from ..format import emit_json, emit_kv, emit_table, emit_text


def register(parent: argparse._SubParsersAction[Any]) -> None:
    p = parent.add_parser("tasks", help="manage task lists")
    sub = p.add_subparsers(dest="action", required=True)

    sub.add_parser("list", help="list all task lists with open counts").set_defaults(handler=_list)

    show = sub.add_parser("show", help="show items in a list")
    show.add_argument("list_name")
    show.set_defaults(handler=_show)

    add = sub.add_parser("add", help="add one or more items to a list")
    add.add_argument("list_name")
    add.add_argument("title", nargs="+", help="title(s) to add")
    add.set_defaults(handler=_add)

    complete = sub.add_parser("complete", help="mark an item complete")
    complete.add_argument("list_name")
    complete.add_argument("title")
    complete.set_defaults(handler=_complete)

    delete = sub.add_parser("delete", help="delete an item or the whole list")
    delete.add_argument("list_name")
    delete.add_argument("--item", help="if given, delete this item instead of the whole list")
    delete.set_defaults(handler=_delete)

    clear = sub.add_parser("clear-completed", help="remove completed items from a list")
    clear.add_argument("list_name")
    clear.set_defaults(handler=_clear_completed)


def _list(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.get("/api/tasks")
    if args.json:
        emit_json(data)
        return
    emit_table(data.get("lists", []), ["name", "open_count"])


def _show(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.get(f"/api/tasks/{quote(args.list_name)}")
    if args.json:
        emit_json(data)
        return
    emit_text(f"List: {data['name']}")
    emit_table(data.get("items", []), ["title", "status"])


def _add(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.post(
        f"/api/tasks/{quote(args.list_name)}/items", json_body={"titles": args.title}
    )
    if args.json:
        emit_json(data)
        return
    emit_text(f"Added {len(data.get('added', []))} item(s) to {args.list_name}.")


def _complete(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.post(f"/api/tasks/{quote(args.list_name)}/items/{quote(args.title)}/complete")
    if args.json:
        emit_json(data)
        return
    emit_kv(data)


def _delete(client: ApiClient, args: argparse.Namespace) -> None:
    if args.item:
        data = client.delete(f"/api/tasks/{quote(args.list_name)}/items/{quote(args.item)}")
    else:
        data = client.delete(f"/api/tasks/{quote(args.list_name)}")
    if args.json:
        emit_json(data)
        return
    emit_kv(data)


def _clear_completed(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.post(f"/api/tasks/{quote(args.list_name)}/clear-completed")
    if args.json:
        emit_json(data)
        return
    emit_text(f"Cleared completed items in {args.list_name}.")
