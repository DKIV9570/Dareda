@echo off
rem dareda graphical interface (Windows): double-click.
chcp 65001 >nul
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo [x] Not installed yet. Run install.ps1 first.
  pause
  exit /b 1
)

set "PYTHONPATH=src;vendor\Mortal\mortal;."
set "PYTHONIOENCODING=utf-8"
rem pythonw = no console window behind the GUI
start "" ".venv\Scripts\pythonw.exe" gui.py
