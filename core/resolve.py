import json
from pathlib import Path

from . import config, paths, runners as runners_mod

DEFAULT_ENTRY_STEMS = ("main", "run", "app", "index")

def search_bases(cwd, depth=None):
    depth = config.max_parent_depth() if depth is None else depth
    cur = cwd.resolve()
    for _ in range(depth + 1):
        yield cur
        if cur.parent == cur:
            break
        cur = cur.parent

def _probe_for(base, target, rname, spec):
    return runners_mod.probe(rname, spec, {
        "cwd": str(base),
        "home": str(paths.HOME),
        "entry": str(target),
    })

def _marker_info(base, spec, depth):
    want = runners_mod.markers_of(spec)
    if not want:
        return None, []
    names, nearest = [], None
    for dist, d in enumerate(search_bases(base, depth)):
        for m in want:
            if (d / m).exists():
                names.append(m)
                if nearest is None or dist < nearest:
                    nearest = dist
    return nearest, sorted(set(names))

def collect(base, name, runners, depth):
    cands = []
    prefix = name.lower()
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return cands

    for entry in entries:
        if not entry.name.lower().startswith(prefix):
            continue

        if entry.is_file():
            rname, spec = runners_mod.by_ext(runners, entry.suffix)
            if not spec:
                continue
            probe = _probe_for(base, entry, rname, spec)
            if not probe["available"]:
                continue
            mdist, mhits = _marker_info(base, spec, depth)
            cands.append({
                "path": entry, "runner": rname, "spec": spec,
                "probe": probe, "base": base, "from_dir": None,
                "marker_hits": mhits, "marker_dist": mdist,
            })

        elif entry.is_dir():
            try:
                inner = sorted(entry.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            for f in inner:
                if not f.is_file() or f.stem.lower() not in DEFAULT_ENTRY_STEMS:
                    continue
                rname, spec = runners_mod.by_ext(runners, f.suffix)
                if not spec:
                    continue
                probe = _probe_for(entry, f, rname, spec)
                if not probe["available"]:
                    continue
                mdist, mhits = _marker_info(entry, spec, depth)
                cands.append({
                    "path": f, "runner": rname, "spec": spec,
                    "probe": probe, "base": entry, "from_dir": entry.name,
                    "marker_hits": mhits, "marker_dist": mdist,
                })
    return cands

def _memory_file(base):
    return paths.resolve_dir_for(str(base.resolve())) / "choices.json"

def load_memory(base):
    f = _memory_file(base)
    if f.is_file():
        try:
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}

