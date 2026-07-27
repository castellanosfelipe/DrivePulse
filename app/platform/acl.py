"""Apply explicit Windows ACLs because machine-scope DPAPI relies on file access."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.platform.detect import is_windows


def harden_global_path(path: Path) -> None:
    """Grant only SYSTEM and built-in Administrators full inherited control."""

    if not is_windows():
        return
    command = [
        "icacls",
        str(path),
        "/inheritance:r",
        "/grant:r",
        "*S-1-5-18:(OI)(CI)F",
        "*S-1-5-32-544:(OI)(CI)F",
        "/T",
        "/C",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise OSError(
            f"No se pudo endurecer la ACL de {path}: {completed.stderr.strip()}"
        )


def inspect_acl(path: Path) -> tuple[bool, str]:
    """Return a read-only ACL assessment suitable for doctor."""

    if not is_windows():
        return False, "La ACL de Windows solo puede verificarse en Windows."
    completed = subprocess.run(
        ["icacls", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        return False, output
    required = ("S-1-5-18", "S-1-5-32-544")
    return all(item in output for item in required), output

