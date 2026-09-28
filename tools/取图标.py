#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Lucide 图标取下来，生成/更新 `system/ui/vendor/lucide.js`。

为什么要有这个脚本
------------------
`vendor/README.md` 里一直写着「`lucide.js` 是脚本生成的，**别手工编辑**」，
但那个脚本**不在仓库里**（只在提交记录里）—— 于是后来谁想补一个图标，
要么翻提交记录，要么手抄（等于破了自己定的规矩）。这个脚本就是把它补回来。

它干什么
--------
1. 把现有 `lucide.js` 里的每一条**原样读出来**（不改动、不重排）；
2. 对照 `unpkg.com/lucide-static@<版本>/icons/<名字>.svg` 把**缺的**补到末尾；
3. 连头注释和 `ico()` 函数一起原子写回（先写临时文件再替换）。

用法
----
    venv\\Scripts\\python.exe tools\\取图标.py                 # 只报告，不写
    venv\\Scripts\\python.exe tools\\取图标.py history clock   # 把这两个补进去
    venv\\Scripts\\python.exe tools\\取图标.py --verify        # 拿线上重新核对现有条目

★ 为什么"现有条目原样保留"：重排/重刷会让 `lucide.js` 整个文件产生无意义 diff
  （80 多个路径全变），以后 review 根本看不出到底加了什么。**只增不改。**

★ 依赖网络（unpkg）。取完就把结果提交进仓库，**运行界面不需要网**。
"""
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

VERSION = "1.48.0"
URL = "https://unpkg.com/lucide-static@%s/icons/%s.svg"
HERE = Path(__file__).resolve().parent.parent
TARGET = HERE / "system" / "ui" / "vendor" / "lucide.js"

HEAD = """/* Lucide 图标（ISC 许可，见 vendor/lucide-LICENSE.txt），版本 %s，取自 lucide-static。
 * 只保留用到的这些图标，每条是 <svg> 里的内容（24x24、1.5 描边、currentColor）。
 * 用法：ico('play')  →  一段 innerHTML 字符串。
 *
 * ★ 这个文件由 `tools/取图标.py` 生成 —— **别手工编辑**（vendor/README.md 里也是这么写的）。
 *   补图标：venv\\Scripts\\python.exe tools\\取图标.py <名字> [<名字> ...]
 */
const LUCIDE = {
""" % VERSION

TAIL = """};

function ico(name, cls) {
  const body = LUCIDE[name] || LUCIDE['file'] || '';
  return '<svg class="' + (cls || 'i') + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' + body + '</svg>';
}
"""

# ★ 行尾那个逗号**必须是可选的**：文件里最后一条后面没有逗号。
#   写成必需的话，最后一条读不出来 —— 重写文件时它就被悄悄丢掉了
#   （补 `history` 时真踩到：`git-branch` 那一行没了，diff 里才看出来）。
ENTRY = re.compile(r'^"([a-z0-9\-]+)":\s*"(.*?)",?\s*$')


def parse(text):
    """读出 {名字: 内容}（保持文件里的顺序 —— Python 3.7+ 的 dict 有序）。"""
    out = {}
    for line in text.splitlines():
        m = ENTRY.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    return out


def fetch(name):
    """抓一个图标，把 <svg> 里的内容归一化成仓库里那种单引号单行写法。"""
    url = URL % (VERSION, name)
    req = urllib.request.Request(url, headers={"User-Agent": "moss-tools/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read().decode("utf-8")
    # ★ 顺序有讲究：unpkg 返回的 svg 第一行是 `<!-- @license ... -->`，
    #   先按第一个 ">" 切会切在**注释**的结尾上（踩过：80 条全部对不上）。
    raw = re.sub(r"<!--.*?-->", "", raw, flags=re.S)       # 去掉许可注释
    body = raw.split("<svg", 1)[1]                         # 去掉 <svg ...> 开标签
    body = body.split(">", 1)[1].rsplit("</svg>", 1)[0]    # 去掉 </svg> 尾标签
    body = body.replace('"', "'").replace("\n", " ")
    body = " ".join(body.split())
    body = re.sub(r"\s*/>", " />", body)                   # 自闭合标签前留一个空格
    body = re.sub(r"<(path|rect|circle|line|polyline|polygon|ellipse|g)\b", r"<\1", body)
    return body


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    verify = "--verify" in sys.argv[1:]

    text = TARGET.read_text(encoding="utf-8")
    have = parse(text)
    if not have:
        print("[错误] 从 %s 里一条图标都没读出来 —— 格式变了？" % TARGET)
        return 1
    print("现有 %d 个图标：%s" % (len(have), TARGET))

    if verify:
        bad, ok = [], 0
        for name, body in have.items():
            try:
                if fetch(name) == body:
                    ok += 1
                else:
                    bad.append(name)
            except Exception as e:
                bad.append("%s(%s)" % (name, e))
        print("线上核对：一致 %d 个；对不上 %s" % (ok, bad or "无"))
        return 1 if bad else 0

    added, failed = [], []
    for name in args:
        if name in have:
            print("  已有，跳过：%s" % name)
            continue
        try:
            have[name] = fetch(name)
            added.append(name)
            print("  取到：%s" % name)
        except Exception as e:
            failed.append("%s：%s" % (name, e))
            print("  [失败] %s：%s" % (name, e))

    if failed:
        print("[错误] 有图标没取到，**什么都没写**（避免写出一份残缺的表）：%s" % failed)
        return 1
    if not added:
        print("没有要补的，文件没动。")
        return 0

    body = HEAD + "".join('"%s": "%s",\n' % (n, b) for n, b in have.items()) + TAIL
    tmp = TARGET.with_suffix(".js.tmp")
    tmp.write_text(body, encoding="utf-8", newline="")
    _replace(tmp, TARGET)
    print("已写回 %s（新增 %d 个：%s；共 %d 个）"
          % (TARGET, len(added), " ".join(added), len(have)))
    print("★ 别忘了把 vendor/README.md 里的图标个数一起改掉。")
    return 0


def _replace(tmp, dest):
    """原子替换。Windows 上正被占用的目标会抛 EIO/EPERM，重试几次。"""
    import os
    import time
    for i in range(5):
        try:
            os.replace(str(tmp), str(dest))
            return
        except OSError as e:
            if i == 4:
                tmp.unlink(missing_ok=True)
                raise SystemExit("[错误] 替换 %s 失败：%s" % (dest, e))
            time.sleep(0.4)


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.platform == "win32":
        try:
            subprocess.run(["chcp", "65001"], shell=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    sys.exit(main())
