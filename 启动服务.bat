@echo off
title FTDYB + Canvas Launcher
cd /d "%~dp0"
echo ========================================
echo   FTDYB Video Agent Studio
echo   + Canvas Launcher
echo ========================================
echo.

REM ============================================================
REM THIS FILE MUST STAY 100% ASCII.
REM Editors re-save it as UTF-8 and corrupt any non-ASCII byte
REM (Chinese paths were destroyed twice this way). The Canvas
REM directory is therefore discovered at runtime via ASCII
REM wildcards below - never hardcode non-ASCII paths here.
REM ============================================================

REM Frontend artifact pre-check: dist is the only frontend; rebuild when missing
REM or when src/web is newer than the artifact (build failure aborts launch)
set "NEED_BUILD=0"
if not exist "static\dist\index.html" set "NEED_BUILD=1"
if exist "static\dist\index.html" for /f %%i in ('powershell -NoProfile -Command "if (@(Get-ChildItem -Path 'src/web' -Recurse -File | Where-Object { $_.LastWriteTime -gt (Get-Item 'static/dist/index.html').LastWriteTime }).Count) { 1 } else { 0 }"') do set "NEED_BUILD=%%i"
if "%NEED_BUILD%"=="1" (
  echo [build] dist missing or stale, running npm run build ...
  call npm run build
  REM errorlevel check: npm run build now chains vite build + size-budget gate;
  REM the size gate can fail AFTER dist/index.html is written, so the old
  REM "if not exist" probe alone cannot catch a failed build.
  if errorlevel 1 (
    echo [build] npm run build exited with error - check output above
    pause
    exit /b 1
  )
  if not exist "static\dist\index.html" (
    echo [build] build failed, run npm run build manually then restart
    pause
    exit /b 1
  )
)

REM Kill stale processes on 8080/3000 by PID before launch (constitution 5.4):
REM prevents port conflicts and loguru rotation WinError 32 file contention.
REM taskkill failure is NOT silenced: an elevated stale process survives
REM silent kills and then blocks the new service with Errno 10048.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8080 " ^| findstr LISTENING') do (
  echo [cleanup] killing stale process on 8080, PID %%p
  taskkill /F /PID %%p >nul 2>&1
  if errorlevel 1 echo [cleanup] FAILED to kill PID %%p - access denied. Close its window manually or run this script as Administrator
)
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000 " ^| findstr LISTENING') do (
  echo [cleanup] killing stale process on 3000, PID %%p
  taskkill /F /PID %%p >nul 2>&1
  if errorlevel 1 echo [cleanup] FAILED to kill PID %%p - access denied. Close its window manually or run this script as Administrator
)

REM Locate the Canvas project at runtime (ASCII wildcards only).
REM Last match wins; today exactly one directory under E:\07* has main.py.
set "CANVAS_DIR="
for /d %%a in ("E:\07*") do (
  for /d %%b in ("%%a\*") do if exist "%%b\main.py" set "CANVAS_DIR=%%b"
)
REM NEVER put unescaped ( ) inside echo text within a ( ) block: a literal
REM ) closes the block early, and the pause/exit below then execute
REM UNCONDITIONALLY - the launcher dies even when discovery succeeded.
if not defined CANVAS_DIR (
  echo [launcher] Canvas project not found under E:\07*\* - no main.py
  pause
  exit /b 1
)

REM Start Canvas service (port 3000); child window keeps open on crash
echo [1/2] Starting Canvas service (port 3000)...
start "Canvas Server" cmd /c "chcp 65001 >nul & cd /d %CANVAS_DIR% && python main.py || (echo. & echo [launcher] Canvas exited with error - see log above & pause)"

REM Wait for Canvas
timeout /t 3 /nobreak >nul

REM Start Agent service (port 8080); child window keeps open on crash
echo [2/2] Starting Agent service (port 8080)...
set PORT=8080
start "Agent Server" cmd /c "chcp 65001 >nul & cd /d %~dp0 && set PORT=8080 && python -m src.video_agent.web || (echo. & echo [launcher] Agent exited with error - see log above & pause)"

REM Wait for Agent
timeout /t 3 /nobreak >nul

REM Open Studio
echo.
echo Opening Studio ...
start http://localhost:8080/
echo.
echo Services started. Do not close the two console windows.
pause
