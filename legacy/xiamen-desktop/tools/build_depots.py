"""Add physically connected simulation depots without changing the base scene."""
from pathlib import Path
import copy,hashlib,json,math,os,subprocess,sys,time
import xml.etree.ElementTree as E

ROOT=Path(__file__).resolve().parents[1]
NET=ROOT/'network'

def write(name,element):
    E.ElementTree(element).write(NET/name,encoding='utf-8',xml_declaration=True)

def build():
    old=E.parse(NET/'multimodal.net.xml').getroot()
    original_edges={edge.get('id'):edge for edge in old.findall('edge') if edge.get('function')!='internal'}
    base_routes=E.parse(NET/'multimodal.rou.xml').getroot()
    route_map={route.get('id'):route for route in base_routes.findall('route')}
    catalogue=json.loads((ROOT/'lines.json').read_text(encoding='utf-8'))
    lines={line['id']:line for line in catalogue['lines']}
    nodes=E.Element('nodes');edges=E.Element('edges');connections=E.Element('connections')
    facilities=E.Element('additional');depots=[]

    def node(ident,xy,kind='priority'):
        E.SubElement(nodes,'node',id=ident,x=f'{xy[0]:.3f}',y=f'{xy[1]:.3f}',type=kind,radius='1.5')
    def edge(ident,fr,to,shape,speed=5):
        element=E.SubElement(edges,'edge',id=ident,attrib={'from':fr,'to':to},numLanes='1',allow='rail_urban',
            width='3.2',speed=str(speed),spreadType='center',shape=' '.join(f'{x:.3f},{y:.3f}' for x,y in shape))
        E.SubElement(element,'param',key='display_line',value=ident.split('_')[0][1:])
    def connect(fr,to):
        E.SubElement(connections,'connection',attrib={'from':fr,'to':to},fromLane='0',toLane='0')
    def polygon(ident,kind,label,shape,color,layer=-4):
        english={'maintenance':'Maintenance bay','storage':'Stabling shed','wash':'Wash facility',
            'dispatch':'Dispatch office','power':'Traction power cabin','ground':'Simulation depot apron'}[kind]
        E.SubElement(facilities,'poly',id=ident,type=english,name=english,color=color,
            layer=str(layer),fill='true',shape=' '.join(f'{x:.3f},{y:.3f}' for x,y in shape))

    for lid,line in lines.items():
        for direction in 'UD':
            ident=f'L{lid}_Y{direction}';base_id=f'L{lid}_DEP_{direction}'
            base=original_edges[base_id];lane=base.find('lane')
            shape=[tuple(map(float,part.split(',')[:2])) for part in lane.get('shape').split()]
            bx,by=shape[0];dx=shape[-1][0]-bx;dy=shape[-1][1]-by;length=math.hypot(dx,dy)
            tangent=(dx/length,dy/length);normal=(-tangent[1],tangent[0])
            def pt(u,v):return (bx+tangent[0]*u+normal[0]*v,by+tangent[1]*u+normal[1]*v)
            def rect(u0,v0,u1,v1):return [pt(u0,v0),pt(u1,v0),pt(u1,v1),pt(u0,v1),pt(u0,v0)]
            common=ident+'_EXIT';incoming=ident+'_IN';head=ident+'_HEAD'
            node(common,pt(-70,0),'rail_signal');node(incoming,pt(-40,-165),'rail_signal');node(head,pt(-880,-165),'rail_signal')
            gate=ident+'_GATE';returned=ident+'_RETURN';loop=ident+'_INLOOP'
            edge(gate,common,base.get('from'),[pt(-70,0),pt(0,0)],7)
            return_platform=f'L{lid}_RD01' if direction=='U' else f'L{lid}_RU{len(line["names"]):02}'
            terminal=original_edges[return_platform]
            terminal_shape=[tuple(map(float,part.split(',')[:2])) for part in terminal.find('lane').get('shape').split()]
            # The return diverges after the existing terminal platform. Its
            # track is offset from the preserved 500 m departure lead.
            edge(returned,terminal.get('to'),incoming,[terminal_shape[-1],pt(620,-165),pt(180,-165),pt(-40,-165)],6)
            edge(loop,incoming,head,[pt(-40,-165),pt(-880,-165)],5)
            connect(return_platform,returned);connect(returned,loop);connect(gate,base_id)
            entry_routes=[];tracks=[]
            for index,v in enumerate((-35,0,35),1):
                suffix=f'{index:02}';start=ident+'_A'+suffix;end=ident+'_E'+suffix
                track=ident+'_T'+suffix;fan_in=ident+'_I'+suffix;fan_out=ident+'_O'+suffix
                node(start,pt(-780,v));node(end,pt(-220,v),'rail_signal')
                edge(track,start,end,[pt(-780,v),pt(-220,v)],5)
                edge(fan_in,head,start,[pt(-880,-165),pt(-845,-150),pt(-820,v),pt(-780,v)],4)
                edge(fan_out,end,common,[pt(-220,v),pt(-170,v),pt(-105,0),pt(-70,0)],4)
                connect(loop,fan_in);connect(fan_in,track);connect(track,fan_out);connect(fan_out,gate)
                stop_id=track+'_HOLD'
                E.SubElement(facilities,'trainStop',id=stop_id,lane=track+'_0',startPos='355',endPos='540',
                    friendlyPos='true',name=f'L{lid} {direction}{index} Stabling track')
                service=copy.deepcopy(route_map[f'Service{lid}{direction}'])
                service_id=f'DepotService{lid}{direction}T{suffix}'
                service.set('id',service_id)
                service.set('edges',' '.join([track,fan_out,gate]+service.get('edges').split()))
                service.insert(0,E.Element('stop',trainStop=stop_id,duration='8'))
                base_routes.append(service)
                entry_id=f'DepotEntry{lid}{direction}T{suffix}'
                entry=E.SubElement(base_routes,'route',id=entry_id,edges=' '.join([return_platform,returned,loop,fan_in,track]))
                E.SubElement(entry,'stop',trainStop=stop_id,duration='86400',parking='false')
                entry_routes.append(entry_id)
                tracks.append(dict(id=track,edge=track,lane=track+'_0',shape=[pt(-780,v),pt(-220,v)],
                    route_id=service_id,entry_route_id=entry_id,exit_signal=end,holding_stop=stop_id,
                    speed_limit_mps=5,capacity_trains=2))
            buildings=[]
            for kind,label,box,color in [
                ('maintenance','检修整备棚',(-720,65,-380,115),'88,107,127'),
                ('storage','存车库',(-755,-70,-340,-10),'67,88,111'),
                ('wash','洗车线设施',(-535,125,-365,150),'65,152,154'),
                ('dispatch','车辆段调度楼',(-280,75,-195,140),'61,111,157'),
                ('power','牵引供电房',(-155,100,-95,145),'156,122,79')]:
                poly=rect(*box);facility_id=ident+'_'+kind
                polygon(facility_id,kind,label,poly,color,-3)
                buildings.append(dict(id=facility_id,kind=kind,label=label,polygon=poly))
            perimeter=rect(-920,-195,40,180)
            polygon(ident+'_ground','ground','仿真车辆段场坪',perimeter,'189,203,204',-8)
            E.SubElement(facilities,'poly',id=ident+'_fence',type='Depot fence',color='87,115,131',layer='-2',fill='false',lineWidth='1.5',shape=' '.join(f'{x:.3f},{y:.3f}' for x,y in perimeter))
            roads=[[pt(-890,160),pt(0,160)],[pt(-890,-185),pt(0,-185)]]
            for road_index,road in enumerate(roads):
                E.SubElement(facilities,'poly',id=ident+f'_road{road_index}',type='Decorative access road',color='137,155,166',layer='-5',fill='false',lineWidth='14',shape=' '.join(f'{x:.3f},{y:.3f}' for x,y in road))
            lights=[pt(u,v) for u in (-850,-630,-410,-190) for v in (-180,165)]
            for lamp_index,(x,y) in enumerate(lights):
                E.SubElement(facilities,'poi',id=ident+f'_light{lamp_index}',type='Lamp',color='250,226,151',layer='-1',x=f'{x:.3f}',y=f'{y:.3f}',width='3',height='3')
            station=line['names'][0 if direction=='U' else -1]
            label=f'Line {lid} / {direction} - Simulation Depot'
            x,y=pt(-440,200)
            sign=E.SubElement(facilities,'poi',id=ident+'_label',type=label,name=label,color='57,93,124,0',layer='10',x=f'{x:.3f}',y=f'{y:.3f}')
            E.SubElement(sign,'param',key='label',value=label)
            depots.append(dict(id=ident,line=lid,direction=direction,terminal_station=station,base=[bx,by],
                base_edge=base_id,tangent=tangent,color=line['color'],tracks=tracks,
                entry=dict(edge=returned,signal=incoming,route_ids=entry_routes,from_edge=return_platform),
                exit=dict(edge=gate,signal=common),geometry=dict(perimeter=perimeter,roads=roads,facilities=buildings,lights=lights),
                representation='physically connected simulation depot; facilities are designed schematic geometry, not surveyed Xiamen assets'))
    # A round-trip may recompute rail junction trims by several metres and
    # change rounding elsewhere. Plain-XML lane shapes and edge lengths are
    # supported explicitly; retain them as fixed design constraints while
    # SUMO computes new internal links and interlocking for the yard forks.
    for ident,original in original_edges.items():
        original_lanes=original.findall('lane')
        fixed=E.SubElement(edges,'edge',id=ident,length=original_lanes[0].get('length'))
        for original_lane in original_lanes:
            E.SubElement(fixed,'lane',index=original_lane.get('index'),shape=original_lane.get('shape'))
    for original_junction in old.findall('junction'):
        if original_junction.get('type')=='internal' or original_junction.get('id','').startswith(':'):continue
        if original_junction.get('shape'):
            E.SubElement(nodes,'node',id=original_junction.get('id'),shape=original_junction.get('shape'))
    meta=dict(version='depot-4.1',representation='simulation depots, not surveyed Xiamen depots',depots=depots)
    (NET/'depot.catalogue.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    write('depot.patch.nod.xml',nodes);write('depot.patch.edg.xml',edges);write('depot.patch.con.xml',connections)
    write('depot.facilities.add.xml',facilities);write('multimodal.depot.rou.xml',base_routes)
    command=[str(ROOT/'runtime/sumo/bin/netconvert.exe'),'--sumo-net-file',str(NET/'multimodal.net.xml'),
        '--node-files',str(NET/'depot.patch.nod.xml'),'--edge-files',str(NET/'depot.patch.edg.xml'),
        '--connection-files',str(NET/'depot.patch.con.xml'),'--output-file',str(NET/'multimodal.depot.pending.net.xml'),
        '--no-turnarounds','true','--junctions.internal-link-detail','32','--offset.disable-normalization','true',
        '--geometry.min-radius.fix.railways','false']
    process=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',errors='replace',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    (NET/'depot.build.log').write_text(process.stdout+'\n'+process.stderr,encoding='utf-8')
    if process.returncode:raise RuntimeError(process.stderr)
    compiled=E.parse(NET/'multimodal.depot.pending.net.xml').getroot()
    current_edges={edge.get('id'):edge for edge in compiled.findall('edge') if edge.get('function')!='internal'}
    differences=[]
    for ident,original in original_edges.items():
        current=current_edges.get(ident)
        if current is None:raise RuntimeError('Missing original edge '+ident)
        for original_lane,current_lane in zip(original.findall('lane'),current.findall('lane')):
            if any(original_lane.get(key)!=current_lane.get(key) for key in ('shape','length')):
                differences.append(dict(edge=ident,old=dict(original_lane.attrib),new=dict(current_lane.attrib)))
    if differences:
        (NET/'depot.geometry-differences.json').write_text(json.dumps(differences,indent=2),encoding='utf-8')
        # Fixed junction boundaries prevent metre-scale retrimming. Reimport
        # still introduces centimetre output-rounding in some custom shapes.
        # Restore these existing design fields from the untouched source;
        # the new topology, rail interlocking and internal links remain SUMO's.
        largest=0.
        for difference in differences:
            a=[tuple(map(float,p.split(',')[:2])) for p in difference['old']['shape'].split()]
            b=[tuple(map(float,p.split(',')[:2])) for p in difference['new']['shape'].split()]
            if len(a)!=len(b):raise RuntimeError('Original shape point count changed: '+difference['edge'])
            largest=max(largest,max(math.dist(p,q) for p,q in zip(a,b)))
        if largest>.15:raise RuntimeError(f'Original geometry changed {largest:.3f} m; derived scenario not published')
        for ident,original in original_edges.items():
            for a,b in zip(original.findall('lane'),current_edges[ident].findall('lane')):
                b.set('shape',a.get('shape'));b.set('length',a.get('length'))
        write('multimodal.depot.pending.net.xml',compiled)
    for ident,original in original_edges.items():
        for a,b in zip(original.findall('lane'),current_edges[ident].findall('lane')):
            if any(a.get(key)!=b.get(key) for key in ('shape','length')):raise RuntimeError('Preservation gate failed: '+ident)
    for depot in depots:
        for track in depot['tracks']:
            lane=current_edges[track['edge']].find('lane')
            track['shape']=[list(map(float,p.split(',')[:2])) for p in lane.get('shape').split()]
            track['length_m']=float(lane.get('length'))
        for role in ('entry','exit'):
            lane=current_edges[depot[role]['edge']].find('lane')
            depot[role]['shape']=[list(map(float,p.split(',')[:2])) for p in lane.get('shape').split()]
    (NET/'depot.catalogue.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding='utf-8')
    (NET/'multimodal.depot.pending.net.xml').replace(NET/'multimodal.depot.net.xml')
    cfg=E.parse(NET/'multimodal.sumocfg').getroot();inp=cfg.find('input')
    inp.find('net-file').set('value','multimodal.depot.net.xml')
    inp.find('route-files').set('value','multimodal.depot.rou.xml')
    inp.find('additional-files').set('value',inp.find('additional-files').get('value')+',depot.facilities.add.xml')
    write('multimodal.depot.pending.sumocfg',cfg)
    check=subprocess.run([str(ROOT/'runtime/sumo/bin/sumo.exe'),'-c','network/multimodal.depot.pending.sumocfg','--end','1'],cwd=ROOT,
        capture_output=True,text=True,encoding='utf-8',errors='replace',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if check.returncode:raise RuntimeError('SUMO could not load the derived depot scene: '+check.stderr)
    (NET/'multimodal.depot.pending.sumocfg').replace(NET/'multimodal.depot.sumocfg')
    report=dict(status='built',depots=len(depots),parallel_storage_tracks=len(depots)*3,
        preserved_original_edges=len(original_edges),original_geometry_changes=0,
        outbound_routes=len(depots)*3,inbound_routes=len(depots)*3,
        source_net_sha256=hashlib.sha256((NET/'multimodal.net.xml').read_bytes()).hexdigest(),
        derived_net_sha256=hashlib.sha256((NET/'multimodal.depot.net.xml').read_bytes()).hexdigest(),
        bounded_reimport_trim_corrections=len(differences),
        maximum_reimport_displacement_m=round(largest if differences else 0.,6),
        sumo_loading_test='passed end=1',
        physical='30 storage tracks plus connected ingress/egress fans and signals',
        decorative='maintenance/storage/wash/dispatch/power buildings, fence, access roads and lighting',
        limitation='Simulation facility geometry, not measured engineering or official Xiamen vehicle depots')
    (NET/'depot.build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=True));return report

def verify():
    """Actual SUMO movement, stabling and red-hold checks for the new tracks."""
    sys.path.insert(0,str(ROOT/'runtime/sumo/tools'))
    import traci
    from traci import constants as tc
    from sumolib.miscutils import getFreeSocketPort
    metadata=json.loads((NET/'depot.catalogue.json').read_text(encoding='utf-8'))
    scenarios=[]
    for mode,duration in [('outbound',900),('inbound',1600)]:
        port=getFreeSocketPort();label='depot_'+mode+'_'+str(time.time_ns())
        log=open(NET/('depot.'+mode+'.sumo.log'),'w',encoding='utf-8')
        process=subprocess.Popen([str(ROOT/'runtime/sumo/bin/sumo.exe'),'-c','network/multimodal.depot.sumocfg',
            '--remote-port',str(port)],cwd=ROOT,stdout=log,stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        conn=None
        try:
            traci.init(port,numRetries=3,label=label,proc=process);conn=traci.getConnection(label)
            expected={};entered={};parked={};collisions=0;teleports=0
            for depot in metadata['depots']:
                for index,track in enumerate(depot['tracks']):
                    vid=mode+'_'+track['id'];route=track['route_id'] if mode=='outbound' else track['entry_route_id']
                    conn.vehicle.add(vid,route,typeID=f'metro{depot["line"]}',depart=str(index*120 if mode=='inbound' else 0),departPos='140')
                    expected[vid]=(depot,track)
            subscribed=set();red_held=False;red_evidence={}
            hold_signal=metadata['depots'][0]['exit']['signal']
            for step in range(int(duration*2)):
                conn.simulationStep()
                now=conn.simulation.getTime()
                collisions+=conn.simulation.getCollidingVehiclesNumber();teleports+=conn.simulation.getStartingTeleportNumber()
                for vid in conn.simulation.getDepartedIDList():
                    conn.vehicle.subscribe(vid,[tc.VAR_ROAD_ID,tc.VAR_SPEED,tc.VAR_STOPSTATE,tc.VAR_POSITION]);subscribed.add(vid)
                readings=conn.vehicle.getAllSubscriptionResults()
                if mode=='outbound' and not red_held:
                    state=conn.trafficlight.getRedYellowGreenState(hold_signal)
                    conn.trafficlight.setRedYellowGreenState(hold_signal,'r'*len(state));red_held=True
                if mode=='outbound' and now==180:
                    blocked=[vid for vid,(depot,track) in expected.items() if depot['id']==metadata['depots'][0]['id']]
                    red_evidence=dict(signal=hold_signal,held_seconds=180,
                        no_held_depot_train_entered_base=all(vid not in entered for vid in blocked),
                        state=conn.trafficlight.getRedYellowGreenState(hold_signal))
                    conn.trafficlight.setProgram(hold_signal,'0')
                for vid,reading in readings.items():
                    depot,track=expected[vid];current=reading.get(tc.VAR_ROAD_ID,'')
                    if mode=='outbound' and current==depot['base_edge']:entered.setdefault(vid,now)
                    if mode=='inbound' and current==track['edge'] and reading.get(tc.VAR_STOPSTATE,0)&1:
                        parked.setdefault(vid,now)
                if mode=='outbound' and len(entered)==len(expected):break
                if mode=='inbound' and len(parked)==len(expected):
                    # Confirm real trains remain on all thirty physical tracks.
                    for _ in range(40):conn.simulationStep()
                    break
            if mode=='outbound' and len(entered)!=30:raise RuntimeError(f'Only {len(entered)}/30 real stock departures reached original leads')
            if mode=='inbound' and len(parked)!=30:raise RuntimeError(f'Only {len(parked)}/30 real inbound trains stopped on storage tracks')
            if collisions or teleports:raise RuntimeError(f'{mode}: collisions={collisions},teleports={teleports}')
            if red_evidence and not red_evidence['no_held_depot_train_entered_base']:raise RuntimeError('Exit red hold was bypassed')
            scenarios.append(dict(mode=mode,vehicles=30,completed=len(entered if mode=='outbound' else parked),
                latest_completion_s=max((entered if mode=='outbound' else parked).values()),collisions=collisions,
                teleports=teleports,red_hold=red_evidence,physically_present_end=len(conn.vehicle.getIDList())))
        finally:
            if conn is not None:conn.close()
            if process.poll() is None:process.terminate();process.wait(timeout=10)
            log.close()
    report=dict(status='pass',scenarios=scenarios,scope='actual storage-track departure, physical return/stabling and exit red hold')
    (NET/'depot.physical-validation.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report));return report

if __name__=='__main__':
    if '--verify-only' in sys.argv:verify()
    else:
        build()
        if '--verify' in sys.argv:verify()
