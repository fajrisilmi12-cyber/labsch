@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LabSCHAgent Installer v0.4.1 (unified)

:: ================================================================
:: LabSCHAgent Installer - UNIFIED (v0.4.1)
::   Lokasi   : %ProgramFiles%\LabSCHAgent
::   Runtime  : %ProgramFiles%\LabSCHAgent\runtime\python.exe (SATU runtime)
::   Task     : LabSCHAgent (SATU scheduled task, SYSTEM, IgnoreNew)
::   State    : %ProgramData%\LabSCHAgent\config.ini
::   Versi    : agent\VERSION (sumber tunggal, via version.py)
:: Setiap tahap memeriksa exit code; GAGAL = berhenti, JANGAN klaim sukses.
:: ================================================================

set "FAIL=0"

:: ----------------------------------------------------------------
:: [0] Administrator check
:: ----------------------------------------------------------------
echo [0/7] Mengecek hak Administrator...
net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Klik kanan install.bat ^> "Run as administrator".
    exit /b 1
)
echo       OK

pushd "%~dp0" >nul 2>&1

:: ----------------------------------------------------------------
:: [1] Konfigurasi + versi tunggal
:: ----------------------------------------------------------------
echo [1/7] Membaca konfigurasi...
set "SERVER_URL=https://labsch-api.<your-subdomain>.workers.dev"
set "API_TOKEN=<your-uuid-token>"
if "%SERVER_URL%"=="https://labsch-api.<your-subdomain>.workers.dev" (
    echo ERROR: SERVER_URL masih placeholder. Isi URL Workers dulu.
    popd >nul 2>&1
    exit /b 2
)
if "%API_TOKEN%"=="<your-uuid-token>" (
    echo ERROR: API_TOKEN masih placeholder. Isi token enrollment dulu.
    popd >nul 2>&1
    exit /b 2
)
set "AGENT_VER=0.4.1"
if exist VERSION set /p "AGENT_VER=" < VERSION
echo       Server : %SERVER_URL%
echo       Versi  : %AGENT_VER%

set "DISPLAY_NAME="
set /p "DISPLAY_NAME=Nama PC (kosong=PC-%COMPUTERNAME%): "
if "%DISPLAY_NAME%"=="" set "DISPLAY_NAME=PC-%COMPUTERNAME%"
set "IS_TEST_FLAG=False"
set /p "IS_TEST=PC testing? [y/N]: "
if /i "%IS_TEST%"=="y" set "IS_TEST_FLAG=True"
echo       Nama PC: %DISPLAY_NAME% (test=%IS_TEST_FLAG%)

:: ----------------------------------------------------------------
:: [2] Runtime tunggal
:: ----------------------------------------------------------------
echo [2/7] Mengecek runtime tunggal...
if not exist "%~dp0runtime\python.exe" (
    echo ERROR: runtime\python.exe tidak ditemukan di paket ini.
    echo Gunakan paket full (dengan folder runtime^) atau jalankan upgrade.
    popd >nul 2>&1
    exit /b 3
)
"%~dp0runtime\python.exe" --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: runtime\python.exe tidak bisa dijalankan ^(exit %ERRORLEVEL%^).
    popd >nul 2>&1
    exit /b 3
)
echo       OK (runtime\python.exe)

:: ----------------------------------------------------------------
:: [3] Dependencies ke runtime
:: ----------------------------------------------------------------
echo [3/7] Memasang dependencies...
"%~dp0runtime\python.exe" -m pip --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: pip tidak tersedia di runtime. Jalankan: runtime\python.exe -m ensurepip --upgrade
    popd >nul 2>&1
    exit /b 3
)
"%~dp0runtime\python.exe" -m pip install --upgrade --disable-pip-version-check psutil requests pywin32
if errorlevel 1 (
    echo ERROR: Gagal memasang dependency ^(exit %ERRORLEVEL%^). Berhenti.
    popd >nul 2>&1
    exit /b 3
)
"%~dp0runtime\python.exe" -c "import win32api,win32con,win32process,win32security,win32ts; print('pywin32 OK')"
if errorlevel 1 (
    echo ERROR: pywin32 import gagal. Jalankan: runtime\python.exe -m pywin32_postinstall -install
    popd >nul 2>&1
    exit /b 3
)
echo       OK

