@echo off
setlocal

title AI Video Cutter - Windows Installer

echo.
echo ==========================================
echo       AI Video Cutter Installer
echo ==========================================
echo.

REM ============================================================
REM CHECK PYTHON
REM ============================================================

echo [1/5] Checking Python...
echo.

where python >nul 2>&1

if errorlevel 1 (
    echo ERROR: Python was not found.
    echo.
    echo Please install Python 3.11 or newer.
    echo Make sure "Add Python to PATH" is enabled.
    echo.
    pause
    exit /b 1
)

python --version

if errorlevel 1 (
    echo.
    echo ERROR: Python could not be started.
    echo.
    pause
    exit /b 1
)

echo.
echo Python found.
echo.


REM ============================================================
REM CREATE VIRTUAL ENVIRONMENT
REM ============================================================

echo [2/5] Creating virtual environment...
echo.

if not exist ".venv" (
    python -m venv .venv

    if errorlevel 1 (
        echo.
        echo ERROR: Could not create the virtual environment.
        echo.
        pause
        exit /b 1
    )

    echo Virtual environment created.
) else (
    echo Virtual environment already exists.
)

echo.


REM ============================================================
REM ACTIVATE VIRTUAL ENVIRONMENT
REM ============================================================

echo [3/5] Activating virtual environment...
echo.

call ".venv\Scripts\activate.bat"

if errorlevel 1 (
    echo.
    echo ERROR: Could not activate the virtual environment.
    echo.
    pause
    exit /b 1
)

echo Virtual environment activated.
echo.


REM ============================================================
REM INSTALL PYTHON DEPENDENCIES
REM ============================================================

echo [4/5] Installing Python dependencies...
echo.

python -m pip install --upgrade pip

if errorlevel 1 (
    echo.
    echo ERROR: Could not upgrade pip.
    echo.
    pause
    exit /b 1
)

python -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo ERROR: Could not install Python dependencies.
    echo.
    pause
    exit /b 1
)

echo.
echo Python dependencies installed.
echo.


REM ============================================================
REM CHECK / INSTALL FFMPEG
REM ============================================================

echo [5/5] Checking FFmpeg...
echo.

where ffmpeg >nul 2>&1

if not errorlevel 1 (
    echo FFmpeg is already installed.
    echo.
    goto FFMPEG_DONE
)

echo FFmpeg was not found.
echo.

REM Check for winget

where winget >nul 2>&1

if errorlevel 1 (
    echo ERROR: Windows Package Manager ^(winget^) was not found.
    echo.
    echo FFmpeg must be installed manually.
    echo.
    echo Download FFmpeg from:
    echo https://ffmpeg.org/download.html
    echo.
    pause
    exit /b 1
)

echo Installing FFmpeg using winget...
echo.
echo This may take a few minutes.
echo.

winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements

if errorlevel 1 (
    echo.
    echo ERROR: FFmpeg installation failed.
    echo.
    pause
    exit /b 1
)

echo.
echo FFmpeg installation completed.
echo.

:FFMPEG_DONE

REM ============================================================
REM FINISHED
REM ============================================================

echo.
echo ==========================================
echo       Installation Complete!
echo ==========================================
echo.
echo The AI Video Cutter is ready.
echo.
echo To start the application, run:
echo.
echo     run_windows.bat
echo.
echo Or manually run:
echo.
echo     .venv\Scripts\activate
echo     python app.py
echo.
echo NOTE:
echo If FFmpeg was just installed, you may need to
echo close and reopen your terminal before Windows
echo recognizes the new FFmpeg PATH.
echo.

pause