import json
import os
import re
import shutil
import sqlite3
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E

_LOCK = threading.RLock()
SCHEMA = 1
EVENT_CHUNK = 60000


def db_path():
    return E.user_data() / "ai" / "history.sqlite"


def _connect():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(p), timeout=20)
    con.row_factory = sqlite3.Row
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.DatabaseError:
        pass
    _init(con)
    return con


def _init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS runs(
      run_id TEXT PRIMARY KEY,
      parent_run_id TEXT,
      handoff_from TEXT,
      pkg_id TEXT,
      workdir TEXT,
      task TEXT,
      summary TEXT,
      caveats TEXT,
      decisions TEXT,
      next_steps TEXT,
      handoff TEXT,
      ok INTEGER,
      kind TEXT,
      status TEXT,
      model TEXT,
      started REAL,
      finished REAL,
      started_text TEXT,
      snapshot_id TEXT,
      files TEXT,
      usage TEXT,
      broad INTEGER DEFAULT 1,
      access TEXT,
      indexed REAL
    );
    CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      run_id TEXT NOT NULL,
      seq INTEGER NOT NULL,
      chunk INTEGER NOT NULL DEFAULT 0,
      role TEXT,
      tool TEXT,
      kind TEXT,
      content TEXT,
      chars INTEGER,
      UNIQUE(run_id, seq, chunk)
    );
    CREATE INDEX IF NOT EXISTS idx_events_run ON events(run_id, seq);
    CREATE INDEX IF NOT EXISTS idx_runs_pkg ON runs(pkg_id, started);
    CREATE INDEX IF NOT EXISTS idx_runs_workdir ON runs(workdir, started);
    CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
      content,
      content='events',
      content_rowid='id',
      tokenize='trigram'
    );
    CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
      INSERT INTO events_fts(rowid, content) VALUES (new.id, new.content);
    END;
    CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
      INSERT INTO events_fts(events_fts, rowid, content) VALUES ('delete', old.id, old.content);
    END;
    CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
      INSERT INTO events_fts(events_fts, rowid, content) VALUES ('delete', old.id, old.content);
      INSERT INTO events_fts(rowid, content) VALUES (new.id, new.content);
    END;
    """)
    have = {str(r[1]) for r in con.execute("PRAGMA table_info(runs)").fetchall()}
    if "broad" not in have:
        con.execute("ALTER TABLE runs ADD COLUMN broad INTEGER DEFAULT 1")
    if "access" not in have:
        con.execute("ALTER TABLE runs ADD COLUMN access TEXT")
    con.commit()


def _redact(text):
    """给模型看的历史片段做最小脱敏；本地 UI 仍可看原文。"""
    text = str(text or "")
    text = re.sub(r"\b(sk-[A-Za-z0-9_-]{4,})", "sk-***", text)
    text = re.sub(r"\b(gh[pousr]_[A-Za-z0-9]{8,})", "***", text)
    text = re.sub(r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|password|secret)"
                  r"(\s*[:=]\s*)([^\s,;\"']{6,})", r"\1\2***", text)
    text = re.sub(r"(?i)\b(bearer\s+)([A-Za-z0-9._~-]{12,})", r"\1***", text)
    return text


def _like_escape(text):
    return str(text or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _is_broad_rec(rec):
    access = (rec or {}).get("access")
    if not isinstance(access, dict):
        return True
    return bool(access.get("full") or access.get("broad"))


def _as_text(content):
    if isinstance(content, list):
        bits = []
        for part in content:
            if not isinstance(part, dict):
                continue
            typ = str(part.get("type") or "")
            if typ == "text":
                bits.append(str(part.get("text") or ""))
            elif typ == "image_url":
                bits.append("[图片]")
            elif typ:
                bits.append("[" + typ + "]")
        return "\n".join(bits)
    return str(content or "")


def _clip(v, cap):
    text = str(v or "")
    return text if len(text) <= cap else text[:cap] + "\n……（档案索引已截断；原始记录仍完整）"


def _chunks(text, size=EVENT_CHUNK):
    text = str(text or "")
    if not text:
        return [""]
    out = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            cut = text.rfind("\n", start + int(size * 0.6), end)
            if cut > start:
                end = cut + 1
        out.append(text[start:end])
        start = end
    return out or [""]


def _summary_text(rec, handoff):
    bits = []
    if rec.get("task"):
        bits.append("任务：" + str(rec.get("task")))
    for key, label in (("summary", "结果"), ("caveats", "注意"),
                       ("decisions", "关键决定"), ("next_steps", "后续")):
        if handoff.get(key):
            bits.append(label + "：" + str(handoff.get(key)))
    files = [str(x) for x in (handoff.get("files") or [])]
    if files:
        bits.append("文件：" + "、".join(files[:40]))
    for v in (handoff.get("verification") or []):
        bits.append(("验证成功：" if v.get("ok") else "验证失败：") +
                    str(v.get("args") or "")[:220] + " → " + str(v.get("out") or "")[:160])
    return "\n".join(bits)


def _event_bases(rec):
    """把一条 run 拆成可读事件；seq 仍是原 messages 下标。"""
    messages = [m for m in (rec.get("messages") or []) if isinstance(m, dict)]
    tool_by_id = {}
    out = []
    for seq, m in enumerate(messages):
        role = str(m.get("role") or "")
        if role == "system":
            continue
        text = _as_text(m.get("content"))
        tool = ""
        kind = role or "message"
        if role == "assistant":
            calls = m.get("tool_calls") or []
            bits = []
            names = []
            for c in calls:
                if not isinstance(c, dict):
                    continue
                fn = c.get("function") or {}
                name = str(fn.get("name") or "")
                args = fn.get("arguments")
                if args is None:
                    args = ""
                if name:
                    names.append(name)
                    tool_by_id[str(c.get("id") or "")] = name
                bits.append("工具调用 %s：%s" % (name or "?", _clip(args, 20000)))
            if names:
                tool = "、".join(dict.fromkeys(names))
                kind = "tool_call"
            if bits:
                text = (text + "\n" if text else "") + "\n".join(bits)
        elif role == "tool":
            tool = tool_by_id.get(str(m.get("tool_call_id") or ""), "")
            kind = "tool_result"
        elif role == "user":
            kind = "user"
        if text or tool:
            out.append({"seq": seq, "role": role or "?", "tool": tool,
                        "kind": kind, "text": text})
    # 原始轨迹已按保留策略清理：只保留摘要，不再把步骤当对话回放
    if rec.get("trace_deleted"):
        return []
    # 老记录/问答记录可能没有 messages，但 UI 步骤还在：也收进档案
    if not out:
        for i, s in enumerate(rec.get("steps") or []):
            if not isinstance(s, dict):
                continue
            text = "\n".join(str(s.get(k) or "") for k in ("brief", "why", "args", "out") if s.get(k))
            out.append({"seq": 100000 + i, "role": "step",
                        "tool": str(s.get("tool") or ""), "kind": "step",
                        "text": text})
    return out


def _scope_filter(rec, workdir="", all_scope=False):
    if all_scope:
        return True
    wd = str(workdir or "")
    rwd = str((rec or {}).get("workdir") or "")
    try:
        import ai_runs as R
        pid = R.pkg_of(wd)
        if pid and R.pkg_of(rwd) == pid:
            return True
    except Exception:
        pass
    if wd:
        try:
            return os.path.normcase(os.path.realpath(rwd)) == \
                   os.path.normcase(os.path.realpath(wd))
        except OSError:
            return rwd == wd
    return False


def index_run(rec):
    if not isinstance(rec, dict) or not rec.get("id"):
        return {"ok": False, "msg": "没有 run_id"}
    rec = dict(rec)
    import ai_runs as R
    rid = str(rec.get("id") or "")
    try:
        pid = R.pkg_of(rec.get("workdir") or "")
    except Exception:
        pid = ""
    handoff = rec.get("handoff") if isinstance(rec.get("handoff"), dict) else R.make_handoff(rec)
    parent = str(rec.get("continued_from") or rec.get("handoff_from") or "")
    access = rec.get("access") if isinstance(rec.get("access"), dict) else None
    broad = 1 if (not access or access.get("full") or access.get("broad")) else 0
    summary_event = {
        "seq": -1, "role": "summary", "tool": "",
        "kind": "handoff", "text": _summary_text(rec, handoff),
    }
    bases = [summary_event] + _event_bases(rec)
    now = time.time()
    with _LOCK:
        con = _connect()
        try:
            con.execute("DELETE FROM events WHERE run_id=?", (rid,))
            con.execute("DELETE FROM runs WHERE run_id=?", (rid,))
            con.execute("""
                INSERT INTO runs(run_id,parent_run_id,handoff_from,pkg_id,workdir,task,summary,
                                 caveats,decisions,next_steps,handoff,ok,kind,status,model,
                                 started,finished,started_text,snapshot_id,files,usage,
                                 broad,access,indexed)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (rid, parent, str(rec.get("handoff_from") or ""), pid,
                  str(rec.get("workdir") or ""), str(rec.get("task") or ""),
                  str(rec.get("summary") or ""), str(rec.get("caveats") or ""),
                  str(rec.get("decisions") or ""), str(rec.get("next_steps") or ""),
                  json.dumps(handoff, ensure_ascii=False),
                  int(bool(rec.get("ok"))), str(rec.get("kind") or "work"),
                  "done" if not rec.get("running") else "running",
                  str(rec.get("model") or ""),
                  float(rec.get("started") or 0), float(rec.get("finished") or 0),
                  str(rec.get("started_text") or ""),
                  str((rec.get("snapshot") or {}).get("id") or "") if isinstance(rec.get("snapshot"), dict) else "",
                  json.dumps(rec.get("files") or [], ensure_ascii=False),
                  json.dumps(rec.get("usage") or {}, ensure_ascii=False),
                  broad, json.dumps(access or {}, ensure_ascii=False), now))
            for ev in bases:
                for ck, chunk in enumerate(_chunks(ev.get("text") or "")):
                    con.execute("""
                        INSERT INTO events(run_id,seq,chunk,role,tool,kind,content,chars)
                        VALUES(?,?,?,?,?,?,?,?)
                    """, (rid, int(ev.get("seq") or 0), ck, str(ev.get("role") or ""),
                          str(ev.get("tool") or ""), str(ev.get("kind") or ""),
                          chunk, len(chunk)))
            con.commit()
            return {"ok": True, "run_id": rid, "events": sum(len(_chunks(e.get("text") or "")) for e in bases)}
        except Exception as e:
            try:
                con.rollback()
            except Exception:
                pass
            return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}
        finally:
            con.close()


