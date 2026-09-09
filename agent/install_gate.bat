@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LabSCH Login Gate Installer

:: ================================================================
:: LabSCH LOGIN GATE Installer -- Opsi B (zero server change)
::
:: Pasang gate yang tanya nama murid tiap login, lalu tulis ke
:: display_name agent. Desktop TIDAK pernah diblokir (fail-open).
::
:: Yang dipasang:
::   1. Startup folder ALL users -- jalan tiap user login
::
:: Yang TIDAK dipasang (sengaja, demi keamanan tes):
::   - Tidak ada service, tidak ada ONSTART task, tidak ada HKLM write
::   - Tidak ada self-protect
::   - Bisa dihapus total via uninstall_gate.bat (1 file delete)
::
:: Jalankan sebagai Administrator (untuk tulis ke All Users startup).
:: ================================================================

:: --- Auto-elevate ---
net session >nul 2>&1
if errorlevel 1 (
    echo Meminta izin Administrator...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

pushd "%~dp0" >nul 2>&1

set "GATE_PY=%~dp0login_gate.py"
if not exist "%GATE_PY%" (
    echo ERROR: login_gate.py tidak ditemukan di %~dp0
    echo Taruh file ini SEFOLDER dengan login_gate.py, lalu jalankan lagi.
    pause
    exit /b 1
)

echo.
echo ================================================================
echo LabSCH LOGIN GATE Installer (Opsi B)
echo ================================================================
echo Gate script: %GATE_PY%
echo.

:: ----------------------------------------------------------------
:: [1/3] Copy gate ke ProgramData (biar gak depends folder installer)
:: ----------------------------------------------------------------
echo [1/3] Copy login_gate.py ke C:\ProgramData\LabSCHAgent ...
set "DEST_DIR=%ProgramData%\LabSCHAgent"
if not exist "%DEST_DIR%" mkdir "%DEST_DIR%"
copy /Y "%GATE_PY%" "%DEST_DIR%\login_gate.py" >nul
if errorlevel 1 (
    echo ERROR: gagal copy ke %DEST_DIR%
    pause
    exit /b 1
)
echo        OK: %DEST_DIR%\login_gate.py

:: ----------------------------------------------------------------
:: [2/3] Bikin launcher .bat di startup folder ALL USERS
::       (HKLM startup = jalan untuk user mana pun yang login)
:: ----------------------------------------------------------------
echo [2/3] Membuat launcher di startup folder (All Users)...
set "STARTUP_DIR=%ProgramData%\Microsoft\Windows\Start Menu\Programs\StartUp"
set "LAUNCHER=%STARTUP_DIR%\LabSCHGate.bat"
(
    echo @echo off
    echo rem LabSCH login gate -- tanya nama murid tiap login, tulis display_name
    echo start "" /min pythonw.exe "%DEST_DIR%\login_gate.py"
) > "%LAUNCHER%"
if errorlevel 1 (
    echo ERROR: gagal membuat launcher di %STARTUP_DIR%
    pause
    exit /b 1
)
echo        OK: %LAUNCHER%

:: ----------------------------------------------------------------
:: [3/3] Selesai -- instruksi uninstall
:: ----------------------------------------------------------------
echo [3/3] Selesai!
echo.
echo Pemasangan BERHASIL.
echo.
echo Cara tes cepat (tanpa reboot):
echo   Jalankan manual:  pythonw.exe "%DEST_DIR%\login_gate.py"
echo   Lalu cek:         type "%DEST_DIR%\config.json"
echo   (cari baris "display_name": "^<nama yang dimasukkan^>")
echo.
echo Setelah reboot/login berikutnya:
echo   - Dialog input nama muncul beberapa detik setelah desktop load
echo   - Isi nama ^(min. 4 huruf^) lalu OK
echo   - Dalam 30 detik, nama muncul di `labschctl clients` (kolom nama PC)
echo.
echo UNINSTALL total ^(1 langkah^):
echo   Hapus file: %LAUNCHER%
echo   Hapus file: %DEST_DIR%\login_gate.py
echo   Atau jalankan uninstall_gate.bat
echo.
pause
