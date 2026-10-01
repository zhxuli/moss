#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""moss 界面 v0 —— 由 `moss.exe` 拉起，宿主把数据准备好后把**路径**放进 `MOSS_UI_DATA`。

三条硬规矩（都是被前几轮踩出来的）
----------------------------------
1. **这里不许 import core。** 发行版里 `core/` 编在 exe 里，磁盘上根本没有那个
   目录。所以界面要跑包时只能回头调 `MOSS_HOST_CMD`（就是 moss.exe 自己），
   和用户手敲命令走同一条路 —— 界面不另开一条执行通道。
2. **界面是渲染器，不认识 pkg.json。** 字段由宿主摊平成 JSON 喂进来
   （`core/ui.py:build_payload`）。包格式改了只改宿主一处。
3. `python.exe` 是控制台程序，而界面模式下宿主没有控制台 ⇒ 起子进程一律带
   `CREATE_NO_WINDOW`，否则点一下闪一个黑框（`E-27` ✅）。

v0 只做四件事：列包、看一个包的说明与参数、带参数跑并看输出、把包的界面开起来。
界面本身（`index.html`）以后随时改 —— 改它**不用重新打包 exe**，这正是把它
放在 exe 外面的理由（`K-10`）。
"""
import base64
import codecs
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import http.server
import shlex
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import webview

HERE = Path(__file__).resolve().parent

# ★ 把**本文件所在目录**塞进 `sys.path`（`V-87` 修，血泪）：
#   自带运行时那份 Python（`system/runtimes/python/3.12/`）是**便携/嵌入**版 ——
#   它的 `sys.path` 来自 `python312._pth`，**不会**像常规 Python 那样把"脚本所在目录"
#   放进 `sys.path`（实测：`sys.path[0]` 是 `python312.zip`）。于是这里 `import backup`
#   （同目录下的兄弟模块）会报 `No module named 'backup'` —— 用户备份时就撞上了。
#   ⚠️ 为什么我的探针一直没暴露：探针是用 `runpy` 跑的，而且**自己插过**
#   `sys.path.insert(0, system/ui)`（venv 那份 Python 也会自动带上脚本目录）
#   ⇒ 又一次"我的验证环境和真启动不是一个世界"（`V-76` 第②条）。
#   这一行让两种跑法都成立。
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW
DETACHED = 0x00000008           # DETACHED_PROCESS
DEVNULL = subprocess.DEVNULL


def _load_data():
    p = os.environ.get("MOSS_UI_DATA")
    if not p:
        raise SystemExit("缺少 MOSS_UI_DATA —— 这个界面只能由宿主拉起（moss ui / 双击 moss.exe）")
    return json.loads(Path(p).read_text(encoding="utf-8"))


DATA = _load_data()
HOST = [str(x) for x in (DATA.get("host_cmd") or [])]



def _split(text):
    """把参数框里那串文本拆成 argv。

    包参数本来就是"一个字符串"（`CL-02`），拼回去由宿主负责；这里只要拆得
    跟用户的直觉一致。带空格的路径用双引号括起来。
    """
    text = (text or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError:            # 引号没配对：别崩，按空白硬拆
        return text.split()


def _run_capture(argv):
    """跑一条宿主命令并把输出抓回来（合并 stdout+stderr，按 UTF-8 解）。"""
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW)
    except OSError as e:
        return {"code": -1, "out": "启动失败：%s" % e}
    return {"code": r.returncode, "out": (r.stdout or "") + (r.stderr or "")}


def _run_capture_split(argv):
    """跑宿主命令，**stdout 和 stderr 分开**拿（`V-31`）。

    ★ 为什么必须分开：`--ui-payload` 的 stdout 是一份**纯 JSON**，而宿主扫描时
      的告警（「pkg.json 解析失败」/「id 不合法」）走 **stderr**。上面那个
      `_run_capture` 是把两股**合并**的 —— 于是一个坏包就能让 JSON 后面多一句话，
      `json.loads` 直接报 `Extra data: line 1 column N`，界面只好退回旧快照：
      **看起来就是"界面不刷新"，而且一句提示都没有**（实测过）。
      跑包那条路要合并（人家本来就是人看的文本），读包表这条必须分开。
    """
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW)
    except OSError as e:
        return {"code": -1, "out": "", "err": "启动失败：%s" % e}
    return {"code": r.returncode, "out": r.stdout or "", "err": r.stderr or ""}


def _json_from_host(out):
    """从宿主的 stdout 里取出那份 JSON。取不到返回 None。

    ★ 为什么不能直接 `json.loads(整段)`：宿主启动时会先跑 `config.load()`，
      而配置文件**不存在**（首次运行）或**写坏了**时，它会往 stdout 打几句
      「[配置] 未找到配置文件……」。那几行和我们这份 JSON 混在一起就是
      `Extra data: line 1 column N` —— 界面只好退回旧快照，看起来就是"界面不刷新，
      还不知道为什么"（`V-31` 那次就是这一类）。所以：整段能解析就用整段，
      不然**从最后往前找第一个 `{` 开头的行**——两条命令的输出都是一行 JSON。
    """
    s = (out or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except ValueError:
        pass
    for line in reversed(s.splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            return json.loads(line)
        except ValueError:
            continue
    return None


# ================================================================ 文件系统
# 界面里的「文件管理」选项卡要能像资源管理器那样操作。三条底线：
#
#   ① **只认两个根**：`user_data/`（用户资产）和 `system/`（出厂件）。
#   ② **路径必须落在根里面**：允许 `user/pkgs/x/main.py`，`../` 逃逸一律拒绝 ——
#      路径最终来自页面，不能假设它是善意的。
#   ③ **删除不是真删**：挪进 `user_data/trash/<时间戳>/<原路径>`（可恢复）。
#
# ★ `system/` 是**可写**的（`D-24`）。理由：出厂件也常常需要就地改一下试试，
#   这个项目的玩法就是"自己改包"，而改包就得改代码；`system/pkgs/*` 虽然是出厂件，
#   但现在还没开始分发、改坏了 git 还能救。界面上**只提示不拦截**：
#   打开 `system/` 里的文件会顶一条"升级时会被整体替换"的提醒。
MAX_READ = 2 * 1024 * 1024          # 超过 2 MB 不给编辑（读出来看看就够）
TRASH_DIRNAME = "trash"

HOME = Path(os.environ.get("MOSS_HOME") or ".")
USER_DATA = Path(os.environ.get("MOSS_USER_DATA_DIR") or (HOME / "user_data"))

ROOTS = [
    {"key": "user", "label": "user_data", "path": USER_DATA, "writable": True,
     "why": "本地安装的包 / 配置 / 数据"},
    {"key": "system", "label": "system", "path": HOME / "system", "writable": True,
     "why": "出厂件（随 moss.exe 分发）—— 能改，但升级时会被整体替换"},
]

# ★ 第三个根：**绝对路径**（页面写的 `abs/D:/python/wwwroot/ZeEn`）。
#   为什么要它（`D-25`）：历史里那些**路径调用**的目标本来就散在磁盘各处
#   （`D:\python\wwwroot\ZeEn` 这类），而前两个根只覆盖 `user_data/` 和 `system/`。
#   历史条目要能"点进去看看那个目录"，就必须能走到根外面 —— 否则它的「文件管理」
#   永远只会说"路径跑到根外面去了"。
#   保护措施照旧不变：删除仍然只进 `user_data/trash/`、二进制与 >2MB 仍然只读、
#   `..` 段仍然拒绝（往上走用界面上那个 ⬆ 按钮，它算的是真正的父目录）。
ABS_KEY = "abs"
ABS_ROOT = {"key": ABS_KEY, "label": "外部目录", "path": None, "writable": True,
            "why": "历史调用所在的目录（不在 user_data/ 和 system/ 里）"}


def _root_by_key(key):
    if key == ABS_KEY:
        return ABS_ROOT
    for r in ROOTS:
        if r["key"] == key:
            return r
    return None


def _abs_of(sub):
    """`abs/` 后面那段 → 绝对路径。半截盘符（`D:`）补成盘根（`D:/`）。"""
    s = str(sub or "").strip()
    if re.fullmatch(r"[A-Za-z]:", s):
        s += "/"
    p = Path(s)
    if not p.is_absolute():
        raise ValueError("`%s/` 后面要跟一个**绝对路径**，收到的是 '%s'" % (ABS_KEY, sub))
    return p


def _resolve(rel):
    """把 `user/pkgs/x/main.py` 解析成绝对路径，并确保没跑出根本身。

    返回 (root_dict, Path)；不合法就抛 ValueError（页面把 message 显示出来）。
    `abs/<绝对路径>` 是第三个根 —— 它没有"根目录"可比，所以不做越界检查
    （它本来就是"根外面"），但仍然拒绝 `..` 段。
    """
    rel = str(rel or "").replace("\\", "/").strip().strip("/")
    key, _, sub = rel.partition("/")
    root = _root_by_key(key)
    if root is None:
        raise ValueError("不认识的根 '%s'（只允许 %s）"
                         % (key, " / ".join([r["key"] for r in ROOTS] + [ABS_KEY])))
    if key == ABS_KEY:
        if ".." in sub.split("/"):
            raise ValueError("路径里不许有 `..`（要用上一级请点界面上的 ⬆）")
        try:
            return root, _abs_of(sub).resolve()
        except OSError as e:
            raise ValueError("路径解析失败：%s" % e)
    base = Path(root["path"])
    try:
        base_r = base.resolve()
        target = (base / sub).resolve() if sub else base_r
    except OSError as e:
        raise ValueError("路径解析失败：%s" % e)
    if target != base_r and base_r not in target.parents:
        raise ValueError("路径跑到根外面去了：%s" % rel)
    return root, target


def _rel_of(path):
    """绝对路径 → 页面用的 `key/子路径`。在三个根里都不成立就返回 None。"""
    p = Path(path).resolve()
    for r in ROOTS:
        base = Path(r["path"]).resolve()
        if p == base:
            return r["key"]
        if base in p.parents:
            return r["key"] + "/" + p.relative_to(base).as_posix()
    return None


def _rel_page(path):
    """页面用的 rel：先按两个真根算，算不出来就落到 `abs/<绝对路径>`。

    ★ 和 `_rel_of` 分开：`_rel_of` 答的是"这东西在哪一层的账上"（`_trash` 要用它
      决定往哪放），`_rel_page` 答的是"页面该拿什么字符串来引用它"。
    """
    rel = _rel_of(path)
    if rel:
        return rel
    return ABS_KEY + "/" + Path(path).resolve().as_posix()


def _human(n):
    """字节数说成人话（备份那边报"省了多少/回收了多少"用）。"""
    try:
        n = float(n or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0
    return "%.1f TB" % n


def _trash(path):
    """把东西挪进 `user_data/trash/<时间戳>/...`（不真删）。

    `abs/` 那些（磁盘上任意位置）也照样进回收站 —— 只是路径里不能带 `:`，
    所以去掉盘符的冒号，落成 `trash/<时间戳>/abs/D/python/...` 这样。
    """
    import time
    rel = _rel_page(path)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    safe = rel.replace(":", "")
    dest = USER_DATA / TRASH_DIRNAME / stamp / Path(safe.replace("/", os.sep))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = _unique(dest)
    shutil.move(str(path), str(dest))
    return rel, _rel_page(dest)


def _unique(path):
    """同名就按资源管理器的规矩加 (2)(3)：`a.txt` → `a (2).txt`。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        cand = path.with_name("%s (%d)%s" % (stem, i, suffix))
        if not cand.exists():
            return cand
    raise OSError("同名文件太多了：%s" % path.name)


def _bad_name(name):
    return (not name) or any(c in name for c in '\\/:*?"<>|') or name in (".", "..")


# ================================================================ 包自己的界面窗口
# 「显示 / 隐藏」那个按钮要管的是**这个包自己的界面窗口**（GUI 包跑起来的那扇窗）。
# 怎么知道哪扇窗是它的：**记下为它拉起过的进程根**（`open_ui` / `run_start` 时记），
# 然后按 PID 树找出这些进程以及它们的子孙，再用 EnumWindows 找属于这些 PID 的顶层窗口。
# 比"按窗口标题猜"可靠得多（标题会被包自己改，也可能撞名）。
_pkg_procs = {}          # 包 id -> {(pid, 创建时间)} —— 见 _remember_proc 的说明
_pkg_hidden = {}         # 包 id -> [被藏起来的窗口句柄]（显示时只放这几个）
#: 内嵌界面的后端进程（`V-48` ✅）：包 id -> {"proc": Popen, "lines": [非消息输出]}
#: ★ 跟 `_pkg_procs` 分开记：那两个是"包=独立进程/窗口"那套，这个是"界面嵌在我们这一页里"
#:   的那套。**切走选项卡不会碰它**（这就是你要的"切走还在后台跑"）。
EMBED = {}
EMBED_LOCK = threading.Lock()

#: 给包界面用的**本地 HTTP 服务**（`V-55` ✅）：`{httpd, port, token}`。
#: ★ 为什么要这么绕一圈：**WebView2 里不能 iframe 一个 `file://` 页面**
#:   （实测：父页也是 file:// 也一样 —— 帧建出来了、却压根不导航，一片空白；
#:    同样的页面在普通 Edge 里能显示，所以这个坑只在 WebView2 上踩得到）。
#:   官方给本地内容的做法就是"开个本地服务"（VS Code 的 webview 也是这么干的）。
#:   顺带把 `file://` 那两个限制（fetch / localStorage）也解决了。
#:   安全：只绑 127.0.0.1、只读（GET/HEAD）、每次启动一个随机 token 要求带在路径里。
_EMBED_SRV = {"httpd": None, "port": 0, "token": ""}


def _remember_proc(pkg, pid):
    """记下"这个 pid 是为它拉起的"。★ 连**创建时间**一起记（`V-45` ✅）。

    为什么非记时间不可：进程一退出，pid 会被系统**回收**给别的进程；只按 pid 认人，
    过一会儿那个号就指向一个跟这个包毫无关系的进程 —— 实测（拿一个活进程的 pid
    冒充"当初记下的那个"）：`pkg_state('img')` 报 `running: True`，还带出 4 个
    "属于它的进程"和 3 个窗口，于是界面上**跑完了按钮还是「停止」**、永远不变回来。
    带上创建时间就认得出"这已经不是当初那个进程"。
    """
    ct = None
    try:
        import psutil
        ct = float(psutil.Process(int(pid)).create_time())
    except Exception:                                                # noqa: BLE001
        ct = None                       # 读不出来就退回"只看 pid"（老行为，聊胜于无）
    _pkg_procs.setdefault(str(pkg), set()).add((int(pid), ct))


