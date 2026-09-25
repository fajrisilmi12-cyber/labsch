# AUDIT — Temp.rar vs repo (temuaan unify v0.4.0)

Sumber: `~/audit` di VPS (20 file agent, label `0.4.0-test13`, dari Temp.rar)
vs repo `labsch-build` cabang `feat/win10-ltsc-appcheck`.

## 1. Nama scheduled task: TIGA varian

| Lokasi | Nama task |
|---|---|
| `audit/install.bat` | `LabSCHAgentOnBoot` (+ hapus `LabSCHAgentWatchdog`) |
| `audit/install_service.py` / agent | `LabSCHAgentWatchdog` |
| `repo upgrade.py` | `LabSCHAgent` |

Keputusan: **satu task `LabSCHAgent`** (SYSTEM, IgnoreNew, restart-on-failure).
`install.bat` + `upgrade.py` hanya membuat itu; semua varian legacy dihapus
(`LabSCHAgentWatchdog`, `LabSCHAgentOnBoot`, `LabSCH*Notify`); Run key
`HKLM\...\Run\LabSCHAgent` dihapus. `labsch_full_uninstall.bat` menghapus
semuanya + verifikasi.

## 2. Lokasi instalasi: DUA lokasi

| Alur | Kode | State |
|---|---|---|
| `audit/install.bat` | dijalankan dari folder sumber (di mana saja) | `C:\ProgramData\LabSCHAgent\config.ini` |
| `repo upgrade.py` | `%ProgramFiles%\LabSCHAgent` (ACL SYSTEM/Admin) | `%ProgramData%\LabSCHAgent\config.ini` (ACL SYSTEM/Admin saja) |

Keputusan: **kode di `%ProgramFiles%\LabSCHAgent`** (siswa read-only),
**state di `%ProgramData%\LabSCHAgent`** (`config.ini`, `health.json`,
`app_install_report.json`, `agent.lock`). Uninstaller menghapus keduanya.

## 3. Versi tersebar: `0.4.0-test13` di ±12 tempat

`User-Agent`, default `--version`, default `get_pending_downloads`,
payload `config.ini`, echo `upgrade.bat`, komentar launcher — semua
hard-code `0.4.0-test13` (audit) vs `0.1.0`/`0.4.0-test2`/`0.4.0-test10`
(repo). Keputusan: **sumber tunggal `agent/VERSION` + `agent/version.py`**
(`AGENT_VERSION`); `install.bat`/`upgrade.py`/`config_sync.py`/`labsch_agent.py`
membacanya. Versi unify: **`0.4.0`**.

## 4. Runtime: system `python` vs `runtime\python.exe`

`audit/install.bat` memakai `python` dari PATH (rapuh — update Python siswa
bisa merusak agent). Keputusan: **satu runtime `runtime\python.exe`**
di `%ProgramFiles%\LabSCHAgent\runtime`; task menunjuk ke sana;
`check_apps.bat` fallback `ProgramFiles → PATH` hanya untuk pemeriksaan manual.

## 5. Exit-code discipline (sebelumnya longgar)

`audit/install.bat` tidak memeriksa kegagalan `schtasks /create|/run`;
koneksi gagal hanya peringatan. Keputusan: tiap tahap `install.bat`,
`upgrade.py`, `app_install.py` memeriksa exit code; gagal = berhenti +
lapor, tanpa klaim sukses. Heartbeat gagal saat install = exit 7 (task tetap
terdaftar agar bisa diperbaiki tanpa reinstall).

## 6. Kebijakan aplikasi tersebar (baru)

URL/checksum/argumen installer sebelumnya akan tersebar di kode bila
ditulis ad-hoc. Keputusan: **`agent/app_config.json`** sebagai konfigurasi
admin tunggal (`python`, `virtualbox`, `packet_tracer`, `download_dir`).
