@echo off
REM ---------------------------------------------------------------------------
REM  WINDROSE - double-click this file. That is the whole instruction.
REM
REM  It sets everything up the first time (a minute or two), starts the
REM  dashboard, and opens your browser. After that it just starts.
REM
REM  Windows does not need any permission fix - unlike the macOS launcher,
REM  a .bat file downloaded in a ZIP double-clicks normally. If SmartScreen
REM  shows a blue "Windows protected your PC" box, click "More info" and then
REM  "Run anyway" - that appears because this file is not code-signed.
REM ---------------------------------------------------------------------------
setlocal
cd /d "%~dp0"

echo.
echo   +----------------------------------------+
echo   ^|  WINDROSE                              ^|
echo   +----------------------------------------+
echo.

REM --- Python, checked in plain language before anything can fail loudly -----
REM "where python" also matches the Windows Store stub, which is not a usable
REM Python, so run it and look at the answer instead of trusting the path.
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)" >nul 2>nul
if errorlevel 1 goto nopython

if not exist venv (
  echo   First run - setting up. This takes a minute and happens once.
  echo.
)

REM --- Hand over to the real script. This file adds no logic of its own. -----
call start.bat
goto :eof

:nopython
echo   Windrose needs Python 3.10 or newer, and this PC does not have it yet.
echo.
echo   1. Download it here:   https://www.python.org/downloads/
echo   2. Run the installer - and on the FIRST screen, tick the box that says
echo.
echo         [x] Add python.exe to PATH
echo.
echo      It is at the bottom and it is OFF by default. It is easy to miss,
echo      and without it Windows cannot find Python afterwards.
echo   3. Finish the installer, then CLOSE this window and double-click this
echo      file again. A window that is already open keeps the old settings,
echo      so it will still say Python is missing until you open a new one.
echo.
echo   Nothing is broken and nothing has been changed on your PC.
echo.
pause
exit /b 1
