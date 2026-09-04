@echo off
REM Build LabSCHAgent.exe with server URL and API token embedded.
REM Usage:
REM   build.bat
REM   build.bat --server https://abc.trycloudflare.com --token YOUR_TOKEN

setlocal

echo === LabSCHAgent Windows Build (with embedded config) ===
echo.

REM Parse args
set "SERVER_URL=https://labsch-api.<your-subdomain>.workers.dev"
set "API_TOKEN=<your-uuid-token>"
set "CLIENT_ID="

:parse_args
if "%~1"=="" goto :done_parsing
if /i "%~1"=="--server" (
    set "SERVER_URL=%~2"
    shift
    shift
    goto :parse_args
)
if /i "%~1"=="--token" (
    set "API_TOKEN=<your-uuid-token>"
    shift
    shift
    goto :parse_args
)
if /i "%~1"=="--client-id" (
    set "CLIENT_ID=%~2"
    shift
    shift
    goto :parse_args
)
shift
goto :parse_args

:done_parsing

if "%API_TOKEN%"=="" (
    echo WARNING: No --token provided. Agent will require --setup on first run.
    echo.
)

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Python not found. Install Python 3.12+ first.
    exit /b 1
)

REM Create venv
if not exist "venv" (
    echo Creating venv...
    python -m venv venv
)

call venv\Scripts\activate.bat

REM Install deps
echo Installing dependencies...
pip install --quiet pyinstaller psutil requests

REM Generate config.ini for the bundle
echo.
echo Generating config.ini with embedded values...
if not exist "C:\ProgramData\LabSCHAgent" mkdir "C:\ProgramData\LabSCHAgent"
(
    echo {
    echo   "server_url": "%SERVER_URL%",
    echo   "api_token": "%API_TOKEN%",
    echo   "client_id": "%CLIENT_ID%",
    echo   "version": "0.1.0"
    echo }
) > "C:\ProgramData\LabSCHAgent\config.ini"

echo Config:
type "C:\ProgramData\LabSCHAgent\config.ini"
echo.

REM Build
echo Building LabSCHAgent.exe...
pyinstaller --onefile --name LabSCHAgent ^
    --hidden-import=psutil ^
    --add-data "config_sync.py;." ^
    --add-data "app_blocker.py;." ^
    --add-data "website_blocker.py;." ^
    labsch_agent.py

if errorlevel 1 (
    echo Build FAILED.
    exit /b 1
)

echo.
echo === Build complete ===
echo Output: dist\LabSCHAgent.exe
echo.
echo Embedded config:
echo   server_url: %SERVER_URL%
echo   api_token:  %API_TOKEN:~0,8%...
echo   client_id:  %CLIENT_ID%^(auto if empty^)
echo.
echo Next steps:
echo   1. Copy dist\LabSCHAgent.exe to target PCs
echo   2. Run as admin: LabSCHAgent.exe
echo   3. Or install as service: LabSCHAgent.exe --install-service
endlocal
