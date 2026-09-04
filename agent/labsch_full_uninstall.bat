@echo off
setlocal EnableExtensions
title LabSCH Full Uninstall

:: ================================================================
:: LabSCH FULL Uninstaller — cabut SEMUANYA:
::   1. Hapus semua blokir (hosts, browser policy, IFEO, Task Mgr)
::   2. Hapus semua auto-start (4 lapis)
::   3. Hapus config + scheduled tasks + Run key
::   4. Matikan proses agent yang lagi jalan
::
:: PC balik ke kondisi BERSIH — gak ada LabSCH, gak ada blokir.
:: Jalankan sebagai Administrator.
:: ================================================================

net session >nul 2>&1
if errorlevel 1 (
    echo Meminta izin Administrator...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

pushd "%~dp0" >nul 2>&1

echo.
echo ================================================================
echo LabSCH FULL UNINSTALL
echo ================================================================
echo.

:: ----------------------------------------------------------------
:: [1/7] Matikan proses agent yang lagi jalan
:: ----------------------------------------------------------------
echo [1/7] Menghentikan proses agent...
taskkill /f /im python.exe /fi "WINDOWTITLE eq LabSCH*" >nul 2>&1
wmic process where "CommandLine like '%%labsch_agent.py%%'" call terminate >nul 2>&1
echo       OK

:: ----------------------------------------------------------------
:: [2/7] Hapus scheduled tasks (auto-start + watchdog)
:: ----------------------------------------------------------------
echo [2/7] Menghapus scheduled tasks...
schtasks /delete /tn "LabSCHAgentOnBoot" /f >nul 2>&1 && echo       Task OnBoot    : DIHAPUS
schtasks /delete /tn "LabSCHAgentWatchdog" /f >nul 2>&1 && echo       Task Watchdog  : DIHAPUS
schtasks /delete /tn "LabSCHAgentNotify" /f >nul 2>&1
schtasks /delete /tn "LabSCHNotify" /f >nul 2>&1
schtasks /delete /tn "LabSCHAgent" /f >nul 2>&1

:: ----------------------------------------------------------------
:: [3/7] Hapus Run key + Startup folder entries
:: ----------------------------------------------------------------
echo [3/7] Menghapus Run key + Startup entries...
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "LabSCHAgent" /f >nul 2>&1 && echo       Run key HKLM   : DIHAPUS
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LabSCHAgent_start.bat" >nul 2>&1 && echo       Startup user   : DIHAPUS
del "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\LabSCHAgent_start.bat" >nul 2>&1 && echo       Startup all    : DIHAPUS

:: ----------------------------------------------------------------
:: [4/7] Bersihkan HOSTS file (hapus semua entri LabSCH)
:: ----------------------------------------------------------------
echo [4/7] Membersihkan hosts file...
:: hosts LabSCH menandai entri dengan komentar "# LabSCH" atau pola 0.0.0.0/127.0.0.1 domain
powershell.exe -NoProfile -Command ^
    "$f='C:\Windows\System32\drivers\etc\hosts';" ^
    "$lines = Get-Content $f -ErrorAction SilentlyContinue;" ^
    "$clean = $lines | Where-Object { $_ -notmatch 'LabSCH' };" ^
    "Set-Content -Path $f -Value $clean -Encoding ASCII" >nul 2>&1
ipconfig /flushdns >nul 2>&1
echo       OK + DNS flush

:: ----------------------------------------------------------------
:: [5/7] Hapus browser policy registry (Edge/Chrome/Brave)
:: ----------------------------------------------------------------
echo [5/7] Menghapus browser policy (Edge/Chrome/Brave)...
for %%B in (Edge Chromium Chrome Brave) do (
    reg delete "HKLM\SOFTWARE\Policies\Microsoft\%%B" /f >nul 2>&1 && echo       %%B policy     : DIHAPUS
    reg delete "HKLM\SOFTWARE\Policies\Google\%%B" /f >nul 2>&1
    reg delete "HKLM\SOFTWARE\Policies\Chromium\%%B" /f >nul 2>&1
)
:: Brave kadang di path vendor sendiri
reg delete "HKLM\SOFTWARE\Policies\BraveSoftware\Brave" /f >nul 2>&1

:: ----------------------------------------------------------------
:: [6/7] Hapus IFEO Debugger entries (app block) + Enable Task Mgr
:: ----------------------------------------------------------------
echo [6/7] Menghapus IFEO entries + re-enable Task Manager...
:: IFEO: hapus "Debugger" value yang diset LabSCH untuk semua exe yang diblokir
powershell.exe -NoProfile -Command ^
    "$base='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options';" ^
    "Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object {" ^
    "  $v = (Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue).Debugger;" ^
    "  if ($v -like '*cmd.exe*exit*') { Remove-ItemProperty -Path $_.PSPath -Name 'Debugger' -ErrorAction SilentlyContinue }" ^
    "}" >nul 2>&1
echo       IFEO           : DIBERSIHKAN
:: Re-enable Task Manager (user + system level)
reg delete "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "DisableTaskMgr" /f >nul 2>&1 && echo       TaskMgr (HKCU) : ENABLED
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "DisableTaskMgr" /f >nul 2>&1 && echo       TaskMgr (HKLM) : ENABLED

:: ----------------------------------------------------------------
:: [7/7] Hapus config + folder agent data
:: ----------------------------------------------------------------
echo [7/7] Menghapus config + folder data...
rmdir /s /q "C:\ProgramData\LabSCHAgent" >nul 2>&1 && echo       ProgramData    : DIHAPUS
:: Windows service (kalau pernah terinstall via install_service.py)
python "%~dp0install_service.py" remove >nul 2>&1 && echo       Service        : DIHAPUS

echo.
echo ================================================================
echo UNINSTALL SELESAI - PC SUDAH BERSIH
echo ================================================================
echo.
echo Yang sudah dicabut:
echo   - Semua blokir situs (hosts + browser policy)
echo   - Semua blokir aplikasi (IFEO)
echo   - Task Manager re-enabled
echo   - Semua auto-start (4 lapis)
echo   - Scheduled tasks + Run key
echo   - Config + folder C:\ProgramData\LabSCHAgent
echo   - Windows service (kalau ada)
echo.
echo CATATAN:
echo   - Browser perlu di-RESTART biar policy hilang dari memory.
echo   - File agent (python files) di folder ini gak kehapus.
echo     Hapus manual folder ini kalau mau total bersih.
echo   - Record PC masih ada di server (bersihkan via labschctl).
echo.
pause
popd >nul 2>&1
exit /b 0
