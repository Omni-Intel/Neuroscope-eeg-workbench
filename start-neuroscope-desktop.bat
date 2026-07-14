@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "NEUROSCOPE_PYTHON="
if exist ".venv312\Scripts\python.exe" set "NEUROSCOPE_PYTHON=.venv312\Scripts\python.exe"
if not defined NEUROSCOPE_PYTHON if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "NEUROSCOPE_PYTHON=%CONDA_PREFIX%\python.exe"
if not defined NEUROSCOPE_PYTHON if exist "D:\ProgramData\miniconda3\envs\oi\python.exe" set "NEUROSCOPE_PYTHON=D:\ProgramData\miniconda3\envs\oi\python.exe"
if not defined NEUROSCOPE_PYTHON if exist "C:\ProgramData\miniconda3\envs\oi\python.exe" set "NEUROSCOPE_PYTHON=C:\ProgramData\miniconda3\envs\oi\python.exe"
if not defined NEUROSCOPE_PYTHON if exist "D:\ProgramData\miniconda3\envs\omni\python.exe" set "NEUROSCOPE_PYTHON=D:\ProgramData\miniconda3\envs\omni\python.exe"
if not defined NEUROSCOPE_PYTHON if exist "C:\ProgramData\miniconda3\envs\omni\python.exe" set "NEUROSCOPE_PYTHON=C:\ProgramData\miniconda3\envs\omni\python.exe"

if not defined NEUROSCOPE_PYTHON (
  echo No project .venv312, active conda, oi, or omni Python environment was found.
  echo Follow the Windows setup steps in README.md first.
  pause
  exit /b 1
)

"%NEUROSCOPE_PYTHON%" -c "import PySide6, pyqtgraph, pyedflib, numpy, scipy" >nul 2>&1
if errorlevel 1 (
  echo Desktop dependencies are missing.
  echo Run: "%NEUROSCOPE_PYTHON%" -m pip install -r requirements-desktop.txt
  pause
  exit /b 1
)

"%NEUROSCOPE_PYTHON%" -m neuroscope_eeg.desktop.app
if errorlevel 1 pause
