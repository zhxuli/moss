# -*- coding: utf-8 -*-
"""宿主界面（v0）：把 `system/ui/main.py` 交给自带运行时去跑。

为什么界面不编进 exe（`K-10` 内核最小化）
----------------------------------------
界面要 pywebview + pythonnet + WebView2。编进 exe 会让 6.3 MB 的产物翻倍，
而且**每改一次界面都要重新打包**。所以界面跟"包"一样放在 exe 外面：
`system/ui/` 是**宿主自己的界面** —— 它不属于任何包，也不能用 `moss --remove` 删掉。

三个进程的角色（别搞混）
------------------------
    moss.exe            宿主。负责解析、找解释器、把包列表写成 JSON、等界面退出。
    system/ui/main.py   界面本体，用**自带运行时**跑（那里有 pywebview）。
                        它**不 import core** —— 发行版里 core 编在 exe 里，
                        磁盘上根本没有这个目录。
    包（`moss :img`）    界面要跑包时，去调 **moss.exe 自己**
                        （`MOSS_HOST_CMD`，打包后就是 exe，源码运行时是 python + moss.py），
                        和用户手敲命令走的是同一条路，不另开一条通道。

为什么要 `CREATE_NO_WINDOW`
---------------------------
界面模式（双击 / `moss ui`，见 `shell.gui_mode()`）下起子进程一律带
`CREATE_NO_WINDOW`，否则点一下闪一个黑框（`E-27` ✅）。
"""
import base64
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config, engine, out, paths, pkg as pkg_mod, registry, runners as runners_mod
from . import shell as shell_mod

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

UI_DIR = paths.SYSTEM_DIR / "ui"
UI_MAIN = UI_DIR / "main.py"
UI_PAGE = UI_DIR / "index.html"

# 界面能显示图标的前提是"宿主把图变成 data URI 塞进 JSON"（见 `_icon_uri`）。
# 为什么不传路径：WebView2 里页面是 file:// 源，直接 <img src="file:///...">
# 会被当跨源子资源挡掉；转成 data URI 最省事，18 个 svg 一共才几 KB。
_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".bmp": "image/bmp", ".ico": "image/x-icon"}
_ICON_MAX_BYTES = 200 * 1024


def _icon(pkg, pkg_dir):
    """图标给界面用。返回 (data URI, 内联 svg 文本)。

    ★ svg 要**内联**（而不是塞进 `<img src=...>`）：那 18 个图标画的是
      `stroke="currentColor"`，只有内联进 DOM 才会跟着主题变色；
      放进 `<img>` 里 currentColor 会退化成黑色，深色主题下直接看不见。
      图标是**数据不是指令**（`X-16`），前端内联前会剥掉 script / 事件属性。
    """
    p = pkg_mod.icon_path(pkg, pkg_dir)
    if not p:
        return "", ""
    try:
        raw = p.read_bytes()
    except OSError:
        return "", ""
    if not raw or len(raw) > _ICON_MAX_BYTES:
        return "", ""
    suffix = p.suffix.lower()
    if suffix == ".svg":
        return "", raw.decode("utf-8", "replace")
    mime = _MIME.get(suffix, "application/octet-stream")
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii")), ""


def _python(table):
    """找一个能跑界面的 Python。返回 (路径 或 None, 说明)。

    ★ 用 `kind="package"` 的顺序（**自带运行时优先**）：界面要 pywebview，
      而这台机器上只有自带运行时里那份是齐的（pythonnet + clr_loader + WebView2）。
      系统 Python 得用户自己 pip install pywebview。
    """
    spec = (table or {}).get("python") or {}
    info = runners_mod.probe("python", spec, {"cwd": str(paths.HOME)}, kind="package")
    return info.get("interpreter"), info.get("why")


def _has_webview(exe):
    """这个解释器旁边有没有 pywebview。只看文件，不起子进程（自检要快）。"""
    if not exe:
        return False
    root = Path(exe).resolve().parent
    cands = [
        root / "Lib" / "site-packages" / "webview" / "__init__.py",   # 自带运行时 / venv
        root / ".." / "Lib" / "site-packages" / "webview" / "__init__.py",
        root / "lib" / "site-packages" / "webview" / "__init__.py",
    ]
    return any(c.is_file() for c in cands)


