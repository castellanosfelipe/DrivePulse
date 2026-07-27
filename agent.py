"""Start one DriveMapper watchdog in the requested Windows logon scope."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import signal
import sys
from pathlib import Path

from app import __version__
from app.config import (
    AGENT_HEARTBEAT_PATH,
    CONFIG_PATH,
    DATABASE_PATH,
    ENTROPY_PATH,
    FERNET_KEY_PATH,
    LOG_DIR,
    RECONCILE_SIGNAL_PATH,
    ensure_runtime_directories,
)
from app.db import StateDatabase
from app.eventlog import EventLogPublisher
from app.logging_setup import configure_logging
from app.mapper import WindowsNetworkMapper
from app.models import DriveScope
from app.platform.mutex import NamedMutex
from app.platform.secretstore import create_secret_store
from app.reconciler import Reconciler
from app.settings_store import SettingsStore
from app.watchdog import Watchdog


def self_test() -> int:
    """Verify modules PyInstaller commonly omits from a frozen bundle."""

    modules = [
        "win32wnet",
        "win32crypt",
        "win32net",
        "win32evtlog",
        "pydantic",
        "sqlite3",
    ]
    for module in modules:
        importlib.import_module(module)
    print(f"DriveMapper {__version__}: self-test correcto")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Agente watchdog de DriveMapper")
    parser.add_argument("--scope", choices=["system", "user"], default="system")
    parser.add_argument("--target-user", default="")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--remove-managed", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--config-path", type=Path, default=CONFIG_PATH)
    parser.add_argument("--database-path", type=Path, default=DATABASE_PATH)
    parser.add_argument("--entropy-path", type=Path, default=ENTROPY_PATH)
    parser.add_argument("--log-dir", type=Path, default=LOG_DIR)
    parser.add_argument("--signal-path", type=Path, default=RECONCILE_SIGNAL_PATH)
    parser.add_argument("--heartbeat-path", type=Path, default=AGENT_HEARTBEAT_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    if args.scope == "system":
        ensure_runtime_directories()
        fernet_key_path = FERNET_KEY_PATH
    else:
        for directory in (
            args.config_path.parent,
            args.database_path.parent,
            args.log_dir,
            args.signal_path.parent,
            args.heartbeat_path.parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        fernet_key_path = args.database_path.parent / ".dev-fernet.key"
    logger = configure_logging(
        args.log_dir, console=not getattr(sys, "frozen", False)
    )
    identity = (args.target_user or "SYSTEM").casefold()
    identity_token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
    mutex_namespace = "Global" if args.scope == "system" else "Local"
    mutex_name = (
        f"{mutex_namespace}\\DriveMapper-{args.scope}-{identity_token}"
    )
    try:
        with NamedMutex(mutex_name) as mutex:
            if not mutex.acquired:
                logger.info(
                    "Ya existe un agente para este scope; no se inicia otro."
                )
                return 0
            database = StateDatabase(args.database_path)
            mapper = WindowsNetworkMapper()
            if args.remove_managed:
                for managed in database.managed_for(args.scope, args.target_user):
                    remote = mapper.remote_for(managed.letter)
                    if remote and remote.casefold() == managed.unc.casefold():
                        mapper.cancel(managed.letter, force=True)
                    database.remove_managed(
                        managed.drive_id, managed.scope, managed.target_user
                    )
                    database.update_status(
                        managed.drive_id,
                        "removed",
                        "Mapeo desmontado durante la desinstalación.",
                    )
                return 0
            secrets = create_secret_store(args.entropy_path, fernet_key_path)
            store = SettingsStore(
                args.config_path,
                secrets,
                enforce_acl=args.scope == "system",
            )
            settings = store.load()
            publisher = EventLogPublisher(settings.settings.eventlog_enabled, logger)
            reconciler = Reconciler(
                mapper, secrets, database, logger, publisher
            )
            watchdog = Watchdog(
                store,
                database,
                reconciler,
                args.signal_path,
                args.heartbeat_path,
                logger,
                scope=DriveScope(args.scope),
                target_user=args.target_user,
            )
            signal.signal(signal.SIGTERM, lambda *_: watchdog.stop())
            signal.signal(signal.SIGINT, lambda *_: watchdog.stop())
            return watchdog.run(once=args.once)
    except Exception:
        logger.exception("El agente terminó por un error no controlado.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
