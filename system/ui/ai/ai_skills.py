# -*- coding: utf-8 -*-
"""**技能**（skills）：按需读的"方法论"，借鉴自 Pi（`V-278`）。

为什么要有它
------------
原来"写新包 / 收拖入"这两套写法指导是**按关键词整段塞进系统提示**的
（`FRAGMENT_RULES`：任务里出现"写/新/建"就把 `new_pkg.md` 全文塞进去）。问题是：
* **靠猜**：关键词命中不等于需要它；
* **不好扩展**：你和包想加一门技能，只能改 Python 里的那张关键词表；
* **带不了东西**：技能目录里本该能放样板包 / 骨架 / 参考文件，整段注入做不到。

Pi 的做法（它的 `docs/skills.md`）值得抄：**一个技能一个目录 + `SKILL.md`**，
系统提示里**只列名字 + 描述 + 路径**（几十个字），正文等模型自己决定读时再读；
目录里还能放 `files/`，正文用相对路径引用它们。

我们的形态
----------
```
system/skills/<名字>/SKILL.md        出厂（跟着版本走）
user_data/skills/<名字>/SKILL.md     你的覆盖版（**同名就整个替换**，跟提示词一个规矩）
```
`SKILL.md` 开头是一小段 frontmatter（只认两个字段，多的忽略）：

```
---
name: new-pkg
description: 写一个新插件包时读它（下手的顺序、pkg.json 要点、样板在哪）
---
（正文：想怎么写就怎么写，中文、Markdown 都行）
```

★ 两条纪律：
1. **不搞隐形兜底**：没有 `description` 的技能**不参与**清单，而且会被点名报出来
   （不然你会以为"AI 今天变笨了"，其实是技能没被认出来）。
2. 正文里引用目录里的文件时，`skill()` 会把**技能目录的绝对路径**一起给它
   （相对路径没法直接读）。
"""
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent                     # system/ui/ai


def _paths():
    """两层技能目录：`system/skills`（出厂）+ `user_data/skills`（你的，同名覆盖）。"""
    import ai_edits as E                                   # noqa: PLC0415
    return [E.HOME / "system" / "skills", E.user_data() / "skills"]


#: frontmatter 就认这两个（其它字段忽略 —— 跟 Pi 一样宽容，但缺 description 要点名）
_FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def _parse(text):
    """`SKILL.md` 的文本 → `(name, description, body)`（没有 frontmatter 就都空）。"""
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
    """`{名字: {name, desc, body, path, where, problems}}`（**user 层覆盖 system 层**）。

    `problems` 是"这份技能哪里不对"（缺 description / 名字对不上目录名）—— 调用方要报出来。
    """
    out = {}
    for d in _paths():                     # 后面的层覆盖前面的（user 赢）
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
                name = sub.name                # 名字缺了就用目录名（跟 Pi 一样宽容）
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
    """能进清单的（**必须有 description**）。"""
    return {k: v for k, v in list_skills().items() if v["desc"]}


def broken():
    """有问题、进不了清单的（要报出来，别静默）。"""
    return {k: v for k, v in list_skills().items() if v["problems"]}


def body(name):
    """读一份技能的正文（给 `skill()` 工具用）。找不到返回 None。"""
    got = list_skills().get(str(name or "").strip())
    return got["body"] if got else None


def note():
    """系统提示里那段"有哪些技能"的清单（**只有名字 + 描述 + 路径**，正文不进来）。

    ★ 这一句是整个设计的要点：正文**不**进系统提示（省 token、也避免"猜着塞"）。
    """
    got = usable()
    if not got:
        return ""
    rows = ["【可用技能】要写新包 / 收拖入这类「方法论」，**先 `skill(名字)` 把那一份读出来**"
            "（读一次就够，别反复读；正文里提到的样板/文件都在它自己目录里）："]
    for k in sorted(got):
        it = got[k]
        rows.append("  · %s —— %s（%s）" % (k, it["desc"], it["path"]))
    return "\n".join(rows)
