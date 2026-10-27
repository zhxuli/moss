# -*- coding: utf-8 -*-
"""MD5 计算 —— 算字符串 / 文件 / 文件夹的 MD5

输入：MOSS_PKG_PARAMS 里的 `target`；输出一份给人看的结果和一份结构化结果。
"""

import json
import os
import sys
import hashlib

# 参数：moss 通过 MOSS_PKG_PARAMS 传 JSON（类型化参数通道）。
try:
    _params = json.loads(os.environ.get("MOSS_PKG_PARAMS") or "{}")
except Exception:
    _params = {}
raw = str(_params.get("target") or "")
s = raw.strip()


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d B" % n) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def quoted(t):
    return len(t) >= 2 and t[0] == t[-1] and t[0] in ('"', "'")


def decide(t):
    """返回 (mode, targets)。mode 是 'text' 或 'path'。"""
    if quoted(t):
        return "text", [t[1:-1]]                    # 带引号 -> 百分百按字符串
    if t and os.path.exists(t):
        return "path", [t]                          # 整串就是一个路径
    if t:
        parts = t.split()
        if len(parts) >= 2 and all(os.path.exists(p) for p in parts):
            return "path", parts                    # 每一项都是已存在的路径
    return "text", [t]                              # 其余一律字符串


if s:
    mode, targets = decide(s)
else:
    try:
        import pyperclip
        clip = (pyperclip.paste() or "").strip()
    except Exception:
        clip = ""
    if not clip:
        print("用法：参数填文件路径或一段文本")
        print("     带引号 = 强制按字符串算")
        print("     不填参数 = 用剪贴板内容")
        sys.exit(1)
    print("用剪贴板内容：%s\n" % (clip if len(clip) <= 60 else clip[:57] + "..."))
    mode, targets = decide(clip)

digests = []

if mode == "text":
    text = targets[0]
    data = text.encode("utf-8")
    d = hashlib.md5(data).hexdigest()
    digests.append(d)
    print("判断为：字符串")
    print("内容  ：%s" % (text if len(text) <= 70 else text[:67] + "..."))
    print("字节数：%d（UTF-8）" % len(data))
    print("MD5   ：%s" % d)
else:
    expanded = []                                   # [(种类, 完整路径, [文件...])]
    for t in targets:
        full = os.path.abspath(t)
        if os.path.isdir(full):
            found = []
            for root, dirs, names in os.walk(full):
                for n in sorted(names):
                    found.append(os.path.join(root, n))
            expanded.append(("文件夹", full, found))
        else:
            expanded.append(("文件", full, [full]))

    total = sum(len(e[2]) for e in expanded)
    if total == 0:
        print("判断为：文件夹")
        print("完整路径：%s" % expanded[0][1])
        print("\n里面没有文件。")
        sys.exit(1)

    if len(expanded) == 1 and expanded[0][0] == "文件":
        p = expanded[0][2][0]
        d = md5_file(p)
        digests.append(d)
        print("判断为：文件")
        print("完整路径：%s" % p)
        print("大小    ：%s" % human(os.path.getsize(p)))
        print("MD5    ：%s" % d)
    else:
        for kind, full, found in expanded:
            print("判断为：%s" % kind)
            print("完整路径：%s" % full)
        print("\n共 %d 个文件：\n" % total)
        for kind, full, found in expanded:
            for p in found:
                d = md5_file(p)
                digests.append(d)
                print("%s  %10s  %s" % (d, human(os.path.getsize(p)), p))

if len(digests) == 1:
    try:
        import pyperclip
        pyperclip.copy(digests[0])
        print("\nMD5 已复制到剪贴板。")
    except Exception:
        pass


# ---------------------------------------------------------------- 结构化返回
# 这一段是迁移时【新增】的（上面的逻辑一行没动）。
# 作用：把结果写进宿主给的 MOSS_RESULT_FILE，宿主读回来当 data ——
# 界面和 AI 拿到的是结构化数据，不用去解析人类可读的 print 文本。
#
# ⚠️ 必须用 globals()：函数体内的 locals() 只有它自己的局部变量，拿不到 digests。
#    digests 在提前 sys.exit 的路径上也可能未定义，所以用 globals().get 兜一下。
def _result():
    return {"md5": list(globals().get("digests") or [])}


_rf = os.environ.get("MOSS_RESULT_FILE")
if _rf:
    try:
        with open(_rf, "w", encoding="utf-8") as _f:
            json.dump(_result(), _f, ensure_ascii=False)
    except Exception:
        pass
