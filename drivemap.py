"""Launch the operator CLI from source or the frozen console executable."""

from __future__ import annotations

from app.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

