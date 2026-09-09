"""Block apps via IFEO (Image File Execution Options) + psutil fallback.

IFEO lebih kuat dari process kill karena:
- User tidak bisa rename process (kalau pake full path)
- IFEO berlaku sebelum process start, jadi tidak bisa di-bypass
- Tidak ada jalan untuk user run app (system block langsung)

Cara kerja IFEO:
- Registry: HKLM\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\Image File Execution Options\\<exe>
- Value: Debugger = "cmd.exe /c exit"
- Efek: Setiap kali <exe> dijalankan, Windows jalanin cmd.exe exit dulu (gagal instant)
"""
import json
import os
import sys
import subprocess
from pathlib import Path
from typing import Iterable, List

# IFEO registry path
IFEO_ROOT = r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options"

# v0.3.5 — subprocess.CREATE_NO_WINDOW so spawned reg.exe/schtasks.exe/etc.
# never flash a console window at the student. Fall back to 0 on non-Windows
# so dev on Linux still works.
try:
    _NO_WINDOW = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
except AttributeError:
    _NO_WINDOW = 0

# v0.3.5 — hard deny-list. If we ever IFEO-block these, the agent itself
# cannot run shutdown / restart / notify / uninstall. The list is deliberately
# broad: every shell, every scripting host, and every interpreter that an
# admin tool or recovery flow could need.
_IFEO_DENY_LIST = frozenset({
    "cmd.exe",
    "powershell.exe",
    "pwsh.exe",
    "wscript.exe",
    "cscript.exe",
    "mshta.exe",
    "rundll32.exe",
    "reg.exe",
    "regedit.exe",
    "taskkill.exe",
    "tasklist.exe",
    "schtasks.exe",
    "sc.exe",
    "net.exe",
    "net1.exe",
    "netstat.exe",
    "whoami.exe",
    "systeminfo.exe",
    "wmic.exe",
    "python.exe",
    "pythonw.exe",
    "python3.exe",
    "explorer.exe",
    "mmc.exe",
    "services.exe",
    "taskmgr.exe",
    "dism.exe",
    "sfc.exe",
    "icacls.exe",
    "takeown.exe",
    "attrib.exe",
    "robocopy.exe",
    "xcopy.exe",
    "copy.exe",
    "del.exe",
    "erase.exe",
    "rd.exe",
    "rmdir.exe",
    "format.exe",
    "diskpart.exe",
})

# v0.3.5 — sidecar file that records which apps *we* IFEO'd. On clear, we
# only remove IFEO entries that match this list, so we never accidentally
# unblock an IFEO entry a sysadmin set manually for a different reason.
SIDECAR_DIR = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "LabSCHAgent"
SIDECAR_PATH = SIDECAR_DIR / "ifeo_apps.json"


def _is_windows() -> bool:
    return os.name == "nt"


def _normalize_exe(name: str) -> str:
    """Lowercase the name and ensure it ends in .exe."""
    n = name.strip().lower()
    if not n.endswith(".exe"):
        n = n + ".exe"
    return n


def _is_denied(process_name: str) -> bool:
    """v0.3.5 — True iff we refuse to IFEO-block this executable because
    doing so would break the agent or the OS recovery story."""
    return _normalize_exe(process_name) in _IFEO_DENY_LIST


def _load_sidecar() -> List[str]:
    """Read the sidecar list (the apps *we* IFEO'd). Returns [] on missing
    or corrupt file (fail-closed: treat as empty, won't unblock anything
    we don't know we blocked)."""
    try:
        if not SIDECAR_PATH.exists():
            return []
        raw = SIDECAR_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, list):
            return []
        out = []
        for item in data:
            if isinstance(item, str):
                out.append(_normalize_exe(item))
        return out
    except (OSError, ValueError, json.JSONDecodeError):
        return []


def _save_sidecar(names: Iterable[str]) -> None:
    """Persist the sidecar list atomically (same pattern as config.json)."""
    normalized = sorted({_normalize_exe(n) for n in names if n})
    SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    tmp = SIDECAR_PATH.with_suffix(SIDECAR_PATH.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(normalized, f, indent=2)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, SIDECAR_PATH)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def block_app_via_ifeo(process_name: str, log_fn=print) -> bool:
    """Block a process by setting IFEO Debugger to 'cmd.exe /c exit'.

    Returns True if successful, False otherwise.
    """
    if not _is_windows():
        log_fn(f"[ifeo_blocker] not Windows, skipping {process_name}")
        return False

    # v0.3.5 — refuse to block anything in the hard deny-list. Doing so
    # would break the agent's own shutdown / restart / notify / uninstall
    # flow (cmd.exe, powershell.exe, reg.exe, schtasks.exe, ...).
    if _is_denied(process_name):
        log_fn(f"[ifeo_blocker] REFUSED to IFEO-block protected exe: {process_name}")
        return False

    normalized = _normalize_exe(process_name)
    key_path = f'{IFEO_ROOT}\\{normalized}'
    cmd = [
        "reg", "add", key_path,
        "/v", "Debugger",
        "/t", "REG_SZ",
        "/d", "cmd.exe /c exit",
        "/f"
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        if result.returncode == 0:
            # v0.3.5 — record what we blocked so cleanup can find it again.
            current = _load_sidecar()
            if normalized not in current:
                current.append(normalized)
                _save_sidecar(current)
            log_fn(f"[ifeo_blocker] IFEO blocked: {normalized}")
            return True
        else:
            log_fn(f"[ifeo_blocker] IFEO failed for {normalized}: {result.stderr}")
            return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log_fn(f"[ifeo_blocker] error: {e}")
        return False


def unblock_app_via_ifeo(process_name: str, log_fn=print) -> bool:
    """Remove IFEO Debugger entry for a process."""
    if not _is_windows():
        return False

    normalized = _normalize_exe(process_name)
    key_path = f'{IFEO_ROOT}\\{normalized}'
    cmd = [
        "reg", "delete", key_path,
        "/v", "Debugger",
        "/f"
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=10,
            creationflags=_NO_WINDOW,
        )
        # v0.3.5 — always drop the entry from the sidecar when we attempt
        # an unblock, whether the reg delete succeeded or not (the entry
        # may have been manually cleared already).
        current = _load_sidecar()
        if normalized in current:
            current.remove(normalized)
            _save_sidecar(current)
        if result.returncode == 0:
            log_fn(f"[ifeo_blocker] IFEO unblocked: {normalized}")
            return True
        return False
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        log_fn(f"[ifeo_blocker] error: {e}")
        return False


def list_blocked_apps(log_fn=print) -> list:
    """List all apps currently blocked via IFEO.

    v0.3.5 — returns the *intersection* of what `reg query /s` finds and
    what we recorded in the sidecar. That way we never report (and never
    cleanup) IFEO entries that some other tool/sysadmin set manually.
    """
    if not _is_windows():
        return []
    cmd = ["reg", "query", IFEO_ROOT, "/s", "/v", "Debugger"]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
            creationflags=_NO_WINDOW,
        )
        in_registry = set()
        current_key = None
        for line in result.stdout.splitlines():
            if "HKEY_LOCAL_MACHINE" in line:
                current_key = line.strip()
            elif "Debugger" in line and current_key:
                exe_name = current_key.split("\\")[-1]
                in_registry.add(_normalize_exe(exe_name))
        sidecar = set(_load_sidecar())
        # Only return apps that are both in the registry AND in our sidecar.
        return sorted(in_registry & sidecar)
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
