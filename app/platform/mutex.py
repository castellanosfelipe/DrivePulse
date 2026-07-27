"""Prevent overlapping agents in the same scope with a named Windows mutex."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self


@dataclass
class NamedMutex:
    """Own and release a process-scoped mutex handle."""

    name: str
    handle: object | None = None
    acquired: bool = False

    def acquire(self) -> bool:
        try:
            import win32api
            import win32event
            import winerror
        except ImportError:
            self.acquired = True
            return True
        self.handle = win32event.CreateMutex(None, False, self.name)
        self.acquired = win32api.GetLastError() != winerror.ERROR_ALREADY_EXISTS
        return self.acquired

    def release(self) -> None:
        if self.handle is None:
            return
        try:
            import win32api

            win32api.CloseHandle(self.handle)
        finally:
            self.handle = None
            self.acquired = False

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()
