@echo on
cd /d "%~dp0"
REM Locate the Canvas project at runtime (ASCII wildcards only).
REM Last match wins; today exactly one directory under E:\07* has main.py.
set "CANVAS_DIR="
for /d %%a in ("E:\07*") do (
  for /d %%b in ("%%a\*") do if exist "%%b\main.py" set "CANVAS_DIR=%%b"
)
if not defined CANVAS_DIR (
  echo [launcher] Canvas project not found under E:\07*\* (no main.py)
  pause
  exit /b 1
)

echo RESULT=[%CANVAS_DIR%]
