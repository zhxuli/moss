# -*- coding: utf-8 -*-
"""备份：**内容寻址**（git 那套 object store）—— 给"开发时把数据存一份"用。
`V-89` 起**按分组（包 id）分文件夹**。

## 一句话

备份时**只记指纹**（路径 → 指纹 + 大小 + 时间），文件的**内容**按指纹单独存一份；
于是同一次备份里的重复文件、**同一组里跨备份**重复的文件，内容都只存一次。
删掉某次备份之后，扫一遍**这一组剩下的清单**，没人引用的对象才删。

## 落盘布局（`user_data/backups/`）

    <分组>/objects/<前2位>/<指纹>      这一组的内容；文件名就是内容指纹 ⇒ 幂等、可去重
    <分组>/objects/_tmp/…             正在写的临时块（写完 rename 过去；GC 时清）
    <分组>/<备份 id>/manifest.json     这一次备份的清单（**唯一的事实来源**）
    <分组> = 包 id（`bmi` / `md5`…）；不是包的来源用保留名 `@user` / `@dir-xxx` / `@abs-xxx`

**为什么按分组分文件夹**（`V-89`，你提的）：全平铺的时候"哪几次备份是哪个包的"只写在
清单里 —— 改个包 id 想"一起改"、删个包想"放心全删"都没有抓手。分好之后：
**改名 = 改一个文件夹名**（`rename_group`）、**删包 = 删一个文件夹**（`drop_group`），
一步到位、也不会误伤别的包。
★ 代价（如实说）：内容块也从"全局一份"变成"每组一份" ⇒ **跨包**不再去重
（同一份内容在两个组里各存一份）。组内去重照旧；跨包撞内容本来就少见，换"能一锅端"值。

## 为什么不做引用计数

计数器要"创建 +1 / 删除 -1"成对，中间任何一次中断都会让它永久漂移 —— 要么内容没了但
清单还在（备份成空壳），要么白占空间且再也降不下来。而"扫一遍**这一组**剩下的清单"
（标记-清除）**永远自愈**。这也跟项目里那条规矩一致：**磁盘是唯一真相**（`D-22`）。

## 写顺序

**先对象、后清单**（清单最后原子落盘）。任何时刻中断都不会留下
"清单指着一个还不存在的对象"这种半成品。

## 指纹

`blake2b-160`（40 个 hex 字符）。比 SHA-256 快一截，大文件时明显；算法名写在清单里
（`hash` 字段），以后想换 SHA-256 也认得出老清单。指纹是**内容**的，不是路径的 ——
同一个文件换个名字、挪个目录，指纹不变（去重照旧生效）。

## 这个模块不 import 界面那边的东西

`sources` 用**绝对路径**，清单里存**页面口径的 rel**（`user/pkgs/x/y`，见 `rel_of`）。
两个回调由调用方给（`system/ui/main.py` 给的是它自己那套根解析）：
`rel_of(abs) -> rel | None`、`resolve(rel) -> 绝对路径`。这样这一块能单独测。
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import shutil
import time
from pathlib import Path

SPEC = 1
HASH_NAME = "blake2b-160"
DIGEST_SIZE = 20                       # 160 位 = 40 个 hex 字符
CHUNK = 1024 * 1024

#: 默认不备份的东西（按**名字**匹配；目录名匹配上就整棵跳过）。
#: `__pycache__` / `*.pyc` 是纯垃圾；`.git` 一定要排除（不然一个仓库能备份出几十万个
#: 小对象，而且是我们自己那套"内容寻址"在备份 git 的"内容寻址"，纯浪费）。
DEFAULT_EXCLUDES = [".*", "__pycache__", "*.pyc", "*.pyo", ".git", ".venv", "venv",
                    "node_modules", ".DS_Store", "Thumbs.db", "*.tmp"]

#: 路径级排除：这些目录**整棵**不备份（相对页面 rel）。
#: `trash` 是回收站（`main.py` 的"删除 = 挪进 trash"），备份它没意义。
PATH_EXCLUDES = ["user/trash"]

#: 用户自己维护的过滤文件（和 `.gitignore` 一个用法）——放在 `user_data/` 下，
#: 存储根（`user_data/backups`）的上一级就是它，所以不用另配路径。
IGNORE_NAME = "snapshot.ignore"
#: 首次使用时自动落一份带注释的模板（照本项目"配置带注释"的老规矩）
IGNORE_TEMPLATE = r"""# moss 版本快照的过滤规则 —— 写法照 .gitignore 的常用那几条。
#
# ── 兼容（和 .gitignore 一个意思）────────────────────────────────
#   *.log            按"名字"排（任意层级的同名文件/目录都算）
#   build/           末尾带 / = 只排目录（连带里面的东西）
#   ?ache            单个字符通配（? = 一个非 / 字符）
#   **/deep.txt      任意层级下的 deep.txt（** 跨目录）
#   logs/**          某个目录下的**所有东西**（含子目录）
#   /user/state/tmp  开头带 / = 从 user_data 根锚定（只排这一个位置）
#   user/pkgs/old/   中间带 / 的按"相对 user_data 的路径"排
#   !keep.log        ! 开头 = 反向保留（前面被排掉的，这个要）
#   [0-9]*.tmp       方括号字符集（和 fnmatch 一样）
#   # 这一行是注释；空行忽略
#
# ── 不兼容（我们**没有**照 git 做，别指望）──────────────────────
#   · 子目录里各自的 .gitignore 继承 —— 我们只有 user_data/snapshot.ignore 这一个文件
#   · git 那条"被排掉的目录里面，再用 ! 也放不回来" —— 我们**允许**放回来（更宽松）
#   · 转义（\#、\!）—— 想排一个真的以 # 开头的名字，暂时没办法
#   · 大小写敏感 —— 我们**一律不区分大小写**（Windows 习惯）
#
# ★ 内置那几条永远生效，你只能"再加"，不能把它们放回来：
#   __pycache__ / *.pyc / *.pyo / .git / .venv / venv / node_modules /
#   .DS_Store / Thumbs.db / *.tmp / user/trash
"""



#: 常见过滤规则（`V-121`）：界面把它们列出来、**按目标目录自动匹配**，用户点选就写进规则框。
#: 每条 = 一个中文标签 + 一组 glob。`care` 是"这条要小心"的提示（点在界面上 hover 显示）。
PRESET_FILTERS = [
    {"id": "logs",     "label": "日志",          "pat": ["*.log"],
     "why": "跑起来才产生的日志，通常不用留版本"},
    {"id": "media",    "label": "视频 / 音频",    "pat": ["*.mp4", "*.mov", "*.avi", "*.mkv", "*.mp3", "*.wav"],
     "why": "又大又不常改 —— 快照会很占地方"},
    {"id": "design",   "label": "设计稿 / 大图",  "pat": ["*.psd", "*.ai", "*.sketch", "*.xcf"],
     "why": "源文件很大，通常另有备份"},
    {"id": "cache",    "label": "缓存 / 编译产物", "pat": ["__pycache__", "*.pyc", "*.pyo", "*.class", "*.o"],
     "why": "每次跑都会变，留了全是噪音（内置已经有了）"},
    {"id": "venv",     "label": "虚拟环境",       "pat": ["venv", ".venv", "env", "site-packages"],
     "why": "几千个文件、随时能重建（内置已有 venv / .venv）"},
    {"id": "deps",     "label": "依赖 / 构建",    "pat": ["node_modules", "dist", "build", "target", ".next"],
     "why": "能一键重装/重编，占地方"},
    {"id": "temp",     "label": "临时 / 备份文件", "pat": ["*.tmp", "*.bak", "*.old", "*~", "*.swp"],
     "why": "临时产物（内置已有 *.tmp）"},
    {"id": "archive",  "label": "压缩包",         "pat": ["*.zip", "*.7z", "*.rar", "*.tar.gz"],
     "why": "大且通常别处也有"},
    {"id": "db",       "label": "数据库文件",      "pat": ["*.db", "*.sqlite", "*.sqlite3", "*.mdb"],
     "why": "二进制、每次都变；要留就留导出脚本"},
    {"id": "dot",      "label": "点开头的隐藏项",  "pat": [".*"],
     "why": "含 .git / .env / .idea —— 勾了会连 .env 一起排掉（内置已经有 .*）"},
]


def glob_hit(name, pats):
    """这个名字命中这组 glob 吗（大小写不敏感，和过滤规则同一套）。"""
    for p in pats:
        if match_rules(name, [p], is_dir=True) or match_rules(name, [p]):
            return True
    return False

def parse_ignore(text):
    """把过滤文件读成一张规则表（保序，带 `!` 反向）。返回字符串列表。"""
    out = []
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        out.append(line)
    return out


def glob_to_re(pat):
    """把 gitignore 那套通配翻成正则（`*` 不跨 `/`、`?` 一个非 `/`、`**` 跨目录）。"""
    out, i, n = [], 0, len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            if pat[i:i + 3] == "**/":
                out.append("(?:.*/)?")          # `**/x` = 任意层级下的 x
                i += 3
                continue
            if pat[i:i + 2] == "**":
                out.append(".*")                # `**` = 跨目录的任意东西
                i += 2
                continue
            out.append("[^/]*")
        elif c == "?":
            out.append("[^/]")
        elif c == "[":
            k = pat.find("]", i + 1)
            if k < 0:
                out.append(re.escape(c))
            else:
                out.append(pat[i:k + 1])
                i = k + 1
                continue
        else:
            out.append(re.escape(c))
        i += 1
    return "".join(out)


def match_rules(name, rules, is_dir=False):
    """按顺序过一遍规则：命中就翻转，`!` 开头表示"取消排除"。返回**最终是否排除**。

    · 末尾带 `/` 的规则只在 `is_dir=True` 时算（"只排目录"）
    · 带 `/` 的规则不在这儿管（那是路径规则，见 `match_path`）"""
    hit = False
    for r in rules:
        neg = r.startswith("!")
        pat = r[1:] if neg else r
        if not pat:
            continue
        if pat.endswith("/"):
            if not is_dir:
                continue
            pat = pat.rstrip("/")
        if "/" in pat or not pat:
            continue                       # 路径规则：交给 match_path
        try:
            if re.fullmatch(glob_to_re(pat.lower()), str(name).lower()):
                hit = not neg
        except re.error:
            pass
    return hit


def match_path(rel, rules):
    """路径规则（带 `/` 的那些）。语义照 gitignore：

    · 开头带 `/`  ⇒ **从 user_data 根锚定**（`/user/state/tmp` 只排那一个位置）
    · 不带 `/` 的路径规则 ⇒ 也当成"根锚定"，但**同时**允许落在任意层级（对用户更宽容）
    · `**` 跨目录、`*` 不跨 `/`；末尾 `/` 只对目录生效
    · 命中一个"目录"就等于命中它下面的一切（走路时目录会被剪掉，天然如此）
    """
    rel = str(rel or "").replace("\\", "/").strip("/").lower()
    hit = False
    for r in rules:
        neg = r.startswith("!")
        pat = r[1:] if neg else r
        pat = pat.replace("\\", "/").strip()
        if not pat or "/" not in pat.strip("/"):
            continue                                  # 纯名字规则：交给 match_rules
        dir_only = pat.endswith("/")
        anchored = pat.startswith("/")
        pat = pat.strip("/")
        if not pat:
            continue
        cands = [glob_to_re(pat)]
        if not anchored:
            cands.append(glob_to_re("**/" + pat))     # 不带 / 的，也允许任意层级
        ok = False
        for rx in cands:
            try:
                if re.fullmatch(rx, rel):
                    ok = True
                    break
                if re.fullmatch(rx + "(?:/.*)?", rel):   # 命中目录 ⇒ 下面的一起算
                    ok = True
                    break
            except re.error:
                continue
        if ok and (not dir_only or "/" in rel or True):
            hit = not neg
    return hit
#: 备份库自己所在的位置（整棵排除，免得备份套娃）。
STORE_DIRNAME = "backups"
#: 内容块目录的名字（在**每个分组**下面各有一份）。
OBJECTS_DIRNAME = "objects"

#: 组名必须是**文件系统安全的目录名**：包 id 本来就是这个形状；
#: 不是包的那些来源用 `@` 开头的保留名（`@user` / `@dir-xxx` / `@abs-xxx`）。
GROUP_RE = re.compile(r"^[A-Za-z0-9_@][A-Za-z0-9_.@-]{0,63}$")


def safe_group(name, fallback="@misc"):
    """把随便什么字符串收拾成一个能当目录名的组名。"""
    n = re.sub(r"[^A-Za-z0-9_.@-]+", "-", str(name or "").strip()).strip("-.")
    n = n[:64]
    if not n or not GROUP_RE.match(n):
        n = fallback
    return n


def group_for_sources(sources):
    """按来源猜分组（调用方没明说时用）。

    规则就三条，好记：
      · 来源里有 `user/pkgs/<x>` / `system/pkgs/<x>` / `user/state/<x>` ⇒ 组名 = `<x>`（包 id）
      · 就是整个 `user` / `system` ⇒ `@user` / `@system`
      · 其它（某个目录 / 外部目录）⇒ `@dir-<最后一段>` / `@abs-<最后一段>`
    """
    srcs = [str(x or "") for x in (sources or [])]
    for s0 in srcs:
        parts = s0.replace("\\", "/").split("/")
        if len(parts) >= 3 and parts[1] in ("pkgs", "state"):
            return safe_group(parts[2])
    for s0 in srcs:
        if s0 in ("user", "system"):
            return "@" + s0
    if srcs:
        first = srcs[0].rstrip("/")
        tail = first.split("/")[-1] or "misc"
        pre = "@abs-" if first.startswith("abs/") else "@dir-"
        # ★ `V-118`（你点出来的）：组名只用**最后一段**时，同名目录会撞车 ——
        #   `D:\\a\\proj` 和 `D:\\b\\proj` 都是 `@abs-proj`；中文名更只剩哈希。
        #   后果：两个目录的快照混进同一个组（列表混、`--tag` 互相覆盖、diff 里出现别人的文件）。
        #   ⇒ 一律再补一段**按完整来源算**的 8 位哈希：可读的名字留着，唯一性靠哈希。
        #   （恢复本身仍然按清单里记的 `sources` 走，所以从来没写错过文件 —— 混的是"账"。）
        import hashlib
        h = hashlib.blake2b(first.lower().encode("utf-8"), digest_size=4).hexdigest()
        head = safe_group(pre.rstrip("-"))          # `@dir` / `@abs`
        nice = safe_group(tail)                     # 能留的字符（中文会被削成空）
        return (head + ("-" + nice if nice else "") + "-" + h)[:64]
    return "@misc"


def _now_text(t=None):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t or time.time()))


def new_id(now=None):
    """备份 id：`20260930-041233-a1b2`（按名字排序 = 时间顺序）。"""
    t = now or time.time()
    return time.strftime("%Y%m%d-%H%M%S", time.localtime(t)) + "-" + os.urandom(2).hex()


def hash_file(path, chunk=CHUNK):
    """算一个文件的指纹（顺带把大小读出来，省得再 stat 一次）。"""
    h = hashlib.blake2b(digest_size=DIGEST_SIZE)
    size = 0
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
            size += len(b)
    return h.hexdigest(), size


def hash_bytes(data):
    h = hashlib.blake2b(digest_size=DIGEST_SIZE)
    h.update(data)
    return h.hexdigest()


class BackupStore:
    """一个备份库 = 一个目录（`user_data/backups`），里面**按分组（包 id）分子文件夹**。"""

    def __init__(self, root, rel_of, resolve, excludes=None, trash=None, log=None):
        self.root = Path(root)
        self.rel_of = rel_of               # abs(Path) -> rel(str) | None
        self.resolve = resolve             # rel(str) -> Path（越界会抛 ValueError）
        self.excludes = list(DEFAULT_EXCLUDES if excludes is None else excludes)
        # ★ `V-103`：用户那份 `user_data/snapshot.ignore` 也并进来（内置的在前 ⇒ 内置永远生效）
        self.ignore_file = Path(root).parent / IGNORE_NAME
        if excludes is None:
            self.excludes += parse_ignore(self._read_ignore())
        # 「同步」模式下把"多出来的文件"挪去哪儿 —— 由调用方给（`main.py` 给的是它那套
        # 回收站 `user_data/trash/<时间戳>/…`）。不给就退回真删（只在测试里会这样）。
        self.trash = trash
        # 说明性日志（迁移老布局时写一句，`main.py` 给的是 `drop_log`）
        self.log = log
        self._migrating = False

    def _say(self, text):
        try:
            if self.log:
                self.log(text)
        except Exception:                                           # noqa: BLE001
            pass

    # ---------------------------------------------------------------- 目录（分组）
    def group_dir(self, group):
        g = safe_group(group)
        if not GROUP_RE.match(g):
            raise ValueError("分组名不合法：%r" % (group,))
        return self.root / g

    def objects(self, group):
        return self.group_dir(group) / OBJECTS_DIRNAME

    def tmp(self, group):
        return self.objects(group) / "_tmp"

    def ensure(self, group):
        self.tmp(group).mkdir(parents=True, exist_ok=True)

    def object_path(self, group, fp):
        return self.objects(group) / str(fp)[:2] / str(fp)

    def groups(self):
        """备份库里现在有哪些组（**按目录来**：有内容块目录、或者有备份，才算一组）。"""
        if not self.root.is_dir():
            return []
        out = []
        for d in sorted(self.root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            if d.name == OBJECTS_DIRNAME:          # 老布局那种"全局对象目录"，不算组
                continue
            # ★ 只认"真有备份"的组：删到最后一次备份之后，那个空壳文件夹不算一组
            #   （它会被 `_prune_group` 收掉；这里挡住"还没来得及收"的那种）。
            if self._ids_in(d):
                out.append(d.name)
        return out

    def _ids_in(self, gdir):
        """一个组里的备份 id（新的在前）。"""
        if not gdir.is_dir():
            return []
        return sorted((d.name for d in gdir.iterdir()
                       if d.is_dir() and (d / "manifest.json").is_file()), reverse=True)

    def ids(self, group=None):
        """备份 id 列表；`group=None` ⇒ 所有组（每组的排在一起）。"""
        if group is not None:
            return self._ids_in(self.group_dir(group))
        out = []
        for g in self.groups():
            out.extend(self._ids_in(self.root / g))
        return out

    def _find(self, bid):
        """按备份 id 找 `(分组, 目录)`；找不到回 `(None, None)`。"""
        bid = str(bid or "")
        if not bid or "/" in bid or "\\" in bid or bid.startswith("."):
            raise ValueError("备份 id 不合法：%r" % (bid,))
        for g in self.groups():
            d = self.root / g / bid
            if (d / "manifest.json").is_file():
                return g, d
        return None, None

    def _backup_dir(self, group, bid):
        return self.group_dir(group) / str(bid)

    # ---------------------------------------------------------------- 老布局迁移
    def ensure_layout(self):
        """老布局（全平铺 + 全局 `objects/`）→ 新布局（按分组）。

        `V-89` 之前的备份是 `backups/<id>/manifest.json` + `backups/objects/…`。
        这里把它们按来源归到各自的组里：清单目录整个挪过去，对象**按组各拷一份**
        （组内去重照旧，跨组的同一份内容会有多份 —— 这是分组换来的代价）。
        只在"真检测到老布局"时动手，而且每步都写日志（`user_data/state/_ui_drop.log`）。
        ★ 不能只跑一次就记住（第一版就这么写的）：老样子的清单**随时可能再冒出来**
          （从别处拷回来的旧备份、手工塞进去的），所以每次都扫一眼 —— 成本就是几次
          `iterdir`，换"永远不会剩一个谁也看不见的孤儿目录"。
        """
        if getattr(self, "_migrating", False):
            return {"migrated": 0, "skipped": True}
        self._migrating = True
        try:
            return self._migrate_legacy()
        finally:
            self._migrating = False

    def _migrate_legacy(self):
        if not self.root.is_dir():
            return {"migrated": 0}
        legacy_obj = self.root / OBJECTS_DIRNAME
        legacy_ids = self._ids_in(self.root)               # 老的：清单直接在 backups/ 下
        if not legacy_ids and not legacy_obj.is_dir():
            return {"migrated": 0}
        moved = 0
        for bid in legacy_ids:
            d = self.root / bid
            try:
                man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
            except Exception as e:                                  # noqa: BLE001
                # ★ 清单读不出来的**也别扔**：挪到 `@broken` 这个组里，界面上照样列出来
                #   （带"清单读不出来"的标记）—— 悄悄不见比报错更坏。
                dest = self.root / "@broken"
                dest.mkdir(parents=True, exist_ok=True)
                target = dest / bid
                if not target.exists():
                    shutil.move(str(d), str(target))
                self._say("备份库迁移：清单坏的 %s 挪到 @broken（%s）" % (bid, e))
                continue
            group = safe_group(man.get("group") or group_for_sources(man.get("sources")))
            dest = self.root / group
            dest.mkdir(parents=True, exist_ok=True)
            target = dest / bid
            if target.exists():
                shutil.rmtree(d, ignore_errors=True)                # 已经挪过了
                continue
            shutil.move(str(d), str(target))
            moved += 1
            self._say("备份库迁移：%s → %s/%s（按来源归组）" % (bid, group, bid))
            # 对象：把这次备份用到的指纹**搬**进这一组的 objects/
            # （搬，不是拷：清单已经跟着挪进组里了，老那份留着只会白占空间）
            for e in man.get("files") or []:
                fp = e.get("fp")
                if not fp:
                    continue
                src = legacy_obj / fp[:2] / fp
                if not src.is_file():
                    continue
                dst = self.object_path(group, fp)
                try:
                    if dst.is_file():
                        src.unlink(missing_ok=True)
                    else:
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(src), str(dst))
                except OSError as ex:                               # noqa: BLE001
                    self._say("备份库迁移：搬内容块 %s 失败（%s）" % (fp[:10], ex))
                else:
                    try:
                        src.parent.rmdir()                          # 桶空了就收掉
                    except OSError:
                        pass
        # 老的对象目录：这一轮之后没人再引用它那一份（各自组里都有了），收掉
        if legacy_obj.is_dir():
            left = [f for b in legacy_obj.iterdir() if b.is_dir() for f in b.iterdir()
                    if f.is_file()]
            if not left:
                shutil.rmtree(legacy_obj, ignore_errors=True)
            else:
                # 还有没用上的（比如某次备份的清单坏了）：留着，但记一句
                self._say("备份库迁移：老对象目录还剩 %d 个没人认领的内容块，先留着" % len(left))
        if moved:
            self._say("备份库迁移：共挪了 %d 次备份（按包 id 分组）" % moved)
        return {"migrated": moved}

    # ---------------------------------------------------------------- 排除
    def presets(self, sources, cap=20000):
        """`V-121`：把 `PRESET_FILTERS` 拿**这次要备份的目录**过一遍，数每条各命中多少。

        界面拿它做"点选式"的过滤设置：命中多的排前面、能点一下就写进规则框。
        只读、只数（走目录时**跳过内置与用户规则已经排掉的**，免得把已经排掉的东西再数一遍）。"""
        counts = {p["id"]: 0 for p in PRESET_FILTERS}
        samples = {p["id"]: [] for p in PRESET_FILTERS}
        seen = 0
        for src in (sources or []):
            # ★ `V-125`（真凶）：`presets()` 收的来源**可能是绝对路径、也可能是 rel**（页面 rel）
            #   —— 界面走 main.py 递的是绝对路径，CLI 递的是原始参数。以前一律 self.resolve(src)
            #   （当 rel 解）⇒ 绝对路径直接抛「不认识的根」被吃掉 ⇒ 一条都不数，
            #   界面上就永远显示没匹配到（而手动点那颗 chip 照样能加规则）。
            base = Path(str(src))
            if not base.exists():
                try:
                    base = self.resolve(src)
                except Exception:                                       # noqa: BLE001
                    continue
            if not base.is_dir():
                base = base.parent if base.is_file() else None
            if base is None:
                continue
            for cur, dirs, names in os.walk(base):
                cp = Path(cur)
                keep = []
                for d in sorted(dirs):
                    # ★ `V-124`（你实测出来的）：**先数再跳** —— 命中的目录哪怕已经被内置规则排掉，
                    #   也要让用户看见。以前是"先跳再数"，于是 `venv`（内置排除项）永远显示"没匹配到"，
                    #   那颗可点的 chip 就白给了（点一下照样能加规则，但用户根本不知道这儿有 venv）。
                    for pr in PRESET_FILTERS:
                        if glob_hit(d, pr["pat"]):
                            counts[pr["id"]] += 1
                            if len(samples[pr["id"]]) < 3:
                                samples[pr["id"]].append(self.rel_of(cp / d) or d)
                    if self._skip_dir_name(d, is_dir=True) or self._skip_rel(self.rel_of(cp / d) or ""):
                        continue
                    keep.append(d)
                dirs[:] = keep
                for n in sorted(names):
                    seen += 1
                    if seen > cap:
                        break
                    for pr in PRESET_FILTERS:
                        if glob_hit(n, pr["pat"]):
                            counts[pr["id"]] += 1
                            if len(samples[pr["id"]]) < 3:
                                samples[pr["id"]].append(self.rel_of(cp / n) or n)
                if seen > cap:
                    break
        out = []
        for pr in PRESET_FILTERS:
            it = dict(pr)
            it["hit"] = counts[pr["id"]]
            it["sample"] = samples[pr["id"]]
            out.append(it)
        out.sort(key=lambda x: (-x["hit"], x["id"]))
        return out

    def group_ignore_file(self, group):
        """这个对象自己那份过滤规则（`V-120`）：`user_data/backups/<组>/ignore`。

        ★ 为什么放这儿而不是项目里的 `.snapignore`：**不往你的项目目录里写文件**（目录可能只读、
          也可能你不想被工具塞东西），而且和"备份库都在 user_data"这条一致；粒度 = 这个包/目录。"""
        return self.group_dir(group) / "ignore"

    def group_ignore(self, group):
        try:
            f = self.group_ignore_file(group)
            return parse_ignore(f.read_text(encoding="utf-8", errors="replace")) if f.is_file() else []
        except Exception:                                               # noqa: BLE001
            return []

    def _read_ignore(self):
        """读 `user_data/snapshot.ignore`；**没有就落一份带注释的模板**（照 config.toml 的老规矩）。"""
        try:
            if not self.ignore_file.is_file():
                self.ignore_file.parent.mkdir(parents=True, exist_ok=True)
                self.ignore_file.write_text(IGNORE_TEMPLATE, encoding="utf-8")
                _lg = getattr(self, "log", None)          # ★ `V-107`：这时 self.log 还没赋值
                if _lg: _lg("快照过滤：生成了模板 %s" % self.ignore_file)
                return IGNORE_TEMPLATE
            return self.ignore_file.read_text(encoding="utf-8", errors="replace")
        except Exception as e:                                          # noqa: BLE001
            _lg = getattr(self, "log", None)
            if _lg: _lg("快照过滤：%s 读不出来（%s），这次只用内置那几条" % (self.ignore_file, e))
            return ""

    def _rules(self):
        """当前生效的规则：内置 + 用户那份（`self.excludes` 里已经并好了）。"""
        return list(self.excludes)

    def _skip_dir_name(self, name, is_dir=False):
        return match_rules(name, self._rules(), is_dir=is_dir)

    def _skip_rel(self, rel):
        if match_path(rel, self._rules()):
            return True
        for pre in PATH_EXCLUDES:
            if rel == pre or rel.startswith(pre + "/"):
                return True
        return False

    # ---------------------------------------------------------------- 新建
    def create(self, sources, title="", note="", excludes=None, group=None,
               by="", by_task=""):
        """备份一批目录/文件。

        `sources` 是**绝对路径**列表（目录会递归；单个文件也行）。
        `group` 不给就按来源猜（见 `group_for_sources`）。
        清单里存的是**页面 rel**（拿不到 rel 的路径会被跳过并记在 `skipped` 里）。
        """
        self.ensure_layout()
        srcs_rel = []
        for s in sources:
            try:
                r = self.rel_of(Path(s))
            except Exception:                                       # noqa: BLE001
                r = None
            if r:
                srcs_rel.append(r)
        g = safe_group(group) if group else group_for_sources(srcs_rel)
        self.ensure(g)
        # ★ `V-120`：生效的规则 = 内置 + 全局那份 + **这个对象自己那份** + 这次临时的。
        #   `excludes` 现在是**追加**语义（以前是"替换"，会把内置/全局丢掉 —— 界面要用追加）。
        ex = list(self.excludes) + self.group_ignore(g) + list(excludes or [])
        saved_ex = self.excludes
        self.excludes = ex
        try:
            return self._create(sources, title, note, g, by=by, by_task=by_task)
        finally:
            self.excludes = saved_ex

    def _create(self, sources, title, note, group, by="", by_task=""):
        bid = new_id()
        files = []
        empty_dirs = []
        skipped = []
        errors = []
        new_objects = 0
        new_bytes = 0
        seen = set()                       # 这一次备份里已经收过的 rel（去重 + 双保险）
        store_prefix = str(self.root.resolve())

        def walk_dir(base: Path, rel_base: str):
            for cur, dirs, names in os.walk(base):
                curp = Path(cur)
                keep = []
                for d in sorted(dirs):
                    if self._skip_dir_name(d, is_dir=True):
                        continue
                    sub_rel = (rel_base + "/" + d) if rel_base else d
                    if self._skip_rel(sub_rel):
                        continue
                    if str((curp / d).resolve()).startswith(store_prefix):
                        continue
                    keep.append(d)
                dirs[:] = keep
                if not names and not dirs:
                    r = self.rel_of(curp)
                    if r and r not in empty_dirs:
                        empty_dirs.append(r)
                for n in sorted(names):
                    if self._skip_dir_name(n):
                        continue
                    if self._skip_rel((rel_base + "/" + n) if rel_base else n):
                        continue
                    self._take(curp / n, group, files, seen, skipped, errors)

        for src in sources:
            p = Path(src)
            if p.is_dir():
                r = self.rel_of(p)
                walk_dir(p, r or "")
            elif p.is_file():
                self._take(p, group, files, seen, skipped, errors)
            else:
                skipped.append(str(p))

        for e in files:
            if e.pop("_new", False):
                new_objects += 1
                new_bytes += e["size"]

        total_bytes = sum(e["size"] for e in files)
        man = {
            "spec": SPEC,
            "id": bid,
            "group": group,
            "title": (title or "").strip() or ("备份 " + _now_text()),
            "note": (note or "").strip(),
            # ★ `V-236`：**这条快照是谁存的**。空串 = 人存的；"ai" = AI 工作台自动存的。
            #   为什么必须是清单里的**真字段**（而不是标题前缀）：你要能"一眼分辨 + 只清 AI 的"，
            #   而标题/注释是给你看的文案（能改、能留空），拿它当判据迟早失准。
            #   为什么不用 tag：`tags.json` 是 tag→id 的**映射**（一个 tag 只能指一条），
            #   AI 跑第二趟就把上一趟的标记顶掉了。
            "by": str(by or "").strip(),
            #: AI 那一次的**任务原文**（你说要的："这样我就知道是干啥之前的代码了"）
            "by_task": str(by_task or "").strip(),
            "created": time.time(),
            "created_text": _now_text(),
            "hash": HASH_NAME,
            "sources": [self.rel_of(Path(s)) or str(s) for s in sources],
            "exclude": list(self.excludes),
            "files": files,
            "empty_dirs": empty_dirs,
            "skipped": skipped[:200],
            "errors": errors[:200],
            "stats": {"files": len(files), "bytes": total_bytes,
                      "new_objects": new_objects, "new_bytes": new_bytes,
                      "empty_dirs": len(empty_dirs),
                      "skipped": len(skipped), "errors": len(errors)},
        }
        d = self._backup_dir(group, bid)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "manifest.json.tmp"
        tmp.write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, d / "manifest.json")        # ★ 原子：清单要么在、要么不在
        return man

    def _take(self, path: Path, group, files, seen, skipped, errors):
        """把一个文件收进这次备份：算指纹 → 本组里没有就把内容落盘 → 记一条。"""
        try:
            if path.is_symlink():
                skipped.append(str(path))
                return
            rel = self.rel_of(path)
            if not rel or rel in seen:
                skipped.append(str(path))
                return
            if self._skip_rel(rel):
                skipped.append(str(path))
                return
            fp, size = hash_file(path)
            seen.add(rel)
            files.append({"rel": rel, "fp": fp, "size": size,
                          "mtime": int(path.stat().st_mtime)})
            if not self.object_path(group, fp).is_file():
                self._put_object(group, path, fp)
                files[-1]["_new"] = True
        except OSError as e:
            errors.append("%s：%s" % (path, e))

    def _put_object(self, group, src: Path, fp):
        """把内容写进这一组的内容库。**写完再验一次指纹**：算完到复制之间文件被改过的
        话，直接用会把"内容 ≠ 文件名"这种坏对象写进去（那是最难查的一类问题）。"""
        for attempt in (1, 2):
            self.ensure(group)
            tmp = self.tmp(group) / ("%s.%d.%s" % (fp[:12], os.getpid(), os.urandom(3).hex()))
            shutil.copyfile(src, tmp)
            again = hash_file(tmp)[0]
            if again != fp:
                tmp.unlink(missing_ok=True)
                if attempt == 2:
                    raise OSError("这个文件在备份过程中一直在变（跳过）：%s" % src)
                fp, _ = hash_file(src)
                continue
            dest = self.object_path(group, fp)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.is_file():
                tmp.unlink(missing_ok=True)         # 别人先写好了，我这块多余
                return
            os.replace(tmp, dest)                   # ★ 原子：对象要么完整、要么没有
            return

    # 兼容老调用（有人在用 `_put_object(src, fp)` 这种两参写法的话）
    # —— 现在一律走分组版本，这里不再留旧签名。

    # ---------------------------------------------------------------- 读清单
    def manifest(self, bid, group=None):
        if group is not None:
            p = self._backup_dir(group, bid) / "manifest.json"
            if not p.is_file():
                raise ValueError("这个分组里没有这次备份：%s/%s" % (group, bid))
            return json.loads(p.read_text(encoding="utf-8"))
        g, d = self._find(bid)
        if not d:
            raise ValueError("没有这次备份：%s" % bid)
        return json.loads((d / "manifest.json").read_text(encoding="utf-8"))

    def _group_of(self, bid, group=None):
        if group:
            return safe_group(group)
        g, d = self._find(bid)
        if not d:
            raise ValueError("没有这次备份：%s" % bid)
        return g

    def list_backups(self, group=None):
        """每次备份一行（列表用）。清单坏了的那次**照样列出来**并标出来 —— 别悄悄不见。"""
        self.ensure_layout()
        out = []
        gs = [self.group_dir(group).name] if group else self.groups()
        for g in gs:
            for bid in self._ids_in(self.root / g):
                try:
                    m = self.manifest(bid, g)
                except Exception as e:                              # noqa: BLE001
                    out.append({"id": bid, "group": g, "broken": str(e),
                                "title": "(清单读不出来)", "files": 0, "bytes": 0,
                                "created_text": ""})
                    continue
                st = m.get("stats") or {}
                out.append({"id": bid, "group": m.get("group") or g,
                            "title": m.get("title") or bid, "note": m.get("note") or "",
                            # `V-236`：谁存的 + 那次的任务原文（界面靠这两样分辨 / 清理）
                            "by": m.get("by") or "", "by_task": m.get("by_task") or "",
                            "created": m.get("created"),
                            "created_text": m.get("created_text") or "",
                            "sources": m.get("sources") or [],
                            "files": st.get("files", len(m.get("files") or [])),
                            "bytes": st.get("bytes", 0),
                            "new_objects": st.get("new_objects", 0),
                            "new_bytes": st.get("new_bytes", 0),
                            "skipped": st.get("skipped", 0), "errors": st.get("errors", 0)})
        out.sort(key=lambda x: str(x.get("created") or ""), reverse=True)
        return out

    # ---------------------------------------------------------------- 看内容
    def _locate_object(self, fp, group=None):
        if group:
            p = self.object_path(group, fp)
            return p if p.is_file() else None
        for g in self.groups():
            p = self.object_path(g, fp)
            if p.is_file():
                return p
        return None

    def read_blob(self, fp, limit=200000, group=None):
        """读一个对象的内容（给"查看文件内容"用）。

        `group` 不给就在各组里找（同一个指纹可能落在多个组里，随便哪个都一样）。
        `limit` 之上的文本也不给全（界面只是个预览；要整份就恢复/导出出来看）。
        """
        fp = str(fp or "")
        if not fp or "/" in fp or "\\" in fp or ".." in fp:
            raise ValueError("指纹不合法")
        p = self._locate_object(fp, group)
        if not p:
            return {"ok": False, "msg": "对象缺失（可能被手工删了）：%s" % fp}
        size = p.stat().st_size
        raw = p.read_bytes()[:limit]
        try:
            text = raw.decode("utf-8")
            return {"ok": True, "binary": False, "size": size, "truncated": size > limit,
                    "text": text, "fp": fp}
        except UnicodeDecodeError:
            return {"ok": True, "binary": True, "size": size, "truncated": size > limit,
                    "fp": fp, "head": raw[:64].hex(" ")}

    # ---------------------------------------------------------------- 恢复
    def plan(self, bid, rels=None, only="all", sync=False, group=None):
        """先算一遍"恢复会发生什么"（不落盘）。

        `rels`：只处理清单里的这些 rel（None = 全部）。
        `only`：`all` = 都恢复；`missing` = 只补不存在的；`changed` = 只补不存在的
                或内容和备份里不一样的（**一样的直接跳过**，省事又不碰你的改动）。
        `sync`：**同步模式** —— 还会把"现在有、备份里没有"的文件列出来
                （`action="extra"`，恢复时**挪进回收站**，不真删）。只对"整次备份"生效：
                你手选了几个文件（`rels` 非空）时不谈同步（不然会把你没选的东西也删了）。
        """
        g = self._group_of(bid, group)
        m = self.manifest(bid, g)
        want = set(rels) if rels else None
        rows = []
        for e in m.get("files") or []:
            rel = e.get("rel")
            if want is not None and rel not in want:
                continue
            try:
                target = self.resolve(rel)
            except Exception as ex:                                 # noqa: BLE001
                rows.append({"rel": rel, "action": "error", "why": str(ex)})
                continue
            fp = e.get("fp")
            exists = target.exists()
            same = False
            if exists and target.is_file():
                try:
                    same = (hash_file(target)[0] == fp)
                except OSError:
                    same = False
            have_obj = self.object_path(g, fp).is_file()
            if not have_obj:
                action, why = "error", "对象缺失（备份库里的内容被删了）"
            elif not exists:
                action, why = "create", ""
            elif same:
                action, why = "same", "和备份里一模一样"
            else:
                action, why = "overwrite", "现在的内容和备份里不一样"
            if only == "missing" and action == "overwrite":
                action, why = "skip", "现在有（这次只补缺的）"
            if only == "changed" and action == "same":
                action, why = "skip", "已经一样"
            rows.append({"rel": rel, "action": action, "why": why, "fp": fp,
                         "size": e.get("size", 0)})
        if sync and want is None:
            rows.extend(self._extras(m))
        cnt = {}
        for r in rows:
            cnt[r["action"]] = cnt.get(r["action"], 0) + 1
        return {"ok": True, "id": bid, "group": g, "title": m.get("title") or bid,
                "rows": rows, "counts": cnt, "empty_dirs": m.get("empty_dirs") or [],
                "sources": m.get("sources") or []}

    def _extras(self, m):
        """现在有、备份里没有的文件（同步模式下要挪走的那批）。

        ★ 只扫**这次备份自己的来源目录**，而且**用备份时同一套排除规则** ——
          被排除的东西（`__pycache__`、`*.pyc`、`.git`、回收站、备份库自己）不算"多出来"，
          同步不会去动它们。
        """
        # ★ `V-120`：按**那次快照清单里记的 exclude** 走 —— 否则"按对象排掉的文件"
        #   会被当成"现在多出来的"，配 `--sync` 还会被挪进回收站。
        _saved_ex = self.excludes
        self.excludes = list(m.get("exclude") or self.excludes)
        known = set(e.get("rel") for e in (m.get("files") or []))
        out = []
        store_prefix = str(self.root.resolve())
        for src in (m.get("sources") or []):
            try:
                base = self.resolve(src)
            except Exception:                                       # noqa: BLE001
                continue
            if not base.is_dir():
                continue
            for cur_dir, dirs, names in os.walk(base):
                curp = Path(cur_dir)
                dirs[:] = [d for d in sorted(dirs)
                           if not self._skip_dir_name(d, is_dir=True)
                           and not str((curp / d).resolve()).startswith(store_prefix)]
                for n in sorted(names):
                    if self._skip_dir_name(n):
                        continue
                    if self._skip_rel(self.rel_of(curp / n) or ""):
                        continue
                    p = curp / n
                    if p.is_symlink():
                        continue
                    rel = self.rel_of(p)
                    if not rel or rel in known or self._skip_rel(rel):
                        continue
                    try:
                        size = p.stat().st_size
                    except OSError:
                        size = 0
                    out.append({"rel": rel, "action": "extra", "fp": "", "size": size,
                                "why": "现在多出来的（同步模式会挪进回收站）"})
        self.excludes = _saved_ex
        return out

    def restore(self, bid, rels=None, only="all", sync=False, group=None):
        """真恢复。**一步到位**：plan 里该做的都做（`error` 那些跳过并报出来）。

        `sync=True` 时，"多出来的"那些会被**挪进回收站**（`self.trash`；没给就真删）。
        """
        g = self._group_of(bid, group)
        plan = self.plan(bid, rels, only, sync=sync, group=g)
        m = self.manifest(bid, g)
        by_rel = {e["rel"]: e for e in (m.get("files") or [])}
        done, skipped, errors, trashed = [], [], [], []
        for r in plan["rows"]:
            if r["action"] in ("same", "skip"):
                skipped.append(r["rel"])
                continue
            if r["action"] == "error":
                errors.append("%s：%s" % (r["rel"], r.get("why") or ""))
                continue
            if r["action"] == "extra":
                try:
                    t = self.resolve(r["rel"])
                except Exception as ex:                             # noqa: BLE001
                    errors.append("%s：%s" % (r["rel"], ex))
                    continue
                try:
                    if self.trash:
                        self.trash(t)
                    else:
                        t.unlink()
                    trashed.append(r["rel"])
                except OSError as ex:
                    errors.append("%s：%s" % (r["rel"], ex))
                continue
            e = by_rel.get(r["rel"]) or {}
            src = self.object_path(g, e.get("fp") or "")
            try:
                target = self.resolve(r["rel"])
                target.parent.mkdir(parents=True, exist_ok=True)
                if r["action"] == "overwrite":
                    bak = target.with_name(target.name + ".bak")
                    try:
                        shutil.copyfile(target, bak)     # ★ 覆盖前留一份 .bak（睡得着）
                    except OSError:
                        pass
                shutil.copyfile(src, target)
                if e.get("mtime"):
                    try:
                        os.utime(target, (e["mtime"], e["mtime"]))
                    except OSError:
                        pass
                done.append(r["rel"])
            except OSError as ex:
                errors.append("%s：%s" % (r["rel"], ex))
        # 空目录也补回来（清单里记着）
        made_dirs = []
        for rel in plan.get("empty_dirs") or []:
            try:
                d = self.resolve(rel)
                if not d.exists():
                    d.mkdir(parents=True, exist_ok=True)
                    made_dirs.append(rel)
            except Exception:                                           # noqa: BLE001
                pass
        return {"ok": True, "id": bid, "group": g, "restored": done, "skipped": skipped,
                "errors": errors, "dirs": made_dirs, "trashed": trashed,
                "counts": {"restored": len(done), "skipped": len(skipped),
                           "errors": len(errors), "dirs": len(made_dirs),
                           "trashed": len(trashed)}}

    # ---------------------------------------------------------------- 导出到别的目录
    def _rel_in_backup(self, man, rel):
        """清单里的 rel → "这次备份内部的相对路径"（导出时用）。

        规则：找**最长**的那个来源前缀，把前缀切掉；要是这次备份有**多个来源**，
        再套一层"来源目录名/"（免得两个来源里的同名文件在导出目录里打架）。
        """
        srcs = [str(x) for x in (man.get("sources") or []) if x]
        hits = [s for s in srcs if rel == s or rel.startswith(s.rstrip("/") + "/")]
        if not hits:
            base = rel.split("/")[-1] or "file"
            return (srcs and len(srcs) > 1) and (base,) or base
        s = max(hits, key=len)
        tail = rel[len(s):].lstrip("/")
        if len(srcs) > 1:
            head = s.rstrip("/").split("/")[-1]
            return head + "/" + tail if tail else head
        return tail or rel.split("/")[-1]

    def export(self, bid, target, subpath="", rels=None, keep_bak=False, group=None):
        """把这次备份的内容**导出到别的目录**（原来那些文件一个都不动）。

        `target`：绝对路径（用户选的 / 拖进来的那个文件夹；不存在就建）。
        `subpath`：用户可以在后面接一段子路径（比如 `2` ⇒ 落到 `target/2/…`）。
        """
        g = self._group_of(bid, group)
        m = self.manifest(bid, g)
        want = set(rels) if rels else None
        base = Path(target).expanduser()
        sub = str(subpath or "").strip().strip("/\\").replace("\\", "/")
        if ".." in sub.split("/"):
            raise ValueError("子路径里不许有 `..`")
        if sub:
            base = base / sub
        written, bak, errors = [], [], []
        total = 0
        for e in m.get("files") or []:
            rel = e.get("rel")
            if want is not None and rel not in want:
                continue
            fp = e.get("fp")
            src = self.object_path(g, fp)
            if not src.is_file():
                errors.append("%s：备份库里的内容块缺失" % rel)
                continue
            dest = base / self._rel_in_backup(m, rel)
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if dest.exists() and keep_bak:
                    try:
                        shutil.copyfile(dest, str(dest) + ".bak")
                        bak.append(str(dest) + ".bak")
                    except OSError:
                        pass
                shutil.copyfile(src, dest)
                if e.get("mtime"):
                    try:
                        os.utime(dest, (e["mtime"], e["mtime"]))
                    except OSError:
                        pass
                written.append(str(dest))
                total += e.get("size", 0)
            except OSError as ex:
                errors.append("%s：%s" % (rel, ex))
        for rel in m.get("empty_dirs") or []:
            try:
                (base / self._rel_in_backup(m, rel)).mkdir(parents=True, exist_ok=True)
            except OSError:
                pass
        return {"ok": True, "id": bid, "group": g, "root": str(base), "written": written,
                "bytes": total, "bak": bak, "errors": errors,
                "counts": {"written": len(written), "errors": len(errors), "bak": len(bak)}}

    def export_plan(self, bid, target, subpath="", rels=None, group=None):
        """导出前先算一遍：会写出几个、其中几个会**盖掉**同名文件（给确认框用）。"""
        g = self._group_of(bid, group)
        m = self.manifest(bid, g)
        want = set(rels) if rels else None
        sub = str(subpath or "").strip().strip("/\\").replace("\\", "/")
        base = Path(target).expanduser()
        if sub:
            base = base / sub
        new_n = over_n = 0
        samples = []
        for e in m.get("files") or []:
            rel = e.get("rel")
            if want is not None and rel not in want:
                continue
            dest = base / self._rel_in_backup(m, rel)
            if dest.exists():
                over_n += 1
                if len(samples) < 3:
                    samples.append(str(dest))
            else:
                new_n += 1
        return {"ok": True, "root": str(base), "new": new_n, "overwrite": over_n,
                "files": new_n + over_n, "samples": samples,
                "bytes": sum(e.get("size", 0) for e in (m.get("files") or [])
                             if want is None or e.get("rel") in want)}

    # ---------------------------------------------------------------- 分组运维
    def rename_group(self, old, new):
        """把一个分组改名（**改包 id 的时候跟着改**）。

        目标组已经存在就**合过去**（内容块按指纹合并，重的只留一份）。
        """
        self.ensure_layout()
        o, n = safe_group(old), safe_group(new)
        if o == n:
            return {"ok": True, "renamed": 0, "msg": "名字没变"}
        src, dst = self.root / o, self.root / n
        if not src.is_dir():
            return {"ok": True, "renamed": 0, "msg": "没有这个分组（不用改）"}
        dst.mkdir(parents=True, exist_ok=True)
        moved = 0
        for bid in self._ids_in(src):
            target = dst / bid
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.move(str(src / bid), str(target))
            moved += 1
        # 内容块合过去（同指纹只留一份）
        src_obj = src / OBJECTS_DIRNAME
        if src_obj.is_dir():
            for bucket in src_obj.iterdir():
                if not bucket.is_dir() or bucket.name == "_tmp":
                    continue
                for f in bucket.iterdir():
                    if not f.is_file():
                        continue
                    d = self.object_path(n, f.name)
                    if not d.is_file():
                        d.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(f), str(d))
        shutil.rmtree(src, ignore_errors=True)
        # 清单里那个 group 字段也顺手改一下（不然界面上显示的还是旧组名）
        for bid in self._ids_in(dst):
            try:
                m = self.manifest(bid, n)
                if m.get("group") != n:
                    m["group"] = n
                    (dst / bid / "manifest.json").write_text(
                        json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")
            except Exception:                                       # noqa: BLE001
                pass
        self._say("备份库：分组改名 %s → %s（%d 次备份）" % (o, n, moved))
        return {"ok": True, "renamed": moved, "msg": "分组已改名：%s → %s" % (o, n)}

    def drop_group(self, group):
        """**整个分组删掉**（连它的内容块）—— 删包 / 清干净某一块数据时用。"""
        self.ensure_layout()
        g = safe_group(group)
        d = self.root / g
        if not d.is_dir():
            return {"ok": True, "removed": 0, "freed": 0, "msg": "没有这个分组"}
        backups = len(self._ids_in(d))
        size = 0
        for f in d.rglob("*"):
            if f.is_file():
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
        shutil.rmtree(d, ignore_errors=True)
        self._say("备份库：删掉整个分组 %s（%d 次备份、%s 字节）" % (g, backups, size))
        return {"ok": True, "removed": backups, "freed": size,
                "msg": "已删掉分组「%s」：%d 次备份、%s" % (g, backups, size)}

    # ---------------------------------------------------------------- 删 + 回收
    def delete_ai(self, bid=None, group=None):
        """**只删 AI 存的那条**（`V-236`）—— 那是"结构性"的闸，不是"提醒 AI 别删"。

        你要的规矩是「**AI 只能清它自己生成的，我的一律不许碰**」。靠提示词写"不要删用户的"
        是**劝**；这个函数是**拦**：它先看清单里的 `by` 字段，不是 `"ai"` 就**直接拒绝**，
        所以哪怕 AI 拿到这个工具、传了你的快照 id，也删不动。

        `bid` 不填 = 把这一组里**所有** `by == "ai"` 的都删掉（`group` 必填，免得手一抖清全库）。
        返回 `{ok, deleted:[…], skipped:[…], msg}`。
        """
        self.ensure_layout()
        if not bid and not group:
            return {"ok": False, "deleted": [], "skipped": [],
                    "msg": "不给 id 就必须给 group（不许「顺手清全库」）"}
        targets = []
        if bid:
            g = self._group_of(bid, group)
            m = self.manifest(bid, g)
            targets = [(bid, g, m)]
        else:
            g = safe_group(group)
            for one in self._ids_in(self.root / g):
                try:
                    targets.append((one, g, self.manifest(one, g)))
                except Exception:                                       # noqa: BLE001
                    continue
        deleted, skipped = [], []
        for one, g, m in targets:
            if str(m.get("by") or "") != "ai":
                skipped.append(one)          # ← 人存的：**碰都不碰**
                continue
            self.delete(one, g)
            deleted.append(one)
        if not deleted:
            return {"ok": True, "deleted": [], "skipped": skipped,
                    "msg": ("没有 AI 存的快照可清" + ("（跳过 %d 条你存的）" % len(skipped) if skipped else ""))}
        return {"ok": True, "deleted": deleted, "skipped": skipped,
                "msg": "清掉 %d 条 AI 存的快照%s"
                       % (len(deleted), ("（你存的 %d 条一条没动）" % len(skipped)) if skipped else "")}

    def delete(self, bid, group=None):
        """删掉一次备份，然后**在这一组里**标记-清除回收没人引用的对象。"""
        g = self._group_of(bid, group)
        d = self._backup_dir(g, bid)
        if not (d / "manifest.json").is_file():
            raise ValueError("没有这次备份：%s" % bid)
        shutil.rmtree(d)
        gc = self.gc(group=g)
        gc["pruned"] = self._prune_group(g)
        gc["deleted"] = bid
        gc["group"] = g
        return gc

    def _prune_group(self, group):
        """这一组要是已经**没有备份**了，就把整个文件夹收掉（空壳留着只会让人困惑）。"""
        d = self.root / safe_group(group)
        if not d.is_dir() or self._ids_in(d):
            return False
        shutil.rmtree(d, ignore_errors=True)
        return not d.exists()

    def gc(self, dry_run=False, group=None):
        """标记-清除：扫一遍**剩下的清单**，把没人引用的对象删掉。

        默认**只在指定的那一组里**扫（`group=None` ⇒ 所有组各扫各的）。
        顺手清 `objects/_tmp` 里的半成品（那是上次写到一半留下的）。
        """
        self.ensure_layout()
        gs = [safe_group(group)] if group else self.groups()
        removed, freed, kept, refs_all = [], 0, 0, 0
        for g in gs:
            refs = set()
            for bid in self._ids_in(self.root / g):
                try:
                    m = self.manifest(bid, g)
                except Exception:                                   # noqa: BLE001
                    continue
                for e in m.get("files") or []:
                    if e.get("fp"):
                        refs.add(e["fp"])
            refs_all += len(refs)
            objdir = self.objects(g)
            if objdir.is_dir():
                for bucket in sorted(objdir.iterdir()):
                    if bucket.name == "_tmp":
                        if not dry_run:
                            for f in bucket.iterdir():
                                try:
                                    f.unlink()
                                except OSError:
                                    pass
                        continue
                    if not bucket.is_dir():
                        continue
                    for f in sorted(bucket.iterdir()):
                        if not f.is_file():
                            continue
                        if f.name in refs:
                            kept += 1
                            continue
                        try:
                            sz = f.stat().st_size
                            if not dry_run:
                                f.unlink()
                            removed.append(g + "/" + f.name)
                            freed += sz
                        except OSError:
                            pass
                    if not dry_run:
                        try:
                            bucket.rmdir()                          # 空了就收掉
                        except OSError:
                            pass
        if not dry_run:
            for g in gs:
                self._prune_group(g)
        return {"ok": True, "dry_run": bool(dry_run), "removed": len(removed),
                "removed_fps": removed[:100], "freed": freed, "kept": kept,
                "referenced": refs_all}

    # ---------------------------------------------------------------- 统计 / 校验
    def stat(self, group=None):
        """汇总：几组、几次备份、多少个内容块、库占多大、**去重省了多少**。"""
        backups = self.list_backups(group)
        all_bytes = sum(b.get("bytes") or 0 for b in backups)
        all_files = sum(b.get("files") or 0 for b in backups)
        obj_bytes = obj_n = 0
        gs = [safe_group(group)] if group else self.groups()
        for g in gs:
            objdir = self.objects(g)
            if not objdir.is_dir():
                continue
            for bucket in objdir.iterdir():
                if not bucket.is_dir() or bucket.name == "_tmp":
                    continue
                for f in bucket.iterdir():
                    if f.is_file():
                        obj_n += 1
                        try:
                            obj_bytes += f.stat().st_size
                        except OSError:
                            pass
        return {"ok": True, "groups": len(self.groups()), "backups": len(backups),
                "files": all_files, "all_bytes": all_bytes, "objects": obj_n,
                "store_bytes": obj_bytes, "saved": max(0, all_bytes - obj_bytes),
                "root": str(self.root), "group": safe_group(group) if group else ""}

    def groups_summary(self):
        """每个分组一行（界面上那个"分组"下拉用）。"""
        self.ensure_layout()
        out = []
        for g in self.groups():
            st = self.stat(g)
            items = self.list_backups(g)
            out.append({"group": g, "backups": st["backups"], "files": st["files"],
                        "bytes": st["all_bytes"], "objects": st["objects"],
                        "store_bytes": st["store_bytes"], "saved": st["saved"],
                        "last": (items[0].get("created_text") if items else ""),
                        "last_title": (items[0].get("title") if items else "")})
        out.sort(key=lambda x: str(x.get("last") or ""), reverse=True)
        return out

    def check(self, bid=None, group=None):
        """校验：清单里提到的对象都还在吗。返回每次备份缺了几个。"""
        gs = [safe_group(group)] if group else self.groups()
        out = []
        for g in gs:
            ids = [bid] if bid else self._ids_in(self.root / g)
            for b in ids:
                try:
                    m = self.manifest(b, g)
                except Exception as e:                              # noqa: BLE001
                    out.append({"id": b, "group": g, "broken": str(e)})
                    continue
                miss = [e["rel"] for e in (m.get("files") or [])
                        if e.get("fp") and not self.object_path(g, e["fp"]).is_file()]
                out.append({"id": b, "group": g, "missing": len(miss),
                            "sample": miss[:10]})
        return {"ok": True, "rows": out}
