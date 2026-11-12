import json
import os
import shlex
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

MAX_SHOW = 20
READ_RAW = 5000

TOMBSTONE = "tombstone"
SKIP_KINDS = ("pkg", TOMBSTONE)

def _user_data():
    d = (os.environ.get("MOSS_USER_DATA_DIR") or "").strip()
    if d:
        return Path(d)
    home = (os.environ.get("MOSS_HOME") or "").strip()
    if home:
        p = Path(home) / "user_data"
        if p.is_dir():
            return p
    return Path(__file__).resolve().parents[2]

def _history_dir():
    d = (os.environ.get("MOSS_HISTORY_DIR") or "").strip()
    if d:
        return Path(d)
    return _user_data() / "history"

def _dedup_key(r):
    return "|".join([
        str(r.get("kind") or ""),
        str(r.get("id") or r.get("target") or ""),
        json.dumps(r.get("params") or {}, sort_keys=True, ensure_ascii=False),
        json.dumps(r.get("args") or [], ensure_ascii=False),
    ])

def _raw_rows(limit=READ_RAW):
    rows = []
    try:
        files = sorted(_history_dir().glob("*.jsonl"), reverse=True)
    except OSError:
        return rows
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not isinstance(r, dict):
                continue
            rows.append(r)
            if len(rows) >= limit:
                return rows
    return rows

def recent_rows(limit=MAX_SHOW):
    rows = _raw_rows()
    dead = {str(r.get("forget") or "") for r in rows
            if (r.get("kind") or "") == TOMBSTONE and r.get("forget")}
    rows = [r for r in rows
            if (r.get("kind") or "") not in SKIP_KINDS
            and r.get("target")
            and _dedup_key(r) not in dead]
    rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    seen, out = set(), []
    for r in rows:
        k = _dedup_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out[:limit]

def _segments(p):
    return [s for s in str(p or "").replace("\\", "/").split("/") if s]

def _leaf(target):
    return str(target or "").replace("\\", "/").rsplit("/", 1)[-1]

def _chain(rec):
    segs = _segments(rec.get("cwd"))
    leaf = _leaf(rec.get("target"))
    if leaf:
        segs.append(leaf)
    return segs

def _alignment(qsegs, chain):
    n = len(qsegs)
    if n == 0 or len(chain) < n:
        return None
    best = None
    for i in range(len(chain) - n + 1):
        exact = 0
        ok = True
        for j in range(n):
            q = qsegs[j].lower()
            c = chain[i + j].lower()
            if not c.startswith(q):
                ok = False
                break
            if c == q:
                exact += 1
        if not ok:
            continue
        key = (1 if i + n == len(chain) else 0, exact, i)
        if best is None or key > best:
            best = key
    return best

def find(rows, query):
    qsegs = _segments(query)
    if not qsegs:
        return []
    hits = []
    for r in rows:
        key = _alignment(qsegs, _chain(r))
        if key is None:
            continue
        alive = 1 if (os.path.isfile(str(r.get("target") or ""))
                      and os.path.isdir(str(r.get("cwd") or ""))) else 0
        hits.append((alive,) + key + (str(r.get("ts") or ""), r))
    hits.sort(key=lambda x: x[:-1], reverse=True)
    return [x[-1] for x in hits]

def _width(s):
    w = 0
    for ch in str(s):
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1
    return w

def _pad(s, n):
    s = str(s)
    room = n - _width(s)
    if room <= 0:
        return s
    return s + " " * room

def _try(s, n):
    out, w = "", 0
    for ch in str(s):
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1
        if w + cw > n:
            break
        out += ch
        w += cw
    return out

def _hhmmss(rec):
    ts = str(rec.get("ts") or "")
    return ts[11:19] if len(ts) >= 19 else ts

def _where(rec):
    cwd = str(rec.get("cwd") or "-")
    args = " ".join(str(a) for a in (rec.get("args") or []))
    tail = ("  " + args) if args else ""
    return "%s%s      ← %s" % (_leaf(rec.get("target")) or "-", tail, cwd)

def print_list(rows, hint=True):
    if not rows:
        print("[信息] 还没有任何启动记录。先随便跑一个脚本，`moss :h` 就有东西了。")
        return 0
    print("最近 %d 条启动记录（已去重，同一件事只留最新一条）" % len(rows))
    for i, r in enumerate(rows, 1):
        line = "  %2d  %s  %s  %s" % (i, _hhmmss(r), _pad(_leaf(r.get("target")) or "-", 22),
                                      r.get("cwd") or "-")
        args = " ".join(str(a) for a in (r.get("args") or []))
        if args:
            line += "   " + _try(args, 40)
        print(line)
    if hint:
        print()
        print("直接敲名字就跑：moss :h <名字>     例：moss :h zeen / moss :h z/m")
        print("想用方向键挑：moss --history（或者 moss :h 后面什么都不加）")
    return 0

KEEP_ENV = ("MOSS_HOME", "MOSS_USER_DATA_DIR", "MOSS_HOST_CMD")

def _clean_env():
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("MOSS_") or k in KEEP_ENV}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env

