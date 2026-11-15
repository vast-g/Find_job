@echo off
REM ==================================================================
REM  Job System - double-click launcher
REM
REM  IMPORTANT: keep this file ASCII-only.
REM  A .bat is read using the console code page (GBK on zh-CN Windows),
REM  so non-ASCII bytes here get mangled - and a mangled quote can break
REM  the whole script. All Chinese UI text lives in job.ps1 instead
REM  (saved as UTF-8 with BOM, which PowerShell 5.1 reads correctly).
REM
REM  Usage:
REM    double-click            -> interactive menu
REM    job.bat start           -> start everything
REM    job.bat stop            -> stop everything
REM    job.bat status          -> show status
REM ==================================================================

chcp 65001 >nul 2>&1
title Job System Console

set "PS1=%~dp0job.ps1"

if not exist "%PS1%" (
    echo [ERROR] job.ps1 not found next to this file:
    echo         %PS1%
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %*

REM No arguments = interactive menu (double-click). Keep the window open
REM so the user can read the result instead of it flashing away.
if "%~1"=="" pause
