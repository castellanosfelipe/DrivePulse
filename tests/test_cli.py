"""Verify CLI mutations, secret-free exports and password argument safety."""

from __future__ import annotations

import json

from app.cli import Runtime, build_parser, main
from app.db import StateDatabase
from app.models import DriveSpec
from app.platform.secretstore import create_secret_store
from app.settings_store import SettingsStore


def runtime(tmp_path) -> Runtime:
    secrets = create_secret_store(
        tmp_path / "entropy",
        tmp_path / "key",
        force_development=True,
    )
    return Runtime(
        SettingsStore(tmp_path / "config.json", secrets, enforce_acl=False),
        secrets,
        StateDatabase(tmp_path / "state.db"),
    )


def test_add_uses_hidden_prompt_and_writes_encrypted_secret(
    tmp_path, monkeypatch
) -> None:
    active = runtime(tmp_path)
    answers = iter(["marker-password", "marker-password"])
    monkeypatch.setattr("app.cli.is_admin", lambda: True)
    monkeypatch.setattr("app.cli.getpass.getpass", lambda _prompt: next(answers))
    monkeypatch.setattr("app.cli.inspect_letter", lambda _letter: type("Use", (), {"is_physical": False})())
    monkeypatch.setattr("app.cli.notify", lambda _path: None)
    monkeypatch.setattr("app.cli.start_task", lambda _name: None)
    result = main(
        [
            "add",
            "--id",
            "seguridad",
            "--letter",
            "Z:",
            "--unc",
            r"\\192.168.230.245\seguridad",
            "--user",
            r"workgroup\readuser",
        ],
        active,
    )
    persisted = (tmp_path / "config.json").read_text(encoding="utf-8")
    assert result == 0
    assert "marker-password" not in persisted
    assert active.store.load().drives[0].secret.startswith("fernet:")


def test_export_omits_secret(tmp_path, monkeypatch) -> None:
    active = runtime(tmp_path)
    settings = active.store.load()
    settings.drives.append(
        DriveSpec(
            id="seguridad",
            letter="Z:",
            unc=r"\\192.168.230.245\seguridad",
            username=r"workgroup\readuser",
            secret=active.secrets.protect("marker-password"),
        )
    )
    active.store.save(settings)
    destination = tmp_path / "export.json"
    assert main(["export", str(destination)], active) == 0
    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert "secret" not in payload["drives"][0]
    assert "marker-password" not in destination.read_text(encoding="utf-8")


def test_parser_has_password_prompt_flag_but_no_value() -> None:
    parser = build_parser()
    parsed = parser.parse_args(["set", "seguridad", "--password"])
    assert parsed.password is True


def test_modify_command_requires_elevation(tmp_path, monkeypatch) -> None:
    active = runtime(tmp_path)
    monkeypatch.setattr("app.cli.is_admin", lambda: False)
    result = main(
        [
            "add",
            "--id",
            "seguridad",
            "--letter",
            "Z:",
            "--unc",
            r"\\192.168.230.245\seguridad",
            "--user",
            r"workgroup\readuser",
        ],
        active,
    )
    assert result == 4
