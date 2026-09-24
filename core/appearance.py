# -*- coding: utf-8 -*-
"""系统外观：深浅模式 + Windows 强调色。

★ 照抄旧项目 `bin/soft/exec/gui_web.py` 的 appearance 部分（E-20 照抄原则）。
  那段代码里有几个已经踩过的坑，原样搬过来：

  · DwmGetColorizationColor 是 **0xAARRGGBB** —— R 在 bits 16-23
  · DWM\\AccentColor 是 **0xAABBGGRR** —— R 在最低字节
  · 别拿"看起来像不像"去反推字节序，只认官方 API

多插件复用
----------
算出来的结果通过环境变量 `MOSS_APPEARANCE`（JSON）注入给包 ——
包是运行在自带运行时里的独立进程，**不能 import 宿主的 core**，
所以外观这种"每台机器不同的动态值"走环境变量，和 `MOSS_HOME` /
`MOSS_PKG_PARAMS` 同一个套路。包内静态的 CSS 令牌则随包分发。
"""
import json
import sys

DEFAULT_ACCENT = (0x00, 0x78, 0xD4)      # Windows 默认蓝，读不到系统强调色时用它
DARK_FG = (29, 29, 31)

# 强调色是否跟随 Windows 系统设置。改成 False 就始终用 DEFAULT_ACCENT。
USE_SYSTEM_ACCENT = True

# 白字压在强调色上至少要达到的对比度。强调色偏亮时会把填充色压暗到满足它
# （"彩色按钮配黑字"用户看着别扭）；设成 0 就完全不压暗、直接用原始强调色。
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
    """（保留给深色主题里已提亮的强调色用）返回其上的字色。"""
    return DARK_FG if _srgb_lum(accent) > 0.42 else (255, 255, 255)


def _accent_pair(rgb):
    """返回 (作为填充色的 accent, 其上的字色)。

    优先白字 —— 这是 Windows/macOS 的惯例。
    白字对比度不够时把填充色压暗到够用（最多 30%，再多颜色就发脏了）；
    本色如果本身很亮（比如系统强调色是金色），那才老老实实用深字。
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

    ⚠️ 字节序陷阱（旧项目在这里翻过一次车，写下来免得后人再"修"坏）：
      · DwmGetColorizationColor 是 **0xAARRGGBB** —— R 在 bits 16-23，有官方文档
      · DWM\\AccentColor 是 **0xAABBGGRR** —— R 在最低字节
      · Explorer\\Accent\\AccentPalette 是 RGB 顺序的字节数组
    三者对同一台机器结果一致。别拿"看起来像不像渐变"去反推字节序。
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
    """要注入给前端的 CSS 变量：深浅模式 + 强调色（含配套字色/按下色/焦点环）。"""
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


def as_env():
    """给子进程注入用的 JSON 串。"""
    return json.dumps(appearance(), ensure_ascii=False)
