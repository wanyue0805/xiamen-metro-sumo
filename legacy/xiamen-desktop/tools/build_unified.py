"""Build one shared SUMO network, depots and pedestrian transfer concourses."""
from pathlib import Path
import math,json,copy,subprocess,xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[1]
cat=json.loads((ROOT/'lines.json').read_text(encoding='utf-8'));configs={x['id']:x for x in cat['lines']};source={lid:json.loads((ROOT/f'network/line{lid}.stations.json').read_text(encoding='utf-8')) for lid in configs}
base={s['name']:(s['x'],s['y']) for s in source[1]}
anchors={1:base,2:{'天竺山':(-14000,14000),'鼎美':(-7600,12500),'马銮中心':(-6500,13000),'体育中心':(base['湖滨东路'][0]-800,base['湖滨东路'][1]+900),'吕厝':base['吕厝'],'五缘湾':(12000,12500)},3:{'厦门火车站':(base['湖滨东路'][0]-200,base['湖滨东路'][1]-700),'湖滨东路':base['湖滨东路'],'体育中心':(base['湖滨东路'][0]-800,base['湖滨东路'][1]+900),'火炬园':base['火炬园'],'五缘湾':(12000,12500),'洪坑':(23500,19000),'蔡厝':(30000,16500)},4:{'集美软件园北':(-4500,26000),'厦门北站':base['厦门北站'],'官浔':(12000,25500),'洪坑':(23500,19000),'前浯':(26000,17000)},6:{'角江路':(-16500,11500),'鼎美':(-7600,12500),'马銮中心':(-6500,13000),'官任':base['官任'],'华侨大学':(-1000,28000)}}
def unit(a,b):
 dx=b[0]-a[0];dy=b[1]-a[1];n=max(.001,math.hypot(dx,dy));return dx/n,dy/n

