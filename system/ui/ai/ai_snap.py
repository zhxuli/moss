import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UI = HERE.parent
if str(UI) not in sys.path:
    sys.path.insert(0, str(UI))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E

TITLE = "AI · 动手前"
NOTE = "[AI] 自动存的"
TASK_IN_TITLE = 40

def _one_line(s):
    return " ".join(str(s or "").split())

def title_for(task):
    t = _one_line(task)
    if not t:
        return ""
    if len(t) > TASK_IN_TITLE:
        t = t[:TASK_IN_TITLE].rstrip() + "…"
    return t

def note_for(task):
    return _one_line(task) or NOTE

def _store():
    import backup as B
    return B.BackupStore(E.user_data() / "backups", _rel_of, _resolve)

def _rel_of(p):
    import backup as B
    for name, root in (("user", E.user_data()),
                       ("system", E.HOME / "system")):
        try:
            rel = os.path.relpath(str(p), str(root))
        except ValueError:
            continue
        if not rel.startswith("..") and not os.path.isabs(rel):
            return "%s/%s" % (name, rel.replace("\\", "/"))
    return "abs/" + str(p).replace(":", "").replace("\\", "/")

def _resolve(rel):
    s = str(rel or "").replace("\\", "/")
    low = s.lower()
    if low.startswith("user/"):
        return E.user_data() / s[5:]
    if low.startswith("system/"):
        return E.HOME / "system" / s[7:]
    if low.startswith("abs/"):
        return Path(s[4:].replace("/", os.sep))
    raise ValueError("认不出这个 rel：%s" % rel)

MAX_FILES = 20000

def _count_files(d, cap=MAX_FILES):
    n = 0
    for _cur, _dirs, names in os.walk(str(d)):
        n += len(names)
        if n > cap:
            return n
    return n

def too_broad(d):
    try:
        p = Path(str(d)).resolve()
    except OSError:
        return "这个路径读不到"
    if p.parent == p:
        return "这是盘根（整块盘不是一次备份的对象）"
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~") or "/")
    try:
        if p == home.resolve():
            return "这是你的用户主目录（太大，也不是一次备份的对象）"
    except OSError:
        pass
    for r in (E.user_data(), E.HOME / "system", E.HOME):
        try:
            if p == Path(r).resolve():
                return "这是 `%s`（整层太大，要存就存它下面的某个包 / 目录）" % Path(r).name
        except OSError:
            continue
    for r in (E.user_data() / "pkgs", E.user_data() / "state",
              E.user_data() / "backups", E.user_data() / "trash",
              E.user_data() / "ai", E.HOME / "system" / "pkgs",
              E.HOME / "core", E.HOME / "system" / "ui",
              E.HOME / "system" / "runtimes"):
        try:
            if p == Path(r).resolve():
                return "这是 `%s`（整层太大，要存就存它下面的某个包 / 目录）" % r.name
        except OSError:
            continue
    try:
        if str(p).lower().startswith(str((E.user_data() / "backups").resolve()).lower()):
            return "这是备份库自己（不能备份备份）"
    except OSError:
        pass
    return ""

def is_scratch(path):
    try:
        p = str(Path(str(path)).resolve()).lower()
    except OSError:
        return False
    for root in (E.user_data() / "backups", E.user_data() / "trash",
                 E.user_data() / "ai" / "tmp"):
        try:
            if p.startswith(str(Path(root).resolve()).lower()):
                return True
        except OSError:
            continue
    try:
        st = str((E.user_data() / "state").resolve()).lower()
    except OSError:
        return False
    return p.startswith(st) and (os.sep + "ai" + os.sep + "tmp" + os.sep) in p

def _pkg_dir(d):
    for root in (E.user_data() / "pkgs", E.HOME / "system" / "pkgs"):
        try:
            rel = Path(str(d)).resolve().relative_to(Path(root).resolve())
        except (ValueError, OSError):
            continue
        if rel.parts:
            return Path(root) / rel.parts[0]
    return None

def scope_dir(path):
    p = Path(str(path))
    try:
        if p.is_dir():
            return _pkg_dir(p) or p
    except OSError:
        return p
    parent = p.parent
    got = _pkg_dir(parent)
    if got:
        return got
    return parent if parent.exists() else p

def snapshot_before(task, workdir, touched=None):
    wd = Path(str(workdir or ""))
    try:
        cands, will_exist = [], []
        if touched:
            d = scope_dir(touched)
            if d.is_dir():
                cands.append(d)
            else:
                will_exist.append(d)
        if wd.is_dir():
            cands.append(wd)
        srcs, why_not = [], []
        seen = set()
        for d in cands:
            try:
                key = str(Path(d).resolve()).lower()
            except OSError:
                key = str(d).lower()
            if key in seen:
                continue
            seen.add(key)
            bad = too_broad(d)
            if bad:
                why_not.append(str(d) + "：" + bad)
                continue
            n = _count_files(d)
            if n > MAX_FILES:
                why_not.append("%s：文件太多（>%d 个）" % (d, MAX_FILES))
                continue
            srcs.append(str(Path(d).resolve()))
        if not srcs:
            if will_exist:
                return {"ok": False, "retry": True,
                        "msg": "要改的东西还没建出来（新建）—— 等它存在了再存动手前的快照"}
            if not wd.is_dir() and not touched:
                return {"ok": False, "msg": "这个目录还不存在（新建包）—— 不用存动手前的快照"}
            return {"ok": False,
                    "msg": ("没有可以存的地方" + ("（" + "；".join(why_not) + "）" if why_not else ""))}
        st = _store()
        man = st.create(srcs, title=title_for(task), note=note_for(task),
                        by="ai", by_task=str(task or "").strip())
        return {"ok": True, "id": man.get("id"), "group": man.get("group"),
                "sources": srcs, "files": (man.get("stats") or {}).get("files"),
                "msg": "存好了：%s（分组 %s，%s 个文件）"
                       % (man.get("id"), man.get("group"),
                          (man.get("stats") or {}).get("files"))}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

def clean_ai(group="", bid=""):
    try:
        st = _store()
        return st.delete_ai(bid=(str(bid or "") or None), group=(str(group or "") or None))
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

def is_pkg_dir(d):
    try:
        return (Path(str(d)) / "pkg.json").is_file()
    except OSError:
        return False

def snapshot_at_start(task, workdir):
    wd = Path(str(workdir or ""))
    if not is_pkg_dir(wd):
        return {"ok": False, "skip": True,
                "msg": "这次不是改一个已经存在的包 —— 等它第一次动手之前再存"}
    got = snapshot_before(task, str(wd))
    got["at_start"] = True
    return got

def drop_untouched(bid, group=""):
    if not bid:
        return {"ok": False, "msg": "没有快照 id"}
    try:
        st = _store()
        got = st.delete_ai(bid=str(bid), group=(str(group or "") or None))
        if isinstance(got, dict):
            got.setdefault("ok", True)
        return got or {"ok": True}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}

def ai_count(group=""):
    try:
        got = [b for b in _store().list_backups(group=(str(group or "") or None))
               if str(b.get("by") or "") == "ai"]
        return len(got)
    except Exception:
        return 0
