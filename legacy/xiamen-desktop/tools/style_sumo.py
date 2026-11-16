"""Style the new native SUMO operating view without changing rail topology."""
from pathlib import Path
import json,math,sys,xml.etree.ElementTree as E
ROOT=Path(__file__).resolve().parents[1]

def build():
    net=E.parse(ROOT/'network/multimodal.net.xml').getroot()
    catalogue=json.loads((ROOT/'lines.json').read_text(encoding='utf-8'))
    lines={l['id']:l for l in catalogue['lines']}
    for edge in net.findall('edge'):
        eid=edge.get('id');line=next((lid for lid in lines if eid.startswith(f'L{lid}_') or eid.startswith(f':L{lid}_')),0)
        if not any('rail_urban' in lane.get('allow','') for lane in edge.findall('lane')):line=0
        parameter=next((p for p in edge.findall('param') if p.get('key')=='display_line'),None)
        if parameter is None:parameter=E.SubElement(edge,'param',key='display_line')
        parameter.set('value',str(line))
    E.ElementTree(net).write(ROOT/'network/multimodal.net.xml',encoding='utf-8',xml_declaration=True)
    stations=json.loads((ROOT/'network/unified.stations.json').read_text(encoding='utf-8'))
    decoration=E.Element('additional')
    for edge in net.findall('edge'):
        eid=edge.get('id');line=next((lid for lid in lines if eid.startswith(f'L{lid}_')),None)
        if line is None or not any(eid.startswith(f'L{line}_{prefix}') for prefix in ('GU','U')):continue
        lane=edge.find('lane')
        if lane is None:continue
        points=[tuple(map(float,p.split(',')[:2])) for p in lane.get('shape').split()]
        left=[];right=[]
        for i,p in enumerate(points):
            a=points[max(0,i-1)];b=points[min(len(points)-1,i+1)];dx=b[0]-a[0];dy=b[1]-a[1];length=max(.001,math.hypot(dx,dy));nx,ny=-dy/length,dx/length
            left.append((p[0]+25*nx,p[1]+25*ny));right.append((p[0]-25*nx,p[1]-25*ny))
        ribbon=left+list(reversed(right))+[left[0]]
        shape=' '.join(f'{x:.2f},{y:.2f}' for x,y in ribbon)
        E.SubElement(decoration,'poly',id='STYLE_'+eid,type='rail_line',color=lines[line]['color'],
                     layer='1',fill='true',shape=shape)
    # Text anchors use the actual hub coordinates, with room for the labels
    # at the default city viewport. Markers remain at the hub locations.
    english={'湖滨东路':'Hubin East Rd','吕厝':'Lvcuo','火炬园':'Torch Park','官任':'Guanren','厦门北站':'Xiamen North','鼎美':'Dingmei','马銮中心':'Maluan Center','体育中心':'Sports Center','五缘湾':'Wuyuan Bay','洪坑':'Hongkeng'}
    label_offsets={
        '体育中心':(-2400,600), '吕厝':(1800,750), '湖滨东路':(1600,-750),
        '鼎美':(-2300,-1000), '马銮中心':(1000,1350),
        '火炬园':(-1300,700), '官任':(-1300,350),
        '厦门北站':(1800,1000), '五缘湾':(1500,800), '洪坑':(1700,800),
    }
    for name,hub in stations['shared_stations'].items():
        members=hub['members'];point=hub['point'];transfer=len(members)>1
        poi=E.SubElement(decoration,'poi',id='STYLE_ST_'+str(len(decoration)),
                     x=str(point[0]),y=str(point[1]+40),color='#f4cc7e' if transfer else '#aac6d8',
                     name=name,width='1.2' if transfer else '0.75',height='1.2' if transfer else '0.75',layer='8')
        if transfer:
            dx,dy=label_offsets.get(name,(1200,700));x,y=point[0]+dx,point[1]+dy
            # A separate transparent POI carries text, leaving the gold marker
            # legible even where several lines and nearby hubs meet.
            text=E.SubElement(decoration,'poi',id='STYLE_HUB_TEXT_'+str(len(decoration)),
                x=str(x),y=str(y),color='0,0,0,0',width='0.5',height='0.5',layer='15')
            E.SubElement(text,'param',key='label',value=english.get(name,name)+' '+ '/'.join(map(str,members)))
            E.SubElement(decoration,'poly',id='STYLE_HUB_LEADER_'+str(len(decoration)),
                type='hub_label_leader',color='#a58c59',layer='7',fill='false',lineWidth='35',
                shape=f'{point[0]:.2f},{point[1]+40:.2f} {x:.2f},{y:.2f}')
    xmin,ymin,xmax,ymax=map(float,net.find('location').get('convBoundary').split(','))
    text=[('XIAMEN METRO + BUS | ONE SHARED CLOCK',(xmin+xmax)/2,ymax+800),
          ('1 DOT = 20 PEOPLE | FINAL COHORT USES ITS ACTUAL WEIGHT',(xmin+xmax)/2,ymax),
          ('SCHEMATIC FEEDERS | TIMED RED / AUTOMATIC BLOCK',(xmin+xmax)/2,ymax-800)]
    for i,(caption,x,y) in enumerate(text):
        label=E.SubElement(decoration,'poi',id=f'STYLE_CAPTION_{i}',x=str(x),y=str(y),type='legend',color='0,0,0,0',width='0.5',height='0.5',layer='15')
        E.SubElement(label,'param',key='label',value=caption)
    E.ElementTree(decoration).write(ROOT/'network/multimodal.style.add.xml',encoding='utf-8',xml_declaration=True)
    view=E.Element('viewsettings');scheme=E.SubElement(view,'scheme',name='XiamenMobility4')
    E.SubElement(scheme,'background',backgroundColor='2,5,10',showGrid='0')
    edges=E.SubElement(scheme,'edges',laneEdgeMode='31',edgeParam='display_line',laneShowBorders='0',showLinkDecals='0',showLinkRules='1',showRails='0',hideConnectors='0',widthExaggeration='6',minSize='0',edgeName_show='0',streetName_show='0')
    colors=E.SubElement(edges,'colorScheme',name='by param (numerical, streetwise)',interpolated='false')
    for value in range(7):E.SubElement(colors,'entry',threshold=str(value),color=lines[value]['color'] if value in lines else '#304957')
    E.SubElement(colors,'entry',threshold='10000000000',color='#304957')
    E.SubElement(scheme,'vehicles',vehicleMode='0',vehicleQuality='2',vehicle_minSize='2',vehicle_exaggeration='1',vehicle_constantSize='0',vehicleName_show='0',showBlinker='1')
    E.SubElement(scheme,'persons',personMode='0',personQuality='0',person_minSize='0',person_exaggeration='1.6',person_constantSize='1',personName_show='0')
    E.SubElement(scheme,'junctions',junctionMode='0',drawShape='0',junctionID_show='0',tlsPhaseName_show='0',showLane2Lane='0')
    E.SubElement(scheme,'additionals',add_minSize='1',add_exaggeration='1',addFullName_show='0',busStopColor='55,179,178',busStopColorSign='240,199,114',trainStopColor='79,127,154',trainStopColorSign='240,199,114')
    E.SubElement(scheme,'pois',poi_minSize='0',poi_exaggeration='1',poi_constantSize='1',poiName_show='1',poiName_onlySelected='1',poiName_size='60',poiType_show='1',poiType_onlySelected='1',poiType_size='55',poiType_color='213,232,243',poiType_constantSize='1',poiTextParam='label',poiText_show='1',poiText_size='65',poiText_constantSize='1',poiText_color='213,232,243',poiText_bgColor='2,5,10,200')
    E.SubElement(scheme,'polys',poly_minSize='0',poly_exaggeration='1',polyName_show='0')
    E.SubElement(view,'viewport',zoom='65',x=str((xmin+xmax)/2),y=str((ymin+ymax)/2+400))
    E.SubElement(view,'delay',value='0')
    E.ElementTree(view).write(ROOT/'network/multimodal.view.xml',encoding='utf-8',xml_declaration=True)
    source=E.parse(ROOT/'network/multimodal.add.xml')
    for poi in source.getroot().findall('poi'):
        width=float(poi.get('width','1'))
        size=.3 if width<3 else .8 if width<10 else 1.15 if width<20 else 1.45
        poi.set('width',str(size));poi.set('height',str(size))
    source.write(ROOT/'network/multimodal.decorated.add.xml',encoding='utf-8',xml_declaration=True)
    cfg_path=ROOT/'network/multimodal.sumocfg';cfg=E.parse(cfg_path);additional=cfg.getroot().find('input/additional-files')
    values=[p for p in additional.get('value').split(',') if p not in ('multimodal.style.add.xml','multimodal.add.xml','multimodal.decorated.add.xml')];values=['multimodal.decorated.add.xml']+values+['multimodal.style.add.xml'];additional.set('value',','.join(values))
    cfg.write(cfg_path,encoding='utf-8',xml_declaration=True)
    print('Native operating style and '+str(len(decoration))+' decorations created.')

if __name__=='__main__':build()
