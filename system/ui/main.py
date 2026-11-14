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

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import win_geom
import icons

NO_WINDOW = 0x08000000
DETACHED = 0x00000008
DEVNULL = subprocess.DEVNULL

_WEBVIEW2_PAGE = "https://developer.microsoft.com/microsoft-edge/webview2/"
_WEBVIEW2_X64 = "https://go.microsoft.com/fwlink/p/?LinkId=2124701"
_WEBVIEW2_BOOT = "https://go.microsoft.com/fwlink/p/?LinkId=2124703"
_NETFX_PAGE = "https://dotnet.microsoft.com/download/dotnet-framework/net48"

_WV2_GUIDS = (
    "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
    "{2CD8A007-E189-409D-A2C8-9AF4EF3C72AA}",
    "{0D50BFEC-CD6A-4F9A-964C-C7416E3ACB10}",
    "{65C35B14-6C1D-4122-AC46-7148CC9D6497}",
)
_WV2_MIN = (86, 0, 622, 0)
_NETFX_462 = 394802

def _ver4(text):
    out = []
    for part in str(text).split("."):
        if not part.isdigit():
            break
        out.append(int(part))
    out = (out + [0, 0, 0, 0])[:4]
    return tuple(out)

def _netfx_release():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full") as k:
            return int(winreg.QueryValueEx(k, "Release")[0] or 0)
    except Exception:
        return 0

def _wv2_builds():
    try:
        import winreg
    except Exception:
        return []
    found = []
    for root, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node"),
                      (winreg.HKEY_CURRENT_USER, r"SOFTWARE")):
        for guid in _WV2_GUIDS:
            try:
                key = sub + r"\Microsoft\EdgeUpdate\Clients" + "\\" + guid
                with winreg.OpenKey(root, key) as k:
                    found.append(str(winreg.QueryValueEx(k, "pv")[0]))
            except Exception:
                pass
    return found

def webview2_status():
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
    import urllib.request
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
    try:
        p = subprocess.run([str(exe), "/silent", "/install"], timeout=900,
                           creationflags=NO_WINDOW)
        if p.returncode in (0, 3010):
            return True
    except Exception:
        pass
    try:
        import ctypes
        r = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(exe), "/silent /install", None, 1)
        return int(r) > 32
    except Exception:
        return False

