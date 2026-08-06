@echo off
chcp 65001 >nul
title FTDYB + Canvas Launcher
cd /d "%~dp0"
echo ========================================
echo   FTDYB - 影视创作工作台
echo   + 画布画布联合启动
echo ========================================
echo.

REM 前端产物前置检查：dist 是唯一前端，缺失时自动补构建；
REM 前端源码（src/web）比产物新时自动重建，防止改了前端代码却还在服务旧产物（构建失败则终止，后端不再有任何回退页面）
set "NEED_BUILD=0"
if not exist "static\dist\index.html" set "NEED_BUILD=1"
if exist "static\dist\index.html" for /f %%i in ('powershell -NoProfile -Command "if (@(Get-ChildItem -Path 'src/web' -Recurse -File | Where-Object { $_.LastWriteTime -gt (Get-Item 'static/dist/index.html').LastWriteTime }).Count) { 1 } else { 0 }"') do set "NEED_BUILD=%%i"
if "%NEED_BUILD%"=="1" (
  echo [build] 前端产物缺失或源码已更新，正在执行 npm run build ...
  call npm run build
  if not exist "static\dist\index.html" (
    echo [build] 构建失败，请手动执行 npm run build 排查后重启
    pause
    exit /b 1
  )
)

REM 启动画布画布服务（端口 3000）
echo [1/2] 正在启动画布画布服务 (port 3000)...
start "Canvas Server" cmd /c "cd /d E:\07 天问\熊布 && python main.py"

REM 等待画布启动
timeout /t 3 /nobreak >nul

REM 启动本项目 Agent 服务（端口 8080）
echo [2/2] 正在启动影视 Agent 服务 (port 8080)...
set PORT=8080
start "Agent Server" cmd /c "cd /d %~dp0 && set PORT=8080 && python -m src.video_agent.web"

REM 等待 Agent 启动
timeout /t 3 /nobreak >nul

REM 打开 Studio 主页
echo.
echo 正在打开工作台...
start http://localhost:8080/
echo.
echo 服务已启动！请勿关闭弹出的两个命令行窗口。
pause
