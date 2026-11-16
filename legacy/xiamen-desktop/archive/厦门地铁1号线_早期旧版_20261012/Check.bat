@echo off
cd /d "%~dp0"
"runtime\python\python.exe" "self_test.py"
pause
