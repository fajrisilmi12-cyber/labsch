"""Block apps by killing matching processes.

Cross-platform via psutil.
"""
import sys
from typing import Iterable

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def _kill_windows(process_names: Iterable[str], log_fn=print) -> int:
    """Kill processes by name on Windows. Returns count killed.

    Implementation: walk psutil.process_iter, match by name() (case-insensitive).
    """
    if not HAS_PSUTIL:
        log_fn("[app_blocker] psutil not available, skipping")
        return 0
    target = {n.lower() for n in process_names}
    killed = 0
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name in target:
                proc.kill()
                log_fn(f"[app_blocker] killed: {name} (pid {proc.pid})")
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    return killed


def block_apps(process_names: Iterable[str], log_fn=print) -> int:
    """Public entry: block (kill) any process matching the given names.

    Args:
        process_names: iterable of process names to block (e.g. ['RobloxPlayerLauncher.exe']).
        log_fn: callable for logging.

    Returns:
        Number of processes killed.
    """
    if not process_names:
        return 0
    return _kill_windows(process_names, log_fn)


# CLI test
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Block apps by killing processes")
    parser.add_argument("names", nargs="+", help="Process names to block (e.g. notepad.exe)")
    args = parser.parse_args()

    n = block_apps(args.names)
    print(f"Killed {n} process(es)")
