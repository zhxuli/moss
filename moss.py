#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""moss 入口。

    python moss.py m            在当前目录找 main.py / main.go / main.html 并运行
    python moss.py :hello       运行装上来的包
    python moss.py --help


════════════════════════════════════════════════════════════════════════
 打包命令（★ 这是【在终端里执行】的命令，别粘到这个文件里来）
════════════════════════════════════════════════════════════════════════

    python -m nuitka --onefile --lto=yes --remove-output --onefile-tempdir-spec="{CACHE_DIR}/moss_build/{TIME}" --windows-icon-from-ico=icon.ico --include-package=core -o moss moss.py

（就这一行，不用换行符续行 —— PowerShell 用反引号、cmd 用 ^，
  两者不通，写成一行最省事。或者直接跑 tools\\打包.cmd）

为什么要 --include-package=core：
    本文件是先 sys.path.insert(...) 再 `from core import cli`，
    nuitka 的静态分析不一定跟得上这种动态 sys.path 操作。不加的话打包会成功，
    但运行时可能报 `No module named 'core'`。

为什么【不要】加 --include-data-dir：
    包（system/pkgs、dev/pkgs）刻意留在 exe 外面 —— 那是 K-10 内核最小化：
    加功能 = 丢一个目录，不用重编 exe。塞进去就反了。

发行与自检：
    moss.exe 和 system/ 必须放在一起（user_data/ 首次运行自动创建）。
    打包完立刻跑：  .\\moss.exe --selfcheck
    再换个目录跑：  cd 任意项目 && D:\\...\\moss.exe m     （验证 MOSS_HOME 定位正确）
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
