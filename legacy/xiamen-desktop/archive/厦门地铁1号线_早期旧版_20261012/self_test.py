from app import Engine,ROOT,STATIONS
import json,xml.etree.ElementTree as ET,tkinter as tk

def arrive(e,target,limit=30000):
 for _ in range(limit):
  e.step()
  if e.arrived and e.current==target:return
 raise AssertionError(f'Arrival timeout: {target}')

def main():
 results={};e=Engine()
 try:
  window=tk.Tk();window.withdraw();window.update();window.destroy();results['tkinter']='PASS'
  assert len(STATIONS)==24 and STATIONS[1]['name']=='镇海路' and STATIONS[24]['name']=='岩内'
  results['station_names_and_endpoints']='PASS'
  xml=ET.parse(ROOT/'network/line1.net.xml').getroot()
  assert all(lane.get('allow')=='rail_urban' for edge in xml.findall('edge') for lane in edge.findall('lane'))
  pairs={x.get('id'):x.get('bidi') for x in xml.findall('edge')}
  assert pairs['U24']=='RU24' and pairs['D01']=='RD01'
  assert sum(j.get('type')=='rail_signal' for j in xml.findall('junction'))>=90
  results['rail_signal_blocks']='PASS'
  results['rail_only_and_terminal_bidirectional_tracks']='PASS'
  settings=ET.parse(ROOT/'network/metro.view.xml').getroot();assert settings.find('scheme/vehicles').get('vehicleQuality')=='2'
  results['native_segmented_carriages']='PASS'
  e.start();assert e.arrived and e.current==1
  assert e.conn.vehicle.getLength('metro1')==120 and e.conn.vehicle.getVehicleClass('metro1')=='rail_urban'
  e.dwell=1;e.terminal_dwell=2;e.set_auto(True)
  for i in range(60000):
   e.step()
   if i%200==0:assert e.conn.simulation.getStartingTeleportNumber()==0
   if len(e.visits)>=48:break
  assert e.visits[:24]==list(range(1,25)),e.visits
  assert e.visits[24:47]==list(range(23,0,-1)),e.visits
  assert e.visits[47]==2,e.visits
  assert len([x for x in e.events if x['event']=='terminal_reversal'])>=2,e.events
  results['northbound_all_24_stations']='PASS';results['southbound_all_24_stations']='PASS';results['both_terminal_reversals_same_vehicle']='PASS'
  e.auto=False;e.go(7)
  for _ in range(60):e.step()
  e.go(4);arrive(e,4);results['redirect_while_moving']='PASS'
  e.speed=8;e.go(8)
  for _ in range(200):e.step();assert e.conn.vehicle.getSpeed('metro1')<=8.01
  arrive(e,8);results['speed_limit_and_selected_destination']='PASS'
  e.close();e.start(direction=-1);assert e.arrived and e.current==24
  e.next_station();arrive(e,23);results['southbound_start_and_next_station']='PASS'
  results['automatic_visit_sequence']=list(range(1,25))+list(range(23,0,-1))+[2]
  results['model_note']='Schematic geometry and model stop timings; actual station names and sequence.'
 finally:e.close()
 (ROOT/'logs/self-test.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(results,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
