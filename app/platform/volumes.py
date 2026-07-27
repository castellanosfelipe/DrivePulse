"""Keep machine-dependent drive-letter checks outside declarative validation."""

from __future__ import annotations

import ctypes
import string
from dataclasses import dataclass

from app.platform.detect import is_windows

DRIVE_UNKNOWN = 0
DRIVE_NO_ROOT_DIR = 1
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6


@dataclass(frozen=True, slots=True)
class LetterUse:
    """Describe how Windows currently uses one DOS drive letter."""

    letter: str
    drive_type: int

    @property
    def is_physical(self) -> bool:
        return self.drive_type in {
            DRIVE_REMOVABLE,
            DRIVE_FIXED,
            DRIVE_CDROM,
            DRIVE_RAMDISK,
        }

    @property
    def is_remote(self) -> bool:
        return self.drive_type == DRIVE_REMOTE


def inspect_letter(letter: str) -> LetterUse:
    """Read the current Windows drive type without modifying the mapping."""

    normalized = letter.upper().rstrip(":") + ":"
    if not is_windows():
        return LetterUse(normalized, DRIVE_NO_ROOT_DIR)
    drive_type = int(ctypes.windll.kernel32.GetDriveTypeW(normalized + "\\"))
    return LetterUse(normalized, drive_type)


def find_free_letter(preferred: str = "Y:") -> str:
    """Choose a temporary nonphysical letter for a connection test."""

    candidates = [preferred.upper()] + [
        f"{letter}:" for letter in reversed(string.ascii_uppercase[3:])
    ]
    for candidate in dict.fromkeys(candidates):
        if inspect_letter(candidate).drive_type in {DRIVE_UNKNOWN, DRIVE_NO_ROOT_DIR}:
            return candidate
    raise RuntimeError("No hay una letra temporal libre para realizar la prueba")

