import json
import os
import shutil
from pathlib import Path

from . import paths

def load():
    table = {}
    for f in (paths.SYSTEM_RUNNERS, paths.USER_RUNNERS):
        if f.is_file():
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    for name, spec in data.items():
                        if name.startswith("_") or not isinstance(spec, dict):
                            continue
                        table[name] = spec
            except Exception:
                pass
    return table

def by_ext(table, ext):
    ext = (ext or "").lower()
    if not ext:
        return None, None
    for name, spec in table.items():
        if not isinstance(spec, dict):
            continue
        exts = [e.lower() for e in (spec.get("ext") or [])]
        if ext in exts:
            return name, spec
    return None, None

def all_exts(table):
    out = []
    for spec in table.values():
        out.extend(spec.get("ext") or [])
    return out

def markers_of(spec):
    return [m.lower() for m in (spec.get("markers") or [])]

def priority_of(spec):
    try:
        return int(spec.get("priority", 99))
    except (TypeError, ValueError):
        return 99

def has_marker_near(base, markers, depth=None):
    from . import config
    depth = config.max_parent_depth() if depth is None else depth
    if not markers:
        return False
    try:
        cur = Path(base).resolve()
    except Exception:
        return False
    for _ in range(depth + 1):
        for m in markers:
            if (cur / m).exists():
                return True
        if cur.parent == cur:
            break
        cur = cur.parent
    return False

def read_runtime_meta(directory):
    f = Path(directory) / "runtime.json"
    if f.is_file():
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}

def _ver_tuple(text):
    out = []
    for part in str(text).replace("-", ".").split("."):
        if part.isdigit():
            out.append(int(part))
        else:
            break
    return tuple(out) or (0,)

def _ver_matches(version, requirement):
    if not requirement:
        return False
    req, ver = _ver_tuple(requirement), _ver_tuple(version)
    if len(req) == 1:
        return ver[:1] == req
    return ver[:len(req)] == req

def runtime_families():
    fams = set()
    for base in (paths.USER_RUNTIMES, paths.SYSTEM_RUNTIMES):
        if base.is_dir():
            for d in base.iterdir():
                if d.is_dir():
                    fams.add(d.name)
    return sorted(fams)

def runtime_versions(family):
    if not family:
        return []
    by_ver = {}
    for base, layer in ((paths.USER_RUNTIMES, "user"), (paths.SYSTEM_RUNTIMES, "system")):
        d = base / family
        if not d.is_dir():
            continue
        for v in sorted(d.iterdir()):
            if not v.is_dir():
                continue
            meta = read_runtime_meta(v)
            ver = str(meta.get("version") or v.name)
            if ver in by_ver:
                continue
            by_ver[ver] = {"version": ver, "dir": v, "layer": layer, "meta": meta}
    return sorted(by_ver.values(), key=lambda r: _ver_tuple(r["version"]))

def default_version(family):
    for f in (paths.USER_RUNTIMES / "default.json", paths.SYSTEM_RUNTIMES / "default.json"):
        if f.is_file():
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                v = (data or {}).get(family)
                if v:
                    return str(v)
            except Exception:
                pass
    return None

def runtime_dir(family, requirement=None):
    if not family:
        return None
    versions = runtime_versions(family)
    if not versions:
        return None

    if requirement:
        hit = [v for v in versions if _ver_matches(v["version"], requirement)]
        if not hit:
            return None
        return max(hit, key=lambda v: _ver_tuple(v["version"]))["dir"]

    want = default_version(family)
    if want:
        hit = [v for v in versions if _ver_matches(v["version"], want)]
        if hit:
            return max(hit, key=lambda v: _ver_tuple(v["version"]))["dir"]

    return versions[-1]["dir"]

def list_runtimes():
    out = []
    for fam in runtime_families():
        for v in runtime_versions(fam):
            meta = v["meta"]
            out.append({
                "family": fam,
                "version": v["version"],
                "layer": v["layer"],
                "dir": v["dir"],
                "label": meta.get("label", fam),
                "interpreter": meta.get("interpreter", ""),
                "provides": (meta.get("provides") or {}).get("runner") or [],
                "isDefault": _ver_matches(v["version"], default_version(fam)),
            })
    return out

def interpreter_specs(spec, kind="path"):
    interp = spec.get("interpreters")
    if isinstance(interp, dict):
        return interp.get(kind) or interp.get("path") or []
    return interp or []

def _interp_candidates(spec, ctx, kind):
    for tpl in interpreter_specs(spec, kind):
        if "{runtime}" in tpl and not ctx.get("runtime"):
            yield (tpl + "  ← 没有这个自带运行时", None)
            continue
        if tpl.startswith("PATH:"):
            yield ("PATH:" + tpl[5:], shutil.which(tpl[5:]))
        else:
            try:
                yield (tpl, tpl.format(**ctx))
            except Exception:
                yield (tpl, None)

def detect_venv(interpreter):
    try:
        p = Path(interpreter).resolve()
    except Exception:
        return None
    for cand in [p.parent, *p.parents]:
        if (cand / "pyvenv.cfg").is_file():
            return str(cand)
    return None

def probe(name, spec, ctx, kind="path", requirement=None):
    result = {"available": False, "interpreter": None, "venv": None,
              "runtime": None, "why": ""}

    if spec.get("builtin"):
        result["available"] = True
        result["why"] = "builtin"
        return result

    if not interpreter_specs(spec, kind):
        result["available"] = True
        result["why"] = "无需解释器"
        return result

    family = spec.get("runtime")
    ctx = dict(ctx)
    rd = runtime_dir(family, requirement)
    ctx["runtime"] = rd or ""
    result["runtime"] = rd

    if requirement and family and not rd:
        have = ", ".join(v["version"] for v in runtime_versions(family)) or "一个都没有"
        result["why"] = ("这个包要求 %s 版本 %s，但 runtimes\\%s\\ 下只有：%s"
                         % (family, requirement, family, have))
        return result

    tried = []
    for source, exe in _interp_candidates(spec, ctx, kind):
        tried.append(source)
        if exe and os.path.isfile(exe):
            result["available"] = True
            result["interpreter"] = exe
            result["venv"] = detect_venv(exe)
            result["why"] = source
            return result

    result["why"] = "没找到：" + ", ".join(tried) if tried else "没有配 interpreters"
    return result
