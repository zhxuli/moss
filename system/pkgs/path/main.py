# -*- coding: utf-8 -*-
"""PATH 管理 —— 一份界面代码（`ui/index.html`，Vue 3），两种跑法（照抄 `bmi` 那个样板，`V-48`）：

    moss :path                 不带参数 → 自己开一个窗口
    在 moss 界面里点「运行」     → 内嵌到 moss 的「界面」选项卡里跑（`pkg.json` 的 `ui.embed`）

界面跟后端说话全部经过 `ui/moss-embed.js` 那个垫片：被嵌进 moss 时走 postMessage，
独立窗口时走 pywebview 的 `js_api`。**改注册表、读写备份全在这个文件里** ——
界面只负责显示，所以"是不是 Python 在干活"看一眼命令行那页的 print 就知道。

★ 数据放哪（`V-200`）：`MOSS_PLUGIN_DATA_DIR`（= `user_data/state/path/`）下面的
  `data/backups/path_backup_<时间戳>.txt`，**一行一个路径**。老位置
  `.path_editor/path_bak/` 仍然**认**（能列出来、能恢复、能删），但**不再往里写**。
★ 只改**当前用户**的 PATH（注册表 `HKCU\\Environment` 的 `Path`，`REG_EXPAND_SZ`），
  不需要管理员；改完广播 `WM_SETTINGCHANGE`（**已经开着的**终端不会变，新开的才看得到）。
★ 上一版是 tkinter 界面（`PathEditorApp` / `RestoreWindow`，还依赖 `windnd` 收拖放）——
  按契约"界面写成网页、别用 Tk 写新包"换掉了：现在一份网页两份环境通用，
  并且**不再需要 windnd**（拖文件夹进来的事由 moss 那边负责）。
"""
import ctypes
import json
import os
import sys
import threading
import winreg
from datetime import datetime
from pathlib import Path

#: 这个包自己的目录（"注册自身目录"那颗按钮用的就是它）
SELF_DIR = os.path.dirname(os.path.abspath(__file__))

#: 宿主注入的插件数据目录；独立运行时退回 `user_data/state/path`
DATA_DIR = Path(
    os.environ.get('MOSS_PLUGIN_DATA_DIR')
    or os.environ.get('PA_PLUGIN_DATA_DIR')
    or (Path(os.environ.get('MOSS_HOME') or Path.home()) / 'user_data' / 'state' / 'path')
)

#: 备份放这儿（`V-200`：按契约用 `data/`——持久、要备份的东西放这里）
BACKUP_DIR = DATA_DIR / 'data' / 'backups'
#: 老位置：只读认，不再写
LEGACY_BACKUP_DIR = DATA_DIR / '.path_editor' / 'path_bak'

TITLE = 'PATH 管理'
UI_FILE = os.path.join(SELF_DIR, 'ui', 'index.html')


