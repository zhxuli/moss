# -*- coding: utf-8 -*-
"""shot —— 截屏（整个屏幕 / 某个窗口）存成 png。契约见同目录 `TOOL.md`。

参数从 stdin 那行 JSON 来（也放在 `MOSS_TOOL_ARGS` 里）；只往 stdout 打**要跟模型说的话**。
"""
import json
import os
import sys
import time
from pathlib import Path


def read_args():
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:                                                  # noqa: BLE001
        raw = ""
    if not raw.strip():
        raw = os.environ.get("MOSS_TOOL_ARGS") or "{}"
    try:
        got = json.loads(raw) if raw.strip() else {}
    except ValueError:
        got = {}
    return got if isinstance(got, dict) else {}


def find_window(title_kw):
    """按标题关键词找窗口 → 返回 `(box, 标题)`；找不到回 `(None, 现有标题列表)`。"""
    try:
        import pygetwindow as gw
    except ImportError as e:                                           # noqa: BLE001
        return None, "（没有 pygetwindow：%s —— 去掉 target 就是整屏截图）" % e
    wins = [w for w in gw.getAllWindows() if str(w.title or "").strip()]
    kw = str(title_kw or "").lower()
    for w in wins:
        if kw in str(w.title or "").lower():
            box = (int(w.left), int(w.top), int(w.left + int(w.width)), int(w.top + int(w.height)))
            return box, str(w.title or "")[:60]
    listing = "\n".join("  · " + str(w.title or "")[:60] for w in wins[:40])
    return None, listing[:2000] or "（一个窗口都没有）"


def main():
    args = read_args()
    target = str(args.get("target") or "").strip()
    out = str(args.get("out") or "").strip()
    try:
        from PIL import ImageGrab
    except ImportError as e:                                           # noqa: BLE001
        print("截不了：自带运行时里没有 PIL（%s）" % e)
        return 3
    box, how = None, "整个屏幕"
    if target:
        box, got = find_window(target)
        if box is None:
            print("没找到标题里带「%s」的窗口。现在的窗口有：\n%s" % (target, got))
            return 2
        how = "窗口「%s」" % got
    if not out:
        d = Path(os.environ.get("MOSS_USER_DATA_DIR") or ".") / "ai" / "shots"
        d.mkdir(parents=True, exist_ok=True)
        out = str(d / ("shot-%s.png" % time.strftime("%Y%m%d-%H%M%S")))
    try:
        img = ImageGrab.grab(bbox=box, all_screens=True)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
    except Exception as e:                                             # noqa: BLE001
        print("截图失败：%s: %s" % (type(e).__name__, e))
        return 4
    size = os.path.getsize(out) if os.path.exists(out) else 0
    print("%s 截下来了：%s（%d×%d，%d 字节）" % (how, out, img.width, img.height, size))
    print("（我看不到图 —— 这是留证据给用户看的；要看像素请自己用 PIL 量。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
