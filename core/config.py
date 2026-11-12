import copy
import os
import re
import tomllib
from pathlib import Path

from . import paths

SYMBOL_BAD = set('&|<>^%!*?()$`"\'=#@,;[]{}')

AI_FIELDS = ("base_url", "api_key", "model")

AI_PRESETS = [
    {"name": "DeepSeek", "desc": "官方 API", "base_url": "https://api.deepseek.com/v1",
     "model": ["deepseek-flash"]},
    {"name": "Gemini", "desc": "Google", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "model": ["gemini-2.0-flash", "gemini-2.5-pro"]},
    {"name": "OpenAI", "desc": "ChatGPT 系列", "base_url": "https://api.openai.com/v1",
     "model": ["gpt-4o-mini", "gpt-4o"]},
    {"name": "Kimi", "desc": "月之暗面", "base_url": "https://api.moonshot.cn/v1",
     "model": ["moonshot-v1-8k", "moonshot-v1-32k"]},
    {"name": "通义千问", "desc": "阿里", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
     "model": ["qwen-plus", "qwen-max"]},
    {"name": "智谱", "desc": "GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4",
     "model": ["glm-4-flash", "glm-4-plus"]},
    {"name": "硅基流动", "desc": "聚合平台", "base_url": "https://api.siliconflow.cn/v1",
     "model": ["deepseek-ai/DeepSeek-V3", "Qwen/Qwen2.5-7B-Instruct"]},
    {"name": "本地 Ollama", "desc": "本机跑", "base_url": "http://127.0.0.1:11434/v1",
     "model": ["qwen2.5:7b"]},
]

def ai_models(prof):
    v = (prof or {}).get("model")
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    s = str(v or "").strip()
    return [s] if s else []

DEFAULT_CONFIG = {
    "ai": {"active": "", "profiles": {}},
    "symbols": {
        "path_mode": "",
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
        "max_parent_depth": 0,
    },
    "ctrl_c": {
        "force_kill": True,
    },
    "shortcut": {
        "prefix": "mo",
        "mo": False,
        "pkg": False,
    },
    "path": {
        "moss": False,
    },
    "ui": {
        "kill_pkgs_on_exit": False,
    },
    "sound": {
        "finish_on": True,
        "finish_file": "",
        "warn_on": True,
        "warn_file": "",
    },
}

CONFIG = copy.deepcopy(DEFAULT_CONFIG)

CONFIG_TEMPLATE = '''[symbols]

path_mode          = ""
no_chdir_mode      = "/"
plugin_mode        = ":"
no_force_kill_mode = "~"

[output]

auto_clear_screen = true
start_banner      = ""
end_banner        = ""
start_time        = true
end_time          = true
duration          = true
pid               = true
directory         = true
command           = true
symbol            = ""

[search]

max_parent_depth = 0

[ctrl_c]

force_kill = true

[ui]

kill_pkgs_on_exit = false

[sound]

finish_on = true
finish_file = ""
warn_on = true
warn_file = ""

[path]

moss = false

[shortcut]

prefix = "mo"
mo  = false
pkg = false

[ai]
active = ""

[ai.profiles]
'''