# ---------------------------------------------------------------- 备份
class BackupManager:
    """备份就是"把当前用户 PATH 那一串存成一份文本"（一行一个路径）。

    ★ 为什么存纯文本：出问题时用记事本就能看、能对、能手工拼回去 —— 备份这种东西
      **可读性**比紧凑重要（而且老备份就是这格式，换格式等于把老备份作废）。
    """

    def __init__(self):
        self.backup_dir = BACKUP_DIR
        self.legacy_dir = LEGACY_BACKUP_DIR
        self.backup_prefix = "path_backup_"
        self.time_format = "%Y%m%d_%H%M%S"

    # ---- 写
    def create_backup(self, paths):
        """返回 (ok, 说明, 文件路径)。空 PATH 不备份（没有意义）。"""
        if not paths:
            return False, "当前 PATH 是空的，没什么可备份", ""
        stamp = datetime.now().strftime(self.time_format)
        f = self.backup_dir / ("%s%s.txt" % (self.backup_prefix, stamp))
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)     # 懒加载：真要写才建目录
            with open(f, 'w', encoding='utf-8') as fh:
                fh.write("\n".join(paths) + "\n")
            return True, "已备份 %d 条到 %s" % (len(paths), f), str(f)
        except OSError as e:
            return False, "备份失败：%s" % e, ""

    # ---- 读
    def read(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as fh:
                return [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            return []

    def _scan(self, folder, legacy):
        out = []
        try:
            files = list(folder.glob("%s*.txt" % self.backup_prefix))
        except OSError:
            return out
        for f in files:
            try:
                stamp = f.stem.replace(self.backup_prefix, '')
                when = datetime.strptime(stamp, self.time_format)
            except ValueError:
                continue
            paths = self.read(str(f))
            out.append({"file": str(f), "time": when.strftime("%Y-%m-%d %H:%M:%S"),
                        "stamp": stamp, "total": len(paths), "paths": paths,
                        "legacy": bool(legacy)})
        return out

    def list_backups(self, current_paths):
        """所有备份，新的在前。带上"与现在比会新增/移除几条"（恢复前先看清楚）。"""
        cur = {os.path.normpath(p).lower() for p in current_paths}
        out = self._scan(self.backup_dir, False) + self._scan(self.legacy_dir, True)
        for b in out:
            bset = {os.path.normpath(p).lower() for p in b["paths"]}
            b["add"] = len(bset - cur)
            b["remove"] = len(cur - bset)
        return sorted(out, key=lambda x: x["stamp"], reverse=True)

    def diff(self, backup_paths, current_paths):
        """这份备份和现在比：会**新增**哪些、会**移除**哪些。"""
        bset = {os.path.normpath(p).lower() for p in backup_paths}
        cur = {os.path.normpath(p).lower() for p in current_paths}
        add = [p for p in backup_paths if os.path.normpath(p).lower() not in cur]
        gone = [p for p in current_paths if os.path.normpath(p).lower() not in bset]
        return add, gone

    def delete(self, filepath):
        """删一份备份。只认自己那两个目录里的（别让界面把任意文件删了）。"""
        p = Path(filepath).resolve()
        for folder in (self.backup_dir, self.legacy_dir):
            try:
                if p.parent.resolve() == folder.resolve() and p.is_file():
                    p.unlink()
                    return True, "已删除备份：%s" % p.name
            except OSError as e:
                return False, "删除失败：%s" % e
        return False, "这个文件不在备份目录里，没动它"


# ---------------------------------------------------------------- PATH（注册表）
class PathManager:
    ENV_REG_KEY = winreg.HKEY_CURRENT_USER
    ENV_REG_SUBKEY = 'Environment'
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A

    def _broadcast_change(self):
        """告诉系统"环境变量变了" —— 新开的进程才会拿到新 PATH。"""
        ctypes.windll.user32.SendNotifyMessageW(
            self.HWND_BROADCAST, self.WM_SETTINGCHANGE, 0, ctypes.c_wchar_p('Environment'))

    def get_user_path_list(self):
        """当前用户的 PATH（拆成一条一条，去掉空的）。系统 PATH 在这个键里看不到 —— 那在
        `HKLM`，我们**不动**它（用户级就够用，也不用管理员）。"""
        try:
            with winreg.OpenKey(self.ENV_REG_KEY, self.ENV_REG_SUBKEY) as key:
                value, _ = winreg.QueryValueEx(key, 'Path')
            return [p.strip() for p in str(value).split(';') if p.strip()]
        except FileNotFoundError:
            return []
        except OSError:
            return []

    def is_registered(self, path):
        want = os.path.normpath(path).lower()
        return any(os.path.normpath(p).lower() == want for p in self.get_user_path_list())

    def write(self, paths, success_msg):
        """整串写回去 + 广播。**所有改动都走这里**（只有一处碰注册表）。"""
        try:
            with winreg.OpenKey(self.ENV_REG_KEY, self.ENV_REG_SUBKEY, 0,
                                winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, 'Path', 0, winreg.REG_EXPAND_SZ, ';'.join(paths))
            self._broadcast_change()
            return True, success_msg
        except OSError as e:
            return False, "改注册表失败：%s" % e

    def add(self, path):
        p = os.path.normpath(str(path).strip().strip('"'))
        cur = self.get_user_path_list()
        if any(os.path.normpath(x).lower() == p.lower() for x in cur):
            return False, "这条已经在 PATH 里了：%s" % p
        return self.write(cur + [p], "已加进 PATH：%s" % p)

    def remove(self, path):
        p = os.path.normpath(str(path).strip().strip('"')).lower()
        cur = self.get_user_path_list()
        left = [x for x in cur if os.path.normpath(x).lower() != p]
        if len(left) == len(cur):
            return False, "这条不在 PATH 里：%s" % path
        return self.write(left, "已从 PATH 移除：%s" % path)

    def dedup(self):
        """去掉重复项（大小写不敏感），保持原顺序。返回 (ok, 说明)。"""
        cur = self.get_user_path_list()
        seen, keep = set(), []
        for p in cur:
            k = os.path.normpath(p).lower()
            if k not in seen:
                seen.add(k)
                keep.append(p)
        if len(keep) == len(cur):
            return False, "没有重复项"
        return self.write(keep, "去掉 %d 条重复项" % (len(cur) - len(keep)))

    def drop_missing(self):
        """把"目录已经不存在"的那些摘掉（只摘**盘符路径**里确实没有的；带 `%VAR%` 的
        展开不了就留着，别误伤）。"""
        cur = self.get_user_path_list()
        keep, gone = [], []
        for p in cur:
            if '%' in p:
                keep.append(p)
                continue
            (gone if not os.path.isdir(p) else keep).append(p)
        if not gone:
            return False, "没有失效的目录"
        ok, msg = self.write(keep, "清掉 %d 条已经不存在的目录" % len(gone))
        return ok, (msg + "：" + "；".join(gone[:3]) + ("…" if len(gone) > 3 else "")) if ok else msg


# ---------------------------------------------------------------- 界面能调的东西
class Api:
    """界面里 `moss.call("名字", {...})` 就能调到下面这些方法。

    ★ 内嵌（stdio）和独立窗口（pywebview `js_api`）**共用同一份** —— 这就是
      "一份界面两种跑法"能成立的原因（照抄 bmi）。
    ★ 约定：真要干活儿的方法返回 `{"ok": bool, "msg": "...", "state": {...}}` ——
      带上**改完之后**的完整状态，界面一次往返就能重画（不用再问一遍）。
    """

    def __init__(self):
        self.pm = PathManager()
        self.bm = BackupManager()

    # ---- 状态
    def state(self, params=None):
        paths = self.pm.get_user_path_list()
        return {
            "ok": True,
            "count": len(paths),
            "paths": sorted(paths, key=str.lower),
            "self_dir": SELF_DIR,
            "self_registered": self.pm.is_registered(SELF_DIR),
            "data_dir": str(DATA_DIR),
            "backup_dir": str(self.bm.backup_dir),
            "legacy_dir": str(self.bm.legacy_dir),
            "missing": [p for p in paths if '%' not in p and not os.path.isdir(p)],
        }

    def info(self, params=None):
        """自证：这些数字是 Python 报的（`V-54` 那条"让后端证明它在干活"）。"""
        print('[path] 后端信息：pid=%d python=%s 数据目录=%s'
              % (os.getpid(), sys.version.split()[0], DATA_DIR), flush=True)
        return {"ok": True, "pid": os.getpid(), "python": sys.version.split()[0],
                "data_dir": str(DATA_DIR), "self_dir": SELF_DIR,
                "embedded": bool(os.environ.get('MOSS_UI_EMBED'))}

    # ---- 改 PATH
    def add(self, params=None):
        p = str((params or {}).get("path") or "").strip()
        if not p:
            return {"ok": False, "msg": "先给一个目录", "state": self.state()}
        ok, msg = self.pm.add(p)
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def add_many(self, params=None):
        """一次加好几条 —— 拖文件夹进来、或拖文件时取它所在的目录（`V-201`）。

        ★ **只写一次注册表、只广播一次**：拖 5 个目录进来不代表要改 5 遍环境变量。
        ★ 拖进来的是**文件** ⇒ 用**它所在的目录**（老 tkinter 界面就是这个规矩）。
        """
        raw = list((params or {}).get("paths") or [])
        cur = self.pm.get_user_path_list()
        seen = {os.path.normpath(p).lower() for p in cur}
        added, dup, bad = [], [], []
        for item in raw:
            p = str(item or "").strip().strip('"')
            if not p:
                continue
            if os.path.isfile(p):                       # 拖的是文件 → 要它所在的目录
                p = os.path.dirname(p)
            p = os.path.normpath(p)
            if not os.path.isdir(p):
                bad.append(p)
                continue
            key = p.lower()
            if key in seen:
                dup.append(p)
                continue
            seen.add(key)
            added.append(p)
        if not added:
            bits = []
            if dup:
                bits.append("%d 条已经在 PATH 里" % len(dup))
            if bad:
                bits.append("%d 条目录不存在" % len(bad))
            why = "、".join(bits) or "没拿到可用的目录"
            print('[path] 没加任何东西：%s' % why, flush=True)
            return {"ok": False, "msg": why, "state": self.state()}
        ok, msg = self.pm.write(cur + added, "加进 PATH %d 条：%s"
                                % (len(added), "；".join(added[:2]) + ("…" if len(added) > 2 else "")))
        if dup or bad:
            msg += "（跳过 %d 条重复 / %d 条不存在）" % (len(dup), len(bad))
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def remove(self, params=None):
        p = str((params or {}).get("path") or "").strip()
        ok, msg = self.pm.remove(p)
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def toggle_self(self, params=None):
        """注册 / 反注册**这个包自己的目录**。"""
        if self.pm.is_registered(SELF_DIR):
            ok, msg = self.pm.remove(SELF_DIR)
        else:
            ok, msg = self.pm.add(SELF_DIR)
        print('[path] %s' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def dedup(self, params=None):
        ok, msg = self.pm.dedup()
        return {"ok": ok, "msg": msg, "state": self.state()}

    def drop_missing(self, params=None):
        ok, msg = self.pm.drop_missing()
        return {"ok": ok, "msg": msg, "state": self.state()}

    def pick_dir(self, params=None):
        """弹系统对话框挑一个文件夹。

        ★ 独立窗口：用 pywebview 的对话框（挂在我们自己那扇窗上）。
          内嵌：我们**没有自己的窗口**（窗口是 moss 的）⇒ 退回 tkinter 的 askdirectory。
          界面那边通常会先问 moss 主界面要（那边有正规的对话框），这条路是兜底。
        """
        start = str((params or {}).get("start") or "").strip() or (self.pm.get_user_path_list() or [SELF_DIR])[0]
        try:
            import webview as _wv
            wins = list(getattr(_wv, "windows", None) or [])
            if wins:
                kind = getattr(getattr(_wv, "FileDialog", None), "FOLDER", None)
                if kind is None:
                    kind = getattr(_wv, "FOLDER_DIALOG", None)
                    if callable(kind):
                        kind = kind()
                if kind is not None:
                    try:
                        res = wins[0].create_file_dialog(kind, directory=start)
                    except TypeError:
                        res = wins[0].create_file_dialog(kind, start)
                    if not res:
                        return {"ok": False, "msg": "没有选（取消）"}
                    return {"ok": True, "path": str(res[0] if isinstance(res, (list, tuple)) else res)}
        except Exception:                                              # noqa: BLE001
            pass
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()                     # 只借它弹一个对话框，别闪出一个空窗
            p = filedialog.askdirectory(title="选一个要加进 PATH 的文件夹", initialdir=start)
            root.destroy()
            if not p:
                return {"ok": False, "msg": "没有选（取消）"}
            return {"ok": True, "path": str(p)}
        except Exception as e:                                          # noqa: BLE001
            return {"ok": False, "msg": "挑文件夹失败：%s" % e}

    # ---- 备份 / 恢复
    def backup_create(self, params=None):
        ok, msg, f = self.bm.create_backup(self.pm.get_user_path_list())
        print('[path] %s' % msg, flush=True)
        return {"ok": ok, "msg": msg, "file": f, "state": self.state()}

    def backup_list(self, params=None):
        return {"ok": True, "items": self.bm.list_backups(self.pm.get_user_path_list()),
                "state": self.state()}

    def backup_preview(self, params=None):
        """恢复前先看清楚：会加什么、会去掉什么。"""
        f = str((params or {}).get("file") or "")
        paths = self.bm.read(f)
        if not paths:
            return {"ok": False, "msg": "这份备份读不出来（文件没了？）", "state": self.state()}
        add, gone = self.bm.diff(paths, self.pm.get_user_path_list())
        return {"ok": True, "add": add, "remove": gone, "paths": paths,
                "msg": "会加 %d 条、去掉 %d 条" % (len(add), len(gone)), "state": self.state()}

    def backup_restore(self, params=None):
        f = str((params or {}).get("file") or "")
        paths = self.bm.read(f)
        if not paths:
            return {"ok": False, "msg": "这份备份读不出来（文件没了？）", "state": self.state()}
        ok, msg = self.pm.write(paths, "已恢复成 %s 那份备份（%d 条）"
                                % (Path(f).stem.replace(self.bm.backup_prefix, ""), len(paths)))
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def backup_delete(self, params=None):
        ok, msg = self.bm.delete(str((params or {}).get("file") or ""))
        return {"ok": ok, "msg": msg, "state": self.state()}


# ---------------------------------------------------------------- 内嵌模式（stdio）
class Embedded:
    """宿主给了 `MOSS_UI_EMBED=1` 时走这儿：**不开窗口**，在 stdin/stdout 上说话。

    协议（`V-48`）：一行一个 JSON 对象 ——
      收 `{"id": 1, "method": "state", "params": {...}}`
      回 `{"id": 1, "ok": true, "result": {...}}` / `{"id": 1, "ok": false, "error": "…"}`
      主动推 `{"event": "名字", "data": {...}}`（本包暂时不推东西，留着口子）
    """

    def __init__(self):
        self.api = Api()

    def send(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    def loop(self):
        for line in sys.stdin:
            line = (line or '').strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send({'event': 'error', 'data': {'why': '这不是 JSON：%s' % line[:80]}})
                continue
            mid = msg.get('id')
            method = str(msg.get('method') or '')
            fn = getattr(self.api, method, None)
            if not callable(fn) or method.startswith('_'):
                self.send({'id': mid, 'ok': False, 'error': '没有这个方法：%s' % method})
                continue
            try:
                self.send({'id': mid, 'ok': True, 'result': fn(msg.get('params'))})
            except Exception as e:                                     # noqa: BLE001
                self.send({'id': mid, 'ok': False, 'error': '%s: %s' % (type(e).__name__, e)})
        return 0


# ---------------------------------------------------------------- 独立窗口
def run_window():
    """自己开一扇窗（`moss :path`）。界面文件和内嵌时**是同一份**。"""
    import webview

    api = Api()
    window = webview.create_window(TITLE, url=UI_FILE, js_api=api,
                                   width=980, height=700, min_size=(620, 460))

    def on_drop(event):
        """页面上的 drop → 把**真实路径**交给页面（`V-201`）。

        ★ Chromium **不把 `File.path` 交给页面**（安全设计）：路径只有 Python 这侧拿得到
          （pywebview 从 WebView2 的 AdditionalObjects 里取出，放在 `pywebviewFullPath`）。
          挂法和 moss 主界面那套**一模一样**（`system/ui/main.py:_on_files_dropped`）——
          而且只有挂过监听，pywebview 才会把路径留下来（没监听它直接丢掉）。
        """
        try:
            files = (event.get("dataTransfer") or {}).get("files") or []
        except Exception:                                              # noqa: BLE001
            files = []
        items = []
        for f in files:
            try:
                p = f.get("pywebviewFullPath")
            except Exception:                                          # noqa: BLE001
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
        print('[path] 拖进来 %d 个（%d 个带路径）' % (len(files), len(items)), flush=True)
        if not items:
            return
        try:
            window.evaluate_js('window.moss && window.moss.__emit("drop", %s)'
                               % json.dumps({"items": [it["path"] for it in items]},
                                            ensure_ascii=False))
        except Exception:                                              # noqa: BLE001
            pass

    def arm_drop():
        """等页面加载完再挂 drop 监听（`webview.start` 里跑，在别的线程）。"""
        try:
            from webview.dom import DOMEventHandler
            window.events.loaded.wait(20)
            window.dom.document.events.drop += DOMEventHandler(
                on_drop, prevent_default=True, stop_propagation=True)
            print('[path] 拖放监听已挂上（拖文件夹进来就能加）', flush=True)
        except Exception as e:                                          # noqa: BLE001
            print('[path] 拖放监听没挂上（不影响别的功能）：%r' % (e,), flush=True)

    threading.Thread(target=arm_drop, daemon=True).start()
    webview.start()
    return 0


# ---------------------------------------------------------------- 命令行
def _split_args(s):
    r"""按空白拆参数，但**不碰反斜杠**（照抄 tree/path 的同名函数）。

    为什么不用 shlex：Windows 路径里的 `\` 会被它当转义吃掉。引号包起来的算一个参数。
    """
    out, cur, quote = [], "", None
    for ch in s:
        if quote:
            if ch == quote:
                quote = None
            else:
                cur += ch
        elif ch in "\"'":
            quote = ch
        elif ch.isspace():
            if cur:
                out.append(cur)
                cur = ""
        else:
            cur += ch
    if cur:
        out.append(cur)
    return out


def _moss_args():
    """从宿主拿参数（`MOSS_PKG_PARAMS` / `MOSS_ARGS`）；拿不到返回 None（退回 sys.argv）。

    `args` 在 pkg.json 里声明成 `rest: true`（包名后面那一整串全归我），所以这里原样拆开。
    """
    raw = os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            p = json.loads(raw) or {}
            if p.get("args"):
                return _split_args(str(p["args"]))
        except ValueError:
            pass
    raw = os.environ.get("MOSS_ARGS")
    if raw:
        return _split_args(raw)
    return None


def print_cli_help():
    print("""
PATH 管理 —— 命令行用法

  moss :path                  打开界面（不带参数）
  moss :path add [目录]       把目录加进**当前用户**的 PATH（别名 register / reg）
  moss :path remove [目录]    从 PATH 里移除（别名 unregister / del）
  moss :path help             这条帮助

  · 省略 [目录] 时用**这个包自己的目录**。
  · 只改当前用户（注册表 HKCU\\Environment\\Path），不需要管理员。
  · 改完广播一次系统消息 —— **已经开着的**终端不会变，新开的才看得到。
  · 备份在 user_data/state/path/data/backups/（界面里有备份 / 恢复 / 对比）。
""")


def parse_cli_args():
    args = _moss_args()
    if args is None:
        args = sys.argv[1:]
    if args and args[0] == '-c':
        args = args[1:]
        if args and (args[0].endswith('.py') or Path(args[0]).is_file()):
            args = args[1:]
    if not args:
        return None, None
    COMMANDS = {'add': ['add', 'register', 'reg'],
                'remove': ['remove', 'unregister', 'del'],
                'help': ['help', '?', '-h', '--help']}
    first = args[0].lower()
    if first in COMMANDS['help']:
        return 'help', None
    for kind in ('add', 'remove'):
        for alias in COMMANDS[kind]:
            if first.startswith(alias + ' '):
                return kind, args[0][len(alias) + 1:].strip('"')
            if first == alias:
                return kind, (" ".join(args[1:]).strip('"') or None)
    # ★ 拖一个文件夹进来（或直接 `moss :path D:\tools\bin`）：第一次位置参数不是命令，
    #   但它**是个存在的目录** ⇒ 当 `add` 用。不这么认的话，拖进来的目录会被当成
    #   "未知命令"，然后打一屏用法退出 —— 而 `pkg.json` 里的 drop 声明就是"拖目录进来"。
    if os.path.isdir(args[0].strip('"')):
        return 'add', args[0].strip('"')
    return first, " ".join(args[1:])


def main():
    if str(os.environ.get('MOSS_UI_EMBED') or '').strip() in ('1', 'true', 'yes'):
        return Embedded().loop()          # 内嵌：不开窗口，在 stdio 上答话
    command, path = parse_cli_args()
    if command is None:
        return run_window()               # 不带参数 → 界面
    if command == 'help':
        print_cli_help()
        return 0
    pm = PathManager()
    target = path or SELF_DIR
    if command == 'add':
        ok, msg = pm.add(target)
    elif command == 'remove':
        ok, msg = pm.remove(target)
    else:
        print("错误：不认识这个命令 %r\n" % command)
        print_cli_help()
        return 1
    print(msg)
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
