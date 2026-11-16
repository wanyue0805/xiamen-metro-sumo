"""Cooperative, single-threaded wall-clock pacing for the Tk SUMO panel."""
from collections import deque
import math
import time


def timing_summary(values):
    values=sorted(values)
    if not values:return {'count':0,'mean_ms':0,'p95_ms':0,'max_ms':0}
    return {'count':len(values),'mean_ms':round(sum(values)/len(values),3),
            'p95_ms':round(values[min(len(values)-1,math.ceil(len(values)*.95)-1)],3),
            'max_ms':round(values[-1],3)}


class BudgetStepper:
    """Accrue simulated seconds, spend them on actual engine time increments.

    At most four simulation steps are attempted per callback and no new step
    starts after the 8 ms budget. A single TraCI step remains indivisible.
    Outstanding time is bounded; pausing clears it rather than racing ahead
    on resume. All calls stay on the Tk/TraCI owning thread.
    """
    def __init__(self,clock=time.perf_counter,budget_ms=8,max_steps=4):
        self.clock=clock;self.budget=budget_ms/1000;self.max_steps=max_steps
        self.last_wall=clock();self.credit=0.;self.quantum=.5;self.engine=None
        self.steps=0;self.dropped_seconds=0.;self.step_ms=deque(maxlen=5000)
        self.samples=deque();self.actual_rate=0.

    def reset(self,engine=None):
        self.engine=engine;self.credit=0.;self.last_wall=self.clock();self.samples.clear();self.actual_rate=0.

    def advance(self,engine,target_rate):
        now=self.clock()
        if engine is not self.engine:self.reset(engine)
        elapsed=max(0,min(.25,now-self.last_wall));self.last_wall=now
        if not engine.conn or engine.paused:
            self.credit=0.;self.samples.clear();self.actual_rate=0.;return 0
        rate=max(1,min(100,float(target_rate)));limit=max(1,min(10,rate*.20))
        self.credit+=elapsed*rate
        if self.credit>limit:self.dropped_seconds+=self.credit-limit;self.credit=limit
        self.quantum=float(getattr(engine,'step_length',self.quantum))
        deadline=self.clock()+self.budget;count=0
        while self.credit+1e-9>=self.quantum and count<self.max_steps and self.clock()<deadline:
            start=self.clock();previous=engine.time;engine.step();delta=engine.time-previous
            self.step_ms.append((self.clock()-start)*1000)
            if delta<=0:self.credit=0.;break
            self.quantum=delta;self.credit=max(0,self.credit-delta);count+=1;self.steps+=1
        sampled=self.clock();self.samples.append((sampled,engine.time))
        while len(self.samples)>2 and self.samples[0][0]<sampled-3:self.samples.popleft()
        if len(self.samples)>1:
            wall=sampled-self.samples[0][0]
            self.actual_rate=(engine.time-self.samples[0][1])/wall if wall else 0.
        return count

    def report(self):
        return {'callback_budget_ms':self.budget*1000,'max_steps_per_callback':self.max_steps,
                'step_length_seconds':self.quantum,'steps':self.steps,
                'dropped_backlog_seconds':round(self.dropped_seconds,3),
                'outstanding_seconds':round(self.credit,3),'actual_rate':round(self.actual_rate,2),
                'step_timing':timing_summary(list(self.step_ms))}


class UiMeasurements:
    def __init__(self):
        self.heartbeat=[];self.frames=[];self.metrics=[];self.map_frames=[];self.near_frames=[]
        self.paint_ms=deque(maxlen=3000)
        self.active=False;self.phases=[];self.phase=None

    def begin_phase(self,name,engine,stepper):
        self.active=True;self.phase={'target_rate':name,'start_wall':time.perf_counter(),
            'start_sim':engine.time,'steps':stepper.steps,'dropped':stepper.dropped_seconds,
            'heartbeat_index':len(self.heartbeat),'frames_index':len(self.frames)}

    def finish_phase(self,engine,stepper):
        phase=self.phase
        if not phase:return
        wall=time.perf_counter()-phase['start_wall'];sim=engine.time-phase['start_sim']
        self.phases.append({'target_rate':phase['target_rate'],'wall_seconds':round(wall,3),
            'simulation_seconds':round(sim,3),'achieved_rate':round(sim/wall,2) if wall else 0,
            'steps':stepper.steps-phase['steps'],'frames':len(self.frames)-phase['frames_index'],
            'dropped_backlog_seconds':round(stepper.dropped_seconds-phase['dropped'],3),
            'heartbeat_lateness':timing_summary(self.heartbeat[phase['heartbeat_index']:]),
            'frame_timing':timing_summary(self.frames[phase['frames_index']:])})
        self.phase=None

    def report(self,engine,stepper):
        return {'version':'3.0','phases':self.phases,'heartbeat_interval_ms':30,
            'heartbeat_lateness':timing_summary(self.heartbeat),'frame_timing':timing_summary(self.frames),
            'map_timing':timing_summary(self.map_frames),'near_view_timing':timing_summary(self.near_frames),
            'frame_through_idle_timing':timing_summary(list(self.paint_ms)),
            'metrics_timing':timing_summary(self.metrics),'scheduler':stepper.report(),
            'simulation_time':engine.time,'network':getattr(engine,'network_name',''),
            'active_trains':sum(t['active'] for t in engine.trains.values()),
            'people':engine.mobility.stats() if getattr(engine,'mobility',None) else {},
            'scope':'Actual Tk event loop and live SUMO; startup excluded; no synchronous prewarming.'}


def acquire_timer_resolution():
    """Scope the Windows timer request to this running panel, release on close.

    A 10 ms Tk callback otherwise often sleeps for a 15.6 ms timer quantum.
    Failure leaves the normal Windows timer in place.
    """
    import os
    if os.name!='nt':return lambda:None
    import ctypes
    winmm=ctypes.WinDLL('winmm');active=winmm.timeBeginPeriod(1)==0
    def release():
        nonlocal active
        if active:winmm.timeEndPeriod(1);active=False
    return release