def bezier(a,b,ta,tb):
 d=math.dist(a,b)*.32;p1=(a[0]+ta[0]*d,a[1]+ta[1]*d);p2=(b[0]-tb[0]*d,b[1]-tb[1]*d);out=[]
 for k in range(49):
  t=k/48;u=1-t;out.append((u**3*a[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*b[0],u**3*a[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*b[1]))
 return out

points={};tangents={};shared={}
for lid,c in configs.items():
 names=c['names'];keys=sorted((names.index(n),p) for n,p in anchors[lid].items());coords=[]
 for i,name in enumerate(names):
  if name in anchors[lid]:coords.append(anchors[lid][name]);continue
  left=max((x for x in keys if x[0]<i),key=lambda x:x[0]);right=min((x for x in keys if x[0]>i),key=lambda x:x[0]);t=(i-left[0])/(right[0]-left[0]);a,b=left[1],right[1];dx,dy=unit(a,b);bend=min(300,math.dist(a,b)*.05)*math.sin(math.pi*t)
  coords.append((a[0]+t*(b[0]-a[0])-dy*bend,a[1]+t*(b[1]-a[1])+dx*bend))
 points[lid]=coords
 for i,name in enumerate(names):
  t=unit(coords[max(0,i-1)],coords[min(len(coords)-1,i+1)])
  if name not in shared:shared[name]={'point':coords[i],'tangent':t,'members':[]}
  shared[name]['members'].append(lid)
 for name,p in anchors[lid].items():
  if name in shared:shared[name]['point']=p
nodes=E.Element('nodes');edges=E.Element('edges');connections=E.Element('connections');add=E.Element('additional');routes=E.Element('routes');station_meta={};hubs={name:f'H{idx:03}' for idx,name in enumerate(shared,1)};ends={}

def add_edge(eid,fr,to,pts,allow='rail_urban',speed=22.2222,width=3.2):
 E.SubElement(edges,'edge',id=eid,attrib={'from':fr,'to':to},allow=allow,numLanes='1',width=str(width),speed=str(speed),spreadType='center',shape=' '.join(f'{x:.3f},{y:.3f}' for x,y in pts))

def connect(a,b):E.SubElement(connections,'connection',attrib={'from':a,'to':b},fromLane='0',toLane='0')

def project(center,tangent,u,v):return center[0]+u*tangent[0]-v*tangent[1],center[1]+u*tangent[1]+v*tangent[0]

def transform(xy,old,new):
 dx,dy=xy[0]-old['x'],xy[1]-old['y'];tx,ty=old['tangent'];u=dx*tx+dy*ty;v=-dx*ty+dy*tx
 return project((new['x'],new['y']),new['tangent'],u,v)

for name,hub in shared.items():E.SubElement(nodes,'node',id=hubs[name],x=str(hub['point'][0]),y=str(hub['point'][1]),z='8',type='priority')
for lid,c in configs.items():
 pre=f'L{lid}_';n=len(c['names']);meta=[];shape={}
 for i,name in enumerate(c['names'],1):
  common=shared[name];t=common['tangent'] if len(common['members'])>1 else unit(points[lid][max(0,i-2)],points[lid][min(n-1,i)]);offset=(common['members'].index(lid)-(len(common['members'])-1)/2)*90
  center=project(common['point'] if len(common['members'])>1 else points[lid][i-1],t,0,offset)
  s=copy.deepcopy(source[lid][i-1]);s.update(x=center[0],y=center[1],tangent=list(t),hub_id=hubs[name],hub_x=common['point'][0],hub_y=common['point'][1],line=lid);meta.append(s)
  for side,off in [('U',-8),('D',8)]:
   a=project(center,t,-130,off);b=project(center,t,130,off);ends[(lid,side,i)]=(a,b)
   for letter,p in [('a',a),('b',b)]:
    nid=f'{pre}{side}{i:02}{letter}';kind='priority' if (side,i,letter) in [('D',1,'a'),('U',n,'b')] else 'rail_signal';E.SubElement(nodes,'node',id=nid,x=str(p[0]),y=str(p[1]),type=kind,radius='1.5')
   pts=[a,b] if side=='U' else [b,a];eid=f'{pre}{side}{i:02}';shape[eid]=pts;add_edge(eid,f'{pre}{side}{i:02}'+('a' if side=='U' else 'b'),f'{pre}{side}{i:02}'+('b' if side=='U' else 'a'),pts,speed=c['speed_kmh']/3.6)
  entry=project(center,t,-15,65);pid=f'{pre}Foot{i:02}';E.SubElement(nodes,'node',id=pid,x=str(entry[0]),y=str(entry[1]),z='8',type='priority')
  foot=f'{pre}Walk{i:02}';hubp=common['point'];distance=math.dist(hubp,entry);s.update(walk_edge=foot,walk_back=foot+'R',walk_pos=distance*.55)
  add_edge(foot,hubs[name],pid,[hubp,entry],allow='pedestrian',speed=1.4,width=3);add_edge(foot+'R',pid,hubs[name],[entry,hubp],allow='pedestrian',speed=1.4,width=3);connect(foot,foot+'R')
 for i in range(1,n):
  for side in ['U','D']:
   pts=bezier(ends[(lid,side,i)][1],ends[(lid,side,i+1)][0],meta[i-1]['tangent'],meta[i]['tangent'])
   if side=='D':pts.reverse()
   eid=f'{pre}G{side}{i:02}';shape[eid]=pts;add_edge(eid,f'{pre}{side}{i:02}b' if side=='U' else f'{pre}{side}{i+1:02}a',f'{pre}{side}{i+1:02}a' if side=='U' else f'{pre}{side}{i:02}b',pts,speed=c['speed_kmh']/3.6)
   connect(f'{pre}{side}{i:02}' if side=='U' else f'{pre}{side}{i+1:02}',eid);connect(eid,f'{pre}{side}{i+1:02}' if side=='U' else f'{pre}{side}{i:02}')
 for i,side,rev,nxt,cross in [(n,'U','RU',f'D{n-1:02}','C_N'),(1,'D','RD','U02','C_S')]:
  old=f'{pre}{side}{i:02}';rid=f'{pre}{rev}{i:02}';pts=list(reversed(shape[old]));add_edge(rid,f'{pre}{side}{i:02}'+('b' if side=='U' else 'a'),f'{pre}{side}{i:02}'+('a' if side=='U' else 'b'),pts,speed=6);shape[rid]=pts;connect(old,rid)
  target=f'{pre}{nxt}';turn=bezier(pts[-1],shape[target][0],unit(pts[0],pts[-1]),unit(shape[target][0],shape[target][-1]));add_edge(pre+cross,f'{pre}{side}{i:02}'+('a' if side=='U' else 'b'),f'{pre}{nxt}'+('b' if nxt.startswith('D') else 'a'),turn,speed=10);connect(rid,pre+cross);connect(pre+cross,target)
 for direction,i,side,sign in [('U',1,'U',-1),('D',n,'D',1)]:
  station=meta[i-1];t=station['tangent'];bay_side='D' if side=='U' else 'U';entry=ends[(lid,bay_side,i)][0 if side=='U' else 1];z=(entry[0]+sign*t[0]*500,entry[1]+sign*t[1]*500);zid=f'{pre}Depot{direction}';E.SubElement(nodes,'node',id=zid,x=str(z[0]),y=str(z[1]),type='priority')
  dep=f'{pre}DEP_{direction}';add_edge(dep,zid,f'{pre}{bay_side}{i:02}'+('a' if side=='U' else 'b'),[z,entry],speed=8);connect(dep,f'{pre}'+('RD01' if direction=='U' else f'RU{n:02}'))
  dx,dy=unit(z,entry);normal=(-dy,dx);rect=[(z[0]+normal[0]*18,z[1]+normal[1]*18),(entry[0]+normal[0]*18,entry[1]+normal[1]*18),(entry[0]-normal[0]*18,entry[1]-normal[1]*18),(z[0]-normal[0]*18,z[1]-normal[1]*18)]
  E.SubElement(add,'poly',id=dep+'_zone',color='0.18,0.30,0.40',layer='-2',fill='true',shape=' '.join(f'{x:.3f},{y:.3f}' for x,y in rect));E.SubElement(add,'poi',id=dep+'_sign',x=str((z[0]+entry[0])/2),y=str((z[1]+entry[1])/2),color=c['color'],width='15',height='15',layer='4',name=f'{lid}号线发车区')
  station['depot_'+direction]=dep
 # Copy decorated platform geometry, remapping into the common station layout.
 original=E.parse(ROOT/f'network/line{lid}.add.xml').getroot()
 for item in original:
  v=copy.deepcopy(item);oldid=v.get('id');v.set('id',pre+oldid)
  if v.tag=='trainStop':
   if oldid=='PU01':v.set('lane','RD01_0')
   if oldid==f'PD{n:02}':v.set('lane',f'RU{n:02}_0')
   idx=int(oldid[2:]);s=meta[idx-1];v.set('lane',pre+v.get('lane'));E.SubElement(v,'access',lane=s['walk_edge']+'_0',pos=str(s['walk_pos']),length='12',friendlyPos='true');E.SubElement(v,'access',lane=s['walk_back']+'_0',pos=str(math.dist((s['hub_x'],s['hub_y']),project((s['x'],s['y']),s['tangent'],-15,65))-s['walk_pos']),length='12',friendlyPos='true')
  else:
   idx=int(oldid[1:3]) if oldid.startswith('S') and not oldid.startswith('Station') else int(oldid[len('Station'):]);old=source[lid][idx-1];new=meta[idx-1]
   if 'shape' in v.attrib:
    pts=[transform(tuple(map(float,p.split(',')[:2])),old,new) for p in v.get('shape').split()];v.set('shape',' '.join(f'{x:.3f},{y:.3f}' for x,y in pts))
   else:
    x,y=transform((float(v.get('x')),float(v.get('y'))),old,new);v.set('x',str(x));v.set('y',str(y))
  add.append(v)
 station_meta[str(lid)]=meta
 typev=copy.deepcopy(E.parse(ROOT/f'network/line{lid}.rou.xml').getroot().find('vType'));typev.set('id',f'metro{lid}');typev.set('personCapacity','1200');typev.set('boardingDuration','0.5');routes.append(typev)
 # Long cyclic service plans. Rail reversal occurs within the terminal platform.
 ring=[f'{pre}U02']
 for j in range(2,n):ring.extend([f'{pre}GU{j:02}',f'{pre}U{j+1:02}'])
 ring.extend([f'{pre}RU{n:02}',f'{pre}C_N',f'{pre}D{n-1:02}'])
 for j in range(n-2,0,-1):ring.extend([f'{pre}GD{j:02}',f'{pre}D{j:02}'])
 ring.extend([f'{pre}RD01',f'{pre}C_S'])
 for direction in ['U','D']:
  if direction=='U':prefix=[f'{pre}DEP_U',f'{pre}RD01',f'{pre}C_S']
  else:
   prefix=[f'{pre}DEP_D',f'{pre}RU{n:02}',f'{pre}C_N',f'{pre}D{n-1:02}']
   for j in range(n-2,0,-1):prefix.extend([f'{pre}GD{j:02}',f'{pre}D{j:02}'])
   prefix.extend([f'{pre}RD01',f'{pre}C_S'])
  plan=prefix+ring*8+[f'{pre}U02'];r=E.SubElement(routes,'route',id=f'Service{lid}{direction}',edges=' '.join(plan))
  for eid in plan:
   suffix=eid[len(pre):]
   if suffix=='RD01':E.SubElement(r,'stop',trainStop=f'{pre}PU01',duration='20');continue
   if suffix==f'RU{n:02}':E.SubElement(r,'stop',trainStop=f'{pre}PD{n:02}',duration='20');continue
   if suffix[0] in ('U','D') and suffix[1:].isdigit():
    idx=int(suffix[1:]);s=meta[idx-1]
    if s['stop_enabled']:E.SubElement(r,'stop',trainStop=f'{pre}P{suffix}',duration='40' if idx in (1,n) else '20')
for node in nodes:
 if node.get('id') in [f'L{lid}_D01a' for lid in configs]+[f'L{lid}_U{len(c["names"]):02}b' for lid,c in configs.items()]:node.set('type','rail_signal')
for name,hub in shared.items():
 members=hub['members'];walks=[next(s for s in station_meta[str(lid)] if s['name']==name)['walk_edge'] for lid in members]
 for a in walks:
  for b in walks:connect(a+'R',b)
 if len(members)>1:
  E.SubElement(add,'poi',id=hubs[name]+'_transfer',x=str(hub['point'][0]),y=str(hub['point'][1]),color='1,0.8,0.3',width='20',height='20',layer='4',name=name+' 换乘 '+','.join(map(str,members)))
E.SubElement(routes,'vType',id='walker',vClass='pedestrian',maxSpeed='1.4',color='0.2,0.9,0.9')
for name,obj in [('unified.nod.xml',nodes),('unified.edg.xml',edges),('unified.con.xml',connections),('unified.add.xml',add),('unified.rou.xml',routes)]:E.ElementTree(obj).write(ROOT/'network'/name,encoding='utf-8',xml_declaration=True)
subprocess.run([str(ROOT/'runtime/sumo/bin/netconvert.exe'),'--node-files',str(ROOT/'network/unified.nod.xml'),'--edge-files',str(ROOT/'network/unified.edg.xml'),'--connection-files',str(ROOT/'network/unified.con.xml'),'--output-file',str(ROOT/'network/unified.net.xml'),'--no-turnarounds','true','--junctions.internal-link-detail','32','--offset.disable-normalization','true','--geometry.min-radius.fix.railways','false'],check=True)
# Junction trimming changes short concourse lengths. Use compiled lane
# lengths for passenger access positions, rather than the input geometry.
lane_lengths={lane.get('id'):float(lane.get('length')) for edge in E.parse(ROOT/'network/unified.net.xml').getroot().findall('edge') for lane in edge.findall('lane')}
for lid,stations in station_meta.items():
 for s in stations:
  s['walk_pos']=lane_lengths[s['walk_edge']+'_0']*.55
  for stop in add.findall('trainStop'):
   if stop.get('id') in [f'L{lid}_PU{s["id"]:02}',f'L{lid}_PD{s["id"]:02}']:
    for access in stop.findall('access'):
     access.set('pos',str(s['walk_pos'] if access.get('lane')==s['walk_edge']+'_0' else lane_lengths[s['walk_back']+'_0']*.45))
E.ElementTree(add).write(ROOT/'network/unified.add.xml',encoding='utf-8',xml_declaration=True)
cfg=E.Element('configuration');inp=E.SubElement(cfg,'input')
for key,val in [('net-file','unified.net.xml'),('route-files','unified.rou.xml'),('additional-files','unified.add.xml')]:E.SubElement(inp,key,value=val)
t=E.SubElement(cfg,'time');E.SubElement(t,'step-length',value='0.5');p=E.SubElement(cfg,'processing');E.SubElement(p,'time-to-teleport',value='-1');rep=E.SubElement(cfg,'report');E.SubElement(rep,'no-step-log',value='true');E.SubElement(rep,'duration-log.disable',value='true');g=E.SubElement(cfg,'gui_only');E.SubElement(g,'gui-settings-file',value='unified.view.xml');E.ElementTree(cfg).write(ROOT/'network/unified.sumocfg',encoding='utf-8',xml_declaration=True)
(ROOT/'network/unified.view.xml').write_text('<viewsettings><scheme name="XiamenNetwork"><vehicles vehicleMode="0" vehicleQuality="2" vehicle_minSize="0" vehicle_exaggeration="1" vehicle_constantSize="0"/><persons personMode="0" personQuality="2"/></scheme><delay value="0"/></viewsettings>',encoding='utf-8')
(ROOT/'network/unified.stations.json').write_text(json.dumps({'stations':station_meta,'shared_stations':shared,'hubs':hubs,'geometry':'shared station aligned schematic, not GIS'},ensure_ascii=False,indent=2),encoding='utf-8')
print('Unified network built: five lines, ten shared interchanges, ten departure zones.')
