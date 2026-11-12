import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading

WIN_DEFAULT_SIZE = (1280, 860)
WIN_MIN_SIZE = (900, 600)
WIN_GEOM_NAME = "_ui_window.json"

TOUCH_W, TOUCH_H = 80, 20
TITLE_STRIP = 32

class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT),
                ("rcNormalPosition", wt.RECT)]

SW_SHOWMINIMIZED, SW_SHOWMAXIMIZED = 2, 3

def screens():
    out = []
    if sys.platform != "win32":
        return out
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFO)]
        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p,
                                ctypes.POINTER(wt.RECT), ctypes.c_void_p)
        u32.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, CB, ctypes.c_void_p]

        def cb(hmon, _hdc, _lprc, _data):
            mi = _MONITORINFO()
            mi.cbSize = ctypes.sizeof(_MONITORINFO)
            if u32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
                m, w = mi.rcMonitor, mi.rcWork
                out.append({"rect": (int(m.left), int(m.top), int(m.right), int(m.bottom)),
                            "work": (int(w.left), int(w.top), int(w.right), int(w.bottom)),
                            "primary": bool(mi.dwFlags & 1)})
            return True

        u32.EnumDisplayMonitors(None, None, CB(cb), None)
    except Exception:
        return []
    return out

def rect_from_hwnd(hwnd):
    if not hwnd:
        return None
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.GetWindowPlacement.argtypes = [ctypes.c_void_p, ctypes.POINTER(_WINDOWPLACEMENT)]
        wp = _WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(_WINDOWPLACEMENT)
        if not u32.GetWindowPlacement(ctypes.c_void_p(int(hwnd)), ctypes.byref(wp)):
            return None
        r = wp.rcNormalPosition
        return {"x": int(r.left), "y": int(r.top),
                "w": int(r.right - r.left), "h": int(r.bottom - r.top),
                "maximized": int(wp.showCmd) == SW_SHOWMAXIMIZED,
                "minimized": int(wp.showCmd) == SW_SHOWMINIMIZED}
    except Exception:
        return None

def _touchable(x, y, w, screens_):
    for s in screens_:
        l, t, r, b = s["work"]
        ix = min(x + max(1, w), r) - max(x, l)
        iy = min(y + TITLE_STRIP, b) - max(y, t)
        if ix >= TOUCH_W and iy >= TOUCH_H:
            return s
    return None

def resolve(saved, scr=None):
    dw, dh = WIN_DEFAULT_SIZE
    default = {"width": dw, "height": dh, "x": None, "y": None, "maximized": False,
               "why": "第一次开（默认大小 · 居中）"}
    if not isinstance(saved, dict) or not saved:
        return default
    maxed = bool(saved.get("maximized"))
    try:
        w, h = int(saved.get("width") or 0), int(saved.get("height") or 0)
    except (TypeError, ValueError):
        return dict(default, maximized=maxed, why="存的那份大小读不出来 → 默认大小 · 居中")
    if w < WIN_MIN_SIZE[0] or h < WIN_MIN_SIZE[1]:
        return dict(default, maximized=maxed, why="存的那份比最小尺寸还小 → 默认大小 · 居中")
    scr = screens() if scr is None else scr
    if scr:
        vl = min(s["rect"][0] for s in scr)
        vt = min(s["rect"][1] for s in scr)
        vr = max(s["rect"][2] for s in scr)
        vb = max(s["rect"][3] for s in scr)
        if w > vr - vl or h > vb - vt:
            w, h = min(w, vr - vl), min(h, vb - vt)
    else:
        try:
            return {"width": w, "height": h, "x": int(saved.get("x")), "y": int(saved.get("y")),
                    "maximized": maxed, "why": "用上次的大小和位置（读不到显示器信息，原样用）"}
        except (TypeError, ValueError):
            return dict(default, maximized=maxed, why="上次的位置读不出来 → 居中")
    try:
        x, y = int(saved.get("x")), int(saved.get("y"))
    except (TypeError, ValueError):
        return {"width": w, "height": h, "x": None, "y": None, "maximized": maxed,
                "why": "上次只有大小（位置没存上）→ 按这个大小居中"}
    hit = _touchable(x, y, w, scr)
    if hit is None:
        return {"width": w, "height": h, "x": None, "y": None, "maximized": maxed,
                "why": "上次那块屏现在没有了（或分辨率变了）→ 大小还记着，位置居中"}
    return {"width": w, "height": h, "x": x, "y": y, "maximized": maxed,
            "why": "用上次的大小和位置%s" % ("（最大化）" if maxed else "")}

