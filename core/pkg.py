import json
import os
import re
import sys
from pathlib import Path

SPEC = 1

_DICT_FIELDS = ("entry", "capabilities", "output", "ai")
_LIST_FIELDS = ("tags", "aliases", "params")

def _fix_shape(pkg):
    for key in _DICT_FIELDS:
        v = pkg.get(key)
        if isinstance(v, dict):
            continue
        if key == "entry" and isinstance(v, str) and v.strip():
            pkg[key] = {"file": v.strip()}
            print("[提示] pkg.json 的 entry 写成了字符串，已按 {\"file\": %r} 处理"
                  % v.strip(), file=sys.stderr)
            continue
        if v not in (None, ""):
            print("[警告] pkg.json 的 %s 应该是对象，已忽略它原来的值：%r"
                  % (key, v), file=sys.stderr)
        pkg.pop(key, None)
    for key in _LIST_FIELDS:
        v = pkg.get(key)
        if v is None or v == "":
            pkg.pop(key, None)
            continue
        if isinstance(v, str):
            v = [x for x in v.replace("，", ",").replace(",", " ").split() if x]
            pkg[key] = v
            print("[提示] pkg.json 的 %s 写成了字符串，已按 %r 处理" % (key, v),
                  file=sys.stderr)
        elif not isinstance(v, list):
            print("[警告] pkg.json 的 %s 应该是数组，已忽略它原来的值：%r"
                  % (key, v), file=sys.stderr)
            pkg.pop(key, None)
            continue
        if key == "params":
            fixed = []
            for p in v:
                if isinstance(p, dict):
                    fixed.append(p)
                elif isinstance(p, str) and p.strip():
                    fixed.append({"name": p.strip()})
                else:
                    print("[警告] pkg.json 的 params 里有一项形状不对，已丢掉：%r"
                          % (p,), file=sys.stderr)
            pkg[key] = fixed

def _example_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    return '"%s"' % s if (" " in s or s == "") else s

def _one_example(it):
    if isinstance(it, str):
        return {"args": it.strip()}
    if not isinstance(it, dict):
        print("[警告] pkg.json 的 ai.examples 里有一项既不是字符串也不是对象，已丢掉：%r"
              % (it,), file=sys.stderr)
        return None
    args = it.get("args")
    if isinstance(args, str):
        return it
    if args is not None:
        print("[警告] pkg.json 的 ai.examples 里的 args 应该是字符串，已按 %r 处理"
              % str(args), file=sys.stderr)
        return dict(it, args=str(args))
    pairs = ["%s=%s" % (k, _example_value(v)) for k, v in it.items()
             if k not in ("note", "why", "desc") and not isinstance(v, (dict, list))]
    if not pairs:
        return {"args": ""}
    return dict(it, args=" ".join(pairs))

def _fix_ai(pkg):
    raw = pkg.get("ai")
    if not isinstance(raw, dict):
        return
    items = raw.get("examples")
    if items is None or items == "":
        return
    ai = dict(raw)
    if not isinstance(items, list):
        items = [items]
    fixed = []
    for it in items:
        ex = _one_example(it)
        if ex is not None:
            fixed.append(ex)
    ai["examples"] = fixed
    pkg["ai"] = ai

def normalize(raw, pid=None):
    pkg = dict(raw) if isinstance(raw, dict) else {}

    pkg["spec"] = int(pkg.get("spec") or SPEC)
    pkg["id"] = str(pkg.get("id") or pid or "").strip()
    pkg["kind"] = str(pkg.get("kind") or "task")
    pkg["version"] = str(pkg.get("version") or "0.0.0")
    _fix_shape(pkg)
    _fix_ai(pkg)
    pkg.setdefault("name", pkg["id"])
    pkg.setdefault("desc", "")
    pkg.setdefault("tags", [])
    pkg.setdefault("aliases", [])
    pkg.setdefault("runner", "")
    pkg.setdefault("entry", {})
    pkg.setdefault("params", [])
    pkg.setdefault("capabilities", {})
    pkg.setdefault("output", {"mode": "text"})
    pkg.setdefault("ai", {"expose": False})
    pkg["drop"] = normalize_drop(pkg.get("drop"))
    return pkg

_DROP_KINDS = ("file", "dir")
_DROP_KEYS = ("cwd", "param", "quote", "base", "ext")
_DROP_BOOL_KEYS = ("cwd", "param", "quote", "base")

_EXT_OK = re.compile(r"^[a-z0-9_+-]+$")

def _norm_ext(raw, where):
    if raw is None or raw == "" or raw is False:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for it in items:
        if not isinstance(it, str):
            print("[警告] %s 里的扩展名应该是字符串，已忽略：%r" % (where, it), file=sys.stderr)
            continue
        e = it.strip().lower().lstrip(".")
        if not e:
            continue
        if e == "*":
            print("[提示] %s 里写了 *（什么都收）—— 和「不写 ext」是一回事" % where,
                  file=sys.stderr)
            return []
        if not _EXT_OK.match(e):
            print("[警告] %s 里的扩展名 %r 含有不认识的字符（点/空格/斜杠都不行），已忽略"
                  % (where, it), file=sys.stderr)
            continue
        if e not in out:
            out.append(e)
    return out