def _live_roots(roots):
    """记下的那些根里，**现在还真是当初那个进程**的。

    判据是创建时间对得上（同一个进程每次读都一样；pid 被回收后换了进程，时间不同）。
    进程已经没了 / 读不出来 → 不算 —— `pkg_state` 就该老老实实说"没在跑"。
    """
    out = set()
    for item in roots:
        try:
            pid, ct = item
        except (TypeError, ValueError):      # 万一表里是裸 pid（老代码 / 手工塞的）
            out.add(int(item))
            continue
        if ct is None:
            out.add(int(pid))
            continue
        try:
            import psutil
            if abs(float(psutil.Process(int(pid)).create_time()) - ct) < 0.01:
                out.add(int(pid))
        except Exception:                                                # noqa: BLE001
            pass
    return out


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD),
                ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD),
                ("pcPriClassBase", ctypes.c_long), ("dwFlags", wt.DWORD),
                ("szExeFile", ctypes.c_wchar * 260)]


def _pid_parents():
    """{pid: 父 pid} 快照。"""
    out = {}
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p          # HANDLE 是 64 位，别截断
        k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)             # TH32CS_SNAPPROCESS
        if not snap or snap == ctypes.c_void_p(-1).value:
            return out
        try:
            e = _PROCESSENTRY32W()
            e.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
            ok = k32.Process32FirstW(ctypes.c_void_p(snap), ctypes.byref(e))
            while ok:
                out[int(e.th32ProcessID)] = int(e.th32ParentProcessID)
                ok = k32.Process32NextW(ctypes.c_void_p(snap), ctypes.byref(e))
        finally:
            k32.CloseHandle(ctypes.c_void_p(snap))
    except Exception:
        pass
    return out


def _with_descendants(roots, parents=None):
    """roots 以及它们的全部子孙 pid —— **只算还活着的**（包的启动器 → 真身常常两三层）。

    ★ 必须按快照过滤掉死 pid：`roots` 是当初记下的 pid，进程退出后那个号
      还留在表里；不过滤的话 `pkg_state` 会永远报"它还在跑" ——
      **实测踩到**：点「停止」把图片工具退出了，按钮却一直显示"停止"不变回来。
    ★ `parents` 允许传进来复用：批量查十几个包时，进程快照只取一次就够（省几十毫秒）。
    """
    if parents is None:
        parents = _pid_parents()
    alive = set(parents)
    kids = {}
    for pid, ppid in parents.items():
        kids.setdefault(ppid, []).append(pid)
    seen, stack = set(), [int(r) for r in roots if int(r) in alive]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        stack.extend(kids.get(p, []))
    return seen


def _top_windows():
    """所有**顶层且有标题**的窗口：[{hwnd, pid, visible, title, class}]。"""
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    out = []
    try:
        u32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p,
                                                       ctypes.c_void_p), ctypes.c_void_p]
        u32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.DWORD)]
        u32.GetWindowTextLengthW.argtypes = [ctypes.c_void_p]
        u32.GetWindowTextW.argtypes = [ctypes.c_void_p, wt.LPWSTR, ctypes.c_int]
        u32.GetClassNameW.argtypes = [ctypes.c_void_p, wt.LPWSTR, ctypes.c_int]
        u32.IsWindowVisible.argtypes = [ctypes.c_void_p]
        u32.GetWindow.argtypes = [ctypes.c_void_p, wt.UINT]

        def cb(hwnd, _l):
            if u32.GetWindow(hwnd, 4):        # GW_OWNER != 0 → 附属窗（工具窗/对话框）
                return True
            n = u32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            cls = ctypes.create_unicode_buffer(256)
            u32.GetClassNameW(hwnd, cls, 256)
            pid = wt.DWORD(0)
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            out.append({"hwnd": hwnd, "pid": int(pid.value), "class": cls.value,
                        "visible": bool(u32.IsWindowVisible(hwnd)), "title": buf.value})
            return True

        u32.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(cb), 0)
    except Exception:
        pass
    return out


# Tk 会给自己建几个**看不见的辅助窗**（实测：`TtkMonitorWindow`，类名 TtkMonitorClass，
# 尺寸还是 2880×1563 —— 靠尺寸/样式根本认不出来）。它们不是"包的界面"，
# 而且一旦被 ShowWindow 放出来，屏幕上会多出一扇莫名其妙的空窗，所以按类名排掉。
_HELPER_CLASSES = ("TtkMonitorClass",)


# ================================================================ 历史账（读 + 删）
# ★ 这一小段是 `core/history.py` 里 `dedup_key` / `should_record` 的**逐字镜像**。
#   为什么要抄一遍：界面进程不能 import core（发行版里 core 编在 exe 里），
#   而两边读的是**同一本账** —— 键算法一旦不同，"界面里删掉一条"在 CLI 的
#   `--history` 里就会又冒出来。**改这里必须同时改 `core/history.py`。**
# ★ 删除走的是**真删**（把那些行从 jsonl 里抠掉，见 `_hist_drop_lines`），
#   不是"追加一条墓碑、读的时候跳过" —— 墓碑那种做法，**能不能跳过取决于读的人
#   那份代码认不认它**：界面后端在 exe 外面、改完就是新的，而终端里的
#   `moss --history` 跑的是编在 exe 里的旧代码，于是会"界面里删了、终端里还在"。
#   真删就没这个问题（谁来读都看不见了），也不用为它重打一次包。


def _hist_read_all():
    """把那本账整个读出来（新的月份在前，行序保持文件里的顺序）。"""
    rows = []
    hist_dir = USER_DATA / "history"
    if not hist_dir.is_dir():
        return rows
    for f in sorted(hist_dir.glob("*.jsonl"), reverse=True):
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            continue
    return rows


def _hist_key(r):
    """去重键（= `core.history.dedup_key`）。"""
    return "|".join([
        str(r.get("kind") or ""),
        str(r.get("id") or r.get("target") or ""),
        json.dumps(r.get("params") or {}, sort_keys=True, ensure_ascii=False),
        json.dumps(r.get("args") or [], ensure_ascii=False),
    ])


def _hist_is_record(r):
    """这条算不算一条历史（= `core.history.should_record`）。"""
    return (r.get("kind") or "") != "pkg"


