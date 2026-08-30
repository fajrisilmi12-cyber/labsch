"""Get stable device identifier from MAC address.

Returns a SHA256 hash of the primary MAC address, which is unique per
physical network adapter. Unlike hostname (renameable) or IP (DHCP),
MAC address is permanent per hardware.

On Windows: uses 'getmac' command (built-in)
On Linux/Mac: uses /sys/class/net or ifconfig
"""
import hashlib
import platform
import re
import subprocess
from typing import Optional


def get_primary_mac() -> Optional[str]:
    """Get the MAC address of the primary network adapter.

    Returns MAC in format 'AA:BB:CC:DD:EE:FF' (uppercase, colon-separated).
    """
    system = platform.system().lower()
    if system == "windows":
        return _get_mac_windows()
    elif system in ("linux", "darwin"):
        return _get_mac_unix()
    return None


def _get_mac_windows() -> Optional[str]:
    """Use 'getmac' command on Windows. Returns first non-empty MAC."""
    try:
        result = subprocess.run(
            ["getmac", "/fo", "csv", "/nh"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return None
        for line in result.stdout.splitlines():
            parts = line.strip().strip('"').split('","')
            if len(parts) >= 1:
                mac = parts[0].strip().strip('"')
                if re.match(r"^[0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}[:-][0-9A-Fa-f]{2}$", mac):
                    return mac.upper().replace("-", ":")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _get_mac_unix() -> Optional[str]:
    """Use /sys/class/net on Linux or ifconfig on macOS."""
    system = platform.system().lower()
    if system == "linux":
        try:
            net_dir = "/sys/class/net"
            import os
            for iface in os.listdir(net_dir):
                if iface == "lo":
                    continue
                addr_file = f"{net_dir}/{iface}/address"
                if os.path.exists(addr_file):
                    with open(addr_file) as f:
                        mac = f.read().strip()
                    if mac and mac != "00:00:00:00:00:00":
                        return mac.upper()
        except (OSError, IOError):
            pass
    # Fallback: use uuid module (less reliable but works)
    try:
        mac_int = uuid.getnode()
        if (mac_int >> 40) & 1:  # Check multicast bit (random MAC)
            return None
        mac = ":".join(f"{(mac_int >> i) & 0xFF:02X}" for i in range(0, 48, 8))
        return mac
    except (ValueError, OSError):
        return None


def get_device_id() -> str:
    """Get a stable device identifier (SHA256 of MAC address).

    Returns a 16-character hex prefix of SHA256(MAC), which is:
    - Unique per physical network adapter
    - Stable across reboots, IP changes, hostname changes
    - Anonymous (cannot be reversed to MAC without brute force)

    Returns 'UNKNOWN-<hostname>' if MAC cannot be determined.
    """
    mac = get_primary_mac()
    if mac:
        h = hashlib.sha256(mac.encode("utf-8")).hexdigest()[:16]
        return f"dev-{h}"
    # Fallback: use hostname
    import socket
    hostname = socket.gethostname()
    h = hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:16]
    return f"host-{h}"


# CLI test
if __name__ == "__main__":
    mac = get_primary_mac()
    print(f"MAC: {mac or 'unknown'}")
    print(f"Device ID: {get_device_id()}")
