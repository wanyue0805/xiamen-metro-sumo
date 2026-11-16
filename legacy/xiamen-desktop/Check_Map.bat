@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0runtime\python\python.exe" -E -s -X utf8 "%~dp0tools\check_map.py"
pause
