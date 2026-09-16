@echo off
chcp 936 >nul
title 一箭又一箭
cd /d "%~dp0"

set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY if exist "D:\python\python.exe" set "PY=D:\python\python.exe"
if not defined PY for /f "delims=" %%i in ('where python 2^>nul') do if not defined PY set "PY=%%i"
if not defined PY goto :nopython

"%PY%" -c "import pygame" >nul 2>nul
if not errorlevel 1 goto :play

echo   正在安装依赖 pygame，请稍候 ...
"%PY%" -m pip install -r requirements.txt
"%PY%" -c "import pygame" >nul 2>nul
if errorlevel 1 goto :nodeps

:play
"%PY%" arrow_game.py
if errorlevel 1 goto :crash
exit /b 0

:nopython
echo.
echo   没有找到 Python。请先安装 Python 3.10 或更高版本，
echo   安装时记得勾选 "Add Python to PATH"。
echo.
pause
exit /b 1

:nodeps
echo.
echo   依赖 pygame 安装失败，请手动执行下面这行命令：
echo       "%PY%" -m pip install -r requirements.txt
echo.
pause
exit /b 1

:crash
echo.
echo   游戏异常退出，请把上面的报错信息截图反馈。
echo.
pause
exit /b 1
