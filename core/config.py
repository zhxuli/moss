# -*- coding: utf-8 -*-
"""配置（TOML）+ 输入法全角前缀还原。

★ 配置文件是 `user_data/config.toml`，格式 **TOML**（`D-23`）。
  为什么不是 JSON：
    · 配置是**给人手改**的，而 JSON 不能写注释 —— 用户打开只看见一堆键值，
      根本不知道某个空串是"没设"还是"故意的"，也就无从下手去改。
    · TOML 能写 `#` 注释，所以**自动生成的默认文件本身就是说明书**（见下面的
      `CONFIG_TEMPLATE`：每一项后面都有一句白话）。
    · 解析零依赖：Python 3.11+ 标准库自带 `tomllib`（只读），自带运行时是 3.12。
    · 宿主**只需要读**：写只发生在"文件不存在时生成默认"，那时直接写那份带注释的
      模板字符串即可 —— Python 标准库没有 TOML 写入库，这里也不需要。
  旧的 `config.json` **不做兼容**（尚未发布，直接换）：现在只认 `.toml`，
  老文件留在磁盘上也不会被读。

★ 字段名与默认值照抄 pa.py:53-78（`E-20` 照抄原则），一个不改：
  `symbols` / `output` / `search` / `ctrl_c` 四组齐全。
★ 首次运行自动创建并提示（照抄 pa.py:80-106 的行为）。
★ `FULLWIDTH_TO_HALF` + `restore_prefix()`：只还原**开头的模式前缀**，
  参数内容一律不碰（中文文件名里的（）、，、。都是合法字符）。
"""
import copy
import os
import tomllib
from pathlib import Path

from . import paths

#: 默认配置。**改这里的时候，`CONFIG_TEMPLATE` 要一起改** —— 自检会核对两者是否一致
#: （`template_problems()`，挂 `moss --selfcheck`），免得"默认值改了、模板没跟上"。
DEFAULT_CONFIG = {
    "symbols": {
        "path_mode": "",           # 空串 = 裸名就是路径调用（默认档，见 bare_owner()）
        "no_chdir_mode": "/",
        "plugin_mode": ":",
        "no_force_kill_mode": "~",
    },
    "output": {
        "auto_clear_screen": True,
        "start_banner": "",
        "end_banner": "",
        "start_time": True,
        "end_time": True,
        "duration": True,
        "pid": True,
        "directory": True,
        "command": True,
        "symbol": "",
    },
    "search": {
        "max_parent_depth": 3,
    },
    "ctrl_c": {
        "force_kill": True,
    },
}

#: 当前生效的配置（`load()` 会用用户文件覆盖它）。
CONFIG = copy.deepcopy(DEFAULT_CONFIG)

