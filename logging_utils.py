import json
import logging
import os
from datetime import datetime
from typing import Optional

_CONFIGURED = False
_DEFAULT_LOGGER_NAME = "podcast_generation_workflow"
_RESERVED_LOG_RECORD_FIELDS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
    "message",
    "event",
}


class JsonFormatter(logging.Formatter):
    """Render log records as json payloads."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.utcnow().isoformat(timespec="milliseconds") + "Z",
            "event": getattr(record, "event", record.getMessage()),
            "severity": record.levelname,
            "logger": record.name,
        }

        message = getattr(record, "message", None) or record.getMessage()
        if message and message != payload["event"]:
            payload["message"] = message

        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_FIELDS:
                continue
            if key.startswith("_"):
                continue
            payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(level: Optional[str] = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    log_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(numeric_level)
    root.addHandler(handler)

    logging.captureWarnings(True)
    _CONFIGURED = True


def get_logger(name: str = _DEFAULT_LOGGER_NAME) -> logging.Logger:
    configure_logging()
    return logging.getLogger(name)


def _sanitize_fields(fields: dict) -> dict:
    sanitized = {}
    for key, value in fields.items():
        safe_key = str(key)
        if safe_key in _RESERVED_LOG_RECORD_FIELDS:
            safe_key = f"field_{safe_key}"
        sanitized[safe_key] = value
    return sanitized


def _log(level: int, event: str, message: Optional[str] = None, logger: Optional[logging.Logger] = None, **fields) -> None:
    log = logger or get_logger()
    extra_fields = _sanitize_fields(fields)
    log.log(level, message or event, extra={"event": event, **extra_fields})


def log_info(event: str, message: Optional[str] = None, logger: Optional[logging.Logger] = None, **fields) -> None:
    _log(logging.INFO, event, message, logger, **fields)


def log_warning(event: str, message: Optional[str] = None, logger: Optional[logging.Logger] = None, **fields) -> None:
    _log(logging.WARNING, event, message, logger, **fields)


def log_error(event: str, message: Optional[str] = None, logger: Optional[logging.Logger] = None, **fields) -> None:
    _log(logging.ERROR, event, message, logger, **fields)
