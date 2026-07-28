"""Provision the desktop wizard configuration without exposing credentials."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.models import APP_VERSION, AppSettings, DriveScope, DriveSpec
from app.platform.secretstore import SecretStore


class ProvisionDrive(BaseModel):
    """Represent one letter and UNC pair collected by the setup wizard."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    letter: str
    unc: str
    username: str = Field(min_length=1, max_length=256)
    password: SecretStr


class ProvisionRequest(BaseModel):
    """Validate the complete secret-bearing request received over stdin."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    target_user: str = Field(min_length=1, max_length=256)
    include_system: bool = True
    drives: list[ProvisionDrive] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_unique_letters(self) -> ProvisionRequest:
        letters = [
            DriveSpec.normalize_letter(item.letter) for item in self.drives
        ]
        if len(letters) != len(set(letters)):
            raise ValueError("Cada unidad debe usar una letra diferente.")
        if any(
            not item.password.get_secret_value() for item in self.drives
        ):
            raise ValueError("Las contraseñas no pueden estar vacías.")
        return self


def provision_settings(
    settings: AppSettings,
    request: ProvisionRequest,
    secrets: SecretStore,
) -> AppSettings:
    """Replace conflicting wizard mappings and preserve unrelated mappings."""

    letters = {
        DriveSpec.normalize_letter(item.letter) for item in request.drives
    }
    target = request.target_user.casefold()

    def keep_existing(drive: DriveSpec) -> bool:
        wizard_owned = drive.id.startswith(("explorer-", "abbyy-"))
        same_user = (
            drive.scope is DriveScope.USER
            and (drive.target_user or "").casefold() == target
        )
        system_conflict = (
            request.include_system
            and drive.scope is DriveScope.SYSTEM
            and drive.letter in letters
        )
        user_conflict = same_user and drive.letter in letters
        return not (wizard_owned or system_conflict or user_conflict)

    configured = [drive for drive in settings.drives if keep_existing(drive)]
    for item in request.drives:
        letter = DriveSpec.normalize_letter(item.letter)
        token = letter[0].lower()
        protected = secrets.protect(item.password.get_secret_value())
        configured.append(
            DriveSpec(
                id=f"explorer-{token}",
                letter=letter,
                unc=item.unc,
                username=item.username,
                secret=protected,
                scope=DriveScope.USER,
                target_user=request.target_user,
                persistent=True,
                description="Visible en el Explorador de archivos.",
            )
        )
        if request.include_system:
            configured.append(
                DriveSpec(
                    id=f"abbyy-{token}",
                    letter=letter,
                    unc=item.unc,
                    username=item.username,
                    secret=protected,
                    scope=DriveScope.SYSTEM,
                    persistent=True,
                    description="Disponible para ABBYY y servicios de Windows.",
                )
            )

    return AppSettings.model_validate(
        settings.model_copy(
            update={"version": APP_VERSION, "drives": configured}
        ).model_dump()
    )
