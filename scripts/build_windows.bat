@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo   Artale EXP Calculator - Windows Standalone Build
echo ========================================================

REM Step 1: Check Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found on PATH. Please install Python 3.10+
    exit /b 1
)

REM Step 2: Check PyInstaller
python -c "import PyInstaller" >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [INFO] PyInstaller not found. Installing pyinstaller...
    pip install pyinstaller
)

REM Step 3: Run build orchestrator
python "%~dp0build_app.py" %*

if %ERRORLEVEL% equ 0 (
    echo.
    echo [BUILD COMPLETED SUCCESSFULLY]
    echo Output directory: dist\ArtaleExpCalculator\
) else (
    echo.
    echo [BUILD FAILED with error code %ERRORLEVEL%]
)

exit /b %ERRORLEVEL%
