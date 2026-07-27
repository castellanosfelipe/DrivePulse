"""Converge desired mappings while respecting ownership and credential safety."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.db import StateDatabase
from app.errors import ErrorDisposition, classify_winerror, extract_winerror
from app.eventlog import EventLogPublisher
from app.mapper import Mapper
from app.models import AppSettings, DriveScope, DriveSpec
from app.platform.network import unc_host
from app.platform.secretstore import SecretStore


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    drive_id: str
    state: str
    detail: str
    winerror: int | None = None
    disposition: ErrorDisposition | None = None


class Reconciler:
    """Compare actual mappings with desired state and make the minimum safe changes."""

    def __init__(
        self,
        mapper: Mapper,
        secrets: SecretStore,
        database: StateDatabase,
        logger: logging.Logger,
        eventlog: EventLogPublisher,
    ) -> None:
        self.mapper = mapper
        self.secrets = secrets
        self.database = database
        self.logger = logger
        self.eventlog = eventlog

    def reconcile(
        self,
        settings: AppSettings,
        scope: DriveScope,
        *,
        target_user: str = "",
        skip_ids: set[str] | None = None,
    ) -> list[ReconcileResult]:
        skip_ids = skip_ids or set()
        desired = [
            drive
            for drive in settings.drives
            if drive.scope is scope
            and (drive.target_user or "").casefold() == target_user.casefold()
        ]
        self._remove_stale(desired, scope, target_user)
        results: list[ReconcileResult] = []
        for drive in desired:
            if drive.id in skip_ids:
                continue
            if not drive.enabled:
                continue
            results.append(
                self._reconcile_drive(
                    drive,
                    timeout_s=settings.settings.connect_timeout_s,
                    target_user=target_user,
                )
            )
        return results

    def _remove_stale(
        self, desired: list[DriveSpec], scope: DriveScope, target_user: str
    ) -> None:
        active = {drive.id: drive for drive in desired if drive.enabled}
        for managed in self.database.managed_for(scope.value, target_user):
            desired_drive = active.get(managed.drive_id)
            unchanged = (
                desired_drive is not None
                and desired_drive.letter.casefold() == managed.letter.casefold()
                and desired_drive.unc.casefold() == managed.unc.casefold()
            )
            if unchanged:
                continue
            try:
                remote = getattr(self.mapper, "remote_for")(managed.letter)
                if remote and remote.casefold() == managed.unc.casefold():
                    self.mapper.cancel(managed.letter, force=True)
                elif remote:
                    self.database.update_status(
                        managed.drive_id,
                        "conflict",
                        "La letra fue reutilizada por un mapeo ajeno; no se desmontó.",
                        level="Warning",
                    )
                    continue
                self.database.remove_managed(
                    managed.drive_id, managed.scope, managed.target_user
                )
                self.database.update_status(
                    managed.drive_id,
                    "removed",
                    "Mapeo eliminado por convergencia declarativa.",
                )
            except BaseException as error:
                self._record_failure(managed.drive_id, error)

    def _reconcile_drive(
        self, drive: DriveSpec, timeout_s: int, target_user: str
    ) -> ReconcileResult:
        try:
            observation = self.mapper.observe(drive, timeout_s)
            correct_remote = (
                observation.remote is not None
                and observation.remote.casefold() == drive.unc.casefold()
            )
            if correct_remote and observation.accessible:
                self.database.upsert_managed(
                    drive.id,
                    drive.scope.value,
                    target_user,
                    drive.letter,
                    drive.unc,
                )
                self.database.close_incident(drive.id)
                self.database.update_status(
                    drive.id, "connected", "Unidad accesible."
                )
                return ReconcileResult(drive.id, "connected", "Unidad accesible.")

            if observation.remote is not None:
                self.mapper.cancel(drive.letter, force=True)

            password = self.secrets.unprotect(drive.secret)
            try:
                self.mapper.connect(drive, password)
            except BaseException as error:
                code = extract_winerror(error)
                disposition = classify_winerror(code).disposition
                if disposition is ErrorDisposition.REMAP:
                    self.mapper.cancel(drive.letter, force=True)
                    self.mapper.connect(drive, password)
                elif disposition is ErrorDisposition.HOST_CONFLICT:
                    self.mapper.cancel_host(unc_host(drive.unc))
                    self.mapper.connect(drive, password)
                else:
                    raise

            verification = self.mapper.observe(drive, timeout_s)
            if (
                verification.remote is None
                or verification.remote.casefold() != drive.unc.casefold()
                or not verification.accessible
            ):
                raise OSError(64, f"El acceso posterior al mapeo falló: {verification.detail}")

            self.database.upsert_managed(
                drive.id,
                drive.scope.value,
                target_user,
                drive.letter,
                drive.unc,
            )
            self.database.close_incident(drive.id)
            changed = self.database.update_status(
                drive.id, "connected", "Unidad mapeada y acceso verificado."
            )
            if changed:
                self.eventlog.publish(
                    "Information", f"{drive.id} ({drive.letter}) quedó disponible."
                )
            return ReconcileResult(
                drive.id, "connected", "Unidad mapeada y acceso verificado."
            )
        except BaseException as error:
            return self._record_failure(drive.id, error)

    def _record_failure(
        self, drive_id: str, error: BaseException
    ) -> ReconcileResult:
        code = extract_winerror(error)
        classification = classify_winerror(code)
        level = "Error" if classification.disposition in {
            ErrorDisposition.PERMANENT,
            ErrorDisposition.UNKNOWN,
        } else "Warning"
        detail = f"{classification.name}: {classification.cause}"
        self.database.open_incident(drive_id, detail, code)
        changed = self.database.update_status(
            drive_id, "failed", detail, code, level
        )
        if changed:
            self.eventlog.publish(level, f"{drive_id}: {detail}")
        self.logger.warning("%s: %s", drive_id, detail)
        return ReconcileResult(
            drive_id, "failed", detail, code, classification.disposition
        )