def _hist_drop_lines(path, key):
    """把账里去重键等于 `key` 的那几行**原地抠掉**。返回删掉的行数。

    ★ 全用二进制：行尾原样保留（不去翻译 `\\r\\n`），只按 `\\n` 切。
    ★ "读完 → 检查有没有变长 → 把新长出来的那段原样续写到后面 → truncate"：
      这样即使正好有一次调用在这期间结束并追加了它那条，也不会被我们截掉。
    """
    try:
        with open(path, "rb+") as fh:
            data = fh.read()
            read_to = fh.tell()
            keep, hit = [], 0
            for raw in data.split(b"\n"):
                s = raw.strip()
                if not s:
                    continue
                try:
                    r = json.loads(s.decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    keep.append(raw)
                    continue
                if _hist_key(r) == key:
                    hit += 1
                else:
                    keep.append(raw)
            if not hit:
                return 0
            # 期间有没有别人追加？（有就原样带上，别截掉）
            fh.seek(0, 2)
            size_now = fh.tell()
            tail = b""
            if size_now > read_to:
                fh.seek(read_to)
                tail = fh.read()
            new = b"".join(b + b"\n" for b in keep) + tail
            fh.seek(0)
            fh.write(new)
            fh.truncate()
            return hit
    except OSError:
        return 0


# ================================================================ 文本编码
# ★ 为什么专门做这件事（有些 txt 打不开、被报成"二进制文件"）：
#   原来的判断只有一句 `b"\x00" in raw[:8192]` —— 而 **UTF-16 文本里每个 ASCII
#   字符后面都跟着一个 0x00**，于是记事本存成的 UTF-16 txt 全被当成二进制拒了。
#   GBK（中文 Windows 上老 .txt 的常见编码）倒是不会被判成二进制，但会解成乱码。
#   现在按 BOM → UTF-16 特征 → UTF-8 → 中文常见编码的顺序猜，并且**把猜到的
#   编码记下来**：保存时按同一种写回去（否则"改一个字保存"会把整个文件转码）。
_BOMS = [
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
]
# 猜的顺序：UTF-8 优先（现在的文件几乎都是），再挑中文 Windows 上最常见的几个。
# `.decode` 失败就换下一个 —— 这些编码的非法序列不同，误判概率很低。
_TRY = ("utf-8", "gbk", "big5", "shift_jis", "latin-1")


def _looks_binary(raw):
    """真的二进制文件：有 NUL，或者控制字符占了一大片。"""
    head = raw[:8192]
    if b"\x00" in head:
        return True
    ctrl = sum(1 for b in head if b < 9 or (13 < b < 32))
    return bool(head) and ctrl / len(head) > 0.10


def _decode_text(raw):
    """bytes → (文本, 编码, BOM 的十六进制串 或 "")。真的二进制返回 (None, None, "")。

    ★ BOM 单独拎出来自己剥（而不是用 `utf-16` / `utf-8-sig` 那种"会自己吃 BOM"的
      编解码器）：因为**写回去时得把同一个 BOM 原样放回去**，而 `utf-16` 写出去
      一定是小端 —— 一个 BE 的文件保存一次就变小端了。这里记的是**精确的**
      `utf-16-le` / `utf-16-be`，加上那个 BOM 串，round-trip 才真的等价。
    """
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            try:
                return raw[len(bom):].decode(enc), enc, bom.hex()
            except (UnicodeDecodeError, LookupError):
                break
    # ★ 顺序有讲究：**先试无 BOM 的 UTF-16，再判二进制**。
    #   反过来的话，UTF-16 里那些 0x00 会先撞上"有 NUL 就是二进制"那条，
    #   于是"另存为 UTF-16、但不写 BOM"的文本文件永远打不开（实测踩到）。
    #   判据用**NUL 的比例 + 落点**（不是"每个 ASCII 后面都得是 0"）：中文在
    #   UTF-16 里两个字节都不是 0，纯按奇数位统计会把"中英混排"的文件漏掉。
    head = raw[:4096]
    nulls = [i for i, b in enumerate(head) if b == 0]
    if len(head) >= 4 and len(nulls) / len(head) > 0.15:
        odd_n = sum(1 for i in nulls if i % 2)
        even_n = len(nulls) - odd_n
        for enc, hit in (("utf-16-le", odd_n), ("utf-16-be", even_n)):
            if hit / len(nulls) > 0.8:
                try:
                    return raw.decode(enc), enc, ""
                except UnicodeDecodeError:
                    pass
    if _looks_binary(raw):
        return None, None, ""
    for enc in _TRY:
        try:
            return raw.decode(enc), enc, ""
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", "replace"), "utf-8", ""


def rerun_argv(target, cwd="", args=""):
    """把一条历史记录翻成"在终端里会手敲的那条命令"。返回 (argv, cwd)，空目标给 (None, None)。

    ★ 为什么不能直接用绝对路径（2026-09-28 实测踩到）：
      `core/resolve.py:find()` 只在 cwd 往上做**名字前缀匹配** —— 绝对路径会被
      当成一个名字（`C:\\x\\y.py` 里还要按 `/` 拆段），永远匹配不到任何候选，
      于是界面上点「运行」只会得到一句"没找到以 … 开头的可运行目标"。
      CLI 自己的 `--history` 回车之所以能跑，是因为它走 `cmd_rerun_record`，
      **直接构造 Invocation、绕过解析器**。界面这边不另开执行通道（`U-16`），
      所以只能翻成手敲形式：

          cwd  = 当初记录的 cwd（不是目录了就退到目标自己所在的目录，再退 user_data）
          名字 = 目标**相对这个 cwd** 的写法；目标不在它下面时只给文件名
                 （只给文件名时靠 `V-20` 那条历史兜底 —— 即 `moss zeen` 那种写法）

      cwd=`D:\\python\\wwwroot\\ZeEn` + 目标=同目录 `main.py` → `moss /main.py`
      目标在子目录里（cwd 是上层）                        → `moss /ZeEn/main.py`
    """
    target = str(target or "").strip()
    if not target:
        return None, None
    tp = Path(target)
    if cwd and Path(cwd).is_dir():
        workdir = Path(cwd)
    elif tp.parent.is_dir():
        workdir = tp.parent
    else:
        workdir = USER_DATA
    try:
        name = tp.resolve().relative_to(workdir.resolve()).as_posix()
    except (ValueError, OSError):
        name = tp.name
    return HOST + ["/" + name] + _split(args), workdir


def _dir_icon(folder, exts):
    """在一个目录里按顺序找 `icon.<ext>`，找到就返回 (data URI, 内联 svg 文本)。

    和宿主 `core/pkg.py:icon_path` 是同一套前缀顺序（svg → png → webp → jpg/jpeg →
    ico → gif → bmp）。这里没法 import core（发行版里它编在 exe 里），所以那份顺序
    由宿主在 payload 里带过来（`icon_exts`），**不各写一份**。
    """
    try:
        folder = Path(folder)
        if not folder.is_dir():
            return "", ""
        for ext in exts:
            f = folder / ("icon" + ext)
            if not f.is_file():
                continue
            raw = f.read_bytes()
            if not raw or len(raw) > 200 * 1024:
                continue
            if ext.lower() == ".svg":
                return "", raw.decode("utf-8", "replace")
            mime = {".png": "image/png", ".webp": "image/webp", ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg", ".ico": "image/x-icon", ".gif": "image/gif",
                    ".bmp": "image/bmp"}.get(ext.lower(), "application/octet-stream")
            return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii")), ""
    except OSError:
        pass
    return "", ""


def _run_registered(proc):
    """把一个刚起的后台进程登记进 RUNS，返回 run_id（`run_start` / `path_start` 共用）。"""
    rid = uuid.uuid4().hex[:10]
    with RUNS_LOCK:
        RUNS[rid] = {"proc": proc, "lines": [], "code": None, "t0": time.time(),
                     "pid": proc.pid,
                     "cmd": " ".join(proc.args[1:] if isinstance(proc.args, list) else [])}
        if len(RUNS) > RUNS_KEEP:
            for old in sorted(RUNS, key=lambda k: RUNS[k]["t0"])[:-RUNS_KEEP]:
                if RUNS[old]["code"] is not None:
                    RUNS.pop(old, None)
    threading.Thread(target=_pump_output, args=(rid,), daemon=True).start()
    return rid


def _env_pkg_id(pid):
    """问一个进程：它的环境变量里 `MOSS_PKG_ID` 是什么。

    ★ 为什么要它：光靠"本程序拉起过的进程树"认不出这些情况 ——
      ① 用户是**从终端**敲 `moss :exec` 开的（本程序没经手）；
      ② 包的父进程 fork 出界面之后**自己退出了**（PID 树断了，界面成了孤儿）；
      ③ moss 界面重启过（内存里那份进程表没了）。
      而宿主给每个包调用都注入了 `MOSS_PKG_ID`（`core/engine.py:144`），
      它跟着子进程一路继承下去 —— 所以"谁在跑这个包"这件事，
      **进程自己身上就写着**，比宿主记的账可靠。
    ⚠️ 已知副作用（`P-18` ⬜）：`MOSS_*` 会顺着长驻服务往下漏（实测 dsh 那棵树里
      node/pwsh 都带着 `MOSS_PKG_ID=dsh`），所以对 `dsh` 这种包，认出来的可能偏多。
      `P-18` 那条定了之后这里会更准。
    """
    try:
        import psutil
        return (psutil.Process(int(pid)).environ() or {}).get("MOSS_PKG_ID")
    except Exception:              # 提权进程读不到环境、进程已退出……
        return None


def _pids_by_cmdline():
    """{pid: 命令行（小写、反斜杠统一成正斜杠）}。

    ★ 这是最便宜也最广的一条线索（实测 391 个进程只要 **22ms**）：包不管是界面型的
      还是后台服务型的，只要是被 `python.exe bootstrap.py …\\pkgs\\<id>\\main.py`
      这种方式拉起来的，命令行里就写着它在哪个包目录里 —— **不用它有窗口**。
      （只读环境的代价是 219ms，所以那条只在"有窗口的进程"上用。）
    """
    out = {}
    try:
        import psutil
        for p in psutil.process_iter(["pid", "cmdline"]):
            try:
                cl = " ".join(p.info["cmdline"] or [])
            except Exception:
                continue
            if cl:
                out[int(p.info["pid"])] = cl.replace("\\", "/").lower()
    except Exception:
        pass
    return out


def _pkg_dir_names(pid):
    """这个 id 对应的**真实包目录名**（可能不只一个，都回）。

    `D-27` 方案 C：目录名和 id **允许不一样**（目录名是文件系统的事、id 是身份）。
    而进程命令行里写的是**真实目录**（`…\\pkgs\\my-first\\run.py`），所以"认进程"
    必须按目录名认 —— 只按 id 认的话，目录名不同的包从终端启动时界面认不出它在跑。
    """
    out = []
    for p in (DATA.get("packages") or []):
        if str(p.get("id")) == str(pid):
            d = p.get("dir")
            if d:
                name = Path(str(d)).name
                if name and name not in out:
                    out.append(name)
    return out


def _pkg_needles(pid):
    """认进程用的那几段命令行片段：`/pkgs/<id>/` 加 `/pkgs/<真实目录名>/`。

    两个线索都留着：id 那条在"目录名恰好等于 id"（出厂包全是）时最快命中，
    目录名那条兜住"两者不一样"的情况。多认一个线索不会认错包 —— 命令行里
    带 `pkgs/<这个名字>/` 的进程，本来就属于这个包。
    """
    names = [str(pid)] + _pkg_dir_names(pid)
    return ["/pkgs/%s/" % n.replace("\\", "/").lower() for n in names if n]


#: 认"这是某个包在跑"时，允许当"执行者"的解释器（小写、不带 .exe）。
#: ★ 为什么要挨个点名（`V-46` ✅）：光看"命令行里出现 `/pkgs/<目录>/`"太宽了 ——
#:   实测同时躺着好几个**完全无关**的进程都带着那条路径：
#:     · PowerToys 的 Monaco 预览器（命令行里是 `…\system\pkgs\img\pkg.json` ——
#:       你在资源管理器里选中过那个文件）
#:     · DSH 的 node 包装器、以及**我自己那条探测命令**（命令行里含有它的**文本**，
#:       文本里提到了那个路径）
#:   结果是界面**永远**认为 img 在跑、按钮永远是「停止」，怎么等都不变回来。
#:   编辑器、杀毒、索引器、随手一条提到路径的命令都会这样。所以判据改成：
#:   "命令行里带着那个目录" **而且** 看起来真的在**执行**它。
_RUNNER_EXES = {
    "python", "pythonw", "py", "python3", "go", "node", "deno", "bun", "java", "javaw",
    "ruby", "perl", "php", "lua", "rscript", "dotnet", "cmd", "powershell", "pwsh",
    "wscript", "cscript", "sh", "bash", "mshta", "moss",
}


def _pkg_run_match(cl, needle):
    """这一条命令行能算成"这个包在跑"吗？（`cl` 已经小写、反斜杠换成斜杠）

    判据两条，满足一条就算：
      ① 开头的可执行文件是**认识的解释器**（python / cmd / pwsh / node…）——
         命令行里又有这个包的目录 ⇒ 基本就是 `python …/pkgs/x/main.py` 这种；
      ② 开头的可执行文件**自己就在这个包目录里**（包自带的 exe，`unwx` 那种）。
    两条都不满足的（预览器、编辑器、杀毒…）只当它是"提到"了这个路径，不算它跑。
    """
    if needle not in cl:
        return False
    # ★ 两头都要剥引号：Windows 上带空格的路径会被引号括起来
    #   （`"c:/program files/python/python.exe" "…/pkgs/img/main.py"`），
    #   只剥开头的话拿到的名字是 `python.exe"`，谁都认不出来（实测踩到）。
    head = cl.strip().split(" ", 1)[0].strip('"')
    name = head.rsplit("/", 1)[-1]
    if name.endswith(".exe"):
        name = name[:-4]
    if name in _RUNNER_EXES:
        return True
    return needle in head            # 可执行文件自己就在包目录里（包自带的 exe）


def _pkg_pids(pkg, parents=None, cmdlines=None, owner_pkg=None):
    """属于这个包、**还活着**的进程：
       ① 宿主记下的进程树（点过运行 / 打开界面的）
       ② 命令行里带着 `pkgs/<id>/` 或 `pkgs/<真实目录名>/` 的
          （从终端开的、后台服务都算；两者不一样时按目录名认，`D-27`）
       ③ 拥有窗口、且环境里 `MOSS_PKG_ID` 等于它的（包自己 re-exec 之类的情况）
    """
    pkg = str(pkg)
    pids = set()
    roots = _live_roots(_pkg_procs.get(pkg) or set())
    if roots:
        pids |= _with_descendants(roots, parents)
    if cmdlines is None:
        cmdlines = _pids_by_cmdline()
    needles = _pkg_needles(pkg)
    pids |= {pid for pid, cl in cmdlines.items()
             if any(_pkg_run_match(cl, n) for n in needles)}
    if owner_pkg is None:
        owner_pkg = {}
        for w in _top_windows():
            pid = w["pid"]
            if pid == os.getpid() or pid in owner_pkg:
                continue
            owner_pkg[pid] = _env_pkg_id(pid)
    pids |= {pid for pid, k in owner_pkg.items() if k == pkg}
    pids.discard(os.getpid())                # 别把 moss 自己的界面窗口算进去
    return pids


def _pkg_windows(pkg):
    pids = _pkg_pids(pkg)
    if not pids:
        return []
    return [w for w in _top_windows()
            if w["pid"] in pids and w["class"] not in _HELPER_CLASSES]


def _is_window(hwnd):
    try:
        return bool(ctypes.WinDLL("user32").IsWindow(ctypes.c_void_p(hwnd)))
    except Exception:
        return False


def _show_window(hwnd, show):
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    SW_SHOW, SW_HIDE, SW_RESTORE = 5, 0, 9
    try:
        u32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
        u32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
        u32.ShowWindow(hwnd, SW_RESTORE if show else SW_HIDE)
        if show:
            u32.SetForegroundWindow(hwnd)
        return True
    except Exception:
        return False


# ================================================================ 后台运行
# 「运行」不能再是"一个阻塞调用" —— 那样跑起来就**没法停**，长驻的东西（服务、
# 开界面的包）会把界面卡在那儿。所以照 exec 的做法拆成三件：
#     run_start  → 起进程、拿一个 run_id，输出丢给一个读线程攒着
#     run_poll   → 问"还在跑吗 / 到现在为止输出了什么"
#     run_stop   → 连子孙一起杀掉（taskkill /T）
# 页面每 200ms 轮询一次，于是输出是**流式**刷出来的，而且随时能停。
RUNS = {}
RUNS_LOCK = threading.Lock()
RUNS_KEEP = 20


def _kill_tree(pid):
    """连子进程一起杀。包可能自己又起了进程（服务、界面），只杀父的会留孤儿。"""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    except Exception:
        pass


def _embed_server():
    """把那个给包界面用的本地 HTTP 服务起起来（第一次用到才起）。返回 (port, token)。"""
    with EMBED_LOCK:
        if _EMBED_SRV["httpd"] is not None:
            return _EMBED_SRV["port"], _EMBED_SRV["token"]
        token = uuid.uuid4().hex
        try:
            httpd = _EmbedServer(("127.0.0.1", 0), _EmbedHandler)
        except OSError as e:
            return 0, "起不来：%s" % e
        _EMBED_SRV.update({"httpd": httpd, "port": httpd.server_address[1], "token": token})
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return _EMBED_SRV["port"], token


class _EmbedServer(http.server.ThreadingHTTPServer):
    """发页面 / 发包界面用的本地服务（`V-77` 起改成这个子类）。

    ★ 只为了把**连接队列**放大：`socketserver` 默认 `request_queue_size = 5`，
      而 Chromium 对同一个源会**并发开 6 条连接**（HTML 里十几个 script/link 一起下）。
      Windows 上队列一满**直接给 ERR_CONNECTION_REFUSED**（不是让你排队等）——
      实测现场就是"同一秒里一半请求 200、另一半连服务都没进到"，界面因此半死不活。
      放大到 128 之后这个坑就没了。`MOSS_EMBED_BACKLOG` 只是为了对照实验留的口子。
    """
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = int(os.environ.get("MOSS_EMBED_BACKLOG") or 128)


class _EmbedHandler(http.server.SimpleHTTPRequestHandler):
    """只读地把安装根下面的文件发给包界面（`V-55`）。

    ★ 三道口子必须一起关上，不然这就是个"本机任意文件读取"：
      ① 只绑 `127.0.0.1`（外面连不上）；
      ② 路径里必须带**本次会话的随机 token**（别的程序猜不到）；
      ③ 只实现 GET/HEAD（不能写），且 `translate_path` 由父类做 `..` 归一化。
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HOME), **kw)

    def log_message(self, *a):                                          # noqa: A003
        pass                        # 别往控制台喷访问日志（一屏都是它）

    def send_response(self, code, message=None):
        """把每个请求 + 状态码记一行（`V-74`）。

        ★ 为什么要留这个：界面一旦空白，第一件事就是问"请求到底有没有到我的服务"。
          到了（200/403/404）= 服务没事，问题在页面；压根没到 = 请求被别人截走了
          （代理之类）。日志写在 `user_data/state/_ui_http.log`，只留最近这些，别长成山。
        """
        try:
            line = "%s  %s  %s\n" % (time.strftime("%H:%M:%S"), code, self.path)
            path = USER_DATA / "state" / "_ui_http.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > 64 * 1024:
                keep = path.read_text(encoding="utf-8", errors="replace")[-16 * 1024:]
                path.write_text(keep, encoding="utf-8")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:                                            # noqa: BLE001
            pass
        super().send_response(code, message)

    def _token_ok(self):
        tk = _EMBED_SRV["token"]
        return bool(tk) and self.path.startswith("/" + tk + "/")

    def do_GET(self):                                                    # noqa: N802
        if not self._token_ok():
            self.send_error(403, "bad token")
            return
        super().do_GET()

    def do_HEAD(self):                                                   # noqa: N802
        if not self._token_ok():
            self.send_error(403, "bad token")
            return
        super().do_HEAD()

    def translate_path(self, path):
        tk = _EMBED_SRV["token"]
        if tk and path.startswith("/" + tk + "/"):
            path = path[len(tk) + 1:]        # 去掉 token 那一段，剩下的才是真路径
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")     # 改了界面文件刷新就见效
        super().end_headers()


def _pump_embed(pid, proc):
    """读内嵌后端进程的输出，按行分两路（`V-48` ✅）：

      · `{` 开头 → 当**消息**，原样送进页面（`window.__mossEmbedFromBackend(一行)`）；
      · 其余（宿主横幅、包的 print）→ 攒起来给命令行面板看，别丢。

    ★ 进程结束时要告诉页面一声，不然界面那边会一直等一个已经不在的后端。
    """
    try:
        for line in proc.stdout:
            s = (line or "").rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("{"):
                try:
                    # ★ 带上 pid：界面上可能同时开着好几个包的内嵌界面，
                    #   它得知道这一行是谁说的，才能送回**那一帧**。
                    window.evaluate_js("window.__mossEmbedFromBackend(%s, %s)"
                                       % (json.dumps(str(pid)), json.dumps(s, ensure_ascii=False)))
                except Exception:                                    # noqa: BLE001
                    pass
            else:
                with EMBED_LOCK:
                    rec = EMBED.get(pid)
                    if rec is not None:
                        rec["lines"].append(s + "\n")
                        if len(rec["lines"]) > 500:                  # 别越攒越多
                            del rec["lines"][:200]
    except Exception:                                                # noqa: BLE001
        pass
    finally:
        try:
            proc.wait(timeout=5)
        except Exception:                                            # noqa: BLE001
            pass
        code = proc.returncode
        with EMBED_LOCK:
            if EMBED.get(pid, {}).get("proc") is proc:
                EMBED.pop(pid, None)
        try:
            window.evaluate_js("window.__mossEmbedGone(%s, %s)"
                               % (json.dumps(pid), json.dumps(code)))
        except Exception:                                            # noqa: BLE001
            pass


def _pump_output(rid):
    """读线程：把子进程的输出攒进 `RUNS[rid]['lines']`。

    ★ `V-86`（写那个交互测试包时实测出来的）：原来是 `for line in proc.stdout` —— 那是
      **按行**交。而"半行"（尾巴上没有换行的输出，最典型的就是 `input("你叫什么？ ")`
      的提示语）会一直被它攥着不交 ⇒ 界面上看着像"跑起来了、但什么都不问"，而你其实
      正被这个包等着回答；等你敲完回车，那句问题才连着你答的一起蹦出来（实测就是这样）。
      所以现在：① 按**块**读（一行一行、或者一个字一个字都太慢）；
      ② 攒到换行就立刻交；③ 手里那半行超过 0.12 秒等不到新数据，也先交出去。
    """
    r = RUNS.get(rid)
    if not r:
        return
    proc = r["proc"]
    pending = [""]                     # 还没交出去的那半行（两个线程都碰，走 RUNS_LOCK）
    stop = threading.Event()

    def emit(text):
        if not text:
            return
        with RUNS_LOCK:
            r["lines"].append(text)

    def ticker():
        # 每 0.12 秒看一眼：手里还攥着半行就先交出去（提示语这类没有换行的输出也能及时看到）
        while not stop.wait(0.12):
            with RUNS_LOCK:
                chunk, pending[0] = pending[0], ""
            emit(chunk)

    threading.Thread(target=ticker, daemon=True).start()
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        fd = proc.stdout.fileno()
        while True:
            buf = os.read(fd, 4096)
            if not buf:
                break
            text = dec.decode(buf)
            if not text:
                continue
            with RUNS_LOCK:
                parts = (pending[0] + text).split("\n")
                pending[0] = parts.pop()           # 最后一段可能没有换行，留着
            if parts:
                emit("\n".join(parts) + "\n")
    except Exception:
        pass
    finally:
        stop.set()
        with RUNS_LOCK:
            chunk, pending[0] = pending[0], ""
        emit(chunk)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        with RUNS_LOCK:
            r["code"] = proc.returncode
        try:
            proc.stdout.close()
        except Exception:
            pass


class Api:
    """给页面用的接口。每个方法都是一个前端可 await 的调用。"""

    def state(self):
        """界面要的那份数据：**每次调用都回宿主重新问一遍**。

        ★ 为什么不能直接返回启动时那份：宿主启动时把 payload 写成**一个文件**交给界面
          （`U-16` 的数据流是单向的），那份文件是**快照**。于是"新建一个包 / 卸载一个包"
          之后列表里看不到新包 —— 界面再来读还是旧的那份，详情里连目录都拿不到。
          现在改成回宿主跑一次 `--ui-payload`（宿主那边就是把 `build_payload()` 原样输出），
          包列表 / 图标 / 目录全是新的；宿主不可用时退回启动时那份，界面不会因此打不开。

        ★ 退回去这件事**不能是静默的**（`V-31` ✅）：退回时在数据里挂一句
          `stale_reason`，界面会把它弹出来 —— 否则"界面不刷新"就成了玄学，
          你看到的只是"我新建的包不见了"，而真正的原因（宿主那边有话说）谁也看不见。
        """
        fresh = self._host_payload()
        if fresh:
            DATA.clear()
            DATA.update(fresh)
            DATA.pop("stale_reason", None)
        else:
            DATA["stale_reason"] = self._payload_error or "读包表失败（宿主没有回话）"
        return DATA

    def _host_payload(self):
        """回宿主问一次 payload。失败返回 None（调用方退回旧的），原因记在 `_payload_error`。"""
        self._payload_error = ""
        if not HOST:
            self._payload_error = "没拿到宿主命令（界面得由 moss 自己拉起）"
            return None
        try:
            r = _run_capture_split(HOST + ["--ui-payload"])     # ★ stdout / stderr 分开
        except OSError as e:
            self._payload_error = "叫不动宿主：%s" % e
            return None
        out = (r.get("out") or "").strip()
        if r.get("code") != 0 or not out:
            tail = ((r.get("err") or "").strip().splitlines() or [""])[-1]
            self._payload_error = ("宿主退出码 %s%s"
                                   % (r.get("code"), ("：" + tail) if tail else ""))
            return None
        data = _json_from_host(out)
        if data is None:
            tail = ((r.get("err") or "").strip().splitlines() or [""])[-1]
            self._payload_error = ("宿主没回 JSON%s"
                                   % ((" —— 宿主说：" + tail) if tail else ""))
            return None
        if not (isinstance(data, dict) and "packages" in data):
            self._payload_error = "宿主回的 JSON 里没有 packages"
            return None
        return data

    def run(self, pid, args_text=""):
        """带参数跑一个包并等它跑完（老的阻塞式；界面现在走 run_start 那一套）。"""
        return _run_capture(HOST + [":" + str(pid)] + _split(args_text))

    def run_start(self, pid, args_text="", cwd=None):
        """起一个后台运行，立刻返回 run_id（输出靠 `run_poll` 拿）。

        `cwd`：**这次运行的工作目录**（拖文件进来那条路会传 —— 你拖着某个文件夹
        到详情页，意思就是"以它为当前目录跑这个包"）。不传就跟以前一样，继承界面
        自己的 cwd。宿主那边 `engine` 是拿 `os.getcwd()` 当包的工作目录的（`pkg.json`
        里没写 `env.cwd` 时），所以这里给它换掉就等于给包换了工作目录。

        ★ 目录不存在就**当没传**：路径可能是刚被删掉的、或者拖的是个断了的网络盘，
          那种情况下宁可退回默认目录，也不要让进程根本起不来。
        """
        argv = HOST + [":" + str(pid)] + _split(args_text)
        workdir = None
        if cwd:
            try:
                if Path(str(cwd)).is_dir():
                    workdir = str(cwd)
            except OSError:
                workdir = None
        # ★ 告诉包"有人在听"（`V-44` ✅）：界面给了它一根 stdin 管子，命令行下面有输入行，
        #   所以它 `input()` 是拿得到回答的。为什么必须说一声：包没法从 `isatty()` 看出来
        #   （管子不是终端，`isatty()` 永远是假），于是像图片工具那样"没终端就拒绝交互"的包
        #   会直接报错退出。约定写在《插件契约》§4（`MOSS_INTERACTIVE`）。
        #   **只给这一次运行加**（不动界面自己的环境），别的地方跑起来的包不受影响。
        run_env = dict(os.environ)
        run_env["MOSS_INTERACTIVE"] = "1"
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE, env=run_env,
                                    text=True, encoding="utf-8", errors="replace",
                                    bufsize=1, creationflags=NO_WINDOW, cwd=workdir)
        except OSError as e:
            return {"ok": False, "msg": "启动失败：%s" % e}
        _remember_proc(pid, proc.pid)          # 记下来，之后才找得到它的界面窗口
        rid = uuid.uuid4().hex[:10]
        with RUNS_LOCK:
            RUNS[rid] = {"proc": proc, "lines": [], "code": None, "t0": time.time(),
                         "pid": proc.pid, "cmd": " ".join(argv[1:])}
            if len(RUNS) > RUNS_KEEP:                    # 只留最近这些，别越攒越多
                for old in sorted(RUNS, key=lambda k: RUNS[k]["t0"])[:-RUNS_KEEP]:
                    if RUNS[old]["code"] is not None:
                        RUNS.pop(old, None)
        threading.Thread(target=_pump_output, args=(rid,), daemon=True).start()
        return {"ok": True, "run_id": rid, "pid": proc.pid}

    def run_input(self, run_id, text=""):
        """往正在跑的那个进程的 **stdin 写一行**（`V-43` ✅）。

        为什么要有它：不少包会**问你一句**再干活 —— 图片工具第一句就是
        「输出到哪？1) 覆盖原图 2) 删除原图 3) 新文件夹」，它 `input()` 等着；
        而界面原来那份命令行是**只读**的（只能看输出），于是包就一直卡在那儿。
        现在命令行下面多一行输入框，回车就走这里。

        ★ 这条路能通，是因为宿主起子进程时**没接 stdin**（`engine` 里只给了 stdout /
          stderr），子进程直接继承宿主的 stdin ⇒ 我们给宿主的 stdin 接一根管子，
          管子另一头就是包在等的那一行。子进程的环境里宿主已经摆了
          `PYTHONIOENCODING=utf-8`（`engine.build_env`），所以这边按 UTF-8 写是对的。
        """
        with RUNS_LOCK:
            run = RUNS.get(str(run_id))
        if not run:
            return {"ok": False, "msg": "这次运行已经结束了（没有进程在等）"}
        proc = run.get("proc")
        # ★ 先看进程还在不在：管道**死了也还能写**（内核缓冲），写进去没人读、也不报错 ——
        #   那种"看着发出去了其实没人收"最误导人，所以先问一句。
        if proc is not None and proc.poll() is not None:
            return {"ok": False, "msg": "它已经跑完了（没在等你回答）"}
        stdin = getattr(proc, "stdin", None)
        if stdin is None:
            return {"ok": False, "msg": "这次运行没接上输入"}
        try:
            stdin.write(str(text) + "\n")
            stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            return {"ok": False, "msg": "它已经不吃输入了（可能跑完了，或者根本没在等）：%s" % e}
        return {"ok": True}

    def run_poll(self, run_id):
        """问一次状态：还在跑吗、输出到哪了、结束了的话退出码是多少。"""
        with RUNS_LOCK:
            r = RUNS.get(run_id)
            if not r:
                return {"ok": False, "msg": "没有这次运行（可能已经被清掉了）"}
            return {"ok": True, "running": r["code"] is None, "code": r["code"],
                    "out": "".join(r["lines"]),
                    "ms": int((time.time() - r["t0"]) * 1000), "pid": r["pid"]}

    def run_stop(self, run_id):
        """停掉：连子孙进程一起杀。"""
        with RUNS_LOCK:
            r = RUNS.get(run_id)
            if not r:
                return {"ok": False, "msg": "没有这次运行"}
            if r["code"] is not None:
                return {"ok": True, "msg": "它已经结束了"}
            pid = r["pid"]
        _kill_tree(pid)
        return {"ok": True, "msg": "已终止这次运行（连同它拉起的子进程）"}

    def open_ui(self, pid, args_text=""):
        """把包的界面开起来：**脱离**当前进程、不抓输出，所以不会卡住界面。"""
        argv = HOST + [":" + str(pid)] + _split(args_text)
        try:
            proc = subprocess.Popen(argv, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
                                    creationflags=NO_WINDOW | DETACHED, close_fds=True)
        except OSError as e:
            return {"ok": False, "msg": "启动失败：%s" % e}
        _remember_proc(pid, proc.pid)          # 同上：留着，好找它的窗口
        return {"ok": True, "msg": "已后台启动：" + " ".join(argv[1:])}

    # ------------------------------------------------ 历史（路径调用）
    def hist_list(self, n=30):
        """最近跑过的**路径调用**（`moss zeen` 这种），最新的在前。

        ★ 数据就是 `user_data/history/*.jsonl` —— 界面进程不 import core（发行版里
          core 编在 exe 里），所以这里直接读那本账，**格式就是接口**。
        ★ 去重/过滤口径**必须和宿主一模一样**（`core/history.py` 的 `dedup_key` /
          `should_record`）：两边读的是同一本账，键算法一旦不同，界面里"删掉一条"
          在 CLI 的 `--history` 里就会**又冒出来**。所以下面 `_hist_key` /
          `_hist_is_record` 是那两个函数的**逐字镜像**
          （改一处必须改两处 —— 这两份注定要重复，因为不能 import）。
        ★ 图标规则：**目标所在目录里若有 `icon.xxx` 就用它**（包列表那边
          宿主的 `pkg.icon_path` 早就在这么做了，这里是同一套前缀顺序）。
        """
        rows = [r for r in _hist_read_all() if _hist_is_record(r)]
        # 去重：同一条命令只留最新那次
        best = {}
        for r in rows:
            key = _hist_key(r)
            old = best.get(key)
            if old is None or str(r.get("ts") or "") > str(old.get("ts") or ""):
                best[key] = r
        out_rows = sorted(best.values(), key=lambda r: str(r.get("ts") or ""), reverse=True)
        try:
            n = max(1, min(200, int(n)))
        except (TypeError, ValueError):
            n = 30
        out_rows = out_rows[:n]

        exts = [str(x) for x in (DATA.get("icon_exts") or
                                 [".svg", ".png", ".webp", ".jpg", ".jpeg", ".ico", ".gif", ".bmp"])]
        items = []
        for r in out_rows:
            target = str(r.get("target") or "")
            cwd = str(r.get("cwd") or "")
            icon_uri, icon_svg = "", ""
            if target:
                icon_uri, icon_svg = _dir_icon(Path(target).parent, exts)
            items.append({
                "ts": str(r.get("ts") or ""),
                "kind": str(r.get("kind") or ""),
                "id": str(r.get("id") or ""),
                "target": target,
                "name": Path(target).name or target,
                "cwd": cwd,
                "args": str(r.get("args") or ""),
                "exit": r.get("exit"),
                # ★ "这东西还在不在"：不在的条目界面画成灰的。
                #   目标没了 / 当初的目录没了，分开报 —— 一个是"跑不了了"，
                #   另一个只影响"在哪儿跑"。
                "exists": bool(target) and Path(target).is_file(),
                "cwd_exists": bool(cwd) and Path(cwd).is_dir(),
                "key": _hist_key(r),
                "icon": icon_uri,
                "icon_svg": icon_svg,
            })
        return {"ok": True, "items": items}

    def hist_forget(self, key):
        """把一条历史**真删掉**：把那几行从账里抠掉（原地改、保留行尾、原子截断）。

        ★ 为什么不是"追加一条墓碑、读的时候跳过"：
          墓碑只是"读的时候跳过"，**能不能跳过取决于读的人那份代码认不认它**。
          界面后端在 exe 外面、改完就是新的；而终端里的 `moss --history` 跑的是
          **编在 exe 里的 `core/history.py`** —— 旧 exe 不认识墓碑，于是
          "界面里删了、终端里还在"，还得为此专门重打一次包。**删就该真的删掉。**

        ★ 怎么做到既真删又不丢正在写的账：
          · **原地改**（`rb+`）而不是"另写一个文件再替换"—— 后者会把"另一头正在跑
            的那次调用结束时补的那条"整个盖掉；
          · 先把当前内容读完、记下读到哪，再检查文件在这期间有没有变长
            （有人追加了），变长就把那段**原样接着写到新内容后面**；
          · 最后 `truncate()` 收尾。行尾不翻译（二进制读写），只按 `\\n` 切。

        找不到这条（比如已经被删过）就什么都不做，报"已经不在了"。
        """
        key = str(key or "").strip()
        if not key:
            return {"ok": False, "msg": "没给要删的那条的键"}
        hist_dir = USER_DATA / "history"
        if not hist_dir.is_dir():
            return {"ok": False, "msg": "历史账不在：%s" % hist_dir}
        removed, touched = 0, []
        for f in sorted(hist_dir.glob("*.jsonl")):
            hit = _hist_drop_lines(f, key)
            if hit:
                removed += hit
                touched.append(f.name)
        if not removed:
            return {"ok": False, "msg": "这条记录已经不在了（可能刚删过一次）"}
        return {"ok": True, "msg": "已删掉这条记录（%d 行，%s）" % (removed, "、".join(touched))}

    def path_start(self, target, cwd="", args=""):
        """重跑一次**路径调用**（历史条目点「运行」就是它）。

        ★ 关键：**不能把绝对路径直接丢给 moss**（2026-09-28 实测踩到）。
          `resolve.find()` 只会在 cwd 往上做**名字前缀匹配**，绝对路径会被当成名字，
          于是永远"候选 0 个" —— 也就是说这条路**从来没真正跑起来过**。
          （CLI 自己的 `--history` 回车能跑，是因为它走 `cmd_rerun_record`，
            直接构造调用、不过解析器。`moss zeen` 那种写法走的是 `V-20` 的历史兜底。）
          所以这里换成**和在终端里手敲完全一样的形式** —— 规则见 `rerun_argv()`。
        """
        argv, workdir = rerun_argv(target, cwd, args)
        if argv is None:
            return {"ok": False, "msg": "这条历史没有目标路径"}
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, encoding="utf-8", errors="replace",
                                    bufsize=1, cwd=str(workdir), creationflags=NO_WINDOW)
        except OSError as e:
            return {"ok": False, "msg": "启动失败：%s" % e}
        rid = uuid.uuid4().hex[:10]
        with RUNS_LOCK:
            RUNS[rid] = {"proc": proc, "lines": [], "code": None, "t0": time.time(),
                         "pid": proc.pid, "cmd": " ".join(argv[1:])}
            if len(RUNS) > RUNS_KEEP:
                for old in sorted(RUNS, key=lambda k: RUNS[k]["t0"])[:-RUNS_KEEP]:
                    if RUNS[old]["code"] is not None:
                        RUNS.pop(old, None)
        threading.Thread(target=_pump_output, args=(rid,), daemon=True).start()
        # 把**真正要跑的命令和当前目录**回报给界面（界面照着显示，不自己另算一遍）
        return {"ok": True, "run_id": rid, "pid": proc.pid,
                "cmd": "moss " + " ".join(argv[len(HOST):]), "cwd": str(workdir)}

    # ------------------------------------------------ 包自己的界面窗口（显示/隐藏）
    def pkg_states(self, ids):
        """**一次**把"这些包分别在不在跑、有没有窗口"全算出来。

        ★ 为什么要批量：左侧列表要给**每一个**包显示状态（跑着的显示绿色停止图标），
          一个包一次调用的话，每轮要重复枚举窗口 N 遍。
          这里只枚举一次窗口、只对"有窗口的进程"读一遍环境，再把结果分给各个包。
        """
        want = [str(x) for x in (ids or [])]
        wins = [w for w in _top_windows() if w["class"] not in _HELPER_CLASSES]
        me = os.getpid()
        owner_pkg = {}                       # 有窗口的 pid -> 它属于哪个包（每个只读一次环境）
        for w in wins:
            pid = w["pid"]
            if pid == me or pid in owner_pkg:
                continue
            owner_pkg[pid] = _env_pkg_id(pid)
        allp = _pid_parents()                # 进程快照也只取一次，所有包共用
        cmdlines = _pids_by_cmdline()        # 命令行也只扫一次（22ms）
        out = {}
        for pkg in want:
            pids = _pkg_pids(pkg, allp, cmdlines, owner_pkg)
            ws = [w for w in wins if w["pid"] in pids]
            vis = [w for w in ws if w["visible"]]
            out[pkg] = {"running": bool(pids), "pids": len(pids),
                        "windows": len(ws), "visible": len(vis) > 0,
                        "titles": [w["title"] for w in ws][:5]}
        return {"ok": True, "states": out}

    def pkg_state(self, pid):
        """这个包**现在在不在跑**、有没有窗口、窗口是显示还是隐藏。

        「在不在跑」不只算宿主自己拉起的：从终端开的、父进程退了的，都认得出
        （看进程环境里的 `MOSS_PKG_ID`）。界面右上角那个按钮就靠它决定
        显示「运行」还是「停止」。
        """
        pids = _pkg_pids(pid)
        ws = [w for w in _top_windows()
              if w["pid"] in pids and w["class"] not in _HELPER_CLASSES]
        vis = [w for w in ws if w["visible"]]
        return {"ok": True, "running": bool(pids), "pids": len(pids),
                "windows": len(ws), "visible": len(vis) > 0,
                "titles": [w["title"] for w in ws][:5]}

    def pkg_stop(self, pid):
        """把这个包正在跑的进程停掉（连子孙一起）—— 不管是谁把它拉起来的。"""
        pids = _pkg_pids(pid)
        if not pids:
            return {"ok": False, "msg": "这个包现在没在跑"}
        for p in pids:
            _kill_tree(p)
        return {"ok": True, "msg": "已停掉这个包（%d 个进程，连同它们的子进程）" % len(pids)}

    def pkg_hide(self, pid):
        """把它的窗口藏起来（不关、不杀，随时能再显示）。"""
        ws = _pkg_windows(pid)
        if not ws:
            return {"ok": False, "msg": "没找到它的窗口 —— 先「打开界面」或「运行」一次"}
        vis = [w for w in ws if w["visible"]]      # ★ 只碰**当前可见**的，辅助窗本来就没显示
        if not vis:
            return {"ok": True, "msg": "它的窗口本来就是隐藏的"}
        done = [w["hwnd"] for w in vis if _show_window(w["hwnd"], False)]
        if done:
            _pkg_hidden[str(pid)] = done            # 记下"是这里藏的"，显示时只放这几个
        return {"ok": bool(done), "msg": "已隐藏 %d 个窗口（没关掉，还能再显示出来）" % len(done)}

    def pkg_show(self, pid):
        """再显示出来，并把它叫到前面。"""
        hs = [h for h in _pkg_hidden.get(str(pid), []) if _is_window(h)]
        if not hs:
            ws = _pkg_windows(pid)
            if not ws:
                return {"ok": False, "msg": "没找到它的窗口 —— 先「打开界面」或「运行」一次"}
            hs = [w["hwnd"] for w in ws]            # 不是这里藏的（比如被最小化过）→ 全放出来
        n = sum(1 for h in hs if _show_window(h, True))
        if n:
            _pkg_hidden.pop(str(pid), None)
        return {"ok": n > 0, "msg": "已显示 %d 个窗口" % n}

    def run_host(self, text):
        """跑一条宿主命令（自检用）：`--selfcheck` / `--history 20` 之类，不带包名。"""
        return _run_capture(HOST + _split(text))

    def open_path(self, path):
        try:
            os.startfile(str(path))        # noqa: S606  Windows 专用
            return {"ok": True, "msg": "已打开：" + str(path)}
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}

    # ------------------------------------------------ 文件浏览 / 编辑（v0.5）
    def fs_roots(self):
        """账上的两个根（`user_data` / `system`）。

        ★ 注意这只是**账**的那两层；页面还能引用第三种：`abs/<绝对路径>`，
          给历史里那些散在磁盘各处的路径调用用（见 `ABS_ROOT`）。
        """
        return {"roots": [{"key": r["key"], "label": r["label"],
                           "path": str(r["path"]), "writable": r["writable"],
                           "why": r["why"],
                           "exists": Path(r["path"]).is_dir()} for r in ROOTS]}

    def fs_list(self, rel):
        """列一个目录。返回的每一项都带 `rel`，页面点它就能继续往下走。"""
        try:
            root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not p.exists():
            return {"ok": False, "msg": "没有这个东西：%s" % rel}
        if not p.is_dir():
            return {"ok": False, "msg": "不是目录：%s" % rel}
        entries = []
        try:
            for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
                if child.name == "__pycache__":
                    continue
                try:
                    st = child.stat()
                    size, mtime = st.st_size, int(st.st_mtime)
                except OSError:
                    size, mtime = 0, 0
                entries.append({"name": child.name, "rel": _rel_page(child),
                                "dir": child.is_dir(), "size": size, "mtime": mtime,
                                "ext": child.suffix.lower().lstrip(".")})
        except OSError as e:
            return {"ok": False, "msg": "读目录失败：%s" % e}
        return {"ok": True, "rel": _rel_page(p), "entries": entries,
                "writable": root["writable"], "path": str(p)}

    def fs_read(self, rel):
        """读一个文件。二进制 / 超大只回报状态，不给编辑（免得把编辑器当十六进制用）。"""
        try:
            root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not p.is_file():
            return {"ok": False, "msg": "不是文件：%s" % rel}
        size = p.stat().st_size
        if size > MAX_READ:
            return {"ok": True, "binary": False, "too_big": True, "size": size,
                    "text": "", "writable": root["writable"],
                    "msg": "文件 %.1f MB，超过 %.1f MB，不给编辑" % (size / 1048576, MAX_READ / 1048576)}
        raw = p.read_bytes()
        text, enc, bom_hex = _decode_text(raw)
        if text is None:
            return {"ok": True, "binary": True, "too_big": False, "size": size,
                    "text": "", "writable": False,
                    "msg": "二进制文件，不给编辑（要看就用「用默认程序打开」）"}
        # ★ 把**猜到的编码**告诉界面：一来状态栏能写清楚"这是 UTF-16 / GBK"，
        #   二来保存时要按同一种 + 同一个 BOM 写回去（否则改一个字就把整个文件转码了）。
        note = "" if enc == "utf-8" and not bom_hex else \
            "%s%s" % (enc.upper(), "（带 BOM）" if bom_hex else "")
        return {"ok": True, "binary": False, "too_big": False, "size": size,
                "text": text, "rel": _rel_page(p), "path": str(p),
                "writable": root["writable"], "encoding": enc, "bom": bom_hex,
                "encoding_note": note,
                "mtime": int(p.stat().st_mtime)}

    def fs_write(self, rel, text, encoding="utf-8", bom=""):
        """写回文件。三个根都能写（`system/` 也放开了，见文件头那段说明）。

        ★ `encoding` / `bom` 由 `fs_read` 给出、界面原样带回来 ——
          **按读进来的编码和 BOM 写回去**。不这么做的话，打开一个 GBK / UTF-16 的
          txt、改一个字保存，整个文件就被悄悄转成 UTF-8 了（在老程序里就成了乱码）。
        """
        try:
            root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if p.is_dir():
            return {"ok": False, "msg": "这是目录，不是文件"}
        enc = str(encoding or "utf-8")
        try:
            "".encode(enc)
        except LookupError:
            return {"ok": False, "msg": "不认识的编码：%s" % enc}
        try:
            head = bytes.fromhex(str(bom)) if bom else b""
        except ValueError:
            return {"ok": False, "msg": "BOM 写坏了：%r" % (bom,)}
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".moss-tmp")
            # ★ 用二进制写：文本模式默认会把 \n 翻成 \r\n，于是"没改一个字、点一下保存"
            #   也会把整个文件的行尾换掉（实测：写 "print(1)\n" 读回来是 "print(1)\r\n"）。
            #   字节级进出才是真的"原样进原样出"。
            with open(tmp, "wb") as f:
                f.write(head + text.encode(enc))
            os.replace(tmp, p)          # 原子替换：写一半断电也不会留半个文件
        except (OSError, UnicodeEncodeError) as e:
            return {"ok": False, "msg": "写不进去：%s" % e}
        return {"ok": True, "msg": "已保存 %s" % rel, "size": p.stat().st_size,
                "mtime": int(p.stat().st_mtime), "encoding": enc,
                "factory": rel.split("/")[0] == "system"}

    def fs_mkdir(self, rel_parent, name):
        return self._fs_create(rel_parent, name, True)

    def fs_touch(self, rel_parent, name):
        return self._fs_create(rel_parent, name, False)

    def _fs_create(self, rel_parent, name, as_dir):
        try:
            _root, parent = _resolve(rel_parent)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        name = str(name or "").strip()
        if _bad_name(name):
            return {"ok": False, "msg": "名字不合法"}
        if not parent.is_dir():
            return {"ok": False, "msg": "父目录不存在：%s" % rel_parent}
        target = parent / name
        if target.exists():
            return {"ok": False, "msg": "已经有一个同名的了"}
        try:
            if as_dir:
                target.mkdir()
            else:
                with open(target, "w", encoding="utf-8", newline=""):
                    pass
        except OSError as e:
            return {"ok": False, "msg": "建不了：%s" % e}
        return {"ok": True, "rel": _rel_page(target), "msg": "已创建 %s" % name}

    def fs_rename(self, rel, new_name):
        try:
            _root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        new_name = str(new_name or "").strip()
        if _bad_name(new_name):
            return {"ok": False, "msg": "名字不合法"}
        if p.parent == p:                          # 盘根没有"父目录里的名字"
            return {"ok": False, "msg": "盘根不能改名"}
        target = p.with_name(new_name)
        if target.exists():
            return {"ok": False, "msg": "已经有一个同名的了"}
        try:
            p.rename(target)
        except OSError as e:
            return {"ok": False, "msg": "改不了名：%s" % e}
        return {"ok": True, "rel": _rel_page(target), "old": rel, "msg": "已改名为 %s" % new_name}

    def fs_delete(self, rels):
        """删除 = **挪进 user_data/trash/**（可恢复），不真删。收一个或多个。

        ★ 两种"根本身"不许删：`user` / `system` 这两个账上的根，
          以及 `abs/` 那边**盘根**（`abs/D:/` —— 那一下就是把整块盘搬走）。
        """
        if isinstance(rels, str):
            rels = [rels]
        done, bad = [], []
        for rel in (rels or []):
            try:
                root, p = _resolve(rel)
            except ValueError as e:
                bad.append("%s：%s" % (rel, e))
                continue
            if root["key"] == ABS_KEY:
                if p.parent == p:                     # D:\ 这种盘根（父目录就是自己）
                    bad.append("%s：盘根不能删" % rel)
                    continue
            elif p == Path(root["path"]).resolve():
                bad.append("%s：根本身不能删" % rel)
                continue
            try:
                _old, new = _trash(p)
                done.append(new)
            except (ValueError, OSError) as e:
                bad.append("%s：%s" % (rel, e))
        if not done:
            return {"ok": False, "msg": "；".join(bad) or "什么都没删"}
        msg = "已挪进回收站（%s）" % "、".join(done[:3])
        if len(done) > 3:
            msg += " 等 %d 项" % len(done)
        if bad:
            msg += "；有 %d 项没成：%s" % (len(bad), bad[0])
        return {"ok": True, "msg": msg, "trash": done, "bad": bad}

    def fs_copy(self, rels, dest_rel, cut=False):
        """复制 / 移动（`cut=True`）若干项到一个目录 —— 资源管理器的 Ctrl+C / Ctrl+X / Ctrl+V。

        同名不覆盖，按资源管理器的规矩起 `名字 (2).ext`。
        """
        if isinstance(rels, str):
            rels = [rels]
        try:
            _droot, dest = _resolve(dest_rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not dest.is_dir():
            return {"ok": False, "msg": "目标不是目录：%s" % dest_rel}
        made, bad = [], []
        for rel in (rels or []):
            try:
                _sroot, src = _resolve(rel)
            except ValueError as e:
                bad.append(str(e))
                continue
            if not src.exists():
                bad.append("%s 不存在" % rel)
                continue
            # 别把目录搬进它自己里面（资源管理器也是直接拒绝的）
            if src.is_dir() and (dest == src or src in dest.parents):
                bad.append("%s：不能把目录放进它自己里面" % src.name)
                continue
            target = _unique(dest / src.name)
            try:
                if cut:
                    shutil.move(str(src), str(target))
                elif src.is_dir():
                    shutil.copytree(str(src), str(target))
                else:
                    shutil.copy2(str(src), str(target))
                made.append(_rel_page(target))
            except (OSError, shutil.Error) as e:
                bad.append("%s：%s" % (src.name, e))
        if not made:
            return {"ok": False, "msg": "；".join(bad) or "什么都没做"}
        verb = "移动" if cut else "复制"
        msg = "已%s %d 项" % (verb, len(made))
        if bad:
            msg += "；有 %d 项没成：%s" % (len(bad), bad[0])
        return {"ok": True, "msg": msg, "made": made, "bad": bad}

    def fs_exists(self, rels):
        """批量问"这些路径在不在"。

        ★ 用途：文件管理里那对"切到另一层"的按钮（`system/pkgs/md5` ↔
          `user_data/pkgs/md5`）**只有那一层真有这个包的目录时才显示** ——
          规则：只有那一层真有这个包的目录时，才显示那个切换按钮 ——
          所以页面需要在渲染时问一次，而不是猜。
        """
        out = {}
        for rel in (rels or []):
            try:
                _root, p = _resolve(rel)
                out[str(rel)] = p.exists()
            except ValueError:
                out[str(rel)] = False
        return {"ok": True, "has": out}

    def fs_open_default(self, rel):
        """用系统默认程序打开（二进制文件、图片这些不该塞进编辑器）。"""
        try:
            _root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not p.exists():
            return {"ok": False, "msg": "没有这个东西：%s" % rel}
        try:
            os.startfile(str(p))        # noqa: S606  Windows 专用
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}
        return {"ok": True, "msg": "已用默认程序打开 %s" % p.name}

    def fs_reveal(self, rel):
        """在资源管理器里选中它。"""
        try:
            _root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        try:
            subprocess.Popen(["explorer", "/select,", str(p)], creationflags=NO_WINDOW)
        except OSError as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": True, "msg": "已在资源管理器中打开"}

    def ui_log(self, text):
        """界面写一行日志（拖放这条线在用，见 `drop_log`）。出问题能一次看清。"""
        drop_log("page: " + str(text or ""))
        return {"ok": True}

    # ------------------------------------------------ 备份（`V-87`）
    # ★ 逻辑全在 `system/ui/backup.py`（内容寻址那套：指纹当文件名、内容只存一份、
    #   删备份后按"标记-清除"回收没人引用的对象）。这里只干两件事：
    #   ① 把**页面口径的 rel** 和**绝对路径**互相换（它自己不认识我们这几个根）；
    #   ② 把结果包成页面能直接用的形状。
    # ★ 放在界面层（不是 `core/`）⇒ **不用重打包 exe**；以后要 `moss --backup` 命令行，
    #   把 `backup.py` 挪进 `core/` 再补一条 CLI 就行（那时候要重打包）。
    def _backup_store(self):
        import backup as _bk
        # `rel_of` 用 `_rel_page`：三个根里算不出来就落成 `abs/<绝对路径>` ——
        # 那正是"外部目录"那个根能表达的东西，恢复时照样认得。
        # ★ `resolve` 要包一层：`_resolve()` 回的是 `(root, Path)` 一对，
        #   而备份库要的是"rel → 绝对路径"（这里第一版忘了拆，报
        #   `'tuple' object has no attribute 'exists'`）。
        # ★ `trash`：同步模式下"现在多出来的"文件挪进回收站（`_trash`，和文件管理里
        #   那个"删除"是同一条路 —— 不真删，随时能捡回来）。
        return _bk.BackupStore(USER_DATA / _bk.STORE_DIRNAME, _rel_page,
                               lambda rel: _resolve(rel)[1],
                               trash=lambda p: _trash(Path(p)),
                               log=drop_log)

    def backup_list(self, group=""):
        """备份列表 + 汇总 + **分组**（`V-89`：按包 id 分文件夹）。

        `group` 给了就只看那一组；不给 = 所有组（列表里每行带 `group`）。
        `groups` 是每个分组一行的汇总，界面那个"分组"下拉用它。
        """
        try:
            st = self._backup_store()
            g = str(group or "") or None
            return {"ok": True, "items": st.list_backups(g), "stat": st.stat(g),
                    "groups": st.groups_summary()}
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": "备份库读不出来：%s" % e, "items": [],
                    "stat": {}, "groups": []}

    def backup_group_hint(self, rels):
        """按来源告诉界面"这次会落到哪个分组"（新建表单上显示一行）。"""
        try:
            import backup as _bk
            rels = [str(r) for r in (rels or [])]
            return {"ok": True, "group": _bk.group_for_sources(rels)}
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_group_info(self, group):
        """一个分组的概况（几次备份、占多少）—— 卸载包的时候用来提示一句。"""
        try:
            st = self._backup_store()
            info = st.stat(group)
            items = st.list_backups(group)
            return {"ok": True, "group": str(group or ""), "backups": info.get("backups", 0),
                    "bytes": info.get("all_bytes", 0), "store_bytes": info.get("store_bytes", 0),
                    "last": (items[0].get("created_text") if items else "")}
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_rename_group(self, old, new):
        """分组改名（改包 id 时跟着改；目标已存在就合过去）。"""
        try:
            return self._backup_store().rename_group(old, new)
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_drop_group(self, group):
        """把整个分组删掉（连它的内容块）—— "这个包不要了，备份也一起清掉"。"""
        try:
            return self._backup_store().drop_group(group)
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_create(self, rels, title="", note="", group="", excludes=None):
        """备份一批 rel（页面给的是 `user/...` / `system/...` / `abs/...`）。

        落到哪个**分组**（`user_data/backups/<分组>/`）：不传就按来源猜（包 ⇒ 包 id，
        整个 user_data ⇒ `@user`，某个目录 ⇒ `@dir-<名字>`）。
        """
        try:
            st = self._backup_store()
            srcs = []
            for rel in (rels or []):
                try:
                    srcs.append(_resolve(rel)[1])
                except ValueError as e:
                    return {"ok": False, "msg": str(e)}
            if not srcs:
                return {"ok": False, "msg": "没有要备份的东西"}
            man = st.create(srcs, title=title, note=note, excludes=excludes,
                            group=(str(group or "") or None))
            return {"ok": True, "id": man["id"], "group": man.get("group"),
                    "stats": man["stats"], "created_text": man["created_text"],
                    "msg": "备份好了（分组 %s）：%s 个文件、%s" % (
                        man.get("group"), man["stats"]["files"],
                        _human(man["stats"]["bytes"]))}
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": "备份失败：%s" % e}

    def backup_manifest(self, bid, group=""):
        """一次备份的清单（含文件列表）。"""
        try:
            st = self._backup_store()
            m = st.manifest(bid, (str(group or "") or None))
            m = dict(m)
            m["ok"] = True
            return m
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_ignore_save(self, text, group=""):
        """把界面里改过的过滤规则写回 `user_data/snapshot.ignore`（覆盖前先留一份 `.bak`）。

        ★ 为什么给界面这条写权限：过滤规则是"用户自己的东西"，让他不必去开记事本。
          写坏了也不要紧 —— `.bak` 就在旁边，而且**规则读不出来时只会退回内置那几条**。"""
        try:
            import backup as _b
            st = self._backup_store()
            g = str(group or "")
            # ★ `V-120`：给了 group 就写**这个对象自己那份**（`backups/<组>/ignore`）——
            #   你定的粒度：记住只对这个包/目录生效，不碰全局。
            f = st.group_ignore_file(g) if g else st.ignore_file
            f.parent.mkdir(parents=True, exist_ok=True)
            if f.is_file():
                try:
                    (f.with_suffix(f.suffix + ".bak")).write_text(
                        f.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                except Exception:                                       # noqa: BLE001
                    pass
            f.write_text(str(text or ""), encoding="utf-8")
            return {"ok": True, "path": str(f), "group": g,
                    "count": len(_b.parse_ignore(text))}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_preview(self, rels):
        """**存之前先试算**：按现在的过滤规则，这些来源里会存哪些、排掉哪些（不落盘）。"""
        try:
            import backup as _b
            st = self._backup_store()
            inc, exc = [], []
            for rel in (rels or []):
                try:
                    base = _resolve(str(rel))[1]
                except Exception:                                       # noqa: BLE001
                    continue
                if base.is_file():
                    (inc if not (st._skip_rel(str(rel)) or st._skip_dir_name(base.name)) else exc).append(str(rel))
                    continue
                if not base.is_dir():
                    continue
                for cur, dirs, names in os.walk(base):
                    cp = Path(cur)
                    keep = []
                    for d in sorted(dirs):
                        sr = st.rel_of(cp / d) or ""
                        if st._skip_dir_name(d, is_dir=True) or st._skip_rel(sr):
                            exc.append(sr)
                        else:
                            keep.append(d)
                    dirs[:] = keep
                    for n in sorted(names):
                        sr = st.rel_of(cp / n) or ""
                        if st._skip_dir_name(n) or st._skip_rel(sr):
                            exc.append(sr)
                        else:
                            inc.append(sr)
            return {"ok": True, "include": inc[:400], "exclude": exc[:400],
                    "n_in": len(inc), "n_out": len(exc),
                    "rules": list(_b.parse_ignore(st._read_ignore())),
                    "builtin": list(_b.DEFAULT_EXCLUDES) + ["/" + p for p in _b.PATH_EXCLUDES]}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_presets(self, rels):
        """预设过滤规则 + 按目标目录自动匹配的命中数（`V-121`）。只读。"""
        try:
            st = self._backup_store()
            srcs = []
            for rel in (rels or []):
                try:
                    srcs.append(str(_resolve(str(rel))[1]))
                except Exception:                                       # noqa: BLE001
                    pass
            return {"ok": True, "presets": st.presets(srcs)}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_group_ignore(self, group):
        """**这个对象**自己那份过滤规则（`V-120`）：文件在哪、现在生效哪些。只读。"""
        try:
            import backup as _b
            st = self._backup_store()
            g = str(group or "")
            f = st.group_ignore_file(g) if g else None
            rules = st.group_ignore(g) if g else []
            # ★ `V-127`：还要告诉界面"**上一次实际用了哪些**" —— 清单里记着 `exclude`。
            #   把内置/全局/本对象那几层减掉，剩下的就是"上次临时选的那些"。
            last = []
            try:
                ids = st.ids(g) if g else []
                if ids:
                    m = st.manifest(ids[0], g)
                    # 内置 + 全局那份 + 本对象固定 —— 这三层都不算"上次临时选的"
                    drop = (set(_b.DEFAULT_EXCLUDES) | set(_b.PATH_EXCLUDES) | set(rules)
                            | set(_b.parse_ignore(st._read_ignore())))
                    last = [x for x in list(m.get("exclude") or []) if x not in drop]
            except Exception:                                           # noqa: BLE001
                last = []
            return {"ok": True, "group": g, "path": (str(f) if f else ""),
                    "rules": rules, "last": last}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_ignore(self):
        """快照的过滤规则（`V-103`）：文件在哪、现在生效哪些、内置的是哪些。

        界面拿它画"创建快照"那一小块里的提示；命令行 `moss --snap ignore` 也用它。
        只读，不改任何东西（文件不存在时**不**在这里生成模板 —— 那是存快照时才做的事）。"""
        try:
            import backup as _b
            st = self._backup_store()
            f = st.ignore_file
            user = []
            if f.is_file():
                try:
                    user = _b.parse_ignore(f.read_text(encoding="utf-8", errors="replace"))
                except Exception:                                       # noqa: BLE001
                    user = []
            return {"ok": True, "path": str(f), "exists": f.is_file(),
                    "user": user, "count": len(user),
                    "builtin": list(_b.DEFAULT_EXCLUDES) + ["/" + p for p in _b.PATH_EXCLUDES],
                    "name": _b.IGNORE_NAME}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_fp(self, rels, dirs=None):
        """差异视图（`V-94`）的"现在这一侧"：**现读磁盘**，不信界面那份缓存。

        ★ 为什么必须现读（你 2026-09-30 反馈的第 3 条）：你在外面把 `pkg.json` 加了两个字符，
          可文件管理那份列表还是旧的（界面不会盯着磁盘看）⇒ 拿缓存的大小去比，两边"一样大"，
          于是**该高亮的没高亮**。
        ★ 返回三样：每个文件的**指纹**（大小一样时才需要它）、每个文件的**现大小**、
          每个**目录的子树字节数**（目录也得能比"谁多谁少"，不然每个目录都会被误判成"变了"）。
          目录那一侧用**和备份同一套排除规则**（`__pycache__`/`.git`/备份库自己…），
          不然磁盘比快照多出几个被排除的文件，目录就永远是"变了"。"""
        fps, sizes, dsz = {}, {}, {}
        try:
            st = self._backup_store()
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e), "fps": {}, "sizes": {}, "dirs": {}}
        for rel in (rels or []):
            try:
                p = _resolve(str(rel))[1]
                if p.is_file():
                    sizes[str(rel)] = p.stat().st_size
                    fps[str(rel)] = _bk.hash_file(p)[0]
            except Exception:                                           # noqa: BLE001
                pass
        for rel in (dirs or []):
            rel = str(rel)
            try:
                base = _resolve(rel)[1]
            except Exception:                                           # noqa: BLE001
                continue
            if not base.is_dir():
                continue
            store = str(st.root.resolve())
            total = 0
            for cur, subs, names in os.walk(base):
                cp = Path(cur)
                subs[:] = [d for d in subs
                           if not st._skip_dir_name(d)                            # noqa: SLF001
                           and not str((cp / d).resolve()).startswith(store)]
                for n in names:
                    if st._skip_dir_name(n):                                  # noqa: SLF001
                        continue
                    try:
                        f = cp / n
                        if f.is_symlink():
                            continue
                        if st._skip_rel(st.rel_of(f) or ""):                 # noqa: SLF001
                            continue
                        total += f.stat().st_size
                    except Exception:                                         # noqa: BLE001
                        pass
            dsz[rel] = total
        return {"ok": True, "fps": fps, "sizes": sizes, "dirs": dsz}

    def backup_blob(self, fp, group=""):
        """看一个对象的内容（文本给文本；二进制只给大小和头部）。"""
        try:
            st = self._backup_store()
            return st.read_blob(fp, group=(str(group or "") or None))
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_plan(self, bid, rels=None, only="all", sync=False, group=""):
        """先算一遍恢复会发生什么（不落盘）—— 界面拿它弹确认框。

        `sync=True`：**同步模式**，多算一类 `extra`（现在有、备份里没有的文件，
        恢复时会挪进回收站）。默认 False = 只补不删。
        """
        try:
            st = self._backup_store()
            return st.plan(bid, rels=rels, only=only, sync=bool(sync),
                           group=(str(group or "") or None))
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_restore(self, bid, rels=None, only="all", sync=False, group=""):
        """真恢复（覆盖前会自动留一份 `.bak`；`sync=True` 时多出来的挪进回收站）。"""
        try:
            st = self._backup_store()
            r = st.restore(bid, rels=rels, only=only, sync=bool(sync),
                           group=(str(group or "") or None))
            c = r.get("counts") or {}
            r["msg"] = "恢复 %s 个、跳过 %s 个、挪走 %s 个、出错 %s 个" % (
                c.get("restored", 0), c.get("skipped", 0), c.get("trashed", 0),
                c.get("errors", 0))
            # ★ 恢复动的是盘上的文件 ⇒ 界面那边"文件列表缓存"得跟着重问
            return r
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    # ------------------------------------------------ 导出到别的目录（`V-88`）
    # ★ 这是**唯一**一处界面能往"两个根"外面写的地方 —— 用户明确挑了/拖了一个目标
    #   文件夹，动作也明确（导出/恢复到那儿）。所以这里按"绝对路径"收，但要挡三样：
    #   不是绝对路径、指向备份库自己、指向一个文件（而不是目录）。
    def _export_target(self, target, subpath=""):
        """把界面给的那串"目标"拆成 `(存在的那个目录, 后面的子路径)`。

        ★ 为什么要拆：你可以直接在里面接着写子目录 —— 比如拖进来 `D:\\out` 之后再敲成
          `D:\\out\\2\\`（`V-88` 你要的"恢复到它的子文件夹"）。那就从右往左找到**第一个
          真实存在的目录**当目标，剩下的当子路径（不存在没关系，导出时建出来）。

        挡三样：不是绝对路径、指向备份库自己、指向一个文件（而不是目录）。
        """
        raw = str(target or "").strip().strip('"')
        if not raw:
            raise ValueError("先选一个目标文件夹（或者把文件夹拖到那一行上）")
        p = Path(raw).expanduser()
        if not p.is_absolute():
            raise ValueError("目标要是一个**绝对路径**：%s" % raw)
        try:
            p = p.resolve()
        except OSError as e:
            raise ValueError("这个路径解析不了：%s" % e)
        tail = []
        while not p.exists() and p.parent != p:
            tail.insert(0, p.name)
            p = p.parent
        store = (USER_DATA / "backups").resolve()
        if p == store or store in p.parents:
            raise ValueError("别往备份库自己里面导（换一个文件夹）")
        if p.exists() and not p.is_dir():
            raise ValueError("这个路径是个文件，不是文件夹：%s" % p)
        extra = str(subpath or "").strip().strip("/\\").replace("\\", "/")
        joined = "/".join([x for x in (["/".join(tail)] if tail else []) + ([extra] if extra else []) if x])
        return p, joined

    def backup_export_plan(self, bid, target, subpath="", rels=None, group=""):
        """导出前算一遍：会写出几个、几个会盖掉同名文件、最终落到哪儿。"""
        try:
            st = self._backup_store()
            base, sub = self._export_target(target, subpath)
            return st.export_plan(bid, base, subpath=sub, rels=rels,
                                  group=(str(group or "") or None))
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_export(self, bid, target, subpath="", rels=None, keep_bak=False, group=""):
        """把这次备份（或选中的几个文件）导出到指定文件夹。

        `target` 里可以直接带子目录（`D:\\out\\2` ⇒ 落到 `D:\\out\\2\\…`）；
        `subpath` 是另一条路（程序里拼的时候用），两边都有就接起来。
        """
        try:
            st = self._backup_store()
            base, sub = self._export_target(target, subpath)
            r = st.export(bid, base, subpath=sub, rels=rels, keep_bak=bool(keep_bak),
                          group=(str(group or "") or None))
            c = r.get("counts") or {}
            r["msg"] = "导出 %s 个到 %s%s" % (c.get("written", 0), r.get("root"),
                                            ("（%s 个出错）" % c["errors"]) if c.get("errors") else "")
            return r
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def pick_dir(self, start=""):
        """弹系统对话框让用户挑一个文件夹（导出目标用）。取消 ⇒ ok=False。"""
        try:
            import webview as _wv
            wins = list(getattr(_wv, "windows", None) or [])
            if not wins:
                return {"ok": False, "msg": "窗口还没准备好，稍一下再试"}
            kind = None
            fd = getattr(_wv, "FileDialog", None)
            if fd is not None:
                kind = getattr(fd, "FOLDER", None)
            if kind is None:
                kind = _wv.FOLDER_DIALOG()          # 老版本：那是个函数
            pick = getattr(_wv, "FOLDER_DIALOG", None)
            if not kind and callable(pick):
                kind = pick()
            start_dir = str(start or "").strip() or str(HOME)
            try:
                res = wins[0].create_file_dialog(kind, directory=start_dir)
            except TypeError:
                res = wins[0].create_file_dialog(kind, start_dir)
            if not res:
                return {"ok": False, "msg": "没有选（取消）"}
            p = res[0] if isinstance(res, (list, tuple)) else res
            return {"ok": True, "path": str(p)}
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": "挑文件夹失败：%s" % e}

    def backup_delete(self, bid, group=""):
        """删掉一次备份，然后**在这一组里**回收没人引用的对象。"""
        try:
            st = self._backup_store()
            r = st.delete(bid, group=(str(group or "") or None))
            r["msg"] = "删掉了，顺手回收了 %s 个没人引用的对象（%s）" % (
                r.get("removed", 0), _human(r.get("freed", 0)))
            return r
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_gc(self, dry_run=False, group=""):
        """标记-清除：把没人引用的对象删掉（`dry_run` 只算不删）。

        `group` 给了就只扫那一组（默认所有组各扫各的）。
        """
        try:
            st = self._backup_store()
            r = st.gc(dry_run=dry_run, group=(str(group or "") or None))
            r["msg"] = ("能回收 %s 个对象（%s）" if dry_run else "回收了 %s 个对象（%s）") % (
                r.get("removed", 0), _human(r.get("freed", 0)))
            return r
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def backup_check(self, bid=None, group=""):
        """校验：清单里提到的对象都还在吗。"""
        try:
            return self._backup_store().check(bid, group=(str(group or "") or None))
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    # ------------------------------------------------ 内嵌界面（`V-48` ✅）
    # 「界面」选项卡里那个 iframe 的另一头，就是这个包的后端进程。
    # ★ 宿主在这里**只当管子**（不懂协议）：页面里 `moss.call("bmi", {...})` 的请求由
    #   包自己的垫片包成一行 JSON，这边原样写进进程 stdin；进程回的行再原样送回页面。
    #   好处：协议归包和契约管，宿主不用为每个方法改代码。
    # ★ 只把 `{` 开头的行当消息转走 —— 宿主的横幅是 `[执行]/[目录]/[PID]` 这种
    #   **数组样子**的行，包的普通输出（print）也可能有；那些进命令行面板，不当消息。
    def embed_url(self, pid):
        """这个包的界面该从哪个地址加载（`V-55` ✅）。

        ★ 为什么不是 `file://`：**WebView2 里 iframe 一个 `file://` 页面是不导航的**
          （实测：帧建出来是空的、连 `load` 都不触发；同一个页面在普通 Edge 里却正常）。
          所以这里给一个**本地 http** 地址，页面和它的 css/js 都从这里拿。
        """
        pid = str(pid)
        rec = None
        for p in (DATA.get("packages") or []):
            if str(p.get("id")) == pid:
                rec = p
                break
        ui = (rec or {}).get("ui") or {}
        path = str(ui.get("embed") or "")
        if not path or not Path(path).is_file():
            return {"ok": False, "msg": "这个包没有可用的界面文件"}
        port, token = _embed_server()
        if not port:
            return {"ok": False, "msg": token or "本地服务起不来"}
        try:
            rel = os.path.relpath(path, str(HOME)).replace("\\", "/")
        except ValueError:                       # 不在同一个盘上（理论上到不了这）
            return {"ok": False, "msg": "界面文件不在安装根里面"}
        if rel.startswith("../"):
            return {"ok": False, "msg": "界面文件不在安装根里面"}
        return {"ok": True,
                "url": "http://127.0.0.1:%d/%s/%s" % (port, token, rel),
                "port": port}

    def embed_start(self, pid, cwd=""):
        """给这个包起一个"内嵌界面"的后端进程（`MOSS_UI_EMBED=1`）。已经起着就复用。"""
        pid = str(pid)
        with EMBED_LOCK:
            cur = EMBED.get(pid)
            if cur and cur["proc"].poll() is None:
                return {"ok": True, "pid": cur["proc"].pid, "reused": True}
        env = dict(os.environ)
        env["MOSS_UI_EMBED"] = "1"          # 约定：包看到它就"别开窗口，在 stdio 上说话"
        env["MOSS_INTERACTIVE"] = "1"
        workdir = None
        if cwd:
            try:
                if Path(str(cwd)).is_dir():
                    workdir = str(cwd)
            except OSError:
                workdir = None
        argv = HOST + [":" + pid]
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE, env=env, cwd=workdir,
                                    text=True, encoding="utf-8", errors="replace",
                                    bufsize=1, creationflags=NO_WINDOW)
        except OSError as e:
            return {"ok": False, "msg": "启动失败：%s" % e}
        with EMBED_LOCK:
            EMBED[pid] = {"proc": proc, "lines": []}
        threading.Thread(target=_pump_embed, args=(pid, proc), daemon=True).start()
        return {"ok": True, "pid": proc.pid}

    def embed_send(self, pid, text):
        """把页面发来的一行（JSON 文本）写进后端进程的 stdin。"""
        pid = str(pid)
        with EMBED_LOCK:
            rec = EMBED.get(pid)
        if not rec or rec["proc"].poll() is not None:
            return {"ok": False, "msg": "这个包的内嵌进程已经结束了"}
        try:
            rec["proc"].stdin.write(str(text).rstrip("\n") + "\n")
            rec["proc"].stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            return {"ok": False, "msg": "写不进去了：%s" % e}
        return {"ok": True}

    def embed_stop(self, pid):
        """停掉这个包的内嵌进程（界面上的「停止」）。"""
        pid = str(pid)
        with EMBED_LOCK:
            rec = EMBED.get(pid)
        if not rec:
            return {"ok": False, "msg": "这个包没在内嵌运行"}
        _kill_tree(rec["proc"].pid)          # 连子孙一起（包可能自己又起了进程）
        try:
            rec["proc"].kill()
        except Exception:                                            # noqa: BLE001
            pass
        with EMBED_LOCK:
            EMBED.pop(pid, None)
        return {"ok": True, "msg": "已停掉这个包的内嵌进程"}

    def embed_state(self, pid):
        """内嵌进程还在不在（界面切走再切回来要靠它判断要不要重起）。"""
        pid = str(pid)
        with EMBED_LOCK:
            rec = EMBED.get(pid)
        alive = bool(rec and rec["proc"].poll() is None)
        return {"ok": True, "running": alive, "pid": (rec["proc"].pid if rec else 0),
                "lines": len(rec["lines"]) if rec else 0}

    def embed_take(self, pid):
        """把后端**不是消息**的那些输出拿走（进命令行面板，别丢了）。"""
        pid = str(pid)
        with EMBED_LOCK:
            rec = EMBED.get(pid)
            if not rec:
                return {"ok": True, "text": ""}
            text = "".join(rec["lines"])
            rec["lines"] = []
        return {"ok": True, "text": text}

    # ------------------------------------------------ 设置（`V-60` ✅）
    # 那颗齿轮点开就是这里。★ 界面**不 import core**（core 编在 exe 里，磁盘上没这个
    # 目录），所以读和写都得回宿主：`moss --settings` / `moss --settings-set <JSON>`。
    # 和 `--ui-payload`、跑包走的是同一条路 —— 不另开一条通道。
    def settings(self):
        """读当前设置：分组 + 每项的当前值 / 默认值 / 说明（都是宿主给的）。"""
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令（界面得由 moss 自己拉起）"}
        r = _run_capture_split(HOST + ["--settings"])
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict) or not data.get("groups"):
            tail = ((r.get("err") or "").strip().splitlines() or [""])[-1]
            return {"ok": False, "msg": "读设置失败：退出码 %s%s"
                                        % (r.get("code"), (" —— " + tail) if tail else "")}
        # 宿主偶尔会多打一句提示（首次运行生成配置文件 / 配置写坏了），
        # 那些话在 stdout 上、不当错误，但**别扔**：拼进 msg 让用户看得见。
        extra = [l for l in (r.get("out") or "").splitlines()
                 if l.strip() and not l.strip().startswith("{")]
        return {"ok": True, "path": str(data.get("path") or ""),
                "groups": data.get("groups") or [],
                "msg": " ".join(x.strip() for x in extra)[:400]}

    def settings_save(self, pairs):
        """把改过的值写回 `user_data/config.toml`（宿主按行换值，注释一字不动）。

        回 `{"ok", "problems", "msg"}`：**problems 要原样带回去**，
        界面得把"为什么不让这么改"摊开说（每一条都带 `key`，好把那一行标红）。
        """
        return self._settings_call("--settings-set", pairs, with_notes=False)

    def settings_check(self, values):
        """**只校验、不写盘**（`V-63`）：界面每改一下就问一次，用来标红 + 决定保存能不能点。

        回 `{"ok", "problems", "notes", "live", "msg"}` —— 规则全在宿主那边
        （`core/config.py` 的 `_check_values`），界面**不自己实现一遍**：
        两处规则早晚会不一致，那种 bug 最难看出来。
        """
        return self._settings_call("--settings-check", values, with_notes=True)

    def _settings_call(self, flag, payload, with_notes):
        """`--settings-set` / `--settings-check` 共用的那一半（叫宿主 + 解析回话）。"""
        empty = {"ok": False, "problems": [], "notes": {}, "live": "", "msg": ""}
        if not HOST:
            empty["msg"] = "没拿到宿主命令（界面得由 moss 自己拉起）"
            return empty
        if not isinstance(payload, dict) or (not payload and not with_notes):
            # 空调用：`set` 是"没改什么"；`check` 不一样 —— **空值也要问宿主**
            # （宿主会把"当前生效的"补全，回一份 notes / live，面板第一屏就靠它）
            return {"ok": True, "problems": [], "notes": {}, "live": "",
                    "msg": "没改什么" if not with_notes else ""}
        # ★ `ensure_ascii=True`：这份 JSON 要走命令行（argv），全 ASCII 最省事 ——
        #   不然几个中文/全角符号就要跟 Windows 的命令行编码较劲。
        body = json.dumps(payload, ensure_ascii=True)
        r = _run_capture_split(HOST + [flag, body])
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict):
            tail = ((r.get("err") or "").strip().splitlines() or [""])[-1]
            return {"ok": False, "problems": [], "notes": {}, "live": "",
                    "msg": "%s 失败：退出码 %s%s"
                           % ("保存" if not with_notes else "检查", r.get("code"),
                              (" —— " + tail) if tail else "")}
        return {"ok": bool(data.get("ok")), "problems": data.get("problems") or [],
                "notes": data.get("notes") or {}, "live": data.get("live") or "",
                "msg": ""}

    def quit(self):
        window.destroy()
        return {"ok": True}


# ★ 别让 WebView2 走系统代理（`V-73`）：界面这一页只跟 127.0.0.1 说话（壳 + 内嵌的包界面），
#   而系统代理（`ProxyServer=127.0.0.1:7897`）会把本机请求也截走 —— 实测现场就是
#   「同一个源、前几个 js `ERR_CONNECTION_REFUSED`、后几个却加载成功」，看着像服务死了，
#   其实是代理时通时不通。用 WebView2 官方认的环境变量把它关掉（`setdefault`：外面想覆盖还能覆盖）。
os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--no-proxy-server")


def _note(text):
    """在 `drop_log()` 还没定义的时候也能留个话（`V-72` 踩过：`_page_url` 是模块加载期调的）。

    ★ 这时候只有 stderr 一定可用 —— `drop_log` 定义在文件更后面（拖放那一段）。
    """
    try:
        print("[moss] %s" % text, file=sys.stderr, flush=True)
    except Exception:                                              # noqa: BLE001
        pass


def _inline_page():
    """把界面的 css/js **就地展开**成一份自包含的 HTML，返回它的路径（`V-78`）。

    ★ 为什么非这么做：页面里十几个 `script`/`link`，每一个都要过一次本地 http。
      实测那条路会抖（同一个源、同一秒：一半请求 200，另一半连服务都没进到，
      浏览器报 `ERR_CONNECTION_REFUSED`）⇒ `Vue is not defined` / `$ is not defined`
      ⇒ 界面半死不活。展开成一份之后，**子资源请求数变成 0**，它再抖也伤不到界面。
    ★ 源码仍然是拆开的多文件（`system/ui/css|js/*`）；这一步只是运行时的组装，
      生成的那份放在 `user_data/state/_ui_inline.html`，能直接打开、也能看。
    ★ 展开不了就返回 None，调用方退回原来的做法（绝不因为这点事让界面开不了）。
    """
    try:
        page = HERE / "index.html"
        html = page.read_text(encoding="utf-8")

        def css_repl(m):
            rel = m.group(1).strip()
            try:
                return "<style>\n" + (HERE / rel).read_text(encoding="utf-8") + "\n</style>"
            except OSError:
                return m.group(0)          # 读不到就原样留着（宁可少内联一个）

        def js_repl(m):
            rel = m.group(1).strip()
            try:
                body = (HERE / rel).read_text(encoding="utf-8")
            except OSError:
                return m.group(0)
            # 内联之后脚本里出现 `</script>` 会提前结束这一块 —— 拆开写，避免踩它
            return "<script>\n" + body.replace("</script>", "<\\/script>") + "\n</script>"

        html = re.sub(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>', css_repl, html)
        html = re.sub(r'<script[^>]*src="([^"]+)"[^>]*></script>', js_repl, html)
        out = USER_DATA / "state" / "_ui_inline.html"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(html, encoding="utf-8", newline="")
        return out
    except Exception as e:                                            # noqa: BLE001
        _note("page: 展开自包含页面失败（%r），退回原做法" % (e,))
        return None


def _page_url():
    """界面这一页该从哪儿加载（`V-72`）。

    ★ 为什么不用 `file://`：pywebview 一看到本地文件 URL，就会**自己起一个内部 http 服务**
      来发页面（`__init__.py` 的 `has_local_urls`）。那个服务不在我们手里 —— 实测它就拒连过：
      devtools 里一屏 `ERR_CONNECTION_REFUSED`（`js/*.js` 全取不到）⇒ `Vue is not defined`、
      `$ is not defined` ⇒ 界面空白。改用我们自己的 `_embed_server()`：只绑 127.0.0.1、
      路径里带本次会话的随机 token、`Cache-Control: no-store`、每请求一个线程 —— 而且它
      **是我们自己启动、自己掌握**的。顺带把「界面改完刷新就见效」也保住了。
      起不来就退回 `file://`（老路子），并在日志里说一声。
    """
    try:
        page = (HERE / "index.html").resolve()
        rel = page.relative_to(HOME.resolve())
    except (OSError, ValueError):
        _note("page: 页面不在安装根下面，退回 file://")
        return str(HERE / "index.html")
    port, token = _embed_server()
    if not port:
        _note("page: 本地服务起不来（%s），退回 file://" % token)
        return str(HERE / "index.html")
    # ★ 优先用"展开成一份"的页面（`V-78`）：子资源请求 0，那条会抖的传输碰不到它
    inlined = _inline_page()
    if inlined is not None:
        try:
            rel = inlined.resolve().relative_to(HOME.resolve())
            url = "http://127.0.0.1:%d/%s/%s" % (port, token, rel.as_posix())
            _note("page: 界面从 %s 加载（自包含，子资源 0 个）" % url)
            return url
        except (OSError, ValueError):
            _note("page: 展开后的页面不在安装根下面，用原始页面")
    url = "http://127.0.0.1:%d/%s/%s" % (port, token, rel.as_posix())
    _note("page: 界面从 %s 加载" % url)
    return url


window = webview.create_window(
    "moss",
    _page_url(),
    js_api=Api(),
    width=1280,
    height=860,
    min_size=(900, 600),
    # ★ text_select 默认是 **False**，页面上的字**选不中**（拖不动、也没法 Ctrl+C）——
    #   pywebview 的 `create_window(..., text_select: bool = False)`。
    #   命令行窗口最要紧的就是"能选中、能复制"，所以这里必须打开它；
    #   页面里也给 `#out` 写了 user-select:text，另外配了「复制全部」按钮。
    text_select=True,
)

# ================================================================ 拖文件进来（`V-35` / `V-38` / `V-39`）
# 你拖着 Explorer 里的一个文件 / 文件夹丢进窗口 ⇒ 界面只列"收得下它"的包、划过谁选谁，
# 到详情页的投放框上松手就按那个包自己声明的规矩跑（`pkg.json` 的 `drop`）。
# **为什么非要有 Python 这一手**：Chromium **不把 `File.path` 交给页面**（安全设计），
# 页面那边只能拿到文件名。pywebview 走的是 WebView2 的 `AdditionalObjects`：拖进来的
# 那一瞬间宿主拿得到**真实路径**，再塞进 DOM 事件的
# `dataTransfer.files[i].pywebviewFullPath` 里。
# ★ 但这条路**只有在 Python 这边挂过 drop 监听时才会开** —— pywebview 里有个
#   `_dnd_state['num_listeners']`，是 0 的时候它把 WebView2 送来的文件直接丢掉
#   （`edgechromium.on_script_notify`）。所以：**路径由这边收，收完交给页面去跑**
#   （页面才知道现在选的是哪个包、参数框在哪儿、按钮怎么点亮）。
# ★ 挂法和 pywebview 官方那个拖放例子一致（挂在 `document` 上 + prevent_default）：
#   `V-40` 里"拖了没反应"的两个怀疑之一，就是当初挂在 `#pane-detail` 这个具体元素上
#   没挂成功（而且我把异常吞了，看不见）。
DROP_LOG = USER_DATA / "state" / "_ui_drop.log"


def drop_log(text):
    """拖放这条线的日志。**纯记事，坏了也不影响功能**（`V-40` 靠它定位）。

    为什么要它：拖放出问题时，"页面没收到拖动"和"WebView2 没给路径"在界面上长得
    一模一样（都是"啥都没发生"）。记一笔就能一次分清。只留最近这些，别让它无限长。
    """
    try:
        DROP_LOG.parent.mkdir(parents=True, exist_ok=True)
        if DROP_LOG.is_file() and DROP_LOG.stat().st_size > 256 * 1024:
            keep = DROP_LOG.read_text(encoding="utf-8", errors="replace")[-64 * 1024:]
            DROP_LOG.write_text(keep, encoding="utf-8")
        line = "%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text)
        with open(DROP_LOG, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:                                                # noqa: BLE001
        pass


def _on_files_dropped(event):
    """页面上的 drop。把真实路径交给页面，剩下的（选包 / 填参数 / 跑）归页面管。"""
    try:
        files = (event.get("dataTransfer") or {}).get("files") or []
    except Exception as e:                                           # noqa: BLE001
        drop_log("drop 事件读不出来：%r" % (e,))
        files = []
    raw = []
    for f in files:
        try:
            raw.append({"name": f.get("name"), "hasPath": bool(f.get("pywebviewFullPath")),
                        "path": f.get("pywebviewFullPath")})
        except Exception:                                            # noqa: BLE001
            pass
    drop_log("host drop: %d 个 —— %s" % (len(files), json.dumps(raw, ensure_ascii=False)))
    items = []
    for f in files:
        try:
            p = f.get("pywebviewFullPath")
        except Exception:                                            # noqa: BLE001
            p = None
        if not p:
            continue
        try:
            is_dir = os.path.isdir(p)
        except OSError:
            is_dir = False
        items.append({"path": str(p), "isDir": bool(is_dir),
                      "dir": str(p) if is_dir else os.path.dirname(str(p)),
                      "name": os.path.basename(str(p))})
    if not items:
        # ★ 这一段就是 `V-40` 的关键证据：WebView2 收到了 drop，但一个路径都没给
        drop_log("→ 一个真实路径都没拿到（WebView2 没给；文件夹尤其可能这样）")
        return
    try:
        window.evaluate_js("window.__mossDrop(%s)" % json.dumps(items, ensure_ascii=False))
        drop_log("→ 已交给页面：%s" % json.dumps(items, ensure_ascii=False))
    except Exception as e:                                           # noqa: BLE001
        drop_log("→ 交给页面时出错：%r" % (e,))


def _arm_file_drop():
    """页面加载完之后，挂上 drop 监听（`webview.start` 里跑，在别的线程）。

    ★ 以前这里整段包在 `try/except: pass` 里 —— `V-40` 那种"拖了没反应"就完全查不出来
      （异常被自己吞了，而 pywebview 那边"注册过监听"就会把路径收走，结果是收走了没人拿）。
      现在**出错就记日志**，连 `import` 都放进 try 里。
    """
    try:
        from webview.dom import DOMEventHandler                 # noqa: PLC0415
        window.events.loaded.wait(20)
        window.dom.document.events.drop += DOMEventHandler(
            _on_files_dropped, prevent_default=True, stop_propagation=True)
        drop_log("armed: 监听挂在 document 上（num_listeners 应该 > 0 了）")
    except Exception as e:                                           # noqa: BLE001
        drop_log("armed 失败（拖放会完全没反应）：%r" % (e,))


if __name__ == "__main__":
    # `--debug`（`V-70`）：开发/排查模式 —— pywebview 会**自动打开 devtools**，
    # 随时按 F12 / 右键「检查」看控制台；页面里的 JS 报错也照样会写到状态栏（红字）。
    # 用法：`moss ui --debug`（宿主会把参数原样转给这个脚本，改这里**不用重打包 exe**）。
    DEBUG = any(a in ("--debug", "--dev", "-d") for a in sys.argv[1:])
    if DEBUG:
        print("[moss] 开发模式：devtools 已开（F12 / 右键「检查」）。"
              "页面里的报错也会写到界面右下角状态栏。", flush=True)
    webview.start(_arm_file_drop, debug=DEBUG)
