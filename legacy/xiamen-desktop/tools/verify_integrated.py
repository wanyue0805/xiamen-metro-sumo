"""End-to-end check of weighted bus/metro transfers and timed rail controls."""
from pathlib import Path
import json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from network_engine import NetworkEngine

def run():
    started=time.monotonic();engine=NetworkEngine()
    try:
        assert engine.network_name.startswith('multimodal') and engine.mobility
        engine.start_all();manager=engine.mobility;manager.start_buses()
        communities=[r['community_name'] for r in manager.routes.values()]
        scenarios=[(communities[0],communities[1],25),(communities[1],communities[0],20),
                   ('湖滨东路',communities[1],40),(communities[0],'莲坂',20)]
        ids=[]
        for origin,destination,count in scenarios:ids.extend(manager.add_group(origin,destination,count))
        assert [manager.groups[p]['count'] for p in ids]==[20,5,20,20,20,20]
        signal='L1_U03a';engine.hold_signal(signal,5)
        for _ in range(12):engine.step()
        assert engine.conn.trafficlight.getProgram(signal)=='0' and engine.signal_stats()['held']==0
        points=set(engine.conn.poi.getIDList())
        assert all(p+'_20people' in points for p in ids)
        assert all(engine.conn.person.getColor(p)[3]==0 for p in ids)
        for iteration in range(12000):
            engine.step()
            if iteration%2000==1999:print(f'Transfer check: {engine.time:.0f}s, {manager.stats()["people_arrived"]}/105 people arrived',flush=True)
            if all(not manager.groups[p]['active'] for p in ids):break
        assert manager.stats()['people_arrived']==105
        for pid in ids:
            group=manager.groups[pid]
            assert group['status']=='已到达' and group['rides'],group
            if group['origin'] in communities:assert group['rides'][0].startswith('B'),group
            if group['destination'] in communities:assert group['rides'][-1].startswith('B'),group
            assert any(v.startswith('L') for v in group['rides']),group
        assert engine.collisions==0 and engine.teleports==0
        points=set(engine.conn.poi.getIDList())
        assert all(p+'_20people' not in points for p in ids),'Arrived cohorts left stale dots'
        report={'result':'PASS','network':engine.network_name,'time':engine.time,'scenarios':scenarios,
                'people':105,'cohort_dots':len(ids),'tail_group_weight':5,
                'one_circle_per_active_cohort':'PASS','no_duplicate_person_glyph':'PASS',
                'actual_bus_and_metro_rides':'PASS','arrival_and_dot_removal':'PASS',
                'signal_timer_restore':'PASS','signal_count':engine.signal_stats()['total'],
                'stats':manager.stats(),'groups':{p:manager.groups[p] for p in ids},
                'collisions':engine.collisions,'teleports':engine.teleports,
                'elapsed_seconds':round(time.monotonic()-started,2)}
        (ROOT/'logs/integrated-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items() if k!='groups'},ensure_ascii=False),flush=True)
        return report
    finally:engine.close()

if __name__=='__main__':run()
