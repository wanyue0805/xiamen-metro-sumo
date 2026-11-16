"""Measure the actual integrated simulation under a reproducible load."""
from pathlib import Path
import argparse,json,os,statistics,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))

def run(steps=2400,base_network=False):
    if base_network:os.environ['XIAMEN_USE_DEPOTS']='0'
    from network_engine import NetworkEngine
    engine=NetworkEngine();timings=[]
    try:
        engine.start_all();engine.mobility.start_buses()
        communities=[route['community_name'] for route in engine.mobility.routes.values()]
        engine.mobility.add_group(communities[0],communities[1],200)
        engine.mobility.set_demand_enabled(True)
        for _ in range(steps):
            started=time.perf_counter();engine.step();timings.append(time.perf_counter()-started)
        report={'result':'PASS' if engine.collisions==engine.teleports==0 else 'FAIL',
                'network':engine.network_name,'steps':len(timings),'simulation_seconds':engine.time,
                'wall_seconds':sum(timings),'step_ms_median':statistics.median(timings)*1000,
                'step_ms_p95':sorted(timings)[min(len(timings)-1,int(len(timings)*.95))]*1000,
                'trains':len(engine.trains),'mobility':engine.mobility.stats(),
                'collisions':engine.collisions,'teleports':engine.teleports,
                'timing_scope':'simulation step, shared readings, passengers, signals and native dots; excludes startup and GUI rendering'}
        (ROOT/'logs').mkdir(exist_ok=True)
        target=ROOT/'logs'/('runtime-benchmark-base.json' if base_network else 'runtime-benchmark.json')
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
        return report
    finally:engine.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--steps',type=int,default=2400);parser.add_argument('--base-network',action='store_true')
    args=parser.parse_args()
    if not 100<=args.steps<=100000:parser.error('--steps must be between 100 and 100000')
    result=run(args.steps,args.base_network)
    sys.exit(0 if result['result']=='PASS' else 1)
