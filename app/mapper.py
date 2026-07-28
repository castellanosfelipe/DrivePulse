"""Wrap WNet APIs and bounded access checks behind a mockable mapping boundary."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.models import DriveSpec

CONNECT_UPDATE_PROFILE = 0x00000001
ERROR_CONNECTION_UNAVAIL = 1201
ERROR_NOT_CONNECTED = 2250


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
    """Map SMB resources in the current Windows logon session using WNet."""

    def remote_for(self, letter: str) -> str | None:
        import pywintypes
        import win32wnet

        try:
            return str(win32wnet.WNetGetConnection(letter))
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
        import win32netcon
        import win32wnet

        resource = {
            "Type": win32netcon.RESOURCETYPE_DISK,
            "LocalName": drive.letter,
            "RemoteName": drive.unc,
            "Provider": None,
        }
        flags = CONNECT_UPDATE_PROFILE if drive.persistent else 0
        win32wnet.WNetAddConnection2(resource, password, drive.username, flags)

    def cancel(self, name: str, *, force: bool = True) -> None:
        import pywintypes
        import win32wnet

        try:
            win32wnet.WNetCancelConnection2(
                name,
                CONNECT_UPDATE_PROFILE,
                force,
            )
        except pywintypes.error as error:
            if getattr(error, "winerror", error.args[0]) not in {
                ERROR_CONNECTION_UNAVAIL,
                ERROR_NOT_CONNECTED,
            }:
                raise

    def cancel_host(self, host: str) -> int:
        import win32netcon
        import win32wnet

        handle = win32wnet.WNetOpenEnum(
            win32netcon.RESOURCE_CONNECTED,
            win32netcon.RESOURCETYPE_DISK,
            0,
            None,
        )
        cancelled = 0
        try:
            while True:
                resources = win32wnet.WNetEnumResource(handle, 0)
                if not resources:
                    break
                for resource in resources:
                    remote = resource.get("RemoteName") or ""
                    remote_host = remote.lstrip("\\").split("\\", 1)[0]
                    if remote_host.casefold() == host.casefold():
                        self.cancel(resource.get("LocalName") or remote, force=True)
                        cancelled += 1
        finally:
            win32wnet.WNetCloseEnum(handle)
        return cancelled


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
