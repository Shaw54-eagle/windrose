@echo off
REM ---------------------------------------------------------------------------
REM Windrose - start on Windows. Double-click me.
REM First run creates a private Python environment and installs dependencies.
REM ---------------------------------------------------------------------------
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3 was not found.
  echo Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^)
  echo then run this again.
  pause
  exit /b 1
)

if not exist venv (
  echo First run - setting up Windrose. This takes a minute and happens once...
  python -m venv venv || (echo Could not create the environment. & pause & exit /b 1)
  venv\Scripts\python -m pip install --quiet --upgrade pip
)

echo Checking dependencies...
venv\Scripts\pip install --quiet -r requirements.txt || (echo Dependency install failed - check your internet. & pause & exit /b 1)

if not exist .env copy .env.example .env >nul

echo.
echo   Windrose  -^>  http://127.0.0.1:7070
echo   Leave this window open. Close it to stop.
echo.
start "" http://127.0.0.1:7070
REM For phone access on your Wi-Fi, change the next line to:  venv\Scripts\python app.py --lan
venv\Scripts\python app.py
pause
