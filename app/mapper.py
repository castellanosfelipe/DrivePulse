"""Wrap the native SMB redirector and bounded access checks behind one boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models import DriveSpec

ERROR_CONNECTION_UNAVAIL = 1201
ERROR_NOT_CONNECTED = 2250
USE_DISKDEV = 0
USE_LOTS_OF_FORCE = 2


@dataclass(frozen=True, slots=True)
class MappingObservation:
    """Describe the remote target and actual readability of a letter."""

    letter: str
    remote: str | None
    accessible: bool
    detail: str = ""


class Mapper(Protocol):
    """Define all state-changing operations used by reconciliation."""

    def remote_for(self, letter: str) -> str | None: ...
    def observe(self, drive: DriveSpec, timeout_s: int) -> MappingObservation: ...
    def connect(self, drive: DriveSpec, password: str) -> None: ...
    def cancel(self, name: str, *, force: bool = True) -> None: ...
    def cancel_host(self, host: str) -> int: ...


class WindowsNetworkMapper:
    """Map SMB resources through the LanmanWorkstation ``NetUse`` API.

    ``NetUseAdd`` is the native SMB-specific API behind the successful
    ``net use`` workflow. Unlike spawning ``net.exe``, the password remains
    in this process' memory and never appears in a command line.
    """

    def remote_for(self, letter: str) -> str | None:
        import pywintypes
        import win32net

        try:
            use = win32net.NetUseGetInfo(None, letter, 2)
            remote = use.get("remote")
            return str(remote) if remote else None
        except pywintypes.error as error:
            if getattr(error, "winerror", error.args[0]) in {
                ERROR_CONNECTION_UNAVAIL,
                ERROR_NOT_CONNECTED,
            }:
                return None
            raise

    def observe(self, drive: DriveSpec, timeout_s: int) -> MappingObservation:
        remote = self.remote_for(drive.letter)
        if remote is None:
            return MappingObservation(drive.letter, None, False, "sin conexión")
        target = Path(drive.letter + "\\") / drive.verify_path
        accessible, detail = _verify_access(target, timeout_s)
        return MappingObservation(drive.letter, remote, accessible, detail)

    def connect(self, drive: DriveSpec, password: str) -> None:
        import win32net

        domain, username = _split_account(drive.username)
        use_info = {
            "local": drive.letter,
            "remote": drive.unc,
            "password": password,
            "status": 0,
            "asg_type": USE_DISKDEV,
            "refcount": 0,
            "usecount": 0,
            "username": username,
            "domainname": domain,
        }
        # Persistence comes from the user/SYSTEM watchdogs, which recreate the
        # mapping in their respective logon sessions after every boot/logon.
        win32net.NetUseAdd(None, 2, use_info)

    def cancel(self, name: str, *, force: bool = True) -> None:
        import pywintypes
        import win32net

        try:
            win32net.NetUseDel(None, name, USE_LOTS_OF_FORCE if force else 0)
        except pywintypes.error as error:
            if getattr(error, "winerror", error.args[0]) not in {
                ERROR_CONNECTION_UNAVAIL,
                ERROR_NOT_CONNECTED,
            }:
                raise

    def cancel_host(self, host: str) -> int:
        import win32net

        cancelled = 0
        uses, _total, _resume = win32net.NetUseEnum(None, 2)
        for use in uses:
            remote = use.get("remote") or ""
            remote_host = remote.lstrip("\\").split("\\", 1)[0]
            if remote_host.casefold() == host.casefold():
                self.cancel(use.get("local") or remote, force=True)
                cancelled += 1
        return cancelled


def _split_account(account: str) -> tuple[str, str]:
    """Return the domain and username expected by ``USE_INFO_2``."""

    if "\\" in account:
        domain, username = account.split("\\", 1)
        return domain, username
    return "", account


def _verify_access(path: Path, timeout_s: int) -> tuple[bool, str]:
    """Run filesystem I/O in a killable helper process with a hard timeout."""

    if getattr(sys, "frozen", False):
        helper = Path(sys.executable).with_name("verify_access.exe")
        command = [str(helper), str(path)]
    else:
        helper = Path(__file__).resolve().parents[1] / "verify_access.py"
        command = [sys.executable, str(helper), str(path)]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except subprocess.TimeoutExpired:
        return False, f"timeout después de {timeout_s} s"
    detail = (completed.stdout or completed.stderr).strip()
    return completed.returncode == 0, detail
