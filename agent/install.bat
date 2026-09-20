@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LabSCHAgent Installer

:: ================================================================
:: LabSCHAgent Installer
:: ================================================================

:: ----------------------------------------------------------------
:: 0. Auto-elevate ke Administrator
:: ----------------------------------------------------------------
echo.
echo ================================================================
echo LabSCHAgent Installer
echo ================================================================
echo.
echo [0/5] Mengecek hak Administrator...
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo =====================================================
    echo  PERHATIAN: Belum ada hak Administrator!
    echo =====================================================
    echo.
    echo CARA YANG BENAR:
    echo   1. TUTUP window ini
    echo   2. Klik kanan file install.bat
    echo   3. Pilih "Run as administrator"
    echo   4. Klik "Yes" di popup UAC
    echo.
    echo JANGAN double-click biasa! Harus klik kanan - Run as admin.
    echo.
    timeout /t 30 /nobreak >nul 2>&1
    exit /b 1
)
echo       OK (running as Administrator)
echo.

pushd "%~dp0" >nul 2>&1

:: ----------------------------------------------------------------
:: 1. Konfigurasi
:: ----------------------------------------------------------------
set "SERVER_URL=https://labsch-api.<your-subdomain>.workers.dev"
set "API_TOKEN=<your-uuid-token>"

if "%API_TOKEN%"=="<your-uuid-token>" (
    echo ERROR: API_TOKEN masih placeholder.
    pause
    exit /b 2
)
if "%SERVER_URL%"=="https://labsch-api.<your-subdomain>.workers.dev" (
    echo ERROR: SERVER_URL masih placeholder.
    pause
    exit /b 2
)

echo Server: %SERVER_URL%
echo Token:  %API_TOKEN:~0,8%...
echo.

:: ----------------------------------------------------------------
:: 1b. Tanya display_name
:: ----------------------------------------------------------------
echo PENAMAAN KOMPUTER
echo.
echo Masukkan nama untuk PC ini (contoh: PC-LAB-01).
echo Kosongkan untuk pakai nama otomatis.
echo.
set "DISPLAY_NAME="
set /p "DISPLAY_NAME=Nama PC: "
if "%DISPLAY_NAME%"=="" set "DISPLAY_NAME=PC-%COMPUTERNAME%"
echo Nama PC: %DISPLAY_NAME%
echo.

:: Test PC?
set "IS_TEST="
set /p "IS_TEST=PC testing/development? [y/N]: "
if /i "%IS_TEST%"=="y" (
    set "IS_TEST_FLAG=True"
) else (
    set "IS_TEST_FLAG=False"
)
echo Test PC: %IS_TEST_FLAG%
echo.

:: ----------------------------------------------------------------
:: 2. Cek Python
:: ----------------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo Python tidak ditemukan. Install Python 3.10+ dulu.
    pause
    exit /b 1
)

:: ----------------------------------------------------------------
:: 3. Install dependencies
:: ----------------------------------------------------------------
echo [1/5] Installing dependencies...
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python tidak ditemukan di PATH.
    pause
    exit /b 1
)
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: pip tidak tersedia pada Python aktif.
    echo Jalankan: python -m ensurepip --upgrade
    pause
    exit /b 1
)
python -m pip install --upgrade --disable-pip-version-check psutil requests pywin32
if errorlevel 1 (
    echo ERROR: Gagal memasang dependency Python.
    pause
    exit /b 1
)
python -c "import win32api,win32con,win32process,win32security,win32ts; print('pywin32 OK')"
if errorlevel 1 (
    echo ERROR: pywin32 terpasang tetapi import gagal.
    echo Coba jalankan: python -m pywin32_postinstall -install
    pause
    exit /b 1
)
echo       OK (pywin32 verified)

:: ----------------------------------------------------------------
:: 4. Setup config
:: ----------------------------------------------------------------
echo [2/5] Writing config...
if not exist "C:\ProgramData\LabSCHAgent" mkdir "C:\ProgramData\LabSCHAgent"
python -c "import json,os;p=os.path.join(os.environ.get('PROGRAMDATA','C:/ProgramData'),'LabSCHAgent','config.ini');json.dump({'server_url':r'%SERVER_URL%','api_token':r'%API_TOKEN%','client_id':'','display_name':r'%DISPLAY_NAME%','is_test':%IS_TEST_FLAG%,'version':'0.4.0-test2'},open(p,'w',encoding='utf-8'),indent=2)"
echo       OK

:: ----------------------------------------------------------------
:: 5. Install self-protection
:: ----------------------------------------------------------------
echo [3/5] Installing self-protection...
schtasks /delete /tn "LabSCHAgentWatchdog" /f >nul 2>&1
schtasks /delete /tn "LabSCHAgentOnBoot" /f >nul 2>&1

:: Satu task kontinu saat boot. Jangan gunakan --once: mode itu heartbeat sekali lalu exit.
:: Jangan buat watchdog periodik kedua karena dapat melahirkan beberapa instance agent.
schtasks /create /tn "LabSCHAgentOnBoot" /tr "python \"%~dp0labsch_agent.py\"" /sc onstart /ru SYSTEM /rl HIGHEST /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "LabSCHAgent" /f >nul 2>&1
schtasks /run /tn "LabSCHAgentOnBoot" >nul 2>&1
echo       OK

:: ----------------------------------------------------------------
:: 6. Lockdown (disable Task Manager)
:: ----------------------------------------------------------------
echo [4/5] Disabling Task Manager...
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "DisableTaskMgr" /t REG_DWORD /d "1" /f >nul 2>&1
reg add "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "DisableTaskMgr" /t REG_DWORD /d "1" /f >nul 2>&1
taskkill /f /im taskmgr.exe >nul 2>&1
echo       OK (jika belum aktif, coba logoff/login)

:: ----------------------------------------------------------------
:: 7. Test heartbeat
:: ----------------------------------------------------------------
echo [5/5] Testing connection...
python labsch_agent.py --once
if errorlevel 1 (
    echo PERINGATAN: Gagal connect ke server.
) else (
    echo KONEKSI BERHASIL.
)

echo.
echo ================================================================
echo INSTALASI SELESAI
echo ================================================================
echo Nama PC: %DISPLAY_NAME%
echo.

:: Tanya langsung start agent
set "START_NOW="
set /p "START_NOW=Start agent sekarang? [Y/n]: "
if /i not "%START_NOW%"=="n" (
    echo Starting agent...
    python labsch_agent.py
)

echo.
echo Tekan tombol apa saja untuk keluar...
pause >nul
popd >nul 2>&1
exit /b 0
