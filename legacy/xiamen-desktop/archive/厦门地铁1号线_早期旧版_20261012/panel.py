"""厦门地铁1号线可视化控制台。全线示意图与真实轨道列车近景。"""
import tkinter as tk
from tkinter import ttk,messagebox
from pathlib import Path
import os,math,bisect,logging,json
from app import Engine,ROOT,STATIONS

TITLE='厦门地铁 1 号线 · SUMO 仿真'

def run_app():
 if os.name=='nt':
  import ctypes
  try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
  except Exception:pass
 (ROOT/'logs').mkdir(exist_ok=True);logging.basicConfig(filename=ROOT/'logs/panel.log',level=logging.INFO,encoding='utf-8',format='%(asctime)s %(levelname)s %(message)s')
 root=tk.Tk();root.title(TITLE);root.configure(bg='#eef2f6')
 width=min(1220,root.winfo_screenwidth()-100);height=min(900,root.winfo_screenheight()-100)
 root.geometry(f'{width}x{height}+40+40');root.minsize(1000,700)
 engine=Engine();style=ttk.Style();style.theme_use('clam')
 style.configure('TLabel',font=('Microsoft YaHei UI',-13));style.configure('TButton',font=('Microsoft YaHei UI',-13),padding=6);style.configure('TCheckbutton',font=('Microsoft YaHei UI',-13));style.configure('Title.TLabel',font=('Microsoft YaHei UI',-25,'bold'))
 outer=ttk.Frame(root,padding=18);outer.pack(fill='both',expand=True)
 ttk.Label(outer,text='厦门地铁 1 号线',style='Title.TLabel').pack(anchor='w')
 ttk.Label(outer,text='镇海路 ⇄ 岩内   ·   24 站   ·   六节地铁列车   ·   双向轨道与终点折返').pack(anchor='w',pady=(4,12))
 body=ttk.Frame(outer);body.pack(fill='both',expand=True)
 mapframe=ttk.Frame(body);mapframe.pack(side='left',fill='both',expand=True,padx=(0,16))
 canvas=tk.Canvas(mapframe,bg='#101d2e',highlightthickness=0);canvas.pack(fill='both',expand=True)
 sidebar=ttk.Frame(body,width=335);sidebar.pack(side='right',fill='y');sidebar.pack_propagate(False)
 scroll=tk.Canvas(sidebar,bg='#d9d8d2',highlightthickness=0);bar=ttk.Scrollbar(sidebar,orient='vertical',command=scroll.yview);bar.pack(side='right',fill='y');scroll.pack(side='left',fill='both',expand=True);scroll.configure(yscrollcommand=bar.set)
 side=ttk.Frame(scroll);inner=scroll.create_window((0,0),window=side,anchor='nw')
 side.bind('<Configure>',lambda e:scroll.configure(scrollregion=scroll.bbox('all')));scroll.bind('<Configure>',lambda e:scroll.itemconfigure(inner,width=e.width))
 status=tk.StringVar(value='尚未启动');telemetry=tk.StringVar(value='速度 0.0 km/h  ·  仿真 0:00\n行驶 0.00 km  ·  到站 0 次');gui=tk.BooleanVar(value=False);direction=tk.StringVar(value='镇海路 → 岩内');rate=tk.IntVar(value=10);speed=tk.DoubleVar(value=80);dwell=tk.IntVar(value=20);speedtext=tk.StringVar(value='最高速度：80 km/h');detail=tk.StringVar(value='全线示意图；站距为仿真配置')
 ttk.Label(side,textvariable=status,wraplength=310,foreground='#a73260',font=('Microsoft YaHei UI',-15,'bold')).pack(fill='x',pady=(0,8))
 ttk.Checkbutton(side,text='同时打开 SUMO 原生窗口',variable=gui).pack(anchor='w')
 ttk.Label(side,text='始发方向').pack(anchor='w',pady=(8,2))
 ttk.Combobox(side,textvariable=direction,values=['镇海路 → 岩内','岩内 → 镇海路'],state='readonly',font=('Microsoft YaHei UI',-13)).pack(fill='x')
 def safe(fn):
  try:fn();redraw()
  except Exception as exc:logging.exception('Control failed');messagebox.showerror('操作提示',str(exc),parent=root)
 def start():engine.start(gui.get(),1 if direction.get().startswith('镇海路') else -1)
 ttk.Button(side,text='启动 / 重置',command=lambda:safe(start)).pack(fill='x',pady=(8,5))
 row=ttk.Frame(side);row.pack(fill='x')
 def auto():engine.set_auto(not engine.auto)
 def pause():
  if not engine.conn:raise RuntimeError('请先启动仿真。')
  engine.paused=not engine.paused
 ttk.Button(row,text='自动全线往返',command=lambda:safe(auto)).pack(side='left',fill='x',expand=True,padx=(0,4))
 ttk.Button(row,text='暂停 / 继续',command=lambda:safe(pause)).pack(side='left',fill='x',expand=True)
 row=ttk.Frame(side);row.pack(fill='x',pady=(5,0))
 def next_station():engine.auto=False;engine.next_station()
 def single_step():
  if not engine.conn:raise RuntimeError('请先启动仿真。')
  engine.paused=True;engine.step()
 ttk.Button(row,text='发往下一站',command=lambda:safe(next_station)).pack(side='left',fill='x',expand=True,padx=(0,4))
 ttk.Button(row,text='单步 0.2 秒',command=lambda:safe(single_step)).pack(side='left',fill='x',expand=True)
 ttk.Label(side,text='选择目的站（双击列表或点击地图）').pack(anchor='w',pady=(12,4))
 listing=ttk.Frame(side);listing.pack(fill='x')
 stations=tk.Listbox(listing,height=9,font=('Microsoft YaHei UI',-13),bg='#f7f9fc',selectbackground='#bd4773',activestyle='none',exportselection=False)
 stations.pack(side='left',fill='both',expand=True);stationbar=ttk.Scrollbar(listing,orient='vertical',command=stations.yview);stationbar.pack(side='right',fill='y');stations.configure(yscrollcommand=stationbar.set)
 for i,s in STATIONS.items():stations.insert('end',f'{i:02}   {s["name"]}')
 stations.selection_set(0)
 def navigate(station):engine.auto=False;engine.go(station)
 def selected():
  chosen=stations.curselection()
  if chosen:navigate(chosen[0]+1)
 stations.bind('<Double-Button-1>',lambda event:safe(selected));ttk.Button(side,text='驶向所选站',command=lambda:safe(selected)).pack(fill='x',pady=5)
 ttk.Label(side,textvariable=speedtext).pack(anchor='w',pady=(8,0))
 def speed_changed(value):
  engine.speed=float(value)/3.6;speedtext.set(f'最高速度：{float(value):.0f} km/h')
  if engine.conn:
   try:engine.conn.vehicle.setMaxSpeed('metro1',engine.speed)
   except Exception:logging.exception('Speed update failed')
 ttk.Scale(side,from_=10,to=80,variable=speed,command=speed_changed).pack(fill='x')
 row=ttk.Frame(side);row.pack(fill='x',pady=6)
 ttk.Label(row,text='仿真倍率').pack(side='left');ttk.Combobox(row,textvariable=rate,values=[1,5,10,20,50,100],state='readonly',width=6).pack(side='left',padx=6)
 ttk.Label(row,text='停站秒数').pack(side='left',padx=(5,0));ttk.Spinbox(row,from_=1,to=60,textvariable=dwell,width=4).pack(side='left',padx=5)
 ttk.Label(side,textvariable=telemetry,justify='left').pack(anchor='w',pady=(8,7))
 ttk.Label(side,text='列车近景 · 六节车厢沿真实轨道转向',font=('Microsoft YaHei UI',-12,'bold')).pack(anchor='w')
 closeup=tk.Canvas(side,height=155,bg='#132436',highlightthickness=0);closeup.pack(fill='x',pady=(4,6))
 ttk.Label(side,text='线路走向为示意；非实测配线或实际运行图',wraplength=310,foreground='#62758b',font=('Microsoft YaHei UI',-12)).pack(anchor='w')
 ys=[s['y'] for s in STATIONS.values()];xs=[s['x'] for s in STATIONS.values()];xmin,xmax=min(xs),max(xs)
 def project(x,y):
  w,h=canvas.winfo_width(),canvas.winfo_height();j=max(0,min(22,bisect.bisect_right(ys,y)-1));t=j+(y-ys[j])/(ys[j+1]-ys[j]);sx=w*.27+(x-xmin)/(xmax-xmin)*w*.40;sy=h-42-t*(h-88)/23
  return sx,sy
 def near_project(x,y):
  center=engine.point_behind(60) if engine.conn else (STATIONS[1]['x'],STATIONS[1]['y'])
  scale=.85
  return closeup.winfo_width()/2+(x-center[0])*scale,closeup.winfo_height()/2-(y-center[1])*scale
 def train_drawing():
  closeup.delete('all')
  if not engine.conn:
   closeup.create_text(closeup.winfo_width()/2,78,text='启动后显示列车近景',fill='#8ea5bc',font=('Microsoft YaHei UI',-13));return
  for edge in engine.net.getEdges(withInternal=True):
   shape=edge.getLane(0).getShape();pts=[near_project(x,y) for x,y in shape]
   if not any(-180<x<closeup.winfo_width()+180 and -180<y<closeup.winfo_height()+180 for x,y in pts):continue
   left=[];right=[]
   for k,(x,y) in enumerate(pts):
    a=pts[max(0,k-1)];b=pts[min(len(pts)-1,k+1)];dx=b[0]-a[0];dy=b[1]-a[1];n=max(.001,math.hypot(dx,dy));nx=-dy/n;ny=dx/n
    left.extend((x+nx*1.5,y+ny*1.5));right.extend((x-nx*1.5,y-ny*1.5))
   if len(left)>2:
    closeup.create_line(*[v for xy in pts for v in xy],fill='#40556a',width=7)
    for line in (left,right):closeup.create_line(*line,fill='#b5c8d4',width=1)
  for k in range(6):
   offset=10+20*k;center=near_project(*engine.point_behind(offset));a=near_project(*engine.point_behind(offset-7));b=near_project(*engine.point_behind(offset+7));dx=a[0]-b[0];dy=a[1]-b[1];n=max(.001,math.hypot(dx,dy));ux,uy=dx/n,dy/n;nx,ny=-uy,ux;x,y=center;half=7.8;wid=2.3
   corners=[(x+u*ux+v*nx,y+u*uy+v*ny) for u,v in [(half,wid),(half,-wid),(-half,-wid),(-half,wid)]]
   closeup.create_polygon(*[v for xy in corners for v in xy],fill='#e787ae' if k==0 else '#dfe8ee',outline='#fff',width=1)
   for off in [-4,0,4]:closeup.create_line(x+off*ux-1.3*nx,y+off*uy-1.3*ny,x+off*ux+1.3*nx,y+off*uy+1.3*ny,fill='#24516c',width=2)
 def redraw():
  canvas.delete('all');w,h=canvas.winfo_width(),canvas.winfo_height()
  # Sea crossing is indicated between Gaoqi and Jimei Xuecun in this schematic.
  sea0=project(STATIONS[13]['x'],STATIONS[13]['y'])[1];sea1=project(STATIONS[14]['x'],STATIONS[14]['y'])[1]
  canvas.create_rectangle(0,sea1-5,w,sea0+5,fill='#16364e',outline='')
  canvas.create_text(68,(sea0+sea1)/2,text='跨海区段',fill='#89bed4',font=('Microsoft YaHei UI',-12))
  for edge in engine.net.getEdges():
   if edge.getID().startswith(('RU','RD')):continue
   pts=[v for xy in edge.getLane(0).getShape() for v in project(*xy)]
   canvas.create_line(*pts,fill='#e49ab6' if edge.getID()[0] in ('U','D') else '#aa668a',width=3,capstyle='round')
  if engine.conn and engine.route:
   pts=engine.track_shape(engine.route)
   if len(pts)>1:canvas.create_line(*[v for xy in pts for v in project(*xy)],fill='#ffd16a',width=2)
  for i,s in STATIONS.items():
   x,y=project(s['x'],s['y']);tag=f's{i}';target=engine.conn and engine.target==i;fill='#ffd16a' if target else '#f5e7ef'
   canvas.create_oval(x-5,y-5,x+5,y+5,fill=fill,outline='#a54c78',width=2,tags=tag)
   left=i%2==0;lx=x-15 if left else x+15
   canvas.create_text(lx,y,text=f'{i:02} {s["name"]}',anchor='e' if left else 'w',fill='#ffd16a' if target else '#e4edf5',font=('Microsoft YaHei UI',-12),tags=tag)
   canvas.tag_bind(tag,'<Button-1>',lambda event,station=i:safe(lambda:navigate(station)))
  canvas.create_text(w-20,18,text='N ↑',anchor='e',fill='#8ca8bf',font=('Microsoft YaHei UI',-13,'bold'))
  canvas.create_text(18,18,text='1号线全线示意图',anchor='w',fill='#f0bfd4',font=('Microsoft YaHei UI',-14,'bold'))
  canvas.create_text(w/2,h-15,text='粉色：双向轨道   ·   黄色：导航区间   ·   青色：列车位置',fill='#839db6',font=('Microsoft YaHei UI',-12))
  snap=engine.snapshot()
  if snap:
   (px,py),v,t=snap;x,y=project(px,py);canvas.create_oval(x-7,y-7,x+7,y+7,fill='#16c7d1',outline='white',width=2)
   telemetry.set(f'速度 {v*3.6:.1f} km/h  ·  仿真 {int(t)//60}:{int(t)%60:02}\n行驶 {engine.distance/1000:.2f} km  ·  到站 {len(engine.visits)} 次')
  train_drawing();label=engine.status
  if engine.conn:label+=(' · 暂停' if engine.paused else ' · 运行')+(' · 自动' if engine.auto else '')
  status.set(label)
 def tick():
  try:
   engine.dwell=max(1,int(dwell.get()))
   if engine.conn and not engine.paused:
    for _ in range(max(1,rate.get())):engine.step()
   redraw()
  except Exception as exc:
   logging.exception('Simulation failed');engine.close();engine.status='请重新启动仿真';redraw();messagebox.showerror('仿真提示',str(exc),parent=root)
  root.after(200,tick)
 def export():
  if not engine.events:raise RuntimeError('暂无运行记录。')
  path=ROOT/'logs/arrival-log.json';path.write_text(json.dumps(engine.events,ensure_ascii=False,indent=2),encoding='utf-8');messagebox.showinfo('已保存',f'运行记录已保存：\n{path}',parent=root)
 ttk.Button(side,text='保存到站 / 折返记录',command=lambda:safe(export)).pack(fill='x',pady=5)
 def close():engine.close();root.destroy()
 canvas.bind('<Configure>',lambda e:redraw());root.protocol('WM_DELETE_WINDOW',close);root.after(200,tick);root.mainloop()
