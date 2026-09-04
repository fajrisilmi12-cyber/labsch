@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LabSCH Startup Installer

:: ================================================================
:: LabSCH STARTUP Installer — pastikan agent JALAN setiap reboot
::
:: Yang dipasang (4 lapis, biar gak mungkin miss):
::   1. Startup folder (user)      — jalan pas user login
::   2. Startup folder (ALL users) — jalan pas user mana pun login
::   3. Run key HKLM               — boot-time launch
::   4. Scheduled task ONSTART     — jalan SEBELUM login (SYSTEM)
::
:: Plus: starter script yang nunggu Python siap (network stack up)
:: lalu launch agent — ini solusi utama masalah "kadang gak ke load"
:: (Python/PATH belum siap saat Run key dieksekusi terlalu dini).
::
:: Jalankan SEKALI sebagai Administrator. Selesai.
:: ================================================================

:: --- Auto-elevate ---
net session >nul 2>&1
if errorlevel 1 (
    echo Meminta izin Administrator...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

pushd "%~dp0" >nul 2>&1

:: --- Lokasi agent (folder tempat file ini + agent ada) ---
set "AGENT_DIR=%~dp0"
set "AGENT_PY=%AGENT_DIR%labsch_agent.py"
if not exist "%AGENT_PY%" (
    echo ERROR: labsch_agent.py tidak ditemukan di %AGENT_DIR%
    echo Taruh file ini SEFOLDER dengan labsch_agent.py, lalu jalankan lagi.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo LabSCH STARTUP Installer
echo ================================================================
echo Agent: %AGENT_PY%
echo.

:: ----------------------------------------------------------------
:: [1/5] Bikin starter script (hidden, nunggu Python siap)
:: ----------------------------------------------------------------
echo [1/5] Membuat starter script (delayed-launch dengan retry)...
(
    echo @echo off
    echo rem LabSCH auto-starter — nunggu sistem siap, lalu launch agent
    echo rem Loop max 60x5s = 5 menit. Kalau python belum siap, retry.
    echo set /a TRIES=0
    echo :wait_python
    echo where python ^>nul 2^>^&1
    echo if errorlevel 1 ^(
    echo     set /a TRIES+=1
    echo     if !TRIES! GEQ 60 exit /b
    echo     timeout /t 5 /nobreak ^>nul
    echo     goto wait_python
    echo ^)
    echo :launch
    echo cd /d "%AGENT_DIR%"
    echo python "%AGENT_PY%"
    echo rem Kalau agent mati, respawn tiap 10 detik
    echo timeout /t 10 /nobreak ^>nul
    echo goto launch
) > "C:\ProgramData\LabSCHAgent\labsch_start.bat" 2>nul
if not exist "C:\ProgramData\LabSCHAgent" mkdir "C:\ProgramData\LabSCHAgent" >nul 2>&1
(
    echo @echo off
    echo rem LabSCH auto-starter - nunggu sistem siap, lalu launch agent
    echo set /a TRIES=0
    echo :wait_python
    echo where python ^>nul 2^>^&1
    echo if errorlevel 1 ^(
    echo     set /a TRIES+=1
    echo     if !TRIES! GEQ 60 exit /b
    echo     timeout /t 5 /nobreak ^>nul
    echo     goto wait_python
    echo ^)
    echo :launch
    echo cd /d "%AGENT_DIR%"
    echo python "%AGENT_PY%"
    echo timeout /t 10 /nobreak ^>nul
    echo goto launch
) > "C:\ProgramData\LabSCHAgent\labsch_start.bat"
echo       OK - C:\ProgramData\LabSCHAgent\labsch_start.bat

:: ----------------------------------------------------------------
:: [2/5] Startup folder — user ini + ALL users
:: ----------------------------------------------------------------
echo [2/5] Memasang di Startup folder (user + all users)...
set "STARTUP_USER=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "STARTUP_ALL=C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp"
copy /y "C:\ProgramData\LabSCHAgent\labsch_start.bat" "%STARTUP_USER%\LabSCHAgent_start.bat" >nul 2>&1 && echo       user startup   OK
copy /y "C:\ProgramData\LabSCHAgent\labsch_start.bat" "%STARTUP_ALL%\LabSCHAgent_start.bat" >nul 2>&1 && echo       all-users startup OK

:: ----------------------------------------------------------------
:: [3/5] Run key HKLM (backup layer)
:: ----------------------------------------------------------------
echo [3/5] Memasang Run key (HKLM)...
reg add "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "LabSCHAgent" /t REG_SZ /d "\"C:\ProgramData\LabSCHAgent\labsch_start.bat\"" /f >nul 2>&1 && echo       OK

:: ----------------------------------------------------------------
:: [4/5] Scheduled task ONSTART (jalan sebelum login, SYSTEM)
:: ----------------------------------------------------------------
echo [4/5] Memasang scheduled task ONSTART...
schtasks /delete /tn "LabSCHAgentOnBoot" /f >nul 2>&1
schtasks /create /tn "LabSCHAgentOnBoot" /tr "\"C:\ProgramData\LabSCHAgent\labsch_start.bat\"" /sc onstart /ru SYSTEM /rl HIGHEST /f >nul 2>&1 && echo       OK (jalan saat boot, sebelum login)
:: Watchdog: respawn tiap 5 menit kalau agent mati
schtasks /delete /tn "LabSCHAgentWatchdog" /f >nul 2>&1
schtasks /create /tn "LabSCHAgentWatchdog" /tr "\"C:\ProgramData\LabSCHAgent\labsch_start.bat\"" /sc minute /mo 5 /ru SYSTEM /rl HIGHEST /f >nul 2>&1 && echo       Watchdog OK (cek tiap 5 menit)

:: ----------------------------------------------------------------
:: [5/5] Verifikasi + test start
:: ----------------------------------------------------------------
echo [5/5] Verifikasi...
schtasks /query /tn "LabSCHAgentOnBoot" >nul 2>&1 && echo       Task OnBoot   : TERPASANG || echo       Task OnBoot   : GAGAL
schtasks /query /tn "LabSCHAgentWatchdog" >nul 2>&1 && echo       Task Watchdog : TERPASANG || echo       Task Watchdog : GAGAL
reg query "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "LabSCHAgent" >nul 2>&1 && echo       Run key       : TERPASANG || echo       Run key       : GAGAL
if exist "%STARTUP_USER%\LabSCHAgent_start.bat" echo       Startup user  : TERPASANG
if exist "%STARTUP_ALL%\LabSCHAgent_start.bat" echo       Startup all   : TERPASANG

echo.
echo ================================================================
echo INSTALASI STARTUP SELESAI
echo ================================================================
echo.
echo Agent akan jalan otomatis saat reboot via 4 lapis:
echo   1. Startup folder (user)      - pas login
echo   2. Startup folder (all users) - user mana pun
echo   3. Run key HKLM               - boot
echo   4. Scheduled task ONSTART     - SEBELUM login
echo.
echo Starter script nunggu Python siap (max 5 menit) lalu launch
echo agent, dan respawn otomatis kalau agent mati.
echo.
echo Uninstall: jalankan labsch_startup_uninstall.bat
echo.
pause
popd >nul 2>&1
exit /b 0
