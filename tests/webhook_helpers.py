"""Build Chronary-style signed webhook deliveries for tests.

Mirrors chronary.webhook._compute_signature: ``sha256=`` + hex HMAC-SHA256
of ``f"{timestamp}." + body`` keyed with the raw secret string.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any

SECRET = "whsec_test_secret_value"
CALENDAR_ID = "cal_ours"


def reminder_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "event_id": "evt_1",
        "calendar_id": CALENDAR_ID,
        "title": "Strategy sync",
        "start_time": "2026-04-17T14:00:00Z",
        "end_time": "2026-04-17T14:30:00Z",
        "reminder_minutes": 10,
    }
    payload.update(overrides)
    return payload


def signed(
    payload: dict[str, Any] | bytes,
    *,
    secret: str = SECRET,
    event_type: str = "event.reminder",
    delivery_id: str | None = "whd_1",
    timestamp: int | None = None,
    test: bool = False,
) -> tuple[bytes, dict[str, str]]:
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    ts = str(int(time.time()) if timestamp is None else timestamp)
    digest = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "X-Timestamp": ts,
        "X-Signature": f"sha256={digest}",
        "X-Chronary-Event-Type": event_type,
    }
    if delivery_id is not None:
        headers["X-Delivery-Id"] = delivery_id
    if test:
        headers["X-Chronary-Test"] = "1"
    return body, headers
