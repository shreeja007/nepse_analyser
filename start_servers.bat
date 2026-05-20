@echo off
echo NEPSE API Server Starter
echo ========================

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

echo Starting NEPSE API servers...
echo.

REM Start the Python script
python start_servers.py

echo.
echo Servers stopped.
pause
