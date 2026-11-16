"""Read-only operational assessment and exports. No simulation commands."""
from pathlib import Path
from datetime import datetime,timezone
import json,csv,math,uuid

def build_assessment(engine,target_rate,actual_rate=None):
    if not hasattr(engine,'_assessment_id'):engine._assessment_id=str(uuid.uuid4())
    manager=getattr(engine,'mobility',None)
    people=dict(manager.stats()) if manager else {}
    if not hasattr(engine,'_assessment_departures'):
        engine._assessment_departures={'index':0,'lines':{}}
    cache=engine._assessment_departures
    if cache['index']>len(engine.departures):cache={'index':0,'lines':{}};engine._assessment_departures=cache
    for event in engine.departures[cache['index']:]:
        key=str(event['line']);line=cache['lines'].setdefault(key,{'count':0,'delay_sum':0.,'max_delay':0.})
        scheduled=event.get('scheduled');scheduled=event['time'] if scheduled is None else scheduled
        delay=max(0.,float(event['time'])-float(scheduled))
        line['count']+=1;line['delay_sum']+=delay;line['max_delay']=max(line['max_delay'],delay)
    cache['index']=len(engine.departures)
    departures={key:{'count':value['count'],'mean_release_delay_seconds':round(value['delay_sum']/value['count'],3),
                        'max_release_delay_seconds':round(value['max_delay'],3)} for key,value in cache['lines'].items()}
    measured=float(actual_rate) if actual_rate is not None else None
    if measured is not None and not math.isfinite(measured):measured=None
    trains=[t for t in engine.trains.values() if t['active']]
    total=people.get('people_total',0);arrived=people.get('people_arrived',0)
    return {'schema':'xiamen-simulation-assessment-v1','session_id':engine._assessment_id,
            'generated_at':datetime.now(timezone.utc).isoformat(),'simulation_seconds':round(engine.time,3),
            'status':'ready' if not engine.conn else 'paused' if engine.paused else 'running',
            'network':engine.network_name,'scope':'仿真设计参数；未接入真实列车或现场信号',
            'rate':{'target':float(target_rate),'actual':round(measured,2) if measured is not None else None},
            'fleet':{'trains_active':len(trains),'people_on_trains':sum(t.get('people',0) for t in trains),
                     'person_objects_on_trains':sum(t.get('passenger_objects',0) for t in trains),
                     'buses_active':people.get('bus_active',0)},
            'passengers':{**people,'unfinished_people':max(0,total-arrived),
                          'completion_fraction':round(arrived/total,6) if total else None},
            'terminal_departures':departures,
            'parameters':{'lines':{str(key):{name:value.get(name) for name in ('enabled','headway','speed','cap')} for key,value in engine.settings.items()},
                          'buses':[{name:r.get(name) for name in ('id','headway','active')} for r in manager.bus_lines()] if manager else []},
            'parameter_units':{'headway':'simulation_seconds','speed':'km/h','cap':'trains'},
            'collisions':engine.collisions,'teleports':engine.teleports,
            'notes':['行程和候车均值仅统计已完成的聚合乘客，按实际人数加权。',
                     '未完成行程另列，不能只凭已到达乘客均值判断方案优劣。',
                     '端点释放偏差来自模型内部计划，不是官方时刻表晚点。']}

def save_assessment(path,engine,target_rate,actual_rate=None):
    path=Path(path).with_suffix('.json');path.parent.mkdir(parents=True,exist_ok=True)
    report=build_assessment(engine,target_rate,actual_rate)
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    manager=getattr(engine,'mobility',None);csv_path=path.with_suffix('.csv')
    fields=['id','people','origin','destination','active','created_seconds','arrival_seconds','journey_seconds','waiting_seconds','pending_seconds','walking_seconds','bus_seconds','metro_seconds']
    with csv_path.open('w',encoding='utf-8-sig',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        if manager:
            for group in manager.groups.values():
                timing=group.get('timing_seconds',{})
                row={'id':group['id'],'people':group['count'],'origin':group['origin'],'destination':group['destination'],
                     'active':group['active'],'created_seconds':group['created'],'arrival_seconds':group.get('arrival'),
                     'journey_seconds':None if group.get('arrival') is None else group['arrival']-group['created'],
                     'waiting_seconds':timing.get('waiting',0)}
                row.update({phase+'_seconds':timing.get(phase,0) for phase in ['pending','walking','bus','metro']});writer.writerow(row)
    return path,csv_path
