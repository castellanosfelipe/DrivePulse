"""Define the declarative configuration contract without querying machine state."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import PureWindowsPath
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

APP_NAME = "DriveMapper"
APP_VERSION = "1.1.0"
ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
UNC_PATTERN = re.compile(
    r'^\\\\(?P<host>[^\\/:*?"<>|]+)\\(?P<share>[^\\/:*?"<>|]+)$'
)
SECRET_PATTERN = r"^(?:dpapi|fernet):[A-Za-z0-9_+/=-]+$"
RESERVED_DRIVE_LETTERS = {"A:", "B:", "C:"}

EncryptedSecret = Annotated[
    str,
    StringConstraints(pattern=SECRET_PATTERN, min_length=9),
]


class DriveScope(str, Enum):
    """Identify the Windows logon session in which a mapping must exist."""

    SYSTEM = "system"
    USER = "user"


class WatchdogSettings(BaseModel):
    """Hold bounded runtime controls for convergence and observability."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    check_interval_s: int = Field(default=60, ge=5, le=3600)
    startup_grace_s: int = Field(default=15, ge=0, le=300)
    connect_timeout_s: int = Field(default=20, ge=1, le=300)
    backoff_initial_s: int = Field(default=5, ge=1, le=300)
    backoff_max_s: int = Field(default=300, ge=1, le=3600)
    log_retention_days: int = Field(default=30, ge=1, le=3650)
    eventlog_enabled: bool = True

    @model_validator(mode="after")
    def validate_backoff_bounds(self) -> WatchdogSettings:
        if self.backoff_max_s < self.backoff_initial_s:
            raise ValueError(
                "backoff_max_s debe ser mayor o igual que backoff_initial_s"
            )
        return self


class DriveSpec(BaseModel):
    """Describe one desired SMB mapping while keeping its secret opaque."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=False,
    )

    id: str
    letter: str
    unc: str
    username: str = Field(min_length=1, max_length=256)
    secret: EncryptedSecret = Field(repr=False)
    scope: DriveScope = DriveScope.SYSTEM
    target_user: str | None = Field(default=None, max_length=256)
    enabled: bool = True
    persistent: bool | None = None
    verify_path: str = Field(default="", max_length=1024)
    description: str = Field(default="", max_length=1024)

    @model_validator(mode="before")
    @classmethod
    def apply_scope_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if normalized.get("persistent") is None:
            normalized["persistent"] = normalized.get("scope", "system") == "user"
        return normalized

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError(
                "id debe ser un slug en minúsculas con letras, números y guiones"
            )
        return value

    @field_validator("letter", mode="before")
    @classmethod
    def normalize_letter(cls, value: Any) -> str:
        normalized = str(value).strip().upper()
        if re.fullmatch(r"[A-Z]", normalized):
            normalized += ":"
        if not re.fullmatch(r"[A-Z]:", normalized):
            raise ValueError("letter debe usar el formato X:")
        if normalized in RESERVED_DRIVE_LETTERS:
            raise ValueError(f"{normalized} está reservada y no puede mapearse")
        return normalized

    @field_validator("unc")
    @classmethod
    def validate_unc(cls, value: str) -> str:
        if not UNC_PATTERN.fullmatch(value):
            raise ValueError(
                r"unc debe identificar exactamente \\host\share, sin barra final"
            )
        return value

    @field_validator("verify_path")
    @classmethod
    def validate_verify_path(cls, value: str) -> str:
        if not value:
            return value
        path = PureWindowsPath(value)
        if path.is_absolute() or path.drive or path.root:
            raise ValueError("verify_path debe ser relativo a la unidad mapeada")
        if any(part == ".." for part in path.parts):
            raise ValueError("verify_path no puede escapar de la unidad")
        return str(path)

    @model_validator(mode="after")
    def validate_scope_identity(self) -> DriveSpec:
        if self.scope is DriveScope.USER and not self.target_user:
            raise ValueError("target_user es obligatorio cuando scope es user")
        if self.scope is DriveScope.SYSTEM and self.target_user is not None:
            raise ValueError("target_user debe omitirse cuando scope es system")
        return self


class AppSettings(BaseModel):
    """Represent the complete, versioned desired state loaded from JSON."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        use_enum_values=False,
    )

    app: Literal["DriveMapper"] = APP_NAME
    version: str = Field(default=APP_VERSION, pattern=r"^\d+\.\d+\.\d+$")
    settings: WatchdogSettings = Field(default_factory=WatchdogSettings)
    drives: list[DriveSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_drives(self) -> AppSettings:
        seen_ids: set[str] = set()
        seen_letters: set[tuple[DriveScope, str | None, str]] = set()
        for drive in self.drives:
            if drive.id in seen_ids:
                raise ValueError(f"id de unidad duplicado: {drive.id}")
            seen_ids.add(drive.id)
            if not drive.enabled:
                continue
            identity = (
                drive.scope,
                drive.target_user.casefold() if drive.target_user else None,
                drive.letter,
            )
            if identity in seen_letters:
                raise ValueError(
                    "letra habilitada duplicada en el mismo scope e identidad: "
                    f"{drive.letter}"
                )
            seen_letters.add(identity)
        return self
