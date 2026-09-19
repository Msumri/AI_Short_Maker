@echo off

title AI Video Cutter

if not exist ".venv\Scripts\activate.bat" (
    echo.
    echo ERROR: Virtual environment was not found.
    echo.
    echo Please run install_windows.bat first.
    echo.
    pause
    exit /b 1
)

call ".venv\Scripts\activate.bat"

python app.py

pause