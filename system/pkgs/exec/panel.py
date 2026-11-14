"""右侧内嵌的网页面板。

网页站几乎都会用 X-Frame-Options / CSP 拒绝被 iframe 嵌入（百度、GitHub 都拒绝，
实测 iframe 里只剩一个禁止图标），所以这里不用 iframe：直接开一扇**真的** WebView2
窗口，再用 SetParent 贴进主窗口的右侧区域。这样地址栏、证书、登录全都是浏览器自己的，
页面也不会被站点判成「被嵌入」。

只在本包自己开窗（gui_web）时可用；界面被内嵌进 moss 选项卡时没有自己的窗口可贴，
attach 会失败，前端据此隐藏「浏览」。
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes

_user32 = ctypes.windll.user32

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
SW_HIDE = 0
SW_SHOWNA = 8

_TITLE_TAG = '__exec_web_panel__'


def _windows_of_this_process():
    """本进程的顶层窗口 -> [(hwnd, 标题, 面积)]"""
    pid = os.getpid()
    got = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def each(hwnd, _lparam):
        owner = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != pid:
            return True
        n = _user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        _user32.GetWindowTextW(hwnd, buf, n + 1)
        rc = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(rc))
        area = max(0, rc.right - rc.left) * max(0, rc.bottom - rc.top)
        got.append((hwnd, buf.value, area))
        return True

    _user32.EnumWindows(each, 0)
    return got


def _by_title(title):
    hwnd = _user32.FindWindowW(None, title)
    return hwnd or None


def _is_alive(hwnd):
    return bool(hwnd) and bool(_user32.IsWindow(hwnd))


class WebPanel:
    """一扇贴进主窗口的网页窗口。show/hide/move 都可反复调。"""

    def __init__(self, log_path=None):
        self._title = _TITLE_TAG + '%d' % os.getpid()
        self._win = None
        self._hwnd = None
        self._parent = None
        self._url = ''
        self._lock = threading.Lock()
        self._log = log_path
        self._creating = False
        self._want = None
        self._box = None
        self.available = False

    def _note(self, text):
        if not self._log:
            return
        try:
            os.makedirs(os.path.dirname(self._log), exist_ok=True)
            with open(self._log, 'a', encoding='utf-8') as f:
                f.write('[%s] %s\n' % (time.strftime('%H:%M:%S'), text))
        except OSError:
            pass

    # ---- 主窗口 ----------------------------------------------------
    def attach(self, hint_title=None):
        """找到要贴进去的主窗口。内嵌模式（本进程没有自己的窗口）返回 False。"""
        if hint_title:
            self._parent = _by_title(hint_title)
        if not _is_alive(self._parent):
            # 自己的窗口里挑最大的那个（界面还没显示出来时也算）
            best = None
            for hwnd, title, area in _windows_of_this_process():
                if title.startswith(_TITLE_TAG) or area < 20000:
                    continue
                if best is None or area > best[1]:
                    best = (hwnd, area)
            self._parent = best[0] if best else None
        self.available = _is_alive(self._parent)
        return self.available

    # ---- 内容 ------------------------------------------------------
    def show(self, url, box=None, force=False):
        """把 url 显示在右侧。box = (x, y, w, h)，单位是设备像素。

        ★ 这个方法可能跑在 pywebview 的桥接线程里：建窗（create_window）有时会等
        界面线程，一旦卡住，排在后面的所有调用（包括保存）都再也排不上队 ——
        界面上表现成「点了完全没反应」。所以建窗一律丢到后台线程，这里立刻返回。
        """
        if not self.available and not self.attach():
            return False
        url = (url or '').strip()
        if not url:
            return False
        if box:
            self._box = box
        if not (self._hwnd and _is_alive(self._hwnd)):
            self._want = (url, box, force)
            if not self._creating:
                self._creating = True
                threading.Thread(target=self._build, daemon=True).start()
            return True
        return self._apply(url, box, force)

    def _build(self):
        """后台把窗口建出来并贴好，然后放上要显示的页面。"""
        try:
            with self._lock:
                self._sweep()
                ok = self._create()
            self._note('_build 建窗 ok=%s' % ok)
            want = self._want
            if ok and want:
                self._apply(want[0], want[1], want[2])
        except Exception as e:
            self._note('_build 出错：%s: %s' % (type(e).__name__, e))
        finally:
            self._creating = False

    def _apply(self, url, box, force=False):
        if force or url != self._url:
            try:
                self._win.load_url(url)
                self._url = url
            except Exception as e:
                self._note('load_url 失败：%s' % e)
                return False
        if box:
            self.move(box)
        _user32.ShowWindow(self._hwnd, SW_SHOWNA)
        return True

    def _sweep(self):
        """只认自己那扇窗口：留着多余的同名窗会让界面上多出一条白边。"""
        if not _is_alive(self._hwnd):
            self._hwnd = None
            self._win = None
        keep = self._hwnd
        for hwnd, title, _area in _windows_of_this_process():
            if title == self._title and hwnd != keep:
                _user32.PostMessageW(hwnd, 0x0010, 0, 0)

    def _create(self, tries=60):
        try:
            import webview
        except Exception:
            return False
        kwargs = dict(url='about:blank', frameless=True, width=600, height=400,
                      x=0, y=0, background_color='#ffffff')
        try:
            self._win = webview.create_window(self._title, **kwargs)
        except Exception:
            return False
        for _ in range(tries):
            hwnd = _by_title(self._title)
            if hwnd:
                self._hwnd = hwnd
                break
            time.sleep(0.05)
        if not self._hwnd:
            return False
        style = _user32.GetWindowLongW(self._hwnd, GWL_STYLE)
        _user32.SetWindowLongW(self._hwnd, GWL_STYLE, (style & ~WS_POPUP) | WS_CHILD)
        if not _user32.SetParent(self._hwnd, self._parent):
            return False
        return True

    def move(self, box):
        self._box = box
        if not (self._hwnd and _is_alive(self._hwnd)):
            return False
        x, y, w, h = [int(round(v)) for v in box]
        ok = bool(_user32.MoveWindow(self._hwnd, x, y, max(1, w), max(1, h), True))
        rc = wintypes.RECT()
        _user32.GetWindowRect(self._hwnd, ctypes.byref(rc))
        self._note('move box=%s ok=%s -> (%d,%d,%d,%d)'
                   % ((x, y, w, h), ok, rc.left, rc.top,
                      rc.right - rc.left, rc.bottom - rc.top))
        return ok

    def is_ready(self):
        """贴进去的那扇窗口现在是不是真的在。"""
        return bool(self._hwnd) and _is_alive(self._hwnd)

    def hide(self):
        if self._hwnd and _is_alive(self._hwnd):
            _user32.ShowWindow(self._hwnd, SW_HIDE)
            return True
        return False

    def close(self):
        if self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win = None
        self._hwnd = None
