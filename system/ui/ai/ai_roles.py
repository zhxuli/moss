import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E

_FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)
BASE_DIR = E.HOME / "system" / "ui" / "ai" / "prompts"
USER_DIR = E.user_data() / "ai" / "prompts"


def _kind_dirs(kind):
    if kind:
        return [BASE_DIR / kind, USER_DIR / kind]
    return [BASE_DIR, USER_DIR]


def _dirs():
    return _kind_dirs("roles")


def _parse(text, fallback_id=""):
    text = text or ""
    m = _FM.match(text)
    head, body = "", text
    if m:
        head, body = m.group(1), text[m.end():]
    meta = {"id": fallback_id, "name": fallback_id or "角色",
            "icon": "sparkles", "desc": ""}
    for ln in head.splitlines():
        if ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k in meta:
            meta[k] = v
    return meta, body.strip()


def _list_kind(kind):
    out = {}
    dirs = _kind_dirs(kind)
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            meta, body = _parse(text, f.stem)
            rid = str(meta.get("id") or f.stem).strip()
            if not re.match(r"^[a-z][a-z0-9_-]{0,31}$", rid):
                continue
            meta.update({"id": rid, "body": body, "path": f,
                         "system_path": dirs[0] / f.name,
                         "user_path": dirs[1] / f.name})
            out[rid] = meta
    return out


def list_roles():
    return _list_kind("roles")


def list_strategies():
    return _list_kind("strategies")


def body(rid):
    got = list_roles().get(str(rid or "").strip())
    return got.get("body") if got else ""


def strategy_body(sid):
    got = list_strategies().get(str(sid or "").strip())
    return got.get("body") if got else ""


def meta(rid):
    got = list_roles().get(str(rid or "").strip())
    if not got:
        return None
    return {k: got.get(k) for k in ("id", "name", "icon", "desc", "path")}


def default_role():
    roles = list_roles()
    if "creator" in roles:
        return "creator"
    return next(iter(roles), "")


def default_strategy():
    rows = list_strategies()
    if "finish" in rows:
        return "finish"
    return next(iter(rows), "")


def note_for_ui():
    return [{"id": v["id"], "name": v.get("name") or v["id"],
             "icon": v.get("icon") or "sparkles", "desc": v.get("desc") or ""}
            for v in sorted(list_roles().values(), key=lambda x: x["id"])]


def strategies_for_ui():
    return [{"id": v["id"], "name": v.get("name") or v["id"],
             "icon": v.get("icon") or "gauge", "desc": v.get("desc") or ""}
            for v in sorted(list_strategies().values(), key=lambda x: x["id"])]


def _prompt_paths(name):
    name = str(name or "").strip()
    if name in ("system", "edit"):
        return BASE_DIR / (name + ".md"), USER_DIR / (name + ".md")
    m = re.match(r"^(roles|strategies)/([a-z][a-z0-9_-]{0,31})$", name)
    if m:
        kind, pid = m.group(1), m.group(2)
        return BASE_DIR / kind / (pid + ".md"), USER_DIR / kind / (pid + ".md")
    return None, None


def _read_text(path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def prompt_catalog():
    out = []
    for n, label in (("system", "系统提示词"), ("edit", "改文件规则")):
        sysp = BASE_DIR / (n + ".md")
        usr = USER_DIR / (n + ".md")
        eff = usr if usr.is_file() else sysp
        out.append({"id": n, "kind": "base", "title": label,
                    "overridden": usr.is_file(),
                    "chars": len(_read_text(eff))})
    for kind, label in (("roles", "工作角色"), ("strategies", "执行策略")):
        for rid, v in sorted(_list_kind(kind).items()):
            usr = v.get("user_path")
            out.append({"id": kind + "/" + rid, "kind": kind,
                        "title": v.get("name") or rid,
                        "overridden": bool(usr and usr.is_file()),
                        "chars": len(v.get("body") or "")})
    return out


def read_prompt(name):
    sysp, usr = _prompt_paths(name)
    if not sysp:
        return {"ok": False, "msg": "不认识的提示词"}
    p = usr if usr.is_file() else sysp
    if not p.is_file():
        return {"ok": False, "msg": "提示词文件不存在：%s" % p}
    return {"ok": True, "id": str(name), "content": _read_text(p),
            "override": usr.is_file(), "path": str(p),
            "default_path": str(sysp)}


def save_prompt(name, text):
    sysp, usr = _prompt_paths(name)
    if not sysp:
        return {"ok": False, "msg": "不认识的提示词"}
    text = str(text or "")
    if not text.strip():
        return {"ok": False, "msg": "不能保存空提示词"}
    try:
        usr.parent.mkdir(parents=True, exist_ok=True)
        tmp = usr.with_name(usr.name + ".tmp")
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(str(tmp), str(usr))
    except OSError as e:
        return {"ok": False, "msg": "存不下来：%s" % e}
    return {"ok": True, "id": str(name), "path": str(usr), "override": True}


def reset_prompt(name):
    sysp, usr = _prompt_paths(name)
    if not sysp:
        return {"ok": False, "msg": "不认识的提示词"}
    try:
        if usr.is_file():
            usr.unlink()
    except OSError as e:
        return {"ok": False, "msg": "恢复失败：%s" % e}
    return {"ok": True, "id": str(name), "override": False}