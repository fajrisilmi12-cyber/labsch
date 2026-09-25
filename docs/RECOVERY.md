# RECOVERY — Pemulihan LabSCH

## 1. Uninstall penuh (Administrator)

```cmd
cd C:\Program Files\LabSCHAgent
labsch_full_uninstall.bat
```

Uninstaller terpadu (v0.4.0) mencabut **semuanya**:

1. Hentikan proses agent (`labsch_agent.py`, bukan semua `python.exe` liar).
2. Hapus scheduled task **tunggal** `LabSCHAgent` + sisa legacy
   (`LabSCHAgentWatchdog`, `LabSCHAgentOnBoot`, `LabSCH*Notify`).
3. Hapus Run key + entri Startup folder.
4. Bersihkan hosts (entri `LabSCH`) + `ipconfig /flushdns`.
5. Hapus browser policy registry (Edge/Chrome/Chromium/Brave).
6. Hapus IFEO `Debugger` milik LabSCH + **re-enable Task Manager**
   (HKCU + HKLM `DisableTaskMgr`).
6b. Restore camera + audio (policy `AllowCamera`, `DenyDeviceClasses`,
   service `audiosrv`/`AudioEndpointBuilder` → auto + start).
7. Hapus state `C:\ProgramData\LabSCHAgent` + kode
   `%ProgramFiles%\LabSCHAgent` + verifikasi tiap tahap (gagal = exit ≠ 0,
   bukan klaim "BERSIH" palsu).

Catatan: browser perlu di-restart agar policy hilang dari memori;
record PC di server dibersihkan via `labschctl`.

## 2. Upgrade (config lama dipertahankan)

```cmd
upgrade.bat        :: klik kanan > Run as administrator
```

`upgrade.py` hanya untuk upgrade: menolak bila `config.ini` tidak ada
(enrollment memakai `install.bat`), menolak bila ada Windows service
LabSCH lama, menghentikan task legacy, menyalin modul + `runtime`,
memverifikasi import dependency, lalu mendaftarkan **satu** task SYSTEM
`LabSCHAgent` (IgnoreNew, restart-on-failure). Modul yang disalin kini
termasuk `version.py`, `appcheck.py`, `app_install.py`, `app_config.json`,
`VERSION`.

## 3. Jika heartbeat gagal setelah (re)install

1. `runtime\python.exe labsch_agent.py --once` — lihat error koneksi/token.
2. Periksa `C:\ProgramData\LabSCHAgent\config.ini` (`server_url` https,
   `api_token` terisi, `version` = isi `VERSION`).
3. `schtasks /query /tn LabSCHAgent` — task harus ada; hanya SATU task.
4. Task Manager → hanya SATU proses agent (`runtime\python.exe labsch_agent.py`).
5. Health terakhir: `%ProgramData%\LabSCHAgent\health.json`
   (`agent_version`, `last_heartbeat`, `policy_status`, `launcher_status`,
   `last_failure`).

## 4. Jika instalasi aplikasi gagal

1. Buka `%ProgramData%\LabSCHAgent\app_install_report.json` — lihat `steps`,
   `exit_code`, dan `post_check`.
2. `Perlu restart` → jadwalkan reboot di luar jam kelas, lalu `check_apps.bat`.
3. Checksum/signature gagal → JANGAN bypass di produksi; minta file +
   checksum resmi ke admin (`--allow-unverified` hanya untuk dev).
4. Packet Tracer `silent_validated=false` → instalasi manual oleh admin.

## 5. Urutan uji Windows (BELUM dijalankan — butuh VM Win10 LTSC)

```
cek aplikasi (check_apps.bat) → instal yang belum ada (app_install.py --all)
→ reboot → cek ulang → upgrade LabSCH (upgrade.bat) → uninstall LabSCH
(labsch_full_uninstall.bat) → verifikasi PC bersih
```

Laporkan hasil nyata tiap tahap; jangan klaim sukses tanpa menjalankannya.
