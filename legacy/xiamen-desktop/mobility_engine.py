"""Real bus/walk/metro passenger stages on the engine's one SUMO connection.

One CG person is a representative cohort of up to 20 people. SUMO handles
its walking, vehicle boarding, stops, transfers and arrival. Aggregate
counts use the stored cohort weight, including a final partial cohort.
The four B services are explicitly schematic feeder demonstrations.
"""
from pathlib import Path
import json
import math
import sys
from collections import deque

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'runtime/sumo/tools'))
import traci
from traci import constants as tc


class MobilityManager:
    PEOPLE_PER_DOT = 20

    def __init__(self, engine):
        self.engine = engine
        path = ROOT/'network/multimodal.routes.json'
        self.available = path.exists()
        self.routes = json.loads(path.read_text(encoding='utf-8'))['routes'] if self.available else {}
        for route in self.routes.values():
            route.update(active=False, next_depart=0., sequence=0)
        self.buses = {}
        self.groups = {}
        self.boardings = []
        self.completed = []
        self.events = deque(maxlen=150)
        self.demand_enabled = False
        self.next_demand = 0.
        self.demand_index = 0
        self._sequence = 0
        self._pois = set()
        self._dot_values = {}
        self._active_groups = set()
        self._stats_cache = None
        self._snapshot_cache = None
        self._people_total = self._people_arrived = 0
        self._bus_boardings = self._metro_boardings = 0
        self._journey_completed_people = 0
        self._journey_person_seconds = 0.
        self._completed_wait_person_seconds = 0.
        self._waiting_person_seconds = 0.
        self._walk_routes = {}
        self._validated_conn = None
        self._community_routes = {r['community_name']:r for r in self.routes.values()}

    def _invalidate(self):
        self._stats_cache = None
        self._snapshot_cache = None

    @property
    def conn(self):
        return self.engine.conn

    def _ensure(self):
        if not self.available:
            raise RuntimeError('公交接驳场景尚未构建，请先运行 tools/build_multimodal.py。')
        self.engine.start()
        if self._validated_conn is not self.conn:
            if 'feeder_bus' not in self.conn.vehicletype.getIDList():
                raise RuntimeError('当前 SUMO 使用旧路网，请关闭并重新启动联合仿真。')
            self._validated_conn = self.conn

    def endpoints(self):
        return [r['community_name'] for r in self.routes.values()] + sorted(self.engine.by_name)

    def bus_lines(self):
        return [dict(r) for r in self.routes.values()]

    def start_bus(self, routeid, headway=None):
        if routeid not in self.routes:
            raise ValueError('请选择有效的接驳线路。')
        self._ensure()
        if headway is not None:
            self.set_bus_headway(routeid, headway)
        route = self.routes[routeid]
        if not route['active']:
            route['next_depart'] = self.engine.time
        route['active'] = True
        self._invalidate()
        self.engine.paused = False
        self.engine.events.append(route['name']+' 已开启 · 公交与地铁共用仿真时钟')

    def start_buses(self):
        for routeid in self.routes:
            self.start_bus(routeid)

    def stop_bus(self, routeid):
        self.routes[routeid]['active'] = False
        self._invalidate()
        self.engine.events.append(self.routes[routeid]['name']+' 停止新增班次；在途公交继续运行')

    def set_bus_headway(self, routeid, seconds):
        seconds = int(seconds)
        if not 30 <= seconds <= 1200:
            raise ValueError('接驳公交间隔应为 30～1200 秒。')
        route = self.routes[routeid]
        route['headway'] = seconds
        route['next_depart'] = min(route['next_depart'], self.engine.time+seconds)

    def set_demand_enabled(self, enabled):
        self.demand_enabled = bool(enabled)
        self._invalidate()
        if self.demand_enabled:
            self._ensure()
            self.start_buses()
            self.next_demand = self.engine.time
            self.engine.paused = False

    def _community(self, label):
        return self._community_routes.get(label)

    def _walk(self, stages, current, target, stop=''):
        start_edge, start_pos = current
        end_edge, end_pos = target
        key = (start_edge, end_edge)
        edges = self._walk_routes.get(key)
        if edges is None:
            edges = [start_edge] if start_edge==end_edge else list(
                self.conn.simulation.findRoute(start_edge, end_edge, vType='walker').edges)
            self._walk_routes[key] = edges
        if not edges:
            raise RuntimeError('公交与地铁步行换乘通道不连通。')
        stages.append(traci.simulation.Stage(type=tc.STAGE_WALKING, edges=edges,
                      departPos=start_pos, arrivalPos=end_pos, destStop=stop, travelTime=-1))
        return target

    def _plan(self, origin, destination):
        inbound, outbound = self._community(origin), self._community(destination)
        start_name = inbound['metro_hub'] if inbound else origin
        end_name = outbound['metro_hub'] if outbound else destination
        if start_name not in self.engine.by_name or end_name not in self.engine.by_name:
            raise ValueError('请选择已建模的地铁站或接驳社区。')
        segments = [] if start_name==end_name else self.engine.plan(start_name, end_name)
        if segments:
            first = self.engine.stations[segments[0]['line']][segments[0]['start']-1]
        else:
            lid, idx = self.engine.by_name[start_name][0]
            first = self.engine.stations[lid][idx-1]
        stages = []
        modes = []
        if inbound:
            initial = (inbound['community_walk'], inbound['community_walk_pos'])
            current = self._walk(stages, initial, initial, inbound['id']+'_CI')
            target = (inbound['hub_walk'], inbound['hub_walk_pos'])
            stages.append(traci.simulation.Stage(type=tc.STAGE_DRIVING, edges=[inbound['id']+'_I'],
                          line=inbound['id'], destStop=inbound['id']+'_HI', arrivalPos=target[1]))
            current = target
            modes.append(inbound['id']+' 公交')
        else:
            initial = (first['walk_edge'], first['walk_pos'])
            current = initial
        for seg in segments:
            lid, direction = seg['line'], seg['direction']
            start = self.engine.stations[lid][seg['start']-1]
            end = self.engine.stations[lid][seg['end']-1]
            current = self._walk(stages, current, (start['walk_edge'], start['walk_pos']),
                                 f'L{lid}_P{direction}{seg["start"]:02}')
            edge = f'L{lid}_{direction}{seg["end"]:02}'
            # Match the original terminal reversing platform stop convention.
            if direction=='U' and seg['end']==1:
                edge = f'L{lid}_RD01'
            if direction=='D' and seg['end']==len(self.engine.stations[lid]):
                edge = f'L{lid}_RU{seg["end"]:02}'
            target = (end['walk_edge'], end['walk_pos'])
            stages.append(traci.simulation.Stage(type=tc.STAGE_DRIVING, edges=[edge], line=f'L{lid}',
                          destStop=f'L{lid}_P{direction}{seg["end"]:02}', arrivalPos=target[1]))
            current = target
            modes.append(f'{lid}号线')
        if outbound:
            target = (outbound['hub_walk'], outbound['hub_walk_pos'])
            current = self._walk(stages, current, target, outbound['id']+'_HO')
            target = (outbound['community_walk'], outbound['community_walk_pos'])
            stages.append(traci.simulation.Stage(type=tc.STAGE_DRIVING, edges=[outbound['id']+'_O'],
                          line=outbound['id'], destStop=outbound['id']+'_CO', arrivalPos=target[1]))
            current = target
            modes.append(outbound['id']+' 公交')
        self._walk(stages, current, current)
        return initial, stages, segments, inbound, outbound, modes

    def add_group(self, origin, destination, count=20):
        count = int(count)
        if not 1 <= count <= 2000:
            raise ValueError('每次客流应为 1～2000 人。')
        if origin==destination:
            raise ValueError('起点和终点请选择不同地点。')
        self._ensure()
        initial, stages, segments, inbound, outbound, modes = self._plan(origin, destination)
        # Construct and validate all stages before enabling affected services.
        for route in (inbound, outbound):
            if route:
                self.start_bus(route['id'])
        for seg in segments:
            if not self.engine.settings[seg['line']]['enabled']:
                self.engine.start_line(seg['line'])
        created = []
        for offset in range(0, count, self.PEOPLE_PER_DOT):
            weight = min(self.PEOPLE_PER_DOT, count-offset)
            self._sequence += 1
            pid = f'CG{self._sequence:05d}'
            self.conn.person.add(pid, initial[0], initial[1], typeID='crowd20')
            self.conn.person.setColor(pid,(0,0,0,0))
            try:
                for stage in stages:
                    self.conn.person.appendStage(pid, stage)
                self.conn.person.setParameter(pid, 'cohort.people', str(weight))
            except Exception:
                self.conn.person.remove(pid)
                raise
            self.groups[pid] = dict(id=pid, count=weight, origin=origin, destination=destination,
                                   plan=' → 换乘 → '.join(modes) if modes else '步行',
                                   status='进入站点', seen=False, active=True, rides=[], position=None,
                                   vehicle='', station=(inbound['metro_hub'] if inbound else origin),
                                   line=None, created=self.engine.time, arrival=None, mode='walking',
                                   timing_seconds={mode:0. for mode in ('pending','walking','waiting','bus','metro')},
                                   _timing_last=self.engine.time, _wait_started=None)
            self.engine.subscribe_person(pid)
            self._active_groups.add(pid)
            self._people_total += weight
            created.append(pid)
        self._invalidate()
        self.engine.paused = False
        self.engine.events.append(f'新增 {count} 人 · {len(created)} 个客流点 · {origin} → {destination}')
        return created

    def _spawn_bus(self, rid, route):
        route['sequence'] += 1
        vid = f'{rid}-{route["sequence"]:04d}'
        self.conn.vehicle.add(vid, rid+'_Service', typeID='feeder_bus', depart='now',
                              departPos='5', departSpeed='0', line=rid)
        color = tuple(int(route['color'][i:i+2], 16) for i in (1, 3, 5))
        self.conn.vehicle.setColor(vid, color)
        self.conn.vehicle.subscribe(vid,[tc.VAR_POSITION,tc.VAR_SPEED,tc.VAR_ROAD_ID,
                                        tc.VAR_LANEPOSITION,tc.LAST_STEP_PERSON_ID_LIST])
        self.buses[vid] = dict(id=vid, line=rid, position=None, speed=0., active=False,
                              hub=route['metro_hub'], community_name=route['community_name'],
                              progress=0., direction='进城', edge='', people=0)
        self.events.append(f'{self.engine.time:.0f}s · {rid} 接驳公交发车')

    def _update_dot(self, group):
        # One circular POI follows each actual SUMO person in every stage.
        # The underlying pedestrian is transparent, avoiding a duplicate
        # triangle while walking and an invisible cohort while riding.
        poi = group['id']+'_20people'
        show = group['active'] and group['position'] is not None
        if show:
            x, y = group['position']
            phase = sum(ord(c) for c in group['id'])
            x += (phase % 5-2)*5
            y += (phase//5 % 5-2)*5
            color = {'bus':(247,188,91,240),'metro':(71,223,230,240),'waiting':(247,211,117,240),'walking':(111,212,219,240)}.get(group['mode'],(111,212,219,240))
            size = .8*math.sqrt(group['count']/self.PEOPLE_PER_DOT)
            if poi not in self._pois:
                self.conn.poi.add(poi, x, y, color, poiType=f'客流代表 {group["count"]} 人',
                                  layer=12, width=size, height=size)
                self._pois.add(poi)
            else:
                previous = self._dot_values.get(poi)
                if previous is None or previous[:2] != (x,y):
                    self.conn.poi.setPosition(poi, x, y)
                if previous is None or previous[2] != color:
                    self.conn.poi.setColor(poi, color)
            self._dot_values[poi] = (x,y,color)
        elif poi in self._pois:
            self.conn.poi.remove(poi, layer=12)
            self._pois.remove(poi)
            self._dot_values.pop(poi,None)

    def _record_timing(self, group, now):
        """Accrue the previous cached passenger stage at the physical step resolution.

        The interval before the first subscription result is pending insertion,
        not walking or waiting. Stage changes are observed on 0.5 s boundaries;
        no extra SUMO query or physical simulation step is introduced.
        """
        previous = group['mode'] if group['seen'] else 'pending'
        elapsed = max(0., now-group['_timing_last'])
        if group['active'] and elapsed:
            group['timing_seconds'][previous] += elapsed
            if previous=='waiting':self._waiting_person_seconds += elapsed*group['count']
        group['_timing_last'] = now
        return previous

    def tick(self, frame=None):
        if not self.conn or self.engine.paused:
            return
        now = self.engine.time
        self._invalidate()
        frame = frame if frame is not None else self.engine.frame
        for rid, route in self.routes.items():
            fleet = sum(b['line']==rid for b in self.buses.values())
            if route['active'] and now>=route['next_depart'] and fleet<8:
                self._spawn_bus(rid, route)
                route['next_depart'] = now+route['headway']
        if self.demand_enabled and now>=self.next_demand:
            communities = [r['community_name'] for r in self.routes.values()]
            origin = communities[self.demand_index%len(communities)]
            dest = communities[(self.demand_index+1)%len(communities)]
            # Small deterministic demonstration demand; no implied real
            # passenger counts or official timetables.
            if len(self._active_groups)<250:
                self.add_group(origin, dest, 40)
            self.demand_index += 1
            self.next_demand = now+120
        ids = frame['active_vehicles']
        pending = frame['pending_vehicles']
        vehicle_readings = frame['vehicle_readings']
        for vid in list(self.buses):
            bus = self.buses[vid]
            if vid not in ids:
                if bus['active'] and vid not in pending:
                    del self.buses[vid]
                continue
            bus['active'] = True
            reading = vehicle_readings.get(vid)
            if reading is None:continue
            bus['position'] = reading[tc.VAR_POSITION]
            bus['speed'] = reading[tc.VAR_SPEED]
            bus['edge'] = reading[tc.VAR_ROAD_ID]
            if bus['edge'].endswith('_I'):
                bus['direction'] = '进城'
                bus['progress'] = reading[tc.VAR_LANEPOSITION]/1200
            elif bus['edge'].endswith('_O'):
                bus['direction'] = '出城'
                bus['progress'] = 1-reading[tc.VAR_LANEPOSITION]/1200
            elif bus['edge'].endswith('_TB'):
                bus['progress'] = 1.
            elif bus['edge'].endswith('_TA'):
                bus['progress'] = 0.
            onboard = reading.get(tc.LAST_STEP_PERSON_ID_LIST,())
            bus['people'] = sum(self.groups[pid]['count'] if pid in self.groups else 1 for pid in onboard)
        persons = frame['person_readings']
        for pid in tuple(self._active_groups):
            group = self.groups[pid]
            previous_mode = self._record_timing(group, now)
            if pid in persons:
                group['seen'] = True
                reading = persons[pid]
                group['position'] = reading[tc.VAR_POSITION]
                vehicle = reading[tc.VAR_VEHICLE]
                group['vehicle'] = vehicle
                if vehicle:
                    mode = 'bus' if vehicle.startswith('B') else 'metro'
                    group['mode'] = mode
                    group['status'] = ('乘坐公交 ' if mode=='bus' else '乘坐地铁 ')+vehicle
                    group['line'] = vehicle.split('-')[0]
                    if not group['rides'] or group['rides'][-1]!=vehicle:
                        group['rides'].append(vehicle)
                        self.boardings.append(dict(time=now, id=pid, count=group['count'], vehicle=vehicle, mode=mode))
                        if mode=='bus':self._bus_boardings += group['count']
                        else:self._metro_boardings += group['count']
                        self.events.append(f'{pid} · {group["count"]} 人上车 {vehicle}')
                else:
                    stage = reading[tc.VAR_STAGE]
                    group['mode'] = 'waiting' if stage.type==tc.STAGE_DRIVING else 'walking'
                    group['status'] = '候车 / 等待换乘' if group['mode']=='waiting' else '步行换乘'
                    edge = reading[tc.VAR_ROAD_ID]
                    if edge.startswith('B'):
                        route = self.routes.get(edge.split('_')[0])
                        if route:
                            group['station'] = route['metro_hub']
                    else:
                        station = self.engine.walk_stations.get(edge)
                        if station:group['station'] = station['name']
                if group['mode']=='waiting':
                    if previous_mode!='waiting' or group['_wait_started'] is None:group['_wait_started']=now
                else:group['_wait_started']=None
                self._update_dot(group)
            elif group['seen'] and group['active']:
                group.update(active=False, status='已到达', mode='arrived', vehicle='', arrival=now)
                self._active_groups.discard(pid)
                self._people_arrived += group['count']
                group['_wait_started'] = None
                journey = now-group['created']
                waiting = group['timing_seconds']['waiting']
                self._journey_completed_people += group['count']
                self._journey_person_seconds += journey*group['count']
                self._completed_wait_person_seconds += waiting*group['count']
                self._update_dot(group)
                self.completed.append(dict(id=pid, count=group['count'], arrival=now,
                                           origin=group['origin'], destination=group['destination'], rides=group['rides'],
                                           journey_seconds=journey, waiting_seconds=waiting,
                                           timing_seconds=dict(group['timing_seconds'])))
                self.events.append(f'{pid} · {group["count"]} 人抵达 {group["destination"]}')

    def stats(self):
        if self._stats_cache is not None:return self._stats_cache
        groups = [self.groups[pid] for pid in self._active_groups]
        self._stats_cache = dict(bus_active=sum(b['active'] for b in self.buses.values()),
                    groups_active=len(groups),
                    people_waiting=sum(g['count'] for g in groups if g['active'] and g['mode']=='waiting'),
                    people_walking=sum(g['count'] for g in groups if g['active'] and g['mode']=='walking'),
                    people_onboard=sum(g['count'] for g in groups if g['active'] and g['vehicle']),
                    people_arrived=self._people_arrived,
                    people_total=self._people_total,
                    bus_boardings=self._bus_boardings,
                    metro_boardings=self._metro_boardings,
                    demand_enabled=self.demand_enabled, people_per_dot=self.PEOPLE_PER_DOT,
                    bus_capacity_people=80,
                    journey_completed_people=self._journey_completed_people,
                    mean_journey_seconds=(self._journey_person_seconds/self._journey_completed_people
                                          if self._journey_completed_people else None),
                    mean_waiting_seconds=(self._completed_wait_person_seconds/self._journey_completed_people
                                          if self._journey_completed_people else None),
                    waiting_person_seconds=self._waiting_person_seconds,
                    longest_waiting_seconds=max((max(0.,self.engine.time-g['_wait_started'])
                                                 for g in groups if g['_wait_started'] is not None),default=0.),
                    timing_resolution_seconds=float(getattr(self.engine,'step_length',.5)))
        return self._stats_cache

    def snapshot(self):
        if self._snapshot_cache is None:
            self._snapshot_cache = dict(buses=[dict(b) for b in self.buses.values() if b['active']],
                    groups=[{**self.groups[pid], 'timing_seconds':dict(self.groups[pid]['timing_seconds'])}
                            for pid in self._active_groups if self.groups[pid]['seen']])
        return self._snapshot_cache

    def bus_snapshot(self):
        return self.snapshot()['buses']

    def person_snapshot(self):
        return self.snapshot()['groups']

    def reset(self):
        self.buses.clear()
        self.groups.clear()
        self.boardings.clear()
        self.completed.clear()
        self._pois.clear()
        self._dot_values.clear()
        self._active_groups.clear()
        self._walk_routes.clear()
        self._validated_conn = None
        self._people_total = self._people_arrived = 0
        self._bus_boardings = self._metro_boardings = 0
        self._journey_completed_people = 0
        self._journey_person_seconds = 0.
        self._completed_wait_person_seconds = 0.
        self._waiting_person_seconds = 0.
        self._invalidate()
        self.demand_enabled = False
        for route in self.routes.values():
            route.update(active=False, next_depart=0., sequence=0)