#: 首次运行写出去的默认配置：**带注释的 TOML 模板**。
#: 为什么是死字符串而不是序列化出来的：① tomllib 只读，标准库没有 TOML 写入器；
#: ② 需要的正是"注释"—— 模板里那些说明就是给用户的文档，序列化不出一句人话。
#: 每条注释都刻意写"这个值是干什么的 + 有没有坑"，不是复述键名。
CONFIG_TEMPLATE = '''# moss 配置 —— 改完存盘即生效（下一次运行 moss 时读它）。
# 这个文件管的是**宿主**：命令前缀符号 / 输出横幅 / 搜索层数 / Ctrl-C 策略。
# 什么都不改也能用；下面每一项都写了它是干什么的。
#
# ★ 不想开编辑器也行：`moss ui` 界面**右下角那颗齿轮**就是这份文件的面板
#   ——「设置」里改的和这里手改的是同一个文件，它按行换值，注释和排版一字不动。

[symbols]
# 命令前缀符号。四项都可以改成你顺手的字符 —— `moss` 会先去掉前缀再判断类型。
#
# ★ 裸名（不带前缀）归谁，就看这两条：**谁留空，裸名就归谁**。
#   下面这样是"默认档"：裸名 = 路径调用（`moss m` 跑当前项目里的脚本），包要写 `:`。
#   如果主要用途是"跑装好的包"（不常写脚本），可以把这两行对调：
#       plugin_mode = ""
#       path_mode   = ":"
#   那样 `moss img` 直接跑包，`moss :m` 才是找文件。
#   注意：**两项不能同时留空**（那就说不清裸名算哪种了，宿主会提示并按"裸名=路径"处理）。
path_mode          = ""     # 路径调用（**空串 = 裸名**）：   moss m
no_chdir_mode      = "/"    # 跑路径但**不切目录**：          moss /m
plugin_mode        = ":"    # 跑**装好的包**：                moss :img
no_force_kill_mode = "~"    # **后台脱离**运行（脱离后 Ctrl+C 也管不到它）：moss ~m

[output]
# 每次运行前后的那几行提示。嫌吵就关掉对应的项（false / 空串）。
auto_clear_screen = true    # 运行前清屏
start_banner      = ""      # 起始横幅文本（空 = 不打印）
end_banner        = ""      # 结束横幅文本（空 = 不打印）
start_time        = true    # 打印开始时间
end_time          = true    # 打印结束时间
duration          = true    # 打印运行总长
pid               = true    # 打印子进程 PID
directory         = true    # 打印工作目录
command           = true    # 打印将要执行的命令
symbol            = ""      # 行首符号（空 = 用内置的）

[search]
# 运行 `moss m` 时"向上找几层目录"。
max_parent_depth = 3

[ctrl_c]
# Ctrl+C 怎么停：true = 第一次就强杀整棵树；false = 先温和 terminate，再按一次才强杀。
force_kill = true
'''


# ================================================================ 「设置」面板（`V-60` ✅）
# 界面上那颗齿轮点开就是这份清单：**把 user_data/config.toml 里已有的键用控件呈现出来**。
#
# ★ 它不新增任何配置项，也不是"第二处设置"：改完还是写回同一个 `config.toml`
#   （按行换值、注释一字不动，见 `set_values`）。所以手改文件和用面板改，
#   结果完全一样，不会出现"面板说 A、文件说 B"。
# ★ 顺序 = 人会怎么找：先符号（最常改），再输出横幅，再找文件，最后 Ctrl-C。
# ★ `settings_problems()` 会核对「每个默认键都有一行、没有多余的键」，挂在
#   `moss --selfcheck` 上 —— 以后给 DEFAULT_CONFIG 加了键却忘了加这里，自检会说话。
# ★ `type` 决定面板画什么控件：`symbol`（前缀符号，单行窄框）、`text`（普通文本）、
#   `bool`（开关）、`int`（数字）。写回时按 TOML 语法生成值。
SETTINGS_GROUPS = [
    {"name": "命令前缀符号",
     "hint": "四项都可以改成你顺手的字符。★ 谁留空，裸名就归谁 —— "
             "比如「路径调用」留空 = `moss m` 跑脚本；想变成 `moss img` 直接跑包，"
             "就把「跑包」也留空、这里填个符号。",
     "items": [
         {"key": "symbols.path_mode", "label": "路径调用（空串 = 裸名）", "type": "symbol",
          "hint": "例：留空 → moss m"},
         {"key": "symbols.no_chdir_mode", "label": "跑路径但不切目录", "type": "symbol",
          "hint": "例：/ → moss /m"},
         {"key": "symbols.plugin_mode", "label": "跑装好的包", "type": "symbol",
          "hint": "例：: → moss :img"},
         {"key": "symbols.no_force_kill_mode", "label": "后台脱离运行", "type": "symbol",
          "hint": "例：~ → moss ~m（脱离后 Ctrl+C 也管不到它）"},
     ]},
    {"name": "每次运行前后的提示",
     "hint": "嫌吵就关掉对应的开关。横幅文本留空 = 不打印。",
     "items": [
         {"key": "output.auto_clear_screen", "label": "运行前清屏", "type": "bool"},
         {"key": "output.start_banner", "label": "起始横幅文本", "type": "text",
          "hint": "空 = 不打印"},
         {"key": "output.end_banner", "label": "结束横幅文本", "type": "text",
          "hint": "空 = 不打印"},
         {"key": "output.start_time", "label": "打印开始时间", "type": "bool"},
         {"key": "output.end_time", "label": "打印结束时间", "type": "bool"},
         {"key": "output.duration", "label": "打印运行总长", "type": "bool"},
         {"key": "output.pid", "label": "打印子进程 PID", "type": "bool"},
         {"key": "output.directory", "label": "打印工作目录", "type": "bool"},
         {"key": "output.command", "label": "打印将要执行的命令", "type": "bool"},
         {"key": "output.symbol", "label": "行首符号", "type": "text",
          "hint": "空 = 用内置的"},
     ]},
    {"name": "找文件",
     "hint": "运行 `moss m` 这类路径调用时，从当前目录往上找几层。",
     "items": [
         {"key": "search.max_parent_depth", "label": "向上找几层目录", "type": "int",
          "hint": "1~20，默认 3"},
     ]},
    {"name": "Ctrl+C",
     "hint": "关掉的话：第一次按只温和地请它退出，再按一次才强杀整棵树。",
     "items": [
         {"key": "ctrl_c.force_kill", "label": "第一次按就强杀整棵树", "type": "bool"},
     ]},
]


