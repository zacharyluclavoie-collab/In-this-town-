@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m tapquest %*) || (python -m tapquest %*)
if errorlevel 1 (
  echo.
  echo Could not start. Install Python 3.10+ from python.org ^(tick "Add python.exe to PATH"^) and try again.
  pause
)
