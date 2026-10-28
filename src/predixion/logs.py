"""Logging with secret redaction.

Log lines carry run ids, stages, counts, and error kinds. Questions, page
content, and model output are not logged unless LOG_CONTENT is enabled, and
even then known secret shapes and configured key values are masked.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import Any

from .config import Settings

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"tvly-[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\"?\s*[:=]\s*\"?)[^\s\",]{6,}"),
]
_REDACTED = "[redacted]"
_extra_secrets: list[str] = []


def redact(text: str) -> str:
    for secret in _extra_secrets:
        text = text.replace(secret, _REDACTED)
    for pattern in _SECRET_PATTERNS:
        if pattern.groups >= 2:
            text = pattern.sub(lambda m: m.group(1) + m.group(2) + _REDACTED, text)
        else:
            text = pattern.sub(_REDACTED, text)
    return text


class RedactingFormatter(logging.Formatter):
    """One JSON object per line, with secrets masked."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, default=str, ensure_ascii=False))


def configure_logging(settings: Settings) -> None:
    _extra_secrets.clear()
    for secret in (settings.openai_api_key, settings.tavily_api_key):
        if secret is not None and len(secret.get_secret_value()) >= 8:
            _extra_secrets.append(secret.get_secret_value())
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter())
    root = logging.getLogger("predixion")
    root.handlers[:] = [handler]
    root.setLevel(settings.log_level.upper())
    root.propagate = False
    # Third-party HTTP clients can log request lines; keep them quiet.
    for name in ("httpx", "httpcore", "openai"):
        logging.getLogger(name).setLevel(logging.WARNING)


def log(logger: logging.Logger, level: int, msg: str, **fields: Any) -> None:
    logger.log(level, msg, extra={"fields": fields})
