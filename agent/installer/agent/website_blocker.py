"""Block websites by editing Windows hosts file.

Strategy:
1. Backup original hosts file to <hosts>.labsch
2. On each config update, write a block between marker comments
3. Format: "127.0.0.1 <domain>" or "0.0.0.0 <domain>"

This is the simple version — production should use DoH detection too.
"""
import os
import shutil
import socket
from pathlib import Path
from typing import Iterable, Tuple

# Windows hosts file path
HOSTS_PATH_WINDOWS = r"C:\Windows\System32\drivers\etc\hosts"
# Linux/macOS (for dev/testing)
HOSTS_PATH_POSIX = "/etc/hosts"

# Marker comments
START_MARKER = "# >>> LabSCHAgent managed — DO NOT EDIT >>>"
END_MARKER = "# <<< LabSCHAgent managed <<<"

DEFAULT_BACKUP = ".labsch.bak"


def get_hosts_path() -> str:
    """Return the hosts file path for current OS."""
    if os.name == "nt":
        return HOSTS_PATH_WINDOWS
    return HOSTS_PATH_POSIX


def _read_file(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8", errors="replace")


def _write_file(path: str, content: str):
    """v0.3.5 — atomic hosts file write.

    Hosts file corruption = DNS broken on the PC. We write to a temp file in
    the SAME directory (so os.replace is atomic on NTFS — same volume) then
    rename. A reader (DNS client) either sees the old file or the new file,
    never a half-written one.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Some filesystems / non-Windows dev paths don't support fsync.
                pass
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _strip_managed_block(content: str) -> str:
    """Remove any previous LabSCHAgent block from content."""
    lines = content.splitlines()
    out = []
    in_block = False
    for line in lines:
        if START_MARKER in line:
            in_block = True
            continue
        if END_MARKER in line:
            in_block = False
            continue
        if not in_block:
            out.append(line)
    # preserve trailing newline if any
    return "\n".join(out) + ("\n" if content.endswith("\n") else "")


def _build_block(blocked: Iterable[str], allowed: Iterable[str]) -> str:
    """Build the managed block content."""
    lines = [START_MARKER]
    for domain in blocked:
        d = domain.strip().lower()
        if d and d not in [a.lower() for a in allowed]:
            lines.append(f"127.0.0.1 {d}")
            lines.append(f"127.0.0.1 www.{d}")
    lines.append(END_MARKER)
    return "\n".join(lines) + "\n"


def backup_once(path: str) -> None:
    """Create a one-time backup of the original hosts file. Idempotent."""
    backup_path = path + DEFAULT_BACKUP
    if not os.path.exists(backup_path):
        try:
            # v0.3.5 — use shutil.copy2 (already does read+write safely) but
            # only as a one-time copy of the *pristine* hosts. We never
            # overwrite the backup once created, so even a partial copy is
            # recoverable: the next apply_blocklist re-tries.
            shutil.copy2(path, backup_path)
        except (OSError, PermissionError):
            # May not have write permission to system folder; ignore for first-run
            pass


def apply_blocklist(blocked: Iterable[str], allowed: Iterable[str] = (),
                    log_fn=print) -> Tuple[bool, str]:
    """Apply the blocklist to the hosts file.

    Args:
        blocked: iterable of domain names to block.
        allowed: iterable of domain names to allow (excluded from blocking).
        log_fn: callable for logging.

    Returns:
        (success, message) tuple.
    """
    hosts_path = get_hosts_path()
    if not os.path.exists(hosts_path):
        return False, f"hosts file not found: {hosts_path}"

    backup_once(hosts_path)

    try:
        current = _read_file(hosts_path)
    except (OSError, PermissionError) as e:
        return False, f"cannot read hosts: {e}"

    stripped = _strip_managed_block(current)
    new_block = _build_block(blocked, allowed)
    new_content = stripped.rstrip() + "\n\n" + new_block

    try:
        _write_file(hosts_path, new_content)
    except (OSError, PermissionError) as e:
        return False, f"cannot write hosts (need admin?): {e}"

    log_fn(f"[website_blocker] applied {len(list(blocked))} block rules")
    return True, "ok"


# CLI test
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Apply blocklist to hosts file")
    parser.add_argument("--block", nargs="+", default=[], help="Domains to block")
    parser.add_argument("--allow", nargs="+", default=[], help="Domains to allow")
    args = parser.parse_args()

    ok, msg = apply_blocklist(args.block, args.allow)
    print(f"{'OK' if ok else 'FAIL'}: {msg}")
    print(f"hosts file: {get_hosts_path()}")
