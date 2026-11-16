@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 下载厦门 OSM 地图，完成后可离线使用。原有仿真配置会保留。
"%~dp0runtime\python\python.exe" -E -s -X utf8 "%~dp0tools\complete_map.py" %*
if errorlevel 1 (
 echo 下载或转换未完成。已有地图与仿真仍可使用，请查看上方错误。
) else (
 echo 已完成。打开 Metro.exe，点击“载入已下载的地图”。
)
pause
