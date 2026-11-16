@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0logs" mkdir "%~dp0logs"
if exist "%~dp0Metro.exe" (
 start "" "%~dp0Metro.exe"
 exit /b
)
if exist "%~dp0runtime\python\pythonw.exe" (
 start "" "%~dp0runtime\python\pythonw.exe" -E -s "%~dp0launch.py"
 exit /b
)
echo Missing portable runtime. Keep the entire project folder together.
pause