def sync(workdir="", limit=1000, all_scope=False, force=False):
    """把尚未建索引的已结束 run 补进档案。

    - 最多处理 limit 条，避免第一次搜索把界面卡死；
    - 同一 scope 20 秒内不重复扫描（新结束的 run 在保存时已即时索引）。
    """
    try:
        import ai_runs as R
        try:
            R.migrate_once()
        except Exception:
            pass
        pkg_id = ""
        try:
            pkg_id = "" if all_scope else R.pkg_of(workdir)
        except Exception:
            pkg_id = ""
        key = "sync:" + ("all" if all_scope else (pkg_id or str(workdir or "")))
        now = time.time()
        with _LOCK:
            con = _connect()
            try:
                row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
                if row and not force and now - float(row[0] or 0) < 20:
                    return {"ok": True, "indexed": 0, "todo": 0, "skipped": True}
            finally:
                con.close()
        scope = None if all_scope else R.scope_of(workdir)
        recs = R.raw_records(scope=scope, limit=limit, everywhere=bool(all_scope),
                             with_trace=True)
        with _LOCK:
            con = _connect()
            try:
                have = {str(x[0]) for x in con.execute("SELECT run_id FROM runs").fetchall()}
            finally:
                con.close()
        todo = [r for r in recs if str(r.get("id") or "") not in have
                and not r.get("running") and isinstance(r.get("messages"), list)]
        n = 0
        for rec in reversed(todo):
            got = index_run(rec)
            if got.get("ok"):
                n += 1
        with _LOCK:
            con = _connect()
            try:
                con.execute("INSERT INTO meta(key,value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                            (key, str(now)))
                con.commit()
            finally:
                con.close()
        return {"ok": True, "indexed": n, "todo": len(todo)}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


def _fts_expr(q):
    q = str(q or "").strip()
    terms = [t for t in re.split(r"\s+", q) if t]
    terms = [t for t in terms if len(t) >= 3]
    if not terms:
        return ""
    return " AND ".join('"%s"' % t.replace('"', '""') for t in terms)


def _snippet_like(text, q, width=150):
    text = str(text or "")
    needle = str(q or "")
    i = text.lower().find(needle.lower()) if needle else -1
    if i < 0:
        return _clip(text, width)
    a = max(0, i - width // 2)
    b = min(len(text), i + len(needle) + width // 2)
    return ("…" if a else "") + text[a:b] + ("…" if b < len(text) else "")


def search(query="", workdir="", limit=8, tool="", run_id="", all_scope=False,
           max_chars=220, allow_broad=False, redact=False):
    q = str(query or "").strip()
    if not q:
        return {"ok": True, "hits": [], "msg": "关键词是空的"}
    try:
        sync(workdir, limit=1000, all_scope=all_scope)
    except Exception:
        pass
    import ai_runs as R
    pkg_id = ""
    try:
        pkg_id = R.pkg_of(workdir)
    except Exception:
        pass
    where, params = [], []
    if not allow_broad:
        where.append("r.broad=0")
    if not all_scope:
        if pkg_id:
            where.append("r.pkg_id=?")
            params.append(pkg_id)
        elif workdir:
            where.append("r.workdir=?")
            params.append(str(workdir))
    if tool:
        where.append("e.tool=?")
        params.append(str(tool))
    if run_id:
        where.append("e.run_id=?")
        params.append(str(run_id))
    try:
        con = _connect()
        try:
            expr = _fts_expr(q)
            rows = []
            if expr:
                sql = """
                  SELECT e.id,e.run_id,e.seq,e.chunk,e.role,e.tool,e.kind,r.task,r.pkg_id,
                         r.started_text,r.ok,r.kind AS run_kind,
                         snippet(events_fts,0,'[[',']]','…',24) AS snip,
                         bm25(events_fts) AS score
                    FROM events_fts
                    JOIN events e ON e.id=events_fts.rowid
                    JOIN runs r ON r.run_id=e.run_id
                   WHERE events_fts MATCH ?%s
                   ORDER BY score LIMIT ?
                """ % ((" AND " + " AND ".join(where)) if where else "")
                try:
                    rows = con.execute(sql, [expr] + params + [max(1, int(limit or 8))]).fetchall()
                except sqlite3.Error:
                    rows = []
            if not rows:
                sql = """
                  SELECT e.id,e.run_id,e.seq,e.chunk,e.role,e.tool,e.kind,r.task,r.pkg_id,
                         r.started_text,r.ok,r.kind AS run_kind,
                         e.content AS snip, 0.0 AS score
                    FROM events e JOIN runs r ON r.run_id=e.run_id
                   WHERE (r.task LIKE ? ESCAPE '\\' OR r.summary LIKE ? ESCAPE '\\'
                          OR e.content LIKE ? ESCAPE '\\')%s
                   ORDER BY e.id DESC LIMIT ?
                """ % ((" AND " + " AND ".join(where)) if where else "")
                like = "%" + _like_escape(q) + "%"
                rows = con.execute(sql, [like, like, like] + params + [max(1, int(limit or 8))]).fetchall()
            hits = []
            for row in rows:
                snip = str(row["snip"] or "")
                if "[[" not in snip:
                    snip = _snippet_like(snip, q, max_chars)
                else:
                    snip = _clip(snip, max_chars)
                if redact:
                    snip = _redact(snip)
                hits.append({
                    "run_id": str(row["run_id"] or ""),
                    "seq": int(row["seq"] or 0),
                    "chunk": int(row["chunk"] or 0),
                    "role": str(row["role"] or ""),
                    "tool": str(row["tool"] or ""),
                    "kind": str(row["kind"] or ""),
                    "task": _redact(row["task"]) if redact else str(row["task"] or ""),
                    "pkg_id": str(row["pkg_id"] or ""),
                    "started_text": str(row["started_text"] or ""),
                    "run_ok": bool(row["ok"]),
                    "run_kind": str(row["run_kind"] or "work"),
                    "snippet": snip,
                })
            return {"ok": True, "hits": hits, "query": q, "count": len(hits),
                    "scope": {"pkg_id": pkg_id, "all": bool(all_scope)}}
        finally:
            con.close()
    except Exception as e:
        return {"ok": False, "hits": [], "msg": "%s: %s" % (type(e).__name__, e)}


def open_run(run_id="", workdir="", seq=0, before=3, after=3,
             max_chars=8000, all_scope=False, allow_broad=False, redact=False):
    try:
        import ai_runs as R
        rec = R.get(str(run_id or ""))
        if not rec:
            return {"ok": False, "msg": "没有这条记录"}
        if not _scope_filter(rec, workdir, all_scope):
            return {"ok": False, "msg": "这条记录不在当前工作区的检索范围里"}
        if not allow_broad and _is_broad_rec(rec):
            return {"ok": False,
                    "msg": "这条记录来自更大的权限范围；当前权限下只能看摘要，不能展开原始轨迹"}
        handoff = rec.get("handoff") if isinstance(rec.get("handoff"), dict) else R.make_handoff(rec)
        _run_task = _redact(rec.get("task")) if redact else str(rec.get("task") or "")
        _run_summary = _redact(rec.get("summary")) if redact else str(rec.get("summary") or "")
        _run_caveats = _redact(rec.get("caveats")) if redact else str(rec.get("caveats") or "")
        run_obj = {
            "id": rec.get("id") or "", "task": _run_task,
            "started_text": rec.get("started_text") or "",
            "ok": bool(rec.get("ok")), "kind": rec.get("kind") or "work",
            "summary": _run_summary, "caveats": _run_caveats,
            "workdir": rec.get("workdir") or "", "handoff": handoff,
            "files": rec.get("files") or [],
            "trace_deleted": bool(rec.get("trace_deleted") or
                                  (rec.get("has_trace") is False and not rec.get("messages"))),
        }
        bases = [e for e in _event_bases(rec) if int(e.get("seq") or 0) >= 0]
        if not bases:
            return {"ok": True, "run": run_obj, "events": [], "seq": 0, "hit_seq": 0,
                    "more_before": False, "more_after": False, "chars": 0,
                    "trace_deleted": bool(run_obj.get("trace_deleted")),
                    "msg": "原始轨迹已清理；这条记录只剩摘要和元数据"}
        want = int(seq or 0)
        pos = min(range(len(bases)), key=lambda i: abs(int(bases[i].get("seq") or 0) - want))
        a = max(0, pos - max(0, int(before or 0)))
        b = min(len(bases), pos + max(0, int(after or 0)) + 1)
        picked = bases[a:b]
        total = 0
        events = []
        for ev in picked:
            text = str(ev.get("text") or "")
            remain = max(0, int(max_chars or 8000) - total)
            if remain <= 0:
                break
            truncated = len(text) > remain
            text = text[:remain]
            total += len(text)
            if redact:
                text = _redact(text)
            events.append({"seq": int(ev.get("seq") or 0), "role": ev.get("role") or "",
                           "tool": ev.get("tool") or "", "kind": ev.get("kind") or "",
                           "text": text, "truncated": truncated})
        handoff = rec.get("handoff") if isinstance(rec.get("handoff"), dict) else R.make_handoff(rec)
        return {"ok": True, "run": run_obj, "events": events,
                "seq": int(picked[0].get("seq") or 0),
            "hit_seq": int(bases[pos].get("seq") or 0),
            "more_before": a > 0, "more_after": b < len(bases),
            "chars": total}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


def settings_path():
    return E.user_data() / "ai" / "history.json"


def load_settings():
    cur = {"max_mb": 20480, "auto_clean": False}
    try:
        p = settings_path()
        if p.is_file():
            got = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(got, dict):
                try:
                    cur["max_mb"] = max(0, min(100000000, int(got.get("max_mb", cur["max_mb"]))))
                except (TypeError, ValueError):
                    pass
                cur["auto_clean"] = bool(got.get("auto_clean", False))
                if cur["max_mb"] <= 0:
                    cur["auto_clean"] = False
    except Exception:
        pass
    return cur


def save_settings(max_mb=20480, auto_clean=False):
    try:
        mb = max(0, min(100000000, int(max_mb or 0)))
    except (TypeError, ValueError):
        return {"ok": False, "msg": "上限要是整数 MB"}
    cur = {"max_mb": mb, "auto_clean": bool(auto_clean) if mb > 0 else False}
    try:
        p = settings_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(cur, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        os.replace(tmp, p)
        return dict(cur, ok=True, path=str(p))
    except OSError as e:
        return {"ok": False, "msg": "存不下来：%s" % e}


def _run_files():
    import ai_runs as R
    out = []
    for d in R.all_dirs():
        if not d.is_dir():
            continue
        out.extend(d.glob("*.json"))
    return out


def _trace_files():
    import ai_runs as R
    out = []
    for d in R.all_dirs():
        td = R.trace_dir_for(d)
        if td.is_dir():
            out.extend(td.glob("*.jsonl.gz"))
    return out


def _db_files():
    p = db_path()
    return [p, Path(str(p) + "-wal"), Path(str(p) + "-shm")]


def _size_of(paths):
    n = 0
    for p in paths:
        try:
            if Path(p).is_file():
                n += Path(p).stat().st_size
        except OSError:
            pass
    return n


def compact_db():
    try:
        p = db_path()
        if not p.is_file():
            return
        con = sqlite3.connect(str(p), timeout=20)
        try:
            try:
                con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.DatabaseError:
                pass
            try:
                con.execute("INSERT INTO events_fts(events_fts) VALUES('optimize')")
                con.commit()
            except sqlite3.DatabaseError:
                pass
            try:
                con.execute("PRAGMA journal_mode=DELETE")
            except sqlite3.DatabaseError:
                pass
            con.execute("VACUUM")
            try:
                con.execute("PRAGMA journal_mode=WAL")
            except sqlite3.DatabaseError:
                pass
            con.commit()
        finally:
            con.close()
    except Exception:
        pass


def stats():
    try:
        import ai_runs as R
        try:
            R.migrate_once()
        except Exception:
            pass
        runs = _run_files()
        traces = _trace_files()
        db = _db_files()
        run_b = _size_of(runs)
        trace_b = _size_of(traces)
        db_b = _size_of(db)
        total = run_b + trace_b + db_b
        try:
            du = shutil.disk_usage(str(E.user_data()))
            free_b = int(du.free)
        except OSError:
            free_b = 0
        st = load_settings()
        return {"ok": True, "runs": len(runs), "traces": len(traces),
                "run_bytes": run_b, "trace_bytes": trace_b, "db_bytes": db_b,
                "total_bytes": total, "free_bytes": free_b,
                "max_mb": int(st.get("max_mb") or 0),
                "auto_clean": bool(st.get("auto_clean")),
                "run_mb": round(run_b / 1048576.0, 2),
                "trace_mb": round(trace_b / 1048576.0, 2),
                "db_mb": round(db_b / 1048576.0, 2),
                "total_mb": round(total / 1048576.0, 2),
                "free_mb": round(free_b / 1048576.0, 2),
                "path": str(E.user_data() / "ai"), "db": str(db_path())}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


def migrate_traces():
    """把旧版内嵌 messages 的 run JSON 拆成 metadata + traces。"""
    try:
        import ai_runs as R
        n = 0
        for p in _run_files():
            try:
                if R.split_trace_file(p):
                    n += 1
            except Exception:
                continue
        return {"ok": True, "migrated": n}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


CLEAN_TO_RATIO = 0.8


def clean(target_mb=None, dry_run=False, force=False):
    """按总占用上限清理最旧的原始轨迹；摘要和 run metadata 永远保留。

    超过上限时清理到上限的 80%，形成水位差，避免每跑一次就触发一点清理。
    """
    try:
        import ai_runs as R
        st = load_settings()
        try:
            limit = int(target_mb if target_mb is not None else (st.get("max_mb") or 0))
        except (TypeError, ValueError):
            limit = int(st.get("max_mb") or 0)
        if limit <= 0:
            return {"ok": False, "msg": "没有设置档案上限（0 = 不限）"}
        target = max(1, int(limit * CLEAN_TO_RATIO))
        before = stats()
        if not before.get("ok"):
            return before
        # 旧 run 先迁移，否则 run JSON 里的 messages 无法单独清理
        migrate_traces()
        before = stats()
        if not before.get("ok"):
            return before
        limit_b = limit * 1048576
        target_b = target * 1048576
        if not force and before["total_bytes"] <= limit_b:
            return {"ok": True, "removed": 0, "bytes": 0,
                    "before_mb": before["total_mb"], "after_mb": before["total_mb"],
                    "limit_mb": limit, "target_mb": target,
                    "msg": "没有超过上限"}
        if before["total_bytes"] <= target_b:
            return {"ok": True, "removed": 0, "bytes": 0,
                    "before_mb": before["total_mb"], "after_mb": before["total_mb"],
                    "limit_mb": limit, "target_mb": target,
                    "msg": "已经低于清理水位"}
        # 按任务完成/开始时间从旧到新清；时间缺失才退回 trace 文件 mtime。
        run_paths = {str(p.stem): p for p in _run_files()}
        age = {}
        for rid, rp in run_paths.items():
            try:
                rec = json.loads(rp.read_text(encoding="utf-8"))
                age[rid] = float(rec.get("finished") or rec.get("started") or 0)
            except Exception:
                age[rid] = 0.0
        def _trace_key(tp):
            rid = tp.name[:-len(".jsonl.gz")] if tp.name.endswith(".jsonl.gz") else tp.name
            old = age.get(rid) or 0.0
            try:
                mt = tp.stat().st_mtime if old <= 0 else 0.0
            except OSError:
                mt = 0.0
            return (old or mt, tp.name)
        traces = sorted(_trace_files(), key=_trace_key)
        removed, freed = 0, 0
        current = before["total_bytes"]
        candidates = []
        for tp in traces:
            try:
                sz = tp.stat().st_size
            except OSError:
                continue
            if current <= target_b:
                break
            candidates.append((tp, sz))
            current -= sz
        if dry_run:
            return {"ok": True, "dry_run": True, "removed": len(candidates),
                    "bytes": sum(x[1] for x in candidates),
                    "before_mb": before["total_mb"],
                    "after_mb": round(max(0, current) / 1048576.0, 2)}
        for tp, sz in candidates:
            rid = tp.name[:-len(".jsonl.gz")]
            rp = run_paths.get(rid)
            try:
                tp.unlink(missing_ok=True)
                if rp and rp.is_file():
                    rec = json.loads(rp.read_text(encoding="utf-8"))
                    if isinstance(rec, dict):
                        rec["has_trace"] = False
                        rec["trace_deleted"] = True
                        rec["trace_deleted_at"] = time.time()
                        rec["trace"] = {"file": tp.name, "deleted": True,
                                        "bytes": sz, "at": time.time()}
                        rec.pop("messages", None)
                        R.write_meta(rp, rec)
                        try:
                            forget(rid)
                            index_run(rec)
                        except Exception:
                            pass
                removed += 1
                freed += sz
            except OSError:
                continue
        if removed:
            with _LOCK:
                compact_db()
        after = stats()
        return {"ok": True, "removed": removed, "bytes": freed,
                "before_mb": before["total_mb"],
                "after_mb": after.get("total_mb", before["total_mb"]),
                "limit_mb": limit, "target_mb": target}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


def rebuild():
    try:
        import ai_runs as R
        migrate_traces()
        files = _run_files()
        clear(all_scope=True)
        n = 0
        for p in files:
            try:
                rec = R.get(p.stem)
                if rec:
                    index_run(rec)
                    n += 1
            except Exception:
                continue
        return {"ok": True, "indexed": n, "runs": len(files)}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


def forget(run_id=""):
    rid = str(run_id or "")
    if not rid:
        return {"ok": False, "msg": "没有 run_id"}
    try:
        with _LOCK:
            con = _connect()
            try:
                con.execute("DELETE FROM events WHERE run_id=?", (rid,))
                con.execute("DELETE FROM runs WHERE run_id=?", (rid,))
                con.commit()
            finally:
                con.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


def clear(workdir="", all_scope=False):
    try:
        import ai_runs as R
        pkg_id = ""
        if not all_scope:
            try:
                pkg_id = R.pkg_of(workdir)
            except Exception:
                pkg_id = ""
        with _LOCK:
            con = _connect()
            try:
                if all_scope:
                    con.execute("DELETE FROM events")
                    con.execute("DELETE FROM runs")
                elif pkg_id:
                    ids = [x[0] for x in con.execute("SELECT run_id FROM runs WHERE pkg_id=?", (pkg_id,))]
                    for rid in ids:
                        con.execute("DELETE FROM events WHERE run_id=?", (rid,))
                    con.execute("DELETE FROM runs WHERE pkg_id=?", (pkg_id,))
                elif workdir:
                    ids = [x[0] for x in con.execute("SELECT run_id FROM runs WHERE workdir=?", (str(workdir),))]
                    for rid in ids:
                        con.execute("DELETE FROM events WHERE run_id=?", (rid,))
                    con.execute("DELETE FROM runs WHERE workdir=?", (str(workdir),))
                con.commit()
            finally:
                con.close()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}
