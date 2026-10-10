#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 moss 打包成单文件 moss.exe。

用法
----
    build.cmd                                           打包（仓库根目录，双击 / 直接敲都行）
    venv\\Scripts\\python.exe tools\\build.py            打包（等价写法，`build.cmd` 就干这个）
    venv\\Scripts\\python.exe tools\\build.py --check    只做前置检查，不打包

★ `build.cmd` 只是"省得敲一长串"：它先 `cd /d "%~dp0"`（自己所在的那个目录）再调 venv 里
  那个 python ⇒ **在哪个目录敲它都一样**。`build.py` 自己**也不依赖 cwd**
  （`HOME = Path(__file__).resolve().parent.parent`，并把 nuitka 的 cwd 设成 HOME）。
  ⚠️ `.cmd` 里**只放 ASCII**：Windows 批处理在 cp936 下会把中文注释的字节拆坏
  （见下面"为什么要用 Python 而不是 .cmd"），真正的逻辑一条都不写在 `.cmd` 里。

首次使用（venv 还不存在时）：

    py -3.12 -m venv venv
    venv\\Scripts\\python.exe -m pip install nuitka

  （2026-09-25 起不再需要 pyautogui：`moss cd` 改成用 ctypes 直接往控制台
    输入缓冲区注入按键，见 core/shell.py。exe 也因此从 8.1 MB 回落。）


关于"命令写在两个地方"
---------------------
用户要求打包命令必须在 `moss.py` 的注释里也留一份（方便直接看）。
重复就会漂移 —— 本项目真发生过：注释和实际命令对不上，照抄必炸。

所以这里加了一道**自动核对**：`build.py` 每次开工前，把 `moss.py` 注释里那条
命令和自己真正要执行的对一遍，不一致就直接报错停下。

**重复是允许的，但漂移是不允许的。** 想改命令，两处一起改。

（要求：打包命令必须在注释里也留一份）

为什么要用 Python 而不是 .cmd
-----------------------------
Windows 批处理对**文件编码**和**行尾**极其敏感，踩过两次：

  · 中文注释在 cp936 下字节被拆坏 —— go build 压根没跑成
  · LF 行尾（.gitattributes 里 `eol=lf` 造成的）让 cmd 解析错乱，
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
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

