"""Five-line desktop control panel with station architecture previews."""
import tkinter as tk
from tkinter import ttk,messagebox
from pathlib import Path
import os,math,json,bisect,logging
from app import Engine,ROOT,LINES,LINE_IDS,CATALOG
TITLE='厦门地铁 · 五线仿真与站台控制台'


def run_app():
 if os.name=='nt':
  import ctypes
  try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
  except Exception:pass
 (ROOT/'logs').mkdir(exist_ok=True);logging.basicConfig(filename=ROOT/'logs/panel.log',level=logging.INFO,encoding='utf-8',format='%(asctime)s %(levelname)s %(message)s')
 root=tk.Tk();root.title(TITLE);root.configure(bg='#eaf0f6')
 w=min(1340,root.winfo_screenwidth()-80);h=min(940,root.winfo_screenheight()-90);root.geometry(f'{w}x{h}+35+35');root.minsize(1080,740)
 engines={lid:Engine(lid) for lid in LINE_IDS};state={'line':1,'station':1,'overview':False};tabs={}
 style=ttk.Style();style.theme_use('clam');style.configure('TLabel',font=('Microsoft YaHei UI',-13));style.configure('TButton',font=('Microsoft YaHei UI',-13),padding=6);style.configure('TCheckbutton',font=('Microsoft YaHei UI',-12))
 outer=ttk.Frame(root,padding=16);outer.pack(fill='both',expand=True)
 titlebar=ttk.Frame(outer);titlebar.pack(fill='x')
 ttk.Label(titlebar,text='厦门地铁 · 五线仿真',font=('Microsoft YaHei UI',-24,'bold')).pack(side='left')
 ttk.Label(titlebar,text='1 / 2 / 3 / 4 / 6 号线  ·  双向运行  ·  精细站台',foreground='#62778e').pack(side='left',padx=20)
 top=ttk.Frame(outer);top.pack(fill='x',pady=(10,12))
 for lid in LINE_IDS:
  button=tk.Button(top,text=f'{lid}号线',bg=LINES[lid]['color'],fg='white',activebackground=LINES[lid]['color'],font=('Microsoft YaHei UI',-15,'bold'),relief='flat',bd=0,padx=20,pady=9,command=lambda line=lid:switch_line(line));button.pack(side='left',fill='x',expand=True,padx=(0,7));tabs[lid]=button
 body=ttk.Frame(outer);body.pack(fill='both',expand=True)
 left=ttk.Frame(body);left.pack(side='left',fill='both',expand=True,padx=(0,15))
 mapcanvas=tk.Canvas(left,bg='#101d2d',highlightthickness=0);mapcanvas.pack(fill='both',expand=True)
 stationcanvas=tk.Canvas(left,height=235,bg='#18283a',highlightthickness=0);stationcanvas.pack(fill='x',pady=(10,0))
 sidebar=ttk.Frame(body,width=326);sidebar.pack(side='right',fill='y');sidebar.pack_propagate(False)
 scroller=tk.Canvas(sidebar,highlightthickness=0,bg='#dce3eb');bar=ttk.Scrollbar(sidebar,orient='vertical',command=scroller.yview);bar.pack(side='right',fill='y');scroller.pack(side='left',fill='both',expand=True);scroller.configure(yscrollcommand=bar.set)
 side=ttk.Frame(scroller);inner=scroller.create_window((0,0),window=side,anchor='nw');side.bind('<Configure>',lambda e:scroller.configure(scrollregion=scroller.bbox('all')));scroller.bind('<Configure>',lambda e:scroller.itemconfigure(inner,width=e.width))
 routeinfo=tk.StringVar();status=tk.StringVar(value='尚未启动');telemetry=tk.StringVar(value='速度 0 km/h  ·  到站 0 次');gui=tk.BooleanVar(value=False);direction=tk.StringVar();rate=tk.IntVar(value=20);speed=tk.DoubleVar(value=80);dwell=tk.IntVar(value=20);follow=tk.BooleanVar(value=True);speedtext=tk.StringVar(value='最高速度：80 km/h')
 ttk.Label(side,textvariable=routeinfo,wraplength=300,font=('Microsoft YaHei UI',-14,'bold')).pack(fill='x',pady=(0,5))
 ttk.Label(side,textvariable=status,wraplength=300,foreground='#217d99').pack(fill='x',pady=(0,7))
 ttk.Checkbutton(side,text='启动选中线路的原生 SUMO 窗口',variable=gui).pack(anchor='w')
 directionbox=ttk.Combobox(side,textvariable=direction,state='readonly',font=('Microsoft YaHei UI',-12));directionbox.pack(fill='x',pady=6)
 def selected_engine():return engines[state['line']]
 def safe(fn):
  try:fn();redraw()
  except Exception as exc:logging.exception('Control failed');messagebox.showerror('操作提示',str(exc),parent=root)
 def start_selected():
  e=selected_engine();e.start(gui.get(),1 if directionbox.current()!=1 else -1);state['station']=e.current
 ttk.Button(side,text='启动 / 重置本线',command=lambda:safe(start_selected)).pack(fill='x',pady=3)
 def start_all():
  for line in LINE_IDS:
   e=engines[line]
   if not e.conn:e.start(gui=False)
   e.set_auto(True)
  state['overview']=True
 ttk.Button(side,text='启动五线并自动往返',command=lambda:safe(start_all)).pack(fill='x',pady=3)
 row=ttk.Frame(side);row.pack(fill='x',pady=3)
 def auto():e=selected_engine();e.set_auto(not e.auto)
 def pause():
  e=selected_engine()
  if not e.conn:raise RuntimeError('请先启动本线。')
  e.paused=not e.paused
 ttk.Button(row,text='本线自动往返',command=lambda:safe(auto)).pack(side='left',fill='x',expand=True,padx=(0,4));ttk.Button(row,text='暂停 / 继续',command=lambda:safe(pause)).pack(side='left',fill='x',expand=True)
 row=ttk.Frame(side);row.pack(fill='x',pady=3)
 def next_stop():e=selected_engine();e.auto=False;e.next_station()
 def one_step():
  e=selected_engine()
  if not e.conn:raise RuntimeError('请先启动本线。')
  e.paused=True;e.step()
 ttk.Button(row,text='发往下一站',command=lambda:safe(next_stop)).pack(side='left',fill='x',expand=True,padx=(0,4));ttk.Button(row,text='单步 0.2 秒',command=lambda:safe(one_step)).pack(side='left',fill='x',expand=True)
 def overview():state['overview']=not state['overview']
 ttk.Button(side,text='五线总览 / 本线地图',command=lambda:safe(overview)).pack(fill='x',pady=3)
 ttk.Label(side,text='站点：单击看站台，双击发车').pack(anchor='w',pady=(9,4))
 listframe=ttk.Frame(side);listframe.pack(fill='x')
 stations=tk.Listbox(listframe,height=8,font=('Microsoft YaHei UI',-12),bg='#f8fafc',selectbackground='#327f9d',exportselection=False,activestyle='none');stations.pack(side='left',fill='both',expand=True);listbar=ttk.Scrollbar(listframe,orient='vertical',command=stations.yview);listbar.pack(side='right',fill='y');stations.configure(yscrollcommand=listbar.set)
 def choose_station(i):
  state['station']=i;follow.set(False);stations.selection_clear(0,'end');stations.selection_set(i-1);stations.see(i-1)
 def list_select(event=None):
  chosen=stations.curselection()
  if chosen:state['station']=chosen[0]+1;follow.set(False);redraw()
 stations.bind('<<ListboxSelect>>',list_select)
 def navigate():
  e=selected_engine();e.auto=False;e.go(state['station']);follow.set(True);state['overview']=False
 stations.bind('<Double-Button-1>',lambda event:safe(navigate));ttk.Button(side,text='驶向所选站',command=lambda:safe(navigate)).pack(fill='x',pady=5)
 ttk.Checkbutton(side,text='近景跟随列车停靠站',variable=follow).pack(anchor='w',pady=3)
 ttk.Label(side,textvariable=speedtext).pack(anchor='w',pady=(7,0))
 def speed_change(value):
  e=selected_engine();e.speed=float(value)/3.6;speedtext.set(f'最高速度：{float(value):.0f} km/h')
  if e.conn:
   try:e.conn.vehicle.setMaxSpeed('metro1',e.speed)
   except Exception:logging.exception('Speed change failed')
 speedscale=ttk.Scale(side,from_=10,to=80,variable=speed,command=speed_change);speedscale.pack(fill='x')
 row=ttk.Frame(side);row.pack(fill='x',pady=7);ttk.Label(row,text='全线倍率').pack(side='left');ttk.Combobox(row,textvariable=rate,values=[1,5,10,20,50,100],state='readonly',width=5).pack(side='left',padx=6);ttk.Label(row,text='停站秒数').pack(side='left',padx=(5,0));ttk.Spinbox(row,from_=1,to=60,textvariable=dwell,width=4).pack(side='left',padx=4)
 ttk.Label(side,textvariable=telemetry,justify='left',wraplength=300).pack(fill='x',pady=8)
 ttk.Label(side,text='4 / 6 号线按 2026-09 试乘方案；灰色站牌为跳停站。线路与建筑为示意模型。',wraplength=300,foreground='#64788d',font=('Microsoft YaHei UI',-12)).pack(fill='x',pady=6)
 def export():
  records=[record for e in engines.values() for record in e.events]
  if not records:raise RuntimeError('暂无运行记录。')
  path=ROOT/'logs/five-line-arrivals.json';path.write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8');messagebox.showinfo('记录已保存',str(path),parent=root)
 ttk.Button(side,text='保存五线运行记录',command=lambda:safe(export)).pack(fill='x',pady=5)
 def rounded(canvas,x0,y0,x1,y1,r=6,**kw):
  pts=[x0+r,y0,x1-r,y0,x1,y0,x1,y0+r,x1,y1-r,x1,y1,x1-r,y1,x0+r,y1,x0,y1,x0,y1-r,x0,y0+r,x0,y0]
  return canvas.create_polygon(pts,smooth=True,splinesteps=8,**kw)
 def switch_line(lid):
  state['line']=lid;state['station']=engines[lid].current;state['overview']=False;follow.set(True)
  e=engines[lid];c=LINES[lid];routeinfo.set(f'{lid}号线  ·  {c["status"]}\n{c["first"]} ⇄ {c["last"]}')
  directionbox.configure(values=[f'{c["first"]} → {c["last"]}',f'{c["last"]} → {c["first"]}']);directionbox.current(0 if e.direction==1 else 1)
  stations.delete(0,'end')
  for i,s in e.stations.items():
   transfer=' ⇄' if s['interchange_lines'] else '';skip='〔跳停〕' if not s['stop_enabled'] else '';stations.insert('end',f'{i:02}  {s["name"]}{transfer}{skip}')
   if skip:stations.itemconfigure(i-1,fg='#8b95a2')
  stations.selection_set(state['station']-1);stations.see(state['station']-1);speedscale.configure(to=c['speed_kmh']);speed.set(e.speed*3.6);speedtext.set(f'最高速度：{e.speed*3.6:.0f} km/h');dwell.set(int(e.dwell));redraw()
 def project(e,x,y):
  ss=list(e.stations.values());ys=[s['y'] for s in ss];xs=[s['x'] for s in ss];j=max(0,min(e.last-2,bisect.bisect_right(ys,y)-1));t=j+(y-ys[j])/(ys[j+1]-ys[j]);w,h=mapcanvas.winfo_width(),mapcanvas.winfo_height();sx=w*.40+(x-min(xs))/max(1,max(xs)-min(xs))*w*.22;sy=h-30-t*(h-75)/(e.last-1);return sx,sy
 def draw_map():
  cv=mapcanvas;cv.delete('all');w,h=cv.winfo_width(),cv.winfo_height();e=selected_engine();c=LINES[state['line']]
  cv.create_text(18,18,text='五线运行总览' if state['overview'] else f'{state["line"]}号线 · 站点地图',anchor='w',fill='#dce8f4',font=('Microsoft YaHei UI',-15,'bold'))
  if state['overview']:
   col=(w-30)/5
   for k,lid in enumerate(LINE_IDS):
    item=engines[lid];cfg=LINES[lid];x=15+k*col;y0=58;y1=h-30
    rounded(cv,x+4,36,x+col-4,h-15,8,fill='#17283b',outline='#263c53')
    cv.create_text(x+col/2,52,text=f'{lid}号线 · {len(item.enabled)}停靠站',fill=cfg['color'],font=('Microsoft YaHei UI',-12,'bold'))
    cv.create_line(x+18,y0+30,x+18,y1-12,fill=cfg['color'],width=3)
    for i,s in item.stations.items():
     y=y0+30+(i-1)*(y1-y0-42)/(item.last-1);tag=f'overview{lid}_{i}'
     cv.create_oval(x+14,y-3,x+22,y+3,fill=cfg['color'] if s['stop_enabled'] else '#687789',outline='',tags=tag)
     cv.create_text(x+28,y,text=s['name'],anchor='w',fill='#ccdbea' if s['stop_enabled'] else '#647488',font=('Microsoft YaHei UI',-10),tags=tag)
     cv.tag_bind(tag,'<Button-1>',lambda event,line=lid,station=i:(switch_line(line),choose_station(station),redraw()))
    if item.conn:
     position=item.snapshot()[0];ss=list(item.stations.values());ys=[s['y'] for s in ss];j=max(0,min(item.last-2,bisect.bisect_right(ys,position[1])-1));t=j+(position[1]-ys[j])/(ys[j+1]-ys[j]);y=y0+30+t*(y1-y0-42)/(item.last-1);cv.create_oval(x+12,y-5,x+24,y+5,fill='#22d4d6',outline='white')
   return
  for edge in e.net.getEdges():
   if edge.getID().startswith(('RU','RD')):continue
   cv.create_line(*[v for xy in edge.getLane(0).getShape() for v in project(e,*xy)],fill=c['color'],width=3)
  if e.conn and e.route:
   pts=e.track_shape(e.route)
   if len(pts)>1:cv.create_line(*[v for xy in pts for v in project(e,*xy)],fill='#ffd378',width=2)
  for i,s in e.stations.items():
   x,y=project(e,s['x'],s['y']);tag=f's{i}';chosen=state['station']==i;left=i%2==0;cw=138;x0=x-cw-12 if left else x+12;x1=x0+cw
   color=c['color'] if s['stop_enabled'] else '#687586';rounded(cv,x0,y-10,x1,y+10,5,fill='#253d52' if chosen else '#1a2d42',outline='#ffd378' if chosen else '#355068',width=1,tags=tag)
   rounded(cv,x0+4,y-7,x0+23,y+7,3,fill=color,outline='',tags=tag);cv.create_text(x0+13,y,text=f'{i:02}',fill='white',font=('Microsoft YaHei UI',-10,'bold'),tags=tag)
   cv.create_text(x0+29,y,text=s['name'],anchor='w',fill='#f0f5fb' if s['stop_enabled'] else '#8b99ab',font=('Microsoft YaHei UI',-11),tags=tag)
   if s['interchange_lines']:cv.create_text(x1-8,y,text='⇄',anchor='e',fill='#ffdb8a',font=('Microsoft YaHei UI',-12,'bold'),tags=tag)
   cv.create_oval(x-5,y-5,x+5,y+5,fill='#ffd378' if chosen else '#d5e2ef',outline=color,width=2,tags=tag)
   cv.tag_bind(tag,'<Button-1>',lambda event,station=i:(choose_station(station),redraw()));cv.tag_bind(tag,'<Double-Button-1>',lambda event,station=i:safe(lambda:(choose_station(station),navigate())))
  if e.conn:
   pos=e.snapshot()[0];x,y=project(e,*pos);cv.create_oval(x-7,y-7,x+7,y+7,fill='#23d6d6',outline='white',width=2)
  cv.create_text(w-16,18,text='站牌 ⇄ 换乘站',anchor='e',fill='#8ea9c2',font=('Microsoft YaHei UI',-11))
 def draw_station():
  cv=stationcanvas;cv.delete('all');w,h=cv.winfo_width(),cv.winfo_height();e=selected_engine();s=e.stations[state['station']];c=LINES[e.line_id];color=c['color'];scale=min((w-90)/300,1.8);center=(s['x'],s['y']);tx,ty=s['tangent'];nx,ny=-ty,tx
  def iso(u,v,z=0):return w/2+u*scale+v*.42*scale,h*.60+v*.46*scale-z*scale
  def polygon(points,fill,outline=''):
   cv.create_polygon(*[v for pt in points for v in iso(*pt)],fill=fill,outline=outline,width=1)
  def rect(a,b,low,high,z,fill,outline=''):polygon([(a,low,z),(b,low,z),(b,high,z),(a,high,z)],fill,outline)
  cv.create_text(17,18,text=f'站台近景 · {s["name"]}',anchor='w',fill='#edf5fb',font=('Microsoft YaHei UI',-15,'bold'))
  x=w-18
  for lid in reversed(s['interchange_lines'] or [e.line_id]):
   rounded(cv,x-29,8,x,29,5,fill=LINES[lid]['color'],outline='');cv.create_text(x-14,18,text=str(lid),fill='white',font=('Microsoft YaHei UI',-12,'bold'));x-=36
  rect(-138,138,-47,47,-1,'#263a4b')
  for v in [-8,8]:
   rect(-136,136,v-3.4,v+3.4,0,'#334858')
   for u in range(-134,136,5):
    a,b=iso(u,v-3.8),iso(u,v+3.8);cv.create_line(*a,*b,fill='#65788c',width=2)
   for off in [-.75,.75]:a,b=iso(-138,v+off),iso(138,v+off);cv.create_line(*a,*b,fill='#ced9e4',width=2)
  for side in [-1,1]:
   lo,hi=sorted([side*15,side*37]);rect(-110,110,lo,hi,0,'#718294','#9dadbb')
   polygon([(-110,lo,0),(110,lo,0),(110,lo,-2),(-110,lo,-2)],'#4a5c70');polygon([(110,lo,0),(110,hi,0),(110,hi,-2),(110,lo,-2)],'#53687c')
   for u in range(-105,110,12):
    a,b=iso(u,lo),iso(u,hi);cv.create_line(*a,*b,fill='#8194a4',width=1)
   a,b=iso(-108,side*15.8,.2),iso(108,side*15.8,.2);cv.create_line(*a,*b,fill='#ffd267',width=3)
   for u in range(-86,88,43):
    a,b=iso(u,side*28,0),iso(u,side*28,7);cv.create_line(*a,*b,fill='#d3e0eb',width=2)
   # Modular translucent canopy keeps platform fixtures visible.
   for u in range(-95,90,38):
    low,high=sorted([side*25,side*35]);rect(u,u+34,low,high,7,color,'#bdd1df')
    a,b=iso(u,low,7),iso(u,high,7);cv.create_line(*a,*b,fill='#e7f1f8',width=1)
   for u in range(-76,80,38):
    a,b=iso(u-4,side*21,1),iso(u+4,side*21,1);cv.create_line(*a,*b,fill='#bd8b5e',width=4)
    for off in [-3,3]:a,b=iso(u+off,side*21,0),iso(u+off,side*21,1);cv.create_line(*a,*b,fill='#495666',width=1)
    a,b=iso(u+10,side*19,0),iso(u+10,side*19,8);cv.create_line(*a,*b,fill='#c5d3e0',width=2);x,y=b;cv.create_oval(x-3,y-2,x+3,y+2,fill='#fff4c3',outline='#e6cf82')
   for u in [-105,105]:
    low,high=sorted([side*25,side*34]);rect(u-5,u+5,low,high,1,'#425c48','#759b74');x,y=iso(u,side*29,3);cv.create_oval(x-7,y-4,x+7,y+4,fill='#6d9677',outline='')
   x,y=iso(-32,side*22,5);rounded(cv,x-40,y-10,x+40,y+10,4,fill='#102235',outline=color,width=2);cv.create_text(x,y,text=s['name'],fill='#e8f1f8',font=('Microsoft YaHei UI',-11,'bold'))
  visible=False
  if e.conn:
   head=e.snapshot()[0];u=(head[0]-center[0])*tx+(head[1]-center[1])*ty;v=(head[0]-center[0])*nx+(head[1]-center[1])*ny;visible=abs(u)<230 and abs(v)<70
   if visible:
    for k in reversed(range(e.cars)):
     front=e.point_behind(k*20+1);back=e.point_behind(k*20+19)
     def local(xy):return (xy[0]-center[0])*tx+(xy[1]-center[1])*ty,(xy[0]-center[0])*nx+(xy[1]-center[1])*ny
     fu,fv=local(front);bu,bv=local(back)
     if abs(fu)>132 or abs(bu)>132 or abs(abs(fv)-8)>4 or abs(abs(bv)-8)>4:continue
     rect(bu,fu,min(fv,bv)-1.4,max(fv,bv)+1.4,3.8,color if k==0 else '#e1e9ef','#f5f9fd')
     polygon([(bu,bv+1.4,3.8),(fu,fv+1.4,3.8),(fu,fv+1.4,1),(bu,bv+1.4,1)],'#7893aa')
     for t in [.2,.45,.7]:
      x,y=iso(bu+(fu-bu)*t,bv+(fv-bv)*t,4);cv.create_rectangle(x-3,y-1,x+3,y+1,fill='#3c6480',outline='')
  caption=('列车进站 / 停靠' if visible else '站台展示 · 等候列车')+('   |   试乘方案跳停站' if not s['stop_enabled'] else '')
  cv.create_text(w/2,h-15,text=caption+'   ·   雨棚 / 灯柱 / 座椅 / 花坛',fill='#9fb5c9',font=('Microsoft YaHei UI',-11))
 def redraw():
  e=selected_engine()
  if follow.get() and e.conn:
   chosen=e.current
   if not e.arrived:
    target=e.stations[e.target];pos=e.snapshot()[0]
    if math.dist(pos,(target['x'],target['y']))<450:chosen=e.target
   state['station']=chosen
  for lid,button in tabs.items():
   item=engines[lid];suffix=' · 暂停' if item.conn and item.paused else (' · 运行' if item.conn else '')
   button.configure(text=f'{lid}号线{suffix}',highlightbackground='#ecf6ff',highlightthickness=2 if lid==state['line'] else 0)
  label=e.status
  if e.conn:label+=(' · 暂停' if e.paused else ' · 运行')+(' · 自动' if e.auto else '')
  status.set(label)
  if e.conn:
   _,v,t=e.snapshot();telemetry.set(f'本线 {v*3.6:.1f} km/h · {int(t)//60}:{int(t)%60:02}\n里程 {e.distance/1000:.2f} km · 到站 {len(e.visits)} 次\n运行线路：'+ ' / '.join(str(lid) for lid,item in engines.items() if item.conn))
  else:telemetry.set(f'本线未启动 · {len(e.enabled)} 个停靠站\n{e.cars} 节车厢 · 最高 {e.config["speed_kmh"]} km/h')
  draw_map();draw_station()
 def tick():
  try:
   try:selected_engine().dwell=max(1,int(dwell.get()))
   except (ValueError,tk.TclError):pass
   for item in engines.values():
    if item.conn and not item.paused:
     for _ in range(max(1,rate.get())):item.step()
   redraw()
  except Exception as exc:
   logging.exception('Simulation failed');messagebox.showerror('仿真提示',str(exc),parent=root)
   for item in engines.values():
    if item.conn:item.paused=True
  root.after(200,tick)
 def close():
  for item in engines.values():item.close()
  root.destroy()
 mapcanvas.bind('<Configure>',lambda event:redraw());stationcanvas.bind('<Configure>',lambda event:redraw());root.protocol('WM_DELETE_WINDOW',close);switch_line(1);root.after(200,tick);root.mainloop()
