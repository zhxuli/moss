import ctypes
import os
import sys

from . import config

CYAN = '\033[36;1m'
RESET = '\033[0m'

def stdout_is_terminal():
    stream = sys.stdout
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False

if not stdout_is_terminal():
    CYAN = ''
    RESET = ''

def null_streams_if_no_console():
    for name, mode in (("stdout", "w"), ("stderr", "w"), ("stdin", "r")):
        if getattr(sys, name, None) is None:
            try:
                setattr(sys, name, open(os.devnull, mode,
                                        encoding="utf-8", errors="replace"))
            except OSError:
                pass

null_streams_if_no_console()

def ensure_utf8_console():
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, ValueError, OSError):
            pass

ensure_utf8_console()

def print_cyan(*args, **kwargs):
    sep = kwargs.get('sep', ' ')
    end = kwargs.get('end', '\n')
    kwargs['end'] = ''
    print(CYAN, end='')
    print(*args, **kwargs)
    print(RESET, end=end)

def clear_screen():
    if not stdout_is_terminal():
        return
    os.system('cls')

ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
STD_OUTPUT_HANDLE = -11

class _COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]

class _SMALL_RECT(ctypes.Structure):
    _fields_ = [("Left", ctypes.c_short), ("Top", ctypes.c_short),
                ("Right", ctypes.c_short), ("Bottom", ctypes.c_short)]

class _CSBI(ctypes.Structure):
    _fields_ = [("dwSize", _COORD), ("dwCursorPosition", _COORD),
                ("wAttributes", ctypes.c_ushort), ("srWindow", _SMALL_RECT),
                ("dwMaximumWindowSize", _COORD)]

def _stdout_handle():
    if os.name != 'nt':
        return None
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.GetStdHandle.restype = ctypes.c_void_p
        k32.GetStdHandle.argtypes = [ctypes.c_int]
        return k32, k32.GetStdHandle(STD_OUTPUT_HANDLE)
    except Exception:
        return None

def _screen_info():
    got = _stdout_handle()
    if not got:
        return None
    k32, h = got
    try:
        import ctypes
        k32.GetConsoleScreenBufferInfo.argtypes = [ctypes.c_void_p,
                                                   ctypes.POINTER(_CSBI)]
        info = _CSBI()
        if k32.GetConsoleScreenBufferInfo(ctypes.c_void_p(h), ctypes.byref(info)):
            return info
    except Exception:
        pass
    return None

def console_size():
    info = _screen_info()
    if not info:
        return None
    w = info.srWindow.Right - info.srWindow.Left + 1
    h = info.srWindow.Bottom - info.srWindow.Top + 1
    return (w, h) if w > 0 and h > 0 else None

def cursor_pos():
    info = _screen_info()
    return (info.dwCursorPosition.X, info.dwCursorPosition.Y) if info else None

def gotoxy(x, y):
    got = _stdout_handle()
    if not got:
        return False
    k32, h = got
    try:
        import ctypes
        k32.SetConsoleCursorPosition.argtypes = [ctypes.c_void_p, _COORD]
        return bool(k32.SetConsoleCursorPosition(ctypes.c_void_p(h), _COORD(x, y)))
    except Exception:
        return False

def write_block(lines, width):
    pad = max(1, width - 1)
    sys.stdout.write("\r\n".join(str(ln)[:pad].ljust(pad) for ln in lines))
    sys.stdout.flush()

def enable_ansi():
    if os.name != 'nt':
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        if mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(k32.SetConsoleMode(
            h, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING))
    except Exception:
        return False

def conditional_clear_screen():
    if config.auto_clear():
        clear_screen()

def banner_lines(started_at, cmd_str, cwd, pid=None):
    cfg = config.output_cfg()
    symbol = cfg.get("symbol", "")
    out = []
    if cfg.get("start_banner"):
        out.append(('pre', cfg["start_banner"]))
    if cfg.get("start_time"):
        out.append(('pre', '%s  %s  %s' % (symbol,
                                           _fmt_time(started_at), symbol)))
    if cfg.get("command"):
        out.append(('pre', '[执行] %s' % cmd_str))
    if cfg.get("directory"):
        out.append(('pre', '[目录] %s' % cwd))
    if cfg.get("pid") and pid is not None:
        out.append(('mid', '[PID] %s' % pid))
    return out

def tail_lines(started_at, ended_at):
    cfg = config.output_cfg()
    symbol = cfg.get("symbol", "")
    out = []
    if cfg.get("duration"):
        out.append('[运行总长] %.2f 秒' % (ended_at - started_at))
    if cfg.get("end_time"):
        out.append('%s  %s  %s' % (symbol, _fmt_time(ended_at), symbol))
    if cfg.get("end_banner"):
        out.append(cfg["end_banner"])
    return out

def _fmt_time(ts):
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
