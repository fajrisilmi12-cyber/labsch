"""LabSCH lab-apps installer (app_install).

Installs only apps reported by appcheck as "Belum terpasang" or
"Versi tidak sesuai" — never downgrades a newer version. Flow per app:

1. appcheck re-check (skip if already "Terpasang"),
2. ensure C:\\Downloads exists, download installer there (real filename),
3. verify SHA-256 from app_config.json + Authenticode signature,
4. run silent install, wait, check exit code,
5. re-check with appcheck, record report, flag Perlu-restart (no auto-reboot).

Must run as Administrator. Installs ONE app at a time (sequential).
Writes a JSON report to %ProgramData%\\LabSCHAgent\\app_install_report.json
and prints a machine-readable JSON summary to stdout.

Usage (Administrator CMD, from the agent folder):
    runtime\\python.exe app_install.py --app virtualbox
    runtime\\python.exe app_install.py --all
    runtime\\python.exe app_install.py --all --allow-unverified   (dev only)
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import appcheck  # noqa: E402

CHECKERS = {
    "python": appcheck.check_python,
    "virtualbox": appcheck.check_virtualbox,
    "packet_tracer": appcheck.check_packet_tracer,
}

PLACEHOLDER_MARKERS = ("ADMIN-FILL", "PLACEHOLDER", "XXX")


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def state_dir():
    return Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "LabSCHAgent"


def sha256_of(path, chunk=1024 * 1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def checksum_ok(path, expected):
    if not expected or any(m in expected for m in PLACEHOLDER_MARKERS):
        return False, "checksum admin belum ditetapkan (ADMIN-FILL) — minta checksum resmi ke admin"
    actual = sha256_of(path)
    if actual.lower() != expected.lower():
        return False, "SHA-256 tidak cocok: dapat %s... diharapkan %s..." % (actual[:16], expected[:16])
    return True, "SHA-256 cocok (%s...)" % actual[:16]


def authenticode_status(path):
    """Check Authenticode signature via PowerShell. Returns (ok, message).

    Unsigned/unknown on non-Windows returns (False, reason) — caller decides.
    """
    if os.name != "nt":
        return False, "verifikasi Authenticode hanya tersedia di Windows"
    ps = (
        "$s = Get-AuthenticodeSignature -LiteralPath '%s';"
        " $s.Status.ToString() + '|' + $s.SignerCertificate.Subject"
        % str(path).replace("'", "''")
    )
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", ps],
            capture_output=True, text=True, timeout=60,
        )
        out = (proc.stdout or "").strip()
        status = out.split("|")[0] if out else "Unknown"
        if status == "Valid":
            return True, "Authenticode Valid (%s)" % out[len("Valid|"):][:120]
        return False, "Authenticode TIDAK valid: %s" % (out or "tidak terbaca")
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "Authenticode tidak dapat diperiksa: %s" % exc


def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": "LabSCHAgent/app_install"})
    with urllib.request.urlopen(req, timeout=300) as resp, open(dest, "wb") as f:
        while True:
            block = resp.read(1024 * 1024)
            if not block:
                break
            f.write(block)
    return dest


def install_one(app, policy, download_dir, allow_unverified=False):
    """Install a single app. Returns a report dict (never raises)."""
    report = {"app": app, "started": utcnow(), "steps": []}

    def step(name, ok, detail=""):
        report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})
        print("[%s] %s: %s %s" % (app, name, "OK" if ok else "GAGAL", detail), flush=True)
        return ok

    # 1. pre-check
    pre = CHECKERS[app](policy)
    report["pre_check"] = pre
    if pre["status"] == appcheck.STATUS_OK:
        step("pre-check", True, "sudah Terpasang (%s) — dilewati" % pre.get("found_version", "?"))
        report.update({"action": "skipped", "exit_code": 0, "needs_restart": False, "finished": utcnow()})
        return report
    if pre["status"] == appcheck.STATUS_FAILED:
        step("pre-check", False, "pemeriksaan gagal: %s" % pre.get("error", "?"))
        report.update({"action": "aborted", "exit_code": None, "needs_restart": False, "finished": utcnow()})
        return report
    step("pre-check", True, "%s (ditemukan: %s)" % (pre["status"], pre.get("found_version") or "-"))

    # 2. download
    try:
        Path(download_dir).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        step("siapkan folder", False, str(exc))
        report.update({"action": "aborted", "exit_code": None, "needs_restart": False, "finished": utcnow()})
        return report
    filename = policy.get("installer_file") or policy.get("installer_url", "").rsplit("/", 1)[-1]
    dest = str(Path(download_dir) / filename)
    try:
        step("unduh", True, "dari %s" % policy.get("installer_url", ""))
        if policy.get("third_party_source"):
            print("[%s] PERINGATAN sumber pihak ketiga: %s" % (app, policy.get("third_party_warning", "")), flush=True)
        report["source_url"] = policy.get("installer_url", "")
        download(policy["installer_url"], dest)
        report["installer_path"] = dest
        step("unduh selesai", True, dest)
    except Exception as exc:  # noqa: BLE001 — network errors must become a report
        step("unduh", False, str(exc)[:300])
        report.update({"action": "failed", "exit_code": None, "needs_restart": False, "finished": utcnow()})
        return report

    # 3. verify checksum + signature
    ok, msg = checksum_ok(dest, policy.get("sha256", ""))
    if not ok and not allow_unverified:
        step("verifikasi checksum", False, msg + " — ABORT. Jangan eksekusi file yang belum terverifikasi.")
        report.update({"action": "aborted", "exit_code": None, "needs_restart": False, "finished": utcnow()})
        return report
    step("verifikasi checksum", ok, msg + (" (dev override --allow-unverified)" if not ok else ""))
    sig_ok, sig_msg = authenticode_status(dest)
    if not sig_ok and not allow_unverified:
        step("verifikasi signature", False, sig_msg + " — ABORT.")
        report.update({"action": "aborted", "exit_code": None, "needs_restart": False, "finished": utcnow()})
        return report
    step("verifikasi signature", sig_ok, sig_msg + (" (dev override)" if not sig_ok else ""))

    # PacketTracer: silent support must be validated by admin config
    if app == "packet_tracer" and not policy.get("silent_validated", False) and not allow_unverified:
        step("validasi silent", False,
             "installer belum tervalidasi mendukung /VERYSILENT — laporkan ke admin; sediakan instalasi manual.")
        report.update({"action": "aborted", "exit_code": None, "needs_restart": False, "finished": utcnow()})
        return report

    # 4. silent install (ONE at a time; NEVER reboot automatically)
    cmd = [dest] + list(policy.get("silent_args", []))
    try:
        proc = subprocess.run(cmd, capture_output=False, timeout=3600)
        rc = proc.returncode
    except (OSError, subprocess.SubprocessError) as exc:
        step("instalasi", False, "gagal dijalankan: %s" % exc)
        report.update({"action": "failed", "exit_code": None, "needs_restart": False, "finished": utcnow()})
        return report
    report["exit_code"] = rc
    report["silent_cmd"] = " ".join([filename] + list(policy.get("silent_args", [])))
    if rc != 0:
        step("instalasi", False, "exit code %s" % rc)
        report.update({"action": "failed", "needs_restart": False, "finished": utcnow()})
        return report
    step("instalasi", True, "exit code 0")

    # 5. post-check
    post = CHECKERS[app](policy)
    report["post_check"] = post
    needs_restart = bool(policy.get("needs_restart", False))
    if post["status"] == appcheck.STATUS_OK:
        step("cek ulang", True, "Terpasang (%s)%s" % (
            post.get("found_version") or "?",
            " — PERLU RESTART" if needs_restart else ""))
        report.update({"action": "installed", "needs_restart": needs_restart, "finished": utcnow()})
    else:
        step("cek ulang", False, "status %s — kemungkinan perlu restart atau instalasi tidak lengkap" % post["status"])
        report.update({"action": "needs-review", "needs_restart": True, "finished": utcnow()})
    return report


def save_report(reports):
    try:
        path = state_dir() / "app_install_report.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"time": utcnow(), "reports": reports}
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        print("Laporan tersimpan: %s" % path, flush=True)
    except OSError as exc:
        print("Gagal menyimpan laporan: %s" % exc, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="LabSCH lab-apps installer (satu per satu, tanpa reboot otomatis)")
    ap.add_argument("--app", choices=list(CHECKERS), help="Install satu aplikasi")
    ap.add_argument("--all", action="store_true", help="Install semua aplikasi yang belum memenuhi kebijakan")
    ap.add_argument("--config", default=None, help="Path app_config.json alternatif")
    ap.add_argument("--download-dir", default=None, help="Folder installer override (default C:\\Downloads)")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="DEV ONLY: lewati verifikasi checksum/signature (jangan di kelas produksi)")
    args = ap.parse_args(argv)

    if bool(args.app) == bool(args.all):
        ap.error("pilih salah satu: --app NAME atau --all")
    if os.name == "nt":
        import ctypes
        if not ctypes.windll.shell32.IsUserAnAdmin():
            print("ERROR: jalankan sebagai Administrator (klik kanan > Run as administrator).")
            return 2

    policy = appcheck.load_policy(args.config)
    dl_dir = args.download_dir or policy.get("download_dir", r"C:\Downloads")
    targets = list(CHECKERS) if args.all else [args.app]
    reports = []
    failed = False
    for app in targets:  # SEQUENTIAL — one at a time, never parallel
        rep = install_one(app, policy.get(app, {}), dl_dir, allow_unverified=args.allow_unverified)
        reports.append(rep)
        if rep.get("action") not in ("installed", "skipped"):
            failed = True
    save_report(reports)
    print(json.dumps({"reports": reports}, indent=2, ensure_ascii=False))
    if any(r.get("needs_restart") for r in reports):
        print("STATUS: Perlu restart — sampaikan ke admin; JANGAN reboot otomatis saat kelas berlangsung.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
