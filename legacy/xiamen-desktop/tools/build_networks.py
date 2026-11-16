"""Rebuild schematic SUMO networks and decorated stations from lines.json."""
from pathlib import Path
import math,json,subprocess,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]

def unit(a,b):
 dx=b[0]-a[0];dy=b[1]-a[1];n=math.hypot(dx,dy);return dx/n,dy/n

def curve(a,b,ta,tb):
 d=math.dist(a,b)*.32;p1=(a[0]+ta[0]*d,a[1]+ta[1]*d);p2=(b[0]-tb[0]*d,b[1]-tb[1]*d);pts=[]
 for k in range(41):
  t=k/40;u=1-t;pts.append((u**3*a[0]+3*u*u*t*p1[0]+3*u*t*t*p2[0]+t**3*b[0],u**3*a[1]+3*u*u*t*p1[1]+3*u*t*t*p2[1]+t**3*b[1]))
 return pts

def build(c,interchanges):
 lid=c['id'];n=len(c['names']);base=f'line{lid}';p=ROOT/'network';raw=c['raw'];length=sum(math.dist(a,b) for a,b in zip(raw,raw[1:]));factor=c['length_km']*1000/length
 xmin=min(x for x,y in raw);ymin=min(y for x,y in raw)
 centers=[((x-xmin+500)*factor,(y-ymin+500)*factor) for x,y in raw]
 nodes=ET.Element('nodes');edges=ET.Element('edges');cons=ET.Element('connections');endpoints={};shapes={};stations=[]
 def edge(eid,startnode,endnode,pts,speed=None):
  shapes[eid]=pts
  ET.SubElement(edges,'edge',id=eid,attrib={'from':startnode,'to':endnode},allow='rail_urban',numLanes='1',width='3.2',speed=str(speed or c['speed_kmh']/3.6),spreadType='center',shape=' '.join(f'{x:.3f},{y:.3f}' for x,y in pts))
 def connect(a,b):ET.SubElement(cons,'connection',attrib={'from':a,'to':b},fromLane='0',toLane='0')
 for idx,(name,center) in enumerate(zip(c['names'],centers),1):
  tangent=unit(centers[max(0,idx-2)],centers[min(n-1,idx)]);tx,ty=tangent;nx,ny=-ty,tx
  stations.append({'id':idx,'name':name,'x':center[0],'y':center[1],'tangent':[tx,ty],'up_edge':f'U{idx:02}','down_edge':f'D{idx:02}','stop_enabled':name not in c.get('skip_names',[]),'interchange_lines':interchanges.get(name,[]),'platform_length_m':210})
  for prefix,offset in [('U',-8),('D',8)]:
   cx=center[0]+offset*nx;cy=center[1]+offset*ny;a=(cx-130*tx,cy-130*ty);b=(cx+130*tx,cy+130*ty);endpoints[(prefix,idx)]=(a,b)
   for letter,pt in [('a',a),('b',b)]:
    node=f'{prefix}{idx:02}{letter}';kind='priority' if node in ('D01a',f'U{n:02}b') else 'rail_signal'
    ET.SubElement(nodes,'node',id=node,x=f'{pt[0]:.3f}',y=f'{pt[1]:.3f}',type=kind,radius='1.5')
   pts=[a,b] if prefix=='U' else [b,a]
   edge(f'{prefix}{idx:02}',f'{prefix}{idx:02}'+('a' if prefix=='U' else 'b'),f'{prefix}{idx:02}'+('b' if prefix=='U' else 'a'),pts)
 for idx in range(1,n):
  for prefix in ['U','D']:
   pts=curve(endpoints[(prefix,idx)][1],endpoints[(prefix,idx+1)][0],stations[idx-1]['tangent'],stations[idx]['tangent'])
   if prefix=='D':pts.reverse()
   eid=f'G{prefix}{idx:02}';first,second=(f'U{idx:02}',f'U{idx+1:02}') if prefix=='U' else (f'D{idx+1:02}',f'D{idx:02}')
   edge(eid,f'{prefix}{idx:02}b' if prefix=='U' else f'{prefix}{idx+1:02}a',f'{prefix}{idx+1:02}a' if prefix=='U' else f'{prefix}{idx:02}b',pts);connect(first,eid);connect(eid,second)
 for terminal,old,new,nextedge,cross in [(n,'U','RU',f'D{n-1:02}','C_N'),(1,'D','RD','U02','C_S')]:
  eid=f'{new}{terminal:02}';original=f'{old}{terminal:02}';pts=list(reversed(shapes[original]));fnode=f'{old}{terminal:02}'+('b' if old=='U' else 'a');tnode=f'{old}{terminal:02}'+('a' if old=='U' else 'b')
  edge(eid,fnode,tnode,pts,6);connect(original,eid)
  cpts=curve(pts[-1],shapes[nextedge][0],unit(pts[0],pts[-1]),unit(shapes[nextedge][0],shapes[nextedge][-1]))
  edge(cross,tnode,f'D{n-1:02}b' if terminal==n else 'U02a',cpts,10);connect(eid,cross);connect(cross,nextedge)
 for suffix,obj in [('nod.xml',nodes),('edg.xml',edges),('con.xml',cons)]:ET.ElementTree(obj).write(p/f'{base}.{suffix}',encoding='utf-8',xml_declaration=True)
 subprocess.run([str(ROOT/'runtime/sumo/bin/netconvert.exe'),'--node-files',str(p/f'{base}.nod.xml'),'--edge-files',str(p/f'{base}.edg.xml'),'--connection-files',str(p/f'{base}.con.xml'),'--output-file',str(p/f'{base}.net.xml'),'--junctions.internal-link-detail','24','--no-turnarounds','true','--geometry.min-radius.fix.railways','false','--offset.disable-normalization','true'],check=True)
 (p/f'{base}.stations.json').write_text(json.dumps(stations,ensure_ascii=False,indent=2),encoding='utf-8')
 color=','.join(str(int(c['color'][i:i+2],16)/255) for i in (1,3,5));r=ET.Element('routes')
 v=ET.SubElement(r,'vType',id='metro',vClass='rail_urban',accel='1',decel='1.2',emergencyDecel='2.5',sigma='0',length=str(c['model_train_length_m']),width='2.8',minGap='5',maxSpeed=str(c['speed_kmh']/3.6),guiShape='rail',color=color)
 for key,value in [('carriageLength','20'),('locomotiveLength','20'),('carriageGap','1')]:ET.SubElement(v,'param',key=key,value=value)
 ET.ElementTree(r).write(p/f'{base}.rou.xml',encoding='utf-8',xml_declaration=True)
 add=ET.Element('additional');count=0
 def poly(id,center,tangent,bounds,color,layer='-1'):
  tx,ty=tangent;nx,ny=-ty,tx;x0,x1,y0,y1=bounds
  points=[(center[0]+u*tx+v*nx,center[1]+u*ty+v*ny) for u,v in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]]
  ET.SubElement(add,'poly',id=id,color=color,layer=layer,fill='true',shape=' '.join(f'{x:.3f},{y:.3f}' for x,y in points))
 for s in stations:
  i=s['id'];center=(s['x'],s['y']);tangent=s['tangent'];tx,ty=tangent;nx,ny=-ty,tx
  for prefix in ['U','D']:ET.SubElement(add,'trainStop',id=f'P{prefix}{i:02}',lane=f'{prefix}{i:02}_0',startPos='20',endPos='230',name=s['name'],friendlyPos='true')
  for side in [-1,1]:
   lo,hi=sorted([side*15,side*36]);tag=f'S{i:02}_{side}'
   poly(tag+'_platform',center,tangent,(-110,110,lo,hi),'0.30,0.38,0.44')
   poly(tag+'_safety',center,tangent,(-110,110,side*15,side*17) if side==1 else(-110,110,-17,-15),'0.95,0.77,0.34','0')
   lo,hi=sorted([side*24,side*33]);poly(tag+'_canopy',center,tangent,(-95,95,lo,hi),color,'1')
   for x in range(-80,81,20):
    poly(tag+f'_bench{x}',center,tangent,(x-3,x+3,side*20-1.2,side*20+1.2),'0.59,0.43,0.28','1')
    pos=(center[0]+x*tx+side*22*nx,center[1]+x*ty+side*22*ny)
    ET.SubElement(add,'poi',id=tag+f'_light{x}',x=f'{pos[0]:.3f}',y=f'{pos[1]:.3f}',color='1,0.95,0.65',width='1.8',height='1.8',layer='2',type='station-light')
   for x in [-105,105]:poly(tag+f'_garden{x}',center,tangent,(x-4,x+4,lo,hi),'0.21,0.46,0.30','1')
  label=(center[0]+43*nx,center[1]+43*ny)
  ET.SubElement(add,'poi',id=f'Station{i:02}',x=f'{label[0]:.3f}',y=f'{label[1]:.3f}',color=color,width='6',height='6',layer='3',type='station',name=s['name'])
 ET.ElementTree(add).write(p/f'{base}.add.xml',encoding='utf-8',xml_declaration=True)
 (p/f'{base}.view.xml').write_text(f'<viewsettings><scheme name="XiamenLine{lid}"><vehicles vehicleMode="0" vehicleQuality="2" vehicle_minSize="0" vehicle_exaggeration="1" vehicle_constantSize="0" showBlinker="0"/><additionals addName_show="0" addFullName_show="1" addFullName_size="14" addFullName_color="25,45,70" addFullName_constantSize="1"/></scheme><delay value="0"/></viewsettings>',encoding='utf-8')
 for mode in ['control','demo']:
  cfg=ET.Element('configuration');inp=ET.SubElement(cfg,'input');ET.SubElement(inp,'net-file',value=f'{base}.net.xml');ET.SubElement(inp,'route-files',value=f'{base}.rou.xml'+(f',{base}.demo.rou.xml' if mode=='demo' else ''));ET.SubElement(inp,'additional-files',value=f'{base}.add.xml');tm=ET.SubElement(cfg,'time');ET.SubElement(tm,'step-length',value='0.2');proc=ET.SubElement(cfg,'processing');ET.SubElement(proc,'time-to-teleport',value='-1');report=ET.SubElement(cfg,'report');ET.SubElement(report,'no-step-log',value='true');ET.SubElement(report,'duration-log.disable',value='true');g=ET.SubElement(cfg,'gui_only');ET.SubElement(g,'gui-settings-file',value=f'{base}.view.xml');ET.ElementTree(cfg).write(p/(f'{base}.control.sumocfg' if mode=='control' else f'{base}.sumocfg'),encoding='utf-8',xml_declaration=True)
 up=['U01']
 for i in range(1,n):up.extend([f'GU{i:02}',f'U{i+1:02}'])
 down=[f'RU{n:02}','C_N',f'D{n-1:02}']
 for i in range(n-2,0,-1):down.extend([f'GD{i:02}',f'D{i:02}'])
 again=['RD01','C_S','U02']
 for i in range(2,n):again.extend([f'GU{i:02}',f'U{i+1:02}'])
 demo=ET.Element('routes');ET.SubElement(demo,'route',id='demo_route',edges=' '.join(up+down+again));veh=ET.SubElement(demo,'vehicle',id=f'XM{lid}_demo',type='metro',route='demo_route',depart='0',departPos='229.9',departSpeed='0')
 for direction,indices in [('U',range(1,n+1)),('D',range(n-1,0,-1)),('U',range(2,n+1))]:
  for i in indices:
   if stations[i-1]['stop_enabled']:ET.SubElement(veh,'stop',trainStop=f'P{direction}{i:02}',duration='40' if i in (1,n) else '20')
 ET.ElementTree(demo).write(p/f'{base}.demo.rou.xml',encoding='utf-8',xml_declaration=True)
 print(f'Line {lid}: {n} nodes, {c["stop_count"]} stops, decorated platforms.',flush=True)

if __name__=='__main__':
 catalog=json.loads((ROOT/'lines.json').read_text(encoding='utf-8'))
 for config in catalog['lines']:build(config,catalog['interchanges'])
