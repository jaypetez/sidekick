"""Logging setup with a redaction filter for accidentally-logged secrets.

Installs a logging filter on the root logger that scans both the format
string and every argument for substrings matching common secret patterns
(``api_key=...``, ``token: ...``, ``password=...``, ``secret=...``) and
replaces the value with ``[REDACTED]``.

This is defense-in-depth: code should not log secrets in the first place,
but a stray ``logger.info("payload=%s", payload)`` should never reveal a
bearer token to anyone tailing logs.
"""

from __future__ import annotations

import logging
import re

_SECRET_RE = re.compile(
    r"(?i)(api[-_]?key|token|secret|password|authorization|bearer)"
    r"(\s*[:=]\s*|\s+)"
    r"(['\"]?)([^\s'\",;]+)\3"
)

_MAX_STR_LEN = 200


def _redact(text: str) -> str:
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", text)


def safe_repr(value: object) -> str:
    """Return a redacted, length-bounded repr of *value* for logging."""
    s = value if isinstance(value, str) else repr(value)
    s = _redact(s)
    if len(s) > _MAX_STR_LEN:
        s = s[:_MAX_STR_LEN] + "...[truncated]"
    return s


class RedactionFilter(logging.Filter):
    """Logging filter that scrubs secret patterns from messages and args."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _redact(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _redact_arg(v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(_redact_arg(a) for a in record.args)
        return True


def _redact_arg(value: object) -> object:
    if isinstance(value, str):
        return _redact(value)
    return value


def install_redaction_filter() -> None:
    """Attach the redaction filter to the root logger and all its handlers.

    The filter is attached both to the root logger (in case handlers are
    added later) and to every existing root handler (because logger-level
    filters do not apply to records that arrive via propagation from
    child loggers — only handler-level filters do).
    """
    flt = RedactionFilter()
    root = logging.getLogger()
    if not any(isinstance(f, RedactionFilter) for f in root.filters):
        root.addFilter(flt)
    for handler in root.handlers:
        if not any(isinstance(f, RedactionFilter) for f in handler.filters):
            handler.addFilter(flt)
