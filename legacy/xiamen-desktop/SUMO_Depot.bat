@echo off
cd /d "%~dp0"
start "" "%~dp0runtime\python\pythonw.exe" "%~dp0tools\run_depot_demo.py"
