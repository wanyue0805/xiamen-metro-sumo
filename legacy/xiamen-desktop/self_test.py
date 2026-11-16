"""End-to-end regression of the delivered common SUMO network."""
from network_engine import NetworkEngine,ROOT,LINE_IDS,DATA
import json,time,math

def run():
 e=NetworkEngine();started=time.time()
 try:
  assert len([h for h in DATA['shared_stations'].values() if len(h['members'])>1])==10
  assert sum('depot_U' in s or 'depot_D' in s for ss in e.stations.values() for s in ss)==10
  e.start_all()
  people=[e.add_passenger(a,b) for a,b in [('镇海路','人才中心'),('蔡厝','前浯'),('董任','岩内')]]
  for i in range(16000):
   e.step()
   if i%4000==3999:print(f'Shared simulation: {e.time:.0f}s, {len(e.trains)} trains, {len(e.departures)} terminal departures',flush=True)
  assert e.collisions==0 and e.teleports==0
  for lid in LINE_IDS:
   assert sum(t['line']==lid and t['active'] for t in e.trains.values())>=4
   for d in 'UD':
    departures=[x['time'] for x in e.departures if x['line']==lid and x['direction']==d]
    assert len(departures)>=5,(lid,d,departures)
    assert all(b-a>=179.5 for a,b in zip(departures,departures[1:])),(lid,d,departures)
    assert max(departures)>7000,(lid,d,'terminal service stalled')
   visits=[v for v in e.visits if v[2]==lid]
   for s in e.stations[lid]:
    seen=any(v[3]==s['id'] for v in visits)
    assert seen==s['stop_enabled'],(lid,s['name'],'stop / skip mismatch')
   assert any(v[5]==f'L{lid}_D01' for v in visits),(lid,'south return missing')
   assert any(v[5]==f'L{lid}_U{len(e.stations[lid]):02}' for v in visits),(lid,'north return missing')
  for pid in people:
   p=e.passengers[pid]
   assert p['status']=='已到达',(pid,p)
   assert len(p['rides'])==len(p['plan']),(pid,p)
   assert [int(vid.split('-')[0][1:]) for vid in p['rides']]==[s['line'] for s in p['plan']]
  # Every station is reachable via the common transfer graph.
  for name in e.by_name:
   if name!='镇海路':assert e.plan('镇海路',name)
  e.set_headway(1,240);assert e.settings[1]['headway']==240
  e.set_speed(1,40)
  for vid,t in e.trains.items():
   if t['line']==1 and t['active']:assert abs(e.conn.vehicle.getMaxSpeed(vid)-40/3.6)<.001
  report={'version':'3.0','result':'PASS','simulation_seconds':e.time,'one_shared_connection':True,'fleet_count':len(e.trains),'interchanges':10,'departure_zones':10,'terminal_departures':len(e.departures),'headway_seconds':180,'collisions':e.collisions,'teleports':e.teleports,'passengers':{p:e.passengers[p] for p in people},'all_enabled_stops_and_skips':'PASS','all_station_trip_plans':'PASS','speed_and_headway_control':'PASS'}
  e.close()
  # A light fleet verifies both reversals on the same train, without a
  # large terminal queue hiding a full round trip within the test horizon.
  e=NetworkEngine()
  for s in e.settings.values():s['cap']=2
  e.start_all()
  def completed():
   for lid in LINE_IDS:
    visits=[v for v in e.visits if v[1]==f'L{lid}-U-001']
    if not any(v[5]==f'L{lid}_D01' for v in visits):return False
    if not any(v[5]==f'L{lid}_U{len(e.stations[lid]):02}' for v in visits):return False
    if sum(v[5]==f'L{lid}_RD01' for v in visits)<2:return False
   return True
  for i in range(24000):
   e.step()
   if i%100==99 and completed():break
  assert completed(),'same train did not complete both terminal reversals'
  assert e.collisions==0 and e.teleports==0
  report.update(all_lines_both_terminal_reversals='PASS',reversal_test_seconds=e.time,elapsed_seconds=round(time.time()-started,2))
  (ROOT/'logs/shared-network-self-test.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps(report,ensure_ascii=False),flush=True);return report
 finally:e.close()

if __name__=='__main__':run()