def _webview2_dialog(detail):
    try:
        import queue
        import tempfile
        import tkinter as tk
        import webbrowser
        from tkinter import ttk
    except Exception as e:
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                None,
                "moss 的界面需要「Microsoft Edge WebView2 运行时」，这台电脑没有：\n"
                "    %s\n\n请自己装一个（是运行时，不是 Edge 浏览器）：\n%s"
                % (detail, _WEBVIEW2_PAGE),
                "moss", 0x10)
        except Exception:
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
    root.withdraw()
    root.title("moss · 需要 WebView2 运行时")
    root.configure(bg=BG)
    root.resizable(False, False)
    w, h = 566, 344
    root.geometry("%dx%d+%d+%d" % (w, h, max(0, (root.winfo_screenwidth() - w) // 2),
                                   max(0, (root.winfo_screenheight() - h) // 3)))
    try:
        root.iconbitmap(default=str(HERE.parent / "icon" / "moss.ico"))
    except Exception:
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

    btns = tk.Frame(box, bg=BG)
    btns.pack(fill="x", side="bottom")

    foot = tk.Label(box, text="", bg=BG, fg=DIM, font=FONT, anchor="w", wraplength=520)
    foot.pack(fill="x", side="bottom", pady=(6, 10))

    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    style.configure("Moss.Horizontal.TProgressbar", troughcolor="#ececf0",
                    background=ACCENT, bordercolor="#ececf0", lightcolor=ACCENT,
                    darkcolor=ACCENT, thickness=8)
    prog = ttk.Progressbar(box, style="Moss.Horizontal.TProgressbar", orient="horizontal",
                           mode="determinate", maximum=100, value=0)
    prog.pack(fill="x", side="bottom")

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
        except Exception:
            pass

    def start():
        b_run.configure(state="disabled", text="正在下载…")
        b_page.configure(state="disabled")
        foot.configure(fg=DIM, text="准备下载…")
        threading.Thread(target=work, daemon=True).start()

    def work():
        tmp = Path(tempfile.gettempdir()) / "moss-webview2"
        try:
            tmp.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            q.put(("fail", "建不了临时目录：%s" % e))
            return
        exe = tmp / "MicrosoftEdgeWebView2RuntimeInstallerX64.exe"
        last = None
        okdl = False
        for url, name in ((_WEBVIEW2_X64, "独立安装包（约 205 MB）"),
                          (_WEBVIEW2_BOOT, "联机引导器（约 2 MB）")):
            if res["cancel"]:
                return
            q.put(("say", "正在下载%s…" % name))
            try:
                _download(url, exe, lambda d, t: q.put(("pct", d, t)), res)
                okdl = True
                break
            except Exception as e:
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
        for _ in range(120):
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
        mk("先装 .NET 4.8", lambda: webbrowser.open(_NETFX_PAGE)).pack(side="left")

    root.protocol("WM_DELETE_WINDOW", lambda: close(False))
    try:
        root.update_idletasks()
        root.deiconify()
        root.attributes("-topmost", True)
        root.after(400, lambda: root.attributes("-topmost", False))
    except Exception:
        root.deiconify()
    root.after(120, pump)
    root.mainloop()
    return res["ok"]

def _webview2_preflight():
    if "--check-webview2" in sys.argv[1:]:
        ok, detail = webview2_status()
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
    path = Path(p)
    data = json.loads(path.read_text(encoding="utf-8"))
    try:
        path.unlink()
    except OSError:
        pass
    return data

DATA = _load_data()
HOST = [str(x) for x in (DATA.get("host_cmd") or [])]

def _shell_line(argv):
    out = []
    for a in argv:
        a = str(a)
        if a == "" or any(c in a for c in ' \t&|^<>()'):
            out.append('"' + a.replace('"', '""') + '"')
        else:
            out.append(a)
    return " ".join(out)

def _split(text):
    text = (text or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError:
        return text.split()

def _ai_arg(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (list, tuple)):
        return ",".join(str(x).strip() for x in v if str(x).strip())
    return str(v)

def _run_capture(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW)
    except OSError as e:
        return {"code": -1, "out": "启动失败：%s" % e}
    return {"code": r.returncode, "out": (r.stdout or "") + (r.stderr or "")}

def _run_capture_split(argv):
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW)
    except OSError as e:
        return {"code": -1, "out": "", "err": "启动失败：%s" % e}
    return {"code": r.returncode, "out": r.stdout or "", "err": r.stderr or ""}

def _json_from_host(out):
    s = (out or "").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except ValueError:
        pass
    got = _first_json(s)
    return got if isinstance(got, dict) else None

MAX_READ = 2 * 1024 * 1024
TRASH_DIRNAME = "trash"

SEARCH_MAX_FILES = 200000
SEARCH_MAX_HITS = 800
SEARCH_MAX_PER_FILE = 48
SEARCH_MAX_BYTES = MAX_READ
SEARCH_LINE_MARKS = 8
SEARCH_LINE_MAX = 240
SEARCH_SKIP_DIRS = {"__pycache__", "node_modules", "venv", ".venv", "site-packages",
                    "dist", "build", ".tox", ".mypy_cache", ".pytest_cache", "runtimes"}
SEARCH_SKIP_TOP = {"trash", "backups"}
SEARCH_BIN_EXT = set("""
    png jpg jpeg gif bmp webp ico tif tiff psd raw heic avif
    exe dll so dylib pyd pyc pyo class jar war zip 7z rar gz tgz bz2 xz zst cab iso dmg msi
    mp3 wav flac ogg m4a aac wma mp4 mkv avi mov wmv flv webm m4v
    pdf doc docx xls xlsx ppt pptx
    ttf otf woff woff2 eot
    db sqlite sqlite3 mdb npy npz pkl bin dat pak
""".split())

def _search_skip_dir(here, d):
    if d in SEARCH_SKIP_DIRS or d.startswith("."):
        return True
    return d == "packages" and here.parent.name == "pkgs"

def _search_hit(line_no, line, matches):
    line = str(line).rstrip("\r\n")
    cols = [[m.start(), max(1, m.end() - m.start())] for m in matches][:SEARCH_LINE_MARKS]
    if len(line) > SEARCH_LINE_MAX:
        mid = cols[0][0] if cols else 0
        start = max(0, min(mid - SEARCH_LINE_MAX // 3, len(line) - SEARCH_LINE_MAX))
        cut = line[start:start + SEARCH_LINE_MAX]
        head = "…" if start > 0 else ""
        tail = "…" if start + len(cut) < len(line) else ""
        keep = []
        for c, n in cols:
            if c < start or c + n > start + len(cut):
                continue
            keep.append([c - start + len(head), n])
        line, cols = head + cut + tail, keep
    return {"line": int(line_no), "text": line, "cols": cols}

HOME = Path(os.environ.get("MOSS_HOME") or ".")
USER_DATA = Path(os.environ.get("MOSS_USER_DATA_DIR") or (HOME / "user_data"))

ROOTS = [
    {"key": "user", "label": "user_data", "path": USER_DATA, "writable": True,
     "why": "本地安装的包 / 配置 / 数据"},
    {"key": "system", "label": "system", "path": HOME / "system", "writable": True,
     "why": "出厂件（随 moss.exe 分发）—— 能改，但升级时会被整体替换"},
]

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
    s = str(sub or "").strip()
    if re.fullmatch(r"[A-Za-z]:", s):
        s += "/"
    p = Path(s)
    if not p.is_absolute():
        raise ValueError("`%s/` 后面要跟一个**绝对路径**，收到的是 '%s'" % (ABS_KEY, sub))
    return p

def _resolve(rel):
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
    p = Path(path).resolve()
    for r in ROOTS:
        base = Path(r["path"]).resolve()
        if p == base:
            return r["key"]
        if base in p.parents:
            return r["key"] + "/" + p.relative_to(base).as_posix()
    return None

def _rel_page(path):
    rel = _rel_of(path)
    if rel:
        return rel
    return ABS_KEY + "/" + Path(path).resolve().as_posix()

def _human(n):
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

_pkg_procs = {}
_pkg_hidden = {}
EMBED = {}
EMBED_LOCK = threading.Lock()
EMBED_STOPPED = set()

_EMBED_DENY = ("user_data/config.toml", "user_data/backups/", "user_data/history/",
               "user_data/state/", "user_data/trash/", "user_data/snapshot.ignore",
               "user_data/runners.json", ".git/", "core/", "venv/")

_FAVICON_RELS = ("system/icon/moss.ico", "icon.ico")

def _favicon_file():
    for rel in _FAVICON_RELS:
        f = HOME / rel
        if f.is_file():
            return f
    return None

_EMBED_SRV = {"httpd": None, "port": 0, "token": ""}

def _remember_proc(pkg, pid):
    ct = None
    try:
        import psutil
        ct = float(psutil.Process(int(pid)).create_time())
    except Exception:
        ct = None
    _pkg_procs.setdefault(str(pkg), set()).add((int(pid), ct))

def _live_roots(roots):
    out = set()
    for item in roots:
        try:
            pid, ct = item
        except (TypeError, ValueError):
            out.add(int(item))
            continue
        if ct is None:
            out.add(int(pid))
            continue
        try:
            import psutil
            if abs(float(psutil.Process(int(pid)).create_time()) - ct) < 0.01:
                out.add(int(pid))
        except Exception:
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
    out = {}
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
        snap = k32.CreateToolhelp32Snapshot(0x00000002, 0)
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
            if u32.GetWindow(hwnd, 4):
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

_HELPER_CLASSES = ("TtkMonitorClass",)

def _hist_read_all():
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
    return "|".join([
        str(r.get("kind") or ""),
        str(r.get("id") or r.get("target") or ""),
        json.dumps(r.get("params") or {}, sort_keys=True, ensure_ascii=False),
        json.dumps(r.get("args") or [], ensure_ascii=False),
    ])

def _hist_is_record(r):
    return (r.get("kind") or "") != "pkg"

def _hist_drop_lines(path, key):
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

_BOMS = [
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
]
_TRY = ("utf-8", "gbk", "big5", "shift_jis", "latin-1")

def _looks_binary(raw):
    head = raw[:8192]
    if b"\x00" in head:
        return True
    ctrl = sum(1 for b in head if b < 9 or (13 < b < 32))
    return bool(head) and ctrl / len(head) > 0.10

def _decode_text(raw):
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            try:
                return raw[len(bom):].decode(enc), enc, bom.hex()
            except (UnicodeDecodeError, LookupError):
                break
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
                cl = pr.cmdline() or []
                if cl:
                    item["cmd"] = " ".join(cl)[:200]
            except Exception:
                pass
        out.append(item)
    return out

def _env_pkg_id(pid):
    try:
        import psutil
        return (psutil.Process(int(pid)).environ() or {}).get("MOSS_PKG_ID")
    except Exception:
        return None

def _pids_by_cmdline():
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
    names = [str(pid)] + _pkg_dir_names(pid)
    return ["/pkgs/%s/" % n.replace("\\", "/").lower() for n in names if n]

_RUNNER_EXES = {
    "python", "pythonw", "py", "python3", "go", "node", "deno", "bun", "java", "javaw",
    "ruby", "perl", "php", "lua", "rscript", "dotnet", "cmd", "powershell", "pwsh",
    "wscript", "cscript", "sh", "bash", "mshta", "moss",
}

def _pkg_run_match(cl, needle):
    if needle not in cl:
        return False
    head = cl.strip().split(" ", 1)[0].strip('"')
    name = head.rsplit("/", 1)[-1]
    if name.endswith(".exe"):
        name = name[:-4]
    if name in _RUNNER_EXES:
        return True
    return needle in head

def _pkg_dirs(pid):
    out = []
    for p in (DATA.get("packages") or []):
        if str(p.get("id")) != str(pid):
            continue
        d = p.get("dir")
        if d and str(d) not in out:
            out.append(str(d))
    return out

def _exe_under(pid, dirs):
    if not dirs:
        return False
    try:
        import psutil
        exe = str(psutil.Process(int(pid)).exe() or "")
    except Exception:
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
    pids |= {pid for pid, k in owner_pkg.items()
             if k == pkg and _exe_under(pid, _pkg_dirs(pkg))}
    pids.discard(os.getpid())
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

RUNS = {}
RUNS_LOCK = threading.Lock()
RUNS_KEEP = 20

_TERM = {"mod": None, "err": ""}

def _term_mod():
    if _TERM["mod"] is None and not _TERM["err"]:
        try:
            import term as _t
        except Exception as e:
            _TERM["err"] = "终端模块加载不了：%s" % e
        else:
            _TERM["mod"] = _t
    return _TERM["mod"]

AI = {"thread": None, "state": None, "task": "", "stop": False, "t0": 0.0}
AI_LOCK = threading.Lock()

_PERM_DENY = {}

def _perm_key(pth):
    try:
        return str(Path(str(pth or "")).resolve()).rstrip("\\/").lower()
    except Exception:
        return str(pth or "").rstrip("\\/").lower()

_AI_CFG = {"t0": 0.0, "got": None}

def _first_json(text):
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
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=NO_WINDOW)
    except Exception:
        pass

def _embed_server():
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
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = int(os.environ.get("MOSS_EMBED_BACKLOG") or 128)

class _EmbedHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(HOME), **kw)

    def log_message(self, *a):
        pass

    def send_response(self, code, message=None):
        try:
            line = "%s  %s  %s\n" % (time.strftime("%H:%M:%S"), code, self.path)
            path = USER_DATA / "state" / "_ui_http.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > 64 * 1024:
                keep = path.read_text(encoding="utf-8", errors="replace")[-16 * 1024:]
                path.write_text(keep, encoding="utf-8")
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(line)
        except Exception:
            pass
        super().send_response(code, message)

    def _token_ok(self):
        tk = _EMBED_SRV["token"]
        return bool(tk) and self.path.startswith("/" + tk + "/")

    def _serve_favicon(self):
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

    def do_GET(self):
        if self._serve_favicon():
            return
        if not self._token_ok():
            self.send_error(403, "bad token")
            return
        super().do_GET()

    def do_HEAD(self):
        if self._serve_favicon():
            return
        if not self._token_ok():
            self.send_error(403, "bad token")
            return
        super().do_HEAD()

    def _rel_of(self, path):
        p = str(path or "").split("?", 1)[0].split("#", 1)[0]
        tk = _EMBED_SRV["token"]
        if tk and p.startswith("/" + tk + "/"):
            p = p[len(tk) + 1:]
        return p.lstrip("/")

    def _serve_live(self):
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
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        return True

    def _blocked(self, rel):
        for d in _EMBED_DENY:
            if rel == d or rel.startswith(d):
                return "denied"
        if (HOME / rel).is_dir():
            return "no listing"
        return None

    def send_head(self):
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
            path = path[len(tk) + 1:]
        raw = urllib.parse.unquote(str(path or "").split("?", 1)[0].split("#", 1)[0]).lstrip("/")
        if raw.startswith("abs/"):
            try:
                return str(Path(raw[len("abs/"):]))
            except OSError:
                return ""
        return super().translate_path(path)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

def _pump_embed(pid, proc):
    try:
        for line in proc.stdout:
            s = (line or "").rstrip("\n")
            if not s.strip():
                continue
            if s.lstrip().startswith("{"):
                try:
                    _js(_float_win(pid) or window,
                        "window.__mossEmbedFromBackend(%s, %s)"
                        % (json.dumps(str(pid)), json.dumps(s, ensure_ascii=False)))
                except Exception:
                    pass
            else:
                with EMBED_LOCK:
                    rec = EMBED.get(pid)
                    if rec is not None:
                        rec["lines"].append(s + "\n")
                        if len(rec["lines"]) > 500:
                            del rec["lines"][:200]
    except Exception:
        pass
    finally:
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        code = proc.returncode
        with EMBED_LOCK:
            if EMBED.get(pid, {}).get("proc") is proc:
                EMBED.pop(pid, None)
            was_stopped = proc in EMBED_STOPPED
            EMBED_STOPPED.discard(proc)
        if was_stopped:
            return
        try:
            _js(_float_win(pid) or window,
                "window.__mossEmbedGone(%s, %s)" % (json.dumps(pid), json.dumps(code)))
        except Exception:
            pass

def _oem_encoding():
    try:
        import ctypes
        return "cp%d" % int(ctypes.windll.kernel32.GetOEMCP())
    except Exception:
        return "utf-8"

def _cmd_new_cwd(base, arg):
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
    r = RUNS.get(rid)
    if not r:
        return
    proc = r["proc"]
    pending = [""]
    stop = threading.Event()

    def emit(text):
        if not text:
            return
        with RUNS_LOCK:
            r["lines"].append(text)

    def ticker():
        while not stop.wait(0.12):
            with RUNS_LOCK:
                chunk, pending[0] = pending[0], ""
            emit(chunk)

    threading.Thread(target=ticker, daemon=True).start()

    def watcher():
        try:
            proc.wait()
        except Exception:
            return
        time.sleep(0.35)
        with RUNS_LOCK:
            if r.get("code") is None:
                r["code"] = proc.returncode

    threading.Thread(target=watcher, daemon=True).start()
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
                pending[0] = parts.pop()
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

_SETTINGS_RULES = {"mod": None, "tried": False}
_SETTINGS_CUR = {}

def _settings_rules():
    if _SETTINGS_RULES["tried"]:
        return _SETTINGS_RULES["mod"]
    _SETTINGS_RULES["tried"] = True
    try:
        import importlib.util
        path = HOME / "system" / "option" / "rules.py"
        spec = importlib.util.spec_from_file_location("moss_settings_rules", str(path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _SETTINGS_RULES["mod"] = mod
    except Exception as e:
        _note("settings: 读不到 system/option/rules.py（%r）—— 校验退回叫宿主" % (e,))
    return _SETTINGS_RULES["mod"]

def _settings_current():
    return dict(_SETTINGS_CUR)

DEFAULT_KILL_ON_EXIT = False

_CFG_CACHE = {"t": 0.0, "data": None}

def _cfg(section, key, default=None):
    now = time.time()
    if _CFG_CACHE["data"] is None or (now - _CFG_CACHE["t"]) > 2.0:
        data = {}
        try:
            import tomllib
            data = tomllib.loads((USER_DATA / "config.toml").read_text(encoding="utf-8"))
        except Exception:
            data = {}
        _CFG_CACHE["data"] = data if isinstance(data, dict) else {}
        _CFG_CACHE["t"] = now
    try:
        val = (_CFG_CACHE["data"].get(str(section)) or {}).get(str(key), default)
    except Exception:
        val = default
    return default if val is None else val

SOUND_KINDS = ("finish", "warn")
SOUND_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".wma", ".ogg", ".flac")
SOUND_DEFAULT_ON = True

def _snd_kind(kind):
    k = str(kind or "").strip().lower()
    return k if k in SOUND_KINDS else SOUND_KINDS[0]

def _snd_builtin(kind):
    return HOME / "system" / "sound" / (_snd_kind(kind) + ".mp3")

def _snd_custom(kind):
    rel = str(_cfg("sound", _snd_kind(kind) + "_file", "") or "").strip()
    if not rel:
        return None
    p = Path(rel)
    if not p.is_absolute():
        p = USER_DATA / p
    return p if p.is_file() else None

def _snd_path(kind):
    p = _snd_custom(kind)
    if p is not None:
        return p
    b = _snd_builtin(kind)
    return b if b.is_file() else None

def _snd_on(kind):
    return bool(_cfg("sound", _snd_kind(kind) + "_on", SOUND_DEFAULT_ON))

def _snd_info(kind):
    k = _snd_kind(kind)
    rel = str(_cfg("sound", k + "_file", "") or "").strip()
    p = _snd_path(k)
    custom = _snd_custom(k)
    return {"key": k, "on": _snd_on(k), "file": rel,
            "name": p.name if p else "",
            "path": str(p) if p else "",
            "builtin": custom is None,
            "exists": bool(p)}

_SND_BAD_NAMES = {"CON", "PRN", "AUX", "NUL"} | {"COM%d" % i for i in range(1, 10)} \
    | {"LPT%d" % i for i in range(1, 10)}

def _snd_safe_name(name, kind, ext):
    stem = Path(str(name or "")).stem or _snd_kind(kind)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", stem).strip(" .-") or _snd_kind(kind)
    if stem.upper() in _SND_BAD_NAMES:
        stem = "snd_" + stem
    return stem[:48] + ext

def _snd_drop_old(kind, old, keep=None):
    if old is None:
        return
    try:
        root = (USER_DATA / "sound").resolve()
        p = Path(old).resolve()
    except OSError:
        return
    if p == root or root not in p.parents:
        return
    if keep is not None:
        try:
            if p == Path(keep).resolve():
                return
        except OSError:
            pass
    other = "warn" if _snd_kind(kind) == "finish" else "finish"
    o = _snd_custom(other)
    if o is not None:
        try:
            if Path(o).resolve() == p:
                return
        except OSError:
            pass
    try:
        p.unlink()
    except OSError:
        pass

_SND_LOCK = threading.Lock()
_SND_SEQ = [0]

def _mci(cmd, want_out=False):
    try:
        buf = ctypes.create_unicode_buffer(256) if want_out else None
        rc = ctypes.windll.winmm.mciSendStringW(
            cmd, buf if buf is not None else None, 256 if buf is not None else 0, None)
        return int(rc), (buf.value if buf is not None else "")
    except Exception:
        return -1, ""

def _snd_play_file(path):
    if os.name != "nt":
        return "非 Windows，跳过"
    ext = path.suffix.lower()
    if ext == ".wav":
        try:
            import winsound
            winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            return "wav"
        except Exception:
            pass
    with _SND_LOCK:
        _SND_SEQ[0] += 1
        alias = "moss_snd_%d" % _SND_SEQ[0]
    src = str(path).replace('"', "")
    rc, _ = _mci('open "%s" type mpegvideo alias %s' % (src, alias))
    if rc != 0:
        rc, _ = _mci('open "%s" type waveaudio alias %s' % (src, alias))
    if rc != 0:
        try:
            import winsound
            winsound.MessageBeep(0x40)
        except Exception:
            pass
        return "beep"
    try:
        _mci("play %s wait" % alias)
    finally:
        _mci("close " + alias)
    return "mci"

def _snd_start(path):
    try:
        threading.Thread(target=_snd_play_file, args=(path,), daemon=True).start()
        return True
    except Exception:
        return False

def _pkg_ids_on_disk():
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
    killed = []
    try:
        with RUNS_LOCK:
            runs = [dict(r) for r in RUNS.values()]
    except Exception:
        runs = []
    for r in runs:
        proc = r.get("proc")
        try:
            pid = int(r.get("pid") or (proc.pid if proc is not None else 0) or 0)
        except Exception:
            pid = 0
        if pid:
            _kill_tree(pid)
            killed.append(pid)
    try:
        embeds = list(EMBED.items())
    except Exception:
        embeds = []
    for _pkg, rec in embeds:
        try:
            proc = (rec or {}).get("proc")
            if proc is not None and proc.poll() is None:
                _kill_tree(proc.pid)
                killed.append(int(proc.pid))
        except Exception:
            pass
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
        except Exception:
            pass
    pids.discard(os.getpid())
    pids |= _with_descendants(pids, parents)
    pids |= _with_descendants({os.getpid()}, parents)
    pids.discard(os.getpid())
    for pid in sorted(pids):
        _kill_tree(int(pid))
        killed.append(int(pid))
    return sorted(set(killed))

def _on_ui_closing():
    try:
        if bool(_cfg("ui", "kill_pkgs_on_exit", DEFAULT_KILL_ON_EXIT)):
            pids = _kill_all_pkg_procs()
            drop_log("退出：按设置收掉插件进程 %d 个 —— %s" % (len(pids), pids[:20]))
    except Exception as e:
        drop_log("退出：收插件进程时出错（不影响关闭）：%r" % (e,))
    return True

_PKG_IDENT = {}
_PKG_DIRS = {}
_PKG_KNOWN = None

def _swap_pid(value, pid):
    if isinstance(value, str):
        return value.replace(pid, "@id@") if pid else value
    if isinstance(value, dict):
        return dict((k, _swap_pid(v, pid)) for k, v in value.items())
    if isinstance(value, list):
        return [_swap_pid(v, pid) for v in value]
    return value

def _ident_norm(data, pid):
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
    try:
        data = json.loads(Path(man).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        body = json.dumps(_ident_norm(data, pid), ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(("%s|%s" % (layer, body)).encode("utf-8")).hexdigest()
    except Exception:
        return None

def _pkg_scan():
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
            except Exception:
                broken += 1
                continue
            fp = _pkg_ident(man, layer, pid)
            if fp is None:
                broken += 1
                continue
            fps.setdefault(pid, fp)
            dirs.setdefault(pid, str(d))
    return fps, dirs, broken

def _pkg_watch_poll():
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
    for g in sorted(gone):
        hit = [a for a in added if a not in used and fps[a] == old[g]]
        if len(hit) == 1:
            used.add(hit[0])
            out["renamed"].append([g, hit[0], "指纹一致"])
    left_g = [g for g in gone if not any(r[0] == g for r in out["renamed"])]
    left_a = [a for a in added if a not in used]
    if len(left_g) == 1 and len(left_a) == 1:
        out["renamed"].append([left_g[0], left_a[0], "按新旧 id 推断"])
        used.add(left_a[0])
    for g in gone:
        if any(r[0] == g for r in out["renamed"]):
            continue
        try:
            still = Path(old_dirs.get(g) or "").is_dir()
        except OSError:
            still = False
        if not still:
            out["gone"].append(g)
    out["changed"] = bool(out["renamed"] or out["gone"] or added
                          or (set(fps) != set(old)))
    _PKG_IDENT.clear()
    _PKG_IDENT.update(fps)
    _PKG_DIRS.clear()
    _PKG_DIRS.update(dirs)
    _PKG_KNOWN = set(fps)
    return out

AUTOSTART_FILE = USER_DATA / "state" / "_ui_autostart.json"
AUTOSTART_MAX = 20

PARASITE_FILE = USER_DATA / "state" / "_ui_parasite.json"

def _parasite_read():
    try:
        data = json.loads(PARASITE_FILE.read_text(encoding="utf-8"))
    except Exception:
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
    try:
        data = json.loads(AUTOSTART_FILE.read_text(encoding="utf-8"))
    except Exception:
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
    def state(self):
        fresh = self._host_payload()
        if fresh:
            DATA.clear()
            DATA.update(fresh)
            DATA.pop("stale_reason", None)
        else:
            DATA["stale_reason"] = self._payload_error or "读包表失败（宿主没有回话）"
        return DATA

    def _host_payload(self):
        self._payload_error = ""
        if not HOST:
            self._payload_error = "没拿到宿主命令 —— 请从 moss 主程序打开界面"
            return None
        try:
            r = _run_capture_split(HOST + ["--ui-payload"])
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
        return _run_capture(HOST + ["--pkg", str(pid)] + _split(args_text))

    def run_start(self, pid, args_text="", cwd=None):
        argv = HOST + ["--pkg", str(pid)] + _split(args_text)
        workdir = None
        if cwd:
            try:
                if Path(str(cwd)).is_dir():
                    workdir = str(cwd)
            except OSError:
                workdir = None
        run_env = dict(os.environ)
        run_env["MOSS_INTERACTIVE"] = "1"
        try:
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    stdin=subprocess.PIPE, env=run_env,
                                    text=True, encoding="utf-8", errors="replace",
                                    bufsize=1, creationflags=NO_WINDOW, cwd=workdir)
        except OSError as e:
            return {"ok": False, "msg": "启动失败：%s" % e}
        _remember_proc(pid, proc.pid)
        rid = uuid.uuid4().hex[:10]
        with RUNS_LOCK:
            RUNS[rid] = {"proc": proc, "lines": [], "code": None, "t0": time.time(),
                         "pid": proc.pid, "cmd": " ".join(argv[1:])}
            if len(RUNS) > RUNS_KEEP:
                for old in sorted(RUNS, key=lambda k: RUNS[k]["t0"])[:-RUNS_KEEP]:
                    if RUNS[old]["code"] is not None:
                        RUNS.pop(old, None)
        threading.Thread(target=_pump_output, args=(rid,), daemon=True).start()
        return {"ok": True, "run_id": rid, "pid": proc.pid}

    def cmd_start(self, cwd, line, pid=""):
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
            dec = "utf-8"
        else:
            argv = ["cmd.exe", "/d", "/s", "/c", text]
            dec = "auto"
        workdir = None
        if base:
            try:
                if Path(base).is_dir():
                    workdir = base
            except OSError:
                workdir = None
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
            if len(RUNS) > RUNS_KEEP:
                for old in sorted(RUNS, key=lambda k: RUNS[k]["t0"])[:-RUNS_KEEP]:
                    if RUNS[old]["code"] is not None:
                        RUNS.pop(old, None)
        threading.Thread(target=_pump_output, args=(rid,), daemon=True).start()
        return {"ok": True, "run_id": rid, "pid": proc.pid, "cmd": text}

    def run_input(self, run_id, text=""):
        with RUNS_LOCK:
            run = RUNS.get(str(run_id))
        if not run:
            return {"ok": False, "msg": "这次运行已经结束了（没有进程在等）"}
        proc = run.get("proc")
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
        with RUNS_LOCK:
            r = RUNS.get(run_id)
            if not r:
                return {"ok": False, "msg": "没有这次运行（可能已经被清掉了）"}
            code = r["code"]
            proc = r.get("proc")
        if code is None and proc is not None:
            pc = proc.poll()
            if pc is not None:
                code = pc
                with RUNS_LOCK:
                    if r.get("code") is None:
                        r["code"] = pc
        with RUNS_LOCK:
            return {"ok": True, "running": code is None, "code": code,
                    "out": "".join(r["lines"]),
                    "ms": int((time.time() - r["t0"]) * 1000), "pid": r["pid"]}

    def run_stop(self, run_id):
        with RUNS_LOCK:
            r = RUNS.get(run_id)
            if not r:
                return {"ok": False, "msg": "没有这次运行"}
            if r["code"] is not None:
                return {"ok": True, "msg": "它已经结束了"}
            pid = r["pid"]
        _kill_tree(pid)
        return {"ok": True, "msg": "已终止这次运行（它起的进程也一起停了）"}

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
        argv = HOST + ["--pkg", str(pid)] + _split(args_text)
        try:
            proc = subprocess.Popen(argv, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
                                    creationflags=NO_WINDOW | DETACHED, close_fds=True)
        except OSError as e:
            return {"ok": False, "msg": "启动失败：%s" % e}
        _remember_proc(pid, proc.pid)
        return {"ok": True, "msg": "已后台启动：" + " ".join(argv[1:])}

    def hist_list(self, n=30):
        rows = [r for r in _hist_read_all() if _hist_is_record(r)]
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
                "exists": bool(target) and Path(target).is_file(),
                "cwd_exists": bool(cwd) and Path(cwd).is_dir(),
                "key": _hist_key(r),
                "icon": icon_uri,
                "icon_svg": icon_svg,
            })
        return {"ok": True, "items": items}

    def hist_forget(self, key):
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
        return {"ok": True, "run_id": rid, "pid": proc.pid,
                "cmd": "moss " + " ".join(argv[len(HOST):]), "cwd": str(workdir)}

    def pkg_states(self, ids):
        want = [str(x) for x in (ids or [])]
        wins = [w for w in _top_windows() if w["class"] not in _HELPER_CLASSES]
        me = os.getpid()
        owner_pkg = {}
        for w in wins:
            pid = w["pid"]
            if pid == me or pid in owner_pkg:
                continue
            owner_pkg[pid] = _env_pkg_id(pid)
        allp = _pid_parents()
        cmdlines = _pids_by_cmdline()
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
        pids = _pkg_pids(pid)
        ws = [w for w in _top_windows()
              if w["pid"] in pids and w["class"] not in _HELPER_CLASSES]
        vis = [w for w in ws if w["visible"]]
        return {"ok": True, "running": bool(pids), "pids": len(pids),
                "windows": len(ws), "visible": len(vis) > 0,
                "titles": [w["title"] for w in ws][:5],
                "procs": _procs_info(pids)}

    def pkg_stop(self, pid):
        pids = _pkg_pids(pid)
        if not pids:
            return {"ok": False, "msg": "这个包现在没在跑"}
        for p in pids:
            _kill_tree(p)
        return {"ok": True, "msg": "已停掉这个包（%d 个进程，它起的子进程也一起停了）" % len(pids)}

    def pkg_hide(self, pid):
        ws = _pkg_windows(pid)
        if not ws:
            return {"ok": False, "msg": "没找到它的窗口 —— 先「运行」或「新窗口运行」一次"}
        vis = [w for w in ws if w["visible"]]
        if not vis:
            return {"ok": True, "msg": "它的窗口本来就是隐藏的"}
        done = [w["hwnd"] for w in vis if _show_window(w["hwnd"], False)]
        if done:
            _pkg_hidden[str(pid)] = done
        return {"ok": bool(done), "msg": "已隐藏 %d 个窗口（没关掉，还能再显示出来）" % len(done)}

    def pkg_show(self, pid):
        hs = [h for h in _pkg_hidden.get(str(pid), []) if _is_window(h)]
        if not hs:
            ws = _pkg_windows(pid)
            if not ws:
                return {"ok": False, "msg": "没找到它的窗口 —— 先「运行」或「新窗口运行」一次"}
            hs = [w["hwnd"] for w in ws]
        n = sum(1 for h in hs if _show_window(h, True))
        if n:
            _pkg_hidden.pop(str(pid), None)
        return {"ok": n > 0, "msg": "已显示 %d 个窗口" % n}

    def run_host(self, text):
        return _run_capture(HOST + _split(text))

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
        self._ai_dir()
        import ai_mode
        return ai_mode

    def _ai_runs(self):
        self._ai_dir()
        import ai_runs
        return ai_runs

    def _ai_ask(self):
        self._ai_dir()
        import ai_ask
        return ai_ask

    def _ai_wildcard(self):
        try:
            return bool(self._ai_mode().wildcard_write(str(AI.get("task_dir") or "")))
        except Exception:
            return False

    def ai_params(self, refresh=False):
        now = time.time()
        if not refresh and _AI_CFG["got"] and now - float(_AI_CFG["t0"]) < 15:
            return _AI_CFG["got"]
        out = {"ok": False, "source": "", "model": "", "base_url": "", "api_key": "",
               "models": [], "why": "",
               "profile": "", "providers": []}
        env_base = (os.environ.get("MOSS_AI_BASE_URL") or "").strip()
        env_model = (os.environ.get("MOSS_AI_MODEL") or "").strip()
        if env_base and env_model:
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
                profs = []
                for nm, one in (obj.get("summary") or {}).items():
                    if not isinstance(one, dict):
                        continue
                    ms = [str(x).strip() for x in (one.get("model") or []) if str(x).strip()]
                    profs.append({"name": nm, "models": ms,
                                  "has_key": bool(one.get("has_key")),
                                  "base_url": str(one.get("base_url") or "").rstrip("/")})
                _cur = str(obj.get("active") or obj.get("profile") or "")
                profs.sort(key=lambda x: (x["name"] != _cur, x["name"]))
                out["providers"] = profs
            else:
                out["why"] = "读不到 AI 配置 —— 去「设置 → AI」配一组（挑一家、把 key 填上）"
        _AI_CFG.update({"t0": now, "got": out})
        return out

    def ai_budget(self, save=None):
        try:
            ai_dir = str(HERE / "ai")
            if ai_dir not in sys.path:
                sys.path.insert(0, ai_dir)
            import ai_budget
            if save is None:
                cur = ai_budget.load()
                return dict(cur, ok=True, warn=ai_budget.warn_at(cur.get("max_tokens")))
            return ai_budget.save(save)
        except Exception as e:
            return {"ok": False, "msg": "预算读不出来：%s" % e}

    def ai_set_budget(self, max_tokens=200000):
        return self.ai_budget(save=max_tokens)

    def ai_info(self, workdir="", refresh=False):
        out = {"ok": True, "running": bool(AI.get("thread") and AI["thread"].is_alive()),
               "workdir": str(workdir or ""), "steps": 0}
        try:
            _c, e, _l = self._ai_mods()
            out["home"] = str(e.HOME)
            out["write_root"] = str(e.write_root())
            bud = self.ai_budget()
            out["max_tokens"] = bud.get("max_tokens")
            out["warn_tokens"] = bud.get("warn")
            try:
                M = self._ai_mode()
                out.update(M.summary(workdir))
            except Exception as exc:
                out["mode_why"] = "权限模块起不来：%s" % exc
            try:
                R = self._ai_runs()
                out["scope"] = {k: (str(v) if k == "dir" else v)
                                for k, v in R.scope_of(workdir).items()}
            except Exception:
                out["scope"] = {"kind": "all", "id": "", "dir": "", "label": "整个项目区"}
            p = self.ai_params(refresh=bool(refresh))
            try:
                import ai_budget as _b2
                _m = str(p.get("model") or "")
                out["context"] = _b2.context_window(_m, bud.get("context") or 0)
                out["compact_at"] = _b2.compact_at(_m, out["context"])
                out["retain_tokens"] = _b2.retain_tokens(_m, out["context"])
            except Exception:
                pass
            out["model"] = p.get("model") or ""
            _ms = [str(x).strip() for x in (p.get("models") or []) if str(x).strip()]
            if not _ms and out["model"]:
                _ms = [out["model"]]
            out["models"] = _ms
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
        except Exception as exc:
            out["ok"] = False
            out["msg"] = "AI 模块起不来：%s: %s" % (type(exc).__name__, exc)
        st = AI.get("state")
        if st:
            out["steps"] = len(st.get("steps") or [])
        return out

    def ai_start(self, task="", workdir="", max_tokens=None, continue_id="", model="", attachments=None):
        task = str(task or "").strip()
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
                _use_model = str(model or "").strip() or p["model"]
                client = c.Client(p["base_url"], p.get("api_key") or "", _use_model)
            except Exception as exc:
                return {"ok": False, "msg": "AI 起不来：%s" % exc}
            wd = str(workdir or "").strip() or str(e.write_root())
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
                except Exception as exc:
                    cont_note = "接不上上次那条（%s）—— 这次按新会话跑" % exc
            bud = self.ai_budget()
            cap = int(max_tokens or bud.get("max_tokens") or 200000)
            import ai_budget as _bud
            _model = str(getattr(client, "model", "") or "")
            _ctx = _bud.context_window(_model, bud.get("context") or 0)
            _at = _bud.compact_at(_model, _ctx)
            _retain = _bud.retain_tokens(_model, _ctx)
            M = self._ai_mode()
            R = self._ai_runs()
            run_id = R.new_id()
            scope = R.scope_of(wd)
            M.begin_run(wd)
            tmp_dir = M.ensure_tmp(run_id, wd)
            started = time.time()
            base = {
                "id": run_id, "task": task, "workdir": wd,
                "attachments": [{"name": a.get("name"), "kind": a.get("kind"),
                                 "size": a.get("size") or 0,
                                 "text": (str(a.get("text") or "")[:200000]
                                          if a.get("kind") == "text" else "")}
                                for a in atts],
                "model": str(getattr(client, "model", "") or ""),
                "max_tokens": cap, "started": started,
                "started_text": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
                "mode": "free" if M.wildcard_write(wd) else "limited",
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
                                 "usage": {}, "killed": [], "stopping": False,
                                 "partial": None}})

            def on_step(row):
                with AI_LOCK:
                    AI["state"]["steps"].append(row)

            def say(line):
                with AI_LOCK:
                    AI["state"]["say"].append(str(line)[:300])
                    if len(AI["state"]["say"]) > 400:
                        del AI["state"]["say"][:200]

            def phase(what):
                with AI_LOCK:
                    AI["state"]["phase"] = str(what)

            def on_snapshot(got):
                with AI_LOCK:
                    AI["state"]["snapshot"] = got

            def on_ask(q):
                with AI_LOCK:
                    AI["state"]["ask"] = q
                    if q is None:
                        _r = AI["state"].pop("ask_row", None)
                    else:
                        _r = None
                if q is None:
                    if _r:
                        try:
                            if not _r.get("done"):
                                _r.update({"done": True, "answer": "",
                                           "out": "（这问题没等到回答：超时或已停止）"})
                        except Exception:
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
                except Exception:
                    pass

            def on_journal(part, force=False):
                rec = dict(base)
                rec.update({"steps": part.get("steps") or [],
                            "usage": part.get("usage") or {},
                            "messages": part.get("messages") or [],
                            "files": part.get("files") or [],
                            "procs": part.get("procs") or [],
                            "killed": part.get("killed") or [],
                            "snapshot": part.get("snapshot"),
                            "snapshot_note": part.get("snapshot_note") or ""})
                if force:
                    rec["continue_note"] = cont_note
                R.save_live(rec, scope)
                with AI_LOCK:
                    AI["state"]["usage"] = dict(part.get("usage") or {})

            asker = self._ai_ask().Asker(publish=on_ask, stop_check=lambda: bool(AI.get("stop")))
            AI["asker"] = asker

            def mode_now():
                return "free" if M.wildcard_write(wd) else "limited"

            def perm_gate(path, why, need, timeout=1800):
                return self._ai_perm_wait(path, why, need, timeout=timeout, workdir=wd)

            def on_stream(n, text, think, chars=0, tchars=0):
                with AI_LOCK:
                    st = AI.get("state")
                    if not st:
                        return
                    if not text and not think:
                        st["partial"] = None
                    else:
                        st["partial"] = {"n": int(n or 0), "text": text, "think": think,
                                         "chars": int(chars or 0),
                                         "tchars": int(tchars or 0),
                                         "t": time.time()}

            def work():
                loop = l.Loop(client, workdir=wd, max_tokens=cap,
                              compact_at=_at, retain_tokens=_retain,
                              on_step=on_step, say=say, on_phase=phase,
                              on_snapshot=on_snapshot, on_stream=on_stream,
                              stop_check=lambda: bool(AI.get("stop")),
                              asker=asker, mode_fn=mode_now, on_journal=on_journal,
                              run_id=run_id, tmp_dir=str(tmp_dir or ""),
                              perm_gate=perm_gate)
                AI["loop"] = loop
                got = {}
                try:
                    if cont_note:
                        say(cont_note)
                    got = loop.run(task, history=hist, from_id=cont_from, attachments=atts)
                    got["continue_note"] = cont_note
                    got["asked_continue"] = cid
                except Exception as exc:
                    got = {"ok": False, "reason": "%s: %s" % (type(exc).__name__, exc),
                           "steps": [], "usage": {}, "files": []}
                finally:
                    try:
                        k = loop.cleanup("收尾")
                        got["procs_killed"] = got.get("procs_killed") or k.get("pids") or []
                    except Exception:
                        pass
                    AI["loop"] = None
                    with AI_LOCK:
                        AI["state"]["ask"] = None
                        AI["state"]["stopping"] = False
                    try:
                        asker.cancel("finished")
                    except Exception:
                        pass
                    try:
                        M.clear_temp()
                    except Exception:
                        pass
                try:
                    rec = dict(base)
                    rec.update({
                        "seconds": round(time.time() - started, 1),
                        "stopped": bool(AI.get("stop")),
                        "ok": bool(got.get("ok")), "reason": got.get("reason") or "",
                        "kind": got.get("kind") or "work",
                        "summary": got.get("summary") or "", "caveats": got.get("caveats") or "",
                        "usage": got.get("usage") or {}, "files": got.get("files") or [],
                        "snapshot": got.get("snapshot"), "steps": got.get("steps") or [],
                        "snapshot_note": got.get("snapshot_note") or "",
                        "folded": got.get("folded") or 0,
                        "messages": got.get("messages") or [],
                        "continued_from": got.get("continued_from") or "",
                        "asked_continue": got.get("asked_continue") or "",
                        "continue_note": got.get("continue_note") or "",
                        "procs_killed": got.get("procs_killed") or [],
                        "edited": got.get("edited") or 0,
                    })
                    saved = R.save(rec, scope)
                    got["run_id"] = saved.get("id") or run_id
                except Exception as exc:
                    got["run_id"] = run_id
                    got["save_error"] = "%s: %s" % (type(exc).__name__, exc)
                with AI_LOCK:
                    AI["state"]["result"] = got
                    AI["state"]["running"] = False

            th = threading.Thread(target=work, daemon=True)
            AI["thread"] = th
            th.start()
            return {"ok": True, "workdir": wd, "model": str(getattr(client, "model", "") or ""),
                    "run_id": run_id, "mode": mode_now(), "tmp": str(tmp_dir or ""),
                    "scope": scope.get("label") or ""}

    def ai_poll(self):
        with AI_LOCK:
            st = AI.get("state")
            if not st:
                return {"ok": True, "running": False, "idle": True, "steps": [], "say": []}
            asker = AI.get("asker")
            ask = st.get("ask")
            if asker is not None:
                try:
                    ask = asker.state()
                except Exception:
                    ask = None
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
                    "snapshot": st.get("snapshot") or None,
                    "max_tokens": int(AI.get("max_tokens") or 0),
                    "context": int(AI.get("context") or 0),
                    "compact_at": int(AI.get("compact_at") or 0),
                    "retain_tokens": int(AI.get("retain_tokens") or 0),
                    "prompt_tokens": int((st.get("steps") or [{}])[-1].get("ptok") or 0)
                                      if st.get("steps") else 0,
                    "usage": dict(st.get("usage") or {}),
                    "ask": ask,
                    "asker": bool(asker is not None and asker.busy()),
                    "perm": perm,
                    "mode": str(AI.get("mode") or ""),
                    "run_id": str(AI.get("run_id") or ""),
                    "tmp": str(AI.get("tmp") or ""),
                    "killed": list(st.get("killed") or []),
                    "stopping": bool(st.get("stopping")),
                    "partial": st.get("partial") or None,
                    "wildcard": self._ai_wildcard(),
                    "skills_rev": self._skills_rev(),
                    "seconds": round(time.time() - float(AI.get("t0") or time.time()), 1)}

    def ai_poll_light(self):
        with AI_LOCK:
            st = AI.get("state")
            if not st:
                return {"ok": True, "running": False, "partial": None}
            return {"ok": True, "running": bool(st.get("running")),
                    "partial": st.get("partial") or None}

    def ai_runs(self, limit=30, workdir=""):
        try:
            R = self._ai_runs()
            try:
                R.migrate_once()
            except Exception:
                pass
            scope = R.scope_of(workdir or self._ai_last_workdir())
            return {"ok": True, "runs": R.list_runs(limit=int(limit or 30), scope=scope),
                    "scope": {k: (str(v) if k == "dir" else v) for k, v in scope.items()}}
        except Exception as e:
            return {"ok": False, "runs": [], "msg": "读不到历史：%s" % e}

    def _ai_last_workdir(self):
        wd = str(AI.get("task_dir") or "")
        if wd:
            return wd
        sc = AI.get("scope") or {}
        try:
            if sc.get("kind") == "pkg" and sc.get("id"):
                return str(HERE.parent / "pkgs" / str(sc["id"]))
        except Exception:
            pass
        return ""

    def ai_mode_get(self, workdir=""):
        try:
            M = self._ai_mode()
            return M.summary(workdir or self._ai_last_workdir())
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_allow(self, path="", read=None, write=None, why="", action="add", force=False,
                 workdir=""):
        try:
            M = self._ai_mode()
            wd = str(workdir or self._ai_last_workdir())
            a = str(action or "add")
            if a == "deny":
                key = _perm_key(path)
                with AI_LOCK:
                    _PERM_DENY[key] = time.time()
                cur = M.find(path, wd)
                if cur is not None and cur.get("pending"):
                    M.allow_rm(path, wd)
                return {"ok": True, "msg": "已拒绝 —— 这次不放行，原来的权限不变",
                        "summary": M.summary(wd)}
            if a == "rm":
                got = M.allow_rm(path, wd)
            else:
                _pend = False if (read is not None or write is not None) else None
                got = M.allow_set(path, read=read, write=write, why=str(why or ""),
                                  by="user", add=True, pending=_pend, force=bool(force),
                                  workdir=wd)
            return dict(got, summary=M.summary(wd))
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_full_access(self, on=True, workdir=""):
        try:
            M = self._ai_mode()
            wd = str(workdir or self._ai_last_workdir())
            got = M.set_full_access(bool(on), wd)
            return dict(got, summary=M.summary(wd))
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_allow_pick(self, workdir=""):
        try:
            import webview as _wv
            win = webview.windows[0] if getattr(webview, "windows", None) else None
            if win is None or not hasattr(win, "create_file_dialog"):
                return {"ok": False, "msg": "这个环境没有目录选择框 —— 把路径粘到输入框里也一样"}
            _kind = getattr(getattr(_wv, "FileDialog", None), "FOLDER", None)
            if _kind is None:
                _kind = getattr(_wv, "FOLDER_DIALOG", 20)
            got = win.create_file_dialog(_kind, allow_multiple=False)
            if not got:
                return {"ok": False, "msg": "没选（取消了）", "cancel": True}
            p = got[0] if isinstance(got, (list, tuple)) else got
            M = self._ai_mode()
            wd = str(workdir or self._ai_last_workdir())
            r = M.allow_add(p, read=True, write=True, why="你选目录加的", by="user",
                            force=True, workdir=wd)
            return dict(r, summary=M.summary(wd))
        except Exception as e:
            return {"ok": False, "msg": "选不了目录：%s: %s" % (type(e).__name__, e)}

    def ai_tmp(self, action="info", run_id="", workdir=""):
        try:
            M = self._ai_mode()
            wd = str(workdir or self._ai_last_workdir())
            if action == "open":
                p = M.tmp_root(wd)
                p.mkdir(parents=True, exist_ok=True)
                os.startfile(str(p))
                return {"ok": True, "msg": "打开了 %s" % p, "tmp": M.tmp_size(wd)}
            if action == "clean":
                got = M.tmp_clean(str(run_id or ""), wd)
                return dict(got, tmp=M.tmp_size(wd))
            return {"ok": True, "tmp": M.tmp_size(wd)}
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def _ai_perm_wait(self, path, why="", need="write", timeout=1800, workdir=""):
        M = self._ai_mode()
        wd = str(workdir or self._ai_last_workdir())
        need_w = str(need or "write") != "read"
        problem = None
        try:
            problem = M.path_problem(path)
        except Exception:
            problem = None
        if problem:
            return {"granted": False, "reason": "bad-path", "msg": problem,
                    "read": False, "write": False, "seconds": 0.0}
        try:
            base = M.find(path, wd)
        except Exception:
            base = None
        base_read = bool((base or {}).get("read"))
        base_write = bool((base or {}).get("write"))
        try:
            M.allow_pending_add(path, why=why, need=need, workdir=wd)
        except Exception:
            pass
        t0 = time.time()
        key = _perm_key(path)
        _row = None
        try:
            _loop = AI.get("loop")
            if _loop is not None:
                _tail = Path(str(path)).name or str(path)
                _row = _loop.note(
                    "perm", "请求放行「%s」" % _tail, why=str(why or ""),
                    args={"path": str(path), "need": str(need or "write")},
                    out="（在等你点「允许 / 拒绝」…）")
        except Exception:
            _row = None
        with AI_LOCK:
            _PERM_DENY.pop(key, None)
            AI["perm"] = {"path": str(path), "why": str(why or ""),
                          "need": str(need or "write"), "at": t0, "workdir": wd}
        reason, it = "timeout", None
        while True:
            if AI.get("stop"):
                reason = "stopped"
                break
            with AI_LOCK:
                _denied_at = _PERM_DENY.get(key, 0.0)
            if _denied_at > t0:
                reason = "denied"
                break
            try:
                it = M.find(path, wd)
            except Exception:
                it = None
            if it is None:
                reason = "denied"
                break
            if it.get("write") or (not need_w and it.get("read")):
                reason = "ok"
                break
            if need_w and it.get("read") and not base_read:
                reason = "read-only"
                break
            if time.time() - t0 > float(timeout or 1800):
                reason = "timeout"
                break
            time.sleep(0.2)
        with AI_LOCK:
            AI["perm"] = None
            _PERM_DENY.pop(key, None)
        try:
            if reason != "denied":
                M.allow_set(path, pending=False, workdir=wd)
        except Exception:
            pass
        granted = reason == "ok" or (reason == "read-only" and not need_w)
        if _row is not None:
            try:
                _ans = {"ok": "允许", "read-only": "只给了读", "denied": "拒绝",
                        "stopped": "已停止", "timeout": "没回应"}.get(reason, reason)
                _row.update({"done": True, "answer": _ans,
                             "out": "你的选择：%s（读=%s 写=%s）" % (
                                 _ans, "开" if (it or {}).get("read") or base_read else "关",
                                 "开" if (it or {}).get("write") or base_write else "关")})
            except Exception:
                pass
        return {"granted": granted, "reason": reason,
                "read": bool((it or {}).get("read")) or base_read,
                "write": bool((it or {}).get("write")) or base_write,
                "seconds": round(time.time() - t0, 1)}

    def ai_answer(self, qid="", text="", choice="", by="user"):
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
            except Exception:
                pass
        return got

    def ai_session_messages(self, run_id=""):
        try:
            return self._ai_runs().messages(str(run_id or ""))
        except Exception as e:
            return {"ok": False, "messages": [], "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_run(self, run_id=""):
        try:
            rec = self._ai_runs().get(run_id)
            if rec:
                rec = dict(rec)
                msgs = rec.pop("messages", None) or []
                rec["cont"] = bool(msgs)
                rec["msgs"] = len(msgs)
            return {"ok": bool(rec), "run": rec, "msg": "" if rec else "没有这条记录"}
        except Exception as e:
            return {"ok": False, "run": None, "msg": "读不到：%s" % e}

    def ai_thread(self, run_id=""):
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
            chain.reverse()
            turns = []
            for r in chain:
                turns.append({
                    "id": r.get("id") or "",
                    "task": r.get("task") or "",
                    "at": r.get("started_text") or "",
                    "result": {"ok": bool(r.get("ok")), "reason": r.get("reason") or "",
                               "kind": r.get("kind") or "work",
                               "summary": r.get("summary") or "", "caveats": r.get("caveats") or "",
                               "files": r.get("files") or [], "usage": r.get("usage") or {},
                               "snapshot": r.get("snapshot"), "folded": r.get("folded") or 0,
                               "run_id": r.get("id") or "",
                               "continue_note": r.get("continue_note") or "",
                               "asked_continue": r.get("asked_continue") or ""},
                    "steps": r.get("steps") or [],
                    "attachments": r.get("attachments") or [],
                })
            return {"ok": True, "turns": turns,
                    "tail": (turns[-1]["id"] if turns else ""),
                    "cont": bool((chain[-1].get("messages") if chain else None) or [])}
        except Exception as e:
            return {"ok": False, "turns": [], "msg": "读不到这条会话：%s" % e}

    def _ai_chain(self, run_id):
        R = self._ai_runs()
        rec = R.get(run_id)
        if not rec:
            return []
        back, rid, guard = [], str(run_id), 0
        while rid and guard < 500:
            r = R.get(rid)
            if not r:
                break
            back.append(r)
            rid = str(r.get("continued_from") or "")
            guard += 1
        back.reverse()
        head = back[0].get("id")
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
        if not snap or not snap.get("id"):
            return False
        try:
            ai_dir = str(HERE / "ai")
            if ai_dir not in sys.path:
                sys.path.insert(0, ai_dir)
            import ai_snap as S
            man = S._store().manifest(snap["id"], snap.get("group"))
            return bool(man)
        except Exception:
            return False

    def ai_session_plan(self, run_id=""):
        try:
            R = self._ai_runs()
            chain = self._ai_chain(run_id)
            ids = [r.get("id") for r in chain]
            if str(run_id) not in ids:
                return {"ok": False, "msg": "找不到这条会话"}
            i = ids.index(str(run_id))
            cut = chain[i:]
            rec = chain[i]
            snap = rec.get("snapshot") or None
            snap_ok = self._ai_snap_exists(snap)
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
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_session_truncate(self, run_id="", confirm=False):
        plan = self.ai_session_plan(run_id)
        if not plan.get("ok"):
            return plan
        if not confirm:
            return {"ok": False, "need_confirm": True, "plan": plan,
                    "msg": "这一步会删记录、并把代码回退到那一刻 —— 请先确认"}
        try:
            R = self._ai_runs()
            import ai_snap as S
            target = plan.get("target")
            restored = ""
            if target:
                r = self.backup_restore(target["id"], None, "all", False, target.get("group") or "")
                if not r or not r.get("ok"):
                    return {"ok": False, "msg": "回退失败，**什么都没删**：%s"
                                                % ((r or {}).get("msg") or "")}
                restored = target["id"]
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
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def _skill_lib(self):
        sk = str(HERE.parent / "ai")
        if sk not in sys.path:
            sys.path.insert(0, sk)
        import skill_lib
        return skill_lib

    def ai_skills(self):
        try:
            return self._skill_lib().summary()
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e),
                    "skills": [], "from_pkgs": [], "broken": [], "dirs": {}}

    def _skills_rev(self):
        try:
            return self._skill_lib().rev()
        except Exception:
            return ""

    def ai_skill_allow(self, sid="", yes=True):
        try:
            return self._skill_lib().allow(sid, bool(yes))
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_skill_read(self, sid=""):
        try:
            return self._skill_lib().read(sid)
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_skill_rm(self, sid="", confirm=False):
        try:
            return self._skill_lib().rm(sid, bool(confirm))
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_skill_promote(self, sid="", confirm=False, new_id=""):
        try:
            sk = self._skill_lib()
            avoid = ()
            try:
                ai_dir = str(HERE / "ai")
                if ai_dir not in sys.path:
                    sys.path.insert(0, ai_dir)
                import ai_tools
                avoid = ai_tools.builtin_names()
            except Exception:
                pass
            return sk.promote(sid, bool(confirm), new_id, builtin=avoid)
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_skill_plan(self, sid="", new_id=""):
        try:
            return self._skill_lib().promote_plan(sid, new_id)
        except Exception as e:
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

    def ai_run_forget(self, run_id="", all_of_them=False, workdir=""):
        try:
            R = self._ai_runs()
            scope = R.scope_of(workdir or self._ai_last_workdir())
            return R.clear(scope) if all_of_them else R.delete(run_id)
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def ai_stop(self):
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
            except Exception:
                pass
        with AI_LOCK:
            asker = AI.get("asker")
        if asker is not None:
            try:
                asker.cancel("stopped")
                with AI_LOCK:
                    if AI.get("state"):
                        AI["state"]["ask"] = None
            except Exception:
                pass
        th = AI.get("thread")
        done = False
        if th is not None:
            try:
                th.join(1.5)
                done = not th.is_alive()
            except Exception:
                pass
        if killed:
            return {"ok": True, "killed": killed, "ms": ms, "done": done,
                    "msg": "已停止（它起的 %d 个进程也一起停了）" % len(killed)}
        return {"ok": True, "killed": [], "done": done,
                "msg": "已停止" if done else "已请求停止 —— 它正在收尾"}

    def open_path(self, path):
        try:
            os.startfile(str(path))
            return {"ok": True, "msg": "已打开：" + str(path)}
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}

    def open_url(self, url):
        import webbrowser
        u = str(url or "").strip()
        if not u.lower().startswith(("http://", "https://")):
            return {"ok": False, "msg": "只能打开 http/https 链接"}
        try:
            ok = bool(webbrowser.open(u))
        except Exception as e:
            return {"ok": False, "msg": str(e)}
        if not ok:
            return {"ok": False, "msg": "系统没接住这个链接"}
        return {"ok": True, "msg": "已在浏览器里打开"}

    def fs_roots(self):
        return {"roots": [{"key": r["key"], "label": r["label"],
                           "path": str(r["path"]), "writable": r["writable"],
                           "why": r["why"],
                           "exists": Path(r["path"]).is_dir()} for r in ROOTS]}

    def fs_list(self, rel):
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

    def fs_search(self, q, opts=None):
        raw_q = str(q or "")
        if not raw_q.strip():
            return {"ok": False, "msg": "先输入要搜的内容"}
        if isinstance(opts, str):
            try:
                opts = json.loads(opts)
            except ValueError:
                opts = {}
        opts = opts if isinstance(opts, dict) else {}
        cs = bool(opts.get("cs"))
        use_re = bool(opts.get("re"))
        word = bool(opts.get("word"))
        deep = bool(opts.get("skip"))
        if use_re:
            try:
                rx = re.compile(raw_q, 0 if cs else re.IGNORECASE)
            except re.error as e:
                return {"ok": False, "msg": "正则写得不对：%s" % e}
        else:
            body = re.escape(raw_q)
            if word:
                body = r"(?<!\w)" + body + r"(?!\w)"
            rx = re.compile(body, 0 if cs else re.IGNORECASE)

        roots = []
        for r in (opts.get("roots") or []):
            r = str(r or "").replace("\\", "/").strip("/")
            if r:
                roots.append(r)
        if not roots:
            roots = ["user", "system"]

        user_base = Path(USER_DATA).resolve()
        t0 = time.perf_counter()
        files, n_hits, scanned, skipped = [], 0, 0, 0
        truncated, dead, cut = False, [], []
        roots = roots[:8]
        for i, rel in enumerate(roots):
            try:
                _root, base = _resolve(rel)
            except ValueError as e:
                dead.append("%s：%s" % (rel, e))
                continue
            if not base.is_dir():
                dead.append("%s：没有这个目录" % rel)
                continue
            left = len(roots) - i
            root_cap = n_hits + max(40, (SEARCH_MAX_HITS - n_hits) // left)
            stopped = False
            queue = [str(base)]
            while queue and not stopped:
                dirpath = queue.pop(0)
                here = Path(dirpath)
                try:
                    with os.scandir(dirpath) as it:
                        entries = sorted(it, key=lambda e: e.name)
                except OSError:
                    continue
                subs = []
                for ent in entries:
                    if stopped:
                        break
                    try:
                        if ent.is_dir(follow_symlinks=False):
                            subs.append(ent.name)
                            continue
                    except OSError:
                        continue
                    fn = ent.name
                    if scanned >= SEARCH_MAX_FILES:
                        stopped = True
                        break
                    if fn.endswith(".moss-tmp"):
                        continue
                    fp = here / fn
                    if fp.suffix.lower().lstrip(".") in SEARCH_BIN_EXT:
                        skipped += 1
                        continue
                    try:
                        size = fp.stat().st_size
                    except OSError:
                        skipped += 1
                        continue
                    if not size or size > SEARCH_MAX_BYTES:
                        skipped += 1
                        continue
                    scanned += 1
                    try:
                        raw = fp.read_bytes()
                    except OSError:
                        skipped += 1
                        continue
                    text, _enc, _bom = _decode_text(raw)
                    if text is None:
                        skipped += 1
                        continue
                    hits, more = [], False
                    for no, line in enumerate(text.splitlines(), 1):
                        ms = list(rx.finditer(line))
                        if ms:
                            hits.append(_search_hit(no, line, ms))
                            if len(hits) >= SEARCH_MAX_PER_FILE:
                                more = True
                                break
                    if not hits:
                        continue
                    room = root_cap - n_hits
                    if len(hits) > room:
                        hits = hits[:room]
                        more = True
                    if not hits:
                        continue
                    files.append({"rel": _rel_page(fp), "name": fn, "dir": _rel_page(here),
                                  "ext": fp.suffix.lower().lstrip("."), "n": len(hits),
                                  "more": more, "hits": hits})
                    n_hits += len(hits)
                    if n_hits >= root_cap:
                        stopped = True
                        break
                for d in sorted(subs):
                    if _search_skip_dir(here, d):
                        continue
                    if not deep and here == user_base and d in SEARCH_SKIP_TOP:
                        continue
                    queue.append(str(here / d))
            if stopped:
                truncated = True
                cut.append(rel)
        ms = int((time.perf_counter() - t0) * 1000)
        out = {"ok": True, "q": raw_q, "files": files,
               "n_files": len(files), "n_hits": n_hits,
               "scanned": scanned, "skipped": skipped,
               "truncated": truncated, "cut": cut, "ms": ms, "roots": roots, "note": ""}
        if dead:
            out["note"] = "；".join(dead[:2])
        return out

    def fs_read(self, rel):
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
        note = "" if enc == "utf-8" and not bom_hex else \
            "%s%s" % (enc.upper(), "（带 BOM）" if bom_hex else "")
        return {"ok": True, "binary": False, "too_big": False, "size": size,
                "text": text, "rel": _rel_page(p), "path": str(p),
                "writable": root["writable"], "encoding": enc, "bom": bom_hex,
                "encoding_note": note,
                "mtime": int(p.stat().st_mtime)}

    def fs_preview_url(self, rel):
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
            with open(tmp, "wb") as f:
                f.write(head + text.encode(enc))
            os.replace(tmp, p)
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
        if p.parent == p:
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
                if p.parent == p:
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
        out = {}
        for rel in (rels or []):
            try:
                _root, p = _resolve(rel)
                out[str(rel)] = p.exists()
            except ValueError:
                out[str(rel)] = False
        return {"ok": True, "has": out}

    def fs_open_default(self, rel):
        try:
            _root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not p.exists():
            return {"ok": False, "msg": "没有这个东西：%s" % rel}
        try:
            os.startfile(str(p))
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}
        return {"ok": True, "msg": "已用默认程序打开 %s" % p.name}

    def fs_reveal(self, rel):
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
        drop_log("page: " + str(text or ""))
        return {"ok": True}

    def _backup_store(self):
        import backup as _bk
        return _bk.BackupStore(USER_DATA / _bk.STORE_DIRNAME, _rel_page,
                               lambda rel: _resolve(rel)[1],
                               trash=lambda p: _trash(Path(p)),
                               log=drop_log)

    def backup_list(self, group=""):
        try:
            st = self._backup_store()
            g = str(group or "") or None
            return {"ok": True, "items": st.list_backups(g), "stat": st.stat(g),
                    "groups": st.groups_summary()}
        except Exception as e:
            return {"ok": False, "msg": "备份库读不出来：%s" % e, "items": [],
                    "stat": {}, "groups": []}

    def backup_group_hint(self, rels):
        try:
            import backup as _bk
            rels = [str(r) for r in (rels or [])]
            return {"ok": True, "group": _bk.group_for_sources(rels)}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_group_info(self, group):
        try:
            st = self._backup_store()
            info = st.stat(group)
            items = st.list_backups(group)
            return {"ok": True, "group": str(group or ""), "backups": info.get("backups", 0),
                    "bytes": info.get("all_bytes", 0), "store_bytes": info.get("store_bytes", 0),
                    "last": (items[0].get("created_text") if items else "")}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_rename_group(self, old, new):
        try:
            return self._backup_store().rename_group(old, new)
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_drop_group(self, group):
        try:
            return self._backup_store().drop_group(group)
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_create(self, rels, title="", note="", group="", excludes=None,
                      by="", by_task=""):
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
        except Exception as e:
            return {"ok": False, "msg": "备份失败：%s" % e}

    def backup_manifest(self, bid, group=""):
        try:
            st = self._backup_store()
            m = st.manifest(bid, (str(group or "") or None))
            m = dict(m)
            m["ok"] = True
            return m
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_ignore_save(self, text, group=""):
        try:
            import backup as _b
            st = self._backup_store()
            g = str(group or "")
            f = st.group_ignore_file(g) if g else st.ignore_file
            f.parent.mkdir(parents=True, exist_ok=True)
            if f.is_file():
                try:
                    (f.with_suffix(f.suffix + ".bak")).write_text(
                        f.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
                except Exception:
                    pass
            f.write_text(str(text or ""), encoding="utf-8")
            return {"ok": True, "path": str(f), "group": g,
                    "count": len(_b.parse_ignore(text))}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_preview(self, rels):
        try:
            import backup as _b
            st = self._backup_store()
            inc, exc = [], []
            for rel in (rels or []):
                try:
                    base = _resolve(str(rel))[1]
                except Exception:
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
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_presets(self, rels):
        try:
            st = self._backup_store()
            srcs = []
            for rel in (rels or []):
                try:
                    srcs.append(str(_resolve(str(rel))[1]))
                except Exception:
                    pass
            return {"ok": True, "presets": st.presets(srcs)}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_group_ignore(self, group):
        try:
            import backup as _b
            st = self._backup_store()
            g = str(group or "")
            f = st.group_ignore_file(g) if g else None
            rules = st.group_ignore(g) if g else []
            last = []
            try:
                ids = st.ids(g) if g else []
                if ids:
                    m = st.manifest(ids[0], g)
                    drop = (set(_b.DEFAULT_EXCLUDES) | set(_b.PATH_EXCLUDES) | set(rules)
                            | set(_b.parse_ignore(st._read_ignore())))
                    last = [x for x in list(m.get("exclude") or []) if x not in drop]
            except Exception:
                last = []
            return {"ok": True, "group": g, "path": (str(f) if f else ""),
                    "rules": rules, "last": last}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_ignore(self):
        try:
            import backup as _b
            st = self._backup_store()
            f = st.ignore_file
            user = []
            if f.is_file():
                try:
                    user = _b.parse_ignore(f.read_text(encoding="utf-8", errors="replace"))
                except Exception:
                    user = []
            return {"ok": True, "path": str(f), "exists": f.is_file(),
                    "user": user, "count": len(user),
                    "builtin": list(_b.DEFAULT_EXCLUDES) + ["/" + p for p in _b.PATH_EXCLUDES],
                    "name": _b.IGNORE_NAME}
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_fp(self, rels, dirs=None):
        fps, sizes, dsz = {}, {}, {}
        try:
            st = self._backup_store()
        except Exception as e:
            return {"ok": False, "msg": str(e), "fps": {}, "sizes": {}, "dirs": {}}
        for rel in (rels or []):
            try:
                p = _resolve(str(rel))[1]
                if p.is_file():
                    sizes[str(rel)] = p.stat().st_size
                    fps[str(rel)] = _bk.hash_file(p)[0]
            except Exception:
                pass
        for rel in (dirs or []):
            rel = str(rel)
            try:
                base = _resolve(rel)[1]
            except Exception:
                continue
            if not base.is_dir():
                continue
            store = str(st.root.resolve())
            total = 0
            for cur, subs, names in os.walk(base):
                cp = Path(cur)
                subs[:] = [d for d in subs
                           if not st._skip_dir_name(d)
                           and not str((cp / d).resolve()).startswith(store)]
                for n in names:
                    if st._skip_dir_name(n):
                        continue
                    try:
                        f = cp / n
                        if f.is_symlink():
                            continue
                        if st._skip_rel(st.rel_of(f) or ""):
                            continue
                        total += f.stat().st_size
                    except Exception:
                        pass
            dsz[rel] = total
        return {"ok": True, "fps": fps, "sizes": sizes, "dirs": dsz}

    def backup_blob(self, fp, group=""):
        try:
            st = self._backup_store()
            return st.read_blob(fp, group=(str(group or "") or None))
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_plan(self, bid, rels=None, only="all", sync=False, group=""):
        try:
            st = self._backup_store()
            return st.plan(bid, rels=rels, only=only, sync=bool(sync),
                           group=(str(group or "") or None))
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_restore(self, bid, rels=None, only="all", sync=False, group=""):
        try:
            st = self._backup_store()
            r = st.restore(bid, rels=rels, only=only, sync=bool(sync),
                           group=(str(group or "") or None))
            c = r.get("counts") or {}
            r["msg"] = "恢复 %s 个、跳过 %s 个、挪走 %s 个、出错 %s 个" % (
                c.get("restored", 0), c.get("skipped", 0), c.get("trashed", 0),
                c.get("errors", 0))
            return r
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def _export_target(self, target, subpath=""):
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
        try:
            st = self._backup_store()
            base, sub = self._export_target(target, subpath)
            return st.export_plan(bid, base, subpath=sub, rels=rels,
                                  group=(str(group or "") or None))
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_export(self, bid, target, subpath="", rels=None, keep_bak=False, group=""):
        try:
            st = self._backup_store()
            base, sub = self._export_target(target, subpath)
            r = st.export(bid, base, subpath=sub, rels=rels, keep_bak=bool(keep_bak),
                          group=(str(group or "") or None))
            c = r.get("counts") or {}
            r["msg"] = "导出 %s 个到 %s%s" % (c.get("written", 0), r.get("root"),
                                            ("（%s 个出错）" % c["errors"]) if c.get("errors") else "")
            return r
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def pick_dir(self, start=""):
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
                kind = _wv.FOLDER_DIALOG()
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
        except Exception as e:
            return {"ok": False, "msg": "挑文件夹失败：%s" % e}

    def pick_file(self, start=""):
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
        except Exception as e:
            return {"ok": False, "msg": "挑文件失败：%s" % e}

    def backup_rm_ai(self, group=""):
        try:
            ai_dir = str(HERE / "ai")
            if ai_dir not in sys.path:
                sys.path.insert(0, ai_dir)
            import ai_snap
            return ai_snap.clean_ai(group=group)
        except Exception as e:
            return {"ok": False, "deleted": [], "skipped": [], "msg": "清不掉：%s" % e}

    def backup_delete(self, bid, group=""):
        try:
            st = self._backup_store()
            r = st.delete(bid, group=(str(group or "") or None))
            r["msg"] = "删掉了，顺手回收了 %s 个没人引用的对象（%s）" % (
                r.get("removed", 0), _human(r.get("freed", 0)))
            return r
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_gc(self, dry_run=False, group=""):
        try:
            st = self._backup_store()
            r = st.gc(dry_run=dry_run, group=(str(group or "") or None))
            r["msg"] = ("能回收 %s 个对象（%s）" if dry_run else "回收了 %s 个对象（%s）") % (
                r.get("removed", 0), _human(r.get("freed", 0)))
            return r
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def backup_check(self, bid=None, group=""):
        try:
            return self._backup_store().check(bid, group=(str(group or "") or None))
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def ui_float(self, pid):
        pid = str(pid)
        with _FLOAT_LOCK:
            cur = _FLOAT.get(pid)
        if cur is not None:
            if _float_ready(cur):
                try:
                    cur.show()
                    cur.restore()
                except Exception:
                    pass
                return {"ok": True, "msg": "这个包的窗口已经开着了"}
            # 那个窗口还在、但页面从来没加载成功（空白窗）⇒ 扔掉重开，别把白板又抬出来
            _close_float_quiet(pid)
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
        except Exception:
            x = y = None
        try:
            w = webview.create_window(title, _PAGE_URL + "#float=" + pid, js_api=_API,
                                      width=960, height=720, x=x, y=y,
                                      min_size=(520, 380), text_select=True)
        except Exception as e:
            return {"ok": False, "msg": "开窗口失败：%s" % e}
        if w is None:
            return {"ok": False, "msg": "开窗口失败（pywebview 没给窗口）"}
        with _FLOAT_LOCK:
            _FLOAT[pid] = w
        _wire_float(pid, w, title)
        _watch_float(pid, w)
        _note("float: :%s 弹出为窗口「%s」" % (pid, title))
        return {"ok": True, "msg": "已弹出为窗口（点最小化就收回）"}

    def ui_dock(self, pid):
        pid = str(pid)
        if _float_win(pid) is None:
            return {"ok": True, "msg": "本来就没弹出"}
        _dock_float(pid, "点了收回")
        return {"ok": True}

    def ui_float_stop(self, pid):
        pid = str(pid)
        _close_float_quiet(pid)
        r = self.embed_stop(pid)
        _js(window, "window.__mossFloatClosed && window.__mossFloatClosed(%s)" % json.dumps(pid))
        return {"ok": True, "msg": (r or {}).get("msg") or "已停掉"}

    def set_win_icon(self, pid, png_b64):
        pid = str(pid)
        w = _float_win(pid)
        if w is None:
            return {"ok": False, "msg": "这个包的浮动窗口已经没了"}
        try:
            import base64 as _b64
            png = _b64.b64decode(str(png_b64 or ""))
        except Exception as e:
            return {"ok": False, "msg": "图标数据坏了：%s" % e}
        if len(png) < 64:
            return {"ok": False, "msg": "图标数据太小了"}
        _ICON_DIR.mkdir(parents=True, exist_ok=True)
        ico = _ICON_DIR / (pid + ".ico")
        try:
            _png_to_ico(png, ico)
        except Exception as e:
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
        except ValueError:
            return {"ok": False, "msg": "界面文件不在安装根里面"}
        if rel.startswith("../"):
            return {"ok": False, "msg": "界面文件不在安装根里面"}
        return {"ok": True,
                "url": "http://127.0.0.1:%d/%s/%s" % (port, token, rel),
                "port": port}

    def embed_start(self, pid, cwd="", args_text=""):
        pid = str(pid)
        with EMBED_LOCK:
            cur = EMBED.get(pid)
            if cur and cur["proc"].poll() is None:
                return {"ok": True, "pid": cur["proc"].pid, "reused": True}
        env = dict(os.environ)
        env["MOSS_UI_EMBED"] = "1"
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
        pid = str(pid)
        _close_float_quiet(pid)
        with EMBED_LOCK:
            rec = EMBED.get(pid)
        if not rec:
            return {"ok": False, "msg": "这个包没在内嵌运行"}
        proc = rec["proc"]
        with EMBED_LOCK:
            EMBED_STOPPED.add(proc)
        _kill_tree(proc.pid)
        try:
            proc.kill()
        except Exception:
            pass
        with EMBED_LOCK:
            EMBED.pop(pid, None)
        return {"ok": True, "msg": "已停掉这个包的内嵌进程"}

    def embed_state(self, pid):
        pid = str(pid)
        with EMBED_LOCK:
            rec = EMBED.get(pid)
        alive = bool(rec and rec["proc"].poll() is None)
        return {"ok": True, "running": alive, "pid": (rec["proc"].pid if rec else 0),
                "lines": len(rec["lines"]) if rec else 0}

    def embed_take(self, pid):
        pid = str(pid)
        with EMBED_LOCK:
            rec = EMBED.get(pid)
            if not rec:
                return {"ok": True, "text": ""}
            text = "".join(rec["lines"])
            rec["lines"] = []
        return {"ok": True, "text": text}

    def settings(self):
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        r = _run_capture_split(HOST + ["--settings"])
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict) or not data.get("groups"):
            tail = ((r.get("err") or "").strip().splitlines() or [""])[-1]
            return {"ok": False, "msg": "读设置失败：退出码 %s%s"
                                        % (r.get("code"), (" —— " + tail) if tail else "")}
        extra = [l for l in (r.get("out") or "").splitlines()
                 if l.strip() and not l.strip().startswith("{")]
        try:
            _SETTINGS_CUR.clear()
            for g in (data.get("groups") or []):
                for it in (g.get("items") or []):
                    _SETTINGS_CUR[it["key"]] = it.get("value")
        except Exception:
            pass
        return {"ok": True, "path": str(data.get("path") or ""),
                "groups": data.get("groups") or [],
                "msg": " ".join(x.strip() for x in extra)[:400]}

    def settings_save(self, pairs):
        return self._settings_call("--settings-set", pairs, with_notes=False)

    def settings_check(self, values):
        try:
            r = _settings_rules()
            if r is not None:
                cur = _settings_current()
                got = r.check(values, cur)
                return {"ok": bool(got["ok"]), "problems": got["problems"],
                        "notes": got["notes"], "live": got["live"], "msg": ""}
        except Exception as e:
            _note("settings: 界面内校验失败（%r），退回叫宿主" % (e,))
        return self._settings_call("--settings-check", values, with_notes=True)

    def _settings_call(self, flag, payload, with_notes):
        empty = {"ok": False, "problems": [], "notes": {}, "live": "", "msg": ""}
        if not HOST:
            empty["msg"] = "没拿到宿主命令 —— 请从 moss 主程序打开界面"
            return empty
        if not isinstance(payload, dict) or (not payload and not with_notes):
            return {"ok": True, "problems": [], "notes": {}, "live": "",
                    "msg": "没改什么" if not with_notes else ""}
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
                "shortcut": data.get("shortcut") or [], "msg": ""}

    def cd_state(self):
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
        return self._cd_run("--install")

    def cd_uninstall(self):
        return self._cd_run("--uninstall")

    def _cd_run(self, flag):
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令"}
        r = _run_capture_split(HOST + ["cd", flag])
        ok = (r.get("code") == 0)
        text = ((r.get("out") or "") + (r.get("err") or "")).strip()
        last = (text.splitlines() or [""])[-1].strip() if text else ""
        return {"ok": ok, "msg": last or ("完成" if ok else "没成功")}

    def list_state(self):
        f = USER_DATA / "state" / "_ui_order.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        ids = data.get("ids")
        return {"ok": True, "ids": ids if isinstance(ids, list) else [],
                "sort": data.get("sort") if isinstance(data.get("sort"), str) else ""}

    def list_state_set(self, ids, sort):
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
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def ai_config(self, name="", reveal=False):
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        flag = "--ai-config-reveal" if reveal else "--ai-config"
        argv = HOST + [flag] + (["--profile=" + str(name)] if str(name or "").strip() else [])
        r = _run_capture_split(argv)
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict) or not data.get("ok"):
            tail = ((r.get("err") or "").strip().splitlines() or [""])[-1] \
                or ((r.get("out") or "").strip().splitlines() or [""])[-1]
            return {"ok": False, "msg": "读 AI 参数失败：退出码 %s%s"
                                        % (r.get("code"), (" —— " + tail) if tail else "")}
        return {"ok": True, "active": data.get("active") or "",
                "name": data.get("profile") or "", "params": data.get("params") or {},
                "profiles": data.get("profiles") or [],
                "summary": data.get("summary") or {}}

    def ai_presets(self):
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
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        name = str(name or "").strip()
        if not name:
            return {"ok": False, "msg": "没说到底删哪一组"}
        r = _run_capture(HOST + ["--ai-profile-del", name])
        return {"ok": r.get("code") == 0, "msg": (r.get("out") or "").strip()}

    def ai_rename(self, old, new):
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
        if not HOST:
            return {"ok": False, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        name = str(name or "").strip()
        if not name:
            return {"ok": False, "msg": "没说到底切哪一组"}
        r = _run_capture(HOST + ["--ai-active", name])
        return {"ok": r.get("code") == 0, "msg": (r.get("out") or "").strip()}

    def new_pkg(self, pid="", name="", desc="", kind=""):
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
        s = str(raw or "").strip().lower()
        s = re.sub(r"[^a-z0-9_-]+", "-", s).strip("-_")
        s = re.sub(r"^[^a-z]+", "", s)
        s = s[:24].strip("-_")
        return s or fallback

    def _pkg_ids_taken(self):
        taken = set()
        for p in (DATA.get("packages") or []):
            try:
                taken.add(str(p.get("id") or "").strip().lower())
                _als = p.get("aliases") or []
                if isinstance(_als, str):
                    _als = [_als]
                for a in _als:
                    taken.add(str(a or "").strip().lower())
            except Exception:
                pass
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
                        except Exception:
                            pass
            except OSError:
                pass
        taken.discard("")
        return taken

    def ai_suggest_pkg(self, idea=""):
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
        except Exception as exc:
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
        except Exception as exc:
            return {"ok": False, "msg": "AI 没答上来：%s" % exc}
        blob, data = raw, {}
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            blob = m.group(0)
        try:
            data = json.loads(blob)
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        nm = str(data.get("name") or "").strip()[:24]
        ds = str(data.get("desc") or "").strip()[:80]
        tk = str(data.get("task") or "").strip()
        pid = self._pkg_id(data.get("id") or nm, fallback="new-pkg")
        taken = self._pkg_ids_taken()
        base = pid
        for n in range(2, 1000):
            if pid not in taken:
                break
            suffix = "-%d" % n
            pid = (base[:32 - len(suffix)].rstrip("-_") + suffix).strip("-_")
        if pid in taken:
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
                "raw": "" if data else raw[:400]}

    def ai_test(self, name="", fields=None):
        if not HOST:
            return {"ok": False, "code": -1, "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        argv = HOST + ["--ai-test"] + ([str(name)] if str(name or "").strip() else [])
        for k in sorted(fields or {}):
            v = (fields or {})[k]
            if v not in (None, ""):
                argv.append("%s=%s" % (k, _ai_arg(v)))
        r = _run_capture(argv)
        return {"ok": r.get("code") == 0, "code": r.get("code"),
                "msg": (r.get("out") or "").strip() or "（宿主没说什么）"}

    def ai_ping(self, name="", model="", fields=None):
        if not HOST:
            return {"ok": False, "model": model, "ms": 0,
                    "msg": "没拿到宿主命令 —— 请从 moss 主程序打开界面"}
        argv = HOST + ["--ai-ping"] + ([str(name).strip()] if str(name or "").strip() else [])
        argv.append("model=" + _ai_arg(model))
        for k in sorted(fields or {}):
            v = (fields or {})[k]
            if v not in (None, ""):
                argv.append("%s=%s" % (k, _ai_arg(v)))
        r = _run_capture_split(argv)
        data = _json_from_host(r.get("out"))
        if not isinstance(data, dict):
            tail = (((r.get("err") or "").strip().splitlines() or [""])[-1]
                    or ((r.get("out") or "").strip().splitlines() or [""])[-1])
            return {"ok": False, "model": model, "ms": 0,
                    "msg": ("测试失败：退出码 %s%s"
                            % (r.get("code"), (" —— " + tail) if tail else ""))}
        return data

    def ai_models(self, name="", fields=None):
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

    def sound_state(self):
        return {"ok": True, "dir": str(USER_DATA / "sound"),
                "exts": [x.lstrip(".") for x in SOUND_EXTS],
                "items": {k: _snd_info(k) for k in SOUND_KINDS}}

    def sound_set(self, kind="finish", on=True):
        k = _snd_kind(kind)
        r = self._settings_call("--settings-set", {"sound.%s_on" % k: bool(on)},
                                with_notes=False)
        return self._sound_done(r, "没改成")

    def sound_play(self, kind="finish", preview=False):
        k = _snd_kind(kind)
        if not preview and not _snd_on(k):
            return {"ok": True, "played": False, "why": "关着"}
        p = _snd_path(k)
        if p is None:
            return {"ok": False, "played": False, "msg": "还没有可用的音频文件"}
        ok = _snd_start(p)
        return {"ok": ok, "played": ok, "name": p.name}

    def sound_pick(self, kind="finish"):
        k = _snd_kind(kind)
        try:
            import webview as _wv
            wins = list(getattr(_wv, "windows", None) or [])
            if not wins:
                return {"ok": False, "msg": "窗口还没准备好，稍一下再试"}
            win = wins[0]
            if not hasattr(win, "create_file_dialog"):
                return {"ok": False, "msg": "这个环境没有文件选择框"}
            fd = getattr(_wv, "FileDialog", None)
            dlg = getattr(fd, "OPEN", None) if fd is not None else None
            if callable(dlg):
                dlg = dlg()
            if dlg is None:
                dlg = getattr(_wv, "OPEN_DIALOG", None)
                if callable(dlg):
                    dlg = dlg()
            if not dlg:
                return {"ok": False, "msg": "这个 pywebview 版本不支持挑文件"}
            types = ("音频 (*.mp3;*.wav;*.m4a;*.aac;*.wma;*.ogg;*.flac)",
                     "所有文件 (*.*)")
            try:
                res = win.create_file_dialog(dlg, allow_multiple=False, file_types=types)
            except TypeError:
                res = win.create_file_dialog(dlg)
            if not res:
                return {"ok": False, "cancelled": True, "msg": "没选（取消了）"}
            p = res if isinstance(res, str) else (res[0] if isinstance(res, (list, tuple)) else "")
            p = str(p or "").strip()
            if not p:
                return {"ok": False, "msg": "没拿到路径"}
            return self.sound_use(k, p)
        except Exception as e:
            return {"ok": False, "msg": "挑文件失败：%s" % e}

    def sound_use(self, kind="finish", path=""):
        k = _snd_kind(kind)
        src = Path(str(path or "").strip())
        if not src.is_file():
            return {"ok": False, "msg": "找不到这个文件：%s" % src}
        ext = src.suffix.lower()
        if ext not in SOUND_EXTS:
            return {"ok": False,
                    "msg": "只认 %s 这几种音频（这个是 %s）"
                           % (" / ".join(x.lstrip(".") for x in SOUND_EXTS),
                              ext or "没有扩展名")}
        d = USER_DATA / "sound"
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {"ok": False, "msg": "建不了 user_data/sound：%s" % e}
        dst = d / _snd_safe_name(src.name, k, ext)
        prev = _snd_custom(k)
        try:
            if src.resolve() != dst.resolve():
                for _try in range(6):
                    try:
                        shutil.copyfile(str(src), str(dst))
                        break
                    except OSError:
                        if _try == 5:
                            raise
                        time.sleep(0.15)
        except OSError as e:
            return {"ok": False, "msg": "复制失败：%s" % e}
        rel = dst.relative_to(USER_DATA).as_posix()
        got = self._sound_done(
            self._settings_call("--settings-set", {"sound.%s_file" % k: rel},
                                with_notes=False), "写不进配置")
        if got.get("ok"):
            _snd_drop_old(k, prev, keep=dst)
            got["msg"] = "换好了：%s" % dst.name
        return got

    def sound_reset(self, kind="finish"):
        k = _snd_kind(kind)
        prev = _snd_custom(k)
        got = self._sound_done(
            self._settings_call("--settings-set", {"sound.%s_file" % k: ""},
                                with_notes=False), "没恢复成")
        if not got.get("ok"):
            return got
        _snd_drop_old(k, prev)
        got["msg"] = "已回到出厂自带的那个"
        return got

    def _sound_done(self, r, fail_msg):
        _CFG_CACHE["data"] = None
        if not (isinstance(r, dict) and r.get("ok")):
            probs = (r or {}).get("problems") or []
            why = str((probs[0] or {}).get("why") or "") if probs else ""
            return {"ok": False, "msg": (r or {}).get("msg") or why or fail_msg}
        return {"ok": True, "items": {k: _snd_info(k) for k in SOUND_KINDS}}

    def ai_save_text(self, name="", text=""):
        try:
            import webview as _wv
            wins = list(getattr(_wv, "windows", None) or [])
            if not wins:
                return {"ok": False, "msg": "窗口还没准备好，稍一下再试"}
            win = wins[0]
            if not hasattr(win, "create_file_dialog"):
                return {"ok": False, "msg": "这个环境没有另存为对话框"}
            fd = getattr(_wv, "FileDialog", None)
            kind = getattr(fd, "SAVE", None) if fd is not None else None
            if kind is None:
                kind = getattr(_wv, "SAVE_DIALOG", None)
                if callable(kind):
                    kind = kind()
            if not kind:
                return {"ok": False, "msg": "这个 pywebview 版本不支持另存为"}
            fn = str(name or "").strip() or "粘贴文本.txt"
            types = ("文本文件 (*.txt)", "所有文件 (*.*)")
            try:
                res = win.create_file_dialog(kind, save_filename=fn, file_types=types)
            except TypeError:
                res = win.create_file_dialog(kind, directory=str(HOME),
                                             save_filename=fn, file_types=types)
            if not res:
                return {"ok": False, "cancelled": True, "msg": "没有选（取消）"}
            p = res if isinstance(res, str) else (res[0] if isinstance(res, (list, tuple)) else "")
            p = str(p or "").strip()
            if not p:
                return {"ok": False, "msg": "没拿到保存路径"}
            body = str(text or "")
            Path(p).write_text(body, encoding="utf-8", newline="\n")
            return {"ok": True, "path": p, "bytes": len(body.encode("utf-8"))}
        except Exception as e:
            return {"ok": False, "msg": "另存为失败：%s" % e}

    def ai_pick_attachments(self, images=False):
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
        except Exception as e:
            return {"ok": False, "msg": "挑附件失败：%s: %s" % (type(e).__name__, e)}

    def ai_ui_state(self):
        f = USER_DATA / "state" / "_ai_ui.json"
        try:
            data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
        except Exception:
            data = {}
        palette = str((data or {}).get("palette") or "") if isinstance(data, dict) else ""
        if not re.match(r"^#[0-9a-fA-F]{6}$", palette):
            palette = ""
        return {"ok": True, "palette": palette}

    def ai_ui_state_set(self, values=None):
        try:
            src = values if isinstance(values, dict) else {}
            f = USER_DATA / "state" / "_ai_ui.json"
            try:
                data = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
            except Exception:
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
        except Exception as e:
            return {"ok": False, "msg": str(e)}

    def pkg_watch(self):
        try:
            got = _pkg_watch_poll()
        except Exception as e:
            _note("pkg_watch 失败：%r" % (e,))
            return {"ok": False, "renamed": [], "gone": [], "changed": False, "ids": [],
                    "msg": str(e)}
        got["ok"] = True
        return got

    def autostart_get(self):
        return {"ok": True, "items": _autostart_read(),
                "packages": [{"id": str(p.get("id") or ""),
                              "name": str(p.get("name") or p.get("id") or ""),
                              "kind": str(p.get("kind") or "")}
                             for p in (DATA.get("packages") or []) if p.get("id")],
                "max": AUTOSTART_MAX}

    def autostart_set(self, items=None):
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
        except Exception as e:
            return {"ok": False, "msg": "存不了：%s" % e}
        return {"ok": True, "items": rows}

    def parasite_get(self):
        return {"ok": True, "ids": _parasite_read()}

    def parasite_set(self, ids=None):
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
        except Exception as e:
            return {"ok": False, "msg": "存不了：%s" % e}
        return {"ok": True, "ids": rows}

    def quit(self):
        window.destroy()
        return {"ok": True}

os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", "--no-proxy-server")

def _note(text):
    try:
        print("[moss] %s" % text, file=sys.stderr, flush=True)
    except Exception:
        pass

def _inline_html():
    try:
        page = HERE / "index.html"
        html = page.read_text(encoding="utf-8")

        def css_repl(m):
            rel = m.group(1).strip()
            try:
                return "<style>\n" + (HERE / rel).read_text(encoding="utf-8") + "\n</style>"
            except OSError:
                return m.group(0)

        def js_repl(m):
            rel = m.group(1).strip()
            try:
                body = (HERE / rel).read_text(encoding="utf-8")
            except OSError:
                return m.group(0)
            return "<script>\n" + body.replace("</script>", "<\\/script>") + "\n</script>"

        html = re.sub(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*>', css_repl, html)
        html = re.sub(r'<script[^>]*src="([^"]+)"[^>]*></script>', js_repl, html)
        html = re.sub(r"(<body[^>]*>)", lambda m: m.group(1) + "\n" + icons.script_tag(), html,
                      count=1, flags=re.I)
        html = re.sub(r"(<!doctype[^>]*>)",
                      lambda m: m.group(1) + "\n",
                      html, count=1, flags=re.I)
        return html
    except Exception as e:
        _note("page: 组装自包含页面失败（%r），退回原做法" % (e,))
        return None

_LIVE = {"html": ""}
LIVE_NAME = "__ui_live.html"

def _drop_legacy_inline():
    p = USER_DATA / "state" / "_ui_inline.html"
    try:
        if p.is_file():
            p.unlink()
            _note("page: 清掉了老位置的 _ui_inline.html（那份自包含页面现在只放内存）")
    except OSError:
        pass

def _page_url():
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
    if not any(a in ("--debug", "--dev", "-d") for a in sys.argv[1:]):
        return
    try:
        import tempfile
        p = Path(tempfile.gettempdir()) / "moss_ui_inline.html"
        p.write_text(html, encoding="utf-8", newline="")
        _note("page: （--debug）这份自包含页面也存了一份到 %s" % p)
    except OSError:
        pass

_ICON_KEEP = []

def _moss_hwnds():
    me = os.getpid()
    return [w["hwnd"] for w in _top_windows() if w["pid"] == me and w["visible"]]

def _apply_window_icon(win=None):
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
        hicon = u32.LoadImageW(None, str(ico), 1, 0, 0, 0x00000010 | 0x00000040)
        if not hicon:
            _note("icon: LoadImageW 没读出 %s" % ico)
            return False
        _ICON_KEEP.append(hicon)
        hwnds = _moss_hwnds()
        for hwnd in hwnds:
            for which in (1, 0):
                r = ctypes.c_size_t(0)
                u32.SendMessageTimeoutW(hwnd, 0x0080, which, hicon,
                                        0x0002, 2000, ctypes.byref(r))
        _note("icon: 窗口图标换成 %s（%d 个窗口）" % (ico.name, len(hwnds)))
        return bool(hwnds)
    except Exception as e:
        _note("icon: 换窗口图标失败（%r）" % (e,))
        return False

_FLOAT = {}
_FLOAT_LOCK = threading.Lock()

_ICON_DIR = USER_DATA / "state" / "_win_icons"

def _png_to_ico(png_bytes, out_path):
    try:
        from io import BytesIO
        from PIL import Image
        im = Image.open(BytesIO(png_bytes)).convert("RGBA")
        if max(im.size) < 256:
            im = im.resize((256, 256), Image.LANCZOS)
        im.save(str(out_path), format="ICO",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
        return
    except ImportError:
        pass
    import struct
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png_bytes), 6 + 16)
    out_path.write_bytes(header + entry + png_bytes)

def _load_icon_file(path):
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.LoadImageW.argtypes = [wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int,
                                   ctypes.c_int, wt.UINT]
        u32.LoadImageW.restype = wt.HANDLE
        hicon = u32.LoadImageW(None, str(path), 1, 0, 0, 0x00000010 | 0x00000040)
        if hicon:
            _ICON_KEEP.append(hicon)
        return hicon
    except Exception:
        return 0

def _hwnd_of(win):
    try:
        h = win.native.Handle
    except Exception:
        return 0
    for cast in ("ToInt64", "ToInt32"):
        try:
            return int(getattr(h, cast)())
        except Exception:
            continue
    try:
        return int(h)
    except Exception:
        return 0

def _hwnd_by_title(title):
    if not title:
        return 0
    for w in _top_windows():
        if w["pid"] == os.getpid() and w["visible"] and w["title"] == title:
            return w["hwnd"]
    return 0

def _wm_set_icon(hwnd, hicon):
    try:
        u32 = ctypes.WinDLL("user32", use_last_error=True)
        u32.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, wt.UINT, wt.WPARAM, wt.LPARAM,
                                            wt.UINT, wt.UINT,
                                            ctypes.POINTER(ctypes.c_size_t)]
        for which in (1, 0):
            r = ctypes.c_size_t(0)
            u32.SendMessageTimeoutW(hwnd, 0x0080, which, hicon,
                                    0x0002, 2000, ctypes.byref(r))
        return True
    except Exception:
        return False

