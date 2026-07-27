"""Prove that user scope derives a minimal per-SID configuration and task."""

from __future__ import annotations

import json

from app.models import AppSettings, DriveSpec
from app.user_views import sync_user_views


def test_user_view_contains_only_its_drives(tmp_path, monkeypatch) -> None:
    settings = AppSettings(
        drives=[
            DriveSpec(
                id="system-drive",
                letter="W:",
                unc=r"\\host\system",
                username=r"workgroup\readuser",
                secret="dpapi:QUJDRA==",
            ),
            DriveSpec(
                id="user-drive",
                letter="Z:",
                unc=r"\\host\user",
                username=r"workgroup\readuser",
                secret="dpapi:RUZHSA==",
                scope="user",
                target_user=r"MACHINE\operator",
            ),
        ]
    )
    monkeypatch.setattr(
        "app.user_views.account_sid", lambda _account: "S-1-5-21-1000"
    )
    monkeypatch.setattr("app.user_views.harden_user_view", lambda *_args: None)
    monkeypatch.setattr(
        "app.user_views.register_user_task",
        lambda *_args: "DriveMapper-User-S-1-5-21-1000",
    )
    views = sync_user_views(
        settings,
        tmp_path / "users",
        tmp_path / "entropy",
        tmp_path / "agent.exe",
    )
    payload = json.loads(
        (views[0].root / "config.json").read_text(encoding="utf-8")
    )
    assert [drive["id"] for drive in payload["drives"]] == ["user-drive"]
    assert "system-drive" not in json.dumps(payload)


def test_removed_user_scope_leaves_empty_view_for_unmount(tmp_path, monkeypatch) -> None:
    root = tmp_path / "users" / "S-1-5-21-1000"
    root.mkdir(parents=True)
    (root / "metadata.json").write_text(
        json.dumps(
            {"account": r"MACHINE\operator", "sid": "S-1-5-21-1000"}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("app.user_views.harden_user_view", lambda *_args: None)
    monkeypatch.setattr(
        "app.user_views.register_user_task", lambda *_args: "task"
    )
    views = sync_user_views(
        AppSettings(),
        tmp_path / "users",
        tmp_path / "entropy",
        tmp_path / "agent.exe",
    )
    payload = json.loads(
        (views[0].root / "config.json").read_text(encoding="utf-8")
    )
    assert payload["drives"] == []

