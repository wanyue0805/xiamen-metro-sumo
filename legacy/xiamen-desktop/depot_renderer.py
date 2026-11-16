"""Cached isometric depot scenery with live trains projected from SUMO XY."""
import json
import math
from pathlib import Path


class DepotRenderer:
    def __init__(self,root):
        self.root=Path(root);self.depots=[];self.signature=None;self.source_mtime=None
        self.visible_trains=[]

    def reload(self,engine):
        self.visible_trains=[]
        path=self.root/'network/depot.catalogue.json'
        if path.exists():
            self.depots=json.loads(path.read_text(encoding='utf-8')).get('depots',[])
            self.source_mtime=path.stat().st_mtime_ns
        else:
            self.depots=[]
            for lid,stations in engine.stations.items():
                for direction,station in [('U',stations[0]),('D',stations[-1])]:
                    edge_id=station.get('depot_'+direction)
                    if not edge_id:continue
                    shape=engine.net.getEdge(edge_id).getShape();a,b=shape[0],shape[-1]
                    length=max(.001,math.dist(a,b));tangent=[(b[i]-a[i])/length for i in range(2)]
                    self.depots.append({'id':f'L{lid}_Y{direction}','line':lid,'direction':direction,
                        'terminal_station':station['name'],'base':list(a),'tangent':tangent,
                        'tracks':[{'id':'T01','edge':edge_id,'shape':shape}],
                        'entry':{'edge':edge_id},'exit':{'edge':edge_id},'geometry':{}})
        self.signature=None;return self.depots

    def choices(self,line=None):
        return [d for d in self.depots if line is None or int(d['line'])==int(line)]

    def draw(self,cv,depot_id,engine,lines):
        depot=next((d for d in self.depots if d['id']==depot_id),self.depots[0] if self.depots else None)
        if not depot:
            cv.delete('all');cv.create_text(25,25,anchor='nw',text='车辆段资料尚未生成',fill='#a8c1d4');return
        w,h=cv.winfo_width(),cv.winfo_height();base=depot['base'];tx,ty=depot['tangent'];length=max(.001,math.hypot(tx,ty));tx/=length;ty/=length;nx,ny=-ty,tx
        def local(p):return (p[0]-base[0])*tx+(p[1]-base[1])*ty,(p[0]-base[0])*nx+(p[1]-base[1])*ny
        geometry=depot.get('geometry',{});tracks=depot.get('tracks',[])
        shapes=[]
        for track in tracks:
            shape=track.get('shape')
            if not shape and engine.net.hasEdge(track['edge']):shape=engine.net.getEdge(track['edge']).getShape()
            if shape:shapes.append((track,[local(p) for p in shape]))
        facilities=geometry.get('facilities',[])
        allpoints=[p for _,shape in shapes for p in shape]
        for f in facilities:allpoints.extend(local(p) for p in f.get('polygon',[]))
        perimeter=geometry.get('perimeter',[])
        allpoints.extend(local(p) for p in perimeter)
        if not allpoints:allpoints=[(0,0),(350,80)]
        u0=min(p[0] for p in allpoints)-35;u1=max(p[0] for p in allpoints)+35;v0=min(p[1] for p in allpoints)-35;v1=max(p[1] for p in allpoints)+45
        if not facilities:v0=min(v0,-70);v1=max(v1,90)
        raw=[(u+v*.38,v*.55-u*.07) for u,v in [(u0,v0),(u0,v1),(u1,v0),(u1,v1)]]
        rx0,rx1=min(p[0] for p in raw),max(p[0] for p in raw);ry0,ry1=min(p[1] for p in raw),max(p[1] for p in raw)
        scale=min(max(1,w-85)/max(1,rx1-rx0),max(1,h-82)/max(1,ry1-ry0),2.5)
        ox=w/2-(rx0+rx1)*scale/2;oy=(h+35)/2-(ry0+ry1)*scale/2
        def iso(u,v,z=0):return ox+(u+v*.38)*scale,oy+(v*.55-u*.07-z)*scale
        def xy(p,z=0):return iso(*local(p),z)
        def polygon(points,fill,outline='',z=0,tags='depot_static'):
            cv.create_polygon(*[c for p in points for c in iso(*p,z)],fill=fill,outline=outline,tags=tags)
        def rect(a,b,low,high,fill,outline='',z=0):polygon([(a,low),(b,low),(b,high),(a,high)],fill,outline,z)
        signature=(w,h,depot['id'],self.source_mtime,id(engine.net))
        if signature!=self.signature:
            cv.delete('all');cv.configure(bg='#152637');self.signature=signature
            rect(u0,u1,v0,v1,'#273947','#4e6578')
            # Perimeter roads, marked maintenance access and fence posts.
            rect(u0+8,u1-8,v1-18,v1-7,'#40515d')
            for u in range(int(u0+12),int(u1-10),22):
                a,b=iso(u,v1-12),iso(u+8,v1-12);cv.create_line(*a,*b,fill='#c4ba87',width=1,tags='depot_static')
            border=[(u0,v0),(u1,v0),(u1,v1),(u0,v1),(u0,v0)]
            cv.create_line(*[c for p in border for c in iso(*p,1)],fill='#7a8f9f',width=1,tags='depot_static')
            for u in range(int(u0),int(u1)+1,35):
                for v in (v0,v1):a,b=iso(u,v),iso(u,v,5);cv.create_line(*a,*b,fill='#6b8194',width=1,tags='depot_static')
            for index,(track,shape) in enumerate(shapes,1):
                if len(shape)<2:continue
                flat=[c for p in shape for c in iso(*p)];cv.create_line(*flat,fill='#596d7c',width=max(3,4*scale),tags='depot_static')
                for off in (-.85,.85):cv.create_line(*[c for u,v in shape for c in iso(u,v+off,.25)],fill='#c9d7df',width=1,tags='depot_static')
                a,b=shape[0],shape[-1];dist=math.dist(a,b)
                for k in range(0,int(dist),12):
                    t=k/max(1,dist);u=a[0]+(b[0]-a[0])*t;v=a[1]+(b[1]-a[1])*t;p,q=iso(u,v-2),iso(u,v+2);cv.create_line(*p,*q,fill='#738896',width=1,tags='depot_static')
                x,y=iso(*a);cv.create_text(x-9,y,text=f'{index:02}',anchor='e',fill='#f3d49b',font=('Segoe UI',-10,'bold'),tags='depot_static')
                # Painted capacity slots are scenery, with no synthetic trains.
                slots=max(1,int(track.get('capacity_trains',1)))
                for slot in range(slots):
                    p=.2+.6*(slot+.5)/slots;u=a[0]+(b[0]-a[0])*p;v=a[1]+(b[1]-a[1])*p;px,py=iso(u,v+5);cv.create_text(px,py,text=f'{index:02}-{slot+1}',fill='#8fa9b9',font=('Segoe UI',-8),tags='depot_static')
            if not facilities:
                facilities=[{'kind':'maintenance','label':'检修棚','local_polygon':[(u0+40,v0+6),(u0+145,v0+6),(u0+145,v0+30),(u0+40,v0+30)]},
                    {'kind':'wash','label':'洗车线','local_polygon':[(u1-100,v0+6),(u1-35,v0+6),(u1-35,v0+25),(u1-100,v0+25)]},
                    {'kind':'office','label':'调度楼','local_polygon':[(u1-70,v1-40),(u1-25,v1-40),(u1-25,v1-21),(u1-70,v1-21)]}]
            for f in facilities:
                points=f.get('local_polygon') or [local(p) for p in f.get('polygon',[])]
                if len(points)>3 and points[0]==points[-1]:points=points[:-1]
                if len(points)<3:continue
                kind=f.get('kind','maintenance');z=12 if kind in ('office','control','dispatch') else 6 if kind in ('wash','washing') else 9
                for a,b in zip(points,points[1:]+points[:1]):
                    cv.create_polygon(*iso(*a),*iso(*b),*iso(*b,z),*iso(*a,z),fill='#4b6375',outline='#748d9e',tags='depot_static')
                    p,q=iso(*a),iso(*a,z);cv.create_line(*p,*q,fill='#829cab',width=1,tags='depot_static')
                polygon(points,'#647b8b','#a8bbc5',z=z)
                # Roof ribs, ventilation equipment and glazed workshop doors
                # provide structure without adding any parked vehicle objects.
                a,b=points[0],points[1]
                for fraction in (.2,.4,.6,.8):
                    u=a[0]+(b[0]-a[0])*fraction;v=a[1]+(b[1]-a[1])*fraction;p,q=iso(u,v,z+.2),iso(u+3,v+5,z+.2);cv.create_line(*p,*q,fill='#8fa5b3',width=1,tags='depot_static')
                if kind in ('dispatch','office','control'):
                    for fraction in (.15,.35,.55,.75):
                        u=a[0]+(b[0]-a[0])*fraction;v=a[1]+(b[1]-a[1])*fraction;p,q=iso(u,v,z*.6),iso(u+5,v,z*.6);cv.create_line(*p,*q,fill='#87c4d3',width=max(1,2*scale),tags='depot_static')
                elif kind in ('maintenance','storage','wash'):
                    p,q=iso(*points[1],z*.4),iso(*points[2],z*.4);cv.create_line(*p,*q,fill='#24485d',width=max(2,4*scale),tags='depot_static')
                center=(sum(p[0] for p in points)/len(points),sum(p[1] for p in points)/len(points));x,y=iso(*center,z+3)
                cv.create_text(x,y,text=f.get('label',{'office':'调度楼','wash':'洗车线'}.get(kind,'检修棚')),fill='#e9f2f8',font=('Microsoft YaHei UI',-10),tags='depot_static')
                if kind in ('maintenance','shed','wash','washing'):
                    for a in points[:2]:p,q=iso(*a,z),iso(a[0]+4,a[1],z);cv.create_line(*p,*q,fill=lines[depot['line']]['color'],width=2,tags='depot_static')
            for u in range(int(u0+25),int(u1-20),90):
                p,q=iso(u,v1-24),iso(u,v1-24,10);cv.create_line(*p,*q,fill='#bdcbd4',width=1,tags='depot_static');x,y=q;cv.create_oval(x-2,y-2,x+2,y+2,fill='#fff3c2',outline='',tags='depot_static')
            cv.create_text(17,18,text=f"车辆段近景 · {depot['terminal_station']}端 / {depot['line']}号线",anchor='w',fill='#edf5fb',font=('Microsoft YaHei UI',-15,'bold'),tags='depot_static')
            cv.create_text(w-16,18,text=f'{len(tracks)} 股道 · 停车位编号',anchor='e',fill='#8caabe',font=('Microsoft YaHei UI',-10),tags='depot_static')
        cv.delete('depot_live');self.visible_trains=[]
        edge_ids={t['edge'] for t in tracks}|{d.get('edge','') for d in (depot.get('entry',{}),depot.get('exit',{}))}
        for vid,train in engine.trains.items():
            if not train.get('active') or train.get('line')!=depot['line']:continue
            u,v=local(train['position']);in_yard=train.get('edge') in edge_ids or train.get('edge','').startswith(depot['id']+'_') or train.get('edge','').startswith(':'+depot['id'])
            if not in_yard or not (u0-10<=u<=u1+10 and v0-10<=v<=v1+10):continue
            self.visible_trains.append(vid)
            for car in reversed(range(lines[depot['line']]['cars'])):
                a=engine.point_behind(train,car*20+1);b=engine.point_behind(train,car*20+19);au,av=local(a);bu,bv=local(b)
                if not (u0-20<=au<=u1+20 and v0-20<=av<=v1+20):continue
                polygon([(bu,bv-1.6),(au,av-1.6),(au,av+1.6),(bu,bv+1.6)],lines[depot['line']]['color'] if car==0 else '#dce7ee','#eff7fc',z=3,tags='depot_live')
                a,b=iso(au,av,4),iso(bu,bv,4);cv.create_line(*a,*b,fill='#385e77',width=2,tags='depot_live')
            x,y=iso(u,v,9);cv.create_text(x,y,text=vid,fill='#d6eef9',font=('Segoe UI',-9),tags='depot_live')
        signals={s['id']:s for s in engine.signal_list(depot['line'])} if hasattr(engine,'signal_list') else {}
        for index,gate in enumerate((depot.get('entry',{}),depot.get('exit',{}))):
            record=signals.get(gate.get('signal'));shape=None
            if gate.get('edge') and engine.net.hasEdge(gate['edge']):shape=engine.net.getEdge(gate['edge']).getShape()
            point=(shape[-1] if index==0 else shape[0]) if shape else base;x,y=xy(point,7)
            raw=record.get('state','') if record else '';color='#ed8582' if raw and set(raw.lower())=={'r'} else '#73ceab' if 'g' in raw.lower() else '#708999'
            cv.create_oval(x-3,y-3,x+3,y+3,fill=color,outline='#d7e6ed',tags='depot_live');cv.create_text(x+6,y,text='入段' if index==0 else '出段',anchor='w',fill='#a8c3d6',font=('Microsoft YaHei UI',-9),tags='depot_live')
        cv.create_text(16,h-14,anchor='w',text=f'实际在段列车 {len(self.visible_trains)} 列 · 设施为场景布置，列车与信号来自实时仿真',fill='#91adbf',font=('Microsoft YaHei UI',-10),tags='depot_live')
