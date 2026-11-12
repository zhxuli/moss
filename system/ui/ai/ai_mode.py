import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E

WILDCARD = "*"
WILDCARD_LABEL = "任意路径"

def _scope_pkg(workdir=""):
    try:
        import ai_runs as R
        return R.pkg_of(str(workdir or ""))
    except Exception:
        return ""

def _legacy_path():
    return E.user_data() / "ai" / "mode.json"

def _path_belongs_to_pkg(pth, pid):
    raw = str(pth or "").strip()
    if not raw or raw == WILDCARD or not pid:
        return False
    try:
        import ai_runs as R
        if R.pkg_of(raw) == pid:
            return True
    except Exception:
        pass
    try:
        st = (E.user_data() / "state" / str(pid)).resolve()
        pp = Path(raw).resolve()
        return pp == st or str(pp).startswith(str(st) + os.sep)
    except (OSError, ValueError):
        return False

def _legacy_seed(workdir=""):
    pid = _scope_pkg(workdir)
    if not pid:
        return {}
    p = _legacy_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        return {}
    rows = []
    for it in (raw.get("allow") or []):
        if isinstance(it, dict) and _path_belongs_to_pkg(it.get("path"), pid):
            one = _norm_perm(it)
            if one:
                rows.append(one)
    return {"allow": rows} if rows else {}

def path(workdir=""):
    pid = _scope_pkg(workdir)
    if pid:
        return E.user_data() / "state" / pid / "ai" / "mode.json"
    return _legacy_path()

def _blank():
    return {"allow": [], "full_access": False}

def _norm_perm(it):
    pth = str(it.get("path") or "").strip()
    if not pth:
        return None
    if "read" in it or "write" in it:
        rd, wr = bool(it.get("read", True)), bool(it.get("write", True))
    else:
        rd = wr = bool(it.get("on", True))
    return {"path": pth, "read": rd, "write": wr,
            "pending": bool(it.get("pending", False)),
            "why": str(it.get("why") or ""), "by": str(it.get("by") or "user"),
            "at": str(it.get("at") or "")}

def load(workdir=""):
    cur = _blank()
    raw = {}
    try:
        p = path(workdir)
        if p.is_file():
            got = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(got, dict):
                raw = got
        elif _scope_pkg(workdir):
            raw = _legacy_seed(workdir)
    except Exception:
        raw = {}
    legacy_full = False
    for it in (raw.get("allow") or []):
        if isinstance(it, dict):
            one = _norm_perm(it)
            if one and str(one.get("by") or "") != "auto":
                cur["allow"].append(one)
                if (one.get("path") == WILDCARD and one.get("write")
                        and "完全权限" in str(one.get("why") or "")):
                    legacy_full = True
    cur["full_access"] = bool(raw.get("full_access", legacy_full))
    if not cur["full_access"]:
        for it in cur["allow"]:
            if it.get("path") == WILDCARD:
                it["read"] = False
                it["write"] = False
    old_mode = str(raw.get("mode") or "")
    if old_mode and not raw.get("seeded"):
        if old_mode == "consult":
            for it in cur["allow"]:
                it["write"] = False
        elif old_mode == "free":
            for it in cur["allow"]:
                it["write"] = True
    return cur

def save(d, workdir=""):
    d = d if isinstance(d, dict) else _blank()
    out = {"allow": [x for x in (d.get("allow") or []) if isinstance(x, dict) and x.get("path")],
           "full_access": bool(d.get("full_access"))}
    try:
        p = path(workdir)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, p)
        return dict(out, ok=True, path=str(p))
    except OSError as e:
        return dict(out, ok=False, msg="存不下来：%s" % e, path=str(path(workdir)))

def _wildcard_row():
    return {"path": WILDCARD, "read": False, "write": False, "why": WILDCARD_LABEL,
            "by": "system", "at": "", "pending": False}

def full_access(workdir=""):
    try:
        return bool(load(workdir).get("full_access"))
    except Exception:
        return False

def set_full_access(on=True, workdir=""):
    cur = load(workdir)
    on = bool(on)
    cur["full_access"] = on
    rows = cur.get("allow") or []
    star = _find(rows, WILDCARD)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    if star is None:
        star = {"path": WILDCARD, "read": False, "write": False, "why": WILDCARD_LABEL,
                "by": "system", "at": "", "pending": False}
        rows.append(star)
    star["read"] = on
    star["write"] = on
    star["pending"] = False
    star["at"] = now
    star["by"] = "user"
    star["why"] = "完全权限（无人值守）" if on else WILDCARD_LABEL
    cur["allow"] = rows
    got = save(cur, workdir)
    got["msg"] = ("完全权限已开启：任意路径可读写；新建 / 修改技能自动批准；危险操作不再确认"
                  if on else "完全权限已关闭：恢复按权限清单；技能重新按指纹授权")
    got["full_access"] = on
    got["item"] = dict(star)
    return got

