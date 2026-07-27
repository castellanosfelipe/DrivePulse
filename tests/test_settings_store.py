"""Verify atomic configuration behavior and the narrow plaintext migration path."""

from __future__ import annotations

import json

from app.platform.secretstore import create_secret_store
from app.settings_store import SettingsStore


def test_migrates_plaintext_before_model_validation(tmp_path) -> None:
    path = tmp_path / "config.json"
    raw = {
        "app": "DriveMapper",
        "version": "1.0.0",
        "settings": {},
        "drives": [
            {
                "id": "seguridad",
                "letter": "Z:",
                "unc": r"\\192.168.230.245\seguridad",
                "username": r"workgroup\readuser",
                "secret": "legacy-plaintext",
            }
        ],
    }
    path.write_text(json.dumps(raw), encoding="utf-8")
    secrets = create_secret_store(
        tmp_path / "entropy",
        tmp_path / "key",
        force_development=True,
    )
    store = SettingsStore(path, secrets, enforce_acl=False)
    loaded = store.load()
    persisted = path.read_text(encoding="utf-8")
    assert loaded.drives[0].secret.startswith("fernet:")
    assert "legacy-plaintext" not in persisted


def test_save_replaces_complete_document(tmp_path) -> None:
    path = tmp_path / "config.json"
    secrets = create_secret_store(
        tmp_path / "entropy",
        tmp_path / "key",
        force_development=True,
    )
    store = SettingsStore(path, secrets, enforce_acl=False)
    settings = store.load()
    store.save(settings)
    assert json.loads(path.read_text(encoding="utf-8"))["app"] == "DriveMapper"

