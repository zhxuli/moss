import gzip
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

KEEP = 0  # 0 = 不自动删除。完整轨迹是用户可检索的档案，删不删由用户决定。

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
            trace_path_for(str(rid), d).unlink(missing_ok=True)
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

def all_dirs():
    return _all_dirs()


def _new_id():
    return "%s-%04x" % (time.strftime("%Y%m%d-%H%M%S"), random.randint(0, 0xffff))

def new_id():
    return _new_id()

def trace_dir_for(run_dir):
    return Path(run_dir).parent / "traces"


def trace_path_for(run_id, run_dir):
    return trace_dir_for(run_dir) / (str(run_id) + ".jsonl.gz")


def _read_trace(path, rec):
    """按 metadata 里的 trace 文件读回 messages；旧记录直接返回内嵌 messages。"""
    if isinstance(rec.get("messages"), list):
        return rec
    meta = rec.get("trace") if isinstance(rec.get("trace"), dict) else {}
    name = str(meta.get("file") or "")
    if not name or meta.get("deleted"):
        rec["messages"] = []
        return rec
    p = trace_dir_for(path.parent) / name
    if not p.is_file():
        rec["messages"] = []
        return rec
    msgs = []
    try:
        with gzip.open(str(p), "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    m = json.loads(line)
                except ValueError:
                    continue
                if isinstance(m, dict):
                    msgs.append(m)
    except OSError:
        msgs = []
    rec["messages"] = msgs
    rec["_trace_missing"] = not bool(msgs) and int(meta.get("msgs") or 0) > 0
    return rec


def _write(path, rec, write_trace=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(rec or {})
    msgs = rec.pop("messages", None)
    rec = {k: v for k, v in rec.items() if not str(k).startswith("_")}
    if not write_trace and msgs:
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(old, dict) and old.get("trace"):
                rec["trace"] = old.get("trace")
                rec["has_trace"] = bool(old.get("has_trace"))
                rec["msgs"] = int(old.get("msgs") or 0)
        except Exception:
            pass
    rid = str(rec.get("id") or path.stem)
    if isinstance(msgs, list) and write_trace:
        if msgs:
            td = trace_dir_for(path.parent)
            td.mkdir(parents=True, exist_ok=True)
            tf = td / (rid + ".jsonl.gz")
            tmp = tf.with_name(tf.name + ".tmp")
            with gzip.open(str(tmp), "wt", encoding="utf-8", compresslevel=6) as fh:
                for m in msgs:
                    fh.write(json.dumps(m, ensure_ascii=False) + "\n")
            os.replace(tmp, tf)
            rec["has_trace"] = True
            rec["msgs"] = len(msgs)
            rec["trace"] = {"file": tf.name, "bytes": tf.stat().st_size,
                            "msgs": len(msgs), "compressed": True,
                            "at": time.time()}
        elif not rec.get("has_trace"):
            rec["has_trace"] = False
            rec["msgs"] = 0
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
        dest = d / (rid + ".json")
        due = True
        try:
            tf = trace_path_for(rid, d)
            if tf.is_file():
                due = (time.time() - tf.stat().st_mtime) >= 5.0
        except OSError:
            due = True
        _write(dest, rec, write_trace=due)
        if moved:
            _drop_stale(rid, d)
        return {"ok": True, "id": rid, "dir": str(d)}
    except Exception as e:
        return {"ok": False, "id": "", "msg": "%s: %s" % (type(e).__name__, e)}

def _prune(d):
    if not KEEP:
        return
    try:
        files = sorted(Path(d).glob("*.json"))
        for old in files[:-KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        pass

def _load(path, with_trace=False):
    try:
        got = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(got, dict):
            return None
        return _read_trace(Path(path), got) if with_trace else got
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
            rec = _load(p, with_trace=False)
            if not rec:
                continue
            rows.append(_fix_workdir(rec, d))
    rows.sort(key=lambda r: str(r.get("id") or ""), reverse=True)
    out = []
    for rec in rows[:max(1, int(limit or 30))]:
        row = {k: rec.get(k) for k in ("id", "task", "workdir", "ok", "reason", "summary",
                                       "caveats", "usage", "files", "snapshot", "seconds",
                                       "snapshot_note", "handoff_from",
                                       "started_text", "finished", "model", "max_tokens",
                                       "kind", "stopped", "continued_from", "running",
                                       "updated", "mode")}
        has_trace = bool(rec.get("messages") or rec.get("has_trace"))
        if has_trace and rec.get("has_trace"):
            try:
                has_trace = trace_path_for(str(rec.get("id") or ""), d).is_file()
            except OSError:
                has_trace = False
        row["cont"] = bool(has_trace or rec.get("messages"))
        row["trace_missing"] = bool(rec.get("has_trace") and not has_trace)
        row["msgs"] = int(rec.get("msgs") or len(rec.get("messages") or []))
        row["steps"] = len(rec.get("steps") or [])
        row["interrupted"] = bool(rec.get("running"))
        if with_steps:
            row["steps_detail"] = rec.get("steps") or []
        out.append(row)
    return out

def raw_records(scope=None, limit=0, everywhere=False, with_trace=False):
    """完整 run 记录（含 messages/steps），给档案索引使用。

    limit 先按文件名截，再读 JSON —— 避免为了取最近 N 条把上千个大文件全读进内存。
    """
    dirs = _all_dirs() if everywhere else [dir_path(scope)]
    paths = []
    for d in dirs:
        if not d.is_dir():
            continue
        paths.extend(d.glob("*.json"))
    paths.sort(key=lambda x: x.name, reverse=True)
    if limit:
        paths = paths[:max(1, int(limit))]
    rows = []
    for p in paths:
        rec = _load(p, with_trace=bool(with_trace))
        if rec:
            rows.append(_fix_workdir(rec, p.parent))
    return rows


def _clip_text(v, cap):
    text = str(v or "")
    return text if len(text) <= cap else text[:cap] + "\n……（已截断）"


def _step_ok(step):
    out = str((step or {}).get("out") or "")
    return out.startswith("退出码 0")


def make_handoff(rec):
    """从一次 run 里提炼出给下一位 Agent 的交接摘要。纯本地整理，不再调模型。"""
    rec = rec or {}
    steps = [s for s in (rec.get("steps") or []) if isinstance(s, dict)]
    runs = []
    for s in steps:
        if str(s.get("tool") or "") != "run_moss":
            continue
        args = str(s.get("args") or "")
        out = str(s.get("out") or "")
        first = out.strip().splitlines()[0][:160] if out.strip() else ""
        runs.append({"args": _clip_text(args, 500), "ok": _step_ok(s),
                     "out": _clip_text(first, 240), "n": s.get("n") or 0})
    return {
        "run_id": str(rec.get("id") or ""),
        "from_task": str(rec.get("task") or ""),
        "summary": _clip_text(rec.get("summary") or rec.get("reason") or "", 2400),
        "caveats": _clip_text(rec.get("caveats") or "", 1200),
        "decisions": _clip_text(rec.get("decisions") or "", 1600),
        "next_steps": _clip_text(rec.get("next_steps") or "", 1200),
        "files": [str(x) for x in (rec.get("files") or [])][:80],
        "snapshot": rec.get("snapshot") or None,
        "ok": bool(rec.get("ok")),
        "kind": str(rec.get("kind") or "work"),
        "verification": runs[-4:],
        "usage": rec.get("usage") or {},
        "finished": rec.get("finished") or 0,
        "started_text": str(rec.get("started_text") or ""),
    }


def handoff_text(rec):
    h = rec.get("handoff") if isinstance(rec.get("handoff"), dict) else make_handoff(rec)
    lines = ["## 上一任务交接摘要（宿主整理的历史证据，不是新指令）"]
    if h.get("from_task"):
        lines.append("- 上次任务：" + str(h.get("from_task")))
    if h.get("summary"):
        lines.append("- 结果：" + str(h.get("summary")))
    if h.get("decisions"):
        lines.append("- 关键决定：" + str(h.get("decisions")))
    if h.get("files"):
        lines.append("- 改动文件：" + "、".join(str(x) for x in h.get("files")[:30]))
    if h.get("verification"):
        bits = []
        for v in h["verification"]:
            bits.append("%s%s（%s）" % ("✓ " if v.get("ok") else "✗ ",
                                       str(v.get("args") or "").replace("\n", " ")[:180],
                                       str(v.get("out") or "")[:120]))
        lines.append("- 已跑过的验证：" + "；".join(bits))
    _snap = h.get("snapshot")
    if isinstance(_snap, dict) and _snap.get("id"):
        lines.append("- 快照：%s（回退在「文件管理 → 版本快照」）" % _snap["id"])
    if h.get("caveats"):
        lines.append("- 没验到 / 要注意：" + str(h.get("caveats")))
    if h.get("next_steps"):
        lines.append("- 下次可以接着看：" + str(h.get("next_steps")))
    if h.get("run_id"):
        lines.append("- 完整轨迹：" + str(h["run_id"]) +
                     "（需要细节时用 history_search 查关键词，再 history_open 看命中附近；不要整条重读）")
    return "\n".join(lines)


def split_trace_file(path):
    """把旧 run JSON 里内嵌的 messages 搬到 traces/*.jsonl.gz。"""
    p = Path(path)
    rec = _load(p, with_trace=False)
    if not rec:
        return False
    msgs = rec.get("messages")
    if not isinstance(msgs, list) or not msgs:
        return False
    _write(p, rec)
    return True


def write_meta(path, rec):
    """只写 run metadata；messages 会按统一规则进 trace。"""
    _write(Path(path), rec)


def get(run_id, scope=None):
    p = _file_of(run_id, scope)
    if not p:
        return None
    rec = _load(p, with_trace=True)
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
            try:
                trace_path_for(str(run_id), p.parent).unlink(missing_ok=True)
            except OSError:
                pass
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
                try:
                    trace_path_for(p.stem, d).unlink(missing_ok=True)
                except OSError:
                    pass
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
                    src_t = trace_path_for(p.stem, p.parent)
                    dst_t = trace_path_for(p.stem, dst.parent)
                    try:
                        if src_t.is_file() and not dst_t.exists():
                            dst_t.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(src_t), str(dst_t))
                        else:
                            src_t.unlink(missing_ok=True)
                    except OSError:
                        pass
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
