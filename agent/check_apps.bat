@echo off
setlocal EnableExtensions
title LabSCH - Cek Aplikasi Lab (teknisi)

:: ================================================================
:: check_apps.bat - pemeriksaan manual oleh TEKNISI (Administrator).
:: Mengecek Python, VirtualBox, Cisco Packet Tracer via registry +
:: exe path + version probe. BACA SAJA - tidak menginstall apapun.
:: Untuk instalasi, gunakan app_install.py terpisah.
:: ================================================================

net session >nul 2>&1
if errorlevel 1 (
    echo ERROR: Klik kanan check_apps.bat ^> "Run as administrator".
    pause
    exit /b 1
)

pushd "%~dp0" >nul 2>&1

if exist "%~dp0runtime\python.exe" (
    set "PY=%~dp0runtime\python.exe"
) else if exist "%ProgramFiles%\LabSCHAgent\runtime\python.exe" (
    set "PY=%ProgramFiles%\LabSCHAgent\runtime\python.exe"
) else (
    set "PY=python"
)

echo ================================================================
echo LabSCH - Pemeriksaan Aplikasi Lab
echo (registry uninstall + exe path + version probe)
echo ================================================================
echo.
"%PY%" "%~dp0appcheck.py"
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" echo CATATAN: appcheck selesai dengan exit %RC%.
echo Status: Terpasang / Belum terpasang / Versi tidak sesuai / Pemeriksaan gagal.
echo Bukti path+versi tercantum pada tiap aplikasi di atas.
echo.
pause
popd >nul 2>&1
exit /b %RC%
