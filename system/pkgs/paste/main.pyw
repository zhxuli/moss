#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EdgePaste 贴边快输 —— 分组版 v2 (main.pyw)
================================================
v2 新增:
  1. 分组: 条目按分组管理, 每个分组可设置「切换热键」
  2. 分组之间热键可以冲突/重复: 只有「已启用」的分组才会注册它的条目热键
  3. 多分组同时生效: 分组纵向堆叠(像 QQ), 生效中的分组蓝色高亮
  4. 生效与展开解耦: 复选框控制"哪些分组生效", 点标题只展开折叠, 互不影响
     中键点标题 = 只勾选这一个分组; 条目可写可选备注(悬停才弹气泡)
  5. 切换方便: 分组切换热键 / 上一组·下一组热键 / 标题拖拽排序 / 条目拖拽归组
  6. 响应快: 勾选/折叠/打字都是增量更新(不重建列表, 不重注册热键, 延迟合并写盘)
沿用:
  · 智能防拦截: 录制时自动挂起全局快捷键, 100% 捕获所有按键
  · 边缘自由拉伸 / 原生吸附 / 自动隐藏 / 单实例
数据: data.json
      (旧版单层 entries 会自动迁移到「默认」分组, 原文件备份为 data.json.v1.bak)
"""

import sys
import os
import json
import time
import queue
import shutil
import threading
import ctypes
import uuid
from pathlib import Path
import tkinter as tk
import tkinter.messagebox as messagebox

# ---------------------------------------------------------------------------
# DPI 感知
# ---------------------------------------------------------------------------
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# ---------------------------------------------------------------------------
# Windows API
# ---------------------------------------------------------------------------
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint),
                ("wParam", WPARAM), ("lParam", LPARAM),
                ("time", ctypes.c_ulong), ("pt", POINT)]


WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_void_p, ctypes.c_uint, WPARAM, LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("style", ctypes.c_uint),
                ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", ctypes.c_void_p),
                ("hIcon", ctypes.c_void_p), ("hCursor", ctypes.c_void_p),
                ("hbrBackground", ctypes.c_void_p), ("lpszMenuName", ctypes.c_wchar_p),
                ("lpszClassName", ctypes.c_wchar_p), ("hIconSm", ctypes.c_void_p)]


def _setup_api():
    u = user32
    u.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_uint, WPARAM, LPARAM]
    u.DefWindowProcW.restype = LRESULT
    u.GetMessageW.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
    u.GetMessageW.restype = ctypes.c_int
    u.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
    u.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
    u.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
    u.RegisterClassExW.restype = ctypes.c_ushort
    u.CreateWindowExW.argtypes = [ctypes.c_uint, ctypes.c_wchar_p, ctypes.c_wchar_p,
                                  ctypes.c_uint, ctypes.c_int, ctypes.c_int,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                  ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    u.CreateWindowExW.restype = ctypes.c_void_p
    u.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
    u.RegisterHotKey.restype = ctypes.c_int
    u.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
    u.UnregisterHotKey.restype = ctypes.c_int
    u.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    u.FindWindowW.restype = ctypes.c_void_p
    u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, WPARAM, LPARAM]
    u.PostMessageW.restype = ctypes.c_int
    u.RegisterWindowMessageW.argtypes = [ctypes.c_wchar_p]
    u.RegisterWindowMessageW.restype = ctypes.c_uint
    u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, WPARAM, LPARAM]
    u.SendMessageW.restype = LRESULT
    u.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    u.GetCursorPos.restype = ctypes.c_int
    # ★ POINT 是【按值传结构体】(HMONITOR MonitorFromPoint(POINT pt, DWORD dwFlags))，
    #   写成 POINTER(POINT) 会把指针当两个 int 塞进寄存器 -> 点变成垃圾值 ->
    #   永远返回同一块显示器（多屏贴边就全错了；单屏因为兜底到主屏所以看不出来）。
    u.MonitorFromPoint.argtypes = [POINT, ctypes.c_ulong]
    u.MonitorFromPoint.restype = ctypes.c_void_p
    u.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    u.GetMonitorInfoW.restype = ctypes.c_int
    u.GetSystemMetrics.argtypes = [ctypes.c_int]
    u.GetSystemMetrics.restype = ctypes.c_int
    u.GetAsyncKeyState.argtypes = [ctypes.c_int]
    u.GetAsyncKeyState.restype = ctypes.c_short
    u.keybd_event.argtypes = [ctypes.c_ubyte, ctypes.c_ubyte, ctypes.c_ulong, ctypes.c_size_t]

    u.OpenClipboard.argtypes = [ctypes.c_void_p]
    u.OpenClipboard.restype = ctypes.c_int
    u.CloseClipboard.restype = ctypes.c_int
    u.EmptyClipboard.restype = ctypes.c_int
    u.GetClipboardData.argtypes = [ctypes.c_uint]
    u.GetClipboardData.restype = ctypes.c_void_p
    u.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
    u.SetClipboardData.restype = ctypes.c_void_p

    u.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                               ctypes.c_uint]
    u.SetWindowPos.restype = ctypes.c_int
    u.GetParent.argtypes = [ctypes.c_void_p]
    u.GetParent.restype = ctypes.c_void_p

    k = kernel32
    k.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
    k.GetModuleHandleW.restype = ctypes.c_void_p
    k.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
    k.CreateMutexW.restype = ctypes.c_void_p
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    k.GetLastError.restype = ctypes.c_ulong
    k.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
    k.GlobalAlloc.restype = ctypes.c_void_p
    k.GlobalLock.argtypes = [ctypes.c_void_p]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [ctypes.c_void_p]
    k.GlobalUnlock.restype = ctypes.c_int
    k.GlobalFree.argtypes = [ctypes.c_void_p]
    k.GlobalFree.restype = ctypes.c_void_p


_setup_api()

# ---------------------------------------------------------------------------
# 常量与配色
# ---------------------------------------------------------------------------
HOTKEY_WND_CLASS = "EdgePasteHotkeyWnd_v15"
MUTEX_NAME = "Global\\EdgePaste_Mutex_v15"
DATA_VERSION = 2

WM_HOTKEY = 0x0312
WM_SHOW = user32.RegisterWindowMessageW("EdgePaste_Show_v15")
WM_DO_REGISTER = 0x0401
WM_DO_UNREGISTER = 0x0402

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002

INITIAL_H = 150

# 热键 ID 分区
HID_TOGGLE = 1
HID_CYCLE_PREV = 2
HID_CYCLE_NEXT = 3
HID_GROUP_BASE = 10
HID_ENTRY_BASE = 1000

# 分组标题条
BAR_ON = "#93c5fd"          # 已启用但非当前分组
BAR_OFF = "#cbd5e1"         # 未启用
BAND_ON = "#dbeafe"         # 生效中的分组底色(醒目)
BAND_ON_CUR = "#bfdbfe"     # 生效中 + 最近操作的分组 (更深一档)
BAND_OFF = "#f1f5f9"        # 未生效
BAND_OFF_CUR = "#e8eef6"    # 未生效 + 最近操作
BORDER_OFF_CUR = "#cbd5e1"  # 未生效但最近操作 -> 灰描边
CARD_BORDER_ON = "#93c5fd"  # 生效分组里的条目卡片描边

APP_BG = "#f8fafc"
HEADER_BG = "#ffffff"
HEADER_BORDER = "#e2e8f0"
CARD_BG = "#ffffff"
CARD_HOVER = "#f1f5f9"
CARD_BORDER = "#cbd5e1"
TEXT_TITLE = "#0f172a"
TEXT_MAIN = "#334155"
TEXT_MUTED = "#94a3b8"
ACCENT = "#2563eb"
ACCENT_HOVER = "#1d4ed8"
ACCENT_FG = "#ffffff"
BADGE_BG = "#e2e8f0"
BADGE_FG = "#475569"
BADGE_RED = "#fee2e2"
BADGE_RED_FG = "#b91c1c"
BADGE_ORANGE = "#ffedd5"
BADGE_ORANGE_FG = "#c2410c"
FLASH_BG = "#dcfce7"

SECTION_BG = "#f1f5f9"
SECTION_CUR_BG = "#dbeafe"
SECTION_LINE = "#e2e8f0"

MOD_TO_VK = {MOD_CONTROL: 0x11, MOD_ALT: 0x12, MOD_SHIFT: 0x10, MOD_WIN: 0x5B}
KEY_VK = {
    "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "BACKSPACE": 0x08,
    "DELETE": 0x2E, "INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
    "PAGEUP": 0x21, "PAGEDOWN": 0x22, "UP": 0x26, "DOWN": 0x28,
    "LEFT": 0x25, "RIGHT": 0x27, "ESCAPE": 0x1B, "PRINT": 0x2A,
    "+": 0xBB, "-": 0xBD, "=": 0xBB, ",": 0xBC, ".": 0xBE,
    "/": 0xBF, ";": 0xBA, "'": 0xDE, "[": 0xDB, "]": 0xDD,
    "\\": 0xDC, "`": 0xC0,
}

SHIFT_MAP = {
    'exclam': '1', '!': '1', 'at': '2', '@': '2', 'numbersign': '3', '#': '3',
    'dollar': '4', '$': '4', 'percent': '5', '%': '5', 'asciicircum': '6', '^': '6',
    'ampersand': '7', '&': '7', 'asterisk': '8', '*': '8', 'parenleft': '9', '(': '9',
    'parenright': '0', ')': '0', 'underscore': '-', '_': '-', 'plus': '=', '+': '=',
    'braceleft': '[', '{': '[', 'braceright': ']', '}': ']', 'bar': '\\', '|': '\\',
    'colon': ';', ':': ';', 'quotedbl': "'", '"': "'", 'less': ',', '<': ',',
    'greater': '.', '>': '.', 'question': '/', '?': '/', 'asciitilde': '`', '~': '`'
}

MOD_KEYSYMS = {'Control_L', 'Control_R', 'Alt_L', 'Alt_R', 'Shift_L', 'Shift_R',
               'Super_L', 'Super_R', 'Win_L', 'Win_R'}

HOTKEY_HWND = [None]
_hotkey_wnd_proc = [None]
event_queue = queue.Queue()


def get_base():
    try:
        f = Path(__file__).resolve()
        if f.is_file(): return f.parent
    except NameError:
        pass
    candidates = []
    if sys.path and sys.path[0] and os.path.isdir(sys.path[0]):
        candidates.append(Path(sys.path[0]).resolve())
    candidates.append(Path.cwd().resolve())
    for c in candidates:
        if (c / "main.pyw").is_file(): return c
    return candidates[0]


BASE = get_base()
# 宿主 moss 注入的插件专属数据目录 (= user_data/state/paste)；老 pa 的 PA_* 与插件目录作兜底
DATA_DIR = Path(os.environ.get("MOSS_PLUGIN_DATA_DIR") or os.environ.get("PA_PLUGIN_DATA_DIR") or BASE)
DATA_FILE = DATA_DIR / "data.json"


def clipboard_get_text():
    if not user32.OpenClipboard(None): return None
    try:
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h: return None
        p = kernel32.GlobalLock(h)
        if not p: return None
        try:
            return ctypes.wstring_at(p)
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def clipboard_set_text(text):
    data = (text + "\x00").encode("utf-16-le")
    h = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not h: return False
    p = kernel32.GlobalLock(h)
    if not p:
        kernel32.GlobalFree(h)
        return False
    try:
        ctypes.memmove(p, data, len(data))
    finally:
        kernel32.GlobalUnlock(h)

    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(h)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(h)
            return False
        return True
    finally:
        user32.CloseClipboard()


def send_ctrl_v():
    user32.keybd_event(VK_CONTROL, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_V, 0, 0, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.03)
    user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)


def key_to_vk(token):
    t = token.strip().upper()
    if t in KEY_VK: return KEY_VK[t]
    if len(t) == 1 and (t.isalpha() or t.isdigit()): return ord(t)
    if t.startswith("F") and t[1:].isdigit():
        n = int(t[1:])
        if 1 <= n <= 24: return 0x70 + n - 1
    return None


def parse_hotkey(s):
    parts = [p.strip() for p in s.replace("＋", "+").split("+") if p.strip()]
    if not parts: return None
    mods = 0
    vk = None
    for p in parts:
        pl = p.lower()
        if pl in ("ctrl", "control"):
            mods |= MOD_CONTROL
        elif pl in ("alt",):
            mods |= MOD_ALT
        elif pl in ("shift",):
            mods |= MOD_SHIFT
        elif pl in ("win", "super"):
            mods |= MOD_WIN
        else:
            vk = key_to_vk(p)
            if vk is None: return None
    if vk is None: return None
    return mods, vk


def _normalize_keysym(ks):
    if ks in SHIFT_MAP: return SHIFT_MAP[ks]
    if len(ks) == 1: return ks.upper()
    m = {"Space": "Space", "Return": "Enter", "BackSpace": "Backspace",
         "Prior": "PageUp", "Next": "PageDown", "Caps_Lock": "CapsLock",
         "Num_Lock": "NumLock", "Scroll_Lock": "ScrollLock", "Escape": "Escape"}
    if ks in m: return m[ks]
    return ks


def compose_hotkey(event):
    """把一次 Tkinter 按键事件转成热键字符串, 无效返回 None"""
    mods = []
    if event.state & 0x4: mods.append("Ctrl")
    if (event.state & 0x20000) or event.keysym.startswith("Alt"):
        if "Alt" not in mods: mods.append("Alt")
    if event.state & 0x1: mods.append("Shift")
    if event.state & 0x40: mods.append("Win")

    key = _normalize_keysym(event.keysym)
    if not key: return None
    return "+".join(mods + [key]) if mods else key


def hotkey_thread_main():
    global HOTKEY_HWND
    hinst = kernel32.GetModuleHandleW(None)

    @WNDPROC
    def wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_DO_REGISTER:
            hid = int(wparam)
            mods = (lparam >> 16) & 0xFFFF
            vk = lparam & 0xFFFF
            return user32.RegisterHotKey(hwnd, hid, mods | MOD_NOREPEAT, vk)
        if msg == WM_DO_UNREGISTER:
            hid = int(wparam)
            return user32.UnregisterHotKey(hwnd, hid)

        if msg == WM_HOTKEY:
            mods = lparam & 0xFFFF
            vk = (lparam >> 16) & 0xFFFF
            keys = [vk]
            for m, kv in MOD_TO_VK.items():
                if mods & m: keys.append(kv)
            deadline = time.time() + 2.0
            while time.time() < deadline:
                if not any(user32.GetAsyncKeyState(k) & 0x8000 for k in keys):
                    break
                time.sleep(0.01)
            event_queue.put(("hotkey", int(wparam)))
            return 0
        if msg == WM_SHOW:
            event_queue.put(("show", None))
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    _hotkey_wnd_proc[0] = wnd_proc
    wc = WNDCLASSEXW()
    wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
    wc.lpfnWndProc = wnd_proc
    wc.hInstance = hinst
    wc.lpszClassName = HOTKEY_WND_CLASS
    user32.RegisterClassExW(ctypes.byref(wc))

    hwnd = user32.CreateWindowExW(
        0x00000080, HOTKEY_WND_CLASS, "EdgePaste", 0x80000000,
        0, 0, 0, 0, None, None, hinst, None)
    HOTKEY_HWND[0] = hwnd

    msg = MSG()
    while True:
        r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
        if r <= 0: break
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


def check_single_instance():
    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if kernel32.GetLastError() == 183:
        kernel32.CloseHandle(handle)
        hwnd = user32.FindWindowW(HOTKEY_WND_CLASS, None)
        if hwnd: user32.PostMessageW(hwnd, WM_SHOW, 0, 0)
        return False
    return True


# ---------------------------------------------------------------------------
# 对话框内的热键录制器
# ---------------------------------------------------------------------------
class HotkeyRecorder:
    """点「录制」→ 挂起全部全局热键 → 捕获下一个按键 → 自动写入"""

    def __init__(self, app, dlg, parent, var, width=16, base_hint="点「录制」按键", button_text="录制"):
        self.app = app
        self.dlg = dlg
        self.var = var
        self.on = False
        self.base_hint = base_hint

        self.frame = tk.Frame(parent, bg=APP_BG)
        self.outer, self.entry = app._create_modern_entry(self.frame, width, var)
        self.outer.pack(side="left")

        self.btn = tk.Button(self.frame, text=button_text, command=self.toggle, bg=HEADER_BG, fg=TEXT_TITLE,
                             activebackground=CARD_HOVER, activeforeground=TEXT_TITLE,
                             relief="flat", bd=0, cursor="hand2", padx=10, pady=3,
                             font=("Microsoft YaHei UI", 9))
        self.btn.pack(side="left", padx=(6, 0))

        self.hint = tk.Label(self.frame, text=base_hint, bg=APP_BG, fg=TEXT_MUTED,
                             font=("Microsoft YaHei UI", 8))
        self.hint.pack(side="left", padx=(8, 0))

        recs = getattr(dlg, "_recorders", None)
        if recs is None:
            recs = []
            dlg._recorders = recs
            dlg._active_rec = None

            def _on_key(e, _dlg=dlg):
                rec = getattr(_dlg, "_active_rec", None)
                return rec.handle_key(e) if rec is not None else None

            dlg.bind("<KeyPress>", _on_key)
        recs.append(self)

    def toggle(self):
        if self.on:
            self.stop("已取消")
        else:
            self.start()

    def start(self):
        for r in getattr(self.dlg, "_recorders", []):
            if r is not self and r.on:
                r.stop(None)
        self.on = True
        self.dlg._active_rec = self
        self.hint.config(text="请按键…(Esc 取消)", fg=ACCENT)
        self.btn.config(text="取消", bg=BADGE_ORANGE, fg=BADGE_ORANGE_FG)
        self.entry.focus_set()
        self.app.clear_hotkeys()   # 关键: 挂起全局热键, 保证按键流进 Tk

    def stop(self, note=None):
        self.on = False
        if getattr(self.dlg, "_active_rec", None) is self:
            self.dlg._active_rec = None
        self.hint.config(text=note if note else self.base_hint, fg=TEXT_MUTED)
        self.btn.config(text="录制", bg=HEADER_BG, fg=TEXT_TITLE)
        self.app.rebind_all()

    def handle_key(self, event):
        if not self.on: return None
        if event.keysym == "Escape":
            self.stop("已取消")
            return "break"
        if event.keysym in MOD_KEYSYMS: return "break"
        hk = compose_hotkey(event)
        if not hk: return "break"
        self.var.set(hk)
        self.stop("录制完成")
        return "break"


# ---------------------------------------------------------------------------
# 自绘小控件: 展开三角 / 复选框 (字体符号太小又不清晰, 自绘的更大更规整)
# ---------------------------------------------------------------------------
class Disclosure(tk.Canvas):
    """展开/折叠三角: 展开向下, 折叠向右"""

    def __init__(self, parent, bg, fg, size=12, box=20, command=None):
        super().__init__(parent, width=box, height=box, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._box, self._size = box, size
        self._base_fg = fg
        self._fg = fg
        self._expanded = False
        self.command = command
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._set_fg(ACCENT))
        self.bind("<Leave>", lambda e: self._set_fg(self._base_fg))
        self._redraw()

    def _click(self, _e=None):
        if self.command: self.command()
        return "break"

    def _set_fg(self, fg):
        self._fg = fg
        self._redraw()

    def config_colors(self, bg, fg=None):
        self.configure(bg=bg)
        if fg is not None:
            self._base_fg = fg
            self._fg = fg
        self._redraw()

    def set_expanded(self, v):
        v = bool(v)
        if v != self._expanded:
            self._expanded = v
            self._redraw()

    def _redraw(self):
        self.delete("all")
        b, s = self._box, self._size
        cx, cy, r = b / 2.0, b / 2.0, s / 2.0
        if self._expanded:
            pts = (cx - r, cy - r * 0.55, cx + r, cy - r * 0.55, cx, cy + r * 0.72)
        else:
            pts = (cx - r * 0.55, cy - r, cx - r * 0.55, cy + r, cx + r * 0.72, cy)
        self.create_polygon(pts, fill=self._fg, outline="")


class CheckBox(tk.Canvas):
    """分组"生效"复选框: 勾上 = 该分组的条目热键生效"""

    def __init__(self, parent, bg, size=14, box=20, command=None, checked=False):
        super().__init__(parent, width=box, height=box, bg=bg,
                         highlightthickness=0, bd=0, cursor="hand2")
        self._box, self._size = box, size
        self._checked = bool(checked)
        self._hover = False
        self.command = command
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda e: self._redraw(hover=True))
        self.bind("<Leave>", lambda e: self._redraw(hover=False))
        self._redraw()

    def _click(self, _e=None):
        self._checked = not self._checked
        self._redraw()
        if self.command: self.command(self._checked)
        return "break"

    def config_bg(self, bg):
        self.configure(bg=bg)
        self._redraw()

    def set_checked(self, v):
        v = bool(v)
        if v != self._checked:
            self._checked = v
            self._redraw()

    def _redraw(self, hover=None):
        if hover is not None:
            self._hover = hover
        self.delete("all")
        b, s = self._box, self._size
        x0 = (b - s) / 2.0
        y0 = (b - s) / 2.0
        x1, y1 = x0 + s, y0 + s
        if self._checked:
            self.create_rectangle(x0, y0, x1, y1, fill=ACCENT, outline=ACCENT)
            self.create_line(x0 + 3, y0 + s * 0.55, x0 + s * 0.42, y1 - 3.5, x1 - 3, y0 + 3,
                             fill="#ffffff", width=2, capstyle="round", joinstyle="round")
        else:
            self.create_rectangle(x0, y0, x1, y1, fill="#ffffff",
                                  outline=(ACCENT if self._hover else BADGE_BG), width=1)


# ---------------------------------------------------------------------------
# 主程序
# ---------------------------------------------------------------------------
class EdgePasteApp:
    def __init__(self):
        self.data = self._load_data()

        if self.data.pop("_migrated", False):
            try:
                if DATA_FILE.is_file():
                    shutil.copy2(str(DATA_FILE), str(DATA_FILE) + ".v1.bak")
            except Exception:
                pass

        self.groups = self.data.get("groups") or []
        for g in self.groups:
            g.setdefault("id", uuid.uuid4().hex[:8])
            g.setdefault("name", "分组")
            g.setdefault("hotkey", "")
            g.setdefault("collapsed", False)
            g.setdefault("entries", [])
            for e in g["entries"]:
                e.pop("name", None)
                e.setdefault("id", uuid.uuid4().hex[:8])
                e.setdefault("content", "")
                e.setdefault("hotkey", "")
                e.setdefault("note", "")     # 备注: 可留空, 只在鼠标悬停时显示

        if not self.groups:
            self.groups.append(self._new_group_dict("默认"))
            self.data["groups"] = self.groups

        gids = [g["id"] for g in self.groups]
        active = [x for x in (self.data.get("active") or []) if x in gids]
        self.active = active if active else [gids[0]]
        cur = self.data.get("current")
        self.current_gid = cur if cur in gids else self.active[0]

        self.settings = self.data.setdefault("settings", {})
        for k, v in (("toggle_hotkey", "Ctrl+Alt+E"),
                     ("prev_group_hotkey", ""),
                     ("next_group_hotkey", ""),
                     ("auto_hide", True),
                     ("snap_threshold", 60),
                     ("strip", 3),
                     ("columns", 1),
                     ("show_inactive", True),
                     ("win_w", 340)):
            self.settings.setdefault(k, v)

        if self.settings.get("strip", 3) > 10:
            self.settings["strip"] = 3

        # 不再强制按列倍数锁定宽度，而是直接读取存储的自定义宽度
        self.win_w = max(250, int(self.settings.get("win_w", 340)))

        self.win = self.data.setdefault("window", {
            "x": None, "y": None, "dock": None,
            "rx": None, "ry": None, "rw": None, "rh": None,
        })

        self.hk_map = {}          # hid -> (kind, key)
        self.hotkey_status = {}   # eid -> none/ok/conflict/invalid/off
        self.group_status = {}    # gid -> none/ok/conflict/invalid
        self.cycle_status = {"prev": "none", "next": "none"}
        self.toggle_status = "none"
        self._hid_map = {}        # target -> hid (稳定分配, 避免顺序变化就重注册)
        self._hid_next = HID_GROUP_BASE
        self._hk_sig = None       # 上次注册的热键指纹
        self._save_job = None     # 延迟保存句柄
        self._h_job = None        # 延迟重算高度句柄
        self._tip = None          # 悬停备注气泡
        self._tip_job = None
        self._tip_hide_job = None
        self.row_widgets = {}
        self.section_widgets = {}
        self.dialog_open = False

        self.interacting = False
        self._last_win_x = None
        self._last_win_y = None
        self._drag = None
        self._press = None          # 按下待定的拖拽
        self._item_drag = None      # 正在进行的列表拖拽
        self._marker = None         # 拖拽插入位置指示线
        self._ghost = None          # 拖拽跟随的小窗

        self.vis = "full"
        self.grace_until = 0.0
        self._anim = None
        self.current_h = INITIAL_H
        self.root = None

        threading.Thread(target=hotkey_thread_main, daemon=True).start()
        for _ in range(100):
            if HOTKEY_HWND[0] is not None: break
            time.sleep(0.05)

    # ------------------------------------------------------------------
    # 数据
    # ------------------------------------------------------------------
    def _load_data(self):
        raw = {}
        try:
            if DATA_FILE.is_file():
                with open(DATA_FILE, "r", encoding="utf-8") as f:
                    raw = json.load(f) or {}
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}

        if "groups" not in raw:
            # ---- v1 -> v2 迁移: 单层 entries 全部放进「默认」分组 ----
            old = raw.pop("entries", []) or []
            g = {"id": uuid.uuid4().hex[:8], "name": "默认", "hotkey": "",
                 "collapsed": False, "entries": []}
            for e in old:
                if not isinstance(e, dict): continue
                g["entries"].append({
                    "id": e.get("id") or uuid.uuid4().hex[:8],
                    "content": e.get("content", ""),
                    "hotkey": e.get("hotkey", ""),
                    "note": e.get("note", ""),
                })
            raw["groups"] = [g]
            raw["active"] = [g["id"]]
            raw["current"] = g["id"]
            raw["_migrated"] = True
        return raw

    def save_data(self):
        self.data["version"] = DATA_VERSION
        self.data["groups"] = self.groups
        self.data["active"] = self.active
        self.data["current"] = self.current_gid
        self.data.pop("entries", None)
        try:
            # 懒加载：只有真正写盘时才创建数据目录
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def schedule_save(self):
        """延迟合并写盘: 打字/连点时不至于每次都写文件"""
        if self.root is None:
            self.save_data()
            return
        try:
            if self._save_job is not None:
                self.root.after_cancel(self._save_job)
            self._save_job = self.root.after(400, self._flush_save)
        except Exception:
            self.save_data()

    def _flush_save(self):
        self._save_job = None
        self.save_data()

    def _new_group_dict(self, name):
        return {"id": uuid.uuid4().hex[:8], "name": name, "hotkey": "",
                "collapsed": False, "entries": []}

    def _unique_name(self, base):
        names = {g["name"] for g in self.groups}
        if base not in names: return base
        i = 2
        while "{}{}".format(base, i) in names:
            i += 1
        return "{}{}".format(base, i)

    def find_group(self, gid):
        for g in self.groups:
            if g["id"] == gid: return g
        return None

    def cur_group(self):
        g = self.find_group(self.current_gid)
        if g is None and self.groups:
            g = self.groups[0]
            self.current_gid = g["id"]
        return g

    def all_entries(self):
        for g in self.groups:
            for e in g.get("entries", []):
                yield g, e

    def find_entry(self, eid):
        for _g, e in self.all_entries():
            if e["id"] == eid: return e
        return None

    def find_entry_ctx(self, eid):
        for g in self.groups:
            for i, e in enumerate(g.get("entries", [])):
                if e["id"] == eid: return g, e, i
        return None, None, -1

    def active_groups(self):
        return [g for g in self.groups if g["id"] in self.active]

    def default_status(self):
        n = len(self.active)
        if n == 0:
            return "未启用任何分组 · 勾选标题左侧的复选框, 该分组的热键才会生效"
        g = self.cur_group()
        if n == 1:
            return "已启用「{}」 · 勾选复选框可同时启用多个分组".format(g["name"] if g else "-")
        names = " · ".join(g["name"] for g in self.active_groups())
        return "已启用 {} 个分组: {}".format(n, names)

    def status(self, text):
        self.status_var.set(text)

    # ------------------------------------------------------------------
    # 分组启用 / 切换
    # ------------------------------------------------------------------
    def after_group_change(self):
        gids = [g["id"] for g in self.groups]
        self.active = [x for x in self.active if x in gids]
        if self.current_gid not in gids:
            self.current_gid = gids[0] if gids else None
        self.save_data()
        self.rebind_all()
        self._rebuild_rows()

    def toggle_active(self, gid, checked=None):
        """复选框: 单纯切换该分组是否生效, 完全不动别的分组, 也不重建界面"""
        g = self.find_group(gid)
        if not g: return
        want = (gid not in self.active) if checked is None else bool(checked)
        if want and gid not in self.active:
            self.active.append(gid)
            msg = "✅ 已启用「{}」: 它的条目热键现在生效".format(g["name"])
        elif (not want) and gid in self.active:
            self.active = [x for x in self.active if x != gid]
            msg = "⏸ 已停用「{}」: 它的热键暂停, 条目仍然可以查看编辑".format(g["name"])
        else:
            return
        self.current_gid = gid
        self.schedule_save()
        self.rebind_all()          # 只重算热键, 不重建界面
        self._refresh_section_states()
        self._refresh_card_borders()
        self.refresh_badges()
        self.status(msg)

    def activate_group(self, gid, exclusive=True, scroll=True):
        """热键用的"切到某分组": 独占/多选启用 + 展开 + 滚动定位 (增量更新, 不重建)"""
        g = self.find_group(gid)
        if not g: return
        changed = False
        if exclusive:
            if self.active != [gid]:
                self.active = [gid]
                changed = True
        elif gid in self.active:
            self.active = [x for x in self.active if x != gid]
            changed = True
        else:
            self.active.append(gid)
            changed = True

        self.current_gid = gid
        g["collapsed"] = False
        self.schedule_save()
        if changed:
            self.rebind_all()
        self._refresh_section_states()
        self._refresh_card_borders()
        self.refresh_badges()
        self._expand_section(gid, True)
        self.status(self.default_status())
        if scroll and gid in self.active:
            self.root.after(30, lambda: self._scroll_to_group(gid))

    def _expand_section(self, gid, expand=True):
        """只显示/隐藏某个分组的内容区(控件都在, 不重建), 秒开"""
        w = self.section_widgets.get(gid)
        if not w or w.get("body") is None: return
        try:
            if expand:
                self._fill_section(gid)
                w["body"].grid()
            else:
                w["body"].grid_remove()
            w["chev"].set_expanded(bool(expand))
        except Exception:
            pass
        # 立即重算高度: 和这次重排合并成一次窗口更新, 避免"先重画再改尺寸"画两遍
        self.update_window_height()

    def _fill_section(self, gid):
        """按需生成分组内的条目卡片 (折叠的分组不生成, 加快首次构建)
        内容条数变了会自动重填, 保证不会残留旧卡片"""
        w = self.section_widgets.get(gid)
        g = self.find_group(gid)
        if not w or not g or w.get("body") is None: return
        entries = g.get("entries", [])
        if w.get("filled") and w.get("filled_n", -1) == len(entries):
            return

        body = w["body"]
        for eid in w.get("card_ids", []):
            self.row_widgets.pop(eid, None)
        for ch in body.winfo_children():
            ch.destroy()
        w["card_ids"] = []

        cols = max(1, int(w.get("cols", 1)))
        for c in range(cols):
            body.grid_columnconfigure(c, weight=1, uniform="col")

        if not entries:
            tk.Label(body, text="这个分组还没有条目 · 点右上角的 ＋ 添加",
                     bg=APP_BG, fg=TEXT_MUTED, font=("Microsoft YaHei UI", 8)).grid(
                row=0, column=0, columnspan=cols, pady=(2, 8), padx=6, sticky="w")
        else:
            for i, entry in enumerate(entries):
                self._build_card(body, g, entry, i // cols, i % cols)
                w["card_ids"].append(entry["id"])
        w["filled"] = True
        w["filled_n"] = len(entries)
        self._refresh_card_borders_for(gid)
        self.refresh_badges()

    def _refresh_card_borders(self):
        """生效分组里的条目卡片画蓝边(纯配色更新, 不重建控件)"""
        on = set()
        for gid in self.active:
            g = self.find_group(gid)
            if not g: continue
            for e in g.get("entries", []):
                on.add(e["id"])
        for eid, w in self.row_widgets.items():
            self._set_card_border(w, eid in on)

    def _refresh_card_borders_for(self, gid):
        g = self.find_group(gid)
        if not g: return
        on = gid in self.active
        for e in g.get("entries", []):
            w = self.row_widgets.get(e["id"])
            if w: self._set_card_border(w, on)

    @staticmethod
    def _set_card_border(w, on):
        try:
            col = CARD_BORDER_ON if on else CARD_BORDER
            w["border"].config(highlightbackground=col, highlightcolor=col)
        except Exception:
            pass

    def cycle_group(self, step):
        if not self.groups: return
        idx = next((i for i, g in enumerate(self.groups) if g["id"] == self.current_gid), 0)
        idx = (idx + step) % len(self.groups)
        g = self.groups[idx]
        self.activate_group(g["id"], exclusive=True)
        self.status("🔀 当前分组: {}".format(g["name"]))

    def add_group(self, name=None):
        g = self._new_group_dict(self._unique_name(name or "新分组"))
        self.groups.append(g)
        self.active.append(g["id"])
        self.current_gid = g["id"]
        self.after_group_change()
        return g

    def _new_group_and_rename(self):
        g = self.add_group()
        self.status("已新建分组, 输入名称后回车")
        self._start_rename(g["id"])

    def duplicate_group(self, gid):
        src = self.find_group(gid)
        if not src: return
        g = self._new_group_dict(self._unique_name(src["name"] + "副本"))
        for e in src.get("entries", []):
            g["entries"].append({
                "id": uuid.uuid4().hex[:8],
                "content": e.get("content", ""),
                "hotkey": e.get("hotkey", ""),
                "note": e.get("note", ""),
            })
        self.groups.append(g)
        self.active.append(g["id"])
        self.current_gid = g["id"]
        self.after_group_change()
        self.status("已复制分组:「{}」".format(g["name"]))

    def rename_group(self, gid, name):
        g = self.find_group(gid)
        name = (name or "").strip()
        if not g or not name or name == g["name"]:
            self._rebuild_rows()
            return
        g["name"] = name
        self.after_group_change()

    def delete_group(self, gid):
        if len(self.groups) <= 1:
            self.status("⚠ 至少要保留一个分组")
            return
        g = self.find_group(gid)
        if not g: return
        n = len(g.get("entries", []))
        if not messagebox.askyesno("删除分组",
                                   "确定删除分组「{}」{}?".format(
                                       g["name"], "及其中 {} 个条目".format(n) if n else ""),
                                   parent=self.root):
            return
        self.groups = [x for x in self.groups if x["id"] != gid]
        self.active = [x for x in self.active if x != gid]
        if self.current_gid == gid:
            self.current_gid = self.active[0] if self.active else self.groups[0]["id"]
        self.after_group_change()
        self.status("🗑 已删除分组")

    def move_group(self, gid, step):
        idx = next((i for i, g in enumerate(self.groups) if g["id"] == gid), -1)
        if idx < 0: return
        j = idx + step
        if j < 0 or j >= len(self.groups): return
        self.groups[idx], self.groups[j] = self.groups[j], self.groups[idx]
        self.after_group_change()

    def toggle_collapse(self, gid):
        g = self.find_group(gid)
        if not g: return
        g["collapsed"] = not bool(g.get("collapsed"))
        self.schedule_save()
        w = self.section_widgets.get(gid)
        if w and w.get("body") is not None:
            self._expand_section(gid, not g["collapsed"])
        else:
            self._rebuild_rows()

    def move_entry(self, eid, target_gid, new_group=False):
        src, e, i = self.find_entry_ctx(eid)
        if src is None or e is None: return
        if new_group:
            tgt = self.add_group()
        else:
            tgt = self.find_group(target_gid)
        if tgt is None or tgt["id"] == src["id"]: return
        src["entries"].pop(i)
        tgt["entries"].append(e)
        self.active.append(tgt["id"]) if tgt["id"] not in self.active else None
        self.current_gid = tgt["id"]
        self.after_group_change()
        self.status("➡ 已移动到「{}」".format(tgt["name"]))

    def add_entry(self, gid):
        """分组标题栏的 ＋ : 直接在该分组里新建一个条目并聚焦输入框"""
        g = self.find_group(gid)
        if not g: return
        was_off = gid not in self.active
        eid = uuid.uuid4().hex[:8]
        g.setdefault("entries", []).append({"id": eid, "content": "", "hotkey": "", "note": ""})
        g["collapsed"] = False
        if was_off:
            self.active.append(gid)
        self.current_gid = gid
        self.save_data()
        self.rebind_all()
        self._rebuild_rows()
        self.root.after(40, lambda: self._focus_entry(eid))
        self.status("➕ 已新增条目到「{}」{}, 直接输入即可 (留空点别处会自动取消)".format(
            g["name"], "并让该分组生效" if was_off else ""))

    def _focus_entry(self, eid):
        w = self.row_widgets.get(eid)
        if not w: return
        try:
            w["entry"].focus_set()
            w["entry"].icursor(tk.END)
        except Exception:
            pass

    def _drop_if_empty(self, eid):
        """新建后没输入任何内容就离开 -> 自动取消, 不留空条目"""
        g, e, _i = self.find_entry_ctx(eid)
        if g is None or e is None: return
        if (e.get("content") or "").strip(): return
        if (e.get("hotkey") or "").strip(): return
        self.delete_entry_by_id(eid)
        self.status("已取消空条目")

    # ------------------------------------------------------------------
    # 窗口
    # ------------------------------------------------------------------
    def _set_geometry(self, x, y, w, h):
        """完全避开 Tkinter 处理负坐标时的 Bug，使用原生 API 定位"""
        try:
            h_id = self.root.winfo_id()
            hwnd = user32.GetParent(h_id)
            if not hwnd:
                hwnd = h_id
            user32.SetWindowPos(ctypes.c_void_p(hwnd), 0, int(x), int(y), int(w), int(h), 0x0014)
        except Exception:
            sx = "+{}".format(int(x)) if x >= 0 else "{}".format(int(x))
            sy = "+{}".format(int(y)) if y >= 0 else "{}".format(int(y))
            self.root.geometry("{}x{}{}{}".format(int(w), int(h), sx, sy))

    def run(self):
        root = tk.Tk()
        self.root = root
        root.title("EdgePaste 贴边快输")
        root.overrideredirect(True)
        root.attributes("-topmost", True)

        root.configure(bg=CARD_BORDER)
        self.main_container = tk.Frame(root, bg=APP_BG)
        self.main_container.pack(fill="both", expand=True, padx=1, pady=1)

        root.geometry("{}x{}".format(self.win_w, self.current_h))
        self._build_ui()
        self._restore_position()
        self.rebind_all()
        self._poll()
        self._poll_events()
        root.mainloop()

    def _build_ui(self):
        # ---------------------------------------------------------- 顶栏
        self.header = tk.Frame(self.main_container, bg=HEADER_BG, height=38)
        self.header.pack(fill="x")
        self.header.pack_propagate(False)

        title = tk.Label(self.header, text="贴边快输", bg=HEADER_BG, fg=TEXT_TITLE,
                         font=("Microsoft YaHei UI", 11, "bold"))
        title.pack(side="left", padx=(14, 8))

        def hbtn(text, cmd, tip=None):
            b = tk.Label(self.header, text=text, bg=HEADER_BG, fg=TEXT_MAIN,
                         font=("Microsoft YaHei UI", 9), cursor="hand2")
            b.pack(side="left", padx=6)

            def on_enter(_e, _b=b, _t=tip):
                _b.config(fg=ACCENT)
                if _t: self.status(_t)

            def on_leave(_e, _b=b):
                _b.config(fg=TEXT_MAIN)
                self.status(self.default_status())

            b.bind("<Button-1>", lambda e: cmd())
            b.bind("<Enter>", on_enter)
            b.bind("<Leave>", on_leave)
            return b

        hbtn("分组", self.open_group_manager, "分组管理: 新建 / 重命名 / 切换热键 / 排序 / 删除")
        hbtn("设置", self.open_settings, "设置: 面板热键 / 循环切换热键 / 吸附 / 列数")

        btn_frame = tk.Frame(self.header, bg=HEADER_BG)
        btn_frame.pack(side="right", fill="y")

        min_btn = tk.Label(btn_frame, text="—", bg=HEADER_BG, fg=TEXT_MAIN, font=("Microsoft YaHei", 10), width=4)
        min_btn.pack(side="left", fill="y")
        min_btn.bind("<Enter>", lambda e: min_btn.config(bg="#f1f5f9"))
        min_btn.bind("<Leave>", lambda e: min_btn.config(bg=HEADER_BG))
        min_btn.bind("<Button-1>", lambda e: self.hide_to_gone())

        close_btn = tk.Label(btn_frame, text="✕", bg=HEADER_BG, fg=TEXT_MAIN, font=("Microsoft YaHei", 10), width=4)
        close_btn.pack(side="left", fill="y")
        close_btn.bind("<Enter>", lambda e: close_btn.config(bg="#ef4444", fg="#ffffff"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(bg=HEADER_BG, fg=TEXT_MAIN))
        close_btn.bind("<Button-1>", lambda e: self.quit_app())

        for w in (self.header, title):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)
            w.bind("<ButtonRelease-1>", self._drag_release)

        tk.Frame(self.main_container, bg=HEADER_BORDER, height=1).pack(fill="x")

        # ---------------------------------------------------------- 边缘调整宽度感应区
        self.left_grip = tk.Frame(self.root, bg=CARD_BORDER, cursor="sb_h_double_arrow")
        self.left_grip.place(x=0, y=0, width=4, relheight=1.0)
        self.left_grip.bind("<Button-1>", self._resize_left_start)
        self.left_grip.bind("<B1-Motion>", self._resize_left_move)
        self.left_grip.bind("<ButtonRelease-1>", self._resize_release)

        self.right_grip = tk.Frame(self.root, bg=CARD_BORDER, cursor="sb_h_double_arrow")
        self.right_grip.place(relx=1.0, x=-4, y=0, width=4, relheight=1.0)
        self.right_grip.bind("<Button-1>", self._resize_right_start)
        self.right_grip.bind("<B1-Motion>", self._resize_right_move)
        self.right_grip.bind("<ButtonRelease-1>", self._resize_release)

        # ---------------------------------------------------------- 列表
        body = tk.Frame(self.main_container, bg=APP_BG)
        body.pack(fill="both", expand=True, padx=6, pady=6)

        self.canvas = tk.Canvas(body, bg=APP_BG, highlightthickness=0, bd=0)
        self.scroll = tk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.list_frame = tk.Frame(self.canvas, bg=APP_BG)
        self._win_id = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")

        self.list_frame.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win_id, width=e.width))
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-int(e.delta / 120), "units"))

        self.status_var = tk.StringVar(value=self.default_status())
        self.status_bar = tk.Label(self.main_container, textvariable=self.status_var, bg=APP_BG, fg=TEXT_MUTED,
                                   font=("Microsoft YaHei UI", 8), anchor="w")
        self.status_bar.pack(fill="x", side="bottom", padx=8, pady=(0, 4))

        self._rebuild_rows()

        self.root.bind("<Button-1>", lambda e: self._touch())

        menu = tk.Menu(self.root, tearoff=0, bg="#ffffff", fg=TEXT_TITLE, activebackground=ACCENT,
                       activeforeground=ACCENT_FG, bd=0)
        menu.add_command(label="显示/隐藏面板", command=self.toggle_vis)
        menu.add_separator()
        menu.add_command(label="新建分组", command=self._new_group_and_rename)
        menu.add_command(label="分组管理…", command=self.open_group_manager)
        menu.add_command(label="设置", command=self.open_settings)
        menu.add_command(label="帮助", command=self.show_help)
        menu.add_separator()
        menu.add_command(label="退出", command=self.quit_app)
        self.header.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

    # ------------------------------------------------------------------
    # 分组列表 (QQ 风格: 纵向堆叠的分组标题; 生效中的分组高亮)
    # ------------------------------------------------------------------
    def _is_collapsed(self, g):
        return bool(g.get("collapsed"))

    def _refresh_section_states(self):
        """只更新已存在的分组标题行(不重建控件), 用于热键状态变化后刷新"""
        for gid, w in self.section_widgets.items():
            g = self.find_group(gid)
            if not g: continue
            enabled = gid in self.active
            cur = gid == self.current_gid
            st = self.group_status.get(gid, "none")
            band, border = self._band_colors(enabled, cur)
            fg = ACCENT if enabled else TEXT_MUTED

            try:
                w["wrap"].config(bg=border)
                w["head"].config(bg=band)
                w["bar"].config(bg=ACCENT if enabled else band)
                for key in ("name", "cnt", "hkl", "add"):
                    w[key].config(bg=band)
                w["name"].config(fg=ACCENT if enabled else (TEXT_TITLE if cur else TEXT_MUTED))
                w["chev"].config_colors(band, ACCENT if enabled else TEXT_MUTED)
                w["chev"].set_expanded(not self._is_collapsed(g))
                w["chk"].config_bg(band)
                w["chk"].set_checked(enabled)
                w["add"].config(fg=TEXT_MUTED)

                hk = (g.get("hotkey") or "").strip()
                if st == "conflict":
                    w["hkl"].config(text=(hk + " ⚠") if hk else "⚠", fg=BADGE_RED_FG)
                elif st == "invalid":
                    w["hkl"].config(text="⚠ 格式", fg=BADGE_RED_FG)
                else:
                    w["hkl"].config(text=hk, fg=BADGE_FG if enabled else TEXT_MUTED)
                w["cnt"].config(text="{} 条".format(len(g.get("entries", []))))
            except Exception:
                pass

    def _band_colors(self, enabled, cur):
        """生效中的分组 -> 醒目的高亮底色 + 同色描边"""
        if enabled:
            return (BAND_ON_CUR if cur else BAND_ON), ACCENT
        return (BAND_OFF_CUR if cur else BAND_OFF), (BORDER_OFF_CUR if cur else BAND_OFF)

    def _start_rename(self, gid):
        w = self.section_widgets.get(gid)
        g = self.find_group(gid)
        if not w or not g: return
        name_lbl = w["name"]
        parent = name_lbl.master
        var = tk.StringVar(value=g["name"])
        ent = tk.Entry(parent, textvariable=var, bg="#ffffff", fg=TEXT_TITLE, relief="flat",
                       font=("Microsoft YaHei UI", 9, "bold"), width=max(4, len(g["name"]) + 2),
                       insertbackground=TEXT_MAIN)
        name_lbl.pack_forget()
        ent.pack(side="left", after=w["chk"])
        ent.focus_set()
        ent.select_range(0, "end")
        done = {"v": False}

        def finish(ok=True):
            if done["v"]: return
            done["v"] = True
            if ok:
                self.rename_group(gid, var.get())
            else:
                self._rebuild_rows()

        ent.bind("<Return>", lambda e: finish(True))
        ent.bind("<Escape>", lambda e: finish(False))
        ent.bind("<FocusOut>", lambda e: finish(True))

    def _group_menu(self, event, gid):
        g = self.find_group(gid)
        if not g: return
        on = gid in self.active
        m = tk.Menu(self.root, tearoff=0, bg="#ffffff", fg=TEXT_TITLE,
                    activebackground=ACCENT, activeforeground=ACCENT_FG, bd=0)
        m.add_command(label=("☑ 生效中 — 点击停用" if on else "☐ 未生效 — 点击启用"),
                      command=lambda: self.toggle_active(gid))
        m.add_command(label=("只启用这一个分组 (中键)" if len(self.active) != 1 or not on else "只保留这一个"),
                      command=lambda: self.activate_group(gid, exclusive=True, scroll=False))
        m.add_separator()
        m.add_command(label="在「{}」新增条目".format(g["name"]), command=lambda: self.add_entry(gid))
        m.add_command(label=("折叠" if not g.get("collapsed") else "展开"),
                      command=lambda: self.toggle_collapse(gid))
        m.add_separator()
        m.add_command(label="重命名", command=lambda: self._start_rename(gid))
        m.add_command(label="复制该分组", command=lambda: self.duplicate_group(gid))
        m.add_command(label="新建分组", command=self._new_group_and_rename)
        m.add_separator()
        m.add_command(label="上移", command=lambda: self.move_group(gid, -1))
        m.add_command(label="下移", command=lambda: self.move_group(gid, 1))
        m.add_separator()
        m.add_command(label="删除分组", command=lambda: self.delete_group(gid))
        m.add_separator()
        m.add_command(label="分组管理…", command=self.open_group_manager)
        m.add_separator()
        m.add_command(label="提示: 直接拖动标题也能排序", state="disabled")
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    # ------------------------------------------------------------------
    # 拖拽: 分组排序 / 条目跨分组移动 (QQ 风格)
    # ------------------------------------------------------------------
    def _bind_dnd(self):
        self.root.bind("<B1-Motion>", self._dnd_motion)
        self.root.bind("<ButtonRelease-1>", self._dnd_release)

    def _unbind_dnd(self):
        for seq in ("<B1-Motion>", "<ButtonRelease-1>"):
            try:
                self.root.unbind(seq)
            except Exception:
                pass

    def _dnd_press(self, event, kind, key, click=None):
        if key is None: return
        self._press = {"kind": kind, "key": key, "x": event.x_root, "y": event.y_root,
                       "click": click}
        self._bind_dnd()

    def _dnd_motion(self, event):
        p = self._press
        if p is None: return
        if self._item_drag is None:
            if abs(event.x_root - p["x"]) < 4 and abs(event.y_root - p["y"]) < 4:
                return
            self.interacting = True
            self._item_drag = {"kind": p["kind"], "key": p["key"], "target": None, "index": 0}
            self._make_ghost(p["kind"], p["key"])
        self._move_ghost(event.x_root, event.y_root)
        self._auto_scroll(event.y_root)
        if self._item_drag["kind"] == "group":
            self._drag_group_over(event.y_root)
        else:
            self._drag_entry_over(event.y_root)

    def _dnd_release(self, event):
        self._unbind_dnd()
        p, d = self._press, self._item_drag
        self._press = None
        self._item_drag = None
        self._destroy_ghost()
        self._hide_marker()
        self.interacting = False
        self.grace_until = time.time() + 0.3

        if d is None:
            # 没移动 = 普通点击
            if p and p.get("click"):
                p["click"]()
            return
        if d["kind"] == "group":
            self.schedule_save()
            g = self.find_group(d["key"])
            self.status("↕ 已调整分组顺序: {}".format(g["name"] if g else ""))
        elif d.get("target"):
            self.move_entry_to_index(d["key"], d["target"], d.get("index", 0))

    def _make_ghost(self, kind, key):
        if kind == "group":
            g = self.find_group(key)
            icon, text = "↕  ", (g or {}).get("name", "")
        else:
            e = self.find_entry(key)
            text = ((e or {}).get("content", "") or "条目")
            text = text[:20] + ("…" if len(text) > 20 else "")
            icon = "➡  "
        try:
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            try:
                t.attributes("-alpha", 0.93)
            except Exception:
                pass
            outer = tk.Frame(t, bg=ACCENT, padx=1, pady=1)
            outer.pack()
            tk.Label(outer, text=icon + text, bg="#ffffff", fg=TEXT_TITLE,
                     font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=4).pack()
            self._ghost = t
        except Exception:
            self._ghost = None

    def _move_ghost(self, x, y):
        if not self._ghost: return
        try:
            self._ghost.geometry("+{}+{}".format(int(x) + 14, int(y) + 12))
        except Exception:
            pass

    def _destroy_ghost(self):
        if self._ghost:
            try:
                self._ghost.destroy()
            except Exception:
                pass
            self._ghost = None

    def _show_marker(self, y_in_list):
        try:
            if self._marker is None or not self._marker.winfo_exists():
                self._marker = tk.Frame(self.list_frame, bg=ACCENT, height=3)
            self._marker.place(x=2, y=max(0, int(y_in_list)), relwidth=1.0, width=-4)
            self._marker.lift()
        except Exception:
            pass

    def _hide_marker(self):
        try:
            if self._marker is not None and self._marker.winfo_exists():
                self._marker.place_forget()
        except Exception:
            pass

    def _auto_scroll(self, y_root):
        try:
            top = self.canvas.winfo_rooty()
            h = self.canvas.winfo_height()
            if y_root < top + 18:
                self.canvas.yview_scroll(-1, "units")
            elif y_root > top + h - 18:
                self.canvas.yview_scroll(1, "units")
        except Exception:
            pass

    def _visible_sections(self):
        out = []
        for g in self.groups:
            w = self.section_widgets.get(g["id"])
            if w: out.append((g, w))
        return out

    def _body_shown(self, w):
        try:
            body = w.get("body")
            return bool(body is not None and body.winfo_ismapped())
        except Exception:
            return False

    def _section_at(self, y_root):
        secs = self._visible_sections()
        for i, (g, w) in enumerate(secs):
            head = w["head"]
            top = head.winfo_rooty()
            if i + 1 < len(secs):
                bottom = secs[i + 1][1]["head"].winfo_rooty()
            else:
                bottom = self.list_frame.winfo_rooty() + self.list_frame.winfo_height()
            if self._body_shown(w):
                bottom = max(bottom, w["body"].winfo_rooty() + w["body"].winfo_height())
            if top <= y_root < bottom:
                return g["id"], w
        return None

    def _cards_of(self, gid):
        """该分组当前可见的条目卡片(按显示顺序), 折叠时不返回"""
        g = self.find_group(gid)
        if not g: return []
        w = self.section_widgets.get(gid)
        if w is None or not self._body_shown(w):
            return []
        out = []
        for e in g.get("entries", []):
            rw = self.row_widgets.get(e["id"])
            if rw: out.append((e["id"], rw["border"]))
        out.sort(key=lambda t: (t[1].winfo_y(), t[1].winfo_x()))
        return out

    def _drag_group_over(self, y_root):
        gid = self._item_drag["key"]
        secs = self._visible_sections()
        if len(secs) < 2: return
        pos = len(secs)
        for i, (_g, w) in enumerate(secs):
            head = w["head"]
            if y_root < head.winfo_rooty() + head.winfo_height() // 2:
                pos = i
                break
        vis_ids = [g["id"] for g, _w in secs]
        if gid not in vis_ids: return
        cur = vis_ids.index(gid)
        ins = pos if pos <= cur else pos - 1
        desired = [x for x in vis_ids if x != gid]
        desired.insert(max(0, min(ins, len(desired))), gid)
        if desired == vis_ids: return

        by_id = {g["id"]: g for g in self.groups}
        slots = [i for i, g in enumerate(self.groups) if g["id"] in vis_ids]
        for slot, want in zip(slots, desired):
            self.groups[slot] = by_id[want]
        self._rebuild_rows()

    def _drag_entry_over(self, y_root):
        d = self._item_drag
        hit = self._section_at(y_root)
        if hit is None:
            d["target"] = None
            self._hide_marker()
            return
        gid, w = hit
        g = self.find_group(gid)
        if g is None:
            d["target"] = None
            self._hide_marker()
            return

        base = self.list_frame.winfo_rooty()
        shown = self._body_shown(w)
        cards = self._cards_of(gid) if shown else []
        idx, y_rel = len(cards), None
        for k, (_eid, wid) in enumerate(cards):
            top = wid.winfo_rooty() - base
            if y_root - base < top + wid.winfo_height() // 2:
                idx, y_rel = k, top - 2
                break
        if y_rel is None:
            if cards:
                last = cards[-1][1]
                y_rel = last.winfo_rooty() - base + last.winfo_height() + 1
            elif shown:
                y_rel = w["body"].winfo_rooty() - base + 2
            else:
                head = w["head"]
                y_rel = head.winfo_rooty() - base + head.winfo_height() + 1

        d["target"] = gid
        d["index"] = idx
        self._show_marker(y_rel)

    def move_entry_to_index(self, eid, target_gid, index):
        src_g, e, i = self.find_entry_ctx(eid)
        tgt = self.find_group(target_gid)
        if src_g is None or e is None or tgt is None: return
        same = (src_g["id"] == tgt["id"])
        index = int(index)
        if same and (i == index or i + 1 == index):
            return
        src_g["entries"].pop(i)
        if same and i < index:
            index -= 1
        index = max(0, min(index, len(tgt["entries"])))
        tgt["entries"].insert(index, e)
        if tgt["id"] not in self.active:
            self.active.append(tgt["id"])
        tgt["collapsed"] = False
        self.current_gid = tgt["id"]
        self.after_group_change()
        self.status("➡ 已移动到「{}」第 {} 位".format(tgt["name"], index + 1))

    def _scroll_to_group(self, gid):
        w = self.section_widgets.get(gid)
        if not w: return
        try:
            self.list_frame.update_idletasks()
            total = max(1, self.canvas.bbox("all")[3])
            y = w["head"].winfo_y()
            self.canvas.yview_moveto(max(0.0, min(1.0, (y - 4) / float(total))))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 边缘缩放
    # ------------------------------------------------------------------
    def _resize_right_start(self, event):
        self.interacting = True
        self._resize_start_x = event.x_root
        self._resize_start_w = self.win_w

    def _resize_right_move(self, event):
        dx = event.x_root - self._resize_start_x
        new_w = max(250, self._resize_start_w + dx)
        self.win_w = new_w
        self._set_geometry(self.win.get("x", self.root.winfo_x()), self.win.get("y", self.root.winfo_y()), self.win_w,
                           self.current_h)

    def _resize_left_start(self, event):
        self.interacting = True
        self._resize_start_x = event.x_root
        self._resize_start_w = self.win_w
        self._resize_start_win_x = self.win.get("x", self.root.winfo_x())

    def _resize_left_move(self, event):
        dx = event.x_root - self._resize_start_x
        new_w = self._resize_start_w - dx
        if new_w >= 250:
            new_x = self._resize_start_win_x + dx
            self.win_w = new_w
            self.win["x"] = new_x
            self._set_geometry(new_x, self.win.get("y", self.root.winfo_y()), self.win_w, self.current_h)

    def _resize_release(self, event):
        self.interacting = False
        self.grace_until = time.time() + 0.3
        self.settings["win_w"] = self.win_w
        self.save_data()

    # ------------------------------------------------------------------
    # 窗口高度
    # ------------------------------------------------------------------
    def _queue_height(self, delay=10):
        """合并多次高度重算, 避免连续操作时反复做几何计算"""
        try:
            if self._h_job is not None:
                self.root.after_cancel(self._h_job)
            self._h_job = self.root.after(delay, self._run_height)
        except Exception:
            self.update_window_height()

    def _run_height(self):
        self._h_job = None
        self.update_window_height()

    def update_window_height(self):
        self.list_frame.update_idletasks()
        h_header = max(self.header.winfo_height(), self.header.winfo_reqheight()) + 1
        h_status = self.status_bar.winfo_reqheight() + 4
        h_padding = 12

        h_list = self.list_frame.winfo_reqheight()
        total_h = h_header + h_list + h_status + h_padding + 2

        pos = self._cursor()
        max_h = 800
        if pos:
            r = self._monitor_rect_at(pos[0], pos[1]) or self._primary_rect()
            max_h = int((r[3] - r[1]) * 0.85)

        new_h = min(total_h, max_h)

        if total_h <= max_h:
            self.scroll.pack_forget()
        else:
            self.scroll.pack(side="right", fill="y")

        if new_h != self.current_h:
            self.current_h = new_h
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))
            if self.vis == "full":
                dock = self.win.get("dock")
                x = self.win.get("x", self.root.winfo_x())
                y = self.win.get("y", self.root.winfo_y())
                if dock == "bottom":
                    rect = self.get_dock_rect()
                    y = rect[3] - self.current_h
                    self.win["y"] = y
                self._set_geometry(x, y, self.win_w, self.current_h)

    def _touch(self):
        if self.interacting: return
        self.grace_until = time.time() + 0.3
        if self.vis == "strip":
            self.set_vis("full")

    # ------------------------------------------------------------------
    # 列表: 分组区块 + 条目卡片
    # ------------------------------------------------------------------
    def _rebuild_rows(self):
        if not hasattr(self, "list_frame"): return
        self._tip_hide()
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.row_widgets = {}
        self.section_widgets = {}
        self._marker = None          # 列表重建, 插入线控件已随之销毁

        # 彻底清空残余的列配置，确保从多列切回少列时宽度能立刻占满
        for c in range(10):
            self.list_frame.grid_columnconfigure(c, weight=0, uniform="")
        self.list_frame.grid_columnconfigure(0, weight=1)

        show_inactive = bool(self.settings.get("show_inactive", True))
        row = 0
        for g in self.groups:
            if (not show_inactive) and g["id"] not in self.active:
                continue
            row = self._build_section(g, row)

        self._build_add_group_row(row)
        self._refresh_section_states()
        self.refresh_badges()
        self._queue_height(30)

        # 条目卡片分批填充: 面板先出现(标题全在), 卡片随后立刻补上 -> 开局不卡
        self._fill_gen = getattr(self, "_fill_gen", 0) + 1
        self._pending_fill = [g["id"] for g in self.groups
                              if g["id"] in self.section_widgets and not self._is_collapsed(g)]
        if self._pending_fill:
            self.root.after(1, lambda: self._fill_chunk(self._fill_gen))

    def _fill_chunk(self, gen):
        if gen != getattr(self, "_fill_gen", 0): return
        if not getattr(self, "_pending_fill", None): return
        gid = self._pending_fill.pop(0)
        try:
            if gid in self.section_widgets:
                self._fill_section(gid)
                self._queue_height(40)
        except Exception:
            pass
        if self._pending_fill:
            self.root.after(1, lambda: self._fill_chunk(gen))

    def _build_add_group_row(self, row):
        bar = tk.Frame(self.list_frame, bg=APP_BG, cursor="hand2")
        bar.grid(row=row, column=0, sticky="we", padx=2, pady=(8, 4))

        lbl = tk.Label(bar, text="＋  新建分组", bg=APP_BG, fg=TEXT_MUTED,
                       font=("Microsoft YaHei UI", 9), anchor="w")
        lbl.pack(side="left", padx=4, pady=4)

        def enter(_e):
            lbl.config(fg=ACCENT)
            self.status("新建一个分组")

        def leave(_e):
            lbl.config(fg=TEXT_MUTED)
            self.status(self.default_status())

        for w in (bar, lbl):
            w.bind("<Button-1>", lambda e: self._new_group_and_rename())
            w.bind("<Enter>", enter)
            w.bind("<Leave>", leave)

    def _build_section(self, g, row):
        gid = g["id"]
        enabled = gid in self.active
        cur = (gid == self.current_gid)
        collapsed = bool(g.get("collapsed"))
        band, border = self._band_colors(enabled, cur)

        # --- 分组标题条外框(生效中的分组 -> 蓝色描边, 一眼看出哪组在生效) ---
        wrap = tk.Frame(self.list_frame, bg=border, padx=1, pady=1)
        wrap.grid(row=row, column=0, sticky="we", padx=1, pady=(4, 1))
        row += 1

        # --- 分组标题条: [┃][▾][☑] 名称 ...... [F1] [3 条] [＋] ---
        head = tk.Frame(wrap, bg=band, cursor="hand2")
        head.pack(fill="x")

        bar = tk.Frame(head, bg=ACCENT if enabled else band, width=3)
        bar.pack(side="left", fill="y")

        chev = Disclosure(head, band, ACCENT if enabled else TEXT_MUTED, size=12, box=20,
                          command=lambda x=gid: self.toggle_collapse(x))
        chev.pack(side="left", padx=(2, 0))

        chk = CheckBox(head, band, size=14, box=20, checked=enabled,
                       command=lambda v, x=gid: self.toggle_active(x, v))
        chk.pack(side="left", padx=(1, 0))

        name = tk.Label(head, text=g["name"], bg=band,
                        fg=ACCENT if enabled else (TEXT_TITLE if cur else TEXT_MUTED),
                        font=("Microsoft YaHei UI", 9, "bold"))
        name.pack(side="left", padx=(6, 0))

        # 右侧: ＋新增条目 | 条数 | 切换热键
        add_btn = tk.Label(head, text="＋", bg=band, fg=TEXT_MUTED,
                           font=("Microsoft YaHei UI", 11, "bold"), cursor="hand2", padx=5)
        add_btn.pack(side="right", padx=(0, 3), pady=1)

        cnt = tk.Label(head, text="{} 条".format(len(g.get("entries", []))), bg=band,
                       fg=BADGE_FG if enabled else TEXT_MUTED, font=("Microsoft YaHei UI", 8))
        cnt.pack(side="right", padx=(0, 4))

        hk = (g.get("hotkey") or "").strip()
        st = self.group_status.get(gid, "none")
        hkl = tk.Label(head, text=hk, bg=band, fg=BADGE_FG if enabled else TEXT_MUTED,
                       font=("Consolas", 8, "bold"))
        if st == "conflict":
            hkl.config(text=(hk + " ⚠") if hk else "⚠", fg=BADGE_RED_FG)
        elif st == "invalid":
            hkl.config(text="⚠ 格式", fg=BADGE_RED_FG)
        if hk:
            hkl.pack(side="right", padx=(0, 8))

        self.section_widgets[gid] = {"head": head, "body": None, "wrap": wrap, "bar": bar,
                                     "chev": chev, "chk": chk, "name": name, "cnt": cnt,
                                     "hkl": hkl, "add": add_btn}

        # ---- 交互 ----
        def on_enter(_e, _g=g, _en=enabled):
            hot = "  切换热键 {}".format(_g["hotkey"]) if _g.get("hotkey") else ""
            self.status("「{}」{} · {} 条{} · 点标题=展开折叠 勾选框=生效 中键=只勾这一个 拖动=排序 ＋=新增".format(
                _g["name"], "●生效中" if _en else "未生效", len(_g.get("entries", [])), hot))

        def on_leave(_e):
            self.status(self.default_status())

        def add_enter(_e):
            add_btn.config(fg=ACCENT)
            self.status("在「{}」里新增一个条目".format(g["name"]))

        def add_leave(_e):
            add_btn.config(fg=TEXT_MUTED)
            self.status(self.default_status())

        add_btn.bind("<Button-1>", lambda e, x=gid: self.add_entry(x))
        add_btn.bind("<Enter>", add_enter)
        add_btn.bind("<Leave>", add_leave)

        chev.bind("<Button-3>", lambda e, x=gid: self._group_menu(e, x))
        chk.bind("<Button-3>", lambda e, x=gid: self._group_menu(e, x))

        # 点标题/名称 = 展开折叠(不动别的分组); 按住拖动 = 调整分组顺序
        for w in (head, name, cnt, hkl, bar, wrap):
            w.bind("<Button-1>", lambda e, x=gid: self._dnd_press(
                e, "group", x, lambda y=x: self.toggle_collapse(y)))
            w.bind("<Button-2>", lambda e, x=gid: self.activate_group(x, exclusive=True, scroll=False))
            w.bind("<Button-3>", lambda e, x=gid: self._group_menu(e, x))
            w.bind("<Double-Button-1>", lambda e, x=gid: self._start_rename(x))
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

        # --- 组内条目 (内容区先占位, 卡片按需生成; 折叠只是隐藏 -> 展开/折叠秒开) ---
        cols = max(1, int(self.settings.get("columns", 1)))
        body = tk.Frame(self.list_frame, bg=APP_BG)
        body.grid(row=row, column=0, sticky="we")
        self.section_widgets[gid]["body"] = body
        self.section_widgets[gid]["cols"] = cols
        self.section_widgets[gid]["filled"] = False
        row += 1

        if collapsed:
            body.grid_remove()
        # 非折叠的分组不在这里立刻生成卡片, 由 _fill_chunk 分批填充(开局不卡)
        else:
            self.section_widgets[gid]["filled"] = False
            self.section_widgets[gid]["filled_n"] = -1

        return row

    def _build_card(self, parent, group, entry, r=0, c=0):
        gid = group["id"]
        eid = entry["id"]
        active = gid in self.active

        # 一层 Frame + highlightthickness 当描边: 生效分组蓝色, 其余灰色 (省一层控件)
        bcol = CARD_BORDER_ON if active else CARD_BORDER
        card_border = tk.Frame(parent, bg=CARD_BG, highlightthickness=1,
                               highlightbackground=bcol, highlightcolor=bcol)
        card_border.grid(row=r, column=c, sticky="nsew", padx=4, pady=4)

        card_bg = card_border

        # 拖拽握把 (把条目拖到别的分组, 或组内排序)
        grip = tk.Label(card_bg, text="≡", bg=CARD_BG, fg=CARD_BORDER,
                        font=("Microsoft YaHei UI", 11, "bold"), cursor="fleur", padx=2)
        grip.pack(side="left", padx=(5, 0), pady=8)

        badge_text = "未设"
        b_bg = BADGE_BG
        b_fg = BADGE_FG

        badge = tk.Label(card_bg, text=badge_text, bg=b_bg, fg=b_fg,
                         font=("Consolas", 8, "bold"), cursor="hand2", takefocus=1, padx=8)
        badge.pack(side="left", padx=(8, 0), pady=10, fill="y")

        content_var = tk.StringVar(value=entry.get("content", ""))
        entry_widget = tk.Entry(card_bg, textvariable=content_var, bg=CARD_BG, fg=TEXT_TITLE,
                                insertbackground=TEXT_MAIN, relief="flat", font=("Microsoft YaHei UI", 10))
        entry_widget.pack(side="left", fill="both", expand=True, padx=8, pady=10)

        del_btn = tk.Label(card_bg, text="✕", bg=CARD_BG, fg=TEXT_MUTED, font=("Microsoft YaHei UI", 10),
                           cursor="hand2")

        # 有备注才显示的小标记(备注本身只在悬停时弹气泡)
        note_lbl = tk.Label(card_bg, text="注", bg=CARD_BG, fg=TEXT_MUTED, font=("Microsoft YaHei UI", 7),
                            cursor="hand2")
        if (entry.get("note") or "").strip():
            note_lbl.pack(side="right", padx=(0, 4))
        note_lbl.bind("<Button-1>", lambda e, x=eid: self.open_note_dialog(x))
        note_lbl.bind("<Enter>", lambda e: (note_lbl.config(fg=ACCENT),
                                            self.status("备注: {}".format(
                                                (self.find_entry(eid) or {}).get("note", "")))))
        note_lbl.bind("<Leave>", lambda e: (note_lbl.config(fg=TEXT_MUTED),
                                            self.status(self.default_status())))

        def on_enter(e):
            card_bg.config(bg=CARD_HOVER)
            entry_widget.config(bg=CARD_HOVER)
            del_btn.config(bg=CARD_HOVER)
            note_lbl.config(bg=CARD_HOVER)
            grip.config(bg=CARD_HOVER, fg=ACCENT)
            del_btn.pack(side="right", padx=(5, 10))
            self._tip_schedule(eid)

        def on_leave(e):
            card_bg.config(bg=CARD_BG)
            entry_widget.config(bg=CARD_BG)
            del_btn.config(bg=CARD_BG)
            note_lbl.config(bg=CARD_BG)
            grip.config(bg=CARD_BG, fg=CARD_BORDER)
            del_btn.pack_forget()
            self._tip_leave()

        for w in (card_bg, badge, entry_widget, del_btn, grip, note_lbl):
            w.bind("<Enter>", on_enter, add="+")
            w.bind("<Leave>", on_leave, add="+")

        grip.bind("<Button-1>", lambda e, x=eid: self._dnd_press(e, "entry", x))
        grip.bind("<Button-3>", lambda e, x=eid: self._entry_menu(e, x, gid))
        grip.bind("<Enter>", lambda e: self.status("拖动这里: 可拖到别的分组, 也可调整组内顺序"), add="+")
        grip.bind("<Leave>", lambda e: self.status(self.default_status()), add="+")
        for w in (card_bg, card_border):
            w.bind("<Button-1>", lambda e, x=eid: self._dnd_press(e, "entry", x))
            w.bind("<Button-3>", lambda e, x=eid: self._entry_menu(e, x, gid))

        # 新建后没输入就离开 -> 自动取消这条空条目
        entry_widget.bind("<FocusOut>",
                          lambda e: self.root.after(10, lambda: self._drop_if_empty(eid)))

        def on_badge_enter(e):
            badge.focus_set()
            badge.config(text="录制中", bg=ACCENT, fg=ACCENT_FG)
            self.clear_hotkeys()   # 极度核心: 挂起全局拦截系统, 百分百捕捉用户按键

        def on_badge_leave(e):
            self.root.focus_set()
            self.refresh_badges()
            self.rebind_all()      # 鼠标移开, 无缝恢复系统全局快捷键拦截

        def on_badge_keypress(e):
            if e.keysym in MOD_KEYSYMS: return

            if e.keysym == "Escape":
                en = self.find_entry(eid)
                if en:
                    en["hotkey"] = ""
                    self.save_data()
                    self.status("🚫 已清除快捷键")
                    self.refresh_badges()
                return "break"

            hk = compose_hotkey(e)
            if not hk: return "break"

            # 只在本分组内去重; 其它分组允许使用相同的热键(这就是分组的意义)
            for other in group.get("entries", []):
                if other["id"] != eid and (other.get("hotkey") or "").strip().lower() == hk.lower():
                    other["hotkey"] = ""

            en = self.find_entry(eid)
            if en:
                en["hotkey"] = hk
                self.save_data()
                self.status("✅ 快捷键设为: {}{}".format(hk, self._hotkey_warning(hk, group)))
                self.refresh_badges()
            return "break"

        badge.bind("<Enter>", on_badge_enter, add="+")
        badge.bind("<Leave>", on_badge_leave, add="+")
        badge.bind("<KeyPress>", on_badge_keypress)

        def do_delete(e):
            self.delete_entry_by_id(eid)

        del_btn.bind("<Button-1>", do_delete)
        del_btn.bind("<Enter>", lambda e: del_btn.config(fg="#ef4444"), add="+")
        del_btn.bind("<Leave>", lambda e: del_btn.config(fg=TEXT_MUTED), add="+")

        def do_copy(e):
            if not eid: return
            en = self.find_entry(eid)
            if en: self.copy_entry(en)

        badge.bind("<Button-1>", do_copy)

        def do_menu(e):
            if not eid: return
            self._entry_menu(e, eid, gid)

        for w in (badge, entry_widget):
            w.bind("<Button-3>", do_menu)

        def on_content_change(*args):
            entry["content"] = content_var.get()
            self.schedule_save()      # 打字时不再每条按键都写盘

        content_var.trace_add("write", on_content_change)

        self.row_widgets[eid] = {"row": card_bg, "border": card_border, "badge": badge,
                                 "content_var": content_var, "grip": grip, "entry": entry_widget,
                                 "note_lbl": note_lbl}

    # ------------------------------------------------------------------
    # 备注: 默认不显示, 鼠标悬停在条目上才弹出气泡
    # ------------------------------------------------------------------
    def _tip_schedule(self, eid):
        e = self.find_entry(eid)
        note = ((e or {}).get("note") or "").strip()
        self._tip_cancel_show()
        if not note:
            return
        if self._tip_hide_job is not None:
            try:
                self.root.after_cancel(self._tip_hide_job)
            except Exception:
                pass
            self._tip_hide_job = None
        try:
            self._tip_job = self.root.after(300, lambda: self._tip_show(note, eid))
        except Exception:
            self._tip_job = None

    def _tip_cancel_show(self):
        if self._tip_job is not None:
            try:
                self.root.after_cancel(self._tip_job)
            except Exception:
                pass
            self._tip_job = None

    def _tip_leave(self):
        """从条目上移开: 延迟一点再关, 免得在卡片内部各控件之间移动时闪烁"""
        self._tip_cancel_show()
        if self._tip is None:
            return
        try:
            if self._tip_hide_job is None:
                self._tip_hide_job = self.root.after(120, self._tip_hide)
        except Exception:
            self._tip_hide()

    def _tip_show(self, note, eid):
        self._tip_job = None
        w = self.row_widgets.get(eid)
        if not w: return
        self._tip_hide()
        try:
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            try:
                t.attributes("-alpha", 0.97)
            except Exception:
                pass
            bubble = tk.Frame(t, bg="#1e293b", padx=1, pady=1)
            bubble.pack()
            tk.Label(bubble, text=note, bg="#1e293b", fg="#f8fafc", justify="left",
                     font=("Microsoft YaHei UI", 9), wraplength=240, padx=10, pady=7).pack()
            t.update_idletasks()
            tw, th = t.winfo_width(), t.winfo_height()

            px, py = self.root.winfo_x(), self.root.winfo_y()
            r = self._monitor_rect_at(px + self.win_w // 2, py + 10) or self._primary_rect()
            cx = px + self.win_w + 6
            if cx + tw > r[2] - 4:
                cx = px - tw - 6
            if cx < r[0] + 4:
                cx = max(r[0] + 4, min(px + self.win_w + 6, r[2] - tw - 4))
            cy = w["border"].winfo_rooty()
            if cy + th > r[3] - 4:
                cy = max(r[1] + 4, r[3] - th - 4)
            t.geometry("+{}+{}".format(int(cx), int(cy)))
            self._tip = t
        except Exception:
            self._tip = None

    def _tip_hide(self):
        self._tip_hide_job = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def open_note_dialog(self, eid):
        """编辑备注: 可留空(留空=不显示气泡)"""
        e = self.find_entry(eid)
        if not e: return
        self._tip_hide()
        self.dialog_open = True
        dlg = tk.Toplevel(self.root)
        dlg.title("备注")
        dlg.configure(bg=APP_BG)
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.transient(self.root)
        dlg.grab_set()

        f_label = ("Microsoft YaHei UI", 10)
        f_small = ("Microsoft YaHei UI", 8)

        tk.Label(dlg, text="备注 (只在鼠标悬停时显示, 可以不写)", bg=APP_BG, fg=TEXT_TITLE,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=20, pady=(16, 2))
        preview = (e.get("content", "") or "").strip()
        preview = preview[:40] + ("…" if len(preview) > 40 else "")
        tk.Label(dlg, text="内容: {}".format(preview or "(空)"), bg=APP_BG, fg=TEXT_MUTED,
                 font=f_small, wraplength=320, justify="left").pack(anchor="w", padx=20, pady=(0, 8))

        box = tk.Frame(dlg, bg=CARD_BORDER, padx=1, pady=1)
        box.pack(fill="both", expand=True, padx=20)
        txt = tk.Text(box, width=38, height=5, bg=CARD_BG, fg=TEXT_TITLE, relief="flat",
                      insertbackground=TEXT_MAIN, font=f_label, wrap="word", padx=6, pady=6)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", e.get("note", ""))
        txt.focus_set()

        err = tk.Label(dlg, text="", bg=APP_BG, fg=BADGE_RED_FG, font=f_small)
        err.pack(anchor="w", padx=20, pady=(6, 0))

        btns = tk.Frame(dlg, bg=APP_BG)
        btns.pack(fill="x", padx=20, pady=(8, 16))

        def close():
            try:
                dlg.destroy()
            finally:
                self.dialog_open = False

        def apply_note(val):
            en = self.find_entry(eid)
            if en is not None:
                en["note"] = val
                self.save_data()
                self._refresh_note_marker(eid)
            close()

        def do_save():
            apply_note(txt.get("1.0", "end").strip())

        def do_clear():
            apply_note("")

        tk.Button(btns, text="保存", command=do_save, bg=ACCENT, fg=ACCENT_FG,
                  activebackground=ACCENT_HOVER, activeforeground=ACCENT_FG,
                  relief="flat", bd=0, cursor="hand2", padx=18, pady=6,
                  font=f_label).pack(side="left")
        tk.Button(btns, text="清除备注", command=do_clear, bg=HEADER_BG, fg=TEXT_MAIN,
                  activebackground=CARD_HOVER, relief="flat", bd=0, cursor="hand2",
                  padx=14, pady=6, font=f_label).pack(side="left", padx=8)
        tk.Button(btns, text="取消", command=close, bg=HEADER_BG, fg=TEXT_TITLE,
                  activebackground=CARD_HOVER, relief="flat", bd=0, cursor="hand2",
                  padx=18, pady=6, font=f_label).pack(side="left")

        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.bind("<Escape>", lambda ev: close())
        dlg.bind("<Control-Return>", lambda ev: do_save())
        self._place_dialog(dlg)

    def _refresh_note_marker(self, eid):
        w = self.row_widgets.get(eid)
        e = self.find_entry(eid)
        if not w or not e: return
        lbl = w.get("note_lbl")
        if lbl is None: return
        try:
            if (e.get("note") or "").strip():
                if not lbl.winfo_ismapped():
                    lbl.pack(side="right", padx=(0, 4))
            else:
                lbl.pack_forget()
        except Exception:
            pass

    def _hotkey_warning(self, hk, group):
        low = hk.strip().lower()
        if (self.settings.get("toggle_hotkey") or "").strip().lower() == low:
            return "   ⚠ 与「面板显示/隐藏」热键相同, 会被面板热键占用"
        for key, label in (("prev_group_hotkey", "上一个分组"), ("next_group_hotkey", "下一个分组")):
            if (self.settings.get(key) or "").strip().lower() == low:
                return "   ⚠ 与「{}」热键相同".format(label)
        for g in self.groups:
            if g["id"] != group["id"] and (g.get("hotkey") or "").strip().lower() == low:
                return "   ⚠ 与分组「{}」的切换热键相同".format(g["name"])
        return ""

    def _entry_menu(self, event, eid, gid):
        m = tk.Menu(self.root, tearoff=0, bg="#ffffff", fg=TEXT_TITLE,
                    activebackground=ACCENT, activeforeground=ACCENT_FG, bd=0)
        m.add_command(label="复制到剪贴板", command=lambda: self.copy_entry(self.find_entry(eid)))
        e = self.find_entry(eid)
        has_note = bool(((e or {}).get("note") or "").strip())
        m.add_command(label="备注… (悬停显示)" + ("  ✎已有" if has_note else ""),
                      command=lambda: self.open_note_dialog(eid))
        if has_note:
            m.add_command(label="清除备注", command=lambda: self._set_note(eid, ""))
        sub = tk.Menu(m, tearoff=0, bg="#ffffff", fg=TEXT_TITLE,
                      activebackground=ACCENT, activeforeground=ACCENT_FG, bd=0)
        for g in self.groups:
            if g["id"] == gid: continue
            sub.add_command(label=g["name"], command=lambda x=g["id"]: self.move_entry(eid, x))
        sub.add_separator()
        sub.add_command(label="新建分组并移入…", command=lambda: self.move_entry(eid, None, True))
        m.add_cascade(label="移动到分组", menu=sub)
        m.add_separator()
        m.add_command(label="删除条目", command=lambda: self.delete_entry_by_id(eid))
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def _set_note(self, eid, note):
        e = self.find_entry(eid)
        if e is None: return
        e["note"] = note or ""
        self.save_data()
        self._refresh_note_marker(eid)
        self.status("已清除备注" if not (note or "").strip() else "备注已保存")

    # ------------------------------------------------------------------
    # 徽标 / 复制 / 删除
    # ------------------------------------------------------------------
    def refresh_badges(self):
        entries = {}
        for _g, e in self.all_entries():
            entries[e["id"]] = e
        for eid, w in self.row_widgets.items():
            entry = entries.get(eid)
            hk = (entry or {}).get("hotkey", "").strip()
            st = self.hotkey_status.get(eid, "none")

            if not hk:
                text, bg, fg = "未设", BADGE_BG, TEXT_MUTED
            elif st == "invalid":
                text, bg, fg = "⚠ 格式", BADGE_ORANGE, BADGE_ORANGE_FG
            elif st == "conflict":
                text, bg, fg = "⚠ 冲突", BADGE_RED, BADGE_RED_FG
            elif st == "off":
                text, bg, fg = hk, BADGE_BG, TEXT_MUTED
            else:
                text, bg, fg = hk, ACCENT, ACCENT_FG
            w["badge"].config(text=text, bg=bg, fg=fg)

    def flash_row(self, eid):
        w = self.row_widgets.get(eid)
        if not w: return
        card_bg = w["row"]
        try:
            card_bg.config(bg=FLASH_BG)
            for child in card_bg.winfo_children():
                try:
                    child.config(bg=FLASH_BG)
                except Exception:
                    pass
        except Exception:
            return

        def revert():
            # 卡片可能已经被重建/销毁, 必须容错
            try:
                if not card_bg.winfo_exists():
                    return
                card_bg.config(bg=CARD_BG)
                for child in card_bg.winfo_children():
                    try:
                        child.config(bg=CARD_BG)
                    except Exception:
                        pass
                self.refresh_badges()
            except Exception:
                pass

        self.root.after(350, revert)

    def copy_entry(self, entry):
        if not entry: return
        content = entry.get("content", "")
        if not content:
            self.status("⚠ 内容为空")
            return
        if clipboard_set_text(content):
            display = (content[:12] + "…") if len(content) > 12 else content
            self.status("📋 已复制: {}".format(display))
            self.flash_row(entry["id"])
        else:
            self.status("⚠ 复制失败")
        self._touch()

    def _ensure_visible(self, eid):
        g, e, _i = self.find_entry_ctx(eid)
        if g is None: return
        changed = False
        if g["id"] not in self.active:
            self.active.append(g["id"])
            changed = True
        if g.get("collapsed"):
            g["collapsed"] = False
        self.schedule_save()
        if changed:
            self.rebind_all()
        self._expand_section(g["id"], True)
        self._refresh_section_states()
        self._refresh_card_borders()
        self.refresh_badges()

    def paste_entry(self, eid):
        entry = self.find_entry(eid)
        if not entry: return
        content = entry.get("content", "")
        if not content: return
        self._ensure_visible(eid)
        old = clipboard_get_text()
        if not clipboard_set_text(content):
            self.status("⚠ 剪贴板被占用")
            return
        self.root.after(40, send_ctrl_v)
        if old is not None:
            self.root.after(500, lambda: clipboard_set_text(old))
        self.flash_row(eid)
        display = (content[:12] + "…") if len(content) > 12 else content
        self.status("⌨ 已输入: {}".format(display))

    def delete_entry_by_id(self, eid):
        g, _e, i = self.find_entry_ctx(eid)
        if g is None: return
        g["entries"].pop(i)
        self.save_data()
        self._rebuild_rows()
        self.rebind_all()

    # ------------------------------------------------------------------
    # 全局热键注册
    # ------------------------------------------------------------------
    def clear_hotkeys(self):
        """强制注销所有注册热键，解除系统监控，使得所有按键都流入 Tkinter 事件"""
        hwnd = HOTKEY_HWND[0]
        if hwnd:
            for hid in list(self.hk_map.keys()):
                user32.SendMessageW(hwnd, WM_DO_UNREGISTER, hid, 0)
        self.hk_map.clear()
        self.hotkey_status.clear()
        self.group_status.clear()
        self.cycle_status = {"prev": "none", "next": "none"}
        self.toggle_status = "none"
        self._hk_sig = None

    def _hid_for(self, target):
        """给每个目标分配固定不变的 hid, 这样排序/折叠都不会引起重新注册"""
        hid = self._hid_map.get(target)
        if hid is None:
            if self._hid_next > 60000:
                self._hid_map.clear()
                self._hid_next = HID_GROUP_BASE
            hid = self._hid_next
            self._hid_next += 1
            self._hid_map[target] = hid
        return hid

    def _hotkey_plan(self):
        """本次应该注册哪些热键 -> [(hid, target, 原字符串, (mods,vk) 或 None)]"""
        plan = []

        def add(target, hk):
            hk = (hk or "").strip()
            if not hk: return
            plan.append((self._hid_for(target), target, hk, parse_hotkey(hk)))

        add(("toggle", None), self.settings.get("toggle_hotkey", ""))
        add(("cycle", "prev"), self.settings.get("prev_group_hotkey", ""))
        add(("cycle", "next"), self.settings.get("next_group_hotkey", ""))
        for g in self.groups:
            add(("group", g["id"]), g.get("hotkey", ""))
        for gid in self.active:
            g = self.find_group(gid)
            if not g: continue
            for e in g.get("entries", []):
                add(("entry", e["id"]), e.get("hotkey", ""))
        return plan

    def rebind_all(self, force=False):
        """重新计算并注册系统热键
        规则: 面板热键 / 循环切换热键 / 所有分组切换热键 -> 始终注册
              条目热键 -> 只注册「已启用」分组里的条目 (所以不同分组之间可以重键)
        优化: 先算指纹, 热键集合没变就直接跳过(不再注销/重注册), 切换生效/折叠都是秒响应"""
        plan = self._hotkey_plan()
        sig = tuple(sorted((hid, parsed) for hid, _t, _hk, parsed in plan))

        if (not force) and sig == self._hk_sig and self.hk_map:
            self._mark_inactive_off()
            self._refresh_section_states()
            self.refresh_badges()
            return

        self.clear_hotkeys()
        hwnd = HOTKEY_HWND[0]
        if not hwnd:
            self._hk_sig = None
            return

        for hid, target, _hk, parsed in plan:
            if parsed is None:
                self._set_status(target, "invalid")
                continue
            mods, vk = parsed
            res = user32.SendMessageW(hwnd, WM_DO_REGISTER, hid, (mods << 16) | vk)
            if res:
                self.hk_map[hid] = target
                self._set_status(target, "ok")
            else:
                self._set_status(target, "conflict")

        self._hk_sig = sig
        self._mark_inactive_off()
        self._refresh_section_states()
        if hasattr(self, "row_widgets"):
            self.refresh_badges()

    def _mark_inactive_off(self):
        """未启用分组的条目: 标记为「暂停」"""
        for g in self.groups:
            if g["id"] in self.active: continue
            for e in g.get("entries", []):
                if (e.get("hotkey") or "").strip():
                    self.hotkey_status[e["id"]] = "off"

    def _set_status(self, target, st):
        kind, key = target
        if kind == "entry":
            self.hotkey_status[key] = st
        elif kind == "group":
            self.group_status[key] = st
        elif kind == "cycle":
            self.cycle_status[key] = st
        else:
            self.toggle_status = st

    # ------------------------------------------------------------------
    # 事件轮询
    # ------------------------------------------------------------------
    def _poll_events(self):
        try:
            while True:
                kind, payload = event_queue.get_nowait()
                if kind == "hotkey":
                    target = self.hk_map.get(payload)
                    if not target: continue
                    tkind, key = target
                    if tkind == "toggle":
                        self.toggle_vis()
                    elif tkind == "entry":
                        self.paste_entry(key)
                    elif tkind == "group":
                        g = self.find_group(key)
                        self.activate_group(key, exclusive=True)
                        if g: self.status("🔀 已切换到分组「{}」".format(g["name"]))
                    elif tkind == "cycle":
                        self.cycle_group(-1 if key == "prev" else 1)
                elif kind == "show":
                    self.show_from_hidden()
        except queue.Empty:
            pass
        try:
            self.root.after(60, self._poll_events)
        except Exception:
            pass

    def _poll(self):
        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()

            if x <= -9000 or y <= -9000:
                try:
                    self.root.after(120, self._poll)
                except Exception:
                    pass
                return

            if (self.settings.get("auto_hide", True)
                    and not self.dialog_open
                    and not self.interacting
                    and self.vis != "gone"):
                dock = self.win.get("dock")
                if dock:
                    r = self.get_dock_rect()
                    pos = self._cursor()
                    if pos:
                        mx, my = pos
                        w, h = self.win_w, self.current_h

                        inside = (x <= mx <= x + w and y <= my <= y + h)
                        near = self._near_edge(dock, r, mx, my, x, y, w, h)

                        want = "full" if (inside or near or time.time() < self.grace_until) else "strip"
                        if want != self.vis:
                            self.set_vis(want)
                else:
                    if self.vis != "full":
                        self.set_vis("full")
        except Exception:
            pass
        try:
            self.root.after(120, self._poll)
        except Exception:
            pass

    def _cursor(self):
        pt = POINT()
        if user32.GetCursorPos(ctypes.byref(pt)):
            return pt.x, pt.y
        return None

    # ------------------------------------------------------------------
    # 显示 / 隐藏 / 吸附
    # ------------------------------------------------------------------
    def toggle_vis(self):
        if self.vis == "gone":
            self.set_vis("full")
        else:
            self.set_vis("gone")

    def hide_to_gone(self):
        self.set_vis("gone")

    def show_from_hidden(self):
        self.set_vis("full")
        self.root.lift()

    def set_vis(self, target):
        if target == self.vis: return
        self._tip_hide()
        self.vis = target
        if target == "full":
            self._show_full()
        elif target == "strip":
            self._to_strip()
        else:
            self._set_geometry(-10000, -10000, self.win_w, self.current_h)

    def _show_full(self):
        dock = self.win.get("dock")
        w, h = self.win_w, self.current_h
        cx = self.win.get("x", self.root.winfo_x())
        cy = self.win.get("y", self.root.winfo_y())
        if dock:
            r = self.get_dock_rect()
            if dock == "left":
                tx, ty = r[0], cy
            elif dock == "right":
                tx, ty = r[2] - w, cy
            elif dock == "top":
                tx, ty = cx, r[1]
            else:
                tx, ty = cx, r[3] - h
        else:
            tx, ty = cx, cy
        self.animate_to(int(tx), int(ty), w, h)
        self.root.lift()

    def _to_strip(self):
        dock = self.win.get("dock")
        if not dock: return
        r = self.get_dock_rect()
        w, h = self.win_w, self.current_h
        s = int(self.settings.get("strip", 3))
        cx = self.win.get("x", self.root.winfo_x())
        cy = self.win.get("y", self.root.winfo_y())

        if dock == "left":
            self.animate_to(r[0] - w + s, cy, w, h)
        elif dock == "right":
            self.animate_to(r[2] - s, cy, w, h)
        elif dock == "top":
            self.animate_to(cx, r[1] - h + s, w, h)
        else:
            self.animate_to(cx, r[3] - s, w, h)

    def animate_to(self, tx, ty, tw, th):
        self._anim = [tx, ty, tw, th]
        self._anim_tick()

    def _anim_tick(self):
        if self.interacting:
            self._anim = None
            return

        a = self._anim
        if not a: return
        tx, ty, tw, th = a
        sx, sy = self.root.winfo_x(), self.root.winfo_y()

        dx = tx - sx
        dy = ty - sy

        nx = sx + (dx // 2) if abs(dx) > 2 else tx
        ny = sy + (dy // 2) if abs(dy) > 2 else ty

        if (nx, ny) == (tx, ty):
            self._set_geometry(tx, ty, tw, th)
            self._anim = None
        else:
            self._set_geometry(nx, ny, tw, th)
            self.root.after(10, self._anim_tick)

    def _drag_start(self, event):
        try:
            self.interacting = True
            self._anim = None
            self.vis = "full"
            self._drag = (event.x_root - self.root.winfo_x(),
                          event.y_root - self.root.winfo_y())
        except Exception:
            pass

    def _drag_move(self, event):
        try:
            if not getattr(self, "_drag", None): return
            dx, dy = self._drag
            self._set_geometry(event.x_root - dx, event.y_root - dy, self.win_w, self.current_h)
        except Exception:
            pass

    def _drag_release(self, event):
        try:
            self._drag = None
            self.interacting = False
            self.grace_until = time.time() + 0.3

            self.root.update_idletasks()
            x, y = self.root.winfo_x(), self.root.winfo_y()
            w, h = self.win_w, self.current_h
            r = self._monitor_rect_at(x + w // 2, y + h // 2) or self._primary_rect()
            thr = int(self.settings.get("snap_threshold", 60))

            dists = {
                "left": max(0, x - r[0]),
                "right": max(0, r[2] - (x + w)),
                "top": max(0, y - r[1]),
                "bottom": max(0, r[3] - (y + h))
            }
            best = min(dists, key=dists.get)

            if dists[best] <= thr:
                if best == "left":
                    x = r[0]
                elif best == "right":
                    x = r[2] - w
                elif best == "top":
                    y = r[1]
                else:
                    y = r[3] - h
                self.win["dock"] = best
                self.win["rx"], self.win["ry"], self.win["rw"], self.win["rh"] = r
            else:
                self.win["dock"] = None

            self._set_geometry(x, y, self.win_w, self.current_h)
            self.win["x"], self.win["y"] = x, y
            self.save_data()
        except Exception:
            pass

    def _restore_position(self):
        dock = self.win.get("dock")
        x, y = self.win.get("x"), self.win.get("y")

        if x is None or y is None:
            pos = self._cursor()
            if pos:
                r = self._monitor_rect_at(pos[0], pos[1]) or self._primary_rect()
            else:
                r = self._primary_rect()

            dock = "top"
            x = r[0] + (r[2] - r[0] - self.win_w) // 2
            y = r[1]
            self.win["dock"] = dock
            self.win["x"] = x
            self.win["y"] = y
            self.win["rx"], self.win["ry"], self.win["rw"], self.win["rh"] = r
        else:
            if dock:
                r = self.get_dock_rect()
                if dock == "left":
                    x = r[0]
                elif dock == "right":
                    x = r[2] - self.win_w
                elif dock == "top":
                    y = r[1]
                else:
                    y = r[3] - self.current_h

        self._set_geometry(x, y, self.win_w, self.current_h)
        self.root.update_idletasks()

    def _primary_rect(self):
        return (0, 0, user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))

    def _monitor_rect_at(self, x, y):
        # ★ 按值传 POINT（见 _setup_api 里的说明）；不要再写 byref。
        hmon = user32.MonitorFromPoint(POINT(int(x), int(y)), 2)
        if not hmon: return None
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)): return None
        r = mi.rcMonitor
        return (r.left, r.top, r.right, r.bottom)

    def get_dock_rect(self):
        r = (self.win.get("rx"), self.win.get("ry"),
             self.win.get("rw"), self.win.get("rh"))
        if r and all(v is not None for v in r): return r
        x = self.win.get("x", self.root.winfo_x())
        y = self.win.get("y", self.root.winfo_y())
        return self._monitor_rect_at(x + self.win_w // 2, y + self.current_h // 2) or self._primary_rect()

    def _near_edge(self, dock, r, mx, my, x, y, w, h):
        if dock == "left": return mx <= r[0] + 5 and (y <= my <= y + h)
        if dock == "right": return mx >= r[2] - 5 and (y <= my <= y + h)
        if dock == "top": return my <= r[1] + 5 and (x <= mx <= x + w)
        if dock == "bottom": return my >= r[3] - 5 and (x <= mx <= x + w)
        return False

    # ------------------------------------------------------------------
    # 通用小组件
    # ------------------------------------------------------------------
    def _create_modern_entry(self, parent, width_val, text_var=None):
        outer = tk.Frame(parent, bg=CARD_BORDER, padx=1, pady=1)
        inner = tk.Entry(outer, textvariable=text_var, width=width_val, bg=CARD_BG, fg=TEXT_TITLE,
                         insertbackground=TEXT_MAIN, relief="flat", font=("Microsoft YaHei UI", 10))
        inner.pack(fill="both", expand=True, padx=4, pady=4)

        inner.bind("<FocusIn>", lambda e: outer.config(bg=ACCENT))
        inner.bind("<FocusOut>", lambda e: outer.config(bg=CARD_BORDER))
        return outer, inner

    def _place_dialog(self, dlg, w=None, h=None):
        dlg.update_idletasks()
        dw = w or dlg.winfo_width()
        dh = h or dlg.winfo_height()
        x = self.root.winfo_x() + (self.win_w - dw) // 2
        y = self.root.winfo_y() + 40
        dlg.geometry("{}x{}+{}+{}".format(dw, dh, max(0, x), max(0, y)))

    # ------------------------------------------------------------------
    # 设置对话框
    # ------------------------------------------------------------------
    def open_settings(self):
        self.dialog_open = True
        dlg = tk.Toplevel(self.root)
        dlg.title("设置")
        dlg.configure(bg=APP_BG)
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.transient(self.root)
        dlg.grab_set()

        f_label = ("Microsoft YaHei UI", 10)
        form_frame = tk.Frame(dlg, bg=APP_BG)
        form_frame.pack(padx=24, pady=(20, 8), fill="both", expand=True)

        def section(text):
            tk.Label(form_frame, text=text, bg=APP_BG, fg=TEXT_MUTED,
                     font=("Microsoft YaHei UI", 8, "bold")).pack(anchor="w", pady=(8, 4))

        def hk_row(label, key, hint):
            tk.Label(form_frame, text=label, bg=APP_BG, fg=TEXT_MAIN, font=f_label).pack(anchor="w", pady=(0, 4))
            fr = tk.Frame(form_frame, bg=APP_BG)
            fr.pack(anchor="w", pady=(0, 8))
            var = tk.StringVar(value=self.settings.get(key, ""))
            rec = HotkeyRecorder(self, dlg, fr, var, width=16, base_hint=hint)
            rec.frame.pack(side="left")
            return var

        section("热键")
        toggle_var = hk_row("面板显示/隐藏", "toggle_hotkey", "例: Ctrl+Alt+E")
        prev_var = hk_row("上一个分组", "prev_group_hotkey", "留空=不用")
        next_var = hk_row("下一个分组", "next_group_hotkey", "留空=不用")

        section("行为")
        auto_var = tk.BooleanVar(value=self.settings.get("auto_hide", True))
        tk.Checkbutton(form_frame, text="自动隐藏 (鼠标移开且停靠边缘时)", variable=auto_var,
                       bg=APP_BG, fg=TEXT_MAIN, activebackground=APP_BG,
                       activeforeground=TEXT_TITLE, selectcolor="#ffffff",
                       font=f_label).pack(anchor="w", pady=(0, 6))

        inact_var = tk.BooleanVar(value=self.settings.get("show_inactive", True))
        tk.Checkbutton(form_frame, text="列表里也列出「未启用」的分组 (取消勾选则只显示已启用的)",
                       variable=inact_var, bg=APP_BG, fg=TEXT_MAIN, activebackground=APP_BG,
                       activeforeground=TEXT_TITLE, selectcolor="#ffffff",
                       font=f_label).pack(anchor="w", pady=(0, 10))

        def spin_row(label, value, lo, hi):
            fr = tk.Frame(form_frame, bg=APP_BG)
            fr.pack(fill="x", pady=(0, 10))
            tk.Label(fr, text=label, bg=APP_BG, fg=TEXT_MAIN, font=f_label).pack(side="left")
            var = tk.IntVar(value=value)
            outer = tk.Frame(fr, bg=CARD_BORDER, padx=1, pady=1)
            outer.pack(side="right")
            tk.Spinbox(outer, from_=lo, to=hi, textvariable=var, width=6, bg=CARD_BG,
                       fg=TEXT_MAIN, relief="flat", buttonbackground=HEADER_BG).pack(fill="both")
            return var

        snap_var = spin_row("吸附距离(像素)", self.settings.get("snap_threshold", 60), 10, 200)
        strip_var = spin_row("边条宽度(像素)", self.settings.get("strip", 3), 2, 20)
        col_var = spin_row("显示列数(1-5)", self.settings.get("columns", 1), 1, 5)

        err = tk.Label(form_frame, text="", bg=APP_BG, fg=BADGE_RED_FG, font=("Microsoft YaHei UI", 8))
        err.pack(anchor="w")

        btns = tk.Frame(dlg, bg=APP_BG)
        btns.pack(padx=24, pady=(4, 18), anchor="w")

        def close():
            self.rebind_all()
            try:
                dlg.destroy()
            finally:
                self.dialog_open = False

        def do_save():
            vals = {"toggle_hotkey": toggle_var.get().strip(),
                    "prev_group_hotkey": prev_var.get().strip(),
                    "next_group_hotkey": next_var.get().strip()}
            for k, v in vals.items():
                if v and parse_hotkey(v) is None:
                    err.config(text="热键格式不对, 示例: F4 / Ctrl+Alt+1")
                    return
            # 循环热键不能和面板热键重复
            used = {}
            labels = {"toggle_hotkey": "面板显示/隐藏", "prev_group_hotkey": "上一个分组",
                      "next_group_hotkey": "下一个分组"}
            for k, v in vals.items():
                if v and v.lower() in used:
                    err.config(text="「{}」与「{}」热键重复".format(labels[k], used[v.lower()]))
                    return
                if v: used[v.lower()] = labels[k]

            self.settings.update(vals)
            self.settings["auto_hide"] = bool(auto_var.get())
            self.settings["show_inactive"] = bool(inact_var.get())
            self.settings["snap_threshold"] = int(snap_var.get())
            self.settings["strip"] = int(strip_var.get())

            new_cols = int(col_var.get())
            if new_cols != self.settings.get("columns"):
                self.settings["columns"] = new_cols

            self.save_data()
            self.rebind_all()
            self._rebuild_rows()
            self.dialog_open = False
            dlg.destroy()

            msgs = []
            if self.toggle_status == "conflict": msgs.append("面板热键被占用")
            if self.cycle_status.get("prev") == "conflict": msgs.append("上一个分组热键被占用")
            if self.cycle_status.get("next") == "conflict": msgs.append("下一个分组热键被占用")
            self.status("⚠ " + " · ".join(msgs) if msgs else "✅ 设置已保存")

        b1 = tk.Button(btns, text="保存", command=do_save, bg=ACCENT, fg=ACCENT_FG,
                       activebackground=ACCENT_HOVER, activeforeground=ACCENT_FG,
                       relief="flat", bd=0, cursor="hand2", padx=20, pady=6, font=f_label)
        b1.pack(side="left")
        b2 = tk.Button(btns, text="取消", command=close, bg=HEADER_BG, fg=TEXT_TITLE,
                       activebackground=CARD_HOVER, relief="flat", bd=0, cursor="hand2",
                       padx=20, pady=6, font=f_label)
        b2.pack(side="left", padx=10)

        dlg.protocol("WM_DELETE_WINDOW", close)
        self._place_dialog(dlg)

    # ------------------------------------------------------------------
    # 分组管理对话框
    # ------------------------------------------------------------------
    def open_group_manager(self):
        self.dialog_open = True
        dlg = tk.Toplevel(self.root)
        dlg.title("分组管理")
        dlg.configure(bg=APP_BG)
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.transient(self.root)
        dlg.grab_set()

        f_label = ("Microsoft YaHei UI", 10)
        f_small = ("Microsoft YaHei UI", 8)

        tk.Label(dlg, text="分组管理", bg=APP_BG, fg=TEXT_TITLE,
                 font=("Microsoft YaHei UI", 11, "bold")).pack(anchor="w", padx=24, pady=(18, 2))
        tk.Label(dlg, text="勾选「生效」的分组才会响应热键(可多选)；不同分组的条目热键可以相同。按住 ≡ 拖动可排序。",
                 bg=APP_BG, fg=TEXT_MUTED, font=f_small).pack(anchor="w", padx=24, pady=(0, 10))

        holder = tk.Frame(dlg, bg=APP_BG)
        holder.pack(fill="both", expand=True, padx=24)

        canvas = tk.Canvas(holder, bg=APP_BG, highlightthickness=0, bd=0, height=260)
        sb = tk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=sb.set)
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=APP_BG)
        wid = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(wid, width=e.width))
        canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-int(e.delta / 120), "units"))

        # 草稿: 保存时才写回
        draft = [{"id": g["id"], "name": g["name"], "hotkey": g.get("hotkey", ""),
                  "entries": g.get("entries", []), "active": g["id"] in self.active}
                 for g in self.groups]
        row_widgets = []
        mgr = {"press": None, "id": None}

        def mgr_press(event, gid):
            mgr["press"] = (event.x_root, event.y_root)
            mgr["id"] = gid
            dlg.bind("<B1-Motion>", mgr_motion)
            dlg.bind("<ButtonRelease-1>", mgr_release)

        def mgr_motion(event):
            if mgr["id"] is None: return
            if mgr["press"] is not None:
                if abs(event.x_root - mgr["press"][0]) < 4 and abs(event.y_root - mgr["press"][1]) < 4:
                    return
                mgr["press"] = None
            cur = next((i for i, it in enumerate(draft) if it["id"] == mgr["id"]), -1)
            if cur < 0: return
            pos = len(draft)
            for i, it in enumerate(draft):
                rw = it.get("_row")
                if rw is None: continue
                try:
                    if event.y_root < rw.winfo_rooty() + rw.winfo_height() // 2:
                        pos = i
                        break
                except Exception:
                    continue
            ins = pos if pos <= cur else pos - 1
            if ins == cur: return
            it = draft.pop(cur)
            draft.insert(max(0, min(ins, len(draft))), it)
            draw()

        def mgr_release(event):
            for seq in ("<B1-Motion>", "<ButtonRelease-1>"):
                try:
                    dlg.unbind(seq)
                except Exception:
                    pass
            mgr["press"] = None
            mgr["id"] = None

        def draw():
            for w in inner.winfo_children():
                w.destroy()
            del row_widgets[:]

            for idx, item in enumerate(draft):
                name_var = tk.StringVar(value=item["name"])
                hk_var = tk.StringVar(value=item["hotkey"])

                rowf = tk.Frame(inner, bg=APP_BG)
                rowf.pack(fill="x", pady=3)
                item["_row"] = rowf

                grip = tk.Label(rowf, text="≡", bg=APP_BG, fg=CARD_BORDER, cursor="fleur",
                                font=("Microsoft YaHei UI", 11, "bold"), padx=2)
                grip.pack(side="left", padx=(0, 6))
                grip.bind("<Button-1>", lambda e, x=item["id"]: mgr_press(e, x))
                grip.bind("<Enter>", lambda e, _b=grip: _b.config(fg=ACCENT))
                grip.bind("<Leave>", lambda e, _b=grip: _b.config(fg=CARD_BORDER))

                def mk_toggle(v, it=item):
                    it["active"] = bool(v)

                chk = CheckBox(rowf, APP_BG, size=14, box=20, checked=item["active"],
                               command=mk_toggle)
                chk.pack(side="left", padx=(0, 4))

                no, ne = self._create_modern_entry(rowf, 12, name_var)
                no.pack(side="left")

                hf = tk.Frame(rowf, bg=APP_BG)
                hf.pack(side="left", padx=(8, 0))
                rec = HotkeyRecorder(self, dlg, hf, hk_var, width=10, base_hint="")
                rec.frame.pack(side="left")

                bf = tk.Frame(rowf, bg=APP_BG)
                bf.pack(side="right")

                def mk_up(i=idx):
                    if i <= 0: return
                    draft[i - 1], draft[i] = draft[i], draft[i - 1]
                    draw()

                def mk_down(i=idx):
                    if i >= len(draft) - 1: return
                    draft[i + 1], draft[i] = draft[i], draft[i + 1]
                    draw()

                def mk_del(i=idx):
                    it = draft[i]
                    if len(draft) <= 1:
                        err.config(text="至少要保留一个分组")
                        return
                    if it["entries"] and not messagebox.askyesno(
                            "删除分组", "「{}」里有 {} 个条目, 一起删除?".format(it["name"], len(it["entries"])),
                            parent=dlg):
                        return
                    draft.pop(i)
                    draw()

                for txt, cmd in (("↑", mk_up), ("↓", mk_down), ("✕", mk_del)):
                    b = tk.Label(bf, text=txt, bg=HEADER_BG, fg=TEXT_MAIN, width=2, cursor="hand2",
                                 font=("Microsoft YaHei UI", 9))
                    b.pack(side="left", padx=2)
                    b.bind("<Button-1>", lambda e, c=cmd: c())
                    b.bind("<Enter>", lambda e, _b=b: _b.config(bg=CARD_HOVER))
                    b.bind("<Leave>", lambda e, _b=b: _b.config(bg=HEADER_BG))

                item["_name_var"] = name_var
                item["_hk_var"] = hk_var
                row_widgets.append(item)

            canvas.configure(scrollregion=canvas.bbox("all"))

        def add_row():
            draft.append({"id": uuid.uuid4().hex[:8], "name": "新分组", "hotkey": "",
                          "entries": [], "active": True})
            draw()

        tool = tk.Frame(dlg, bg=APP_BG)
        tool.pack(fill="x", padx=24, pady=(8, 0))
        tk.Button(tool, text="＋ 新建分组", command=add_row, bg=HEADER_BG, fg=TEXT_TITLE,
                  activebackground=CARD_HOVER, relief="flat", bd=0, cursor="hand2",
                  padx=12, pady=4, font=f_label).pack(side="left")

        err = tk.Label(dlg, text="", bg=APP_BG, fg=BADGE_RED_FG, font=f_small)
        err.pack(anchor="w", padx=24, pady=(6, 0))

        btns = tk.Frame(dlg, bg=APP_BG)
        btns.pack(fill="x", padx=24, pady=(8, 18))

        def close():
            self.rebind_all()
            try:
                dlg.destroy()
            finally:
                self.dialog_open = False

        def do_save():
            # 1) 名称 / 热键 校验
            seen = {}
            for it in row_widgets:
                it["name"] = (it["_name_var"].get() or "").strip() or it["name"]
                hk = (it["_hk_var"].get() or "").strip()
                if hk and parse_hotkey(hk) is None:
                    err.config(text="「{}」的热键格式不对, 示例: Ctrl+Alt+1".format(it["name"]))
                    return
                it["hotkey"] = hk
            for it in row_widgets:
                hk = it["hotkey"].lower()
                if not hk: continue
                if hk in seen:
                    err.config(text="切换热键重复: {} (「{}」与「{}」)".format(it["hotkey"], seen[hk], it["name"]))
                    return
                seen[hk] = it["name"]
            for it in row_widgets:
                hk = it["hotkey"].lower()
                if not hk: continue
                for key, label in (("toggle_hotkey", "面板热键"),
                                   ("prev_group_hotkey", "上一个分组"),
                                   ("next_group_hotkey", "下一个分组")):
                    if (self.settings.get(key) or "").strip().lower() == hk:
                        err.config(text="「{}」与{}重复".format(it["name"], label))
                        return

            # 2) 写回
            new_groups = []
            for it in row_widgets:
                g = self.find_group(it["id"])
                if g is None:
                    g = {"id": it["id"], "name": it["name"], "hotkey": it["hotkey"],
                         "collapsed": False, "entries": it["entries"]}
                else:
                    g["name"] = it["name"]
                    g["hotkey"] = it["hotkey"]
                new_groups.append(g)
            self.groups = new_groups

            # 生效状态跟着一起保存
            on_ids = [it["id"] for it in row_widgets if it.get("active")]
            self.active = [g["id"] for g in self.groups if g["id"] in on_ids]

            self.after_group_change()
            if self.active:
                self.status("✅ 分组已保存 ({} 个分组生效)".format(len(self.active)))
            else:
                self.status("✅ 分组已保存 · 当前没有生效的分组, 勾选复选框才会响应热键")
            self.dialog_open = False
            dlg.destroy()

        tk.Button(btns, text="保存", command=do_save, bg=ACCENT, fg=ACCENT_FG,
                  activebackground=ACCENT_HOVER, activeforeground=ACCENT_FG,
                  relief="flat", bd=0, cursor="hand2", padx=20, pady=6,
                  font=f_label).pack(side="left")
        tk.Button(btns, text="取消", command=close, bg=HEADER_BG, fg=TEXT_TITLE,
                  activebackground=CARD_HOVER, relief="flat", bd=0, cursor="hand2",
                  padx=20, pady=6, font=f_label).pack(side="left", padx=10)

        draw()
        dlg.protocol("WM_DELETE_WINDOW", close)
        self._place_dialog(dlg)

    # ------------------------------------------------------------------
    # 帮助 / 退出
    # ------------------------------------------------------------------
    def show_help(self):
        self.dialog_open = True
        dlg = tk.Toplevel(self.root)
        dlg.title("帮助")
        dlg.configure(bg=APP_BG)
        dlg.attributes("-topmost", True)
        dlg.transient(self.root)
        text = (
            "EdgePaste 贴边快输 · 分组版\n"
            "─────────────────────────\n"
            "【分组列表】分组纵向排列, 分组再多也不会挤\n"
            "· 勾选标题上的复选框 = 让该分组生效(可多选), 生效的分组是蓝色高亮的\n"
            "· 中键点标题 = 只勾选这一个分组(清空其它分组的勾选)\n"
            "· 点标题 / 点三角 = 展开或折叠, 不影响别的分组\n"
            "· 按住标题上下拖 = 调整分组顺序 (会实时预览)\n"
            "· 双击标题 = 改名; 右键标题 = 启用/复制/新增条目/上移下移/删除\n"
            "· 标题右侧 ＋ = 在该分组新增条目; 底部「＋ 新建分组」= 新建分组\n"
            "· 只有生效的分组才响应热键 —— 所以不同分组可以用相同热键\n"
            "· 没生效的分组只是热键暂停, 条目照常可以查看和编辑\n"
            "【条目】\n"
            "· 新增后直接打字即可; 空着点别处会自动取消这条空条目\n"
            "· 备注(可选): 条目右键 → 备注…, 平时不显示, 鼠标悬停时才弹气泡\n"
            "    有备注的条目右侧会有一个小小的「注」字\n"
            "· 按住条目左侧的 ≡ 拖动 = 拖到别的分组, 或调整组内顺序 (蓝线=落点)\n"
            "· 悬停在快捷键标签上直接按键 = 录制快捷键 (不怕被系统拦截)\n"
            "· 单击快捷键标签 = 复制到剪贴板; 右键条目 = 移动/复制/删除\n"
            "· 按快捷键 = 自动粘贴到当前光标处\n"
            "【窗口】\n"
            "· 顶栏可拖动, 靠近屏幕边缘松手自动吸附并隐藏\n"
            "· 拖到屏幕中间松手 = 常驻悬浮; 左右边缘可拖拽调宽度\n"
        )
        tk.Label(dlg, text=text, bg=APP_BG, fg=TEXT_MAIN, justify="left",
                 font=("Microsoft YaHei UI", 9)).pack(padx=24, pady=20)

        def close():
            dlg.destroy()
            self.dialog_open = False

        tk.Button(dlg, text="知道了", command=close,
                  bg=ACCENT, fg=ACCENT_FG, relief="flat", bd=0, cursor="hand2",
                  activebackground=ACCENT_HOVER, activeforeground=ACCENT_FG,
                  padx=20, pady=6, font=("Microsoft YaHei UI", 10)).pack(pady=(0, 20))
        dlg.protocol("WM_DELETE_WINDOW", close)
        dlg.update_idletasks()
        w, h = dlg.winfo_width(), dlg.winfo_height()
        x = self.root.winfo_x() + (self.win_w - w) // 2
        y = self.root.winfo_y() + 40
        dlg.geometry("+{}+{}".format(max(0, x), max(0, y)))

    def quit_app(self):
        try:
            if self._save_job is not None:
                try:
                    self.root.after_cancel(self._save_job)
                except Exception:
                    pass
                self._save_job = None
            self.save_data()
        finally:
            self.root.destroy()


def main():
    try:
        if not check_single_instance(): return
        app = EdgePasteApp()
        app.run()
    except Exception as e:
        import traceback
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            with open(DATA_DIR / "error.log", "w", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except Exception:
            pass
        try:
            messagebox.showerror("EdgePaste 错误", str(e))
        except Exception:
            pass


if __name__ == "__main__":
    main()
