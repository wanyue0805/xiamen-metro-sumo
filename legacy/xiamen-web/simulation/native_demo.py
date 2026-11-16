"""Portable entry for standalone native SUMO demonstrations."""
import os,sys,subprocess,traceback,time
from network_engine import ROOT,sumo_working_root,NetworkEngine
try:
 line=sys.argv[1] if len(sys.argv)>1 else 'network'
 if line not in ('network','1','2','3','4','6'):raise ValueError('未知线路')
 working=sumo_working_root();os.chdir(working);os.environ['SUMO_HOME']=str(working/'runtime/sumo')
 if line=='network' and (ROOT/'network/multimodal.sumocfg').exists():
  engine=NetworkEngine()
  try:
   engine.start_all(gui=True)
   if engine.mobility:
    engine.mobility.start_buses();engine.mobility.set_demand_enabled(True)
    communities=[r['community_name'] for r in engine.mobility.routes.values()]
    engine.mobility.add_group(communities[0],communities[1],60)
   while engine.conn:
    try:engine.step()
    except Exception as exc:
     import traci
     if isinstance(exc,traci.exceptions.FatalTraCIError):break
     raise
    time.sleep(.02)
  finally:engine.close()
  sys.exit(0)
 config='network/unified.demo.sumocfg' if line=='network' else f'network/line{line}.sumocfg'
 command=['runtime/sumo/bin/sumo-gui.exe','-c',config,'--start','--delay','30']
 if (ROOT/'network/multimodal.view.xml').exists():command+=['--gui-settings-file','network/multimodal.view.xml']
 subprocess.Popen(command,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
except Exception:
 (ROOT/'logs').mkdir(exist_ok=True);(ROOT/'logs/native-startup.log').write_text(traceback.format_exc(),encoding='utf-8')
 import ctypes
 ctypes.windll.user32.MessageBoxW(None,'原生轨道窗口启动失败。请查看 logs/native-startup.log。','厦门地铁 · 启动提示',0x10)
