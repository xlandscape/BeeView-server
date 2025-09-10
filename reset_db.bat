@echo off
REM Database Reset Helper Script for Windows

echo 🗄️  Database Reset Configuration
echo ==================================

REM Check current setting
if "%RESET_DATABASE%"=="true" (
    echo Current setting: RESET_DATABASE=true (Database will be completely reset on startup)
) else (
    echo Current setting: RESET_DATABASE=false (Only data will be cleared, tables kept)
)

echo.
echo Options:
echo 1. Enable complete database reset (drop all tables)
echo 2. Disable complete database reset (keep table structure)
echo 3. Start server with current setting
echo 4. Exit

set /p choice="Choose option (1-4): "

if "%choice%"=="1" (
    set RESET_DATABASE=true
    echo ✅ Set RESET_DATABASE=true
    echo 🚀 Starting server with complete database reset...
    uvicorn main:app --reload --port 8000
) else if "%choice%"=="2" (
    set RESET_DATABASE=false
    echo ✅ Set RESET_DATABASE=false
    echo 🚀 Starting server with data clearing only...
    uvicorn main:app --reload --port 8000
) else if "%choice%"=="3" (
    echo 🚀 Starting server with current setting...
    uvicorn main:app --reload --port 8000
) else if "%choice%"=="4" (
    echo 👋 Goodbye!
    exit /b 0
) else (
    echo ❌ Invalid option
    exit /b 1
)
