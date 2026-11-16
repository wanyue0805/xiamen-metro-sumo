"""Visible bootstrap and persistent diagnostics for double-click startup."""
from pathlib import Path
import os,sys,traceback,logging
ROOT=Path(__file__).resolve().parent
os.chdir(ROOT);(ROOT/'logs').mkdir(exist_ok=True)
log=open(ROOT/'logs/startup.log','a',encoding='utf-8',buffering=1)
sys.stdout=log;sys.stderr=log
logging.basicConfig(filename=ROOT/'logs/panel.log',level=logging.INFO,encoding='utf-8',format='%(asctime)s %(levelname)s %(message)s')
print('\nStarting metro:',__import__('datetime').datetime.now(),sys.executable)
try:
 import tkinter as tk
 splash=tk.Tk();splash.title('厦门综合交通 · 正在启动');splash.geometry('420x135+120+120');splash.configure(bg='#142538')
 tk.Label(splash,text='厦门综合交通 · 运营调度中心',bg='#142538',fg='white',font=('Microsoft YaHei UI',17,'bold')).pack(pady=(25,8))
 tk.Label(splash,text='正在载入轨道、公交接驳、客流和信号…',bg='#142538',fg='#aac3d8',font=('Microsoft YaHei UI',11)).pack();splash.update()
 from shared_panel import run_app
 splash.destroy();run_app()
except Exception:
 details=traceback.format_exc();print(details);log.flush()
 message='地铁仿真启动失败。\n请保留完整项目文件夹。\n\n错误：'+details.splitlines()[-1]+'\n\n详细日志：'+str(ROOT/'logs/startup.log')
 if os.name=='nt':
  import ctypes
  ctypes.windll.user32.MessageBoxW(None,message,'厦门地铁 · 启动提示',0x10)
 else:print(message)
 raise
finally:log.close()
