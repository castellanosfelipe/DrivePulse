"""Inspect and start installed tasks without recreating Scheduler logic in the CLI."""

from __future__ import annotations

import json
import html
import subprocess
from pathlib import Path
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


def register_user_task(
    account: str,
    sid: str,
    agent_path: Path,
    view_root: Path,
    entropy_path: Path,
) -> str:
    """Register an AtLogOn watchdog in the user's own logon session."""

    task_name = f"DriveMapper-User-{sid}"
    arguments = " ".join(
        [
            "--scope user",
            f'--target-user &quot;{html.escape(account)}&quot;',
            f'--config-path &quot;{html.escape(str(view_root / "config.json"))}&quot;',
            f'--database-path &quot;{html.escape(str(view_root / "data" / "drivemapper.db"))}&quot;',
            f'--entropy-path &quot;{html.escape(str(entropy_path))}&quot;',
            f'--log-dir &quot;{html.escape(str(view_root / "logs"))}&quot;',
            f'--signal-path &quot;{html.escape(str(view_root / "data" / ".reconcile"))}&quot;',
            f'--heartbeat-path &quot;{html.escape(str(view_root / "data" / "agent-status.json"))}&quot;',
        ]
    )
    escaped_agent = html.escape(str(agent_path))
    escaped_working = html.escape(str(agent_path.parent))
    escaped_sid = html.escape(sid)
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Author>DriveMapper</Author><Description>Mapeos SMB del usuario {escaped_sid}.</Description></RegistrationInfo>
  <Triggers><LogonTrigger><Enabled>true</Enabled><UserId>{escaped_sid}</UserId></LogonTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>{escaped_sid}</UserId><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec><Command>{escaped_agent}</Command><Arguments>{arguments}</Arguments><WorkingDirectory>{escaped_working}</WorkingDirectory></Exec></Actions>
</Task>"""
    xml_path = view_root / "task.xml"
    xml_path.write_text(xml, encoding="utf-16")
    completed = subprocess.run(
        ["schtasks.exe", "/Create", "/TN", task_name, "/XML", str(xml_path), "/F"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise OSError(
            f"No se pudo registrar {task_name}: "
            f"{(completed.stderr or completed.stdout).strip()}"
        )
    return task_name

