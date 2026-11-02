@echo off
REM MAX Bot Receiver - Windows Launcher
echo Запуск MAX Bot Receiver...

REM Проверка Python
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please install Python.
    pause
    exit /b 1
)

REM Запуск с поддержкой параметров
python bot_receiver.py %*
pause
