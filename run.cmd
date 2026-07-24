@echo off
rem One-click analysis (Windows): double-click, or drag a log file onto it.
rem chcp 65001 = switch console to UTF-8 so run.py's Chinese output renders.
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [x] Not installed yet. Run install.ps1 first ^(right-click - Run with PowerShell^).
  pause
  exit /b 1
)

set "PYTHONPATH=src;vendor\Mortal\mortal;."
set "PYTHONIOENCODING=utf-8"
".venv\Scripts\python.exe" run.py %*
