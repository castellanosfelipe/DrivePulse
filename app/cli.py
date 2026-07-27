"""Expose safe administration commands without ever accepting a password value."""

from __future__ import annotations

import argparse
import getpass
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from app import __version__
from app.config import (
    AGENT_HEARTBEAT_PATH,
    CONFIG_PATH,
    DATABASE_PATH,
    ENTROPY_PATH,
    FERNET_KEY_PATH,
    LOG_DIR,
    PROGRAM_DATA_DIR,
    PROGRAM_FILES_DIR,
    RECONCILE_SIGNAL_PATH,
    USER_VIEWS_DIR,
    ensure_runtime_directories,
)
from app.db import StateDatabase
from app.doctor import run_doctor
from app.errors import ConfigurationError, ConnectivityError, PrivilegeError
from app.mapper import WindowsNetworkMapper
from app.models import AppSettings, DriveScope, DriveSpec
from app.platform.detect import is_admin
from app.platform.network import unc_host
from app.platform.scheduled_task import start_task
from app.platform.secretstore import SecretStore, create_secret_store
from app.platform.signals import notify
from app.platform.volumes import find_free_letter, inspect_letter
from app.settings_store import SettingsStore
from app.user_views import sync_user_views

EXIT_OK = 0
EXIT_USAGE = 1
EXIT_CONFIG = 2
EXIT_CONNECTIVITY = 3
EXIT_PRIVILEGE = 4


@dataclass
class Runtime:
    store: SettingsStore
    secrets: SecretStore
    database: StateDatabase


def create_runtime() -> Runtime:
    ensure_runtime_directories()
    secrets = create_secret_store(ENTROPY_PATH, FERNET_KEY_PATH)
    return Runtime(
        SettingsStore(CONFIG_PATH, secrets),
        secrets,
        StateDatabase(DATABASE_PATH),
    )


def require_admin() -> None:
    if not is_admin():
        raise PrivilegeError(
            "Este comando modifica configuración protegida. "
            "Abra la consola como administrador."
        )


def save_and_notify(runtime: Runtime, settings: AppSettings) -> None:
    runtime.store.save(settings)
    has_user_scope = any(
        drive.scope is DriveScope.USER for drive in settings.drives
    )
    if has_user_scope or USER_VIEWS_DIR.exists():
        sync_user_views(
            settings,
            USER_VIEWS_DIR,
            ENTROPY_PATH,
            PROGRAM_FILES_DIR / "agent" / "agent.exe",
        )
    notify(RECONCILE_SIGNAL_PATH)
    try:
        start_task("DriveMapper-System")
    except OSError:
        pass


def find_drive(settings: AppSettings, drive_id: str) -> DriveSpec:
    for drive in settings.drives:
        if drive.id == drive_id:
            return drive
    raise ConfigurationError(f"No existe una unidad con id '{drive_id}'.")


def command_list(args: argparse.Namespace, runtime: Runtime) -> int:
    settings = runtime.store.load()
    status = {item["drive_id"]: item for item in runtime.database.statuses()}
    rows = []
    for drive in settings.drives:
        state = status.get(drive.id, {})
        rows.append(
            {
                "id": drive.id,
                "letter": drive.letter,
                "unc": drive.unc,
                "scope": drive.scope.value,
                "enabled": drive.enabled,
                "state": state.get("state", "sin datos"),
                "last_error": state.get("detail", ""),
            }
        )
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return EXIT_OK
    headers = ("ID", "LETRA", "SCOPE", "HABILITADA", "ESTADO", "UNC")
    print("  ".join(headers))
    for row in rows:
        print(
            f"{row['id']:<18} {row['letter']:<5} {row['scope']:<7} "
            f"{str(row['enabled']):<10} {row['state']:<12} {row['unc']}"
        )
    return EXIT_OK


def _prompt_password(confirm: bool = True) -> str:
    password = getpass.getpass("Contraseña SMB: ")
    if not password:
        raise ConfigurationError("La contraseña no puede estar vacía.")
    if confirm and password != getpass.getpass("Confirmar contraseña SMB: "):
        raise ConfigurationError("Las contraseñas no coinciden.")
    return password


def command_add(args: argparse.Namespace, runtime: Runtime) -> int:
    require_admin()
    settings = runtime.store.load()
    if inspect_letter(args.letter).is_physical:
        raise ConfigurationError(
            f"{args.letter} está ocupada por un volumen físico."
        )
    password = _prompt_password()
    drive = DriveSpec(
        id=args.id,
        letter=args.letter,
        unc=args.unc,
        username=args.user,
        secret=runtime.secrets.protect(password),
        scope=args.scope,
        target_user=args.target_user,
        persistent=args.persistent,
        verify_path=args.verify_path,
        description=args.description,
    )
    updated = settings.model_copy(
        update={"drives": [*settings.drives, drive]}
    )
    updated = AppSettings.model_validate(updated.model_dump())
    save_and_notify(runtime, updated)
    print(f"Unidad {drive.id} agregada; el agente fue notificado.")
    return EXIT_OK


