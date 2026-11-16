@echo off
cd /d "%~dp0"
"%~dp0runtime\python\python.exe" -E -s "%~dp0launch.py"
echo Startup log: %~dp0logs\startup.log
pause
