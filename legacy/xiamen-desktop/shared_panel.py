import tkinter as tk
from tkinter import ttk,messagebox,filedialog
import math,json,os,logging,time,subprocess
from geo_map import GeoMap
from run_assessment import save_assessment
from map_symbols import RetainedLayer,vehicle_symbol,person_symbol,group_offset,draw_legend
from depot_renderer import DepotRenderer
from ui_scheduler import BudgetStepper,UiMeasurements,acquire_timer_resolution
from network_engine import NetworkEngine,ROOT,LINES,LINE_IDS,DATA,sumo_working_root
TITLE='厦门综合交通仿真 · 3.0'

class StationAdapter:
 def __init__(self,engine,lid,train):
  self.engine=engine;self.line_id=lid;self.stations={s['id']:s for s in engine.stations[lid]};self.cars=LINES[lid]['cars'];self.train=train;self.conn=engine.conn if train else None
 def snapshot(self):return self.train['position'],self.train['speed'],self.engine.time
 def point_behind(self,d):return self.engine.point_behind(self.train,d)

def run_app():
 if os.name=='nt':
  import ctypes
  try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
  except Exception:pass
 root=tk.Tk();root.title(TITLE);root.configure(bg='#eaf0f6')
 root.geometry(f'{min(1540,root.winfo_screenwidth()-70)}x{min(970,root.winfo_screenheight()-80)}+25+20');root.minsize(1100,740)
 if os.environ.get('XIAMEN_UI_SIZE'):root.geometry(os.environ['XIAMEN_UI_SIZE'])
 engine=NetworkEngine();geo=GeoMap(ROOT);depotview=DepotRenderer(ROOT);depotview.reload(engine);stepper=BudgetStepper();measurements=UiMeasurements();state={'line':1,'station':5,'focus':None,'zoom':1.,'pan':[0.,0.],'projection':None,'frame_dirty':True,'metrics_dirty':True,'last_frame':0.,'last_metrics':0.,'last_model_time':None};tabs={};hits=[]
 style=ttk.Style();style.theme_use('clam');style.configure('TFrame',background='#eaf0f6');style.configure('TLabel',background='#eaf0f6',foreground='#233d53');style.configure('Primary.TButton',background='#087f8c',foreground='white',font=('Microsoft YaHei UI',-14,'bold'),padding=10);style.map('Primary.TButton',background=[('active','#096575')]);style.configure('TCheckbutton',background='#eaf0f6');style.configure('TRadiobutton',background='#eaf0f6',font=('Microsoft YaHei UI',-12));style.configure('TLabel',font=('Microsoft YaHei UI',-13));style.configure('TButton',font=('Microsoft YaHei UI',-13),padding=7);style.configure('TCheckbutton',font=('Microsoft YaHei UI',-12))
 style.configure('TNotebook',background='#eaf0f6',borderwidth=0);style.configure('TNotebook.Tab',padding=(10,11),font=('Microsoft YaHei UI',-12,'bold'),background='#dbe5ed',foreground='#49647b');style.map('TNotebook.Tab',background=[('selected','#ffffff')],foreground=[('selected','#087f8c')]);style.configure('Treeview',font=('Microsoft YaHei UI',-11),rowheight=27,background='white',fieldbackground='white',foreground='#253e52');style.configure('Treeview.Heading',font=('Microsoft YaHei UI',-11,'bold'),background='#dbe5ed',foreground='#324f68');style.configure('Danger.TButton',foreground='#a33d3d',padding=7)
 style.configure('TLabelframe',background='#eaf0f6',bordercolor='#c9d7e3',relief='solid');style.configure('TLabelframe.Label',background='#eaf0f6',foreground='#345a73',font=('Microsoft YaHei UI',-13,'bold'));style.configure('TCombobox',padding=4);style.configure('TSpinbox',padding=4)
 outer=ttk.Frame(root,padding=14);outer.pack(fill='both',expand=True)
 header=tk.Frame(outer,bg='#12324c',padx=18,pady=13);header.pack(fill='x')
 tk.Label(header,text='厦门综合交通  /  运营调度中心',bg='#12324c',fg='#f0f7fc',font=('Microsoft YaHei UI',-23,'bold')).pack(side='left')
 clock=tk.StringVar(value='准备就绪');tk.Label(header,textvariable=clock,bg='#12324c',fg='#a7c8dc',font=('Microsoft YaHei UI',-12)).pack(side='right')
 ttk.Label(outer,text='XIAMEN MOBILITY   ·   五线轨道 / 公交接驳 / 客流换乘 / 信号防护',foreground='#6b8799',font=('Microsoft YaHei UI',-11)).pack(anchor='w',pady=(7,0))
 metrics=ttk.Frame(outer);metrics.pack(fill='x',pady=(10,0));metric_vars={}
 for key,caption in [('trains','在轨列车'),('buses','运行公交'),('people','聚合客流出发人数'),('signals','人工红灯 / 信号数')]:
  card=tk.Frame(metrics,bg='white',padx=14,pady=7);card.pack(side='left',fill='x',expand=True,padx=4);tk.Label(card,text=caption,bg='white',fg='#73879a',font=('Microsoft YaHei UI',-11)).pack(anchor='w');metric_vars[key]=tk.StringVar(value='—');tk.Label(card,textvariable=metric_vars[key],bg='white',fg='#173e56',font=('Microsoft YaHei UI',-21,'bold')).pack(anchor='w')
 top=ttk.Frame(outer);top.pack(fill='x',pady=10)
 def select(lid):
  state['line']=lid;state['focus']=None;state['station']=next(s['id'] for s in engine.stations[lid] if s['interchange_lines']);headway.set(engine.settings[lid]['headway']);speed.set(engine.settings[lid]['speed']);stationbox.configure(values=[f"{s['id']:02}  {s['name']}" for s in engine.stations[lid]]);stationbox.current(state['station']-1);refresh_depots();redraw()
 for lid in LINE_IDS:
  b=tk.Button(top,text=f'{lid}号线',bg=LINES[lid]['color'],fg='white',font=('Microsoft YaHei UI',-15,'bold'),relief='flat',padx=16,pady=9,command=lambda lid=lid:select(lid));b.pack(side='left',expand=True,fill='x',padx=4);tabs[lid]=b
 toolbar=ttk.Frame(outer);toolbar.pack(fill='x',pady=(0,9))
 mapmode=tk.StringVar(value='geo' if geo.data else 'schematic')
 def switch_map():
  state['zoom']=1.;state['pan']=[0.,0.];geo.signature=None;model_layer.clear();state['map_signature']=None;mapcanvas.delete('all');redraw()
 ttk.Radiobutton(toolbar,text='城市地理地图',variable=mapmode,value='geo',command=switch_map).pack(side='left',padx=(0,12))
 ttk.Radiobutton(toolbar,text='联合仿真路网',variable=mapmode,value='schematic',command=switch_map).pack(side='left',padx=(0,12))
 ttk.Button(toolbar,text='恢复全图',command=switch_map).pack(side='left')
 mapstatus=tk.StringVar(value=geo.summary());ttk.Label(toolbar,textvariable=mapstatus,foreground='#51748a',font=('Microsoft YaHei UI',-11)).pack(side='right')
 body=ttk.Frame(outer);body.pack(fill='both',expand=True)
 left=ttk.Frame(body);left.pack(side='left',expand=True,fill='both',padx=(0,12))
 mapcanvas=tk.Canvas(left,height=100,bg='#101d2d',highlightthickness=0);mapcanvas.pack(fill='both',expand=True)
 legend=tk.Canvas(left,height=54,bg='#14283a',highlightthickness=0);legend.pack(fill='x');legend.bind('<Configure>',lambda e:draw_legend(legend));model_layer=RetainedLayer(mapcanvas)
 nearbar=ttk.Frame(left);nearbar.pack(fill='x',pady=(8,5));near_mode=tk.StringVar(value='station');near_expanded=tk.BooleanVar(value=False);depot_scope=tk.StringVar(value='本线两端');depot_choice=tk.StringVar();depot_names={}
 ttk.Label(nearbar,text='场站近景',font=('Microsoft YaHei UI',-12,'bold')).pack(side='left',padx=(0,12))
 ttk.Radiobutton(nearbar,text='站台',variable=near_mode,value='station',command=lambda:switch_near()).pack(side='left',padx=(0,9));ttk.Radiobutton(nearbar,text='车辆段',variable=near_mode,value='depot',command=lambda:switch_near()).pack(side='left',padx=(0,12))
 depot_scopebox=ttk.Combobox(nearbar,textvariable=depot_scope,values=['本线两端','全网十段'],state='readonly',width=9);depot_scopebox.pack(side='left',padx=(0,6));depot_box=ttk.Combobox(nearbar,textvariable=depot_choice,state='readonly',width=25);depot_box.pack(side='left',fill='x',expand=True)
 ttk.Checkbutton(nearbar,text='放大近景',variable=near_expanded,command=lambda:(resize_near(),redraw())).pack(side='right',padx=(7,0))
 stationcanvas=tk.Canvas(left,height=220,bg='#18283a',highlightthickness=0);stationcanvas.pack(fill='x')
 sidebar=ttk.Frame(body,width=380);sidebar.pack(side='right',fill='y');sidebar.pack_propagate(False)
 notebook=ttk.Notebook(sidebar);notebook.pack(fill='both',expand=True);panels={};scrollers=[]
 for key,label in [('operations','运营'),('mobility','客流公交'),('signals','轨道信号'),('map','地图资料')]:
  page=ttk.Frame(notebook);notebook.add(page,text=label);scroll=tk.Canvas(page,bg='#eaf0f6',highlightthickness=0);bar=ttk.Scrollbar(page,orient='vertical',command=scroll.yview);bar.pack(side='right',fill='y');scroll.pack(side='left',fill='both',expand=True);scroll.configure(yscrollcommand=bar.set)
  content=ttk.Frame(scroll,padding=(11,12));window=scroll.create_window((0,0),window=content,anchor='nw');content.bind('<Configure>',lambda e,scroll=scroll:scroll.configure(scrollregion=scroll.bbox('all')));scroll.bind('<Configure>',lambda e,scroll=scroll,window=window:scroll.itemconfigure(window,width=e.width));panels[key]=content;scrollers.append((scroll,content))
 side=panels['operations']
 operation_card=ttk.LabelFrame(side,text='行车与时钟',padding=10);operation_card.pack(fill='x',pady=(0,12));side=operation_card
 gui=tk.BooleanVar(value=False);headway=tk.IntVar(value=180);rate=tk.IntVar(value=20);speed=tk.DoubleVar(value=80);info=tk.StringVar();fleet=tk.StringVar();detail=tk.StringVar();trip=tk.StringVar();passinfo=tk.StringVar();follow=tk.BooleanVar(value=True)
 def safe(fn):
  try:fn();redraw()
  except Exception as exc:logging.exception('control');messagebox.showerror('操作提示',str(exc),parent=root)
 ttk.Label(side,text='运营控制',font=('Microsoft YaHei UI',-17,'bold')).pack(anchor='w')
 ttk.Checkbutton(side,text='同时打开 SUMO 轨道窗口',variable=gui).pack(anchor='w',pady=5)
 ttk.Button(side,text='启动五线 · 双向连续发车',style='Primary.TButton',command=lambda:safe(lambda:engine.start_all(gui.get()))).pack(fill='x',pady=3)
 ttk.Button(side,text='启动选中线路',command=lambda:safe(lambda:engine.start_line(state['line'],gui.get()))).pack(fill='x',pady=3)
 def pause():engine.paused=not engine.paused
 ttk.Button(side,text='暂停 / 继续整个路网',command=lambda:safe(pause)).pack(fill='x',pady=3)
 def stop_dispatch():engine.settings[state['line']]['enabled']=False;engine.events.append(f"{state['line']}号线停止增派车辆，已有列车继续运行")
 ttk.Button(side,text='本线停止增派列车',command=lambda:safe(stop_dispatch)).pack(fill='x',pady=3)
 def reset():
  nonlocal engine
  engine.close();engine=NetworkEngine();stepper.reset(engine);depotview.reload(engine);state['map_signature']=None;state['focus']=None;state.pop('passenger',None);passinfo.set('');groupinfo.set('');depot_action.set('');demand.set(False);signal_detail.set('已重置，启动仿真后查看实时信号。')
  if getattr(engine,'mobility',None):
   bus_names.clear();bus_names.update({str(r['id']):r.get('name',str(r['id'])) for r in engine.mobility.bus_lines()});busbox.configure(values=list(bus_names.values()));buschoice.set(next(iter(bus_names.values()),''))
   for field in groupboxes:field.configure(values=engine.mobility.endpoints())
  busshapes.clear();busshapes.extend(edge.getShape() for edge in engine.net.getEdges() if edge.getID().startswith(('B01_','B02_','B03_','B04_')) and 'Walk' not in edge.getID());select(state['line'])
  if bus_names:show_bus()
 ttk.Button(side,text='重置整个路网',command=lambda:safe(reset)).pack(fill='x',pady=3)
 row=ttk.Frame(side);row.pack(fill='x',pady=(10,3));ttk.Label(row,text='发车间隔（秒）').pack(side='left');ttk.Spinbox(row,from_=60,to=600,increment=30,textvariable=headway,width=6).pack(side='right')
 ttk.Button(side,text='应用本线发车间隔',command=lambda:safe(lambda:engine.set_headway(state['line'],headway.get()))).pack(fill='x',pady=3)
 row=ttk.Frame(side);row.pack(fill='x',pady=5);ttk.Label(row,text='最高速度（km/h）').pack(side='left');ttk.Spinbox(row,from_=10,to=120,increment=10,textvariable=speed,width=6).pack(side='right')
 ttk.Button(side,text='应用本线速度',command=lambda:safe(lambda:engine.set_speed(state['line'],speed.get()))).pack(fill='x',pady=3)
 row=ttk.Frame(side);row.pack(fill='x',pady=6);ttk.Label(row,text='仿真速度').pack(side='left');ttk.Combobox(row,textvariable=rate,values=[1,5,10,20,50,100],width=6,state='readonly').pack(side='right')
 ttk.Label(side,textvariable=fleet,foreground='#38708f',wraplength=305).pack(fill='x',pady=7)
 ttk.Separator(side).pack(fill='x',pady=6)
 side=panels['mobility']
 ttk.Label(side,text='客流与公交接驳',font=('Microsoft YaHei UI',-17,'bold')).pack(anchor='w')
 mobilityinfo=tk.StringVar(value='启动路网后，可生成分组乘客与接驳公交。');ttk.Label(side,textvariable=mobilityinfo,foreground='#357c89',wraplength=327).pack(fill='x',pady=(7,8))
 ttk.Label(side,text='每个客流点表示 20 人；不足 20 人显示余量。',foreground='#657e94',wraplength=327).pack(fill='x',pady=(0,8))
 assessmentinfo=tk.StringVar(value='有乘客到达后显示行程与候车均值。')
 assessment_card=ttk.LabelFrame(side,text='运行评估',padding=8);assessment_card.pack(fill='x',pady=(0,8))
 ttk.Label(assessment_card,textvariable=assessmentinfo,wraplength=305,foreground='#365c70').pack(fill='x')
 def export_assessment():
  name=filedialog.asksaveasfilename(parent=root,title='保存运行评估',defaultextension='.json',filetypes=[('JSON report','*.json')],initialfile='厦门运行评估.json')
  if name:
   paths=save_assessment(name,engine,rate.get(),stepper.actual_rate)
   engine.events.append('运行评估已保存：'+paths[0].name);redraw()
 ttk.Button(assessment_card,text='导出运行报告与客流明细',command=lambda:safe(export_assessment)).pack(fill='x',pady=(7,0))
 ttk.Label(assessment_card,text='均值仅统计已到达聚合乘客，按人数加权。',wraplength=305,foreground='#657e94').pack(fill='x')
 def mobility():
  manager=getattr(engine,'mobility',None)
  if manager is None:raise RuntimeError('客流与公交模块尚未载入，请重新启动最新版项目。')
  return manager
 demand=tk.BooleanVar(value=False)
 def demand_changed():
  if demand.get():engine.start_all(gui.get())
  mobility().set_demand_enabled(demand.get())
 ttk.Checkbutton(side,text='持续生成示范客流',variable=demand,command=lambda:safe(demand_changed)).pack(anchor='w',pady=3)
 bus_card=ttk.LabelFrame(side,text='公交接驳服务',padding=10);bus_card.pack(fill='x',pady=(9,12));side=bus_card
 buslines=mobility().bus_lines() if getattr(engine,'mobility',None) else [];bus_names={str(r['id']):r.get('name',f"{r['id']} · {r.get('label',r['id'])}") for r in buslines}
 ttk.Label(side,text='接驳公交线路',font=('Microsoft YaHei UI',-14,'bold')).pack(anchor='w',pady=(10,4))
 buschoice=tk.StringVar(value=next(iter(bus_names.values()),''));busbox=ttk.Combobox(side,textvariable=buschoice,values=list(bus_names.values()),state='readonly');busbox.pack(fill='x')
 busheadway=tk.IntVar(value=120);row=ttk.Frame(side);row.pack(fill='x',pady=7);ttk.Label(row,text='公交间隔（秒）').pack(side='left');ttk.Spinbox(row,from_=30,to=600,increment=30,textvariable=busheadway,width=7).pack(side='right')
 busdetail=tk.StringVar();ttk.Label(side,textvariable=busdetail,foreground='#587086',wraplength=327).pack(fill='x',pady=(0,4))
 def selected_bus_id():
  selected=buschoice.get()
  if not selected:raise ValueError('当前没有公交线路。')
  return selected.split(' · ',1)[0]
 def show_bus(event=None):
  selected=next((r for r in mobility().bus_lines() if str(r['id'])==selected_bus_id()),None)
  if selected:
   busheadway.set(selected.get('headway',120));busdetail.set(f"{selected.get('community_name','接驳起点')} ⇄ {selected.get('metro_hub','轨道枢纽')}\n线路为模拟接驳，公交与地铁共用仿真时钟。")
 busbox.bind('<<ComboboxSelected>>',show_bus)
 def start_bus():engine.start(gui.get());mobility().start_bus(selected_bus_id(),busheadway.get());engine.paused=False
 ttk.Button(side,text='启动本线接驳公交',style='Primary.TButton',command=lambda:safe(start_bus)).pack(fill='x',pady=3)
 row=ttk.Frame(side);row.pack(fill='x',pady=3);ttk.Button(row,text='应用间隔',command=lambda:safe(lambda:mobility().set_bus_headway(selected_bus_id(),busheadway.get()))).pack(side='left',expand=True,fill='x',padx=(0,4));ttk.Button(row,text='停止本线增派',command=lambda:safe(lambda:mobility().stop_bus(selected_bus_id()))).pack(side='left',expand=True,fill='x')
 def start_buses():engine.start(gui.get());mobility().start_buses();engine.paused=False
 ttk.Button(side,text='启动全部接驳线',command=lambda:safe(start_buses)).pack(fill='x',pady=3)
 side=panels['mobility'];journey_card=ttk.LabelFrame(side,text='乘客行程',padding=10);journey_card.pack(fill='x',pady=(0,12));side=journey_card
 ttk.Label(side,text='轨道换乘与分组出行',font=('Microsoft YaHei UI',-15,'bold')).pack(anchor='w')
 names=sorted(engine.by_name);origin=tk.StringVar(value='镇海路');destination=tk.StringVar(value='人才中心')
 for caption,var in [('出发站',origin),('目的站',destination)]:
  ttk.Label(side,text=caption).pack(anchor='w',pady=(5,2));ttk.Combobox(side,textvariable=var,values=names,state='readonly').pack(fill='x')
 def plan():trip.set(engine.trip_text(engine.plan(origin.get(),destination.get())))
 ttk.Button(side,text='查看乘车方案',command=lambda:safe(plan)).pack(fill='x',pady=4)
 def passenger():plan();pid=engine.add_passenger(origin.get(),destination.get());state['passenger']=pid
 ttk.Button(side,text='单人换乘演示',command=lambda:safe(passenger)).pack(fill='x',pady=3)
 ttk.Label(side,textvariable=trip,wraplength=305,foreground='#476279').pack(fill='x',pady=4)
 ttk.Label(side,textvariable=passinfo,wraplength=305,foreground='#278e86').pack(fill='x',pady=4)
 groupnames=mobility().endpoints() if getattr(engine,'mobility',None) else names
 grouporigin=tk.StringVar(value=next((r.get('community_name') for r in buslines if r.get('community_name')),'镇海路'));groupdestination=tk.StringVar(value='人才中心');groupcount=tk.IntVar(value=100)
 groupboxes=[]
 for caption,var in [('客流出发点',grouporigin),('客流目的地',groupdestination)]:
  ttk.Label(side,text=caption).pack(anchor='w',pady=(5,2));field=ttk.Combobox(side,textvariable=var,values=groupnames,state='readonly');field.pack(fill='x');groupboxes.append(field)
 row=ttk.Frame(side);row.pack(fill='x',pady=7);ttk.Label(row,text='出发人数').pack(side='left');ttk.Spinbox(row,from_=1,to=1000,increment=20,textvariable=groupcount,width=7).pack(side='right')
 groupinfo=tk.StringVar()
 def send_group():
  engine.start_all(gui.get());manager=mobility();created=manager.add_group(grouporigin.get(),groupdestination.get(),groupcount.get());groupinfo.set(f"已生成 {groupcount.get()} 人客流：{grouporigin.get()} → {groupdestination.get()}\n公交下车后步行接入地铁换乘。")
 ttk.Button(side,text='生成人员流动 · 公交地铁联动',style='Primary.TButton',command=lambda:safe(send_group)).pack(fill='x',pady=3)
 ttk.Label(side,textvariable=groupinfo,wraplength=327,foreground='#278e86').pack(fill='x',pady=5)
 side=panels['operations']
 station_card=ttk.LabelFrame(side,text='场站巡视',padding=10);station_card.pack(fill='x',pady=(0,12));side=station_card
 ttk.Label(side,text='站台与列车',font=('Microsoft YaHei UI',-17,'bold')).pack(anchor='w')
 stationbox=ttk.Combobox(side,state='readonly');stationbox.pack(fill='x',pady=5)
 def choose_station(event=None):state['station']=stationbox.current()+1;follow.set(False);redraw()
 stationbox.bind('<<ComboboxSelected>>',choose_station)
 ttk.Checkbutton(side,text='近景跟随选中列车',variable=follow).pack(anchor='w')
 trainbox=ttk.Combobox(side,state='readonly');trainbox.pack(fill='x',pady=5)
 def choose_train(event=None):state['focus']=trainbox.get();redraw()
 trainbox.bind('<<ComboboxSelected>>',choose_train)
 ttk.Label(side,textvariable=detail,wraplength=305).pack(fill='x',pady=4)
 ttk.Label(side,textvariable=info,wraplength=305,foreground='#76899a').pack(fill='x',pady=8)
 depotinfo=tk.StringVar(value='车辆段近景显示真实在段列车与出入段信号。');ttk.Label(side,textvariable=depotinfo,wraplength=300,foreground='#658497').pack(fill='x',pady=(4,6))
 def inspect_depot():depot_scope.set('本线两端');near_mode.set('depot');refresh_depots();switch_near()
 ttk.Button(side,text='查看本线车辆段近景',command=inspect_depot).pack(fill='x',pady=3)
 depot_action=tk.StringVar();depot_controls=ttk.Frame(side);depot_controls.pack(fill='x',pady=(5,3))
 def depot_train():
  chosen=selected_train()
  if not chosen:raise ValueError('请先启动线路并选择一列实际运行列车。')
  return chosen
 def request_depot():
  train=depot_train();engine.send_to_depot(train['id']);depot_action.set(f"{train['id']} 已预约回段：到端站清客后进入车辆段整备。")
 def release_depot():
  train=depot_train();engine.release_from_depot(train['id']);depot_action.set(f"{train['id']} 已申请结束整备，按出段信号重新投入运营。")
 ttk.Button(depot_controls,text='预约回段整备',command=lambda:safe(request_depot)).pack(side='left',fill='x',expand=True,padx=(0,5));ttk.Button(depot_controls,text='整备完成 · 出段',command=lambda:safe(release_depot)).pack(side='left',fill='x',expand=True)
 ttk.Label(side,textvariable=depot_action,wraplength=300,foreground='#278e86').pack(fill='x',pady=4)
 ttk.Separator(side).pack(fill='x',pady=7)
 side=panels['signals']
 ttk.Label(side,text='轨道信号调度',font=('Microsoft YaHei UI',-17,'bold')).pack(anchor='w')
 ttk.Label(side,text='查看实际 SUMO 信号与区段占用，按需设置限时红灯，或恢复自动铁路信号。',wraplength=327,foreground='#587086').pack(fill='x',pady=(7,9))
 signal_scope=tk.StringVar(value='本线');row=ttk.Frame(side);row.pack(fill='x');ttk.Label(row,text='查看范围').pack(side='left');scopebox=ttk.Combobox(row,textvariable=signal_scope,values=['本线','全部线路'],state='readonly',width=11);scopebox.pack(side='right')
 signal_frame=ttk.Frame(side);signal_frame.pack(fill='x',pady=8);signal_tree=ttk.Treeview(signal_frame,columns=('state','mode','occupied'),show='tree headings',height=10,selectmode='browse');signal_tree.heading('#0',text='区段信号');signal_tree.column('#0',width=120,minwidth=100);signal_tree.heading('state',text='灯色');signal_tree.column('state',width=43,stretch=False);signal_tree.heading('mode',text='模式');signal_tree.column('mode',width=54,stretch=False);signal_tree.heading('occupied',text='占用');signal_tree.column('occupied',width=55,stretch=False);signal_tree.pack(side='left',fill='both',expand=True);signal_bar=ttk.Scrollbar(signal_frame,orient='vertical',command=signal_tree.yview);signal_bar.pack(side='right',fill='y');signal_tree.configure(yscrollcommand=signal_bar.set)
 for tag,color in [('red','#ad4c4c'),('green','#27806e'),('hold','#b87921')]:signal_tree.tag_configure(tag,foreground=color)
 signal_detail=tk.StringVar(value='启动仿真后可查看实时灯色与区段占用。');ttk.Label(side,textvariable=signal_detail,wraplength=327,foreground='#547087').pack(fill='x',pady=(0,6))
 signal_seconds=tk.IntVar(value=60);row=ttk.Frame(side);row.pack(fill='x',pady=6);ttk.Label(row,text='保持红灯（仿真秒）').pack(side='left');ttk.Spinbox(row,from_=5,to=900,increment=15,textvariable=signal_seconds,width=7).pack(side='right')
 def selected_signal():
  selection=signal_tree.selection()
  if not selection:raise ValueError('请先选择一个轨道信号。')
  return selection[0]
 def hold_selected():engine.hold_signal(selected_signal(),signal_seconds.get())
 def release_selected():engine.release_signal(selected_signal())
 ttk.Button(side,text='选中区段 · 限时红灯',style='Danger.TButton',command=lambda:safe(hold_selected)).pack(fill='x',pady=3)
 ttk.Button(side,text='选中区段 · 恢复自动',style='Primary.TButton',command=lambda:safe(release_selected)).pack(fill='x',pady=3)
 ttk.Button(side,text='本线全部信号 · 限时红灯',command=lambda:safe(lambda:engine.set_line_hold(state['line'],signal_seconds.get()))).pack(fill='x',pady=3)
 def release_line():
  for record in engine.signal_list(state['line']):engine.release_signal(record['id'])
 ttk.Button(side,text='本线全部信号 · 恢复自动',command=lambda:safe(release_line)).pack(fill='x',pady=3)
 ttk.Label(side,text='红灯到期后自动归还 SUMO 信号控制；区段保护由铁路信号逻辑处理。',wraplength=327,foreground='#73879a').pack(fill='x',pady=8)
 signal_rows={}
 def show_signal(event=None):
  selection=signal_tree.selection();record=signal_rows.get(selection[0]) if selection else None
  if record:signal_detail.set(f"{record['id']}  ·  实际状态 {record.get('state','—')}\n{record.get('mode','自动闭塞')} · 剩余 {record.get('remaining',0):.0f} 秒\n接近轨道占用：{record.get('occupied','—')}")
 signal_tree.bind('<<TreeviewSelect>>',show_signal)
 side=panels['map']
 ttk.Label(side,text='城市地图与数据',font=('Microsoft YaHei UI',-17,'bold')).pack(anchor='w')
 def reload_map():
  if not geo.reload():raise RuntimeError('尚无地图缓存，请先双击 Download_Map.bat 下载。')
  realbus_labels.clear();realbus_labels.update({str(r['id']):f"{r.get('ref') or '未编号'} · {r.get('name') or str(r['id'])} [{r['id']}]" for r in geo.bus_routes});realbus_box.configure(values=list(realbus_labels.values()))
  if realbus_choice.get() not in realbus_labels.values():realbus_choice.set(next(iter(realbus_labels.values()),''))
  mapstatus.set(geo.summary());mapmode.set('geo');switch_map()
 def open_osm():
  cfg=ROOT/'maps/osm/xiamen.osm.sumocfg'
  if not cfg.exists():raise RuntimeError('尚未生成真实地图场景，请先双击 Download_Map.bat。')
  working=sumo_working_root();subprocess.Popen([str(working/'runtime/sumo/bin/sumo-gui.exe'),'-c','maps/osm/xiamen.osm.sumocfg'],cwd=working)
 def coverage():
  if not geo.data:raise RuntimeError('请先下载地图。')
  report=geo.data['report'];text='\n'.join(f"{lid}号线：{v['matched']}/{v['total']} 个站点已定位" for lid,v in report['station_coverage'].items())
  text+='\n\n缺少坐标：'+('、'.join(report['missing_unique']) or '无')+'\n\n虚线为站点示意连接。原有仿真仍使用示意轨道。'
  messagebox.showinfo('真实地图覆盖检查',text,parent=root)
 ttk.Button(side,text='载入已下载的地图',command=lambda:safe(reload_map)).pack(fill='x',pady=3)
 ttk.Button(side,text='查看站点覆盖与缺失',command=lambda:safe(coverage)).pack(fill='x',pady=3)
 ttk.Button(side,text='打开 SUMO 真实路网',command=lambda:safe(open_osm)).pack(fill='x',pady=3)
 ttk.Separator(side).pack(fill='x',pady=10)
 ttk.Label(side,text='真实公交 GIS 线网',font=('Microsoft YaHei UI',-15,'bold')).pack(anchor='w')
 realbus_labels={str(r['id']):f"{r.get('ref') or '未编号'} · {r.get('name') or str(r['id'])} [{r['id']}]" for r in geo.bus_routes}
 firstreal=next((r for r in geo.bus_routes if any(s.get('metro_nearby') for s in r.get('stops',[]))),geo.bus_routes[0] if geo.bus_routes else None)
 realbus_choice=tk.StringVar(value=realbus_labels.get(str(firstreal['id']),'') if firstreal else '');realbus_show=tk.BooleanVar(value=False);realbus_info=tk.StringVar()
 if firstreal:state['osm_bus_id']=str(firstreal['id'])
 realbus_ref_count=len({r.get('ref') for r in geo.bus_routes if r.get('ref')});ttk.Label(side,text=f"已缓存 {len(geo.bus_routes)} 条方向关系 / {realbus_ref_count} 个线路编号。",foreground='#357c89',wraplength=327).pack(fill='x',pady=(6,4))
 realbus_box=ttk.Combobox(side,textvariable=realbus_choice,values=list(realbus_labels.values()),state='readonly');realbus_box.pack(fill='x',pady=3)
 def selected_realbus():return next((r for r in geo.bus_routes if realbus_labels.get(str(r['id']))==realbus_choice.get()),None)
 def update_realbus(event=None):
  route=selected_realbus();state['show_osm_bus']=realbus_show.get()
  if route:
   state['osm_bus_id']=str(route['id']);nearby=[f"{s.get('name','公交站')} → {link['name']} {link['distance_m']:.0f} m" for s in route.get('stops',[]) for link in s.get('metro_nearby',[])];realbus_info.set(f"{route.get('from','')} → {route.get('to','')}\n{len(route.get('stops',[]))} 个站点成员 · {len(route.get('shapes_wgs84',[]))} 段来源几何\n地铁近邻（直线距离 ≤ 650 m）：\n"+('\n'.join(nearby[:8]) or '当前线路未找到地铁近邻站点')+('\n…' if len(nearby)>8 else ''))
  geo.signature=None;redraw()
 realbus_box.bind('<<ComboboxSelected>>',update_realbus)
 ttk.Checkbutton(side,text='在城市地图显示选中真实公交线',variable=realbus_show,command=lambda:safe(update_realbus)).pack(anchor='w',pady=4)
 def locate_realbus():
  route=selected_realbus()
  if not route:raise ValueError('当前没有可显示的真实公交线路。')
  points=[geo.project(*p) for shape in route.get('shapes_wgs84',[]) for p in shape]
  if not points:raise ValueError('这条 OSM 关系暂无可显示的线路几何。')
  xmin,xmax,ymin,ymax=geo.bounds;w,h=mapcanvas.winfo_width(),mapcanvas.winfo_height();base=min(max(1,w-70)/(xmax-xmin),max(1,h-130)/(ymax-ymin));rx0,rx1=min(p[0] for p in points),max(p[0] for p in points);ry0,ry1=min(p[1] for p in points),max(p[1] for p in points);state['zoom']=max(.7,min(8,min((w-120)/max(100,rx1-rx0),(h-150)/max(100,ry1-ry0))/base));scale=base*state['zoom'];state['pan']=[((xmin+xmax)-(rx0+rx1))*scale/2,((ry0+ry1)-(ymin+ymax))*scale/2];mapmode.set('geo');realbus_show.set(True);update_realbus()
 ttk.Button(side,text='定位并显示本条公交线路',command=lambda:safe(locate_realbus)).pack(fill='x',pady=3)
 def open_realbus_sumo():
  cfg=ROOT/'maps/osm/xiamen.bus.sumocfg'
  if not cfg.exists():raise RuntimeError('真实公交运行场景尚未生成，请先运行 tools/build_osm_buses.py。')
  working=sumo_working_root();subprocess.Popen([str(working/'runtime/python/pythonw.exe'),'-E','-s',str(working/'tools/run_osm_buses.py')],cwd=working)
 ttk.Button(side,text='打开 SUMO · 真实公交地理场景',command=lambda:safe(open_realbus_sumo)).pack(fill='x',pady=3)
 ttk.Label(side,textvariable=realbus_info,wraplength=327,foreground='#587086').pack(fill='x',pady=6)
 ttk.Label(side,text='橙线来自 OSM 公交方向关系；虚线连接表示地铁近邻，采用直线距离。真实地理场景采用模拟发车间隔；联动运行的 B01–B04 为独立接驳示范线。',wraplength=327,foreground='#73879a').pack(fill='x',pady=(3,7))
 eventbox=tk.Text(side,height=6,bg='#e0e8f0',fg='#486278',font=('Microsoft YaHei UI',-11),relief='flat',wrap='word');eventbox.pack(fill='x',pady=5)
 ttk.Label(left,text='滚轮缩放 · 拖动移图 · 点击列车选择 · 长条列车 · 橙色公交 · 圆点客流（状态见图例）',foreground='#658098').pack(anchor='w',pady=(4,0))
 def selected_train():
  trains=[t for t in engine.trains.values() if t['line']==state['line'] and t['active']]
  if state['focus'] in engine.trains and engine.trains[state['focus']]['active']:return engine.trains[state['focus']]
  return trains[0] if trains else None
 def station_adapter():return StationAdapter(engine,state['line'],selected_train())
 def rounded(canvas,x0,y0,x1,y1,r=6,**kw):canvas.create_rectangle(x0,y0,x1,y1,**kw)
 def scroll_side(event,canvas):
  canvas.yview_scroll(-1 if event.delta>0 else 1,'units');return 'break'
 def bind_scroll(widget,canvas):
  if widget.winfo_class() not in ('Text','TCombobox','TSpinbox','TEntry','Treeview','TScrollbar'):
   widget.bind('<MouseWheel>',lambda event:scroll_side(event,canvas))
  for child in widget.winfo_children():bind_scroll(child,canvas)
 for scroll,content in scrollers:bind_scroll(content,scroll);scroll.bind('<MouseWheel>',lambda event,scroll=scroll:scroll_side(event,scroll))
 railshapes={lid:[edge.getShape() for edge in engine.net.getEdges() if edge.getID().startswith(f'L{lid}_') and 'Walk' not in edge.getID() and '_R' not in edge.getID()] for lid in LINE_IDS}
 busshapes=[edge.getShape() for edge in engine.net.getEdges() if edge.getID().startswith(('B01_','B02_','B03_','B04_')) and 'Walk' not in edge.getID()]
 coords=[pt for shapes in railshapes.values() for shape in shapes for pt in shape];xmin=min(p[0] for p in coords);xmax=max(p[0] for p in coords);ymin=min(p[1] for p in coords);ymax=max(p[1] for p in coords)
 def draw_map():
  cv=mapcanvas
  if mapmode.get()=='geo' and geo.data:
   state['map_signature']=None;geo.draw(cv,state,engine,LINES,hits);return
  geo.signature=None;w,h=cv.winfo_width(),cv.winfo_height();scale=min(max(1,w-95)/(xmax-xmin),max(1,h-100)/(ymax-ymin))*state['zoom'];ox=w/2-(xmin+xmax)*scale/2+state['pan'][0];oy=h/2+(ymin+ymax)*scale/2+state['pan'][1]
  def xy(x,y):return ox+x*scale,oy-y*scale
  signature=(w,h,state['zoom'],tuple(state['pan']),state['line'],id(engine.net))
  if signature!=state.get('map_signature'):
   model_layer.clear();cv.configure(bg='#101d2d');cv.delete('all');state['map_signature']=signature
   for lid,shapes in railshapes.items():
    for shape in shapes:
     if len(shape)>1:cv.create_line(*[v for p in shape for v in xy(*p)],fill=LINES[lid]['color'],width=3 if lid==state['line'] else 2,smooth=False)
   for shape in busshapes:
    if len(shape)>1:cv.create_line(*[v for p in shape for v in xy(*p)],fill='#37a79f',width=1,dash=(3,3))
   if getattr(engine,'mobility',None):
    for route in engine.mobility.bus_lines():
     point=route.get('community_point')
     if point:
      x,y=xy(*point);cv.create_rectangle(x-3,y-3,x+3,y+3,fill='#3ad6c6',outline='#c2f6ec');cv.create_text(x,y+11,text=f"{route['id']} 接驳",fill='#8ad6cd',font=('Microsoft YaHei UI',-10))
   for lid,stations in engine.stations.items():
    for s in stations:
     x,y=xy(s['x'],s['y']);r=2 if lid!=state['line'] else 3;cv.create_oval(x-r,y-r,x+r,y+r,fill='#142438' if s['stop_enabled'] else '#7b8191',outline=LINES[lid]['color'],width=1)
     if lid==state['line'] and (state['zoom']>1.5 or s['id'] in (1,len(stations))):cv.create_text(x+6,y-7,text=s['name'],fill='#d8e5ef',anchor='w',font=('Microsoft YaHei UI',-11))
     if 'depot_U' in s or 'depot_D' in s:
      dep=s.get('depot_U',s.get('depot_D'));shape=engine.net.getEdge(dep).getShape();dx,dy=xy(*shape[0]);cv.create_rectangle(dx-5,dy-5,dx+5,dy+5,fill='#b89755',outline='#ffe5ac');cv.create_text(dx,dy+11,text='发车区',fill='#ccb488',font=('Microsoft YaHei UI',-10))
   for name,hub in DATA['shared_stations'].items():
    if len(hub['members'])<2:continue
    x,y=xy(*hub['point']);cv.create_oval(x-6,y-6,x+6,y+6,fill='#152437',outline='#f5cb73',width=2)
    dx,dy,anchor={'湖滨东路':(-10,12,'e'),'体育中心':(-11,-8,'e'),'吕厝':(10,-4,'w'),'鼎美':(-10,5,'e'),'马銮中心':(10,-10,'w'),'火炬园':(-9,-9,'e')}.get(name,(9,4,'w'))
    cv.create_text(x+dx,y+dy,text=name+' '+ '/'.join(map(str,hub['members'])),anchor=anchor,fill='#f3d8a3',font=('Microsoft YaHei UI',-11))
   cv.create_text(18,18,text='五线联合铁路网',anchor='w',fill='#e7f1fb',font=('Microsoft YaHei UI',-17,'bold'));cv.create_text(18,43,text='1 · 2 · 3 · 4 · 6 号线   |   10 个换乘站   |   10 个端点发车区',anchor='w',fill='#93abc0',font=('Microsoft YaHei UI',-11))
   cv.create_text(w-16,h-15,text=('真实地图尚未下载 · 当前显示仿真示意' if mapmode.get()=='geo' else '轨道为模型位置 · 公交为模拟接驳 · 客流点 20 人'),anchor='e',fill='#8199ae',font=('Microsoft YaHei UI',-10))
  model_layer.begin();hits.clear()
  item=model_layer.item
  for vid,t in engine.trains.items():
   if not t['active']:continue
   x,y=xy(*t['position']);vehicle_symbol(item,('train',vid),'train',x,y,LINES[t['line']]['color'],vid==state['focus']);hits.append((x,y,vid))
  manager=getattr(engine,'mobility',None)
  if manager:
   snapshot=manager.snapshot()
   for b in snapshot.get('buses',[]):
    if not b.get('position'):continue
    x,y=xy(*b['position']);vehicle_symbol(item,('bus',b['id']),'bus',x,y,'#ffb454')
    if state['zoom']>1.5:item(('buslabel',b['id']),'text',(x+9,y),text=b['line'],anchor='w',fill='#ffce92',font=('Microsoft YaHei UI',-10))
   for group in snapshot.get('groups',[]):
    if not group.get('active') or not group.get('position'):continue
    x,y=xy(*group['position']);dx,dy=group_offset(group);person_symbol(item,('group',group['id']),group,x+dx,y+dy)
   if engine.conn and notebook.index(notebook.select())==2:
    for signal in engine.signal_list(state['line']):
     point=signal.get('position')
     if not point:continue
     x,y=xy(*point);color='#e87373' if 'r' in signal.get('state','').lower() else '#70d6a9'
     item(('signal',signal['id']),'oval',(x-2,y-2,x+2,y+2),fill=color,outline='#f0f6fa')
  model_layer.finish()
 def zoom(event):state['zoom']=max(.7,min(8,state['zoom']*(1.18 if event.delta>0 else 1/1.18)));redraw()
 def press(event):
  state['drag']=(event.x,event.y,list(state['pan']))
  if hits:
   x,y,vid=min(hits,key=lambda hit:math.hypot(event.x-hit[0],event.y-hit[1]))
   if math.hypot(event.x-x,event.y-y)<12:
    select(engine.trains[vid]['line']);state['focus']=vid;redraw()
 def drag(event):
  if 'drag' in state:x,y,pan=state['drag'];state['pan']=[pan[0]+event.x-x,pan[1]+event.y-y];redraw()
 mapcanvas.bind('<MouseWheel>',zoom);mapcanvas.bind('<ButtonPress-1>',press);mapcanvas.bind('<B1-Motion>',drag)
 def draw_station():
  cv=stationcanvas;w,h=cv.winfo_width(),cv.winfo_height();e=station_adapter();s=e.stations[state['station']];c=LINES[e.line_id];color=c['color'];scale=min((w-90)/300,1.8);center=(s['x'],s['y']);tx,ty=s['tangent'];nx,ny=-ty,tx
  def iso(u,v,z=0):return w/2+u*scale+v*.42*scale,h*.60+v*.46*scale-z*scale
  layer=['station_static']
  def polygon(points,fill,outline=''):
   cv.create_polygon(*[v for pt in points for v in iso(*pt)],fill=fill,outline=outline,width=1,tags=layer[0])
  def rect(a,b,low,high,z,fill,outline=''):polygon([(a,low,z),(b,low,z),(b,high,z),(a,high,z)],fill,outline)
  signature=(w,h,e.line_id,state['station'],s['stop_enabled'],id(engine.net))
  if signature!=state.get('station_signature'):
   cv.delete('all');state['station_signature']=signature
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
  cv.delete('station_live');layer[0]='station_live'
  def live(name,*args,**kwargs):kwargs['tags']='station_live';return getattr(cv,name)(*args,**kwargs)
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
      x,y=iso(bu+(fu-bu)*t,bv+(fv-bv)*t,4);live('create_rectangle',x-3,y-1,x+3,y+1,fill='#3c6480',outline='')
  caption=('列车进站 / 停靠' if visible else '站台展示 · 等候列车')+('   |   试乘方案跳停站' if not s['stop_enabled'] else '')
  live('create_text',w/2,h-15,text=caption+'   ·   雨棚 / 灯柱 / 座椅 / 花坛',fill='#9fb5c9',font=('Microsoft YaHei UI',-11))
 def put(variable,value):
  if variable.get()!=value:variable.set(value)
 def refresh_depots(event=None):
  rows=depotview.choices(state['line'] if depot_scope.get()=='本线两端' else None);previous=depot_choice.get();depot_names.clear();depot_names.update({d['id']:f"{d['line']}号线 · {d['terminal_station']}端 · {'上行' if d['direction']=='U' else '下行'}" for d in rows});depot_box.configure(values=list(depot_names.values()))
  if previous not in depot_names.values():depot_choice.set(next(iter(depot_names.values()),''))
  redraw()
 def chosen_depot_id():return next((key for key,value in depot_names.items() if value==depot_choice.get()),None)
 def draw_near():
  if near_mode.get()=='depot':state['station_signature']=None;depotview.draw(stationcanvas,chosen_depot_id(),engine,LINES)
  else:depotview.signature=None;draw_station()
 def switch_near():
  near_expanded.set(near_mode.get()=='depot');resize_near();state['station_signature']=None;depotview.signature=None;redraw()
 def redraw():
  state['frame_dirty']=True;state['metrics_dirty']=True
 def update_metrics():
  lid=state['line'];trains=[t for t in engine.trains.values() if t['line']==lid];active=[t for t in trains if t['active']];chosen=selected_train()
  values=tuple(t['id'] for t in active)
  if values!=state.get('train_values'):trainbox.configure(values=values);state['train_values']=values
  if chosen:
   if trainbox.get()!=chosen['id']:trainbox.set(chosen['id'])
   if follow.get():
    state['station']=chosen['next_station']
    if stationbox.current()!=state['station']-1:stationbox.current(state['station']-1)
   s=engine.stations[lid][chosen['next_station']-1];hold=f" · 发车时刻 {chosen['release']:.0f}s" if chosen['release'] else ''
   put(detail,f"{chosen['id']} · {'上行' if chosen['direction']=='U' else '下行'}\n{chosen['speed']*3.6:.1f} km/h · {'停站' if chosen['stop'] else '运行'}{hold}\n当前 / 前方站：{s['name']}")
  else:
   if trainbox.get():trainbox.set('')
   put(detail,'点击路网上的列车可查看运行状态')
  for line,b in tabs.items():
   n=sum(t['active'] and t['line']==line for t in engine.trains.values());values=(f'{line}号线 · {n}列',2 if line==lid else 0)
   if values!=state.get('tab_'+str(line)):b.configure(text=values[0],highlightthickness=values[1],highlightbackground='#426480');state['tab_'+str(line)]=values
  put(clock,f"共享时钟 {int(engine.time)//3600:02}:{int(engine.time)%3600//60:02}:{int(engine.time)%60:02}  ·  {'未启动' if not engine.conn else '暂停' if engine.paused else '运行'}  ·  目标 {rate.get()}× / 实际 {stepper.actual_rate:.1f}×")
  counts={d:sum(t['direction']==d for t in active) for d in 'UD'};departures=sum(x['line']==lid for x in engine.departures)
  put(fleet,f"{lid}号线：上行 {counts['U']} 列 · 下行 {counts['D']} 列\n待入轨 {len(trains)-len(active)} 列 · 端点发车 {departures} 次\n间隔 {engine.settings[lid]['headway']} 秒 · 车队上限 {engine.settings[lid]['cap']} 列")
  put(metric_vars['trains'],str(sum(t['active'] for t in engine.trains.values())))
  manager=getattr(engine,'mobility',None)
  if manager:
   stats=manager.stats();put(metric_vars['buses'],str(stats.get('bus_active',0)));put(metric_vars['people'],str(stats.get('people_total',0)));put(mobilityinfo,f"候车 / 步行 {stats.get('people_waiting',0)+stats.get('people_walking',0)} 人 · 乘车 {stats.get('people_onboard',0)} 人\n已到达 {stats.get('people_arrived',0)} 人 · 活跃客流点 {stats.get('groups_active',0)}")
   def minutes(value):return '暂无完成行程' if value is None else f'{value/60:.1f} 分钟'
   put(assessmentinfo,f"已到达 {stats.get('people_arrived',0)} / {stats.get('people_total',0)} 人\n平均行程 {minutes(stats.get('mean_journey_seconds'))}\n平均候车 {minutes(stats.get('mean_waiting_seconds'))}\n当前最长候车 {stats.get('longest_waiting_seconds',0)/60:.1f} 分钟")
  else:put(metric_vars['buses'],'0');put(metric_vars['people'],'0')
  if hasattr(engine,'signal_stats'):
   signal_stats=engine.signal_stats();put(metric_vars['signals'],f"{signal_stats.get('held',0)} / {signal_stats.get('total',0)}")
   if notebook.index(notebook.select())==2:
    records=engine.signal_list(lid if signal_scope.get()=='本线' else None);signal_rows.clear();signal_rows.update({str(r['id']):r for r in records});present=set(signal_tree.get_children());wanted=set(signal_rows)
    for sid in present-wanted:signal_tree.delete(sid)
    for sid,record in signal_rows.items():
     hold=record.get('mode') in ('hold','manual','red_hold','红灯保持');raw=record.get('state','');isred='r' in raw.lower();isgreen='g' in raw.lower();tag='hold' if hold else 'red' if isred and not isgreen else 'green';values=('红/绿' if isred and isgreen else '红' if isred else '绿' if isgreen else '—','保持' if hold else '待机' if record.get('mode')=='未启动' else '自动',record.get('occupied',0))
     if sid in present:
      if tuple(signal_tree.item(sid,'values'))!=tuple(str(v) for v in values) or tuple(signal_tree.item(sid,'tags'))!=(tag,):signal_tree.item(sid,values=values,tags=(tag,))
     else:signal_tree.insert('','end',iid=sid,text=sid,values=values,tags=(tag,))
    show_signal()
  put(info,'端点待发、站台折返、信号防护。换乘站连接各线站台，乘客步行换乘。4、6 号线保留试乘跳停方案。')
  pid=state.get('passenger')
  if pid in engine.passengers:p=engine.passengers[pid];put(passinfo,f"{pid} · {p['status']}\n已乘："+' → '.join(p['rides']))
  events='\n'.join(list(engine.events)[-5:])
  if events!=state.get('events'):eventbox.configure(state='normal');eventbox.delete('1.0','end');eventbox.insert('end',events);eventbox.configure(state='disabled');state['events']=events
  selected_depot=next((d for d in depotview.depots if depot_names.get(d['id'])==depot_choice.get()),None)
  if selected_depot:
   prefix=selected_depot['id'];actual_count=sum(t['active'] and (t.get('edge','').startswith(prefix+'_') or t.get('edge','').startswith(':'+prefix)) for t in engine.trains.values());put(depotinfo,f"{selected_depot['terminal_station']}端 · {len(selected_depot.get('tracks',[]))} 股存车轨\n实际在段 {actual_count} 列 · 出入段信号防护")
 def render_now(force=False):
  now=time.perf_counter();model_changed=state['last_model_time']!=engine.time
  if force or state['metrics_dirty'] or now-state['last_metrics']>=.5:
   if force or state['metrics_dirty'] or model_changed or (engine.conn and not engine.paused):
    start=time.perf_counter();update_metrics()
    if measurements.active:measurements.metrics.append((time.perf_counter()-start)*1000)
   state['last_metrics']=now;state['metrics_dirty']=False
  if force or ((state['frame_dirty'] or model_changed) and now-state['last_frame']>=.05):
   start=time.perf_counter();draw_map();middle=time.perf_counter()
   if force or state['frame_dirty'] or now-state.get('last_near',0)>=.1:draw_near();state['last_near']=now
   end=time.perf_counter()
   if measurements.active:measurements.map_frames.append((middle-start)*1000);measurements.near_frames.append((end-middle)*1000);measurements.frames.append((end-start)*1000)
   root.after_idle(lambda start=start:measurements.paint_ms.append((time.perf_counter()-start)*1000))
   state['last_frame']=end;state['last_model_time']=engine.time;state['frame_dirty']=False
 def tick():
  callback_start=time.perf_counter()
  try:stepper.advance(engine,rate.get());render_now()
  except Exception as exc:engine.paused=True;logging.exception('simulation');messagebox.showerror('仿真提示',str(exc),parent=root)
  if not state.get('closing'):root.after(max(1,int(10-(time.perf_counter()-callback_start)*1000)),tick)
 root._scheduler=stepper;root._ui_measurements=measurements;root._simulation_clock_reset=lambda:stepper.reset(engine)
 root.bind('<<SimulationClockReset>>',lambda e:root._simulation_clock_reset())
 def close():
  if state.get('closing'):return
  state['closing']=True
  try:engine.close()
  finally:root.destroy()
 root.protocol('WM_DELETE_WINDOW',close);mapcanvas.bind('<Configure>',lambda e:redraw());stationcanvas.bind('<Configure>',lambda e:redraw());scopebox.bind('<<ComboboxSelected>>',lambda e:redraw());notebook.bind('<<NotebookTabChanged>>',lambda e:redraw());depot_scopebox.bind('<<ComboboxSelected>>',refresh_depots);depot_box.bind('<<ComboboxSelected>>',lambda e:(near_mode.set('depot'),switch_near()));select(1);plan()
 def resize_near(event=None):
  height=min(360,int(root.winfo_height()*.35)) if near_expanded.get() else 160 if root.winfo_height()>=900 else 130
  if int(stationcanvas.cget('height'))!=height:stationcanvas.configure(height=height)
 root.bind('<Configure>',lambda e:resize_near() if e.widget is root else None,add='+')
 requested_start=os.environ.get('XIAMEN_UI_TAB','')
 if requested_start=='depot':near_mode.set('depot');switch_near()
 elif requested_start in panels:notebook.select(list(panels).index(requested_start))
 if bus_names:show_bus()
 update_realbus()
 root.update_idletasks();(ROOT/'logs/ready.json').write_text(json.dumps({'pid':os.getpid(),'title':TITLE,'ready':True,'time':time.time()},ensure_ascii=False),encoding='utf-8')
 root.after(20,tick)
 if os.environ.get('XIAMEN_UI_SMOKE')=='1':
  def smoke_report():
   root.update_idletasks();render_now(True);report={'title':TITLE,'map_available':bool(geo.data),'mode':mapmode.get(),'map_summary':geo.summary(),'tabs':[notebook.tab(i,'text') for i in range(notebook.index('end'))],'bus_lines':list(bus_names),'real_bus_catalogue_count':len(geo.bus_routes),'signal_count':engine.signal_stats()['total'],'visible_signal_rows':len(signal_tree.get_children()),'window':[root.winfo_width(),root.winfo_height()],'sidebar_width':sidebar.winfo_width(),'map_size':[mapcanvas.winfo_width(),mapcanvas.winfo_height()],'near_size':[stationcanvas.winfo_width(),stationcanvas.winfo_height()],'body_size':[body.winfo_width(),body.winfo_height()],'mobility_available':getattr(engine,'mobility',None) is not None,'metrics':{k:v.get() for k,v in metric_vars.items()},'near_mode':near_mode.get(),'depot_count':len(depotview.depots),'depot_visible_trains':depotview.visible_trains,'scheduler':stepper.report()}
   (ROOT/'logs/ui-smoke.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf-8')
   if os.environ.get('XIAMEN_UI_CAPTURE'):
    from ui_capture import capture_window
    capture_window(root,os.environ['XIAMEN_UI_CAPTURE'])
  root.after(1200,smoke_report)
  root.after(int(float(os.environ.get('XIAMEN_UI_SMOKE_SECONDS','15'))*1000),close)
 if os.environ.get('XIAMEN_GUI_TEST')=='1' and os.environ.get('XIAMEN_UI_PERF_TEST')!='1':
  def demo():
   if os.environ.get('XIAMEN_UI_TAB')=='depot':engine.set_headway(1,60)
   engine.start_all();pid=engine.add_passenger('镇海路','人才中心');state['passenger']=pid
   if getattr(engine,'mobility',None):engine.mobility.start_buses();engine.mobility.add_group(grouporigin.get(),groupdestination.get(),100)
   for _ in range(200 if os.environ.get('XIAMEN_UI_TAB')=='depot' else 1900):engine.step()
   engine.paused=True
   chosen=next((t for t in engine.trains.values() if t['active'] and t['stop'] and engine.stations[t['line']][t['station']-1]['interchange_lines']),None)
   if chosen:select(chosen['line']);state['focus']=chosen['id'];state['station']=chosen['station'];follow.set(False);stationbox.current(chosen['station']-1)
   else:select(3);state['station']=2;follow.set(False);stationbox.current(1)
   redraw()
   requested=os.environ.get('XIAMEN_UI_TAB','')
   if requested in panels:notebook.select(list(panels).index(requested))
   if requested=='depot':
    depotview.reload(engine);depot_scope.set('全网十段');refresh_depots();near_mode.set('depot');switch_near();yard_edges={t['edge']:d for d in depotview.depots for t in d.get('tracks',[])}
    in_yard=next((t for t in engine.trains.values() if t['active'] and (t.get('edge') in yard_edges or any(t.get('edge','').startswith(d['id']+'_') or t.get('edge','').startswith(':'+d['id']) for d in depotview.depots))),None)
    if in_yard:
     depot=yard_edges.get(in_yard['edge']) or next(d for d in depotview.depots if in_yard['edge'].startswith(d['id']+'_') or in_yard['edge'].startswith(':'+d['id']));select(in_yard['line']);state['focus']=in_yard['id'];depot_choice.set(depot_names[depot['id']]);follow.set(False)
   render_now(True)
   if requested=='signals' and signal_tree.get_children():
    sid=signal_tree.get_children()[0];signal_tree.selection_set(sid);signal_tree.focus(sid);engine.hold_signal(sid,60);redraw()
   if requested=='map':locate_realbus()
   render_now(True);(ROOT/'logs/gui-test-ready.json').write_text(json.dumps({'pid':os.getpid(),'trains':len(engine.trains),'passenger':engine.passengers[pid],'tab':requested,'mobility':engine.mobility.stats() if engine.mobility else None,'signals':engine.signal_stats(),'depot_id':chosen_depot_id(),'depot_visible_trains':depotview.visible_trains},ensure_ascii=False),encoding='utf-8')
  root.after(1000,lambda:safe(demo))
 if os.environ.get('XIAMEN_UI_PERF_TEST')=='1':
  phase_seconds=max(3,float(os.environ.get('XIAMEN_UI_PERF_SECONDS','24'))/2);heartbeat_due=[0.]
  def heartbeat():
   now=time.perf_counter()
   if measurements.active:measurements.heartbeat.append(max(0,(now-heartbeat_due[0])*1000))
   heartbeat_due[0]=now+.03
   if not state.get('closing'):root.after(30,heartbeat)
  def perf_finish_phase():
   measurements.finish_phase(engine,stepper)
   if len(measurements.phases)==1:
    rate.set(100);stepper.reset(engine);measurements.begin_phase(100,engine,stepper);root.after(int(phase_seconds*1000),perf_finish_phase)
   else:
    report=measurements.report(engine,stepper);measurements.active=False;engine.paused=True;(ROOT/'logs/ui-performance-4.1.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');close()
  def perf_begin():
   engine.start_all();manager=getattr(engine,'mobility',None)
   if manager:
    manager.start_buses();communities=[r['community_name'] for r in manager.bus_lines()]
    if len(communities)>1:manager.add_group(communities[0],communities[1],200)
    manager.set_demand_enabled(True)
   rate.set(20);stepper.reset(engine);measurements.paint_ms.clear();measurements.begin_phase(20,engine,stepper);heartbeat_due[0]=time.perf_counter()+.03;root.after(30,heartbeat);root.after(int(phase_seconds*1000),perf_finish_phase)
  root.after(500,lambda:safe(perf_begin))
 release_timer=acquire_timer_resolution()
 try:root.mainloop()
 finally:release_timer()
