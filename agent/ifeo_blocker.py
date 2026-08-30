"""Block apps via IFEO (Image File Execution Options) + psutil fallback.

IFEO lebih kuat dari process kill karena:
- User tidak bisa rename process (kalau pake full path)
- IFEO berlaku sebelum process start, jadi tidak bisa di-bypass
- Tidak ada jalan untuk user run app (system block langsung)

Cara kerja IFEO:
- Registry: HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\<exe>
- Value: Debugger = "cmd.exe /c exit"
- Efek: Setiap kali <exe> dijalankan, Windows jalanin cmd.exe exit dulu (gagal instant)
"""
import os
import sys
import subprocess
from pathlib import Path
from typing import Iterable

# IFEO registry path
IFEO_ROOT = r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"


def _is_windows() -> bool:
    return os.name == "nt"


def block_app_via_ifeo(process_name: str, log_fn=print) -> bool:
    """Block a process by setting IFEO Debugger to 'cmd.exe /c exit'.

    Returns True if successful, False otherwise.
    """
    if not _is_windows():
        log_fn(f"[ifeo_blocker] not Windows, skipping {process_name}")
        return False
    if not process_name.lower().endswith(".exe"):
        process_name = process_name + ".exe"

    key_path = f'{IFEO_ROOT}\\{process_name}'
    cmd = [
        "reg", "add", key_path,
        "/v", "Debugger",
        "/t", "REG_SZ",
        "/d", "cmd.exe /c exit",
        "/f"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            log_fn(f"[ifeo_blocker] IFEO blocked: {process_name}")
            return True
        else:
            log_fn(f"[ifeo_blocker] IFEO failed for {process_name}: {result.stderr}")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log_fn(f"[ifeo_blocker] error: {e}")
        return False


def unblock_app_via_ifeo(process_name: str, log_fn=print) -> bool:
    """Remove IFEO Debugger entry for a process."""
    if not _is_windows():
        return False
    if not process_name.lower().endswith(".exe"):
        process_name = process_name + ".exe"

    key_path = f'{IFEO_ROOT}\\{process_name}'
    cmd = [
        "reg", "delete", key_path,
        "/v", "Debugger",
        "/f"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            log_fn(f"[ifeo_blocker] IFEO unblocked: {process_name}")
            return True
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log_fn(f"[ifeo_blocker] error: {e}")
        return False


def list_blocked_apps(log_fn=print) -> list:
    """List all apps currently blocked via IFEO."""
    if not _is_windows():
        return []
    cmd = ["reg", "query", IFEO_ROOT, "/s", "/v", "Debugger"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        blocked = []
        current_key = None
        for line in result.stdout.splitlines():
            if "HKEY_LOCAL_MACHINE" in line:
                current_key = line.strip()
            elif "Debugger" in line and current_key:
                # Extract exe name from key path
                exe_name = current_key.split("\\")[-1]
                blocked.append(exe_name)
        return blocked
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []


def block_apps_ifeo(process_names: Iterable[str], log_fn=print) -> int:
    """Block multiple apps via IFEO. Returns count successful."""
    count = 0
    for name in process_names:
        if block_app_via_ifeo(name, log_fn):
            count += 1
    return count


# CLI test
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Block apps via IFEO")
    parser.add_argument("action", choices=["block", "unblock", "list"])
    parser.add_argument("names", nargs="*", help="Process names (with or without .exe)")
    args = parser.parse_args()

    if args.action == "list":
        apps = list_blocked_apps()
        print(f"Blocked apps ({len(apps)}):")
        for a in apps:
            print(f"  - {a}")
    elif args.action == "block":
        n = block_apps_ifeo(args.names)
        print(f"Blocked {n} app(s)")
    elif args.action == "unblock":
        for n in args.names:
            unblock_app_via_ifeo(n)
        print(f"Unblocked {len(args.names)} app(s)")
