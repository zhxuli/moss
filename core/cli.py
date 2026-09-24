# -*- coding: utf-8 -*-
"""CLI 分发 —— 入口分类与命令派发。

★ 照抄 pa.py:856-931 的 main() 分流顺序（E-20 照抄原则）：
    帮助 → `~`后台脱离前缀 → `cd` → `pick|select|menu` → `:`包调用
    → `/`不切目录 → 路径查找
  moss 的增量：包模型 / 类型化参数 / 结构化返回 / 历史（pa 没有这些）

★ 内建订阅者在这里挂上（`T-05`）：历史服务订阅 `after:run`。
  它是**内核行为**，不是钩子 —— 审计不能依赖一个可以被禁用/写坏的东西。
"""
import json
import os
import sys
import time
from pathlib import Path

try:
    import pyautogui
except ImportError:
    pyautogui = None

from . import (clip, config, engine, events, history, out, paths, pkg as pkg_mod,
               registry, resolve, runners as runners_mod)

USAGE = """moss —— 多语言启动器

用法:
  moss <名字> [参数...]        在当前目录（及向上几层）找匹配的脚本并运行
                               例: moss m        → main.py / main.go / main.html
                                   moss b/m      → 进 b 开头的子目录再找 m 开头
                                   moss s/t/main → 逐级往下
  moss /<名字>                 同上，但**不切换目录**（在当前目录里跑）
  moss ~<名字>                 后台脱离运行，不阻塞当前控制台

  moss :<别名> [参数...]       运行一个已安装的包
                               例: moss :md5 hello
  moss :                       打开交互式选择（上下键 + 回车）

  moss cd <目标>               智能找目录并切换（模拟键盘输入，窗口要激活）
  moss pick | select | menu    交互式选择要运行的包

  moss --list                  列出已安装的包
  moss --history [条数]        看最近的启动记录（默认 10 条）
  moss --rerun <序号>          重跑历史里的第 N 条（不用先 cd 回去）
  moss --resolve <名字>        只看解析结果，不执行
  moss --selfcheck             自检：安装根 / runner 表 / 包 / 运行时
  moss -h | --help             本帮助

说明:
  · 参数写法二选一：位置参数（按 params 顺序）或 key=value
  · 包可以把某个参数标成 rest:true，表示「剩下的参数全归我，我自己解释」
    （img 就是这种：`moss :img webp 60% 1200 *.png`）
  · 环境变量 MOSS_HOME / MOSS_PLUGIN_DATA_DIR 会注入给子进程
  · 配置在 user_data\\config.json（输出横幅、清屏、max_parent_depth、Ctrl-C 策略）
"""


# ---------------------------------------------------------------- 参数
def _coerce(spec, value):
    t = (spec.get("type") or "string").lower()
    if value is None:
        return None
    try:
        if t == "int":
            return int(str(value).strip())
        if t == "float":
            return float(str(value).strip())
        if t == "bool":
            return str(value).strip().lower() in ("1", "true", "yes", "on", "y")
    except Exception:
        return spec.get("default")
    return str(value)


def parse_params(pkg, args):
    """把命令行参数映射到包声明的 params 上（类型化参数，F-08）。

    ★ `rest: true` —— 吞掉「剩下的全部位置参数」，原样拼成一个字符串交给包。
      为什么需要它：像 img 这种「自己有一套小语法」的包
      （`moss :img webp 60% 1200 *.png`），参数个数和含义都由包自己定，
      宿主没法预先声明成几个具名参数。

      没有这个标记时宿主**只取前 N 个位置参数、多余的静默丢掉** ——
      用户多打一个词就悄无声息地没了，这种坑比报错难查得多。

      `rest` 参数应当声明在 params 的**最后**（它后面再写位置参数就永远轮不到）。
    """
    spec = pkg.get("params") or []
    named, positional = {}, []
    for a in args:
        if "=" in a and not a.startswith("="):
            k, _, v = a.partition("=")
            named[k.strip()] = v
        else:
            positional.append(a)

    params = {}
    for p in spec:
        n = p.get("name")
        if not n:
            continue
        params[n] = _coerce(p, named.get(n, p.get("default")))

    pi = 0
    for p in spec:
        n = p.get("name")
        if not n or n in named:
            continue
        if p.get("rest"):
            params[n] = _coerce(p, " ".join(positional[pi:]))
            pi = len(positional)
            continue
        if pi < len(positional):
            params[n] = _coerce(p, positional[pi])
            pi += 1
    return params


