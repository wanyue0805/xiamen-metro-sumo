"""Download real Xiamen OSM data and build a separate SUMO inspection scenario.

No existing network or operating catalogue is replaced. Standard library only.
"""
from pathlib import Path
import argparse, datetime, hashlib, json, math, os, subprocess, sys, time
import urllib.parse, urllib.request, xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
BBOX = (117.87, 24.38, 118.46, 24.88)  # WGS84 west,south,east,north
SERVERS = ['https://overpass-api.de/api/interpreter',
           'https://overpass.private.coffee/api/interpreter',
           'https://osm.hpi.de/overpass/api/interpreter']

def nearby_bus_exclusion_reason(info):
    """A rectangular map bbox also intersects Kinmen; keep its services separate."""
    identity=' '.join(str(info.get(key,'')) for key in ('name','operator','network','from','to')).lower()
    if any(token in identity for token in ('金門','金门','kinmen','金城車站','金城车站','九宮碼頭','九宫码头')):
        return 'Explicit OSM agency/route metadata identifies the neighbouring Kinmen bus network, outside the Xiamen operating catalogue.'
    return None

def project(lon, lat):
    return ((lon-118.15)*111320*math.cos(math.radians(24.60)),
            (lat-24.60)*111320)

def utm50(lon,lat):
    """WGS84 UTM zone 50N; avoids adding pyproj to the portable runtime."""
    a=6378137.;e2=0.0066943799901413165;k=.9996
    phi=math.radians(lat);delta=math.radians(lon-117.)
    ep=e2/(1-e2);n=a/math.sqrt(1-e2*math.sin(phi)**2)
    t=math.tan(phi)**2;c=ep*math.cos(phi)**2;aa=math.cos(phi)*delta
    m=a*((1-e2/4-3*e2**2/64-5*e2**3/256)*phi
         -(3*e2/8+3*e2**2/32+45*e2**3/1024)*math.sin(2*phi)
         +(15*e2**2/256+45*e2**3/1024)*math.sin(4*phi)
         -35*e2**3/3072*math.sin(6*phi))
    x=k*n*(aa+(1-t+c)*aa**3/6+(5-18*t+t*t+72*c-58*ep)*aa**5/120)+500000
    y=k*(m+n*math.tan(phi)*(aa*aa/2+(5-t+9*c+4*c*c)*aa**4/24+(61-58*t+t*t+600*c-330*ep)*aa**6/720))
    return x,y

