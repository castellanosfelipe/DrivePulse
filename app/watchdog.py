"""Run continuous convergence with persistent backoff and clean shutdown behavior."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path

from app.db import StateDatabase
from app.errors import ErrorDisposition
from app.models import DriveScope, DriveSpec
from app.platform.signals import token
from app.reconciler import Reconciler
from app.settings_store import SettingsStore


def fingerprint(drive: DriveSpec) -> str:
    """Hash retry-relevant encrypted configuration without exposing a secret."""

    payload = "|".join(
        [drive.unc, drive.username, drive.secret, drive.letter, str(drive.enabled)]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class Watchdog:
    """Repeatedly reconcile and stop retries that could lock the shared account."""

    def __init__(
        self,
        store: SettingsStore,
        database: StateDatabase,
        reconciler: Reconciler,
        signal_path: Path,
        heartbeat_path: Path,
        logger: logging.Logger,
        *,
        scope: DriveScope = DriveScope.SYSTEM,
        target_user: str = "",
    ) -> None:
        self.store = store
        self.database = database
        self.reconciler = reconciler
        self.signal_path = signal_path
        self.heartbeat_path = heartbeat_path
        self.logger = logger
        self.scope = scope
        self.target_user = target_user
        self.stop_event = threading.Event()
        self.started_at = time.time()

    def stop(self) -> None:
        """Request shutdown without unmapping any drive."""

        self.stop_event.set()

    def run(self, *, once: bool = False) -> int:
        settings = self.store.load()
        if not once and settings.settings.startup_grace_s:
            self.stop_event.wait(settings.settings.startup_grace_s)
        last_signal = token(self.signal_path)
        while not self.stop_event.is_set():
            try:
                settings = self.store.load()
            except BaseException as error:
                self.logger.error(
                    "Configuración inválida; se conservan los mapeos existentes: %s",
                    error,
                )
                if once:
                    return 2
                self.stop_event.wait(30)
                continue
            now = time.time()
            retries = self.database.retries()
            relevant = [
                drive
                for drive in settings.drives
                if drive.scope is self.scope
                and (drive.target_user or "").casefold()
                == self.target_user.casefold()
            ]
            skip_ids: set[str] = set()
            for drive in relevant:
                state = retries.get(drive.id)
                current_fingerprint = fingerprint(drive)
                if state and state["fingerprint"] != current_fingerprint:
                    self.database.clear_retry(drive.id)
                    state = None
                if state and (
                    bool(state["permanent"])
                    or (
                        state["next_attempt_at"] is not None
                        and float(state["next_attempt_at"]) > now
                    )
                ):
                    skip_ids.add(drive.id)

            results = self.reconciler.reconcile(
                settings,
                self.scope,
                target_user=self.target_user,
                skip_ids=skip_ids,
            )
            for result in results:
                drive = next(item for item in relevant if item.id == result.drive_id)
                if result.state == "connected":
                    self.database.clear_retry(result.drive_id)
                    continue
                previous = retries.get(result.drive_id)
                attempts = int(previous["attempts"]) + 1 if previous else 1
                permanent = result.disposition in {
                    ErrorDisposition.PERMANENT,
                    ErrorDisposition.UNKNOWN,
                }
                delay = min(
                    settings.settings.backoff_initial_s * (2 ** (attempts - 1)),
                    settings.settings.backoff_max_s,
                )
                self.database.set_retry(
                    result.drive_id,
                    fingerprint(drive),
                    attempts,
                    None if permanent else now + delay,
                    permanent,
                )

            self._write_heartbeat()
            if once:
                return 0 if all(item.state == "connected" for item in results) else 3
            interval = settings.settings.check_interval_s
            deadline = time.monotonic() + interval
            while not self.stop_event.is_set() and time.monotonic() < deadline:
                self.stop_event.wait(min(1.0, deadline - time.monotonic()))
                current_signal = token(self.signal_path)
                if current_signal != last_signal:
                    last_signal = current_signal
                    break
        return 0

    def _write_heartbeat(self) -> None:
        self.heartbeat_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pid": os.getpid(),
            "scope": self.scope.value,
            "target_user": self.target_user,
            "started_at_epoch": self.started_at,
            "updated_at_epoch": time.time(),
            "statuses": self.database.statuses(),
        }
        temporary = self.heartbeat_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temporary, self.heartbeat_path)

