"""Validate the delivered map, provenance, station coverage and SUMO loading."""
from pathlib import Path
from collections import Counter
import hashlib,json,subprocess,sys,xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tools'))
from download_map import utm50
from network_engine import sumo_working_root

def main():
    directory=ROOT/'maps/osm';data=json.loads((directory/'map.json').read_text(encoding='utf-8'))
    report=data['report'];digest=hashlib.sha256((directory/'xiamen.osm.xml').read_bytes()).hexdigest()
    assert digest==report['sha256'],'OSM checksum differs from map report'
    catalogue=json.loads((ROOT/'lines.json').read_text(encoding='utf-8'))
    for line in catalogue['lines']:
        for name in line['names']:
            assert name in data['stations'],(line['id'],name,'Missing coordinates')
            station=data['stations'][name]
            assert station['priority']>=3,(name,'Station match is not marked as subway in OSM')
    osm=E.parse(directory/'xiamen.osm.xml').getroot();nodes={n.get('id'):n for n in osm.findall('node')}
    net=E.parse(directory/'xiamen.net.xml').getroot();location=net.find('location');offset=tuple(map(float,location.get('netOffset').split(',')))
    errors=[]
    for junction in net.findall('junction'):
        node=nodes.get(junction.get('id'))
        if node is None:continue
        x,y=utm50(float(node.get('lon')),float(node.get('lat')))
        error=((float(junction.get('x'))-x-offset[0])**2+(float(junction.get('y'))-y-offset[1])**2)**.5
        if error<.1:errors.append(error)
    assert len(errors)>100,'Too few matching UTM projection reference points'
    working=sumo_working_root()
    result=subprocess.run([str(working/'runtime/sumo/bin/sumo.exe'),'-c','maps/osm/xiamen.osm.sumocfg','--end','1','--no-step-log','true'],cwd=working,capture_output=True,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    assert result.returncode==0,result.stdout+'\n'+result.stderr
    stops=E.parse(directory/'xiamen.stops.add.xml').getroot()
    summary={'result':'PASS','station_entries':sum(len(l['names']) for l in catalogue['lines']),
             'unique_stations':len(data['stations']),'station_coverage':report['station_coverage'],
             'map_features':dict(Counter(f['kind'] for f in data['features'])),
             'sumo_edges':sum(e.get('function')!='internal' for e in net.findall('edge')),
             'sumo_imported_stops':dict(Counter(s.tag for s in stops)),
             'projection_reference_points':len(errors),'max_reference_error_meters':round(max(errors),4),
             'osm_sha256':digest,'sumo_load':'PASS','layer_errors':report.get('layer_errors',{})}
    (ROOT/'logs/map-validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
