@echo off
setlocal EnableExtensions EnableDelayedExpansion
title FULL ALLOWLIST WEB v4 - SETUP - Windows 10 LTSC

:: ================================================================
:: FULL ALLOWLIST WEB v4 - SETUP
:: Windows 10 LTSC
::
:: Browser yang dikelola : Microsoft Edge, Google Chrome, Brave
:: Diizinkan             : Google Search, ChatGPT, Gemini, Claude,
::                         Canva, Wikipedia, SIAPkerja Kemnaker
:: Diblokir              : YouTube (seluruh domain), Roblox
:: Layanan Windows       : TIDAK diblokir
::
:: Cara menjalankan:
::   Klik kanan file ini > Run as administrator
::   Atau jalankan dari flashdisk, lalu klik Yes di UAC
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

pushd "%~dp0" >nul 2>&1

echo.
echo ================================================================
echo FULL ALLOWLIST WEB v4 - SETUP
echo ================================================================
echo.

:: ----------------------------------------------------------------
:: 1. Bersihkan aturan firewall lama (QUIC)
:: ----------------------------------------------------------------
echo [1/5] Membersihkan aturan firewall lama...
netsh advfirewall firewall delete rule name="Block QUIC Outbound" >nul 2>&1
netsh advfirewall firewall delete rule name="Block QUIC Inbound"  >nul 2>&1
echo       OK

:: ----------------------------------------------------------------
:: 2. Terapkan whitelist ke Edge
:: ----------------------------------------------------------------
echo [2/5] Memasang whitelist Microsoft Edge...
call :ApplyBrowserWhitelist "HKLM\SOFTWARE\Policies\Microsoft\Edge"
echo       OK

:: ----------------------------------------------------------------
:: 3. Terapkan whitelist ke Chrome
:: ----------------------------------------------------------------
echo [3/5] Memasang whitelist Google Chrome...
call :ApplyBrowserWhitelist "HKLM\SOFTWARE\Policies\Google\Chrome"
echo       OK

:: ----------------------------------------------------------------
:: 4. Terapkan whitelist ke Brave
:: ----------------------------------------------------------------
echo [4/5] Memasang whitelist Brave...
call :ApplyBrowserWhitelist "HKLM\SOFTWARE\Policies\BraveSoftware\Brave"
echo       OK

:: ----------------------------------------------------------------
:: 5. Blokir Roblox via IFEO
:: ----------------------------------------------------------------
echo [5/5] Memblokir Roblox desktop...
for %%G in (
    RobloxPlayerBeta.exe
    RobloxPlayerLauncher.exe
    RobloxPlayerInstaller.exe
    RobloxStudioBeta.exe
) do (
    reg add "HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\%%G" /v Debugger /t REG_SZ /d "cmd.exe /c exit" /f >nul
    echo       Blokir %%G
)

ipconfig /flushdns >nul 2>&1

echo.
echo ================================================================
echo PEMASANGAN SELESAI
echo ================================================================
echo.
echo BOLEH DIBUKA:
echo   Google Search, ChatGPT, Gemini, Claude, Canva,
echo   Wikipedia, SIAPkerja Kemnaker
echo.
echo DIBLOKIR:
echo   Semua situs lain + YouTube + Roblox
echo.
echo PENTING:
echo   1. Tutup TOTAL Edge/Chrome/Brave via Task Manager
echo   2. Restart komputer
echo   3. Cek kebijakan: edge://policy atau chrome://policy
echo.

choice /C YN /N /M "Restart komputer sekarang? [Y/N]: "
if errorlevel 2 goto :NoRestart

echo.
echo Komputer akan restart dalam 10 detik.
shutdown /r /t 10 /c "Whitelist web dipasang. Restart diperlukan."
popd >nul 2>&1
exit /b 0

:NoRestart
echo.
echo Silakan restart manual nanti.
pause
popd >nul 2>&1
exit /b 0


:: ================================================================
:: SUBROUTINE: Terapkan whitelist untuk satu browser Chromium
:: ================================================================
:ApplyBrowserWhitelist
set "POLICY_ROOT=%~1"

:: Hapus daftar lama
reg delete "%POLICY_ROOT%\URLBlocklist" /f >nul 2>&1
reg delete "%POLICY_ROOT%\URLAllowlist" /f >nul 2>&1

:: Block all
reg add "%POLICY_ROOT%\URLBlocklist" /v 1 /t REG_SZ /d "*" /f >nul

:: Blok spesifik (override prioritas *)
set "IDX=1"
for %%D in (
    youtube.com
    youtu.be
    youtube-nocookie.com
    googlevideo.com
    ytimg.com
    youtube.googleapis.com
    youtubei.googleapis.com
    roblox.com
) do (
    set /a IDX+=1
    reg add "%POLICY_ROOT%\URLBlocklist" /v !IDX! /t REG_SZ /d "%%D" /f >nul
)

:: Allowlist — dependensi Google, AI, dan Kemnaker
set "IDX=0"
for %%D in (
    .google.com
    .www.google.com
    .accounts.google.com
    .gemini.google.com
    .ogs.google.com
    gstatic.com
    googleapis.com
    googleusercontent.com
    ggpht.com
    recaptcha.net
    .www.googletagmanager.com
    chatgpt.com
    openai.com
    oaistatic.com
    oaiusercontent.com
    oaistatsig.com
    openaimerge.com
    .cdn.workos.com
    .setup.workos.com
    .forwarder.workos.com
    workoscdn.com
    .workos.imgix.net
    .challenges.cloudflare.com
    claude.ai
    anthropic.com
    .canva.com
    .canvacode.com
    .canva-apps.com
    .canva.link
    .canva.ai
    .kemnaker.go.id
    siapkerja.kemnaker.go.id
    account.kemnaker.go.id
    skillhub.kemnaker.go.id
    karirhub.kemnaker.go.id
    talenthub.kemnaker.go.id
    wikipedia.org
    .wikipedia.org
    en.wikipedia.org
    id.wikipedia.org
    mediawiki.org
    .mediawiki.org
    wikimedia.org
    .wikimedia.org
    wmflabs.org
) do (
    set /a IDX+=1
    reg add "%POLICY_ROOT%\URLAllowlist" /v !IDX! /t REG_SZ /d "%%D" /f >nul
)

:: Matikan Secure DNS
reg add "%POLICY_ROOT%" /v DnsOverHttpsMode /t REG_SZ /d "off" /f >nul

:: Matikan Incognito / InPrivate
reg add "%POLICY_ROOT%" /v InPrivateModeAvailability /t REG_DWORD /d 1 /f >nul
reg add "%POLICY_ROOT%" /v IncognitoModeAvailability /t REG_DWORD /d 1 /f >nul

exit /b 0
