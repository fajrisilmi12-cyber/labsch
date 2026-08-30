@echo off
setlocal EnableExtensions EnableDelayedExpansion
title LabSCHAgent Uninstaller

:: ================================================================
:: LabSCHAgent Uninstaller
::
:: Menghapus:
:: - Scheduled task
:: - Run key
:: - Re-enable Task Manager
:: - Config file
:: ================================================================

net session >nul 2>&1
if errorlevel 1 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo.
echo ================================================================
echo LabSCHAgent Uninstaller
echo ================================================================
echo.

echo [1/4] Removing scheduled task...
schtasks /delete /tn "LabSCHAgentWatchdog" /f >nul 2>&1
echo       OK

echo [2/4] Removing Run key...
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "LabSCHAgent" /f >nul 2>&1
echo       OK

echo [3/4] Re-enabling Task Manager...
reg delete "HKCU\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" /v "DisableTaskMgr" /f >nul 2>&1
echo       OK

echo [4/4] Removing config...
if exist "C:\ProgramData\LabSCHAgent\config.ini" (
    del /f /q "C:\ProgramData\LabSCHAgent\config.ini" >nul 2>&1
    echo       OK
)

echo.
echo ================================================================
echo UNINSTALL SELESAI
echo ================================================================
echo.
echo - Scheduled task removed
echo - Run key removed
echo - Task Manager re-enabled
echo - Config removed
echo.
echo Catatan: Agent binary (.exe) tidak dihapus. Hapus manual jika perlu.
echo.
pause
exit /b 0
