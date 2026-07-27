"""Verify ACL hardening grants effective permissions to existing files."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.platform import acl


def test_global_acl_grants_direct_rights_before_recursive_cleanup(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(acl, "is_windows", lambda: True)
    monkeypatch.setattr(
        acl.subprocess,
        "run",
        lambda command, **_kwargs: (
            commands.append(command)
            or SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )

    acl.harden_global_path(tmp_path)

    assert commands[0][-4:] == [
        "*S-1-5-18:F",
        "*S-1-5-32-544:F",
        "/T",
        "/C",
    ]
    assert "(OI)(CI)" not in " ".join(commands[0])
    assert commands[-1][-2:] == [
        "*S-1-5-18:(OI)(CI)F",
        "*S-1-5-32-544:(OI)(CI)F",
    ]


def test_user_mutable_acl_has_direct_and_inheritable_grants(
    tmp_path: Path, monkeypatch
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(acl, "is_windows", lambda: True)
    monkeypatch.setattr(
        acl.subprocess,
        "run",
        lambda command, **_kwargs: (
            commands.append(command)
            or SimpleNamespace(returncode=0, stdout="", stderr="")
        ),
    )
    root = tmp_path / "user"
    entropy = tmp_path / ".entropy"

    acl.harden_user_view(root, "S-1-5-21-1000", entropy)

    data_commands = [
        command for command in commands if str(root / "data") in command
    ]
    assert any("*S-1-5-21-1000:M" in command for command in data_commands)
    assert any(
        "*S-1-5-21-1000:(OI)(CI)M" in command for command in data_commands
    )
    entropy_commands = [
        command for command in commands if str(entropy) in command
    ]
    assert entropy_commands[-1][-1] == "*S-1-5-21-1000:R"
