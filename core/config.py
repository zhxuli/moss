# -*- coding: utf-8 -*-
"""配置 + 输入法全角前缀还原。

★ 照抄 pa.py:53-149（E-20 照抄原则）：
  · 默认配置的**完整四组结构**（symbols / output / search / ctrl_c）
  · 首次运行自动创建 config.json 并提示
  · FULLWIDTH_TO_HALF 全角标点还原表
  · restore_prefix() 只还原**开头的模式前缀**，参数内容一律不碰
"""
import copy
import json

from . import paths

# 照抄 pa.py:54-78，字段名和默认值一个不改
DEFAULT_CONFIG = {
    "symbols": {
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
    # ★ 子进程环境净化（X-15）。第 5 组，前 4 组照抄 pa.py 的字段一个不改。
    "security": {
        # 开着的时候，形似凭据的环境变量**不传给插件**（见 core/engine.py 的说明）
        "scrub_env": True,
        # 额外要剥掉的名字（精确匹配，大小写不敏感）—— 有些项目的凭据变量名
        # 不含 KEY/TOKEN/SECRET/PASSWORD 这些词
        "scrub_extra": [],
        # 白名单：即使名字命中敏感形状也保留。比如 TOKENIZERS_PARALLELISM 不是凭据，
        # 被误杀了会让某些库少一个性能设置
        "keep_env": [],
    },
}

# pa.py:116-123 原样
FULLWIDTH_TO_HALF = {
    '：': ':', '；': ';', '，': ',', '。': '.', '、': '\\', '／': '/',
    '＝': '=', '－': '-', '～': '~', '！': '!', '？': '?', '＠': '@',
    '＃': '#', '＄': '$', '％': '%', '＾': '^', '＆': '&', '＊': '*',
    '（': '(', '）': ')', '【': '[', '】': ']', '｛': '{', '｝': '}',
    '《': '<', '》': '>', '｜': '|', '＋': '+', '＿': '_',
    '“': '"', '”': '"', '‘': "'", '’': "'", '　': ' ',
}

CONFIG = copy.deepcopy(DEFAULT_CONFIG)


def load():
    """读用户配置并覆盖默认值，缺文件就自动创建。

    照抄 pa.py:80-106 —— 包括"未找到配置文件，将为您自动创建一个"的提示。
    """
    global CONFIG
    CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    try:
        paths.ensure_user_dirs()
        cfg_path = paths.USER_CONFIG

        if cfg_path.is_file():
            with open(cfg_path, "r", encoding="utf-8") as f:
                user = json.load(f)
            added = []
            for section, settings in DEFAULT_CONFIG.items():
                if section in user:
                    if isinstance(settings, dict) and isinstance(user[section], dict):
                        CONFIG[section].update(user[section])
                    else:
                        CONFIG[section] = user[section]
                else:
                    # ★ 新版本新增的配置组要**补进文件**，只用默认值是不够的：
                    #   用户在 config.json 里看不到这个开关，就等于"它不存在"
                    #   （实测踩过：加了 security 组，而用户的配置文件里没有，
                    #    于是"怎么关掉环境净化/加白名单"根本无从下手）。
                    user[section] = copy.deepcopy(settings)
                    added.append(section)
            if added:
                try:
                    with open(cfg_path, "w", encoding="utf-8") as f:
                        json.dump(user, f, indent=2, ensure_ascii=False)
                    from . import out
                    out.print_cyan("[配置] 新版本新增了配置组 %s，已补进 %s"
                                   % ("/".join(added), cfg_path))
                except Exception as e:
                    from . import out
                    out.print_cyan("[配置警告] 新配置组补写失败: %s（本次仍用默认值）" % e)
        else:
            from . import out
            out.print_cyan("[配置] 未找到配置文件，将为您自动创建一个。")
            try:
                with open(cfg_path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)
                out.print_cyan("[配置] 成功创建配置文件: %s" % cfg_path)
            except Exception as e:
                out.print_cyan("[配置错误] 无法创建配置文件: %s" % e)
                out.print_cyan("[配置] 将在本次运行中使用默认设置。")

    except (json.JSONDecodeError, IOError) as e:
        from . import out
        out.print_cyan("[配置错误] 加载配置文件失败: %s. 将使用默认设置。" % e)
    except Exception as e:
        from . import out
        out.print_cyan("[未知配置错误]: %s. 将使用默认设置。" % e)

    return CONFIG


# ---------------------------------------------------------------- 取值helper
def symbols():
    return CONFIG.get("symbols", {})


def plugin_symbol():
    return symbols().get("plugin_mode", ":")


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


def security_cfg():
    return CONFIG.get("security", {})


def restore_prefix(arg):
    """把参数开头被输入法打成全角的模式前缀还原成半角。

    照抄 pa.py:126-149 —— 只处理开头最多两个字符，而且只认 moss 自己在用的
    三个前缀符号（`:` 插件、`/` 不切目录、`~` 后台脱离）。
    后面的内容一概不动：中文文件名里的（）、，、。都是合法字符，
    把整个参数一起转反而会把 `moss 报告（终稿）` 这种东西改坏。
    """
    if not arg:
        return arg
    prefixes = {plugin_symbol(), no_chdir_symbol(), detach_symbol()}
    out = list(arg)
    for i in range(min(2, len(out))):
        half = FULLWIDTH_TO_HALF.get(out[i])
        if half and half in prefixes:
            out[i] = half
        else:
            break
    return "".join(out)