def available(table=None):
    """界面能不能开。返回 (ok, 说明)。`--selfcheck` 与 `launch()` 共用。"""
    if not UI_MAIN.is_file():
        return False, "缺文件：%s" % UI_MAIN
    if not UI_PAGE.is_file():
        return False, "缺文件：%s" % UI_PAGE
    if table is None:
        table = runners_mod.load()
    exe, why = _python(table)
    if not exe:
        return False, "找不到能跑界面的 Python（%s）" % (why or "没配解释器")
    if not _has_webview(exe):
        # `V-367`：这句会出现在**弹给用户的 MessageBox** 里 ⇒ 说人话。
        #   以前写的是"这个 Python 里没有 pywebview：<路径>\n       自带运行时
        #   （system\runtimes\python\）里是带的；系统 Python 需要自己 pip install
        #   pywebview" —— 里面既有内部目录，又有一段**源码缩进漏进了文案**（那 7 个空格）。
        return False, ("界面缺一个组件（pywebview），跑不起来。\n"
                       "用 moss 自带的 Python 跑界面就行；%s 里没有这个组件。" % exe)
    return True, exe


def host_cmd():
    """界面要跑包时该调谁：打包后是 moss.exe 自己，源码运行时是 python + moss.py。

    （界面**不 import core**，所以它没法自己解析包 —— 必须回到宿主这条路上来。）

    ★ **绝对不能用 `sys.executable`**（2026-09-27 实测踩到）：nuitka onefile 下
      它指的是**临时解包目录**里那个解释器 ——
      `C:\\Users\\…\\AppData\\Local\\moss_build\\134350634283468622\\python.exe`，
      那个目录随进程结束就没了。界面上点"运行"于是报
      `启动失败：[WinError 2] 系统找不到指定的文件`（截图里当场看见的）。
      改用 **`sys.argv[0]`**：它指向"真正被启动的那个文件" —— 打包后是 moss.exe、
      源码运行是 moss.py。`core/paths.py` 定位安装根用的也是它（同一个理由）。
    """
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv else ""
    exe = os.path.abspath(sys.executable or "")
    if argv0.lower().endswith(".py") and os.path.isfile(argv0):
        return [exe, argv0]                 # 源码运行：<python> moss.py
    if os.path.isfile(argv0):
        return [argv0]                      # 打包后：moss.exe 自己
    return [exe]


def _ui_of(pkg, pkg_dir):
    """包的「界面」声明（`V-48` ✅）：`"ui": {"embed": "ui/index.html"}`。

    声明里写的是**相对包目录**的路径；这里解析成**绝对路径**再交给界面 ——
    界面只管把它变成 `file://` 塞进 iframe，不用自己拼包目录（也不用认识包格式）。
    文件不存在就当没声明（并在 stderr 说一句），免得界面上多出一个点进去空白的选项卡。
    """
    raw = pkg.get("ui")
    if not isinstance(raw, dict):
        return None
    rel = str(raw.get("embed") or "").strip()
    if not rel:
        return None
    full = (Path(pkg_dir) / rel).resolve() if not os.path.isabs(rel) else Path(rel)
    if not full.is_file():
        print("[警告] %s 声明了界面 %r，但文件不存在（这个包不会有「界面」选项卡）"
              % (pkg_dir, rel), file=sys.stderr)
        return None
    title = raw.get("title")
    if isinstance(title, dict):
        title = title.get("zh-CN") or title.get("en") or ""
    return {"embed": str(full), "title": str(title or "")}


