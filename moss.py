#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""moss 入口。

    moss m            在当前目录找 main.py / main.go / main.html 并运行
    moss :hello       运行装上来的包
    moss --help


════════════════════════════════════════════════════════════════════════
 怎么打包：跑 tools\\build.py
════════════════════════════════════════════════════════════════════════

    venv\\Scripts\\python.exe tools\\build.py

**别照抄 nuitka 命令。** 打包用的命令行只在 `tools\\build.py` 里存一份 ——
早先我在这个文件的注释里也抄了一份，结果它和真正在用的命令不一致
（漏了必须的开关、解释器也不对），照抄必然失败。
**同一条命令只留一个出处。**

build.py 里有几个必须的东西，原因值得知道：

  · 必须用 `venv\\Scripts\\python.exe`（Python 3.12），**不是系统 python**
    系统 python 是 3.13，而 nuitka 在 3.13 + MinGW/gcc 下直接 FATAL：
        non-MSVC is not currently supported with Python 3.13

  · 必须带 `--assume-yes-for-downloads`
    nuitka 首次要下载它自己那份精确匹配的 winlibs MinGW gcc
    （本机 D:\\soft\\mingw64 那个它不认）；非交互环境下它会自动回答 "no" 然后失败。

  · 必须带 `--include-package=core`
    本文件是先 `sys.path.insert(...)` 再 `from core import cli`，
    nuitka 的静态分析不一定跟得上这种动态 sys.path 操作。
    不加的话打包会成功，但运行时可能报 `No module named 'core'`。

  · **不要**加 `--include-data-dir`
    包（system/pkgs、dev/pkgs）刻意留在 exe 外面 —— 那是 K-10 内核最小化：
    加功能 = 丢一个目录，不用重编 exe。塞进去就反了。

发行与自检
----------
    moss.exe 和 system/ 必须放在一起（user_data/ 首次运行自动创建）。
    打包完立刻跑：  .\\moss.exe --selfcheck
    再换个目录跑：  cd 任意项目 && D:\\...\\moss.exe m    （验证 MOSS_HOME 定位正确）
"""
import sys
from pathlib import Path

# 保证从任意 cwd 运行都能 import core
sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import cli       # noqa: E402


def main():
    try:
        return cli.main(sys.argv[1:])
    except KeyboardInterrupt:
        print("\n[提示] 操作已取消。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
