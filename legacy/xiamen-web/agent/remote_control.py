"""Network IO is isolated; every simulation action executes on the Tk owner thread."""
import json,math,time,threading,queue,uuid,random,logging,urllib.parse
from collections import OrderedDict
from pathlib import Path
from run_assessment import build_assessment
import websocket

BASE=Path(__file__).resolve().parents[1]

class RemoteControl:
    def __init__(self,get_engine,reset,get_rate,set_rate,config=None,geo=None,get_actual_rate=None):
        self.get_engine=get_engine;self.reset=reset;self.get_rate=get_rate;self.set_rate=set_rate;self.get_actual_rate=get_actual_rate
        self.config=config or json.loads((BASE/'config/device.json').read_text(encoding='utf-8'))
        if not (self.config['url'].startswith('wss://') or self.config['url'].startswith('ws://127.0.0.1:')):
            raise ValueError('设备只允许 WSS 或本机测试连接')
        self.commands=queue.Queue(maxsize=32);self.results=queue.Queue(maxsize=32)
        self.stopping=threading.Event();self.connected=False;self.epoch=None;self.latest=None
        self.lock=threading.Lock();self.generation=str(uuid.uuid4());self.ledger=OrderedDict();self.sample_sequence=0
        self.tracked_engine=self.get_engine();self.last_publish=0;self.disconnect_seen=False;self.connection_label='正在连接';self.socket=None
        self.geo=geo
        try:
            if self.geo is None:
                from geo_map import GeoMap
                self.geo=GeoMap(BASE/'simulation')
        except Exception:pass
        self.thread=threading.Thread(target=self.network,daemon=True);self.thread.start()

    def network(self):
        backoff=1
        while not self.stopping.is_set():
            ws=None
            try:
                proxy=self.config.get('proxy',{})
                options={'timeout':8,'header':{'Authorization':'Bearer '+self.config['token']},'enable_multithread':True,
                         'http_no_proxy':['127.0.0.1','localhost']}
                if proxy.get('host'):options.update(http_proxy_host=proxy['host'],http_proxy_port=int(proxy['port']))
                else:options['http_no_proxy'].append(urllib.parse.urlparse(self.config['url']).hostname)
                ws=websocket.create_connection(self.config['url'],**options);ws.settimeout(.2)
                self.socket=ws;self.epoch=str(uuid.uuid4());self.connected=True;self.connection_label='已连接';connected_at=time.monotonic();last_send=0;last_payload=None;encoded=None
                while not self.stopping.is_set():
                    ws.settimeout(3)
                    while not self.results.empty():
                        packet=self.results.get_nowait()
                        if packet.pop('_epoch',None)==self.epoch:ws.send(json.dumps(packet,ensure_ascii=False))
                    now=time.monotonic()
                    if now-last_send>=.25:
                        with self.lock:payload=self.latest
                        if payload:
                            if payload is not last_payload:
                                encoded=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':'));last_payload=payload
                            ws.send(encoded)
                        last_send=now
                    ws.settimeout(max(.01,min(.2,.25-(time.monotonic()-last_send))))
                    try:
                        raw=ws.recv()
                        if not raw:raise ConnectionError('连接已关闭')
                        if len(raw)>16384:raise ValueError('指令过大')
                        packet=json.loads(raw)
                        if packet.get('type') in ('command','control_lost'):
                            packet['_epoch']=self.epoch
                            try:self.commands.put_nowait(packet)
                            except queue.Full:raise ConnectionError('指令队列已满')
                    except websocket.WebSocketTimeoutException:pass
                    if time.monotonic()-connected_at>=10:backoff=1
            except Exception as exc:
                logging.warning('Device transport reconnect: %s',type(exc).__name__)
                self.connection_label='离线 · 等待重连'
            finally:
                self.connected=False;self.epoch=None;self.socket=None
                if ws:
                    try:ws.close()
                    except Exception:pass
            self.stopping.wait(backoff*(.8+random.random()*.4));backoff=min(30,backoff*2)

    def pump(self):
        e=self.get_engine()
        if e is not self.tracked_engine:
            self.tracked_engine=e;self.generation=str(uuid.uuid4())
        if not self.connected and not self.disconnect_seen:
            if e.conn and not e.paused:e.paused=True;e.events.append('远程连接断开，已暂停仿真；可在本地继续')
            self._clear_commands()
            self.disconnect_seen=True
        if self.connected:self.disconnect_seen=False
        for _ in range(8):
            try:packet=self.commands.get_nowait()
            except queue.Empty:break
            if packet.get('_epoch')!=self.epoch or not self.connected:continue
            if packet['type']=='control_lost':
                e=self.get_engine()
                if e.conn:e.paused=True;e.events.append('网页控制者离线，仿真已暂停')
                continue
            result=self.execute(packet);result['_epoch']=packet['_epoch']
            try:self.results.put_nowait(result)
            except queue.Full:pass
        if time.monotonic()-self.last_publish>=.25:
            self.last_publish=time.monotonic()
            self.sample_sequence+=1
            with self.lock:self.latest={'type':'telemetry','sequence':self.sample_sequence,'state':self.snapshot()}

    @staticmethod
    def number(value,lo,hi):
        if isinstance(value,bool):raise ValueError('数值无效')
        n=float(value)
        if not math.isfinite(n) or not lo<=n<=hi:raise ValueError(f'数值应在 {lo:g}～{hi:g} 之间')
        return n

    def execute(self,p):
        result={'type':'result','id':p.get('id'),'ok':False}
        try:
            if not isinstance(p.get('id'),str) or len(p['id'])>80:raise ValueError('指令标识无效')
            if p['id'] in self.ledger:return dict(self.ledger[p['id']])
            if self.number(p.get('expires'),0,1e15)<time.time()*1000:raise ValueError('指令已过期')
            if p.get('generation')!=self.generation:raise ValueError('仿真会话已变化，请刷新状态后操作')
            action=p['action'];a=p.get('args',{});e=self.get_engine()
            if not isinstance(a,dict):raise ValueError('参数无效')
            if action=='start':
                if not e.conn:
                    with self.lock:
                        initial=self.snapshot();initial['status']='starting';self.sample_sequence+=1;self.latest={'type':'telemetry','sequence':self.sample_sequence,'state':initial}
                    # The network thread can publish the starting snapshot; no fixed startup sleep.
                e.start_all(False)
            elif action=='pause':e.paused=True
            elif action=='resume':
                if not e.conn:raise ValueError('请先启动仿真')
                e.paused=False
            elif action=='stop':
                if e.conn:self.reset();self.tracked_engine=self.get_engine();self.generation=str(uuid.uuid4())
            elif action=='rate':self.set_rate(self.number(a.get('value'),1,50))
            elif action in ('line_speed','headway','line_start','line_stop'):
                lid=int(self.number(a.get('line'),1,6))
                if lid not in e.settings:raise ValueError('请选择存在的线路')
                if action=='line_speed':e.set_speed(lid,self.number(a.get('value'),10,120))
                elif action=='headway':e.set_headway(lid,int(self.number(a.get('value'),60,600)))
                elif action=='line_start':e.start_line(lid,False)
                else:e.settings[lid]['enabled']=False
            elif action=='vehicle_speed':
                if not e.conn:raise ValueError('请先启动仿真')
                vid=a.get('id');ids=set(e.frame.get('active_vehicles',()))
                if not isinstance(vid,str) or vid not in ids:raise ValueError('车辆已离开或不存在')
                value=self.number(a.get('value'),-1,120)
                if value<0 and value!=-1:raise ValueError('恢复自动速度请使用 -1')
                if value>=0:
                    maximum=e.conn.vehicle.getMaxSpeed(vid)*3.6
                    if value>maximum:raise ValueError(f'不能超过车辆最大速度 {maximum:.1f} km/h')
                e.conn.vehicle.setSpeed(vid,value/3.6 if value>=0 else -1)
            elif action=='signal_hold':e.hold_signal(a.get('id'),self.number(a.get('seconds'),5,900))
            elif action=='signal_release':e.release_signal(a.get('id'))
            elif action in ('bus_start','bus_stop','demand'):
                if not e.mobility:raise ValueError('当前场景不支持公交')
                if not e.conn:raise ValueError('请先启动仿真')
                if action=='bus_start':e.mobility.start_buses()
                elif action=='bus_stop':e.mobility.stop_bus(a.get('id'))
                else:
                    if not isinstance(a.get('enabled'),bool):raise ValueError('客流开关无效')
                    e.mobility.set_demand_enabled(a['enabled'])
            elif action=='depot_enter':e.send_to_depot(a.get('id'),track=int(self.number(a.get('track',0),0,2)))
            elif action=='depot_release':e.release_from_depot(a.get('id'))
            else:raise ValueError('不支持的指令')
            result.update(ok=True,generation=self.generation,message='操作已执行')
        except Exception as exc:result['error']=str(exc)
        if isinstance(p.get('id'),str):
            self.ledger[p['id']]=dict(result)
            while len(self.ledger)>128:self.ledger.popitem(last=False)
        return result

    def snapshot(self):
        e=self.get_engine();vehicles=[];people=[];stats={}
        measured=self.get_actual_rate() if self.get_actual_rate else None
        if measured is not None and (not e.conn or e.paused):measured=0.
        for t in e.trains.values():
            if not t['active']:continue
            point=self.geo.train_point(t,e) if self.geo and self.geo.data else None
            vehicles.append({'id':t['id'],'kind':'train','line':t['line'],'position':t['position'],'geo':point,
                             'speed':round(t['speed']*3.6,1),'people':t.get('people',0),'edge':t['edge'],'depot':t.get('depot_phase','正线')})
        if e.mobility:
            for b in e.mobility.bus_snapshot():
                point=b.get('geo_point') or (self.geo.feeder_point(b.get('position'),b.get('hub'),e) if self.geo and self.geo.data else None)
                vehicles.append({'id':b['id'],'kind':'bus','line':b.get('line','公交'),'position':b['position'],'geo':point,
                                 'speed':round(b.get('speed',0)*3.6,1),'people':b.get('people',0),'edge':b.get('edge',''),'depot':'公交'})
        if e.mobility:
            buses={b['id']:b for b in e.mobility.bus_snapshot()}
            stats=dict(e.mobility.stats())
            for group in e.mobility.person_snapshot():
                if not group.get('active') or not group.get('position'):continue
                point=self.geo.crowd_point(group,e,buses) if self.geo and self.geo.data else None
                people.append({k:group.get(k) for k in ('id','position','mode','count','vehicle')})
                people[-1]['geo']=point
        signals=[{k:s[k] for k in ('id','line','position','state','mode','remaining','occupied')} for s in e.signal_list()]
        return {'generation':self.generation,'status':'ready' if not e.conn else 'paused' if e.paused else 'running',
                'time':round(e.time,1),'rate':self.get_rate(),'actual_rate':measured,
                'assessment':build_assessment(e,self.get_rate(),measured),'network':e.network_name,'vehicles':vehicles,'signals':signals,
                'people':people,'mobility':stats,'settings':e.settings,'events':list(e.events)[-6:],'collisions':e.collisions,'teleports':e.teleports,
                'connection':self.connection_label,'backend':'libsumo 1.27.1',
                'geo_mapping':getattr(self.geo,'TRAIN_MAPPING_VERSION','legacy')}

    def shutdown(self):
        self.stopping.set()
        if self.socket:
            try:self.socket.close()
            except Exception:pass

    def _clear_commands(self):
        while True:
            try:self.commands.get_nowait()
            except queue.Empty:return