def _setting_spec(key):
    """按键（`段.键`）取面板上那一项的定义；没有返回 None。"""
    for g in SETTINGS_GROUPS:
        for it in g["items"]:
            if it["key"] == key:
                return it
    return None


def settings_problems():
    """自检用：面板清单和 `DEFAULT_CONFIG` 对不对得上。返回问题清单（空 = 一致）。

    两边的**键集合必须完全一样**：面板漏一个键 = 用户改不到它；面板多一个键 =
    点保存时写不进去（`set_values` 会说"文件里没找到那一行"）。所以这里两个方向都查。
    """
    problems = []
    seen = set()
    for g in SETTINGS_GROUPS:
        for it in g["items"]:
            key = str(it.get("key") or "")
            if "." not in key:
                problems.append("设置项 %r 的键要写成「段.键」" % key)
                continue
            section, name = key.split(".", 1)
            if section not in DEFAULT_CONFIG or name not in DEFAULT_CONFIG.get(section, {}):
                problems.append("设置项 %s 在 DEFAULT_CONFIG 里没有对应的键" % key)
                continue
            if key in seen:
                problems.append("设置项 %s 出现了两次" % key)
            seen.add(key)
            want = DEFAULT_CONFIG[section][name]
            kind = it.get("type") or "text"
            if isinstance(want, bool) and kind != "bool":
                problems.append("设置项 %s 是个开关，type 该写 bool（现在 %r）" % (key, kind))
            elif isinstance(want, int) and not isinstance(want, bool) and kind != "int":
                problems.append("设置项 %s 是整数，type 该写 int（现在 %r）" % (key, kind))
            elif isinstance(want, str) and kind not in ("symbol", "text"):
                problems.append("设置项 %s 是字符串，type 该写 symbol/text（现在 %r）"
                                % (key, kind))
    for section, defaults in DEFAULT_CONFIG.items():
        for name in defaults:
            key = "%s.%s" % (section, name)
            if key not in seen:
                problems.append("默认配置里有 %s，但设置面板清单里没有它" % key)
    return problems


def settings_groups():
    """给「设置」面板的那份数据：分组 + 每项的当前值 / 默认值 / 说明。"""
    out = []
    for g in SETTINGS_GROUPS:
        items = []
        for it in g["items"]:
            section, name = it["key"].split(".", 1)
            items.append({
                "key": it["key"],
                "label": it["label"],
                "type": it.get("type") or "text",
                "hint": it.get("hint") or "",
                "value": CONFIG.get(section, {}).get(name, DEFAULT_CONFIG[section][name]),
                "default": DEFAULT_CONFIG[section][name],
            })
        out.append({"name": g["name"], "hint": g.get("hint") or "", "items": items})
    return out


