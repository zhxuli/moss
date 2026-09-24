#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""moss 入口。

    moss m            在当前目录找 main.py / main.go / main.html 并运行
    moss :hello       运行装上来的包
    moss --help


════════════════════════════════════════════════════════════════════════
 打包命令（留在这里一份，方便直接看、直接粘）
════════════════════════════════════════════════════════════════════════

    venv\Scripts\python.exe -m nuitka --onefile --lto=yes --remove-output --assume-yes-for-downloads --onefile-tempdir-spec="{CACHE_DIR}/moss_build/{TIME}" --windows-icon-from-ico=icon.ico --include-package=core -o moss moss.py

★ 上面这一行和 `tools\build.py` 里实际执行的是**同一条命令**。
  `build.py` 每次开工前会**自动核对这一行**：对不上就直接报错停下，
  不会让你照着一条过期的命令去撞墙。所以这里可以放心留一份。

  要改命令，两处一起改（build.py 会把对不上的地方指给你看）。

每个参数为什么必须有
--------------------
· `venv\Scripts\python.exe` —— **不能用系统 `python`**
  系统 python 是 3.13，nuitka 在 3.13 + MinGW/gcc 下直接 FATAL：
      non-MSVC is not currently supported with Python 3.13
  venv 里是 3.12，且把构建工具链挡在系统 Python 外面。名字用规范的 `venv`。

· `--assume-yes-for-downloads`
  nuitka 首次要下载它自己**那份精确匹配的** winlibs MinGW gcc
  （本机 `D:\soft\mingw64` 那个它明确不认）。非交互环境下它会自动回答 "no"
  然后 FATAL: Only this specific gcc is supported with Nuitka。

· `--include-package=core`
  本文件是先 `sys.path.insert(...)` 再 `from core import cli`，
  nuitka 的静态分析不一定跟得上这种动态 sys.path 操作。
  不加的话打包会成功，但运行时可能报 `No module named 'core'`。

· **不要**加 `--include-data-dir`
  包（`system/pkgs`、`dev/pkgs`）刻意留在 exe 外面 —— 那是 `K-10` 内核最小化：
  加功能 = 丢一个目录，不用重编 exe。

发行与自检
----------
`moss.exe` 和 `system/` 必须放在一起（`user_data/` 首次运行自动创建）。
打包完立刻跑：

    .\moss.exe --selfcheck
    cd 任意项目 && D:\...\moss.exe m      # 验证 MOSS_HOME 定位正确
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