def _js(win, code):
    try:
        win.evaluate_js(code)
        return True
    except Exception:
        return False

def _float_win(pid):
    with _FLOAT_LOCK:
        return _FLOAT.get(str(pid))

_FLOAT_LOAD_TIMEOUT = 10.0


def _float_ready(win):
    """这扇浮动窗口算不算「能用」：还在，而且页面当初真加载成功过。
    ★ 页面没加载成功的窗口 = 一扇白板（连 HTTP 请求都不发），留着只会骗人：
      下次再点「独立窗口」会走到 `show()` 那条路，把同一块白板又抬出来。"""
    try:
        if win.events.closed.is_set():
            return False
        return bool(win.events.loaded.is_set())
    except Exception:
        return False


def _watch_float(pid, win):
    """窗口建出来 ≠ 页面加载成功。

    ★ 真事（2026-11-14 用户报的「点独立窗口是一片空白」）：WebView2 运行时会自己更新
      （这台机器 11-14 凌晨 3:37 从 157.0.4341.46 换成了 .57）。moss 界面进程要是那会儿
      还开着，它手里那套 WebView2 环境还是旧的 —— 之后**新开**的 WebView2（= 浮动窗口）
      就初始化不起来：窗口出来了，里面一帧文档都没有，连请求都不发，页面那边一行日志
      都留不下（所以只看页内日志会以为是"啥也没发生"）。关掉重开一样白，重启 moss 立刻好。

    ⇒ 这里等不到 `loaded` 就把这扇窗关掉、退回内嵌，并把原因告诉用户。"""
    def run():
        try:
            ok = win.events.loaded.wait(_FLOAT_LOAD_TIMEOUT)
        except Exception:
            ok = False
        if ok or _float_win(pid) is not win:
            return
        _close_float_quiet(pid)
        _note("float: :%s 窗口建出来了但页面 %g 秒内没加载（WebView2 环境起不来？）"
              % (pid, _FLOAT_LOAD_TIMEOUT))
        _js(window, "window.__mossFloatFailed && window.__mossFloatFailed(%s, %s)"
            % (json.dumps(pid), json.dumps(
                "窗口没加载出来（WebView2 运行时刚更新过？重启 moss 就好）",
                ensure_ascii=False)))
    threading.Thread(target=run, daemon=True).start()


