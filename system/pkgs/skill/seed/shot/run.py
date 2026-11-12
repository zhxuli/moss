import json
import os
import sys
import time
from pathlib import Path

def read_args():
    raw = (os.environ.get("MOSS_PKG_PARAMS")
           or os.environ.get("MOSS_TOOL_ARGS") or "").strip()
    if not raw:
        try:
            raw = sys.stdin.read()
        except Exception:
            raw = ""
    try:
        got = json.loads(raw) if raw.strip() else {}
    except ValueError:
        got = {}
    return got if isinstance(got, dict) else {}

def out_dir():
    d = (os.environ.get("MOSS_PLUGIN_DATA_DIR") or "").strip()
    base = Path(d) if d else (Path(os.environ.get("MOSS_USER_DATA_DIR") or ".") /
                              "state" / "--shot")
    return base / "shots"

def find_window(title_kw):
    try:
        import pygetwindow as gw
    except ImportError as e:
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
    except ImportError as e:
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
        d = out_dir()
        d.mkdir(parents=True, exist_ok=True)
        out = str(d / ("shot-%s.png" % time.strftime("%Y%m%d-%H%M%S")))
    try:
        img = ImageGrab.grab(bbox=box, all_screens=True)
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        img.save(out)
    except Exception as e:
        print("截图失败：%s: %s" % (type(e).__name__, e))
        return 4
    size = os.path.getsize(out) if os.path.exists(out) else 0
    print("%s 截下来了：%s（%d×%d，%d 字节）" % (how, out, img.width, img.height, size))
    print("（我看不到图 —— 这是留证据给用户看的；要看像素请自己用 PIL 量。）")
    return 0

if __name__ == "__main__":
    sys.exit(main())
