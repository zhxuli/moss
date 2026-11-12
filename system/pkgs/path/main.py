import ctypes
import json
import os
import shutil
import sys
import threading
import winreg
from datetime import datetime
from pathlib import Path

if getattr(sys, 'frozen', False):
    SELF_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SELF_DIR = os.path.dirname(os.path.abspath(__file__))

def _ui_file():
    for c in (Path(SELF_DIR) / 'ui' / 'index.html',
              Path(os.path.dirname(os.path.abspath(__file__))) / 'ui' / 'index.html'):
        if c.is_file():
            return str(c)
    return ""

UI_FILE = _ui_file()

def _data_dir():
    for env in ('MOSS_PLUGIN_DATA_DIR', 'PA_PLUGIN_DATA_DIR'):
        v = os.environ.get(env)
        if v:
            return Path(v)
    home = os.environ.get('MOSS_HOME')
    if home:
        return Path(home) / 'user_data' / 'state' / 'path'
    if getattr(sys, 'frozen', False):
        return Path(SELF_DIR) / 'user_data' / 'state' / 'path'
    return Path.home() / 'user_data' / 'state' / 'path'

DATA_DIR = _data_dir()

BACKUP_DIR = DATA_DIR / 'data' / 'backups'
LEGACY_BACKUP_DIR = DATA_DIR / '.path_editor' / 'path_bak'

SYS_BACKUP_DIR = DATA_DIR / 'data' / 'backups_system'
SYS_WRITER = Path(SELF_DIR) / 'syswrite.py'

TITLE = 'PATH 管理'

