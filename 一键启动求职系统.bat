@echo off
title Job System One-Click Start

echo ============================================
echo   Job System - starting backend services
echo ============================================
echo.

echo [1/5] MySQL (service MySQL9)...
net start MySQL9 >nul 2>&1

echo [2/5] Redis...
tasklist /fi "imagename eq redis-server.exe" | find /i "redis-server.exe" >nul || start "redis" /min "D:\develop_software\Redis-x64-3.2.100\redis-server.exe"

echo [3/5] Ollama...
powershell -NoProfile -Command "if (-not (Get-Process ollama -ErrorAction SilentlyContinue)) { Start-Process ollama -ArgumentList 'serve' -WindowStyle Minimized }"

echo [4/5] Python Agent (port 8000)...
start "python-agent" cmd /k "cd /d %~dp0job-agent && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000"

echo [5/5] Java backend (port 8080)...
start "java-backend" cmd /k "cd /d %~dp0job-platform && mvn -pl job-server -am -DskipTests install && mvn -pl job-server spring-boot:run"

echo.
echo Done. Wait for the two new windows to finish loading,
echo then open WeChat DevTools and import job-miniprogram.
echo.
pause
