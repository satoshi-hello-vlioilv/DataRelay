@echo off
setlocal
cd /d "%~dp0"
if not exist logs mkdir logs
echo [%date% %time%] DataRelay startup > logs\startup.log
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python was not found. >> logs\startup.log
  echo Python was not found.
  pause
  exit /b 1
)
echo Python command: %PY% >> logs\startup.log
%PY% --version >> logs\startup.log 2>&1
rem requirements.txt lives under config\ (it is not in the app root).
set "REQ=requirements.txt"
if exist "config\requirements.txt" set "REQ=config\requirements.txt"
if exist "Config\requirements.txt" set "REQ=Config\requirements.txt"
rem Only Flask is required for the default Navigator API engine (same as start.vbs).
%PY% -c "import flask" >> logs\startup.log 2>&1
if errorlevel 1 (
  echo Installing packages from %REQ%... >> logs\startup.log
  %PY% -m pip install --user -r "%REQ%" >> logs\startup.log 2>&1
)
if errorlevel 1 (
  echo Package installation failed.
  start "" notepad logs\startup.log
  pause
  exit /b 1
)
start "" /min powershell -NoProfile -WindowStyle Hidden -Command "$s=(New-Object -ComObject WScript.Shell); Start-Sleep -Milliseconds 300; $s.SendKeys('% n')" >nul 2>&1
title DataRelay
rem app.py refuses to be started directly; start_app.py is the supported entry point.
echo Starting start_app.py... >> logs\startup.log
%PY% start_app.py >> logs\startup.log 2>&1
if errorlevel 1 (
  echo Application startup failed.
  start "" notepad logs\startup.log
  pause
  exit /b 1
)
