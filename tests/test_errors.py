"""Lock the credential-safe retry taxonomy to the required Win32 codes."""

from __future__ import annotations

import pytest

from app.errors import ErrorDisposition, classify_winerror


@pytest.mark.parametrize("code", [1, 53, 55, 64, 1203, 1222])
def test_transient_codes_retry(code: int) -> None:
    assert classify_winerror(code).disposition is ErrorDisposition.TRANSIENT


@pytest.mark.parametrize("code", [67, 86, 1326, 1909])
def test_permanent_codes_stop(code: int) -> None:
    assert classify_winerror(code).disposition is ErrorDisposition.PERMANENT


@pytest.mark.parametrize("code", [86, 1326, 1909])
def test_credential_failures_are_critical(code: int) -> None:
    assert classify_winerror(code).critical is True


def test_special_remediation_codes() -> None:
    assert classify_winerror(85).disposition is ErrorDisposition.REMAP
    assert classify_winerror(1201).disposition is ErrorDisposition.REMAP
    assert classify_winerror(1219).disposition is ErrorDisposition.HOST_CONFLICT


def test_unknown_code_is_not_retried_automatically() -> None:
    assert classify_winerror(9999).disposition is ErrorDisposition.UNKNOWN
