#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""打开网址 / 本地路径 —— 一层薄包装。

真正的判断逻辑（TLD 白名单 → 当网址还是当路径 → 补齐 http:// → start 打开）
**一个字都没改，全在旁边的 main.bat 里**，是从旧项目原样拷过来的。

为什么要这层包装
----------------
新宿主的 runner 启动模板（`system/runners.json` 里 `shell` 那条）是：

    cmd /c {entry}

**它后面不带参数** —— 宿主是把参数放在 `MOSS_PKG_PARAMS` / `MOSS_ARGS`
两个环境变量里递给子进程的。所以如果直接拿 `main.bat` 当入口，
那句 `set "input_str=%~1"` 永远是空的，脚本只会打一句"请提供参数"。

这层包装只干一件事：把宿主给的参数**原样**喂给那个 .bat。
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BAT = os.path.join(HERE, "main.bat")


def _target():
    r"""取出「要打开什么」这一个参数。

    新宿主把参数放在 `MOSS_PKG_PARAMS`（JSON，键是 pkg.json 里的参数名）里；
    读不到再退 `MOSS_ARGS`（原样字符串）；再读不到才按 `sys.argv` 取 ——
    这样直接 `python main.py google.com` 调试也照旧能用。
    """
    raw = os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            p = json.loads(raw) or {}
            if p.get("target"):
                return str(p["target"])
        except Exception:
            pass
    raw = os.environ.get("MOSS_ARGS")
    if raw:
        return raw.strip()
    for a in sys.argv[1:]:
        if a in ("-c", "") or a.endswith("main.py"):
            continue
        return a
    return ""


def main():
    t = _target()
    if not t:
        # 没给参数时的用法提示（照 .bat 自己的意思写，命令名换成 moss）
        print("用法: moss :open <url_or_path>")
        print("示例: moss :open google.com")
        print("      moss :open main.py")
        print(r'      moss :open "C:\Users\Admin"')
        # 退出码照抄旧 main.bat：它的 show_usage 最后是 goto :eof → 0
        return 0
    # 把参数交给 main.bat（列表形式，Python 会自己处理带空格路径的引号）
    return subprocess.call([os.environ.get("COMSPEC", "cmd.exe"), "/c", BAT, t])


if __name__ == "__main__":
    sys.exit(main())