def _norm_drop_rule(rule, where, kind):
    if rule is None or rule is False or rule == "":
        return None
    if rule is True:
        return {"cwd": False, "param": True, "quote": True, "base": False, "ext": []}
    if not isinstance(rule, dict):
        print("[警告] %s 里的这一项应该是对象或 false，已忽略：%r" % (where, rule),
              file=sys.stderr)
        return None
    out = dict((k, bool(rule.get(k))) for k in _DROP_BOOL_KEYS)
    out["quote"] = True if rule.get("quote") is None else bool(rule.get("quote"))
    if kind == "file":
        out["ext"] = _norm_ext(rule.get("ext"), where)
    elif "ext" in rule:
        print("[提示] %s 是文件夹那一项，写 ext 没意义（文件夹没有扩展名），已忽略" % where,
              file=sys.stderr)
    for k in rule:
        if k not in _DROP_KEYS:
            print("[提示] %s 里多了一个不认识的键 %r，已忽略" % (where, k), file=sys.stderr)
    if not out["cwd"] and not out["param"]:
        out["param"] = True
    return out

def normalize_drop(raw):
    if raw is None or raw == "" or raw is False:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for i, it in enumerate(items):
        where = "pkg.json 的 drop[%d]" % i
        if not isinstance(it, dict):
            print("[警告] %s 应该是对象，已忽略：%r" % (where, it), file=sys.stderr)
            continue
        cmd = {"label": str(it.get("label") or "运行")}
        for kind in _DROP_KINDS:
            cmd[kind] = _norm_drop_rule(it.get(kind), where, kind)
        if cmd["file"] is None and cmd["dir"] is None:
            print("[警告] %s 里 file / dir 一个都没写（或都写了 false），这条命令没用，"
                  "已忽略" % where, file=sys.stderr)
            continue
        for k in it:
            if k not in _DROP_KINDS and k != "label":
                print("[提示] %s 里多了一个不认识的键 %r，已忽略" % (where, k), file=sys.stderr)
        out.append(cmd)
    return out

def load(pkg_dir):
    f = pkg_dir / "pkg.json"
    if not f.is_file():
        return None
    try:
        with open(f, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return normalize(raw, pkg_dir.name)

def save(pkg_dir, pkg):
    pkg_dir.mkdir(parents=True, exist_ok=True)
    with open(pkg_dir / "pkg.json", "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False, indent=2)

DOCS_KEYS = ("readme", "usage", "agent")

def docs_of(pkg, pkg_dir, limit=None):
    raw = pkg.get("docs")
    if not isinstance(raw, dict):
        return {}
    got = {}
    for key in DOCS_KEYS:
        rel = str(raw.get(key) or "").strip()
        if not rel:
            continue
        full = Path(rel) if os.path.isabs(rel) else (Path(pkg_dir) / rel)
        try:
            if not full.is_file():
                continue
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        got[key] = {
            "file": rel,
            "text": text if limit is None else text[:limit],
            "truncated": bool(limit is not None and len(text) > limit),
            "size": len(text),
        }
    return got

def entry_path(pkg, pkg_dir):
    entry = pkg.get("entry") or {}
    rel = entry.get("file")
    if not rel:
        return None
    p = (pkg_dir / rel).resolve()
    try:
        p.relative_to(pkg_dir.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None

ICON_EXTS = (".svg", ".png", ".webp", ".jpg", ".jpeg", ".ico", ".gif", ".bmp")

def icon_path(pkg, pkg_dir):
    name = pkg.get("icon")
    cands = [str(name)] if name else ["icon" + e for e in ICON_EXTS]
    try:
        root = Path(pkg_dir).resolve()
    except OSError:
        return None
    for rel in cands:
        try:
            p = (root / rel).resolve()
            p.relative_to(root)
        except (ValueError, OSError):
            continue
        if p.is_file() and p.suffix.lower() in ICON_EXTS:
            return p
    return None

def icon_problem(pkg, pkg_dir):
    name = pkg.get("icon")
    if not name:
        return None
    if icon_path(pkg, pkg_dir) is not None:
        return None
    ext = Path(str(name)).suffix.lower()
    if ext and ext not in ICON_EXTS:
        return "icon 声明的扩展名不认识：%s（认这些：%s）" % (name, " ".join(ICON_EXTS))
    return "icon 声明的文件找不到（或跑出了包目录）：%s" % name

def inline_code(pkg):
    entry = pkg.get("entry") or {}
    code = entry.get("inline")
    return code if isinstance(code, str) and code else None

def display_name(pkg, lang="zh-CN"):
    for key in ("name", "desc"):
        v = pkg.get(key)
        if isinstance(v, dict):
            pkg[key] = v.get(lang) or next(iter(v.values()), "")
        elif v is None:
            pkg[key] = ""
    return pkg

def find_params(pkg):
    out = {}
    spec = pkg.get("params") or []
    for p in spec:
        if "name" in p:
            out[p["name"]] = p.get("default")
    return out