def settings_payload():
    """`moss --settings` 输出给界面的东西（**纯 JSON**）。

    为什么要有这条命令：界面跑在自带运行时里，而 `core` 是编进 exe 的
    （`K-10` 内核最小化）—— 磁盘上根本没有 core 这个目录，界面 import 不到它。
    所以界面要读设置、要改设置，都只能回来叫宿主（和跑包、`--ui-payload` 同一条路）。
    """
    return {"path": str(paths.USER_CONFIG), "groups": settings_groups()}


def _check_values(values):
    """写盘之前先看这批值本身合不合法（面板的"守门人"）。返回问题清单（空 = 可以写）。

    ★ 为什么在这里拦"两个前缀都留空" / "两个前缀撞车"：这两种配置会让
      「裸名到底算什么」说不清，`load()` 每次都只会打一行提示、然后按默认处理 ——
      用户以为自己改了、其实没生效。面板是**有人看着的编辑器**，那种情况下
      直接说"这么配不行"比"写进去、然后每次启动都抱怨一句"强。
    """
    spec = {}
    for g in SETTINGS_GROUPS:
        for it in g["items"]:
            spec[it["key"]] = it
    # 校验看的是「**改完之后的整体**」，不是只看这次动的那几项
    after = {}
    for key in spec:
        section, name = key.split(".", 1)
        after[key] = CONFIG.get(section, {}).get(name, DEFAULT_CONFIG[section][name])
    after.update(values)

    problems = []
    for key, val in values.items():
        it = spec.get(key)
        if it is None:
            problems.append("不认识的设置项：%s" % key)
            continue
        kind = it.get("type") or "text"
        if kind == "bool":
            if not isinstance(val, bool):
                problems.append("%s 要的是开关（true/false），收到 %r" % (key, val))
        elif kind == "int":
            if isinstance(val, bool) or not isinstance(val, int):
                problems.append("%s 要的是整数，收到 %r" % (key, val))
            elif not 1 <= val <= 20:
                problems.append("%s 只允许 1~20（现在 %r）" % (key, val))
        else:
            if not isinstance(val, str):
                problems.append("%s 要的是字符串，收到 %r" % (key, val))
                continue
            if kind == "symbol":
                if len(val) > 4:
                    problems.append("%s 最多 4 个字符（现在 %r）" % (key, val))
                if any(c.isspace() for c in val):
                    problems.append("%s 里不能有空格 / 换行（现在 %r）" % (key, val))
                if "#" in val or "=" in val or '"' in val or "'" in val:
                    problems.append("%s 里不能有 # = \" ' 这几个字符（会和配置文件语法打架，"
                                    "现在 %r）" % (key, val))
            else:
                # TOML 的基本字符串**不能跨行**：横幅文本里混进换行会把整个文件写坏，
                # 而界面上的框就是单行的 —— 这里挡住，别让它有机会落到文件里。
                if "\n" in val or "\r" in val:
                    problems.append("%s 里不能有换行（现在 %r）" % (key, val))

    if not after.get("symbols.path_mode") and not after.get("symbols.plugin_mode"):
        problems.append("「路径调用」和「跑包」不能同时留空 —— 那样裸名（moss m）"
                        "算是哪一种就说不清了")
    used = {}
    for key in ("symbols.path_mode", "symbols.no_chdir_mode",
                "symbols.plugin_mode", "symbols.no_force_kill_mode"):
        v = after.get(key) or ""
        if not v:
            continue                    # 空串不是符号，是"这一类不带前缀"，不参与查重
        if v in used:
            problems.append("「%s」和「%s」用了同一个符号 %r —— 命令含义会有歧义"
                            % (used[v], key, v))
        else:
            used[v] = key
    return problems


def _toml_literal(value, kind):
    """按 TOML 语法写出一个值（这一步决定文件里长什么样）。"""
    if kind == "bool":
        return "true" if value else "false"
    if kind == "int":
        return str(int(value))
    s = str(value)
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')


