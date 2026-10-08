# -*- coding: utf-8 -*-
"""AI 的**权限（读 / 写）+ 临时空间**（`V-316`：把原来那套"三档模式 + 独立放行开关"合并掉）。

用户 2026-10-07 的原话（这一版就是照它重做的）：
  · 「比如我打开 github 这个插件 然后点 ai 那么 我就是要改它 所以这种情况下 放行这里
     理应就应该已经有它了 并且默认给他放手权限才对」
  · 「它这个放行列表 里面的列表 应该和我们这个权限设置是一体的才对 而不是一个单独的开关
     我们没有必要用2个开关来控制一件事情」
  · 「我们用 读 写 两个权限复选框来设置就可以了 这样我们的界面就更简洁
     我们就不需要那个单独的权限设置了」

于是**只有一个模型**：一份清单，每条 `{path, read, write}`。
  · **能不能读 / 能不能写，就看清单里那一行勾没勾**（外加几处"基础设施"永远可用，见下）；
  · **当前这个包**（`user_data/pkgs/<一个包>` 或 `system/pkgs/<一个包>`）**读写都默认开着**
    —— 它不是清单里的一条记录，是**算出来的默认**（`_scope_allows` / `_current_row`，`V-343`）；
    出厂包也一样（`V-347`：用户说了"去掉这个限制 让用户可以自己修改 自由 DIY"）；
  · 「只想咨询、别改我代码」= 把那一行的**写**取消勾选（一键，不需要另一个"模式"）；
  · 「放手」= 把 `*`（任意路径）那一行的**写**打开 —— 那时**危险操作也不再问你**
    （你都已经说"随便写"了，再拦就是多一个开关控同一件事）。

状态存在 `user_data/ai/mode.json`（换了内里的形状，但**文件名保留**，老文件会自动迁移）：

    {"allow": [{"path": "...", "read": true, "write": true, "why": "当前这个包",
                "by": "auto", "at": "..."},
               {"path": "*", "read": false, "write": false, "why": "任意路径（硬锁除外）",
                "by": "system"}],
     "seeded": ["github"]}       ← 已经自动加过清单的包 id（用户删了就不再自动加回来）

★ 硬锁（**永远是拒绝**，勾了 `*` 也拦）：`core/`、`moss.exe`、`moss.py`、`venv/`、`.git/`、
  `user_data/backups/`。前四个是"编进 exe / 构建链"，改了会让人以为改了源码（`K-10`）；
  `backups/` 是 AI 自己那条退路，不许它删自己的救生圈。
★ 永远可用的几处（不算权限，算"它的工具"）：它自己的临时空间（`state/<id>/ai/tmp`、
  `user_data/ai/tmp`）、它自己造的手（`user_data/state/skill/`）、契约（`system/spec`，
  而且**只能用 `spec` 工具读**）、样板包（`system/pkgs/`，照它抄）。
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent                      # system/ui/ai
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E                                        # noqa: E402

#: 清单里那一行"任意路径"（勾上写 = 放手；勾上读 = 哪儿都能看）
WILDCARD = "*"
WILDCARD_LABEL = "任意路径"          # `V-318`：界面上只写这四个字（"硬锁"不进界面）


# ------------------------------------------------------------------ 存取
def path():
    return E.user_data() / "ai" / "mode.json"


def _blank():
    return {"allow": []}


def _norm_perm(it):
    """把一条读成 `{path, read, write, why, by, at}`（**认老的 `on` 字段**，迁移用）。"""
    pth = str(it.get("path") or "").strip()
    if not pth:
        return None
    if "read" in it or "write" in it:
        rd, wr = bool(it.get("read", True)), bool(it.get("write", True))
    else:                                     # 老形状（`V-307`~`V-315`）：一个 `on` 管读写
        rd = wr = bool(it.get("on", True))
    return {"path": pth, "read": rd, "write": wr,
            # ★ `V-319`/`V-323`：`pending` = "AI 提出请求、用户还没点允许/拒绝" ——
            #   它只是**闸的登记本**，界面上**不画**（请求只在权限卡上半段那一条里问）
            "pending": bool(it.get("pending", False)),
            "why": str(it.get("why") or ""), "by": str(it.get("by") or "user"),
            "at": str(it.get("at") or "")}


def load():
    """读清单（没有 / 读坏了 ⇒ 出厂形状；**不抛**）。老形状自动迁移（见 `_norm_perm`）。"""
    cur = _blank()
    raw = {}
    try:
        p = path()
        if p.is_file():
            got = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(got, dict):
                raw = got
    except Exception:                                                    # noqa: BLE001
        raw = {}
    for it in (raw.get("allow") or []):
        if isinstance(it, dict):
            one = _norm_perm(it)
            # ★ `V-343`：`by="auto"` 那批是"打开 AI 页就把当前这个包写进清单"那个时代的产物 ——
            #   现在"当前这个包"改成**算出来的默认**（见 `_scope_allows`），这些行是纯垃圾：
            #   留着只会让清单越用越长（真机上攒了 6 个 `system/pkgs/*` 的出厂样板包）。
            if one and str(one.get("by") or "") != "auto":
                cur["allow"].append(one)
    # 老文件里那个 `mode`（`V-307`~`V-315` 的三档）→ **翻译成清单里的勾选**，别让它悄悄失效
    old_mode = str(raw.get("mode") or "")
    if old_mode and not raw.get("seeded"):
        if old_mode == "consult":
            for it in cur["allow"]:
                it["write"] = False
        elif old_mode == "free":
            for it in cur["allow"]:
                it["write"] = True
    return cur


def save(d):
    """原子写（先 `.tmp` 再 `os.replace`）—— 和窗口几何 / 排序一个路子。"""
    d = d if isinstance(d, dict) else _blank()
    out = {"allow": [x for x in (d.get("allow") or []) if isinstance(x, dict) and x.get("path")]}
    try:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, p)
        return dict(out, ok=True, path=str(p))
    except OSError as e:
        return dict(out, ok=False, msg="存不下来：%s" % e, path=str(path()))


def _wildcard_row():
    return {"path": WILDCARD, "read": False, "write": False, "why": WILDCARD_LABEL,
            "by": "system", "at": "", "pending": False}


def allow_list():
    """清单（保证含 `*` 那一行；顺序：非通配在前、`*` 在最后）。"""
    cur = load()
    rows = [it for it in cur["allow"] if it.get("path") != WILDCARD]
    star = next((it for it in cur["allow"] if it.get("path") == WILDCARD), None) or _wildcard_row()
    rows.append(star)
    return rows


def _find(rows, pth):
    key = _norm(pth)
    for it in rows:
        if _norm(it.get("path")) == key:
            return it
    return None


# ------------------------------------------------------------------ 改清单
def allow_set(pth, read=None, write=None, why="", by="user", add=True, pending=None,
              force=False):
    """加一条 / 改一条（`read` / `write` 给 `None` 就保持原样；`pending` 给 `None` 也保持原样）。

    ★ `path` 是 `*` 时就是那行"任意路径"（用来表达"放手"）。
    ★ `V-319`：`pending` = "AI 提出请求、还没被用户勾过" 的标记 —— 用户一动手（勾读/写、或者删掉）
      它就该清掉（调用点显式传 `pending=False`）。
    """
    raw = str(pth or "").strip().strip('"')
    if not raw:
        return {"ok": False, "msg": "路径是空的"}
    if raw != WILDCARD:
        bad = protected(Path(raw))
        if bad:
            return {"ok": False, "msg": bad}
    cur = load()
    rows = cur.get("allow") or []
    it = _find(rows, raw)
    if it is None:
        # ★ `*` 那一行是**永远存在**的（列表里总会显示它，只是文件里还没有）——
        #   所以"改它"（`add=False`）也不能当成"清单里没有这条"给拒了。
        if not add and raw != WILDCARD:
            return {"ok": False, "msg": "清单里没有这条"}
        # ★ `V-328`：**只有"新加一条"才挑路径**（乱打字 / 打错 / 不存在的目录挡在这儿）；
        #   已经在清单里的那一条只改勾 —— 老条目可能指向拔了的盘，不该连"关掉它"都不让。
        problem = path_problem(raw)
        if problem:
            return {"ok": False, "msg": problem, "bad_path": True}
        it = {"path": raw, "read": True, "write": True, "why": str(why or ""),
              "by": str(by or "user"), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "pending": bool(pending) if pending is not None else False}
        if raw == WILDCARD:
            it.update({"read": False, "write": False, "why": why or WILDCARD_LABEL,
                       "by": "system", "pending": False})
        rows.append(it)
    if read is not None:
        it["read"] = bool(read)
    if write is not None:
        it["write"] = bool(write)
    if pending is not None:
        it["pending"] = bool(pending)
    if force:
        # ★ `V-344`：**用户主动加进来的**（拖进来 / 手输 / 选目录）—— 归属和说明都按用户的来。
        #   不这么做的话，那条老的 `by="ai"` + `why="要求读这个目录的文件…"` 会**赖着不走**
        #   ⇒ 你拖进来的目录被写成"它请求的：…"，可 AI 压根没请求过它（你报的就是这个）。
        it["by"] = str(by or "user")
        it["why"] = str(why or "")
    else:
        if why:
            it["why"] = str(why)
        if by and it.get("by") in ("", "user"):
            it["by"] = str(by)
    cur["allow"] = rows
    got = save(cur)
    got["msg"] = "%s：读=%s 写=%s" % (it["path"], "开" if it.get("read") else "关",
                                     "开" if it.get("write") else "关")
    got["item"] = dict(it)
    return got


def allow_add(pth, read=True, write=True, why="", by="user", pending=None, force=False):
    return allow_set(pth, read=read, write=write, why=why, by=by, add=True,
                     pending=pending, force=force)


def _is_abs_path(raw):
    """像不像一个**绝对路径**（`D:\\x` / `D:/x` / UNC `\\\\主机\\共享`）——`*` 是唯一特例。"""
    try:
        return Path(str(raw)).is_absolute()
    except Exception:                                                # noqa: BLE001
        return False


def path_problem(pth, must_exist=True):
    """这个路径**能不能进清单**：`None` = 能；否则回一句**给人看的话**。

    ★ `V-328`（用户报的："目录权限这里 我可以随便打字 哪怕不是一个路径 就可以点添加"）：
      清单管的是**目录**，所以这里卡三道，每道都给一句人话（界面直接弹出来、它也能读懂）：
        ① 必须是**绝对路径**（`D:\\项目\\我的包` / UNC `\\\\主机\\共享`；`*` = 任意路径）；
        ② 必须**存在**（打错一个字母 / 拿猜的路径来问，都挡在这儿）；
        ③ 必须是**目录**（一个文件的路径放进"目录权限"里没有意义）。
    `must_exist=False` 只判形状（给"老清单里已经有的那一条"用 —— 那个盘可能拔了，
    但不能因此连"把它关掉"都不让改）。
    """
    raw = str(pth or "").strip().strip('"').strip()
    if not raw:
        return "先填一个目录（或者把文件夹拖到这一页）"
    if raw == WILDCARD:
        return None
    bad = protected(Path(raw))
    if bad:
        return bad
    if not _is_abs_path(raw):
        return ("要填**完整的绝对路径**（像 D:\\项目\\我的包 那样）——「%s」不是一个路径" % raw)
    if must_exist:
        p = Path(raw)
        if not p.exists():
            return "这个目录不存在：%s（先确认路径对不对）" % raw
        if not p.is_dir():
            return "这不是目录（这份清单管的是目录）：%s" % raw
    return None


def find(pth):
    """按路径找那一条（没有就回 `None`）—— 宿主等用户勾权限时**现读**它。"""
    return _find(load().get("allow") or [], pth)


def allow_pending_add(pth, why="", need="write"):
    """**AI 提出请求**：登记一条"待允许"（读/写都关着 + `pending=True`）给闸用（`find` 现读它）。

    ★ `V-323`（用户把界面设计重发了一遍）：**请求只在权限卡上半段那一条里问**（琥珀底 +
      允许 / 拒绝）。所以这条 `pending` **不再往清单里画**（界面上看不见它）—— 它的作用只剩
      "宿主和闸之间的登记本"：点「允许」= 把读写勾上（`ai_allow(..., action="add")`）⇒ 闸读到
      勾就放行、这条也正式进清单；点「拒绝」= 把这条删掉（`action="rm"`）⇒ 闸读到"没了"就判拒绝，
      清单里什么都不会多出来。
    ★ 用户已有的那条**不覆盖**（他自己勾过的权限说了算）。
    ★ `V-328`：路径先过 `path_problem()`（绝对路径 / 存在 / 是目录）—— 拿乱打的、不存在的
      路径来问用户，闸那边会返回 `bad-path`，工具会当场把它顶回去（别拿猜的路径去麻烦用户）。
    """
    raw = str(pth or "").strip().strip('"')
    problem = path_problem(raw)
    if problem:
        return {"ok": False, "msg": problem, "bad_path": True}
    it = find(raw)
    if it is not None:
        return {"ok": True, "msg": "清单里已经有这条了", "exists": True}
    return allow_add(raw, read=False, write=False,
                     why=str(why or ""), by="ai", pending=True)


def allow_rm(pth):
    cur = load()
    key = _norm(pth)
    rows = [it for it in (cur.get("allow") or []) if _norm(it.get("path")) != key]
    if len(rows) == len(cur.get("allow") or []):
        return {"ok": False, "msg": "清单里没有这条"}
    cur["allow"] = rows
    got = save(cur)
    got["msg"] = "从清单里删掉了（它现在读不了也写不了这里）"
    return got


# ------------------------------------------------------------------ 判权限
def _inside(path, root):
    try:
        p = os.path.realpath(str(path))
        r = os.path.realpath(str(root))
    except OSError:
        return False
    return p == r or p.startswith(r + os.sep)


def _norm(p):
    try:
        return os.path.normcase(os.path.realpath(str(p)))
    except OSError:
        return os.path.normcase(str(p))


def _hit(rows, path, kind):
    """清单里有没有一条**勾了 `kind`（read/write）**、且覆盖这个路径的行。"""
    for it in list(rows) + list(_TEMP):
        if not it.get(kind):
            continue
        pth = str(it.get("path") or "")
        if pth == WILDCARD or _inside(path, pth):
            return it
    return None


def pkg_roots():
    """包的**两个根**：用户包（`user_data/pkgs`）+ 出厂包（`system/pkgs`）。

    ★ `V-347`：出厂包从这一版起**也算"当前这个包"** —— 用户的原话是「无法阻止用户修改 system
      下面的包 我们应该去掉这个限制 让用户可以自己修改 自由 DIY 才能更有乐趣」，而这跟上一层
      早就定过的事是同一个立场：`D-24`（界面的文件管理里 `system/` **可编辑**、**只提示不拦截**）。
    """
    return (E.write_root(), E.HOME / "system" / "pkgs")


def is_factory(wd):
    """这个目录是不是**出厂包**（`system/pkgs/` 底下）—— 只用来提示，不用来拦。"""
    return _inside(wd, E.HOME / "system" / "pkgs")


def _is_pkg_scope(scope):
    """`scope` 是不是**某个具体的包**（`user_data/pkgs/<一个包>` 或 `system/pkgs/<一个包>`）。

    ★ `V-343`：只有这一种 scope 才享受"默认读写都开"。两道排除照旧：
      · 两个 `pkgs` 的**根**本身（`user_data/pkgs` / `system/pkgs`）—— 放开等于放开所有包；
      · 更外面的东西（`system/ui` 之类）不是包，不该跟着沾光。
    """
    sc = str(scope or "").strip()
    if not sc:
        return False
    try:
        s = os.path.realpath(sc)
    except OSError:
        return False
    for r in pkg_roots():
        try:
            root = os.path.realpath(str(r))
        except OSError:
            continue
        if not s.startswith(root + os.sep):
            continue
        rel = os.path.relpath(s, root).replace("\\", "/")
        parts = [x for x in rel.split("/") if x and x != "."]
        if parts:
            return True
    return False


def _scope_allows(path, scope, kind, rows=None):
    """**这次干活的那个包**：读 / 写默认都开 —— 但它**不是清单里的一条记录**（`V-343`）。

    ★ 为什么不再落盘（用户报的"清单越用越长"）：以前"AI 页在哪个包上打开过"就把它写进
      `allow`（`read=True, write=True`）⇒ **在左边点过一遍包列表，清单就长满了**，
      连出厂样板包都会被写进去；而且那是个**只读查询的副作用**，非常难查。
    ★ 现在的规矩：
      · scope 里默认全放行（`_is_pkg_scope` 认的那种包）；
      · **只有用户主动动过那一行的开关**，才会真的落一条显式记录 —— 那时以记录为准
        （他把「写」关掉 = "我只想咨询，别改我代码"）。
    """
    if not _is_pkg_scope(scope):
        return False
    if not _inside(path, scope):
        return False
    rows = allow_list() if rows is None else rows
    own = _find(rows, scope)
    if own is None:
        return True                      # 没被用户覆盖过 ⇒ 默认开
    return bool(own.get(kind))


def _current_row(workdir, rows=None):
    """界面上那条「当前这个包」：清单里没有显式记录时，给一条**算出来的**默认（读写都开）。

    ★ `V-347`：出厂包（`system/pkgs/<id>`）**也走这一条** —— 多带一个 `factory` 标记，
      界面拿它在那行后面补一句「· 出厂件」（**只提示不拦**：宿主升级时 `system/` 会被整体替换）。
      标记是**算出来的**，所以用户把「写」关掉之后落的那条显式记录也照样带着它。
    """
    wd = str(workdir or "").strip()
    if not _is_pkg_scope(wd):
        return None
    rows = allow_list() if rows is None else rows
    own = _find(rows, wd)
    if own is not None:
        row = dict(own, current=True)
    else:
        row = {"path": wd, "read": True, "write": True,
               "why": "当前这个包（默认：读写都开）", "by": "current",
               "at": "", "pending": False, "current": True}
    if is_factory(wd):
        row["factory"] = True
    return row


#: 「只允许这一次」的**临时**放行（用户点那个选项时用）—— 只活在这一次跑里，不写清单
#: （`begin_run()` 时清空）。为什么不落盘：用户说的就是"这一次"。
_TEMP = []


def allow_temp(pth, why="", read=True, write=True):
    raw = str(pth or "").strip()
    if not raw:
        return {"ok": False, "msg": "路径是空的"}
    if not any(_norm(x.get("path")) == _norm(raw) for x in _TEMP):
        _TEMP.append({"path": raw, "why": str(why or ""), "read": bool(read), "write": bool(write)})
    return {"ok": True, "msg": "这一次放行：%s" % raw}


def temp_list():
    return [dict(x) for x in _TEMP]


def clear_temp():
    _TEMP[:] = []


def is_ai_tmp(path):
    """这个路径是不是**AI 自己的临时空间**（含各插件那一份）。

    ★ 两处都认：`user_data/ai/tmp/**`（全局）和 `user_data/state/<任意id>/ai/tmp/**`（按插件）。
      读写守卫都靠它放行 —— 不然它会"把草稿写进自己的 tmp 却读不回来"（这一条踩过）。
    """
    p = Path(str(path or ""))
    if _inside(p, E.user_data() / "ai" / "tmp"):
        return True
    try:
        st = E.user_data() / "state"
        rel = p.resolve().relative_to(st.resolve())
    except (OSError, ValueError):
        return False
    parts = rel.parts
    return len(parts) >= 3 and parts[1] == "ai" and parts[2] == "tmp"


#: 硬锁（勾了"任意路径"也进不去）。判据在 `protected()` 里，这里只是给人看的说明。
PROTECTED_WHY = (
    ("core", "`core/**` 是**编进 moss.exe** 的（`K-10`）—— 改磁盘上的源码不重打包等于没改，"
             "而且要改它得由人来做。"),
    ("moss.exe", "`moss.exe` 是发行物本体，改写它 = 把程序砸了。"),
    ("moss.py", "`moss.py` 是 exe 的源码入口，改它要重新打包才生效（由人来做）。"),
    ("venv", "`venv/**` 是打包用的 Python 环境（构建链），不归 AI 动。"),
    (".git", "`.git/**` 是版本库，改它等于伪造历史。"),
)


def protected(path):
    """是不是**硬锁**路径（是就回一句给人看的原因，不是回 None）。"""
    p = Path(path)
    home = E.HOME
    if _inside(p, home / "core"):
        return "[拒绝] 受保护路径（硬锁）：" + PROTECTED_WHY[0][1]
    if _inside(p, home / "venv"):
        return "[拒绝] 受保护路径（硬锁）：" + PROTECTED_WHY[3][1]
    if _inside(p, home / ".git"):
        return "[拒绝] 受保护路径（硬锁）：" + PROTECTED_WHY[4][1]
    for f in ("moss.exe", "moss.py"):
        try:
            if os.path.realpath(str(p)) == os.path.realpath(str(home / f)):
                return "[拒绝] 受保护路径（硬锁）：改它要重新打包才生效（这件事由人来做）。"
        except OSError:
            pass
    if _inside(p, E.user_data() / "backups"):
        return ("[拒绝] `user_data/backups/**` 是**版本快照仓** —— 那是你（和 AI）的退路，"
                "不许由 AI 来写 / 删。要清快照请用界面「版本快照」那一页，或者 `snap_clean` 清 AI 自己存的。")
    return None


def readable_builtin(path):
    """几处**不算权限**的"基础设施"（它的工具 / 契约 / 样板）——能读就回 True。

    `system/spec` 那一处另有铁律：**只能用 `spec` 工具读**（整篇 read_file 会被拒，见
    `ai_edits.check_readable`）—— 所以这里放过，交给那一条去拦。
    """
    return (is_ai_tmp(path)
            or _inside(path, E.tool_root())
            or _inside(path, E.HOME / "system" / "spec")
            or _inside(path, E.HOME / "system" / "pkgs"))


def writable_builtin(path):
    """几处**不算权限**的可写（它自己的草稿纸 / 它自己造的手）。"""
    return is_ai_tmp(path) or _inside(path, E.tool_root())


def can_read(path, scope=None):
    """能读就回 None，不能读就回一句**给人看的原因**。

    `scope` = **这次干活的那个包**（`V-343`：它在 scope 里默认就能读，不需要清单里有一条）。
    """
    if path is None:
        return None
    if readable_builtin(path):
        return None
    rows = allow_list()
    if _hit(rows, path, "read"):
        return None
    if _scope_allows(path, scope, "read", rows):
        return None
    return ("[拒绝] 读权限没开：`%s` 不在 AI 能读的清单里。\n"
            "两条路：① 用 `allow_path` 工具**请求**（`need=\"read\"`）—— 那条请求会出现在"
            "权限卡上半段，他点「允许」这个目录就进清单了；② 让他在 AI 页那份"
            "「目录权限控制」清单里把它加进来、勾上「读」。"
            % path)


def can_write(path, scope=None):
    """能写就回 None，不能写就回一句**给人看的原因**。

    `scope` = **这次干活的那个包**（`V-343`：它在 scope 里默认就能写；用户把那一行的「写」
    关掉之后，以清单里那条显式记录为准）。
    """
    if path is None:
        return None
    bad = protected(Path(path))
    if bad:
        return bad
    if writable_builtin(path):
        return None
    rows = allow_list()
    if _hit(rows, path, "write"):
        return None
    if _scope_allows(path, scope, "write", rows):
        return None
    return ("[拒绝] 写权限没开：`%s` 不在清单里（或者那一行的**写**没勾）。\n"
            "两条路：① 用 `allow_path` 工具**请求**（`need=\"write\"`）—— 那条请求会出现在"
            "权限卡上半段，他点「允许」这个目录就进清单了；② 让他在那份「目录权限控制」清单里"
            "把它加进来、勾上「写」。\n"
            "（他如果只是**问事**、不想让它动代码，那就是故意把「写」关着的 —— 别硬来，"
            "把需要改的地方说清楚、用 `answer` 收尾。）" % path)


def wildcard_write():
    """`*` 那一行勾了**写**没有（= 用户说了"放手"）。"""
    it = _find(allow_list(), WILDCARD)
    return bool(it and it.get("write"))


def writable_roots():
    """现在**能写**的地方（给提示词 / 界面显示用）：`[路径, ...]`。"""
    return [it["path"] for it in allow_list() if it.get("write")]


def readable_extra():
    """清单里勾了读的那些路径（`ai_edits.read_roots()` 用它）。"""
    return [Path(it["path"]) for it in allow_list()
            if it.get("read") and it.get("path") != WILDCARD and it.get("path")]


# ------------------------------------------------------------------ 危险操作
#: `run_moss` 里出现这些词 = "这条命令会动盘 / 动系统"（要问一声）
DANGER_WORDS = (
    "--remove", "--rename", "--new", "--snap", "--alias", "--pip",
    " remove", " rm ", " rm", "rm ", " del ", "delete", " rmdir", " format",
    " kill", " taskkill", " stop-process", ">", ">>", "|", "&&", "||",
    "pip install", "--ai-profile", "reg ", "regedit", "shutdown",
)


def danger_of(tool, args):
    """这一步是不是"危险操作"（是就回一句**为什么危险**，不是回 None）。

    ★ 判据故意"宁可多问一句"：这是给"改坏了不好收"那种动作留的一道闸。
    ★ 勾了 `*` 的**写**（= 放手）时**不再问**（`needs_confirm`）—— 你都已经说随便写了，
      再拦一次就是"两个开关控同一件事"（用户 2026-10-07 明确不要这个）。
    """
    name = str(tool or "")
    a = args or {}
    if name == "run_moss":
        line = (" " + str(a.get("args") or "").lower() + " ")
        for w in DANGER_WORDS:
            if w in line:
                return "这条命令看起来会**动盘 / 动系统**：`moss %s`（命中「%s」）" % (
                    str(a.get("args") or "")[:60], w.strip())
        return None
    if name == "write_file" and a.get("overwrite"):
        return "**整篇覆盖**一个已经存在的文件（改几行的话 `edit_file` 更安全）"
    if name == "snap_clean":
        return "清掉你自己存的版本快照（回退用的退路）"
    return None


def needs_confirm(danger):
    """这个危险操作要不要**问用户**（`danger` 是 `danger_of()` 的理由）。"""
    return bool(danger) and not wildcard_write()


# ------------------------------------------------------------------ 临时空间
#: 保留最近多少个 run 的临时目录（更老的自动删）
TMP_KEEP = 10


def _pkg_id(workdir):
    """这次干活的地方是哪个包（不针对包就回 `""`）—— 惰性 import，防环。"""
    try:
        import ai_runs as R                                          # noqa: PLC0415
        return R.pkg_of(workdir)
    except Exception:                                                # noqa: BLE001
        return ""


def tmp_root(workdir=""):
    """AI 干活的临时空间。**跟着插件走**（`V-314`）：

        包里的活   ⇒ `user_data/state/<包id>/ai/tmp/<这次跑的 id>/`
        不针对某个包 ⇒ `user_data/ai/tmp/<这次跑的 id>/`（全局桶）

    ★ 会话、tmp、包数据全都住 `state/<包id>/ai/` 底下 ⇒ `moss --rename`（整目录搬
      `state/<旧id>`）一处动作，几样一起走，不会留下孤儿。
    """
    pid = _pkg_id(workdir)
    if pid:
        return E.user_data() / "state" / pid / "ai" / "tmp"
    return E.user_data() / "ai" / "tmp"


def tmp_for(run_id, workdir=""):
    rid = str(run_id or "").strip() or ("run-%d" % int(time.time()))
    safe = "".join(ch for ch in rid if ch.isalnum() or ch in "-_")[:64] or "run"
    return tmp_root(workdir) / safe


def ensure_tmp(run_id, workdir=""):
    """建好这次跑的临时目录并回它的路径（建不上就回 None —— 不因此挡住干活）。"""
    try:
        d = tmp_for(run_id, workdir)
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        return None


def prune_tmp(keep=TMP_KEEP, workdir=""):
    """只留最近 `keep` 个（按名字排），更老的删掉。回 `{ok, removed, kept}`。

    ★ 按**这个包自己的 tmp 目录**清 —— 别去动别的插件的临时文件（`V-314`）。
    """
    root = tmp_root(workdir)
    if not root.is_dir():
        return {"ok": True, "removed": [], "kept": []}
    try:
        dirs = [d for d in root.iterdir() if d.is_dir()]
    except OSError:
        return {"ok": False, "removed": [], "kept": [], "msg": "读不了临时目录"}
    dirs.sort(key=lambda d: d.name, reverse=True)
    keep_dirs = dirs[:max(1, int(keep or 1))]
    removed = []
    for d in dirs[max(1, int(keep or 1)):]:
        try:
            shutil.rmtree(d, ignore_errors=True)
            removed.append(d.name)
        except OSError:
            pass
    return {"ok": True, "removed": removed, "kept": [d.name for d in keep_dirs]}


def tmp_clean(run_id="", workdir=""):
    """清空：给了 `run_id` 只清那一格，否则把这个**桶**（这个插件的 tmp）清掉。"""
    root = tmp_root(workdir)
    try:
        if run_id:
            d = tmp_for(run_id, workdir)
            if d.is_dir():
                shutil.rmtree(d, ignore_errors=True)
                return {"ok": True, "msg": "清掉了这次跑的临时目录：%s" % d.name}
            return {"ok": True, "msg": "这次跑的临时目录本来就没有"}
        n = 0
        if root.is_dir():
            for d in root.iterdir():
                try:
                    if d.is_dir():
                        shutil.rmtree(d, ignore_errors=True)
                    else:
                        d.unlink(missing_ok=True)
                    n += 1
                except OSError:
                    pass
        return {"ok": True, "msg": "清掉了 %d 项" % n}
    except OSError as e:
        return {"ok": False, "msg": "清不掉：%s" % e}


def tmp_size(workdir=""):
    """临时空间现在多大（字节 + 文件数）—— 界面上那一行显示它。"""
    root = tmp_root(workdir)
    total, n = 0, 0
    if root.is_dir():
        for d in root.rglob("*"):
            try:
                if d.is_file():
                    total += d.stat().st_size
                    n += 1
            except OSError:
                pass
    return {"path": str(root), "bytes": total, "files": n}


def human_size(n):
    try:
        v = float(n or 0)
    except (TypeError, ValueError):
        return "0 B"
    for unit, div in (("GB", 1073741824.0), ("MB", 1048576.0), ("KB", 1024.0)):
        if v >= div:
            return "%.1f %s" % (v / div, unit)
    return "%.0f B" % v


def child_env(base=None, run_id="", workdir=""):
    """给 AI 起的子进程一套环境：`TMP`/`TEMP`/`MOSS_AI_TMP` 全指到这次的临时目录。"""
    env = dict(base or os.environ)
    rid = str(run_id or env.get("MOSS_AI_RUN_ID") or "")
    wd = str(workdir or env.get("MOSS_AI_WORKDIR") or "")
    d = ensure_tmp(rid, wd)
    if d:
        env["TMP"] = str(d)
        env["TEMP"] = str(d)
        env["MOSS_AI_TMP"] = str(d)
    return env


def begin_run(workdir=""):
    """开一次跑之前调一下：清掉上一跑的"只允许这一次" + 收拾这个桶里旧的临时目录。"""
    clear_temp()
    return prune_tmp(workdir=workdir)


def perm_note(workdir=""):
    """给**模型**看的一段"你现在能读哪儿 / 能写哪儿"（`ai_loop.env_note` 用它）。

    ★ 为什么要写清：权限现在是**用户勾出来的清单**，它自己看不见那个界面 ——
      不告诉它，它就会在"写不了的地方"白撞几次（真机上那就是白烧 token）。
    ★ `V-343`：**当前这次干活的包**是"算出来的默认"（不在清单里）—— 必须单独说一句，
      不然它会以为"清单里没有 ⇒ 不能写"，白撞一轮。
    """
    rows = allow_list()
    wd = str(workdir or "").strip()
    cur = _current_row(workdir, rows)
    cur_write = bool(cur and cur.get("write"))
    wr = [it["path"] for it in rows
          if it.get("write") and it.get("path") != WILDCARD and it.get("path") != wd]
    rd = [it["path"] for it in rows
          if it.get("read") and it.get("path") != WILDCARD and it.get("path") != wd]
    star_w = wildcard_write()
    out = []
    if cur is not None and cur_write:
        out.append("★ **这次干活的那个包** = `%s`：**默认就能读、能写**，不用申请"
                   "（用户随时可以在界面上把它的「写」关掉）。" % wd)
    elif cur is not None:
        out.append("★ **这次干活的那个包** = `%s`：用户把它的「写」**关掉了** —— "
                   "这一轮你只能读它，别改。" % wd)
    if star_w:
        out.append("🔓 **放手**：除硬锁路径外**哪儿都能写**（危险操作也不再问你）。"
                   "越是这样越要自己兜住：改之前想清楚，改完跑一遍。")
    elif wr:
        out.append("清单里另外勾了「写」的：%s" % "；".join("`%s`" % p for p in wr))
    elif not cur_write:
        out.append("**一个地方都不能写**（用户把「写」全关着）—— 这是**只读**的一轮："
                   "读必要的、答他问的，用 `answer` 收尾，别试着改文件。")

    if not star_w:
        out.append("要动**清单外**的目录：用 `allow_path` **请求**（`need` 说清只读还是要写）—— "
                   "那条请求会出现在**权限卡上半段**（琥珀底那条），他点「允许」就进清单了"
                   "（他点「拒绝」或一直不理就别硬来）。"
                   "★ 别拿「只是想看看」去申请：当前那个包和 `system/pkgs/` 样板本来就看得见。")
    if rd:
        out.append("清单里另外勾了「读」的：%s" % "；".join("`%s`" % p for p in rd))
    out.append("你自己那几处永远可用：临时空间（`MOSS_AI_TMP`）、你自己造的手"
               "（`user_data/state/skill/`）、契约（只能用 `spec` 工具读）、样板包（`system/pkgs/`）。")
    return "\n".join(out)



def summary(workdir=""):
    """给界面用的一份状态（`ai_info` 会把它摊进返回值）。

    ★ `V-343`：**当前这个包**不再靠"写进清单"体现，而是**算出来的第一条**
      （`_current_row`）—— 所以它不会污染 `mode.json`，清单也不会随"点过哪些包"变长。
    """
    rows = allow_list()
    star = rows[-1] if rows and str(rows[-1].get("path")) == WILDCARD else None
    body = rows[:-1] if star else rows
    cur = _current_row(workdir, rows)
    out = ([cur] if cur else []) + \
          [it for it in body
           if not (cur and _norm(it.get("path")) == _norm(cur.get("path")))]
    if star:
        out.append(star)
    return {"ok": True,
            "allow": out,
            "wildcard": wildcard_write(),
            # 界面上那颗「可写 N 处」胶囊数的是**清单里的**（"任意路径"那行不算）
            "writable_n": len([1 for it in out
                               if it.get("write") and it.get("path") != WILDCARD]),
            "current": (cur or {}).get("path") or "",
            "tmp": tmp_size(workdir), "tmp_keep": TMP_KEEP,
            "protected": [{"name": n, "why": w} for n, w in PROTECTED_WHY]}
