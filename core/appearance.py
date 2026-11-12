import json
import sys

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

def as_env():
    return json.dumps(appearance(), ensure_ascii=False)
