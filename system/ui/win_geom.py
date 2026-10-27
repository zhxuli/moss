# -*- coding: utf-8 -*-
"""主窗口的「大小 + 位置」记忆（`V-223`）。

为什么单独一个文件
------------------
这段逻辑跟界面的主流程没关系，却最该被**单独测** —— 双屏、拔屏、换分辨率、最大化、
最小化，每一条写错都是"窗口跑到看不见的地方去、下次开出来是空的"那种坑。
`system/ui/main.py` 只负责 import 它、把窗口和配置路径交给它。

存在哪 / 存什么
---------------
`user_data/state/_ui_window.json`：
`{"x": …, "y": …, "width": …, "height": …, "maximized": bool}`。

★ 坐标是**虚拟屏**的：副屏摆在主屏左边时整片都是**负数**（实测这台机器：主屏 `0..3840`、
  副屏 `-3840..0`）。所以"`x < 0` 就算坏"这种判断**一定不能写** —— 判据只能拿矩形去跟
  每块屏求交。

★ 为什么用 `GetWindowPlacement` 而不是 pywebview 的 `window.x/y/width/height`：
  窗口**最大化**时那几个值就是最大化后的（典型是 `-8,-8,1936,1048`），拿它当"下次开的位置"
  会把窗口越开越大；`GetWindowPlacement` 给的 `rcNormalPosition` 才是"**还原**之后该在哪儿"，
  顺带还告诉我们现在是正常 / 最大化 / 最小化。
"""
import ctypes
import ctypes.wintypes as wt
import json
import os
import sys
import threading

#: 没存过几何时的默认值（原来硬编码在 `create_window` 那行）
WIN_DEFAULT_SIZE = (1280, 860)
#: 最小尺寸（`MinimumSize` 那道闸，别比它小）
WIN_MIN_SIZE = (900, 600)
#: 文件名（存 `user_data/state/` 下）
WIN_GEOM_NAME = "_ui_window.json"

#: 标题栏那一条要露出多少才算"还抓得住"（`resolve` 的判据）
TOUCH_W, TOUCH_H = 80, 20
TITLE_STRIP = 32          # 标题栏大约多高


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT),
                ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [("length", wt.UINT), ("flags", wt.UINT), ("showCmd", wt.UINT),
                ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT),
                ("rcNormalPosition", wt.RECT)]


SW_SHOWMINIMIZED, SW_SHOWMAXIMIZED = 2, 3


def screens():
    """所有显示器：`[{'rect': (l,t,r,b), 'work': (l,t,r,b), 'primary': bool}]`。

    虚拟屏坐标（主屏 `(0,0)` 起算，左边那块副屏是负数）。拿不到就回空表 ——
    那种情况下 `resolve()` 会**原样相信存下来的值**（非 Windows / 读不到显示器时别自作聪明）。
    """
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
    except Exception:                                                    # noqa: BLE001
        return []
    return out


def rect_from_hwnd(hwnd):
    """从窗口句柄读「正常状态下的矩形 + 现在是最大化还是最小化」。

    返回 `{"x","y","w","h","maximized","minimized"}`；读不到给 `None`。
    ★ 窗口最大化/最小化时 `rcNormalPosition` 仍然是**还原后**该在的位置 —— 这正是我们要存的东西。
    """
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
    except Exception:                                                    # noqa: BLE001
        return None


def _touchable(x, y, w, screens_):
    """标题栏那一条还落在某块屏的工作区里吗？→ 命中的那块屏（或 None）。

    ★ 只要求**标题栏**（顶部一条）露出来：只要还能抓住它，窗口就没丢 ——
      不要求整个窗口都在屏内（横跨两块屏是合法的用法，不该被"拉回来"）。
    """
    for s in screens_:
        l, t, r, b = s["work"]
        ix = min(x + max(1, w), r) - max(x, l)
        iy = min(y + TITLE_STRIP, b) - max(y, t)
        if ix >= TOUCH_W and iy >= TOUCH_H:
            return s
    return None


