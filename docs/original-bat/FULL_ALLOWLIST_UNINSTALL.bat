@echo off
setlocal EnableExtensions EnableDelayedExpansion
title FULL ALLOWLIST WEB v4 - UNINSTALL - Windows 10 LTSC

:: ================================================================
:: FULL ALLOWLIST WEB v4 - UNINSTALL
:: Windows 10 LTSC
::
:: Menghapus SEMUA kebijakan whitelist yang dipasang oleh
:: FULL_ALLOWLIST_SETUP.bat:
::   - URLBlocklist / URLAllowlist (Edge, Chrome, Brave)
::   - DnsOverHttpsMode
::   - InPrivateModeAvailability / IncognitoModeAvailability
::   - IFEO block untuk Roblox
::   - Firewall rules lama (QUIC)
::
:: Setelah uninstall, browser kembali normal (tidak ada blokir).
:: Restart diperlukan agar kebijakan baru berlaku.
:: ================================================================

:: ----------------------------------------------------------------
:: 0. Auto-elevate ke Administrator
:: ----------------------------------------------------------------
net session >nul 2>&1
if errorlevel 1 (
    echo.
    echo Meminta izin Administrator...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    if errorlevel 1 (
        echo.
        echo ERROR: Permintaan Administrator gagal atau dibatalkan.
        echo Jalankan ulang sebagai administrator.
        pause
    )
    exit /b
)

echo.
echo ================================================================
echo FULL ALLOWLIST WEB v4 - UNINSTALL
echo ================================================================
echo.

:: ----------------------------------------------------------------
:: 1. Hapus firewall rules
:: ----------------------------------------------------------------
echo [1/5] Menghapus aturan firewall...
netsh advfirewall firewall delete rule name="Block QUIC Outbound" >nul 2>&1
netsh advfirewall firewall delete rule name="Block QUIC Inbound"  >nul 2>&1
echo       OK

:: ----------------------------------------------------------------
:: 2. Hapus kebijakan Edge
:: ----------------------------------------------------------------
echo [2/5] Menghapus whitelist Microsoft Edge...
call :RemoveBrowserPolicies "HKLM\SOFTWARE\Policies\Microsoft\Edge"
echo       OK

:: ----------------------------------------------------------------
:: 3. Hapus kebijakan Chrome
:: ----------------------------------------------------------------
echo [3/5] Menghapus whitelist Google Chrome...
call :RemoveBrowserPolicies "HKLM\SOFTWARE\Policies\Google\Chrome"
echo       OK

:: ----------------------------------------------------------------
:: 4. Hapus kebijakan Brave
:: ----------------------------------------------------------------
echo [4/5] Menghapus whitelist Brave...
call :RemoveBrowserPolicies "HKLM\SOFTWARE\Policies\BraveSoftware\Brave"
echo       OK

:: ----------------------------------------------------------------
:: 5. Hapus IFEO block Roblox
:: ----------------------------------------------------------------
echo [5/5] Menghapus blokir Roblox...
for %%G in (
    RobloxPlayerBeta.exe
    RobloxPlayerLauncher.exe
    RobloxPlayerInstaller.exe
    RobloxStudioBeta.exe
) do (
    reg delete "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\%%G" /f >nul 2>&1
    if not errorlevel 1 echo       Dihapus %%G
)

ipconfig /flushdns >nul 2>&1

echo.
echo ================================================================
echo UNINSTALL SELESAI
echo ================================================================
echo.
echo SEMUA kebijakan whitelist telah dihapus.
echo Browser akan kembali normal setelah restart.
echo.
echo YANG DIHAPUS:
echo   - URLBlocklist / URLAllowlist (Edge, Chrome, Brave)
echo   - DnsOverHttpsMode (kembali default)
echo   - Incognito/InPrivate mode (kembali aktif)
echo   - IFEO block untuk Roblox
echo.
echo PENTING:
echo   1. Tutup TOTAL Edge/Chrome/Brave via Task Manager
echo   2. Restart komputer agar perubahan berlaku
echo.

choice /C YN /N /M "Restart komputer sekarang? [Y/N]: "
if errorlevel 2 goto :NoRestart

echo.
echo Komputer akan restart dalam 10 detik.
shutdown /r /t 10 /c "Whitelist web dihapus. Restart diperlukan."
exit /b 0

:NoRestart
echo.
echo Silakan restart manual nanti.
pause
exit /b 0


:: ================================================================
:: SUBROUTINE: Hapus semua kebijakan untuk satu browser Chromium
:: ================================================================
:RemoveBrowserPolicies
set "POLICY_ROOT=%~1"

:: Hapus URLBlocklist dan URLAllowlist
reg delete "%POLICY_ROOT%\URLBlocklist" /f >nul 2>&1
reg delete "%POLICY_ROOT%\URLAllowlist" /f >nul 2>&1

:: Hapus DnsOverHttpsMode
reg delete "%POLICY_ROOT%" /v DnsOverHttpsMode /f >nul 2>&1

:: Hapus Incognito/InPrivate mode
reg delete "%POLICY_ROOT%" /v InPrivateModeAvailability /f >nul 2>&1
reg delete "%POLICY_ROOT%" /v IncognitoModeAvailability /f >nul 2>&1

exit /b 0
