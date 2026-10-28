"""JSON structured logging that never prints secrets or raw chat content."""

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

SAFE_EXTRA = ("job_id", "user_id", "provider", "key_id", "model", "status", "event", "path")
_TOKEN_LIKE = re.compile(r"\b(?:sk|pk|gsk|xai|key|or|ms)-[A-Za-z0-9_\-]{8,}|AIza[0-9A-Za-z_\-]{20,}")
_BEARER = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+")
_ASSIGNMENT = re.compile(
    r"(?i)((?:api[_-]?key|authorization|password|secret|token)[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"
)


def redact(text: str) -> str:
    text = _TOKEN_LIKE.sub("[REDACTED]", text)
    text = _BEARER.sub(r"\1[REDACTED]", text)
    return _ASSIGNMENT.sub(r"\1[REDACTED]", text)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for field in SAFE_EXTRA:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = str(value)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # LiteLLM can echo request payloads at debug level; keep it quiet.
    for noisy in ("LiteLLM", "litellm", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
