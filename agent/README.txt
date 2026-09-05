LabSCH Agent v0.3.5 - README
=============================

INSTALLASI CEPAT:
1. Extract zip ini ke folder manapun (contoh: C:\Temp\labsch)
2. Edit config.ini, isi "display_name" dengan nama PC (mis. "PC-LAB-01")
   - Token & URL sudah pre-baked, tinggal pakai
3. Klik kanan install.bat -> "Run as Administrator"
4. Klik "Yes" di popup UAC
5. Ikuti prompt di layar (display_name, is_test, dll)
6. Selesai! Service LabSCHAgent akan auto-start setiap boot.

CARA PAKAI SERVICE:
- Agent jalan otomatis di background
- Heartbeat ke server setiap 60 detik
- Server bisa push profile (Rules Lab) -> client apply
- Server bisa lock screen, notify, shutdown, restart, dll

UNINSTALL:
- Klik kanan uninstall.bat -> "Run as Administrator"
- Atau pakai labsch_full_uninstall.bat untuk bersih total

TROUBLESHOOTING:
- "Python tidak ditemukan": Install Python 3.10+ dari python.org
  (centang "Add Python to PATH" saat install)
- "Tidak bisa connect ke server": Cek internet, firewall, dan token
- "Access denied": Pastikan Run as Administrator

FILE YANG TERINSTALL:
- C:\ProgramData\LabSCHAgent\config.ini (server URL + token)
- C:\ProgramData\LabSCHAgent\agent.log (log agent)
- Scheduled Task "LabSCHAgentWatchdog" (restart tiap 5 menit)
- Scheduled Task "LabSCHAgentOnBoot" (start saat boot)
- Run key "LabSCHAgent" (HKLM auto-start)
- Task Manager disabled (HKCU policy)

VERSI:
- Agent:    v0.3.5
- Workers:  0.3.5-workers
- Server:   0.3.5-server (FastAPI di 127.0.0.1:8080)

DOKUMENTASI LENGKAP:
https://github.com/fajrisilmi12-cyber/labsch
