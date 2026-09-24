# -*- coding: utf-8 -*-
"""runner 注册表：**执行方式变成数据**（F-19 / E-14）。

这一块是"内核最小化"（K-10）的关键：
    加一种语言 = 往 `system/runners.json` 加一条，或者往 `user_data/runners.json` 加一条。
    **不改宿主代码，不重编 exe。**

支持两级层叠：系统一份（随版本走）+ 用户一份（用户优先）。
但**包不得自带 runner**（K-09）—— 否则"下载一个包"就等于
"获得执行任意语言代码的能力"，安全等级要跳一大档。
"""
import json
import os
import shutil
from pathlib import Path

from . import paths


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


def _interp_candidates(spec, ctx):
    """把一个 runner 的 interpreters 模板展开成 (来源说明, 实际路径) 序列。

    ⚠️ 即使没找到也要 yield（exe 为 None）—— 否则 probe() 收集不到
       "试过哪些地方"，报出来的错会变成误导性的"没有配 interpreters"。
    """
    for tpl in spec.get("interpreters") or []:
        if tpl.startswith("PATH:"):
            yield ("PATH:" + tpl[5:], shutil.which(tpl[5:]))
        else:
            try:
                yield (tpl, tpl.format(**ctx))
            except Exception:
                yield (tpl, None)


def detect_venv(interpreter):
    """从解释器路径往上找 pyvenv.cfg，找到就认为那是虚拟环境根。

    ★ 注意（E-20 / E-11）：M1 **照抄旧行为**，只把它当作"找到了解释器"，
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


def probe(name, spec, ctx):
    """探测这个 runner 在这台机器上能不能用。

    返回 {"available": bool, "interpreter": str|None, "venv": str|None, "why": str}
    builtin 类（html / url / path 这种宿主自己动手的）永远可用。
    """
    result = {"available": False, "interpreter": None, "venv": None, "why": ""}

    if spec.get("builtin"):
        result["available"] = True
        result["why"] = "builtin"
        return result

    # 没有声明 interpreters 也不需要解释器的（比如 .exe 直接跑）→ 永远可用
    if not (spec.get("interpreters") or []):
        result["available"] = True
        result["why"] = "无需解释器"
        return result

    tried = []
    for source, exe in _interp_candidates(spec, ctx):
        tried.append(source)
        if exe and os.path.isfile(exe):
            result["available"] = True
            result["interpreter"] = exe
            result["venv"] = detect_venv(exe)
            result["why"] = source
            return result
        if source.startswith("PATH:") and exe:
            result["available"] = True
            result["interpreter"] = exe
            result["why"] = source
            return result

    result["why"] = "没找到：" + ", ".join(tried) if tried else "没有配 interpreters"
    return result


def markers_of(spec):
    return [m.lower() for m in (spec.get("markers") or [])]