:: ----------------------------------------------------------------
:: [4] Deploy ke %ProgramFiles%\LabSCHAgent (SATU lokasi)
:: ----------------------------------------------------------------
echo [4/7] Deploy ke %%ProgramFiles%%\LabSCHAgent...
set "TARGET=%ProgramFiles%\LabSCHAgent"
mkdir "%TARGET%" >nul 2>&1
for %%M in (labsch_agent.py config_sync.py version.py appcheck.py app_install.py app_config.json VERSION app_blocker.py website_blocker.py browser_policy.py ifeo_blocker.py self_protect.py device_id.py device_blocker.py command_executor.py downloader.py windows_launch.py labsch_launcher.py run_launcher.bat) do (
    if exist "%~dp0%%M" copy /y "%~dp0%%M" "%TARGET%\%%M" >nul 2>&1
)
if not exist "%TARGET%\labsch_agent.py" (
    echo ERROR: Gagal menyalin labsch_agent.py ke %TARGET%.
    popd >nul 2>&1
    exit /b 4
)
if exist "%~dp0runtime" xcopy /e /i /y "%~dp0runtime" "%TARGET%\runtime" >nul 2>&1
if not exist "%TARGET%\runtime\python.exe" (
    echo ERROR: Gagal menyalin runtime ke %TARGET%\runtime.
    popd >nul 2>&1
    exit /b 4
)
icacls "%TARGET%" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-32-545:(OI)(CI)RX" >nul 2>&1
echo       OK (%TARGET%)

:: ----------------------------------------------------------------
:: [5] State + config (versi tunggal dari VERSION)
:: ----------------------------------------------------------------
echo [5/7] Menulis config...
if not exist "C:\ProgramData\LabSCHAgent" mkdir "C:\ProgramData\LabSCHAgent" >nul 2>&1
"%TARGET%\runtime\python.exe" -c "import json,os;p=os.path.join(os.environ.get('PROGRAMDATA','C:/ProgramData'),'LabSCHAgent','config.ini');json.dump({'server_url':r'%SERVER_URL%','api_token':r'%API_TOKEN%','client_id':'','display_name':r'%DISPLAY_NAME%','is_test':%IS_TEST_FLAG%,'version':r'%AGENT_VER%'},open(p,'w',encoding='utf-8'),indent=2)"
if errorlevel 1 (
    echo ERROR: Gagal menulis config.ini ^(exit %ERRORLEVEL%^).
    popd >nul 2>&1
    exit /b 5
)
icacls "C:\ProgramData\LabSCHAgent" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" >nul 2>&1
echo       OK

:: ----------------------------------------------------------------
:: [6] SATU scheduled task: LabSCHAgent (+bersihkan legacy)
:: ----------------------------------------------------------------
echo [6/7] Mendaftarkan scheduled task tunggal LabSCHAgent...
for %%T in (LabSCHAgentWatchdog LabSCHAgentOnBoot LabSCHNotify LabSCHAgentNotify) do (
    schtasks /end /tn "%%T" >nul 2>&1
    schtasks /delete /tn "%%T" /f >nul 2>&1
)
schtasks /end /tn "LabSCHAgent" >nul 2>&1
schtasks /delete /tn "LabSCHAgent" /f >nul 2>&1
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "LabSCHAgent" /f >nul 2>&1
schtasks /create /tn "LabSCHAgent" /tr "\"%TARGET%\runtime\python.exe\" \"%TARGET%\labsch_agent.py\"" /sc onstart /ru SYSTEM /rl HIGHEST /f
if errorlevel 1 (
    echo ERROR: Gagal membuat task LabSCHAgent ^(exit %ERRORLEVEL%^). Berhenti.
    popd >nul 2>&1
    exit /b 6
)
schtasks /query /tn "LabSCHAgent" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Task LabSCHAgent tidak terdaftar setelah create. Berhenti.
    popd >nul 2>&1
    exit /b 6
)
echo       OK (task LabSCHAgent terdaftar)

:: ----------------------------------------------------------------
:: [7] Heartbeat uji (wajib sukses sebelum klaim selesai)
:: ----------------------------------------------------------------
echo [7/7] Tes koneksi heartbeat...
"%TARGET%\runtime\python.exe" "%TARGET%\labsch_agent.py" --once
if errorlevel 1 (
    echo PERINGATAN: heartbeat gagal ^(exit %ERRORLEVEL%^) - task tetap terdaftar, periksa server/token.
    popd >nul 2>&1
    exit /b 7
)
schtasks /run /tn "LabSCHAgent" >nul 2>&1

echo.
echo ================================================================
echo INSTALASI SELESAI - LabSCHAgent %AGENT_VER%
echo   Lokasi : %TARGET%
echo   Runtime: %TARGET%\runtime\python.exe
echo   Task   : LabSCHAgent
echo   Nama PC: %DISPLAY_NAME%
echo ================================================================
popd >nul 2>&1
exit /b 0
