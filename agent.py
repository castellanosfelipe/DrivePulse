"""Start one DriveMapper watchdog in the requested Windows logon scope."""

from __future__ import annotations

import argparse
import importlib
import signal
import sys

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
    parser.add_argument("--self-test", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.self_test:
        return self_test()
    ensure_runtime_directories()
    logger = configure_logging(LOG_DIR, console=not getattr(sys, "frozen", False))
    mutex_name = f"Global\\DriveMapper-{args.scope}-{args.target_user or 'SYSTEM'}"
    with NamedMutex(mutex_name) as mutex:
        if not mutex.acquired:
            logger.info("Ya existe un agente para este scope; no se inicia otro.")
            return 0
        secrets = create_secret_store(ENTROPY_PATH, FERNET_KEY_PATH)
        store = SettingsStore(CONFIG_PATH, secrets)
        database = StateDatabase(DATABASE_PATH)
        settings = store.load()
        publisher = EventLogPublisher(settings.settings.eventlog_enabled, logger)
        reconciler = Reconciler(
            WindowsNetworkMapper(), secrets, database, logger, publisher
        )
        watchdog = Watchdog(
            store,
            database,
            reconciler,
            RECONCILE_SIGNAL_PATH,
            AGENT_HEARTBEAT_PATH,
            logger,
            scope=DriveScope(args.scope),
            target_user=args.target_user,
        )
        signal.signal(signal.SIGTERM, lambda *_: watchdog.stop())
        signal.signal(signal.SIGINT, lambda *_: watchdog.stop())
        return watchdog.run(once=args.once)


if __name__ == "__main__":
    raise SystemExit(main())

