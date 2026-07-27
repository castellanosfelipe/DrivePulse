"""Exercise add, repair, removal and ownership-safe conflict convergence."""

from __future__ import annotations

import logging
from dataclasses import replace

from app.db import StateDatabase
from app.eventlog import EventLogPublisher
from app.mapper import MappingObservation
from app.models import AppSettings, DriveScope, DriveSpec
from app.reconciler import Reconciler


class FakeSecrets:
    def unprotect(self, blob: str) -> str:
        return "password"


class FakeMapper:
    def __init__(self) -> None:
        self.remotes: dict[str, str] = {}
        self.accessible: set[str] = set()
        self.cancelled: list[str] = []

    def remote_for(self, letter: str) -> str | None:
        return self.remotes.get(letter)

    def observe(self, drive: DriveSpec, timeout_s: int) -> MappingObservation:
        remote = self.remotes.get(drive.letter)
        return MappingObservation(
            drive.letter,
            remote,
            drive.letter in self.accessible,
        )

    def connect(self, drive: DriveSpec, password: str) -> None:
        self.remotes[drive.letter] = drive.unc
        self.accessible.add(drive.letter)

    def cancel(self, name: str, *, force: bool = True) -> None:
        self.cancelled.append(name)
        self.remotes.pop(name, None)
        self.accessible.discard(name)

    def cancel_host(self, host: str) -> int:
        return 0


def drive(**overrides: object) -> DriveSpec:
    values: dict[str, object] = {
        "id": "minvivienda",
        "letter": "W:",
        "unc": r"\\192.168.230.245\minvivienda",
        "username": r"workgroup\readuser",
        "secret": "dpapi:QUJDRA==",
    }
    values.update(overrides)
    return DriveSpec.model_validate(values)


def make_reconciler(tmp_path) -> tuple[Reconciler, FakeMapper, StateDatabase]:
    mapper = FakeMapper()
    database = StateDatabase(tmp_path / "state.db")
    logger = logging.getLogger(f"reconciler-{tmp_path}")
    return (
        Reconciler(
            mapper,
            FakeSecrets(),
            database,
            logger,
            EventLogPublisher(False, logger),
        ),
        mapper,
        database,
    )


def test_adds_missing_mapping(tmp_path) -> None:
    reconciler, mapper, database = make_reconciler(tmp_path)
    result = reconciler.reconcile(AppSettings(drives=[drive()]), DriveScope.SYSTEM)
    assert result[0].state == "connected"
    assert mapper.remotes["W:"] == r"\\192.168.230.245\minvivienda"
    assert database.managed_for("system")[0].drive_id == "minvivienda"


def test_repairs_wrong_or_inaccessible_mapping(tmp_path) -> None:
    reconciler, mapper, _ = make_reconciler(tmp_path)
    mapper.remotes["W:"] = r"\\other\share"
    result = reconciler.reconcile(AppSettings(drives=[drive()]), DriveScope.SYSTEM)
    assert result[0].state == "connected"
    assert mapper.cancelled == ["W:"]


def test_removes_deleted_mapping_owned_by_agent(tmp_path) -> None:
    reconciler, mapper, database = make_reconciler(tmp_path)
    configured = AppSettings(drives=[drive()])
    reconciler.reconcile(configured, DriveScope.SYSTEM)
    reconciler.reconcile(AppSettings(), DriveScope.SYSTEM)
    assert "W:" not in mapper.remotes
    assert database.managed_for("system") == []


def test_does_not_remove_letter_reused_by_third_party(tmp_path) -> None:
    reconciler, mapper, database = make_reconciler(tmp_path)
    reconciler.reconcile(AppSettings(drives=[drive()]), DriveScope.SYSTEM)
    mapper.remotes["W:"] = r"\\third-party\share"
    mapper.accessible.add("W:")
    reconciler.reconcile(AppSettings(), DriveScope.SYSTEM)
    assert mapper.remotes["W:"] == r"\\third-party\share"
    assert database.managed_for("system")


def test_disabled_mapping_is_removed(tmp_path) -> None:
    reconciler, mapper, database = make_reconciler(tmp_path)
    reconciler.reconcile(AppSettings(drives=[drive()]), DriveScope.SYSTEM)
    reconciler.reconcile(
        AppSettings(drives=[drive(enabled=False)]),
        DriveScope.SYSTEM,
    )
    assert "W:" not in mapper.remotes
    assert database.managed_for("system") == []

