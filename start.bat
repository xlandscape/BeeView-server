@echo off
REM ============================================================
REM BeeView – start the server and open the browser
REM ============================================================
setlocal

cd /d "%~dp0"

REM --- Check venv exists ------------------------------------------------------
if not exist "venv\Scripts\activate.bat" (
    echo ERROR: Virtual environment not found. Run setup.bat first.
    pause
    exit /b 1
)

REM --- Check data exists ------------------------------------------------------
if not exist "data\beeview.duckdb" (
    echo ERROR: Database not found at data\beeview.duckdb
    echo Make sure the data folder was copied correctly.
    pause
    exit /b 1
)

REM --- Activate and start -----------------------------------------------------
call venv\Scripts\activate.bat

echo Starting BeeView on http://localhost:32000 ...
echo Press Ctrl+C to stop.
echo.

REM Open browser after a short delay
start "" cmd /c "timeout /t 3 /nobreak >nul & start http://localhost:32000"

python main.py
