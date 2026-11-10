@echo off
setlocal
if not exist "%~dp0simulator\ONR Scuba.exe" goto missing
cd /d "%~dp0simulator"
start "" "%~dp0simulator\ONR Scuba.exe"
exit /b 0
:missing
echo Simulator is missing. Place the supplied build in the simulator folder.
pause
exit /b 1
