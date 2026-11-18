"""``sidekick-webhook`` — manage the Chronary ``event.reminder`` webhook.

Talks to Chronary directly (not to the running bot). Typical flow once the
dashboard is reachable at a public HTTPS URL (tunnel / reverse proxy)::

    sidekick-webhook register --url https://hooks.example.com/webhooks/chronary
    # the signing secret is saved to $SIDEKICK_CONFIG_DIR/chronary_webhook.secret
    # (0600) — never printed. Paste CHRONARY_WEBHOOK_ID into .env, restart,
    # then set PRE_EVENT_SOURCE=webhook (settings page or .env)
    sidekick-webhook test
    sidekick-webhook status
    sidekick-webhook delete

Chronary refuses private / localhost destinations (the endpoint is
deactivated with ``unsafe_destination_url``), so ``register`` requires an
``https://`` URL.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlparse

from dotenv import load_dotenv

from . import runtime_config
from .web.auth import write_private_file
from .webhooks import REMINDER_EVENT_TYPE, WEBHOOK_PATH, secret_file_path

ClientFactory = Callable[[str], Any]

TEST_POLL_SECONDS = 20


def _default_client(api_key: str) -> Any:
    from chronary import Chronary

    return Chronary(api_key=api_key)


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set (add it to .env or export it).")
    return value


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def cmd_register(client: Any, args: argparse.Namespace) -> int:
    url = args.url.strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        print("--url must be a public https:// URL (Chronary rejects private ones).")
        return 2
    if parsed.path.rstrip("/") != WEBHOOK_PATH:
        print(f"note: Sidekick serves webhooks at {WEBHOOK_PATH}; got path {parsed.path!r}.")

    if os.getenv("CHRONARY_WEBHOOK_ID", "").strip() and not args.force:
        print(
            "CHRONARY_WEBHOOK_ID is already set. Run `sidekick-webhook delete` first, "
            "or pass --force to create another subscription."
        )
        return 2

    webhook = client.webhooks.create(url=url, events=[REMINDER_EVENT_TYPE])
    webhook_id, secret = _get(webhook, "id"), _get(webhook, "secret")

    minutes = runtime_config.get_int("PRE_EVENT_REMINDER_MINUTES", 30) or 0
    calendar_id = os.getenv("CHRONARY_CALENDAR_ID", "").strip()
    if calendar_id and minutes > 0:
        # Chronary fires one event.reminder per offset; make the calendar
        # default match Sidekick's lead time (events without their own
        # `reminders` inherit it).
        client.calendars.update(calendar_id, default_reminders=[minutes])
        print(f"Calendar {calendar_id}: default reminder set to {minutes} minutes.")

    # Chronary returns the signing secret exactly once. Store it owner-only
    # rather than printing it, so it never ends up in scrollback or logs;
    # the server reads this file when CHRONARY_WEBHOOK_SECRET is unset.
    secret_path = secret_file_path()
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    write_private_file(secret_path, str(secret).encode("utf-8"))

    print(f"Registered webhook {webhook_id} -> {url}")
    print(f"Signing secret saved to {secret_path} (mode 0600).")
    print()
    print("Add this to your .env:")
    print(f"  CHRONARY_WEBHOOK_ID={webhook_id}")
    print()
    print("Then restart Sidekick and set PRE_EVENT_SOURCE=webhook (settings page or .env).")
    return 0


def cmd_status(client: Any, _args: argparse.Namespace) -> int:
    webhook_id = _require_env("CHRONARY_WEBHOOK_ID")
    webhook = client.webhooks.get(webhook_id)
    print(f"Webhook {webhook_id}")
    print(f"  url:     {_get(webhook, 'url')}")
    print(f"  events:  {', '.join(_get(webhook, 'events') or [])}")
    print(f"  active:  {_get(webhook, 'active')}")
    reason = _get(webhook, "deactivated_reason")
    if reason:
        print(f"  deactivated: {reason}")
    deliveries = client.webhooks.list_deliveries(webhook_id, limit=5)
    rows = _get(deliveries, "data") or []
    print(f"  recent deliveries: {len(rows)}")
    for row in rows:
        print(
            f"    {_get(row, 'created_at')}  {_get(row, 'event_type')}  "
            f"{_get(row, 'status')}  attempts={_get(row, 'attempts')}"
        )
    return 0 if _get(webhook, "active") else 1


def cmd_test(
    client: Any, _args: argparse.Namespace, *, sleep: Callable[[float], None] = time.sleep
) -> int:
    webhook_id = _require_env("CHRONARY_WEBHOOK_ID")
    sent = client.webhooks.send_test(webhook_id, event_type=REMINDER_EVENT_TYPE)
    delivery_id = _get(sent, "delivery_id")
    print(f"Test delivery {delivery_id} queued; waiting for the result...")
    deadline = time.monotonic() + TEST_POLL_SECONDS
    status = "pending"
    detail: Any = None
    while time.monotonic() < deadline:
        detail = client.webhooks.get_delivery(webhook_id, delivery_id)
        status = _get(detail, "status", "pending")
        if status != "pending":
            break
        sleep(1)
    code = _get(detail, "last_response_status")
    error = _get(detail, "last_error_code")
    print(f"  status: {status}  http: {code}  error: {error or '-'}")
    return 0 if status == "delivered" else 1


def cmd_delete(client: Any, _args: argparse.Namespace) -> int:
    webhook_id = _require_env("CHRONARY_WEBHOOK_ID")
    client.webhooks.delete(webhook_id)
    secret_file_path().unlink(missing_ok=True)
    print(f"Deleted webhook {webhook_id} and its stored signing secret.")
    print("Remove CHRONARY_WEBHOOK_ID (and CHRONARY_WEBHOOK_SECRET, if you set it) from .env")
    print("and set PRE_EVENT_SOURCE=poll so the 5-minute check takes over again.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sidekick-webhook", description="Manage Sidekick's Chronary reminder webhook."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    reg = sub.add_parser("register", help="create the event.reminder subscription")
    reg.add_argument("--url", required=True, help=f"public https URL ending in {WEBHOOK_PATH}")
    reg.add_argument("--force", action="store_true", help="register even if one is configured")
    sub.add_parser("status", help="show the subscription and recent deliveries")
    sub.add_parser("test", help="send a signed test event.reminder and report the result")
    sub.add_parser("delete", help="delete the subscription")
    return parser


COMMANDS: dict[str, Callable[[Any, argparse.Namespace], int]] = {
    "register": cmd_register,
    "status": cmd_status,
    "test": cmd_test,
    "delete": cmd_delete,
}


def main(argv: Sequence[str] | None = None, *, client_factory: ClientFactory | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    client = (client_factory or _default_client)(_require_env("CHRONARY_API_KEY"))
    return COMMANDS[args.command](client, args)


def entrypoint() -> None:
    sys.exit(main())