# ---------------------------------------------------------------- 调用构造
def build_pkg_inv(rec, params, via="cli"):
    pkg = rec["pkg"]
    pkg_dir = Path(rec["dir"])
    entry = pkg_mod.entry_path(pkg, pkg_dir)
    if entry is None and not pkg_mod.inline_code(pkg):
        return None, "包 '%s' 找不到入口文件（entry.file 指向的文件不存在）" % pkg["id"]

    env = pkg.get("env") or {}
    cwd = env.get("cwd") or os.getcwd()

    inv = {
        "kind": "pkg",
        "id": pkg["id"],
        "pkg_kind": pkg.get("kind"),
        "alias": pkg.get("aliases", [None])[0] if pkg.get("aliases") else pkg["id"],
        "version": pkg.get("version"),
        "runner": pkg.get("runner"),
        "target": str(entry) if entry else None,
        "inline": pkg_mod.inline_code(pkg),
        "cwd": cwd,
        "params": params,
        "args": [],
        "via": via,
        "pkg_dir": str(pkg_dir),
    }
    req = (pkg.get("requires") or {}).get(pkg.get("runner"))
    if req:
        inv["runtimeRequirement"] = str(req)
    return inv, None


def build_path_inv(cand, args, via="cli", change_dir=True):
    """路径调用。

    change_dir=True （默认）：cwd = 目标文件所在目录 —— 照抄 pa.py 的 change_dir 语义
    change_dir=False（`/` 前缀）：cwd = 调用者当前目录，脚本原地跑，不切目录
    """
    cwd = str(Path.cwd()) if not change_dir else str(cand["base"])
    return {
        "kind": "path",
        "id": None,
        "runner": cand["runner"],
        "target": str(cand["path"]),
        "cwd": cwd,
        "interpreter": cand["probe"].get("interpreter"),
        "venv": cand["probe"].get("venv"),
        "params": {},
        "args": list(args),
        "via": via,
    }


def _fill_interpreter(inv, table):
    """给调用补上解释器，**顺带检查这个 runner 在本机到底能不能用**。

    返回 (inv, 错误信息或 None)。
    """
    if inv.get("interpreter"):
        return inv, None

    spec = table.get(inv.get("runner"))
    if spec is None:
        return inv, ("不认识 runner '%s'。检查 system\\runners.json，"
                     "或往 user_data\\runners.json 里加一条。" % inv.get("runner"))

    kind = "package" if inv.get("kind") == "pkg" else "path"
    probe = runners_mod.probe(inv.get("runner"), spec, {
        "cwd": inv.get("cwd") or os.getcwd(),
        "home": str(paths.HOME),
        "entry": inv.get("target") or "",
    }, kind=kind, requirement=inv.get("runtimeRequirement"))
    if not probe.get("available"):
        return inv, ("这个包需要 '%s'，但本机用不了。\n"
                     "       原因：%s\n"
                     "       装好它，或往 user_data\\runners.json 里补一条可用的解释器路径。"
                     % (inv.get("runner"), probe.get("why")))
    inv["interpreter"] = probe.get("interpreter")
    inv["venv"] = probe.get("venv")
    return inv, None


# ---------------------------------------------------------------- 子命令
def cmd_list(table, skip_clear=False):
    if not skip_clear:
        out.conditional_clear_screen()
    recs = registry.scan_all()
    if not recs:
        out.print_cyan("[信息] 还没有安装任何包。包放在 %s" % paths.SYSTEM_PKGS)
        return 0
    out.print_cyan("已安装的包（%d）：" % len(recs))
    print("  %-16s %-8s %-6s %-7s %s" % ("别名", "类型", "版本", "层", "说明"))
    print("  " + "-" * 72)
    for r in recs:
        p = r["pkg"]
        alias = ",".join(p.get("aliases") or []) or p["id"]
        layer = r["layer"] + ("→遮蔽" + r["shadowed"] if r.get("shadowed") else "")
        print("  %-16s %-8s %-6s %-7s %s" % (
            alias[:16], p.get("kind", ""), str(p.get("version", ""))[:6], layer,
            str(p.get("desc", ""))[:30]))
    return 0


