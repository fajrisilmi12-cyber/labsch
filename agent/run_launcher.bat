@echo off
setlocal EnableExtensions
title LabSCH Launcher

pushd "%~dp0" >nul 2>&1

set "PY="
if exist "%ProgramFiles%\LabSCHAgent\runtime\pythonw.exe" (
    set "PY=%ProgramFiles%\LabSCHAgent\runtime\pythonw.exe"
) else if exist "%ProgramFiles%\LabSCHAgent\runtime\python.exe" (
    set "PY=%ProgramFiles%\LabSCHAgent\runtime\python.exe"
) else if exist "%~dp0runtime\pythonw.exe" (
    set "PY=%~dp0runtime\pythonw.exe"
) else if exist "%~dp0runtime\python.exe" (
    set "PY=%~dp0runtime\python.exe"
) else (
    where pythonw >nul 2>&1 && set "PY=pythonw"
    if not defined PY where python >nul 2>&1 && set "PY=python"
)

if not defined PY (
    echo ERROR: Python tidak ditemukan.
    pause
    popd >nul 2>&1
    exit /b 1
)

start "" "%PY%" "%~dp0labsch_launcher.py"
popd >nul 2>&1
exit /b 0