# ★ 控制台编码：Windows 中文系统的控制台默认 cp936(GBK)，
#   本文件里有 ✔ ✗ 这类符号，print 时直接 UnicodeEncodeError 崩在半路
#   （踩过：前置检查明明通过了，却报 "gbk codec can't encode character '\u2714'"）。
#   改成 UTF-8 并让控制台跟着切页；真出不来也只会变成 ?，不会中断打包。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
if os.name == "nt":
    try:
        subprocess.run(["chcp", "65001"], shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

HOME = Path(__file__).resolve().parent.parent
REQUIRED = (3, 12)
DOC_SOURCE = "moss.py"          # 注释里留了一份命令的那个文件
DOC_MARKER = "-m nuitka"

#: 图标（`V-181`）：**一份，放在 `system/` 里**。两处消费它 ——
#:   ① 构建时嵌进 exe（`--windows-icon-from-ico`）；
#:   ② 界面服务拿它当 `/favicon.ico` 发（`system/ui/main.py` 里同一路径）。
#: ★ 为什么从仓库根搬进 `system/`：`system/` 是**发行目录**（`moss.exe` + `system/`），
#:   图标属于发行物、不属于源码树；放根上还有第二个坏处 —— 发行包往别处一拷，
#:   图标就跟安装根脱钩了。**用相对路径**（nuitka 的 cwd 是安装根，实测 build.py
#:   里就是 `cwd=str(HOME)`），这样 `moss.py` 注释里那份命令不绑死本机盘符。
ICON_REL = "system/icon/moss.ico"
ICON = HOME / ICON_REL

#: onefile 解包目录的**名字前缀**（`V-380`）。真正用的是 `moss-<构建指纹>`。
ONEFILE_DIR_PREFIX = "moss"
#: `moss.exe` 被占着时的产物名（你定的：**仍然是 .exe，能直接双击运行**；
#: `.old` 那种名字跑不起来）。`.gitignore` 里也把它挡掉了。
ALT_EXE_NAME = "moss.exe.exe"
#: `{CACHE_DIR}` 在本机就是 `%LOCALAPPDATA%`（清残渣时要自己算出来 —— 那一步在 Python 里做，
#: 不是 nuitka 展开的）。
MOSS_BUILD_DIR = Path(os.environ.get("LOCALAPPDATA")
                      or (Path.home() / "AppData" / "Local")) / "moss_build"
#: 指纹里也要算进去的那串**固定参数**：换了参数就是换了产物 ⇒ 该换目录。
#: （不含 `--onefile-tempdir-spec` 自己 —— 那里面就有指纹，自己算自己要转圈。）
_FIXED_FLAGS = ("--onefile --lto=yes --remove-output --windows-icon-from-ico=" + ICON_REL +
                " --windows-console-mode=hide --onefile-cache-mode=cached"
                " --include-package=core")
#: 解包目录名里的指纹（算出来的，注释里写不出具体值 ⇒ 核对时按占位符比）。
_STAMP_RE = re.compile(r"moss_build[/\\]" + ONEFILE_DIR_PREFIX + r"-[0-9a-f]{4,}", re.I)
_STAMP_PLACEHOLDER = "moss_build/" + ONEFILE_DIR_PREFIX + "-<stamp>"
#: 这一次的产物名 / 有没有被占着（`preflight` 填，`main` 用）。
_OUT = {"locked": False}


_STAMP_CACHE = []


def source_stamp():
    """算一个**每次打包都不同**的短指纹，用来当 onefile 解包目录的名字（`V-380`）。

    ★ 一次构建里**只算一次**（`_STAMP_CACHE`）：`preflight` 要拿它拼命令、打完包清旧目录时
      又要拿它当"留着的那一个" —— 而它带了构建时刻，算两次就是两个名字，清目录那句"留着"
      会留一个**根本不存在**的名字（新 exe 的目录反而被当成旧的删掉）。同一进程里缓存住。

    为什么要它（而不是 nuitka 的几个 token）
    ----------------------------------------
    · `{TIME}`（原来那个）：nuitka 的 `isDynamicSpec()` 把 `{TIME}` 归进
      **"每次运行都会变"** 那一类 ⇒ 默认的 `--onefile-cache-mode=auto` 解析成
      `temporary` ＝ **每次启动都重新解包 23 MB**，而且**一句警告都不打**
      （实测：`moss.exe --resolve` 1.2 秒，只该 0.3 秒；解包目录堆到 95 个 / 2.1 GB）。
    · `{VERSION}`（nuitka 手册里那个例子）：要 exe 带版本资源才有效 —— 本项目一个版本号
      都没有（`FileVersion` 是空的）⇒ 展开出来是空的 ⇒ 所有构建挤**同一个**目录，
      而 Windows 上**正在跑的那个 moss 锁着里面的 DLL**。
    · 所以自己算：**源码内容 + 构建时刻**。每次打包一个**新**目录 ⇒ 绝不会和正在跑的那份撞。

    ★ 为什么指纹里要有"构建时刻"（不只是内容）：`--onefile-cache-mode` 下引导程序会**逐文件
      比 CRC32**（`OnefileBootstrap.c`：`readPayloadChecksumValue` vs `getFileCRC32`）——
      一致就一个字节都不碰（快），不一致就要**覆写**，而覆写一个**正被运行中的 moss 占着的
      文件** = fatal，下一个 `moss.exe` 直接起不来。就算源码一模一样，LTO / venv 里的
      python312.dll 也可能让产物字节不同 ⇒ 只用内容哈希就留着这个坑。带上时刻就没这问题了。
    """
    if _STAMP_CACHE:                          # 同一进程里算过就用同一个（见上面那段）
        return _STAMP_CACHE[0]
    h = hashlib.sha1()
    files = [HOME / "moss.py", ICON]
    files += sorted((HOME / "core").rglob("*.py"))
    for f in files:
        try:
            h.update(f.relative_to(HOME).as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(f.read_bytes())
            h.update(b"\0")
        except OSError:                       # 少一个文件也要算出一个稳定的指纹（不许崩）
            continue
    h.update(_FIXED_FLAGS.encode("utf-8"))
    try:
        from nuitka import __version__ as _nv               # noqa: PLC0415
    except Exception:                                       # noqa: BLE001
        _nv = "?"
    h.update(("\n|py=%s|nuitka=%s|at=%d" % (sys.version, _nv, time.time_ns())).encode("utf-8"))
    stamp = h.hexdigest()[:8]
    _STAMP_CACHE.append(stamp)
    return stamp


def exe_is_locked():
    """`moss.exe` 正被占着吗（界面开着 / 有进程在跑它）。

    ★ 为什么非要知道（`V-380`）：Windows 不给**删/覆写**正在运行的 exe —— 实测 nuitka 最后
      一步 `os.unlink('moss.exe')` 拿到 `WinError 5 拒绝访问`，整次打包白跑。
    ★ 那怎么办：**产物换个名字**（`moss.exe.exe`，你定的）—— 正跑着的那个 `moss.exe` 一个
      字节都不动、照常能用，新产物也仍然是 `.exe`、**能直接双击运行**（`moss.exe.old` 那种
      名字就跑不起来）。关掉 moss 之后再打一次，它就会正常替换 `moss.exe`。
    """
    exe = HOME / "moss.exe"
    if not exe.is_file():
        return False
    try:
        with open(str(exe), "r+b"):            # 能独占打开 ⇒ 没被占
            pass
        return False
    except OSError:
        return True


def tempdir_spec(stamp):
    """给 nuitka 的 `--onefile-tempdir-spec`：**同一个构建固定、换构建就换**。"""
    return "{CACHE_DIR}/moss_build/" + ONEFILE_DIR_PREFIX + "-" + stamp


def mask_stamp(s):
    """把"算出来的那两样"换成占位符，好和 `moss.py` 注释里那一份比：
    · 解包目录名里的构建指纹；
    · 产物名（`moss` / `moss.exe.exe` —— 后者是"`moss.exe` 被占着"时的备用名）。"""
    s = _STAMP_RE.sub(_STAMP_PLACEHOLDER, s)
    return s.replace(ALT_EXE_NAME, "moss")


def prune_old_cache(keep_name):
    """清掉 onefile 的旧解包目录，回 `(清掉几个, 留着几个)`。

    · 名字**只认两种**：纯数字（老 `{TIME}` 留下的 FILETIME 名）和 `moss-*`（新指纹名）——
      `moss_build/` 底下别的东西**一个都不碰**。
    · 删不掉的（正在跑的 moss 锁着里面的 DLL）**跳过并说一声**，不算失败。
    """
    if not MOSS_BUILD_DIR.is_dir():
        return 0, 0
    gone = kept = 0
    for d in sorted(MOSS_BUILD_DIR.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if not (name.isdigit() or name.startswith(ONEFILE_DIR_PREFIX + "-")):
            continue
        if name == keep_name:
            kept += 1
            continue
        try:
            shutil.rmtree(str(d))
            gone += 1
        except OSError:
            print("  · 跳过一个清不掉的（大概正被运行中的 moss 占着）：%s" % name)
            kept += 1
    return gone, kept


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

    want = _normalize(mask_stamp(" ".join(cmd[3:])))     # cmd[3:] = nuitka 之后的全部参数
    found = None
    for line in doc_path.read_text(encoding="utf-8").splitlines():
        if DOC_MARKER in line:
            found = line.split(DOC_MARKER, 1)[1]
            break

    if found is None:
        return ("%s 的注释里找不到打包命令（要求必须留一份）。\n"
                "       应当有一行形如：venv\\Scripts\\python.exe -m nuitka ..."
                % DOC_SOURCE)

    got = _normalize(mask_stamp(found))
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
    if not ICON.is_file():
        return None, die("找不到 %s（图标文件，构建时嵌进 exe 的那个；"
                         "界面窗口的 favicon 也用它）" % ICON_REL)

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

    stamp = source_stamp()
    spec = tempdir_spec(stamp)
    # ★ `V-380`：`moss.exe` 被占着（界面开着）时，产物换个名字 —— 见 `exe_is_locked()`。
    locked = exe_is_locked()
    _OUT["locked"] = locked                 # `main` 打完包要按它决定产物名 / 收尾的话
    out_name = ALT_EXE_NAME if locked else "moss"
    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--lto=yes",
        "--remove-output",
        # nuitka 要用它自己那份精确匹配的 winlibs MinGW gcc。
        # 非交互环境下它会自动答 "no" 然后失败，所以必须加这个开关。
        "--assume-yes-for-downloads",
        # ★ `V-380`：解包目录 = `{CACHE_DIR}/moss_build/moss-<构建指纹>`。
        #   指纹**不是** `{TIME}`（那是"每次运行都变" ⇒ nuitka 判成 dynamic ⇒ 每次启动
        #   重新解包 23 MB），也不是 `{VERSION}`（本项目没有版本号 ⇒ 展开成空 ⇒ 所有构建
        #   挤同一个目录、还会撞上正在跑的进程锁住的 DLL）。见 `source_stamp()`。
        "--onefile-tempdir-spec=" + spec,
        # ★ `V-380`：**明说**要缓存模式。这样万一以后谁又把 `{TIME}` / `{PID}` / `{RANDOM}`
        #   塞回 spec，**打包当场报错**（nuitka: "run-time dynamic spec … cannot be used
        #   with cached mode"），不会再静默退化成"每次解包"。默认的 `auto` 是会退化的。
        "--onefile-cache-mode=cached",
        "--windows-icon-from-ico=" + ICON_REL,
        # 一个 exe 同时当命令行程序和界面程序（G-18 ✅）：**控制台子系统**（终端里
        # 一切照旧，shell 也会照常等它跑完），但那个控制台窗口如果是**为它新建的**
        # （双击 / 快捷方式 / 快速启动栏），bootstrap 会把它藏起来 —— 所以双击不弹
        # 黑框，而 `moss :md5 abc`、`moss cd`、`--history` 这些交互行为一个字没变。
        #
        # ★ 为什么不用 attach：attach 的产物是 **GUI 子系统**，而 PowerShell 对
        #   GUI 子系统的 exe **不等**（实测 `moss ui` 0.04 秒就返回、窗口还在开），
        #   于是 `moss cd`（要靠父 shell 阻塞着才读得到注入的按键）、`--history`
        #   的方向键列表、img 那种命令行菜单全都会被"抢输入"。hide 两样都要到了。
        "--windows-console-mode=hide",
        "--include-package=core",
        "-o", out_name,
        "moss.py",
    ]

    err = check_doc_sync(cmd)
    if err:
        return None, die(err)

    print("  注释核对: ✔ %s 里的命令与本次要执行的一致" % DOC_SOURCE)
    print("  产物   : %s" % (HOME / (ALT_EXE_NAME if locked else "moss.exe")))
    if locked:
        print("           ★ `moss.exe` 正被占着（界面开着？）⇒ 这次打成 %s：" % ALT_EXE_NAME)
        print("             正在跑的那个 moss 一个字节都没动、照常能用；")
        print("             等关掉 moss 再打一次，就会正常替换成 moss.exe。")
    print("  解包目录: %s（指纹 %s —— 每次打包换一个，旧的打包时清）"
          % (spec.replace("{CACHE_DIR}", str(MOSS_BUILD_DIR.parent)), stamp))
    print("  旧目录  : 打完包会清一遍（只清 %s 里我们自己那两种名字）" % MOSS_BUILD_DIR)
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

    # ★ `V-380`：主产物要是正被占着（界面开着），这一次的产物**换个名字**（`moss.exe.exe`）——
    #   正在跑的那个 `moss.exe` 一个字节都不动（不然 nuitka 最后一步 `os.unlink('moss.exe')`
    #   会拿到 WinError 5，整次打包白跑；这一轮实测踩到了）。产物名是 `preflight` 定的。
    locked = bool(_OUT["locked"])
    print("开始编译。首次运行会下载约 100MB 的 C 编译器到用户缓存（之后不再下载），")
    print("之后每次约 1-3 分钟。")
    print("=" * 64)
    sys.stdout.flush()

    rc = subprocess.call(cmd, cwd=str(HOME))
    if rc != 0:
        return die("nuitka 返回 %d，打包失败。" % rc)

    exe = HOME / (ALT_EXE_NAME if locked else "moss.exe")
    if not exe.is_file():
        return die("nuitka 报成功，但 %s 不存在。" % exe.name)

    # 上一次"被占着"那次留下的备用产物：这次正常替换成功了就顺手清掉，别攒着。
    if not locked:
        stale = HOME / ALT_EXE_NAME
        if stale.is_file():
            try:
                stale.unlink()
                print("（顺手清掉上一次留下的 %s）" % ALT_EXE_NAME)
            except OSError:
                print("（%s 清不掉、先留着 —— 大概它正被另一个进程跑着）" % ALT_EXE_NAME)

    print()
    print("=" * 64)
    print("[完成] %s  (%.1f MB)" % (exe, exe.stat().st_size / 1048576))
    print("=" * 64)
    # ★ `V-380`：顺手把旧的解包目录清掉 —— `{TIME}` 那版实测堆了 95 个 / 2.1 GB。
    print()
    print("清理 onefile 的旧解包目录：%s" % MOSS_BUILD_DIR)
    gone, kept = prune_old_cache("%s-%s" % (ONEFILE_DIR_PREFIX, source_stamp()))
    print("  清掉 %d 个，留着 %d 个（留着的是当前指纹那份 + 清不掉的）" % (gone, kept))
    print("  ★ 换过指纹之后的**第一次**运行会解包一次（约 0.5 秒），之后就一直复用那份了。")
    if locked:
        print()
        print("★ 这次是备用产物：`moss.exe` 正被占着，所以打成了 %s。" % ALT_EXE_NAME)
        print("  1) 直接用它就测新版：  %s --selfcheck" % exe)
        print("  2) 想让它变成正式的 `moss.exe`：关掉 moss（界面）之后再敲一次 build；")
        print("     或者你自己把 %s 改名成 moss.exe（改名之后双击/命令行都正常）。" % ALT_EXE_NAME)
        print("  3) 它已经在 `.gitignore` 里了，不会进 git。")
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
