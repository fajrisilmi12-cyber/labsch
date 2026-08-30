"""Browser policy management (registry-based).

Implements the same logic as the FULL ALLOWLIST WEB v4 BAT script,
but in Python with dynamic configuration from LabSCH server.

Approach:
- Set URLBlocklist and URLAllowlist via Chrome/Edge/Brave group policy
- Disable Secure DNS (DoH)
- Disable Incognito/Private mode
"""
import os
import sys
import subprocess
from typing import Iterable


# Chromium-based browser registry paths
BROWSER_POLICIES = {
    "edge": r"HKLM\SOFTWARE\Policies\Microsoft\Edge",
    "chrome": r"HKLM\SOFTWARE\Policies\Google\Chrome",
    "brave": r"HKLM\SOFTWARE\Policies\BraveSoftware\Brave",
}


def _is_windows() -> bool:
    return os.name == "nt"


def _reg_add(key_path: str, value_name: str, value: str, reg_type: str = "REG_SZ") -> bool:
    """Add a registry value. Returns True on success."""
    cmd = [
        "reg", "add", key_path,
        "/v", value_name,
        "/t", reg_type,
        "/d", value,
        "/f",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _reg_delete(key_path: str, value_name: str) -> bool:
    """Delete a registry value."""
    cmd = ["reg", "delete", key_path, "/v", value_name, "/f"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def _reg_delete_key(key_path: str) -> bool:
    """Delete an entire registry key (subkey)."""
    cmd = ["reg", "delete", key_path, "/f"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def apply_browser_policy(
    blocked_sites: Iterable[str],
    allowed_sites: Iterable[str],
    log_fn=print,
) -> int:
    """Apply URLBlocklist and URLAllowlist to all managed browsers.

    Returns count of successful browsers configured.
    """
    if not _is_windows():
        log_fn("[browser_policy] not Windows, skipping")
        return 0

    success = 0
    blocked_list = list(blocked_sites)
    allowed_list = list(allowed_sites)

    for browser_name, policy_root in BROWSER_POLICIES.items():
        try:
            # Wipe old entries
            _reg_delete_key(f"{policy_root}\\URLBlocklist")
            _reg_delete_key(f"{policy_root}\\URLAllowlist")

            # Block everything first
            _reg_add(policy_root, "URLBlocklist", "")  # placeholder
            _reg_add(f"{policy_root}\\URLBlocklist", "1", "*")

            # Add specific blocks
            for i, site in enumerate(blocked_list, start=2):
                _reg_add(f"{policy_root}\\URLBlocklist", str(i), site)

            # Add allows
            for i, site in enumerate(allowed_list, start=1):
                _reg_add(f"{policy_root}\\URLAllowlist", str(i), site)

            # Disable DoH
            _reg_add(policy_root, "DnsOverHttpsMode", "off")

            # Disable incognito
            _reg_add(policy_root, "InPrivateModeAvailability", "1", "REG_DWORD")
            _reg_add(policy_root, "IncognitoModeAvailability", "1", "REG_DWORD")

            log_fn(f"[browser_policy] applied to {browser_name}: {len(blocked_list)} blocks, {len(allowed_list)} allows")
            success += 1
        except Exception as e:
            log_fn(f"[browser_policy] error for {browser_name}: {e}")

    return success


def clear_browser_policy(log_fn=print) -> int:
    """Remove all browser policies (rollback)."""
    if not _is_windows():
        return 0

    success = 0
    for browser_name, policy_root in BROWSER_POLICIES.items():
        try:
            _reg_delete_key(f"{policy_root}\\URLBlocklist")
            _reg_delete_key(f"{policy_root}\\URLAllowlist")
            _reg_delete(policy_root, "DnsOverHttpsMode")
            _reg_delete(policy_root, "InPrivateModeAvailability")
            _reg_delete(policy_root, "IncognitoModeAvailability")
            log_fn(f"[browser_policy] cleared for {browser_name}")
            success += 1
        except Exception as e:
            log_fn(f"[browser_policy] error clearing {browser_name}: {e}")

    return success


# CLI
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Browser policy manager")
    parser.add_argument("action", choices=["apply", "clear"])
    parser.add_argument("--block", nargs="+", default=[], help="Sites to block")
    parser.add_argument("--allow", nargs="+", default=[], help="Sites to allow")
    args = parser.parse_args()

    if args.action == "apply":
        n = apply_browser_policy(args.block, args.allow)
        print(f"Applied policy to {n} browser(s)")
    elif args.action == "clear":
        n = clear_browser_policy()
        print(f"Cleared policy for {n} browser(s)")
