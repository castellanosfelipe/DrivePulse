"""Centralize filesystem locations so production ACLs and tests stay predictable."""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "DriveMapper"
PROGRAM_FILES_DIR = Path(
    os.environ.get("DRIVEMAPPER_INSTALL_DIR", r"C:\Program Files\DriveMapper")
)
PROGRAM_DATA_DIR = Path(
    os.environ.get("DRIVEMAPPER_DATA_DIR", r"C:\ProgramData\DriveMapper")
)
CONFIG_PATH = PROGRAM_DATA_DIR / "config.json"
DATA_DIR = PROGRAM_DATA_DIR / "data"
LOG_DIR = PROGRAM_DATA_DIR / "logs"
DATABASE_PATH = DATA_DIR / "drivemapper.db"
ENTROPY_PATH = DATA_DIR / ".entropy"
FERNET_KEY_PATH = DATA_DIR / ".dev-fernet.key"
RECONCILE_SIGNAL_PATH = DATA_DIR / ".reconcile"
AGENT_HEARTBEAT_PATH = DATA_DIR / "agent-status.json"


def ensure_runtime_directories() -> None:
    """Create mutable runtime directories before an elevated ACL pass."""

    for path in (PROGRAM_DATA_DIR, DATA_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)

