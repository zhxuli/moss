# -*- coding: utf-8 -*-
"""
exec 的界面（WebView2）。

这里用 Apple 的**设计语言**——克制、留白、排版层级、材质、按下即反馈、克制的动效——
但窗口本身完全遵循 Windows 习惯：

  · 原生标题栏（可拖动 / 边缘缩放 / Win+方向贴靠 / 双击最大化 / Alt+F4 全部免费）
  · Ctrl 系快捷键，不是 ⌘
  · 跟随系统强调色，而不是硬编码 Apple 蓝

也就是说：审美是 Apple 的，操作习惯是 Windows 的。不把 Windows 应用化妆成 macOS。

为什么不用 tkinter：材质（半透明+模糊）、圆角、投影、CSS 过渡、系统字体排版，
Tk 全都做不到（Tk 没有图层合成器，子控件无法半透明）。WebView2 原生支持，
而且 bin/runtime 里已经带了 pywebview。
"""
import os
import sys
import threading

import core

TITLE = '快捷执行'
DEFAULT_ACCENT = (0x00, 0x78, 0xD4)      # Windows 默认蓝，读不到系统强调色时用它
DARK_FG = (29, 29, 31)

# 强调色是否跟随 Windows 系统设置。改成 False 就始终用 DEFAULT_ACCENT。
USE_SYSTEM_ACCENT = True

# 白字压在强调色上至少要达到的对比度。强调色偏亮时会把填充色压暗到满足它
# （"彩色按钮配黑字"用户看着别扭）；设成 0 就完全不压暗、直接用原始强调色。
MIN_ACCENT_CONTRAST = 4.0


# ---------------------------------------------------------------- 系统外观
def _hex(rgb):
    return '#%02x%02x%02x' % tuple(max(0, min(255, int(c))) for c in rgb)


def _mix(rgb, other, ratio):
    return tuple(c + (o - c) * ratio for c, o in zip(rgb, other))


