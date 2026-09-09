@echo off
setlocal EnableExtensions
title LabSCH Login Gate Uninstaller

:: ================================================================
:: LabSCH LOGIN GATE Uninstaller -- hapus TOTAL gate (Opsi B)
::
:: Menghapus:
::   1. Launcher dari startup folder (All Users)
::   2. login_gate.py dari ProgramData
::
:: TIDAK menyentuh:
::   - Agent LabSCH, config.json, auto-start layers agent
::   - Hosts file, registry policy, IFEO (itu urusan agent)
::
:: Jalankan sebagai Administrator.
:: ================================================================

net session >nul 2>&1
if errorlevel 1 (
    echo Meminta izin Administrator...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo ================================================================
echo LabSCH LOGIN GATE Uninstaller
echo ================================================================
echo.

set "STARTUP_DIR=%ProgramData%\Microsoft\Windows\Start Menu\Programs\StartUp"
set "DEST_DIR=%ProgramData%\LabSCHAgent"

echo [1/2] Hapus launcher dari startup...
if exist "%STARTUP_DIR%\LabSCHGate.bat" (
    del /F /Q "%STARTUP_DIR%\LabSCHGate.bat"
    echo        OK: dihapus
) else (
    echo        Tidak ada -- skip
)

echo [2/2] Hapus gate script...
if exist "%DEST_DIR%\login_gate.py" (
    del /F /Q "%DEST_DIR%\login_gate.py"
    echo        OK: dihapus
) else (
    echo        Tidak ada -- skip
)

echo.
echo Selesai. Gate sudah TOTAL hilang.
echo Agent LabSCH tidak tersentuh (masih jalan seperti biasa).
echo.
pause
