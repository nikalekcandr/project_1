@echo off
rem Run MindForge from source (requires Python 3.10+ from python.org)
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  set "PY=py -3"
  set "PYW=pyw -3"
) else (
  set "PY=python"
  set "PYW=pythonw"
)
%PY% -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 (
  echo Failed to install dependencies. Make sure Python 3.10+ is installed: https://www.python.org/downloads/
  pause
  exit /b 1
)
start "" %PYW% main.py
