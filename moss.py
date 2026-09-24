#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""moss 入口。

    python moss.py m            在当前目录找 main.py / main.go / main.html 并运行
    python moss.py :hello       运行装上来的包
    python moss.py --help

打包（M1 之后再做）：
    python -m nuitka --onefile --windows-icon-from-ico=icon.ico -o moss moss.py
    ★ 打包后 system/ 要跟着 exe 一起分发（G-04）。
      路径定位走 core/paths.py，用的是 sys.argv[0]（照抄 pa.py），onefile 下也正确。
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