def cmd_history(n):
    rows = history.recent(n)
    if not rows:
        out.print_cyan("[信息] 还没有任何启动记录。")
        return 0
    out.print_cyan("最近 %d 条启动记录：" % len(rows))
    for i, r in enumerate(rows, 1):
        what = r.get("id") or r.get("target") or "?"
        print("  %2d) [%s] %-22s cwd=%s  exit=%s  %sms"
              % (i, r.get("via", "?"), str(what)[-22:], r.get("cwd") or "-",
                 r.get("exit"), r.get("ms")))
    print("\n用 `moss --rerun <序号>` 可以重跑（不用先 cd 回去）。")
    return 0


def cmd_rerun(idx, table):
    rows = history.recent(50)
    if not (1 <= idx <= len(rows)):
        out.print_cyan("[错误] 序号超范围（1-%d）。" % len(rows))
        return 1
    r = rows[idx - 1]
    out.print_cyan("[重跑] 来自历史：%s" % (r.get("id") or r.get("target")))

    if r.get("kind") == "pkg" and r.get("id"):
        rec = registry.find_alias(r["id"])
        if not rec:
            out.print_cyan("[错误] 包 '%s' 已经不在了。" % r["id"])
            return 1
        inv, err = build_pkg_inv(rec, r.get("params") or {}, via="history")
        if err:
            out.print_cyan("[错误] %s" % err)
            return 1
    else:
        target = r.get("target")
        cwd = r.get("cwd") or os.getcwd()
        if not target or not os.path.isfile(target):
            out.print_cyan("[错误] 目标已经不在了：%s" % target)
            return 1
        inv = {
            "kind": "path", "id": None, "runner": r.get("runner"),
            "target": target, "cwd": cwd,
            "params": {}, "args": r.get("args") or [], "via": "history",
        }
    inv, err = _fill_interpreter(inv, table)
    if err:
        out.print_cyan("[错误] %s" % err)
        return 1
    return engine.run(inv, table)


def cmd_resolve(name, table):
    """只看解析结果，不执行。

    输出刻意按"层"分组 —— 因为真正的搜索语义是
    **第一层有候选就不再往上找**（照抄 pa.py:908 的 generate_search_paths 用法）。
    """
    out.print_cyan("[解析] `moss %s` —— 逐层向上搜索，第一层有候选就停" % name)
    depth = config.max_parent_depth()
    hit_base, hit_cands = None, []
    for base in resolve.search_bases(Path.cwd(), depth):
        cands = resolve.candidates_at(base, name, table, depth)
        if cands and hit_base is None:
            hit_base, hit_cands = base, cands
        flag = "  ★ 命中，停在这一层" if (cands and base == hit_base) else ""
        print("  %s   候选 %d 个%s" % (base, len(cands), flag))
        for c in cands:
            if c["marker_hits"]:
                d = c.get("marker_dist")
                where = "本目录" if d == 0 else ("上层 %d 级" % d if d is not None else "?")
                marks = "  项目标记: %s（%s）" % (",".join(c["marker_hits"]), where)
            else:
                marks = ""
            print("      %-16s runner=%-10s %s%s"
                  % (c["path"].name, c["runner"], c["probe"].get("why"), marks))
        if hit_base is not None:
            break

    if hit_base is None:
        out.print_cyan("\n[结论] 在 %s 及向上 %d 层内没找到以 '%s' 开头的可运行目标。"
                       % (Path.cwd(), depth, name))
        print("       注意：只有装了对应 runner 的才算候选（`moss --selfcheck` 看 runner 表）。")
        return 1

    try:
        cand, why = resolve.disambiguate(hit_cands, hit_base, name, depth)
    except resolve.Aborted:
        out.print_cyan("\n[结论] 需要你选择，但当前不是交互环境（或你取消了）。")
        return 1
    out.print_cyan("\n[结论] 选中 %s\n       依据：%s" % (cand["path"], why))
    return 0


