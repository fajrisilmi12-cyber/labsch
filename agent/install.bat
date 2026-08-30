@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LabSCHAgent 1-Click Installer

:: ================================================================
:: LabSCHAgent 1-Click Installer
::
:: Satu file ini ngejalanin semuanya:
:: 1. Auto-elevate ke Administrator
:: 2. Setup config (server URL + token)
:: 3. Install self-protection (scheduled task + Run key)
:: 4. Lockdown (disable Task Manager)
:: 5. Start agent immediately
::
:: Tinggal double-click file ini. Tidak perlu command line.
:: ================================================================

:: ----------------------------------------------------------------
:: 0. Auto-elevate ke Administrator
:: ----------------------------------------------------------------
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo Meminta izin Administrator...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

pushd "%~dp0" >nul 2>&1

:: ----------------------------------------------------------------
:: 1. Konfigurasi (ganti kalau perlu, default sudah benar)
:: ----------------------------------------------------------------
set "SERVER_URL=https://enhanced-tmp-chances-completion.trycloudflare.com"
set "API_TOKEN=UR5BMxbHVbC-w-jAN_qfCo5ahaJe_6NDhlfWITYi-0M"

echo.
echo ================================================================
echo LabSCHAgent 1-Click Installer
echo ================================================================
echo.
echo Server: %SERVER_URL%
echo Token:  %API_TOKEN:~0,8%...
echo.

:: ----------------------------------------------------------------
:: 1b. Tanya display_name (untuk identifikasi di server)
:: ----------------------------------------------------------------
echo ================================================================
echo PENAMAAN KOMPUTER
echo ================================================================
echo.
echo Masukkan nama untuk PC ini. Contoh:
echo   - PC-LAB-01 (PC laboratorium nomor 1)
echo   - PC-GURU-FAJRI (PC guru)
echo   - PC-TEST-MSI (PC testing, akan dikecualikan dari profile)
echo.
echo Kosongkan untuk pakai nama otomatis (PC-{hostname}).
echo.
set "DISPLAY_NAME="
set /p "DISPLAY_NAME=Nama PC: "
if "%DISPLAY_NAME%"=="" set "DISPLAY_NAME=PC-%COMPUTERNAME%"
echo Nama PC: %DISPLAY_NAME%
echo.

:: Tanya apakah PC ini untuk testing (dikecualikan dari profile rules)
set "IS_TEST="
set /p "IS_TEST=PC testing/development? (PC ini dikecualikan dari rules lab) [y/N]: "
if /i "%IS_TEST%"=="y" (
    set "IS_TEST_FLAG=true"
) else (
    set "IS_TEST_FLAG=false"
)
echo Test PC: %IS_TEST_FLAG%
echo.

:: ----------------------------------------------------------------
:: 2. Cek Python
:: ----------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo Python tidak ditemukan. Install Python 3.10+ dulu dari python.org
    echo Download: https://www.python.org/downloads/
    echo JANGAN LUPA centang "Add Python to PATH" saat install.
    pause
    exit /b 1
)

:: ----------------------------------------------------------------
:: 3. Install dependencies
:: ----------------------------------------------------------------
echo [1/5] Installing dependencies...
pip install --quiet psutil requests >nul 2>&1
if errorlevel 1 (
    pip install --user psutil requests
)
echo       OK

:: ----------------------------------------------------------------
:: 4. Setup config
:: ----------------------------------------------------------------
echo [2/5] Writing config...
if not exist "C:\ProgramData\LabSCHAgent" mkdir "C:\ProgramData\LabSCHAgent"
(
    echo {
    echo   "server_url": "%SERVER_URL%",
    echo   "api_token": "%API_TOKEN%",
    echo   "client_id": "",
    echo   "display_name": "%DISPLAY_NAME%",
    echo   "is_test": %IS_TEST_FLAG%,
    echo   "version": "0.1.0"
    echo }
) > "C:\ProgramData\LabSCHAgent\config.ini"
echo       OK

:: ----------------------------------------------------------------
:: 5. Install self-protection
:: ----------------------------------------------------------------
echo [3/5] Installing self-protection (scheduled task + Run key)...
schtasks /delete /tn "LabSCHAgentWatchdog" /f >nul 2>&1
schtasks /create /tn "LabSCHAgentWatchdog" /tr "python \"%~dp0labsch_agent.py\"" /sc minute /mo 5 /ru SYSTEM /rl HIGHEST /f >nul 2>&1
if errorlevel 1 (
    echo       WARNING: scheduled task gagal (mungkin nama task sudah ada)
) else (
    echo       scheduled task OK (restart tiap 5 menit)
)
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "LabSCHAgent" /t REG_SZ /d "python \"%~dp0labsch_agent.py\"" /f >nul 2>&1
if errorlevel 1 (
    echo       WARNING: Run key gagal
) else (
    echo       Run key OK (auto-start saat boot)
)

:: ----------------------------------------------------------------
:: 6. Lockdown (disable Task Manager)
:: ----------------------------------------------------------------
echo [4/5] Disabling Task Manager...
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "DisableTaskMgr" /t REG_DWORD /d "1" /f >nul 2>&1
echo       OK

:: ----------------------------------------------------------------
:: 7. Test heartbeat (1x)
:: ----------------------------------------------------------------
echo [5/5] Testing connection to server...
python labsch_agent.py --once
if errorlevel 1 (
    echo.
    echo PERINGATAN: Gagal connect ke server. Cek internet / token.
    echo Agent tetap terinstall, coba jalanin manual nanti.
) else (
    echo.
    echo KONEKSI BERHASIL. Agent sudah terdaftar.
)

:: ----------------------------------------------------------------
:: 8. Selesai
:: ----------------------------------------------------------------
echo.
echo ================================================================
echo INSTALASI SELESAI
echo ================================================================
echo.
echo Yang sudah terpasang:
echo   - Nama PC: %DISPLAY_NAME%
echo   - Test PC: %IS_TEST_FLAG%
echo   - Config di C:\ProgramData\LabSCHAgent\
echo   - Scheduled Task "LabSCHAgentWatchdog" (auto-respawn)
echo   - Run key "LabSCHAgent" (auto-start saat boot)
echo   - Task Manager disabled
echo   - Agent terdaftar di server
echo.
echo Agent akan jalan otomatis:
echo   - Setiap 5 menit (kalau dimatikan)
echo   - Setiap kali PC di-restart
echo.
echo Untuk UNINSTALL (misal pindah PC), jalankan: uninstall.bat
echo.

:: Tanya langsung start agent
choice /C YN /N /M "Start agent sekarang (foreground)? [Y/N]: "
if errorlevel 2 goto :NoStart

echo.
echo Starting agent... (tekan Ctrl+C untuk keluar)
echo.
python labsch_agent.py

:NoStart
echo.
echo Agent akan jalan otomatis tiap 5 menit / boot.
echo Untuk start manual: python labsch_agent.py
echo.
pause
popd >nul 2>&1
exit /b 0