def build_payload():
    """交给界面的全部数据（界面只是个渲染器，不认识 pkg.json 的格式）。"""
    pkgs = []
    for rec in registry.scan_all():
        p = rec["pkg"]
        # ★ 多语言 name/desc 要**先摊平**：`display_name` 是**就地改 pkg 并返回 pkg
        #   自己**（不是返回名字字符串）。曾经把它当名字字符串用，18 个包
        #   全显示成 `[object Object]`。
        pkg_mod.display_name(p)
        ai = p.get("ai") or {}
        icon_uri, icon_svg = _icon(p, rec["dir"])
        item = {
            "id": p.get("id") or rec["id"],
            "name": p.get("name") or rec["id"],
            "desc": p.get("desc") or "",
            "kind": p.get("kind") or "",
            "version": str(p.get("version") or ""),
            "layer": rec["layer"],
            "dir": str(rec["dir"]),
            "aliases": [str(a) for a in (p.get("aliases") or [])],
            "tags": [str(t) for t in (p.get("tags") or [])],
            "params": p.get("params") or [],
            # 「拖进来」声明（`V-38` ✅）：已经是"命令数组"了（`pkg.normalize_drop` 归一化过），
            # 空数组 = 这个包不收拖入。界面拖动时**只列收得下的包**、只画对应的投放框。
            "drop": p.get("drop") or [],
            # 「界面能不能内嵌」（`V-48` ✅）：`_ui_of()` 已经把相对路径解析成绝对路径。
            # `None` = 这个包没有可内嵌的界面（界面上那个选项卡就不出现）。
            "ui": _ui_of(p, rec["dir"]),
            "docs": p.get("docs") or {},
            "ai_expose": bool(ai.get("expose")),
            "ai_risk": str(ai.get("risk") or ""),
            "examples": [str(e.get("args") or "") for e in (ai.get("examples") or [])
                         if isinstance(e, dict)],
            "icon": icon_uri,
            "icon_svg": icon_svg,
        }
        if rec.get("shadowed"):
            item["shadowed"] = rec["shadowed"]
        pkgs.append(item)
    return {
        "home": str(paths.HOME),
        "user_data": str(paths.USER_DIR),
        "host_cmd": host_cmd(),
        "launch_kind": shell_mod.launch_kind(),
        # 图标后缀顺序由宿主带过去：界面那侧要按同一套顺序去"历史目标目录"里
        # 找 `icon.xxx`，两边共用一份顺序，免得以后 `F-29` 改了漏改
        "icon_exts": list(pkg_mod.ICON_EXTS),
        # ★ `V-305`：界面**不再硬编码 `:`** —— 「跑包 / 路径 / 不切目录 / 后台」这几个符号
        #   都是 `symbols` 段里可改的（设置→符号），界面照搬显示、并照它拼命令行。
        "symbols": {
            "plugin": config.plugin_symbol(),
            "path": config.path_symbol(),
            "no_chdir": config.no_chdir_symbol(),
            "detach": config.detach_symbol(),
        },
        "packages": pkgs,
    }


def _alert(text):
    """GUI 模式下没有控制台，`print` 等于丢进 NUL —— 那种情况要弹窗。"""
    if shell_mod.has_console():
        out.print_cyan(text)
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, "moss", 0x40)
    except Exception:
        pass


def launch(args=None):
    """开界面。返回退出码（界面窗口关掉就返回）。"""
    table = runners_mod.load()
    ok, why = available(table)
    if not ok:
        _alert("打不开界面：%s" % why)
        return 1

    exe, _ = _python(table)
    fd, tmp = tempfile.mkstemp(prefix="moss-ui-", suffix=".json")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        tmp_path.write_text(json.dumps(build_payload(), ensure_ascii=False),
                            encoding="utf-8")
        env = os.environ.copy()
        env["MOSS_HOME"] = str(paths.HOME)
        env["MOSS_USER_DATA_DIR"] = str(paths.USER_DIR)
        env["MOSS_UI_DATA"] = str(tmp_path)
        env["MOSS_HOST_CMD"] = json.dumps(host_cmd(), ensure_ascii=False)
        env["PYTHONIOENCODING"] = "utf-8"

        argv = [exe, str(UI_MAIN)] + list(args or [])
        flags = _NO_WINDOW if shell_mod.gui_mode() else 0
        try:
            proc = subprocess.Popen(argv, cwd=str(paths.HOME), env=env,
                                    creationflags=flags)
        except OSError as e:
            _alert("界面启动失败：%s" % e)
            return 1

        # 等界面退出：关掉窗口 = 这次调用结束（Ctrl+C 连带把界面收掉）。
        try:
            while proc.poll() is None:
                time.sleep(0.1)
        except KeyboardInterrupt:
            engine.kill_process_tree(proc.pid)
            return 130
        return proc.returncode or 0
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass
