"""Convert Win32 failures into safe retry decisions that protect the SMB account."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ErrorDisposition(str, Enum):
    """Describe how reconciliation may proceed after a Windows error."""

    TRANSIENT = "transient"
    PERMANENT = "permanent"
    REMAP = "remap"
    HOST_CONFLICT = "host_conflict"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ErrorClassification:
    """Attach an operator-facing cause and action to a Win32 error."""

    code: int
    name: str
    disposition: ErrorDisposition
    cause: str
    action: str
    critical: bool = False


_ERRORS = {
    1: ErrorClassification(
        1, "ERROR_INVALID_FUNCTION", ErrorDisposition.TRANSIENT,
        "El proveedor de red de Windows no estaba listo para procesar el mapeo.",
        "El agente volverá a intentarlo con backoff sin bloquear la cuenta.",
    ),
    53: ErrorClassification(
        53, "ERROR_BAD_NETPATH", ErrorDisposition.TRANSIENT,
        "La ruta de red no está disponible.",
        "Verifique red, DNS/IP y disponibilidad del NAS; el agente reintentará.",
    ),
    55: ErrorClassification(
        55, "ERROR_DEV_NOT_EXIST", ErrorDisposition.TRANSIENT,
        "El recurso de red dejó de estar disponible.",
        "El agente limpiará el estado y reintentará con backoff.",
    ),
    64: ErrorClassification(
        64, "ERROR_NETNAME_DELETED", ErrorDisposition.TRANSIENT,
        "La sesión SMB fue eliminada.",
        "El agente reconstruirá la conexión con backoff.",
    ),
    67: ErrorClassification(
        67, "ERROR_BAD_NET_NAME", ErrorDisposition.PERMANENT,
        "El share solicitado no existe o cambió de nombre.",
        "Confirme el nombre del share en el Synology y corrija la configuración.",
    ),
    85: ErrorClassification(
        85, "ERROR_ALREADY_ASSIGNED", ErrorDisposition.REMAP,
        "La letra local ya está ocupada, posiblemente por una unidad fantasma.",
        "El agente cancelará el mapeo gestionado y volverá a crearlo.",
    ),
    86: ErrorClassification(
        86, "ERROR_INVALID_PASSWORD", ErrorDisposition.PERMANENT,
        "La contraseña fue rechazada.",
        "Actualice la contraseña con 'drivemap set <id> --password'.",
        True,
    ),
    1201: ErrorClassification(
        1201, "ERROR_CONNECTION_UNAVAIL", ErrorDisposition.REMAP,
        "La letra conserva una conexion persistente recordada pero desconectada.",
        "El agente eliminara el perfil recordado y recreara el mapeo.",
    ),
    1203: ErrorClassification(
        1203, "ERROR_NO_NET_OR_BAD_PATH", ErrorDisposition.TRANSIENT,
        "La ruta SMB o el proveedor de red todavía no están disponibles.",
        "Verifique TCP/445 y el NAS; el agente reintentará automáticamente.",
    ),
    1219: ErrorClassification(
        1219, "ERROR_SESSION_CREDENTIAL_CONFLICT", ErrorDisposition.HOST_CONFLICT,
        "Ya existe una conexión al servidor con credenciales distintas.",
        "Cierre las conexiones SMB al mismo host o unifique la cuenta configurada.",
    ),
    1222: ErrorClassification(
        1222, "ERROR_NO_NETWORK", ErrorDisposition.TRANSIENT,
        "Windows aún no tiene una red disponible.",
        "El agente esperará y volverá a intentarlo automáticamente.",
    ),
    1326: ErrorClassification(
        1326, "ERROR_LOGON_FAILURE", ErrorDisposition.PERMANENT,
        "El usuario o la contraseña no son válidos.",
        "Verifique la cuenta y rote la contraseña antes de reactivar intentos.",
        True,
    ),
    1909: ErrorClassification(
        1909, "ERROR_ACCOUNT_LOCKED_OUT", ErrorDisposition.PERMANENT,
        "La cuenta SMB está bloqueada.",
        "Desbloquee la cuenta en el NAS; no habrá nuevos intentos automáticos.",
        True,
    ),
}


def classify_winerror(code: int) -> ErrorClassification:
    """Return a stable classification even for an unrecognized Windows code."""

    return _ERRORS.get(
        code,
        ErrorClassification(
            code,
            f"WINERROR_{code}",
            ErrorDisposition.UNKNOWN,
            "Windows devolvió un error no clasificado.",
            "Revise Event Log y agent.log antes de decidir si debe reintentarse.",
        ),
    )


def extract_winerror(error: BaseException) -> int:
    """Extract pywin32/OS error codes without parsing localized text."""

    value = getattr(error, "winerror", None)
    if isinstance(value, int):
        return value
    if error.args and isinstance(error.args[0], int):
        return error.args[0]
    return 1


class DriveMapperError(RuntimeError):
    """Base class for operator-safe application errors."""


class ConfigurationError(DriveMapperError):
    """Indicate invalid or unsafe desired state."""


class ConnectivityError(DriveMapperError):
    """Indicate an SMB or network failure."""


class PrivilegeError(DriveMapperError):
    """Indicate that an administrative operation lacks elevation."""
