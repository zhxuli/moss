# -*- coding: utf-8 -*-
"""输出与屏幕控制。

★ 照抄 pa.py:39-50（print_cyan / CYAN / RESET）和 pa.py:201-207（清屏）。
  pa.py 的控制台配色和"自动清屏"是用户天天在看的，原样搬过来。

★ 另外在这里统一做一次**控制台 UTF-8 兜底**（见 `ensure_utf8_console`）：
  程序里到处是 ✔ ✗ ⚠ 这类符号，Windows 中文控制台默认 cp936 编码，
  `print('✔')` 会直接 UnicodeEncodeError 把程序崩掉。
"""
import ctypes
import os
import sys

from . import config

CYAN = '\033[36;1m'
RESET = '\033[0m'


def ensure_utf8_console():
    """让控制台吃得下 ✔ ✗ ⚠ 这类符号。两步，缺一不可：

      1. 把**控制台代码页**切成 UTF-8（65001）—— 只改 Python 这边的话，
         字节到了控制台还是花屏；
      2. 把 `sys.stdout/stderr` 重设成 UTF-8 —— 只改代码页的话，
         Python 仍按 cp936 编码，照样抛 UnicodeEncodeError。

    任一步失败都不抛异常：`errors='replace'` 兜底，最坏情况显示成 `?`，
    **绝不允许因为一个符号把整个程序崩掉**。

    实测事故：`moss --selfcheck` 在中文控制台上必崩 ——
    `gbk codec can't encode character '\\u2714'`，而它检查的东西全是好的。
    """
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
    """青色加粗输出。照抄 pa.py:43-50。"""
    sep = kwargs.get('sep', ' ')
    end = kwargs.get('end', '\n')
    kwargs['end'] = ''
    print(CYAN, end='')
    print(*args, **kwargs)
    print(RESET, end=end)


def clear_screen():
    """照抄 pa.py:201-202。"""
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
    """可见窗口的（列数, 行数）。取不到返回 None。

    ★ **权威来源是控制台自己**，不能用 `shutil.get_terminal_size()` ——
      它优先信 `COLUMNS`/`LINES` 环境变量，一旦那个值比真实窗口宽，
      打出来的行就会**折行**，而折行会让"原地重画"的行数算错、整屏错位（实测踩过）。
    """
    info = _screen_info()
    if not info:
        return None
    w = info.srWindow.Right - info.srWindow.Left + 1
    h = info.srWindow.Bottom - info.srWindow.Top + 1
    return (w, h) if w > 0 and h > 0 else None


def cursor_pos():
    """当前光标（列, 行）。取不到返回 None。"""
    info = _screen_info()
    return (info.dwCursorPosition.X, info.dwCursorPosition.Y) if info else None


def gotoxy(x, y):
    """把光标挪到 (列, 行)。**不用 ANSI 转义** —— 转义在"\\n 不回车"的控制台上
    会把原地重画画到半行上去（实测整屏糊掉），走 Win32 API 没这个问题。"""
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
    """把一组行铺满屏宽写出（**补齐空格 = 擦掉上一帧的残留**），行尾用 `\\r\\n`。

    为什么不用 `\\033[K` + `\\n`：开了 VT 的控制台上 Python 的 `\\n` 有可能
    只下移不回车，于是"原地重画"落在半行上 —— 实测就是这个把界面糊了。
    """
    pad = max(1, width - 1)
    sys.stdout.write("\r\n".join(str(ln)[:pad].ljust(pad) for ln in lines))
    sys.stdout.flush()


def enable_ansi():
    """打开 ANSI 光标控制（`\\033[A` 上移、`\\033[K` 清到行尾）。返回是否可用。

    为什么必须有：历史列表要**原地重画**二十来行，靠 `cls` 整屏清会闪得没法用。
    Python 3.6+ 通常已经替我们开了这个模式，但不能假定 ——
    被重定向、老 conhost、或者宿主改过控制台模式时就不生效。
    """
    if os.name != 'nt':
        return True
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.GetStdHandle(STD_OUTPUT_HANDLE)
        mode = ctypes.c_uint32()
        if not k32.GetConsoleMode(h, ctypes.byref(mode)):
            return False                      # 输出不是控制台（被重定向了）
        if mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING:
            return True
        return bool(k32.SetConsoleMode(
            h, mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING))
    except Exception:
        return False


def conditional_clear_screen():
    """照抄 pa.py:205-207：受 output.auto_clear_screen 控制。"""
    if config.auto_clear():
        clear_screen()


def banner_lines(started_at, cmd_str, cwd, pid=None):
    """执行前后的横幅。照抄 pa.py:226-231 与 307-313 的字段与顺序。"""
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
    """收尾横幅。照抄 pa.py:307-313。"""
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
