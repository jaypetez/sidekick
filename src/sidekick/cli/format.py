"""Tiny rendering helpers for the CLI.

Everything goes through ``stdout``. ``--json`` short-circuits the
pretty-print and emits the raw envelope data so the CLI is scriptable.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def emit_json(data: Any) -> None:
    json.dump(data, sys.stdout, indent=2, default=str, sort_keys=True)
    sys.stdout.write("\n")


def emit_table(rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Plain-text table — pure stdlib, no rich dependency."""
    if not rows:
        sys.stdout.write("(no rows)\n")
        return
    widths = {c: len(c) for c in columns}
    for row in rows:
        for c in columns:
            widths[c] = max(widths[c], len(_stringify(row.get(c))))
    header = "  ".join(c.ljust(widths[c]) for c in columns)
    sys.stdout.write(header + "\n")
    sys.stdout.write("  ".join("-" * widths[c] for c in columns) + "\n")
    for row in rows:
        line = "  ".join(_stringify(row.get(c)).ljust(widths[c]) for c in columns)
        sys.stdout.write(line + "\n")


def emit_kv(data: dict[str, Any]) -> None:
    if not data:
        sys.stdout.write("(empty)\n")
        return
    width = max(len(k) for k in data)
    for key in sorted(data):
        sys.stdout.write(f"{key.ljust(width)}  {_stringify(data[key])}\n")


def emit_text(text: str) -> None:
    sys.stdout.write(text)
    if not text.endswith("\n"):
        sys.stdout.write("\n")


def _stringify(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, str):
        return value
    if isinstance(value, dict | list):
        return json.dumps(value, default=str, sort_keys=True)
    return str(value)
