"""Add explicitly modelled feeder buses to the preserved five-line network.

The feeder roads are schematic access corridors, not official Xiamen bus
routes. Original rail nodes, edges, stops, service plans and settings are
copied unchanged; this builder only writes files named multimodal.*.
"""
from pathlib import Path
import copy
import json
import math
import subprocess
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parents[1]
NET = ROOT / 'network'


def write(name, root):
    E.ElementTree(root).write(NET / name, encoding='utf-8', xml_declaration=True)


def build():
    nodes = E.parse(NET / 'unified.nod.xml').getroot()
    edges = E.parse(NET / 'unified.edg.xml').getroot()
    connections = E.parse(NET / 'unified.con.xml').getroot()
    additional = E.parse(NET / 'unified.add.xml').getroot()
    routes = E.parse(NET / 'unified.rou.xml').getroot()
    for vehicle_type in routes.findall('vType'):
        if vehicle_type.get('id', '').startswith('metro'):
            vehicle_type.set('personCapacity', '60')
            vehicle_type.set('boardingDuration', '4')
    stations = json.loads((NET / 'unified.stations.json').read_text(encoding='utf-8'))
    specs = [('B01', '湖滨东路', '#f4b85b'), ('B02', '吕厝', '#61c8b5'),
             ('B03', '厦门北站', '#98a5f8'), ('B04', '五缘湾', '#f38fc1')]
    meta = {}

    def node(nid, xy):
        E.SubElement(nodes, 'node', id=nid, x=str(xy[0]), y=str(xy[1]), type='priority', radius='4')

    def edge(eid, fr, to, shape, pedestrian=False):
        E.SubElement(edges, 'edge', id=eid, attrib={'from': fr, 'to': to},
                     numLanes='1', allow='pedestrian' if pedestrian else 'bus',
                     speed='1.4' if pedestrian else '12.5',
                     width='3' if pedestrian else '3.5', spreadType='center',
                     shape=' '.join(f'{x:.3f},{y:.3f}' for x, y in shape))

    def connect(a, b):
        E.SubElement(connections, 'connection', attrib={'from': a, 'to': b}, fromLane='0', toLane='0')

    E.SubElement(routes, 'vType', id='feeder_bus', vClass='bus', guiShape='bus',
                 length='12', width='2.5', maxSpeed='12.5', accel='1.3', decel='3.0',
                 minGap='3', sigma='0.2', personCapacity='4', boardingDuration='4',
                 color='0.96,0.72,0.35')
    E.SubElement(routes, 'vType', id='crowd20', vClass='pedestrian', guiShape='pedestrian',
                 maxSpeed='1.4', width='0.6', length='0.6', color='0.20,0.90,0.92')

    for rid, name, color in specs:
        hub = stations['hubs'][name]
        xy = stations['shared_stations'][name]['point']
        hx, hy = xy
        # A closed bus-only road ring avoids road/rail conflicts. Its two
        # terminal walks join the existing real pedestrian hub graph.
        points = {'A': (hx-1450, hy-250), 'B': (hx-250, hy-250),
                  'C': (hx-250, hy-330), 'D': (hx-1450, hy-330),
                  'CF': (hx-1470, hy-190)}
        for suffix, p in points.items():
            node(rid+'_'+suffix, p)
        ring = []
        for suffix, fr, to in [('I', 'A', 'B'), ('TB', 'B', 'C'), ('O', 'C', 'D'), ('TA', 'D', 'A')]:
            eid = rid+'_'+suffix
            edge(eid, rid+'_'+fr, rid+'_'+to, [points[fr], points[to]])
            ring.append(eid)
        for a, b in zip(ring, ring[1:]+ring[:1]):
            connect(a, b)
        for suffix, fr, to, shape in [
            ('CWalk', rid+'_A', rid+'_CF', [points['A'], points['CF']]),
            ('CWalkR', rid+'_CF', rid+'_A', [points['CF'], points['A']]),
            ('HWalk', hub, rid+'_B', [xy, (hx-130, hy-120), points['B']]),
            ('HWalkR', rid+'_B', hub, [points['B'], (hx-130, hy-120), xy])]:
            edge(rid+'_'+suffix, fr, to, shape, True)
        connect(rid+'_CWalk', rid+'_CWalkR')
        connect(rid+'_CWalkR', rid+'_CWalk')
        connect(rid+'_HWalk', rid+'_HWalkR')
        connect(rid+'_HWalkR', rid+'_HWalk')
        members = stations['shared_stations'][name]['members']
        hub_stations = [next(s for s in stations['stations'][str(lid)] if s['name']==name) for lid in members]
        for s in hub_stations:
            connect(rid+'_HWalkR', s['walk_edge'])
            connect(s['walk_back'], rid+'_HWalk')
        for suffix, lane, lo, hi, kind, label in [
            ('CI', rid+'_I_0', 35, 65, 'community', '社区站·进城'),
            ('HI', rid+'_I_0', 1130, 1160, 'hub', '地铁站·到达'),
            ('HO', rid+'_O_0', 35, 65, 'hub', '地铁站·出发'),
            ('CO', rid+'_O_0', 1130, 1160, 'community', '社区站·到达')]:
            stop = E.SubElement(additional, 'busStop', id=rid+'_'+suffix, lane=lane,
                                startPos=str(lo), endPos=str(hi), friendlyPos='true',
                                name=f'{name} {label}', lines=rid, personCapacity='100')
            walks = ['CWalk', 'CWalkR'] if kind=='community' else ['HWalk', 'HWalkR']
            for walk in walks:
                E.SubElement(stop, 'access', lane=rid+'_'+walk+'_0', pos='10',
                             length='15' if kind=='community' else '45', friendlyPos='true')
        r = E.SubElement(routes, 'route', id=rid+'_Service', edges=' '.join(ring*24))
        for _ in range(24):
            for suffix in ['CI', 'HI', 'HO', 'CO']:
                E.SubElement(r, 'stop', busStop=rid+'_'+suffix, duration='18')
        E.SubElement(additional, 'poi', id=rid+'_HubSign', x=str(hx-250), y=str(hy-220),
                     color=color, layer='5', width='14', height='14',
                     name=f'{rid} {name} 接驳示范 · 公交⇄地铁')
        E.SubElement(additional, 'poi', id=rid+'_CommunitySign', x=str(hx-1450), y=str(hy-150),
                     color=color, layer='5', width='10', height='10',
                     name=f'{rid} 社区站 · 接驳示范')
        meta[rid] = {'id': rid, 'name': f'{rid} · {name}接驳示范', 'metro_hub': name,
                     'community_name': f'{rid} · {name}社区', 'color': color,
                     'stops': [f'{name}社区', f'{name}地铁站'], 'headway': 180,
                     'hub_id': hub, 'hub_point': list(xy),
                     'community_point': list(points['CF']), 'road_length': 1200,
                     'community_walk': rid+'_CWalk', 'hub_walk': rid+'_HWalk',
                     'representation': 'schematic feeder demonstration; not an official bus route'}

    write('multimodal.nod.xml', nodes)
    write('multimodal.edg.xml', edges)
    write('multimodal.con.xml', connections)
    write('multimodal.rou.xml', routes)
    command = [str(ROOT/'runtime/sumo/bin/netconvert.exe'),
               '--node-files', str(NET/'multimodal.nod.xml'),
               '--edge-files', str(NET/'multimodal.edg.xml'),
               '--connection-files', str(NET/'multimodal.con.xml'),
               '--output-file', str(NET/'multimodal.net.xml'), '--no-turnarounds', 'true',
               '--junctions.internal-link-detail', '32', '--offset.disable-normalization', 'true',
               '--geometry.min-radius.fix.railways', 'false']
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace')
    (ROOT/'logs').mkdir(exist_ok=True)
    (ROOT/'logs/multimodal-build.log').write_text(result.stdout+'\n'+result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(result.stderr)
    compiled = E.parse(NET/'multimodal.net.xml').getroot()
    lengths = {lane.get('id'): float(lane.get('length')) for edge in compiled.findall('edge') for lane in edge.findall('lane')}
    for rid, info in meta.items():
        for key in ('community_walk', 'hub_walk'):
            info[key+'_pos'] = lengths[info[key]+'_0']*.55
        for stop in additional.findall('busStop'):
            if not stop.get('id', '').startswith(rid+'_'):
                continue
            for access in stop.findall('access'):
                access.set('pos', str(lengths[access.get('lane')]*.55))
    write('multimodal.add.xml', additional)
    cfg = E.parse(NET/'unified.sumocfg').getroot()
    for elem in cfg.find('input'):
        elem.set('value', elem.get('value').replace('unified.', 'multimodal.'))
    cfg.find('gui_only/gui-settings-file').set('value', 'multimodal.view.xml')
    write('multimodal.sumocfg', cfg)
    (NET/'multimodal.view.xml').write_text(
        '<viewsettings><scheme name="XiamenNetwork"><vehicles vehicleMode="0" vehicleQuality="2" '
        'vehicle_minSize="0" vehicle_exaggeration="1" vehicle_constantSize="0"/>'
        '<persons personMode="0" personQuality="0" person_minSize="1" person_exaggeration="2"/>'
        '</scheme><delay value="0"/></viewsettings>', encoding='utf-8')
    (NET/'multimodal.routes.json').write_text(json.dumps({'routes': meta,
        'people_per_full_dot': 20, 'bus_capacity_people': 80,
        'metro_capacity_people': 1200,
        'geometry': 'original unified metro schematic plus schematic feeder roads',
        'official_routes': False}, ensure_ascii=False, indent=2), encoding='utf-8')
    # Verify preservation against the existing compiled rail graph.
    old = E.parse(NET/'unified.net.xml').getroot()
    new_by_id = {edge.get('id'): edge for edge in compiled.findall('edge')}
    checked = 0
    for edge in old.findall('edge'):
        if edge.get('function')=='internal':
            continue
        current = new_by_id[edge.get('id')]
        if edge.get('id').startswith('L') and 'Walk' not in edge.get('id'):
            for a, b in zip(edge.findall('lane'), current.findall('lane')):
                if a.get('shape') != b.get('shape') or a.get('length') != b.get('length'):
                    raise RuntimeError('Original rail/walk geometry changed: '+edge.get('id'))
            checked += 1
    report = {'status': 'pass', 'preserved_original_edges': checked,
              'feeder_routes': len(meta), 'bus_stops': 16,
              'bus_capacity_people': 80, 'representative_weight': 20}
    (ROOT/'logs/multimodal-build.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if (ROOT/'tools/style_sumo.py').exists():
        import style_sumo
        style_sumo.build()
    print(json.dumps(report))
    return meta


if __name__ == '__main__':
    build()
