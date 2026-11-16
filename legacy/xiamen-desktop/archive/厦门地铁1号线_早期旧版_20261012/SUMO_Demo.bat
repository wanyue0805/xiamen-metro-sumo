@echo off
cd /d "%~dp0"
set "SUMO_HOME=%~dp0runtime\sumo"
start "" "runtime\sumo\bin\sumo-gui.exe" -c "network\line1.sumocfg" --start --delay 30
