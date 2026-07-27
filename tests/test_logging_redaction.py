"""Demonstrate that marker secrets never reach a configured handler."""

from __future__ import annotations

import logging

from app.logging_setup import SECRET_REGISTRY, SecretRedactionFilter


class CaptureHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def test_redacts_message_and_arguments() -> None:
    secret = "do-not-write-this-value"
    SECRET_REGISTRY.replace([secret])
    logger = logging.getLogger("test-redaction")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(logging.INFO)
    handler = CaptureHandler()
    handler.addFilter(SecretRedactionFilter())
    logger.addHandler(handler)
    logger.info("password=%s direct=%s", secret, secret)
    assert handler.messages == ["password=[REDACTED] direct=[REDACTED]"]
    assert secret not in handler.messages[0]

