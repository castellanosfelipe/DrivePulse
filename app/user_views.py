"""Derive per-SID configuration views so user agents cannot read SYSTEM secrets."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from app.models import AppSettings, DriveScope
from app.platform.acl import harden_user_view
from app.platform.identity import account_sid
from app.platform.scheduled_task import register_user_task


@dataclass(frozen=True, slots=True)
class UserView:
    account: str
    sid: str
    root: Path
    task_name: str


def sync_user_views(
    settings: AppSettings,
    views_root: Path,
    entropy_path: Path,
    agent_path: Path,
) -> list[UserView]:
    """Write least-privilege derived views and idempotent AtLogOn tasks."""

    grouped: dict[str, list] = {}
    for drive in settings.drives:
        if drive.scope is DriveScope.USER and drive.target_user:
            grouped.setdefault(drive.target_user, []).append(drive)

    views_root.mkdir(parents=True, exist_ok=True)
    known: dict[str, tuple[str, Path]] = {}
    for account in grouped:
        sid = account_sid(account)
        known[sid] = (account, views_root / sid)
    for metadata in views_root.glob("*/metadata.json"):
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
            known.setdefault(str(payload["sid"]), (str(payload["account"]), metadata.parent))
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue

    results: list[UserView] = []
    for sid, (account, root) in known.items():
        root.mkdir(parents=True, exist_ok=True)
        (root / "data").mkdir(exist_ok=True)
        (root / "logs").mkdir(exist_ok=True)
        view_settings = settings.model_copy(
            update={"drives": grouped.get(account, [])}
        )
        config_path = root / "config.json"
        temporary = root / "config.json.tmp"
        temporary.write_text(
            json.dumps(
                view_settings.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, config_path)
        (root / "metadata.json").write_text(
            json.dumps({"account": account, "sid": sid}, indent=2) + "\n",
            encoding="utf-8",
        )
        harden_user_view(root, sid, entropy_path)
        task_name = register_user_task(
            account, sid, agent_path, root, entropy_path
        )
        results.append(UserView(account, sid, root, task_name))
    return results

