@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\python\python.exe" -X utf8 -E -s "%~dp0self_test.py"
pause
