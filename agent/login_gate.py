"""
LabSCH Login Gate — Opsi B (cara lama, zero server change)
==========================================================
Jalan saat user login (Startup folder / Run key HKCU).
Tanya nama murid -> tulis ke display_name di config agent.

Server: TIDAK ada perubahan. Agent tetap pakai endpoint lama.
Admin lihat "siapa pakai PC apa" via `labschctl clients`.

Cara kerja:
  1. Baca C:/ProgramData/LabSCHAgent/config.json
  2. Minta nama murid minimal 4 huruf (validasi lokal, loop sampai valid)
  3. Tulis display_name=<nama> ke config (atomic write)
  4. Agent heartbeat berikutnya (<=30s) otomatis bawa nama baru ke server

Fail-safe (built-in):
  - Kalau config agent tidak ada -> tetap minta nama, simpan ke file gate sendiri,
    agent akan baca saat sudah terpasang.
  - Kalau user cancel/ESC -> window tertutup, TIDAK ada blokir desktop (fail-open).
  - Nama divalidasi lokal: [A-Za-z0-9 ._-], 4-64 char (mirror server regex).
"""

import ctypes
import json
import os
import re
import sys
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "LabSCHAgent"
CONFIG_FILE = CONFIG_DIR / "config.json"
GATE_PENDING_FILE = CONFIG_DIR / "gate_pending_name.json"

# Mirror server-side regex (workers/src/handlers/validation.ts): karakter diizinkan,
# tapi minimal harus ada >=4 HURUF (angka/spasi/strip tidak dihitung sebagai huruf).
NAME_RE = re.compile(r"^[A-Za-z0-9 ._-]{4,64}$")
MIN_LETTERS_RE = re.compile(r"[A-Za-z]")


def valid_name(name: str) -> bool:
    """Total 4-64 char dan minimal 4 huruf (bukan spasi/angka)."""
    if not NAME_RE.match(name or ""):
        return False
    return len(MIN_LETTERS_RE.findall(name)) >= 4


def ask_name_dialog() -> str:
    """Tampilkan input box Windows native (VBScript via PowerShell, no third-party).

    Returns empty string kalau user cancel / dialog gagal.
    """
    # PowerShell + Microsoft.VisualBasic InputBox — built-in di semua Windows 10/11
    ps_script = (
        "[void][System.Reflection.Assembly]::LoadWithPartialName('Microsoft.VisualBasic');"
        "[Microsoft.VisualBasic.Interaction]::InputBox("
        "'Siapa nama kamu? (min. 4 huruf)', 'LabSCH - Login', '')"
    )
    import subprocess
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_script],
            capture_output=True, text=True, timeout=120,
            creationflags=0x08000000 if os.name == "nt" else 0,  # CREATE_NO_WINDOW
        )
        return (out.stdout or "").strip()
    except Exception:
        return ""


def write_display_name(name: str) -> bool:
    """Tulis display_name ke config agent (atomic), atau pending-file kalau
    config belum ada (agent belum terpasang di PC ini)."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if CONFIG_FILE.exists():
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            cfg["display_name"] = name
            tmp = CONFIG_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, CONFIG_FILE)
        else:
            # Agent belum terpasang — simpan pending, agent pickup nanti
            GATE_PENDING_FILE.write_text(
                json.dumps({"display_name": name}, indent=2), encoding="utf-8"
            )
        return True
    except Exception:
        return False


def main() -> int:
    max_attempts = 5
    for attempt in range(1, max_attempts + 1):
        name = ask_name_dialog()
        if valid_name(name):
            ok = write_display_name(name)
            # Selesai — desktop tetap terbuka (fail-open by design)
            return 0
        # Nama kosong/pendek -> tanya lagi (kecuali user cancel total -> fail-open)
        if name == "":
            return 0  # user cancel: jangan blokir desktop
    # Habis percobaan -> fail-open juga (nama belum tersimpan, agent pakai nama lama)
    return 0


if __name__ == "__main__":
    sys.exit(main())
