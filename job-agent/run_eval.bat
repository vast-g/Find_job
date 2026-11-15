@echo off
REM ============================================================
REM  Job Agent - Evaluation Center
REM  NOTE: This file is intentionally ASCII-only.
REM  Windows cmd.exe parses .bat files using the console code page,
REM  which varies by environment (936/GBK or 65001/UTF-8). Any
REM  non-ASCII byte in a .bat can be mis-parsed and turn into
REM  "not recognized as an internal or external command".
REM  Chinese output still works: Python adapts to the console.
REM ============================================================
cd /d "%~dp0"
title Job Agent - Evaluation Center

:menu
cls
echo ============================================================
echo   Job Agent - Evaluation Center
echo ============================================================
echo.
echo   [ SETUP ]
echo   [1] Environment check        (seconds, no model calls)
echo   [2] Judge self-test          (seconds, 2 API calls)
echo   [3] Offline pipeline test    (no model calls)
echo   [4] Validate dataset         (no model calls)
echo   [C] Rebuild knowledge base   (required after adding docs)
echo.
echo   [ RUN ]
echo   [5] Smoke run 3 cases        (no judge, about 1 min)
echo   [6] Run 10 cases             (with judge, 5-10 min)
echo   [7] Run all 75 cases         (with judge)
echo.
echo   [ TWO-PHASE MODE - recommended for full runs ]
echo   [E] Execute all cases, NO judge   (saves runs for reuse)
echo   [J] Judge ONLY, reuse saved runs  (no agent cost)
echo.
echo   [ RESULTS ]
echo   [8] Regenerate report
echo   [9] Mine bad cases + update regression set
echo   [A] Set current result as baseline
echo   [B] Regression gate
echo.
echo   [0] Exit
echo.
set /p mode="Select: "

if /i "%mode%"=="1" python -m benchmark.cli check
if /i "%mode%"=="2" python -m benchmark.cli judge-test
if /i "%mode%"=="3" python tools\selftest_pipeline.py
if /i "%mode%"=="4" python tools\validate_dataset.py
if /i "%mode%"=="C" call "%~dp0rebuild_kb.bat"
if /i "%mode%"=="5" python -m benchmark.cli run --limit 3 --no-judge --verbose
if /i "%mode%"=="6" python -m benchmark.cli run --limit 10
if /i "%mode%"=="7" python -m benchmark.cli run --all
if /i "%mode%"=="E" python -m benchmark.cli run --all --no-judge
if /i "%mode%"=="J" python -m benchmark.cli run --all --reuse-runs
if /i "%mode%"=="8" python -m benchmark.cli report
if /i "%mode%"=="9" python -m benchmark.cli mine
if /i "%mode%"=="A" python -m benchmark.cli baseline
if /i "%mode%"=="B" python -m benchmark.cli gate
if /i "%mode%"=="0" exit /b 0

echo.
echo ============================================================
echo   Done. Outputs: benchmark\reports\  benchmark\bad_cases\
echo ============================================================
echo.
pause
goto menu
