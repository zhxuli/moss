import json
import os
import re
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
      indexed REAL
    );
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
    con.commit()


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
    return True


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
                                 started,finished,started_text,snapshot_id,files,usage,indexed)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                  json.dumps(rec.get("usage") or {}, ensure_ascii=False), now))
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


def sync(workdir="", limit=120, all_scope=False):
    """把尚未建索引的已结束 run 补进档案。只在需要搜索时做，最多处理 limit 条。"""
    try:
        import ai_runs as R
        try:
            R.migrate_once()
        except Exception:
            pass
        scope = None if all_scope else R.scope_of(workdir)
        recs = R.raw_records(scope=scope, limit=limit, everywhere=bool(all_scope))
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
           max_chars=220):
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
                   WHERE (r.task LIKE ? OR r.summary LIKE ? OR e.content LIKE ?)%s
                   ORDER BY e.id DESC LIMIT ?
                """ % ((" AND " + " AND ".join(where)) if where else "")
                like = "%" + q + "%"
                rows = con.execute(sql, [like, like, like] + params + [max(1, int(limit or 8))]).fetchall()
            hits = []
            for row in rows:
                snip = str(row["snip"] or "")
                if "[[" not in snip:
                    snip = _snippet_like(snip, q, max_chars)
                else:
                    snip = _clip(snip, max_chars)
                hits.append({
                    "run_id": str(row["run_id"] or ""),
                    "seq": int(row["seq"] or 0),
                    "chunk": int(row["chunk"] or 0),
                    "role": str(row["role"] or ""),
                    "tool": str(row["tool"] or ""),
                    "kind": str(row["kind"] or ""),
                    "task": str(row["task"] or ""),
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
             max_chars=8000, all_scope=False):
    try:
        import ai_runs as R
        rec = R.get(str(run_id or ""))
        if not rec:
            return {"ok": False, "msg": "没有这条记录"}
        if not _scope_filter(rec, workdir, all_scope):
            return {"ok": False, "msg": "这条记录不在当前工作区的检索范围里"}
        bases = [e for e in _event_bases(rec) if int(e.get("seq") or 0) >= 0]
        if not bases:
            return {"ok": False, "msg": "这条记录没有可读的对话事件（可能太旧）"}
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
            text = text[:remain]
            total += len(text)
            events.append({"seq": int(ev.get("seq") or 0), "role": ev.get("role") or "",
                           "tool": ev.get("tool") or "", "kind": ev.get("kind") or "",
                           "text": text})
        handoff = rec.get("handoff") if isinstance(rec.get("handoff"), dict) else R.make_handoff(rec)
        return {"ok": True, "run": {
            "id": rec.get("id") or "", "task": rec.get("task") or "",
            "started_text": rec.get("started_text") or "",
            "ok": bool(rec.get("ok")), "kind": rec.get("kind") or "work",
            "summary": rec.get("summary") or "", "caveats": rec.get("caveats") or "",
            "workdir": rec.get("workdir") or "", "handoff": handoff,
            "files": rec.get("files") or [],
        }, "events": events, "seq": int(picked[0].get("seq") or 0),
            "hit_seq": int(bases[pos].get("seq") or 0),
            "more_before": a > 0, "more_after": b < len(bases),
            "chars": total}
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
