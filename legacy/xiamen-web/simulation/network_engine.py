"""One SUMO connection, timed fleets, terminal slots and real passenger transfers."""
from pathlib import Path
from collections import deque
import os,sys,json,math,re,heapq,time,hashlib,tempfile,subprocess,bisect
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parent
os.environ['SUMO_HOME']=str(ROOT/'runtime/sumo')
sys.path.insert(0,str(ROOT/'runtime/sumo/tools'))
import traci,sumolib
from traci import constants as tc
CATALOG=json.loads((ROOT/'lines.json').read_text(encoding='utf-8'))
LINES={x['id']:x for x in CATALOG['lines']};LINE_IDS=CATALOG['line_ids']
DATA=json.loads((ROOT/'network/unified.stations.json').read_text(encoding='utf-8'))

def network_ready(name):
 if name.endswith('.depot') and not all((ROOT/p).exists() for p in ('depot_scene.py','network/depot.catalogue.json')):return False
 cfg=ROOT/f'network/{name}.sumocfg'
 if not cfg.exists() or not (ROOT/f'network/{name}.net.xml').exists():return False
 try:
  for setting in ET.parse(cfg).getroot().find('input'):
   if setting.tag in ('net-file','route-files','additional-files'):
    for value in setting.get('value','').split(','):
     if value and not (cfg.parent/value).exists():return False
  return True
 except (OSError,ET.ParseError,TypeError):return False

def sumo_working_root():
 """An ASCII directory junction works around SUMO's Windows path parsing."""
 if os.name!='nt' or str(ROOT).isascii():return ROOT
 import _winapi
 candidates=[Path(tempfile.gettempdir())/'XiamenMetro',Path(os.environ.get('PUBLIC','C:/Users/Public'))/'Documents/XiamenMetro']
 for base in candidates:
  if not str(base).isascii():continue
  try:
   base.mkdir(parents=True,exist_ok=True);alias=base/('project_'+hashlib.sha256(str(ROOT).encode('utf-8')).hexdigest()[:16])
   if not alias.exists():_winapi.CreateJunction(str(ROOT),str(alias))
   if alias.resolve()==ROOT.resolve():return alias
  except OSError:continue
 raise RuntimeError('SUMO 无法使用当前中文路径。请将完整文件夹移到英文路径，例如 C:\\XiamenMetro，再启动。')

def runtime_additionals(name):
 """Retain all operational XML; remote canvases already draw static decoration.

 Content-addressed, atomically published and kept beside the source files so
 relative references retain their meaning. Original inputs remain untouched.
 """
 if os.environ.get('XIAMEN_FULL_DECORATIONS')=='1':return None
 cfg=ROOT/f'network/{name}.sumocfg'
 entry=ET.parse(cfg).getroot().find('input/additional-files')
 if entry is None:return None
 sources=[cfg.parent/v.strip() for v in entry.get('value','').split(',') if v.strip()]
 contents=[p.read_bytes() for p in sources]
 digest=hashlib.sha256(b'remote-operational-v1\0'+b'\0'.join(contents)).hexdigest()[:24]
 target=cfg.parent/f'.remote-operational-{digest}.add.xml'
 if not target.exists():
  root=ET.Element('additional')
  for content in contents:
   for node in ET.fromstring(content):
    if node.tag not in ('poly','poi'):root.append(node)
  temporary=target.with_name(target.name+f'.{os.getpid()}.tmp')
  try:
   ET.ElementTree(root).write(temporary,encoding='utf-8',xml_declaration=True)
   os.replace(temporary,target)
  finally:
   temporary.unlink(missing_ok=True)
 return 'network/'+target.name

