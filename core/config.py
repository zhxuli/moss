# -*- coding: utf-8 -*-
"""配置 + 输入法全角前缀还原。

★ 照抄 pa.py:53-149（E-20 照抄原则）：
  · 默认配置与用户配置的合并方式
  · FULLWIDTH_TO_HALF 全角标点还原表
  · restore_prefix() 只还原**开头的模式前缀**，参数内容一律不碰

后者的价值是实战验证过的：中文输入法开着"中文标点"时，
`moss :clock` 会被打成 `moss ：clock`，不还原就认不出来。
"""
import copy
import json

from . import paths

DEFAULT_CONFIG = {
    "symbols": {
        "plugin_mode": ":",
    },
    "search": {
        "max_parent_depth": 3,
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
    """读用户配置并覆盖默认值。失败就用默认值，不中断。"""
    global CONFIG
    CONFIG = copy.deepcopy(DEFAULT_CONFIG)
    try:
        if paths.USER_CONFIG.is_file():
            with open(paths.USER_CONFIG, "r", encoding="utf-8") as f:
                user = json.load(f)
            for section, settings in DEFAULT_CONFIG.items():
                if section in user:
                    if isinstance(settings, dict) and isinstance(user[section], dict):
                        CONFIG[section].update(user[section])
                    else:
                        CONFIG[section] = user[section]
    except Exception:
        pass
    return CONFIG


def restore_prefix(arg):
    """把参数开头被输入法打成全角的模式前缀还原成半角。

    照抄 pa.py:126-149 —— 只处理开头最多两个字符，而且只认 moss 自己在用的前缀符号。
    后面的内容一概不动：中文文件名里的（）、，、。都是合法字符，
    把整个参数一起转反而会把 `moss 报告（终稿）` 这种东西改坏。
    """
    if not arg:
        return arg
    prefixes = {CONFIG["symbols"].get("plugin_mode", ":")}
    out = list(arg)
    for i in range(min(2, len(out))):
        half = FULLWIDTH_TO_HALF.get(out[i])
        if half and half in prefixes:
            out[i] = half
        else:
            break
    return "".join(out)


def plugin_symbol():
    return CONFIG["symbols"].get("plugin_mode", ":")


def max_parent_depth():
    return CONFIG.get("search", {}).get("max_parent_depth", 3)