class BackupManager:
    def __init__(self):
        self.backup_dir = BACKUP_DIR
        self.legacy_dir = LEGACY_BACKUP_DIR
        self.sys_backup_dir = SYS_BACKUP_DIR
        self.backup_prefix = "path_backup_"
        self.time_format = "%Y%m%d_%H%M%S"

    _BAD = set('\\/:*?"<>|')

    def clean_name(self, name, fallback=""):
        s = "".join(ch for ch in str(name or "") if ch not in self._BAD and ord(ch) >= 32)
        s = s.strip().rstrip(".")
        s = s.strip()
        return (s or fallback)[:60].strip()

    def _unique(self, folder, stem):
        f = folder / (stem + ".txt")
        n = 2
        while f.exists():
            f = folder / ("%s (%d).txt" % (stem, n))
            n += 1
        return f

    def _resolve(self, filepath):
        p = Path(str(filepath or "")).resolve()
        for folder in (self.backup_dir, self.legacy_dir):
            try:
                if p.parent.resolve() == folder.resolve() and p.is_file():
                    return p
            except OSError:
                continue
        return None

    def create_backup(self, paths, name=""):
        if not paths:
            return False, "当前 PATH 是空的，没什么可备份", ""
        stamp = datetime.now().strftime(self.time_format)
        stem = self.clean_name(name, "") or ("%s%s" % (self.backup_prefix, stamp))
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)
            f = self._unique(self.backup_dir, stem)
            with open(f, 'w', encoding='utf-8') as fh:
                fh.write("\n".join(paths) + "\n")
            return True, "已备份 %d 条到 %s" % (len(paths), f.name), str(f)
        except OSError as e:
            return False, "备份失败：%s" % e, ""

    def create_sys_backup(self, paths, tag=""):
        if paths is None:
            return False, ""
        stamp = datetime.now().strftime(self.time_format)
        stem = "sys_path_backup_%s%s" % (stamp, ("_" + tag) if tag else "")
        try:
            self.sys_backup_dir.mkdir(parents=True, exist_ok=True)
            f = self._unique(self.sys_backup_dir, stem)
            with open(f, 'w', encoding='utf-8') as fh:
                fh.write("\n".join(paths) + ("\n" if paths else ""))
            return True, str(f)
        except OSError:
            return False, ""

    def rename(self, filepath, name):
        p = self._resolve(filepath)
        if p is None:
            return False, "这个文件不在备份目录里，没动它", ""
        stem = self.clean_name(name, "")
        if not stem:
            return False, "名字不能是空的", ""
        if stem == p.stem:
            return True, "名字没变（还是 %s）" % p.name, str(p)
        target = self._unique(p.parent, stem)
        try:
            p.rename(target)
            return True, "已改名为：%s" % target.name, str(target)
        except OSError as e:
            return False, "改名失败：%s" % e, ""

    def read(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as fh:
                return [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            return []

    def _scan(self, folder, legacy):
        out = []
        try:
            files = sorted(folder.glob("*.txt"))
        except OSError:
            return out
        for f in files:
            try:
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
            except OSError:
                continue
            stem = f.stem
            custom, when = stem, mtime
            if stem.startswith(self.backup_prefix):
                try:
                    when = datetime.strptime(stem[len(self.backup_prefix):], self.time_format)
                    custom = ""
                except ValueError:
                    pass
            paths = self.read(str(f))
            out.append({"file": str(f), "name": custom, "time": when.strftime("%Y-%m-%d %H:%M:%S"),
                        "sort": when.strftime(self.time_format), "total": len(paths),
                        "paths": paths, "legacy": bool(legacy)})
        return out

    def list_backups(self, current_paths):
        cur = {os.path.normpath(p).lower() for p in current_paths}
        out = self._scan(self.backup_dir, False) + self._scan(self.legacy_dir, True)
        for b in out:
            bset = {os.path.normpath(p).lower() for p in b["paths"]}
            b["add"] = len(bset - cur)
            b["remove"] = len(cur - bset)
        return sorted(out, key=lambda x: x["sort"], reverse=True)

    def diff(self, backup_paths, current_paths):
        bset = {os.path.normpath(p).lower() for p in backup_paths}
        cur = {os.path.normpath(p).lower() for p in current_paths}
        add = [p for p in backup_paths if os.path.normpath(p).lower() not in cur]
        gone = [p for p in current_paths if os.path.normpath(p).lower() not in bset]
        return add, gone

    def delete(self, filepath):
        p = self._resolve(filepath)
        if p is None:
            return False, "这个文件不在备份目录里，没动它"
        try:
            p.unlink()
            return True, "已删除备份：%s" % p.name
        except OSError as e:
            return False, "删除失败：%s" % e

def dir_state(p):
    try:
        real = os.path.expandvars(p)
    except Exception:
        return 'unknown'
    if '%' in real:
        return 'unknown'
    return 'ok' if os.path.isdir(real) else 'missing'

class _SEI(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("fMask", ctypes.c_ulong),
                ("hwnd", ctypes.c_void_p), ("lpVerb", ctypes.c_wchar_p),
                ("lpFile", ctypes.c_wchar_p), ("lpParameters", ctypes.c_wchar_p),
                ("lpDirectory", ctypes.c_wchar_p), ("nShow", ctypes.c_int),
                ("hInstApp", ctypes.c_void_p), ("lpIDList", ctypes.c_void_p),
                ("lpClass", ctypes.c_wchar_p), ("hkeyClass", ctypes.c_void_p),
                ("dwHotKey", ctypes.c_ulong), ("hIcon", ctypes.c_void_p),
                ("hProcess", ctypes.c_void_p)]

SEE_MASK_NOCLOSEPROCESS = 0x00000040
ERROR_CANCELLED = 1223
_shell32 = ctypes.WinDLL('shell32', use_last_error=True)
_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

def _pyw():
    exe = sys.executable or ''
    base = os.path.basename(exe).lower()
    if base.startswith('python'):
        folder = os.path.dirname(exe)
        for name in ('pythonw.exe', 'python.exe'):
            cand = os.path.join(folder, name)
            if os.path.isfile(cand):
                return cand
        return exe
    return shutil.which('pythonw.exe') or shutil.which('python.exe') or exe

def run_elevated(exe, script, args, timeout=180):
    params = '"%s"%s' % (script, ''.join(' "%s"' % a for a in args))
    sei = _SEI()
    sei.cbSize = ctypes.sizeof(_SEI)
    sei.fMask = SEE_MASK_NOCLOSEPROCESS
    sei.lpVerb = 'runas'
    sei.lpFile = exe
    sei.lpParameters = params
    sei.nShow = 0
    try:
        ok = _shell32.ShellExecuteExW(ctypes.byref(sei))
    except OSError as e:
        return None, '提权失败：%s' % e
    if not ok:
        code = ctypes.get_last_error()
        if code == ERROR_CANCELLED:
            return None, '你在 UAC 弹窗里点了「取消」，系统 PATH 一个字没动'
        return None, '提权没起来（错误码 %s）—— 这次什么都没改' % (code or '未知')
    if not sei.hProcess:
        return None, '提权起来了但拿不到进程句柄 —— 这次不确定改没改，请点「刷新」看一眼'
    try:
        _kernel32.WaitForSingleObject(ctypes.c_void_p(sei.hProcess), int(timeout) * 1000)
        code = ctypes.c_ulong()
        _kernel32.GetExitCodeProcess(ctypes.c_void_p(sei.hProcess), ctypes.byref(code))
        return int(code.value), ''
    finally:
        _kernel32.CloseHandle(ctypes.c_void_p(sei.hProcess))

class PathManager:
    ENV_REG_KEY = winreg.HKEY_CURRENT_USER
    ENV_REG_SUBKEY = 'Environment'
    SYS_REG_KEY = winreg.HKEY_LOCAL_MACHINE
    SYS_REG_SUBKEY = 'SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Environment'
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A

    def _broadcast_change(self):
        ctypes.windll.user32.SendNotifyMessageW(
            self.HWND_BROADCAST, self.WM_SETTINGCHANGE, 0, ctypes.c_wchar_p('Environment'))

    def get_user_path_list(self):
        try:
            with winreg.OpenKey(self.ENV_REG_KEY, self.ENV_REG_SUBKEY) as key:
                value, _ = winreg.QueryValueEx(key, 'Path')
            return [p.strip() for p in str(value).split(';') if p.strip()]
        except FileNotFoundError:
            return []
        except OSError:
            return []

    def get_system_path_list(self):
        try:
            with winreg.OpenKey(self.SYS_REG_KEY, self.SYS_REG_SUBKEY) as key:
                value, _ = winreg.QueryValueEx(key, 'Path')
            return [p.strip() for p in str(value).split(';') if p.strip()]
        except FileNotFoundError:
            return []
        except OSError:
            return []

    def write_system(self, paths):
        try:
            payload = json.dumps({'paths': list(paths)}, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            return False, '要写的内容不对：%s' % e
        writer = Path(SYS_WRITER)
        if not writer.is_file():
            return False, '缺了提权写注册表的小工人：%s' % writer
        exe = _pyw()
        if not exe:
            return False, '找不到能跑提权脚本的 Python 解释器'
        tmp = DATA_DIR / 'tmp'
        try:
            tmp.mkdir(parents=True, exist_ok=True)
            tag = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            pf = tmp / ('syswrite_%s.json' % tag)
            rf = tmp / ('syswrite_%s.result.json' % tag)
            pf.write_text(payload, encoding='utf-8')
        except OSError as e:
            return False, '写临时文件失败：%s' % e
        try:
            code, why = run_elevated(exe, str(writer), [str(pf), str(rf)])
            if code is None:
                return False, why
            try:
                res = json.loads(rf.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                res = {}
            if res.get('ok'):
                self._broadcast_change()
                return True, (res.get('msg') or '已写入系统 PATH：%d 条' % len(paths)
                              ) + '（已经开着的程序不会变，新开的才看得到）'
            if res.get('msg'):
                return False, res['msg']
            return False, '提权进程退出了（%s）却没留下结果 —— 请点「刷新」看一眼现在是什么' % code
        finally:
            for f in (pf, rf):
                try:
                    f.unlink()
                except OSError:
                    pass

    def is_registered(self, path):
        want = os.path.normpath(path).lower()
        return any(os.path.normpath(p).lower() == want for p in self.get_user_path_list())

    def write(self, paths, success_msg):
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

PATHM = PathManager()
BACKUPM = BackupManager()

class Api:
    def state(self, params=None):
        paths = PATHM.get_user_path_list()
        sys_paths = PATHM.get_system_path_list()
        return {
            "ok": True,
            "count": len(paths),
            "paths": paths,
            "self_dir": SELF_DIR,
            "self_registered": PATHM.is_registered(SELF_DIR),
            "data_dir": str(DATA_DIR),
            "backup_dir": str(BACKUPM.backup_dir),
            "legacy_dir": str(BACKUPM.legacy_dir),
            "missing": [p for p in paths if dir_state(p) == 'missing'],
            "sys_paths": sys_paths,
            "sys_count": len(sys_paths),
            "sys_missing": [p for p in sys_paths if dir_state(p) == 'missing'],
            "sys_backup_dir": str(BACKUPM.sys_backup_dir),
        }

    def probe_path(self, params=None):
        raw = str((params or {}).get("path") or "").strip().strip('"')
        if not raw:
            return {"ok": False, "kind": "empty", "msg": "先给一个目录"}
        p = os.path.normpath(raw)
        if os.path.isdir(p):
            return {"ok": True, "kind": "dir", "path": p, "msg": "目录"}
        if os.path.isfile(p):
            d = os.path.dirname(p)
            return {"ok": True, "kind": "file", "path": d, "msg": "这是文件，加的是它所在的目录：%s" % d}
        return {"ok": False, "kind": "none", "path": p, "msg": "这个路径不存在：%s" % p}

    def scan(self, params=None):
        items = [str(p or "").strip() for p in ((params or {}).get("paths") or [])]
        items = [p for p in items if p]
        return {"ok": True, "missing": [p for p in items if dir_state(p) == 'missing']}

    def save(self, params=None):
        raw = list((params or {}).get("paths") or [])
        out = []
        for it in raw:
            p = str(it or "").strip().strip('"')
            if not p:
                continue
            out.append(os.path.normpath(p))
        ok, msg = PATHM.write(out, "已保存 %d 条到当前用户的 PATH（已广播）" % len(out))
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def sys_save(self, params=None):
        raw = list((params or {}).get("paths") or [])
        out = []
        for it in raw:
            p = str(it or "").strip().strip('"')
            if p:
                out.append(os.path.normpath(p))
        cur = PATHM.get_system_path_list()
        same = ([os.path.normpath(x).lower() for x in out] ==
                [os.path.normpath(x).lower() for x in cur])
        if same:
            return {"ok": False, "msg": "和现在一模一样，没动它", "state": self.state()}
        ok_b, before = BACKUPM.create_sys_backup(cur, "改动前")
        ok, msg = PATHM.write_system(out)
        if ok:
            ok_a, after = BACKUPM.create_sys_backup(out, "改动后")
            tail = "；备份：%s" % (Path(after).name if ok_a else "改动后那份没存上")
        else:
            tail = "；改动前那份还在：%s" % (Path(before).name if ok_b else "（改动前那份也没存上）")
        print('[path] 系统 PATH —— %s%s' % (msg, tail), flush=True)
        return {"ok": ok, "msg": msg + tail, "state": self.state()}

    def info(self, params=None):
        print('[path] 后端信息：pid=%d python=%s 数据目录=%s'
              % (os.getpid(), sys.version.split()[0], DATA_DIR), flush=True)
        return {"ok": True, "pid": os.getpid(), "python": sys.version.split()[0],
                "data_dir": str(DATA_DIR), "self_dir": SELF_DIR,
                "embedded": bool(os.environ.get('MOSS_UI_EMBED'))}

    def add(self, params=None):
        p = str((params or {}).get("path") or "").strip()
        if not p:
            return {"ok": False, "msg": "先给一个目录", "state": self.state()}
        ok, msg = PATHM.add(p)
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def add_many(self, params=None):
        raw = list((params or {}).get("paths") or [])
        cur = PATHM.get_user_path_list()
        seen = {os.path.normpath(p).lower() for p in cur}
        added, dup, bad = [], [], []
        for item in raw:
            p = str(item or "").strip().strip('"')
            if not p:
                continue
            if os.path.isfile(p):
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
        ok, msg = PATHM.write(cur + added, "加进 PATH %d 条：%s"
                                % (len(added), "；".join(added[:2]) + ("…" if len(added) > 2 else "")))
        if dup or bad:
            msg += "（跳过 %d 条重复 / %d 条不存在）" % (len(dup), len(bad))
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def remove(self, params=None):
        p = str((params or {}).get("path") or "").strip()
        ok, msg = PATHM.remove(p)
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def toggle_self(self, params=None):
        if PATHM.is_registered(SELF_DIR):
            ok, msg = PATHM.remove(SELF_DIR)
        else:
            ok, msg = PATHM.add(SELF_DIR)
        print('[path] %s' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def dedup(self, params=None):
        ok, msg = PATHM.dedup()
        return {"ok": ok, "msg": msg, "state": self.state()}

    def drop_missing(self, params=None):
        ok, msg = PATHM.drop_missing()
        return {"ok": ok, "msg": msg, "state": self.state()}

    def pick_dir(self, params=None):
        start = str((params or {}).get("start") or "").strip() or (PATHM.get_user_path_list() or [SELF_DIR])[0]
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
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            p = filedialog.askdirectory(title="选一个要加进 PATH 的文件夹", initialdir=start)
            root.destroy()
            if not p:
                return {"ok": False, "msg": "没有选（取消）"}
            return {"ok": True, "path": str(p)}
        except Exception as e:
            return {"ok": False, "msg": "挑文件夹失败：%s" % e}

    def backup_create(self, params=None):
        name = str((params or {}).get("name") or "")
        ok, msg, f = BACKUPM.create_backup(PATHM.get_user_path_list(), name)
        print('[path] %s' % msg, flush=True)
        return {"ok": ok, "msg": msg, "file": f, "state": self.state()}

    def backup_rename(self, params=None):
        p = params or {}
        ok, msg, f = BACKUPM.rename(str(p.get("file") or ""), str(p.get("name") or ""))
        print('[path] %s' % msg, flush=True)
        return {"ok": ok, "msg": msg, "file": f, "state": self.state()}

    def backup_list(self, params=None):
        return {"ok": True, "items": BACKUPM.list_backups(PATHM.get_user_path_list()),
                "state": self.state()}

    def backup_preview(self, params=None):
        f = str((params or {}).get("file") or "")
        paths = BACKUPM.read(f)
        if not paths:
            return {"ok": False, "msg": "这份备份读不出来（文件没了？）", "state": self.state()}
        add, gone = BACKUPM.diff(paths, PATHM.get_user_path_list())
        return {"ok": True, "add": add, "remove": gone, "paths": paths,
                "msg": "会加 %d 条、去掉 %d 条" % (len(add), len(gone)), "state": self.state()}

    def backup_restore(self, params=None):
        f = str((params or {}).get("file") or "")
        paths = BACKUPM.read(f)
        if not paths:
            return {"ok": False, "msg": "这份备份读不出来（文件没了？）", "state": self.state()}
        ok, msg = PATHM.write(paths, "已恢复成 %s 那份备份（%d 条）"
                                % (Path(f).stem.replace(BACKUPM.backup_prefix, ""), len(paths)))
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def backup_delete(self, params=None):
        ok, msg = BACKUPM.delete(str((params or {}).get("file") or ""))
        return {"ok": ok, "msg": msg, "state": self.state()}

class Embedded:
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
            except Exception as e:
                self.send({'id': mid, 'ok': False, 'error': '%s: %s' % (type(e).__name__, e)})
        return 0

def run_window():
    if not UI_FILE:
        print("[错误] 找不到界面文件 ui/index.html —— 打包时它得跟着一起发：\n"
              "       onedir：把 ui\\ 放在 exe 旁边；onefile：加 --include-data-dir=ui=ui\n"
              "       命令行不受影响：help / add / remove 照常能用", file=sys.stderr)
        return 2
    try:
        import webview
    except ImportError as e:
        print("[错误] 这个程序里没有 pywebview，界面开不了（%s）\n"
              "       两个办法：① 用 moss 跑它（`moss :path`）—— 自带运行时里 pywebview 是齐的；\n"
              "                 ② 自己打包时把它带上：--include-package=webview（还要 WebView2 运行时）\n"
              "       只跑命令行不受影响：help / add / remove" % e, file=sys.stderr)
        return 2

    api = Api()
    window = webview.create_window(TITLE, url=UI_FILE, js_api=api,
                                   width=980, height=700, min_size=(620, 460))

    def on_drop(event):
        try:
            files = (event.get("dataTransfer") or {}).get("files") or []
        except Exception:
            files = []
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
        except Exception:
            pass

    def arm_drop():
        try:
            from webview.dom import DOMEventHandler
            window.events.loaded.wait(20)
            window.dom.document.events.drop += DOMEventHandler(
                on_drop, prevent_default=True, stop_propagation=True)
            print('[path] 拖放监听已挂上（拖文件夹进来就能加）', flush=True)
        except Exception as e:
            print('[path] 拖放监听没挂上（不影响别的功能）：%r' % (e,), flush=True)

    threading.Thread(target=arm_drop, daemon=True).start()
    webview.start()
    return 0

def _split_args(s):
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
  moss :path list             把两级 PATH 都打出来（只读）
  moss :path help             这条帮助

  · 省略 [目录] 时用**这个包自己的目录**。
  · add / remove 只改当前用户（HKCU\\Environment\\Path），不需要管理员。
  · **系统级**（机器级，HKLM）的增删改在**界面**里做：保存时弹一次 UAC，
    提权只用于写那一个值，写完就退；改动前后各备份一份。
  · 改完广播一次系统消息 —— **已经开着的**终端不会变，新开的才看得到。
  · 备份：用户级在 data/backups/，系统级在 data/backups_system/。
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
                'list': ['list', 'ls', 'show'],
                'help': ['help', '?', '-h', '--help']}
    first = args[0].lower()
    if first in COMMANDS['help']:
        return 'help', None
    if first in COMMANDS['list']:
        return 'list', None
    for kind in ('add', 'remove'):
        for alias in COMMANDS[kind]:
            if first.startswith(alias + ' '):
                return kind, args[0][len(alias) + 1:].strip('"')
            if first == alias:
                return kind, (" ".join(args[1:]).strip('"') or None)
    if os.path.isdir(args[0].strip('"')):
        return 'add', args[0].strip('"')
    return first, " ".join(args[1:])

def print_paths():
    pm = PathManager()
    user = pm.get_user_path_list()
    sysl = pm.get_system_path_list()
    def dump(title, items):
        print("%s：%d 条" % (title, len(items)))
        gone = 0
        for i, p in enumerate(items, 1):
            st = dir_state(p)
            mark = '   ← 目录不存在' if st == 'missing' else ''
            gone += 1 if st == 'missing' else 0
            print("  %2d. %s%s" % (i, p, mark))
        return gone

    gone_user = dump("用户级 PATH（HKCU\\Environment，能改）", user)
    print("")
    gone_sys = dump("系统级 PATH（HKLM，机器级 —— 改它要管理员）", sysl)
    if gone_user or gone_sys:
        print("")
        print("· 盘上已经不存在的：用户级 %d 条、系统级 %d 条（界面里也能一键标出来）。"
              % (gone_user, gone_sys))
    print("")
    print("· 程序真正能搜到的是「用户级 + 系统级」拼起来的那条。")
    print("· 带 %VAR% 的按当前环境展开后再看盘上有没有；变量本身没定义的就不下结论。")
    return 0

def main():
    if str(os.environ.get('MOSS_UI_EMBED') or '').strip() in ('1', 'true', 'yes'):
        return Embedded().loop()
    command, path = parse_cli_args()
    if command is None:
        return run_window()
    if command == 'help':
        print_cli_help()
        return 0
    if command == 'list':
        return print_paths()
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
