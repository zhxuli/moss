import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E

KEEP = 60

def pkg_of(workdir):
    try:
        p = Path(str(workdir or "")).resolve()
    except OSError:
        return ""
    roots = []
    for r in (E.write_root(), E.HOME / "system" / "pkgs"):
        try:
            roots.append(Path(r).resolve())
        except OSError:
            pass
    for root in roots:
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if not parts:
            continue
        name = parts[0]
        if not _ok_id(name):
            continue
        pkg_id = name
        try:
            man = root / name / "pkg.json"
            if man.is_file():
                got = json.loads(man.read_text(encoding="utf-8"))
                cand = str((got or {}).get("id") or "").strip()
                if _ok_id(cand):
                    pkg_id = cand
        except Exception:
            pass
        return pkg_id
    return ""

def _ok_id(pid):
    pid = str(pid or "")
    if not pid or pid.startswith("_"):
        return False
    if not (pid[0].islower() and pid.isascii()):
        return False
    return all(ch.isalnum() or ch in "_-" for ch in pid)

def scope_dir(workdir=""):
    pid = pkg_of(workdir)
    if pid:
        return E.user_data() / "state" / pid / "ai" / "runs"
    return E.user_data() / "ai" / "runs"

def scope_of(workdir="", pid=""):
    pid = str(pid or "").strip() or pkg_of(workdir)
    if pid:
        return {"kind": "pkg", "id": pid,
                "dir": E.user_data() / "state" / pid / "ai" / "runs", "label": "包 " + pid}
    return {"kind": "all", "id": "", "dir": E.user_data() / "ai" / "runs", "label": "整个项目区"}

def dir_path(scope=None):
    if isinstance(scope, dict):
        d = scope.get("dir")
        if d:
            return Path(d)
        if scope.get("id"):
            return E.user_data() / "state" / str(scope["id"]) / "ai" / "runs"
        return E.user_data() / "ai" / "runs"
    s = str(scope or "").strip()
    if not s or s == "all":
        return E.user_data() / "ai" / "runs"
    if ("\\" in s) or ("/" in s) or (":" in s):
        return scope_dir(s)
    return E.user_data() / "state" / s / "ai" / "runs"

def _common_pkg(files):
    ids = set()
    for f in files or []:
        pid = pkg_of(f)
        if not pid:
            return ""
        ids.add(pid)
    return next(iter(ids)) if len(ids) == 1 else ""

def _rehome(rec):
    try:
        rec = dict(rec or {})
        pid_now = pkg_of(rec.get("workdir"))
        pid_new = _common_pkg(rec.get("files"))
        if not pid_new or pid_new == pid_now:
            return rec, False
        for root in (E.user_data() / "pkgs", E.HOME / "system" / "pkgs"):
            d = Path(root) / pid_new
            if d.is_dir():
                old = str(rec.get("workdir") or "")
                rec["workdir"] = str(d)
                rec["scope"] = "pkg"
                rec["scope_id"] = pid_new
                rec["rehomed_from"] = rec.get("rehomed_from") or old
                return rec, True
    except Exception:
        pass
    return dict(rec or {}), False

def _drop_stale(rid, keep):
    keep = str(keep)
    for d in _all_dirs():
        if str(d) == keep:
            continue
        p = Path(d) / (str(rid) + ".json")
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass

def _all_dirs():
    out = [E.user_data() / "ai" / "runs"]
    st = E.user_data() / "state"
    try:
        if st.is_dir():
            for d in st.iterdir():
                p = d / "ai" / "runs"
                if p.is_dir():
                    out.append(p)
    except OSError:
        pass
    return out

def _new_id():
    return "%s-%04x" % (time.strftime("%Y%m%d-%H%M%S"), random.randint(0, 0xffff))

def new_id():
    return _new_id()

def _write(path, rec):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)

def save(rec, scope=None):
    try:
        rec, moved = _rehome(rec)
        rec.setdefault("id", _new_id())
        rec.setdefault("finished", time.time())
        rec["running"] = False
        d = dir_path(rec.get("workdir") if moved
                     else (scope if scope is not None else rec.get("workdir")))
        d.mkdir(parents=True, exist_ok=True)
        _write(d / (rec["id"] + ".json"), rec)
        if moved:
            _drop_stale(rec["id"], d)
        _prune(d)
        return {"ok": True, "id": rec["id"], "dir": str(d)}
    except Exception as e:
        return {"ok": False, "id": "", "msg": "%s: %s" % (type(e).__name__, e)}

def save_live(rec, scope=None):
    try:
        rec, moved = _rehome(rec)
        rid = str(rec.get("id") or "").strip()
        if not rid:
            return {"ok": False, "id": "", "msg": "没有 id"}
        rec["running"] = True
        rec.setdefault("started", time.time())
        rec["updated"] = time.time()
        d = dir_path(rec.get("workdir") if moved
                     else (scope if scope is not None else rec.get("workdir")))
        _write(d / (rid + ".json"), rec)
        if moved:
            _drop_stale(rid, d)
        return {"ok": True, "id": rid, "dir": str(d)}
    except Exception as e:
        return {"ok": False, "id": "", "msg": "%s: %s" % (type(e).__name__, e)}

