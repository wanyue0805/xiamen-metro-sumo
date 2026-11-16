"""Resumeable, additive OSM completion and source-backed bus route catalogue.

Only fully parsed, unremarked Overpass responses are committed. Failed tiles
leave the previous geography intact. This does not change the operating model.
"""
from pathlib import Path
import argparse, concurrent.futures, datetime, hashlib, json, math, shutil
import os, subprocess, sys, time, urllib.parse, urllib.request, xml.etree.ElementTree as ET
import download_map as base

ROOT = base.ROOT
OUT = ROOT / 'maps/osm'
# The HPI mirror is responsive for small XML requests when other public
# endpoints time out. A fallback remains available, but never replaces data
# with a response containing a timeout remark.
SERVERS = [base.SERVERS[2],base.SERVERS[0],base.SERVERS[1]]
STAMP = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
REFRESH = False

def tags(element):
    return {tag.get('k'): tag.get('v') for tag in element.findall('tag')}

def validate_osm(root):
    if root.tag != 'osm' or root.find('remark') is not None:
        raise ValueError(root.findtext('remark') or 'Response is not OSM')
    node_ids={node.get('id') for node in root.findall('node')}
    missing={nd.get('ref') for way in root.findall('way') for nd in way.findall('nd') if nd.get('ref') not in node_ids}
    if missing:
        raise ValueError(f'Incomplete way geometry: {len(missing)} referenced nodes are missing')

def query(kind, key, value, bbox=None, recursive=False, regex=False):
    selection = '<query type="' + kind + '"><has-kv k="' + key + '" ' + ('regv' if regex else 'v') + '="' + value + '"/>'
    if bbox:
        w,s,e,n = bbox
        selection += f'<bbox-query s="{s:.6f}" w="{w:.6f}" n="{n:.6f}" e="{e:.6f}"/>'
    selection += '</query>'
    if recursive:
        selection += '<union><item/><recurse type="' + ('down' if kind == 'relation' else 'way-node') + '"/></union>'
    return '<osm-script output="xml" timeout="40">' + selection + '<print mode="body"/></osm-script>'

def route_query(route,bbox=None):
    """Find route parents from a small local object set, avoiding global route bbox scans."""
    w,s,e,n=bbox or base.BBOX
    kind,key,value,recurse = ('node','highway','bus_stop','node-relation') if route=='bus' else ('way','railway','subway','way-relation')
    return (f'<osm-script output="xml" timeout="40"><query type="{kind}"><has-kv k="{key}" v="{value}"/>'
            f'<bbox-query s="{s}" w="{w}" n="{n}" e="{e}"/></query>'
            f'<recurse type="{recurse}"/><query type="relation"><item/><has-kv k="route" v="{route}"/></query>'
            '<union><item/><recurse type="down"/></union><print mode="body"/></osm-script>')

def fetch(task):
    name, xml_query, cache = task
    if cache.exists() and not REFRESH:
        try:
            root = ET.parse(cache).getroot()
            validate_osm(root)
            return dict(name=name, ok=True, cache=str(cache), reused=True,
                        ways=len(root.findall('way')), relations=len(root.findall('relation')))
        except (OSError, ET.ParseError, ValueError):
            pass
    errors = []
    # Requests remain small and concurrency stays at two to respect the public service.
    for server in SERVERS[:2]:
        print(f'Fetching {name} from {server}', flush=True)
        try:
            request = urllib.request.Request(server + '?' + urllib.parse.urlencode({'data': xml_query}),
                headers={'User-Agent':'XiamenMetro-SUMO/3.2 (local educational simulation)', 'Accept':'application/xml'})
            opener = urllib.request.build_opener() if os.environ.get('XIAMEN_MAP_USE_PROXY')=='1' else urllib.request.build_opener(urllib.request.ProxyHandler({}))
            started=time.monotonic()
            with opener.open(request, timeout=48) as response:
                chunks=[];size=0
                while True:
                    chunk=response.read(65536)
                    if not chunk:break
                    chunks.append(chunk);size+=len(chunk)
                    if size>48*1024*1024 or time.monotonic()-started>150:
                        raise TimeoutError('Response exceeded 150 second /48 MB limit')
                content=b''.join(chunks)
            root = ET.fromstring(content)
            validate_osm(root)
            if not any(root.findall(k) for k in ('node','way','relation')):
                # A complete empty tile is still valid and counted accurately.
                pass
            temporary = cache.with_suffix('.pending.xml')
            temporary.write_bytes(content)
            temporary.replace(cache)
            result = dict(name=name, ok=True, cache=str(cache), endpoint=server, bytes=len(content),
                          sha256=hashlib.sha256(content).hexdigest(), ways=len(root.findall('way')),
                          relations=len(root.findall('relation')))
            print(f'Completed {name}: {result["ways"]} ways, {result["relations"]} relations', flush=True)
            return result
        except Exception as exc:
            errors.append(f'{server}: {type(exc).__name__}: {exc}')
            print(f'{name}: {exc}', flush=True)
    return dict(name=name, ok=False, errors=errors)

