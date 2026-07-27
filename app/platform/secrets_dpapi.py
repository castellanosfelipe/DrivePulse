"""Use machine-scope DPAPI because administrators write secrets consumed by SYSTEM."""

from __future__ import annotations

import base64
import os

CRYPTPROTECT_LOCAL_MACHINE = 0x4
PREFIX = "dpapi:"


class DpapiSecretProtector:
    """Encrypt and decrypt secret text with Windows machine-scope DPAPI."""

    prefix = PREFIX

    def __init__(self, entropy: bytes) -> None:
        self._entropy = entropy

    def protect(self, plaintext: str) -> str:
        import win32crypt

        description = "DriveMapper credential"
        protected = win32crypt.CryptProtectData(
            plaintext.encode("utf-8"),
            description,
            self._entropy,
            None,
            None,
            CRYPTPROTECT_LOCAL_MACHINE,
        )
        return PREFIX + base64.b64encode(protected).decode("ascii")

    def unprotect(self, blob: str) -> str:
        import win32crypt

        if not blob.startswith(PREFIX):
            raise ValueError("El secreto no usa el prefijo dpapi:")
        protected = base64.b64decode(blob.removeprefix(PREFIX), validate=True)
        _, plaintext = win32crypt.CryptUnprotectData(
            protected,
            self._entropy,
            None,
            None,
            0,
        )
        return plaintext.decode("utf-8")


def new_entropy() -> bytes:
    """Generate additional entropy that is stored under the hardened data ACL."""

    return os.urandom(32)

