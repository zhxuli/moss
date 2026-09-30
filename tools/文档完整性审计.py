#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档完整性审计：检查源文件的内容有没有在合并 / 改写中丢失。

背景
----
把文档从多个来源合并、或反复改写时，最容易出的事就是**悄悄丢内容**
（本项目就真实发生过一次：合并到单一文档时整篇漏掉了 v1 设计稿 411 行）。

这个脚本把源文件逐行拿到目标文档里找，把找不到的列出来，并且**分成两类**：
  · 已声明排除 —— 我们**明知并有意**不要的（归档横幅、被改写的旧状态行、被否决的旧章节）
  · 意外缺失   —— **这一类必须为 0**，不为 0 就说明真丢东西了

用法
----
    python 文档完整性审计.py <目标文档> <源文件1> [源文件2 ...]

退出码：意外缺失为 0 → 0；否则 → 1。

维护
----
合并方式变了、或有意排除了新东西，就往 `EXCLUDE` 里加一条**前缀**。
前缀既可以是 `## ` 开头（排除整节），也可以是任意行首（排除若干行）。
"""
import io
import os
import re
import sys

# ★ 控制台编码：本文件要打 ✅ ❌ ⬜ ⭐ ⚠ 这些符号，而 Windows 中文控制台
#   默认 cp936(GBK)，print 上去直接 UnicodeEncodeError 崩掉。
#   独立工具不 import core（那会连带读 user_data），所以就地兜一下。
if os.name == "nt":
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except Exception:
        pass
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

# ---------------------------------------------------------------- 已声明的排除
# 这些是"我们明确知道不要的"，不是丢失。
EXCLUDE = [
    # —— v1 中有意未搬回的章节（理由见文档「第三部分」表头） ——
    "## 0. 一句话结论",
    "## 2. 目标与不变量",
    "## 3. 统一模型",
    "## 4. 分层、覆盖与升级",
    "## 6. 分发：Web 下载源",
    "## 8. 迁移路径",
    "## 9. 开放问题",
    # —— 各源文件头部的"别读这份"归档横幅 ——
    "> ⛔ **别读这份。**",
    "> 保留此文件仅为历史留档",
    "> ---",
    # —— 合并时有意替换掉的旧表头 / 旧状态行 ——
    "> 📌 **决策的权威状态",
    '> 本文讲"为什么这么设计"',
    "> 两者冲突时，以台账为准。",
    "> ⚠️ 本文描述的是**新项目**的设计",
    "> 状态：**待确认的设计稿**",
    "> 本文取代 `统一包架构设计.md`",
    "> 这篇是**从头重定格式**",
    "> **代码一行未改。**",
    "> **这是咱俩所有商量的唯一真相来源。**",
    "> 讨论过程可以散在对话里",
    "> 最后更新：2026-09-24（第 1 版）",
    # —— v1 旧文档头注（描述的是那份旧稿自己的状态，不是正文内容） ——
    "> ⚠️ **本文已被",
    "> v2 是从头重定格式",
    "> 本文的价值在于：",
    "> 但 §3–§8 的目标形态请以 v2 为准。",
    "> 状态：设计稿 · 2026-09-24",
    "> 目标读者：本项目后续开发者",
    "> 相关代码：`pa_soft/pa.py`",
    "> `pa_soft/bin/soft/*/plugin.json`",
    "> 本文只讲**设计决策**。",
    "- 详细设计与论证：",
    "- **那份文档讲",
    "| 1 | `G-01` `G-02` |",
    "| 4 | `F-01`… |",
    "| 5 | `R-01`… |",
    "| G-01 | 新项目放在哪个路径 |",
    "| G-02 | 新项目叫什么名字 |",
    "| F-01 | 清单文件名",
    # —— 状态被确认后更新过的旧行（源文件里还是 ⬜，文档里已 ✅） ——
    "| G-03 | 是否沿用 Python + nuitka 打包 | ⬜",
    "| G-04 | 宿主是单文件 exe，还是 exe + 文件夹 | ⬜",
]


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def is_heading(s):
    return s.lstrip().startswith("#")


def is_noise(s):
    return s in ("", "---", "|") or set(s) <= set("-| ")


def excluded(line, heading):
    """当前行是否命中排除前缀（含"所在章节被排除"）。"""
    for p in EXCLUDE:
        if line.startswith(p):
            return True
        if heading and heading.startswith(p):
            return True
    return False


def audit(target_path, source_paths):
    target = io.open(target_path, encoding="utf-8").read()
    t_lines = set(n for n in (norm(l) for l in target.splitlines()) if n)
    t_blob = norm(target)

    print("目标文档: %s" % target_path)
    print("  行数 %d   字符 %d" % (len(target.splitlines()), len(target)))

    total_expected_missing = 0
    for path in source_paths:
        src = io.open(path, encoding="utf-8").read()
        heading = None
        miss_excl, miss_body, miss_head = [], [], []

        for raw in src.splitlines():
            line = norm(raw)
            if not line or is_noise(line):
                continue
            if line.lstrip().startswith("## "):
                heading = line
            if line in t_lines or line in t_blob:
                continue
            if excluded(line, heading):
                miss_excl.append(line)
            elif is_heading(line):
                miss_head.append(line)
            else:
                miss_body.append(line)

        total_expected_missing += len(miss_body)

        print()
        print("=" * 74)
        print("源: %s" % path)
        print("  已声明排除 %d   标题变化 %d   ★意外缺失 %d"
              % (len(miss_excl), len(miss_head), len(miss_body)))
        print("=" * 74)
        if miss_body:
            print("  ★ 意外缺失（需要人工确认）：")
            for m in miss_body:
                print("     ✗ %s" % m[:140])
        if miss_head:
            print("  标题变化（改编号属正常，仅供核对）：")
            for m in miss_head:
                print("     · %s" % m[:140])

    print()
    if total_expected_missing == 0:
        print("✅ 结论：意外缺失 0 —— 没有丢东西。")
        return 0
    print("⚠️  结论：意外缺失 %d 行 —— 请人工核对上面标 ✗ 的行。" % total_expected_missing)
    return 1


DECL_RE = re.compile(r"当前状态：(\d+) 条议题 —— ✅ (\d+) / ❌ (\d+) / ⬜ (\d+)")


def check_declared(path):
    """核对文档自己声明的议题数量与实际是否一致。

    ★ `V-100`：编号到三位数了，这条正则原来只认 `\d{2}` —— `V-100` 那一行**数不进去**，
      于是"实际 352 / 声明 353"报了个假的不一致（先怀疑工具）。改成 `\d{2,3}`。

    文档第一部分表头写着"当前状态：N 条议题 —— ✅ a / ❌ b / ⬜ c"。
    任何一次编辑如果把议题弄丢了，这个数就对不上 —— 这是最省事的一道防线。
    """
    text = io.open(path, encoding="utf-8").read()
    m = DECL_RE.search(text)
    print()
    print("=" * 74)
    print("声明状态自检")
    print("=" * 74)
    if not m:
        print("  · 文档里没写「当前状态：N 条议题」这一行，跳过（不算失败）")
        return 0

    decl_total = int(m.group(1))
    decl = {"✅": int(m.group(2)), "❌": int(m.group(3)), "⬜": int(m.group(4))}

    actual = {"✅": 0, "❌": 0, "⬜": 0}
    seen = set()
    for ln in text.splitlines():
        mm = re.match(r"^\|\s*([A-Z]{1,3}-\d{2,3})\s*\|.*?\|\s*(✅|❌|⬜)\s*\|", ln)
        if mm and mm.group(1) not in seen:
            seen.add(mm.group(1))
            actual[mm.group(2)] += 1

    ok = True
    print("  声明: 共 %d 条  ✅ %d / ❌ %d / ⬜ %d"
          % (decl_total, decl["✅"], decl["❌"], decl["⬜"]))
    print("  实际: 共 %d 条  ✅ %d / ❌ %d / ⬜ %d"
          % (len(seen), actual["✅"], actual["❌"], actual["⬜"]))
    if len(seen) != decl_total:
        print("  ✗ 总数对不上！有议题被弄丢了，或声明行该更新了")
        ok = False
    for k in ("✅", "❌", "⬜"):
        if actual[k] != decl[k]:
            print("  ✗ %s 数量对不上：声明 %d，实际 %d" % (k, decl[k], actual[k]))
            ok = False
    if ok:
        print("  ✅ 一致")
        return 0
    return 1


def main():
    args = [a for a in sys.argv[1:]]
    if len(args) < 2:
        print(__doc__)
        return 2
    rc1 = audit(args[0], args[1:])
    rc2 = check_declared(args[0])
    return max(rc1, rc2)


if __name__ == "__main__":
    sys.exit(main())
