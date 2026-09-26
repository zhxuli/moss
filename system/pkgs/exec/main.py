#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快捷执行 (exec) —— QuickTools 插件

  moss :exec               打开管理器
  moss :exec list          在控制台列出全部命令
  moss :exec <别名> [参数]  直接在控制台执行该命令

数据位置：宿主 moss 注入的 MOSS_PLUGIN_DATA_DIR/cmds/<别名>.json
（= user_data/state/exec/cmds）；老 pa 的 PA_* 与插件自身目录作兜底。

界面说明：主界面是 WebView2（Apple 风格，见 gui_web.py）；若本机缺 pywebview
或 WebView2 运行时，自动退回 tkinter 基础界面（gui_tk.py）。
"""
import sys

import core


def print_list():
    core.init_cmds_dir()
    commands = core.load_all_commands()
    if not commands:
        print("[提示] 当前没有任何预设命令，运行 'moss :exec' 打开管理器添加。")
        return
    print("\n[当前可用命令清单]")
    print("-" * 52)
    width = max([len(c['alias']) for c in commands] + [5])
    for c in commands:
        print(" %-*s | [%-6s] | %s" % (width, c['alias'], c['type'].upper(), c['description']))
    print("-" * 52)


def run_alias(alias, args):
    core.init_cmds_dir()
    item = core.load_command(alias)
    if not item:
        print("[错误] 未知命令 '%s'。" % alias)
        print("  · exec 里已有的命令：moss :exec list")
        print("  · 所有已安装的包：  moss")
        return 1
    core.run_in_console(item, args)
    return 0


def run_gui():
    """优先 WebView 界面；不可用时退回 tkinter。"""
    try:
        import webview  # noqa: F401
        from gui_web import run_gui as run_web
    except Exception as e:
        print("[提示] WebView 界面不可用（%s），改用基础界面。" % e)
        from gui_tk import run_gui as run_base
        run_base()
        return
    run_web()

def _moss_args():
    """moss 宿主把包参数放在 MOSS_PKG_PARAMS / MOSS_ARGS 里（老 pa 是拼在 argv 里）。
    有就返回解析好的参数表，没有返回 None —— 那就走原来的 sys.argv 逻辑。"""
    import json as _json
    import os as _os
    # ★ 空串要当成"宿主没给参数"，继续往下走、最后退回 sys.argv（同一个坑：
    #   moss 注入的 MOSS_PKG_PARAMS 会留在整个子进程树里，值通常是 {"args": ""}；
    #   旧写法直接返回 []，于是 sys.argv 永远轮不到 —— 见 dsh/main.py 里的长注释）。
    raw = _os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            got = str(_json.loads(raw).get("args") or "").strip()
            if got:
                return core.split_args(got)
        except Exception:
            pass
    raw = (_os.environ.get("MOSS_ARGS") or "").strip()
    if raw:
        return core.split_args(raw)
    return None


def main():
    # pa 会把插件参数拼成一个字符串传进来，这里拆回参数列表。
    # 用 core.split_args 而不是 shlex —— shlex 会吃掉 Windows 路径里的反斜杠。
    clean_args = _moss_args()
    if clean_args is None:
        clean_args = []
        for arg in sys.argv:
            if arg in ['-c', ''] or arg.endswith('main.py'):
                continue
            clean_args.extend(core.split_args(arg))

    if not clean_args:
        run_gui()
        return

    first = clean_args[0].lower()
    rest = clean_args[1:]

    if first in ('gui', '-g', '--gui'):
        run_gui()
        return

    if first in ('list', 'ls'):
        print_list()
        return

    # 内部入口：界面里的"在新控制台窗口运行"会用到
    if first == '--run':
        if not rest:
            print("[错误] --run 需要一个命令别名。")
            return
        run_alias(rest[0], rest[1:])
        return

    run_alias(first, rest)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[提示] 操作已取消。")
