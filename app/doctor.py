"""Collect read-only prerequisite evidence with ticket-ready remediation guidance."""

from __future__ import annotations

import json
import subprocess
import winreg
from dataclasses import asdict, dataclass
from pathlib import Path

from app.models import AppSettings
from app.platform.acl import inspect_acl
from app.platform.detect import is_admin
from app.platform.network import check_endpoint, unc_host
from app.platform.scheduled_task import inspect_task
from app.platform.secretstore import SecretStore
from app.platform.volumes import inspect_letter


@dataclass(frozen=True, slots=True)
class Finding:
    """Carry status, evidence and remediation as one doctor result."""

    check: str
    status: str
    detail: str
    action: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def _registry_dword(
    hive: int, path: str, name: str
) -> tuple[int | None, str]:
    try:
        with winreg.OpenKey(hive, path) as key:
            value, _kind = winreg.QueryValueEx(key, name)
            return int(value), "configurado"
    except FileNotFoundError:
        return None, "no configurado"
    except OSError as error:
        return None, str(error)


def _smb_connections() -> list[dict[str, object]]:
    script = (
        "Get-SmbConnection | Select-Object ServerName,ShareName,"
        "UserName,Dialect,Signed,Encrypted | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        return []
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else [data]


def run_doctor(
    settings: AppSettings,
    secrets: SecretStore,
    program_data_dir: Path,
) -> list[Finding]:
    """Run all diagnostics without writing registry, tasks, ACLs or mappings."""

    findings: list[Finding] = []
    findings.append(
        Finding(
            "Privilegios",
            "ok" if is_admin() else "error",
            "La sesión está elevada." if is_admin() else "La sesión no está elevada.",
            "Abra PowerShell con 'Ejecutar como administrador'." if not is_admin() else "",
        )
    )
    task = inspect_task("DriveMapper-System")
    findings.append(
        Finding(
            "Tarea DriveMapper-System",
            "ok" if task.exists and task.last_result in {None, 0, 267009} else "warning",
            (
                f"Estado={task.state}; última ejecución={task.last_run_time}; "
                f"resultado={task.last_result}"
                if task.exists
                else task.detail or "No está registrada."
            ),
            "Ejecute install.ps1 nuevamente como administrador." if not task.exists else "",
        )
    )
    hosts = sorted({unc_host(drive.unc) for drive in settings.drives})
    for host in hosts:
        endpoint = check_endpoint(host)
        status = "ok" if endpoint.tcp_445_ok else "error"
        findings.append(
            Finding(
                f"SMB {host}:445",
                status,
                f"ICMP={endpoint.icmp_ok}; TCP/445={endpoint.tcp_445_ok}; {endpoint.detail}",
                (
                    "Verifique cable/VLAN, firewall y servicio SMB del Synology."
                    if not endpoint.tcp_445_ok
                    else ""
                ),
            )
        )

    guest, guest_detail = _registry_dword(
        winreg.HKEY_LOCAL_MACHINE,
        r"SYSTEM\CurrentControlSet\Services\LanmanWorkstation\Parameters",
        "AllowInsecureGuestAuth",
    )
    findings.append(
        Finding(
            "AllowInsecureGuestAuth",
            "warning" if guest == 1 else "ok",
            f"Valor={guest!r} ({guest_detail}).",
            (
                "No habilite acceso invitado salvo que el Synology realmente lo exija; "
                "prefiera la cuenta readuser."
                if guest == 1
                else ""
            ),
        )
    )
    linked, linked_detail = _registry_dword(
        winreg.HKEY_LOCAL_MACHINE,
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
        "EnableLinkedConnections",
    )
    findings.append(
        Finding(
            "EnableLinkedConnections",
            "ok" if linked == 1 else "warning",
            f"Valor={linked!r} ({linked_detail}).",
            (
                "Solo configúrelo en 1 si un usuario debe compartir letras entre "
                "procesos elevados y no elevados; no afecta a SYSTEM."
                if linked != 1
                else ""
            ),
        )
    )

    connections = _smb_connections()
    configured_hosts = {host.casefold() for host in hosts}
    for connection in connections:
        server = str(connection.get("ServerName", ""))
        if server.casefold() not in configured_hosts:
            continue
        findings.append(
            Finding(
                f"Sesión SMB {server}/{connection.get('ShareName', '')}",
                "ok",
                (
                    f"Usuario={connection.get('UserName')}; "
                    f"dialecto={connection.get('Dialect')}; "
                    f"firmada={connection.get('Signed')}; "
                    f"cifrada={connection.get('Encrypted')}"
                ),
                "",
            )
        )
    for drive in settings.drives:
        use = inspect_letter(drive.letter)
        findings.append(
            Finding(
                f"Letra {drive.letter}",
                "error" if use.is_physical else "ok",
                f"GetDriveType={use.drive_type}.",
                (
                    "Cambie la letra configurada: está ocupada por un volumen físico."
                    if use.is_physical
                    else ""
                ),
            )
        )
        try:
            secrets.unprotect(drive.secret)
            findings.append(
                Finding(
                    f"Secreto {drive.id}",
                    "ok",
                    "El blob puede descifrarse en este equipo.",
                    "",
                )
            )
        except BaseException as error:
            findings.append(
                Finding(
                    f"Secreto {drive.id}",
                    "error",
                    f"No se pudo descifrar: {type(error).__name__}.",
                    f"Actualice la contraseña con drivemap set {drive.id} --password.",
                )
            )
    acl_ok, acl_detail = inspect_acl(program_data_dir)
    findings.append(
        Finding(
            "ACL ProgramData",
            "ok" if acl_ok else "error",
            acl_detail,
            "Ejecute install.ps1 nuevamente para reaplicar la ACL." if not acl_ok else "",
        )
    )
    return findings

