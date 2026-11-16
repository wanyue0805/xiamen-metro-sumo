"""厦门地铁1号线：24站、双线、真实SUMO列车折返；轨道几何为示意模型。"""
from pathlib import Path
from collections import deque
import os,sys,shutil,json,math,time,logging,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parent
if (ROOT/'runtime/sumo/bin/sumo.exe').exists():os.environ['SUMO_HOME']=str(ROOT/'runtime/sumo')
if os.environ.get('SUMO_HOME'):sys.path.insert(0,str(Path(os.environ['SUMO_HOME'])/'tools'))
import traci,sumolib
CATALOG=json.loads((ROOT/'lines.json').read_text(encoding='utf-8'))
LINES={item['id']:item for item in CATALOG['lines']}
LINE_IDS=CATALOG['line_ids']
DATA=json.loads((ROOT/'stations.json').read_text(encoding='utf-8'))
STATIONS={s['id']:s for s in DATA['stations']}
TRAIN_LENGTH=120.0

class Engine:
 def __init__(self,line_id=1):
  self.line_id=int(line_id);self.config=LINES[self.line_id];self.last=len(self.config['names']);self.train_length=self.config['model_train_length_m'];self.cars=self.config['cars']
  self.stations={item['id']:item for item in json.loads((ROOT/f'network/line{self.line_id}.stations.json').read_text(encoding='utf-8'))};self.enabled=[i for i,item in self.stations.items() if item['stop_enabled']]
  self.net=sumolib.net.readNet(str(ROOT/f'network/line{self.line_id}.net.xml'),withInternal=True)
  self.conn=None;self.sequence=0;self.speed=self.config['speed_kmh']/3.6;self.dwell=20.0;self.terminal_dwell=40.0
  self.direction=1;self.target=1;self.current=1;self.arrived=True;self.paused=True;self.auto=False
  self.route=[];self.dest_edge='U01';self.history=deque(maxlen=2500);self.distance=0;self.visits=[];self.events=[];self.pending=None;self.status='尚未启动';self.last_heading=None;self.last_reversed=False
  self.links={(c.get('from'),c.get('to')):c.get('via') for c in ET.parse(ROOT/f'network/line{self.line_id}.net.xml').getroot().findall('connection') if c.get('via')}
 def binary(self,gui=False):
  name='sumo-gui' if gui else 'sumo';path=ROOT/'runtime/sumo/bin'/(name+'.exe')
  if os.name=='nt' and path.exists():return str(path)
  path=shutil.which(name)
  if path:return path
  raise RuntimeError('找不到 SUMO。Windows 请保留完整 runtime 文件夹；其他系统请安装 SUMO。')
 def start(self,gui=False,direction=1):
  self.close();os.chdir(ROOT);(ROOT/'logs').mkdir(exist_ok=True);self.sequence+=1
  cmd=[self.binary(gui),'-c',f'network/line{self.line_id}.control.sumocfg','--start','--quit-on-end','--error-log',f'logs/sumo-line{self.line_id}-errors.log']
  if gui:cmd.extend(['--delay','0'])
  label=f'xiamen_line{self.line_id}_{os.getpid()}_{self.sequence}';traci.start(cmd,label=label,numRetries=3)
  self.conn=traci.getConnection(label)
  if gui:self.conn.gui.setSchema('View #0',f'XiamenLine{self.line_id}')
  self.direction=1 if direction>=0 else -1;initial=1 if self.direction==1 else self.last;edge=f'{"U" if self.direction==1 else "D"}{initial:02}'
  self.conn.route.add('initial',[edge]);self.conn.vehicle.add('metro1','initial',typeID='metro',departPos='229.9',departSpeed='0')
  self.conn.vehicle.setStop('metro1',edge,pos=230,duration=1e9);self.conn.simulationStep()
  self.target=initial;self.current=initial;self.dest_edge=edge;self.route=[edge];self.arrived=False;self.auto=False;self.paused=False;self.distance=0;self.visits=[];self.events=[];self.pending=None;self.last_heading=None;self.last_reversed=False
  self.reset_history()
  for _ in range(80):
   self.step()
   if self.arrived:break
  if not self.arrived:raise RuntimeError('始发站停车失败。')
  self.paused=True;self.status=f'就绪 · {self.stations[initial]["name"]}'
 def reset_history(self):
  v=self.conn.vehicle;shape=self.net.getLane(v.getLaneID('metro1')).getShape();pos=v.getLanePosition('metro1');self.history.clear()
  for d in range(-int(self.train_length)-20,1):self.history.append((self.distance+d,sumolib.geomhelper.positionAtShapeOffset(shape,max(0,pos+d))))
 def go(self,station):
  if not self.conn:raise RuntimeError('请先启动仿真。')
  station=int(station)
  if station not in self.stations:raise ValueError(f'站点编号须为 1～{self.last}。')
  if station not in self.enabled:raise ValueError('该站在此试乘方案中跳停，不能选为停靠目的站。')
  v=self.conn.vehicle;current=v.getRoadID('metro1')
  if current.startswith(':'):
   self.pending=station;self.paused=False;self.status=f'通过连接轨道后驶向 {self.stations[station]["name"]}';return
  self.pending=None
  if self.arrived and self.current==station:self.status=f'已在 {self.stations[station]["name"]}';return
  candidates=[]
  destinations=[f'U{station:02}',f'D{station:02}'] if station not in (1,self.last) else (['D01'] if station==1 else [f'U{self.last:02}'])
  for dest in destinations:
   route=list(self.conn.simulation.findRoute(current,dest,vType='metro').edges)
   if not route:continue
   if current==dest and v.getLanePosition('metro1')>=229:
    options=[]
    for outgoing in self.net.getEdge(current).getOutgoing():
     tail=list(self.conn.simulation.findRoute(outgoing.getID(),dest,vType='metro').edges)
     if tail:options.append([current]+tail)
    route=min(options,key=lambda r:sum(self.net.getEdge(x).getLength() for x in r)) if options else []
   if route:candidates.append((sum(self.net.getEdge(x).getLength() for x in route),dest,route))
  if not candidates:raise RuntimeError('没有可达轨道，请重新启动仿真。')
  _,dest,route=min(candidates,key=lambda x:x[0])
  # Remove old stops in reverse order, preserving live vehicle state.
  while v.getStops('metro1'):
   if v.isStopped('metro1'):v.resume('metro1')
   else:
    stop=v.getStops('metro1')[0];v.setStop('metro1',stop.lane.rsplit('_',1)[0],pos=stop.endPos,duration=0)
  v.setRoute('metro1',route)
  for terminal,reverse in [(f'U{self.last:02}',f'RU{self.last:02}'),('D01','RD01')]:
   if terminal in route and reverse in route and terminal!=current:
    v.setStop('metro1',terminal,pos=230,duration=self.terminal_dwell)
  v.setStop('metro1',dest,pos=230,duration=1e9);v.setMaxSpeed('metro1',self.speed)
  self.target=station;self.dest_edge=dest;self.route=route;self.arrived=False;self.paused=False;self.status=f'驶向 {self.stations[station]["name"]}'
 def next_station(self):
  if not self.conn:raise RuntimeError('请先启动仿真。')
  if not self.arrived:raise RuntimeError('请等列车到站后再发往下一站。')
  if self.current==self.last:self.direction=-1
  elif self.current==1:self.direction=1
  candidates=[i for i in self.enabled if (i-self.current)*self.direction>0]
  if not candidates:raise RuntimeError('没有下一停靠站。')
  self.go(min(candidates) if self.direction==1 else max(candidates))
 def set_auto(self,value):
  if not self.conn:raise RuntimeError('请先启动仿真。')
  self.auto=bool(value)
  if value:
   self.paused=False
   if self.arrived:self.dwell_until=self.conn.simulation.getTime()
 def step(self):
  if not self.conn:return
  self.conn.simulationStep();v=self.conn.vehicle
  if 'metro1' not in v.getIDList():raise RuntimeError('列车离开轨道，请重置仿真。')
  self.distance=v.getDistance('metro1');xy=v.getPosition('metro1');heading=v.getAngle('metro1');edge=v.getRoadID('metro1')
  if self.last_heading is not None and abs((heading-self.last_heading+180)%360-180)>120 and v.getSpeed('metro1')<2:
   self.reset_history();self.events.append({'line':self.line_id,'event':'terminal_reversal','edge':edge,'time':self.conn.simulation.getTime()})
  self.last_heading=heading
  if not self.history or self.distance>self.history[-1][0]+.005:self.history.append((self.distance,xy))
  if self.pending is not None and not edge.startswith(':'):self.go(self.pending)
  if v.isStopped('metro1') and edge==self.dest_edge and not self.arrived:
   self.arrived=True;self.current=self.target
   self.direction=1 if self.dest_edge.startswith('U') else -1
   self.visits.append(self.current);self.events.append({'line':self.line_id,'event':'arrival','station':self.current,'name':self.stations[self.current]['name'],'time':self.conn.simulation.getTime()})
   self.status=f'已到达 {self.stations[self.current]["name"]}'
   self.dwell_until=self.conn.simulation.getTime()+(self.terminal_dwell if self.current in (1,self.last) else self.dwell)
  elif not self.arrived and v.isStopped('metro1') and edge in (f'U{self.last:02}','D01'):
   self.status=(self.stations[self.last]['name'] if edge==f'U{self.last:02}' else self.stations[1]['name'])+' · 折返停车'
  elif not self.arrived:self.status=f'驶向 {self.stations[self.target]["name"]}'
  if self.auto and self.arrived and self.conn.simulation.getTime()>=getattr(self,'dwell_until',0):self.next_station()
 def point_behind(self,offset):
  wanted=self.distance-offset;previous=None
  for d,xy in self.history:
   if d>=wanted:
    if previous is None:return xy
    d0,p0=previous;f=(wanted-d0)/max(.00001,d-d0);return p0[0]+f*(xy[0]-p0[0]),p0[1]+f*(xy[1]-p0[1])
   previous=d,xy
  return previous[1] if previous else (0,0)
 def track_shape(self,edges):
  pts=[]
  for k,eid in enumerate(edges):
   pts.extend(self.net.getEdge(eid).getLane(0).getShape())
   if k+1<len(edges):
    pair=eid,edges[k+1];seen=set()
    while pair in self.links and pair not in seen:
     seen.add(pair);lane=self.links[pair];pts.extend(self.net.getLane(lane).getShape());pair=lane.rsplit('_',1)[0],edges[k+1]
  return pts
 def snapshot(self):
  if not self.conn:return None
  return self.conn.vehicle.getPosition('metro1'),self.conn.vehicle.getSpeed('metro1'),self.conn.simulation.getTime()
 def close(self):
  if self.conn:
   try:self.conn.close()
   except Exception:pass
   self.conn=None

if __name__=='__main__':
 from shared_panel import run_app
 run_app()
