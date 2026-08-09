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
  echo 未找到项目 .venv312、当前 conda、oi 或 omni Python 环境。
  echo 请先按 README 的 Windows 安装步骤配置环境。
  pause
  exit /b 1
)

"%NEUROSCOPE_PYTHON%" -c "import PySide6, pyqtgraph, pyedflib, pylsl, numpy, scipy" >nul 2>&1
if errorlevel 1 (
  echo 当前环境缺少桌面控制台依赖。
  echo 请执行："%NEUROSCOPE_PYTHON%" -m pip install -r requirements-desktop.txt
  pause
  exit /b 1
)

"%NEUROSCOPE_PYTHON%" -m neuroscope_eeg.desktop.app
if errorlevel 1 pause
