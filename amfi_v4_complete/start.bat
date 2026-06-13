@echo off
title AMFI Agent v4 - Autonomous NOC Agent
color 0A

echo.
echo ====================================================
echo   AMFI Agent v4 -- Autonomous NOC Agent
echo ====================================================
echo.

cd /d "%~dp0"

echo [1/3] Checking Python...
python --version 2>nul || (echo ERROR: Python not found && pause && exit /b 1)

echo [2/3] Checking Ollama...
curl -s http://localhost:11434/api/tags >nul 2>&1 && (
    echo   Ollama: Running
) || (
    echo   Ollama: Not running - starting...
    start "" "C:\Users\%USERNAME%\AppData\Local\Programs\Ollama\ollama.exe" serve
    timeout /t 4 /nobreak >nul
)

echo [3/3] Starting AMFI Agent...
echo.
echo   Dashboard:  http://localhost:8000
echo   API docs:   http://localhost:8000/docs
echo   Press Ctrl+C to stop
echo.

python run.py

pause