def repair_tile(task):
    """One bounded subdivision of a failed dense tile; commit only all four successes."""
    name,xml_query,path=task
    script=ET.fromstring(xml_query);bbox=script.find('./query/bbox-query')
    if bbox is None:return dict(name=name,ok=False,errors=['Task has no direct bbox'])
    w,s,e,n=[float(bbox.get(key)) for key in ('w','s','e','n')]
    children=[]
    for row in range(2):
        for col in range(2):
            child=ET.fromstring(xml_query);box=child.find('./query/bbox-query')
            coordinates=(w+(e-w)*col/2,s+(n-s)*row/2,w+(e-w)*(col+1)/2,s+(n-s)*(row+1)/2)
            for key,value in zip(('w','s','e','n'),coordinates):box.set(key,f'{value:.8f}')
            subname=f'{name}_sub_{row}_{col}'
            children.append((subname,ET.tostring(child,encoding='unicode'),path.parent/(subname+'.osm.xml')))
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(fetch,children))
    if not all(result['ok'] for result in results):
        return dict(name=name,ok=False,subtiles=results,errors=['One or more bounded subtiles failed; previous geometry retained'])
    elements={}
    for result in results:
        for item in ET.parse(result['cache']).getroot():
            if item.tag in ('node','way','relation'):elements[(item.tag,item.get('id'))]=item
    root=ET.Element('osm',version='0.6',generator='XiamenMetro complete 2x2 subdivision')
    rank={'node':0,'way':1,'relation':2}
    for key,item in sorted(elements.items(),key=lambda pair:(rank[pair[0][0]],int(pair[0][1]))):root.append(item)
    validate_osm(root)
    temporary=path.with_suffix('.pending.xml');ET.ElementTree(root).write(temporary,encoding='utf-8',xml_declaration=True);temporary.replace(path)
    return dict(name=name,ok=True,cache=str(path),subtiles=results,
                ways=len(root.findall('way')),relations=len(root.findall('relation')))

def build_catalogue(osm_path):
    osm = ET.parse(osm_path).getroot()
    nodes = {node.get('id'):node for node in osm.findall('node')}
    ways = {way.get('id'):way for way in osm.findall('way')}
    station_data = json.loads((OUT/'map.json').read_text(encoding='utf-8'))['stations']
    routes = [];nearby_excluded=[]
    def point(item):
        if item.tag == 'node': return [float(item.get('lon')),float(item.get('lat'))]
        points = [point(nodes[nd.get('ref')]) for nd in item.findall('nd') if nd.get('ref') in nodes]
        if points: return [sum(p[i] for p in points)/len(points) for i in (0,1)]
    for relation in osm.findall('relation'):
        info = tags(relation)
        if info.get('route') != 'bus': continue
        route = dict(id=relation.get('id'), name=info.get('name',''), ref=info.get('ref',''),
                     colour=info.get('colour','#ECA72C'), operator=info.get('operator',''),
                     **{'from':info.get('from',''),'to':info.get('to','')},
                     osm_url='https://www.openstreetmap.org/relation/' + relation.get('id'),
                     way_ids=[], shapes_wgs84=[], stops=[])
        for member in relation.findall('member'):
            kind, ident, role = member.get('type'),member.get('ref'),member.get('role','')
            item = (nodes if kind == 'node' else ways if kind == 'way' else {}).get(ident)
            if item is None: continue
            item_tags = tags(item)
            if kind == 'way' and not ('platform' in role or item_tags.get('public_transport') == 'platform'):
                points = [point(nodes[nd.get('ref')]) for nd in item.findall('nd') if nd.get('ref') in nodes]
                if len(points)>1:
                    route['way_ids'].append(ident)
                    route['shapes_wgs84'].append(points)
            if ('stop' in role or 'platform' in role or item_tags.get('highway') == 'bus_stop'):
                p = point(item)
                if not p: continue
                nearby = []
                for name,station in station_data.items():
                    dx=(p[0]-station['lon'])*111320*math.cos(math.radians(p[1]));dy=(p[1]-station['lat'])*111320
                    distance = math.hypot(dx,dy)
                    if distance<=650:nearby.append(dict(name=name,distance_m=round(distance)))
                route['stops'].append(dict(id=kind+'/'+ident, name=item_tags.get('name','未命名公交站'),
                    lon=p[0],lat=p[1],role=role,metro_nearby=sorted(nearby,key=lambda x:x['distance_m'])))
        route['shape_wgs84'] = [p for shape in route['shapes_wgs84'] for p in shape]
        route['geometry_complete'] = len(route['way_ids']) == sum(m.get('type')=='way' and not 'platform' in m.get('role','') for m in relation.findall('member'))
        exclusion=base.nearby_bus_exclusion_reason(info)
        if exclusion:
            route['exclusion_reason']=exclusion
            nearby_excluded.append(route)
        else:
            routes.append(route)
    data = dict(source='OpenStreetMap contributors', license='ODbL 1.0',source_url='https://www.openstreetmap.org/copyright',
                downloaded_at=STAMP,bbox_wgs84=base.BBOX,routes=routes,nearby_excluded=nearby_excluded,
                scope='Xiamen candidate bus routes; explicitly identified neighbouring Kinmen services excluded by OSM agency/route metadata',
                limitations=['OSM bus coverage is incomplete; route labels and geometry come only from downloaded OSM relations.',
                             'Nearby metro station links use straight-line distance within 650 m, not audited walking paths.',
                             'No official timetable, headway or realtime passenger demand is provided by OSM.'])
    base.atomic_json(OUT/'bus_catalogue.json',data)
    return dict(routes=len(routes),nearby_excluded_routes=len(nearby_excluded),route_refs=sorted(set(r['ref'] for r in routes)),
                stop_members=sum(len(r['stops']) for r in routes),
                unique_osm_stop_objects=len({stop['id'] for route in routes for stop in route['stops']}),
                unique_osm_stop_objects_with_metro_links=len({stop['id'] for route in routes for stop in route['stops'] if stop['metro_nearby']}),
                routes_with_geometry=sum(bool(r['way_ids']) for r in routes),
                routes_with_metro_links=sum(any(s['metro_nearby'] for s in r['stops']) for r in routes))

