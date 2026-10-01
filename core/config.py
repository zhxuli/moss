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
import re
import tomllib
from pathlib import Path

from . import paths

#: 默认配置。**改这里的时候，`CONFIG_TEMPLATE` 要一起改** —— 自检会核对两者是否一致
#: （`template_problems()`，挂 `moss --selfcheck`），免得"默认值改了、模板没跟上"。
#: AI 那几组参数的字段（`V-137`）：一组一份，明文存 `user_data/config.toml` 的 `[ai.profiles.<组名>]`。
AI_FIELDS = ("base_url", "api_key", "model", "temperature", "max_tokens",
             "top_p", "timeout", "stream", "note")

DEFAULT_CONFIG = {
    # ★ `V-137`：AI 那几组（`[ai] active` + `[ai.profiles.<组名>]`）—— **不声明在这里，
    #   `load()` 会把整段当"不认识的段"丢掉**（实测踩过：写了组、读回来是空的）。
    "ai": {"active": "", "profiles": {}},
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


# ---------------------------------------------------------------- AI（`V-137`）
# 一组 = `[ai.profiles.<组名>]`；`active` 指当前用哪一组。参数**明文**存在这个文件里
# （它在 user_data/ 下、不进仓库）；跑包时宿主会把当前那组注入成 `MOSS_AI_*` 环境变量。
#   字段：base_url 接口地址 / api_key 密钥 / model 模型名 / temperature 温度 /
#         max_tokens 最大输出（0=不限）/ top_p / timeout 秒 / stream 流式 / note 备注
# 加一组（命令行最省事，也可以照这个样子手写）：
#   moss --ai-profile-set mine base_url=https://api.deepseek.com/v1 model=deepseek-chat api_key=sk-xxx
# ★ 这里**只声明 active**：示例写在注释里 —— 模板和默认值（`DEFAULT_CONFIG`）必须对得上，
#   不然 `--selfcheck` 的"模板和默认值一致"那条会报错（实测踩过）。
[ai]
active = ""
# 各组：一组一张表（`moss --ai-profile-set <组名> …` 会往里加；也可以照注释里的样子手写）
[ai.profiles]
'''


# ================================================================ 「设置」面板（`V-60` ✅ / `V-63` ✅）
# 界面上那颗齿轮点开就是这份清单：**把 user_data/config.toml 里已有的键用控件呈现出来**。
#
# ★ 它不新增任何配置项，也不是"第二处设置"：改完还是写回同一个 `config.toml`
#   （按行换值、注释一字不动，见 `set_values`）。所以手改文件和用面板改，
#   结果完全一样，不会出现"面板说 A、文件说 B"。
# ★ **这里的分组顺序 ≠ 文件里的顺序**：写回是"按键找那一行"，不按顺序生成文件，
#   所以可以放心把最常改的摆前面、把相关的排在一起。
# ★ 每一项都得把话说明白（`V-63` 的教训：原来「向上找几层目录」这种写法，
#   人根本不知道它在说什么）——`label` 是名字，`hint` 是"它到底干什么、什么时候用"。
# ★ `type` 决定面板画什么控件：`symbol`（前缀符号，单个字符的小框）、`text`（文本）、
#   `bool`（开关）、`int`（步进器）。
# ★ `settings_problems()` 会核对这份清单和 `DEFAULT_CONFIG` 对不对得上（键、类型、
#   以及每条该有的说明有没有写），挂在 `moss --selfcheck` 上。
SETTINGS_GROUPS = [
    # `V-137`：AI 参数（多组）。`ai.active` 是普通文本（组名）；`ai.profiles` 是**表**，
    # 面板里只显示一行说明、不能手改（改它走 `moss --ai-profile-set`，见 `set_values` 里的路由）。
    {"name": "AI", "icon": "cpu", "blurb": "AI 参数（可以配多组）：一组一份，明文存在 user_data/config.toml；"
                            "跑包时会把当前那组注入成 MOSS_AI_* 环境变量",
     "items": [
         {"key": "ai.active", "label": "当前组", "type": "text",
          "hint": "现在用哪一组；组名要和 [ai.profiles.<组名>] 对上（改名请用 moss --ai-profile-set）"},
         {"key": "ai.profiles", "label": "各组", "type": "text",
          "hint": "加/改组请用命令行：moss --ai-profile-set <组名> base_url=… model=… api_key=…；"
                  "moss --ai-active <组名> 切当前组；moss --ai-test 测连接。"},
     ]},
    {"name": "快捷命令", "icon": "hash", "live": True,
     "blurb": "行首那个符号决定这条命令是什么意思。四项都能换成你顺手的字符"
              "（moss 会先去掉前缀，再判断这条命令属于哪一类）。"
              "谁留空，裸名就归谁 —— 这两项是互相牵制的，配错了下面会标红。",
     "items": [
         {"key": "symbols.path_mode", "label": "路径调用", "type": "symbol",
          "hint": "留空 = 裸名就是它：moss m 直接在当前目录（及上层）找 main.py 之类的入口跑。"},
         {"key": "symbols.no_chdir_mode", "label": "不切目录", "type": "symbol",
          "hint": "moss /m：在**当前目录**跑那个文件，不切到它所在的目录 —— "
                  "脚本里要用当前目录的相对路径时用这个。"},
         {"key": "symbols.plugin_mode", "label": "跑包", "type": "symbol",
          "hint": "moss :img：冒号后面是包名，id 和别名都能用。"},
         {"key": "symbols.no_force_kill_mode", "label": "后台脱离", "type": "symbol",
          "hint": "moss ~m：脱离控制台跑，Ctrl+C 也管不到它 —— 跑服务、跑长任务用。"},
     ]},
    {"name": "执行提示", "icon": "terminal",
     "blurb": "每次跑东西时，宿主在运行前 / 运行后打印的那几行。嫌吵就关掉对应的开关"
              "（关掉之后，界面「命令行」那一页里也会少这几行）。",
     "items": [
         {"key": "output.auto_clear_screen", "label": "运行前清屏", "type": "bool",
          "hint": "先清掉上一次的输出再跑；想留着它就别开。"},
         {"key": "output.command", "label": "打印将要执行的命令", "type": "bool",
          "hint": "把最终敲的那条命令原样打出来 —— 排查参数问题时最有用的一行。"},
         {"key": "output.directory", "label": "打印工作目录", "type": "bool",
          "hint": "这个包（或脚本）是在哪个目录里跑的。"},
         {"key": "output.pid", "label": "打印子进程 PID", "type": "bool",
          "hint": "子进程的进程号 —— 和任务管理器里对上号用。"},
         {"key": "output.start_time", "label": "打印开始时间", "type": "bool",
          "hint": "哪一刻开始跑的。"},
         {"key": "output.end_time", "label": "打印结束时间", "type": "bool",
          "hint": "哪一刻跑完的。"},
         {"key": "output.duration", "label": "打印运行总长", "type": "bool",
          "hint": "跑完打印这次用了多久（秒）。"},
     ]},
    {"name": "输出格式", "icon": "type",
     "blurb": "那几行的文字样式：前后各可以打一整行自己的话，也能改行首的符号。",
     "items": [
         {"key": "output.start_banner", "label": "起始横幅文本", "type": "text",
          "hint": "运行前打印的一整行自定义文字；留空 = 不打印。"},
         {"key": "output.end_banner", "label": "结束横幅文本", "type": "text",
          "hint": "运行后打印的一整行自定义文字；留空 = 不打印。"},
         {"key": "output.symbol", "label": "行首符号", "type": "text",
          "hint": "上面那几行开头的符号（例如 >）；留空 = 用内置的 [执行] 这种。"},
     ]},
    {"name": "高级设置", "icon": "sliders",
     "blurb": "不常动的两项：找文件往上找几层，以及按 Ctrl+C 时怎么处理这个子进程树。",
     "items": [
         {"key": "search.max_parent_depth", "label": "向上查找层数", "type": "int",
          "hint": "跑 moss m 这类路径调用时，从当前目录开始一层层往上找，谁先命中算谁。"
                  "这一项是「含当前目录在内最多看几个目录」：默认 3 = 当前 + 往上 3 级，"
                  "一共 4 个目录。往上找得越远越慢，也越容易撞上上层项目里的同名文件"
                  "（撞上就会停下来问你选哪个）。"},
         {"key": "ctrl_c.force_kill", "label": "第一次按 Ctrl+C 就强杀整棵树", "type": "bool",
          "hint": "在终端里按 Ctrl+C 时，第一次就强杀整棵进程树。关掉之后：第一次只温和地"
                  "请它退出，再按一次才强杀 —— 有收尾工作的包适合关掉。"},
     ]},
]

def _split_key(key):
    section, _, name = str(key).partition(".")
    return section, name


def _setting_spec(key):
    """按键（`段.键`）取面板上那一项的定义；没有返回 None。"""
    for g in SETTINGS_GROUPS:
        for it in g["items"]:
            if it["key"] == key:
                return it
    return None


def _after_values(values):
    """把「这次要改的」叠在「当前生效的」上面 —— 校验看的是改完之后的整体。"""
    after = {}
    for g in SETTINGS_GROUPS:
        for it in g["items"]:
            section, name = _split_key(it["key"])
            after[it["key"]] = CONFIG.get(section, {}).get(name, DEFAULT_CONFIG[section][name])
    after.update(values or {})
    return after


def _live_line(after):
    """「现在这样」那一行（给命令前缀符号那组用的活预览）。

    ★ 为什么这句话必须由宿主算：裸名归谁是一条规则（谁的前缀是空串谁占裸名），
      界面自己推一遍就是第二处真相。面板每改一下都来问一次，显示的就是当下真的会怎样。
    """
    p = after.get("symbols.path_mode") or ""
    g = after.get("symbols.plugin_mode") or ""
    if not p and not g:
        return "⚠ 两个都留空 —— 裸名（moss m）到底算找文件还是跑包，说不清了"
    if p and g:
        return "⚠ 两个都有前缀 —— 谁也没占住裸名，moss m 现在按「找文件」处理"
    who = "跑包" if (p and not g) else "找文件"
    parts = ["现在：裸名 moss m 归「%s」" % who]
    if p:
        parts.append("moss %sm 找文件" % p)
    if g:
        parts.append("moss %simg 跑包" % g)
    n = after.get("symbols.no_chdir_mode") or ""
    if n:
        parts.append("moss %sm 不切目录" % n)
    d = after.get("symbols.no_force_kill_mode") or ""
    if d:
        parts.append("moss %sm 后台脱离" % d)
    return " ｜ ".join(parts)


def _notes_for(after):
    """每一行底下那句「现在这样」（宿主算、界面只显示）：键 → 一句话。"""
    notes = {}
    p = after.get("symbols.path_mode") or ""
    g = after.get("symbols.plugin_mode") or ""
    n = after.get("symbols.no_chdir_mode") or ""
    d = after.get("symbols.no_force_kill_mode") or ""
    notes["symbols.path_mode"] = ("现在：裸名 moss m = 找文件"
                                  if not p else "现在：moss %sm = 找文件" % p)
    notes["symbols.plugin_mode"] = ("现在：裸名 moss img = 跑包"
                                    if not g else "现在：moss %simg = 跑包" % g)
    notes["symbols.no_chdir_mode"] = ("现在：这一类不带前缀（用裸名或路径前缀）"
                                      if not n else "现在：moss %sm = 不切目录" % n)
    notes["symbols.no_force_kill_mode"] = ("现在：这一类不带前缀"
                                           if not d else "现在：moss %sm = 后台脱离" % d)
    try:
        v = int(after.get("search.max_parent_depth", DEFAULT_CONFIG["search"]["max_parent_depth"]))
    except (TypeError, ValueError):
        v = DEFAULT_CONFIG["search"]["max_parent_depth"]
    notes["search.max_parent_depth"] = ("现在：从当前目录起，连自己带父目录一共 %d 个目录"
                                        "（当前 + 往上 %d 级）" % (v + 1, v))
    return notes


def _check_values(values):
    """看这批值合不合法 / 有没有该提醒的地方。

    返回 `[{"key", "why", "level"}]`：`level` 是 `"error"`（不许保存）或
    `"warn"`（只是提醒，能存）。
    ★ 为什么要把 `key` 带上：面板得把出问题的那一行标红，只有一句话不知道该红哪儿。
    """
    values = dict(values or {})
    after = _after_values(values)
    problems = []

    # ★ `also`：这条冲突**还牵涉哪几行** —— 面板要把它们一起标红
    #   （"两个前缀不能同时留空"是两行一起错，只红一行会让人以为改那一行就行）。
    def err(key, why, also=None):
        problems.append({"key": key, "why": why, "level": "error", "also": list(also or [])})

    def warn(key, why, also=None):
        problems.append({"key": key, "why": why, "level": "warn", "also": list(also or [])})

    # ① 逐项：类型 / 范围 / 字符
    for key, val in values.items():
        it = _setting_spec(key)
        if it is None:
            err(key, "不认识的设置项")
            continue
        kind = it.get("type") or "text"
        if kind == "bool":
            if not isinstance(val, bool):
                err(key, "要的是开关（true / false），收到 %r" % (val,))
        elif kind == "int":
            if isinstance(val, bool) or not isinstance(val, int):
                err(key, "要的是整数，收到 %r" % (val,))
            elif not 1 <= val <= 20:
                err(key, "只允许 1~20（现在 %r）" % (val,))
        else:
            if not isinstance(val, str):
                err(key, "要的是字符串，收到 %r" % (val,))
                continue
            if kind == "symbol":
                if len(val) > 4:
                    err(key, "最多 4 个字符（现在 %r）" % (val,))
                if any(c.isspace() for c in val):
                    err(key, "里不能有空格 / 换行（现在 %r）" % (val,))
                if "#" in val or "=" in val or '"' in val or "'" in val:
                    err(key, "里不能有 # = \" ' 这几个字符（会和配置文件语法打架，"
                             "现在 %r）" % (val,))
                elif val and val in "/\\.":
                    warn(key, "「%s」也是路径里常见的字符 —— moss /m 和 moss /a/b "
                              "会长得很像，容易看错" % val)
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
    # （不然红字会落在另一行上，看着像在说别人）
    def _label(k):
        it = _setting_spec(k) or {}
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
    # ★ 注意 `after` 里的键是**扁平的**（`output.pid` 这种），不是嵌套 dict ——
    #   这里踩过一次：写成 `after.get("output")` 拿到 None，于是"全关"那条提醒
    #   不管怎么配都会响。
    flags = ("output.command", "output.directory", "output.pid",
             "output.start_time", "output.end_time", "output.duration")
    if (not any(bool(after.get(k)) for k in flags)
            and not str(after.get("output.start_banner") or "").strip()
            and not str(after.get("output.end_banner") or "").strip()):
        warn("output.command", "运行前后一行提示都不打了 —— 出问题时不容易看出"
                               "它到底跑没跑、跑了什么")
    return problems


def settings_check(values=None):
    """只校验、不写盘：面板每改一下就来问一次，用来标红 + 决定保存按钮能不能点。

    回 `{"ok", "problems", "notes", "live"}`：`ok` = 没有 error（warn 不算）。
    """
    values = dict(values or {})
    after = _after_values(values)
    problems = _check_values(values)
    return {"ok": not any(p["level"] == "error" for p in problems),
            "problems": problems,
            "notes": _notes_for(after),
            "live": _live_line(after)}


def settings_problems():
    """自检用：面板清单和 `DEFAULT_CONFIG` 对不对得上。返回问题清单（空 = 一致）。

    两边键集合必须完全一样：面板漏一个键 = 用户改不到；面板多一个键 =
    点保存时写不进去（`set_values` 会说"文件里没找到那一行"）。两个方向都查。
    另外查"该有的说明有没有写"（`V-63`：说不清的设置项等于没写）。
    """
    problems = []
    seen = set()
    for g in SETTINGS_GROUPS:
        if not str(g.get("name") or "").strip():
            problems.append("有个设置分组没有 name")
        if not str(g.get("blurb") or "").strip():
            problems.append("分组「%s」没写 blurb（一句话说明这组是干什么的）" % g.get("name"))
        if not str(g.get("icon") or "").strip():
            problems.append("分组「%s」没写 icon" % g.get("name"))
        for it in g["items"]:
            key = str(it.get("key") or "")
            if "." not in key:
                problems.append("设置项 %r 的键要写成「段.键」" % key)
                continue
            section, name = _split_key(key)
            if section not in DEFAULT_CONFIG or name not in DEFAULT_CONFIG.get(section, {}):
                problems.append("设置项 %s 在 DEFAULT_CONFIG 里没有对应的键" % key)
                continue
            if key in seen:
                problems.append("设置项 %s 出现了两次" % key)
            seen.add(key)
            if not str(it.get("label") or "").strip():
                problems.append("设置项 %s 没写 label" % key)
            if not str(it.get("hint") or "").strip():
                problems.append("设置项 %s 没写 hint（人看不懂它是干什么的）" % key)
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
            section, name = _split_key(it["key"])
            items.append({
                "key": it["key"],
                "label": it["label"],
                "type": it.get("type") or "text",
                "hint": it.get("hint") or "",
                "value": CONFIG.get(section, {}).get(name, DEFAULT_CONFIG[section][name]),
                "default": DEFAULT_CONFIG[section][name],
            })
        out.append({"name": g["name"], "icon": g.get("icon") or "",
                    "blurb": g.get("blurb") or "", "live": bool(g.get("live")),
                    "items": items})
    return out


def settings_payload():
    """`moss --settings` 输出给界面的东西（纯 JSON）。

    为什么要有这条命令：界面跑在自带运行时里，而 `core` 是编进 exe 的
    （`K-10` 内核最小化）—— 磁盘上根本没有 core 这个目录，界面 import 不到它。
    所以界面要读设置、要改设置，都只能回来叫宿主（和跑包、`--ui-payload` 同一条路）。
    """
    return {"path": str(paths.USER_CONFIG), "groups": settings_groups()}


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

    ★ 为什么得扫一遍字符串：符号是用户随便填的，`path_mode = "#"` 是合法值 ——
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
    # ★ `V-137`：`ai.*` 单独处理 —— `ai.profiles` 是**表**，通用那条"逐键写 TOML"的路子会把它写成
    #   一个字符串，下次读就崩（`ai_profiles()` 拿到的不是 dict）。所以：
    #     ai.active     → 切当前组（`ai_set_active`）
    #     ai.profiles   → **忽略**（只认 `--ai-profile-set`，免得手滑写坏）
    try:
        _ai = {k: v for k, v in (values or {}).items() if str(k).startswith("ai.")}
        if _ai:
            for k in list(_ai):
                if k == "ai.active" and str(_ai[k] or "").strip():
                    ai_set_active(str(_ai[k]).strip(), path)
                values.pop(k, None)
            if not values:
                return True, []
    except Exception:                                                   # noqa: BLE001
        pass
    """把面板上改过的值写回配置文件，返回 `{"ok", "problems"}`。

    ★ 为什么按行换值，而不是"重新生成整个文件"：那份 TOML 的注释就是说明书
      （`D-23`：自动生成的默认文件本身就是文档）。重新生成会把注释全丢掉 ——
      用户下次打开只看见一堆键值，根本不知道某个空串是"没设"还是"故意的"。
    ★ 一个键都没找到 = 一行都不写（不做"写一半"）：半截生效比没生效更难查。
    ★ 写完立刻按 TOML 读回来核对：说的和写的不是一回事，这种错在这儿抓住最省事。
    """
    target = Path(path) if path else paths.USER_CONFIG
    problems = _check_values(values)
    if any(p["level"] == "error" for p in problems):
        return {"ok": False, "problems": problems}

    try:
        if not target.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(CONFIG_TEMPLATE, encoding="utf-8", newline="\n")
        raw = target.read_text(encoding="utf-8")
    except OSError as e:
        return {"ok": False,
                "problems": [{"key": "", "why": "读不了配置文件：%s" % e, "level": "error"}]}

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
            problems.append({"key": k, "why": "配置文件里没找到 %s 那一行"
                                              "（我没动这个文件）" % k, "level": "error"})
        return {"ok": False, "problems": problems}

    tmp = target.with_name(target.name + ".tmp")
    try:
        tmp.write_text(nl.join(lines) + nl, encoding="utf-8", newline="")
        os.replace(str(tmp), str(target))
    except OSError as e:
        try:
            tmp.unlink()
        except OSError:
            pass
        return {"ok": False,
                "problems": [{"key": "", "why": "写不进配置文件：%s" % e, "level": "error"}]}

    try:
        with open(target, "rb") as f:
            got = tomllib.load(f)
    except Exception as e:                                   # noqa: BLE001
        problems.append({"key": "", "why": "写完之后这个文件读不回来了：%s" % e,
                         "level": "error"})
    else:
        for key, want in values.items():
            sec, name = _split_key(key)
            have = (got.get(sec) or {}).get(name, "<没有>")
            if have != want:
                problems.append({"key": key,
                                 "why": "没写进去：想要 %r，文件里是 %r" % (want, have),
                                 "level": "error"})
            else:
                CONFIG.setdefault(sec, {})[name] = want      # 内存里那份也跟着更新
    return {"ok": not any(p["level"] == "error" for p in problems),
            "problems": problems}


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


# ---------------------------------------------------------------- AI 那几组（`V-137`）
def _ai_section_text(profiles, active):
    """把 AI 那几节拼成 TOML 文本（整段重建，文件其它部分一字不动）。"""
    out = ['[ai]', 'active = %s' % _toml_str(active or ""), '']
    for name in sorted(profiles or {}):
        pr = profiles[name] or {}
        out.append('[ai.profiles.%s]' % name)
        for k in AI_FIELDS:
            if k not in pr:
                continue
            v = pr.get(k)
            if isinstance(v, bool):
                out.append('%s = %s' % (k, 'true' if v else 'false'))
            elif isinstance(v, (int, float)) and not isinstance(v, bool):
                out.append('%s = %s' % (k, v))
            else:
                out.append('%s = %s' % (k, _toml_str(v)))
        out.append('')
    return '\n'.join(out)


def _toml_str(v):
    t = str(v if v is not None else "")
    return '"' + t.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n') + '"'


def _write_ai_section(profiles, active, path=None):
    """只替换文件里的 `[ai]`/`[ai.profiles.*]` 那几节，别的一个字不动。

    ★ 为什么整段重建而不是逐行改：profiles 是**动态表**（增删组、组名字数不一），
      逐行改要处理"删组""改组名"这些情况，容易把文件弄坏；整段换掉最稳。"""
    p = Path(path or paths.USER_CONFIG)
    txt = p.read_text(encoding="utf-8") if p.is_file() else CONFIG_TEMPLATE
    lines = txt.splitlines()
    keep, skipping = [], False
    for ln in lines:
        st = ln.strip()
        if st.startswith("[ai]") or st.startswith("[ai.") or st.startswith("[[ai"):
            skipping = True
            continue
        if skipping and st.startswith("[") and not st.startswith("[ai"):
            skipping = False
        if skipping:
            continue
        keep.append(ln)
    body = "\n".join(keep).rstrip("\n")
    p.write_text(body + "\n\n" + _ai_section_text(profiles, active), encoding="utf-8")


def ai_profiles(path=None):
    """当前的 AI 各组（`{组名: {字段…}}`）。"""
    cfg = load().get("ai") or {}
    profs = cfg.get("profiles") or {}
    return {k: dict(v or {}) for k, v in profs.items()}


def ai_active_name(path=None):
    return str((load().get("ai") or {}).get("active") or "")


def ai_active_profile(path=None):
    """当前那组的参数（`active` 为空或那组不存在时，取第一组）。"""
    profs = ai_profiles(path)
    name = ai_active_name(path)
    if name not in profs:
        name = sorted(profs)[0] if profs else ""
    if not name:
        return "", {}
    return name, dict(profs[name])


def ai_profile_set(name, fields, path=None):
    """加/改组（给了哪几个字段就写哪几个；其它字段保持）。"""
    name = re.sub(r"[^A-Za-z0-9_.@-]", "_", str(name or "").strip())[:40] or "default"
    profs = ai_profiles(path)
    cur = dict(profs.get(name) or {})
    for k, v in (fields or {}).items():
        if k in AI_FIELDS:
            cur[k] = v
    profs[name] = cur
    active = ai_active_name(path) or name
    _write_ai_section(profs, active, path)
    return name, cur


def ai_profile_del(name, path=None):
    profs = ai_profiles(path)
    profs.pop(str(name), None)
    active = ai_active_name(path)
    if active == name:
        active = sorted(profs)[0] if profs else ""
    _write_ai_section(profs, active, path)
    return sorted(profs)


def ai_set_active(name, path=None):
    _, _ = ai_profile_set(name, {}, path)          # 组不存在就先建个空壳，免得指到一个不存在的组
    profs = ai_profiles(path)
    _write_ai_section(profs, str(name), path)
    return str(name)


def ai_import_legacy(path=None, legacy=None):
    """把老的 `user_data/state/ai/config.json` 导成一组（`V-137` 的迁移）。"""
    f = Path(legacy) if legacy else (paths.USER_DIR / "state" / "ai" / "config.json")
    if not f.is_file():
        return None
    try:
        import json as _json
        j = _json.loads(f.read_text(encoding="utf-8"))
    except Exception:                                                   # noqa: BLE001
        return None
    fields = {}
    if j.get("BASE_URL"):
        fields["base_url"] = j["BASE_URL"]
    if j.get("MODEL"):
        fields["model"] = j["MODEL"]
    if j.get("API_KEY"):
        fields["api_key"] = j["API_KEY"]
    fields["note"] = "从旧的 state/ai/config.json 导进来的"
    name, _ = ai_profile_set("legacy-ai", fields, path)
    return name


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
