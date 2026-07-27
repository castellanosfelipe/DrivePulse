"""Create rotating logs whose filter removes active secrets before formatting."""

from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from threading import RLock
from typing import Iterable


class SecretRegistry:
    """Keep sensitive marker values in memory solely for output redaction."""

    def __init__(self) -> None:
        self._values: set[str] = set()
        self._lock = RLock()

    def replace(self, values: Iterable[str]) -> None:
        with self._lock:
            self._values = {value for value in values if value}

    def add(self, value: str) -> None:
        if value:
            with self._lock:
                self._values.add(value)

    def redact(self, text: object) -> str:
        result = str(text)
        with self._lock:
            for value in sorted(self._values, key=len, reverse=True):
                result = result.replace(value, "[REDACTED]")
        return result


SECRET_REGISTRY = SecretRegistry()


class SecretRedactionFilter(logging.Filter):
    """Redact message text and arguments before any handler emits a record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = SECRET_REGISTRY.redact(record.msg)
        if isinstance(record.args, dict):
            record.args = {
                key: SECRET_REGISTRY.redact(value)
                for key, value in record.args.items()
            }
        elif isinstance(record.args, tuple):
            record.args = tuple(SECRET_REGISTRY.redact(value) for value in record.args)
        if record.exc_text:
            record.exc_text = SECRET_REGISTRY.redact(record.exc_text)
        return True


def configure_logging(
    log_dir: Path,
    retention_days: int = 30,
    *,
    console: bool = False,
) -> logging.Logger:
    """Configure the application logger once and return it."""

    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("drivemapper")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s",
        "%Y-%m-%dT%H:%M:%S%z",
    )
    file_handler = TimedRotatingFileHandler(
        log_dir / "agent.log",
        when="midnight",
        backupCount=retention_days,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(SecretRedactionFilter())
    logger.addHandler(file_handler)
    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(SecretRedactionFilter())
        logger.addHandler(stream_handler)
    return logger

