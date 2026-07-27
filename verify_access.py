"""Perform one bounded child-process filesystem read for the parent agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    path = Path(sys.argv[1])
    try:
        if path.is_dir():
            with os.scandir(path) as entries:
                next(entries, None)
        else:
            with path.open("rb") as handle:
                handle.read(1)
    except OSError as error:
        print(f"{type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print("acceso verificado")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

