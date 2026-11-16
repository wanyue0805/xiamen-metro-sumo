"""Offline OSM vector basemap for the existing Tkinter dispatch panel."""
from pathlib import Path
import json, math, re, logging
from map_symbols import vehicle_symbol,person_symbol,group_offset
try:
    from PIL import Image,ImageDraw,ImageTk
except ImportError:
    Image=ImageDraw=ImageTk=None

class GeoMap:
    TRAIN_MAPPING_VERSION="physical-edge-20261021"
    def __init__(self, root):
        self.root=Path(root);self.data=None;self.signature=None;self.bounds=None;self.bus_routes=[]
        self.features_by_kind={};self._bus_by_id={};self._bus_geometry={};self._edge_geometry={};self._dynamic={};self._station_models={}
        self._basemap_photo=None;self._raster_signature=None;self._geo_network=None;self._train_edge_maps={}
        try:self.reload()
        except (OSError,ValueError,KeyError,TypeError):
            self.data=None;logging.exception('Cannot load map cache; schematic view remains available')

    def reload(self):
        bus_path=self.root/'maps/osm/bus_catalogue.json'
        if bus_path.exists():
            self.bus_routes=json.loads(bus_path.read_text(encoding='utf-8')).get('routes',[])
            if isinstance(self.bus_routes,dict):self.bus_routes=list(self.bus_routes.values())
        self._bus_by_id={str(route['id']):route for route in self.bus_routes}
        self._bus_geometry={}
        for route in self.bus_routes:
            shapes=[]
            for shape in route.get('shapes_wgs84',[]):
                points=[self.project(*point) for point in shape]
                if len(points)>1:shapes.append((points,self.feature_bounds(points)))
            stops=[(stop,self.project(stop['lon'],stop['lat'])) for stop in route.get('stops',[])
                   if stop.get('lon') is not None and stop.get('lat') is not None]
            self._bus_geometry[str(route['id'])]=(shapes,stops)
        path=self.root/'maps/osm/map.json'
        if path.exists():
            candidate=json.loads(path.read_text(encoding='utf-8'))
            if not candidate.get('stations') or not candidate.get('features'):
                raise ValueError('地图缓存缺少站点或几何数据')
            points=[s['point'] for s in candidate['stations'].values()]
            if any(len(p)!=2 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in p) for p in points):
                raise ValueError('站点坐标缓存无效')
            if not candidate.get('report',{}).get('station_coverage'):raise ValueError('地图缺少覆盖报告')
            self.data=candidate
            self.features_by_kind={kind:[] for kind in ('land','water','green','coast','road','future_rail','rail')}
            for feature in candidate['features']:
                if len(feature.get('points',[]))<2:continue
                feature['_bounds']=self.feature_bounds(feature['points'])
                self.features_by_kind.setdefault(feature['kind'],[]).append(feature)
            self.bounds=(min(p[0] for p in points)-1500,max(p[0] for p in points)+1500,
                         min(p[1] for p in points)-1500,max(p[1] for p in points)+1500)
            self.way_lines={}
            for rel in self.data['report']['subway_relations']:
                match=re.search(r'(?:Line\s*|地铁)?([12346])(?:号线|\b)',rel['name']+' '+rel['ref'],re.I)
                if match:
                    for way in rel['way_ids']:self.way_lines[way]=int(match.group(1))
        self.signature=None
        self._edge_geometry.clear();self._dynamic.clear();self._station_models.clear();self._train_edge_maps.clear();self._geo_network=None
        self._raster_signature=None;self._basemap_photo=None
        return bool(self.data)

    def summary(self):
        if not self.data:return '真实地图尚未下载 · 联合仿真仍可使用'
        cov=self.data['report']['station_coverage']
        matched=sum(v['matched'] for v in cov.values());total=sum(v['total'] for v in cov.values())
        suffix=' · 道路部分覆盖' if self.data['report'].get('layers',{}).get('roads',{}).get('partial') else ''
        return f'OSM 地理底图 · {matched}/{total} 个线路站点有坐标'+suffix

    @staticmethod
    def project(lon,lat):
        return (lon-118.15)*111320*math.cos(math.radians(24.60)),(lat-24.60)*111320

    def selected_bus(self,state):
        return self._bus_by_id.get(str(state.get('osm_bus_id')))

    @staticmethod
    def feature_bounds(points):
        return min(p[0] for p in points),max(p[0] for p in points),min(p[1] for p in points),max(p[1] for p in points)

    @staticmethod
    def overlaps(bounds,viewport):
        return not (bounds[1]<viewport[0] or bounds[0]>viewport[1] or bounds[3]<viewport[2] or bounds[2]>viewport[3])

    @staticmethod
    def edge_fraction(shape, position):
        total=sum(math.dist(a,b) for a,b in zip(shape,shape[1:]))
        if not total:return 0
        best=(float('inf'),0);walked=0
        for a,b in zip(shape,shape[1:]):
            dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
            if not length:continue
            t=max(0,min(1,((position[0]-a[0])*dx+(position[1]-a[1])*dy)/length**2))
            distance=math.hypot(position[0]-a[0]-t*dx,position[1]-a[1]-t*dy)
            if distance<best[0]:best=(distance,(walked+t*length)/total)
            walked+=length
        return best[1]

    @staticmethod
    def _rail_node_station(node, line, count):
        """Decode physical node ownership, never the last passenger stop."""
        prefix=f'L{line}_'
        if not node.startswith(prefix):return None
        name=node[len(prefix):]
        platform=re.fullmatch(r'[UD](\d+)[ab]',name)
        if platform:
            index=int(platform.group(1))
            return index if 1<=index<=count else None
        # Depot geometry belongs to the corresponding terminal. Its position
        # stays schematic on the geographic view, as in the existing legend.
        if name=='DepotU' or name.startswith('YU_'):return 1
        if name=='DepotD' or name.startswith('YD_'):return count
        return None

    def _train_edge_map(self, train, engine):
        if engine.net is not self._geo_network:
            self._geo_network=engine.net;self._train_edge_maps.clear()
        edge_id=train.get('edge','');lid=train['line'];key=(lid,edge_id)
        if key in self._train_edge_maps:return self._train_edge_maps[key]
        stations=engine.stations[lid]
        try:edge=engine.net.getEdge(edge_id)
        except KeyError:return None  # First subscription has no position yet.
        first=self._rail_node_station(edge.getFromNode().getID(),lid,len(stations))
        last=self._rail_node_station(edge.getToNode().getID(),lid,len(stations))
        if first is None or last is None:return None
        a=self.data['stations'].get(stations[first-1]['name'],{}).get('point')
        b=self.data['stations'].get(stations[last-1]['name'],{}).get('point')
        if a is None or b is None:return None
        mapping=(a,b,max(.001,edge.getLength()))
        self._train_edge_maps[key]=mapping
        return mapping

    def train_point(self, train, engine):
        """Map current physical edge endpoints, including internal junctions.

        GU/GD and terminal connectors interpolate between the actual two
        stations. Platforms, turnbacks and their internal lanes are anchored
        to their own station even during approach, pass-through or skipping.
        train['station'] is historical service state and is never a position.
        """
        if not self.data:return None
        mapping=self._train_edge_map(train,engine)
        if mapping is None:return None
        a,b,length=mapping
        if a==b:return tuple(a)
        lane_position=train.get('lane_position')
        if lane_position is None:
            fraction=self.edge_fraction(engine.net.getEdge(train['edge']).getShape(),train['position'])
        else:
            fraction=max(0,min(1,float(lane_position)/length))
        return tuple(x+(y-x)*fraction for x,y in zip(a,b))

    def station_model_point(self, name, engine):
        key=(id(engine),name)
        if key in self._station_models:return self._station_models[key]
        members=engine.by_name.get(name,[])
        if not members:return None
        lid,index=members[0];station=engine.stations[lid][index-1]
        self._station_models[key]=(station['x'],station['y'])
        return self._station_models[key]

    def feeder_point(self, position, hub, engine):
        """Anchor model feeder roads at the matching OSM station, in meters."""
        station=self.data['stations'].get(hub);model=self.station_model_point(hub,engine)
        if not station or not model or not position:return None
        return tuple(station['point'][i]+position[i]-model[i] for i in range(2))

    def crowd_point(self, group, engine, buses):
        if group.get('geo_point'):return group['geo_point']
        vehicle=group.get('vehicle')
        if vehicle in engine.trains:return self.train_point(engine.trains[vehicle],engine)
        if vehicle in buses:
            bus=buses[vehicle]
            return self.feeder_point(bus.get('position'),bus.get('hub'),engine)
        station=group.get('station')
        if isinstance(station,(list,tuple)) and len(station)==2:
            lid,index=station
            station=engine.stations[int(lid)][int(index)-1]['name']
        if station in self.data['stations']:
            return self.feeder_point(group.get('position'),station,engine) or self.data['stations'][station]['point']
        manager=getattr(engine,'mobility',None)
        if manager:
            for route in manager.bus_lines():
                if route.get('community_name') in (group.get('origin'),group.get('destination')):
                    return self.feeder_point(group.get('position'),route.get('metro_hub'),engine)
        return None

    def draw(self, cv, state, engine, lines, hits):
        if not self.data:return
        w,h=cv.winfo_width(),cv.winfo_height();xmin,xmax,ymin,ymax=self.bounds
        scale=min(max(1,w-70)/(xmax-xmin),max(1,h-130)/(ymax-ymin))*state['zoom']
        ox=w/2-(xmin+xmax)*scale/2+state['pan'][0]
        oy=(h+45)/2+(ymin+ymax)*scale/2+state['pan'][1]
        def xy(p):return ox+p[0]*scale,oy-p[1]*scale
        viewport=((0-ox)/scale,(w-ox)/scale,(oy-h)/scale,(oy-60)/scale)
        signature=(id(cv),w,h,state['zoom'],tuple(state['pan']),state['line'],state.get('show_osm_bus',False),state.get('osm_bus_id'))
        if signature!=self.signature:
            cv.delete('all');self.signature=signature
            self._dynamic.clear()
            cv.configure(bg='#10283b')
            # Thousands of unchanged map vectors otherwise get repainted by
            # Tk whenever a train point moves. Cache those geographic layers
            # as one image; labels and live objects remain native canvas items.
            raster_key=(id(cv),w,h,state['zoom'],tuple(state['pan']),state['line'])
            raster_enabled=Image is not None
            paint=None
            if raster_enabled and raster_key!=self._raster_signature:
                bitmap=Image.new('RGB',(max(1,w),max(1,h)),'#10283b');paint=ImageDraw.Draw(bitmap)
                for x in range(0,w,64):paint.line((x,0,x,h),fill='#153247')
                for y in range(0,h,64):paint.line((0,y,w,y),fill='#153247')
            elif not raster_enabled:
                for x in range(0,w,64):cv.create_line(x,0,x,h,fill='#153247')
                for y in range(0,h,64):cv.create_line(0,y,w,y,fill='#153247')
            if paint is not None or not raster_enabled:
                for kind in ('land','water','green','coast','road','future_rail','rail'):
                    for f in self.features_by_kind.get(kind,()):
                        if not self.overlaps(f['_bounds'],viewport):continue
                        if kind=='road' and f.get('highway') and state['zoom']<=1.4 and f['highway'] not in ('motorway','motorway_link','trunk','trunk_link','primary','primary_link','secondary','secondary_link'):continue
                        model=f['points'];simplified=[model[0]];spacing=1.8/scale
                        for point in model[1:-1]:
                            if math.dist(simplified[-1],point)>spacing:simplified.append(point)
                        simplified.append(model[-1]);points=[xy(point) for point in simplified]
                        if kind in ('land','water','green') and f['closed']:
                            color={'land':'#1b3542','water':'#123e54','green':'#163c38'}[kind]
                            if paint is not None:paint.polygon(points,fill=color)
                            else:cv.create_polygon(*[value for point in points for value in point],fill=color,outline='')
                        else:
                            lid=self.way_lines.get(f['id']) if kind=='rail' else None
                            color=lines[lid]['color'] if lid in lines else {'coast':'#4e8799','road':'#385b6b' if f.get('highway') in ('motorway','trunk','primary') else '#2a4858','rail':'#6c8c9b','future_rail':'#698492','water':'#246075','green':'#24584c','land':'#1b3542'}[kind]
                            width=2.5 if lid==state['line'] else 1
                            if paint is not None:
                                if kind=='future_rail':
                                    for a,b in zip(points,points[1:]):
                                        length=math.dist(a,b)
                                        if not length:continue
                                        for start in range(0,math.ceil(length),6):
                                            end=min(length,start+2)
                                            piece=[tuple(a[k]+(b[k]-a[k])*offset/length for k in (0,1)) for offset in (start,end)]
                                            paint.line(piece,fill=color,width=1)
                                else:paint.line(points,fill=color,width=max(1,round(width)))
                            else:cv.create_line(*[value for point in points for value in point],fill=color,width=width,dash=(2,4) if kind=='future_rail' else ())
            if raster_enabled:
                if paint is not None:self._basemap_photo=ImageTk.PhotoImage(bitmap,master=cv);self._raster_signature=raster_key
                cv.create_image(0,0,anchor='nw',image=self._basemap_photo,tags='geo_basemap')
            # Dashed station connectors explicitly denote schematic completion.
            for lid,stations in engine.stations.items():
                for a,b in zip(stations,stations[1:]):
                    sa,sb=self.data['stations'].get(a['name']),self.data['stations'].get(b['name'])
                    if sa and sb:
                        cv.create_line(*xy(sa['point']),*xy(sb['point']),fill=lines[lid]['color'],width=2 if lid==state['line'] else 1,dash=(4,5))
            occupied=[]
            for lid,stations in engine.stations.items():
                for s in stations:
                    geo=self.data['stations'].get(s['name'])
                    if not geo:continue
                    x,y=xy(geo['point']);r=4 if lid==state['line'] else 2
                    cv.create_oval(x-r,y-r,x+r,y+r,fill='#10283b',outline=lines[lid]['color'],width=2)
                    if s['interchange_lines']:
                        cv.create_oval(x-6,y-6,x+6,y+6,outline='#f8d084',width=2)
                    if lid==state['line'] and (state['zoom']>1.8 or s['interchange_lines'] or s['id'] in (1,len(stations))):
                        if all(abs(x-a)>85 or abs(y-b)>16 for a,b in occupied):
                            cv.create_text(x+9,y-9,text=s['name'],anchor='w',fill='#eaf5f8',font=('Microsoft YaHei UI',-11));occupied.append((x,y))
            route=self.selected_bus(state) if state.get('show_osm_bus') else None
            if route:
                # Keep OSM way pieces separate; relation ordering need not form
                # one connected vehicle route or a valid SUMO service.
                shapes,stops=self._bus_geometry.get(str(route['id']),((),()))
                for shape,bounds in shapes:
                    if not self.overlaps(bounds,viewport):continue
                    points=[xy(point) for point in shape]
                    if len(points)>1:cv.create_line(*[v for p in points for v in p],fill='#ffb46a',width=3)
                for stop,model_point in stops:
                    point=xy(model_point);x,y=point
                    if x<0 or x>w or y<60 or y>h:continue
                    cv.create_oval(x-2.5,y-2.5,x+2.5,y+2.5,fill='#ffce92',outline='#553e2c')
                    for link in stop.get('metro_nearby',[]):
                        metro=self.data['stations'].get(link.get('name'))
                        if metro:cv.create_line(*point,*xy(metro['point']),fill='#ffca82',width=1,dash=(2,3))
                    if state['zoom']>3 and stop.get('metro_nearby'):cv.create_text(x+6,y-7,text=stop.get('name','公交站'),anchor='w',fill='#ffdbab',font=('Microsoft YaHei UI',-10))
            # Legible overlay panels keep attribution and provenance visible.
            cv.create_rectangle(0,0,w,67,fill='#0c2132',outline='')
            cv.create_text(18,22,text='厦门 · 城市与轨道',anchor='w',fill='#edf6fa',font=('Microsoft YaHei UI',-19,'bold'))
            cv.create_text(18,48,text=self.summary(),anchor='w',fill='#8fb3c6',font=('Microsoft YaHei UI',-11))
            if route:cv.create_text(w-16,22,text=f"OSM 公交 {route.get('ref','')} · {len(route.get('stops',[]))} 个站点成员",anchor='e',fill='#ffce92',font=('Microsoft YaHei UI',-11))
            cv.create_rectangle(0,h-45,w,h,fill='#0c2132',outline='')
            cv.create_text(16,h-31,text='实线 OSM轨道 · 虚线 站序连接 · 符号见下方图例',anchor='w',fill='#a4c2ce',font=('Microsoft YaHei UI',-10))
            cv.create_text(16,h-13,text='© OpenStreetMap contributors · ODbL | 列车 / 接驳为模型映射',anchor='w',fill='#7498ac',font=('Microsoft YaHei UI',-10))
            # Metric scale bar is tied to projection and zoom.
            length=2000*scale
            if length<180:
                cv.create_line(w-25-length,h-30,w-25,h-30,fill='#d8e9ef',width=2)
                cv.create_text(w-25-length/2,h-15,text='2 km',fill='#9ebdca',font=('Segoe UI',-10))
        touched=set();hits.clear()
        def item(key,kind,coords,**options):
            touched.add(key);old=self._dynamic.get(key)
            if old is None:
                ident=getattr(cv,'create_'+kind)(*coords,**options)
                self._dynamic[key]=(ident,options)
            else:
                ident,previous=old;cv.coords(ident,*coords)
                if previous!=options:cv.itemconfigure(ident,**options);self._dynamic[key]=(ident,options)
        for vid,t in engine.trains.items():
            if not t['active']:continue
            point=self.train_point(t,engine)
            if point is None:continue
            x,y=xy(point);vehicle_symbol(item,('train',vid),'train',x,y,lines[t['line']]['color'],vid==state['focus'])
            hits.append((x,y,vid))
        manager=getattr(engine,'mobility',None)
        if manager:
            snapshot=manager.snapshot();buses={b['id']:b for b in snapshot.get('buses',[])}
            for b in buses.values():
                point=b.get('geo_point') or self.feeder_point(b.get('position'),b.get('hub'),engine)
                if point is None:continue
                x,y=xy(point);vehicle_symbol(item,('bus',b['id']),'bus',x,y,'#ffb454')
                if state['zoom']>1.5:item(('buslabel',b['id']),'text',(x+7,y),text=b['line'],anchor='w',fill='#ffce92',font=('Microsoft YaHei UI',-10),tags='geo_mobility')
            for group in snapshot.get('groups',[]):
                if group.get('status') in ('arrived','到达'):continue
                point=self.crowd_point(group,engine,buses)
                if point is None:continue
                x,y=xy(point);dx,dy=group_offset(group);person_symbol(item,('group',group['id']),group,x+dx,y+dy)
        for key in list(self._dynamic):
            if key not in touched:cv.delete(self._dynamic.pop(key)[0])