def _split_comment(rest):
    """把一行的「值 + 后面那段注释」拆开，返回 (值连着它的留白, 注释段)。

    ★ 为什么得扫一遍字符串：符号是用户随便填的，`path_mode = "#"` 是**合法值** ——
      用 `rest.find("#")` 去切会把值本身当成注释切掉，于是"改了、看着没变"。
    """
    quote = ""
    i = 0
    while i < len(rest):
        c = rest[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                quote = ""
        elif c in "\"'":
            quote = c
        elif c == "#":
            return rest[:i], rest[i:]
        i += 1
    return rest, ""


def set_values(values, path=None):
    """把面板上改过的值写回配置文件，返回 `{"ok", "problems", "groups"}`。

    ★ 为什么按行换值，而不是"重新生成整个文件"：那份 TOML 的注释**就是说明书**
      （`D-23`：自动生成的默认文件本身就是文档）。重新生成会把注释全丢掉 ——
      用户下次打开只看见一堆键值，根本不知道某个空串是"没设"还是"故意的"。
    ★ 一个键都没找到 = 一行都不写（不做"写一半"）：半截生效比没生效更难查。
    ★ 写完**立刻按 TOML 读回来核对**：说的和写的不是一回事，这种错在这儿抓住最省事。
    """
    target = Path(path) if path else paths.USER_CONFIG
    problems = _check_values(values)
    if problems:
        return {"ok": False, "problems": problems, "groups": settings_groups()}

    try:
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(CONFIG_TEMPLATE, encoding="utf-8", newline="\n")
        raw = target.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False, "problems": ["读不了配置文件：%s" % e], "groups": settings_groups()}

    nl = "\r\n" if "\r\n" in raw else "\n"
    section = ""
    left = dict(values)
    lines = []
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s[1:-1].strip()
            lines.append(line)
            continue
        head, sep, rest = line.partition("=")
        key = "%s.%s" % (section, head.strip()) if (sep and section) else ""
        if key in left:
            kind = (_setting_spec(key) or {}).get("type") or "text"
            val, comment = _split_comment(rest)
            if val.strip():                                  # 值两边原来的留白照抄
                lead = val[:len(val) - len(val.lstrip())]
                trail = val[len(val.rstrip()):]
            else:
                lead, trail = (val or " "), ""
            lines.append("%s=%s%s%s%s" % (head, lead, _toml_literal(left.pop(key), kind),
                                          trail, comment.rstrip()))
            continue
        lines.append(line)

    if left:
        for k in left:
            problems.append("配置文件里没找到 %s 那一行（我没动这个文件）" % k)
        return {"ok": False, "problems": problems, "groups": settings_groups()}

    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(nl.join(lines) + nl, encoding="utf-8", newline="")
        os.replace(str(tmp), str(target))
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        return {"ok": False, "problems": ["写不进配置文件：%s" % e], "groups": settings_groups()}

    try:
        with open(target, "rb") as f:
            got = tomllib.load(f)
    except Exception as e:                                   # noqa: BLE001
        problems.append("写完之后这个文件读不回来了：%s" % e)
    else:
        for key, want in values.items():
            sec, name = key.split(".", 1)
            have = (got.get(sec) or {}).get(name, "<没有>")
            if have != want:
                problems.append("%s 没写进去：想要 %r，文件里是 %r" % (key, want, have))
            else:
                CONFIG.setdefault(sec, {})[name] = want      # 内存里那份也跟着更新
    return {"ok": not problems, "problems": problems, "groups": settings_groups()}


