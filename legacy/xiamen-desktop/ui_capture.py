"""Capture only the Tk window for optional Windows UI smoke artifacts."""
import ctypes
from ctypes import wintypes


def capture_window(root,target):
    from PIL import Image
    user=ctypes.windll.user32;gdi=ctypes.windll.gdi32
    user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
    hwnd=user.GetAncestor(root.winfo_id(),2)
    user.GetWindowDC.argtypes=[wintypes.HWND];user.GetWindowDC.restype=wintypes.HDC
    user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
    user.PrintWindow.argtypes=[wintypes.HWND,wintypes.HDC,wintypes.UINT]
    user.ReleaseDC.argtypes=[wintypes.HWND,wintypes.HDC]
    gdi.CreateCompatibleDC.argtypes=[wintypes.HDC];gdi.CreateCompatibleDC.restype=wintypes.HDC
    gdi.CreateCompatibleBitmap.argtypes=[wintypes.HDC,ctypes.c_int,ctypes.c_int];gdi.CreateCompatibleBitmap.restype=wintypes.HBITMAP
    gdi.SelectObject.argtypes=[wintypes.HDC,wintypes.HGDIOBJ];gdi.SelectObject.restype=wintypes.HGDIOBJ
    gdi.DeleteObject.argtypes=[wintypes.HGDIOBJ];gdi.DeleteDC.argtypes=[wintypes.HDC]
    gdi.GetDIBits.argtypes=[wintypes.HDC,wintypes.HBITMAP,wintypes.UINT,wintypes.UINT,ctypes.c_void_p,ctypes.c_void_p,wintypes.UINT]
    bounds=wintypes.RECT();user.GetWindowRect(hwnd,ctypes.byref(bounds));width=bounds.right-bounds.left;height=bounds.bottom-bounds.top
    source=user.GetWindowDC(hwnd);memory=gdi.CreateCompatibleDC(source);bitmap=gdi.CreateCompatibleBitmap(source,width,height);previous=gdi.SelectObject(memory,bitmap)
    class Header(ctypes.Structure):
        _fields_=[('size',wintypes.DWORD),('width',wintypes.LONG),('height',wintypes.LONG),('planes',wintypes.WORD),('bitcount',wintypes.WORD),('compression',wintypes.DWORD),('sizeimage',wintypes.DWORD),('xppm',wintypes.LONG),('yppm',wintypes.LONG),('clrused',wintypes.DWORD),('clrimportant',wintypes.DWORD)]
    try:
        if not user.PrintWindow(hwnd,memory,2):raise RuntimeError('无法捕获调度窗口。')
        info=Header();info.size=40;info.width=width;info.height=-height;info.planes=1;info.bitcount=32;buffer=ctypes.create_string_buffer(width*height*4)
        if gdi.GetDIBits(memory,bitmap,0,height,buffer,ctypes.byref(info),0)!=height:raise RuntimeError('窗口截图数据不完整。')
        Image.frombytes('RGB',(width,height),buffer.raw,'raw','BGRX').save(target)
    finally:
        gdi.SelectObject(memory,previous);gdi.DeleteObject(bitmap);gdi.DeleteDC(memory);user.ReleaseDC(hwnd,source)
