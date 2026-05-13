@echo off
REM ============================================================
REM Package BeeView for xcopy deployment to another machine
REM Creates: BeeView-portable\ folder ready to copy/zip
REM ============================================================
setlocal

cd /d "%~dp0"

set DEST=BeeView-portable

echo === Packaging BeeView for distribution ===
echo Output: %DEST%\
echo.

REM --- Clean previous build ---------------------------------------------------
if exist "%DEST%" (
    echo Removing previous %DEST%\ ...
    rmdir /s /q "%DEST%"
)
mkdir "%DEST%"

REM --- Server source files ----------------------------------------------------
echo Copying server files...
copy /y *.py "%DEST%\" >nul
copy /y requirements.txt "%DEST%\" >nul
copy /y setup.bat "%DEST%\" >nul
copy /y start.bat "%DEST%\" >nul

REM --- Data folder (DB + shapefiles, no huge HDF5 by default) -----------------
echo Copying data...
mkdir "%DEST%\data"
if exist "data\beeview.duckdb"                     copy /y "data\beeview.duckdb" "%DEST%\data\" >nul
if exist "data\vegetation classes.json"             copy /y "data\vegetation classes.json" "%DEST%\data\" >nul
if exist "data\land cover to vegetation default mapping.csv" copy /y "data\land cover to vegetation default mapping.csv" "%DEST%\data\" >nul

REM Copy shapefile components
for %%e in (shp dbf prj shx cpg) do (
    if exist "data\lulc.%%e" copy /y "data\lulc.%%e" "%DEST%\data\" >nul
)

REM Copy HDF5 (large but needed)
if exist "data\arr.dat" (
    echo Copying arr.dat ^(this may take a moment^)...
    copy /y "data\arr.dat" "%DEST%\data\" >nul
)

REM --- Frontend (pre-built) ---------------------------------------------------
echo Copying frontend...
xcopy /s /e /i /q "frontend" "%DEST%\frontend" >nul

REM --- Summary ----------------------------------------------------------------
echo.
echo === Package complete ===
echo.
echo Contents of %DEST%\:
dir /b "%DEST%"
echo.
echo To deploy on another Windows machine:
echo   1. Copy the %DEST%\ folder to the target machine
echo   2. Install Python 3.11+ (https://python.org, check "Add to PATH")
echo   3. Run setup.bat  (one time — creates venv, installs deps)
echo   4. Run start.bat  (opens BeeView at http://localhost:32000)
echo.
pause
