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
REM directories are therefore discovered at runtime via ASCII
REM wildcards below - never hardcode non-ASCII paths here.
REM ============================================================
REM The launcher always starts the infinite-canvas stack
REM (canvas-agent + web dev server + Agent backend).

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

REM ============================================================
REM infinite-canvas stack
REM ============================================================

REM --- canvas-agent (port 17371) ---
REM Launch the locked 0.6.0 package straight from the npx cache with node.
REM NEVER call npx here: on this machine its download step can hang 10+
REM minutes. The cache path below is pure ASCII and may stay hardcoded.
set "CANVAS_AGENT_JS=C:\Users\ASUS\AppData\Local\npm-cache\_npx\9a1dd9a4da0bffe2\node_modules\@basketikun\canvas-agent\dist\index.js"
netstat -ano | findstr ":17371 " | findstr LISTENING >nul 2>&1
if not errorlevel 1 (
  echo [launcher] canvas-agent already listening on 17371 - skip launch
  goto CANVAS_SITE_FLOW
)
if not exist "%CANVAS_AGENT_JS%" (
  echo [launcher] canvas-agent cache NOT found:
  echo   %CANVAS_AGENT_JS%
  echo [launcher] start it manually in another terminal, then rerun or connect by hand:
  echo   npx -y @basketikun/canvas-agent@0.6.0
  goto CANVAS_SITE_FLOW
)
echo [1/3] Starting canvas-agent (port 17371)...
start "Canvas Agent" cmd /c "node "%CANVAS_AGENT_JS%" || (echo. & echo [launcher] canvas-agent exited with error - see log above & pause)"

:CANVAS_SITE_FLOW
REM --- infinite-canvas web dev server (port 3000) ---
REM The repo lives outside this workspace in a non-ASCII directory;
REM discover it at runtime via ASCII wildcards: E:\09*\*\web
set "IC_WEB_DIR="
for /d %%a in ("E:\09*") do (
  for /d %%b in ("%%a\*") do if exist "%%b\web\package.json" set "IC_WEB_DIR=%%b\web"
)
if not defined IC_WEB_DIR (
  echo [launcher] infinite-canvas web dir not found under E:\09*\*\web - no web\package.json
  echo [launcher] start it manually: npm run dev inside the infinite-canvas web folder
  goto START_AGENT_FLOW
)
echo [2/3] Starting infinite-canvas web dev server (port 3000)...
start "Infinite Canvas Web" cmd /c "chcp 65001 >nul & cd /d "%IC_WEB_DIR%" && npm run dev || (echo. & echo [launcher] infinite-canvas web exited with error - see log above & pause)"
timeout /t 3 /nobreak >nul
goto START_AGENT_FLOW

:START_AGENT_FLOW
REM Start Agent service (port 8080); child window keeps open on crash.
echo [3/3] Starting Agent service (port 8080)...
set PORT=8080
start "Agent Server" cmd /c "chcp 65001 >nul & cd /d "%~dp0" && set PORT=8080 && python -m src.video_agent.web || (echo. & echo [launcher] Agent exited with error - see log above & pause)"

REM Wait for Agent
timeout /t 3 /nobreak >nul

REM Open Studio
echo.
echo Opening Studio ...
start http://localhost:8080/
echo.
echo Services started. Do not close the console windows.
pause
