"""Apply explicit Windows ACLs because machine-scope DPAPI relies on file access."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.platform.detect import is_windows


def _run_icacls(command: list[str], label: Path) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise OSError(f"No se pudo aplicar la ACL de {label}: {detail}")


def harden_global_path(path: Path) -> None:
    """Grant only SYSTEM and built-in Administrators full inherited control."""

    if not is_windows():
        return
    commands = [
        [
            "icacls", str(path), "/grant:r",
            "*S-1-5-18:F", "*S-1-5-32-544:F", "/T", "/C",
        ],
        ["icacls", str(path), "/inheritance:r"],
        [
            "icacls", str(path), "/remove:g",
            "*S-1-5-32-545", "*S-1-1-0", "*S-1-5-11", "/T", "/C",
        ],
        [
            "icacls", str(path), "/grant:r",
            "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F",
        ],
    ]
    for command in commands:
        _run_icacls(command, path)


def inspect_acl(path: Path) -> tuple[bool, str]:
    """Return a read-only ACL assessment suitable for doctor."""

    if not is_windows():
        return False, "La ACL de Windows solo puede verificarse en Windows."
    try:
        import win32security

        descriptor = win32security.GetFileSecurity(
            str(path), win32security.DACL_SECURITY_INFORMATION
        )
        dacl = descriptor.GetSecurityDescriptorDacl()
        if dacl is None:
            return False, "La ruta tiene DACL nula; cualquier usuario tendría acceso."
        allowed: dict[str, int] = {}
        for index in range(dacl.GetAceCount()):
            header, mask, sid = dacl.GetAce(index)
            if header[0] != win32security.ACCESS_ALLOWED_ACE_TYPE:
                continue
            sid_text = win32security.ConvertSidToStringSid(sid)
            allowed[sid_text] = allowed.get(sid_text, 0) | int(mask)
        required = {"S-1-5-18", "S-1-5-32-544"}
        forbidden = {"S-1-5-32-545", "S-1-1-0", "S-1-5-11"}
        missing = sorted(required.difference(allowed))
        exposed = sorted(forbidden.intersection(allowed))
        ok = not missing and not exposed
        detail = (
            f"ACE permitidas={sorted(allowed)}; "
            f"faltantes={missing}; acceso amplio={exposed}."
        )
        return ok, detail
    except OSError as error:
        return False, str(error)


def harden_user_view(root: Path, sid: str, entropy_path: Path) -> None:
    """Give one user read-only config and mutable state only for that SID view."""

    if not is_windows():
        return
    broad_sids = ["*S-1-5-32-545", "*S-1-1-0", "*S-1-5-11"]
    commands = [
        ["icacls", str(root), "/inheritance:r"],
        ["icacls", str(root), "/remove:g", *broad_sids],
        [
            "icacls", str(root), "/grant:r",
            "*S-1-5-18:F", "*S-1-5-32-544:F", f"*{sid}:RX",
        ],
        [
            "icacls", str(root / "config.json"), "/inheritance:r",
            "/remove:g", *broad_sids,
        ],
        [
            "icacls", str(root / "config.json"), "/grant:r",
            "*S-1-5-18:F", "*S-1-5-32-544:F", f"*{sid}:R",
        ],
    ]
    for mutable in (root / "data", root / "logs"):
        commands.extend(
            [
                [
                    "icacls", str(mutable), "/grant:r",
                    "*S-1-5-18:F", "*S-1-5-32-544:F", f"*{sid}:M",
                    "/T", "/C",
                ],
                ["icacls", str(mutable), "/inheritance:r"],
                ["icacls", str(mutable), "/remove:g", *broad_sids, "/T", "/C"],
                [
                    "icacls", str(mutable), "/grant:r",
                    "*S-1-5-18:(OI)(CI)F",
                    "*S-1-5-32-544:(OI)(CI)F",
                    f"*{sid}:(OI)(CI)M",
                ],
            ]
        )
    commands.extend(
        [
            ["icacls", str(entropy_path), "/inheritance:r"],
            ["icacls", str(entropy_path), "/remove:g", *broad_sids],
            [
                "icacls", str(entropy_path), "/grant:r",
                "*S-1-5-18:F", "*S-1-5-32-544:F", f"*{sid}:R",
            ],
        ]
    )
    for command in commands:
        _run_icacls(command, root)
