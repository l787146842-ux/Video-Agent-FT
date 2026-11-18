@echo off

title FTDYB Video Agent Studio
cd /d "%~dp0"
echo ========================================
echo   FTDYB Video Agent Studio
echo ========================================
echo.

REM ============================================================
REM THIS FILE MUST STAY 100% ASCII.
REM Editors re-save it as UTF-8 and corrupt any non-ASCII byte
REM (Chinese paths were destroyed twice this way). Canvas source
REM now lives inside this repo, so only %~dp0 is used at runtime.
REM ============================================================

REM Frontend artifact pre-check: dist is the main app; rebuild when missing
REM or when src/web is newer than the artifact (build failure aborts launch)
set "NEED_BUILD=0"
if not exist "static\dist\index.html" set "NEED_BUILD=1"
if exist "static\dist\index.html" for /f %%i in ('powershell -NoProfile -Command "if (@(Get-ChildItem -Path 'src/web' -Recurse -File | Where-Object { $_.LastWriteTime -gt (Get-Item 'static/dist/index.html').LastWriteTime }).Count) { 1 } else { 0 }"') do set "NEED_BUILD=%%i"
if "%NEED_BUILD%"=="1" (
  echo [build] dist missing or stale, running npm run build ...
  call npm run build
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

REM Canvas sub-app artifact pre-check: static\canvas-app is a separate React
REM bundle (served at /canvas-app/). Rebuild when missing or when the vendored
REM canvas source is newer than the artifact.
set "NEED_CANVAS_BUILD=0"
if not exist "static\canvas-app\index.html" set "NEED_CANVAS_BUILD=1"
if exist "static\canvas-app\index.html" for /f %%i in ('powershell -NoProfile -Command "if (@(Get-ChildItem -Path 'vendors/infinite-canvas/web/src' -Recurse -File | Where-Object { $_.LastWriteTime -gt (Get-Item 'static/canvas-app/index.html').LastWriteTime }).Count) { 1 } else { 0 }"') do set "NEED_CANVAS_BUILD=%%i"
if "%NEED_CANVAS_BUILD%"=="1" (
  echo [build] canvas artifact missing or stale, running npm run build:canvas ...
  call npm run build:canvas
  if errorlevel 1 (
    echo [build] npm run build:canvas exited with error - check output above
    pause
    exit /b 1
  )
  if not exist "static\canvas-app\index.html" (
    echo [build] canvas build failed, run npm run build:canvas manually then restart
    pause
    exit /b 1
  )
)

REM Kill stale process on 8080 by PID before launch (constitution 5.4):
REM prevents port conflicts and loguru rotation WinError 32 file contention.
REM taskkill failure is NOT silenced: an elevated stale process survives
REM silent kills and then blocks the new service with Errno 10048.
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8080 " ^| findstr LISTENING') do (
  echo [cleanup] killing stale process on 8080, PID %%p
  taskkill /F /PID %%p >nul 2>&1
  if errorlevel 1 echo [cleanup] FAILED to kill PID %%p - access denied. Close its window manually or run this script as Administrator
)

REM Canvas agent is built into this service (L2): no Node sidecar, no port 3000/17371.
echo [1/1] Starting Agent service (port 8080)...
set PORT=8080
start "Agent Server" cmd /c "chcp 65001 >nul & cd /d "%~dp0" && set PORT=8080 && python -m src.video_agent.web || (echo. & echo [launcher] Agent exited with error - see log above & pause)"

REM Wait for Agent
timeout /t 3 /nobreak >nul

echo.
echo Opening Studio ...
start http://localhost:8080/
echo.
echo Service started. Do not close the console window.
pause
