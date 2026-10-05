# -*- coding: utf-8 -*-
"""**设置面板的规则**（纯函数）—— 宿主和界面**共用这一份**（`V-276`）。

为什么要独立出来
----------------
你说得对：「后台的 python 代码自己为什么不干，还得重起一个进程？」。原来的做法是
**界面 → 起一个 `moss.exe` → 它在里面算**（真机实测那一趟 **0.73~1.07 秒**，
而真正算这几行只要 **≈20ms**）。根因是 `U-16` 那条分层规矩被一刀切了：
发行版里 `core/` 编进 exe、磁盘上没有，界面 `import core` 会失败 ⇒ 于是连
"纯读纯算"的活也一律回头叫宿主。

现在把规则搬到这里：**`system/` 下的一个普通模块**（随发行版走、磁盘上一定有），
* 宿主 `core/config.py` 调它（CLI / 打包后的 exe 都走这条）；
* 界面进程 `system/ui/main.py` 也 import 它 ⇒ **同进程、0 进程、<1ms**。

三条纪律
--------
1. **不许 import `core`**（否则界面又拿不到）—— 这里的默认值来自 `settings.json`；
2. 与 `core/config.py` 里的实现**行为必须逐字一致** —— `tools/设置规则探针.py` 拿同一批
   输入把两边的 `problems / notes / live` 逐字对比（谁改了都得两边一起改，否则探针红）；
3. 面板清单（有哪些键、标签、说明、默认值）是**数据**：`settings.json`
   （由 `tools/导出设置清单.py` 从 `core/config.py` 的 `SETTINGS_GROUPS` 生成）。
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent                 # system/option
SPEC_FILE = HERE / "settings.json"

#: 读一次就够（面板是静态资产）
_CACHE = {}


def spec():
    """`settings.json` 的内容（读不到就返回一个空壳 —— 调用方自己会退回宿主那一路）。"""
    if "spec" in _CACHE:
        return _CACHE["spec"]
    try:
        data = json.loads(SPEC_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    _CACHE["spec"] = data
    return data


def symbol_bad():
    return set(spec().get("symbol_bad") or "")


def groups():
    return spec().get("groups") or []


def items():
    """`{键: 那一项的定义}`（键是 `段.键`）。"""
    if "items" in _CACHE:
        return _CACHE["items"]
    out = {}
    for g in groups():
        for it in (g.get("items") or []):
            out[it["key"]] = it
    _CACHE["items"] = out
    return out


def setting_spec(key):
    return items().get(str(key or ""))


def after_values(values, current=None):
    """把"这次要改的"叠在"当前生效的"上面 —— 校验看的是**改完之后**的整体。

    `current` = 当前生效值（界面手里是打开面板时拿到的 `orig`；宿主那边是 `CONFIG`）。
    界面每次都会把**整份面板状态**发过来，所以 `current` 通常用不上；它只是兜底。
    """
    cur = dict(current or {})
    after = {}
    for key, it in items().items():
        after[key] = cur.get(key, it.get("default"))
    after.update(values or {})
    return after


def live(after):
    """底部那块预览（多行）：一个能照抄的例子 + 搜索逻辑（`V-156` / `V-157`）。"""
    p = after.get("symbols.path_mode") or ""
    g = after.get("symbols.plugin_mode") or ""
    n = after.get("symbols.no_chdir_mode") or ""
    d = after.get("symbols.no_force_kill_mode") or ""
    depth = 3
    try:
        depth = int(after.get("search.max_parent_depth", 3))
    except (TypeError, ValueError):
        pass
    who = "跑包" if (p and not g) else "找文件"
    out = ["现在：裸名 moss m 归「%s」" % who, ""]
    out.append("例子：文件在 ./src/ceshi/main.py")
    out.append("  moss %ss/c/m        每段按前缀找：s→src/  c→ceshi/  m→main.py" % p)
    out.append("                      找到就用 python 跑它，工作目录切到 src/ceshi/")
    if n:
        out.append("  moss %s%ss/c/m       同一个文件，但在当前目录跑（不切过去）" % (n, p))
    out.append("")
    out.append("怎么找：从当前目录往上逐层找（连自己一共 %d 个目录），某一层里第一个满足的就用它"
               % (depth + 1))
    out.append("        某一段要是目录（s、c），最后一段是文件名的开头（m）；大小写不敏感")
    out.append("        同一层有多个候选时：项目标记 → 上次在这个目录选过的 → 类型优先级；还打平就问你")
    out.append("执行的是：python <找到的那个文件>（那一层有 venv 就用 venv 里的 python）")
    if g:
        out.append("")
        out.append("其他：moss %simg   跑装好的包        moss %sm   后台脱离运行" % (g, d) if d
                   else "其他：moss %simg   跑装好的包" % g)
    if not p and not g:
        out.append("")
        out.append("⚠ 两个都留空 —— 裸名（moss m）到底算找文件还是跑包，说不清了")
    if p and g:
        out.append("")
        out.append("⚠ 两个都有前缀 —— 谁也没占住裸名，moss m 现在按「找文件」处理")
    return "\n".join(out)


def notes(after):
    """每一行底下那句「现在这样」（宿主算、界面只显示）：键 → 一句话。"""
    out = {}
    p = after.get("symbols.path_mode") or ""
    g = after.get("symbols.plugin_mode") or ""
    n = after.get("symbols.no_chdir_mode") or ""
    d = after.get("symbols.no_force_kill_mode") or ""
    out["symbols.path_mode"] = ("现在：裸名 moss m = 找文件并运行"
                                if not p else "现在：moss %sm = 找文件并运行" % p)
    out["symbols.plugin_mode"] = ("现在：裸名 moss img = 跑包"
                                  if not g else "现在：moss %simg = 跑包" % g)
    out["symbols.no_chdir_mode"] = ("现在：这一类不带前缀（用裸名或路径前缀）"
                                    if not n else "现在：moss %sm = 找文件但不切目录" % n)
    out["symbols.no_force_kill_mode"] = ("现在：这一类不带前缀"
                                         if not d else "现在：moss %sm = 后台脱离" % d)
    it = setting_spec("search.max_parent_depth") or {}
    try:
        v = int(after.get("search.max_parent_depth", it.get("default")))
    except (TypeError, ValueError):
        v = it.get("default") or 0
    out["search.max_parent_depth"] = ("现在：只在当前目录找，不往上"
                                      if v == 0 else
                                      "现在：从当前目录起往上找 %d 级（连自己一共 %d 个目录）"
                                      % (v, v + 1))
    return out


def problems(values, current=None):
    """看这批值合不合法 / 有没有该提醒的地方。

    返回 `[{"key", "why", "level", "also"}]`：`level` 是 `"error"`（不许保存）或
    `"warn"`（只是提醒，能存）。**逐字照抄 `core/config.py::_check_values`**（行为要对上）。
    """
    values = dict(values or {})
    after = after_values(values, current)
    out = []
    bad_chars = symbol_bad()

    def err(key, why, also=None):
        out.append({"key": key, "why": why, "level": "error", "also": list(also or [])})

    def warn(key, why, also=None):
        out.append({"key": key, "why": why, "level": "warn", "also": list(also or [])})

    # ① 逐项：类型 / 范围 / 字符
    for key, val in values.items():
        it = setting_spec(key)
        if it is None:
            err(key, "不认识的设置项")
            continue
        kind = it.get("type") or "text"
        if kind == "raw":
            continue                    # `V-159`：表 / 结构化的项，通用校验管不着
        if kind == "bool":
            if not isinstance(val, bool):
                err(key, "要的是开关（true / false），收到 %r" % (val,))
        elif kind == "int":
            if isinstance(val, bool) or not isinstance(val, int):
                err(key, "要的是整数，收到 %r" % (val,))
            elif not 0 <= val <= 20:
                err(key, "只允许 0~20（0 = 只看当前目录，现在 %r）" % (val,))
        else:
            if not isinstance(val, str):
                err(key, "要的是字符串，收到 %r" % (val,))
                continue
            if kind == "symbol":
                if len(val) > 4:
                    err(key, "最多 4 个字符（现在 %r）" % (val,))
                if any(c.isspace() for c in val):
                    err(key, "里不能有空格 / 换行（现在 %r）" % (val,))
                _bad = sorted({c for c in val if c in bad_chars})
                if _bad:
                    err(key, "「%s」在命令行里有特殊意思（重定向 / 管道 / 变量 / 通配那一类），"
                             "当前缀会出事 —— 换一个普通的，比如 / : ~ . - _ 或者一个字母"
                             % " ".join(_bad))
            else:
                # TOML 的基本字符串不能跨行：横幅文本里混进换行会把整个文件写坏
                if "\n" in val or "\r" in val:
                    err(key, "里不能有换行（现在 %r）" % (val,))

    # ② 跨项：裸名归谁（这是这两种前缀符号互相干扰的地方）
    if not after.get("symbols.path_mode") and not after.get("symbols.plugin_mode"):
        pair = ["symbols.path_mode", "symbols.plugin_mode"]
        main = next((k for k in pair if k in values), pair[0])
        err(main, "「路径调用」和「跑包」不能同时留空 —— 那样裸名（moss m）算哪一种"
                  "就说不清了", also=[k for k in pair if k != main])

    # 同一个符号用两次：把**同一组的键**收在一起，然后报在"用户刚动过的那一行"上
    def _label(k):
        it = setting_spec(k) or {}
        return it.get("label") or k

    by_value = {}
    for key in ("symbols.path_mode", "symbols.no_chdir_mode",
                "symbols.plugin_mode", "symbols.no_force_kill_mode"):
        v = after.get(key) or ""
        if v:                           # 空串不是符号，是"这一类不带前缀"，不参与查重
            by_value.setdefault(v, []).append(key)
    for v, keys in by_value.items():
        if len(keys) < 2:
            continue
        main = next((k for k in keys if k in values), keys[0])
        others = [k for k in keys if k != main]
        err(main, "和「%s」用了同一个符号 %r —— 命令含义会有歧义"
            % ("、".join(_label(k) for k in others), v), also=others)

    # ③ 提醒（能存，但值得知道）
    try:
        depth = int(after.get("search.max_parent_depth", 3))
    except (TypeError, ValueError):
        depth = 3
    if depth >= 6:
        warn("search.max_parent_depth",
             "找得有点远（一共 %d 个目录）—— 容易撞上上层项目里的同名文件，"
             "撞上就会停下来问你" % (depth + 1))
    flags = ("output.command", "output.directory", "output.pid",
             "output.start_time", "output.end_time", "output.duration")
    if (not any(bool(after.get(k)) for k in flags)
            and not str(after.get("output.start_banner") or "").strip()
            and not str(after.get("output.end_banner") or "").strip()):
        warn("output.command", "运行前后一行提示都不打了 —— 出问题时不容易看出"
                               "它到底跑没跑、跑了什么")
    return out


def check(values=None, current=None):
    """面板要的那一份：`{"ok", "problems", "notes", "live"}`（跟宿主 `--settings-check` 同形）。"""
    vals = dict(values or {})
    after = after_values(vals, current)
    probs = problems(vals, current)
    return {"ok": not any(p["level"] == "error" for p in probs),
            "problems": probs,
            "notes": notes(after),
            "live": live(after)}


def panel(current=None):
    """给「设置」面板的那份数据：分组 + 每项的当前值 / 默认值 / 说明。

    `current` = 当前生效值（界面手里是宿主给的 `value`；宿主那边是 `CONFIG`）。
    缺了就用 `settings.json` 里的 `default`。
    """
    cur = dict(current or {})
    out = []
    for g in groups():
        its = []
        for it in (g.get("items") or []):
            its.append({"key": it["key"], "label": it["label"],
                        "type": it.get("type") or "text", "hint": it.get("hint") or "",
                        "value": cur.get(it["key"], it.get("default")),
                        "default": it.get("default")})
        out.append({"name": g["name"], "icon": g.get("icon") or "",
                    "blurb": g.get("blurb") or "", "live": bool(g.get("live")),
                    "items": its})
    return out