def resolve(saved, scr=None):
    """把"存下来的那份"翻译成给 `create_window` 用的东西。

    返回 `{"width","height","x","y","maximized","why"}` —— 宽高**一定有**；
    `x`/`y` 可能是 `None`（= 交给 pywebview 居中）。`why` 是给人看的一句话（写进启动日志）。

    规矩（`V-223`）：
      ① 大小：不小于 `WIN_MIN_SIZE`；也不超过**整个虚拟屏**（横跨两块屏合法，所以不按单块裁）；
      ② 位置：标题栏得还抓得住（副屏在主屏左边、坐标是负数也认）；
      ③ 位置找不回来（拔了屏 / 换了分辨率）⇒ **大小还记着**、位置居中 —— 别把窗口丢在看不见的地方。
    """
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
        if w > vr - vl or h > vb - vt:                    # 换小屏了：裁到虚拟屏
            w, h = min(w, vr - vl), min(h, vb - vt)
    else:
        # 读不到显示器信息：**原样信它**（别在这个环境里瞎裁）
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


# ---------------------------------------------------------------- 存 / 读
def load(path):
    """读上次存的几何；**读不出来/坏了就当没存过**（绝不因为一个配置文件开不了界面）。"""
    try:
        raw = json.loads(open(str(path), encoding="utf-8").read())
    except Exception:                                                    # noqa: BLE001
        return {}
    return raw if isinstance(raw, dict) else {}


def save(path, geom):
    """原子写（先写 .tmp 再 `os.replace`）—— 别让断电/崩溃留下半份 JSON。"""
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
    except Exception:                                                    # noqa: BLE001
        return False


# ---------------------------------------------------------------- 盯着窗口
def _find_hwnd(title=""):
    """在本进程里找那扇 `WindowsForms10.*` 顶层窗口（按标题优先）。

    为什么需要这条退路：跨线程读 pywebview 的 `window.native.Handle` 不总靠谱
    （而且它是个 `System.IntPtr`，`int()` 直接抛 `TypeError`）。按**本进程 pid + 窗体类**
    找是稳的 —— 同一时刻这个进程里也就这么几扇窗。
    """
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
        for hwnd, t, _a in got:                      # 标题对得上就用它
            if title and t == title:
                return hwnd
        got.sort(key=lambda x: -x[2])                # 否则挑面积最大的那扇
        return got[0][0]
    except Exception:                                                    # noqa: BLE001
        return 0


def _hwnd_of(window):
    """这扇窗口的原生句柄（HWND）；拿不到给 0。

    ★ `window.native.Handle` 是 **`System.IntPtr`**，`int()` 会抛 `TypeError`（实测踩到），
      得 `.ToInt32()`；那条路失败就自己 `EnumWindows` 找（`_find_hwnd`）。
    """
    try:
        h = window.native.Handle
        hwnd = int(h.ToInt32()) if hasattr(h, "ToInt32") else int(h)
        if hwnd:
            return hwnd
    except Exception:                                                    # noqa: BLE001
        pass
    try:
        title = str(getattr(window, "title", "") or "")
    except Exception:                                                    # noqa: BLE001
        title = ""
    return _find_hwnd(title)


def watch(window, path, note=None, delay=0.8):
    """盯着这扇窗口，把"正常状态下的大小和位置"记进 `path`（`V-223`）。

    · `moved` / `resized` / `maximized` / `restored` 都只是**打个标记**，真正的快照延迟
      `delay` 秒后取一次 —— 拖窗口会连发几十个事件，不能每个都写盘；
    · 最小化**不存**（那时候坐标是 `-32000` 那种）；
    · 关窗时立刻补一次（`closed`）；
    · 每次都从 `GetWindowPlacement` 现读（不看事件参数）—— 最大化那一瞬间 `moved` 可能
      比 `maximized` 先到，拿事件参数存就会把"最大化后的坐标"当成正常位置。

    返回一个 dict（探针要拿它看内部状态 / 手动 `flush()`）。
    """
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
                return False                      # 没变就别写盘
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
        """关窗**之前**补一次（`closing` 早于窗口销毁 —— 这时候窗口句柄还有效）。

        ★ 为什么不能只靠 `closed`：WinForms 的 `closed` 是在窗体**销毁之后**发的，
          那时 `GetWindowPlacement` 已经拿不到东西了 ⇒ 最后那次位置就丢了。
        """
        with st["lock"]:
            if st["timer"] is not None:
                st["timer"].cancel()
                st["timer"] = None
        write_now()

    for ev in ("moved", "resized", "maximized", "restored"):
        try:
            event = getattr(window.events, ev)
            event += soon                     # pywebview 的 Event 支持 `+=`
        except Exception:                                                # noqa: BLE001
            pass
    for ev in ("closing", "closed"):
        try:
            event = getattr(window.events, ev)
            event += on_closing
        except Exception:                                                # noqa: BLE001
            pass
    st["flush"] = write_now
    return st
