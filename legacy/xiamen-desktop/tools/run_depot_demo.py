"""Visible native yard demo backed by the normal dispatch engine."""
from pathlib import Path
import ctypes,json,os,sys,time,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from network_engine import NetworkEngine
import traci

def run():
    engine=NetworkEngine()
    try:
        if not engine.depots:raise RuntimeError('请先完成车辆段构建，再打开车辆段演示。')
        engine.set_headway(1,60);engine.start_line(1,gui=True)
        depot=engine.depots.get_depot(1,'U')
        points=depot['geometry']['perimeter']
        engine.conn.gui.setBoundary('View #0',min(p[0] for p in points)-120,min(p[1] for p in points)-120,
                                    max(p[0] for p in points)+120,max(p[1] for p in points)+120)
        # Small light markers keep the real storage tracks legible on zoom.
        for pid in engine.conn.poi.getIDList():
            if '_Y' in pid and '_light' in pid:
                engine.conn.poi.setWidth(pid,.35);engine.conn.poi.setHeight(pid,.35)
        deadline=float(os.environ.get('XIAMEN_DEPOT_DEMO_TEST_SECONDS','7200'))
        while engine.time<deadline:
            engine.step()
            if 'XIAMEN_DEPOT_DEMO_TEST_SECONDS' not in os.environ:time.sleep(.03)
        report={'result':'PASS','network':engine.network_name,'time':engine.time,'yard':depot['id'],
                'active_trains':sum(t['active'] for t in engine.trains.values()),
                'collisions':engine.collisions,'teleports':engine.teleports}
        (ROOT/'logs/depot-demo-session.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    except traci.exceptions.FatalTraCIError:
        pass
    finally:engine.close()

if __name__=='__main__':
    try:run()
    except Exception:
        (ROOT/'logs/depot-demo-launch.log').write_text(traceback.format_exc(),encoding='utf8')
        ctypes.windll.user32.MessageBoxW(None,'车辆段演示启动失败，请查看 logs/depot-demo-launch.log。','车辆段演示',0x10)