def atomic_json(path, data):
    tmp = path.with_suffix(path.suffix+'.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)

def download(target, endpoint=None):
    w,s,e,n = BBOX
    box=f'<bbox-query s="{s}" w="{w}" n="{n}" e="{e}"/>'
    def query(kind, key, value, regex=False):
        attr='regv' if regex else 'v'
        return f'<query type="{kind}"><has-kv k="{key}" {attr}="{value}"/>{box}</query>'
    layers={
        'subway':query('way','railway','subway'),
        'future_subway':'<union>'+query('way','railway','construction').replace('</query>', '<has-kv k="construction" v="subway"/></query>')+query('way','railway','proposed').replace('</query>', '<has-kv k="proposed" v="subway"/></query>')+'</union>',
        'stations':'<union>'+''.join(query(t,'railway','^(station|halt)$',True)+query(t,'public_transport','station') for t in ('node','way','relation'))+'</union>',
        'coast':query('way','natural','coastline'),
        'roads':query('way','highway','^(motorway|trunk|primary|secondary)$',True),
        'water':query('way','natural','water'),
        'relations':query('relation','route','subway')}
    elements={};sources={};errors={}
    for name,selection in layers.items():
        layer_path=target.parent/(name+'.osm.xml')
        success=False
        for server in ([endpoint] if endpoint else SERVERS):
            print(f'Downloading layer: {name} from {server}',flush=True)
            q='<osm-script output="xml" timeout="50">'+selection
            if name!='relations':q+='<union><item/><recurse type="way-node"/></union>'
            q+='<print mode="body"/></osm-script>'
            try:
                req=urllib.request.Request(server+'?'+urllib.parse.urlencode({'data':q}),headers={'User-Agent':'XiamenMetro-SUMO/3.1','Accept':'application/xml'})
                # A configurable proxy can be selected explicitly with --use-proxy.
                opener=urllib.request.build_opener() if os.environ.get('XIAMEN_MAP_USE_PROXY')=='1' else urllib.request.build_opener(urllib.request.ProxyHandler({}))
                started=time.monotonic()
                with opener.open(req,timeout=40) as response:
                    chunks=[];size=0
                    while True:
                        chunk=response.read(65536)
                        if not chunk:break
                        chunks.append(chunk);size+=len(chunk)
                        if time.monotonic()-started>100 or size>64*1024*1024:
                            raise TimeoutError('Map layer exceeded download time/size limit')
                    content=b''.join(chunks)
                osm=ET.fromstring(content)
                if osm.tag!='osm':raise ValueError('Non-OSM response')
                remark=osm.find('remark')
                partial=remark is not None
                if partial and (name in ('subway','stations') or not osm.findall('way')):
                    raise ValueError('Incomplete required/empty OSM response')
                if partial:
                    errors.setdefault(name,[]).append(remark.text or 'Partial layer response')
                if name in ('subway','stations') and len(osm)<5:raise ValueError('Required layer is empty')
                layer_path.write_bytes(content)
                for item in osm:
                    if item.tag in ('node','way','relation'):elements[(item.tag,item.get('id'))]=item
                sources[name]={'endpoint':server,'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'partial':partial}
                success=True;break
            except Exception as exc:
                errors.setdefault(name,[]).append(f'{type(exc).__name__}: {exc}')
                print(f'{name}: {exc}',flush=True)
        if not success and name in ('subway','stations'):
            raise RuntimeError(f'Required layer {name} could not be downloaded; previous map preserved.')
    merged=ET.Element('osm',version='0.6',generator='XiamenMetro OSM layer merger')
    order={'node':0,'way':1,'relation':2}
    for key,item in sorted(elements.items(),key=lambda pair:(order[pair[0][0]],int(pair[0][1]))):merged.append(item)
    ET.ElementTree(merged).write(target,encoding='utf-8',xml_declaration=True)
    return {'layers':sources,'layer_errors':errors,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}

def prepare(osm_path, output, provenance):
    osm = ET.parse(osm_path).getroot()
    nodes = {v.get('id'):v for v in osm.findall('node')}
    ways = {v.get('id'):v for v in osm.findall('way')}
    features = []; candidates = {}; relations = []
    def tags(item):return {x.get('k'):x.get('v') for x in item.findall('tag')}
    def coords(item):
        if item.tag == 'node': return [(float(item.get('lon')),float(item.get('lat')))]
        if item.tag == 'way':
            if any(x.get('ref') not in nodes for x in item.findall('nd')):return []
            return [(float(nodes[x.get('ref')].get('lon')),float(nodes[x.get('ref')].get('lat'))) for x in item.findall('nd')]
        return [p for m in item.findall('member') if m.get('type')=='node' and m.get('ref') in nodes for p in coords(nodes[m.get('ref')])]
    def normalized(name):return name.replace('地铁站','').removesuffix('站').strip()
    for item in osm:
        t=tags(item); pts=coords(item)
        if item.tag == 'way' and len(pts)>1:
            kind = ('rail' if t.get('railway') in ('subway','light_rail','rail') else
                    'future_rail' if t.get('railway') in ('construction','proposed') and t.get('construction',t.get('proposed'))=='subway' else
                    'coast' if t.get('natural')=='coastline' else
                    'water' if t.get('natural')=='water' else
                    'green' if t.get('landuse') in ('forest','grass') or t.get('leisure')=='park' else
                    'road' if t.get('highway') else None)
            if kind:
                features.append({'id':item.get('id'),'kind':kind,'points':[project(*p) for p in pts],
                                 'closed':pts[0]==pts[-1], 'railway':t.get('railway'), 'highway':t.get('highway'), 'name':t.get('name','')})
        if t.get('route')=='subway':
            relations.append({'id':item.get('id'),'name':t.get('name',''),'ref':t.get('ref',''),
                              'way_ids':[m.get('ref') for m in item.findall('member') if m.get('type')=='way']})
        if pts and (t.get('railway') in ('station','halt') or t.get('public_transport')=='station'):
            lon=sum(p[0] for p in pts)/len(pts);lat=sum(p[1] for p in pts)/len(pts)
            if not BBOX[0]<=lon<=BBOX[2] or not BBOX[1]<=lat<=BBOX[3]:continue
            for name in (t.get('name'), t.get('name:zh')):
                if name:
                    key=normalized(name)
                    priority = (3 if t.get('station')=='subway' or t.get('subway')=='yes' else 1)+(1 if item.tag=='node' else 0)
                    if key not in candidates or priority>candidates[key]['priority']:
                        candidates[key]={'name':name,'lon':lon,'lat':lat,'point':project(lon,lat),
                                         'osm_id':item.get('id'),'osm_type':item.tag,'priority':priority,
                                         'railway':t.get('railway'),'station':t.get('station')}
    # Assemble split coast ways into closed islands, without inventing boundaries.
    coast={key:[n.get('ref') for n in way.findall('nd')] for key,way in ways.items() if tags(way).get('natural')=='coastline'}
    ends={}
    for key,ids in coast.items():
        if len(ids)>1:
            ends.setdefault(ids[0],[]).append(key);ends.setdefault(ids[-1],[]).append(key)
    unused=set(coast)
    while unused:
        key=unused.pop();chain=list(coast[key])
        if len(chain)<2:continue
        while chain[-1]!=chain[0]:
            options=[k for k in ends.get(chain[-1],[]) if k in unused]
            if not options:break
            nxt=options[0];unused.remove(nxt);part=coast[nxt]
            if part[0]!=chain[-1]:part=list(reversed(part))
            chain.extend(part[1:])
        if chain[-1]==chain[0] and len(chain)>10 and all(k in nodes for k in chain):
            pts=[project(float(nodes[k].get('lon')),float(nodes[k].get('lat'))) for k in chain]
            area=abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(pts,pts[1:])))/2
            if area>50000:features.append({'id':'island_'+key,'kind':'land','points':pts,'closed':True})
    catalogue=json.loads((ROOT/'lines.json').read_text(encoding='utf-8'))
    found={}; missing={}; counts={}
    for line in catalogue['lines']:
        lid=str(line['id']);counts[lid]={'total':len(line['names']),'matched':0};missing[lid]=[]
        for name in line['names']:
            match=candidates.get(normalized(name))
            if match:
                found[name]=match;counts[lid]['matched']+=1
            else:missing[lid].append(name)
    missing_unique=sorted({n for ns in missing.values() for n in ns})
    report={'source':'OpenStreetMap contributors','license':'ODbL 1.0',
            'source_url':'https://www.openstreetmap.org/copyright',
            'downloaded_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),
            'bbox_wgs84':BBOX,**provenance,'osm_nodes':len(nodes),'osm_ways':len(ways),
            'subway_relations':relations,'station_coverage':counts,'missing_by_line':missing,
            'missing_unique':missing_unique,
            'limitations':['OSM completeness varies; missing station coordinates remain unknown.',
                          'Station connectors are illustrative, not surveyed track geometry.',
                          'Existing simulation network and timetable remain the original schematic model.']}
    if len(features)<10 or len(found)<5:raise ValueError('Insufficient usable map/station data; cache unchanged')
    atomic_json(output/'map.json',{'features':features,'stations':found,'report':report})
    atomic_json(output/'coverage.json',report)
    return report

