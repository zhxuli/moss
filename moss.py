#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""moss 入口。

    moss m            在当前目录找 main.py / main.go / main.html 并运行
    moss :hello       运行装上来的包
    moss --help


════════════════════════════════════════════════════════════════════════
 打包命令（留在这里一份，方便直接看、直接粘）
════════════════════════════════════════════════════════════════════════

    venv\Scripts\python.exe -m nuitka --onefile --lto=yes --remove-output --assume-yes-for-downloads --onefile-tempdir-spec="{CACHE_DIR}/moss_build/moss-<stamp>" --onefile-cache-mode=cached --windows-icon-from-ico=system/icon/moss.ico --windows-console-mode=hide --include-package=core -o moss moss.py

    （懒得敲就在仓库根目录敲  build.cmd  —— 它 cd 到自己那个目录再调上面这条；
      `build.py` 自己不依赖 cwd，所以从哪个目录敲都一样。）

★ 上面这一行和 `tools\build.py` 里实际执行的是**同一条命令**。
  `build.py` 每次开工前会**自动核对这一行**：对不上就直接报错停下，
  不会照着一条过期的命令去撞墙。所以这里可以放心留一份。

  要改命令，两处一起改（build.py 会把对不上的地方指出来）。

★ 那个 `<stamp>` 是 `build.py` 自己算出来的**构建指纹**（`moss.py` + `core/**` + 图标 +
  固定参数的内容哈希 **+ 构建时刻**，8 位十六进制），核对的时候按占位符比 —— 注释里写不出
  具体值。**每次打包一个新目录**，旧的打包时清掉（清不掉的跳过：那份正被运行中的 moss 占着）。
  为什么不是 `{TIME}`：nuitka 把 `{TIME}` 当成"每次**运行**都会变"，于是**每次启动都重新解包
  23 MB**（实测 1.2 秒，只该 0.3 秒），而且一声不响、解包目录还会堆（实测堆到 95 个 /
  2.1 GB）。`--onefile-cache-mode=cached` 是保险：以后谁再把 `{TIME}` 塞回来，**打包当场
  报错**。细节见 `tools/build.py` 的 `source_stamp()`。

★ 打包时如果旧的 `moss.exe` 正被占着（界面开着），`build.py` 会**把产物打成 `moss.exe.exe`**
  （你定的名字：仍然是 `.exe`、能直接双击运行）—— 正在跑的那个 `moss.exe` 一个字节都不动。
  关掉 moss 之后再打一次，就会正常替换 `moss.exe`（并顺手清掉那个 `moss.exe.exe`）。

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
  包（`system/pkgs`）刻意留在 exe 外面 —— 那是 `K-10` 内核最小化：
  加功能 = 丢一个目录，不用重编 exe。

· `--windows-console-mode=hide`（`G-18` ✅，2026-09-27）
  一个 exe 要同时当命令行程序和界面程序用，就靠这一档。
  nuitka 四档的差别只在"要不要给它一个控制台窗口"：
      force（默认）从终端启动就用那个终端，没有就**新建一个**（双击弹黑框）
      disable      完全不用也不建控制台（终端里敲就什么都看不见）
      attach       有现成的控制台就用它输出，没有就一个都不建
      hide         新建的控制台**藏起来**；已有控制台（终端里敲）时与 force 相同
                   ← 就是它
  `hide` 下产物仍是**控制台子系统**，这一点至关重要：**PowerShell 对 GUI 子系统的
  exe 根本不等**（实测 `attach` 档下 `moss ui` 0.04 秒就返回、窗口还在开），
  而 `moss cd`（要靠父 shell 阻塞着才读得到注入进去的按键）、`--history` 的
  方向键列表、`img` 那种命令行菜单**全都依赖"shell 在等它"**。
  `hide` 两样都要到了：终端里一切照旧（连 Ctrl-C、交互输入都不变），
  双击 / 快捷方式 / 快速启动栏启动时那个黑框在 bootstrap 阶段就被 `SW_HIDE` 掉
  （判据是它当时是那个控制台上唯一的进程）。
  判"是不是被双击启动的"因此不能只看"有没有控制台"，还得看那个控制台窗口
  是不是被藏起来的 —— 见 `core/shell.py:gui_mode()`。

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

# ★ 第一件事就把控制台切成 UTF-8。
#   程序里到处是 ✔ ✗ ⚠ 这类符号，Windows 中文控制台默认 cp936，
#   `moss --selfcheck` 会直接 `gbk codec can't encode character '\u2714'` 崩掉。
#   放在 import core 之前是最保险的位置（out 模块 import 时也会再兜一次）。
from core import out as _out     # noqa: E402
_out.ensure_utf8_console()

from core import cli       # noqa: E402


def main():
    try:
        return cli.main(sys.argv[1:])
    except KeyboardInterrupt:
        print("\n[提示] 操作已取消。")
        return 130


if __name__ == "__main__":
    sys.exit(main())