def _parse_host_cmd(raw):
    try:
        v = json.loads(raw)
    except ValueError:
        v = None
    if isinstance(v, list) and v:
        cmd = [str(x) for x in v]
    elif isinstance(v, str) and v.strip():
        cmd = [v.strip()]
    elif os.path.exists(raw.strip('"')):
        cmd = [raw.strip('"')]
    else:
        try:
            cmd = [str(x) for x in shlex.split(raw, posix=True)]
        except ValueError:
            return None
    if not cmd:
        return None
    first = cmd[0].strip('"')
    cmd[0] = first
    if os.path.dirname(first):
        if not os.path.exists(first):
            return None
    elif not shutil.which(first):
        return None
    return cmd

def host_cmd():
    raw = (os.environ.get("MOSS_HOST_CMD") or "").strip()
    if raw:
        cmd = _parse_host_cmd(raw)
        if cmd:
            return cmd

    home = (os.environ.get("MOSS_HOME") or "").strip()
    if home:
        base = Path(home)
        for name in ("moss.exe", "moss.cmd", "moss.bat"):
            p = base / name
            if p.is_file():
                return [str(p)]
        p = base / "moss.py"
        if p.is_file():
            return [sys.executable, str(p)]

    found = shutil.which("moss")
    if found:
        return [found]
    return None

def _interactive():
    try:
        return bool(sys.stdout.isatty() and sys.stdin.isatty())
    except Exception:
        return False

def _call(argv, cwd=None):
    try:
        return subprocess.call(argv, cwd=cwd, env=_clean_env())
    except OSError as e:
        print("[错误] 起不来：%s" % e)
        print("       命令：%s" % " ".join('"%s"' % c for c in argv))
        return 2

def _write_result(payload):
    f = (os.environ.get("MOSS_RESULT_FILE") or "").strip()
    if not f:
        return
    try:
        Path(f).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass

def _show_history(rows):
    host = host_cmd()
    if host and _interactive():
        rc = _call(host + ["--history"])
        if rc == 0:
            return 0
    return print_list(rows)

def _run_cwd(rec):
    cwd = str(rec.get("cwd") or "")
    target = str(rec.get("target") or "")
    parent = os.path.dirname(os.path.abspath(target)) if target else cwd
    try:
        same = os.path.normcase(os.path.abspath(cwd)) == os.path.normcase(parent)
    except OSError:
        same = False
    if same:
        return cwd, None
    return parent, ("这条记录当时是「不切目录」跑的（moss /…）：目标不在 %s 里，"
                    "改用目标所在目录。" % cwd)

def _run_record(rec, extra):
    target = str(rec.get("target") or "")
    leaf = _leaf(target)
    args = [str(a) for a in (rec.get("args") or [])] + list(extra)
    cwd, note = _run_cwd(rec)

    argv = host_cmd()
    if not argv:
        print("[错误] 找不到 moss 宿主：既没有 MOSS_HOST_CMD，MOSS_HOME 下也没有 moss.exe。")
        print("       自己敲：cd /d \"%s\"" % cwd)
        print("               moss %s%s" % (leaf, (" " + " ".join(args)) if args else ""))
        return 2

    if note:
        print("[提示] %s" % note)
    print("[历史] %s  →  %s" % (leaf or "-", target))
    print("[目录] %s" % cwd)
    if args:
        print("[参数] %s" % " ".join(args))
    sys.stdout.flush()

    rc = _call(argv + [leaf] + args, cwd=cwd)
    _write_result({"query": "", "target": target, "cwd": cwd,
                   "runner": rec.get("runner") or "", "exit": rc})
    return rc

def main():
    params = {}
    try:
        params = json.loads(os.environ.get("MOSS_PKG_PARAMS") or "{}") or {}
    except ValueError:
        params = {}
    query = str(params.get("target") or "").strip()
    extra = str(params.get("extra") or "").split()

    rows = recent_rows()

    if not query:
        return _show_history(rows)

    hits = find(rows, query)
    if not hits:
        print("[错误] 历史里没有叫 '%s' 的记录。" % query)
        if rows:
            print("       最近跑过这些（`moss :h <名字>` 直接重跑其中一条）：")
            for r in rows[:5]:
                print("         %s" % _where(r))
        print("       ★ 只记**路径调用**（`moss zeen` 这种）；`moss :包名` 不进历史。")
        _write_result({"query": query, "target": "", "cwd": "", "runner": "", "exit": 1})
        return 1

    best = hits[0]
    target = str(best.get("target") or "")
    cwd = str(best.get("cwd") or "")

    if not os.path.isdir(cwd):
        print("[错误] 记录里的目录已经不在了：%s" % cwd)
        print("       目标：%s" % target)
        if len(hits) > 1:
            print("       还有 %d 条同名记录，试试把名字写细一点（moss :h z/m）。" % (len(hits) - 1))
        _write_result({"query": query, "target": target, "cwd": cwd, "runner": "", "exit": 1})
        return 1
    if not os.path.isfile(target):
        print("[错误] 目标文件已经不在了：%s" % target)
        if len(hits) > 1:
            print("       还有 %d 条同名记录，试试把名字写细一点（moss :h z/m）。" % (len(hits) - 1))
        _write_result({"query": query, "target": target, "cwd": cwd, "runner": "", "exit": 1})
        return 1

    if len(hits) > 1:
        print("[提示] '%s' 命中 %d 条，取最近的一条；想跑别的把名字写细一点："
              % (query, len(hits)))
        for r in hits[1:4]:
            print("         %s" % _where(r))

    rc = _run_record(best, extra)
    _write_result({"query": query, "target": target, "cwd": cwd,
                   "runner": best.get("runner") or "", "exit": rc})
    return rc

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[提示] 操作已取消。")
        sys.exit(130)
