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
    try:
        import webview
        from gui_web import run_gui as run_web
    except Exception as e:
        print("[提示] WebView 界面不可用（%s），改用基础界面。" % e)
        from gui_tk import run_gui as run_base
        run_base()
        return
    run_web()

def _moss_args():
    import json as _json
    import os as _os
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
    try:
        from embed import Embedded, embedded_now
        if embedded_now():
            return Embedded().loop()
    except ImportError:
        pass

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
