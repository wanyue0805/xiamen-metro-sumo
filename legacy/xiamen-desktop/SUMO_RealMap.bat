@echo off
cd /d "%~dp0"
start "" "%~dp0runtime\python\pythonw.exe" -E -s "%~dp0tools\open_real_map.py"
