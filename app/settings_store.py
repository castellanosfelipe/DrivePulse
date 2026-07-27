"""Persist desired state atomically and migrate plaintext secrets before validation."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.errors import ConfigurationError
from app.models import AppSettings
from app.platform.acl import harden_global_path
from app.platform.secretstore import SecretStore


class SettingsStore:
    """Read and atomically replace the configuration under a hardened ACL."""

    def __init__(
        self,
        path: Path,
        secret_store: SecretStore,
        *,
        enforce_acl: bool = True,
    ) -> None:
        self.path = path
        self.secret_store = secret_store
        self.enforce_acl = enforce_acl

    def load(self) -> AppSettings:
        if not self.path.exists():
            return AppSettings()
        try:
            raw: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ConfigurationError(
                f"No se pudo leer {self.path}: {error}"
            ) from error
        migrated = self._migrate_plaintext_secrets(raw)
        try:
            settings = AppSettings.model_validate(raw)
        except ValidationError as error:
            raise ConfigurationError(
                f"La configuración no es válida: {error}"
            ) from error
        if migrated:
            self.save(settings)
        return settings

    def save(self, settings: AppSettings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        payload = settings.model_dump(mode="json")
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, self.path)
        if self.enforce_acl:
            harden_global_path(self.path.parent)

    def _migrate_plaintext_secrets(self, raw: dict[str, Any]) -> bool:
        migrated = False
        drives = raw.get("drives", [])
        if not isinstance(drives, list):
            return False
        for drive in drives:
            if not isinstance(drive, dict):
                continue
            secret = drive.get("secret")
            if isinstance(secret, str) and not secret.startswith(("dpapi:", "fernet:")):
                drive["secret"] = self.secret_store.protect(secret)
                migrated = True
        return migrated

