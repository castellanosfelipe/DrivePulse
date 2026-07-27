"""Prove that development encryption round-trips without plaintext persistence."""

from __future__ import annotations

from app.platform.secretstore import create_secret_store


def test_fernet_round_trip(tmp_path) -> None:
    store = create_secret_store(
        tmp_path / "entropy",
        tmp_path / "fernet.key",
        force_development=True,
    )
    blob = store.protect("extremely-secret-marker")
    assert blob.startswith("fernet:")
    assert "extremely-secret-marker" not in blob
    assert store.unprotect(blob) == "extremely-secret-marker"

