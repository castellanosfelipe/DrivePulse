"""Provide a clearly marked non-production secret backend for tests and CI."""

from __future__ import annotations

from cryptography.fernet import Fernet

PREFIX = "fernet:"


class FernetSecretProtector:
    """Encrypt development secrets while making their non-DPAPI origin explicit."""

    prefix = PREFIX

    def __init__(self, key: bytes) -> None:
        self._fernet = Fernet(key)

    def protect(self, plaintext: str) -> str:
        return PREFIX + self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def unprotect(self, blob: str) -> str:
        if not blob.startswith(PREFIX):
            raise ValueError("El secreto no usa el prefijo fernet:")
        token = blob.removeprefix(PREFIX).encode("ascii")
        return self._fernet.decrypt(token).decode("utf-8")

