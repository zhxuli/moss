# -*- coding: utf-8 -*-
"""runner 注册表：**执行方式变成数据**（`F-19` / `E-14`）。

这一块是"内核最小化"（`K-10`）的关键：
    加一种语言 = 往 `system/runners.json` 加一条，或者往 `user_data/runners.json` 加一条。
    **不改宿主代码，不重编 exe。**

三层叠放：
    system/runners.json   随版本走
    user_data/runners.json 用户覆盖（优先）
    自带的解释器放 system/runtimes/<名字>/（用户层可覆盖同名）

**包不得自带 runner**（`K-09`）—— 否则"下载一个包"就等于
"获得执行任意语言代码的能力"，安全等级要跳一大档。

★ 解释器顺序为什么分两组（照抄 pa.py 的既有语义，`E-20`）：
    pa.py 的**插件模式**是  自带 runtime → venv → 系统 python（`pa.py:677` 传 runtime_python）
    pa.py 的**项目模式**是  venv → 系统 python（`pa.py:926` 不传 runtime_python）
  也就是：**我们自己写的包用我们自己的 Python（保证依赖在）；
  用户的脚本用用户项目的 venv（尊重项目环境）。** 这个区分是对的，保留。
"""
import json
import os
import shutil
from pathlib import Path

from . import paths


# ---------------------------------------------------------------- 注册表
def load():
    """系统层 + 用户层叠加，用户优先。"""
    table = {}
    for f in (paths.SYSTEM_RUNNERS, paths.USER_RUNNERS):
        if f.is_file():
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    table.update(data)
            except Exception:
                pass
    return table


def by_ext(table, ext):
    """扩展名 → (runner 名, runner 定义)。查表，不是写死的 if/elif。"""
    ext = (ext or "").lower()
    if not ext:
        return None, None
    for name, spec in table.items():
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


# ---------------------------------------------------------------- 自带运行时
def runtime_dir(name):
    """找一个自带运行时的目录：**用户层优先，然后出厂层**。

    `system/runtimes/<名字>/`，目录名就是 runner 里 `"runtime"` 字段的值。
    用户层可覆盖 —— 以后做"组件下载"时装到 `user_data/runtimes/` 就能盖掉出厂的。
    """
    if not name:
        return None
    for base in (paths.USER_RUNTIMES, paths.SYSTEM_RUNTIMES):
        d = base / name
        if d.is_dir():
            return str(d)
    return None


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


def list_runtimes():
    """列出所有自带运行时（用户层 + 出厂层）。给自检用。"""
    out, seen = [], set()
    for base, layer in ((paths.USER_RUNTIMES, "user"), (paths.SYSTEM_RUNTIMES, "system")):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            if not d.is_dir() or d.name in seen:
                continue
            seen.add(d.name)
            meta = read_runtime_meta(d)
            out.append({
                "name": d.name,
                "layer": layer,
                "dir": d,
                "version": meta.get("version", ""),
                "label": meta.get("label", d.name),
                "interpreter": meta.get("interpreter", ""),
                "provides": (meta.get("provides") or {}).get("runner") or [],
            })
    return out


# ---------------------------------------------------------------- 探测
def interpreter_specs(spec, kind="path"):
    """取某个调用类型下的解释器候选列表。

    支持分组写法，也兼容旧的扁平列表：
        "interpreters": { "package": [...], "path": [...] }
        "interpreters": [ ... ]        ← 旧写法，两组都用它
    """
    interp = spec.get("interpreters")
    if isinstance(interp, dict):
        return interp.get(kind) or interp.get("path") or []
    return interp or []


def _interp_candidates(spec, ctx, kind):
    """把 interpreters 模板展开成 (来源说明, 实际路径) 序列。

    ⚠️ 即使没找到也要 yield（exe 为 None）—— 否则 probe() 收集不到
       "试过哪些地方"，报出来的错会变成误导性的"没有配 interpreters"。
    """
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
    """从解释器路径往上找 pyvenv.cfg，找到就认为那是虚拟环境根。

    ★ 注意（`E-11`）：M1 **照抄旧行为**，只把它当作"找到了解释器"，
      刻意**不**去设 VIRTUAL_ENV / PATH —— pa.py 这么跑几个月没出问题，
      不许在这里"改进"。
    """
    try:
        p = Path(interpreter).resolve()
    except Exception:
        return None
    for cand in [p.parent, *p.parents]:
        if (cand / "pyvenv.cfg").is_file():
            return str(cand)
    return None


def probe(name, spec, ctx, kind="path"):
    """探测这个 runner 在这台机器上能不能用。

    kind: "package"（跑我们自己的包）| "path"（跑用户项目里的脚本）
          两者的解释器顺序不同，见模块 docstring。

    返回 {"available": bool, "interpreter": str|None, "venv": str|None,
          "runtime": str|None, "why": str}
    """
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

    ctx = dict(ctx)
    rd = runtime_dir(spec.get("runtime"))
    ctx["runtime"] = rd or ""
    result["runtime"] = rd

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
