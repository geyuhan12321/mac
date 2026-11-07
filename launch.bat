@echo off
cd /d "%~dp0"

where pythonw.exe >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw.exe "app.py"
    exit /b
)

where python.exe >nul 2>nul
if %errorlevel%==0 (
    python.exe "app.py"
    exit /b
)

echo.
echo   Python not found.
echo   Install Python 3.10+ and tick "Add python.exe to PATH", then run:
echo       python -m pip install PySide6-Essentials
echo.
pause
