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
import tomllib

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