def _pkg_title(rec):
    def pick(v):
        if isinstance(v, dict):
            return str(v.get("zh-CN") or next(iter(v.values()), "") or "")
        return str(v or "")
    ui = (rec or {}).get("ui") or {}
    return (pick(ui.get("title")) or pick((rec or {}).get("name")) or "").strip()

def _destroy_soon(win, delay=0.25):
    def run():
        try:
            win.destroy()
        except Exception:
            pass
    try:
        threading.Timer(delay, run).start()
    except Exception:
        run()

def _close_float_quiet(pid):
    with _FLOAT_LOCK:
        w = _FLOAT.pop(str(pid), None)
    if w is not None:
        _destroy_soon(w)
    return w is not None

def _dock_float(pid, why=""):
    pid = str(pid)
    with _FLOAT_LOCK:
        w = _FLOAT.pop(pid, None)
    _js(window, "window.__mossFloatDock && window.__mossFloatDock(%s)" % json.dumps(pid))
    if w is not None:
        _destroy_soon(w)
    _note("float: :%s 收回（%s）" % (pid, why or "？"))

def _float_closed(pid):
    pid = str(pid)
    with _FLOAT_LOCK:
        w = _FLOAT.pop(pid, None)
    if w is None:
        return
    try:
        Api().embed_stop(pid)
    except Exception as e:
        _note("float: :%s 关闭时停后端失败（%r）" % (pid, e))
    _js(window, "window.__mossFloatClosed && window.__mossFloatClosed(%s)" % json.dumps(pid))
    _note("float: :%s 被关掉 → 按约定当作结束" % pid)

