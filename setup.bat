@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto check_env
py -3.11 -c "import struct; assert struct.calcsize('P') == 8" >nul 2>&1
if errorlevel 1 goto use_python
py -3.11 -m venv .venv
if errorlevel 1 goto failed
goto check_env
:use_python
python -c "import sys, struct; assert sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8" >nul 2>&1
if errorlevel 1 goto missing_python
python -m venv .venv
if errorlevel 1 goto failed
:check_env
".venv\Scripts\python.exe" -c "import sys, struct; assert sys.version_info[:2] == (3, 11) and struct.calcsize('P') == 8, 'Use 64-bit Python 3.11'"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements-expert.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import torch, cv2, mss, pynput, ultralytics, watchdog, orjson; print('Imports OK. CUDA available:', torch.cuda.is_available())"
if errorlevel 1 goto failed
".venv\Scripts\python.exe" main.py --role scout-expert --help
if errorlevel 1 goto failed
echo.
echo Setup complete. Open 01-simulator.bat, then 02-cmd.bat. See README.md for details.
pause
exit /b 0
:missing_python
echo.
echo Install 64-bit Python 3.11 with the Python launcher, then run setup.bat again.
echo Python installers: https://www.python.org/downloads/windows/
pause
exit /b 1
:failed
echo.
echo Setup failed. Read the error above. Internet access is required for installation.
pause
exit /b 1
