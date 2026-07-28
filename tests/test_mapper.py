"""Verify WNet resource construction without creating a real network mapping."""

from __future__ import annotations

from unittest.mock import patch

import pywintypes

from app.mapper import CONNECT_UPDATE_PROFILE, WindowsNetworkMapper
from app.models import DriveScope, DriveSpec


def drive(
    persistent: bool,
    *,
    scope: DriveScope = DriveScope.SYSTEM,
) -> DriveSpec:
    return DriveSpec(
        id="seguridad",
        letter="Z:",
        unc=r"\\192.168.230.245\seguridad",
        username=r"workgroup\readuser",
        secret="dpapi:QUJDRA==",
        persistent=persistent,
        scope=scope,
        target_user=(
            r"MACHINE\operator" if scope is DriveScope.USER else None
        ),
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
        mapper.connect(
            drive(True, scope=DriveScope.USER),
            "marker-password",
        )
    assert add.call_args.args[-1] == CONNECT_UPDATE_PROFILE


def test_system_mapping_never_writes_an_interactive_profile() -> None:
    mapper = WindowsNetworkMapper()
    with patch("win32wnet.WNetAddConnection2") as add:
        mapper.connect(drive(True), "marker-password")
    assert add.call_args.args[-1] == 0


def test_cancel_removes_remembered_profile() -> None:
    mapper = WindowsNetworkMapper()
    with patch("win32wnet.WNetCancelConnection2") as cancel:
        mapper.cancel("F:", force=True)
    assert cancel.call_args.args == ("F:", CONNECT_UPDATE_PROFILE, True)


def test_disconnected_remembered_mapping_is_observed_as_absent() -> None:
    mapper = WindowsNetworkMapper()
    unavailable = pywintypes.error(
        1201,
        "WNetGetConnection",
        "La conexión no está disponible.",
    )
    with patch("win32wnet.WNetGetConnection", side_effect=unavailable):
        assert mapper.remote_for("F:") is None


def test_cancel_tolerates_disconnected_remembered_mapping() -> None:
    mapper = WindowsNetworkMapper()
    unavailable = pywintypes.error(
        1201,
        "WNetCancelConnection2",
        "La conexión no está disponible.",
    )
    with patch("win32wnet.WNetCancelConnection2", side_effect=unavailable):
        mapper.cancel("F:", force=True)
