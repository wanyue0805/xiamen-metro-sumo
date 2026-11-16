"""Native GIS bus demonstration with one live circular dot per 20-person cohort."""
from pathlib import Path
import ctypes,json,os,subprocess,sys,time,traceback,xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from network_engine import sumo_working_root
import traci
from sumolib.miscutils import getFreeSocketPort

def run():
    working=sumo_working_root();cfg=working/'maps/osm/xiamen.bus.sumocfg'
    if not cfg.exists():raise FileNotFoundError('请先完成地图下载和真实公交场景构建。')
    view=E.parse(working/'maps/osm/xiamen.view.xml');scheme=view.getroot().find('scheme');scheme.set('name','XiamenGeoBus4')
    pois=scheme.find('pois')
    if pois is None:pois=E.SubElement(scheme,'pois')
    for key,value in {'poi_minSize':'0','poi_constantSize':'1','poiName_show':'0','poiType_show':'0','poiTextParam':'label','poiText_show':'1','poiText_size':'55','poiText_color':'225,237,245','poiText_constantSize':'1'}.items():pois.set(key,value)
    view.write(working/'maps/osm/xiamen.bus.live.view.xml',encoding='utf-8',xml_declaration=True)
    port=getFreeSocketPort();label=f'osm_bus_{os.getpid()}_{time.time_ns()}'
    env=os.environ.copy();env['SUMO_HOME']=str(working/'runtime/sumo');env['__COMPAT_LAYER']='HIGHDPIAWARE'
    startup=None
    if os.name=='nt':
        startup=subprocess.STARTUPINFO();startup.dwFlags|=subprocess.STARTF_USESHOWWINDOW;startup.wShowWindow=1
    with open(ROOT/'logs/osm-bus-process.log','a',encoding='utf-8') as log:
        proc=subprocess.Popen([str(working/'runtime/sumo/bin/sumo-gui.exe'),'-c','maps/osm/xiamen.bus.sumocfg',
            '--start','--quit-on-end','--gui-settings-file','maps/osm/xiamen.bus.live.view.xml','--window-size','1400,950','--window-pos','80,60','--remote-port',str(port)],
            cwd=working,env=env,stdout=log,stderr=log,startupinfo=startup)
    conn=None;dots=set();groups={}
    try:
        traci.init(port,numRetries=12,label=label,proc=proc);conn=traci.getConnection(label)
        labels={'湖滨东路':'Hubin East Rd','吕厝':'Lvcuo','火炬园':'Torch Park','官任':'Guanren','厦门北站':'Xiamen North','鼎美':'Dingmei','马銮中心':'Maluan Center','体育中心':'Sports Center','五缘湾':'Wuyuan Bay','洪坑':'Hongkeng'}
        for poi in E.parse(working/'maps/osm/xiamen.transit.add.xml').getroot().findall('poi'):
            pid=poi.get('id');conn.poi.setWidth(pid,.8);conn.poi.setHeight(pid,.8)
            for name,label_text in labels.items():
                if name in (poi.get('name','')+' '+poi.get('type','')):conn.poi.setParameter(pid,'label',label_text)
        test_limit=float(os.environ.get('XIAMEN_OSM_TEST_SECONDS','7200'))
        (ROOT/'logs/osm-bus-live-ready.json').write_text(json.dumps({'pid':os.getpid(),'sumo_pid':proc.pid,'ready':True}),encoding='utf-8')
        while conn.simulation.getTime()<test_limit:
            conn.simulationStep();active=set(conn.person.getIDList())
            for pid in active:
                conn.person.setColor(pid,(0,0,0,0));xy=conn.person.getPosition(pid)
                count=int(conn.person.getParameter(pid,'cohort.people') or '20')
                vehicle=conn.person.getVehicle(pid);dot='GIS_COHORT_'+pid
                color=(242,181,88,255) if vehicle else (99,220,229,255)
                if dot not in dots:
                    conn.poi.add(dot,*xy,color,poiType=f'{count} people',layer=12,width=.8,height=.8);dots.add(dot)
                else:conn.poi.setPosition(dot,*xy);conn.poi.setColor(dot,color)
                group=groups.setdefault(pid,{'count':count,'rides':[],'arrived':False})
                if vehicle and (not group['rides'] or group['rides'][-1]!=vehicle):group['rides'].append(vehicle)
            for dot in list(dots):
                pid=dot[len('GIS_COHORT_'):]
                if pid not in active:
                    conn.poi.remove(dot,layer=12);dots.remove(dot);groups[pid]['arrived']=True
            if proc.poll() is not None:break
            if 'XIAMEN_OSM_TEST_SECONDS' not in os.environ:time.sleep(.03)
    except traci.exceptions.FatalTraCIError:
        pass  # Closing the native window is the ordinary exit action.
    finally:
        if conn:
            try:conn.close()
            except traci.exceptions.FatalTraCIError:pass
        elif proc.poll() is None:proc.terminate()
        if groups:(ROOT/'logs/osm-bus-live-session.json').write_text(json.dumps({'groups':groups,'people_per_dot':20},ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    try:run()
    except Exception:
        (ROOT/'logs/osm-bus-launch.log').write_text(traceback.format_exc(),encoding='utf-8')
        ctypes.windll.user32.MessageBoxW(None,'真实公交场景启动失败，请查看 logs/osm-bus-launch.log。','厦门公交地理仿真',0x10)