def _wire_float(pid, win, title):
    pid = str(pid)

    def later(fn, *a):
        threading.Thread(target=fn, args=a, daemon=True).start()

    win.events.minimized += lambda *a: later(_dock_float, pid, "点了最小化")
    win.events.closed += lambda *a: later(_float_closed, pid)
    win.events.shown += lambda *a: later(_apply_window_icon)
    _ = title

_PAGE_URL = _page_url()
_API = Api()

_WIN_GEOM_FILE = USER_DATA / "state" / win_geom.WIN_GEOM_NAME
_WIN_GEOM = win_geom.resolve(win_geom.load(_WIN_GEOM_FILE))

window = webview.create_window(
    "moss",
    _PAGE_URL,
    js_api=_API,
    width=_WIN_GEOM["width"],
    height=_WIN_GEOM["height"],
    x=_WIN_GEOM["x"],
    y=_WIN_GEOM["y"],
    min_size=win_geom.WIN_MIN_SIZE,
    maximized=_WIN_GEOM["maximized"],
    text_select=True,
)
_GEOM_WATCH = win_geom.watch(window, _WIN_GEOM_FILE, note=lambda s: _note("main: " + s))

DROP_LOG = USER_DATA / "state" / "_ui_drop.log"

def drop_log(text):
    try:
        DROP_LOG.parent.mkdir(parents=True, exist_ok=True)
        if DROP_LOG.is_file() and DROP_LOG.stat().st_size > 256 * 1024:
            keep = DROP_LOG.read_text(encoding="utf-8", errors="replace")[-64 * 1024:]
            DROP_LOG.write_text(keep, encoding="utf-8")
        line = "%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), text)
        with open(DROP_LOG, "a", encoding="utf-8") as fh:
            fh.write(line)
    except Exception:
        pass

