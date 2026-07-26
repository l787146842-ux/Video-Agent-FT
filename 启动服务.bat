@echo off
chcp 65001 >nul
title Flova Studio Server
cd /d "%~dp0"
echo ========================================
echo   Flova Studio - 影视创作工作台
echo ========================================
echo.
echo 正在启动服务...
echo.
python -m src.video_agent.web
pause
