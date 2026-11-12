import io
import os
import re
import sys

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

EXCLUDE = [
    "## 0. 一句话结论",
    "## 2. 目标与不变量",
    "## 3. 统一模型",
    "## 4. 分层、覆盖与升级",
    "## 6. 分发：Web 下载源",
    "## 8. 迁移路径",
    "## 9. 开放问题",
    "> ⛔ **别读这份。**",
    "> 保留此文件仅为历史留档",
    "> ---",
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
        print("用法: python tools/文档完整性审计.py <基准文档> <待审计文档...>")
        return 2
    rc1 = audit(args[0], args[1:])
    rc2 = check_declared(args[0])
    return max(rc1, rc2)

if __name__ == "__main__":
    sys.exit(main())
