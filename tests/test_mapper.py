"""Verify native SMB resource construction without creating a real mapping."""

from __future__ import annotations

from unittest.mock import patch

import pywintypes

from app.mapper import USE_LOTS_OF_FORCE, WindowsNetworkMapper
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


def test_connect_passes_password_in_memory_to_netuse() -> None:
    mapper = WindowsNetworkMapper()
    with patch("win32net.NetUseAdd") as add:
        mapper.connect(drive(False), "marker-password")
    server, level, use_info = add.call_args.args
    assert server is None
    assert level == 2
    assert use_info["local"] == "Z:"
    assert use_info["remote"] == r"\\192.168.230.245\seguridad"
    assert use_info["password"] == "marker-password"
    assert use_info["username"] == "readuser"
    assert use_info["domainname"] == "workgroup"


def test_user_mapping_uses_same_smb_backend() -> None:
    mapper = WindowsNetworkMapper()
    with patch("win32net.NetUseAdd") as add:
        mapper.connect(
            drive(True, scope=DriveScope.USER),
            "marker-password",
        )
    assert add.call_args.args[1] == 2


def test_upn_account_is_not_split_as_a_domain_account() -> None:
    mapper = WindowsNetworkMapper()
    spec = drive(True).model_copy(update={"username": "readuser@example.test"})
    with patch("win32net.NetUseAdd") as add:
        mapper.connect(spec, "marker-password")
    use_info = add.call_args.args[2]
    assert use_info["username"] == "readuser@example.test"
    assert use_info["domainname"] == ""


def test_cancel_forces_netuse_removal() -> None:
    mapper = WindowsNetworkMapper()
    with patch("win32net.NetUseDel") as cancel:
        mapper.cancel("F:", force=True)
    assert cancel.call_args.args == (None, "F:", USE_LOTS_OF_FORCE)


def test_disconnected_mapping_is_observed_as_absent() -> None:
    mapper = WindowsNetworkMapper()
    unavailable = pywintypes.error(
        1201,
        "NetUseGetInfo",
        "La conexión no está disponible.",
    )
    with patch("win32net.NetUseGetInfo", side_effect=unavailable):
        assert mapper.remote_for("F:") is None


def test_cancel_tolerates_missing_mapping() -> None:
    mapper = WindowsNetworkMapper()
    unavailable = pywintypes.error(
        2250,
        "NetUseDel",
        "La conexión no existe.",
    )
    with patch("win32net.NetUseDel", side_effect=unavailable):
        mapper.cancel("F:", force=True)


def test_remote_for_returns_native_smb_target() -> None:
    mapper = WindowsNetworkMapper()
    with patch(
        "win32net.NetUseGetInfo",
        return_value={"local": "W:", "remote": r"\\nas\share"},
    ):
        assert mapper.remote_for("W:") == r"\\nas\share"


def test_cancel_host_removes_only_matching_smb_server() -> None:
    mapper = WindowsNetworkMapper()
    uses = [
        {"local": "W:", "remote": r"\\192.168.230.245\one"},
        {"local": "Z:", "remote": r"\\other\share"},
        {"local": "", "remote": r"\\192.168.230.245\IPC$"},
    ]
    with (
        patch("win32net.NetUseEnum", return_value=(uses, 3, 0)),
        patch.object(mapper, "cancel") as cancel,
    ):
        assert mapper.cancel_host("192.168.230.245") == 2
    assert [call.args[0] for call in cancel.call_args_list] == [
        "W:",
        r"\\192.168.230.245\IPC$",
    ]
