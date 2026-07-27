"""Lock backoff and permanent credential-failure suppression semantics."""

from __future__ import annotations

import logging

from app.db import StateDatabase
from app.errors import ErrorDisposition
from app.models import AppSettings, DriveScope, DriveSpec
from app.reconciler import ReconcileResult
from app.watchdog import Watchdog


class FakeStore:
    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings

    def load(self) -> AppSettings:
        return self.settings


class FakeReconciler:
    def __init__(self, result: ReconcileResult) -> None:
        self.result = result
        self.skip_history: list[set[str]] = []

    def reconcile(self, settings, scope, *, target_user="", skip_ids=None):
        self.skip_history.append(set(skip_ids or set()))
        if self.result.drive_id in (skip_ids or set()):
            return []
        return [self.result]


def settings() -> AppSettings:
    return AppSettings(
        settings={
            "startup_grace_s": 0,
            "backoff_initial_s": 5,
            "backoff_max_s": 30,
        },
        drives=[
            DriveSpec(
                id="seguridad",
                letter="Z:",
                unc=r"\\192.168.230.245\seguridad",
                username=r"workgroup\readuser",
                secret="dpapi:QUJDRA==",
            )
        ],
    )


def test_permanent_failure_persists_suppression(tmp_path) -> None:
    database = StateDatabase(tmp_path / "state.db")
    reconciler = FakeReconciler(
        ReconcileResult(
            "seguridad",
            "failed",
            "credencial inválida",
            1326,
            ErrorDisposition.PERMANENT,
        )
    )
    watchdog = Watchdog(
        FakeStore(settings()),
        database,
        reconciler,
        tmp_path / "signal",
        tmp_path / "heartbeat",
        logging.getLogger("watchdog-permanent"),
        scope=DriveScope.SYSTEM,
    )
    assert watchdog.run(once=True) == 3
    retry = database.retries()["seguridad"]
    assert retry["permanent"] == 1
    assert retry["attempts"] == 1
    assert watchdog.run(once=True) == 0
    assert reconciler.skip_history[-1] == {"seguridad"}


def test_transient_failure_schedules_backoff(tmp_path) -> None:
    database = StateDatabase(tmp_path / "state.db")
    reconciler = FakeReconciler(
        ReconcileResult(
            "seguridad",
            "failed",
            "ruta no disponible",
            53,
            ErrorDisposition.TRANSIENT,
        )
    )
    watchdog = Watchdog(
        FakeStore(settings()),
        database,
        reconciler,
        tmp_path / "signal",
        tmp_path / "heartbeat",
        logging.getLogger("watchdog-transient"),
    )
    assert watchdog.run(once=True) == 3
    retry = database.retries()["seguridad"]
    assert retry["permanent"] == 0
    assert retry["next_attempt_at"] is not None

