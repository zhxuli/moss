# -*- coding: utf-8 -*-
"""runner 注册表：**执行方式变成数据**（`F-19` / `E-14`）。

这一块是"内核最小化"（`K-10`）的关键：
    加一种语言 = 往 `system/runners.json` 加一条，或者往 `user_data/runners.json` 加一条。
    **不改宿主代码，不重编 exe。**

两层叠放：
    system/runners.json      随版本走
    user_data/runners.json   用户覆盖（优先）
    自带的解释器放 system/runtimes/<家族>/<版本>/（用户层可覆盖同名版本）

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
    """系统层 + 用户层叠加，用户优先。

    ★ 跳过 `_` 开头的键和任何非字典的值。
      为什么必须有这道过滤：`runners.json` 是给人手改的文件，忍不住会写注释键
      （本文件自己就有一个 `_priorityWhy`）。原来 `table.update(data)` 会把
      注释字符串也当成 runner 塞进表里，之后 `by_ext` 对它调 `.get()` 直接崩，
      **整套 runner 表全废** —— 加一行说明就把程序搞挂，这个代价太大了。
      实测踩到：加 `_priorityWhy` 的当天就崩在 `find()` 里。
    """
    table = {}
    for f in (paths.SYSTEM_RUNNERS, paths.USER_RUNNERS):
        if f.is_file():
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    for name, spec in data.items():
                        if name.startswith("_") or not isinstance(spec, dict):
                            continue      # 注释键 / 写坏了的值，忽略掉
                        table[name] = spec
            except Exception:
                pass
    return table


def by_ext(table, ext):
    """扩展名 → (runner 名, runner 定义)。查表，不是写死的 if/elif。

    再兜一层 `isinstance(spec, dict)`：万一有别的路径把脏值塞进表里，
    这里是"整个解析流程的必经之地"，不能让它崩。
    """
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
    """同一层里多个候选打平时的**类型优先级**（数字越小越优先）。

    ★ 顺序的依据不是"语言流行度"，而是**这个文件被放在这里当入口的故意程度**：
        1  shell(.bat/.cmd)  作者手写的启动脚本 —— 往往还会先激活 venv、设好环境，
                             直接跑源码反而缺环境
        2  powershell(.ps1)  同样是脚本
        3  exe               编译好的成品
        4  python / 5 go     源码
        6  html              「打开一个页面」，最被动
        99 没写 priority 的   新加一门语言不用改宿主代码

    ★ 顺序来自 `runners.json` 的 `priority` 字段，**不写死在这里** ——
      这是 F-19「执行方式变成数据」：加语言只改 JSON。
      没写就排最后，所以以后新增 runner 忘填也不会插到别人前面。
    """
    try:
        return int(spec.get("priority", 99))
    except (TypeError, ValueError):
        return 99


def has_marker_near(base, markers, depth=None):
    """`base` 或它的祖先目录里有没有这些标记文件？

    用途：判断"这是不是一个（模块化的）项目" —— 比如 Go 有 go.mod 就说明
    该用 `go run .` 跑整个包，没有就只能 `go run <文件>`。

    和 resolve 里的项目标记一样，**要往上找**（在 `proj/cmd/` 里跑，
    `proj/go.mod` 也得算数）。
    """
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


# ---------------------------------------------------------------- 自带运行时
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
    """'3.12.11' → (3, 12, 11)，可比较。"""
    out = []
    for part in str(text).replace("-", ".").split("."):
        if part.isdigit():
            out.append(int(part))
        else:
            break
    return tuple(out) or (0,)


def _ver_matches(version, requirement):
    """版本是否满足要求。

        "3.12"  → 精确到 major.minor（前两段相同）
        "3"     → 同主版本
    """
    if not requirement:
        return False
    req, ver = _ver_tuple(requirement), _ver_tuple(version)
    if len(req) == 1:
        return ver[:1] == req
    return ver[:len(req)] == req


def runtime_families():
    """所有运行时家族名（python / node / …）。"""
    fams = set()
    for base in (paths.USER_RUNTIMES, paths.SYSTEM_RUNTIMES):
        if base.is_dir():
            for d in base.iterdir():
                if d.is_dir():
                    fams.add(d.name)
    return sorted(fams)


def runtime_versions(family):
    """某家族下的所有版本，**用户层优先**（同版本用户层覆盖系统层）。

    目录结构：`<runtimes>/<family>/<版本>/`

    ⚠️ family 为空必须直接返回空表 —— 大多数 runner（go / html / powershell /
       shell / exe）**根本不依赖自带运行时**，spec 里没有 "runtime" 字段。
       不挡这一下就会 `Path / None` 直接 TypeError 崩掉。
    """
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
                continue                       # 用户层已经占了
            by_ver[ver] = {"version": ver, "dir": v, "layer": layer, "meta": meta}
    return sorted(by_ver.values(), key=lambda r: _ver_tuple(r["version"]))


def default_version(family):
    """读 `default.json` 里**钉住**的默认版本（用户层优先）。"""
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
    """挑一个自带运行时目录，找不到返回 None。

    ★ **family 为空 = 这个 runner 不用自带运行时**（go / html / powershell /
      shell / exe 都是），直接返回 None。它们靠 `interpreters` 里的
      `PATH:xxx` 或 builtin 去找自己的解释器。

    ★ 默认版本是**钉住的**（`default.json`），**不是自动取最高版本**。
      否则以后新装一个 3.14，所有没声明版本的包会在你毫无察觉的情况下换解释器。
      要换默认版本，必须显式改 `default.json` —— 那是一个有意识的决定。

    ★ 包可以钉死自己的版本：`pkg.json` 里 `"requires": { "python": "3.12" }`。
      钉了但没装 → 返回 None，**绝不退而求其次用别的版本**。
    """
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

    # 没钉默认版本 → 用最高的（自检会提醒去钉一个）
    return versions[-1]["dir"]


def list_runtimes():
    """列出所有自带运行时（家族 × 版本）。给自检用。"""
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


def probe(name, spec, ctx, kind="path", requirement=None):
    """探测这个 runner 在这台机器上能不能用。

    kind:        "package"（跑我们自己的包）| "path"（跑用户项目里的脚本）
                两者解释器顺序不同，见模块 docstring。
    requirement: 包钉的运行时版本，如 "3.12"。钉了但没装 → 直接不可用，
                绝不退而求其次用别的版本。

    返回 {"available", "interpreter", "venv", "runtime", "why"}
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

    family = spec.get("runtime")
    ctx = dict(ctx)
    rd = runtime_dir(family, requirement)
    ctx["runtime"] = rd or ""
    result["runtime"] = rd

    # 钉了版本但没装 → 直接判定不可用。**不许静默换版本**。
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