def convert(osm_path, output):
    sys.path.insert(0,str(ROOT))
    from network_engine import sumo_working_root
    working=sumo_working_root()
    osm_path=working/osm_path.resolve().relative_to(ROOT)
    output=working/output.resolve().relative_to(ROOT)
    binary=working/'runtime/sumo/bin/netconvert.exe'
    cfg=output/'xiamen.osm.sumocfg'; temporary=output/'xiamen.pending.net.xml'
    command=[str(binary),'--osm-files',str(osm_path),'-o',str(temporary),
             '--keep-edges.by-vclass','passenger,bus,subway,rail_urban',
             '--geometry.remove','true',
             '--junctions.join','true','--no-turnarounds','true',
             '--ptstop-output',str(output/'xiamen.stops.add.xml'),
             '--output.original-names','true','--error-log',str(output/'conversion.log')]
    result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace')
    (output/'conversion-output.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
    if result.returncode:raise RuntimeError('SUMO netconvert failed; see maps/osm/conversion-output.log')
    ET.parse(temporary);temporary.replace(output/'xiamen.net.xml')
    location=ET.parse(output/'xiamen.net.xml').getroot().find('location')
    if '+zone=50 ' not in location.get('projParameter',''):
        raise ValueError('Unexpected map projection; expected UTM50N')
    offset=tuple(map(float,location.get('netOffset').split(',')))
    def net_point(node):
        x,y=utm50(float(node.get('lon')),float(node.get('lat')))
        return x+offset[0],y+offset[1]
    osm=ET.parse(osm_path).getroot();nodes={n.get('id'):n for n in osm.findall('node')}
    additional=ET.Element('additional')
    for way in osm.findall('way'):
        tags={t.get('k'):t.get('v') for t in way.findall('tag')}
        if tags.get('natural') not in ('coastline','water'):continue
        points=[net_point(nodes[n.get('ref')]) for n in way.findall('nd') if n.get('ref') in nodes]
        if len(points)<2:continue
        ET.SubElement(additional,'poly',id='osm_'+way.get('id'),type=tags['natural'],color='0.24,0.52,0.64',layer='-10',fill='true' if tags['natural']=='water' and points[0]==points[-1] else 'false',shape=' '.join(f'{x:.2f},{y:.2f}' for x,y in points))
    ET.ElementTree(additional).write(output/'xiamen.context.add.xml',encoding='utf-8',xml_declaration=True)
    build_native_view(osm_path, output)
    cfg.write_text('<?xml version="1.0" encoding="UTF-8"?><configuration><input><net-file value="xiamen.net.xml"/><additional-files value="xiamen.context.add.xml,xiamen.stops.add.xml,xiamen.transit.add.xml"/></input><time><end value="3600"/></time><gui_only><gui-settings-file value="xiamen.view.xml"/></gui_only></configuration>',encoding='utf-8')
    print('Separate real-geometry SUMO inspection scene built.',flush=True)

def build_native_view(osm_path, output):
    """OSM geometry overlays, source station labels and a quiet SUMO map theme."""
    osm=ET.parse(osm_path).getroot()
    nodes={node.get('id'):node for node in osm.findall('node')}
    ways={way.get('id'):way for way in osm.findall('way')}
    location=ET.parse(output/'xiamen.net.xml').getroot().find('location')
    offset=tuple(map(float,location.get('netOffset').split(',')))
    def projected(lon,lat):
        x,y=utm50(lon,lat);return x+offset[0],y+offset[1]
    def points(way):
        return [projected(float(nodes[nd.get('ref')].get('lon')),float(nodes[nd.get('ref')].get('lat'))) for nd in way.findall('nd') if nd.get('ref') in nodes]
    def tags(item):return {t.get('k'):t.get('v') for t in item.findall('tag')}
    catalogue=json.loads((ROOT/'lines.json').read_text(encoding='utf-8'))
    line_colours={str(line['id']):line['color'] for line in catalogue['lines']}
    rail_colours={};bus_ways={}
    for relation in osm.findall('relation'):
        info=tags(relation);route=info.get('route')
        if route not in ('subway','bus'):continue
        if route=='bus' and nearby_bus_exclusion_reason(info):continue
        raw_ref=info.get('ref','').removeprefix('L').removesuffix('号线').strip()
        colour=line_colours.get(raw_ref,info.get('colour','#6E84A3') if route=='subway' else '#D6A34D')
        for member in relation.findall('member'):
            if member.get('type')!='way' or 'platform' in member.get('role',''):continue
            (rail_colours if route=='subway' else bus_ways)[member.get('ref')]=(colour,info.get('ref',info.get('name','')))
    additional=ET.Element('additional');rail_count=0;bus_count=0
    for ident,way in ways.items():
        info=tags(way);kind='rail' if info.get('railway') in ('subway','light_rail') else 'bus' if ident in bus_ways else None
        if not kind:continue
        shape=points(way)
        if len(shape)<2:continue
        colour,ref=(rail_colours.get(ident,('#6E84A3','OSM轨道'))) if kind=='rail' else bus_ways[ident]
        ET.SubElement(additional,'poly',id=f'geo_{kind}_{ident}',type=f'OSM {kind} {ref}',color=colour,
            layer='8' if kind=='rail' else '5',fill='false',lineWidth='65' if kind=='rail' else '28',
            shape=' '.join(f'{x:.2f},{y:.2f}' for x,y in shape))
        if kind=='rail':rail_count+=1
        else:bus_count+=1
    map_path=output/'map.json' if (output/'map.json').exists() else ROOT/'maps/osm/map.json'
    map_cache=json.loads(map_path.read_text(encoding='utf-8'))
    stations=map_cache['stations']
    island_count=0
    for feature in map_cache['features']:
        if feature['kind']!='land' or not feature.get('closed'):continue
        shape=[projected(118.15+p[0]/(111320*math.cos(math.radians(24.60))),24.60+p[1]/111320) for p in feature['points']]
        ET.SubElement(additional,'poly',id=f'geo_island_{island_count}',type='OSM closed coastline',color='221,234,222',
            layer='-15',fill='true',shape=' '.join(f'{x:.2f},{y:.2f}' for x,y in shape))
        island_count+=1
    for index,(name,station) in enumerate(stations.items()):
        served=[str(line['id']) for line in catalogue['lines'] if name in line['names']]
        x,y=projected(station['lon'],station['lat'])
        element=ET.SubElement(additional,'poi',id=f'geo_station_{index}',type=name,name=name,
            color=line_colours.get(served[0] if served else '', '#405C77'),layer='20',
            x=f'{x:.2f}',y=f'{y:.2f}',width='90',height='90')
        ET.SubElement(element,'param',key='lines',value=','.join(served))
        ET.SubElement(element,'param',key='osm_source',value=f'https://www.openstreetmap.org/{station["osm_type"]}/{station["osm_id"]}')
    ET.ElementTree(additional).write(output/'xiamen.transit.add.xml',encoding='utf-8',xml_declaration=True)
    view=ET.Element('viewsettings');scheme=ET.SubElement(view,'scheme',name='XiamenGeoTransit')
    ET.SubElement(scheme,'background',backgroundColor='235,243,248',showGrid='0')
    edges=ET.SubElement(scheme,'edges',laneEdgeMode='0',laneShowBorders='0',showLinkDecals='0',
        showLinkRules='0',showRails='1',widthExaggeration='1.2',minSize='0.15',
        edgeName_show='0',streetName_show='0')
    uniform=ET.SubElement(edges,'colorScheme',name='uniform')
    ET.SubElement(uniform,'entry',color='149,169,183',threshold='0')
    ET.SubElement(scheme,'junctions',drawJunctionShape='0',junctionName_show='0')
    ET.SubElement(scheme,'vehicles',vehicleMode='0',vehicleQuality='2',vehicle_exaggeration='1.5',vehicle_minSize='3')
    ET.SubElement(scheme,'persons',personMode='0',personQuality='0',person_minSize='4',person_exaggeration='3')
    ET.SubElement(scheme,'pois',poi_minSize='4',poi_exaggeration='1',poiName_show='0',poiType_show='1',
        poiType_size='12',poiType_color='39,62,82',poiType_constantSize='0')
    ET.SubElement(scheme,'polys',polyName_show='0',polyType_show='0')
    ET.SubElement(scheme,'additionals',addName_show='0',addFullName_show='0')
    ET.ElementTree(view).write(output/'xiamen.view.xml',encoding='utf-8',xml_declaration=True)
    atomic_json(output/'native_view_report.json',dict(station_labels=len(stations),rail_way_overlays=rail_count,
        bus_way_overlays=bus_count,closed_coast_islands=island_count,projection='WGS84/UTM 50N + SUMO offset',
        view='XiamenGeoTransit',source='OSM nodes, ways and relations; no invented track connectors'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--offline',action='store_true',help='Rebuild from cached OSM without downloading')
    parser.add_argument('--endpoint');parser.add_argument('--use-proxy',action='store_true');parser.add_argument('--skip-convert',action='store_true')
    args=parser.parse_args()
    if args.use_proxy:os.environ['XIAMEN_MAP_USE_PROXY']='1'
    output=ROOT/'maps/osm';output.mkdir(parents=True,exist_ok=True)
    osm_path=output/'xiamen.osm.xml'
    if not args.offline and not args.endpoint and osm_path.exists():
        # Once a cache exists, ordinary updates must remain additive. The old
        # whole-city request could otherwise replace a completed map with a
        # truncated response. Explicit --endpoint retains the legacy API.
        import complete_map
        previous_argv=sys.argv
        try:
            sys.argv=[str(ROOT/'tools/complete_map.py')]+(['--skip-convert'] if args.skip_convert else [])
            complete_map.main()
        finally:
            sys.argv=previous_argv
        return
    provenance={}
    if not args.offline:
        # Keep each download in a staging directory until processing succeeds.
        staging=output/('download_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'))
        staging.mkdir();osm_path=staging/'xiamen.osm.xml'
        provenance=download(osm_path,args.endpoint)
    elif not osm_path.exists():raise FileNotFoundError('No cached OSM yet. Run without --offline first.')
    else:
        existing_report=output/'coverage.json'
        previous=json.loads(existing_report.read_text(encoding='utf-8')) if existing_report.exists() else {}
        provenance={k:v for k,v in previous.items() if k in ('layers','layer_errors','endpoint')}
        provenance.update(sha256=hashlib.sha256(osm_path.read_bytes()).hexdigest(),cache_rebuild=True)
    build_output=osm_path.parent
    if not args.skip_convert:convert(osm_path,build_output)
    report=prepare(osm_path,build_output,provenance)
    if build_output!=output:
        import shutil
        existing=[p for p in output.iterdir() if p.is_file()]
        if existing:
            history=output/('previous_'+datetime.datetime.now().strftime('%Y%m%d_%H%M%S'));history.mkdir()
            for p in existing:shutil.copy2(p,history/p.name)
        for p in build_output.iterdir():
            if p.is_file():shutil.copy2(p,output/p.name)
    if not args.skip_convert and (output/'bus_catalogue.json').exists():
        import complete_map
        complete_map.rebuild_bus_scene()
    print(json.dumps({'ways':report['osm_ways'],'station_coverage':report['station_coverage'],
                      'missing_unique':report['missing_unique']},ensure_ascii=False,indent=2),flush=True)

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print(str(exc),file=sys.stderr,flush=True);sys.exit(1)
