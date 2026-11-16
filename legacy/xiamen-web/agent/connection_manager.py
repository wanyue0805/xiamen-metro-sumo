from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
import json,subprocess,sys,webbrowser,ctypes
try:ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:pass
BASE=Path(__file__).resolve().parents[1]
access=json.loads((BASE/'config/access.json').read_text(encoding='utf-8'))
root=tk.Tk();root.title('SUMO 网页远程控制 · 启动中心');root.geometry('600x620');root.resizable(False,False)
root.configure(bg='#111f2e');style=ttk.Style();style.theme_use('clam')
style.configure('TFrame',background='#111f2e');style.configure('TLabel',background='#111f2e',foreground='#e9f1f7',font=('Microsoft YaHei UI',11));style.configure('TButton',font=('Microsoft YaHei UI',10),padding=9);style.configure('TCheckbutton',background='#111f2e',foreground='#aebdca',font=('Microsoft YaHei UI',9))
box=ttk.Frame(root,padding=25);box.pack(fill='both',expand=True)
ttk.Label(box,text='SUMO · 远程调度',font=('Microsoft YaHei UI',21,'bold')).pack(anchor='w')
ttk.Label(box,text='先启动 Windows 面板，再登录网页控制。',foreground='#8d9eae').pack(anchor='w',pady=(8,17))
for title,value in [('网页地址',access['url']),('用户名',access['username'])]:
    row=ttk.Frame(box);row.pack(fill='x',pady=4);ttk.Label(row,text=title,width=9).pack(side='left');entry=ttk.Entry(row);entry.insert(0,value);entry.configure(state='readonly');entry.pack(side='left',fill='x',expand=True)
row=ttk.Frame(box);row.pack(fill='x',pady=4);ttk.Label(row,text='登录密码',width=9).pack(side='left');password=ttk.Entry(row,show='•');password.insert(0,access['password']);password.configure(state='readonly');password.pack(side='left',fill='x',expand=True)
def toggle():password.configure(show='' if password.cget('show') else '•')
ttk.Button(box,text='显示 / 隐藏密码',command=toggle).pack(anchor='e',pady=5)
def start():
    executable=Path(sys.executable).with_name('pythonw.exe')
    subprocess.Popen([str(executable),'-B',str(BASE/'agent/launch_remote.py')],cwd=BASE,creationflags=subprocess.CREATE_NO_WINDOW)
    messagebox.showinfo('已启动','正在打开独立远程面板。\n原项目与原 Metro.exe 保留。',parent=root)
row=ttk.Frame(box);row.pack(fill='x',pady=13)
ttk.Button(row,text='启动 Windows 远程面板',command=start).pack(side='left',fill='x',expand=True,padx=(0,8))
ttk.Button(row,text='打开网页',command=lambda:webbrowser.open(access['url'])).pack(side='left',fill='x',expand=True)
device_path=BASE/'config/device.json'
device=json.loads(device_path.read_text(encoding='utf-8'))
use_proxy=tk.BooleanVar(value=bool(device.get('proxy')))
def change_proxy():
    device=json.loads(device_path.read_text(encoding='utf-8'))
    if use_proxy.get():device['proxy']={'host':'127.0.0.1','port':7897}
    else:device.pop('proxy',None)
    device_path.write_text(json.dumps(device,ensure_ascii=False,indent=2),encoding='utf-8')
    messagebox.showinfo('连接设置已保存','请关闭并重新启动远程面板以使用新设置。',parent=root)
ttk.Checkbutton(box,text='通过本机 Clash 代理连接（127.0.0.1:7897）',variable=use_proxy,command=change_proxy).pack(anchor='w',pady=(0,10))
ttk.Label(box,text='关闭远程面板即停止本次仿真与设备连接。',foreground='#8d9eae',font=('Microsoft YaHei UI',9)).pack(anchor='w')
root.update_idletasks()
root.geometry(f'{max(600,root.winfo_reqwidth())}x{max(560,root.winfo_reqheight()+12)}')
root.mainloop()
