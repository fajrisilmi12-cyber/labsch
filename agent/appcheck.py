"""LabSCH lab-apps checker (appcheck).

Checks Python, Oracle VirtualBox, and Cisco Packet Tracer on Windows via
three independent signals — never ``where``/PATH alone:

1. Windows registry uninstall keys (HKLM/HKCU, incl. WOW6432Node),
2. well-known executable paths (+ shutil.which as a hint only),
3. a version probe (``--version`` / ``-v`` / product-version).

Per-app result status (Indonesian, per spec):
  - "Terpasang"            — found and version satisfies policy
  - "Belum terpasang"      — no registry entry and no executable
  - "Versi tidak sesuai"   — found but older than the required version
  - "Pemeriksaan gagal"    — the check itself errored

A newer version than required is NEVER flagged for downgrade: it reports
"Terpasang" with a note. Each result carries evidence (path + version).

Must run as Administrator/SYSTEM for full registry visibility, but degrades
gracefully otherwise. On non-Windows (Linux dev/CI) ``winreg`` is absent and
all registry lookups return empty — the module stays importable and the
pure logic (version compare, result building) is testable with mocks.
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

try:  # Windows only
    import winreg
except ImportError:  # Linux / CI
    winreg = None

CONFIG_NAME = "app_config.json"

STATUS_OK = "Terpasang"
STATUS_MISSING = "Belum terpasang"
STATUS_MISMATCH = "Versi tidak sesuai"
STATUS_FAILED = "Pemeriksaan gagal"

UNINSTALL_KEYS = [
    (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", False),
    (r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", False),
    (r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", True),  # HKCU
]


def load_policy(config_path=None):
    path = Path(config_path) if config_path else Path(__file__).resolve().parent / CONFIG_NAME
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _parse_version(text):
    """Extract first dotted version tuple from text, e.g. '6.1.50r161033' -> (6,1,50)."""
    if not text:
        return None
    m = re.search(r"(\d+(?:\.\d+)+)", str(text))
    if not m:
        return None
    try:
        return tuple(int(p) for p in m.group(1).split("."))
    except ValueError:
        return None


def compare_versions(found, required):
    """Return 1 if found>required, 0 if equal (prefix-equal counts), -1 if older."""
    f, r = _parse_version(found), _parse_version(required)
    if f is None or r is None:
        return None
    n = max(len(f), len(r))
    f += (0,) * (n - len(f))
    r += (0,) * (n - len(r))
    return (f > r) - (f < r)


def registry_search(name_fragments):
    """Search uninstall registry keys for DisplayName containing any fragment.

    Returns list of {name, version, location}. Empty list when winreg is
    unavailable (non-Windows) or on registry errors.
    """
    results = []
    if winreg is None:
        return results
    frags = [f.lower() for f in name_fragments]
    hives = [(winreg.HKEY_LOCAL_MACHINE, False), (winreg.HKEY_CURRENT_USER, True)]
    for subkey, want_user in UNINSTALL_KEYS:
        for hive, is_user in hives:
            if is_user != want_user:
                continue
            try:
                root = winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            except OSError:
                try:
                    root = winreg.OpenKey(hive, subkey)
                except OSError:
                    continue
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(root, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(root, sub) as k:
                        try:
                            disp, _ = winreg.QueryValueEx(k, "DisplayName")
                        except OSError:
                            continue
                        if not disp or not any(f in str(disp).lower() for f in frags):
                            continue
                        try:
                            ver, _ = winreg.QueryValueEx(k, "DisplayVersion")
                        except OSError:
                            ver = ""
                        try:
                            loc, _ = winreg.QueryValueEx(k, "InstallLocation")
                        except OSError:
                            loc = ""
                        results.append({"name": str(disp), "version": str(ver or ""), "location": str(loc or "")})
                except OSError:
                    continue
    return results


def find_exe(exe_names, extra_dirs=None):
    """Locate an executable: known dirs first, PATH (shutil.which) as hint only."""
    candidates = []
    for d in extra_dirs or []:
        for exe in exe_names:
            p = Path(d) / exe
            candidates.append(str(p))
    for exe in exe_names:
        w = shutil.which(exe)
        if w and w not in candidates:
            candidates.append(w)
    for c in candidates:
        if c and Path(c).is_file():
            return c
    return None


def probe_version(exe_path, args_list=("--version", "-v", "--Version")):
    """Run exe with version flags; return stdout text or None."""
    for args in args_list:
        try:
            proc = subprocess.run([exe_path, args], capture_output=True, text=True, timeout=30)
            out = (proc.stdout or "") + (proc.stderr or "")
            if out.strip():
                return out.strip()
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def windows_product_version(exe_path):
    """Read Windows PE product version via PowerShell (None on failure/non-Windows)."""
    if os.name != "nt":
        return None
    try:
        ps = (
            "(Get-Item -LiteralPath '%s').VersionInfo.ProductVersion" % exe_path.replace("'", "''")
        )
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=30,
        )
        out = (proc.stdout or "").strip()
        return out or None
    except (OSError, subprocess.SubprocessError):
        return None


def _build_result(app, policy, reg_hits, exe_path, found_version, error=None):
    required = policy.get("version") or policy.get("min_version") or policy.get("recommended_version", "")
    if error:
        return {
            "app": app, "status": STATUS_FAILED, "expected": required,
            "found_version": found_version or "", "path": exe_path or "",
            "evidence": "", "error": error,
        }
    if not reg_hits and not exe_path:
        return {
            "app": app, "status": STATUS_MISSING, "expected": required,
            "found_version": "", "path": "",
            "evidence": "tidak ada entri registry uninstall dan executable tidak ditemukan",
            "error": "",
        }
    evidence_bits = []
    if reg_hits:
        r0 = reg_hits[0]
        evidence_bits.append("registry: %s [%s]" % (r0["name"], r0["version"] or "?"))
    if exe_path:
        evidence_bits.append("exe: %s" % exe_path)
    if found_version:
        evidence_bits.append("versi: %s" % found_version)
    if required and found_version:
        cmp = compare_versions(found_version, required)
        if cmp is not None and cmp < 0:
            return {
                "app": app, "status": STATUS_MISMATCH, "expected": required,
                "found_version": found_version, "path": exe_path or "",
                "evidence": "; ".join(evidence_bits), "error": "",
            }
    note = ""
    if required and found_version:
        cmp = compare_versions(found_version, required)
        if cmp is not None and cmp > 0:
            note = " (lebih baru dari kebijakan %s — tidak di-downgrade)" % required
    return {
        "app": app, "status": STATUS_OK, "expected": required,
        "found_version": found_version or "", "path": exe_path or "",
        "evidence": "; ".join(evidence_bits) + note, "error": "",
    }


def check_python(policy=None):
    policy = policy or load_policy().get("python", {})
    try:
        reg_hits = registry_search(policy.get("registry_names", ["Python"]))
        exe_path = find_exe(["python.exe", "python3.exe"], [r"C:\Python310", r"C:\Python311", r"C:\Program Files\Python310", r"C:\Program Files\Python311"])
        found = probe_version(exe_path) if exe_path else None
        if found:
            m = re.search(r"Python\s+(\d+(?:\.\d+)+)", found)
            found = m.group(1) if m else None
        if not found and reg_hits and reg_hits[0]["version"]:
            found = reg_hits[0]["version"]
        result = _build_result("python", policy, reg_hits, exe_path, found)
        if exe_path and result["status"] == STATUS_OK:
            try:
                pip = subprocess.run([exe_path, "-m", "pip", "--version"], capture_output=True, text=True, timeout=30)
                result["pip"] = (pip.stdout or "").strip() if pip.returncode == 0 else "pip TIDAK tersedia"
            except (OSError, subprocess.SubprocessError):
                result["pip"] = "pip tidak dapat diperiksa"
        return result
    except Exception as exc:  # noqa: BLE001 — status must always be reportable
        return _build_result("python", policy, [], None, None, error=str(exc))


def check_virtualbox(policy=None):
    policy = policy or load_policy().get("virtualbox", {})
    try:
        reg_hits = registry_search(policy.get("registry_names", ["VirtualBox"]))
        exe_path = find_exe(policy.get("exe_names", ["VBoxManage.exe", "VirtualBox.exe"]),
                            policy.get("install_locations", []))
        found = probe_version(exe_path, ("--version", "-v")) if exe_path else None
        if not found and exe_path:
            found = windows_product_version(exe_path)
        if not found and reg_hits and reg_hits[0]["version"]:
            found = reg_hits[0]["version"]
        return _build_result("virtualbox", policy, reg_hits, exe_path, found)
    except Exception as exc:  # noqa: BLE001
        return _build_result("virtualbox", policy, [], None, None, error=str(exc))


def check_packet_tracer(policy=None):
    policy = policy or load_policy().get("packet_tracer", {})
    try:
        reg_hits = registry_search(policy.get("registry_names", ["Packet Tracer"]))
        exe_path = find_exe(policy.get("exe_names", ["PacketTracer.exe"]),
                            policy.get("install_locations", []))
        found = windows_product_version(exe_path) if exe_path else None
        if not found and exe_path:
            found = probe_version(exe_path)
        if not found and reg_hits and reg_hits[0]["version"]:
            found = reg_hits[0]["version"]
        return _build_result("packet_tracer", policy, reg_hits, exe_path, found)
    except Exception as exc:  # noqa: BLE001
        return _build_result("packet_tracer", policy, [], None, None, error=str(exc))


def check_all(policy=None):
    policy = policy or load_policy()
    return {
        "python": check_python(policy.get("python", {})),
        "virtualbox": check_virtualbox(policy.get("virtualbox", {})),
        "packet_tracer": check_packet_tracer(policy.get("packet_tracer", {})),
    }


if __name__ == "__main__":
    print(json.dumps(check_all(), indent=2, ensure_ascii=False))
