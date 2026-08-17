@echo off
cd /d "%~dp0"
set "V1="
for /d %%a in ("E:\07*") do (
  for /d %%b in ("%%a\*") do if exist "%%b\main.py" set "V1=%%b"
)
echo V1=[%V1%]
set "V2="
for /d %%b in ("E:\07*\*") do if exist "%%b\main.py" set "V2=%%b"
echo V2=[%V2%]
