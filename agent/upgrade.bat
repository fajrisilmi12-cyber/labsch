@echo off
setlocal EnableExtensions
echo LabSCH unified upgrade (v0.4.0, single task LabSCHAgent) - existing configuration only
net session >nul 2>&1
if errorlevel 1 (
  echo ERROR: Right-click upgrade.bat and select Run as administrator.
  pause
  exit /b 1
)
pushd "%~dp0"
"%~dp0runtime\python.exe" "%~dp0upgrade.py"
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" echo Upgrade failed. Read the error above; do not start another agent manually.
pause
popd
exit /b %RESULT%
