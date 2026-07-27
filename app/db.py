"""Persist ownership, transitions, incidents and retry suppression across restarts."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterator


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class ManagedMapping:
    drive_id: str
    scope: str
    target_user: str
    letter: str
    unc: str


class StateDatabase:
    """Use short SQLite transactions so SYSTEM and user agents can coexist."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY,
                    drive_id TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    state TEXT NOT NULL,
                    cause TEXT NOT NULL,
                    winerror INTEGER
                );
                CREATE TABLE IF NOT EXISTS incidents (
                    id INTEGER PRIMARY KEY,
                    drive_id TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT,
                    cause TEXT NOT NULL,
                    winerror INTEGER,
                    UNIQUE(drive_id, ended_at)
                );
                CREATE TABLE IF NOT EXISTS managed_mappings (
                    drive_id TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    target_user TEXT NOT NULL DEFAULT '',
                    letter TEXT NOT NULL,
                    unc TEXT NOT NULL,
                    last_applied_at TEXT NOT NULL,
                    PRIMARY KEY (drive_id, scope, target_user)
                );
                CREATE TABLE IF NOT EXISTS drive_status (
                    drive_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    winerror INTEGER,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS retry_state (
                    drive_id TEXT PRIMARY KEY,
                    fingerprint TEXT NOT NULL,
                    attempts INTEGER NOT NULL,
                    next_attempt_at REAL,
                    permanent INTEGER NOT NULL
                );
                """
            )

    def update_status(
        self,
        drive_id: str,
        state: str,
        detail: str,
        winerror: int | None = None,
        level: str = "Information",
    ) -> bool:
        with self.connection() as connection:
            previous = connection.execute(
                "SELECT state, detail, winerror FROM drive_status WHERE drive_id=?",
                (drive_id,),
            ).fetchone()
            changed = previous is None or tuple(previous) != (state, detail, winerror)
            connection.execute(
                """
                INSERT INTO drive_status(drive_id,state,detail,winerror,updated_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(drive_id) DO UPDATE SET
                  state=excluded.state, detail=excluded.detail,
                  winerror=excluded.winerror, updated_at=excluded.updated_at
                """,
                (drive_id, state, detail, winerror, utc_now()),
            )
            if changed:
                connection.execute(
                    """
                    INSERT INTO events(
                      drive_id,occurred_at,level,state,cause,winerror
                    ) VALUES(?,?,?,?,?,?)
                    """,
                    (drive_id, utc_now(), level, state, detail, winerror),
                )
            return changed

    def open_incident(
        self, drive_id: str, cause: str, winerror: int | None = None
    ) -> None:
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT 1 FROM incidents WHERE drive_id=? AND ended_at IS NULL",
                (drive_id,),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO incidents(drive_id,started_at,cause,winerror)
                    VALUES(?,?,?,?)
                    """,
                    (drive_id, utc_now(), cause, winerror),
                )

    def close_incident(self, drive_id: str) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE incidents SET ended_at=?
                WHERE drive_id=? AND ended_at IS NULL
                """,
                (utc_now(), drive_id),
            )

    def upsert_managed(
        self, drive_id: str, scope: str, target_user: str, letter: str, unc: str
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO managed_mappings(
                  drive_id,scope,target_user,letter,unc,last_applied_at
                ) VALUES(?,?,?,?,?,?)
                ON CONFLICT(drive_id,scope,target_user) DO UPDATE SET
                  letter=excluded.letter, unc=excluded.unc,
                  last_applied_at=excluded.last_applied_at
                """,
                (drive_id, scope, target_user, letter, unc, utc_now()),
            )

    def managed_for(self, scope: str, target_user: str = "") -> list[ManagedMapping]:
        with self.connection() as connection:
            rows = connection.execute(
                """
                SELECT drive_id,scope,target_user,letter,unc
                FROM managed_mappings WHERE scope=? AND target_user=?
                """,
                (scope, target_user),
            ).fetchall()
        return [ManagedMapping(**dict(row)) for row in rows]

    def remove_managed(self, drive_id: str, scope: str, target_user: str = "") -> None:
        with self.connection() as connection:
            connection.execute(
                """
                DELETE FROM managed_mappings
                WHERE drive_id=? AND scope=? AND target_user=?
                """,
                (drive_id, scope, target_user),
            )

    def set_retry(
        self,
        drive_id: str,
        fingerprint: str,
        attempts: int,
        next_attempt_at: float | None,
        permanent: bool,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO retry_state(
                  drive_id,fingerprint,attempts,next_attempt_at,permanent
                ) VALUES(?,?,?,?,?)
                ON CONFLICT(drive_id) DO UPDATE SET
                  fingerprint=excluded.fingerprint, attempts=excluded.attempts,
                  next_attempt_at=excluded.next_attempt_at,
                  permanent=excluded.permanent
                """,
                (drive_id, fingerprint, attempts, next_attempt_at, int(permanent)),
            )

    def retries(self) -> dict[str, dict[str, object]]:
        with self.connection() as connection:
            rows = connection.execute("SELECT * FROM retry_state").fetchall()
        return {str(row["drive_id"]): dict(row) for row in rows}

    def clear_retry(self, drive_id: str) -> None:
        with self.connection() as connection:
            connection.execute("DELETE FROM retry_state WHERE drive_id=?", (drive_id,))

    def statuses(self) -> list[dict[str, object]]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT * FROM drive_status ORDER BY drive_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def export_status_json(self) -> str:
        return json.dumps(self.statuses(), ensure_ascii=False)

