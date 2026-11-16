from pathlib import Path
import sys,os,logging,traceback
BASE=Path(__file__).resolve().parents[1]
# Prevent two owned remote panels from fighting for the device connection.
import ctypes
_mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\SUMO_Web_Remote_1432466251')
if ctypes.windll.kernel32.GetLastError()==183:
    if '--headless' not in sys.argv:ctypes.windll.user32.MessageBoxW(None,'远程面板已在运行，请使用已有窗口。','SUMO 远程面板',0x40)
    raise SystemExit(0)
sys.path.insert(0,str(BASE/'agent/deps'));sys.path.insert(0,str(BASE/'simulation'));sys.path.insert(0,str(BASE/'agent'))
os.environ['LIBSUMO_AS_TRACI']='quiet'
os.chdir(BASE/'simulation')
(BASE/'simulation/logs').mkdir(exist_ok=True)
logging.basicConfig(filename=BASE/'simulation/logs/remote.log',level=logging.INFO,encoding='utf-8')
sys.stderr=open(BASE/'simulation/logs/remote-callbacks.log','a',encoding='utf-8',buffering=1)
try:
    import traci
    import libsumo
    if traci.simulation is not libsumo.simulation or not hasattr(traci,'TraCIStage'):
        raise RuntimeError('内置 SUMO 接口载入失败；远程入口禁止回退到 TCP TraCI')
    if '--headless' in sys.argv:
        import time
        from network_engine import NetworkEngine
        from remote_control import RemoteControl
        from ui_scheduler import BudgetStepper,acquire_timer_resolution
        state={'engine':NetworkEngine(),'rate':20}
        def reset():
            state['engine'].close();state['engine']=NetworkEngine()
        remote=RemoteControl(lambda:state['engine'],reset,lambda:state['rate'],lambda value:state.update(rate=value),get_actual_rate=lambda:stepper.actual_rate)
        stepper=BudgetStepper();release_timer=acquire_timer_resolution()
        try:
            while True:
                callback_start=time.perf_counter()
                remote.pump()
                try:stepper.advance(state['engine'],state['rate'])
                except Exception as exc:
                    state['engine'].paused=True;state['engine'].events.append('仿真异常，已暂停：'+str(exc));logging.exception('Simulation step')
                time.sleep(max(.001,.01-(time.perf_counter()-callback_start)))
        finally:
            remote.shutdown();state['engine'].close();release_timer()
    else:
        from shared_panel import run_app
        run_app()
except Exception:
    logging.exception('Remote startup')
    import ctypes
    ctypes.windll.user32.MessageBoxW(None,'远程面板启动失败。请查看新项目 simulation\\logs\\remote.log。\n'+traceback.format_exc().splitlines()[-1],'SUMO 远程面板',0x10)
    raise
