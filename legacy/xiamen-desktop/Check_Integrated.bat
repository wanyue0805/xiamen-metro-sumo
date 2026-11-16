@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\python\python.exe" -E -s -X utf8 "%~dp0tools\verify_integrated.py"
pause
