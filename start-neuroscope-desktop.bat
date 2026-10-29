@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if errorlevel 1 exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo Run setup-workbench.ps1 first. The application requires the project uv .venv.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m neuroscope_eeg.desktop.app
set "NEUROSCOPE_EXIT_CODE=%errorlevel%"
if not "%NEUROSCOPE_EXIT_CODE%"=="0" pause
exit /b %NEUROSCOPE_EXIT_CODE%
