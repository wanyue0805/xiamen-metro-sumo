"""Double-click entry for the independent OSM inspection scenario."""
from pathlib import Path
import sys,subprocess,ctypes
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
try:
    from network_engine import sumo_working_root
    working=sumo_working_root()
    if not (ROOT/'maps/osm/xiamen.osm.sumocfg').exists():
        raise FileNotFoundError('请先双击 Download_Map.bat 下载并转换地图。')
    subprocess.Popen([str(working/'runtime/sumo/bin/sumo-gui.exe'),'-c','maps/osm/xiamen.osm.sumocfg'],cwd=working)
except Exception as exc:
    ctypes.windll.user32.MessageBoxW(None,str(exc),'厦门真实地图',0x10)