def _prune(d):
    try:
        files = sorted(Path(d).glob("*.json"))
        for old in files[:-KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        pass

def _load(path):
    try:
        got = json.loads(Path(path).read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else None
    except Exception:
        return None

def _file_of(run_id, scope=None):
    rid = str(run_id or "").strip()
    if not rid:
        return None
    cand = [dir_path(scope)] if scope is not None else []
    cand += _all_dirs()
    seen = set()
    for d in cand:
        if str(d) in seen:
            continue
        seen.add(str(d))
        p = Path(d) / (rid + ".json")
        if p.is_file():
            return p
    return None

def _bucket_pkg_dir(d):
    try:
        st = (E.user_data() / "state").resolve()
        parts = Path(d).resolve().relative_to(st).parts
    except (OSError, ValueError):
        return ""
    if not parts:
        return ""
    pid = parts[0]
    for root in (E.user_data() / "pkgs", E.HOME / "system" / "pkgs"):
        try:
            p = Path(root) / pid
        except OSError:
            continue
        if p.is_dir():
            return str(p)
    return ""

def _fix_workdir(rec, d):
    wd = str(rec.get("workdir") or "")
    try:
        if wd and Path(wd).is_dir():
            return rec
    except OSError:
        pass
    now = _bucket_pkg_dir(d)
    if not now:
        return rec
    rec = dict(rec)
    rec["workdir"] = now
    rec["workdir_fixed"] = True
    return rec

def list_runs(limit=30, with_steps=False, scope=None, everywhere=False):
    dirs = _all_dirs() if everywhere else [dir_path(scope)]
    rows = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.json"):
            rec = _load(p)
            if not rec:
                continue
            rows.append(_fix_workdir(rec, d))
    rows.sort(key=lambda r: str(r.get("id") or ""), reverse=True)
    out = []
    for rec in rows[:max(1, int(limit or 30))]:
        row = {k: rec.get(k) for k in ("id", "task", "workdir", "ok", "reason", "summary",
                                       "caveats", "usage", "files", "snapshot", "seconds",
                                       "snapshot_note",
                                       "started_text", "finished", "model", "max_tokens",
                                       "kind", "stopped", "continued_from", "running",
                                       "updated", "mode")}
        row["cont"] = bool(rec.get("messages"))
        row["msgs"] = len(rec.get("messages") or [])
        row["steps"] = len(rec.get("steps") or [])
        row["interrupted"] = bool(rec.get("running"))
        if with_steps:
            row["steps_detail"] = rec.get("steps") or []
        out.append(row)
    return out

def get(run_id, scope=None):
    p = _file_of(run_id, scope)
    if not p:
        return None
    rec = _load(p)
    return _fix_workdir(rec, p.parent) if rec else None

def messages(run_id, scope=None):
    rec = get(run_id, scope) or {}
    msgs = [m for m in (rec.get("messages") or []) if isinstance(m, dict)]
    blob = json.dumps(msgs, ensure_ascii=False)
    return {"ok": bool(msgs), "messages": msgs, "task": rec.get("task") or "",
            "at": rec.get("started_text") or "", "model": rec.get("model") or "",
            "count": len(msgs), "bytes": len(blob.encode("utf-8")),
            "note": "" if msgs else "这条是更早的记录 —— 那时候还没存对话，接不上",
            "workdir": rec.get("workdir") or "", "id": str(run_id or "")}

def delete(run_id, scope=None):
    p = _file_of(run_id, scope)
    try:
        if p:
            p.unlink(missing_ok=True)
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "msg": str(e)}

def clear(scope=None):
    n = 0
    d = dir_path(scope)
    try:
        if d.is_dir():
            for p in d.glob("*.json"):
                p.unlink(missing_ok=True)
                n += 1
    except OSError:
        pass
    return {"ok": True, "removed": n, "dir": str(d)}

def migrate_once():
    ud = E.user_data()
    marker = ud / "ai" / ".runs_scoped"
    if marker.exists():
        return {"ok": True, "skipped": True, "moved": 0}
    src = ud / "ai" / "runs"
    moved, failed = 0, 0
    try:
        if src.is_dir():
            for p in list(src.glob("*.json")):
                rec = _load(p)
                if not rec:
                    continue
                pid = pkg_of(rec.get("workdir"))
                if not pid:
                    continue
                dst = ud / "state" / pid / "ai" / "runs" / p.name
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists():
                        shutil.move(str(p), str(dst))
                    else:
                        p.unlink(missing_ok=True)
                    moved += 1
                except OSError:
                    failed += 1
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("%s\nmoved=%d failed=%d\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), moved, failed), encoding="utf-8")
        except OSError:
            pass
    except OSError:
        pass
    return {"ok": True, "skipped": False, "moved": moved, "failed": failed}
