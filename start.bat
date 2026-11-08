@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Download it from https://www.python.org/downloads/
  echo During setup, tick "Add python.exe to PATH", then run this file again.
  pause
  exit /b
)
start "" cmd /c "timeout /t 2 >nul & start http://localhost:8000"
echo Shelfwise is running at http://localhost:8000  (close this window to stop it)
python server.py
pause
