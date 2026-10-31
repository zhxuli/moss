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
import hashlib
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
import urllib.parse
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

import win_geom                                                  # noqa: E402  (V-223：窗口几何)
import icons                                                     # noqa: E402  (V-267：图标表)

NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW
DETACHED = 0x00000008           # DETACHED_PROCESS
DEVNULL = subprocess.DEVNULL


# ================================================================ WebView2 运行时预检（`V-390`）
# ★ 为什么这件事在**界面进程**里做，而不是宿主 `core/ui.py` 里：
#   宿主是 nuitka 编出来的 exe，手边只有 ctypes / MessageBoxW；而"下载 + 进度条 + 重试"要
#   图形工具包，tkinter 恰好只在**自带运行时**里是齐的（`system/runtimes/python/3.12`，
#   tcl/tk/tk86t.dll 都在）。于是分工是：
#       core/ui.py  --子进程 `--check-webview2`-->  这里      （判定逻辑只有这一份）
#       system/ui/main.py  缺就弹框：下载 → 静默安装 → 复查 → 继续开界面
#
# ★ 症状（`V-390`，2026-10-24 远程装机踩到）：客户机没装 WebView2 时，pywebview 6 会
#   **一声不响**退回 MSHTML（IE 内核）—— 窗口照样开，但页面只剩静态文字：图标一个都没有、
#   插件列表空白、状态栏一行「“pywebview”未定义」。用户只会以为"程序坏了"。
#   判据来自 `webview/platforms/winforms.py:_is_chromium()`：.NET Framework ≥ 4.6.2
#   **且** 注册表里有 Edge WebView2 运行时，两条都满足才用 EdgeChromium。
# ⚠️ 装 **Edge 浏览器** 不算（那条 GUID 是 `{56EB18F8-…}`，pywebview 不看）；Chrome 更不算
#   —— pywebview 在 Windows 只有 WebView2 / MSHTML(IE) / CEF 三个后端，没有"外部浏览器"。
_WEBVIEW2_PAGE = "https://developer.microsoft.com/microsoft-edge/webview2/"
#: 独立安装包（MicrosoftEdgeWebView2RuntimeInstallerX64.exe，约 205 MB）—— 有真字节进度
_WEBVIEW2_X64 = "https://go.microsoft.com/fwlink/p/?LinkId=2124701"
#: 联机引导器（MicrosoftEdgeWebview2Setup.exe，约 2 MB）—— 独立包下不动时兜底
_WEBVIEW2_BOOT = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
#: .NET Framework 4.8 下载页（WebView2 要 4.6.2+；太老的话装了运行时也白装）
_NETFX_PAGE = "https://dotnet.microsoft.com/download/dotnet-framework/net48"

#: pywebview 认这四个 EdgeUpdate 客户端（运行时 / Beta / Dev / Canary）
_WV2_GUIDS = (
    "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",      # Microsoft Edge WebView2 Runtime
    "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",      # Beta
    "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",      # Dev
    "{65C35B14-6C1D-4122-AC46-7148CC9D6497}",      # Canary
)
#: 86.0.622.0 以下 pywebview 不认（`_is_new_version('86.0.622.0', build)`）
_WV2_MIN = (86, 0, 622, 0)
#: .NET Framework 4.6.2 的 Release 号（pywebview 里那个 394802 就是它）
_NETFX_462 = 394802


def _ver4(text):
    """'155.0.4283.62' → (155, 0, 4283, 62)，固定四段，能直接比大小。"""
    out = []
    for part in str(text).split("."):
        if not part.isdigit():
            break
        out.append(int(part))
    out = (out + [0, 0, 0, 0])[:4]
    return tuple(out)


def _netfx_release():
    """`.NET Framework` 的 Release 号（没有就 0）。>= 394802 = 4.6.2+。"""
    try:
        import winreg                                               # noqa: PLC0415
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as k:
            return int(winreg.QueryValueEx(k, "Release")[0] or 0)
    except Exception:                                               # noqa: BLE001
        return 0


def _wv2_builds():
    """登记在案的 WebView2 运行时版本号（HKLM 的 WOW6432Node 那份 + HKCU 那份）。

    两份都要看：管理员装上的是 HKLM（WOW6432Node），**不提权装**的是 HKCU
    （`%LOCALAPPDATA%\\Microsoft\\EdgeWebView`）—— 后者 pywebview 也认，所以没管理员权限
    的机器照样能救。
    """
    try:
        import winreg                                               # noqa: PLC0415
    except Exception:                                               # noqa: BLE001
        return []
    found = []
    for root, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node"),
                      (winreg.HKEY_CURRENT_USER, r"SOFTWARE")):
        for guid in _WV2_GUIDS:
            try:
                key = sub + r"\Microsoft\EdgeUpdate\Clients" + "\\" + guid
                with winreg.OpenKey(root, key) as k:
                    found.append(str(winreg.QueryValueEx(k, "pv")[0]))
            except Exception:                                       # noqa: BLE001
                pass
    return found


def webview2_status():
    """(能不能用 Chromium 内核, 一句人话)。判据**照抄** pywebview 的 `winforms._is_chromium()`：

        .NET Framework 的 Release >= 394802（4.6.2+）
        **且** EdgeUpdate\\Clients 里有 WebView2（或 Beta/Dev/Canary）的 pv >= 86.0.622.0

    ★ 为什么不直接 `import webview.platforms.winforms` 看 `wf.renderer`：那次 import 会把
      CLR 拉起来，并**当场**把 renderer 定死；而我们装完还得让 pywebview 自己重新判一次
      （装好就能用，不用重启 moss）。所以这里只读注册表，判据与它保持一致。
    """
    rel = _netfx_release()
    builds = _wv2_builds()
    best = max((_ver4(b) for b in builds), default=(0, 0, 0, 0))
    if rel < _NETFX_462:
        return False, ("缺 .NET Framework 4.6.2+（本机 Release=%s）" % (rel or "没读到"))
    if best < _WV2_MIN:
        if builds:
            return False, "WebView2 运行时太旧（%s）" % builds[0]
        return False, "缺 Microsoft Edge WebView2 运行时（装 Edge 浏览器不算）"
    return True, "WebView2 %s（Chromium 内核）" % ".".join(str(x) for x in best)


def _download(url, dest, on_progress=None, cancel=None, timeout=60):
    """流式下载到 `dest`，每 256 KB 回调一次 `on_progress(已下字节, 总字节)`（总长度未知给 0）。

    ★ 先落 `.part` 再改名：中途断网/被杀不能留下一个"看着像装好了"的半个安装包。
    ★ `cancel` 是个 dict（`{"cancel": bool}`）而不是 Event —— 这里只需要一个能被外部
      随时翻的旗子，tkinter 那边改它不需要锁。
    """
    import urllib.request                                           # noqa: PLC0415
    part = str(dest) + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": "moss-setup"})
    with urllib.request.urlopen(req, timeout=timeout) as r, open(part, "wb") as f:
        try:
            total = int(r.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            total = 0
        done = 0
        while True:
            if cancel is not None and cancel.get("cancel"):
                raise RuntimeError("已取消")
            chunk = r.read(262144)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    os.replace(part, str(dest))
    size = dest.stat().st_size
    if size < 100 * 1024:
        raise RuntimeError("下载回来只有 %d 字节，像是被网络/代理拦了" % size)
    return size


def _run_installer(exe):
    """静默安装 WebView2 运行时。返回"有没有发起成功"（装没装成由调用方复查注册表判定）。

    ★ **不提权**跑就等于"装到当前用户"（`%LOCALAPPDATA%\\Microsoft\\EdgeWebView`），
      pywebview 也查 HKCU 那份 —— 所以客户机没有管理员权限也能救。
    ★ 提权那次是**兜底**：先按当前权限试，被拒/失败才 `ShellExecuteW("runas")`（会弹 UAC）。
      `ShellExecuteW` 是异步的，这里只负责发起，结果照样靠后面的复查。
    """
    try:
        p = subprocess.run([str(exe), "/silent", "/install"], timeout=900,
                           creationflags=NO_WINDOW)
        if p.returncode in (0, 3010):        # 3010 = 装好了但要重启；这里用不着重启
            return True
    except Exception:                                               # noqa: BLE001
        pass
    try:
        import ctypes                                               # noqa: PLC0415
        r = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(exe), "/silent /install", None, 1)
        return int(r) > 32
    except Exception:                                               # noqa: BLE001
        return False


