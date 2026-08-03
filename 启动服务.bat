@echo off
chcp 65001 >nul
title FTDYB + Canvas Launcher
cd /d "%~dp0"
echo ========================================
echo   FTDYB - 影视创作工作台
echo   + 熊布画布联合启动
echo ========================================
echo.

REM 启动熊布画布服务（端口 3000）
echo [1/2] 正在启动熊布画布服务 (port 3000)...
start "Canvas Server" cmd /c "cd /d E:\07 天问\熊布 && python main.py"

REM 等待熊布启动
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