def _srgb_lum(rgb):
    def ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = ch(rgb[0]), ch(rgb[1]), ch(rgb[2])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = _srgb_lum(a), _srgb_lum(b)
    lo, hi = min(la, lb), max(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _pick_fg(accent):
    """（保留给深色主题里已提亮的强调色用）返回其上的字色。"""
    return DARK_FG if _srgb_lum(accent) > 0.42 else (255, 255, 255)


def _accent_pair(rgb):
    """返回 (作为填充色的 accent, 其上的字色)。

    优先白字 —— 这是 Windows/macOS 的惯例，"彩色按钮配黑字"用户看着别扭。
    白字对比度不够时把填充色压暗到够用（最多 30%，再多颜色就发脏了）；
    本色如果本身很亮（比如系统强调色是金色），那才老老实实用深字 ——
    Windows 对浅色强调色也是这么处理的。
    """
    if _srgb_lum(rgb) > 0.42:
        return rgb, DARK_FG
    if MIN_ACCENT_CONTRAST > 0:
        for k in (0.10, 0.18, 0.24, 0.30):
            cand = _mix(rgb, (0, 0, 0), k)
            if _contrast(cand, (255, 255, 255)) >= MIN_ACCENT_CONTRAST:
                return cand, (255, 255, 255)
        return _mix(rgb, (0, 0, 0), 0.30), (255, 255, 255)
    return rgb, (255, 255, 255)


def is_dark_mode():
    """读注册表判断系统是深色还是浅色（比让 WebView 自己猜可靠）。"""
    if sys.platform != 'win32':
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize')
        try:
            value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
            return value == 0
        finally:
            winreg.CloseKey(key)
    except Exception:
        return False


def _system_accent():
    """取 Windows 强调色 RGB；取不到返回 None。

    ⚠ 字节序陷阱（我在这里翻过一次车，写下来免得后人再"修"坏）：
      · DwmGetColorizationColor 是 **0xAARRGGBB** —— R 在 bits 16-23，这是有官方文档的
      · DWM\\AccentColor 是 **0xAABBGGRR** —— R 在最低字节
      · Explorer\\Accent\\AccentPalette 是 RGB 顺序的字节数组
    三者对同一台机器结果一致。别拿"看起来像不像渐变"去反推字节序 ——
    判断只认官方 API。
    """
    if not USE_SYSTEM_ACCENT or sys.platform != 'win32':
        return None

    # 准绳：官方 API
    try:
        import ctypes
        import ctypes.wintypes as wt
        value = wt.DWORD()
        opaque = wt.BOOL()
        ctypes.windll.dwmapi.DwmGetColorizationColor(
            ctypes.byref(value), ctypes.byref(opaque))
        rgb = ((value.value >> 16) & 0xFF, (value.value >> 8) & 0xFF, value.value & 0xFF)
        if rgb != (0, 0, 0):
            return rgb
    except Exception:
        pass

    # 回退：注册表（0xAABBGGRR，R 在最低位）
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Microsoft\Windows\DWM')
        try:
            value, _ = winreg.QueryValueEx(key, 'AccentColor')
            rgb = (value & 0xFF, (value >> 8) & 0xFF, (value >> 16) & 0xFF)
            if rgb != (0, 0, 0):
                return rgb
        finally:
            winreg.CloseKey(key)
    except Exception:
        pass
    return None


def appearance():
    """要注入给前端的 CSS 变量：深浅模式 + 强调色（含配套的字色/按下色/焦点环）。"""
    rgb = _system_accent() or DEFAULT_ACCENT
    dark = is_dark_mode()
    base = _mix(rgb, (255, 255, 255), 0.30) if dark else rgb
    accent, fg = _accent_pair(base)
    press = _mix(accent, (0, 0, 0), 0.16)
    r, g, b = (int(round(c)) for c in accent)
    return {
        'theme': 'dark' if dark else 'light',
        'accent': _hex(accent),
        'accent-fg': _hex(fg),
        'accent-press': _hex(press),
        'ring': 'rgba(%d, %d, %d, %.2f)' % (r, g, b, 0.55 if dark else 0.45),
        'field-focus': 'rgba(%d, %d, %d, %.2f)' % (r, g, b, 0.22 if dark else 0.15),
    }


# ---------------------------------------------------------------- JS 桥
class Api:
    def __init__(self):
        self._window = None
        self._runs = {}
        self._lock = threading.Lock()

    def attach(self, window):
        self._window = window

    # -- 启动数据 ------------------------------------------------------
    def bootstrap(self):
        core.init_cmds_dir()
        look = appearance()
        return {
            # 前后端协议版本：前端 api.js 里也有一份，对不上会告警
            'apiVersion': 2,
            'ok': True,
            'commands': core.load_all_commands(),
            'picker': core.PICKER,
            'pickerDefault': core.PICKER_DEFAULT,
            'newTypes': core.NEW_TYPES,
            'types': core.TYPES,
            'afterActions': core.AFTER_ACTIONS,
            'placeholders': core.PLACEHOLDERS,
            'dataDir': core.CMDS_DIR,
            'theme': look['theme'],
            'accent': look,
        }

    def cmd_list(self):
        core.init_cmds_dir()
        return {'ok': True, 'commands': core.load_all_commands()}

    # -- 增删改 --------------------------------------------------------
    def cmd_save(self, item, original_alias=None):
        ok, payload = core.save_command(item or {}, original_alias)
        if not ok:
            return {'ok': False, 'message': payload}
        return {'ok': True, 'alias': payload}

    def cmd_remove(self, alias):
        ok, payload = core.delete_command(alias)
        if not ok:
            return {'ok': False, 'message': payload}
        return {'ok': True, 'alias': payload}

    # -- 运行 ----------------------------------------------------------
    def run_start(self, alias, args=''):
        item = core.load_command(alias)
        if not item:
            return {'ok': False, 'message': "命令 '%s' 不存在。" % alias}
        try:
            session = core.session_for(item, args)
        except Exception as e:
            return {'ok': False, 'message': '无法启动：%s' % e}
        with self._lock:
            self._runs[session.id] = session
        return {'ok': True, 'id': session.id}

    def run_poll(self, run_id):
        with self._lock:
            session = self._runs.get(run_id)
        if not session:
            return {'ok': False, 'running': False, 'output': '', 'returncode': None}
        state = session.poll()
        state['ok'] = True
        return state

    def run_stop(self, run_id):
        with self._lock:
            session = self._runs.get(run_id)
        if session:
            session.stop()
        return {'ok': True}

    def run_console(self, alias, args=''):
        ok, payload = core.open_in_new_console(alias, args)
        return {'ok': ok, 'message': None if ok else payload}

    # -- 其它 ----------------------------------------------------------
    def sys_reveal(self):
        try:
            core.ensure_cmds_dir()
            os.startfile(core.CMDS_DIR)
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'message': str(e)}

    def sys_copy(self, text):
        ok = core.clipboard_set(text or '')
        return {'ok': ok, 'message': None if ok else '写入剪贴板失败。'}

    def sys_pick_path(self, kind='file'):
        """打开系统文件/文件夹选择框。kind: file | dir"""
        w = self._window
        if not w:
            return {'ok': False, 'message': '窗口未就绪。'}
        try:
            import webview
            if kind == 'dir':
                picked = w.create_file_dialog(webview.FOLDER_DIALOG)
            else:
                picked = w.create_file_dialog(
                    webview.OPEN_DIALOG, allow_multiple=False,
                    file_types=('Python 文件 (*.py)', '所有文件 (*.*)'))
        except Exception as e:
            return {'ok': False, 'message': '打开选择框失败：%s' % e}
        if not picked:
            return {'ok': True, 'path': ''}
        first = picked[0] if isinstance(picked, (list, tuple)) else picked
        return {'ok': True, 'path': str(first)}


def run_gui():
    """打开管理器窗口。pywebview 缺失时抛 ImportError，由 main 决定怎么兜底。

    用 url=<本地文件> 而不是 html=<字符串>：这样才能用相对路径引用
    ui/vendor/ 下的本地资源（语法高亮库），不必把库内联进 HTML。
    pywebview 会为本地文件起一个内置 http 服务，相对路径正常工作。
    """
    import webview

    api = Api()
    index = os.path.join(core.PLUGIN_DIR, 'ui', 'index.html')
    window = webview.create_window(
        TITLE,
        url=index,
        js_api=api,
        width=1200, height=780,
        min_size=(1000, 640),
        text_select=False,
    )
    api.attach(window)
    webview.start()
