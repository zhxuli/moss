# -*- coding: utf-8 -*-
"""输出与屏幕控制。

★ 照抄 pa.py:39-50（print_cyan / CYAN / RESET）和 pa.py:201-207（清屏）。
  pa.py 的控制台配色和"自动清屏"是用户天天在看的，原样搬过来。
"""
import os

from . import config

CYAN = '\033[36;1m'
RESET = '\033[0m'


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