def cmd_selfcheck(table):
    """打包后烟测用（S-05）：把关键路径全部读一遍。"""
    ok = True
    out.print_cyan("moss 自检")
    print("=" * 60)
    info = paths.describe()
    print("  调用名    : %s" % info["invocation"])
    print("  安装根    : %s   %s" % (info["home"], "存在" if paths.HOME.is_dir() else "✗ 不存在"))
    ok &= paths.HOME.is_dir()
    print("  system/   : %s   %s" % (info["system"], "存在" if paths.SYSTEM_DIR.is_dir() else "✗ 不存在"))
    ok &= paths.SYSTEM_DIR.is_dir()
    print("  user_data/: %s   %s" % (info["user"], "存在" if paths.USER_DIR.is_dir() else "（首次运行会创建）"))
    print("  runner 表 : %d 个 runner —— %s"
          % (len(table), ", ".join(sorted(table.keys())) or "（空！）"))
    ok &= bool(table)

    rts = runners_mod.list_runtimes()
    print("  自带运行时: %d 个" % len(rts))
    for r in rts:
        exe = (Path(r["dir"]) / r["interpreter"]) if r["interpreter"] else None
        good = bool(exe and exe.is_file())
        pin = " ★默认" if r["isDefault"] else ""
        print("     - %-8s %-9s [%s]%s  %s"
              % (r["family"], r["version"], r["layer"], pin,
                 "✔" if good else "✗ 缺解释器 " + r["interpreter"]))
    if not rts:
        print("     （没有自带运行时，包会退化到用系统解释器）")
    for fam in runners_mod.runtime_families():
        if not runners_mod.default_version(fam):
            print("     ⚠ 家族 '%s' 没有在 default.json 里钉默认版本" % fam)

    recs = registry.scan_all()
    print("  包        : %d 个" % len(recs))
    for r in recs:
        e = pkg_mod.entry_path(r["pkg"], Path(r["dir"]))
        print("     - %-12s runner=%-10s 入口=%s" % (
            r["id"], r["pkg"].get("runner"),
            (e.name if e else ("inline" if pkg_mod.inline_code(r["pkg"]) else "✗ 缺失"))))
    print("  pyautogui : %s   （cd 功能需要它）" % ("可用" if pyautogui else "✗ 缺失"))
    print("  剪贴板    : %s   （cd 到中文路径时需要它）" % clip.describe())
    print("=" * 60)
    out.print_cyan("结论: %s" % ("✅ 自检通过" if ok else "✗ 自检失败"))
    return 0 if ok else 1


# ---------------------------------------------------------------- 交互式选择
def interactive_pick(recs):
    """上下键 + 回车的选择器。照抄 pa.py:491-521。"""
    import msvcrt
    idx = 0

    def render():
        out.conditional_clear_screen()
        out.print_cyan("=== 选择包 (↑↓ 选择, 回车运行, Esc 退出) ===\n")
        for i, r in enumerate(recs):
            mark = '\u25b6' if i == idx else ' '
            p = r["pkg"]
            alias = ",".join(p.get("aliases") or []) or p["id"]
            print("  %s%2d. (%s) %-16s %s" % (mark, i + 1, r["layer"], alias,
                                              str(p.get("desc", ""))[:40]))

    render()
    while True:
        try:
            ch = msvcrt.getwch()
        except Exception:
            return None
        if ch == '\x1b':
            out.conditional_clear_screen()
            return None
        if ch in ('\x00', '\xe0'):
            ch2 = msvcrt.getwch()
            if ch2 in ('H', 'A'):
                idx = (idx - 1) % len(recs)
                render()
            elif ch2 in ('P', 'B'):
                idx = (idx + 1) % len(recs)
                render()
        elif ch in ('\r', '\n'):
            out.conditional_clear_screen()
            return recs[idx]


