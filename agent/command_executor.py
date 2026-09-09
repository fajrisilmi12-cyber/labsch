"""Verified Windows executors for LabSCH remote power and lock commands."""
from dataclasses import dataclass
import ctypes
import os
import subprocess

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass(frozen=True)
class Outcome:
    ok: bool
    reason: str


def _text(data) -> str:
    if not data:
        return ""
    if isinstance(data, bytes):
        return data.decode("utf-8", errors="replace").strip()
    return str(data).strip()


def _lock_active_console() -> tuple[bool, str]:
    if os.name != "nt":
        return False, "lock requires Windows"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    session = kernel32.WTSGetActiveConsoleSessionId()
    if session == 0xFFFFFFFF:
        return False, "no active console session"
    # Disconnecting the interactive session displays the Windows sign-in screen.
    # Unlike LockWorkStation from Session 0, this acts on the actual console user.
    if not wtsapi32.WTSDisconnectSession(None, session, False):
        return False, f"WTSDisconnectSession session={session} winerror={ctypes.get_last_error()}"
    return True, f"WTSDisconnectSession session={session}"


def execute(command: str) -> Outcome:
    if command == "lock":
        ok, reason = _lock_active_console()
        return Outcome(ok, reason)
    switches = {"shutdown": "/s", "restart": "/r"}
    switch = switches.get(command)
    if not switch:
        return Outcome(False, f"unsupported command: {command}")
    system_root = os.environ.get("SystemRoot", r"C:\Windows")
    executable = os.path.join(system_root, "System32", "shutdown.exe")
    try:
        result = subprocess.run(
            [executable, switch, "/t", "0", "/f", "/d", "p:0:0", "/c", f"LabSCH remote {command}"],
            capture_output=True, timeout=15, creationflags=_NO_WINDOW,
        )
    except Exception as exc:
        return Outcome(False, f"{type(exc).__name__}: {exc}")
    stderr = _text(result.stderr)
    stdout = _text(result.stdout)
    detail = stderr or stdout or "accepted by shutdown.exe"
    return Outcome(result.returncode == 0, f"exit={result.returncode}: {detail}")