def save_memory(base, name, chosen_name):
    paths.ensure_user_dirs()
    d = _memory_file(base).parent
    d.mkdir(parents=True, exist_ok=True)
    mem = load_memory(base)
    mem[name.lower()] = chosen_name
    with open(_memory_file(base), "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)

class Aborted(Exception):
    pass

def _describe(c, root=None):
    label = c["path"].name
    if root is not None:
        try:
            rel = c["base"].resolve().relative_to(Path(root).resolve())
            if str(rel) not in (".", ""):
                label = "%s\\%s" % (rel, label)
        except Exception:
            pass

    extra = ""
    if c["marker_hits"]:
        d = c.get("marker_dist")
        where = "本目录" if d == 0 else ("上层 %d 级" % d if d is not None else "?")
        extra = "  ← 项目标记: %s（%s）" % (", ".join(c["marker_hits"]), where)
    via = c["probe"].get("why") or ""
    return "%-30s [%s]  %s%s" % (label, c["runner"], via, extra)

def _ask(cands, base, name):
    print("[选择] '%s' 有 %d 个可用的目标：" % (name, len(cands)))
    for i, c in enumerate(cands, 1):
        print("   %d) %s" % (i, _describe(c, base)))
    print("   0) 取消")
    try:
        raw = input("请输入序号并回车（默认 1）: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise Aborted()
    if raw == "0":
        raise Aborted()
    if not raw:
        idx = 0
    else:
        try:
            idx = int(raw) - 1
        except ValueError:
            raise Aborted()
    if not (0 <= idx < len(cands)):
        raise Aborted()
    chosen = cands[idx]
    save_memory(base, name, chosen["path"].name)
    return chosen, "用户选择"

def disambiguate(cands, base, name, depth):
    perfect = [c for c in cands if c["path"].stem.lower() == name.lower()]
    if len(perfect) == 1:
        return perfect[0], "精确名字匹配"
    if len(cands) == 1:
        return cands[0], "唯一可用候选"

    def _score(c):
        dist = c.get("marker_dist")
        if dist is None:
            return (999, 0)
        return (dist, -len(c["marker_hits"]))

    ranked = sorted(cands, key=lambda c: (_score(c), c["path"].name.lower()))
    top = ranked[0]
    if top["marker_hits"] and (len(ranked) == 1 or _score(top) < _score(ranked[1])):
        where = "本目录" if top["marker_dist"] == 0 else "上层 %d 级" % top["marker_dist"]
        return top, "项目标记 %s（%s）" % (", ".join(top["marker_hits"]), where)

    last = (load_memory(base).get(name.lower()) or "")
    if last:
        for c in cands:
            if c["path"].name.lower() == last.lower():
                return c, "上次选过"

    def _pri(c):
        return runners_mod.priority_of(c["spec"])

    by_type = sorted(cands, key=lambda c: (_pri(c), c["path"].name.lower()))
    if len(by_type) == 1 or _pri(by_type[0]) < _pri(by_type[1]):
        return by_type[0], "类型优先级 %s" % by_type[0]["runner"]

    return _ask(cands, base, name)

def split_path_expr(expr):
    return [p for p in str(expr).replace("\\", "/").split("/") if p]

def _match_dirs(base, head):
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    dirs = [e for e in entries if e.is_dir() and e.name.lower().startswith(head.lower())]
    exact = [d for d in dirs if d.name.lower() == head.lower()]
    return exact if len(exact) == 1 else sorted(dirs, key=lambda p: p.name.lower())

def _walk(base, parts, runners, depth):
    head, rest = parts[0], parts[1:]
    if not rest:
        return collect(base, head, runners, depth)
    out = []
    for d in _match_dirs(base, head):
        out.extend(_walk(d, rest, runners, depth))
    return out

def candidates_at(base, name, runners, depth):
    parts = split_path_expr(name)
    if len(parts) >= 2:
        return _walk(base, parts, runners, depth)
    return collect(base, name, runners, depth)

def find(name, cwd, runners, depth=None):
    for base in search_bases(cwd, depth):
        if not base.is_dir():
            continue
        cands = candidates_at(base, name, runners, depth)
        if not cands:
            continue
        try:
            return disambiguate(cands, base, name, depth)
        except Aborted:
            return None, "用户取消"
    return None, None

def probe_all(cwd, name, runners, depth=None):
    rows = []
    for base in search_bases(cwd, depth):
        for c in candidates_at(base, name, runners, depth):
            rows.append((str(base), c))
    return rows

def _ask_dir(dirs, name):
    print("[选择] '%s' 匹配到 %d 个目录：" % (name, len(dirs)))
    for i, d in enumerate(dirs, 1):
        print("   %d) %s" % (i, d.name))
    print("   0) 取消")
    try:
        raw = input("请输入序号并回车（默认 1）: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise Aborted()
    if raw == "0":
        raise Aborted()
    if not raw:
        idx = 0
    elif raw.isdigit():
        idx = int(raw) - 1
    else:
        raise Aborted()
    if not (0 <= idx < len(dirs)):
        raise Aborted()
    return dirs[idx]

def _walk_dir(base, parts, depth):
    head, rest = parts[0], parts[1:]
    if rest:
        for d in _match_dirs(base, head):
            hit = _walk_dir(d, rest, depth)
            if hit:
                return hit
        return None

    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return None

    dirs = [e for e in entries if e.is_dir() and e.name.lower().startswith(head.lower())]
    files = [e for e in entries if e.is_file() and e.name.lower().startswith(head.lower())]
    exact = [d for d in dirs if d.name.lower() == head.lower()]

    if len(exact) == 1:
        return exact[0]
    if len(dirs) == 1:
        return dirs[0]
    if not dirs and len(files) == 1:
        return files[0].parent
    if dirs:
        return _ask_dir(dirs, head)
    return None

def find_dir(expr, cwd, depth=None):
    parts = split_path_expr(expr)
    if not parts:
        return None
    for base in search_bases(cwd, depth):
        if not base.is_dir():
            continue
        try:
            hit = _walk_dir(base, parts, depth)
        except Aborted:
            return None
        if hit:
            return hit
    return None
