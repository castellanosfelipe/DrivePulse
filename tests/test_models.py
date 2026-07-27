"""Verify structural configuration rules independently from machine state."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models import AppSettings, DriveScope, DriveSpec


def drive(**overrides: object) -> DriveSpec:
    values: dict[str, object] = {
        "id": "minvivienda",
        "letter": "w",
        "unc": r"\\192.168.230.245\minvivienda",
        "username": r"workgroup\readuser",
        "secret": "dpapi:QUJDRA==",
    }
    values.update(overrides)
    return DriveSpec.model_validate(values)


def test_normalizes_letter_and_system_persistence() -> None:
    result = drive()
    assert result.letter == "W:"
    assert result.scope is DriveScope.SYSTEM
    assert result.persistent is False
    assert "secret" not in repr(result)


def test_user_requires_target_and_defaults_persistent() -> None:
    with pytest.raises(ValidationError, match="target_user"):
        drive(scope="user")
    result = drive(scope="user", target_user=r"MACHINE\operator")
    assert result.persistent is True


@pytest.mark.parametrize("letter", ["A:", "b:", "C", "AA:", "1:"])
def test_rejects_reserved_or_invalid_letters(letter: str) -> None:
    with pytest.raises(ValidationError):
        drive(letter=letter)


@pytest.mark.parametrize(
    "unc",
    [
        r"C:\local",
        r"\\host",
        r"\\host\share\\",
        r"\\host\share\folder",
        "host/share",
    ],
)
def test_rejects_invalid_unc(unc: str) -> None:
    with pytest.raises(ValidationError):
        drive(unc=unc)


def test_rejects_duplicate_enabled_letter_in_scope() -> None:
    first = drive()
    second = drive(
        id="seguridad",
        unc=r"\\192.168.230.245\seguridad",
    )
    with pytest.raises(ValidationError, match="duplicada"):
        AppSettings(drives=[first, second])


def test_allows_same_letter_in_different_scope() -> None:
    first = drive()
    second = drive(
        id="seguridad",
        unc=r"\\192.168.230.245\seguridad",
        scope="user",
        target_user=r"MACHINE\operator",
    )
    assert len(AppSettings(drives=[first, second]).drives) == 2


def test_rejects_plaintext_secret() -> None:
    with pytest.raises(ValidationError):
        drive(secret="not-encrypted")

