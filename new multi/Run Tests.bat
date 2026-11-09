@echo off
cd /d "%~dp0"
where py >nul 2>nul && (py -3 -m unittest discover -s tests & py -3 -m tapquest --soak 24) || (python -m unittest discover -s tests & python -m tapquest --soak 24)
pause
