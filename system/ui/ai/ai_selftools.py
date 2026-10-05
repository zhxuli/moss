# -*- coding: utf-8 -*-
"""**AI 自己的工具**（`V-280`）：它工作的时候缺一只手，就自己造一只，用户看不见。

为什么单独开一层（你 2026-10-05 定的）
--------------------------------------
插件包（`user_data/pkgs/`）是**面向用户的目录**：插件页要列它、`:别名` 要跑它、
`--remove` 能删它、`--selfcheck` 要数它。把"AI 自己要用的手"塞进那儿，用户看到的就是
一堆莫名其妙的包（原话：「用户使用的时候 肯定会觉得难受 因为特别凌乱」），
而且**用户还能一键删掉**，删了 AI 下次就残废。所以另起一层，跟"用户的插件"彻底分开。

两层（跟你定的 `user > system` 一个规矩）
----------------------------------------
```
system/ai/tools/<名字>/TOOL.md + run.py       出厂（跟着版本走，**默认已允许**）
user_data/ai/tools/<名字>/TOOL.md + run.py    它自己造的手（**要人点一次「允许」**）
```
`system` 层是我们写的、进发行版前就审过了 ⇒ 不用批准；`user` 层是**AI 写、宿主执行**的东西
⇒ 第一次要人点头（`3ⓑ`）。点头记在 `user_data/ai/tools_allow.json`，**并且绑指纹**：
`TOOL.md + run.py` 一改，指纹就变 ⇒ 自动退回"待批准"（不然"批准"就成了永久通行证）。

`TOOL.md` 长这样（frontmatter 只认这四个字段，多的忽略）
-------------------------------------------------------
```
---
name: shot
description: 截屏 / 截某个窗口，存成 png 并把绝对路径回给我
params:
  target: 窗口标题关键词（不填 = 整个屏幕）
  out: 存到哪个文件（不填 = 自动起名）
timeout: 60
---
（正文：给人看的说明，模型看不到这一段）
```

`run.py` 的契约（一页说完，模型照这个写）
---------------------------------------
* 启动：`<自带运行时>\\python.exe system/bootstrap.py <工具目录>\\run.py`
  （自带运行时是嵌入式发行版、隔离模式 ⇒ 必须经 `bootstrap.py` 才能 `import` 同目录的兄弟文件）
* **参数**：stdin 一行 JSON（就是模型给的那些参数），同时也放在环境变量 `MOSS_TOOL_ARGS` 里
* **回话**：stdout 的文本**原样**回给模型（截尾 60 行 / 4000 字）；退出码非 0 会在前面加一句
* `cwd` = 工具目录；`MOSS_HOME` / `MOSS_USER_DATA_DIR` / `MOSS_UI_DATA` 原样带下去
* 超时（frontmatter 的 `timeout`，默认 60 秒，最多 300）会被杀掉并回一句人话

★ 工具表是**一次跑开工那一刻定死**的：它这一次跑新造的手，**下一次**才进表 ——
  这也正好卡在"你要点同意"那一步上，不会出现"自己写了自己马上调"的窗口。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent                     # system/ui/ai
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E                                       # noqa: E402

#: 名字的合法形状（跟函数名一个规格：模型那边 `name` 只能长这样）
NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

#: 默认超时 / 上限
TIMEOUT = 60
TIMEOUT_MAX = 300

#: 回到模型那边的截断（跟 `run_moss` 一个口径）
TAIL_LINES = 60
TAIL_CHARS = 4000


def roots():
    """两层工具目录：`system/ai/tools`（出厂）+ `user_data/ai/tools`（它自己造的）。"""
    return [(E.HOME / "system" / "ai" / "tools", "system"),
            (E.user_data() / "ai" / "tools", "user")]


def allow_path():
    """点头记在这儿（一个 json，不是工具目录里的文件 —— 免得被当成"工具的一部分"）。"""
    return E.user_data() / "ai" / "tools_allow.json"


# ------------------------------------------------------------------ TOOL.md 解析
_FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.S)


def parse_md(text):
    """`TOOL.md` → `(name, desc, params, timeout, body)`。

    frontmatter 是**一层缩进**的 YAML-lite：顶格的 `key: value` 是字段，缩进两格的
    挂在最近的 `params:` 下面。跟 `ai_skills._parse` 是同一个路子，只是那边只要两个
    平字段 —— 这边要多认一层 `params`，所以单独写（不去动已经验过的技能那套）。
    """
    name = desc = ""
    params, timeout, key = [], 0, ""
    m = _FM.match(text or "")
    if not m:
        return "", "", [], 0, (text or "").strip()
    head, body = m.group(1), text[m.end():]
    for raw in head.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#") or ":" not in raw:
            continue
        indent = len(raw) - len(raw.lstrip())
        k, _, v = raw.strip().partition(":")
        k, v = k.strip().lower(), v.strip()
        if indent and key == "params":
            params.append((k, v))
            continue
        key = k
        if k == "name":
            name = v
        elif k == "description":
            desc = v
        elif k == "timeout":
            try:
                timeout = int(float(v or 0))
            except ValueError:
                timeout = 0
    return name, desc, params, timeout, body.strip()


def _fp(md_raw, sc_raw, name):
    """指纹 = 名字 + TOOL.md + run.py 的 sha1 前 16 位。改一个字就变。"""
    h = hashlib.sha1()
    h.update(str(name).encode("utf-8"))
    for blob in (md_raw, sc_raw):
        h.update(b"\0")
        h.update(blob or b"")
    return h.hexdigest()[:16]


# ------------------------------------------------------------------ 点头表
def allowed_map():
    try:
        got = json.loads(allow_path().read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except Exception:                                                  # noqa: BLE001
        return {}


def _save_allow(d):
    p = allow_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ 扫描
def list_tools(roots_in=None, avoid=()):
    """`{名字: {...}}` —— **user 层覆盖 system 层**（同名就是覆盖，跟技能一个规矩）。

    每一项：`{name, desc, params, timeout, dir, layer, md, script, fp, allowed, why, problems}`。
    `avoid`：内置工具的名字（撞名的不进表 —— 否则它会盖掉 `read_file` 那种）。
    """
    out = {}
    amap = allowed_map()
    avoid = {str(x) for x in (avoid or ())}
    for d, layer in (roots_in if roots_in is not None else roots()):
        d = Path(d)
        if not d.is_dir():
            continue
        for sub in sorted(d.iterdir()):
            if not sub.is_dir():
                continue
            md, sc = sub / "TOOL.md", sub / "run.py"
            probs = []
            if not md.is_file():
                probs.append("缺 TOOL.md")
            if not sc.is_file():
                probs.append("缺 run.py（入口脚本）")
            md_raw = md.read_bytes() if md.is_file() else b""
            sc_raw = sc.read_bytes() if sc.is_file() else b""
            name, desc, params, timeout, _body = parse_md(
                md_raw.decode("utf-8", "replace") if md_raw else "")
            if not name:
                name = sub.name                      # 名字缺了就用目录名（宽容，但下面要点名）
            if name != sub.name:
                probs.append("frontmatter 里的 name（%s）和目录名（%s）不一样" % (name, sub.name))
            if not NAME_RE.match(name or ""):
                probs.append("名字只能用字母数字下划线短横线（≤64 个字符）")
            if name in avoid:
                probs.append("和内置工具撞名了（%s）" % name)
            if not desc:
                probs.append("缺 description —— 这样它进不了工具表")
            fp = _fp(md_raw, sc_raw, name) if (md_raw and sc_raw) else ""
            if layer == "system":
                allowed, why = True, "出厂工具（随版本走，不用批准）"
            else:
                rec = amap.get(name) or {}
                if rec.get("fp") and rec.get("fp") == fp:
                    allowed, why = True, "你已经允许过（%s）" % (rec.get("at") or "")
                elif rec:
                    allowed, why = False, "你允许过之后它又改过 ⇒ 要重新允许"
                else:
                    allowed, why = False, "还没允许"
            out[name] = {"name": name, "desc": desc, "params": list(params),
                         "timeout": _clamp_timeout(timeout), "dir": sub, "layer": layer,
                         "md": md, "script": sc, "fp": fp, "allowed": allowed, "why": why,
                         "problems": probs}
    return out


def _clamp_timeout(t):
    try:
        t = int(t or 0)
    except (TypeError, ValueError):
        t = 0
    if t <= 0:
        return TIMEOUT
    return max(5, min(TIMEOUT_MAX, t))


def usable(roots_in=None, avoid=()):
    """**能进工具表**的：没毛病 + 已允许（出厂层默认允许）。"""
    return {k: v for k, v in list_tools(roots_in, avoid).items()
            if not v["problems"] and v["allowed"]}


def pending(roots_in=None, avoid=()):
    """**等人点头**的：没毛病、但还没允许（界面上那条黄条就是它）。"""
    return {k: v for k, v in list_tools(roots_in, avoid).items()
            if not v["problems"] and not v["allowed"]}


def broken(roots_in=None, avoid=()):
    """有毛病、进不了表的（要说出来，别静默）。"""
    return {k: v for k, v in list_tools(roots_in, avoid).items() if v["problems"]}


# ------------------------------------------------------------------ 给模型的两样
def specs_from(got):
    """`{名字: 那一项}` → 工具表里那几张（**参数全是字符串**，跟自制工具的契约一致）。"""
    rows = []
    for k in sorted(got or {}):
        it = got[k]
        props = {}
        for p, d in (it.get("params") or []):
            props[p] = {"type": "string", "description": d or ""}
        rows.append({"type": "function", "function": {
            "name": k,
            "description": "%s（**你自己造的工具**；目录 %s）" % (it.get("desc") or "", it.get("dir")),
            "parameters": {"type": "object", "properties": props, "required": []}}})
    return rows


def specs(avoid=()):
    return specs_from(usable(avoid=avoid))


def note(got=None, avoid=()):
    """系统提示里那段"你已经有哪些自己的手"（没有就回空串 —— 不加噪音）。"""
    got = usable(avoid=avoid) if got is None else got
    if not got:
        return ""
    rows = ["【我自己的工具】这些是**已经允许我用**的工具（工具表里就在，直接调）："]
    for k in sorted(got):
        rows.append("  · %s(%s) —— %s" % (
            k, "、".join(p for p, _ in (got[k].get("params") or [])) or "无参数",
            got[k].get("desc") or ""))
    rows.append("  · 缺什么手的时候：先 `skill(\"self-tool\")` 看怎么写，"
                "然后写到 `%s/<名字>/`；我写完**要用户点一次「允许」**下一次跑才生效。"
                % (E.user_data() / "ai" / "tools"))
    return "\n".join(rows)


# ------------------------------------------------------------------ 跑一只
def _python():
    """自带运行时（隔离模式，所以要配 `bootstrap.py`）；找不到就退回当前解释器。"""
    rt = E.HOME / "system" / "runtimes" / "python"
    try:
        for exe in sorted(rt.glob("*/python.exe")):
            return str(exe)
    except OSError:
        pass
    return sys.executable


def _cmd(script):
    boot = E.HOME / "system" / "bootstrap.py"
    py = _python()
    if boot.is_file() and Path(py).name.lower().startswith("python"):
        return [py, str(boot), str(script)]
    return [py, str(script)]


def _env(args, name):
    keep = {"MOSS_HOME", "MOSS_USER_DATA_DIR", "MOSS_UI_DATA"}
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("MOSS_") and k not in keep)}
    env["MOSS_TOOL_NAME"] = str(name)
    env["MOSS_TOOL_ARGS"] = json.dumps(args or {}, ensure_ascii=False)
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def tail(text, lines=TAIL_LINES, chars=TAIL_CHARS):
    s = str(text or "")
    if not s.strip():
        return "（没有输出）"
    ls = s.splitlines()
    cut = len(ls) > lines
    if cut:
        s = "\n".join(ls[-lines:])
    if len(s) > chars:
        s = s[-chars:]
    return ("……（前面还有 %d 行，已省略）\n" % (len(ls) - lines) if cut else "") + s


def run(name, args, avoid=(), roots_in=None):
    """真跑一只工具。回一段**给模型看**的文本（跟 `run_moss` 一个口径）。

    `roots_in` 只给探针用（造一组**合成**的两层目录，别去动仓库里那份出厂件）。
    """
    got = usable(roots_in, avoid).get(str(name or "").strip())
    if not got:
        pend = pending(roots_in, avoid).get(str(name or "").strip())
        if pend:
            return ("[没允许] 工具「%s」你造出来了、也写进盘了，但**用户还没点「允许」**"
                    "（`%s`）—— 这一次跑用不了。先干别的，或者跟用户说一声。" % (name, pend["why"]))
        return ("[错误] 没有这个工具：%s（内置的：%s；你自己的：%s）"
                % (name, "、".join(avoid) or "（没传）",
                   "、".join(sorted(usable(roots_in, avoid))) or "（还没有）"))
    cmd = _cmd(got["script"])
    try:
        p = subprocess.run(
            cmd, input=json.dumps(args or {}, ensure_ascii=False),
            cwd=str(got["dir"]), env=_env(args, name),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=int(got["timeout"] or TIMEOUT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        return ("[超时] 工具「%s」跑了 %s 秒还没回 —— 被杀了。"
                "（要更长就在 TOOL.md 里写 `timeout:`，最多 %d 秒。）"
                % (name, got["timeout"], TIMEOUT_MAX))
    except OSError as e:
        return "[跑不起来] %s\n  命令 = %r\n  目录 = %r" % (e, cmd, str(got["dir"]))
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    head = "工具「%s」退出码 %d" % (name, p.returncode)
    if err:
        head += "\n[stderr]\n" + tail(err)
    return head + "\n" + tail(out)


# ------------------------------------------------------------------ 人的几个动作
def allow(name, yes=True, roots_in=None):
    """允许 / 撤销（**只对 user 层有意义** —— 出厂层本来就允许）。

    `roots_in` 只给探针用（合成现场）。
    """
    got = list_tools(roots_in).get(str(name or "").strip())
    if not got:
        return {"ok": False, "msg": "没有这个工具：%s" % name}
    if got["layer"] == "system":
        return {"ok": False, "msg": "「%s」是出厂工具（system 层）—— 本来就能用，不用批准，"
                                    "也不该在这儿改。" % name}
    d = allowed_map()
    if yes:
        d[got["name"]] = {"fp": got["fp"], "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    else:
        d.pop(got["name"], None)
    _save_allow(d)
    return {"ok": True, "name": got["name"], "allowed": bool(yes),
            "msg": ("允许了：%s —— 它**下一次**跑就能用（工具表是开工那一刻定的）" % got["name"])
                   if yes else ("撤销了：%s —— 它还留在盘上，但进不了工具表" % got["name"])}


def rm(name, confirm=False, roots_in=None):
    """删掉一只**它自己造的**工具（出厂层不许删 —— 哪怕带了 `confirm`）。

    `roots_in` 只给探针用（合成现场；**探针绝不去碰仓库里那份出厂件**）。
    """
    got = list_tools(roots_in).get(str(name or "").strip())
    if not got:
        return {"ok": False, "msg": "没有这个工具：%s" % name}
    if got["layer"] == "system":
        return {"ok": False, "msg": "「%s」是出厂工具，删不得（它是发行版的一部分）。"
                                    "要改就改仓库里那份。" % name}
    if not confirm:
        return {"ok": False, "need_confirm": True,
                "msg": "删掉「%s」的目录？%s" % (got["name"], got["dir"])}
    try:
        shutil.rmtree(str(got["dir"]))
    except OSError as e:
        return {"ok": False, "msg": "删不掉：%s" % e}
    d = allowed_map()
    d.pop(got["name"], None)
    _save_allow(d)
    return {"ok": True, "name": got["name"], "msg": "删掉了：%s" % got["name"]}


def read(name, limit=20000, roots_in=None):
    """看一眼它写了什么（界面那个「看一眼」用它）。"""
    got = list_tools(roots_in).get(str(name or "").strip())
    if not got:
        return {"ok": False, "msg": "没有这个工具：%s" % name}
    def _one(p):
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            return "（读不出来：%s）" % e
        return t[:limit] + ("\n……（截到 %d 字）" % limit if len(t) > limit else "")
    return {"ok": True, "name": got["name"], "layer": got["layer"], "dir": str(got["dir"]),
            "md": _one(got["md"]) if got["md"].is_file() else "（缺 TOOL.md）",
            "script": _one(got["script"]) if got["script"].is_file() else "（缺 run.py）",
            "allowed": got["allowed"], "why": got["why"], "problems": got["problems"]}


def summary():
    """界面/宿主一次拿全：三堆 + 目录（`ai_self_tools` 那个 API 用它）。"""
    got = list_tools()
    def _row(it):
        return {"name": it["name"], "desc": it["desc"], "layer": it["layer"],
                "dir": str(it["dir"]), "allowed": it["allowed"], "why": it["why"],
                "params": [p for p, _ in it["params"]], "problems": it["problems"],
                "timeout": it["timeout"]}
    return {"ok": True,
            "mine": [_row(v) for _, v in sorted(got.items())
                     if not v["problems"] and v["allowed"]],
            "pending": [_row(v) for _, v in sorted(got.items())
                        if not v["problems"] and not v["allowed"]],
            "broken": [_row(v) for _, v in sorted(got.items()) if v["problems"]],
            "dirs": {"mine": str(roots()[1][0]), "factory": str(roots()[0][0])},
            "allow_file": str(allow_path())}
