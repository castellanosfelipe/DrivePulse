"""Publish state transitions to Windows Event Log without making it mandatory."""

from __future__ import annotations

import logging


class EventLogPublisher:
    """Write pre-registered DriveMapper events and degrade safely if unavailable."""

    def __init__(self, enabled: bool, logger: logging.Logger) -> None:
        self.enabled = enabled
        self.logger = logger

    def publish(self, level: str, message: str) -> None:
        if not self.enabled:
            return
        try:
            import servicemanager

            if level == "Error":
                servicemanager.LogErrorMsg(message)
            elif level == "Warning":
                servicemanager.LogWarningMsg(message)
            else:
                servicemanager.LogInfoMsg(message)
        except (ImportError, OSError) as error:
            self.logger.warning(
                "No se pudo publicar en Event Log: %s", error
            )

