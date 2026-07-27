"""Select DPAPI in production and an explicit Fernet backend only for development."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol

from cryptography.fernet import Fernet

from app.logging_setup import SECRET_REGISTRY
from app.platform.detect import is_windows
from app.platform.secrets_dpapi import DpapiSecretProtector, new_entropy
from app.platform.secrets_fernet import FernetSecretProtector


class SecretProtector(Protocol):
    """Describe the minimal encryption backend needed by configuration storage."""

    prefix: str

    def protect(self, plaintext: str) -> str: ...

    def unprotect(self, blob: str) -> str: ...


class SecretStore:
    """Protect secrets and register plaintext solely for log redaction."""

    def __init__(self, protector: SecretProtector, *, production: bool) -> None:
        self._protector = protector
        self._production = production

    def protect(self, plaintext: str) -> str:
        SECRET_REGISTRY.add(plaintext)
        return self._protector.protect(plaintext)

    def unprotect(self, blob: str) -> str:
        if self._production and blob.startswith("fernet:"):
            raise ValueError("Los secretos fernet: están prohibidos en producción")
        plaintext = self._protector.unprotect(blob)
        SECRET_REGISTRY.add(plaintext)
        return plaintext


def _read_or_create(path: Path, factory: callable) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path.read_bytes()
    value = factory()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(value)
    os.replace(temporary, path)
    return value


def create_secret_store(
    entropy_path: Path,
    fernet_key_path: Path,
    *,
    force_development: bool = False,
) -> SecretStore:
    """Build the platform-appropriate store without silently downgrading Windows."""

    if is_windows() and not force_development:
        entropy = _read_or_create(entropy_path, new_entropy)
        return SecretStore(DpapiSecretProtector(entropy), production=True)
    key = _read_or_create(fernet_key_path, Fernet.generate_key)
    return SecretStore(FernetSecretProtector(key), production=False)