def allow_list(workdir=""):
    cur = load(workdir)
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

def allow_set(pth, read=None, write=None, why="", by="user", add=True, pending=None,
              force=False, workdir=""):
    raw = str(pth or "").strip().strip('"')
    if not raw:
        return {"ok": False, "msg": "路径是空的"}
    if raw != WILDCARD:
        bad = protected(Path(raw))
        if bad:
            return {"ok": False, "msg": bad}
    cur = load(workdir)
    rows = cur.get("allow") or []
    it = _find(rows, raw)
    if it is None:
        if not add and raw != WILDCARD:
            return {"ok": False, "msg": "清单里没有这条"}
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
        it["by"] = str(by or "user")
        it["why"] = str(why or "")
    else:
        if why:
            it["why"] = str(why)
        if by and it.get("by") in ("", "user"):
            it["by"] = str(by)
    if raw == WILDCARD and write is not None and not bool(write):
        cur["full_access"] = False
    cur["allow"] = rows
    got = save(cur, workdir)
    got["msg"] = "权限已保存：%s（读 %s · 写 %s）" % (it["path"], "开" if it.get("read") else "关",
                                                 "开" if it.get("write") else "关")
    got["item"] = dict(it)
    return got

def allow_add(pth, read=True, write=True, why="", by="user", pending=None, force=False,
              workdir=""):
    return allow_set(pth, read=read, write=write, why=why, by=by, add=True,
                     pending=pending, force=force, workdir=workdir)

def _is_abs_path(raw):
    try:
        return Path(str(raw)).is_absolute()
    except Exception:
        return False

def path_problem(pth, must_exist=True):
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

def find(pth, workdir=""):
    return _find(load(workdir).get("allow") or [], pth)

def allow_pending_add(pth, why="", need="write", workdir=""):
    raw = str(pth or "").strip().strip('"')
    problem = path_problem(raw)
    if problem:
        return {"ok": False, "msg": problem, "bad_path": True}
    it = find(raw, workdir)
    if it is not None:
        return {"ok": True, "msg": "清单里已经有这条了", "exists": True}
    return allow_add(raw, read=False, write=False,
                     why=str(why or ""), by="ai", pending=True, workdir=workdir)

def allow_rm(pth, workdir=""):
    cur = load(workdir)
    key = _norm(pth)
    rows = [it for it in (cur.get("allow") or []) if _norm(it.get("path")) != key]
    if len(rows) == len(cur.get("allow") or []):
        return {"ok": False, "msg": "清单里没有这条"}
    if _norm(pth) == WILDCARD:
        cur["full_access"] = False
    cur["allow"] = rows
    got = save(cur, workdir)
    got["msg"] = "从清单里删掉了（它现在读不了也写不了这里）"
    return got

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
    for it in list(rows) + list(_TEMP):
        if not it.get(kind):
            continue
        pth = str(it.get("path") or "")
        if pth == WILDCARD or _inside(path, pth):
            return it
    return None

def pkg_roots():
    return (E.write_root(), E.HOME / "system" / "pkgs")

def is_factory(wd):
    return _inside(wd, E.HOME / "system" / "pkgs")

def _is_pkg_scope(scope):
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
    if not _is_pkg_scope(scope):
        return False
    if not _inside(path, scope):
        return False
    rows = allow_list(scope) if rows is None else rows
    own = _find(rows, scope)
    if own is None:
        return True
    return bool(own.get(kind))

def _current_row(workdir, rows=None):
    wd = str(workdir or "").strip()
    if not _is_pkg_scope(wd):
        return None
    rows = allow_list(wd) if rows is None else rows
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

PROTECTED_WHY = (
    ("core", "这是程序本体，改了要重新打包才生效，而且只能由人来做。"),
    ("moss.exe", "`moss.exe` 就是程序本身，改写它等于把程序砸了。"),
    ("moss.py", "这是程序的源码入口，改了要重新打包才生效（只能由人来做）。"),
    ("venv", "`venv/**` 是打包环境，不归 AI 动。"),
    (".git", "`.git/**` 是版本库，改它等于伪造历史。"),
)

def protected(path):
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
                return "[拒绝] 受保护路径（硬锁）：这是程序本体，改它不生效（要重新打包，只能由人来做）。"
        except OSError:
            pass
    if _inside(p, E.user_data() / "backups"):
        return ("[拒绝] `user_data/backups/**` 是**版本快照仓** —— 那是你（和 AI）的退路，"
                "不许由 AI 来写 / 删。要清快照只能用户自己在界面「版本快照」那一页清"
                "（`V-382`：AI 这边连删快照的工具都没有了）。")
    return None

def readable_builtin(path):
    return (is_ai_tmp(path)
            or _inside(path, E.tool_root())
            or _inside(path, E.HOME / "system" / "spec")
            or _inside(path, E.HOME / "system" / "pkgs"))