def command_remove(args: argparse.Namespace, runtime: Runtime) -> int:
    require_admin()
    settings = runtime.store.load()
    drive = find_drive(settings, args.id)
    if args.keep_mounted:
        runtime.database.remove_managed(
            drive.id, drive.scope.value, drive.target_user or ""
        )
    updated = settings.model_copy(
        update={"drives": [item for item in settings.drives if item.id != args.id]}
    )
    save_and_notify(runtime, AppSettings.model_validate(updated.model_dump()))
    print(
        f"Unidad {args.id} eliminada"
        + (" y dejada montada." if args.keep_mounted else "; se desmontará.")
    )
    return EXIT_OK


def command_toggle(
    args: argparse.Namespace, runtime: Runtime, enabled: bool
) -> int:
    require_admin()
    settings = runtime.store.load()
    target = find_drive(settings, args.id)
    drives = [
        item.model_copy(update={"enabled": enabled}) if item.id == target.id else item
        for item in settings.drives
    ]
    save_and_notify(
        runtime,
        AppSettings.model_validate(settings.model_copy(update={"drives": drives}).model_dump()),
    )
    print(f"Unidad {args.id} {'habilitada' if enabled else 'deshabilitada'}.")
    return EXIT_OK


def command_set(args: argparse.Namespace, runtime: Runtime) -> int:
    require_admin()
    settings = runtime.store.load()
    target = find_drive(settings, args.id)
    changes = {
        key: value
        for key, value in {
            "letter": args.letter,
            "unc": args.unc,
            "username": args.user,
            "verify_path": args.verify_path,
            "description": args.description,
        }.items()
        if value is not None
    }
    if args.password:
        changes["secret"] = runtime.secrets.protect(_prompt_password())
    if not changes:
        raise ConfigurationError("No se indicó ningún cambio.")
    replacement = target.model_copy(update=changes)
    drives = [
        replacement if item.id == target.id else item for item in settings.drives
    ]
    save_and_notify(
        runtime,
        AppSettings.model_validate(settings.model_copy(update={"drives": drives}).model_dump()),
    )
    runtime.database.clear_retry(target.id)
    print(f"Unidad {target.id} actualizada.")
    return EXIT_OK


def command_test(args: argparse.Namespace, runtime: Runtime) -> int:
    require_admin()
    drive = find_drive(runtime.store.load(), args.id)
    temporary_letter = find_free_letter()
    temporary = drive.model_copy(
        update={"letter": temporary_letter, "persistent": False}
    )
    mapper = WindowsNetworkMapper()
    password = runtime.secrets.unprotect(drive.secret)
    try:
        mapper.connect(temporary, password)
        result = mapper.observe(temporary, 20)
        if not result.accessible:
            raise ConnectivityError(
                f"El mapeo temporal no es accesible: {result.detail}"
            )
        print(
            f"Prueba correcta: {drive.unc} fue accesible temporalmente en "
            f"{temporary_letter}."
        )
        return EXIT_OK
    finally:
        mapper.cancel(temporary_letter, force=True)


def command_apply(_args: argparse.Namespace, _runtime: Runtime) -> int:
    require_admin()
    notify(RECONCILE_SIGNAL_PATH)
    start_task("DriveMapper-System")
    print("Reconciliación solicitada en el contexto SYSTEM.")
    return EXIT_OK


def command_status(args: argparse.Namespace, runtime: Runtime) -> int:
    heartbeat: dict[str, object] = {}
    if AGENT_HEARTBEAT_PATH.exists():
        try:
            heartbeat = json.loads(AGENT_HEARTBEAT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            heartbeat = {}
    payload = {
        "agent_running": bool(heartbeat)
        and time.time() - float(heartbeat.get("updated_at_epoch", 0)) < 180,
        "uptime_s": (
            int(time.time() - float(heartbeat.get("started_at_epoch", time.time())))
            if heartbeat
            else None
        ),
        "drives": runtime.database.statuses(),
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"Agente activo: {'sí' if payload['agent_running'] else 'no'}")
        print(f"Uptime: {payload['uptime_s'] if payload['uptime_s'] is not None else '-'} s")
        for item in payload["drives"]:
            print(
                f"{item['drive_id']}: {item['state']} — {item['detail']}"
            )
    return EXIT_OK


def command_logs(args: argparse.Namespace, _runtime: Runtime) -> int:
    path = LOG_DIR / "agent.log"
    if not path.exists():
        print("Todavía no existe agent.log.")
        return EXIT_OK
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(lines[-args.tail :]))
    return EXIT_OK


def command_doctor(args: argparse.Namespace, runtime: Runtime) -> int:
    findings = run_doctor(runtime.store.load(), runtime.secrets, PROGRAM_DATA_DIR)
    if args.json:
        print(json.dumps([item.to_dict() for item in findings], ensure_ascii=False, indent=2))
    else:
        symbols = {"ok": "✅", "warning": "⚠", "error": "❌"}
        for finding in findings:
            print(f"{symbols[finding.status]} {finding.check}: {finding.detail}")
            if finding.action:
                print(f"   Acción: {finding.action}")
    return EXIT_CONNECTIVITY if any(item.status == "error" for item in findings) else EXIT_OK


