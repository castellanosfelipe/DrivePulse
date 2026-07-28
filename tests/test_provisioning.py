"""Verify the graphical setup provisioning contract."""

from __future__ import annotations

from app.models import AppSettings, DriveScope, DriveSpec
from app.platform.secretstore import create_secret_store
from app.provisioning import ProvisionRequest, provision_settings


def request() -> ProvisionRequest:
    return ProvisionRequest.model_validate(
        {
            "target_user": r"MACHINE\operator",
            "include_system": True,
            "drives": [
                {
                    "letter": "W:",
                    "unc": r"\\192.168.230.245\minvivienda",
                    "username": r"workgroup\readuser",
                    "password": "marker-password",
                },
                {
                    "letter": "Z:",
                    "unc": r"\\192.168.230.245\seguridad",
                    "username": r"workgroup\readuser",
                    "password": "marker-password",
                },
            ],
        }
    )


def test_wizard_creates_persistent_explorer_and_system_mappings(tmp_path) -> None:
    secrets = create_secret_store(
        tmp_path / "entropy",
        tmp_path / "key",
        force_development=True,
    )
    result = provision_settings(AppSettings(), request(), secrets)

    assert len(result.drives) == 4
    assert {
        (drive.scope, drive.letter, drive.persistent)
        for drive in result.drives
    } == {
        (DriveScope.USER, "W:", True),
        (DriveScope.USER, "Z:", True),
        (DriveScope.SYSTEM, "W:", False),
        (DriveScope.SYSTEM, "Z:", False),
    }
    assert {
        drive.target_user
        for drive in result.drives
        if drive.scope is DriveScope.USER
    } == {r"MACHINE\operator"}
    assert all("marker-password" not in drive.secret for drive in result.drives)


def test_wizard_replaces_conflicting_legacy_mapping(tmp_path) -> None:
    secrets = create_secret_store(
        tmp_path / "entropy",
        tmp_path / "key",
        force_development=True,
    )
    legacy = DriveSpec(
        id="legacy-w",
        letter="W:",
        unc=r"\\old\share",
        username="old-user",
        secret=secrets.protect("old-password"),
        scope=DriveScope.SYSTEM,
    )
    result = provision_settings(
        AppSettings(drives=[legacy]),
        request(),
        secrets,
    )

    assert all(drive.id != "legacy-w" for drive in result.drives)
    assert len(
        [
            drive
            for drive in result.drives
            if drive.scope is DriveScope.SYSTEM and drive.letter == "W:"
        ]
    ) == 1
