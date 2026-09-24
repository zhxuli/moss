# -*- coding: utf-8 -*-
"""剪贴板读写。

为什么内核需要它
----------------
`pyautogui.typewrite()` **打不了非 ASCII 字符** —— 中文没有键位映射，
会被**静默丢弃**。实测：

    输入 : cd "D:\\study\\GO\\学习\\基础知识\\BMI"
    打出 : cd "D:\\study\\GO\\\\\\BMI"        ← 6 个汉字整段消失

这是 `pa.py:845` 就有的 bug（照抄时一起搬过来了），所以 `cd` 到中文路径
必须改走"剪贴板 + Ctrl+V"。

用 pyperclip（pyautogui 本来就依赖它，两个环境里都有）。
"""
try:
    import pyperclip
except ImportError:
    pyperclip = None


def available():
    return pyperclip is not None


def get():
    """读剪贴板文本；读不到返回空串（不抛）。"""
    if pyperclip is None:
        return ""
    try:
        return pyperclip.paste() or ""
    except Exception:
        return ""


def set(text):
    """写剪贴板。成功返回 True。"""
    if pyperclip is None:
        return False
    try:
        pyperclip.copy(text if text is not None else "")
        return True
    except Exception:
        return False


def describe():
    return "pyperclip %s" % getattr(pyperclip, "__version__", "?") if available() else "✗ 缺失"