def _collect_problems(user, problems):
    """把用户配置里"明显写错"的地方挑出来：类型不对 / 段名不认识。

    ★ 为什么要有这道：TOML 里 `max_parent_depth = "3"`（带引号）是**字符串**，
      直接进 `for depth in ...` 之类的比较会抛异常；而段名写错（`[symbol]`）
      会让整段配置**静默失效**。两种都是"用户以为改了、其实没生效"，
      所以一律**打一行说明 + 退回默认值**，不静默、也不崩。
    """
    # ① 段名不认识
    for section in user:
        if section not in DEFAULT_CONFIG:
            problems.append("配置里有不认识的段 [%s]，已忽略（是不是拼错了？）" % section)

    # ② 符号本身写得不合理（重复 / 两个都留空）—— 这两种都会让"命令是什么意思"变得说不清，
    #    必须在用户改完的当场说出来，而不是等他敲命令时莫名其妙。
    sym = user.get("symbols")
    if isinstance(sym, dict):
        names = ("path_mode", "no_chdir_mode", "plugin_mode", "no_force_kill_mode")
        vals = {n: sym.get(n, DEFAULT_CONFIG["symbols"][n]) for n in names}
        if not vals["path_mode"] and not vals["plugin_mode"]:
            problems.append("symbols 里 path_mode 和 plugin_mode **不能同时留空** —— "
                            "那样裸名该算哪一类就说不清了；本次按「裸名 = 路径调用」处理。"
                            "（想改成「裸名 = 跑包」：plugin_mode 留空，path_mode 填个符号）")
        seen = {}
        for n in names:
            v = vals[n]
            if not v:              # 空串不是符号，是"这一类不带前缀"，不参与查重
                continue
            if v in seen:
                problems.append("symbols 里 %s 和 %s 都用了同一个符号 %r —— "
                                "命令含义会有歧义，请改成不同的符号" % (seen[v], n, v))
            else:
                seen[v] = n

    # ③ 类型不对
    for section, defaults in DEFAULT_CONFIG.items():
        got = user.get(section)
        if not isinstance(got, dict):
            continue
        for key, want in defaults.items():
            if key not in got:
                continue
            val = got[key]
            if isinstance(want, bool):
                ok = isinstance(val, bool)
            elif isinstance(want, int):
                ok = isinstance(val, int) and not isinstance(val, bool)
            elif isinstance(want, str):
                ok = isinstance(val, str)
            else:
                ok = True
            if not ok:
                problems.append("%s.%s 要的是 %s，你写的是 %s（%r）→ 本次用默认值 %r"
                                % (section, key, type(want).__name__,
                                   type(val).__name__, val, want))
                got.pop(key)          # 让默认值接手


def load():
    """读用户配置并覆盖默认值；缺文件就自动创建（带注释的模板）。

    照抄 pa.py:80-106 的行为（含"未找到配置文件，将为您自动创建一个"的提示），
    只把格式从 JSON 换成 TOML。
    """
    global CONFIG
    CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    try:
        paths.ensure_user_dirs()
        cfg_path = paths.USER_CONFIG

        if cfg_path.is_file():
            with open(cfg_path, "rb") as f:          # tomllib 只吃二进制流
                user = tomllib.load(f)
            if isinstance(user, dict):
                problems = []
                _collect_problems(user, problems)
                for section, settings in DEFAULT_CONFIG.items():
                    got = user.get(section)
                    if isinstance(settings, dict) and isinstance(got, dict):
                        CONFIG[section].update(got)
                if problems:
                    from . import out
                    for p in problems:
                        out.print_cyan("[配置] %s" % p)
        else:
            from . import out
            out.print_cyan("[配置] 未找到配置文件，将为您自动创建一个。")
            try:
                with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(CONFIG_TEMPLATE)
                out.print_cyan("[配置] 成功创建配置文件: %s" % cfg_path)
            except Exception as e:
                out.print_cyan("[配置错误] 无法创建配置文件: %s" % e)
                out.print_cyan("[配置] 将在本次运行中使用默认设置。")

    except tomllib.TOMLDecodeError as e:
        from . import out
        out.print_cyan("[配置错误] 配置文件语法不对: %s。将使用默认设置。" % e)
    except (OSError, ValueError) as e:
        from . import out
        out.print_cyan("[配置错误] 加载配置文件失败: %s. 将使用默认设置。" % e)
    except Exception as e:
        from . import out
        out.print_cyan("[未知配置错误]: %s. 将使用默认设置。" % e)

    return CONFIG