def command_export(args: argparse.Namespace, runtime: Runtime) -> int:
    settings = runtime.store.load()
    payload = settings.model_dump(mode="json")
    for drive in payload["drives"]:
        drive.pop("secret", None)
    Path(args.file).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Configuración sin secretos exportada a {args.file}.")
    return EXIT_OK


def command_import(args: argparse.Namespace, runtime: Runtime) -> int:
    require_admin()
    try:
        raw = json.loads(Path(args.file).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"No se pudo importar: {error}") from error
    for drive in raw.get("drives", []):
        if "secret" not in drive:
            print(f"Credencial para {drive.get('id', drive.get('unc', 'unidad'))}")
            drive["secret"] = runtime.secrets.protect(_prompt_password())
    settings = AppSettings.model_validate(raw)
    for drive in settings.drives:
        if inspect_letter(drive.letter).is_physical:
            raise ConfigurationError(
                f"{drive.letter} está ocupada por un volumen físico."
            )
    save_and_notify(runtime, settings)
    print(f"Se importaron {len(settings.drives)} unidades.")
    return EXIT_OK


def command_sync_user_tasks(
    _args: argparse.Namespace, runtime: Runtime
) -> int:
    require_admin()
    views = sync_user_views(
        runtime.store.load(),
        USER_VIEWS_DIR,
        ENTROPY_PATH,
        PROGRAM_FILES_DIR / "agent" / "agent.exe",
    )
    print(f"Se sincronizaron {len(views)} tareas de usuario.")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="drivemap",
        description=(
            "Administra mapeos SMB persistentes. Las contraseñas nunca se aceptan "
            "como valor de argumento; se solicitan mediante prompt oculto."
        ),
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="Listar unidades configuradas")
    list_parser.add_argument("--json", action="store_true")
    list_parser.set_defaults(handler=command_list)

    add = subparsers.add_parser("add", help="Agregar una unidad")
    add.add_argument("--id", required=True)
    add.add_argument("--letter", required=True)
    add.add_argument("--unc", required=True)
    add.add_argument("--user", required=True)
    add.add_argument("--scope", choices=["system", "user"], default="system")
    add.add_argument("--target-user")
    persistence = add.add_mutually_exclusive_group()
    persistence.add_argument("--persistent", action="store_true", default=None)
    persistence.add_argument("--no-persistent", dest="persistent", action="store_false")
    add.add_argument("--verify-path", default="")
    add.add_argument("--description", default="")
    add.set_defaults(handler=command_add)

    remove = subparsers.add_parser("remove", help="Eliminar una unidad")
    remove.add_argument("id")
    remove.add_argument("--keep-mounted", action="store_true")
    remove.set_defaults(handler=command_remove)

    for name, enabled in (("enable", True), ("disable", False)):
        toggle = subparsers.add_parser(name)
        toggle.add_argument("id")
        toggle.set_defaults(
            handler=lambda args, runtime, state=enabled: command_toggle(
                args, runtime, state
            )
        )

    set_parser = subparsers.add_parser("set", help="Editar una unidad")
    set_parser.add_argument("id")
    set_parser.add_argument("--letter")
    set_parser.add_argument("--unc")
    set_parser.add_argument("--user")
    set_parser.add_argument(
        "--password",
        action="store_true",
        help="Solicitar una contraseña nueva mediante prompt oculto",
    )
    set_parser.add_argument("--verify-path")
    set_parser.add_argument("--description")
    set_parser.set_defaults(handler=command_set)

    test_parser = subparsers.add_parser("test", help="Probar sin cambiar configuración")
    test_parser.add_argument("id")
    test_parser.set_defaults(handler=command_test)

    apply_parser = subparsers.add_parser("apply", help="Forzar reconciliación SYSTEM")
    apply_parser.set_defaults(handler=command_apply)

    status = subparsers.add_parser("status", help="Mostrar estado vivo")
    status.add_argument("--json", action="store_true")
    status.set_defaults(handler=command_status)

    logs = subparsers.add_parser("logs", help="Mostrar las últimas líneas del log")
    logs.add_argument("--tail", type=int, default=100)
    logs.set_defaults(handler=command_logs)

    doctor = subparsers.add_parser("doctor", help="Diagnóstico de solo lectura")
    doctor.add_argument("--json", action="store_true")
    doctor.set_defaults(handler=command_doctor)

    export = subparsers.add_parser("export", help="Exportar sin secretos")
    export.add_argument("file")
    export.set_defaults(handler=command_export)

    import_parser = subparsers.add_parser("import", help="Importar y solicitar secretos")
    import_parser.add_argument("file")
    import_parser.set_defaults(handler=command_import)
    sync_users = subparsers.add_parser(
        "sync-user-tasks",
        help=argparse.SUPPRESS,
    )
    sync_users.set_defaults(handler=command_sync_user_tasks)
    return parser


def main(argv: list[str] | None = None, runtime: Runtime | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        active_runtime = runtime or create_runtime()
        return int(args.handler(args, active_runtime))
    except PrivilegeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_PRIVILEGE
    except ConfigurationError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIG
    except ConnectivityError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONNECTIVITY
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIG
