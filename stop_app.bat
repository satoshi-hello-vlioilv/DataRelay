@echo off
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python was not found.
  pause
  exit /b 1
)
%PY% process_manager.py
pause
