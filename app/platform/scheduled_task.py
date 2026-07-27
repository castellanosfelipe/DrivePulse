"""Inspect and start installed tasks without recreating Scheduler logic in the CLI."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TaskStatus:
    """Represent the support-relevant portion of a scheduled task."""

    name: str
    exists: bool
    state: str = ""
    last_run_time: str = ""
    last_result: int | None = None
    detail: str = ""


def start_task(name: str) -> None:
    """Start an installed task and raise an actionable error on failure."""

    completed = subprocess.run(
        ["schtasks.exe", "/Run", "/TN", name],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise OSError(
            f"No se pudo iniciar la tarea {name}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )


def inspect_task(name: str) -> TaskStatus:
    """Query task state and last result through PowerShell 5.1 JSON output."""

    escaped = name.replace("'", "''")
    script = (
        f"$task=Get-ScheduledTask -TaskName '{escaped}' -ErrorAction Stop;"
        f"$info=Get-ScheduledTaskInfo -TaskName '{escaped}' -ErrorAction Stop;"
        "[pscustomobject]@{State=[string]$task.State;"
        "LastRunTime=[string]$info.LastRunTime;"
        "LastTaskResult=[int]$info.LastTaskResult}|ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return TaskStatus(
            name,
            False,
            detail=(completed.stderr or completed.stdout).strip(),
        )
    try:
        data = json.loads(completed.stdout)
        return TaskStatus(
            name,
            True,
            str(data["State"]),
            str(data["LastRunTime"]),
            int(data["LastTaskResult"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        return TaskStatus(name, False, detail=f"Salida no reconocida: {error}")