def _webview2_dialog(detail):
    """「缺 WebView2」对话框：下载（带进度）→ 静默安装 → 复查。

    返回 True = 现在能用了（装好了），调用方接着开界面；False = 用户放弃/装失败。

    ★ 线程规矩：下载/安装跑在**工作线程**里，**一个字都不碰 tkinter**（只往 queue 里放），
      由界面线程 `after` 泵出来。跨线程直接改控件在这套 tk 上会随机崩。
    """
    try:
        import queue                                                # noqa: PLC0415
        import tempfile                                             # noqa: PLC0415
        import tkinter as tk                                        # noqa: PLC0415
        import webbrowser                                           # noqa: PLC0415
        from tkinter import ttk                                     # noqa: PLC0415
    except Exception as e:                                          # noqa: BLE001
        # 连 tkinter 都起不来（理论上不会）：退回系统弹窗 —— 信息少，但**绝不静默**。
        try:
            import ctypes                                           # noqa: PLC0415
            ctypes.windll.user32.MessageBoxW(
                None,
                "moss 的界面需要「Microsoft Edge WebView2 运行时」，这台电脑没有：\n"
                "    %s\n\n请自己装一个（是运行时，不是 Edge 浏览器）：\n%s"
                % (detail, _WEBVIEW2_PAGE),
                "moss", 0x10)
        except Exception:                                           # noqa: BLE001
            print("[moss] 缺 WebView2 运行时（%s）：%s" % (detail, _WEBVIEW2_PAGE),
                  file=sys.stderr, flush=True)
        print("[moss] 对话框起不来：%r" % (e,), file=sys.stderr, flush=True)
        return False

    ACCENT, FG, FG2, DIM, BG, FIELD = ("#0071e3", "#1d1d1f", "#515154",
                                       "#86868b", "#ffffff", "#f5f5f7")
    FONT = ("Microsoft YaHei UI", 9)
    FONT_H = ("Microsoft YaHei UI", 12, "bold")

    res = {"ok": False, "cancel": False}
    q = queue.Queue()

    root = tk.Tk()
    root.withdraw()                     # 布局算完再显示，免得先闪一下毛坯窗
    root.title("moss · 需要 WebView2 运行时")
    root.configure(bg=BG)
    root.resizable(False, False)
    w, h = 566, 344
    root.geometry("%dx%d+%d+%d" % (w, h, max(0, (root.winfo_screenwidth() - w) // 2),
                                   max(0, (root.winfo_screenheight() - h) // 3)))
    try:
        root.iconbitmap(default=str(HERE.parent / "icon" / "moss.ico"))
    except Exception:                                               # noqa: BLE001
        pass

    box = tk.Frame(root, bg=BG, padx=22, pady=16)
    box.pack(fill="both", expand=True)

    tk.Label(box, text="moss 需要「Microsoft Edge WebView2 运行时」", bg=BG, fg=FG,
             font=FONT_H, anchor="w").pack(fill="x")
    body = ("这台电脑上没装它，界面就只能退回 IE 内核渲染 —— 表现是：窗口能开，但只有几行"
            "静态文字，插件列表是空的，按钮点不动。\n\n"
            "点下面的按钮，moss 会自己下载并安装（约 205 MB）；装完自动继续，不用重启 moss。")
    tk.Label(box, text=body, bg=BG, fg=FG2, font=FONT, justify="left", anchor="w",
             wraplength=520).pack(fill="x", pady=(8, 12))

    # ★ 下半截全部 `side="bottom"` 自下而上堆：按钮 → 进度文字 → 进度条 → 状态条。
    #   这样"富余的空白"只会落在正文和状态条之间，不会在进度条下面挖一个洞（第一版就是那样，
    #   看着像少画了一块）。窗口高度也就能压到 340。
    btns = tk.Frame(box, bg=BG)
    btns.pack(fill="x", side="bottom")

    foot = tk.Label(box, text="", bg=BG, fg=DIM, font=FONT, anchor="w", wraplength=520)
    foot.pack(fill="x", side="bottom", pady=(6, 10))

    style = ttk.Style(root)
    try:
        style.theme_use("clam")             # vista 主题的进度条是系统绿，改不动颜色
    except Exception:                                               # noqa: BLE001
        pass
    style.configure("Moss.Horizontal.TProgressbar", troughcolor="#ececf0",
                    background=ACCENT, bordercolor="#ececf0", lightcolor=ACCENT,
                    darkcolor=ACCENT, thickness=8)
    prog = ttk.Progressbar(box, style="Moss.Horizontal.TProgressbar", orient="horizontal",
                           mode="determinate", maximum=100, value=0)
    prog.pack(fill="x", side="bottom")

    # 状态条：检测结果 / 装完的结果都写在这儿（灰底，和界面里那些提示条一个长相）
    bar = tk.Frame(box, bg=FIELD, padx=12, pady=8)
    bar.pack(fill="x", side="bottom", pady=(14, 0))
    said = tk.Label(bar, text="检测结果：" + detail, bg=FIELD, fg=FG2, font=FONT,
                    anchor="w", justify="left", wraplength=492)
    said.pack(fill="x")

    def mk(text, cmd, primary=False):
        b = tk.Button(btns, text=text, command=cmd, font=FONT, relief="flat", bd=0,
                      highlightthickness=0, padx=14, pady=6, cursor="hand2")
        if primary:
            b.configure(bg=ACCENT, fg="#ffffff", disabledforeground="#d6e8ff",
                        activebackground="#0063c8", activeforeground="#ffffff")
        else:
            b.configure(bg=FIELD, fg=FG2, activebackground="#ececf0", activeforeground=FG)
        return b

    def close(ok):
        res["ok"] = bool(ok)
        res["cancel"] = True
        try:
            root.destroy()
        except Exception:                                           # noqa: BLE001
            pass

    def start():
        b_run.configure(state="disabled", text="正在下载…")
        b_page.configure(state="disabled")
        foot.configure(fg=DIM, text="准备下载…")
        threading.Thread(target=work, daemon=True).start()

    def work():
        """工作线程：下载 → 安装 → 复查。只往 queue 里放话，不碰任何控件。"""
        tmp = Path(tempfile.gettempdir()) / "moss-webview2"
        try:
            tmp.mkdir(parents=True, exist_ok=True)
        except OSError as e:                                        # noqa: BLE001
            q.put(("fail", "建不了临时目录：%s" % e))
            return
        exe = tmp / "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
        last = None
        okdl = False
        # 独立包优先（进度是真的）；它下不动（代理/墙）就退回 2 MB 的联机引导器，
        # 让安装器自己去下主体 —— 那条路只能显示"正在安装"，但至少有救。
        for url, name in ((_WEBVIEW2_X64, "独立安装包（约 205 MB）"),
                          (_WEBVIEW2_BOOT, "联机引导器（约 2 MB）")):
            if res["cancel"]:
                return
            q.put(("say", "正在下载%s…" % name))
            try:
                _download(url, exe, lambda d, t: q.put(("pct", d, t)), res)
                okdl = True
                break
            except Exception as e:                                  # noqa: BLE001
                last = e
        if not okdl:
            q.put(("fail", "下载失败：%s\n可以直接点「打开下载页面」手动装。" % last))
            return
        if res["cancel"]:
            return
        q.put(("say", "下载好了，正在安装（1-3 分钟；中途可能弹 UAC 授权窗）…"))
        q.put(("pulse",))
        _run_installer(exe)
        q.put(("say", "正在确认安装结果…"))
        for _ in range(120):                # 注册表可能滞后，最多等 60 秒
            if res["cancel"]:
                return
            if webview2_status()[0]:
                q.put(("done", "装好了，正在打开界面…"))
                return
            time.sleep(0.5)
        q.put(("fail", "装完没检测到 WebView2 —— 多半是 UAC 被拒或被安全软件拦了。\n"
                       "点「打开下载页面」手动装一次，然后重开 moss。"))

    def pump():
        try:
            while True:
                msg = q.get_nowait()
                kind = msg[0]
                if kind == "say":
                    prog.stop()
                    prog.configure(mode="determinate")
                    foot.configure(fg=DIM, text=msg[1])
                elif kind == "pct":
                    done, total = msg[1], msg[2]
                    if total > 0:
                        prog.configure(mode="determinate",
                                       value=min(100.0, done * 100.0 / total))
                        foot.configure(text="下载中 %.1f / %.1f MB（%d%%）"
                                       % (done / 1048576.0, total / 1048576.0,
                                          done * 100 // total))
                    else:
                        foot.configure(text="下载中 %.1f MB…" % (done / 1048576.0))
                elif kind == "pulse":
                    b_run.configure(text="正在安装…")
                    prog.configure(mode="indeterminate")
                    prog.start(14)
                elif kind == "done":
                    prog.stop()
                    prog.configure(mode="determinate", value=100)
                    foot.configure(fg="#0a7a2f", text=msg[1])
                    said.configure(fg="#0a7a2f",
                                   text="✔ " + (webview2_status()[1] or "已装好"))
                    root.after(700, lambda: close(True))
                    return
                elif kind == "fail":
                    prog.stop()
                    prog.configure(mode="determinate", value=0)
                    foot.configure(fg="#c0392b", text=msg[1])
                    b_run.configure(state="normal", text="重试")
                    b_page.configure(state="normal")
                    b_quit.configure(text="退出")
        except queue.Empty:
            pass
        root.after(120, pump)

    b_run = mk("下载并安装", start, primary=True)
    b_page = mk("打开下载页面", lambda: webbrowser.open(_WEBVIEW2_PAGE))
    b_quit = mk("先不装，退出", lambda: close(False))
    b_quit.pack(side="right")
    b_run.pack(side="right", padx=(0, 8))
    b_page.pack(side="right", padx=(0, 8))
    if _netfx_release() < _NETFX_462:
        # .NET 太老：单装 WebView2 也没用，直接把那条路摆在旁边
        mk("先装 .NET 4.8", lambda: webbrowser.open(_NETFX_PAGE)).pack(side="left")

    root.protocol("WM_DELETE_WINDOW", lambda: close(False))
    try:
        root.update_idletasks()
        root.deiconify()
        root.attributes("-topmost", True)      # 它是"拦路"的：别被别的窗口压在后面
        root.after(400, lambda: root.attributes("-topmost", False))
    except Exception:                                               # noqa: BLE001
        root.deiconify()
    root.after(120, pump)
    root.mainloop()
    return res["ok"]


def _webview2_preflight():
    """开窗之前先确认渲染内核能用（`V-390`）。三种走法：

    · `--check-webview2`：只吐**一行 JSON** 就退出 —— 给宿主 `--selfcheck` 用，
      判定逻辑只此一份（宿主自己不读注册表，免得以后 pywebview 换判据时漏改一处）。
    · `MOSS_SKIP_WEBVIEW2_CHECK=1`：整段跳过（无头探针 / 没有图形环境时用）。
    · 其余：能用就什么都不做；不能用就弹框（下载+进度+安装），装好了继续，放弃就退出。
    """
    if "--check-webview2" in sys.argv[1:]:
        ok, detail = webview2_status()
        # `ensure_ascii=True`：这一行要穿过命令行/管道，纯 ASCII 最省事（宿主那边 json 解回来）
        print(json.dumps({"ok": ok, "detail": detail}, ensure_ascii=True), flush=True)
        raise SystemExit(0)
    if os.environ.get("MOSS_SKIP_WEBVIEW2_CHECK"):
        return
    ok, detail = webview2_status()
    if ok:
        return
    print("[moss] 渲染内核：%s —— 弹框让用户装 WebView2" % detail,
          file=sys.stderr, flush=True)
    if not _webview2_dialog(detail):
        raise SystemExit("[moss] 没有 WebView2 运行时，界面开不了"
                         "（退回 IE 内核只会得到一页空白）。装一个再来：%s" % _WEBVIEW2_PAGE)


_webview2_preflight()


def _load_data():
    p = os.environ.get("MOSS_UI_DATA")
    if not p:
        raise SystemExit("缺少 MOSS_UI_DATA —— 这个界面只能由宿主拉起（moss ui / 双击 moss.exe）")
    return json.loads(Path(p).read_text(encoding="utf-8"))


DATA = _load_data()
HOST = [str(x) for x in (DATA.get("host_cmd") or [])]



def _shell_line(argv):
    """把 argv 拼成一条**能在 cmd 里直接敲**的命令行（`V-352`，给终端用）。

    ★ 和 `subprocess.list2cmdline` 的区别：那个是给 `CreateProcess` 的 CRT 用的，
      只在"有空格"时加引号；而**在 cmd 里**，`&` `|` `^` `>` `<` 就算没空格也是操作符，
      不括起来会被 cmd 拆成两条命令。所以这里带上它们一起判。
    ★ 参数里真有双引号时用 cmd 自己那套写法（`""`）—— 它同时也是 CRT 认的写法。
    """
    out = []
    for a in argv:
        a = str(a)
        if a == "" or any(c in a for c in ' \t&|^<>()'):
            out.append('"' + a.replace('"', '""') + '"')
        else:
            out.append(a)
    return " ".join(out)


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


def _ai_arg(v):
    """把界面递来的一个字段值变成 `k=v` 里那个 v（`V-138` / `V-139`）。

    ★ 列表（现在只有 `model` 会多个）要拼成 `a,b`：宿主那边按逗号拆回列表。
    ★ 开关必须写成 `true`/`false`（`V-138` 留下的规矩）—— 现在 AI 那几个字段里没有开关了，
      但这条留着：以后再加 bool 字段时不会再踩一次"存成整数"。
    """
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(str(x).strip() for x in v if str(x).strip())
    return str(v)


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
      而配置文件里**有多余的段**（或不存在 / 写坏了）时，它会往 **stdout** 打几句
      「[配置] …」。那几行和我们这份 JSON 混在一起就是
      `Extra data: line 1 column N` —— 界面只好退回旧快照，看起来就是"界面不刷新，
      还不知道为什么"（`V-31` 那次就是这一类）。
    ★ `V-362`：这里曾经只兜"**单行** JSON"那一档（从后往前找一行以 `{` 开头的）——
      而 `--ai-config` / `--settings` 这类**是多行缩进的 JSON**（`indent=2`）⇒
      只要 stdout 前面多一句话（实测：配置文件里多一个 `[cleanup]` 段，
      宿主每跑一次都打 6 行警告），整段解不了、逐行也解不了 ⇒ 界面报
      **「读 AI 参数失败」**。现在改成跟 `_first_json` 一条路：**从每个 `{` 开始试
      `raw_decode`**，前置噪音和多行 JSON 一起吃得下。
    """
    s = (out or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except ValueError:
        pass
    got = _first_json(s)
    return got if isinstance(got, dict) else None


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
#: 被「停止」**主动杀掉**的内嵌后端（`V-297`）：proc 对象集合。
#: ★ 界面点「停止」时，`embed_stop` 先往这里记一笔；`_pump_embed` 收尾看到它，
#:   就**不再**发 `__mossEmbedGone`（那会再弹一句"内嵌进程结束了（退出码 1）"）——
#:   强杀必然是非 0，界面那边已经弹过「已停掉…」了，两个提示是重复的。
EMBED_STOPPED = set()

#: 这个界面服务**不许发**的路径（相对安装根，`V-170`）。
#: ★ 为什么：服务的根是整个安装根，而界面真正需要的只有 `system/ui/**` 和自包含页面 ——
#:   配置（明文 key）、快照库、命令历史、各包运行期数据没理由经一个 HTTP 端口发出去。
#: 敏感路径一律不发（`V-170`）。★ `V-277`：界面那一页**不在这个名单里** —— 它现在只在内存里
#: （虚拟地址 `__ui_live.html`，由 `_EmbedHandler._serve_live()` 直接答），所以原来那条
#: "给 `user_data/state/_ui_inline.html` 开后门"的例外（`_EMBED_ALLOW`）**已经删掉了**。
_EMBED_DENY = ("user_data/config.toml", "user_data/backups/", "user_data/history/",
               "user_data/state/", "user_data/trash/", "user_data/snapshot.ignore",
               "user_data/runners.json", ".git/", "core/", "venv/")

#: 界面窗口的 favicon（`V-181`）：**一份图标，两个消费者** —— 构建时嵌进 exe 的
#: `--windows-icon-from-ico`（`tools/build.py` 里的 `ICON_REL`）和这里发出去的
#: `/favicon.ico`，指的是**同一个文件**。
#: ★ 为什么单独开这条路：浏览器/WebView 一进页面就会自己去要 `/favicon.ico`，
#:   而它**不知道 token**（token 在页面地址里，favicon 是浏览器自己拼的根路径），
#:   于是以前一律 403，控制台里就留一行"没有 favicon.ico"的抱怨 —— 不是错误，
#:   但看着像坏了。图标本身不是秘密（发行物里就有），放行这一个路径不损 `V-170`。
#:   第二个名字是搬家前的老位置，纯兜底：老安装根里那份也认。
_FAVICON_RELS = ("system/icon/moss.ico", "icon.ico")


def _favicon_file():
    """按新旧顺序找那份图标；一个都没有就返回 None。"""
    for rel in _FAVICON_RELS:
        f = HOME / rel
        if f.is_file():
            return f
    return None

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


def _procs_info(pids, cmdlines=None):
    """这些 pid 的"人话身份"：pid / 起于 / 命令行（截断）—— 给界面显示用。

    ★ 为什么要有它（`V-216`）：用户报「明明提示跑完了，界面上还显示在运行」。查下来是**一个
      孤儿进程**（更早那次启动留下的 `python bootstrap.py …\\pkgs\\path\\main.py`，父进程早没了、
      它自己在 stdin 上等着）—— `_pkg_pids` 认得出它（命令行里写着包目录），于是包**永远**是
      "运行中"。只给一个 `pids: 1` 谁也看不出这是啥；把 pid + 起始时间 + 命令行摆出来，
      一眼就能看出"这是昨天那个孤儿"，而不是"我刚跑的那次还没结束"。
    """
    out = []
    if cmdlines is None:
        cmdlines = _pids_by_cmdline()
    try:
        import psutil
    except ImportError:
        psutil = None
    for pid in sorted(pids)[:6]:
        pid = int(pid)
        item = {"pid": pid, "started": "", "cmd": (cmdlines.get(pid) or "")[:200]}
        if psutil is not None:
            try:
                pr = psutil.Process(pid)
                item["started"] = time.strftime("%m-%d %H:%M:%S",
                                                time.localtime(pr.create_time()))
                # 显示用**原始大小写**（`cmdlines` 那份是小写 + 正斜杠，给人看太别扭）
                cl = pr.cmdline() or []
                if cl:
                    item["cmd"] = " ".join(cl)[:200]
            except Exception:                                        # noqa: BLE001
                pass
        out.append(item)
    return out


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


def _pkg_dirs(pid):
    """这个包对应的**真实目录**（绝对路径，可能不止一个）。

    `V-220` 用：判"这个有窗口的进程是不是**包自己的程序**"（包自己的 exe 一定在它的目录里）。
    """
    out = []
    for p in (DATA.get("packages") or []):
        if str(p.get("id")) != str(pid):
            continue
        d = p.get("dir")
        if d and str(d) not in out:
            out.append(str(d))
    return out


def _exe_under(pid, dirs):
    """这个进程的可执行文件是不是就在这些目录里（`V-220`）。

    ★ 为什么用**可执行文件位置**当判据：`MOSS_PKG_ID` 会被包拉起的子进程继承（"往下漏"），
      只认环境变量就会把 `explorer.exe`（被 .bat 的 `start` 拉起来的）、用户的浏览器、
      输入法工具这些都算成调用它们的那个包在跑 —— 后果是"停止"把桌面/浏览器杀了。
      exe 路径就写在进程自己身上（`psutil.Process(pid).exe()`），骗不了。
    """
    if not dirs:
        return False
    try:
        import psutil
        exe = str(psutil.Process(int(pid)).exe() or "")
    except Exception:                                                # noqa: BLE001
        return False
    if not exe:
        return False
    exe = exe.replace("\\", "/").lower()
    for d in dirs:
        base = str(d).replace("\\", "/").lower().rstrip("/")
        if base and exe.startswith(base + "/"):
            return True
    return False


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
    # ★ `V-220`：光看"环境里写着这个包 id"会**认错人** —— `MOSS_PKG_ID` 是注入到进程环境里的，
    #   包拉起的**任何**子进程都会继承它（`P-18` 记的就是这个"往下漏"）。实测两起真事故：
    #     · `suoluetu`（图标缓存那个包）的 .bat 里 `start "" explorer.exe` ⇒ **explorer.exe 带着
    #       `MOSS_PKG_ID=suoluetu`**，而它**有窗口** ⇒ 被算成"suoluetu 在跑"：
    #       ① 重启 moss 也照样显示「停止」（那是**进程**层面的判断，重启没用）；
    #       ② 点「停止」⇒ `pkg_stop` 把 explorer.exe 一起杀了 —— **桌面和任务栏当场没了**。
    #     · DSH 那条线上，用户浏览器（Maxthon）、node、pwsh、输入法工具全带着 `MOSS_PKG_ID=dsh`
    #       ⇒ `dsh` 永远"在跑"，"停止"下去就是把浏览器和 agent 全杀了。
    #   所以这一条**加一道硬条件**：这个有窗口的进程，**可执行文件得真在包目录里** ——
    #   那才是"包自己的界面"；explorer.exe / Maxthon.exe 在 C:\Windows 或别处，一律不算。
    pids |= {pid for pid, k in owner_pkg.items()
             if k == pkg and _exe_under(pid, _pkg_dirs(pkg))}
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

# 命令行里那个**常驻 DOS 终端**（`V-348`）：会话本体在 `system/ui/term.py`（同目录兄弟模块）。
# ★ 惰性 import：终端这一块（ctypes / ConPTY / 管道）万一加载不了，只让「终端」这一个功能
#   如实报错，**绝不许把整个界面拖下水** —— 出错的立场是"要看得见"，不是"连坐"（`V-76`）。
_TERM = {"mod": None, "err": ""}


def _term_mod():
    if _TERM["mod"] is None and not _TERM["err"]:
        try:
            import term as _t
        except Exception as e:                                         # noqa: BLE001
            _TERM["err"] = "终端模块加载不了：%s" % e
        else:
            _TERM["mod"] = _t
    return _TERM["mod"]

# AI 工作台（`V-230`~`V-233`）那一次任务的状态：一个后台线程 + 一份能被轮询的状态。
# 一次只有一个任务（同一个 tab 上并行跑两个 agent 只会互相踩文件）。
AI = {"thread": None, "state": None, "task": "", "stop": False, "t0": 0.0}
AI_LOCK = threading.Lock()

#: ★ `V-325`：**"这条权限请求被拒了"** 的登记（`路径 → 拒绝那一刻`）。
#:   为什么不能靠"那一行被删了"来判拒绝：第二次请求（要写）时那一行本来就存在（只读），
#:   删了会把用户之前批过的**读**一起收掉。所以拒绝只在宿主这边记一笔，闸拿它当场判 `denied`，
#:   清单本身**一个字都不动**。闸开工时比时间戳（只认这一趟里的拒绝），收工后自己清掉。
_PERM_DENY = {}


def _perm_key(pth):
    """登记/查拒绝用的键：路径统一成小写 + 去掉尾部分隔符（`Path` 那套归一化）。"""
    try:
        return str(Path(str(pth or "")).resolve()).rstrip("\\/").lower()
    except Exception:                                                # noqa: BLE001
        return str(pth or "").rstrip("\\/").lower()

#: AI 参数的缓存（`V-234`）：界面**没有** `MOSS_AI_*`，得回头问宿主
#: （`moss --ai-config-reveal`）；那是起一个进程，不能每 700ms 轮询就问一次。
_AI_CFG = {"t0": 0.0, "got": None}


def _first_json(text):
    """从一段可能有横幅/告警的文字里抠出**第一份** JSON 对象（`V-234`）。

    为什么不用 `json.loads(整段)`：宿主会把 `[执行] / [目录]` 这类横幅和告警混在输出里
    （`--ui-payload` 那条路踩过同样的坑，见 `_run_capture_split`）。这里从每个 `{` 开始试。
    """
    s = str(text or "")
    i = s.find("{")
    while i >= 0:
        try:
            obj, _end = json.JSONDecoder().raw_decode(s[i:])
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        i = s.find("{", i + 1)
    return None


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

    def _serve_favicon(self):
        """`/favicon.ico` 特例（`V-181`）：**不带 token 也发**。已处理返回 True。"""
        p = str(self.path or "").split("?", 1)[0].split("#", 1)[0]
        if p not in ("/favicon.ico", "/favicon.png"):
            return False
        try:
            f = _favicon_file()
            data = f.read_bytes() if f else b""
        except OSError:
            data = b""
        if not data:
            self.send_error(404, "no favicon")
            return True
        self.send_response(200)
        self.send_header("Content-Type", "image/x-icon")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)
        return True

    def do_GET(self):                                                    # noqa: N802
        if self._serve_favicon():
            return
        if not self._token_ok():
            self.send_error(403, "bad token")
            return
        super().do_GET()

    def do_HEAD(self):                                                   # noqa: N802
        if self._serve_favicon():
            return
        if not self._token_ok():
            self.send_error(403, "bad token")
            return
        super().do_HEAD()

    def _rel_of(self, path):
        """把请求路径变成"相对安装根的 posix 路径"（先剥掉 token 那一段）。"""
        p = str(path or "").split("?", 1)[0].split("#", 1)[0]
        tk = _EMBED_SRV["token"]
        if tk and p.startswith("/" + tk + "/"):
            p = p[len(tk) + 1:]
        return p.lstrip("/")

    def _serve_live(self):
        """`V-277`：界面那一页现在在**内存**里 —— 虚拟地址要它就直接答，不碰磁盘。

        返回 True = 这个请求已经处理完了（调用方别再走静态文件那条路）。
        """
        if self._rel_of(self.path) != LIVE_NAME:
            return False
        html = _LIVE.get("html") or ""
        if not html:
            self.send_error(404, "no live page")
            return True
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()                      # `end_headers` 会给它加 `Cache-Control: no-store`
        if self.command != "HEAD":
            self.wfile.write(body)
        return True

    def _blocked(self, rel):
        """敏感路径一律挡住（`V-170`）；目录也不给列（要拿文件得知道确切路径）。"""
        for d in _EMBED_DENY:
            if rel == d or rel.startswith(d):
                return "denied"
        if (HOME / rel).is_dir():
            return "no listing"
        return None

    def send_head(self):
        # ★ `V-277`：界面那一页是内存里那份（虚拟地址），先问它 —— 它不落盘，
        #   所以也不该受"目录不给列 / 敏感路径"那套静态规则管。
        if self._serve_live():
            return None
        rel = self._rel_of(self.path)
        why = self._blocked(rel)
        if why:
            self.send_error(403 if why == "denied" else 404, why)
            return None
        return super().send_head()

    def translate_path(self, path):
        tk = _EMBED_SRV["token"]
        if tk and path.startswith("/" + tk + "/"):
            path = path[len(tk) + 1:]        # 去掉 token 那一段，剩下的才是真路径
        # ★ 文件管理的 **HTML / MD 浏览模式**要能加载同目录下的 CSS / 图片 / JS。
        #   这类页面里的相对地址会变成 `/…/abs/<绝对路径>`，这里把它映射回真实文件。
        #   仍然要求随机 token（本机其它程序猜不到），和 pywebview 的 `fs_read` 是同一级信任。
        raw = urllib.parse.unquote(str(path or "").split("?", 1)[0].split("#", 1)[0]).lstrip("/")
        if raw.startswith("abs/"):
            try:
                return str(Path(raw[len("abs/"):]))
            except OSError:
                return ""
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
                    # ★ `V-192`：帧可能正待在**浮动窗口**里 —— 那就送给那个窗口。
                    _js(_float_win(pid) or window,
                        "window.__mossEmbedFromBackend(%s, %s)"
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
            was_stopped = proc in EMBED_STOPPED      # 是界面点「停止」杀掉的？
            EMBED_STOPPED.discard(proc)
        if was_stopped:
            # ★ `V-297`：主动停掉的**不再报**"结束了（退出码 1）" —— 界面已经弹过「已停掉…」了。
            return
        try:
            _js(_float_win(pid) or window,          # `V-192`：帧在浮动窗口里就送给它
                "window.__mossEmbedGone(%s, %s)" % (json.dumps(pid), json.dumps(code)))
        except Exception:                                            # noqa: BLE001
            pass


def _oem_encoding():
    """cmd 那些**内建命令**（`dir` / `echo` / `ping`）按**控制台代码页**吐字节（中文 Windows
    = cp936）。★ `V-371`：拿 UTF-8 去读它们 ⇒ 用户敲个 `dir` 回来全是乱码替换符
    （`tools\\命令行探针.py` 第 ⑥ 段当场验的）。取不到就退回 UTF-8。"""
    try:
        import ctypes                                                    # noqa: PLC0415
        return "cp%d" % int(ctypes.windll.kernel32.GetOEMCP())
    except Exception:                                                    # noqa: BLE001
        return "utf-8"


def _cmd_new_cwd(base, arg):
    """`cd <arg>` 算出来的新目录（`V-371`）。算不出来（不存在 / 非法）回 `None`。

    `arg` 空 = 原地（界面会把它当"把当前目录打出来看看"）；`D:` = 那个盘的根；
    别的按"相对当前目录"算（`..` 也在内）—— 跟 cmd 里一个口径。
    """
    a = str(arg or "").strip().strip('"')
    if not a:
        return str(base or "")
    try:
        if re.match(r"(?i)^[a-z]:$", a):
            a += "\\"
        p = Path(a)
        if not p.is_absolute() and base:
            p = Path(base) / a
        p = Path(os.path.normpath(str(p)))
        return str(p) if p.is_dir() else None
    except OSError:
        return None


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

    def watcher():
        """★ `V-219`：**子进程一退就算跑完了 —— 不等管道 EOF**。

        为什么非要有它（用户报的"程序已经退出了，界面还亮着红色的停止按钮"）：
        子进程的 stdout 是我们的**管道**，而它拉起的**孙进程会继承这个写端**。最典型的一例就是
        `.bat` 里那句 `start "" explorer.exe`（`suoluetu` 那个包第 17 行就是这个）——
        `cmd.exe` 早就退出了，可 explorer.exe 还叼着管道 ⇒ 下面那个 `os.read` **永远等不到 EOF**
        ⇒ `r["code"]` 一直是 None ⇒ `run_poll` 永远回 `running: true` ⇒ 界面上那颗「停止」
        一直红着；偏偏 `run_input` 问的是**进程本身**（`proc.poll()`，已经退了）⇒ 你往命令行敲回车，
        它说"它已经跑完了" —— 同一件事两个说法，自相矛盾。现在按**进程退出**判收工，
        再给读线程 0.35 秒把管道里剩的输出读完。

        （残留一个小尾巴：那个读线程还阻塞在 `os.read` 上、跟着进程一起走（daemon），
        每次这种运行留一个线程 + 一个管道句柄，不碍事 —— 比起"界面永远显示在跑"划算得多。）
        """
        try:
            proc.wait()
        except Exception:                                            # noqa: BLE001
            return
        time.sleep(0.35)                     # 让读线程把管道里剩的读完再收工
        with RUNS_LOCK:
            if r.get("code") is None:
                r["code"] = proc.returncode

    threading.Thread(target=watcher, daemon=True).start()
    # ★ `V-371`：**这一段按哪种编码解，不能写死** —— 包（`PYTHONIOENCODING=utf-8`）是 UTF-8，
    #   而 cmd 那些内建命令按**控制台代码页**吐字节，那个代码页在不同环境里还不一样
    #   （实测：界面自己的子进程 = 936〔GBK〕；我在一个代码页 65001 的终端里跑同样的命令
    #   就变成 UTF-8，连 `ping` 的中英文都会跟着变）。所以 `dec == "auto"` 的那些
    #   **先严格试 UTF-8，不像才按控制台代码页**；定下来这一跑就照它（逐段判会抖）。
    _auto = (r.get("dec") == "auto")
    _picked = None
    dec = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        fd = proc.stdout.fileno()
        while True:
            buf = os.read(fd, 4096)
            if not buf:
                break
            if _auto and _picked is None:
                try:
                    buf.decode("utf-8")
                    _picked = "utf-8"
                except UnicodeDecodeError:
                    _picked = _oem_encoding()
            if _auto and _picked != "utf-8":
                text = buf.decode(_picked, "replace")
            else:
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


# ================================================================ 设置：界面内校验（`V-276`）
# ★ 你说得对：界面进程**就是 Python**，而"校验设置"是**纯计算**（不读盘不写盘）——
#   没有任何理由为它起一个 `moss.exe`（那一趟真机实测 0.73~1.07 秒，算本身 ≈20ms）。
#   规则放在 `system/option/rules.py`（**不 import core**，所以界面能直接用），
#   宿主 `core/config.py` 用的是**同一套逻辑**，`tools/设置规则探针.py` 逐字对比两边输出。
_SETTINGS_RULES = {"mod": None, "tried": False}
#: 面板打开时宿主给的那份"当前生效值"（`settings_current` 用；`check` 只拿它兜底）
_SETTINGS_CUR = {}


def _settings_rules():
    """加载 `system/option/rules.py`；拿不到返回 None（调用方退回"叫宿主"那条老路）。"""
    if _SETTINGS_RULES["tried"]:
        return _SETTINGS_RULES["mod"]
    _SETTINGS_RULES["tried"] = True
    try:
        import importlib.util                                        # noqa: PLC0415
        path = HOME / "system" / "option" / "rules.py"
        spec = importlib.util.spec_from_file_location("moss_settings_rules", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SETTINGS_RULES["mod"] = mod
    except Exception as e:                                            # noqa: BLE001
        _note("settings: 读不到 system/option/rules.py（%r）—— 校验退回叫宿主" % (e,))
    return _SETTINGS_RULES["mod"]


def _settings_current():
    """宿主给的"当前生效值"（键 → 值）；没打开过面板就是空的（那时 `check` 用默认值兜底）。"""
    return dict(_SETTINGS_CUR)


# ================================================================ 退出 / 更名跟随 / 自动启动
# `V-354` ~ `V-356`（用户 2026-10-09 提的三件）。★ 这三块都在**界面自己的进程**里算：
# 不再为了问一句"包表变了吗"去起一个 `moss.exe`（那要 ≈1 秒，而这是每 2.5 秒一轮的事）。
#: 「退出时结束所有插件进程」那个开关的出厂默认（和 `core/config.py` 里那个键的默认值一致）。
DEFAULT_KILL_ON_EXIT = False

_CFG_CACHE = {"t": 0.0, "data": None}


def _cfg(section, key, default=None):
    """读 `user_data/config.toml` 里的一项（`V-354`）。

    ★ 为什么不回头问宿主（`moss --settings`）：那是起一个进程（真机 ≈1 秒），而这句
      只是"关界面的那一刻，那个开关开着没有"。读文件 1 毫秒，而且**手改 config.toml
      立刻生效**（不用重启 moss）。读不到 / 读坏了就交回默认值 —— 收进程这件事绝不许
      因为一个配置文件而变玄学（读不出来就是"没开"）。
    ★ 缓存 2 秒：同一轮里可能被问好几次（关相邻的两个窗口）。
    """
    now = time.time()
    if _CFG_CACHE["data"] is None or (now - _CFG_CACHE["t"]) > 2.0:
        data = {}
        try:
            import tomllib                                             # noqa: PLC0415
            data = tomllib.loads((USER_DATA / "config.toml").read_text(encoding="utf-8"))
        except Exception:                                              # noqa: BLE001
            data = {}
        _CFG_CACHE["data"] = data if isinstance(data, dict) else {}
        _CFG_CACHE["t"] = now
    try:
        val = (_CFG_CACHE["data"].get(str(section)) or {}).get(str(key), default)
    except Exception:                                                  # noqa: BLE001
        val = default
    return default if val is None else val


def _pkg_ids_on_disk():
    """磁盘上现在有哪些包（返回**目录名**集合）。

    ★ 为什么要问磁盘：认进程靠的是命令行里那段 `/pkgs/<目录名>/`（`D-27`：目录名和 id
      允许不一样），而界面手里那份 `DATA` 是上次刷新时的。
    """
    out = set()
    for root in (USER_DATA / "pkgs", HOME / "system" / "pkgs"):
        try:
            for d in root.iterdir():
                if d.is_dir() and (d / "pkg.json").is_file():
                    out.add(d.name)
        except OSError:
            pass
    return out


def _kill_all_pkg_procs():
    """把**所有**插件进程收掉（连子孙），返回被杀掉的 pid 列表（`V-354`）。

    ★ 认进程一律走 `_pkg_pids()` —— 它身上带着 `V-220` 那道硬条件（可执行文件得真在包
      目录里），所以不会像"只认 `MOSS_PKG_ID`"那样把 explorer.exe / 用户的浏览器一起
      杀掉（那两起真事故都记在 `_pkg_pids` 的注释里）。
    ★ 三个来源都要收：① 界面自己起的（`RUNS`）；② 内嵌界面的后端（`EMBED`）；
      ③ 别的什么人起的（终端敲的、上一次界面留下的孤儿）—— 按包目录名去认；
      ④ **界面自己拉起的整棵树**（AI 工作台的子进程、常驻终端那个 shell 都在里面）。
    """
    killed = []
    # ① 界面自己起的后台运行（含"在终端里跑"的那种）
    try:
        with RUNS_LOCK:
            runs = [dict(r) for r in RUNS.values()]
    except Exception:                                                  # noqa: BLE001
        runs = []
    for r in runs:
        proc = r.get("proc")
        try:
            pid = int(r.get("pid") or (proc.pid if proc is not None else 0) or 0)
        except Exception:                                              # noqa: BLE001
            pid = 0
        if pid:
            _kill_tree(pid)
            killed.append(pid)
    # ② 内嵌界面的后端
    try:
        embeds = list(EMBED.items())
    except Exception:                                                  # noqa: BLE001
        embeds = []
    for _pkg, rec in embeds:
        try:
            proc = (rec or {}).get("proc")
            if proc is not None and proc.poll() is None:
                _kill_tree(proc.pid)
                killed.append(int(proc.pid))
        except Exception:                                              # noqa: BLE001
            pass
    # ③ 剩下的：按"包"认（记下的进程树 / 命令行里的包目录 / 包自己的窗口）
    parents = _pid_parents()
    cmdlines = _pids_by_cmdline()
    owner_pkg = {}
    for w in _top_windows():
        pid = w["pid"]
        if pid != os.getpid() and pid not in owner_pkg:
            owner_pkg[pid] = _env_pkg_id(pid)
    ids = set(_pkg_procs) | set(EMBED) | set(_pkg_ids_on_disk())
    ids |= {str(p.get("id")) for p in (DATA.get("packages") or []) if p.get("id")}
    pids = set()
    for one in ids:
        if not one:
            continue
        try:
            pids |= _pkg_pids(str(one), parents, cmdlines, owner_pkg)
        except Exception:                                              # noqa: BLE001
            pass
    pids.discard(os.getpid())                    # 别把自己（界面）算进去
    pids |= _with_descendants(pids, parents)     # 连带它们的子孙
    # ④ **界面自己拉起的整棵树**（= 这个进程的全部活着的子孙）：AI 工作台的子进程、
    #    常驻终端那个 shell（包就跑在里面）、以及任何还没被上面三条认出来的 —— 关掉界面
    #    就不留活口（`V-307` 那个"几十个 moss/python 进程"的现场就是没这一条）。
    #    ★ 这一条**只碰自己的子孙**，所以照样不会动用户的浏览器 / 编辑器。
    pids |= _with_descendants({os.getpid()}, parents)
    pids.discard(os.getpid())
    for pid in sorted(pids):
        _kill_tree(int(pid))
        killed.append(int(pid))
    return sorted(set(killed))


def _on_ui_closing():
    """界面窗口被关掉（× / 任务栏 / 界面里退出）时要干的事（`V-354`）。

    ★ 走 pywebview 的 `closing` 事件：winforms 后端在 `FormClosing` 里**同步**调它，
      而 `window.destroy()`（`Api.quit` 那条路）也会经过它（`destroy_window` → `Close()`）。
    ★ 返回值要是**真值**：`closing.set()` 会把每个处理函数的返回值收起来，谁回了 `False`
      就等于"取消这次关闭"。我们只干活、不拦人。
    ★ 这里是**阻塞**的（同步事件）：收进程几百毫秒，窗口会晚一会儿才消失 —— 这是有意的，
      不然进程还没收完窗口就没了，"收干净"这件事就没人保证了。
    """
    try:
        if bool(_cfg("ui", "kill_pkgs_on_exit", DEFAULT_KILL_ON_EXIT)):
            pids = _kill_all_pkg_procs()
            drop_log("退出：按设置收掉插件进程 %d 个 —— %s" % (len(pids), pids[:20]))
    except Exception as e:                                             # noqa: BLE001
        drop_log("退出：收插件进程时出错（不影响关闭）：%r" % (e,))
    return True


# ---------------------------------------------------------------- 更名跟随（`V-355`）
# 用户原话：「如果用户对当前打开的界面 不存在了 对不上了 但是出现了一个新的id 那基本就能
# 判断是它改名了 …… 当然如果你有更精准的办法更好了」。
# 「更精准的办法」= **身份指纹**：`pkg.json` 去掉 `id` 之后的内容 + 层 + 那个文件的创建时间。
# 为什么它就够准：`moss --rename` 那三步（包目录 / 数据目录 / 清单里的 id）里，清单只改
# `id` 一个字段，而且是**截断重写同一个文件**（创建时间不变）⇒ 这三样在改名前后一字不差。
# 编码之外还留了一条兜底（一个走、一个来 ⇒ 按新旧 id 推断），两条都会在界面上说明依据。
#: id -> 指纹；id -> 包目录（判"是真没了还是改坏了"用）
_PKG_IDENT = {}
_PKG_DIRS = {}
#: 上一次全量扫描的 id 集合（`None` = 还没扫过，第一次只记基线、不报任何东西）
_PKG_KNOWN = None


def _swap_pid(value, pid):
    """把**显示名**里的旧 id 逐字换成占位符（只给 `name` 用，见 `_ident_norm`）。"""
    if isinstance(value, str):
        return value.replace(pid, "@id@") if pid else value
    if isinstance(value, dict):
        return dict((k, _swap_pid(v, pid)) for k, v in value.items())
    if isinstance(value, list):
        return [_swap_pid(v, pid) for v in value]
    return value


def _ident_norm(data, pid):
    """把清单压成"**改名前后一模一样**"的那一份内容（再键排序算指纹）。

    ★ 只动**改名真正会动的那些字段**（`core/cli.py::cmd_rename` 第 ③ 步）：
      · `id`        —— 整个去掉（它就是被换掉的那个）；
      · `name`      —— 旧 id **逐字**换成新 id ⇒ 这里统一压成 `@id@`；
      · `aliases`   —— **整条等于**旧 id 的换成新 id ⇒ 这里同样整条压成 `@id@`。
      ⚠️ 别的字段**一个字都不许碰** —— 尤其不能对整份清单做 `str.replace`：
        别名 `myoldname` 里含旧 id，可改名**并不动它**；要是把它压成 `my@id@`，
        改名前后就对不上了（真踩过：探针 E7 当场红）。
    """
    out = dict(data) if isinstance(data, dict) else {}
    out.pop("id", None)
    if "name" in out:
        out["name"] = _swap_pid(out.get("name"), str(pid or ""))
    al = out.get("aliases")
    if isinstance(al, list):
        p = str(pid or "")
        out["aliases"] = ["@id@" if (p and str(a) == p) else a for a in al]
    return out


def _pkg_ident(man, layer, pid=""):
    """一个包的**身份指纹**（改名时不变）。算不出来回 None（调用方当"读坏了"）。

    ★ 指纹 = 清单**去掉 id、把显示名里那句旧 id 和等于旧 id 的别名压成占位符**之后的内容
      （键排序）+ 在哪一层。为什么它就是"同一个包"：`moss --rename` 动的就这三样
      （`core/cli.py::cmd_rename` 第 ③ 步），别的字段一个字不动
      （连空白/排版都不算数 —— 我们比的是解析后的内容，不是字节）。
    ★ 为什么不掺"目录名 / 目录时间 / 文件时间"：那几样正好是**会变**的，掺进去就认不出来了。
    ★ 撞车怎么办（两个包的清单除了 id 一模一样，比如同一份骨架复制出来的）：这一步要求
      "**唯一命中**"才认（见 `_pkg_watch_poll`），撞车就自动退到第二条判据（一个走一个来）。
    """
    try:
        data = json.loads(Path(man).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        body = json.dumps(_ident_norm(data, pid), ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(("%s|%s" % (layer, body)).encode("utf-8")).hexdigest()
    except Exception:                                                  # noqa: BLE001
        return None


def _pkg_scan():
    """扫一遍磁盘上的包：`({id: 指纹}, {id: 目录}, 读不出来的目录数)`。

    ★ 纯读盘（两个 `pkgs` 根下的 `pkg.json`），不起进程 —— 才敢每 2.5 秒走一次。
    """
    fps, dirs, broken = {}, {}, 0
    for layer, root in (("user", USER_DATA / "pkgs"), ("system", HOME / "system" / "pkgs")):
        try:
            entries = sorted(root.iterdir())
        except OSError:
            continue
        for d in entries:
            man = d / "pkg.json"
            if not (d.is_dir() and man.is_file()):
                continue
            try:
                pid = str((json.loads(man.read_text(encoding="utf-8")) or {}).get("id")
                          or d.name)
            except Exception:                                          # noqa: BLE001
                broken += 1                    # 正在被编辑 / 写坏了：这一轮当"不知道"
                continue
            fp = _pkg_ident(man, layer, pid)   # ★ 指纹要**自己的 id**（归一化用）
            if fp is None:
                broken += 1
                continue
            fps.setdefault(pid, fp)            # 先扫 user 层 ⇒ 覆盖关系和宿主一致
            dirs.setdefault(pid, str(d))
    return fps, dirs, broken


def _pkg_watch_poll():
    """看一眼「包表变了吗 / 谁改名了」（界面每 2.5 秒问一次）。

    返回 `{"renamed": [[旧, 新, 依据], ...], "gone": [id, ...], "changed": bool,
    "ids": [...]}`。第一次调用**只记基线**（不然界面一开就把"我上次看到的"当成变了）。
    """
    global _PKG_KNOWN
    fps, dirs, _broken = _pkg_scan()
    out = {"renamed": [], "gone": [], "changed": False, "ids": sorted(fps)}
    if _PKG_KNOWN is None:
        _PKG_IDENT.clear()
        _PKG_IDENT.update(fps)
        _PKG_DIRS.clear()
        _PKG_DIRS.update(dirs)
        _PKG_KNOWN = set(fps)
        return out
    old, old_dirs = dict(_PKG_IDENT), dict(_PKG_DIRS)
    gone = [i for i in old if i not in fps]
    added = [i for i in fps if i not in old]
    used = set()
    # ① 指纹对得上 = 铁定是同一个包改了名
    for g in sorted(gone):
        hit = [a for a in added if a not in used and fps[a] == old[g]]
        if len(hit) == 1:
            used.add(hit[0])
            out["renamed"].append([g, hit[0], "指纹一致"])
    # ② 兜底：一个走、一个来 ⇒ 按新旧 id 推断（用户自己提的那条判据）
    left_g = [g for g in gone if not any(r[0] == g for r in out["renamed"])]
    left_a = [a for a in added if a not in used]
    if len(left_g) == 1 and len(left_a) == 1:
        out["renamed"].append([left_g[0], left_a[0], "按新旧 id 推断"])
        used.add(left_a[0])
    # ③ 真没了的：目录都不在了才说（`pkg.json` 正被编辑时目录还在 ⇒ 不吓人）
    for g in gone:
        if any(r[0] == g for r in out["renamed"]):
            continue
        try:
            still = Path(old_dirs.get(g) or "").is_dir()
        except OSError:
            still = False
        if not still:
            out["gone"].append(g)
    # ★ `changed` 只认"**结构**变了"（多了 / 少了 / 改名了）—— 故意**不**把"清单内容变了"
    #   算进来：界面拿到 `changed` 会去问一遍宿主（那是起一个 `moss.exe`，≈1 秒），而
    #   AI 干活时会一次次改包里的文件（`pkg.json` 也在其中）⇒ 每改一下就起一个进程，
    #   那是白烧。清单内容变了那条路由现有的 `refreshPkgs`（存盘的调用点）自己管。
    out["changed"] = bool(out["renamed"] or out["gone"] or added
                          or (set(fps) != set(old)))
    _PKG_IDENT.clear()
    _PKG_IDENT.update(fps)
    _PKG_DIRS.clear()
    _PKG_DIRS.update(dirs)
    _PKG_KNOWN = set(fps)
    return out


# ---------------------------------------------------------------- 自动启动（`V-356` / `V-358`）
# 用户原话：「启动 moss 的 ui 以后 可以自动启动一些插件或历史记录（可以自定义参数）」，
# 后来（`V-358`）又说了它该在哪儿：「把那个自动启动放在详情里面去设置 而不是放到设置里面去
# 那样很不直观 那个地方可以编辑 删除 以及查看启动状态」。
# ⇒ **配置的入口在「详情」页**（包详情 / 历史详情各有一块），设置里那一组整个撤掉了；
#   也**没有"总开关"**了 —— 每条自己有一个开关（"已加入 · 开 / 关"），
#   这也是"不允许两个开关控制同一件事"那条规矩（`V-316`）的延续。
# ★ 存哪儿：`user_data/state/_ui_autostart.json` —— **不进 config.toml**：那是一串带参数的
#   条目（不是一个键一行），面板那种渲染摆不下；而 `_ui_order.json` 一直是这么存的（同一套路）。
AUTOSTART_FILE = USER_DATA / "state" / "_ui_autostart.json"
#: 最多几条（再多也不是"自动启动"了，是把界面当开机脚本用）
AUTOSTART_MAX = 20

#: 寄生模式名单（`V-379`）：`user_data/state/_ui_parasite.json`，形状 `{"ids": ["md5", "path"]}`。
#: ★ 这里存的是一份**名单**（不像自动启动那种"带参数的条目"），所以照 `_ui_order.json` 那个形状。
#: ★ 为什么不写进 `pkg.json`：那是**你的用法选择**，不是包的属性 —— 清单会被升级整体替换掉，
#:   AI 也不该能替你打开它。`D-22`"磁盘是真相"在这里分两层：包归包，你的偏好归 `state/`。
PARASITE_FILE = USER_DATA / "state" / "_ui_parasite.json"


def _parasite_read():
    """读寄生模式名单，回**id 列表**（去空、去重、保序）。

    文件不在 / 读坏了 = 空名单（**绝不许因此起不来界面**，也不许崩在详情页上）。
    """
    try:
        data = json.loads(PARASITE_FILE.read_text(encoding="utf-8"))
    except Exception:                                                  # noqa: BLE001
        data = {}
    if not isinstance(data, dict):
        data = {}
    out = []
    for i in (data.get("ids") or []):
        s = str(i or "").strip()
        if s and s[:400] not in out:
            out.append(s[:400])
    return out


def _autostart_read():
    """读自动启动那份配置，回**条目表** `[{kind, id, args, cwd, name, on}, …]`。

    文件不在 / 读坏了 = 空表（**绝不许因此起不来界面**，也不许崩在详情页上）。
    """
    try:
        data = json.loads(AUTOSTART_FILE.read_text(encoding="utf-8"))
    except Exception:                                                  # noqa: BLE001
        data = {}
    if not isinstance(data, dict):
        data = {}
    items = []
    for it in (data.get("items") or [])[:AUTOSTART_MAX]:
        if not isinstance(it, dict):
            continue
        kind = "hist" if str(it.get("kind")) == "hist" else "pkg"
        pid = str(it.get("id") or "").strip()
        if not pid:
            continue
        items.append({"kind": kind, "id": pid, "args": str(it.get("args") or ""),
                      "cwd": str(it.get("cwd") or ""), "name": str(it.get("name") or ""),
                      "on": it.get("on") is not False})
    return items


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
            self._payload_error = "没拿到宿主命令 —— 请从 moss 主程序打开界面"
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
            self._payload_error = "包表读回来是空的（格式不对）"
            return None
        return data

    def run(self, pid, args_text=""):
        """带参数跑一个包并等它跑完（老的阻塞式；界面现在走 run_start 那一套）。"""
        # ★ `V-305`：界面这边起包一律走 **`--pkg <id>` 稳定入口** —— 它跟"跑包符号"
        #   （`symbols.plugin_mode`，用户可以在设置里改）解耦。千万别再写回 `":" + pid`：
        #   用户把符号改成别的之后，那条命令宿主就认不出来了。
        return _run_capture(HOST + ["--pkg", str(pid)] + _split(args_text))

    def run_start(self, pid, args_text="", cwd=None):
        """起一个后台运行，立刻返回 run_id（输出靠 `run_poll` 拿）。

        `cwd`：**这次运行的工作目录**（拖文件进来那条路会传 —— 你拖着某个文件夹
        到详情页，意思就是"以它为当前目录跑这个包"）。不传就跟以前一样，继承界面
        自己的 cwd。宿主那边 `engine` 是拿 `os.getcwd()` 当包的工作目录的（`pkg.json`
        里没写 `env.cwd` 时），所以这里给它换掉就等于给包换了工作目录。

        ★ 目录不存在就**当没传**：路径可能是刚被删掉的、或者拖的是个断了的网络盘，
          那种情况下宁可退回默认目录，也不要让进程根本起不来。
        """
        argv = HOST + ["--pkg", str(pid)] + _split(args_text)
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

    def cmd_start(self, cwd, line, pid=""):
        """在 `cwd` 里跑**界面「命令行」那根输入行敲的一行**（`V-371`）。

        为什么需要它：那个对象**没在跑**的时候，那一行原来是死的（"这个包现在没在跑"）。
        你要的是"像普通命令行那样直接敲" —— 但常驻终端只有**一条 shell**（`V-348`/`V-352`），
        把 A 的包目录 `cd` 过去再敲 A 的命令，等于**打断正跑在里面那个包**（那条 shell 的
        stdin 就是它的）。所以这里**另起一个一次性进程**：
          · `cd ...` 这种改目录的**不起进程** —— 算好新目录回给界面（每一份「命令行」自己记 cwd）；
          · 以「跑包符号」开头的交给 **moss 自己**（cmd.exe 里没有你 PowerShell 那个包装函数，
            所以不能原样丢给 cmd）；
          · 别的就是 `cmd.exe /d /s /c <line>`（= 你在自己终端里敲一条命令）。
        输出 / 停止 / 回话都走现成的 `run_poll` / `run_stop` / `run_input`（同一套管子）。
        """
        text = str(line or "").strip()
        if not text:
            return {"ok": False, "msg": "空命令"}
        base = str(cwd or "")
        m = re.match(r"(?i)^cd(?:\s+(.*))?$", text)
        if m:
            arg = (m.group(1) or "").strip().strip('"')
            new = _cmd_new_cwd(base, arg)
            if new is None:
                return {"ok": False, "msg": "没有这个目录：%s" % arg}
            return {"ok": True, "cd": new, "cmd": text}
        sym = str((DATA.get("symbols") or {}).get("plugin") or ":")
        if sym and text.startswith(sym):
            argv = HOST + _split(text)
            # moss 自己（以及它拉起的包）那边宿主摆了 `PYTHONIOENCODING=utf-8` ⇒ 按 UTF-8 读
            dec = "utf-8"
        else:
            # ★ `V-371`：cmd 那条**不知道**会吐哪种编码（控制台代码页随环境变）⇒ 让读线程
            #   自己判（先严格试 UTF-8、不像再按控制台代码页）。★ 别用 `chcp 65001` 去"统一"：
            #   试过 —— 同一行里改代码页会把这一行里的中文**输入**搅烂。
            argv = ["cmd.exe", "/d", "/s", "/c", text]
            dec = "auto"
        workdir = None
        if base:
            try:
                if Path(base).is_dir():
                    workdir = base
            except OSError:
                workdir = None
        # 和 `run_start` 一个道理：告诉它"有人在听"（界面给了 stdin 管子，下面那根输入行能回话）
        env = dict(os.environ)
        env["MOSS_INTERACTIVE"] = "1"
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE, env=env,
                                    text=True, encoding="utf-8", errors="replace",
                                    bufsize=1, creationflags=NO_WINDOW, cwd=workdir)
        except OSError as e:
            return {"ok": False, "msg": "跑不起来：%s" % e}
        rid = uuid.uuid4().hex[:10]
        with RUNS_LOCK:
            RUNS[rid] = {"proc": proc, "lines": [], "code": None, "t0": time.time(),
                         "pid": proc.pid, "cmd": text, "cwd": workdir or "",
                         "manual": True, "dec": dec}
            if len(RUNS) > RUNS_KEEP:                    # 只留最近这些，别越攒越多
                for old in sorted(RUNS, key=lambda k: RUNS[k]["t0"])[:-RUNS_KEEP]:
                    if RUNS[old]["code"] is not None:
                        RUNS.pop(old, None)
        threading.Thread(target=_pump_output, args=(rid,), daemon=True).start()
        return {"ok": True, "run_id": rid, "pid": proc.pid, "cmd": text}

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
        """问一次状态：还在跑吗、输出到哪了、结束了的话退出码是多少。

        ★ `V-219`：这里**以进程为准**（`proc.poll()`），不是以"管道读到 EOF"为准 ——
          管道可能被孙进程叼着（`.bat` 里 `start ""` 那种），那样永远等不到 EOF。
          这一问是界面每 200ms 问一次的，绝不能因为一个叼着管道的孙进程就说"还在跑"。
        """
        with RUNS_LOCK:
            r = RUNS.get(run_id)
            if not r:
                return {"ok": False, "msg": "没有这次运行（可能已经被清掉了）"}
            code = r["code"]
            proc = r.get("proc")
        if code is None and proc is not None:
            pc = proc.poll()
            if pc is not None:                        # 兜底：watcher 那一刻可能还没轮到
                code = pc
                with RUNS_LOCK:
                    if r.get("code") is None:
                        r["code"] = pc
        with RUNS_LOCK:
            return {"ok": True, "running": code is None, "code": code,
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
        return {"ok": True, "msg": "已终止这次运行（它起的进程也一起停了）"}

    # ------------------------------------------------ 常驻 DOS 终端（`V-348`）
    # 为什么另起一套，而不是继续往上面那三件里塞：`run_*` 是**"一个包一次运行"**的管子，
    # 包一退出管子就废 —— 用户报的正是「一旦停止运行就没法继续执行 dos 命令」。
    # 终端是**界面自己的 shell**：一直活着，命令跑完回到提示符，接着敲就行。
    # 两个后端（真伪控制台 / 管道）+ 自动降级都在 `system/ui/term.py` 里。
    def term_start(self, cols=100, rows=30):
        t = _term_mod()
        if t is None:
            return {"ok": False, "mode": "", "note": _TERM["err"], "alive": False,
                    "history": "", "fresh": True}
        return t.start(cols, rows, cwd=str(HOME), home=str(HOME))

    def term_poll(self):
        t = _term_mod()
        if t is None:
            return {"ok": False, "out": "", "mode": "", "note": _TERM["err"], "alive": False}
        return t.poll()

    def term_write(self, text=""):
        t = _term_mod()
        if t is None:
            return {"ok": False, "msg": _TERM["err"]}
        return t.write(text)

    def term_run(self, pid, args_text="", cwd=None):
        """把「跑这个包」**敲进那个常驻终端**（`V-352`）—— 包就真跑在这个 shell 里。

        ★ 为什么不在界面那边拼命令：`HOST`（打包后是 `moss.exe`、源码运行时是
          `<python> moss.py`）和参数拆法（`_split`）都在这儿，界面不认识它们
          （`core/ui.py` 那条"界面不 import core"的边界照旧）。
        ★ 退出码不用我们操心：moss 自己会在终端里打出 `[退出码] N` 那一行。
        ★ `cwd` 用 `pushd/popd` 包起来：目录只对**这一次运行**有效，跑完 shell 还留在原处
          （和 `run_start` 的 cwd 语义对齐 —— 不这么写，用户拖进一个目录之后 shell 就再也
          回不来了）。
        """
        t = _term_mod()
        if t is None:
            return {"ok": False, "msg": _TERM["err"]}
        argv = HOST + ["--pkg", str(pid)] + _split(args_text)
        line = _shell_line(argv)
        pre = ""
        try:
            if cwd and Path(str(cwd)).is_dir():
                pre = 'pushd "%s" && (' % str(cwd)
                line = line + ") & popd"
        except OSError:
            pre = ""
        return t.run(pre + line)

    def term_resize(self, cols=100, rows=30):
        t = _term_mod()
        if t is None:
            return {"ok": False, "msg": _TERM["err"]}
        return t.resize(cols, rows)

    def term_stop(self):
        t = _term_mod()
        if t is None:
            return {"ok": False, "msg": _TERM["err"]}
        return t.stop()

    def open_ui(self, pid, args_text=""):
        """把包的界面开起来：**脱离**当前进程、不抓输出，所以不会卡住界面。"""
        argv = HOST + ["--pkg", str(pid)] + _split(args_text)
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
                        "titles": [w["title"] for w in ws][:5],
                        "procs": _procs_info(pids, cmdlines)}
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
                "titles": [w["title"] for w in ws][:5],
                "procs": _procs_info(pids)}

    def pkg_stop(self, pid):
        """把这个包正在跑的进程停掉（连子孙一起）—— 不管是谁把它拉起来的。"""
        pids = _pkg_pids(pid)
        if not pids:
            return {"ok": False, "msg": "这个包现在没在跑"}
        for p in pids:
            _kill_tree(p)
        return {"ok": True, "msg": "已停掉这个包（%d 个进程，它起的子进程也一起停了）" % len(pids)}

    def pkg_hide(self, pid):
        """把它的窗口藏起来（不关、不杀，随时能再显示）。"""
        ws = _pkg_windows(pid)
        if not ws:
            return {"ok": False, "msg": "没找到它的窗口 —— 先「运行」或「新窗口运行」一次"}
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
                return {"ok": False, "msg": "没找到它的窗口 —— 先「运行」或「新窗口运行」一次"}
            hs = [w["hwnd"] for w in ws]            # 不是这里藏的（比如被最小化过）→ 全放出来
        n = sum(1 for h in hs if _show_window(h, True))
        if n:
            _pkg_hidden.pop(str(pid), None)
        return {"ok": n > 0, "msg": "已显示 %d 个窗口" % n}

    def run_host(self, text):
        """跑一条宿主命令（自检用）：`--selfcheck` / `--history 20` 之类，不带包名。"""
        return _run_capture(HOST + _split(text))

    # ---------------------------------------------------------------- AI 工作台（`V-230`~`V-233`）
    # ★ 为什么在这儿而不做成一个包：这一页要**贴着当前选中的包**，还要把结果直接反映到
    #   文件管理 / 命令行 / 运行状态上 —— 全是宿主**进程内**的状态（`V-231` 定的形态）。
    # ★ 为什么所有 AI 模块都是**惰性 import**：它们是新代码，写坏了也**不许**把整个界面
    #   拖下水（界面起不来 = 用户什么都干不了）。所以失败只在 AI 那一页上说清楚。
    def _ai_mods(self):
        ai_dir = str(HERE / "ai")
        if ai_dir not in sys.path:
            sys.path.insert(0, ai_dir)
        import ai_client
        import ai_edits
        import ai_loop
        return ai_client, ai_edits, ai_loop

    def _ai_dir(self):
        ai_dir = str(HERE / "ai")
        if ai_dir not in sys.path:
            sys.path.insert(0, ai_dir)
        return ai_dir

    def _ai_mode(self):
        """`ai_mode`（`V-307`：三档权限 / 放行清单 / 临时空间）—— 惰性 import，坏不了界面。"""
        self._ai_dir()
        import ai_mode
        return ai_mode

    def _ai_runs(self):
        """`ai_runs`（`V-243`/`V-307`：会话记录 —— 现在按"干活的地方"分桶）。"""
        self._ai_dir()
        import ai_runs
        return ai_runs

    def _ai_ask(self):
        """`ai_ask`（`V-308`：它问、你答 —— loop 会阻塞在那儿等）。"""
        self._ai_dir()
        import ai_ask
        return ai_ask

    def _ai_wildcard(self):
        """现在是不是"放手"（清单里「任意路径」那一行勾了**写**）—— `V-316`。"""
        try:
            return bool(self._ai_mode().wildcard_write())
        except Exception:                                                # noqa: BLE001
            return False

    def ai_params(self, refresh=False):
        """拿"当前那组 AI 参数"（`V-234`）。

        ★★ 为什么不能读 `MOSS_AI_*`：那几个变量是宿主发给**包**的（`core/engine.py` 在起
           子进程时注入）。**界面进程自己没有** —— 所以第一版在工作台里显示"还没配 AI"，
           而配置明明在（`moss --ai-test` 是通的）。真机上就是这么表现的。
        ★ 也不许自己去读 `config.toml`：那份的**唯一读者是宿主**（格式会变，契约里写死了
           "别在包里读它"，界面同理）。所以这里回头调宿主：
           `moss --ai-config-reveal` 打的就是一份 JSON（含明文 key）。
        """
        now = time.time()
        if not refresh and _AI_CFG["got"] and now - float(_AI_CFG["t0"]) < 15:
            return _AI_CFG["got"]
        out = {"ok": False, "source": "", "model": "", "base_url": "", "api_key": "",
               "models": [], "why": "",
               # ★ `V-386`：`profile` = **当前那组**的名字；`providers` = **所有**组 + 各自模型
               #   清单 —— 顶栏那个模型下拉要能**跨服务商**选（以前只问得到当前那组，配两家也
               #   永远只看得见第一家的）。见 `ai_info()` / `ai.js` 的 `modelGroups`。
               "profile": "", "providers": []}
        env_base = (os.environ.get("MOSS_AI_BASE_URL") or "").strip()
        env_model = (os.environ.get("MOSS_AI_MODEL") or "").strip()
        if env_base and env_model:                 # 万一哪天界面进程也有了，直接用
            out.update({"ok": True, "source": "环境变量", "base_url": env_base.rstrip("/"),
                        "api_key": (os.environ.get("MOSS_AI_API_KEY") or "").strip(),
                        "model": env_model,
                        "models": [m.strip() for m in (os.environ.get("MOSS_AI_MODELS") or "").split(",")
                                   if m.strip()] or [env_model]})
            out["profile"] = "环境变量"
            out["providers"] = [{"name": "环境变量", "models": out["models"],
                                 "has_key": bool(out["api_key"]),
                                 "base_url": out["base_url"]}]
        else:
            r = _run_capture_split(HOST + ["--ai-config-reveal"])
            obj = _first_json((r.get("out") or "") + (r.get("err") or ""))
            if obj and obj.get("ok") and isinstance(obj.get("params"), dict):
                p = obj["params"]
                models = [str(m).strip() for m in (p.get("model") or []) if str(m).strip()]
                out.update({"ok": bool(models and p.get("base_url")), "source": "宿主",
                            "base_url": str(p.get("base_url") or "").rstrip("/"),
                            "api_key": str(p.get("api_key") or ""), "model": models[0] if models else "",
                            "models": models, "profile": obj.get("profile") or "",
                            "why": "" if models and p.get("base_url")
                                   else "AI 配置里接口地址 / 模型没填全"})
                # ★ `V-386`：**每一组**各自配了哪些模型。宿主 `--ai-config` 已经一起给了
                #   `summary`（每组：地址 / 模型 / 有没有 key），所以这里**不用再起一个进程**
                #   —— `ai_info` 是每 700ms 一跳的，多一趟就是灾难。
                profs = []
                for nm, one in (obj.get("summary") or {}).items():
                    if not isinstance(one, dict):
                        continue
                    ms = [str(x).strip() for x in (one.get("model") or []) if str(x).strip()]
                    profs.append({"name": nm, "models": ms,
                                  "has_key": bool(one.get("has_key")),
                                  "base_url": str(one.get("base_url") or "").rstrip("/")})
                # 当前那组排最前（下拉第一眼就是正在用的那家），其余按名字。
                _cur = str(obj.get("active") or obj.get("profile") or "")
                profs.sort(key=lambda x: (x["name"] != _cur, x["name"]))
                out["providers"] = profs
            else:
                out["why"] = "读不到 AI 配置 —— 去「设置 → AI」配一组（挑一家、把 key 填上）"
        _AI_CFG.update({"t0": now, "got": out})
        return out

    def ai_budget(self, save=None):
        """这次任务的预算（`V-239`）：**按 token 上限算**（你定的：步数不好换算成钱）。

        实现搬到了 `system/ui/ai/ai_budget.py`（`core/snap.py` 那种"一份实现两处用"）——
        这样探针不必 import 整个界面就能验它。出厂默认 **20 万 token**、到 80% 劝一次收尾。
        """
        try:
            ai_dir = str(HERE / "ai")
            if ai_dir not in sys.path:
                sys.path.insert(0, ai_dir)
            import ai_budget
            if save is None:
                cur = ai_budget.load()
                return dict(cur, ok=True, warn=ai_budget.warn_at(cur.get("max_tokens")))
            return ai_budget.save(save)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "预算读不出来：%s" % e}

    def ai_set_budget(self, max_tokens=200000):
        """界面上那一格"token 上限"调的（就一个数，改完立刻生效）。"""
        return self.ai_budget(save=max_tokens)

    def ai_info(self, workdir="", refresh=False):
        """这一页要显示的东西：模型 / 提示词（含缺失）/ 能写哪儿 / 预算 / 在不在跑。

        ★ `V-307`：多三样 —— **权限模式 + 放行清单 + 临时空间**（还有"这条会话算谁的"）。
        """
        out = {"ok": True, "running": bool(AI.get("thread") and AI["thread"].is_alive()),
               "workdir": str(workdir or ""), "steps": 0}
        try:
            _c, e, _l = self._ai_mods()
            out["home"] = str(e.HOME)
            out["write_root"] = str(e.write_root())
            bud = self.ai_budget()
            out["max_tokens"] = bud.get("max_tokens")
            out["warn_tokens"] = bud.get("warn")
            # ★ `V-316`：权限清单（读/写勾选）+ 临时空间（现读 —— 改完要立刻看见）
            # ★ `V-314`：临时空间**按插件分**（`state/<包id>/ai/tmp/`），所以要带 workdir
            try:
                M = self._ai_mode()
                # ★ `V-343`：这里**不再** `ensure_pkg()` —— `ai_info` 是个**只读查询**，
                #   每 700ms 一跳、换一次选中的包就调一次；在里面写盘等于
                #   "在左边点过一遍包列表，权限清单就长满了"（用户报的那个）。
                #   现在"当前这个包"由 `summary(workdir)` **算出来**（第一条），不落盘。
                out.update(M.summary(workdir))
            except Exception as exc:                                      # noqa: BLE001
                out["mode_why"] = "权限模块起不来：%s" % exc
            # ★ `V-307`：这条会话是"哪个包"的（历史按它分桶 —— 用户要的"只看这个模块的历史"）
            try:
                R = self._ai_runs()
                out["scope"] = {k: (str(v) if k == "dir" else v)
                                for k, v in R.scope_of(workdir).items()}
            except Exception:                                             # noqa: BLE001
                out["scope"] = {"kind": "all", "id": "", "dir": "", "label": "整个项目区"}
            # ★ 顺序要紧（`V-252`）：下面两处都要用 `p`，而 `p` 原来是在**这之后**才赋值的
            #   ⇒ `UnboundLocalError` 被那个 `except: pass` 吞掉，`context` / `compact_at`
            #   从来就没带上过（界面上那一行"上下文 xx / yy（zz%）"一直吃的是默认值）。
            p = self.ai_params(refresh=bool(refresh))
            # `V-244`：上下文窗口和两条线（DSH 的 80% / 16%）—— 那一小行提示要用
            try:
                import ai_budget as _b2
                _m = str(p.get("model") or "")
                out["context"] = _b2.context_window(_m, bud.get("context") or 0)
                out["compact_at"] = _b2.compact_at(_m, out["context"])
                out["retain_tokens"] = _b2.retain_tokens(_m, out["context"])
            except Exception:                                          # noqa: BLE001
                pass
            out["model"] = p.get("model") or ""
            # ★ `V-252`：**这一家配了哪些模型**（`core/config.py` 里 model 可以是一串）——
            #   顶栏那个模型下拉用它。只有一条就只显示那一条。
            _ms = [str(x).strip() for x in (p.get("models") or []) if str(x).strip()]
            if not _ms and out["model"]:
                _ms = [out["model"]]
            out["models"] = _ms
            # ★ `V-386`：**所有**服务商 + 各自模型 —— 顶栏那个下拉按家分组；选别家的模型
            #   就顺手把那家设为当前（`ai.js` 的 `pickModel()`）。`profile` 标着当前是哪家。
            out["providers"] = p.get("providers") or []
            out["profile"] = p.get("profile") or ""
            out["base_url"] = p.get("base_url") or ""
            out["has_key"] = bool(p.get("api_key"))
            out["key_from"] = p.get("source") or ""
            out["why"] = p.get("why") or ""
            used, missing = [], []
            task = (AI.get("task") or "")
            text, _u, miss = _l.compose_system(task or "随便")
            out["prompts"] = [Path(u.split(" ← ")[-1]).name for u in _u]
            out["missing_prompts"] = miss or _l.missing_prompts(list(_l.BASE_PROMPTS))
            out["prompt_bytes"] = len(text or "")
        except Exception as exc:                                          # noqa: BLE001
            out["ok"] = False
            out["msg"] = "AI 模块起不来：%s: %s" % (type(exc).__name__, exc)
        st = AI.get("state")
        if st:
            out["steps"] = len(st.get("steps") or [])
        return out

    def ai_start(self, task="", workdir="", max_tokens=None, continue_id="", model="", attachments=None):
        """开始一次任务（后台线程跑 loop，界面靠 `ai_poll` 拿步骤流）。

        ★ **收尾不变量（`V-423`，用户反复报过）**：`state["running"]` 不许在最终
          `state["result"]` 就绪之前改成 `False`。页面只在 `running=true` 时轮询；
          如果先报"结束"、过一会儿才写入结果，页面会在中间那一拍停问，最终结论卡
          永远不出现（只能点历史会话从盘上读回来）。收尾写盘慢（几十 MB 记录）时
          这个空窗很容易被撞上，所以两件事必须在同一把锁里一起发布。

        `workdir`：这次在哪儿干活 —— 当前选中的包目录（`user_data/pkgs/<包>` 或
            `system/pkgs/<包>`），或者 `user_data/pkgs`（新建包）。
        `max_tokens`：这次任务的 token 上限（不给就读 `user_data/ai/budget.json`，默认 20 万）。
        `continue_id`（`V-251`）：**接着哪条记录聊** —— 把那条记录里的对话（`messages`）
            接上去，然后这次的任务作为新的一句追加在后面。空 = 新开一条。
        `model`（`V-252`）：**这次用哪个模型**（顶栏那个下拉）。空 = 用这家配置里的第一个。
            换模型连带换上下文窗口（压缩那条线按模型算，见 `ai_budget.context_window`）。
        ★ 为什么必须有：你原话「怎么还是找不到历史会话记录，一旦重新打开 moss 只能重新再来
          —— 你见哪个 AI 助手连历史记录都没有的？」。以前存了"任务 + 步骤流"，但**对话本身
          没存**，所以只能"看"，不能"接着说"。
        写权限是**那份权限清单**说了算（`ai_mode.can_write`）：两个 `pkgs` 根
        （`user_data/pkgs` + `system/pkgs`）下的**当前这个包**默认读写都开（`V-347` 起出厂包
        也一样），硬锁那几处照旧写不了。
        """
        task = str(task or "").strip()
        # ★ 附件：界面只送轻量元数据；图片/文本的正文在这里截断保护，路径附件交给 loop 现读。
        raw_atts = attachments if isinstance(attachments, list) else []
        atts = []
        for a in raw_atts[:20]:
            if not isinstance(a, dict):
                continue
            kind = str(a.get("kind") or "").strip()
            name = str(a.get("name") or "").strip()[:120] or "附件"
            one = {"kind": kind, "name": name,
                   "mime": str(a.get("mime") or "").strip()[:100]}
            try:
                one["size"] = int(a.get("size") or 0)
            except (TypeError, ValueError):
                one["size"] = 0
            if kind == "path":
                pth = str(a.get("path") or "").strip()
                if not pth:
                    continue
                one["path"] = pth
            elif kind == "text":
                text = str(a.get("text") or "")
                if not text:
                    continue
                one["text"] = text[:120000]
                one["size"] = len(text)
            elif kind == "data":
                data_url = str(a.get("data_url") or "")
                if not data_url or len(data_url) > 20 * 1024 * 1024:
                    continue
                one["data_url"] = data_url
            else:
                continue
            atts.append(one)
        if not task and atts:
            task = "请分析我发来的附件。"
        if not task:
            return {"ok": False, "msg": "先写一句你要它干什么，或者加个附件。"}
        with AI_LOCK:
            if AI.get("thread") and AI["thread"].is_alive():
                return {"ok": False, "msg": "已经在跑了 —— 等它完，或者按「停止」。"}
            try:
                c, e, l = self._ai_mods()
                p = self.ai_params(refresh=True)
                if not (p.get("base_url") and p.get("model")):
                    return {"ok": False, "msg": p.get("why") or
                            "还没配 AI —— 去「设置 → AI」挑一家、把 key 填上。"}
                # `V-252`：顶栏选的那个模型优先（列表里没有也照样发 —— 网关可能支持别名，
                #   真发不出去时错误会照实回来，比在这儿瞎拦强）
                _use_model = str(model or "").strip() or p["model"]
                client = c.Client(p["base_url"], p.get("api_key") or "", _use_model)
            except Exception as exc:                                      # noqa: BLE001
                return {"ok": False, "msg": "AI 起不来：%s" % exc}
            wd = str(workdir or "").strip() or str(e.write_root())
            # ★ `V-251`：要接着哪条聊 —— 把那条记录里的对话取出来（取不到就当新开一条，
            #   但要**如实说一声**，别让用户以为"它还记着"）。
            # ★ `V-259`：`cont_note` 现在会**跟着结果回到界面**（原来只在 `say` 里飘一下，
            #   而界面根本不显示 `say` ⇒ "它到底接着没有"用户完全看不出来）。
            hist, cont_from, cont_note = [], "", ""
            cid = str(continue_id or "").strip()
            if not cid:
                cont_note = "新会话（没带之前的对话）"
            else:
                try:
                    rec = self._ai_runs().get(cid)
                    if not rec:
                        cont_note = "接不上上次那条（没找到那条记录）—— 这次按新会话跑"
                    else:
                        hist = [m for m in (rec.get("messages") or [])
                                if isinstance(m, dict) and m.get("role")]
                        
                        # ★ 修复残缺会话：如果上一次在等待工具/权限时被强退，
                        #   末尾会有未闭合的 tool_calls，下次继续聊时 OpenAI 会报 HTTP 400。
                        _pending = {}
                        for m in hist:
                            r = m.get("role")
                            if r == "assistant" and m.get("tool_calls"):
                                for c in m.get("tool_calls"):
                                    _pending[c.get("id")] = True
                            elif r == "tool":
                                _pending.pop(m.get("tool_call_id", ""), None)
                            else:
                                _pending.clear()
                        if _pending:
                            while hist:
                                r = hist[-1].get("role")
                                if r == "tool":
                                    hist.pop()
                                elif r == "assistant" and hist[-1].get("tool_calls"):
                                    hist.pop()
                                    break
                                else:
                                    break

                        if hist:
                            cont_from = cid
                            cont_note = "接着上次那条聊（它还记着之前 %d 条对话）" % len(hist)
                        else:
                            cont_note = "接不上上次那条（那条记录里没存对话）—— 这次按新会话跑"
                except Exception as exc:                                  # noqa: BLE001
                    cont_note = "接不上上次那条（%s）—— 这次按新会话跑" % exc
            bud = self.ai_budget()                       # 预算：界面给就听界面的，否则读存的
            cap = int(max_tokens or bud.get("max_tokens") or 200000)
            # ★ `V-244`：上下文压缩照 DSH 的参数 —— 触发线 = 窗口 × 0.8、逐字保留 = 窗口 × 0.16
            import ai_budget as _bud
            _model = str(getattr(client, "model", "") or "")
            _ctx = _bud.context_window(_model, bud.get("context") or 0)
            _at = _bud.compact_at(_model, _ctx)
            _retain = _bud.retain_tokens(_model, _ctx)
            # ---- `V-307`：这次跑的 id / 临时空间 / 权限模式 / 提问桥 / 每步落盘 --------
            # ★ 为什么 id 要在**开工这一刻**定下来：每步落盘（`save_live`）和跑完那条正式
            #   记录必须是**同一个文件** —— 用户强制重启那次丢记录，就是因为原来只有收尾写一次。
            M = self._ai_mode()
            R = self._ai_runs()
            run_id = R.new_id()
            scope = R.scope_of(wd)
            M.begin_run(wd)                      # 清掉上一跑的"只允许这一次"+ 收拾这个桶的旧 tmp
            tmp_dir = M.ensure_tmp(run_id, wd)   # `V-314`：tmp 跟着插件走（`state/<包id>/ai/tmp/`）
            started = time.time()
            base = {
                "id": run_id, "task": task, "workdir": wd,
                "attachments": [{"name": a.get("name"), "kind": a.get("kind"),
                                 "size": a.get("size") or 0} for a in atts],
                "model": str(getattr(client, "model", "") or ""),
                "max_tokens": cap, "started": started,
                "started_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
                # `V-316`：这次是不是"放手"（清单里勾了任意路径的写）—— 记一条账
                "mode": "free" if M.wildcard_write() else "limited",
                "tmp_dir": str(tmp_dir or ""),
                "scope": scope.get("kind"), "scope_id": scope.get("id") or "",
                "asked_continue": cid, "continue_note": cont_note,
            }
            AI.update({"task": task, "stop": False, "t0": started,
                       "task_dir": wd,
                       "max_tokens": cap, "context": _ctx,
                       "compact_at": _at, "retain_tokens": _retain,
                       "run_id": run_id, "scope": scope, "tmp": str(tmp_dir or ""),
                       "asker": None, "loop": None,
                       "state": {"running": True, "steps": [], "result": None, "say": [],
                                 "phase": "", "snapshot": None, "ask": None,
                                 "usage": {}, "killed": [], "stopping": False}})

            def on_step(row):
                with AI_LOCK:
                    AI["state"]["steps"].append(row)

            def say(line):
                with AI_LOCK:
                    AI["state"]["say"].append(str(line)[:300])
                    if len(AI["state"]["say"]) > 400:
                        del AI["state"]["say"][:200]

            def phase(what):
                # `V-242`：让页面分得清"模型在想"和"执行工具" —— 前者可能要等十几秒，
            #   以前看起来就是"卡死了"（用户原话：卡很久了没动作）。
                with AI_LOCK:
                    AI["state"]["phase"] = str(what)

            def on_snapshot(got):
                # ★ `V-250`：开工前那条快照**存好就告诉页面** —— 「版本快照」那一列要跟着刷新。
                #   以前只有跑完才从 `result.snapshot` 里知道，而快照是**动手之前**就存了的，
                #   于是"存是存了，切过去看不见"（用户原话："没有刷新 所以我是看不到它刚刚做的快照"）。
                with AI_LOCK:
                    AI["state"]["snapshot"] = got

            def on_ask(q):
                """`V-308`：它现在挂着一个问题等人答（`None` = 没在问）。界面照这个画卡片。

                ★ `V-333`：**问答也进聊天记录** —— 问题一出现就往步骤流插一条 `ask` 记录行，
                  答完（或超时/停止）把结果写回同一条；这样界面上它是"它说的"一条气泡，
                  翻旧会话还能看见你当时选了什么。
                """
                with AI_LOCK:
                    AI["state"]["ask"] = q
                    if q is None:
                        _r = AI["state"].pop("ask_row", None)
                    else:
                        _r = None
                if q is None:
                    if _r:                              # 没答上（超时 / 停止 / 界面走了）
                        try:
                            if not _r.get("done"):
                                _r.update({"done": True, "answer": "",
                                           "out": "（这问题没等到回答：超时或已停止）"})
                        except Exception:                # noqa: BLE001
                            pass
                    return
                try:
                    _loop = AI.get("loop")
                    if _loop is None:
                        return
                    _row = _loop.note(
                        "ask", str(q.get("question") or "（它有个问题）"),
                        why=str(q.get("why") or ""),
                        args={"qid": str(q.get("qid") or ""),
                              "kind": str(q.get("kind") or "ask"),
                              "options": list(q.get("options") or []),
                              "allow_text": bool(q.get("allow_text")),
                              "detail": str(q.get("detail") or "")},
                        out="（在等你回答…）")
                    with AI_LOCK:
                        AI["state"]["ask_row"] = _row
                except Exception:                                        # noqa: BLE001
                    pass

            def on_journal(part, force=False):
                """`V-307`：**每步落盘** —— 重启 moss 之后这条记录还在（标"上次没跑完"）。"""
                rec = dict(base)
                rec.update({"steps": part.get("steps") or [],
                            "usage": part.get("usage") or {},
                            "messages": part.get("messages") or [],
                            "files": part.get("files") or [],
                            "procs": part.get("procs") or [],
                            "killed": part.get("killed") or [],
                            "snapshot": part.get("snapshot"),
                            # ★ `V-382`：快照没存上的原因（结论卡上的告警要用）
                            "snapshot_note": part.get("snapshot_note") or ""})
                if force:
                    rec["continue_note"] = cont_note
                R.save_live(rec, scope)
                with AI_LOCK:
                    AI["state"]["usage"] = dict(part.get("usage") or {})

            asker = self._ai_ask().Asker(publish=on_ask, stop_check=lambda: bool(AI.get("stop")))
            AI["asker"] = asker
            # ★ `V-316`：权限**现读**（用户可能跑到一半去勾/取消勾）——`mode_fn` 只剩
            #   "是不是放手"这一个问题，由清单里「任意路径」那一行回答。

            def mode_now():
                return "free" if M.wildcard_write() else "limited"

            def work():
                loop = l.Loop(client, workdir=wd, max_tokens=cap,
                              compact_at=_at, retain_tokens=_retain,
                              on_step=on_step, say=say, on_phase=phase,
                              on_snapshot=on_snapshot,
                              stop_check=lambda: bool(AI.get("stop")),
                              asker=asker, mode_fn=mode_now, on_journal=on_journal,
                              run_id=run_id, tmp_dir=str(tmp_dir or ""),
                              perm_gate=self._ai_perm_wait)
                AI["loop"] = loop
                got = {}
                try:
                    if cont_note:
                        say(cont_note)
                    got = loop.run(task, history=hist, from_id=cont_from, attachments=atts)
                    # ★ `V-259`：这两条**跟着结果回界面**（界面把它显示在「用户指令」卡旁边）——
                    #   用户一眼就能看出"这次到底接着没有"，不用猜、也不用等出问题再查盘。
                    got["continue_note"] = cont_note
                    got["asked_continue"] = cid
                except Exception as exc:                                  # noqa: BLE001
                    got = {"ok": False, "reason": "%s: %s" % (type(exc).__name__, exc),
                           "steps": [], "usage": {}, "files": []}
                finally:
                    # ★ `V-307`：**不管怎么收的场，子进程一个不留**（`loop.cleanup` 已经杀过一遍，
                    #   这里再兜一次，并且把"杀掉几个"如实带给界面）。
                    try:
                        k = loop.cleanup("收尾")
                        got["procs_killed"] = got.get("procs_killed") or k.get("pids") or []
                    except Exception:                                      # noqa: BLE001
                        pass
                    AI["loop"] = None
                    with AI_LOCK:
                        # ★ `V-423`：**先别把 running 落回 False**。
                        #   收尾还要把最终记录写盘；大记录（几十 MB）可能要好几秒。
                        #   以前这里先报 running=false、result 仍是 None，而页面只在
                        #   running=true 时轮询 ⇒ 那一跳之后再也不问，结论卡永远不出现，
                        #   只能去点历史会话把它从盘上读回来。结果和 running 必须
                        #   **在同一把锁里一起交出去**（见下面最后那段）。
                        AI["state"]["ask"] = None
                        AI["state"]["stopping"] = False
                    try:
                        asker.cancel("finished")
                    except Exception:                                      # noqa: BLE001
                        pass
                    try:
                        M.clear_temp()                     # "只允许这一次"随这次跑结束
                    except Exception:                                      # noqa: BLE001
                        pass
                # ★ `V-243`：跑完**落盘**（你说的"历史记录不保存是不行的"—— 原来只在内存里，
                #   moss 一重启，任务原文/步骤流/结论/token 全没了）。存不上也不影响结果。
                try:
                    rec = dict(base)
                    rec.update({
                        "seconds": round(time.time() - started, 1),
                        "stopped": bool(AI.get("stop")),
                        "ok": bool(got.get("ok")), "reason": got.get("reason") or "",
                        # ★ `V-269`：`kind="chat"` = 只是回答问题（没动文件、没验收）——
                        #   界面拿它把结论卡写成「💬 回答」，也不显示"开工快照"那一行。
                        "kind": got.get("kind") or "work",
                        "summary": got.get("summary") or "", "caveats": got.get("caveats") or "",
                        "usage": got.get("usage") or {}, "files": got.get("files") or [],
                        "snapshot": got.get("snapshot"), "steps": got.get("steps") or [],
                        # ★ `V-382`：没存上快照的原因（结论卡据此告警"这次没有退路"）
                        "snapshot_note": got.get("snapshot_note") or "",
                        "folded": got.get("folded") or 0,
                        # ★ `V-251`：这条会话的对话本身 + 从哪条接过来的 ——
                        #   「接着聊」靠它，重启 moss 也不会"只能重新再来"。
                        "messages": got.get("messages") or [],
                        "continued_from": got.get("continued_from") or "",
                        "asked_continue": got.get("asked_continue") or "",
                        "continue_note": got.get("continue_note") or "",
                        # ★ `V-307`：杀掉了哪些进程 / 这次是哪个模式跑的（用户要看得见）
                        "procs_killed": got.get("procs_killed") or [],
                        "edited": got.get("edited") or 0,
                    })
                    saved = R.save(rec, scope)
                    got["run_id"] = saved.get("id") or run_id
                except Exception as exc:                                  # noqa: BLE001
                    got["run_id"] = run_id
                    got["save_error"] = "%s: %s" % (type(exc).__name__, exc)
                with AI_LOCK:
                    # ★ `V-423`：最终结果和 `running=false` **同一拍**交给页面。
                    #   分开写的那段空窗，正好会让"结束但没结论卡"复现。
                    AI["state"]["result"] = got
                    AI["state"]["running"] = False

            th = threading.Thread(target=work, daemon=True)
            AI["thread"] = th
            th.start()
            # ★ 别在这儿假设 client 长什么样（`V-233` 探针用假模型时踩到）：
            #   线程已经起来了，这里再抛异常的话，页面会看到"起不来"而其实任务已经在跑。
            return {"ok": True, "workdir": wd, "model": str(getattr(client, "model", "") or ""),
                    "run_id": run_id, "mode": mode_now(), "tmp": str(tmp_dir or ""),
                    "scope": scope.get("label") or ""}

    def ai_poll(self):
        """当前这次任务的进度（步骤流 + 结果）。界面每半秒问一次。

        ★ **返回不变量（`V-423`）**：只要这里回 `running=False`，同一次返回里就必须
          已经带着最终 `result`（除非真的从未开跑、`idle=True`）。不要为了"让顶栏
          早点停"而提前把 running 落成 false —— 页面会停止轮询。

        ★ `V-307`/`V-308`：多回几样 —— **活的 token 账**（不用等跑完才看得到数字）、
          **现在挂着的问题**（它问你话的那张卡）、权限模式、临时目录、杀掉过哪些进程。
        """
        with AI_LOCK:
            st = AI.get("state")
            if not st:
                return {"ok": True, "running": False, "idle": True, "steps": [], "say": []}
            asker = AI.get("asker")
            ask = st.get("ask")
            # ★ `V-319` 修：`asking`（已经等了几秒）**只有 `Asker.state()` 会算**，
            #   而 `st["ask"]` 是 publish 那一份原件 ⇒ 以前界面上是"已经等了 秒"（数字空着）。
            if asker is not None:
                try:
                    # The Asker is authoritative. Do not fall back to the stale
                    # published copy after an answer/timeout has cleared its queue.
                    ask = asker.state()
                except Exception:                                        # noqa: BLE001
                    ask = None
            # ★ `V-319` 退路：`st["ask"]` 还在、可 asker 那边已经收工时，也把秒数算出来
            #   （不然又是"已经等了 秒"那种空数字）。
            if ask and "asking" not in ask and ask.get("at"):
                try:
                    ask = dict(ask, asking=round(time.time() - float(ask.get("at")), 1))
                except (TypeError, ValueError):
                    pass
            perm = AI.get("perm")
            if perm:
                perm = dict(perm, asking=round(time.time() - float(perm.get("at") or time.time()), 1))
            return {"ok": True, "running": bool(st.get("running")),
                    "task": AI.get("task") or "", "steps": list(st.get("steps") or []),
                    "say": list(st.get("say") or [])[-40:], "result": st.get("result"),
                    "phase": st.get("phase") or "",
                    # ★ `V-250`：开工前那条快照（一存好就有，不用等跑完）——
                    #   界面拿它去刷新「版本快照」那一列。
                    "snapshot": st.get("snapshot") or None,
                    "max_tokens": int(AI.get("max_tokens") or 0),
                    "context": int(AI.get("context") or 0),
                    "compact_at": int(AI.get("compact_at") or 0),
                    "retain_tokens": int(AI.get("retain_tokens") or 0),
                    "prompt_tokens": int((st.get("steps") or [{}])[-1].get("ptok") or 0)
                                      if st.get("steps") else 0,
                    # ---- `V-307`：活的那几样 ----
                    "usage": dict(st.get("usage") or {}),
                    "ask": ask,
                    "asker": bool(asker is not None and asker.busy()),
                    # ★ `V-319`：**待允许的目录**（左下角清单里那一行要闪烁）
                    "perm": perm,
                    "mode": str(AI.get("mode") or ""),
                    "run_id": str(AI.get("run_id") or ""),
                    "tmp": str(AI.get("tmp") or ""),
                    "killed": list(st.get("killed") or []),
                    "stopping": bool(st.get("stopping")),
                    # `V-316`：现在是不是放手（界面不再有"模式"这一格，但轮询里带着它，
                    # 让页面能显示"它现在能不能放手写"）
                    "wildcard": self._ai_wildcard(),
                    "skills_rev": self._skills_rev(),
                    "seconds": round(time.time() - float(AI.get("t0") or time.time()), 1)}

    def ai_runs(self, limit=30, workdir=""):
        """跑过的那些任务（`V-243`：重启 moss 还在）。列表**不带步骤流**，那个用 `ai_run(id)`。

        ★ `V-307`：**只看"这个干活的地方"那些** —— 用户原话「我在 github 可视化助手这里
          使用了 ai 那么在历史这里 按说 它应该只要显示这个模块下的历史就可以了
          不需要其他的插件的 ai 对话也显示出来」。
          同时**顺手把老记录归位一次**（`migrate_once`：按 `workdir` 搬进各自的包目录）。
        """
        try:
            R = self._ai_runs()
            try:
                R.migrate_once()
            except Exception:                                            # noqa: BLE001
                pass
            scope = R.scope_of(workdir or self._ai_last_workdir())
            return {"ok": True, "runs": R.list_runs(limit=int(limit or 30), scope=scope),
                    "scope": {k: (str(v) if k == "dir" else v) for k, v in scope.items()}}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "runs": [], "msg": "读不到历史：%s" % e}

    def _ai_last_workdir(self):
        """界面没带 `workdir` 时兜底：用这次会话（或最近一次）干活的那个目录。"""
        wd = str(AI.get("task_dir") or "")
        if wd:
            return wd
        sc = AI.get("scope") or {}
        try:
            if sc.get("kind") == "pkg" and sc.get("id"):
                return str(HERE.parent / "pkgs" / str(sc["id"]))
        except Exception:                                                # noqa: BLE001
            pass
        return ""

    # ------------------------------------------------ 权限模式 / 放行清单（`V-307`）
    def ai_mode_get(self, workdir=""):
        """权限清单 + 临时空间（界面右下角那一块）。

        ★ `V-316`：顺手**把当前这个包自动加进清单**（读+写都开）—— 你打开某个插件点 AI，
          意思就是"我要改它"，不该还要你自己去加一条。
        """
        try:
            M = self._ai_mode()
            return M.summary(workdir or self._ai_last_workdir())
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_allow(self, path="", read=None, write=None, why="", action="add", force=False):
        """权限清单：`action` = `add` / `set`（改勾选）/ `rm`（删掉）/ `deny`（**拒绝一次请求**）。

        ★ `V-316`：**读 / 写各一个勾**，不再有"模式"那种第二个开关控同一件事。
          `path="*"` 那一行就是"任意路径"（勾上写 = 放手）。
        ★ `V-325`：`deny` 是给"请求那一条上的「拒绝」"用的 —— 它**不改清单**（用户之前批过的
          读还在），只在宿主这边记一笔"这条请求被拒了"，闸（`_ai_perm_wait`）当场就能判 `denied`。
          以前是"把那一行删掉 = 拒绝"，可是第二次请求（要写）时那一行本来就存在（只读），
          删了等于把用户批过的读也一起收了 —— 不对。
        """
        try:
            M = self._ai_mode()
            a = str(action or "add")
            if a == "deny":
                key = _perm_key(path)
                with AI_LOCK:
                    _PERM_DENY[key] = time.time()
                cur = M.find(path)
                if cur is not None and cur.get("pending"):
                    M.allow_rm(path)                 # 这趟刚摆的"待允许"⇒ 收走（列表里本来不画它）
                return {"ok": True, "msg": "已拒绝 —— 这次不放行，原来的权限不变",
                        "summary": M.summary(self._ai_last_workdir())}
            if a == "rm":
                got = M.allow_rm(path)
            else:
                # ★ `V-319`：他勾了读/写（或加了一条）⇒ 那一行不再是"待允许"，闪烁收掉
                _pend = False if (read is not None or write is not None) else None
                # ★ `V-343`：`add=True` 一直是"不存在就建、存在就改"（upsert）——
                #   "当前这个包"那条在清单里本来**没有**（它是算出来的），
                #   用户一动它的开关就得能建出来，所以 `set` 也走 upsert。
                # ★ `V-344`：`force` = "这是**用户主动加的**"（拖进来 / 手输）——
                #   让这条记录把归属和说明都改成用户的，别继承以前那条 `by="ai"` 的 why。
                got = M.allow_set(path, read=read, write=write, why=str(why or ""),
                                  by="user", add=True, pending=_pend, force=bool(force))
            return dict(got, summary=M.summary(self._ai_last_workdir()))
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_full_access(self, on=True):
        """切「完全权限（无人值守）」：路径全开 + 危险操作不问 + 技能自动批准。

        ★ 和清单里单独勾「任意路径」不同：那个只给文件系统权限；这个还要让
          `skill_lib` 把 AI 新建 / 修改的技能动态判成已批准（不会写死进授权表，
          关掉开关后就会回到按指纹授权）。
        """
        try:
            M = self._ai_mode()
            got = M.set_full_access(bool(on))
            return dict(got, summary=M.summary(self._ai_last_workdir()))
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_allow_pick(self):
        """**选一个文件夹**加进放行清单（点「+ 加目录」那颗按钮）。

        ★ 用 pywebview 的原生目录选择框（`window.create_file_dialog`）—— 用户原话
          "允许通过添加或者拖动的方式 增加放行的路径"。拖动那条由界面接（`ai_allow`）。
        ★ 拿不到对话框（老 webview / 无 GUI）就如实说，让用户手打路径 —— 不静默失败。
        """
        try:
            import webview as _wv
            win = webview.windows[0] if getattr(webview, "windows", None) else None
            if win is None or not hasattr(win, "create_file_dialog"):
                return {"ok": False, "msg": "这个环境没有目录选择框 —— 把路径粘到输入框里也一样"}
            # ★ 这个版本的 pywebview 里 `FOLDER_DIALOG` **已弃用**（用它会在 stderr 打一行
            #   deprecation 告警）—— 优先用新的 `FileDialog.FOLDER`，拿不到再退回老常量。
            _kind = getattr(getattr(_wv, "FileDialog", None), "FOLDER", None)
            if _kind is None:
                _kind = getattr(_wv, "FOLDER_DIALOG", 20)
            got = win.create_file_dialog(_kind, allow_multiple=False)
            if not got:
                return {"ok": False, "msg": "没选（取消了）", "cancel": True}
            p = got[0] if isinstance(got, (list, tuple)) else got
            M = self._ai_mode()
            # ★ `V-328`：这里原来写的是 `allow_add(p, on=True, …)` —— `allow_add` 根本没有
            #   `on` 这个参数（`V-316` 起就是 `read` / `write` 了）⇒ 每次「选目录…」都会
            #   TypeError 被 except 兜住、报一句"选不了目录"。现在按真签名来（读+写都开）。
            r = M.allow_add(p, read=True, write=True, why="你选目录加的", by="user", force=True)
            return dict(r, summary=M.summary())
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "选不了目录：%s: %s" % (type(e).__name__, e)}

    def ai_tmp(self, action="info", run_id="", workdir=""):
        """AI 的临时空间：`info` / `open` / `clean`（用户要一个"能放心清理"的 tmp）。

        ★ `V-314`：它是**这个插件自己的**那一格（`state/<包id>/ai/tmp/`），
          所以三样操作都要带 `workdir` —— 清 A 包的临时文件不会碰 B 包的。
        """
        try:
            M = self._ai_mode()
            wd = str(workdir or self._ai_last_workdir())
            if action == "open":
                p = M.tmp_root(wd)
                p.mkdir(parents=True, exist_ok=True)
                os.startfile(str(p))                                    # noqa: S606
                return {"ok": True, "msg": "打开了 %s" % p, "tmp": M.tmp_size(wd)}
            if action == "clean":
                got = M.tmp_clean(str(run_id or ""), wd)
                return dict(got, tmp=M.tmp_size(wd))
            return {"ok": True, "tmp": M.tmp_size(wd)}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def _ai_perm_wait(self, path, why="", need="write", timeout=1800):
        """**权限请求的闸**：请求出现在**权限卡上半段那一条**（琥珀底 + 允许 / 拒绝），等他点。

        ★ `V-323`/`V-325`（用户把界面设计重发并说清了流程）：点「允许」⇒ 那一条消失、目录进
        下面清单；点「拒绝」⇒ 那一条消失、清单里什么都不加。宿主这边靠**现读清单**判：
        勾上了 = 放行、那条没了 = 拒绝。

        回 `{granted, read, write, reason, seconds}`；`reason` = `ok` / `read-only` /
        `denied` / `stopped` / `timeout`。

        ★★ **写权限必须"问过一次"才算数**（用户报的：先批了读、随后它要写，
        "它尝试写入也没问 直接失败了"）：老逻辑看到那一行已经是"只读"就**当场**回
        `read-only`，于是他根本没机会点「允许」。现在：
          · 进来先记下**请求前那一行是什么样**（`base_read`）；
          · 要写、而那一行本来就只读 ⇒ **照问**（照旧阻塞，等他点允许/拒绝），
            只有"等待期间他自己勾了读、写还关着"才算 `read-only`；
          · 原来就没有那一行 ⇒ 由 `allow_pending_add` 摆一条待允许的（界面不画它，闸要用）。
        """
        M = self._ai_mode()
        need_w = str(need or "write") != "read"
        # ★ `V-328`：路径本身不合法（乱打的 / 不存在 / 不是目录）⇒ **别摆请求**，当场回它
        #   `bad-path`（工具那边会把这句话原样还给模型，让它先去确认路径）。
        problem = None
        try:
            problem = M.path_problem(path)
        except Exception:                                            # noqa: BLE001
            problem = None
        if problem:
            return {"granted": False, "reason": "bad-path", "msg": problem,
                    "read": False, "write": False, "seconds": 0.0}
        try:
            base = M.find(path)
        except Exception:                                            # noqa: BLE001
            base = None
        base_read = bool((base or {}).get("read"))
        base_write = bool((base or {}).get("write"))
        try:
            M.allow_pending_add(path, why=why, need=need)
        except Exception:                                            # noqa: BLE001
            pass
        t0 = time.time()
        key = _perm_key(path)
        # ★ `V-333`：**请求本身也进聊天记录**（用户原话："申请权限 … 直接在聊天记录上进行
        #   渲染交互 … 我选择以后 后续我翻看聊天记录 也能看我之前的选择"）——
        #   在这儿插一条 `perm` 记录行，答完**原地**把结果写回去（`answer` / `out` / `done`）。
        _row = None
        try:
            _loop = AI.get("loop")
            if _loop is not None:
                _tail = Path(str(path)).name or str(path)
                _row = _loop.note(
                    "perm", "请求放行「%s」" % _tail, why=str(why or ""),
                    args={"path": str(path), "need": str(need or "write")},
                    out="（在等你点「允许 / 拒绝」…）")
        except Exception:                                            # noqa: BLE001
            _row = None
        with AI_LOCK:
            _PERM_DENY.pop(key, None)        # 这一趟从干净开始（上一次的拒绝不算）
            AI["perm"] = {"path": str(path), "why": str(why or ""),
                          "need": str(need or "write"), "at": t0}
        reason, it = "timeout", None
        while True:
            if AI.get("stop"):
                reason = "stopped"
                break
            # ★ `V-325`：他在那一条请求上点了「拒绝」⇒ 当场算拒绝（**清单一个字没动**）
            with AI_LOCK:
                _denied_at = _PERM_DENY.get(key, 0.0)
            if _denied_at > t0:
                reason = "denied"
                break
            try:
                it = M.find(path)
            except Exception:                                        # noqa: BLE001
                it = None
            if it is None:
                reason = "denied"            # 那条没了（老流程的 ✕ / 用户自己删了）
                break
            if it.get("write") or (not need_w and it.get("read")):
                reason = "ok"
                break
            # ★ 只读：只有"这一趟里它才拿到的读"才算用户的选择；
            #   请求之前就是只读的（他批过读、没批写）⇒ **不算回答**，继续等（= 再问一次）。
            if need_w and it.get("read") and not base_read:
                reason = "read-only"
                break
            if time.time() - t0 > float(timeout or 1800):
                reason = "timeout"
                break
            time.sleep(0.2)
        with AI_LOCK:
            AI["perm"] = None
            _PERM_DENY.pop(key, None)        # 这一趟用完了，别留着影响下一次
        try:
            if reason != "denied":           # 拒绝那条留着他原来批过的权限；别的把这趟登记收掉
                M.allow_set(path, pending=False)
        except Exception:                                            # noqa: BLE001
            pass
        granted = reason == "ok" or (reason == "read-only" and not need_w)
        # ★ `V-333`：把结果**写回那条记录行**（聊天记录里那一问一答就齐了）
        if _row is not None:
            try:
                _ans = {"ok": "允许", "read-only": "只给了读", "denied": "拒绝",
                        "stopped": "已停止", "timeout": "没回应"}.get(reason, reason)
                _row.update({"done": True, "answer": _ans,
                             "out": "你的选择：%s（读=%s 写=%s）" % (
                                 _ans, "开" if (it or {}).get("read") or base_read else "关",
                                 "开" if (it or {}).get("write") or base_write else "关")})
            except Exception:                                        # noqa: BLE001
                pass
        return {"granted": granted, "reason": reason,
                "read": bool((it or {}).get("read")) or base_read,
                "write": bool((it or {}).get("write")) or base_write,
                "seconds": round(time.time() - t0, 1)}

    def ai_answer(self, qid="", text="", choice="", by="user"):
        """**回答它的问题**（`V-308`）。答完 loop 那边就继续跑了。"""
        with AI_LOCK:
            asker = AI.get("asker")
            cur = (AI.get("state") or {}).get("ask")
        if asker is None:
            return {"ok": False, "msg": "现在没有在等回答的问题（那次跑已经结束了）"}
        if not cur or not qid or str(cur.get("qid")) != str(qid):
            return {"ok": False, "msg": "这个问题已经过期或已经回答了，请处理当前仍在等待的问题。"}
        got = asker.submit(text=text, choice=choice, by=by)
        if got.get("ok"):
            with AI_LOCK:
                st = AI.get("state") or {}
                row = st.get("ask_row")
                if st:
                    st["ask"] = None
            # ★ `V-333`：把用户的选择写回那条记录行（聊天记录里"它问 / 我答"成对留着）
            try:
                if row is not None:
                    _what = str(choice or "") or str(text or "")
                    _args = row.get("args") or {}
                    if isinstance(_args, str):
                        try:
                            _args = json.loads(_args)
                        except (TypeError, ValueError):
                            _args = {}
                    row["options"] = list(_args.get("options") or [])
                    row.update({"done": True, "answer": _what,
                                "out": "你的回答：%s" % (_what or "（空）")})
            except Exception:                                        # noqa: BLE001
                pass
        return got

    def ai_session_messages(self, run_id=""):
        """**看这条会话喂给它的完整提示词历史**（`V-307`）。

        用户原话："我可以通过点击某个会话 来查看 这个会话喂给他的历史记录 或者叫提示词
        (包括我问的和它回答的 所有历史)"。给的就是落盘的那份 `messages`（系统提示 + 每一问
        + 它每次回的 + 工具结果），界面上按角色分色摆出来。
        """
        try:
            return self._ai_runs().messages(str(run_id or ""))
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "messages": [], "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_run(self, run_id=""):
        """一次任务的完整记录（含步骤流）—— 界面上点「看」用。

        ★ `V-251`：**不把 `messages` 发给页面**（那是整条会话，几百 KB）—— 页面只需要
          知道"这条能不能接着聊"（`cont`），真要接着聊时把 **id** 交回来，宿主自己去读。
        """
        try:
            rec = self._ai_runs().get(run_id)
            if rec:
                rec = dict(rec)
                msgs = rec.pop("messages", None) or []
                rec["cont"] = bool(msgs)
                rec["msgs"] = len(msgs)
            return {"ok": bool(rec), "run": rec, "msg": "" if rec else "没有这条记录"}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "run": None, "msg": "读不到：%s" % e}

    def ai_thread(self, run_id=""):
        """**这条记录所在的整条会话**（链头 → 这条）—— 给界面画整段对话。

        ★ `V-262`：你原话「重启以后 之前的会话历史没有丢失 但是在页面 没有显示」。
          根因：重启后界面只 `ai_run(最后那条)` ⇒ 只画最后一轮，前面几轮根本没进页面
          （标题也因此变成"最后那个问题"）。
          这里顺着 `continued_from` 一路往回走（防止环：最多 500 步），反过来输出
          `[{id, task, at, steps, result}]`。
        ★ 和 `ai_run` 一样：**不带 `messages`**（那是模型要的对话，几百 KB，页面用不着）。
        """
        try:
            R = self._ai_runs()
            rid, chain, guard = str(run_id or ""), [], 0
            while rid and guard < 500:
                rec = R.get(rid)
                if not rec:
                    break
                chain.append(rec)
                rid = str(rec.get("continued_from") or "")
                guard += 1
            chain.reverse()                                    # 链头在前（时间顺序）
            turns = []
            for r in chain:
                turns.append({
                    "id": r.get("id") or "",
                    "task": r.get("task") or "",
                    "at": r.get("started_text") or "",
                    # 每一轮的"结论卡"就照 `ai_run` 那套字段给（页面直接画）
                    "result": {"ok": bool(r.get("ok")), "reason": r.get("reason") or "",
                               "kind": r.get("kind") or "work",
                               "summary": r.get("summary") or "", "caveats": r.get("caveats") or "",
                               "files": r.get("files") or [], "usage": r.get("usage") or {},
                               "snapshot": r.get("snapshot"), "folded": r.get("folded") or 0,
                               "run_id": r.get("id") or "",
                               "continue_note": r.get("continue_note") or "",
                               "asked_continue": r.get("asked_continue") or ""},
                    "steps": r.get("steps") or [],
                })
            return {"ok": True, "turns": turns,
                    "tail": (turns[-1]["id"] if turns else ""),
                    "cont": bool((chain[-1].get("messages") if chain else None) or [])}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "turns": [], "msg": "读不到这条会话：%s" % e}

    # ------------------------------------------------ 会话：编辑 / 删除（`V-279`）
    # ★ 你定的三条（2026-10-05）：
    #   ① **编辑会话 N = 回到它自己的开工快照**（撤销它的改动）；快照没了 ⇒ 退到**再往前
    #      最近那个**（并明确告警"那之后的改动也会一起撤掉"）；
    #   ② 删镜像**只删 `by=ai` 的**，而且**回退要用的那一条保留**（用户自己存的快照一律不碰）；
    #   ③ **只允许"从链尾往回连续删"** —— 也就是任何一条 N 都只能删 `N..链尾`，中间那条
    #      不许单独删（这也正是"删 N 及其之后的所有会话"）。
    #   ★ 另外照样给**跨链告警**：回退是"整个包目录回到那一刻"，别的会话链后来做的改动
    #     也会被一起撤掉 —— 这件事跟删哪几条无关，必须说在前面。
    def _ai_chain(self, run_id):
        """`run_id` 所在那条会话链（链头 → 链尾，按时间排）。回 `[{run...}, ...]`。

        顺着 `continued_from` 往回走到头，再顺着"谁接着它"往前走。防环 500 步。
        ★ `V-307`：记录现在**按"干活的地方"分桶**存（`state/<包id>/ai/runs/`），
          所以往前找"谁接着它"要**所有桶一起看**（`everywhere=True`）。
        """
        R = self._ai_runs()
        rec = R.get(run_id)
        if not rec:
            return []
        # 往回
        back, rid, guard = [], str(run_id), 0
        while rid and guard < 500:
            r = R.get(rid)
            if not r:
                break
            back.append(r)
            rid = str(r.get("continued_from") or "")
            guard += 1
        back.reverse()                                                 # 链头在前
        head = back[0].get("id")
        # 往前（谁接着它 + 接着下一代……），按时间排序
        rows = R.list_runs(limit=2000, with_steps=False, everywhere=True)
        kids = {}
        for r in rows:
            p = str(r.get("continued_from") or "")
            if p:
                kids.setdefault(p, []).append(r)
        chain, seen, queue = [], set(), [head]
        while queue:
            cur = queue.pop(0)
            if not cur or cur in seen:
                continue
            seen.add(cur)
            r = next((x for x in rows if x.get("id") == cur), None)
            if r is None:
                r = R.get(cur)
            if not r:
                continue
            chain.append(r)
            for k in sorted(kids.get(cur, []), key=lambda x: x.get("finished") or 0):
                queue.append(k.get("id"))
        chain.sort(key=lambda r: (r.get("finished") or 0))
        return chain

    def _ai_snap_exists(self, snap):
        """这条镜像在盘上还在吗（用户自己在「版本快照」里清过 / 或"编辑会话"回退时收走了）。"""
        if not snap or not snap.get("id"):
            return False
        try:
            ai_dir = str(HERE / "ai")
            if ai_dir not in sys.path:
                sys.path.insert(0, ai_dir)
            import ai_snap as S                                        # noqa: PLC0415
            man = S._store().manifest(snap["id"], snap.get("group"))
            return bool(man)
        except Exception:                                              # noqa: BLE001
            return False

    def ai_session_plan(self, run_id=""):
        """**只算不改**：把"这条要删什么、回退到哪条镜像、有什么坑"摆给界面看（确认框用它）。

        回 `{ok, id, task, delete_ids, delete_tasks, snap, target, fallback, prev_id,
             chat_only, group, warnings, chain_n, index}`。
        """
        try:
            R = self._ai_runs()
            chain = self._ai_chain(run_id)
            ids = [r.get("id") for r in chain]
            if str(run_id) not in ids:
                return {"ok": False, "msg": "找不到这条会话"}
            i = ids.index(str(run_id))
            cut = chain[i:]                                            # ★ 后缀：N..链尾
            rec = chain[i]
            snap = rec.get("snapshot") or None
            snap_ok = self._ai_snap_exists(snap)
            # 快照没了（或本来就没有）⇒ 往前找最近一条还在的
            # ★ 注意 `fallback` 的语义：**只在这一轮自己的快照不可用、真退到更早那条时才给**。
            #   一开始我写成了"只要有更早的候选就填上" —— 探针立刻抓住：正常那条会话也会
            #   带着 fallback 回界面，于是确认框会冤枉地告警「不是这一轮自己的」。
            cand, prev_id = None, (ids[i - 1] if i > 0 else "")
            for r in reversed(chain[:i]):
                s = r.get("snapshot") or None
                if self._ai_snap_exists(s):
                    cand = {"id": s["id"], "group": s.get("group"),
                            "from_task": r.get("task") or "",
                            "from_at": r.get("started_text") or ""}
                    break
            fallback = None if snap_ok else cand
            target = ({"id": snap["id"], "group": snap.get("group"), "from_task": rec.get("task") or "",
                       "from_at": rec.get("started_text") or ""} if snap_ok else cand)
            files_made = any((r.get("files") or []) for r in cut)
            chat_only = not files_made
            warns = []
            if chat_only:
                warns.append("这条（以及它之后那几轮）**没改过文件**（纯问答）—— 不用回退，"
                             "只删记录。")
            elif not snap_ok and fallback:
                warns.append("这条**自己的开工快照没了**，只能退到更早的那一条"
                             "（「%s」%s）—— **那之后的改动会一起被撤掉**。"
                             % (fallback["from_task"][:20], fallback["from_at"]))
            elif not snap_ok and not fallback:
                warns.append("找不到任何可回退的镜像 —— 删掉之后**代码回不到那一刻**，"
                             "只是记录没了。")
            # 跨链：同一个包里别的会话链，在这条快照之后还改过文件
            if target:
                group = str(target.get("group") or "")
                after = target.get("from_at") or ""
                others = []
                for r in R.list_runs(limit=2000, everywhere=True):
                    if r.get("id") in ids or not (r.get("files") or []):
                        continue
                    s = r.get("snapshot") or {}
                    if group and str(s.get("group") or "") != group:
                        continue
                    if str(r.get("started_text") or "") > str(after):
                        others.append("%s（%s）" % ((r.get("task") or "")[:16],
                                                   r.get("started_text") or ""))
                if others:
                    warns.append("★ 回退是**整个包目录**回到那一刻 —— 这些**其它会话**的改动"
                                 "也会被一起撤掉：%s" % "；".join(others[:4]))
            if len(cut) > 1:
                warns.append("会连它**后面**那 %d 轮一起删掉（只允许「从链尾往回连续删」）。"
                             % (len(cut) - 1))
            return {"ok": True, "id": str(run_id), "task": rec.get("task") or "",
                    "index": i, "chain_n": len(chain),
                    "delete_ids": [r.get("id") for r in cut],
                    "delete_tasks": [(r.get("task") or "")[:40] for r in cut],
                    "snap": ({"id": snap["id"], "group": snap.get("group")} if snap else None),
                    "snap_exists": snap_ok, "target": target, "fallback": fallback,
                    "prev_id": prev_id, "chat_only": chat_only,
                    "group": (target or {}).get("group") or "",
                    "warnings": warns}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_session_truncate(self, run_id="", confirm=False):
        """**真做**：删 `N..链尾` 的记录 + 回退到目标镜像 + 删掉被删会话**自己的**镜像。

        ★ `confirm=False` 时**什么都不动**，只把计划回给你（界面要先弹确认框）。
        ★ 回退要用的那一条镜像**保留**（你定的）—— 不然这一步不可逆。
        ★ 删镜像只走 `ai_snap.clean_ai(bid=…)`，它内部只认 `by == "ai"` 的（用户自己存的碰不到）。
        """
        plan = self.ai_session_plan(run_id)
        if not plan.get("ok"):
            return plan
        if not confirm:
            return {"ok": False, "need_confirm": True, "plan": plan,
                    "msg": "这一步会删记录、并把代码回退到那一刻 —— 请先确认"}
        try:
            R = self._ai_runs()
            import ai_snap as S                                        # noqa: PLC0415
            target = plan.get("target")
            restored = ""
            if target:
                r = self.backup_restore(target["id"], None, "all", False, target.get("group") or "")
                if not r or not r.get("ok"):
                    return {"ok": False, "msg": "回退失败，**什么都没删**：%s"
                                                % ((r or {}).get("msg") or "")}
                restored = target["id"]
            # 删被删会话自己的镜像（**保留回退用的那一条**）
            dropped, kept = [], []
            for rid in plan["delete_ids"]:
                rec = R.get(rid) or {}
                s = rec.get("snapshot") or None
                if not s or not s.get("id"):
                    continue
                if target and s["id"] == target["id"]:
                    kept.append(s["id"])
                    continue
                got = S.clean_ai(group=s.get("group") or "", bid=s["id"])
                if got.get("ok"):
                    dropped.append(s["id"])
            for rid in plan["delete_ids"]:
                R.delete(rid)
            return {"ok": True, "removed": plan["delete_ids"], "restored_from": restored,
                    "kept_snapshot": (kept[0] if kept else ""), "dropped_snapshots": dropped,
                    "prev_id": plan.get("prev_id") or "",
                    "msg": "删了 %d 条会话%s%s" % (
                        len(plan["delete_ids"]),
                        ("，回退到镜像 %s" % restored) if restored else "（没有可回退的镜像）",
                        ("，清掉 %d 条镜像" % len(dropped)) if dropped else "")}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    # ------------------------------------------------ AI 的技能（`V-280`/`V-281`）
    # ★ 你 2026-10-05 定的：AI 干活缺一只手（比如"给某个界面截屏"），**可以自己造一只**；
    #   但那东西不能塞进 `user_data/pkgs/` —— 那是面向用户的目录，混进去用户看着乱、
    #   还能被 `--remove` 一键删掉。所以：
    #     · **技能本体** = `user_data/state/skill/<--名字>/`（`:skill` 插件的**数据目录**，
    #       跟 `:exec` 把命令放 `state/exec/cmds/` 一个道理）；每个技能是**一个目录**
    #       （`pkg.json` + 入口 + `icon.svg` + 任意文件）= 插件那种多文件结构。
    #     · **规矩**住在 `system/ai/skill_lib.py` —— 宿主和 `:skill` 插件 import 同一份。
    #     · id **必须 `--` 开头**（`--shot`）：插件 id 要求首字母是字母，所以它永远污染不到
    #       用户的命名空间；模型看到的工具名是去掉 `--` 的那个。
    #     · **第一次要你在 AI 页那行或「技能」界面点一次「允许」**，并且绑指纹（它事后改了
    #       `pkg.json` / 入口 / 图标，授权自动作废、退回待批准）。
    #     · 界面上「看一眼 / 允许 / 转为插件 / 删除」都在这儿和 `:skill` 插件里（同一份规矩）。
    def _skill_lib(self):
        sk = str(HERE.parent / "ai")                    # system/ai
        if sk not in sys.path:
            sys.path.insert(0, sk)
        import skill_lib                                               # noqa: PLC0415
        return skill_lib

    def ai_skills(self):
        """技能那一页要的全部数据（AI 页那行 + `:skill` 界面都用它）。"""
        try:
            return self._skill_lib().summary()
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e),
                    "skills": [], "from_pkgs": [], "broken": [], "dirs": {}}

    def _skills_rev(self):
        """技能状态小指纹（只读盘、轻量）—— `ai_poll` 带着它，界面状态一变就重读。"""
        try:
            return self._skill_lib().rev()
        except Exception:                                                # noqa: BLE001
            return ""

    def ai_skill_allow(self, sid="", yes=True):
        """允许 / 撤销一只技能（从样例抄来的也算你的，能撤销）。"""
        try:
            return self._skill_lib().allow(sid, bool(yes))
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_skill_read(self, sid=""):
        """「看一眼」：把它写的那些文件原文拿出来（点允许之前先看）。"""
        try:
            return self._skill_lib().read(sid)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_skill_rm(self, sid="", confirm=False):
        """删掉一只技能（`confirm=False` 时**什么都不删**，只回一句"确认一下"）。"""
        try:
            return self._skill_lib().rm(sid, bool(confirm))
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_skill_promote(self, sid="", confirm=False, new_id=""):
        """把技能转成插件：去掉 `--`、搬进 `user_data/pkgs/`（id 撞了会拒，让你自己起名字）。"""
        try:
            sk = self._skill_lib()
            avoid = ()
            try:
                ai_dir = str(HERE / "ai")
                if ai_dir not in sys.path:
                    sys.path.insert(0, ai_dir)
                import ai_tools                                        # noqa: PLC0415
                avoid = ai_tools.builtin_names()
            except Exception:                                          # noqa: BLE001
                pass
            return sk.promote(sid, bool(confirm), new_id, builtin=avoid)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_skill_plan(self, sid="", new_id=""):
        """**只算不改**：转插件会不会撞 id（界面弹确认框之前先问这个）。"""
        try:
            return self._skill_lib().promote_plan(sid, new_id)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_run_forget(self, run_id="", all_of_them=False, workdir=""):
        """删一条（或全清）任务记录。记录只是回顾用的，删了不影响包。

        ★ `V-307`：记录按"干活的地方"分桶了 —— 全清**只清这个桶**（不会顺手把别的包的会话删掉）。
        """
        try:
            R = self._ai_runs()
            scope = R.scope_of(workdir or self._ai_last_workdir())
            return R.clear(scope) if all_of_them else R.delete(run_id)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    def ai_stop(self):
        """按「停止」：**立刻停**（`V-307` 改成真的立刻）。

        老行为（用户报的现场）：只在**下一轮开头**看一眼停止标志 ⇒ 界面提示"停在下一轮"，
        然后正在跑的那次请求 / 那个工具就那么卡着，最长能挂二十分钟。现在一次做四件事：

          ① 置停止标志 —— 模型那边**正在发的请求**会被掐断（`ai_client` 每 0.2 秒看一眼）；
          ② **杀掉它起过的子进程**（连子孙）：`run_moss` 的阻塞循环每 0.15 秒看一眼，
             正在跑的包会当场被 `taskkill /T` 收掉，loop 也会立刻收工；
          ③ **放走挂着的问题**（它可能正等你回答 —— 不能让"停止"卡在一张没人答的卡片上）；
          ④ 状态上写 `stopping`，线程万一还赖着没退，界面也不会永远显示"执行中"
             （`work()` 的 `finally` 一定会把 `running` 落回 False）。
        """
        AI["stop"] = True
        killed, ms = [], 0.0
        loop = AI.get("loop")
        if loop is not None:
            try:
                got = loop.tools.kill_children("用户按了停止")
                killed, ms = got.get("pids") or [], got.get("ms") or 0
                with AI_LOCK:
                    if AI.get("state"):
                        AI["state"]["killed"] = list(AI["state"].get("killed") or []) + killed
                        AI["state"]["stopping"] = True
            except Exception:                                            # noqa: BLE001
                pass
        with AI_LOCK:
            asker = AI.get("asker")
        if asker is not None:
            try:
                asker.cancel("stopped")
                with AI_LOCK:
                    if AI.get("state"):
                        AI["state"]["ask"] = None
            except Exception:                                            # noqa: BLE001
                pass
        # 等一小会儿让它自己收尾（正常 ≤0.3 秒就回到了）：回来了就把结果说清楚，
        # 没回来也**不骗人** —— 如实说"还在收尾"，界面照旧能接着操作。
        th = AI.get("thread")
        done = False
        if th is not None:
            try:
                th.join(1.5)
                done = not th.is_alive()
            except Exception:                                            # noqa: BLE001
                pass
        if killed:
            # `V-367`：说人话（去掉"顺手""连子孙""毫秒"这种开发口吻）
            return {"ok": True, "killed": killed, "ms": ms, "done": done,
                    "msg": "已停止（它起的 %d 个进程也一起停了）" % len(killed)}
        return {"ok": True, "killed": [], "done": done,
                "msg": "已停止" if done else "已请求停止 —— 它正在收尾"}

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

    def fs_preview_url(self, rel):
        """给文件管理的**浏览模式**一个本地 URL（HTML / Markdown 预览用）。

        ★ 为什么要经本地 HTTP 服务：WebView2 里 iframe 不能加载 `file://` 页面，
          而且 HTML 里的 `./style.css`、`./img.png` 也得跟着能取到。
        ★ 返回的 `base` 以 `/` 结尾，预览页塞进 `<base href="…">` 就能解析相对资源；
          `url` 是这个文件本身（也可以直接给 iframe src）。
        """
        try:
            _root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not p.is_file():
            return {"ok": False, "msg": "不是文件：%s" % rel}
        port, token = _embed_server()
        if not port:
            return {"ok": False, "msg": token or "本地预览服务起不来"}
        try:
            ap = p.resolve().as_posix()
        except OSError as e:
            return {"ok": False, "msg": "路径解析失败：%s" % e}
        quoted = urllib.parse.quote(ap, safe="/:")
        url = "http://127.0.0.1:%d/%s/abs/%s" % (port, token, quoted)
        base = url.rsplit("/", 1)[0] + "/"
        return {"ok": True, "url": url, "base": base, "path": str(p),
                "rel": _rel_page(p), "name": p.name}

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

    def backup_create(self, rels, title="", note="", group="", excludes=None,
                      by="", by_task=""):
        """备份一批 rel（页面给的是 `user/...` / `system/...` / `abs/...`）。

        落到哪个**分组**（`user_data/backups/<分组>/`）：不传就按来源猜（包 ⇒ 包 id，
        整个 user_data ⇒ `@user`，某个目录 ⇒ `@dir-<名字>`）。

        `by` / `by_task`（`V-236`）：**谁存的** + **那次的任务原文**。
        人从界面点「存快照」时是空的；AI 工作台存"动手前"那条时会给 `by="ai"`。
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
                            group=(str(group or "") or None),
                            by=by, by_task=by_task)
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
        """弹系统对话框让用户挑一个文件夹（导出目标 / 插件的「选文件夹」用）。

        ★ 取消 ⇒ `ok=False` **并且带 `cancelled=True`**（`V-212`）：这是给插件分辨
          "用户自己关掉了框"和"这条路压根走不通"用的 —— 以前两者都只是"没拿到 path"，
          插件按"问不到"处理就会**再弹一个自己那张对话框**（`path` 包真踩到：取消一次弹两次）。
          窗口还没准备好 / 抛错**不算取消**，那时插件退回自己那条兜底是对的。
        """
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
                return {"ok": False, "cancelled": True, "msg": "没有选（取消）"}
            p = res[0] if isinstance(res, (list, tuple)) else res
            return {"ok": True, "path": str(p)}
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": "挑文件夹失败：%s" % e}

    def pick_file(self, start=""):
        """弹系统对话框让用户挑一个**文件**（`V-180`：历史那边的"打开文件并运行"用）。

        只给"能跑的东西"做过滤（py/pyw/go/exe/html/ps1/bat/cmd），也留一个"所有文件"。
        """
        try:
            import webview as _wv
            wins = list(getattr(_wv, "windows", None) or [])
            if not wins:
                return {"ok": False, "msg": "窗口还没准备好，稍一下再试"}
            kind = None
            fd = getattr(_wv, "FileDialog", None)
            if fd is not None:
                kind = getattr(fd, "OPEN", None)
            if kind is None:
                kind = getattr(_wv, "OPEN_DIALOG", None)
                if callable(kind):
                    kind = kind()
            if not kind:
                return {"ok": False, "msg": "这个 pywebview 版本不支持挑文件"}
            types = ("可执行文件 (*.py;*.pyw;*.go;*.exe;*.html;*.htm;*.ps1;*.bat;*.cmd)",
                     "所有文件 (*.*)")
            start_dir = str(start or "").strip() or str(HOME)
            try:
                res = wins[0].create_file_dialog(kind, directory=start_dir, file_types=types)
            except TypeError:
                res = wins[0].create_file_dialog(kind, start_dir, types)
            if not res:
                return {"ok": False, "cancelled": True, "msg": "没有选（取消）"}
            p = res[0] if isinstance(res, (list, tuple)) else res
            return {"ok": True, "path": str(p)}
        except Exception as e:                                      # noqa: BLE001
            return {"ok": False, "msg": "挑文件失败：%s" % e}

    def backup_rm_ai(self, group=""):
        """**只删 AI 存的快照**（`V-236`）。

        ★ 这不是"UI 帮忙过滤一下" —— 后端走的是 `BackupStore.delete_ai()`，
          它逐条看清单里的 `by` 字段，**不是 `"ai"` 的直接跳过**。
          所以"AI 不能删用户存的快照"是**结构性**保证，不靠提示词自觉。
        """
        try:
            ai_dir = str(HERE / "ai")
            if ai_dir not in sys.path:
                sys.path.insert(0, ai_dir)
            import ai_snap
            return ai_snap.clean_ai(group=group)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "deleted": [], "skipped": [], "msg": "清不掉：%s" % e}

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
    # ★ 宿主在这里**只当管子**（不懂协议）：页面里 `moss.call("方法名", {...})` 的请求由
    #   包自己的垫片包成一行 JSON，这边原样写进进程 stdin；进程回的行再原样送回页面。
    #   好处：协议归包和契约管，宿主不用为每个方法改代码。
    # ★ 只把 `{` 开头的行当消息转走 —— 宿主的横幅是 `[执行]/[目录]/[PID]` 这种
    #   **数组样子**的行，包的普通输出（print）也可能有；那些进命令行面板，不当消息。
    # ------------------------------------------------ 浮动窗口（`V-192` / `V-194`）
    def ui_float(self, pid):
        """把内嵌那一帧**弹出**成 moss 自己的另一个窗口（后端进程一步不动）。

        ★ 为什么能这么干：pywebview 的 `create_window()` 在 `start()` **跑过之后**、
          且**不在主线程**时，会**立刻建窗** —— 源码原话
          `This immediately creates the window only if start has already been called`；
          Windows 后端真实现了（`platforms/winforms.py:682 create_window`）。
          而 js_api 的方法本来就跑在**非主线程** ⇒ 这里直接建窗就行。
        """
        pid = str(pid)
        with _FLOAT_LOCK:
            cur = _FLOAT.get(pid)
        if cur is not None:                    # 已经开着 → 抬到前面
            try:
                cur.show()
                cur.restore()
            except Exception:                                          # noqa: BLE001
                pass
            return {"ok": True, "msg": "这个包的窗口已经开着了"}
        rec = None
        for p in (DATA.get("packages") or []):
            if str(p.get("id")) == pid:
                rec = p
                break
        if not rec or not ((rec.get("ui") or {}).get("embed")):
            return {"ok": False, "msg": "这个包没有内嵌界面，弹不出来"}
        title = _pkg_title(rec) or ("moss · " + pid)
        try:
            x = int(window.x) + 40
            y = int(window.y) + 40
        except Exception:                                              # noqa: BLE001
            x = y = None
        try:
            w = webview.create_window(title, _PAGE_URL + "#float=" + pid, js_api=_API,
                                      width=960, height=720, x=x, y=y,
                                      min_size=(520, 380), text_select=True)
        except Exception as e:                                         # noqa: BLE001
            return {"ok": False, "msg": "开窗口失败：%s" % e}
        if w is None:
            return {"ok": False, "msg": "开窗口失败（pywebview 没给窗口）"}
        with _FLOAT_LOCK:
            _FLOAT[pid] = w
        _wire_float(pid, w, title)
        _note("float: :%s 弹出为窗口「%s」" % (pid, title))
        return {"ok": True, "msg": "已弹出为窗口（点最小化就收回）"}

    def ui_dock(self, pid):
        """把浮动窗口**收回**主窗口那张选项卡（后端继续跑）。"""
        pid = str(pid)
        if _float_win(pid) is None:
            return {"ok": True, "msg": "本来就没弹出"}
        # ★ `V-367`：收回这**一个动作**只留一条提示 —— 上面 `_dock_float` 已经推了
        #   `__mossFloatDock`（那一页会弹「已收回主窗口」），这里再回一句「已收回」
        #   就是同一件事说两遍（两条不同措辞）。所以正常这条路**不回 msg**。
        _dock_float(pid, "点了收回")
        return {"ok": True}

    def ui_float_stop(self, pid):
        """浮动窗口里的「停止」：**停掉后端 + 关掉窗口** —— 和那颗 X 一个意思（`V-194`）。"""
        pid = str(pid)
        _close_float_quiet(pid)                 # 先摘记录，免得关闭事件又当一次"用户关的"
        r = self.embed_stop(pid)
        _js(window, "window.__mossFloatClosed && window.__mossFloatClosed(%s)" % json.dumps(pid))
        return {"ok": True, "msg": (r or {}).get("msg") or "已停掉"}

    def set_win_icon(self, pid, png_b64):
        """把浮动窗口的图标换成**这个包自己的图标**（`V-195`）。

        ★ 为什么要绕"页面光栅化 → 这里收 PNG"这一圈：Windows 的窗口图标要的是 **HICON**，
          而包图标大多是 **svg**（`icon.svg`，`currentColor` 的线条画），系统不认 svg。
          页面那边本来就是个浏览器 —— 顺手把 svg 画进 canvas 导出 PNG 最省事
          （不用为这一个功能引 svg 渲染库）。
        ★ 收到 PNG 之后存成一面**多尺寸 .ico**（16/32/48/256）再 `LoadImageW` ——
          多尺寸 Windows 才会按 DPI / 任务栏自己挑一张，不会糊。
        """
        pid = str(pid)
        w = _float_win(pid)
        if w is None:
            return {"ok": False, "msg": "这个包的浮动窗口已经没了"}
        try:
            import base64 as _b64                                       # noqa: PLC0415
            png = _b64.b64decode(str(png_b64 or ""))
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "图标数据坏了：%s" % e}
        if len(png) < 64:
            return {"ok": False, "msg": "图标数据太小了"}
        _ICON_DIR.mkdir(parents=True, exist_ok=True)
        ico = _ICON_DIR / (pid + ".ico")
        try:
            _png_to_ico(png, ico)
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "转 ico 失败：%s" % e}
        hicon = _load_icon_file(ico)
        if not hicon:
            return {"ok": False, "msg": "系统读不了这个 ico"}
        hwnd = _hwnd_of(w) or _hwnd_by_title(getattr(w, "title", "") or "")
        if not hwnd:
            return {"ok": False, "msg": "找不到那个窗口的句柄"}
        _wm_set_icon(hwnd, hicon)
        return {"ok": True, "msg": "图标换好了"}

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

    def embed_start(self, pid, cwd="", args_text=""):
        """给这个包起一个"内嵌界面"的后端进程（`MOSS_UI_EMBED=1`）。已经起着就复用。

        `cwd` / `args_text` 只在本次真启动时生效（复用已有进程时不会重起）。
        """
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
        argv = HOST + ["--pkg", str(pid)] + _split(args_text)
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
        """停掉这个包的内嵌进程（界面上的「停止」）。浮动窗口也一起关掉（`V-192`）。"""
        pid = str(pid)
        _close_float_quiet(pid)             # 别留一张"后端已经没了"的死窗口
        with EMBED_LOCK:
            rec = EMBED.get(pid)
        if not rec:
            return {"ok": False, "msg": "这个包没在内嵌运行"}
        proc = rec["proc"]
        with EMBED_LOCK:
            # ★ `V-297`：先记一笔"这是我们停的"，`_pump_embed` 收尾就**别**再弹
            #   "内嵌进程结束了（退出码 1）"（强杀必然非 0，那个提示是重复的）。
            EMBED_STOPPED.add(proc)
        _kill_tree(proc.pid)                 # 连子孙一起（包可能自己又起了进程）
        try:
            proc.kill()
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
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
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
        # ★ `V-276`：把这份"当前生效值"记下来 —— `settings_check` 现在在**本进程**里算，
        #   需要它来兜底（界面每次都把整份值送过来，所以它通常用不上）。
        try:
            _SETTINGS_CUR.clear()
            for g in (data.get("groups") or []):
                for it in (g.get("items") or []):
                    _SETTINGS_CUR[it["key"]] = it.get("value")
        except Exception:                                             # noqa: BLE001
            pass
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
        """**只校验、不写盘**：用来标红 + 决定"保存"能不能点。

        ★ `V-276`：**在界面进程里直接算**了 —— 不再起一个 `moss.exe`。
          为什么可以：规则本身是**纯计算**（不读盘、不写盘），而界面进程**就是 Python**；
          真机实测那一趟 `moss.exe --settings-check` 要 **0.73~1.07 秒**（其中校验 ≈20ms，
          其余全是 onefile 冷启动），而这里算一遍 **<1ms**。
          规则只有一份：`system/option/rules.py`（宿主 `core/config.py` 也用同一套逻辑，
          `tools/设置规则探针.py` 拿同一批输入把两边的输出**逐字对比**，谁漂了探针就红）。
        ★ 拿不到那份模块（老安装 / 被人删了）就**退回老路**：叫宿主算 —— 慢，但不会算错。
        """
        try:
            r = _settings_rules()
            if r is not None:
                cur = _settings_current()
                got = r.check(values, cur)
                return {"ok": bool(got["ok"]), "problems": got["problems"],
                        "notes": got["notes"], "live": got["live"], "msg": ""}
        except Exception as e:                                        # noqa: BLE001
            _note("settings: 界面内校验失败（%r），退回叫宿主" % (e,))
        return self._settings_call("--settings-check", values, with_notes=True)

    def _settings_call(self, flag, payload, with_notes):
        """`--settings-set` / `--settings-check` 共用的那一半（叫宿主 + 解析回话）。"""
        empty = {"ok": False, "problems": [], "notes": {}, "live": "", "msg": ""}
        if not HOST:
            empty["msg"] = "没拿到宿主命令 —— 请从 moss 主程序打开界面"
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
                # ★ `V-298`：短命令那颗开关存完之后，宿主会说"生成了/删了哪些" —— 带回去让界面弹一句。
                "shortcut": data.get("shortcut") or [], "msg": ""}

    # ------------------------------------------------------------ 命令接入：cd 增强（`V-299`）
    #   「命令接入」那一页除了 PATH 开关，还管 `moss cd` 的"无回显"包装函数。
    #   状态和安装都回来叫宿主（`--cd-status` / `cd --install` / `cd --uninstall`），
    #   界面不 import core。
    def cd_state(self):
        """cd 包装函数装没装（只读，给那页显示）。"""
        empty = {"ok": False, "any": False, "profiles": [], "msg": "没拿到宿主命令"}
        if not HOST:
            return empty
        r = _run_capture_split(HOST + ["--cd-status"])
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict):
            return empty
        return {"ok": True, "any": bool(data.get("any")),
                "profiles": data.get("profiles") or []}

    def cd_install(self):
        """装 cd 包装函数（= `moss cd --install`）：`moss cd <目标>` 屏幕上不留回显。"""
        return self._cd_run("--install")

    def cd_uninstall(self):
        """卸掉 cd 包装函数（回到"注入按键"那条路）。"""
        return self._cd_run("--uninstall")

    def _cd_run(self, flag):
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令"}
        r = _run_capture_split(HOST + ["cd", flag])
        ok = (r.get("code") == 0)
        text = ((r.get("out") or "") + (r.get("err") or "")).strip()
        last = (text.splitlines() or [""])[-1].strip() if text else ""
        return {"ok": ok, "msg": last or ("完成" if ok else "没成功")}

    # ------------------------------------------------------------ 插件列表的排序（`V-300`）
    #   用户把包拖成自己的顺序 → 存 `user_data/state/_ui_order.json`。
    #   ★ 为什么走宿主存、不用 localStorage：页面地址带随机端口/token（`_page_url`），
    #     每次启动源都变 ⇒ localStorage 读不回来（`core.js` 里记过这个坑）。
    def list_state(self):
        """读插件列表的「自定义顺序 + 排序档」。读坏了就当没存（返回空）。"""
        f = USER_DATA / "state" / "_ui_order.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except Exception:                                                 # noqa: BLE001
            data = {}
        if not isinstance(data, dict):
            data = {}
        ids = data.get("ids")
        return {"ok": True, "ids": ids if isinstance(ids, list) else [],
                "sort": data.get("sort") if isinstance(data.get("sort"), str) else ""}

    def list_state_set(self, ids, sort):
        """存「自定义顺序 + 排序档」。原子写（先 .tmp 再 replace），跟窗口几何一个路子。"""
        try:
            d = USER_DATA / "state"
            d.mkdir(parents=True, exist_ok=True)
            f = d / "_ui_order.json"
            tmp = f.with_name(f.name + ".tmp")
            tmp.write_text(json.dumps({"ids": [str(x) for x in (ids or [])],
                                       "sort": str(sort or "")}, ensure_ascii=False),
                           encoding="utf-8")
            os.replace(str(tmp), str(f))
            return {"ok": True}
        except Exception as e:                                            # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    # ------------------------------------------------------------ AI 那几组参数（`V-138`）
    #   ★ 为什么这几条**不走**上面那套「设置项」：`[ai.profiles.<组名>]` 是**表套表**，
    #     组名是用户自己起的 —— 面板那种"一个键一行"的渲染摆不下
    #     「选组 / 加组 / 删组 / 设为当前 / 测连接」。存储和规则仍然只有 `core/config.py`
    #     那一份，这里只是把宿主的几条命令包一层（界面不自己解析 TOML）。
    def ai_config(self, name="", reveal=False):
        """读一组 AI 参数（`name` 空 = 当前那组）。**key 默认打码**，`reveal=True` 才给全文。"""
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        flag = "--ai-config-reveal" if reveal else "--ai-config"
        argv = HOST + [flag] + (["--profile=" + str(name)] if str(name or "").strip() else [])
        r = _run_capture_split(argv)
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict) or not data.get("ok"):
            # 出错时宿主可能把话打在 stdout（`[错误] 没有这一组`）也可能打在 stderr，
            # 两股都看一眼 —— 只说"退出码 1"等于没说。
            tail = ((r.get("err") or "").strip().splitlines() or [""])[-1] \
                or ((r.get("out") or "").strip().splitlines() or [""])[-1]
            return {"ok": False, "msg": "读 AI 参数失败：退出码 %s%s"
                                        % (r.get("code"), (" —— " + tail) if tail else "")}
        return {"ok": True, "active": data.get("active") or "",
                "name": data.get("profile") or "", "params": data.get("params") or {},
                "profiles": data.get("profiles") or [],
                # ★ `V-140`：列表那一屏要的摘要（每组一行：地址 / 模型 / key 填没填）
                "summary": data.get("summary") or {}}

    def ai_presets(self):
        """常见服务商的**预制参数**（`V-139`）—— 面板上那排「常用」按钮读的就是它。

        ★ 表在 `core/config.py` 的 `AI_PRESETS` 里（只有一份真相）：面板只是照它画按钮，
          点一下把「名字 / 接口地址 / 模型」填进表单，用户只需要再粘一把 key。
        """
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        r = _run_capture_split(HOST + ["--ai-presets"])
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict) or not data.get("presets"):
            tail = ((r.get("err") or "").strip().splitlines() or [""])[-1] \
                or ((r.get("out") or "").strip().splitlines() or [""])[-1]
            return {"ok": False, "presets": [],
                    "msg": "读预制参数失败：退出码 %s%s"
                           % (r.get("code"), (" —— " + tail) if tail else "")}
        return {"ok": True, "presets": data.get("presets") or []}

    def ai_save(self, name, fields):
        """加/改一组（**明文**写 `config.toml`）—— 只送用户真改过的那几个字段。

        回 `{"ok", "name", "msg"}`；`msg` 是宿主那句「已存：X（字段 …）」，直接显示。
        """
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        name = str(name or "").strip()
        if not name:
            return {"ok": False, "msg": "先给这一组起个名字"}
        if not isinstance(fields, dict) or not fields:
            return {"ok": False, "msg": "这一组没有改动"}
        argv = HOST + ["--ai-profile-set", name]
        for k in sorted(fields):
            argv.append("%s=%s" % (k, _ai_arg(fields[k])))
        r = _run_capture(argv)
        out = (r.get("out") or "").strip()
        return {"ok": r.get("code") == 0, "name": name,
                "msg": out or ("保存失败：退出码 %s" % r.get("code"))}

    def ai_delete(self, name):
        """删一组（当前那组被删掉时，宿主会自动把当前挪到剩下的第一组）。"""
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        name = str(name or "").strip()
        if not name:
            return {"ok": False, "msg": "没说到底删哪一组"}
        r = _run_capture(HOST + ["--ai-profile-del", name])
        return {"ok": r.get("code") == 0, "msg": (r.get("out") or "").strip()}

    def ai_rename(self, old, new):
        """给一组改名（`V-139`）：面板上「名字」改完保存走这条。

        ★ 为什么不"按新名字再存一遍"：那样得把明文 key 从宿主读回界面再送回去，
          多一次明文往返、还容易把 key 弄丢（面板上只有打码那串）—— 宿主整块搬最稳。
        """
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        old, new = str(old or "").strip(), str(new or "").strip()
        if not old or not new:
            return {"ok": False, "msg": "没说清改哪一组 / 改成什么"}
        r = _run_capture(HOST + ["--ai-rename", old, new])
        if r.get("code") != 0:
            return {"ok": False, "name": "", "msg": (r.get("out") or "").strip()
                                                   or "没改成（名字被占用了？）"}
        return {"ok": True, "name": new, "msg": (r.get("out") or "").strip()}

    def ai_set_active(self, name):
        """选当前用哪一组（就是「设为当前」，以后跑包注入的就是这一组）。"""
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        name = str(name or "").strip()
        if not name:
            return {"ok": False, "msg": "没说到底切哪一组"}
        r = _run_capture(HOST + ["--ai-active", name])
        return {"ok": r.get("code") == 0, "msg": (r.get("out") or "").strip()}

    # ------------------------------------------------------------ 新建包（`V-387`）
    def new_pkg(self, pid="", name="", desc="", kind=""):
        """建一个包的骨架（走宿主 `moss --new`，唯一实现）。

        ★ 为什么不在这里拼 `run_host("--new x name=…")`：名字/介绍里会有空格、引号、中文，
          走**列表式 argv** 才不用跟命令行的引号较劲（`_run_capture` 收的就是列表）。
        ★ 失败（id 非法 / 已存在）时把宿主那句话原样带回去，别吞成"没成功"。
        """
        pid = str(pid or "").strip().lower()
        if not pid:
            return {"ok": False, "code": 1, "msg": "先说个 id（小写字母开头）", "out": ""}
        argv = HOST + ["--new", pid]
        if str(name or "").strip():
            argv.append("name=" + str(name).strip())
        if str(desc or "").strip():
            argv.append("desc=" + str(desc).strip())
        if str(kind or "").strip():
            argv.append("kind=" + str(kind).strip())
        r = _run_capture(argv)
        ok = r.get("code") == 0
        text = (r.get("out") or "").strip() or ("建好了" if ok else "没建成")
        return {"ok": ok, "code": r.get("code"), "msg": text, "out": text}

    @staticmethod
    def _pkg_id(raw, fallback="new-pkg"):
        """把模型给的名字**掰成合法 id**：小写、字母开头、`[a-z0-9_-]`、≤24。

        规矩跟 `core/paths.py` 的 `valid_id()` 一致（32 是硬上限，这里留余量给 `-2` 后缀）。
        模型常给中文 / 大写 / 带空格的名字，所以这一步**必须**有，不能直接信它。
        """
        s = str(raw or "").strip().lower()
        s = re.sub(r"[^a-z0-9_-]+", "-", s).strip("-_")
        s = re.sub(r"^[^a-z]+", "", s)
        s = s[:24].strip("-_")
        return s or fallback

    def _pkg_ids_taken(self):
        """已经占着的包“名字”（id / 别名 / 目录名）—— 两层都查，避免新建时撞名。

        ★ `V-424`：不能只看 `user_data/pkgs`。system 层有同 id / 同别名的包时，
          新建一个空白用户包会把它**静默遮蔽**；AI 看到退出码 0，还以为成功了。
        ★ 显示名（pkg.json 的 `name`）**不要求唯一**；id / 别名才是解析身份。
        """
        taken = set()
        for p in (DATA.get("packages") or []):
            try:
                taken.add(str(p.get("id") or "").strip().lower())
                _als = p.get("aliases") or []
                if isinstance(_als, str):
                    _als = [_als]
                for a in _als:
                    taken.add(str(a or "").strip().lower())
            except Exception:                                            # noqa: BLE001
                pass
        # 包表可能是旧的 / 还没加载：直接扫两层的目录与清单兜底。
        for base in (USER_DATA / "pkgs", HOME / "system" / "pkgs"):
            try:
                for p in base.iterdir():
                    if p.is_dir():
                        taken.add(p.name.strip().lower())
                        try:
                            _man = json.loads((p / "pkg.json").read_text(encoding="utf-8"))
                            if isinstance(_man, dict):
                                taken.add(str(_man.get("id") or "").strip().lower())
                                _als = _man.get("aliases") or []
                                if isinstance(_als, str):
                                    _als = [_als]
                                for a in _als:
                                    taken.add(str(a or "").strip().lower())
                        except Exception:                                # noqa: BLE001
                            pass
            except OSError:
                pass
        taken.discard("")
        return taken

    def ai_suggest_pkg(self, idea=""):
        """**让 AI 定一个包**：`id` / 名字 / 介绍 / 开工那句任务（`V-387`）。

        用户原话：「创建的时候 其实这个项目到底用啥名字 怎么写介绍 怎么写 id 我也拿不准
        …… 能不能也有个简单的 AI 帮我完成」。

        ★ 只发**一次**最小请求（不带工具、不建 loop）—— 这是"起名"，不是"干活"；
          真正的活由建完包之后那一次 `ai_start` 干。
        ★ 返回的都只是**建议**：界面上那四个框照样能改，这里不替用户拍板。
        ★ id 当场按 `core/paths.py` 的规矩掰正，并避开两层的 id / 别名（`-2`、`-3`…）。
        """
        idea = str(idea or "").strip()
        if not idea:
            return {"ok": False, "msg": "先说一句你想让它干什么 —— 一句话就行"}
        try:
            p = self.ai_params(refresh=True)
            if not (p.get("base_url") and p.get("model")):
                return {"ok": False,
                        "msg": p.get("why") or "还没配 AI —— 去「设置 → AI」挑一家、把 key 填上"}
            c, _e, _l = self._ai_mods()
            client = c.Client(p.get("base_url"), p.get("api_key") or "", p.get("model"))
        except Exception as exc:                                         # noqa: BLE001
            return {"ok": False, "msg": "AI 起不来：%s" % exc}
        sys_msg = (
            "你是 moss 的插件规划助手。用户在做一个新插件（moss 里叫「包」），你替他把"
            "id / 名字 / 介绍 / 第一句任务定下来。\n"
            "只输出**一个 JSON 对象**，不要解释、不要 Markdown 代码块，键固定四个：\n"
            '{"id": "...", "name": "...", "desc": "...", "task": "..."}\n'
            "规则：\n"
            "· id：小写英文字母开头，只含小写字母/数字/-/_，不超过 24 个字符，"
            "一眼能看出是干什么的（例：shot-archive）。\n"
            "· name：中文短名字，4-12 个字，不带引号。\n"
            "· desc：一句话（20-40 字）说清它干什么、什么时候用 —— 会显示在插件列表里。\n"
            "· task：给随后写代码的 AI 的第一句指令（中文，一句话说清目标 + 关键约束，"
            "不要写成需求文档）。\n"
            "· 除 id 外全部用中文；不要 emoji。"
        )
        t0 = time.time()
        try:
            got = client.chat([{"role": "system", "content": sys_msg},
                               {"role": "user", "content": "我想做的东西：" + idea}])
            raw = str((got or {}).get("text") or "").strip()
        except Exception as exc:                                         # noqa: BLE001
            return {"ok": False, "msg": "AI 没答上来：%s" % exc}
        # ---- 从回复里抠 JSON（模型偶尔包一层 ```，或者前后带话）----
        blob, data = raw, {}
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            blob = m.group(0)
        try:
            data = json.loads(blob)
        except Exception:                                                # noqa: BLE001
            data = {}
        if not isinstance(data, dict):
            data = {}
        nm = str(data.get("name") or "").strip()[:24]
        ds = str(data.get("desc") or "").strip()[:80]
        tk = str(data.get("task") or "").strip()
        pid = self._pkg_id(data.get("id") or nm, fallback="new-pkg")
        taken = self._pkg_ids_taken()
        base = pid
        # ★ `V-424`：旧代码写成 `("%s-%d" % (base, n))[:24]`；base 刚好 24 字符时
        #   后缀被整段截掉，循环到 50 次仍返回原 id ⇒ 用户点创建收到“已存在”。
        #   现在按 32 字符硬上限给后缀留位。
        for n in range(2, 1000):
            if pid not in taken:
                break
            suffix = "-%d" % n
            pid = (base[:32 - len(suffix)].rstrip("-_") + suffix).strip("-_")
        if pid in taken:                 # 极端兜底：别把冲突的 id 交出去
            pid = (base[:25].rstrip("-_") + "-" + uuid.uuid4().hex[:6]).strip("-_")
        if not nm:
            nm = pid
        if not ds:
            ds = idea[:60]
        if not tk:
            tk = "做一个「%s」的包：%s" % (nm, idea)
        return {"ok": True, "id": pid, "name": nm, "desc": ds, "task": tk,
                "model": str(p.get("model") or ""),
                "ms": int((time.time() - t0) * 1000),
                # 模型没按格式回（抠不出 JSON）时上面是兜底值；把原文截一段带回去，
                # 让"它到底说了啥"能查（别把几 KB 塞进页面）。
                "raw": "" if data else raw[:400]}

    def ai_test(self, name="", fields=None):
        """**测试连接**：宿主按这一组的 `stream` 真发一个最小请求，把结果原样带回来。

        ★ 这里必须让**宿主**去发：key 和 url 都只存在宿主那边读得到的配置里，
          界面不该为了测一下就把明文 key 拿过来再自己发一遍（多一处明文、多一处出错）。
        """
        if not HOST:
            return {"ok": False, "code": -1, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        argv = HOST + ["--ai-test"] + ([str(name)] if str(name or "").strip() else [])
        # ★ `V-147`：面板可以把"表里现在的值"一起送过来 ⇒ **不用先保存也能测**。
        #   只是临时覆盖，一个字节都不落盘。
        for k in sorted(fields or {}):
            v = (fields or {})[k]
            if v not in (None, ""):
                argv.append("%s=%s" % (k, _ai_arg(v)))
        r = _run_capture(argv)
        return {"ok": r.get("code") == 0, "code": r.get("code"),
                "msg": (r.get("out") or "").strip() or "（宿主没说什么）"}

    def ai_models(self, name="", fields=None):
        """**获取可用模型**：宿主 GET `{base_url}/models`，把清单回给设置面板。

        ★ 和 `ai_test` 同一条路：key / URL 不拿到界面自己发，只做一次临时覆盖；
          这样「还没保存就先点一下获取模型」也能用，而且明文 key 不出宿主。
        """
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        argv = HOST + ["--ai-models"] + ([str(name).strip()] if str(name or "").strip() else [])
        for k in sorted(fields or {}):
            v = (fields or {})[k]
            if v not in (None, ""):
                argv.append("%s=%s" % (k, _ai_arg(v)))
        r = _run_capture_split(argv)
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict):
            tail = (((r.get("err") or "").strip().splitlines() or [""])[-1]
                    or ((r.get("out") or "").strip().splitlines() or [""])[-1])
            return {"ok": False, "models": [],
                    "msg": ("获取模型失败：退出码 %s%s"
                            % (r.get("code"), (" —— " + tail) if tail else ""))}
        return data

    def ai_balance(self, name="", fields=None):
        """**查询余额**：宿主按已知服务商接口去查，回一句人话 + 原始详情。"""
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        argv = HOST + ["--ai-balance"] + ([str(name).strip()] if str(name or "").strip() else [])
        for k in sorted(fields or {}):
            v = (fields or {})[k]
            if v not in (None, ""):
                argv.append("%s=%s" % (k, _ai_arg(v)))
        r = _run_capture_split(argv)
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict):
            tail = (((r.get("err") or "").strip().splitlines() or [""])[-1]
                    or ((r.get("out") or "").strip().splitlines() or [""])[-1])
            return {"ok": False, "msg": ("查余额失败：退出码 %s%s"
                                         % (r.get("code"), (" —— " + tail) if tail else ""))}
        return data

    def ai_pick_attachments(self, images=False):
        """给 AI 输入框挑本地附件 / 图片（系统文件对话框，**可多选**）。

        为什么不走页面的 `<input type=file>`：WebView 里拿到的只是浏览器 File 对象，
        非图片附件没法把真实路径交给 loop 去读。这里直接回真实路径，图片由 loop 现读并
        embed，文本 / 代码附件也照常当 path 附件处理 —— 两种上传按钮因此都是真能用的。
        """
        try:
            import webview as _wv
            wins = list(getattr(_wv, "windows", None) or [])
            if not wins:
                return {"ok": False, "msg": "窗口还没准备好，稍一下再试"}
            win = wins[0]
            if not hasattr(win, "create_file_dialog"):
                return {"ok": False, "msg": "这个环境没有文件选择框"}
            fd = getattr(_wv, "FileDialog", None)
            kind = getattr(fd, "OPEN", None) if fd is not None else None
            if callable(kind):
                kind = kind()
            if kind is None:
                kind = getattr(_wv, "OPEN_DIALOG", None)
            if callable(kind):
                kind = kind()
            if not kind:
                return {"ok": False, "msg": "这个 pywebview 版本不支持挑文件"}
            types = (("图片 (*.png;*.jpg;*.jpeg;*.gif;*.webp;*.bmp;*.svg;*.avif)",
                      "所有文件 (*.*)") if images else ("所有文件 (*.*)",))
            try:
                res = win.create_file_dialog(kind, allow_multiple=True, file_types=types)
            except TypeError:
                try:
                    res = win.create_file_dialog(kind, allow_multiple=True)
                except TypeError:
                    res = win.create_file_dialog(kind)
            if not res:
                return {"ok": False, "cancelled": True, "msg": "没选（取消了）"}
            paths = [res] if isinstance(res, str) else list(res)
            out = []
            for raw in paths:
                path = str(raw or "").strip()
                if not path:
                    continue
                try:
                    size = os.path.getsize(path)
                except OSError:
                    size = 0
                out.append({"path": path, "name": os.path.basename(path), "size": size})
            if images:
                out = [x for x in out if re.search(
                    r"\.(png|jpe?g|gif|webp|bmp|svg|ico|avif)$", x["path"], re.I)]
            return {"ok": True, "files": out, "count": len(out)}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "挑附件失败：%s: %s" % (type(e).__name__, e)}

    def ai_ui_state(self):
        """读 AI 页自己的轻量偏好（当前只有调色盘颜色）。

        ★ 不用 localStorage：`_page_url` 每次启动都带随机端口 / token，源会变
          （和 `_ui_order.json` 同一个坑），所以照旧存进 user_data/state。
        """
        f = USER_DATA / "state" / "_ai_ui.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except Exception:                                               # noqa: BLE001
            data = {}
        palette = str((data or {}).get("palette") or "") if isinstance(data, dict) else ""
        if not re.match(r"^#[0-9a-fA-F]{6}$", palette):
            palette = ""
        return {"ok": True, "palette": palette}

    def ai_ui_state_set(self, values=None):
        """保存 AI 页偏好。只认白名单键，颜色必须是 `#RRGGBB` 或空串。"""
        try:
            src = values if isinstance(values, dict) else {}
            f = USER_DATA / "state" / "_ai_ui.json"
            try:
                data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
            except Exception:                                           # noqa: BLE001
                data = {}
            if not isinstance(data, dict):
                data = {}
            if "palette" in src:
                palette = str(src.get("palette") or "").strip()
                if palette and not re.match(r"^#[0-9a-fA-F]{6}$", palette):
                    return {"ok": False, "msg": "颜色格式不对（要 #RRGGBB）"}
                data["palette"] = palette
            d = USER_DATA / "state"
            d.mkdir(parents=True, exist_ok=True)
            tmp = f.with_name(f.name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            os.replace(str(tmp), str(f))
            return {"ok": True, "palette": str(data.get("palette") or "")}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": str(e)}

    # ------------------------------------------------------------ 更名跟随（`V-355`）
    #   界面每 2.5 秒问一次："包表变了吗 / 谁改名了"。**纯读盘、不起进程** ——
    #   起一次 `moss.exe` 要 1 秒，这种轮询绝不能走那条路。
    def pkg_watch(self):
        """回 `{ok, renamed, gone, changed, ids}`（含义见 `_pkg_watch_poll`）。"""
        try:
            got = _pkg_watch_poll()
        except Exception as e:                                         # noqa: BLE001
            _note("pkg_watch 失败：%r" % (e,))
            return {"ok": False, "renamed": [], "gone": [], "changed": False, "ids": [],
                    "msg": str(e)}
        got["ok"] = True
        return got

    # ------------------------------------------------------------ 自动启动（`V-356` / `V-358`）
    def autostart_get(self):
        """「详情」页那一块要的数据：**条目表** + 可选的插件清单（提示用）。

        ★ 没有"总开关"：每条自己一个 `on`（`V-358` 你去掉那个开关的）。
        """
        return {"ok": True, "items": _autostart_read(),
                "packages": [{"id": str(p.get("id") or ""),
                              "name": str(p.get("name") or p.get("id") or ""),
                              "kind": str(p.get("kind") or "")}
                             for p in (DATA.get("packages") or []) if p.get("id")],
                "max": AUTOSTART_MAX}

    def autostart_set(self, items=None):
        """整表存回自动启动（原子写 `user_data/state/_ui_autostart.json`）。

        ★ 界面上那几下（加入 / 改参数 / 开关 / 删掉）都是"改内存里那一份 → 整表存回来"，
          和插件列表排序（`list_state_set`）一个路子：**没有"保存"按钮漏掉一半**这种事。
        """
        rows = []
        for it in (items or [])[:AUTOSTART_MAX]:
            if not isinstance(it, dict):
                continue
            pid = str(it.get("id") or "").strip()
            if not pid:
                continue
            rows.append({"kind": "hist" if str(it.get("kind")) == "hist" else "pkg",
                         "id": pid[:400], "args": str(it.get("args") or "")[:400],
                         "cwd": str(it.get("cwd") or "")[:400],
                         "name": str(it.get("name") or "")[:120],
                         "on": it.get("on") is not False})
        try:
            AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = AUTOSTART_FILE.with_name(AUTOSTART_FILE.name + ".tmp")
            tmp.write_text(json.dumps({"items": rows}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(str(tmp), str(AUTOSTART_FILE))
        except Exception as e:                                         # noqa: BLE001
            return {"ok": False, "msg": "存不了：%s" % e}
        return {"ok": True, "items": rows}

    # ------------------------------------------------------------ 寄生模式（`V-379`）
    def parasite_get(self):
        """「详情」页那一行要的数据：**名单**（哪些包开着寄生模式）。

        ★ 名单是"你的用法选择"（存 `user_data/state/_ui_parasite.json`），不是包的属性。
        """
        return {"ok": True, "ids": _parasite_read()}

    def parasite_set(self, ids=None):
        """整表存回寄生模式名单（原子写，和 `autostart_set` 一个路子）。

        ★ 界面上就一下（拨开关）⇒ 改内存里那一份 → 整表存回来；没有"保存按钮漏掉一半"这种事。
        """
        rows = []
        for i in (ids or []):
            s = str(i or "").strip()
            if s and s[:400] not in rows:
                rows.append(s[:400])
        try:
            PARASITE_FILE.parent.mkdir(parents=True, exist_ok=True)
            tmp = PARASITE_FILE.with_name(PARASITE_FILE.name + ".tmp")
            tmp.write_text(json.dumps({"ids": rows}, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            os.replace(str(tmp), str(PARASITE_FILE))
        except Exception as e:                                         # noqa: BLE001
            return {"ok": False, "msg": "存不了：%s" % e}
        return {"ok": True, "ids": rows}

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


def _inline_html():
    """把界面的 css/js **就地展开**成一份自包含的 HTML，返回**字符串**（`V-78` / `V-277`）。

    ★ 为什么非这么做：页面里十几个 `script`/`link`，每一个都要过一次本地 http。
      实测那条路会抖（同一个源、同一秒：一半请求 200，另一半连服务都没进到，
      浏览器报 `ERR_CONNECTION_REFUSED`）⇒ `Vue is not defined` / `$ is not defined`
      ⇒ 界面半死不活。展开成一份之后，**子资源请求数变成 0**，它再抖也伤不到界面。
    ★ 源码仍然是拆开的多文件（`system/ui/css|js/*`）；这一步只是运行时的组装。
    ★ `V-277`（你提的）：**组装结果只放内存，不落盘** —— 以前写在
      `user_data/state/_ui_inline.html`，可那是**界面的构建产物、不是用户数据**，
      放那儿名不正言不顺（还逼着服务在 `_EMBED_ALLOW` 里为它开一个例外）。
      现在由 `_EmbedHandler` 用一个虚拟地址（`__ui_live.html`）直接从内存发出去；
      `moss ui --debug` 时另外 dump 一份到 `%TEMP%` 供人打开看（那份不对外服务）。
    ★ 组装不了就返回 None，调用方退回原来的做法（绝不因为这点事让界面开不了）。
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
        # 图标表（`V-267`）：`system/icon/svg/*.svg` 读出来插在 `<body>` 后面。
        # ★ 必须插在**所有脚本之前**：`vendor/lucide.js` 的 `ico()` 在**定义时**不看表，
        #   但页面里 `paintStaticIcons()` 之类是加载期就调 `ico()` 的 —— 表得先在那儿。
        html = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + "\n" + icons.script_tag(), html,
                      count=1, flags=re.I)
        # ★ `V-271` / `V-277`：在页面里**自己写一句"这是运行时组装的"** —— 不然谁在 devtools
        #   里看到这一大坨，会以为界面就长在这儿。放在 doctype **后面**。
        html = re.sub(r"(<!doctype[^>]*>)",
                      lambda m: m.group(1) + "\n"
                      "<!-- 这是 moss 启动时**在内存里**把 css/js/图标表组装成的一份自包含页面"
                      "（好让页面一个子请求都不用发）。它**不在磁盘上**，你看到的这一坨不是源："
                      "要改界面请改 system/ui/**（index.html / css/*.css / js/*.js），然后重启 moss；"
                      "组装逻辑在 system/ui/main.py 的 _inline_html()。"
                      "想看它长什么样：`moss ui --debug` 会在 %TEMP% 留一份。 -->",
                      html, count=1, flags=re.I)
        return html
    except Exception as e:                                            # noqa: BLE001
        _note("page: 组装自包含页面失败（%r），退回原做法" % (e,))
        return None


#: `V-277`：组装好的那份自包含页面（**只放内存**）。`_page_url()` 填，`_EmbedHandler` 发。
#: 虚拟地址就叫这个 —— 它不是磁盘上的文件，服务认得这个词、直接从内存答。
_LIVE = {"html": ""}
LIVE_NAME = "__ui_live.html"


def _drop_legacy_inline():
    """`V-277`：把老版本遗留在 `user_data/state/` 里的 `_ui_inline.html` 删掉（一次性）。

    ★ 它在 `user_data/` 里不进 git、删了也不影响运行；只是别再让那个"看着像用户数据"的
     856 KB 文件躺在那儿了（你提的：那个文件本来就不该在用户目录里）。
    """
    p = USER_DATA / "state" / "_ui_inline.html"
    try:
        if p.is_file():
            p.unlink()
            _note("page: 清掉了老位置的 _ui_inline.html（那份自包含页面现在只放内存）")
    except OSError:
        pass


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
    _drop_legacy_inline()
    # ★ 优先用"组装成一份"的页面（`V-78`）：子资源请求 0，那条会抖的传输碰不到它。
    #   `V-277`：这份**不落盘**，走一个虚拟地址、由 `_EmbedHandler` 从内存答。
    html = _inline_html()
    if html:
        _LIVE["html"] = html
        url = "http://127.0.0.1:%d/%s/%s" % (port, token, LIVE_NAME)
        _note("page: 界面从 %s 加载（自包含：css/js 已内联，%d KB，只在内存里）"
              % (url, len(html.encode("utf-8")) // 1024))
        _dump_live_for_debug(html)
        return url
    url = "http://127.0.0.1:%d/%s/%s" % (port, token, rel.as_posix())
    _note("page: 界面从 %s 加载（没组装成自包含，按多文件走）" % url)
    return url


def _dump_live_for_debug(html):
    """`--debug` 时把这份自包含页面**另存一份**到 `%TEMP%`，方便直接打开看（不对外服务）。"""
    if not any(a in ("--debug", "--dev", "-d") for a in sys.argv[1:]):
        return
    try:
        import tempfile                                               # noqa: PLC0415
        p = Path(tempfile.gettempdir()) / "moss_ui_inline.html"
        p.write_text(html, encoding="utf-8", newline="")
        _note("page: （--debug）这份自包含页面也存了一份到 %s" % p)
    except OSError:
        pass


# ================================================================ 窗口图标（`V-182`）
# ★ 症状：打包之后跑起来，窗口**左上角那颗还是 python 的 logo**，不是我们的 ico。
# ★ 根因（和"图标有没有嵌进 exe"是两件不相干的事，所以嵌了也没用）：pywebview 的
#   Windows 后端**造窗时自己就把窗口图标设成了"当前解释器 exe 的图标"** ——
#   `webview/platforms/winforms.py`：
#       handle = kernel32.GetModuleHandleW(None)
#       icon_handle = windll.shell32.ExtractIconW(handle, sys.executable, 0)
#       if icon_handle != 0: self.Icon = Icon.FromHandle(...).Clone()
#   而界面是**自带运行时**跑的（`core/ui.py` ⇒ `system/runtimes/python/3.12/python.exe`），
#   那个 exe 的图标正是 python 的 logo ⇒ 窗口左上角、任务栏、Alt+Tab 全是它。
#   官方那条 `webview.start(icon=...)` 参数文档里写明 **只在 GTK/QT 上有效**，
#   Windows 这条路走不通。（实测对照：不换的时候 `WM_GETICON` 回来的句柄就是
#   python.exe 那个图标；`ExtractIconW(python.exe)` 拿到的正是它。）
# ★ 怎么换：等窗口在了，拿 **`WM_SETICON`** 把大 / 小图标都指到我们那份 ico
#   （大图标 = 标题栏 + 任务栏，小图标 = Alt+Tab、标题栏小尺寸）。图标用的是
#   **和构建时嵌进 exe 的同一份文件**（`system/icon/moss.ico`，见 `_favicon_file`）。
# ★★ 两个坑，都是实测踩出来的（`V-182`）：
#   ① **不许从 pywebview 的事件回调里换** —— `window.events.shown/loaded += …` 那条路
#      看着最自然（"窗口刚建出来就换"），实测**会把界面整个卡死**：事件处理函数是
#      pywebview 起的一个**后台线程**里跑的（`webview/event.py` 的 `Event.set` 里
#      `threading.Thread(target=execute).start()`），在那个线程里去动窗口，界面从此
#      一帧都不再抽消息（探针实测：`WM_NULL` 一直超时、日志停在换图标那一行为止）。
#      改成 **`webview.start(func)` 给的那个线程**（`_arm_file_drop`，人家本来就在跟
#      窗口打交道：挂 drop 监听）就一切正常。
#   ② **用 `SendMessageTimeoutW` 而不是 `SendMessageW`** —— 跨线程/跨进程的同步
#      `SendMessage` 一旦对面不抽消息就是**无限等**（我第一版探针就这么把自己和目标
#      窗口一起等死了）。带上 2 秒超时，最坏情况也只是这次没换上，卡不住人。
_ICON_KEEP = []          # 保住 LoadImage 出来的句柄：窗口还在用它，别让它被回收


def _moss_hwnds():
    """本进程**所有可见的顶层窗口**（主窗口 + 浮动窗口们）。
    ★ 从 `V-192` 起不按标题挑了：浮动窗口的标题是**包名**，按 "moss" 挑就只挑得到主窗口，
      浮动窗口会一直顶着 python 的 logo。反正是我们自己进程的窗口，一次全换最省心
      （有属主的窗口在 `_top_windows` 里已经被滤掉了）。
    """
    me = os.getpid()
    return [w["hwnd"] for w in _top_windows() if w["pid"] == me and w["visible"]]


def _apply_window_icon(win=None):
    """把界面窗口的图标换成我们那份 ico（`V-182`）。成功返回 True。

    ★ 只在 `_arm_file_drop` 那个线程里叫它（见上面①②两条）。
    """
    ico = _favicon_file()
    if ico is None:
        _note("icon: 找不到 %s，窗口图标保持系统那个" % (_FAVICON_RELS[0],))
        return False
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int,
                                   ctypes.c_int, wt.UINT]
        u32.LoadImageW.restype = wt.HANDLE
        u32.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, wt.UINT, wt.WPARAM,
                                            wt.LPARAM, wt.UINT, wt.UINT,
                                            ctypes.POINTER(ctypes.c_size_t)]
        u32.SendMessageTimeoutW.restype = wt.LPARAM
        # IMAGE_ICON | LR_LOADFROMFILE | LR_DEFAULTSIZE：让系统按 DPI 自己挑尺寸
        hicon = u32.LoadImageW(None, str(ico), 1, 0, 0, 0x00000010 | 0x00000040)
        if not hicon:
            _note("icon: LoadImageW 没读出 %s" % ico)
            return False
        _ICON_KEEP.append(hicon)
        hwnds = _moss_hwnds()
        for hwnd in hwnds:
            for which in (1, 0):                                       # ICON_BIG / ICON_SMALL
                r = ctypes.c_size_t(0)
                u32.SendMessageTimeoutW(hwnd, 0x0080, which, hicon,        # WM_SETICON
                                        0x0002, 2000, ctypes.byref(r))     # SMTO_ABORTIFHUNG
        _note("icon: 窗口图标换成 %s（%d 个窗口）" % (ico.name, len(hwnds)))
        return bool(hwnds)
    except Exception as e:                                             # noqa: BLE001
        _note("icon: 换窗口图标失败（%r）" % (e,))
        return False


# ================================================================ 浮动窗口（`V-192` / `V-194`）
# 一句话：**把内嵌那一帧"弹出"成 moss 自己的另一个窗口** —— 后端进程一步都不动，
# 变的只是"这一帧显示在哪个窗口里"。
#
# ★ 为什么这么设计（`V-190` ❌ 的教训）：一开始我想的是"独立窗口 = 包自己开的那个窗口"，
#   于是要解决"两个进程之间怎么搬家"（通道 / 单实例 / 状态接力，一大堆）。
#   其实**根本不用**：只要 moss 自己开第二个窗口、把同一帧搬过去，就没有第二个进程。
#   代价只有一处 —— 那一帧是新文档（前端状态重来），后端状态原样还在。
#
# ★ 三颗按钮的语义（你定的，`V-194`）：
#     · **最小化 ＝ 收回内嵌**（窗口消失、内容回主窗口那张选项卡，后端继续跑）
#     · **关闭　 ＝ 结束**（停掉后端 + 关窗）
#   最小化那条靠 pywebview 的窗口事件实现 —— Windows 后端本来就在 `Resize` 里发
#   `events.minimized`（`platforms/winforms.py:365`），不用无边框、不用自绘标题栏。
_FLOAT = {}                       # 包 id → pywebview 窗口对象（同一时刻一个包最多一个）
_FLOAT_LOCK = threading.Lock()

#: 浮动窗口的图标（`V-195`）：包自己的 `icon.*` 光栅化之后存这儿，一面多尺寸 .ico。
#: ★ 放 `user_data/state/` 下：可再生、不用备份（下次弹出会重画一遍）。
_ICON_DIR = USER_DATA / "state" / "_win_icons"


def _png_to_ico(png_bytes, out_path):
    """一张 PNG → 一面多尺寸 .ico（16/32/48/256）。

    ★ 有 PIL 就用它（自带运行时里有）；没有就退化成一个**单帧**的 PNG 型 ico ——
      ICO 容器本身很简单（6 字节头 + 每帧 16 字节目录 + 数据），Vista 起允许帧里直接放 PNG，
      所以不引依赖也做得出来，只是少几档尺寸（Windows 会自己缩）。
    """
    try:
        from io import BytesIO                                      # noqa: PLC0415
        from PIL import Image                                       # noqa: PLC0415
        im = Image.open(BytesIO(png_bytes)).convert("RGBA")
        if max(im.size) < 256:                                      # 给足最大那档，别让小图放大后糊
            im = im.resize((256, 256), Image.LANCZOS)
        im.save(str(out_path), format="ICO",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
        return
    except ImportError:
        pass
    import struct                                                   # noqa: PLC0415
    header = struct.pack("<HHH", 0, 1, 1)                            # reserved / type=icon / 1 帧
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png_bytes), 6 + 16)
    out_path.write_bytes(header + entry + png_bytes)


def _load_icon_file(path):
    """用我们自己的那份 ico 换窗口图标（`V-182` 那套，只是文件来自包自己）。"""
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int,
                                   ctypes.c_int, wt.UINT]
        u32.LoadImageW.restype = wt.HANDLE
        # IMAGE_ICON | LR_LOADFROMFILE | LR_DEFAULTSIZE：让系统按 DPI 从多尺寸里挑
        hicon = u32.LoadImageW(None, str(path), 1, 0, 0, 0x00000010 | 0x00000040)
        if hicon:
            _ICON_KEEP.append(hicon)
        return hicon
    except Exception:                                                  # noqa: BLE001
        return 0


def _hwnd_of(win):
    """pywebview 窗口对象的原生句柄（拿不到给 0）。

    ★ 能直接问 native 就别去猜：`window.native` 在 Windows 后端就是那个 WinForms `Form`，
      `.Handle` 就是 HWND。按标题找窗口是退路（标题可能和别的窗口撞）。
    """
    try:
        h = win.native.Handle
    except Exception:                                                  # noqa: BLE001
        return 0
    for cast in ("ToInt64", "ToInt32"):
        try:
            return int(getattr(h, cast)())
        except Exception:                                              # noqa: BLE001
            continue
    try:
        return int(h)
    except Exception:                                                  # noqa: BLE001
        return 0


def _hwnd_by_title(title):
    if not title:
        return 0
    for w in _top_windows():
        if w["pid"] == os.getpid() and w["visible"] and w["title"] == title:
            return w["hwnd"]
    return 0


def _wm_set_icon(hwnd, hicon):
    """大图标（标题栏 + 任务栏）和小图标（Alt+Tab）都指过去。"""
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, wt.UINT, wt.WPARAM, wt.LPARAM,
                                            wt.UINT, wt.UINT,
                                            ctypes.POINTER(ctypes.c_size_t)]
        for which in (1, 0):                                           # ICON_BIG / ICON_SMALL
            r = ctypes.c_size_t(0)
            u32.SendMessageTimeoutW(hwnd, 0x0080, which, hicon,
                                    0x0002, 2000, ctypes.byref(r))     # SMTO_ABORTIFHUNG
        return True
    except Exception:                                                  # noqa: BLE001
        return False


def _js(win, code):
    """往某个窗口里塞一段 JS（塞不进去就当没事 —— 窗口可能刚被关掉）。"""
    try:
        win.evaluate_js(code)
        return True
    except Exception:                                                  # noqa: BLE001
        return False


def _float_win(pid):
    with _FLOAT_LOCK:
        return _FLOAT.get(str(pid))


def _pkg_title(rec):
    """包标题：`ui.title` 优先（多语言取 zh-CN 或第一个），否则包自己的 name。"""
    def pick(v):
        if isinstance(v, dict):
            return str(v.get("zh-CN") or next(iter(v.values()), "") or "")
        return str(v or "")
    ui = (rec or {}).get("ui") or {}
    return (pick(ui.get("title")) or pick((rec or {}).get("name")) or "").strip()


def _destroy_soon(win, delay=0.25):
    """过一小会儿再销毁窗口。

    ★ 为什么要延后：这个函数经常是**在它自己的 js_api 调用里**被触发的（浮动窗口点
      「收回」/「停止」时，调用者就是那个窗口）—— 立刻销毁会让那次调用的回包没有落地的地方。
      让回包先回去，再关窗。
    """
    def run():
        try:
            win.destroy()
        except Exception:                                              # noqa: BLE001
            pass
    try:
        threading.Timer(delay, run).start()
    except Exception:                                                  # noqa: BLE001
        run()


def _close_float_quiet(pid):
    """把某个包的浮动窗口关掉（不触发"关闭＝结束"那套 —— 调用方自己在收尾）。"""
    with _FLOAT_LOCK:
        w = _FLOAT.pop(str(pid), None)
    if w is not None:
        _destroy_soon(w)
    return w is not None


def _dock_float(pid, why=""):
    """收回：告诉主窗口那一页把帧建回来，然后销毁浮动窗口。**后端一点不动。**"""
    pid = str(pid)
    with _FLOAT_LOCK:
        w = _FLOAT.pop(pid, None)
    _js(window, "window.__mossFloatDock && window.__mossFloatDock(%s)" % json.dumps(pid))
    if w is not None:
        _destroy_soon(w)
    _note("float: :%s 收回（%s）" % (pid, why or "？"))


def _float_closed(pid):
    """浮动窗口**被用户关掉**了 ⇒ 按约定 X ＝ 结束：停掉后端 + 告诉主窗口那一页。

    ★ 我们自己收回/停掉时会**先把记录摘掉**，所以这里摘不到记录＝不是用户关的，
      直接返回（免得"收回"被当成"结束"把后端杀了）。
    """
    pid = str(pid)
    with _FLOAT_LOCK:
        w = _FLOAT.pop(pid, None)
    if w is None:
        return
    try:
        Api().embed_stop(pid)
    except Exception as e:                                             # noqa: BLE001
        _note("float: :%s 关闭时停后端失败（%r）" % (pid, e))
    _js(window, "window.__mossFloatClosed && window.__mossFloatClosed(%s)" % json.dumps(pid))
    _note("float: :%s 被关掉 → 按约定当作结束" % pid)


def _wire_float(pid, win, title):
    """给浮动窗口挂三件事：窗口图标、最小化＝收回、关闭＝结束（`V-182` / `V-194`）。

    ★ 事件回调跑在 pywebview 自己起的线程里 —— `V-182` 的教训是"别在那个线程里直接动窗口"
      （那次换图标把界面整个卡死了）。所以这里每一件都丢给一个普通后台线程去做。
    """
    pid = str(pid)

    def later(fn, *a):
        threading.Thread(target=fn, args=a, daemon=True).start()

    win.events.minimized += lambda *a: later(_dock_float, pid, "点了最小化")
    win.events.closed += lambda *a: later(_float_closed, pid)
    win.events.shown += lambda *a: later(_apply_window_icon)
    _ = title          # 标题已经由 create_window 定好（winforms 后端不会让网页标题盖掉它）


_PAGE_URL = _page_url()          # 主窗口那一页的地址；浮动窗口用同一个，只多一个 #float=<id>
_API = Api()                     # 两个窗口共用同一个 js_api 实例（浮动窗口里也要能用 embed_*）

# ★ `V-223`：主窗口的**大小和位置**记在 `user_data/state/_ui_window.json`，下次开还在这儿。
#   双屏的坑（坐标是虚拟屏的、副屏在主屏左边就是负数）、拔屏、换分辨率、最大化/最小化
#   都在 `win_geom.py` 里处理，这里只负责"读回来 → 建窗 → 盯着它"。
#   任何一步出问题都**不影响开界面**（读不出来就按默认 + 居中）。
_WIN_GEOM_FILE = USER_DATA / "state" / win_geom.WIN_GEOM_NAME
_WIN_GEOM = win_geom.resolve(win_geom.load(_WIN_GEOM_FILE))

window = webview.create_window(
    "moss",
    _PAGE_URL,
    js_api=_API,
    width=_WIN_GEOM["width"],
    height=_WIN_GEOM["height"],
    x=_WIN_GEOM["x"],                 # None = 交给 pywebview 居中（拔了屏就是这样）
    y=_WIN_GEOM["y"],
    min_size=win_geom.WIN_MIN_SIZE,
    maximized=_WIN_GEOM["maximized"],  # 上次是最大化的，这次也最大化
    # ★ text_select 默认是 **False**，页面上的字**选不中**（拖不动、也没法 Ctrl+C）——
    #   pywebview 的 `create_window(..., text_select: bool = False)`。
    #   命令行窗口最要紧的就是"能选中、能复制"，所以这里必须打开它；
    #   页面里也给 `#out` 写了 user-select:text，另外配了「复制全部」按钮。
    text_select=True,
)
_GEOM_WATCH = win_geom.watch(window, _WIN_GEOM_FILE, note=lambda s: _note("main: " + s))

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
                        "path": f.get("pywebviewFullPath"),
                        "type": f.get("type") or "", "size": f.get("size") or 0})
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
        try:
            _size = int(f.get("size") or 0)
        except (TypeError, ValueError):
            _size = 0
        _name = os.path.basename(str(p))
        _one = {"path": str(p), "isDir": bool(is_dir),
                "dir": str(p) if is_dir else os.path.dirname(str(p)),
                "name": _name}
        if not is_dir:
            _one["mime"] = str(f.get("type") or "")
            _one["size"] = _size
        items.append(_one)
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
        _apply_window_icon(window)          # `V-182`：窗口这时一定在了，换成我们那份 ico
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
    # ★ `V-354`：关窗口那一刻要干的事（按设置把插件进程收掉）。挂的是**主窗口** ——
    #   浮动窗口（`ui_float` 开的那些）不挂：关一个浮动窗口顺手把插件全杀了是不对的。
    window.events.closing += _on_ui_closing
    webview.start(_arm_file_drop, debug=DEBUG)
