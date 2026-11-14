import os
import sys
import threading

import core

TITLE = '快捷执行'
DEFAULT_ACCENT = (0x00, 0x78, 0xD4)
DARK_FG = (29, 29, 31)

USE_SYSTEM_ACCENT = True

MIN_ACCENT_CONTRAST = 4.0

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
    return DARK_FG if _srgb_lum(accent) > 0.42 else (255, 255, 255)

def _accent_pair(rgb):
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
    if not USE_SYSTEM_ACCENT or sys.platform != 'win32':
        return None

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

class Api:
    def __init__(self):
        self._window = None
        self._runs = {}
        self._lock = threading.Lock()
        self._panel = None

    def attach(self, window):
        self._window = window
        try:
            import panel
            self._panel = panel.WebPanel(log_path=os.path.join(core.TEMP_DIR, 'panel.log'))
            self._panel.attach(TITLE)
        except Exception:
            self._panel = None

    # ---- 右侧内嵌的网页面板 ---------------------------------------
    def _panel_box(self, p):
        try:
            dpr = float(p.get('dpr') or 1) or 1.0
            r = p.get('rect') or {}
            return tuple(float(r.get(k) or 0) * dpr for k in ('x', 'y', 'w', 'h'))
        except (TypeError, ValueError):
            return None

    def panel_show(self, params=None):
        p = self._p(params)
        if (p.get('open_in') or 'panel') != 'panel':
            return {'ok': False, 'message': '这条命令用的是系统浏览器'}
        if not self._panel:
            return {'ok': False, 'message': '这种运行方式下没有可贴的窗口'}
        url = (p.get('url') or '').strip()
        alias = str(p.get('alias') or '').strip()
        if alias:
            item = core.load_command(alias)
            if not item or item['type'] != 'url':
                return {'ok': False, 'message': '这条不是网址命令'}
            url = core._absolute_url(core.expand(item['code'], p.get('args') or ''))
        ok = self._panel.show(url, self._panel_box(p), force=bool(p.get('force')))
        self._panel._note('panel_show ok=%s url=%s available=%s'
                          % (ok, url, self._panel.available))
        return {'ok': ok, 'message': None if ok else '网页面板没能打开'}


    def panel_url(self, params=None):
        """命令 + 参数 -> 最终网址。前端用它给 iframe 填地址。"""
        p = self._p(params)
        url = (p.get('url') or '').strip()
        alias = str(p.get('alias') or '').strip()
        if alias:
            item = core.load_command(alias)
            if not item or item['type'] != 'url':
                return {'ok': False, 'message': '这条不是网址命令'}
            url = core._absolute_url(core.expand(item['code'], p.get('args') or ''))
        return {'ok': bool(url), 'url': url}

    def panel_move(self, params=None):
        if not self._panel:
            return {'ok': False}
        box = self._panel_box(self._p(params))
        return {'ok': bool(box and self._panel.move(box))}

    def panel_hide(self, params=None):
        if not self._panel:
            return {'ok': False}
        return {'ok': self._panel.hide()}

    def panel_state(self, params=None):
        return {'ok': True, 'ready': bool(self._panel and self._panel.is_ready())}

    @staticmethod
    def _p(params):
        return params if isinstance(params, dict) else {}

    def bootstrap(self, params=None):
        core.init_cmds_dir()
        look = appearance()
        if self._panel and not self._panel.available:
            self._panel.attach(TITLE)
        return {
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
            'embedded': bool(os.environ.get('MOSS_UI_EMBED')),
            'panel': bool(self._panel and self._panel.available),
        }

    def cmd_list(self, params=None):
        core.init_cmds_dir()
        return {'ok': True, 'commands': core.load_all_commands()}

    def cmd_save(self, params=None):
        p = self._p(params)
        ok, payload = core.save_command(p.get('item') or {}, p.get('original_alias'))
        if not ok:
            return {'ok': False, 'message': payload}
        return {'ok': True, 'alias': payload}

    def cmd_remove(self, params=None):
        ok, payload = core.delete_command(self._p(params).get('alias'))
        if not ok:
            return {'ok': False, 'message': payload}
        return {'ok': True, 'alias': payload}

    def run_start(self, params=None):
        p = self._p(params)
        alias = p.get('alias')
        item = core.load_command(alias)
        if not item:
            return {'ok': False, 'message': "命令 '%s' 不存在。" % alias}
        try:
            session = core.session_for(item, p.get('args') or '')
        except Exception as e:
            return {'ok': False, 'message': '无法启动：%s' % e}
        with self._lock:
            self._runs[session.id] = session
        return {'ok': True, 'id': session.id}

    def run_poll(self, params=None):
        run_id = self._p(params).get('id')
        with self._lock:
            session = self._runs.get(run_id)
        if not session:
            return {'ok': False, 'running': False, 'output': '', 'returncode': None}
        state = session.poll()
        state['ok'] = True
        return state

    def run_stop(self, params=None):
        run_id = self._p(params).get('id')
        with self._lock:
            session = self._runs.get(run_id)
        if session:
            session.stop()
        return {'ok': True}

    def run_console(self, params=None):
        p = self._p(params)
        ok, payload = core.open_in_new_console(p.get('alias'), p.get('args') or '')
        return {'ok': ok, 'message': None if ok else payload}

    def sys_reveal(self, params=None):
        try:
            core.ensure_cmds_dir()
            os.startfile(core.CMDS_DIR)
            return {'ok': True}
        except Exception as e:
            return {'ok': False, 'message': str(e)}

    def sys_copy(self, params=None):
        ok = core.clipboard_set(self._p(params).get('text') or '')
        return {'ok': ok, 'message': None if ok else '写入剪贴板失败。'}

    def sys_pick_path(self, params=None):
        kind = (self._p(params).get('kind') or 'file')
        w = self._window
        if w:
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
                return {'ok': True, 'path': '', 'cancelled': True}
            first = picked[0] if isinstance(picked, (list, tuple)) else picked
            return {'ok': True, 'path': str(first)}
        return self._pick_tk(kind)

    @staticmethod
    def _pick_tk(kind):
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            if kind == 'dir':
                got = filedialog.askdirectory(title='选一个目录')
            else:
                got = filedialog.askopenfilename(title='选一个文件')
            root.destroy()
        except Exception as e:
            return {'ok': False, 'message': '这个环境里开不了选择框：%s' % e}
        if not got:
            return {'ok': True, 'path': '', 'cancelled': True}
        return {'ok': True, 'path': str(got)}

def run_gui():
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
