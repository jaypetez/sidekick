"""`sidekick-cli chat ...` — talks to /api/chat."""

from __future__ import annotations

import argparse
from typing import Any

from ..client import ApiClient
from ..format import emit_json, emit_text


def register(parent: argparse._SubParsersAction[Any]) -> None:
    p = parent.add_parser("chat", help="talk to the agent from the terminal")
    sub = p.add_subparsers(dest="action", required=True)

    send = sub.add_parser("send", help="send a single message and print the reply")
    send.add_argument("text")
    send.add_argument(
        "--chat-id",
        dest="chat_id",
        default="cli:default",
        help="conversation id; defaults to a CLI-scoped id so it stays separate from the web chat",
    )
    send.set_defaults(handler=_send)

    reset = sub.add_parser("reset", help="clear the CLI's conversation history")
    reset.add_argument("--chat-id", dest="chat_id", default="cli:default")
    reset.set_defaults(handler=_reset)

    history = sub.add_parser("history", help="print the conversation log")
    history.add_argument("--chat-id", dest="chat_id", default="cli:default")
    history.set_defaults(handler=_history)


def _send(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.post("/api/chat", json_body={"text": args.text, "chat_id": args.chat_id})
    if args.json:
        emit_json(data)
        return
    emit_text(data.get("assistant", ""))


def _reset(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.post("/api/chat/reset", json_body={"chat_id": args.chat_id})
    if args.json:
        emit_json(data)
        return
    emit_text(f"Reset {data.get('chat_id')}")


def _history(client: ApiClient, args: argparse.Namespace) -> None:
    data = client.get("/api/chat", params={"chat_id": args.chat_id})
    if args.json:
        emit_json(data)
        return
    for pair in data.get("messages", []):
        if pair.get("user"):
            emit_text(f"you> {pair['user']}")
        if pair.get("assistant"):
            emit_text(f"bot> {pair['assistant']}")
