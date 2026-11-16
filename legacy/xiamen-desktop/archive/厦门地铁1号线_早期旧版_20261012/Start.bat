@echo off
cd /d "%~dp0"
if not exist "logs" mkdir "logs"
if exist "runtime\python\pythonw.exe" (
 start "" "runtime\python\pythonw.exe" -E -s "app.py"
) else (
 python "app.py"
 if errorlevel 1 pause
)
