#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Lucide 图标取下来，落成 `system/icon/svg/<名字>.svg`（一个图标一个文件）。

为什么长这样（`V-267`）
----------------------
你原话：「你把很多 svg 图标放在了 moss 的代码中，这导致代码很臃肿，应该把所有的 svg
图标都迁移到文件当中去，以减少代码行数」。于是 260 条 path 数据从
`system/ui/vendor/lucide.js` 里搬出来、一个图标一个 `.svg`；那份 `.js` 只剩二十来行的
`ico()`（它读宿主注入的 `window.__MOSS_ICONS`，实现见 `system/ui/icons.py`）。

★ 这个脚本以前是"往 `lucide.js` 的表里插一行" —— 表没了，它也就跟着改成**写文件**。
  规矩没变：**只增不改**（已有的文件一个字节都不动，免得整目录产生无意义 diff）。

它干什么
--------
1. 先看 `system/icon/svg/` 里**已经有了哪些**（按文件名）；
2. 缺的那些去 `unpkg.com/lucide-static@<版本>/icons/<名字>.svg` 取，套上统一画笔写成文件；
3. 取不到就**一个文件都不写**（免得留下半份）。

用法
----
    venv\\Scripts\\python.exe tools\\取图标.py                 # 只报告，不写
    venv\\Scripts\\python.exe tools\\取图标.py history clock   # 把这两个补进去
    venv\\Scripts\\python.exe tools\\取图标.py --verify        # 拿线上重新核对现有文件
    venv\\Scripts\\python.exe tools\\取图标.py --vb "0 0 1024 1024" --solid <名字>
                                                              # 非 Lucide 的图（自绘/别的库）

★ 依赖网络（unpkg）。取完就把结果提交进仓库，**运行界面不需要网**。
★ `moss-` 开头的是**手工加的**（不在 lucide-static 里）—— `--verify` 跳过它们；
  要换成别的来源就自己把文件放进目录（`icons.py` 只认"能不能解析出 viewBox"）。
"""
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

VERSION = "1.48.0"
URL = "https://unpkg.com/lucide-static@%s/icons/%s.svg"
HERE = Path(__file__).resolve().parent.parent
SVG_DIR = HERE / "system" / "icon" / "svg"

#: 描边族（Lucide 那一套）统一画笔 —— 写进文件的 `<g>` 里，`ico()` 不再关心这些
STROKE_ATTRS = ('fill="none" stroke="currentColor" stroke-width="1.5" '
                'stroke-linecap="round" stroke-linejoin="round"')
SOLID_ATTRS = 'fill="currentColor"'


def parse(text):
    """一个 .svg 文件 → `{vb, body}`（跟 `system/ui/icons.py` 一样只认 viewBox + 里面那段）。"""
    m = re.search(r"<svg\b[^>]*\bviewBox=\"([^\"]+)\"[^>]*>(.*)</svg>", text, re.S | re.I)
    if not m:
        return None
    return {"vb": m.group(1).strip(), "body": m.group(2).strip()}


def inner(body):
    """把文件里 `<g …>…</g>` 那层剥掉，只留路径 —— `--verify` 拿它跟线上比。"""
    m = re.search(r"<g\b[^>]*>(.*)</g>", body, re.S)
    return norm(m.group(1)) if m else norm(body)


def norm(s):
    """归一化：单引号、单行、自闭合前留一个空格 —— 线上下来的和文件里的都用这一套。"""
    s = s.replace('"', "'").replace("\n", " ")
    s = " ".join(s.split())
    s = re.sub(r"\s*/>", " />", s)
    return re.sub(r"<(path|rect|circle|line|polyline|polygon|ellipse|g)\b", r"<\1", s)


def fetch(name):
    """抓一个图标，把 `<svg>` 里的内容归一化成仓库里那种单引号单行写法。"""
    url = URL % (VERSION, name)
    req = urllib.request.Request(url, headers={"User-Agent": "moss-tools/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8")
    # ★ 顺序有讲究：unpkg 返回的 svg 第一行是 `<!-- @license ... -->`，
    #   先按第一个 ">" 切会切在**注释**的结尾上（踩过：80 条全部对不上）。
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)       # 去掉许可注释
    body = raw.split("<svg", 1)[1]                         # 去掉 <svg ...> 开标签
    body = body.split(">", 1)[1].rsplit("</svg>", 1)[0]    # 去掉 </svg> 尾标签
    return norm(body)


def svg_file(name, body, vb, attrs):
    """拼出一个 `.svg` 文件的内容（两行：`<svg …>` + 自带画笔的 `<g>`）。"""
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s">\n'
            "<g %s>%s</g>\n"
            "</svg>\n" % (vb, attrs, body))


def _replace(tmp, dest):
    """原子替换。Windows 上正被占用的目标会抛 EIO/EPERM，重试几次。"""
    for i in range(5):
        try:
            os.replace(str(tmp), str(dest))
            return
        except OSError as e:
            if i == 4:
                tmp.unlink(missing_ok=True)
                raise SystemExit("[错误] 替换 %s 失败：%s" % (dest, e))
            time.sleep(0.4)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    verify = "--verify" in sys.argv[1:]
    vb = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--vb=")),
              "0 0 24 24")
    attrs = SOLID_ATTRS if "--solid" in sys.argv[1:] else STROKE_ATTRS

    have = {}
    for p in sorted(SVG_DIR.glob("*.svg")):
        got = parse(p.read_text(encoding="utf-8", errors="replace"))
        if got:
            have[p.stem] = got
    print("现有 %d 个图标：%s" % (len(have), SVG_DIR))
    if not have:
        print("[错误] 一个图标都没读出来 —— 目录不对，还是文件格式变了？")
        return 1

    if verify:
        bad, ok = [], 0
        for name, got in have.items():
            # ★ 手工加的那几颗（`moss-*`）不在 lucide-static 里（`moss-openai` 是 Tabler 的
            #   标记、另外三颗是自绘）—— 别拿线上去核对它，白报"取不到"。
            if name.startswith("moss-"):
                continue
            try:
                if fetch(name) == inner(got["body"]):
                    ok += 1
                else:
                    bad.append(name)
            except Exception as e:                             # noqa: BLE001
                bad.append("%s(%s)" % (name, e))
        print("线上核对：一致 %d 个；对不上 %s" % (ok, bad or "无"))
        return 1 if bad else 0

    added, failed = [], []
    for name in args:
        if name in have:
            print("  已有，跳过：%s" % name)
            continue
        try:
            added.append((name, fetch(name)))
            print("  取到：%s" % name)
        except Exception as e:                                 # noqa: BLE001
            failed.append("%s：%s" % (name, e))
            print("  [失败] %s：%s" % (name, e))

    if failed:
        print("[错误] 有图标没取到，**什么都没写**（避免写出一份残缺的目录）：%s" % failed)
        return 1
    if not added:
        print("没有要补的，目录没动。")
        return 0

    for name, body in added:
        dest = SVG_DIR / (name + ".svg")
        tmp = SVG_DIR / (name + ".svg.tmp")
        tmp.write_text(svg_file(name, body, vb, attrs), encoding="utf-8", newline="")
        _replace(tmp, dest)
    print("已写入 %d 个：%s（目录里现在 %d 个）"
          % (len(added), " ".join(n for n, _ in added), len(have) + len(added)))
    print("★ 别忘了把 vendor/README.md 里那句图标个数一起改掉。")
    return 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                      # noqa: BLE001
            pass
    if sys.platform == "win32":
        try:
            subprocess.run(["chcp", "65001"], shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:                                      # noqa: BLE001
            pass
    sys.exit(main())