def rebuild_bus_scene():
    """Keep derived bus routes in sync whenever the geographic SUMO net changes."""
    helper=ROOT/'tools/build_osm_buses.py'
    catalogue=OUT/'bus_catalogue.json'
    if not helper.exists() or not catalogue.exists():return {'status':'not_configured'}
    if not json.loads(catalogue.read_text(encoding='utf-8')).get('routes'):
        return {'status':'unavailable','reason':'No real OSM bus relations downloaded'}
    result=subprocess.run([sys.executable,str(helper),'--max-routes','6'],cwd=ROOT,
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=120,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:
        raise RuntimeError('OSM map converted, but derived bus scene could not be rebuilt: '+result.stderr[-1000:])
    manifest=json.loads((OUT/'xiamen.bus-build.json').read_text(encoding='utf-8'))
    if manifest.get('net_sha256')!=hashlib.sha256((OUT/'xiamen.net.xml').read_bytes()).hexdigest():
        raise ValueError('Derived bus routes do not match the newly converted network')
    check=subprocess.run([str(ROOT/'runtime/sumo/bin/sumo.exe'),'-c','maps/osm/xiamen.bus.sumocfg','--end','1'],cwd=ROOT,
        capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if check.returncode:raise RuntimeError('Derived bus scene failed SUMO loading: '+check.stderr[-1000:])
    print('Derived geographic bus scene rebuilt and loaded by SUMO.',flush=True)
    return dict(status='rebuilt_and_sumo_checked',routes=manifest['compiled_demonstration_routes'],
                net_sha256=manifest['net_sha256'],people_per_dot=manifest.get('people_per_dot'))

def main():
    global REFRESH
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline', action='store_true')
    parser.add_argument('--refresh', action='store_true',help='Request fresh tiles while retaining previous geometry if a request fails')
    parser.add_argument('--grid',type=int,default=4)
    parser.add_argument('--layers',default='roads,water,bus,subway_relations')
    parser.add_argument('--skip-convert',action='store_true')
    args=parser.parse_args();REFRESH=args.refresh;OUT.mkdir(exist_ok=True,parents=True)
    cache=OUT/'completion_tiles';cache.mkdir(exist_ok=True)
    tasks=[];wanted=set(args.layers.split(','));w,s,e,n=base.BBOX
    for row in range(args.grid):
        for col in range(args.grid):
            bbox=(w+(e-w)*col/args.grid,s+(n-s)*row/args.grid,w+(e-w)*(col+1)/args.grid,s+(n-s)*(row+1)/args.grid)
            for layer,key,value in [('roads','highway','^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|service|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link)$'),('water','natural','water')]:
                if layer in wanted:
                    name=f'{layer}_{args.grid}_{row}_{col}'
                    tasks.append((name,query('way',key,value,bbox,True,layer=='roads'),cache/(name+'.osm.xml')))
    for layer,value in [('bus','bus'),('subway_relations','subway')]:
        if layer in wanted:
            tasks.insert(0,(layer,route_query(value),cache/(layer+'.osm.xml')))
    results=[]
    if not args.offline:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            for result in pool.map(fetch,tasks):results.append(result)
        for index,result in enumerate(results):
            if not result['ok'] and result['name'].startswith(('roads_','water_')):
                repair=repair_tile(tasks[index])
                repair['initial_errors']=result.get('errors',[])
                results[index]=repair
    else:
        for name,q,path in tasks:
            if path.exists():results.append(dict(name=name,ok=True,cache=str(path),reused=True))
            else:results.append(dict(name=name,ok=False,errors=['Cache tile missing']))
    original=OUT/'xiamen.osm.xml';elements={}
    prior=ET.parse(original).getroot()
    for item in prior:
        if item.tag in ('node','way','relation'):elements[(item.tag,item.get('id'))]=item
    before=dict(nodes=len(prior.findall('node')),ways=len(prior.findall('way')),relations=len(prior.findall('relation')))
    for result in results:
        if result['ok']:
            for item in ET.parse(result['cache']).getroot():
                if item.tag in ('node','way','relation'):elements[(item.tag,item.get('id'))]=item
    stage=OUT/('completion_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'));stage.mkdir()
    merged=ET.Element('osm',version='0.6',generator='XiamenMetro additive tiled completion')
    rank={'node':0,'way':1,'relation':2}
    for key,item in sorted(elements.items(),key=lambda p:(rank[p[0][0]],int(p[0][1]))):merged.append(item)
    osm_path=stage/'xiamen.osm.xml';ET.ElementTree(merged).write(osm_path,encoding='utf-8',xml_declaration=True)
    previous=json.loads((OUT/'coverage.json').read_text(encoding='utf-8'))
    provenance={key:previous[key] for key in ('layers','layer_errors') if key in previous}
    provenance['layers'] = dict(provenance.get('layers',{}))
    for layer in ('roads','water'):
        selected=[r for r in results if r['name'].startswith(layer+'_')]
        if selected:
            provenance['layers'][layer]=dict(endpoint='additive XML tiles: '+SERVERS[0],
                partial=not all(r['ok'] for r in selected),requested_tiles=len(selected),
                complete_tiles=sum(r['ok'] for r in selected),previous_geometry_preserved=True)
    for layer in ('bus','subway_relations'):
        selected=[r for r in results if r['name']==layer]
        if selected and selected[0]['ok']:
            provenance['layers'][layer]={key:value for key,value in selected[0].items() if key not in ('cache','name')}
            provenance['layers'][layer]['partial']=False
    provenance['previous_layer_errors']=provenance.pop('layer_errors',{})
    provenance['layer_errors']={r['name']:r['errors'] for r in results if not r['ok']}
    provenance.update(completion_tiles=results,completion_mode='additive, complete responses only',sha256=hashlib.sha256(osm_path.read_bytes()).hexdigest())
    report=base.prepare(osm_path,stage,provenance)
    if not args.skip_convert:base.convert(osm_path,stage)
    history=OUT/('previous_completion_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'));history.mkdir()
    for item in stage.iterdir():
        if item.is_file():
            if (OUT/item.name).exists():shutil.copy2(OUT/item.name,history/item.name)
            shutil.copy2(item,OUT/item.name)
    bus=build_catalogue(OUT/'xiamen.osm.xml')
    bus_scene=rebuild_bus_scene() if not args.skip_convert else {'status':'skipped_conversion'}
    after=dict(nodes=len(merged.findall('node')),ways=len(merged.findall('way')),relations=len(merged.findall('relation')))
    completion=dict(before=before,after=after,tiles=results,bus=bus,bus_scene=bus_scene,downloaded_at=STAMP,
                    complete_road_tiles=sum(r['ok'] for r in results if r['name'].startswith('roads_')),
                    requested_road_tiles=args.grid**2 if 'roads' in wanted else 0,
                    station_coverage=report['station_coverage'],
                    road_query_scope='motorway/trunk/primary/secondary/tertiary/unclassified/residential/living_street/service and links; OSM source coverage, not an official completeness audit')
    base.atomic_json(OUT/'completion_report.json',completion)
    print(json.dumps({k:v for k,v in completion.items() if k!='tiles'},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':main()