def load(path):
    try:
        raw = json.loads(open(str(path), encoding="utf-8").read())
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}

def save(path, geom):
    try:
        p = str(path)
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(json.dumps(geom, ensure_ascii=False))
        os.replace(tmp, p)
        return True
    except Exception:
        return False

def _find_hwnd(title=""):
    if sys.platform != "win32":
        return 0
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]
        u32.GetClassNameW.argtypes = [ctypes.c_void_p, wt.LPWSTR, ctypes.c_int]
        u32.GetWindowTextW.argtypes = [ctypes.c_void_p, wt.LPWSTR, ctypes.c_int]
        u32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        u32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.RECT)]
        me = os.getpid()
        got = []
        CB = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

        def cb(hwnd, _l):
            pid = wt.DWORD(0)
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if int(pid.value) != me:
                return True
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hwnd, cls, 256)
            if not cls.value.startswith("WindowsForms10"):
                return True
            n = u32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            rc = wt.RECT()
            u32.GetWindowRect(hwnd, ctypes.byref(rc))
            got.append((int(hwnd), buf.value,
                        max(1, rc.right - rc.left) * max(1, rc.bottom - rc.top)))
            return True

        u32.EnumWindows(CB(cb), None)
        if not got:
            return 0
        for hwnd, t, _a in got:
            if title and t == title:
                return hwnd
        got.sort(key=lambda x: -x[2])
        return got[0][0]
    except Exception:
        return 0

def _hwnd_of(window):
    try:
        h = window.native.Handle
        hwnd = int(h.ToInt32()) if hasattr(h, "ToInt32") else int(h)
        if hwnd:
            return hwnd
    except Exception:
        pass
    try:
        title = str(getattr(window, "title", "") or "")
    except Exception:
        title = ""
    return _find_hwnd(title)

def watch(window, path, note=None, delay=0.8):
    st = {"timer": None, "last": {}, "saved": 0, "path": path, "lock": threading.Lock()}

    def snapshot():
        return rect_from_hwnd(_hwnd_of(window))

    def write_now():
        with st["lock"]:
            st["timer"] = None
        snap = snapshot()
        if not snap or snap.get("minimized"):
            return False
        geom = {"x": snap["x"], "y": snap["y"], "width": snap["w"], "height": snap["h"],
                "maximized": bool(snap["maximized"])}
        with st["lock"]:
            if geom == st["last"]:
                return False
            st["last"] = dict(geom)
        if save(path, geom):
            st["saved"] += 1
            if note:
                note("窗口几何已记住：%(width)sx%(height)s @ (%(x)s, %(y)s)%(max)s"
                     % dict(geom, max="（最大化）" if geom["maximized"] else ""))
            return True
        return False

    def soon(*_a):
        with st["lock"]:
            if st["timer"] is not None:
                st["timer"].cancel()
            t = threading.Timer(delay, write_now)
            t.daemon = True
            st["timer"] = t
        t.start()

    def on_closing(*_a):
        with st["lock"]:
            if st["timer"] is not None:
                st["timer"].cancel()
                st["timer"] = None
        write_now()

    for ev in ("moved", "resized", "maximized", "restored"):
        try:
            event = getattr(window.events, ev)
            event += soon
        except Exception:
            pass
    for ev in ("closing", "closed"):
        try:
            event = getattr(window.events, ev)
            event += on_closing
        except Exception:
            pass
    st["flush"] = write_now
    return st
