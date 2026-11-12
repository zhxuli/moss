import sys

from . import paths, pkg as pkg_mod

def _scan_layer(base_dir, layer):
    found = []
    if not base_dir.is_dir():
        return found
    for d in sorted(base_dir.iterdir()):
        if not d.is_dir():
            continue
        p = pkg_mod.load(d)
        if p is None:
            if (d / "pkg.json").is_file():
                print("[警告] %s 的 pkg.json 解析失败（JSON 语法错误？），"
                      "这个包会被当成不存在。" % d, file=sys.stderr)
            continue
        if not paths.valid_id(p.get("id")):
            print("[警告] %s 的 id '%s' 不合法（只允许 %s），这个包会被当成不存在。"
                  % (d, p.get("id"), paths.ID_RE.pattern), file=sys.stderr)
            continue
        pkg_mod.display_name(p)
        found.append({"id": p["id"], "layer": layer, "dir": d, "pkg": p})
    return found

def layers():
    return [(paths.SYSTEM_PKGS, "system"), (paths.USER_PKGS, "user")]

def scan_all():
    by_id = {}
    for base, layer in layers():
        for rec in _scan_layer(base, layer):
            if rec["id"] in by_id:
                rec["shadowed"] = by_id[rec["id"]]["layer"]
            by_id[rec["id"]] = rec
    return sorted(by_id.values(), key=lambda r: r["id"])

def dir_of(rec):
    d = rec.get("dir")
    return getattr(d, "name", None) or (str(d).replace("\\", "/").rstrip("/").split("/")[-1]
                                        if d else "")

def dir_mismatch(rec):
    name = dir_of(rec)
    return name if name and name != str(rec.get("id") or "") else None

def _system_has_id(pid):
    if not paths.SYSTEM_PKGS.is_dir():
        return False
    want = str(pid or "").lower()
    for d in sorted(paths.SYSTEM_PKGS.iterdir()):
        if not d.is_dir():
            continue
        p = pkg_mod.load(d)
        if p and str(p.get("id") or "").lower() == want:
            return True
    return False

def _probe_by_dirname(name):
    if not name:
        return None
    for base, layer in reversed(layers()):
        d = base / name
        if not d.is_dir():
            continue
        p = pkg_mod.load(d)
        if p is None or not paths.valid_id(p.get("id")):
            continue
        pkg_mod.display_name(p)
        pid = str(p.get("id") or "").lower()
        aliases = [str(x).lower() for x in (p.get("aliases") or [])]
        if name != pid and name not in aliases:
            continue
        rec = {"id": p["id"], "layer": layer, "dir": d, "pkg": p}
        if layer == "user" and ((paths.SYSTEM_PKGS / p["id"]).is_dir()
                                or _system_has_id(p["id"])):
            rec["shadowed"] = "system"
        return rec
    return None

def find_alias(alias):
    name = (alias or "").strip().lower()
    if not name:
        return None
    rec = _probe_by_dirname(name)
    if rec is not None:
        return rec
    for rec in scan_all():
        names = [str(a).lower() for a in (rec["pkg"].get("aliases") or [])]
        if name in names or name == rec["id"].lower():
            return rec
    return None
