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
            import win32evtlog
            import win32evtlogutil

            event_type = win32evtlog.EVENTLOG_INFORMATION_TYPE
            if level == "Error":
                event_type = win32evtlog.EVENTLOG_ERROR_TYPE
            elif level == "Warning":
                event_type = win32evtlog.EVENTLOG_WARNING_TYPE
            win32evtlogutil.ReportEvent(
                "DriveMapper",
                1,
                eventType=event_type,
                strings=[message],
            )
        except (ImportError, OSError) as error:
            self.logger.warning(
                "No se pudo publicar en Event Log: %s", error
            )
