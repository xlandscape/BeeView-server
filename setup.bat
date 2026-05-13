@echo off
REM ============================================================
REM BeeView – one-time setup (run once on a new machine)
REM Requires: Python 3.11+ on PATH
REM ============================================================
setlocal

cd /d "%~dp0"

echo === BeeView Setup ===
echo.

REM --- Check Python -----------------------------------------------------------
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python not found on PATH.
    echo Install Python 3.11+ from https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo Found: %%v
echo.

REM --- Create virtual environment ---------------------------------------------
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
    if %ERRORLEVEL% neq 0 (
        echo ERROR: Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo Virtual environment created.
) else (
    echo Virtual environment already exists.
)
echo.

REM --- Install dependencies ---------------------------------------------------
echo Installing dependencies...
call venv\Scripts\activate.bat
pip install --upgrade pip >nul 2>&1
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)
echo.
echo === Setup complete ===
echo Run start.bat to launch BeeView.
pause