def _on_files_dropped(event):
    try:
        files = (event.get("dataTransfer") or {}).get("files") or []
    except Exception as e:
        drop_log("drop 事件读不出来：%r" % (e,))
        files = []
    raw = []
    for f in files:
        try:
            raw.append({"name": f.get("name"), "hasPath": bool(f.get("pywebviewFullPath")),
                        "path": f.get("pywebviewFullPath"),
                        "type": f.get("type") or "", "size": f.get("size") or 0})
        except Exception:
            pass
    drop_log("host drop: %d 个 —— %s" % (len(files), json.dumps(raw, ensure_ascii=False)))
    items = []
    for f in files:
        try:
            p = f.get("pywebviewFullPath")
        except Exception:
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
        drop_log("→ 一个真实路径都没拿到（WebView2 没给；文件夹尤其可能这样）")
        return
    try:
        window.evaluate_js("window.__mossDrop(%s)" % json.dumps(items, ensure_ascii=False))
        drop_log("→ 已交给页面：%s" % json.dumps(items, ensure_ascii=False))
    except Exception as e:
        drop_log("→ 交给页面时出错：%r" % (e,))

def _arm_file_drop():
    try:
        from webview.dom import DOMEventHandler
        window.events.loaded.wait(20)
        _apply_window_icon(window)
        window.dom.document.events.drop += DOMEventHandler(
            _on_files_dropped, prevent_default=True, stop_propagation=True)
        drop_log("armed: 监听挂在 document 上（num_listeners 应该 > 0 了）")
    except Exception as e:
        drop_log("armed 失败（拖放会完全没反应）：%r" % (e,))

def _hook_webview_log():
    """把 pywebview 自己的日志也接进 `user_data/state/_ui_drop.log`。

    ★ 它的报错（最典型的就是 `WebView2 initialization failed with exception: ...`）默认只
      走 logging 到 stderr —— 双击启动的 moss 根本没有 stderr，于是"窗口空白"这种事就彻底
      没有线索可查（2026-11-14 那次排查就是卡在这儿）。"""
    try:
        import logging as _logging

        class _WebviewLog(_logging.Handler):
            def emit(self, record):
                try:
                    drop_log("webview[%s] %s" % (record.levelname, record.getMessage()))
                except Exception:
                    pass

        lg = _logging.getLogger("pywebview")
        lg.addHandler(_WebviewLog())
        lg.setLevel(_logging.WARNING)
    except Exception:
        pass

if __name__ == "__main__":
    DEBUG = any(a in ("--debug", "--dev", "-d") for a in sys.argv[1:])
    if DEBUG:
        print("[moss] 开发模式：devtools 已开（F12 / 右键「检查」）。"
              "页面里的报错也会写到界面右下角状态栏。", flush=True)
    _hook_webview_log()
    window.events.closing += _on_ui_closing
    webview.start(_arm_file_drop, debug=DEBUG)
