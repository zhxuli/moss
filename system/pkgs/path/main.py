# -*- coding: utf-8 -*-
"""PATH 管理 —— 一份界面代码（`ui/index.html`，Vue 3），两种跑法（照抄 `skill` 那个样板，`V-48`）：

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

#: 这个包自己的目录（"注册自身目录"那颗按钮用的就是它）。
#: ★ 打包成 exe 之后 `__file__` 指向**临时解包目录**（nuitka onefile 会把东西解到 %TEMP% 下的
#:   一次性目录），拿它算出来的路径既不稳、也不是用户看到的那个 —— 冻结之后一律用
#:   **exe 所在的目录**（`V-207`）。
if getattr(sys, 'frozen', False):
    SELF_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    SELF_DIR = os.path.dirname(os.path.abspath(__file__))


def _ui_file():
    """界面文件 `ui/index.html` 在哪（找不到返回空串）。

    ★ 打包之后它也**得跟着一起发**：onedir 放 exe 旁边、onefile 用
      `--include-data-dir=ui=ui` 打进包里（运行时在解包目录）—— 所以这里把两处都试一遍。
      两处都没有 ⇒ 调用方给一句人话，别开一扇空窗（那种最难查）。
    """
    for c in (Path(SELF_DIR) / 'ui' / 'index.html',
              Path(os.path.dirname(os.path.abspath(__file__))) / 'ui' / 'index.html'):
        if c.is_file():
            return str(c)
    return ""


UI_FILE = _ui_file()

#: 宿主注入的插件数据目录；独立运行时（直接 `python main.py` / 打包的 exe）按这个顺序退：
#: `PA_PLUGIN_DATA_DIR` → `MOSS_HOME/user_data/state/path` → **打包的 exe 就放在自己旁边**
#: → 最后才是家目录（并说一声数据放哪了，免得用户找不到备份）。
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
    # 直接 `python main.py` 调试：放家目录（界面上右下角会把实际路径显示出来，AGENT.md 也写了）
    return Path.home() / 'user_data' / 'state' / 'path'


DATA_DIR = _data_dir()

#: 备份放这儿（`V-200`：按契约用 `data/`——持久、要备份的东西放这里）
BACKUP_DIR = DATA_DIR / 'data' / 'backups'
#: 老位置：只读认，不再写
LEGACY_BACKUP_DIR = DATA_DIR / '.path_editor' / 'path_bak'

TITLE = 'PATH 管理'


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

    # ---- 名字（`V-209`）
    #: Windows 文件名里不许出现的字符（还有控制字符，见下面过滤）
    _BAD = set('\\/:*?"<>|')

    def clean_name(self, name, fallback=""):
        """把用户起的名字洗成**能当文件名**的样子（`V-209`）。

        ★ 只洗"文件系统不接受"的东西，**不动中文/空格/下划线/横线** —— 备份名是给人看的，
          "改注册表之前" 这种中文名就该原样留着。空 / 全被洗掉就退回 `fallback`。
        """
        s = "".join(ch for ch in str(name or "") if ch not in self._BAD and ord(ch) >= 32)
        s = s.strip().rstrip(".")                      # 结尾的空格和点在 Windows 上不收
        s = s.strip()
        return (s or fallback)[:60].strip()

    def _unique(self, folder, stem):
        """在 `folder` 里找一个没被占用的 `<stem>.txt`（重名就加 ` (2)`、` (3)`…）。"""
        f = folder / (stem + ".txt")
        n = 2
        while f.exists():
            f = folder / ("%s (%d).txt" % (stem, n))
            n += 1
        return f

    def _resolve(self, filepath):
        """只认自己那两个目录里的文件（别让界面通过这条路动别的文件）。"""
        p = Path(str(filepath or "")).resolve()
        for folder in (self.backup_dir, self.legacy_dir):
            try:
                if p.parent.resolve() == folder.resolve() and p.is_file():
                    return p
            except OSError:
                continue
        return None

    # ---- 写
    def create_backup(self, paths, name=""):
        """存一份备份。返回 (ok, 说明, 文件路径)。

        ★ 默认名字还是**时间戳**（`path_backup_20261003_012345.txt`）—— 自动、不会重名、
          也方便按时间排；`name` 给了就用**用户起的名字**（`V-209`：你说"可以修改名字"）。
        ★ 空 PATH 不备份（没有意义）。
        """
        if not paths:
            return False, "当前 PATH 是空的，没什么可备份", ""
        stamp = datetime.now().strftime(self.time_format)
        stem = self.clean_name(name, "") or ("%s%s" % (self.backup_prefix, stamp))
        try:
            self.backup_dir.mkdir(parents=True, exist_ok=True)     # 懒加载：真要写才建目录
            f = self._unique(self.backup_dir, stem)
            with open(f, 'w', encoding='utf-8') as fh:
                fh.write("\n".join(paths) + "\n")
            return True, "已备份 %d 条到 %s" % (len(paths), f.name), str(f)
        except OSError as e:
            return False, "备份失败：%s" % e, ""

    def rename(self, filepath, name):
        """给一份备份**改名**（同目录、同格式，只换文件名）。返回 (ok, 说明, 新路径)。"""
        p = self._resolve(filepath)
        if p is None:
            return False, "这个文件不在备份目录里，没动它", ""
        stem = self.clean_name(name, "")
        if not stem:
            return False, "名字不能是空的", ""
        if stem == p.stem:                             # 改回同一个名字：什么都不做（别变成 (2)）
            return True, "名字没变（还是 %s）" % p.name, str(p)
        target = self._unique(p.parent, stem)
        try:
            p.rename(target)
            return True, "已改名为：%s" % target.name, str(target)
        except OSError as e:
            return False, "改名失败：%s" % e, ""

    # ---- 读
    def read(self, filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as fh:
                return [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            return []

    def _scan(self, folder, legacy):
        """扫一个目录里的备份。

        ★ `V-209` 起**不再要求文件名里有时间戳**：以前是 `glob("path_backup_*.txt")` 再
          `strptime`，解析不出来就 `continue` —— 那样"用户起了名字"的备份会**在列表里凭空消失**
          （写了文件、界面看不见，最坏的一种 bug）。现在：一个目录里的 `.txt` 都算，
          时间取**文件的修改时间**，名字里能解析出时间戳的就当默认名、解析不出的当自定义名。
        """
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
                try:                                    # 老格式：名字里就是时间
                    when = datetime.strptime(stem[len(self.backup_prefix):], self.time_format)
                    custom = ""                         # 默认名 → 卡片上只显示时间
                except ValueError:
                    pass
            paths = self.read(str(f))
            out.append({"file": str(f), "name": custom, "time": when.strftime("%Y-%m-%d %H:%M:%S"),
                        "sort": when.strftime(self.time_format), "total": len(paths),
                        "paths": paths, "legacy": bool(legacy)})
        return out

    def list_backups(self, current_paths):
        """所有备份，新的在前。带上"与现在比会新增/移除几条"（恢复前先看清楚）。"""
        cur = {os.path.normpath(p).lower() for p in current_paths}
        out = self._scan(self.backup_dir, False) + self._scan(self.legacy_dir, True)
        for b in out:
            bset = {os.path.normpath(p).lower() for p in b["paths"]}
            b["add"] = len(bset - cur)
            b["remove"] = len(cur - bset)
        return sorted(out, key=lambda x: x["sort"], reverse=True)

    def diff(self, backup_paths, current_paths):
        """这份备份和现在比：会**新增**哪些、会**移除**哪些。"""
        bset = {os.path.normpath(p).lower() for p in backup_paths}
        cur = {os.path.normpath(p).lower() for p in current_paths}
        add = [p for p in backup_paths if os.path.normpath(p).lower() not in cur]
        gone = [p for p in current_paths if os.path.normpath(p).lower() not in bset]
        return add, gone

    def delete(self, filepath):
        """删一份备份。只认自己那两个目录里的（别让界面把任意文件删了）。"""
        p = self._resolve(filepath)
        if p is None:
            return False, "这个文件不在备份目录里，没动它"
        try:
            p.unlink()
            return True, "已删除备份：%s" % p.name
        except OSError as e:
            return False, "删除失败：%s" % e


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
#: 两个干活的对象**放在模块级**，`Api` 身上一个数据属性都不留。
#: ★ 为什么（`V-207`，真踩过）：pywebview 会把 `js_api` 实例的属性**挨个递归序列化**给 JS
#:   （`get_functions` 用 `dir(obj)` 往下走，只按类型挑，**不看下划线**）。我原来写成
#:   `self.pm = PathManager()`，里面全是 `pathlib.Path` —— 于是独立窗口一开就刷一屏
#:   `[pywebview] Error while processing bm.backup_dir._drv: 'WindowsPath' object has no attribute '_drv'`。
#:   把这俩挪走之后，`dir(Api())` 里只剩方法，桥那一侧干干净净。
PATHM = PathManager()
BACKUPM = BackupManager()


class Api:
    """界面里 `moss.call("名字", {...})` 就能调到下面这些方法。

    ★ 内嵌（stdio）和独立窗口（pywebview `js_api`）**共用同一份** —— 这就是
      "一份界面两种跑法"能成立的原因（照抄 skill）。
    ★ 约定：真要干活儿的方法返回 `{"ok": bool, "msg": "...", "state": {...}}` ——
      带上**改完之后**的完整状态，界面一次往返就能重画（不用再问一遍）。
    ★ **身上别挂数据**（尤其别挂 `Path` / 窗口 / 锁这类对象）：见上面 `PATHM` 那段注释。
    """


    # ---- 状态
    def state(self, params=None):
        """当前的完整状态。

        ★ `paths` 是**注册表里的原始顺序**（`V-211`）：界面**照这个顺序显示**（编号就是 PATH
          里的位次）、也照这个顺序**保存**回去 —— PATH 是有先后的（同名命令谁在前谁赢），
          界面绝不顺手按字母重排。上一版这里返回的是排好序的，界面又拿它当"要写回去的清单"，
          等于**一存就把用户的 PATH 重排了一遍**（改"先改后存"时才发现的）。
        """
        paths = PATHM.get_user_path_list()
        return {
            "ok": True,
            "count": len(paths),
            "paths": paths,
            "self_dir": SELF_DIR,
            "self_registered": PATHM.is_registered(SELF_DIR),
            "data_dir": str(DATA_DIR),
            "backup_dir": str(BACKUPM.backup_dir),
            "legacy_dir": str(BACKUPM.legacy_dir),
            "missing": [p for p in paths if '%' not in p and not os.path.isdir(p)],
        }

    def probe_path(self, params=None):
        """看一眼这个路径是什么（`V-211`）：界面那个「添加」按钮靠它决定怎么处理。

        空 / 不存在 / 是文件 / 是目录 —— 四种情况界面各有一套说法（是文件就加它所在的目录，
        不存在就报错且**不动输入框**）。只读，绝不写注册表。
        """
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

    def save(self, params=None):
        """把界面那份**清单**整串写回注册表（`V-211`：先改后存）。

        ★ 界面上的增删只是**改界面上的草稿**，攒够了一次性写、广播一次 —— 这比"每点一下就
          改一次系统环境变量"稳得多（也不会在拖 5 个目录时广播 5 次）。
        ★ 顺序**按界面给的来**（界面保留了注册表的原顺序，新加的排后面）。
        ★ **原样写**：这里只做"去掉空串 + `normpath`"，**不替用户去重、不排序**（探针逮到过）——
          注册表里本来就可能有一模一样的两条（大小写不同），界面也照样画两行；"保存"要是顺手
          给它去一条，就等于**用户没按过「去重」，数据却被改了**（而且界面显示的"改动处数"也
          对不上）。去重是界面那颗「去重」按钮的事，用户按了才做。
        """
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

    def info(self, params=None):
        """自证：这些数字是 Python 报的（`V-54` 那条"让后端证明它在干活"）。"""
        print('[path] 后端信息：pid=%d python=%s 数据目录=%s'
              % (os.getpid(), sys.version.split()[0], DATA_DIR), flush=True)
        return {"ok": True, "pid": os.getpid(), "python": sys.version.split()[0],
                "data_dir": str(DATA_DIR), "self_dir": SELF_DIR,
                "embedded": bool(os.environ.get('MOSS_UI_EMBED'))}

    # ---- 改 PATH
    #: ★ 这几个（`add` / `add_many` / `remove` / `dedup` / `drop_missing`）是**马上写注册表**的
    #:   老接口（`V-211` 之前界面就是这么点的）。现在**界面不再用它们**了 —— 界面走
    #:   `probe_path` 看路 + `save` 一次性写（先改后存，没保存的还高亮着）。留着是给脚本 /
    #:   命令行那种"就要立刻生效"的用法，语义仍然是"调用即写、即广播"。
    def add(self, params=None):
        p = str((params or {}).get("path") or "").strip()
        if not p:
            return {"ok": False, "msg": "先给一个目录", "state": self.state()}
        ok, msg = PATHM.add(p)
        print('[path] %s（Python 改的注册表）' % msg, flush=True)
        return {"ok": ok, "msg": msg, "state": self.state()}

    def add_many(self, params=None):
        """一次加好几条 —— 拖文件夹进来、或拖文件时取它所在的目录（`V-201`）。

        ★ **只写一次注册表、只广播一次**：拖 5 个目录进来不代表要改 5 遍环境变量。
        ★ 拖进来的是**文件** ⇒ 用**它所在的目录**（老 tkinter 界面就是这个规矩）。
        """
        raw = list((params or {}).get("paths") or [])
        cur = PATHM.get_user_path_list()
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
        """注册 / 反注册**这个包自己的目录**。"""
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
        """弹系统对话框挑一个文件夹。

        ★ 独立窗口：用 pywebview 的对话框（挂在我们自己那扇窗上）。
          内嵌：我们**没有自己的窗口**（窗口是 moss 的）⇒ 退回 tkinter 的 askdirectory。
          界面那边通常会先问 moss 主界面要（那边有正规的对话框），这条路是兜底。
        """
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
        """存一份备份。`name` 给了就用它当文件名，不给就用时间戳（`V-209`）。"""
        name = str((params or {}).get("name") or "")
        ok, msg, f = BACKUPM.create_backup(PATHM.get_user_path_list(), name)
        print('[path] %s' % msg, flush=True)
        return {"ok": ok, "msg": msg, "file": f, "state": self.state()}

    def backup_rename(self, params=None):
        """给一份备份改名（`V-209`）。只换文件名，内容一个字不动。"""
        p = params or {}
        ok, msg, f = BACKUPM.rename(str(p.get("file") or ""), str(p.get("name") or ""))
        print('[path] %s' % msg, flush=True)
        return {"ok": ok, "msg": msg, "file": f, "state": self.state()}

    def backup_list(self, params=None):
        return {"ok": True, "items": BACKUPM.list_backups(PATHM.get_user_path_list()),
                "state": self.state()}

    def backup_preview(self, params=None):
        """这份备份和**注册表里现在那份**比：会加什么、会去掉什么。

        ★ `V-214` 起**界面不走这条路了**：界面上的对比是拿它和**你正在编辑的那份清单**比的
          （存没存都算），而且是本地算的（一 hover 就能立刻展开，不用先问一趟）。这个方法留着
          给脚本 / 命令行那种"就想跟注册表比一比"的用法。
        """
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
    """自己开一扇窗（`moss :path`，或者直接 `python main.py` / 打包的 exe）。"""
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