SETTINGS_GROUPS = [
    {"name": "命令接入", "icon": "globe",
     "blurb": "让 moss 在命令行里好用：把 moss 加进 PATH（任何终端都能直接敲 moss），"
              "再顺手装一下 cd 增强（moss cd 屏幕上不留回显）。",
     "items": [
         {"key": "path.moss", "label": "把 moss 加进系统 PATH", "type": "bool",
          "hint": "打开后 moss 会把它自己所在的目录加进**当前用户**的 PATH —— 之后任何终端里"
                  "直接敲 moss 就行，不用写全路径。只改当前用户、不用管理员。"
                  "改完**新开一个终端**才生效（**不用重启电脑**）；本来就在 PATH 里的不会重复加。"},
     ]},
    {"name": "快捷命令", "icon": "hash", "live": True,
     "blurb": "行首那个符号决定命令的种类。留空 = 裸名就用这一类。",
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
     {"name": "短名设置", "icon": "moss-shortcut",
      "blurb": "把 moss :包名 缩成一条直接能敲的命令：往 PATH 上加一个目录，"
               "往里放一批小启动器。新建 / 改名 / 删除包会自动跟着变。",
      "items": [
          {"key": "shortcut.prefix", "label": "前缀", "type": "text",
           "placeholder": "如 mo",
           "hint": "短命令的前缀（默认 mo）。moimg = mo + img，所以换前缀会一起换。"
                   "要字母开头、只含字母/数字/-/_、1~8 个字符 —— 它既是命令名也是文件名。"},
          {"key": "shortcut.mo", "label": "「前缀」= moss（一条 alias 式的短命令）", "type": "bool",
           "hint": "打开后生成一条 `<前缀>` —— 它就是 moss：<前缀> :img、<前缀> --help、"
                   "「前缀 ~m」都能用，和直接敲 moss 一模一样。"},
          {"key": "shortcut.pkg", "label": "「前缀+包名」= moss :包名（融合短命令）", "type": "bool",
           "hint": "给每个已安装的包生成一条「前缀+包名」：moimg 就等于 moss :img。"
                   "前缀的作用是不撞上系统里的同名命令。"},
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
    {"name": "输出格式", "icon": "braces",
     "blurb": "那几行的文字样式：前后各可以打一整行自己的话，也能改行首的符号。",
     "items": [
         {"key": "output.start_banner", "label": "起始横幅文本", "type": "text",
          "hint": "运行前打印的一整行自定义文字；留空 = 不打印。"},
         {"key": "output.end_banner", "label": "结束横幅文本", "type": "text",
          "hint": "运行后打印的一整行自定义文字；留空 = 不打印。"},
         {"key": "output.symbol", "label": "行首符号", "type": "text",
          "hint": "上面那几行开头的符号（例如 >）；留空 = 用内置的 [执行] 这种。"},
     ]},
    {"name": "高级设置", "icon": "settings",
     "blurb": "不常动的三项：找文件往上找几层、按 Ctrl+C 时怎么处理这个子进程树，"
              "以及关掉界面时要不要把插件进程一起收掉。",
     "items": [
         {"key": "search.max_parent_depth", "label": "向上查找层数", "type": "int",
          "hint": "跑 moss m 这类路径调用时，从当前目录往上找几级。0 = 只看当前目录（默认）；"
                  "填 3 就是当前目录 + 往上 3 级，一共 4 个目录。往上找得越远越慢，"
                  "也越容易撞上上层项目里的同名文件（撞上就会停下来问你选哪个）。"},
         {"key": "ctrl_c.force_kill", "label": "第一次按 Ctrl+C 就强杀整棵树", "type": "bool",
          "hint": "在终端里按 Ctrl+C 时，第一次就强杀整棵进程树。关掉之后：第一次只温和地"
                  "请它退出，再按一次才强杀 —— 有收尾工作的包适合关掉。"},
         {"key": "ui.kill_pkgs_on_exit", "label": "退出时结束所有插件进程", "type": "bool",
          "hint": "关掉 moss 界面时，把还在后台跑的插件进程**一起结束掉**（连它拉起的子孙进程）"
                  "—— 不留后台孤儿。默认关：插件会继续在后台跑（长驻服务那种适合这样）。"},
     ]},
    {"name": "A I 引擎", "icon": "activity",
     "blurb": "配置 AI 服务的地址和密钥（可以多组）",
     "items": [
         {"key": "ai.active", "label": "当前组", "type": "text",
          "hint": "跑包时用哪一组。"},
         {"key": "ai.profiles", "label": "各组", "type": "raw",
          "hint": "每组：接口地址 / 密钥 / 模型；在面板上点「新建」或某行的「编辑」改。"},
         {"key": "sound.finish_on", "label": "任务结束音效", "type": "bool",
          "hint": "AI 跑完一轮、把结论摆出来的时候响一下。关掉就不响（也可以换成自己的音频）。"},
         {"key": "sound.finish_file", "label": "任务结束音效文件", "type": "text",
          "hint": "留空 = 用出厂自带的那一个（system/sound/finish.mp3）；"
                  "换法：面板上点「换一个」选文件，或把音频直接拖到那一行上 —— "
                  "选好的会被复制到 user_data/sound/，原文件删了也不影响。"},
         {"key": "sound.warn_on", "label": "需要你确认时的提示音", "type": "bool",
          "hint": "AI 有话要问你、或者要你放行一个目录的时候响一下 —— 就是它在等你动手的那些时候。"},
         {"key": "sound.warn_file", "label": "提示音文件", "type": "text",
          "hint": "留空 = 用出厂自带的那一个（system/sound/warn.mp3）；换法同上。"},
     ]},
]

def _split_key(key):
    section, _, name = str(key).partition(".")
    return section, name

def _setting_spec(key):
    for g in SETTINGS_GROUPS:
        for it in g["items"]:
            if it["key"] == key:
                return it
    return None

def _after_values(values):
    after = {}
    for g in SETTINGS_GROUPS:
        for it in g["items"]:
            section, name = _split_key(it["key"])
            after[it["key"]] = CONFIG.get(section, {}).get(name, DEFAULT_CONFIG[section][name])
    after.update(values or {})
    return after

def _live_lines(after):
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

def _live_line(after):
    return _live_lines(after)

def _notes_for(after):
    notes = {}
    p = after.get("symbols.path_mode") or ""
    g = after.get("symbols.plugin_mode") or ""
    n = after.get("symbols.no_chdir_mode") or ""
    d = after.get("symbols.no_force_kill_mode") or ""
    notes["symbols.path_mode"] = ("现在：裸名 moss m = 找文件并运行"
                                  if not p else "现在：moss %sm = 找文件并运行" % p)
    notes["symbols.plugin_mode"] = ("现在：裸名 moss img = 跑包"
                                    if not g else "现在：moss %simg = 跑包" % g)
    notes["symbols.no_chdir_mode"] = ("现在：这一类不带前缀（用裸名或路径前缀）"
                                      if not n else "现在：moss %sm = 找文件但不切目录" % n)
    notes["symbols.no_force_kill_mode"] = ("现在：这一类不带前缀"
                                           if not d else "现在：moss %sm = 后台脱离" % d)
    try:
        v = int(after.get("search.max_parent_depth", DEFAULT_CONFIG["search"]["max_parent_depth"]))
    except (TypeError, ValueError):
        v = DEFAULT_CONFIG["search"]["max_parent_depth"]
    notes["search.max_parent_depth"] = ("现在：只在当前目录找，不往上"
                                        if v == 0 else
                                        "现在：从当前目录起往上找 %d 级（连自己一共 %d 个目录）"
                                        % (v, v + 1))
    return notes

def _check_values(values):
    values = dict(values or {})
    after = _after_values(values)
    problems = []

    def err(key, why, also=None):
        problems.append({"key": key, "why": why, "level": "error", "also": list(also or [])})

    def warn(key, why, also=None):
        problems.append({"key": key, "why": why, "level": "warn", "also": list(also or [])})

    for key, val in values.items():
        it = _setting_spec(key)
        if it is None:
            err(key, "不认识的设置项")
            continue
        kind = it.get("type") or "text"
        if kind == "raw":
            continue
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
                _bad = sorted({c for c in val if c in SYMBOL_BAD})
                if _bad:
                    err(key, "「%s」在命令行里有特殊意思（重定向 / 管道 / 变量 / 通配那一类），"
                             "当前缀会出事 —— 换一个普通的，比如 / : ~ . - _ 或者一个字母"
                             % " ".join(_bad))
            else:
                if "\n" in val or "\r" in val:
                    err(key, "里不能有换行（现在 %r）" % (val,))

    pv = after.get("shortcut.prefix")
    if pv is not None and not re.match(r"^[A-Za-z][A-Za-z0-9_-]{0,7}$", str(pv)):
        err("shortcut.prefix", "前缀要字母开头、只含字母/数字/-/_，1~8 个字符（现在 %r）" % (pv,))

    if not after.get("symbols.path_mode") and not after.get("symbols.plugin_mode"):
        pair = ["symbols.path_mode", "symbols.plugin_mode"]
        main = next((k for k in pair if k in values), pair[0])
        err(main, "「路径调用」和「跑包」不能同时留空 —— 那样裸名（moss m）算哪一种"
                  "就说不清了", also=[k for k in pair if k != main])

    def _label(k):
        it = _setting_spec(k) or {}
        return it.get("label") or k

    by_value = {}
    for key in ("symbols.path_mode", "symbols.no_chdir_mode",
                "symbols.plugin_mode", "symbols.no_force_kill_mode"):
        v = after.get(key) or ""
        if v:
            by_value.setdefault(v, []).append(key)
    for v, keys in by_value.items():
        if len(keys) < 2:
            continue
        main = next((k for k in keys if k in values), keys[0])
        others = [k for k in keys if k != main]
        err(main, "和「%s」用了同一个符号 %r —— 命令含义会有歧义"
            % ("、".join(_label(k) for k in others), v), also=others)

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
    return problems

def settings_check(values=None):
    values = dict(values or {})
    after = _after_values(values)
    problems = _check_values(values)
    return {"ok": not any(p["level"] == "error" for p in problems),
            "problems": problems,
            "notes": _notes_for(after),
            "live": _live_line(after)}

def settings_problems():
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
    out = []
    for g in SETTINGS_GROUPS:
        items = []
        for it in g["items"]:
            section, name = _split_key(it["key"])
            value = CONFIG.get(section, {}).get(name, DEFAULT_CONFIG[section][name])
            if it["key"] == "path.moss":
                try:
                    from . import shortcut as _sc
                    value = _sc.moss_on_path()
                except Exception:
                    pass
            items.append({
                "key": it["key"],
                "label": it["label"],
                "type": it.get("type") or "text",
                "hint": it.get("hint") or "",
                "placeholder": it.get("placeholder") or "",
                "value": value,
                "default": DEFAULT_CONFIG[section][name],
            })
        out.append({"name": g["name"], "icon": g.get("icon") or "",
                    "blurb": g.get("blurb") or "", "live": bool(g.get("live")),
                    "items": items})
    return out

def settings_payload():
    return {"path": str(paths.USER_CONFIG), "groups": settings_groups()}

def _toml_literal(value, kind):
    if kind == "bool":
        return "true" if value else "false"
    if kind == "int":
        return str(int(value))
    s = str(value)
    return '"%s"' % s.replace("\\", "\\\\").replace('"', '\\"')

def _split_comment(rest):
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

def _ensure_sections(raw, sections):
    have = set()
    for line in raw.splitlines():
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            have.add(s[1:-1].strip())
    add = [s for s in sections if s and s not in have]
    if not add:
        return raw
    nl = "\r\n" if "\r\n" in raw else "\n"
    block = ["", "# ---- 下面是程序新增的段（保留你原来的内容，只补缺的） ----"]
    for section in add:
        block.append("[%s]" % section)
        for name, val in (DEFAULT_CONFIG.get(section) or {}).items():
            kind = "bool" if isinstance(val, bool) else ("int" if isinstance(val, int) else "text")
            block.append("%s = %s" % (name, _toml_literal(val, kind)))
    text = raw
    if text and not text.endswith(("\n", "\r")):
        text += nl
    return text + nl.join(block) + nl

def set_values(values, path=None):
    try:
        _ai = {k: v for k, v in (values or {}).items() if str(k).startswith("ai.")}
        if _ai:
            for k in list(_ai):
                if k == "ai.active" and str(_ai[k] or "").strip():
                    ai_set_active(str(_ai[k]).strip(), path)
                values.pop(k, None)
            if not values:
                return True, []
    except Exception:
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

    try:
        raw = _ensure_sections(raw, [_split_key(k)[0] for k in values])
    except Exception:
        pass

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
            if val.strip():
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
    except Exception as e:
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
                CONFIG.setdefault(sec, {})[name] = want
    return {"ok": not any(p["level"] == "error" for p in problems),
            "problems": problems}

def _collect_problems(user, problems):
    for section in user:
        if section not in DEFAULT_CONFIG:
            problems.append("配置里有不认识的段 [%s]，已忽略（是不是拼错了？）" % section)

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
            if not v:
                continue
            if v in seen:
                problems.append("symbols 里 %s 和 %s 都用了同一个符号 %r —— "
                                "命令含义会有歧义，请改成不同的符号" % (seen[v], n, v))
            else:
                seen[v] = n

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
                got.pop(key)

def _ai_section_text(profiles, active):
    out = ['[ai]', 'active = %s' % _toml_str(active or ""), '']
    for name in sorted(profiles or {}):
        pr = profiles[name] or {}
        key = name if re.fullmatch(r"[A-Za-z0-9_-]+", str(name)) else _toml_str(name)
        out.append('[ai.profiles.%s]' % key)
        for k in AI_FIELDS:
            if k not in pr:
                continue
            v = pr.get(k)
            if isinstance(v, (list, tuple)):
                out.append('%s = [%s]' % (k, ", ".join(_toml_str(x) for x in v)))
            elif isinstance(v, bool):
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
    cfg = load().get("ai") or {}
    profs = cfg.get("profiles") or {}
    return {k: dict(v or {}) for k, v in profs.items()}

def ai_active_name(path=None):
    return str((load().get("ai") or {}).get("active") or "")

def ai_active_profile(path=None):
    profs = ai_profiles(path)
    name = ai_active_name(path)
    if name not in profs:
        name = sorted(profs)[0] if profs else ""
    if not name:
        return "", {}
    return name, dict(profs[name])

def ai_profile_set(name, fields, path=None):
    name = re.sub(r'["\\\[\]\.\r\n\t]', "_", str(name or "").strip())[:40].strip() or "default"
    profs = ai_profiles(path)
    cur = dict(profs.get(name) or {})
    for k, v in (fields or {}).items():
        if k not in AI_FIELDS:
            continue
        if k == "model":
            if isinstance(v, (list, tuple)):
                cur[k] = [str(x).strip() for x in v if str(x).strip()]
            else:
                cur[k] = [x.strip() for x in re.split(r"[,\n]", str(v)) if x.strip()]
        else:
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
    _, _ = ai_profile_set(name, {}, path)
    profs = ai_profiles(path)
    _write_ai_section(profs, str(name), path)
    return str(name)

def ai_rename(old, new, path=None):
    old = str(old or "").strip()
    new = re.sub(r'["\\\[\]\.\r\n\t]', "_", str(new or "").strip())[:40].strip()
    if not old or not new or old == new:
        return None
    profs = ai_profiles(path)
    if old not in profs or new in profs:
        return None
    profs[new] = profs.pop(old)
    active = ai_active_name(path)
    _write_ai_section(profs, new if active == old else active, path)
    return new

def ai_import_legacy(path=None, legacy=None):
    f = Path(legacy) if legacy else (paths.USER_DIR / "state" / "ai" / "config.json")
    if not f.is_file():
        return None
    try:
        import json as _json
        j = _json.loads(f.read_text(encoding="utf-8"))
    except Exception:
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
    global CONFIG
    CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    try:
        paths.ensure_user_dirs()
        cfg_path = paths.USER_CONFIG

        if cfg_path.is_file():
            with open(cfg_path, "rb") as f:
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

def symbols():
    return CONFIG.get("symbols", {})

def plugin_symbol():
    return symbols().get("plugin_mode", ":")

def path_symbol():
    return symbols().get("path_mode", "")

def bare_owner():
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
    if not arg:
        return arg
    prefixes = {s for s in (plugin_symbol(), no_chdir_symbol(), detach_symbol()) if s}
    out = list(arg)
    for i in range(min(2, len(out))):
        half = FULLWIDTH_TO_HALF.get(out[i])
        if half and half in prefixes:
            out[i] = half
        else:
            break
    return "".join(out)

FULLWIDTH_TO_HALF = {
    '：': ':', '；': ';', '，': ',', '。': '.', '、': '\\', '／': '/',
    '＝': '=', '－': '-', '～': '~', '！': '!', '？': '?', '＠': '@',
    '＃': '#', '＄': '$', '％': '%', '＾': '^', '＆': '&', '＊': '*',
    '（': '(', '）': ')', '【': '[', '】': ']', '｛': '{', '｝': '}',
    '《': '<', '》': '>', '｜': '|', '＋': '+', '＿': '_',
    '“': '"', '”': '"', '‘': "'", '’': "'", '　': ' ',
}
