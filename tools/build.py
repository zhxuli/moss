#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 moss 打包成单文件 moss.exe。

用法
----
    venv\\Scripts\\python.exe tools\\build.py            打包
    venv\\Scripts\\python.exe tools\\build.py --check    只做前置检查，不打包

首次使用（venv 还不存在时）：

    py -3.12 -m venv venv
    venv\\Scripts\\python.exe -m pip install nuitka


关于"命令写在两个地方"
---------------------
用户要求打包命令必须在 `moss.py` 的注释里也留一份（方便直接看）。
重复就会漂移 —— 本项目真发生过：注释和实际命令对不上，照抄必炸。

所以这里加了一道**自动核对**：`build.py` 每次开工前，把 `moss.py` 注释里那条
命令和自己真正要执行的对一遍，不一致就直接报错停下。

**重复是允许的，但漂移是不允许的。** 想改命令，两处一起改。

（用户原话：「你必须把命令放到注释里面一份」）

为什么要用 Python 而不是 .cmd
-----------------------------
Windows 批处理对**文件编码**和**行尾**极其敏感，我踩了两次：

  · 中文注释在 cp936 下字节被拆坏 —— go build 压根没跑成
  · LF 行尾（我自己 .gitattributes 里 `eol=lf` 造成的）让 cmd 解析错乱，
    REM 里的英文单词被当成命令执行

Python 脚本没有这两个问题。少一类文件，少一类坑。

为什么必须 Python 3.12、必须 venv
---------------------------------
nuitka 在 Python 3.13 + MinGW/gcc 下**不受支持**：

    FATAL: non-MSVC is not currently supported with Python 3.13,
           due to differences in layout internal structures of Python.

这台机器没装 Visual Studio，所以 `--msvc=latest` 那条路也走不通。
venv 把构建工具链挡在系统 Python 外面，名字用规范的 `venv`。
"""
import os
import subprocess
import sys
from pathlib import Path

HOME = Path(__file__).resolve().parent.parent
REQUIRED = (3, 12)
DOC_SOURCE = "moss.py"          # 注释里留了一份命令的那个文件
DOC_MARKER = "-m nuitka"


def die(msg, code=1):
    print("[错误] %s" % msg)
    return code


def _normalize(s):
    """比对前归一化，容忍三种写法差异：

    1. 引号 —— 注释里为了能直接粘进 PowerShell 要给 {CACHE_DIR}/... 加引号，
       subprocess 直接传参不需要
    2. 反斜杠双写 —— 普通字符串里的 `\\` 和原始字符串里的 `\\` 在源码文本上
       看起来一样，但含义不同；统一按单反斜杠比
    3. 多余空白
    """
    s = s.replace("\\\\", "\\")
    return " ".join(s.replace('"', "").replace("'", "").split())


def check_doc_sync(cmd):
    """核对 moss.py 注释里的命令和 cmd 是否一致。返回错误串或 None。

    这就是让"命令写两份"变安全的东西 —— 没有它，注释迟早变成错误指令。
    """
    doc_path = HOME / DOC_SOURCE
    if not doc_path.is_file():
        return "找不到 %s" % doc_path

    want = _normalize(" ".join(cmd[3:]))          # cmd[3:] = nuitka 之后的全部参数
    found = None
    for line in doc_path.read_text(encoding="utf-8").splitlines():
        if DOC_MARKER in line:
            found = line.split(DOC_MARKER, 1)[1]
            break

    if found is None:
        return ("%s 的注释里找不到打包命令（要求必须留一份）。\n"
                "       应当有一行形如：venv\\Scripts\\python.exe -m nuitka ..."
                % DOC_SOURCE)

    got = _normalize(found)
    if got != want:
        return ("%s 注释里的打包命令和 build.py 实际要跑的不一致 —— 不许漂移：\n"
                "       注释 : %s\n"
                "       实际 : %s\n"
                "       两处一起改。"
                % (DOC_SOURCE, got[:120], want[:120]))

    # 另外确认注释里写的是 venv 里的解释器，不是系统 python
    head = doc_path.read_text(encoding="utf-8")
    if "venv\\Scripts\\python.exe" not in head and "venv/Scripts/python.exe" not in head:
        return ("%s 注释里的解释器不是 venv\\Scripts\\python.exe —— "
                "用系统 python（3.13）会 FATAL。" % DOC_SOURCE)
    return None


def preflight():
    """返回 (cmd, None) 或 (None, 错误码)。"""
    print("moss 打包")
    print("=" * 64)
    print("  安装根 : %s" % HOME)

    if not (HOME / "moss.py").is_file():
        return None, die("找不到 moss.py")
    if not (HOME / "icon.ico").is_file():
        return None, die("找不到 icon.ico（见 design\\图标提示词.md）")

    print("  构建器 : Python %d.%d.%d" % sys.version_info[:3])
    if sys.version_info[:2] != REQUIRED:
        return None, die("必须用 Python %d.%d 打包（nuitka 在 3.13 + MinGW 下不受支持）。\n"
                         "       正确用法：venv\\Scripts\\python.exe tools\\build.py\n"
                         "       venv 不存在：py -3.12 -m venv venv && "
                         "venv\\Scripts\\python.exe -m pip install nuitka" % REQUIRED)

    try:
        import nuitka  # noqa: F401
    except ImportError:
        return None, die("这个 Python 里没有 nuitka。装一下：\n"
                         "       %s -m pip install nuitka" % sys.executable)

    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--lto=yes",
        "--remove-output",
        # nuitka 要用它自己那份精确匹配的 winlibs MinGW gcc。
        # 非交互环境下它会自动答 "no" 然后失败，所以必须加这个开关。
        "--assume-yes-for-downloads",
        '--onefile-tempdir-spec={CACHE_DIR}/moss_build/{TIME}',
        "--windows-icon-from-ico=icon.ico",
        "--include-package=core",
        "-o", "moss",
        "moss.py",
    ]

    err = check_doc_sync(cmd)
    if err:
        return None, die(err)

    print("  注释核对: ✔ %s 里的命令与本次要执行的一致" % DOC_SOURCE)
    print("  产物   : %s" % (HOME / "moss.exe"))
    print("=" * 64)
    print("实际执行的命令（唯一出处；%s 注释里那一份由上面核对保证同步）："
          % DOC_SOURCE)
    print("  %s -m nuitka %s" % (sys.executable, " ".join(cmd[3:])))
    print("=" * 64)
    return cmd, 0


def main():
    check_only = "--check" in sys.argv[1:]

    cmd, code = preflight()
    if cmd is None:
        return code

    if check_only:
        print("[检查模式] 前置检查全部通过，未执行打包。")
        return 0

    print("开始编译。首次运行会下载约 100MB 的 C 编译器到用户缓存（之后不再下载），")
    print("之后每次约 1-3 分钟。")
    print("=" * 64)
    sys.stdout.flush()

    rc = subprocess.call(cmd, cwd=str(HOME))
    if rc != 0:
        return die("nuitka 返回 %d，打包失败。" % rc)

    exe = HOME / "moss.exe"
    if not exe.is_file():
        return die("nuitka 报成功，但 moss.exe 不存在。")

    print()
    print("=" * 64)
    print("[完成] %s  (%.1f MB)" % (exe, exe.stat().st_size / 1048576))
    print("=" * 64)
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
