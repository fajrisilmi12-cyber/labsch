# APPCHECK — Pemeriksaan & Pemasangan Aplikasi Lab

Cakupan: Python, Oracle VirtualBox, Cisco Packet Tracer pada Windows 10 LTSC / Windows 11.
Jalankan dengan hak **Administrator/SYSTEM**. Status uji Windows: **BELUM** (butuh VM Win10 LTSC).

## 1. Pemeriksaan (read-only)

Teknisi (manual, CMD Administrator):

```cmd
cd C:\Program Files\LabSCHAgent
check_apps.bat
```

atau langsung:

```cmd
runtime\python.exe appcheck.py
```

Agent (hak SYSTEM via task `LabSCHAgent`):

```cmd
runtime\python.exe appcheck.py
```

### Metode — tiga sinyal independen (jangan hanya `where`)

1. **Registry uninstall** Windows (`HKLM`/`HKCU`, termasuk `WOW6432Node`):
   `DisplayName`, `DisplayVersion`, `InstallLocation`.
2. **Lokasi executable** yang dikenal + `PATH` hanya sebagai petunjuk.
3. **Uji versi**: `python --version`, `VBoxManage --version`,
   ProductVersion PE via PowerShell (Packet Tracer).

### Status per aplikasi + bukti

| Status | Arti |
|---|---|
| `Terpasang` | Ditemukan dan versi memenuhi kebijakan admin |
| `Belum terpasang` | Tidak ada entri registry dan executable tidak ditemukan |
| `Versi tidak sesuai` | Ditemukan tetapi lebih lama dari versi kebijakan |
| `Pemeriksaan gagal` | Pemeriksaannya sendiri error (detail di `error`) |

Setiap hasil membawa `path`, `found_version`, `expected`, dan `evidence`
(contoh: `registry: Oracle VM VirtualBox 6.1.50 [6.1.50]; exe: C:\Program Files\Oracle\VirtualBox\VBoxManage.exe; versi: 6.1.50`).

Versi **lebih baru** dari kebijakan TIDAK di-downgrade otomatis —
dilaporkan `Terpasang` dengan catatan.

## 2. Kebijakan admin (satu tempat)

`agent/app_config.json` — versi, URL installer, SHA-256, argumen silent.
Blok `_comment` di atas file menjelaskan aturan sumber:

- VirtualBox 6.1.50 (build 161033):
  `https://download.virtualbox.org/virtualbox/6.1.50/VirtualBox-6.1.50-161033-Win.exe`
  → `VirtualBox-6.1.50-161033-Win.exe --silent --ignore-reboot`
- Packet Tracer 9.0 64-bit: utamakan installer resmi Cisco Networking
  Academy. URL archive.org adalah **sumber pihak ketiga** — wajib lolos
  Authenticode + checksum, dan flag `silent_validated` harus `true`
  (sudah divalidasi mendukung `/VERYSILENT /NORESTART`) sebelum instalasi.
  Jangan gunakan nama contoh `CiscoPacketTracer_XXX_Windows_32bit_setup.exe`.
- Python ≥ 3.10 64-bit: `python-<versi>-amd64.exe /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1`.
  Pertimbangkan runtime khusus LabSCH agar update Python siswa tidak merusak agent.

> Sebelum produksi: ganti semua `ADMIN-FILL-SHA256-*` dengan SHA-256 resmi.

## 3. Pemasangan (satu per satu, tanpa reboot otomatis)

```cmd
:: Administrator CMD, dari folder agent
runtime\python.exe app_install.py --app virtualbox
runtime\python.exe app_install.py --all
```

Alur per aplikasi: cek (`appcheck`) → buat `C:\Downloads` → unduh dengan
**nama file sebenarnya** → verifikasi checksum + Authenticode (gagal = ABORT,
jangan eksekusi) → instal silent → tunggu selesai → periksa **exit code** →
cek ulang → catat (waktu, sumber, versi, exit code, kebutuhan reboot, hasil
cek ulang) ke `%ProgramData%\LabSCHAgent\app_install_report.json` untuk
dashboard. Pemasangan berjalan **satu per satu**; reboot otomatis
**dilarang** saat kelas — tampilkan `Perlu restart` kepada admin.

## 4. Uji Linux/CI (tanpa Windows)

```bash
python3 -m py_compile agent/appcheck.py agent/app_install.py agent/version.py
pytest tests/test_appcheck.py -v   # winreg dimock; registry_search -> []
python3 agent/appcheck.py          # di Linux: semua "Belum terpasang"
```
