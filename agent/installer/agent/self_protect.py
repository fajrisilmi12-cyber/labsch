"""Self-protection: prevent students from killing the LabSCH agent.

Multi-layer protection:
1. Scheduled Task that re-spawns the agent if killed
2. Registry entry to mark the service as critical
3. Folder/file ACL restrict access
4. Hide agent from Task Manager (best effort)
5. Watchdog: detect kill attempts, log them

The agent uses:
- psutil to monitor itself
- subprocess to re-launch if killed
- Windows Scheduled Tasks for persistence
"""
import os
import sys
import time
import ctypes
import subprocess
from pathlib import Path
from typing import Optional


# v0.3.5 — subprocess.CREATE_NO_WINDOW so spawned reg.exe/schtasks.exe/etc.
# never flash a console window at the student. Fall back to 0 on non-Windows.
try:
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
except AttributeError:
    _NO_WINDOW = 0


def _run(cmd: list, timeout: int = 10, **kw) -> subprocess.CompletedProcess:
    """v0.3.5 — single helper so every subprocess call gets explicit timeout
    + CREATE_NO_WINDOW consistently. Returns CompletedProcess for callers
    that want to inspect stdout/stderr.
    """
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("timeout", timeout)
    kw.setdefault("creationflags", _NO_WINDOW)
    return subprocess.run(cmd, **kw)


def _is_windows() -> bool:
    return os.name == "nt"


def _is_admin() -> bool:
    """Check if running as administrator."""
    if not _is_windows():
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def install_self_protection(agent_path: str, log_fn=print) -> bool:
    """Install multiple layers of self-protection.

    Args:
        agent_path: Full path to LabSCHAgent.exe or python.exe running the script.
        log_fn: callable for logging.

    Returns:
        True if at least one layer installed, False if all failed.
    """
    if not _is_windows():
        log_fn("[self_protect] not Windows, skipping")
        return False

    if not _is_admin():
        log_fn("[self_protect] not running as admin, some protections may fail")

    success_count = 0

    # Layer 1: Scheduled Task that re-spawns agent every 5 minutes
    if _install_scheduled_task(agent_path, log_fn):
        success_count += 1

    # Layer 2: Registry Run key (auto-start on boot)
    if _install_run_key(agent_path, log_fn):
        success_count += 1

    # Layer 3: Disable Task Manager (optional, very aggressive)
    # NOTE: too aggressive, can be reversed via group policy
    # Leaving disabled by default, enable via --lockdown flag

    log_fn(f"[self_protect] installed {success_count} protection layer(s)")
    return success_count > 0


def _install_scheduled_task(agent_path: str, log_fn=print) -> bool:
    """Create a scheduled task that restarts the agent every 5 minutes.

    This is the strongest protection: even if user kills the process,
    Task Scheduler will re-spawn it.
    """
    task_name = "LabSCHAgentWatchdog"

    # Delete existing task first (idempotent)
    _run(
        ["schtasks", "/delete", "/tn", task_name, "/f"],
        timeout=10,
    )

    # Create new task
    cmd = [
        "schtasks", "/create",
        "/tn", task_name,
        "/tr", f'"{agent_path}"',
        "/sc", "minute",
        "/mo", "5",
        "/ru", "SYSTEM",
        "/rl", "HIGHEST",
        "/f",
    ]
    try:
        result = _run(cmd, timeout=15)
        if result.returncode == 0:
            log_fn(f"[self_protect] scheduled task created: {task_name}")
            return True
        else:
            log_fn(f"[self_protect] scheduled task failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        log_fn("[self_protect] scheduled task timeout")
        return False


def _install_run_key(agent_path: str, log_fn=print) -> bool:
    """Add to HKLM Run key for boot-time auto-start."""
    key_path = r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
    cmd = [
        "reg", "add", key_path,
        "/v", "LabSCHAgent",
        "/t", "REG_SZ",
        "/d", f'"{agent_path}"',
        "/f",
    ]
    try:
        result = _run(cmd, timeout=10)
        if result.returncode == 0:
            log_fn(f"[self_protect] run key added: HKLM\\...\\Run\\LabSCHAgent")
            return True
        log_fn(f"[self_protect] run key failed: {result.stderr}")
        return False
    except subprocess.TimeoutExpired:
        return False


def uninstall_self_protection(log_fn=print) -> bool:
    """Remove all self-protection layers."""
    if not _is_windows():
        return False

    success = 0

    # Remove scheduled task
    try:
        result = _run(
            ["schtasks", "/delete", "/tn", "LabSCHAgentWatchdog", "/f"],
            timeout=10,
        )
        if result.returncode == 0:
            log_fn("[self_protect] scheduled task removed")
            success += 1
    except subprocess.TimeoutExpired:
        pass

    # Remove run key
    try:
        result = _run(
            ["reg", "delete", r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
             "/v", "LabSCHAgent", "/f"],
            timeout=10,
        )
        if result.returncode == 0:
            log_fn("[self_protect] run key removed")
            success += 1
    except subprocess.TimeoutExpired:
        pass

    return success > 0


def install_filesystem_protection(agent_dir: str, log_fn=print) -> bool:
    """Restrict write/delete access to agent folder.

    Uses icacls to deny write access to Users group.
    Admin can still modify (for updates).
    """
    if not _is_windows():
        return False

    cmd = [
        "icacls", agent_dir,
        "/deny", "Users:(W,DC,DE)",
        "/inheritance:r",
    ]
    try:
        result = _run(cmd, timeout=15)
        if result.returncode == 0:
            log_fn(f"[self_protect] filesystem restricted: {agent_dir}")
            return True
        log_fn(f"[self_protect] filesystem restrict failed: {result.stderr}")
        return False
    except subprocess.TimeoutExpired:
        return False


def disable_task_manager(log_fn=print) -> bool:
    """Aggressive: disable Task Manager so user can't kill the agent.

    WARNING: this also prevents user from using Task Manager for anything.
    Reversible via group policy.
    """
    if not _is_windows():
        return False

    cmd = [
        "reg", "add",
        r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
        "/v", "DisableTaskMgr",
        "/t", "REG_DWORD",
        "/d", "1",
        "/f",
    ]
    try:
        result = _run(cmd, timeout=10)
        if result.returncode == 0:
            log_fn("[self_protect] Task Manager disabled")
            return True
        return False
    except subprocess.TimeoutExpired:
        return False


def enable_task_manager(log_fn=print) -> bool:
    """Re-enable Task Manager."""
    if not _is_windows():
        return False

    cmd = [
        "reg", "delete",
        r"HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System",
        "/v", "DisableTaskMgr",
        "/f",
    ]
    try:
        result = _run(cmd, timeout=10)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


# CLI
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="LabSCH self-protection")
    parser.add_argument("action", choices=["install", "uninstall", "lockdown", "unlockdown", "protect-files"])
    parser.add_argument("--path", help="Agent exe path (required for install/protect-files)")
    args = parser.parse_args()

    if args.action == "install":
        if not args.path:
            print("ERROR: --path required for install")
            sys.exit(1)
        install_self_protection(args.path)
    elif args.action == "uninstall":
        uninstall_self_protection()
    elif args.action == "lockdown":
        disable_task_manager()
    elif args.action == "unlockdown":
        enable_task_manager()
    elif args.action == "protect-files":
        if not args.path:
            print("ERROR: --path required for protect-files")
            sys.exit(1)
        install_filesystem_protection(args.path)
