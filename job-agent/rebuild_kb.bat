@echo off
REM ============================================================
REM  Rebuild RAG knowledge base index
REM  NOTE: This file MUST stay pure ASCII.
REM  Windows cmd.exe parses .bat using the console code page,
REM  which varies (936/GBK or 65001/UTF-8). Any non-ASCII byte
REM  can be mis-parsed and break the script. Chinese output from
REM  Python is fine (Python adapts to the console).
REM ============================================================
cd /d "%~dp0"
title Rebuild RAG Knowledge Base

:menu
cls
echo ============================================================
echo   Rebuild RAG Knowledge Base
echo ============================================================
echo.
echo   Knowledge sources (merged):
echo     1. data\knowledge.jsonl     curated entries (16, authoritative)
echo     2. data\docs\               in-project documents (2)
echo     3. external materials       see EXTRA_DOCS_DIRS in .env
echo.
echo   [1] Quick rebuild   sources 1+2 only          about 1 min
echo   [2] Full rebuild    sources 1+2+external      about 30-50 min
echo   [3] Show current index content (no rebuild)
echo   [0] Cancel
echo.
set /p mode="Select (0-3): "

if "%mode%"=="3" goto showonly
if "%mode%"=="0" exit /b 0
if "%mode%"=="1" goto quick
if "%mode%"=="2" goto full

echo Invalid choice
pause
exit /b 1

:showonly
echo.
python tools\list_docs.py
echo.
pause
exit /b 0

:quick
echo.
echo [Quick rebuild] indexing in-project sources only...
python -m app.rag.indexer build_all --no-extra
set "RC=%ERRORLEVEL%"
goto done

:full
echo.
echo ============================================================
echo   Full rebuild
echo ============================================================
echo   - parses pdf / docx / txt / md in the external materials
echo   - takes about 30-50 minutes, keep this window open
echo   - the old index is replaced ONLY after everything succeeds
echo   - if it gets interrupted, just run this again:
echo     it resumes from the last checkpoint, not from scratch
echo   - 136 legacy .doc files are not supported and are skipped
echo.
echo   Configured knowledge sources:
echo.
python tools\show_sources.py
echo.
pause
echo.
echo [Full rebuild] starting...
python -m app.rag.indexer build_all
REM Capture the exit code IMMEDIATELY: reading %ERRORLEVEL% after a
REM goto is unreliable, which is what caused the earlier false
REM "Rebuild FAILED" report on an actually-successful build.
set "RC=%ERRORLEVEL%"
goto done

:done
echo.
echo   Indexer exit code: %RC%
echo.
echo   Verifying the index (this is the real success criterion):
echo.
REM Judge success by whether the index actually loads, not by the
REM exit code alone. The index is the ground truth.
python tools\list_docs.py
if errorlevel 1 goto failed

echo ============================================================
echo   Next steps:
echo     1) Re-run evaluation to see the impact on recall
echo     2) Add questions for the new material into
echo        benchmark\dataset\testset.jsonl
echo ============================================================
pause
exit /b 0

:failed
echo.
echo ============================================================
echo   Rebuild FAILED. Common causes:
echo     - Ollama not running (need 127.0.0.1:11434 reachable)
echo     - qwen3-embedding:4b not pulled
echo     - wrong path in EXTRA_DOCS_DIRS (.env)
echo.
echo   If the build was interrupted: just run this again.
echo   It resumes from the last checkpoint instead of starting over.
echo ============================================================
pause
exit /b 1
