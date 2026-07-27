"""Verify WNet resource construction without creating a real network mapping."""

from __future__ import annotations

from unittest.mock import patch

from app.mapper import CONNECT_UPDATE_PROFILE, WindowsNetworkMapper
from app.models import DriveSpec


def drive(persistent: bool) -> DriveSpec:
    return DriveSpec(
        id="seguridad",
        letter="Z:",
        unc=r"\\192.168.230.245\seguridad",
        username=r"workgroup\readuser",
        secret="dpapi:QUJDRA==",
        persistent=persistent,
    )


def test_connect_passes_password_in_memory_and_no_profile_flag() -> None:
    mapper = WindowsNetworkMapper()
    with patch("win32wnet.WNetAddConnection2") as add:
        mapper.connect(drive(False), "marker-password")
    resource, password, username, flags = add.call_args.args
    assert resource["LocalName"] == "Z:"
    assert resource["RemoteName"] == r"\\192.168.230.245\seguridad"
    assert password == "marker-password"
    assert username == r"workgroup\readuser"
    assert flags == 0


def test_user_persistence_sets_profile_flag() -> None:
    mapper = WindowsNetworkMapper()
    with patch("win32wnet.WNetAddConnection2") as add:
        mapper.connect(drive(True), "marker-password")
    assert add.call_args.args[-1] == CONNECT_UPDATE_PROFILE

