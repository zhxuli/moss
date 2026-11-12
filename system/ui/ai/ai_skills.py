import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

def _paths():
    import ai_edits as E
    return [E.HOME / "system" / "skills", E.user_data() / "skills"]

_FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)

def _parse(text):
    m = _FM.match(text or "")
    if not m:
        return "", "", (text or "").strip()
    head, body = m.group(1), text[m.end():]
    name = desc = ""
    for ln in head.splitlines():
        if ":" not in ln:
            continue
        k, _, v = ln.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k == "name":
            name = v
        elif k == "description":
            desc = v
    return name, desc, body.strip()

def list_skills():
    out = {}
    for d in _paths():
        if not d.is_dir():
            continue
        for sub in sorted(d.iterdir()):
            f = sub / "SKILL.md"
            if not (sub.is_dir() and f.is_file()):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            name, desc, body = _parse(text)
            probs = []
            if not name:
                name = sub.name
            if name != sub.name:
                probs.append("frontmatter 里的 name（%s）和目录名（%s）不一样" % (name, sub.name))
            if not desc:
                probs.append("缺 description —— 这样它不会出现在清单里")
            out[name] = {"name": name, "desc": desc, "body": body, "path": f,
                         "where": str(d), "problems": probs}
    return out

def names():
    return sorted(list_skills().keys())

def usable():
    return {k: v for k, v in list_skills().items() if v["desc"]}

def broken():
    return {k: v for k, v in list_skills().items() if v["problems"]}

def body(name):
    got = list_skills().get(str(name or "").strip())
    return got["body"] if got else None

def note():
    got = usable()
    if not got:
        return ""
    rows = ["【可用技能】要写新包 / 收拖入这类「方法论」，**先 `skill(名字)` 把那一份读出来**"
            "（读一次就够，别反复读；正文里提到的样板/文件都在它自己目录里）："]
    for k in sorted(got):
        it = got[k]
        rows.append("  · %s —— %s（%s）" % (k, it["desc"], it["path"]))
    return "\n".join(rows)
