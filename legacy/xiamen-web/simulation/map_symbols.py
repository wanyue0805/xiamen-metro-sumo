"""Shared, retained canvas symbols for the desktop and remote desktop panels."""
import math

BUS_COLOR='#ffb454'
PERSON_COLORS={'walking':'#66e0cc','waiting':'#ffe178','bus':'#ffb454','metro':'#cfb5ff'}

class RetainedLayer:
    def __init__(self,canvas):
        self.canvas=canvas;self.items={};self.touched=set()
    def begin(self):self.touched.clear()
    def item(self,key,kind,coords,**options):
        self.touched.add(key);old=self.items.get(key)
        if old is None:
            ident=getattr(self.canvas,'create_'+kind)(*coords,**options)
        else:
            ident,previous_coords,previous=old
            if previous_coords!=tuple(coords):self.canvas.coords(ident,*coords)
            if previous!=options:self.canvas.itemconfigure(ident,**options)
        self.items[key]=(ident,tuple(coords),options)
        return ident
    def finish(self):
        for key in list(self.items):
            if key not in self.touched:self.canvas.delete(self.items.pop(key)[0])
    def clear(self):
        for ident,_,_ in self.items.values():self.canvas.delete(ident)
        self.items.clear()

def vehicle_symbol(item,key,kind,x,y,color,selected=False):
    if selected:item((key,'focus'),'oval',(x-14,y-14,x+14,y+14),outline='#ffffff',width=2)
    if kind=='train':
        item((key,'body'),'rectangle',(x-10,y-4,x+10,y+4),fill=color,outline='#ffffff',width=1.3)
        item((key,'windows'),'line',(x-6,y,x+6,y),fill='#142438',width=2,dash=(3,2))
    else:
        item((key,'body'),'rectangle',(x-5,y-7,x+5,y+7),fill=BUS_COLOR,outline='#fff3d6',width=1.3)
        item((key,'windows'),'line',(x-3,y-3,x+3,y-3),fill='#503716',width=2)

def person_symbol(item,key,group,x,y):
    color=PERSON_COLORS.get(group.get('mode'),'#66e0cc')
    radius=3.3 if int(group.get('count',20))==20 else 2.7
    item((key,'body'),'oval',(x-radius,y-radius,x+radius,y+radius),fill=color,outline='#122436',width=1.2)
    if int(group.get('count',20))!=20:
        item((key,'count'),'text',(x+5,y-6),text=str(group['count']),anchor='w',fill=color,font=('Microsoft YaHei UI',-10))

def group_offset(group):
    seed=sum(ord(c) for c in str(group['id']));angle=seed*2.39996;offset=11+(seed%4)*3
    return math.cos(angle)*offset,math.sin(angle)*offset

def draw_legend(canvas):
    canvas.delete('all');width=canvas.winfo_width()
    def item(key,kind,coords,**options):return getattr(canvas,'create_'+kind)(*coords,**options)
    vehicle_symbol(item,'train','train',22,14,'#d65d8d')
    canvas.create_text(40,14,text='列车 · 长条 / 线路色',anchor='w',fill='#ecf4fb',font=('Microsoft YaHei UI',-12))
    vehicle_symbol(item,'bus','bus',235,14,BUS_COLOR)
    canvas.create_text(248,14,text='公交 · 橙色车形',anchor='w',fill='#ecf4fb',font=('Microsoft YaHei UI',-12))
    canvas.create_oval(418,10,426,18,fill=PERSON_COLORS['walking'],outline='#fff')
    canvas.create_text(434,14,text='客流 · 圆点',anchor='w',fill='#ecf4fb',font=('Microsoft YaHei UI',-12))
    labels=[('walking','步行'),('waiting','候车'),('bus','公交内'),('metro','地铁内')]
    for i,(mode,label) in enumerate(labels):
        x=18+i*88;canvas.create_oval(x-3,36,x+3,42,fill=PERSON_COLORS[mode],outline='')
        canvas.create_text(x+8,39,text=label,anchor='w',fill='#b9cfde',font=('Microsoft YaHei UI',-11))
    canvas.create_text(374,39,text='通常 1 点 = 20 人 · 尾组标人数',anchor='w',fill='#b9cfde',font=('Microsoft YaHei UI',-11))
