@echo off
setlocal EnableExtensions
title LabSCH Startup Uninstaller

:: ================================================================
:: LabSCH STARTUP Uninstaller -- hapus semua 4 lapis auto-start
:: Jalankan sebagai Administrator.
:: ================================================================

net session >nul 2>&1
if errorlevel 1 (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo Menghapus semua auto-start LabSCH...

schtasks /delete /tn "LabSCHAgentOnBoot" /f >nul 2>&1 && echo   Task OnBoot   : DIHAPUS
schtasks /delete /tn "LabSCHAgentWatchdog" /f >nul 2>&1 && echo   Task Watchdog : DIHAPUS
reg delete "HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run" /v "LabSCHAgent" /f >nul 2>&1 && echo   Run key       : DIHAPUS
del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\LabSCHAgent_start.bat" >nul 2>&1 && echo   Startup user  : DIHAPUS
del "C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp\LabSCHAgent_start.bat" >nul 2>&1 && echo   Startup all   : DIHAPUS
del "C:\ProgramData\LabSCHAgent\labsch_start.bat" >nul 2>&1

echo.
echo Selesai. Agent gak akan jalan otomatis lagi.
echo (Agent yang lagi jalan tetap hidup sampai PC direstart/dimatikan manual)
echo.
pause
exit /b 0
