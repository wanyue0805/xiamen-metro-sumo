"""Timed red holds with automatic restoration of SUMO rail interlocking."""
import math,re

class RailDispatch:
    def __init__(self, engine):
        self.engine=engine;self.signals={};self.holds={};self.original_programs={};self.readings={}
        self._ordered=();self._snapshots={};self._stats=None;self._markers=set()
        for node in engine.net.getNodes():
            match=re.match(r'L([12346])_',node.getID())
            if match and node.getType()=='rail_signal':
                self.signals[node.getID()]={'id':node.getID(),'line':int(match.group(1)),
                                            'position':node.getCoord(),'lanes':()}

    def attach(self):
        from traci import constants as tc
        conn=self.engine.conn;available=set(conn.trafficlight.getIDList())
        self.signals={sid:s for sid,s in self.signals.items() if sid in available}
        self._ordered=tuple(sorted(self.signals.items()))
        for sid,s in self.signals.items():
            self.original_programs[sid]=conn.trafficlight.getProgram(sid)
            s['lanes']=conn.trafficlight.getControlledLanes(sid)
            s['controlled_edges']=tuple({lane.rsplit('_',1)[0] for lane in s['lanes']})
            conn.trafficlight.subscribe(sid,[tc.TL_RED_YELLOW_GREEN_STATE,tc.TL_CURRENT_PROGRAM])
        self.update()

    def require(self,sid):
        if not self.engine.conn:raise RuntimeError('请先启动路网，再调度轨道信号。')
        if sid not in self.signals:raise ValueError('此信号不属于当前铁路网。')

    def hold(self,sid,seconds=60):
        self.require(sid);seconds=float(seconds)
        if not math.isfinite(seconds) or not 5<=seconds<=1800:
            raise ValueError('红灯保持时间须在 5～1800 秒仿真时间之间。')
        conn=self.engine.conn;state=conn.trafficlight.getRedYellowGreenState(sid)
        if not state:raise RuntimeError('信号没有可控制的轨道连接。')
        conn.trafficlight.setRedYellowGreenState(sid,'r'*len(state))
        self.holds[sid]={'until':self.engine.time+seconds,'seconds':seconds}
        self.engine.events.append(f'{self.engine.time:.0f}s · {sid} 保持红灯 {seconds:g} 秒')
        self._marker(sid,True)
        self.readings[sid]={'state':'r'*len(state),'program':'online'}
        self._snapshots.clear();self._stats=None

    def release(self,sid,automatic=False):
        self.require(sid)
        self.engine.conn.trafficlight.setProgram(sid,self.original_programs.get(sid,'0'))
        self.holds.pop(sid,None);self._marker(sid,False)
        self.engine.events.append(f'{self.engine.time:.0f}s · {sid} '+('到时恢复自动闭塞' if automatic else '恢复自动闭塞'))
        self.readings.pop(sid,None)
        self._snapshots.clear();self._stats=None

    def hold_line(self,lid,seconds=60):
        ids=[sid for sid,s in self.signals.items() if s['line']==int(lid)]
        if not ids:raise ValueError('本线没有可控制的轨道信号。')
        # Validate before mutating any rail signal.
        if not math.isfinite(float(seconds)) or not 5<=float(seconds)<=1800:raise ValueError('保持时间应为 5～1800 秒。')
        for sid in ids:self.require(sid)
        applied=[]
        try:
            for sid in ids:self.hold(sid,seconds);applied.append(sid)
        except Exception:
            for sid in applied:self.release(sid)
            raise
        return len(applied)

    def release_all(self,lid=None):
        ids=[sid for sid in self.holds if lid is None or self.signals[sid]['line']==int(lid)]
        for sid in ids:self.release(sid)
        return len(ids)

    def before_step(self):
        for sid,hold in list(self.holds.items()):
            if self.engine.time>=hold['until']:self.release(sid,automatic=True)

    def update(self):
        if not self.engine.conn:return
        from traci import constants as tc
        values=self.engine.conn.trafficlight.getAllSubscriptionResults()
        self._snapshots.clear();self._stats=None
        for sid,r in values.items():
            if sid in self.signals:self.readings[sid]={'state':r.get(tc.TL_RED_YELLOW_GREEN_STATE,''),'program':r.get(tc.TL_CURRENT_PROGRAM,'')}

    def snapshot(self,lid=None):
        key=None if lid is None else int(lid)
        if key in self._snapshots:return self._snapshots[key]
        occupied={t['edge'] for t in self.engine.trains.values() if t['active']}
        result=[]
        for sid,s in self._ordered or sorted(self.signals.items()):
            if lid is not None and s['line']!=int(lid):continue
            r=self.readings.get(sid,{})
            result.append({**s,'state':r.get('state','—'),
                'mode':'红灯保持' if sid in self.holds else ('自动闭塞' if self.engine.conn else '未启动'),
                'remaining':max(0,self.holds.get(sid,{}).get('until',self.engine.time)-self.engine.time),
                'occupied':sum(edge in occupied for edge in s.get('controlled_edges',())),
                'program':r.get('program','')})
        self._snapshots[key]=result
        return result

    def stats(self):
        if self._stats is not None:return self._stats
        states=[r.get('state','') for r in self.readings.values()]
        self._stats={'total':len(self.signals),'held':len(self.holds),
                'red':sum(bool(s) and set(s.lower())=={'r'} for s in states),
                'green':sum('g' in s.lower() for s in states),'automatic':len(self.signals)-len(self.holds)}
        return self._stats

    def _marker(self,sid,held):
        # A timed hold is visible in the native SUMO view as a labeled red marker.
        conn=self.engine.conn;pid='DISPATCH_'+sid
        if held:
            if pid not in self._markers:
                x,y=self.signals[sid]['position'];conn.poi.add(pid,x,y,(255,90,95,255),poiType='调度红灯 '+sid,layer=12,width=1.5,height=1.5)
                self._markers.add(pid)
        elif pid in self._markers:
            conn.poi.remove(pid,layer=12);self._markers.remove(pid)
