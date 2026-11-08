@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" -u run_experiment.py
set "ONR_SESSION_EXIT=%errorlevel%"
pause
exit /b %ONR_SESSION_EXIT%
:missing
echo The Python environment is missing. Run setup.bat once in this folder.
pause
exit /b 1
