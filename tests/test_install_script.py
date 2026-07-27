"""Guard mandatory Scheduler, ACL, offline-build and uninstall semantics."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_install_registers_system_principal_and_both_triggers() -> None:
    script = text("install.ps1")
    assert "S-1-5-18" in script
    assert "<BootTrigger>" in script
    assert "EventID=10000" in script
    assert "NetworkProfile/Operational" in script
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in script
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in script
    assert "<ExecutionTimeLimit>PT0S</ExecutionTimeLimit>" in script
    assert "<Count>999</Count>" in script


def test_install_is_elevated_idempotent_and_hardens_acl() -> None:
    script = text("install.ps1")
    assert "WindowsBuiltInRole]::Administrator" in script
    assert "Register-ScheduledTask" in script
    assert "-Force" in script
    assert "/inheritance:r" in script
    assert "/remove:g" in script
    assert "*S-1-5-32-544" in script
    assert "New-EventLog" in script
    assert "'Machine'" in script
    assert "sync-user-tasks" in script


def test_build_never_uses_online_pip() -> None:
    script = text("build.ps1")
    assert "--no-index" in script
    assert "--find-links" in script
    assert "pytest -q" in script
    assert "--self-test" in script
    assert "Invoke-WebRequest" not in script
    assert "pip install -r" not in script


def test_uninstall_preserves_data_unless_purge_and_mappings_are_opt_in() -> None:
    script = text("uninstall.ps1")
    assert "[switch]$RemoveMappings" in script
    assert "[switch]$Purge" in script
    assert "if ($RemoveMappings)" in script
    assert "if ($Purge" in script
    assert "--remove-managed" in script
