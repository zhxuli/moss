#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 moss 打包成单文件 moss.exe。

用法
----
    venv\\Scripts\\python.exe tools\\build.py

首次使用（venv 还不存在时）：

    py -3.12 -m venv venv
    venv\\Scripts\\python.exe -m pip install nuitka

为什么要用 Python 而不是 .cmd
-----------------------------
Windows 批处理对**文件编码**和**行尾**极其敏感，我踩了两次：

  · 中文注释在 cp936 下字节被拆坏 —— go build 压根没跑成
  · LF 行尾（我自己的 .gitattributes 里 `eol=lf` 造成的）让 cmd 解析错乱，
    REM 注释里的英文单词被当成命令执行

Python 脚本没有这两个问题，而且能顺手做前置检查。**少一类文件，少一类坑。**

为什么必须 Python 3.12、必须 venv
---------------------------------
nuitka 在 Python 3.13 + MinGW/gcc 下**不受支持**：

    FATAL: non-MSVC is not currently supported with Python 3.13,
           due to differences in layout internal structures of Python.

这台机器没装 Visual Studio，所以 `--msvc=latest` 那条路也走不通。
venv 把构建工具链挡在系统 Python 外面，名字用规范的 `venv`（不是 .build-venv）。

为什么必须 --include-package=core
---------------------------------
moss.py 是先 sys.path.insert(...) 再 `from core import cli`，nuitka 的静态分析
不一定跟得上这种动态 sys.path 操作。不加的话打包会成功，但运行时报
`No module named 'core'`。

为什么【不要】加 --include-data-dir
-----------------------------------
包（system/pkgs、dev/pkgs）刻意留在 exe 外面 —— 那是 K-10 内核最小化：
加功能 = 丢一个目录，不用重编 exe。
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent
REQUIRED = (3, 12)


def die(msg, code=1):
    print("[错误] %s" % msg)
    return code


def main():
    print("moss 打包")
    print("=" * 62)
    print("  安装根 : %s" % HOME)

    # ---- 前置检查 ----
    if not (HOME / "moss.py").is_file():
        return die("找不到 moss.py")
    if not (HOME / "icon.ico").is_file():
        return die("找不到 icon.ico（见 design\\图标提示词.md）")

    ver = sys.version_info[:2]
    print("  构建器 : Python %d.%d.%d" % sys.version_info[:3])
    if ver != REQUIRED:
        print()
        return die("必须用 Python %d.%d 打包。nuitka 在 3.13 + MinGW 下不受支持。\n"
                   "       正确用法：venv\\Scripts\\python.exe tools\\build.py\n"
                   "       venv 不存在的话：py -3.12 -m venv venv && "
                   "venv\\Scripts\\python.exe -m pip install nuitka"
                   % REQUIRED)

    try:
        import nuitka  # noqa: F401
    except ImportError:
        print()
        return die("这个 Python 里没有 nuitka。装一下：\n"
                   "       %s -m pip install nuitka" % sys.executable)

    # ---- 打包 ----
    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--lto=yes",
        "--remove-output",
        # nuitka 要用它自己那份精确匹配的 winlibs MinGW gcc（本机 D:\soft\mingw64
        # 那个它不认，会明确拒绝）。首次使用需要下载约 100MB 到用户缓存。
        # 非交互环境下它会自动回答 "no" 然后失败，所以必须加这个开关。
        "--assume-yes-for-downloads",
        '--onefile-tempdir-spec={CACHE_DIR}/moss_build/{TIME}',
        "--windows-icon-from-ico=icon.ico",
        "--include-package=core",
        "-o", "moss",
        "moss.py",
    ]
    print("  产物   : %s" % (HOME / "moss.exe"))
    print("=" * 62)
    print("实际执行的命令（这是唯一出处，别在别处再抄一份）：")
    print("  %s -m nuitka %s" % (sys.executable, " ".join(cmd[3:])))
    print("=" * 62)
    print("开始编译。首次运行会下载约 100MB 的 C 编译器到用户缓存（之后不再下载），")
    print("之后每次约 1-3 分钟。")
    print("=" * 62)
    sys.stdout.flush()

    rc = subprocess.call(cmd, cwd=str(HOME))
    if rc != 0:
        return die("nuitka 返回 %d，打包失败。" % rc)

    exe = HOME / "moss.exe"
    if not exe.is_file():
        return die("nuitka 报成功，但 moss.exe 不存在。")

    size_mb = exe.stat().st_size / 1048576
    print()
    print("=" * 62)
    print("[完成] %s  (%.1f MB)" % (exe, size_mb))
    print("=" * 62)
    print()
    print("接下来两步别省（nuitka onefile 下路径最容易翻车）：")
    print("  1) %s --selfcheck" % exe)
    print("  2) cd 到任意项目目录，用同一路径跑  %s m" % exe)
    print()
    print("发行时：moss.exe 必须和 system\\ 文件夹放在一起。")
    print("        user_data\\ 首次运行会自动创建。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