def handle_pick(table, detach=False):
    """照抄 pa.py:524-542，换成"选包"。"""
    recs = registry.scan_all()
    if not recs:
        out.print_cyan("[信息] 未找到任何包。")
        return 1
    chosen = interactive_pick(recs)
    if not chosen:
        out.print_cyan("[取消] 已退出。")
        return 0
    inv, err = build_pkg_inv(chosen, {}, via="cli")
    if err:
        out.print_cyan("[错误] %s" % err)
        return 1
    inv, err = _fill_interpreter(inv, table)
    if err:
        out.print_cyan("[错误] %s" % err)
        return 1
    return engine.run(inv, table, detach=detach)


# ---------------------------------------------------------------- cd
def _type_command(text):
    """把命令"打"进当前活动窗口。返回 (方式, 错误信息)。

    ⚠️ `pyautogui.typewrite()` **打不了非 ASCII 字符** —— 中文没有键位映射，
       会被**静默丢弃**。实测（用户真实撞到的）：

           输入 : cd "D:\\study\\GO\\学习\\基础知识\\BMI"
           打出 : cd "D:\\study\\GO\\\\\\BMI"     ← 汉字整段消失

       这是 `pa.py:845` 就有的 bug（照抄时一起搬过来了）。

    所以分两条路：
      · 纯 ASCII 路径 -> 照旧 typewrite（**不碰用户剪贴板**）
      · 含中文等    -> 剪贴板 + Ctrl+V，**用完把剪贴板还回去**
    """
    if all(ord(c) < 128 for c in text):
        pyautogui.typewrite(text)
        return "typewrite", None

    if not clip.available():
        return None, "路径含非 ASCII 字符，需要 pyperclip 走剪贴板，但它不可用"

    saved = clip.get()
    if not clip.set(text):
        return None, "写入剪贴板失败"
    time.sleep(0.05)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.08)
    pyautogui.press('enter')
    time.sleep(0.4)          # 等控制台把粘贴内容吃完，再把剪贴板还回去
    clip.set(saved)
    return "clipboard", None


def handle_cd(target_str):
    """智能找目录并切换。照抄 pa.py:810-853（用模拟键盘输入切目录）。

    增量：含中文的路径改走剪贴板粘贴（见 `_type_command` 的说明）。
    """
    if pyautogui is None:
        out.print_cyan("[错误] 'cd' 功能需要 'pyautogui' 库。")
        out.print_cyan("请先安装: pip install pyautogui")
        return 1

    target_path = resolve.find_dir(target_str, Path.cwd())

    if not target_path:
        out.conditional_clear_screen()
        out.print_cyan("[错误] 未找到目标目录: %s" % target_str)
        return 1

    abs_path = target_path.resolve()
    command = 'cd "%s"' % abs_path
    ascii_only = all(ord(c) < 128 for c in command)

    out.conditional_clear_screen()
    out.print_cyan("[切换目录] 准备执行: %s" % command)
    if ascii_only:
        out.print_cyan("[注意] 0.1秒后将模拟键盘输入, 请确保命令行窗口是当前活动窗口!")
    else:
        out.print_cyan("[注意] 路径含中文，将用「剪贴板 + Ctrl+V」输入"
                       "（临时占用剪贴板，用完还原）")
        out.print_cyan("[注意] 请确保命令行窗口是当前活动窗口!")

    try:
        time.sleep(0.1)
        how, err = _type_command(command)
        if err:
            raise RuntimeError(err)
        if how == "clipboard":
            out.print_cyan("[完成] 已用剪贴板方式输入（剪贴板已还原）。")
    except Exception as e:
        out.print_cyan("[错误] 模拟键盘输入失败: %s" % e)
        out.print_cyan("您可以手动复制并粘贴以下命令:")
        out.print_cyan(command)
    return 0


