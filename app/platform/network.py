"""Provide bounded network prerequisite checks without changing Windows settings."""

from __future__ import annotations

import socket
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EndpointCheck:
    """Capture ICMP and SMB port reachability for doctor output."""

    host: str
    icmp_ok: bool
    tcp_445_ok: bool
    detail: str


def check_endpoint(host: str, timeout_s: float = 3.0) -> EndpointCheck:
    """Probe ICMP and TCP/445; SMB reachability is judged primarily by TCP."""

    ping = subprocess.run(
        ["ping", "-n", "1", "-w", str(int(timeout_s * 1000)), host],
        capture_output=True,
        text=True,
        check=False,
    )
    tcp_ok = False
    detail = ""
    try:
        with socket.create_connection((host, 445), timeout=timeout_s):
            tcp_ok = True
    except OSError as error:
        detail = str(error)
    return EndpointCheck(host, ping.returncode == 0, tcp_ok, detail)


def unc_host(unc: str) -> str:
    """Extract a host from a structurally validated UNC root."""

    return unc.lstrip("\\").split("\\", 1)[0]