class NetworkEngine:
 def __init__(self):
  self.stations={int(k):v for k,v in DATA['stations'].items()}
  self.network_name='unified'
  if os.environ.get('XIAMEN_USE_ORIGINAL_NETWORK')!='1' and (ROOT/'mobility_engine.py').exists():
   if network_ready('multimodal'):self.network_name='multimodal'
   if os.environ.get('XIAMEN_USE_DEPOTS')!='0' and network_ready('multimodal.depot'):self.network_name='multimodal.depot'
  self.net=sumolib.net.readNet(str(ROOT/f'network/{self.network_name}.net.xml'),withInternal=True)
  self.conn=None;self.paused=True;self.time=0.;self.trains={};self.departures=[];self.visits=[];self.events=deque(maxlen=100);self.passengers={};self.teleports=0;self.collisions=0
  self.settings={lid:dict(enabled=False,headway=180,next_U=0.,next_D=0.,sequence=0,cap=24,speed=LINES[lid]['speed_kmh']) for lid in LINE_IDS}
  self.step_length=.5;self.step_index=0;self.gui=False;self.frame={};self._lane_shapes={};self._line_counts={lid:0 for lid in LINE_IDS}
  self.walk_stations={edge:s for stations in self.stations.values() for s in stations for edge in (s['walk_edge'],s['walk_back'])}
  self._edge_stations={}
  for edge in self.net.getEdges():
   match=re.match(r'L\d+_(RU|RD|U|D)(\d+)$',edge.getID())
   if match:self._edge_stations[edge.getID()]=(match.group(1),int(match.group(2)))
  self.reserved={};self._last_depart={};self._build_graph()
  from rail_dispatch import RailDispatch
  self.dispatch=RailDispatch(self);self.mobility=None
  self.depots=None;self._depot_routes={};self._depot_requests={};self._depot_snapshot=None;self._depot_edges={}
  if self.network_name.endswith('.depot'):
   from depot_scene import DepotManager
   self.depots=DepotManager(self)
   self._depot_edges={edge.getID():self.depots.locate(edge.getID().lstrip(':')) for edge in self.net.getEdges(withInternal=True)}
   for route in ET.parse(ROOT/'network/multimodal.depot.rou.xml').getroot().findall('route'):
    if route.get('id','').startswith(('DepotService','DepotEntry')):
     self._depot_routes[route.get('id')]=(tuple(route.get('edges').split()),[dict(stop.attrib) for stop in route.findall('stop')])
  if self.network_name.startswith('multimodal'):
   from mobility_engine import MobilityManager
   self.mobility=MobilityManager(self)
 def start(self,gui=False):
  if self.conn:return
  (ROOT/'logs').mkdir(exist_ok=True)
  binary=Path('runtime/sumo/bin')/('sumo-gui.exe' if gui else 'sumo.exe')
  # SUMO's Windows argument parser cannot reliably decode non-ASCII
  # absolute paths. Relative arguments preserve Chinese install paths.
  previous_cwd=Path.cwd();previous_home=os.environ.get('SUMO_HOME')
  try:
   working_root=sumo_working_root();os.chdir(working_root);os.environ['SUMO_HOME']=str(working_root/'runtime/sumo')
   # Embedded libsumo preserves the TraCI API without opening a TCP listener.
   if gui:raise ValueError('远程入口使用内置仿真；原生 SUMO 窗口请使用原项目入口。')
   args=['sumo','-c',f'network/{self.network_name}.sumocfg','--xml-validation','never','--xml-validation.net','never','--xml-validation.routes','never','--error-log','logs/network-errors.log']
   additionals=runtime_additionals(self.network_name)
   if additionals:args+=['--additional-files',additionals]
   started=time.perf_counter();traci.start(args)
   self.startup_seconds=time.perf_counter()-started
  finally:
   os.chdir(previous_cwd)
   if previous_home is None:os.environ.pop('SUMO_HOME',None)
   else:os.environ['SUMO_HOME']=previous_home
  self.conn=traci
  self.conn.simulation.subscribe([tc.VAR_TIME,tc.VAR_DEPARTED_VEHICLES_IDS,tc.VAR_ARRIVED_VEHICLES_IDS,
   tc.VAR_TELEPORT_STARTING_VEHICLES_NUMBER,tc.VAR_COLLIDING_VEHICLES_NUMBER,
   tc.VAR_PENDING_VEHICLES,tc.VAR_ARRIVED_PERSONS_IDS])
  self.conn.vehicle.subscribe('',[tc.TRACI_ID_LIST])
  self.dispatch.attach()
  if gui:
   self.conn.gui.setSchema('View #0','XiamenMobility4' if self.network_name.startswith('multimodal') else 'XiamenNetwork')
   xmin,ymin,xmax,ymax=self.net.getBoundary();margin=max(xmax-xmin,ymax-ymin)*.04
   self.conn.gui.setBoundary('View #0',xmin-margin,ymin-margin,xmax+margin,ymax+margin)
   if self.network_name.startswith('multimodal'):
    self.conn.gui.setOffset('View #0',(xmin+xmax)/2,(ymin+ymax)/2+400)
    self.conn.gui.setZoom('View #0',65)
  self.paused=False;self.events.append('联合路网已启动：五线共用一个仿真时钟')
 def start_line(self,lid,gui=False):
  self.start(gui);s=self.settings[lid];s['enabled']=True;s['next_U']=self.time;s['next_D']=self.time;self.paused=False
 def start_all(self,gui=False):
  self.start(gui)
  for lid in LINE_IDS:
   if not self.settings[lid]['enabled']:self.start_line(lid)
 def set_headway(self,lid,value):
  value=int(value)
  if not 60<=value<=600:raise ValueError('发车间隔应为 60～600 秒。')
  self.settings[lid]['headway']=value
  for d in 'UD':self.settings[lid]['next_'+d]=min(self.settings[lid]['next_'+d],self.time+value)
 def set_speed(self,lid,value):
  value=float(value)
  if not 10<=value<=LINES[lid]['speed_kmh']:raise ValueError('速度须在 10 和本线最高速度之间。')
  self.settings[lid]['speed']=value
  if self.conn:
   for vid,t in self.trains.items():
    if t['line']==lid and t['active']:self.conn.vehicle.setMaxSpeed(vid,value/3.6)
 def _spawn(self,lid,d):
  s=self.settings[lid];departure=self.depots.choose_spawn(lid,d) if self.depots else None
  if self.depots and departure is None:return False
  s['sequence']+=1;vid=f'L{lid}-{d}-{s["sequence"]:03}'
  self.conn.vehicle.add(vid,departure['route_id'] if departure else f'Service{lid}{d}',typeID=f'metro{lid}',depart='now',departPos=str(departure['depart_pos'] if departure else 140),departSpeed='0',line=f'L{lid}')
  self._line_counts[lid]+=1
  self.trains[vid]=dict(id=vid,line=lid,origin=d,direction=d,active=False,position=(0,0),speed=0,edge='',angle=0,history=deque(maxlen=2400),distance=0,stop=False,station=1 if d=='U' else len(self.stations[lid]),next_station=1 if d=='U' else len(self.stations[lid]),terminal=None,release=None,visits=0)
  if departure:self.trains[vid].update(depot=departure['depot_id'],depot_track=departure['track_id'],depot_phase='出段')
  self.events.append(f'{self.time:.0f}s · {lid}号线 {d}方向 · {vid} 进入待发区')
  return True
 def step(self):
  if not self.conn or self.paused:return
  self.dispatch.before_step()
  for lid,s in self.settings.items():
   if not s['enabled']:continue
   for d in 'UD':
    if self.time>=s['next_'+d] and self._line_counts[lid]<s['cap']:
     if self._spawn(lid,d):s['next_'+d]=self.time+s['headway']
  self.conn.simulationStep();self.step_index+=1
  simulation=self.conn.simulation.getSubscriptionResults()
  self.time=simulation[tc.VAR_TIME]
  self.teleports+=simulation[tc.VAR_TELEPORT_STARTING_VEHICLES_NUMBER];self.collisions+=simulation[tc.VAR_COLLIDING_VEHICLES_NUMBER]
  readings=self.conn.vehicle.getAllSubscriptionResults()
  active=set(readings.get('',{}).get(tc.TRACI_ID_LIST,()))
  arrived=set(simulation[tc.VAR_ARRIVED_VEHICLES_IDS])
  for vid in arrived:
   train=self.trains.pop(vid,None)
   if train:self._line_counts[train['line']]-=1
  for vid in active:
   if vid not in self.trains:continue
   t=self.trains[vid]
   if not t['active']:
    self.conn.vehicle.subscribe(vid,[tc.VAR_POSITION,tc.VAR_SPEED,tc.VAR_ROAD_ID,tc.VAR_LANEPOSITION,tc.VAR_STOPSTATE,tc.VAR_ANGLE,tc.VAR_DISTANCE,tc.VAR_LANE_ID,tc.VAR_PERSON_NUMBER])
    self.conn.vehicle.setMaxSpeed(vid,self.settings[t['line']]['speed']/3.6);t['active']=True
  self.frame={'simulation':simulation,'vehicle_readings':readings,'active_vehicles':active,
   'arrived_vehicles':arrived,'pending_vehicles':set(simulation[tc.VAR_PENDING_VEHICLES]),
   'person_readings':self.conn.person.getAllSubscriptionResults()}
  for vid,r in readings.items():
   if vid not in self.trains:continue
   t=self.trains[vid];edge=r[tc.VAR_ROAD_ID];pos=r[tc.VAR_POSITION];distance=r[tc.VAR_DISTANCE];angle=r[tc.VAR_ANGLE];speed=r[tc.VAR_SPEED];stopped=bool(r[tc.VAR_STOPSTATE]&1)
   station=self._edge_stations.get(edge)
   if station:
    typ,idx=station;t['direction']='D' if typ in ('D','RU') else 'U';t['next_station']=idx
   if t['history'] and abs((angle-t['angle']+180)%360-180)>120 and speed<2:t['history'].clear()
   if not t['history']:
    lane_id=r[tc.VAR_LANE_ID]
    offset=r[tc.VAR_LANEPOSITION]
    for k in range(-LINES[t['line']]['model_train_length_m']-10,1):t['history'].append((distance+k,self.lane_point(lane_id,max(0,offset+k))))
   if distance-t['distance']>.4 or not t['history']:t['history'].append((distance,pos))
   if stopped and (not t['stop'] or edge!=t['edge']):
    if station:t['station']=idx;t['visits']+=1;self.visits.append((self.time,vid,t['line'],idx,t['direction'],edge))
    terminal='U' if edge==f'L{t["line"]}_RD01' else ('D' if edge==f'L{t["line"]}_RU{len(self.stations[t["line"]]):02}' else None)
    t['terminal']=terminal
    depot_request=self._depot_requests.get(vid)
    if terminal and not (depot_request and depot_request['from_edge']==edge and not r[tc.VAR_PERSON_NUMBER]):
     key=(t['line'],terminal);h=self.settings[t['line']]['headway'];slot=max(math.ceil((self.time+20)/h)*h,self.reserved.get(key,-h)+h,self._last_depart.get(key,-h)+h)
     self.reserved[key]=slot;t['release']=slot
     stopid=f'L{t["line"]}_P{terminal}{(1 if terminal=="U" else len(self.stations[t["line"]])):02}'
     self.conn.vehicle.setBusStop(vid,stopid,duration=max(20,slot-self.time),until=slot)
   if not stopped and t['terminal'] and speed>.05:
    key=(t['line'],t['terminal']);self._last_depart[key]=self.time;self.departures.append(dict(time=self.time,id=vid,line=t['line'],direction=t['terminal'],scheduled=t['release']))
    self.events.append(f'{self.time:.0f}s · {vid} 从端点发车');t['terminal']=None;t['release']=None
   t.update(position=pos,speed=speed,edge=edge,angle=angle,distance=distance,stop=stopped,lane_position=r[tc.VAR_LANEPOSITION],lane=r[tc.VAR_LANE_ID],people=r[tc.VAR_PERSON_NUMBER],passenger_objects=r[tc.VAR_PERSON_NUMBER])
   if self.depots:
    depot=self._depot_edges.get(edge)
    if depot:t['depot']=depot['id']
    elif t.get('depot_phase')=='出段':t['depot_phase']='正线'
    if t.get('depot_phase')=='出段' and edge!=t.get('depot_track'):t['depot_track']=None
    request=self._depot_requests.get(vid)
    if request and edge==request['from_edge'] and stopped and not t['people']:self._enter_depot(vid,request)
    if t.get('depot_phase')=='入段' and edge==t.get('depot_track') and stopped:t['depot_phase']='已入段';t['terminal']=None;t['release']=None
  persons=self.frame['person_readings']
  for pid,p in self.passengers.items():
   if pid in persons:
    p['seen']=True;vehicle=persons[pid].get(tc.VAR_VEHICLE,'')
    if vehicle:
     p['status']='乘坐 '+vehicle
     if not p['rides'] or p['rides'][-1]!=vehicle:p['rides'].append(vehicle);self.events.append(f'{pid} 上车 {vehicle}')
    else:p['status']='步行 / 候车 / 换乘'
   elif p['seen'] and p['status']!='已到达':p['status']='已到达';p['arrival']=self.time;self.events.append(f'{pid} 已到达 {p["destination"]}')
  self.dispatch.update()
  if self.mobility:self.mobility.tick(self.frame)
  self._update_passenger_counts()
  self._depot_snapshot=None
 def _update_passenger_counts(self):
  """Expose represented people while preserving raw SUMO object occupancy.

  An onboard cohort is one SUMO person, usually representing twenty people.
  Single passengers and any ungrouped persons still count as one. All input
  comes from this step's shared subscriptions; no per-train TraCI calls.
  Physical capacities, empty-train depot checks and the model are unchanged.
  """
  extra={};groups=self.mobility.groups if self.mobility else {}
  for pid,reading in self.frame.get('person_readings',{}).items():
   vehicle=reading.get(tc.VAR_VEHICLE,'');group=groups.get(pid)
   if vehicle in self.trains and group:
    extra[vehicle]=extra.get(vehicle,0)+int(group['count'])-1
  for vid,train in self.trains.items():
   train['people']=train.get('passenger_objects',0)+extra.get(vid,0)
 def depot_list(self,lid=None):
  if not self.depots:return []
  if self._depot_snapshot is None:self._depot_snapshot=self.depots.snapshot()
  return [depot for depot in self._depot_snapshot if lid is None or depot['line']==int(lid)]
 def send_to_depot(self,vid,direction=None,track=0):
  if not self.depots or not self.conn:raise RuntimeError('请先启动带车辆段的联合仿真。')
  train=self.trains.get(vid)
  if not train or not train['active']:raise ValueError('请选择实际运行中的列车。')
  if train.get('depot_phase') in ('入段','已入段'):raise ValueError('列车已在入段流程中。')
  direction=direction or train.get('terminal') or ('D' if train['direction']=='U' else 'U')
  depot=self.depots.get_depot(train['line'],direction)
  track=int(track)
  if not 0<=track<len(depot['tracks']):raise ValueError('请选择有效的存车股道。')
  target=depot['tracks'][track]
  occupied=sum(t['id']!=vid and (t.get('depot_track')==target['id'] or t.get('edge')==target['edge']) for t in self.trains.values())
  reserved=sum(other!=vid and request['track_id']==target['id'] for other,request in self._depot_requests.items())
  if occupied+reserved>=target['capacity_trains']:raise ValueError('该存车股道已占满或已预约，请选择其他股道。')
  self._depot_requests[vid]={'depot_id':depot['id'],'track_id':target['id'],
   'holding_stop':target['holding_stop'],'route_id':target['entry_route_id'],
   'from_edge':depot['entry']['from_edge']}
  train['depot_request']=depot['id'];self._depot_snapshot=None
  self.events.append(f'{self.time:.0f}s · {vid} 预约入段 {depot["terminal_station"]} {track+1}股 · 端点清客后入段')
  return dict(self._depot_requests[vid])
 def _assign_depot_route(self,vid,route_id,skip_stop=None):
  # Change an actual stopped train's route. Resume/remove the old stop
  # plan first; retaining its cyclic future station stops would invalidate
  # the short depot entry route. No moveTo or signal overrides are used.
  train=self.trains[vid]
  if train['stop']:self.conn.vehicle.resume(vid)
  stops=self.conn.vehicle.getStops(vid)
  for index in range(len(stops)-1,-1,-1):self.conn.vehicle.replaceStop(vid,index,'')
  self.conn.vehicle.setRouteID(vid,route_id)
  new_stops=self.conn.vehicle.getStops(vid)
  if new_stops:
   if skip_stop:
    for index in range(len(new_stops)-1,-1,-1):
     if new_stops[index].stoppingPlaceID==skip_stop:self.conn.vehicle.replaceStop(vid,index,'')
  else:
   for stop in self._depot_routes[route_id][1]:
    sid=stop.get('trainStop') or stop.get('busStop')
    if sid and sid!=skip_stop:self.conn.vehicle.setBusStop(vid,sid,duration=float(stop.get('duration',20)))
 def _enter_depot(self,vid,request):
  self._assign_depot_route(vid,request['route_id'])
  train=self.trains[vid];train.update(depot=request['depot_id'],depot_track=request['track_id'],depot_phase='入段',terminal=None,release=None)
  train.pop('depot_request',None);self._depot_requests.pop(vid,None)
  self.events.append(f'{self.time:.0f}s · {vid} 经真实入段轨道进入 {request["depot_id"]}')
 def release_from_depot(self,vid):
  train=self.trains.get(vid)
  if not self.depots or not self.conn or not train or train.get('depot_phase')!='已入段' or not train['stop']:
   raise ValueError('请选择实际停在存车股道的列车。')
  depot=self.depots.by_id[train['depot']]
  track=next(track for track in depot['tracks'] if track['id']==train['depot_track'])
  self._assign_depot_route(vid,track['route_id'],skip_stop=track['holding_stop'])
  train.update(depot_phase='出段',direction=depot['direction'],terminal=None,release=None)
  self._depot_snapshot=None;self.paused=False
  self.events.append(f'{self.time:.0f}s · {vid} 从 {depot["id"]} 出段，恢复正线停站计划')
  return track['route_id']
 def subscribe_person(self,pid):
  self.conn.person.subscribe(pid,[tc.VAR_POSITION,tc.VAR_VEHICLE,tc.VAR_ROAD_ID,tc.VAR_STAGE],parameters={tc.VAR_STAGE:0})
 def lane_point(self,lane_id,offset):
  cached=self._lane_shapes.get(lane_id)
  if cached is None:
   shape=self.net.getLane(lane_id).getShape();cumulative=[0.]
   for a,b in zip(shape,shape[1:]):cumulative.append(cumulative[-1]+math.dist(a,b))
   cached=(shape,cumulative);self._lane_shapes[lane_id]=cached
  shape,cumulative=cached
  index=bisect.bisect_right(cumulative,offset)-1
  if index>=len(shape)-1:return shape[-1]
  index=max(0,index);ratio=(offset-cumulative[index])/max(.0001,cumulative[index+1]-cumulative[index])
  return tuple(shape[index][k]+ratio*(shape[index+1][k]-shape[index][k]) for k in (0,1))
 def signal_list(self,lid=None):return self.dispatch.snapshot(lid)
 def signal_stats(self):return self.dispatch.stats()
 def hold_signal(self,sid,seconds=60):return self.dispatch.hold(sid,seconds)
 def release_signal(self,sid):return self.dispatch.release(sid)
 def set_line_hold(self,lid,seconds=60):return self.dispatch.hold_line(lid,seconds)
 def release_all_signals(self,lid=None):return self.dispatch.release_all(lid)
 def point_behind(self,t,offset):
  history=t['history'];target=t['distance']-offset
  if not history:return t['position']
  following=history[-1]
  if target>=following[0]:return following[1]
  for previous in reversed(history):
   if previous[0]<=target:
    ratio=(target-previous[0])/max(.0001,following[0]-previous[0]);ratio=max(0,min(1,ratio));return tuple(previous[1][i]+ratio*(following[1][i]-previous[1][i]) for i in (0,1))
   following=previous
  return history[0][1]
 def _build_graph(self):
  self.graph={};self.by_name={}
  for lid,stations in self.stations.items():
   valid=[s for s in stations if s['stop_enabled']]
   for s in valid:self.graph[(lid,s['id'])]=[];self.by_name.setdefault(s['name'],[]).append((lid,s['id']))
   for a,b in zip(valid,valid[1:]):
    cost=math.hypot(a['x']-b['x'],a['y']-b['y'])/(LINES[lid]['speed_kmh']/3.6)+35
    self.graph[(lid,a['id'])].append(((lid,b['id']),cost));self.graph[(lid,b['id'])].append(((lid,a['id']),cost))
  for members in self.by_name.values():
   for a in members:
    for b in members:
     if a!=b:self.graph[a].append((b,110))
 def plan(self,origin,destination):
  if origin==destination:raise ValueError('起点和终点请选择不同站点。')
  queue=[];best={};previous={};targets=set(self.by_name[destination])
  for node in self.by_name[origin]:best[node]=0;heapq.heappush(queue,(0,node))
  end=None
  while queue:
   cost,a=heapq.heappop(queue)
   if cost!=best[a]:continue
   if a in targets:end=a;break
   for b,w in self.graph[a]:
    if cost+w<best.get(b,float('inf')):best[b]=cost+w;previous[b]=a;heapq.heappush(queue,(cost+w,b))
  if end is None:raise ValueError('无法找到行程。')
  nodes=[end]
  while nodes[-1] in previous:nodes.append(previous[nodes[-1]])
  nodes.reverse();segments=[]
  for a,b in zip(nodes,nodes[1:]):
   if a[0]!=b[0]:continue
   if segments and segments[-1]['line']==a[0] and segments[-1]['end']==a[1]:segments[-1]['end']=b[1]
   else:segments.append(dict(line=a[0],start=a[1],end=b[1]))
  for s in segments:s['direction']='U' if s['end']>s['start'] else 'D'
  return segments
 def trip_text(self,segments):
  return ' → 换乘 → '.join(f'{s["line"]}号线 {self.stations[s["line"]][s["start"]-1]["name"]} → {self.stations[s["line"]][s["end"]-1]["name"]}' for s in segments)
 def add_passenger(self,origin,destination):
  segments=self.plan(origin,destination)
  for s in segments:
   if not self.settings[s['line']]['enabled']:self.start_line(s['line'])
  pid=f'P{len(self.passengers)+1:03}';first=self.stations[segments[0]['line']][segments[0]['start']-1]
  self.conn.person.add(pid,first['walk_edge'],first['walk_pos'],typeID='walker')
  prev=None
  for seg in segments:
   lid=seg['line'];start=self.stations[lid][seg['start']-1];end=self.stations[lid][seg['end']-1];d=seg['direction'];stop=f'L{lid}_P{d}{seg["start"]:02}';dest=f'L{lid}_P{d}{seg["end"]:02}'
   walk=[start['walk_edge']] if prev is None else list(self.conn.simulation.findRoute(prev['walk_edge'],start['walk_edge'],vType='walker').edges)
   if not walk:raise RuntimeError('换乘步行通道不连通。')
   stage=traci.simulation.Stage(type=tc.STAGE_WALKING,edges=walk,departPos=(first['walk_pos'] if prev is None else prev['walk_pos']),arrivalPos=start['walk_pos'],destStop=stop,travelTime=-1)
   self.conn.person.appendStage(pid,stage)
   edge=f'L{lid}_{d}{seg["end"]:02}'
   if d=='U' and seg['end']==1:edge=f'L{lid}_RD01'
   if d=='D' and seg['end']==len(self.stations[lid]):edge=f'L{lid}_RU{seg["end"]:02}'
   # TraCI does not insert the XML parser's exit-access stage. Keep the
   # alighting position in the receiving concourse's coordinates; destStop
   # still governs the real train stop at which the ride ends.
   self.conn.person.appendStage(pid,traci.simulation.Stage(type=tc.STAGE_DRIVING,edges=[edge],line=f'L{lid}',destStop=dest,arrivalPos=end['walk_pos']))
   prev=end
  self.conn.person.appendStage(pid,traci.simulation.Stage(type=tc.STAGE_WALKING,edges=[prev['walk_edge']],departPos=prev['walk_pos'],arrivalPos=prev['walk_pos'],travelTime=-1))
  self.passengers[pid]=dict(origin=origin,destination=destination,plan=segments,status='进入车站',rides=[],seen=False)
  self.subscribe_person(pid)
  self.paused=False;return pid
 def close(self):
  if self.conn:
   if self.mobility and self.mobility.groups:
    (ROOT/'logs/last-mobility-session.json').write_text(json.dumps({'time':self.time,'stats':self.mobility.stats(),'completed':self.mobility.completed},ensure_ascii=False,indent=2),encoding='utf-8')
   try:self.conn.close()
   except traci.exceptions.FatalTraCIError:pass
   finally:
    self.conn=None;self.paused=True;self.frame={};self.gui=False;self.dispatch.holds.clear();self.dispatch.readings.clear()
    self.dispatch._snapshots.clear();self.dispatch._stats=None;self.dispatch._markers.clear()
    self._depot_requests.clear();self._depot_snapshot=None
    if self.mobility:self.mobility.reset()
