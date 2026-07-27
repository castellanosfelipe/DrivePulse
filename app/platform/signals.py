"""Wake a running agent through a local sentinel without exposing a network port."""

from __future__ import annotations

import os
import time
from pathlib import Path


def notify(path: Path) -> None:
    """Atomically update the reconciliation sentinel."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(str(time.time_ns()), encoding="ascii")
    os.replace(temporary, path)


def token(path: Path) -> int:
    """Return a cheap change token for the sentinel."""

    try:
        return path.stat().st_mtime_ns
    except FileNotFoundError:
        return 0

