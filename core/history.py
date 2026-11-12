import json
from datetime import datetime

from . import paths

MAX_SHOW = 20
READ_RAW = 5000

def _file_for_now():
    return paths.HISTORY_DIR / (datetime.now().strftime("%Y-%m") + ".jsonl")

def append(entry):
    try:
        paths.ensure_user_dirs()
        entry = dict(entry)
        entry.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        with open(_file_for_now(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False

def _iter_files():
    if not paths.HISTORY_DIR.is_dir():
        return []
    return sorted(paths.HISTORY_DIR.glob("*.jsonl"), reverse=True)

def recent(n=20):
    out = []
    for f in _iter_files():
        try:
            with open(f, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except Exception:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
            if len(out) >= n:
                return out
    return out

def dedup_key(r):
    return "|".join([
        str(r.get("kind") or ""),
        str(r.get("id") or r.get("target") or ""),
        json.dumps(r.get("params") or {}, sort_keys=True, ensure_ascii=False),
        json.dumps(r.get("args") or [], ensure_ascii=False),
    ])

def dedup(rows):
    ordered = sorted(rows, key=lambda r: str(r.get("ts") or ""), reverse=True)
    seen = set()
    out = []
    for r in ordered:
        k = dedup_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out

def recent_unique(limit=MAX_SHOW, raw=READ_RAW):
    rows = recent(raw)
    dead = _forgotten(rows)
    rows = [r for r in rows if should_record(r) and dedup_key(r) not in dead]
    return dedup(rows)[:limit]

def should_record(entry):
    return (entry.get("kind") or "") not in ("pkg", TOMBSTONE)

TOMBSTONE = "tombstone"

def forget(entry):
    if not entry:
        return False
    key = entry if isinstance(entry, str) else dedup_key(entry)
    if not key:
        return False
    return append({"via": "ui", "kind": TOMBSTONE, "forget": key})

def _forgotten(rows):
    return {str(r.get("forget") or "") for r in rows
            if (r.get("kind") or "") == TOMBSTONE and r.get("forget")}

def match_keys(r):
    keys = set()
    t = r.get("target")
    if t:
        base = str(t).replace("/", "\\").rsplit("\\", 1)[-1]
        if base:
            keys.add(base.lower())
            if "." in base:
                keys.add(base.rsplit(".", 1)[0].lower())
    cwd = r.get("cwd")
    if cwd:
        seg = str(cwd).rstrip("\\/").replace("/", "\\").rsplit("\\", 1)[-1]
        if seg:
            keys.add(seg.lower())
    return keys

def find_recent(name):
    want = str(name or "").strip().lower()
    if not want:
        return None
    for r in recent_unique():
        if want in match_keys(r):
            return r
    return None

def _entry_from(inv, result=None, state=None):
    entry = {
        "via": inv.get("via", "cli"),
        "kind": inv.get("kind"),
        "id": inv.get("id"),
        "target": inv.get("target"),
        "cwd": inv.get("cwd"),
        "runner": inv.get("runner"),
        "args": inv.get("args") or [],
        "params": inv.get("params") or {},
    }
    if result is not None:
        entry["exit"] = result.get("exit")
        entry["ms"] = result.get("ms")
    if state:
        entry["state"] = state
    return entry

def on_before_run(payload):
    inv = (payload or {}).get("invocation") or {}
    if not should_record(inv):
        return None
    return append(_entry_from(inv, state="start"))

def on_after_run(payload):
    inv = (payload or {}).get("invocation") or {}
    if not should_record(inv):
        return None
    return append(_entry_from(inv, result=(payload or {}).get("result") or {}))
