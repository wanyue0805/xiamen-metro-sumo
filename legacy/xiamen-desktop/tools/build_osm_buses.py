"""Compile auditable OSM bus demonstrations on the separate GIS SUMO map.

Original OSM relation names and stop order are retained. Missing or
unconnected stops are reported; routes are accepted only when a useful
portion can be matched to bus-permitted roads. Demonstration schedules
are synthetic and never presented as official operations or timetables.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import os
import sys
import warnings
import xml.etree.ElementTree as E

ROOT = Path(__file__).resolve().parents[1]
MAP = ROOT/'maps/osm'
sys.path.insert(0, str(ROOT/'runtime/sumo/tools'))
import sumolib
from download_map import utm50


def write(path, root):
    E.ElementTree(root).write(path, encoding='utf-8', xml_declaration=True)


def build(max_routes=6):
    catalogue = json.loads((MAP/'bus_catalogue.json').read_text(encoding='utf-8'))
    if not catalogue.get('routes'):
        raise RuntimeError('No downloaded OSM bus relations are available.')
    net_path = MAP/'xiamen.net.xml'
    net = sumolib.net.readNet(str(net_path))
    warnings.filterwarnings('ignore', message="Module 'rtree' not available.*")
    additional = E.Element('additional')
    plans = E.Element('routes')
    E.SubElement(plans, 'vType', id='osm_demo_bus', vClass='bus', guiShape='bus',
                 length='12', width='2.5', maxSpeed='15', accel='1.2', decel='3',
                 personCapacity='4', boardingDuration='4', color='0.95,0.7,0.3')
    E.SubElement(plans, 'vType', id='osm_crowd20', vClass='pedestrian', color='0.2,0.9,0.92')
    compiled, rejected = [], []
    used_refs = set()
    neighbors = {}

    def candidates(stop, heading, member_ids):
        raw = utm50(stop['lon'], stop['lat']);off=net.getLocationOffset();xy=(raw[0]+off[0],raw[1]+off[1])
        cache_key = (round(stop['lon'], 5), round(stop['lat'], 5))
        if cache_key not in neighbors:
            found = net.getNeighboringEdges(xy[0], xy[1], r=180, includeJunctions=False)
            neighbors[cache_key] = found
        out = []
        for edge, distance in neighbors[cache_key]:
            lanes = [lane for lane in edge.getLanes() if lane.allows('bus') and lane.getLength()>35]
            if not lanes:
                continue
            lane = lanes[-1]
            offset, _ = sumolib.geomhelper.polygonOffsetAndDistanceToPoint(xy, lane.getShape())
            pos = max(10., min(lane.getLength()-10., offset))
            a = sumolib.geomhelper.positionAtShapeOffset(lane.getShape(), max(0., pos-8))
            b = sumolib.geomhelper.positionAtShapeOffset(lane.getShape(), min(lane.getLength(), pos+8))
            dx, dy = b[0]-a[0], b[1]-a[1]
            norm = max(.1, math.hypot(dx, dy)*math.hypot(*heading))
            alignment = (dx*heading[0]+dy*heading[1])/norm
            source_id = edge.getID().lstrip('-').split('#')[0]
            score = distance + (1-alignment)*40 + (0 if source_id in member_ids else 80)
            out.append(dict(edge=edge, lane=lane, pos=pos, distance=distance, score=score))
        return sorted(out, key=lambda item: item['score'])[:5]

    # Ordinary bus services are preferred over BRT where dedicated lanes
    # may still be absent from a partially downloaded road network.
    ordered = sorted(catalogue['routes'], key=lambda r: ('快' in str(r.get('ref', '')), -len(r.get('stops', []))))
    for original in ordered:
        if len(compiled)>=max_routes:
            break
        ref = str(original.get('ref') or original['id'])
        if ref in used_refs:
            continue
        raw_stops = original.get('stops', [])
        # Prefer stop positions; platforms can duplicate the same stop.
        stops = []
        for stop in raw_stops:
            if stops:
                prev = stops[-1]
                if math.hypot((stop['lon']-prev['lon'])*101400, (stop['lat']-prev['lat'])*111300)<55:
                    continue
            stops.append(stop)
        if len(stops)<3:
            rejected.append({'id': original['id'], 'ref': ref, 'reason': 'fewer than three distinct stop positions'})
            continue
        members = set(map(str, original.get('way_ids', [])))
        route_edges, mapped, skipped = [], [], []
        previous = None
        for index, stop in enumerate(stops):
            next_stop = stops[min(len(stops)-1, index+1)]
            if index==len(stops)-1:
                prev_stop = stops[index-1]
                heading = ((stop['lon']-prev_stop['lon'])*101400, (stop['lat']-prev_stop['lat'])*111300)
            else:
                heading = ((next_stop['lon']-stop['lon'])*101400, (next_stop['lat']-stop['lat'])*111300)
            options = candidates(stop, heading, members)
            chosen, path = None, None
            if previous is None:
                if options:
                    chosen = options[0]
                    path = (chosen['edge'],)
            else:
                best_score = float('inf')
                for option in options:
                    if option['edge']==previous['edge']:
                        if option['pos']<=previous['pos']+20:
                            continue
                        candidate_path, distance = (option['edge'],), option['pos']-previous['pos']
                    else:
                        candidate_path, distance = net.getShortestPath(previous['edge'], option['edge'],
                            vClass='bus', maxCost=18000, fromPos=previous['pos'], toPos=option['pos'])
                    if candidate_path and distance+option['score']*4<best_score:
                        chosen, path = option, candidate_path
                        best_score = distance+option['score']*4
            if chosen is None:
                skipped.append({'id': stop['id'], 'name': stop['name'], 'reason': 'no connected bus-permitted road within 180 m'})
                continue
            ids = [edge.getID() for edge in path]
            route_edges.extend(ids if not route_edges else ids[1:])
            mapped.append({'stop': stop, 'edge': chosen['edge'].getID(), 'lane': chosen['lane'].getID(),
                           'pos': chosen['pos'], 'road_match_distance_m': round(chosen['distance'], 1)})
            previous = chosen
        coverage = len(mapped)/len(stops)
        if len(mapped)<3 or coverage<.60:
            rejected.append({'id': original['id'], 'ref': ref, 'matched_stops': len(mapped),
                             'unique_stops': len(stops), 'coverage': coverage,
                             'reason': 'insufficient connected stop coverage', 'skipped': skipped})
            continue
        rid = 'OSM_BUS_'+str(original['id'])
        for index, stop in enumerate(mapped):
            sid = rid+'_S'+str(index)
            stop['sumo_stop_id'] = sid
            pos = stop['pos']
            E.SubElement(additional, 'busStop', id=sid, lane=stop['lane'],
                         startPos=str(pos-8), endPos=str(pos+5), friendlyPos='true',
                         name=stop['stop']['name'], lines=rid)
        route = E.SubElement(plans, 'route', id=rid, edges=' '.join(route_edges))
        for stop in mapped:
            E.SubElement(route, 'stop', busStop=stop['sumo_stop_id'], duration='20')
        color = original.get('colour') or '#eab54c'
        if not color.startswith('#') or len(color)!=7:
            color = '#eab54c'
        # 300 seconds is an explicit demonstration schedule, not OSM data.
        E.SubElement(plans, 'flow', id=rid+'_bus', route=rid, type='osm_demo_bus', line=rid,
                     begin=str(len(compiled)*12), end='3600', period='300',
                     departPos='0', departLane='best', color=color)
        # Each real person represents a twenty-person cohort. An initial
        # driving stage waits at the first real bus stop without inventing
        # sidewalk access when the imported map lacks pedestrian lanes.
        start, end = mapped[0], mapped[min(2, len(mapped)-1)]
        person = E.SubElement(plans, 'person', id=rid+'_crowd20', type='osm_crowd20',
                              depart='0', departPos=str(start['pos']-2))
        E.SubElement(person, 'param', key='cohort.people', value='20')
        E.SubElement(person, 'ride', attrib={'from': start['edge'], 'to': end['edge']},
                     lines=rid, busStop=end['sumo_stop_id'])
        compiled.append({'id': original['id'], 'ref': ref, 'name': original.get('name'),
                         'osm_url': original.get('osm_url'), 'sumo_route_id': rid,
                         'stops_total': len(stops), 'stops_matched': len(mapped),
                         'stop_coverage_fraction': round(coverage, 4), 'stops': mapped,
                         'skipped': skipped, 'route_edges': route_edges,
                         'schedule': 'synthetic demonstration: every 300 seconds',
                         'physical_geometry': 'imported OSM roads with connected shortest-path gaps'})
        used_refs.add(ref)
    if not compiled:
        report = {'status': 'unavailable', 'reason': 'No relation passed the connected-road acceptance threshold',
                  'rejected': rejected}
        (MAP/'xiamen.bus-build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        raise RuntimeError(report['reason'])
    write(MAP/'xiamen.bus.add.xml', additional)
    write(MAP/'xiamen.bus.rou.xml', plans)
    cfg = E.parse(MAP/'xiamen.osm.sumocfg').getroot()
    inp = cfg.find('input')
    E.SubElement(inp, 'route-files', value='xiamen.bus.rou.xml')
    current = inp.find('additional-files')
    current.set('value', current.get('value')+',xiamen.bus.add.xml')
    time_settings = cfg.find('time')
    time_settings.find('end').set('value', '7200')
    E.SubElement(time_settings, 'step-length', value='0.5')
    processing = E.SubElement(cfg, 'processing')
    E.SubElement(processing, 'time-to-teleport', value='-1')
    report_settings = E.SubElement(cfg, 'report')
    E.SubElement(report_settings, 'no-step-log', value='true')
    E.SubElement(report_settings, 'duration-log.disable', value='true')
    write(MAP/'xiamen.bus.sumocfg', cfg)
    report = {'status': 'built', 'source': catalogue.get('source'),
              'catalogue_routes': len(catalogue['routes']), 'compiled_demonstration_routes': len(compiled),
              'net_sha256': hashlib.sha256(net_path.read_bytes()).hexdigest(),
              'people_per_dot': 20, 'bus_capacity_people': 80,
              'limitations': ['Schedules and demand are synthetic demonstrations.',
                             'Shortest paths fill gaps between matched stops; not an audited operating alignment.',
                             'This GIS scene is separate from the schematic metro dispatch scene.',
                             'No physical metro transfer is claimed in the GIS bus scene.'],
              'routes': compiled, 'rejected': rejected}
    (MAP/'xiamen.bus-build.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'compiled_routes': len(compiled),
                      'refs': [route['ref'] for route in compiled]}))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--max-routes', type=int, default=6)
    args = parser.parse_args()
    build(args.max_routes)
