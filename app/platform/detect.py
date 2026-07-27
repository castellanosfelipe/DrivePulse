"""Detect Windows capabilities without importing pywin32 on development hosts."""

from __future__ import annotations

import ctypes
import os
import sys


def is_windows() -> bool:
    """Return whether the current interpreter runs on Windows."""

    return sys.platform == "win32"


def is_admin() -> bool:
    """Return administrative elevation state, false on unsupported platforms."""

    if not is_windows():
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False