# ---------------------------------------------------------------- 主入口
def main(argv):
    config.load()

    # 输入法把模式前缀打成全角时先还原（照抄 pa.py:857-859）
    if argv:
        argv = [config.restore_prefix(argv[0])] + list(argv[1:])

    paths.ensure_user_dirs()

    # 内建订阅者：历史（不是钩子！见 T-05）
    events.BUS.on("after:run", history.on_after_run, name="history")

    table = runners_mod.load()
    reg = registry.load()
    registry.sync(reg)

    # ---- 帮助（照抄 pa.py:861-866：先文档再列表） ----
    if not argv or argv[0] in ("-h", "--help", "help"):
        out.conditional_clear_screen()
        print(USAGE)
        print()
        return cmd_list(table, skip_clear=True)

    first = argv[0]
    rest = argv[1:]

    # ---- `~` 后台脱离前缀（照抄 pa.py:870-874） ----
    detach = False
    dsym = config.detach_symbol()
    if first.startswith(dsym):
        detach = True
        first = first[len(dsym):]

    # ---- cd（照抄 pa.py:876-881） ----
    if first.lower() == 'cd':
        if rest:
            return handle_cd(rest[0])
        out.print_cyan("[错误] 'cd' 命令需要一个目标路径。用法: moss cd <目标>")
        return 1

    # ---- pick / select / menu（照抄 pa.py:883-886） ----
    if first.lower() in ('pick', 'select', 'menu'):
        return handle_pick(table, detach=detach)

    # ---- moss 自己的选项 ----
    if first in ("-l", "--list"):
        return cmd_list(table)
    if first == "--selfcheck":
        return cmd_selfcheck(table)
    if first == "--history":
        n = 10
        if rest:
            try:
                n = max(1, int(rest[0]))
            except ValueError:
                pass
        return cmd_history(n)
    if first == "--rerun":
        if not rest:
            out.print_cyan("[错误] --rerun 需要一个序号。先看 `moss --history`。")
            return 1
        try:
            return cmd_rerun(int(rest[0]), table)
        except ValueError:
            out.print_cyan("[错误] --rerun 的序号必须是数字。")
            return 1
    if first == "--resolve":
        if not rest:
            out.print_cyan("[错误] --resolve 需要一个名字。")
            return 1
        return cmd_resolve(rest[0], table)

    # ---- 包调用（照抄 pa.py:888-894） ----
    psym = config.plugin_symbol()
    if first.startswith(psym):
        alias = first.lstrip(psym).strip()
        if not alias:
            # 照抄 pa.py:890-892 —— 光一个符号就是打开选择器
            return handle_pick(table, detach=detach)
        rec = registry.find_alias(alias)
        if not rec:
            out.print_cyan("[错误] 没有这个包：'%s'。用 `moss --list` 看有哪些。" % alias)
            return 1
        if not registry.is_enabled(reg, rec["id"]):
            out.print_cyan("[错误] 包 '%s' 已被禁用。" % rec["id"])
            return 1
        params = parse_params(rec["pkg"], rest)
        inv, err = build_pkg_inv(rec, params, via="cli")
        if err:
            out.print_cyan("[错误] %s" % err)
            return 1
        inv, err = _fill_interpreter(inv, table)
        if err:
            out.print_cyan("[错误] %s" % err)
            return 1
        return engine.run(inv, table, detach=detach)

    # ---- 路径调用（照抄 pa.py:896-928） ----
    ncsym = config.no_chdir_symbol()
    change_dir = not first.startswith(ncsym)
    clean_arg = first.lstrip(ncsym)

    cand, why = resolve.find(clean_arg, Path.cwd(), table)
    if cand is None:
        if why == "用户取消":
            out.print_cyan("[取消] 已退出。")
            return 130
        out.print_cyan("[错误] 在 %s 及上层没找到以 '%s' 开头的可运行目标。"
                       % (Path.cwd(), clean_arg))
        print("       （只在装了对应 runner 的情况下才算候选：用 `moss --resolve %s` 看细节）"
              % clean_arg)
        return 1

    out.print_cyan("[选中] %s  ← %s" % (cand["path"], why))
    inv = build_path_inv(cand, rest, via="cli", change_dir=change_dir)
    inv, err = _fill_interpreter(inv, table)
    if err:
        out.print_cyan("[错误] %s" % err)
        return 1
    return engine.run(inv, table, detach=detach)