def writable_builtin(path):
    return is_ai_tmp(path) or _inside(path, E.tool_root())

def can_read(path, scope=None):
    if path is None:
        return None
    if readable_builtin(path):
        return None
    rows = allow_list(scope)
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
    if path is None:
        return None
    bad = protected(Path(path))
    if bad:
        return bad
    if writable_builtin(path):
        return None
    rows = allow_list(scope)
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

def wildcard_write(workdir=""):
    it = _find(allow_list(workdir), WILDCARD)
    return bool(it and it.get("write"))

def writable_roots(workdir=""):
    return [it["path"] for it in allow_list(workdir) if it.get("write")]

def readable_extra(workdir=""):
    return [Path(it["path"]) for it in allow_list(workdir)
            if it.get("read") and it.get("path") != WILDCARD and it.get("path")]

DANGER_WORDS = (
    "--remove", "--rename", "--new", "--snap", "--alias", "--pip",
    " remove", " rm ", " rm", "rm ", " del ", "delete", " rmdir", " format",
    " kill", " taskkill", " stop-process", ">", ">>", "|", "&&", "||",
    "pip install", "--ai-profile", "reg ", "regedit", "shutdown",
)

def danger_of(tool, args):
    name = str(tool or "")
    a = args or {}
    if name == "run_moss":
        line = (" " + str(a.get("args") or "").lower() + " ")
        for w in DANGER_WORDS:
            if w in line:
                return "这条命令看起来会**动盘 / 动系统**：`moss %s`（命中「%s」）" % (
                    str(a.get("args") or "")[:60], w.strip())
        return None
    if name == "snap_clean":
        return None
    return None

def needs_confirm(danger, workdir=""):
    return bool(danger) and not wildcard_write(workdir)

TMP_KEEP = 10

def _pkg_id(workdir):
    try:
        import ai_runs as R
        return R.pkg_of(workdir)
    except Exception:
        return ""

def tmp_root(workdir=""):
    pid = _pkg_id(workdir)
    if pid:
        return E.user_data() / "state" / pid / "ai" / "tmp"
    return E.user_data() / "ai" / "tmp"

def tmp_for(run_id, workdir=""):
    rid = str(run_id or "").strip() or ("run-%d" % int(time.time()))
    safe = "".join(ch for ch in rid if ch.isalnum() or ch in "-_")[:64] or "run"
    return tmp_root(workdir) / safe

def ensure_tmp(run_id, workdir=""):
    try:
        d = tmp_for(run_id, workdir)
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        return None

def prune_tmp(keep=TMP_KEEP, workdir=""):
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
    clear_temp()
    return prune_tmp(workdir=workdir)

def perm_note(workdir=""):
    rows = allow_list(workdir)
    wd = str(workdir or "").strip()
    cur = _current_row(workdir, rows)
    cur_write = bool(cur and cur.get("write"))
    wr = [it["path"] for it in rows
          if it.get("write") and it.get("path") != WILDCARD and it.get("path") != wd]
    rd = [it["path"] for it in rows
          if it.get("read") and it.get("path") != WILDCARD and it.get("path") != wd]
    star_w = wildcard_write(workdir)
    full = full_access(workdir)
    out = []
    if cur is not None and cur_write:
        out.append("★ **这次干活的那个包** = `%s`：**默认就能读、能写**，不用申请"
                   "（用户随时可以在界面上把它的「写」关掉）。" % wd)
    elif cur is not None:
        out.append("★ **这次干活的那个包** = `%s`：用户把它的「写」**关掉了** —— "
                   "这一轮你只能读它，别改。" % wd)
    if full:
        out.append("🔓 **完全权限（无人值守）**：除硬锁路径外**哪儿都能写**；"
                   "你**新建或修改的技能会自动视为已批准**，不用停下来等用户点「允许」；"
                   "危险操作 / 覆盖也不再问你。★ 这种时候**一次 `allow_path` 都不要调** —— "
                   "你要碰的地方本来就允许，申请只会白弹一张卡、白等一个人。"
                   "★ 技能**本次开工的工具表仍然是固定的**：新造/改过的技能本次不能直接变成工具，"
                   "要试就跑 `run_moss(\":skill run <名字> …\")`；不要用 `ask` 等用户批准。"
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
    rows = allow_list(workdir)
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
            "wildcard": wildcard_write(workdir),
            "full_access": full_access(workdir),
            "writable_n": len([1 for it in out
                               if it.get("write") and it.get("path") != WILDCARD]),
            "current": (cur or {}).get("path") or "",
            "scope_id": _scope_pkg(workdir),
            "store": str(path(workdir)),
            "tmp": tmp_size(workdir), "tmp_keep": TMP_KEEP,
            "protected": [{"name": n, "why": w} for n, w in PROTECTED_WHY]}