def template_problems():
    """自检用：`CONFIG_TEMPLATE` 和 `DEFAULT_CONFIG` 是否一致。

    防止"以后给 DEFAULT_CONFIG 加了新键、忘了往模板里加"—— 那样用户打开
    `config.toml` 就看不到这个键，等于文档缺失。返回问题清单（空 = 一致）。
    """
    try:
        parsed = tomllib.loads(CONFIG_TEMPLATE)
    except Exception as e:
        return ["模板本身 TOML 语法错误: %s" % e]
    problems = []
    for section, defaults in DEFAULT_CONFIG.items():
        got = parsed.get(section)
        if not isinstance(got, dict):
            problems.append("模板里缺 [%s] 段" % section)
            continue
        for key, want in defaults.items():
            if key not in got:
                problems.append("模板里缺 %s.%s" % (section, key))
            elif got[key] != want:
                problems.append("模板 %s.%s = %r，默认是 %r" % (section, key, got[key], want))
    for section in parsed:
        if section not in DEFAULT_CONFIG:
            problems.append("模板里有默认配置里没有的段 [%s]" % section)
    return problems


# ---------------------------------------------------------------- 取值helper
def symbols():
    return CONFIG.get("symbols", {})


def plugin_symbol():
    return symbols().get("plugin_mode", ":")


def path_symbol():
    """路径调用的前缀。**空串 = 裸名就是路径调用**（默认档）。"""
    return symbols().get("path_mode", "")


def bare_owner():
    """裸名（不带任何前缀）归哪个命名空间：`"path"` 还是 `"package"`。

    规则一句话：**谁的前缀是空串，裸名就归谁**（`CL-12`）。
      · 默认 `path_mode = ""`、`plugin_mode = ":"` → 裸名 = 路径调用（`moss m`）
      · 对调成 `plugin_mode = ""`、`path_mode = ":"` → 裸名 = 跑包（`moss img`）

    两个都空（配置非法）或两个都非空（谁也没占裸名）→ 一律按 `"path"`：
    `load()` 已经就此打过提示，这里**不再自作聪明**，免得"配置写错"变成"命令乱跑"。
    """
    p = path_symbol()
    g = plugin_symbol()
    if not p and g:
        return "path"
    if p and not g:
        return "package"
    return "path"


def no_chdir_symbol():
    return symbols().get("no_chdir_mode", "/")


def detach_symbol():
    return symbols().get("no_force_kill_mode", "~")


def output_cfg():
    return CONFIG.get("output", {})


def force_kill():
    return CONFIG.get("ctrl_c", {}).get("force_kill", True)


def auto_clear():
    return CONFIG.get("output", {}).get("auto_clear_screen", True)


def max_parent_depth():
    return CONFIG.get("search", {}).get("max_parent_depth", 3)


def restore_prefix(arg):
    """把参数开头被输入法打成全角的模式前缀还原成半角。

    照抄 pa.py:126-149 —— 只处理开头最多两个字符，而且只认 moss 自己在用的
    三个前缀符号（`:` 插件、`/` 不切目录、`~` 后台脱离）。
    后面的内容一概不动：中文文件名里的（）、，、。都是合法字符，
    把整个参数一起转反而会把 `moss 报告（终稿）` 这种东西改坏。
    """
    if not arg:
        return arg
    # ★ 空串符号要滤掉：它是"配置没填"的意思，不是"匹配任何开头"
    prefixes = {s for s in (plugin_symbol(), no_chdir_symbol(), detach_symbol()) if s}
    out = list(arg)
    for i in range(min(2, len(out))):
        half = FULLWIDTH_TO_HALF.get(out[i])
        if half and half in prefixes:
            out[i] = half
        else:
            break
    return "".join(out)


# pa.py:116-123 原样
FULLWIDTH_TO_HALF = {
    '：': ':', '；': ';', '，': ',', '。': '.', '、': '\\', '／': '/',
    '＝': '=', '－': '-', '～': '~', '！': '!', '？': '?', '＠': '@',
    '＃': '#', '＄': '$', '％': '%', '＾': '^', '＆': '&', '＊': '*',
    '（': '(', '）': ')', '【': '[', '】': ']', '｛': '{', '｝': '}',
    '《': '<', '》': '>', '｜': '|', '＋': '+', '＿': '_',
    '“': '"', '”': '"', '‘': "'", '’': "'", '　': ' ',
}
