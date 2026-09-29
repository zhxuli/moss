# -*- coding: utf-8 -*-
"""CLI 分发 —— 入口分类与命令派发。

★ 照抄 pa.py:856-931 的 main() 分流顺序（E-20 照抄原则）：
    帮助 → `~`后台脱离前缀 → `cd` → `:`包调用 → `/`不切目录 → 路径查找
  （pa 的 `pick|select|menu` 选择器 **2026-09-27 去掉了**，见 `CL-13`）
  moss 的增量：包模型 / 类型化参数 / 结构化返回 / 历史（pa 没有这些）

★ 内建订阅者在这里挂上（`T-05`）：历史服务订阅 `after:run`。
  它是**内核行为**，不是钩子 —— 审计不能依赖一个可以被禁用/写坏的东西。
"""
import json
import os
import shutil
import sys
import unicodedata
from pathlib import Path

from . import (config, engine, events, history, out, paths, pkg as pkg_mod,
               registry, resolve, runners as runners_mod, shell, ui)

USAGE = """moss —— 多语言启动器

用法:
  moss <名字> [参数...]        在当前目录（及向上几层）找匹配的脚本并运行
                               例: moss m        → main.py / main.go / main.html
                                   moss b/m      → 进 b 开头的子目录再找 m 开头
                                   moss s/t/main → 逐级往下
                               文件系统里找不到时，会去「历史」里找同名的那次调用
                               （例如 moss zeen 直接进上次那个 ZeEn），命中多个取最近的
  moss /<名字>                 同上，但不切换目录（在当前目录里跑）
  moss ~<名字>                 后台脱离运行，不阻塞当前控制台

  moss :<别名> [参数...]       运行一个已安装的包
                               例: moss :md5 hello

  moss ui                      打开界面（双击 moss.exe / 快捷方式 / 快速启动栏也是这个 ——
                               没有控制台时不开命令行，直接开界面）
  moss --ui                    同上（写全一点的形式，脚本里更显眼）

  moss cd <目标>               智能找目录并切过去（认出父 shell 后把命令注入控制台）
  moss cd --install            把 cd 包装函数写进 PowerShell 配置 → 屏幕上不留回显
  moss cd --uninstall          删掉那个包装函数

  moss --history               最近启动记录：方向键选择，回车直接再跑一次（去重，最多 20 条）
                               回车进入程序后，程序退出即结束，不会回到列表
  moss --history <条数>        只打印不交互（管道 / 脚本用这种）
  moss --remove <别名>         卸载一个包：包本体 + 它的数据（永久删除，需确认；-y 跳过）
  moss --spec                  打印「插件契约」：怎么写一个插件（写插件 / AI 调用前请先读）
  moss --new <id>              生成一个能跑的插件骨架到 user_data/pkgs/<id>/
  moss --rename <旧> <新id>    给一个包改名：包目录 / 数据目录 / 清单里的 id 一起改
                               （新 id 写成它现在的 id，就是"把目录名对齐成 id"）
  moss --resolve <名字>        只看解析结果，不执行（排障用：为什么选中它 / 为什么没找到）
  moss --selfcheck             自检：安装根 / runner 表 / 包 / 自带运行时 / cd 注入

说明:
  · 参数写法二选一：位置参数（按 params 顺序）或 key=value
  · 包可以把某个参数标成 rest:true，表示「剩下的参数全部交给这个包自己解释」
    （img 就是这种：moss :img webp 60% 1200 *.png）
  · 环境变量 MOSS_HOME / MOSS_PLUGIN_DATA_DIR 会注入给子进程
  · 配置在 user_data\\config.toml（带注释：命令前缀符号 / 输出横幅 / 清屏 /
    搜索层数 / Ctrl-C 策略 —— 打开那个文件就知道每一项是干什么的）
  · 裸名（不带前缀）归谁可以改：默认 moss m 找文件、moss :img 跑包；
    若主要用途是"跑装好的包"（不常写脚本），把 config.toml 里的 plugin_mode 留空、
    path_mode 填 ":" —— 于是 moss img 直接跑包，moss :img 才是找文件
  · 有没有参数决定干什么，有没有控制台决定怎么进来：
      终端里敲 moss           → 用法 + 包列表（命令行）
      终端里敲 moss ui        → 界面
      双击 / 快捷方式 / 快速启动栏 → 界面（没有控制台，命令行打给谁看呢）
      带参数（moss :img 60%） → 一律按参数干活，不看有没有控制台
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
    icon = pkg_mod.icon_path(pkg, pkg_dir)

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
        "icon": str(icon) if icon else None,
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
#: 两层的说法与位置（U-15：列表要按这两类分块显示，并写明"在哪、谁压谁"）
_LAYERS = (
    ("user", "用户插件", "你自己写的 / 从商店装的，升级不碰", paths.USER_PKGS),
    ("system", "系统插件", "随 moss 分发，升级时整体替换", paths.SYSTEM_PKGS),
)


def _pkg_rows(recs):
    """把扫描结果按层分好组（保持 _LAYERS 的顺序）。"""
    by_layer = {}
    for r in recs:
        by_layer.setdefault(r["layer"], []).append(r)
    return by_layer


def cmd_list(table, skip_clear=False):
    if not skip_clear:
        out.conditional_clear_screen()
    recs = registry.scan_all()
    if not recs:
        out.print_cyan("[信息] 还没有安装任何包。包放在 %s" % paths.SYSTEM_PKGS)
        return 0

    by_layer = _pkg_rows(recs)
    out.print_cyan("已安装的包（%d）—— 按层分组" % len(recs))
    print("  优先级：用户插件 > 系统插件"
          "（同名时高优先级遮蔽低优先级，低层原件保留）")
    for key, cn, why, where in _LAYERS:
        rows = by_layer.get(key)
        if not rows:
            continue                      # 这一类是空的就不显示
        print()
        print("  【%s】%s%s" % (cn, why, ("　" + str(where)) if where else ""))
        print("    %-16s %-7s %-7s %s" % ("别名", "类型", "版本", "说明"))
        print("    " + "-" * 68)
        for r in rows:
            p = r["pkg"]
            alias = ",".join(p.get("aliases") or []) or p["id"]
            tail = ""
            if r.get("shadowed"):
                tail += "  [它遮住了 %s 层的同名包]" % r["shadowed"]
            print("    %-16s %-7s %-7s %s%s" % (
                alias[:16], p.get("kind", ""), str(p.get("version", ""))[:7],
                str(p.get("desc", ""))[:34], tail))
    return 0


def _term_size():
    """（列, 行）。优先问控制台自己，问不到再退回环境变量/默认值。"""
    size = out.console_size()
    if size:
        return max(20, size[0]), max(8, size[1])
    try:
        s = shutil.get_terminal_size((100, 30))
        return max(20, s.columns), max(8, s.lines)
    except Exception:
        return 100, 30


def _hist_time(r):
    ts = str(r.get("ts") or "")
    return ts[11:19] if len(ts) >= 19 else ts


# ---------------------------------------------------------------- 显示宽度
# ★ 排版必须按**显示宽度**算，不能用 len()：中文 / 全角字符在终端里占两列。
#   而且 `▶ … ✔ ·` 这类符号的宽度是"不确定"的（East Asian Ambiguous，
#   有的字体按 1 列、有的按 2 列）—— 实测 `▶` 后面就多出一格。
#   所以下面只用宽度确定的字符：ASCII 一定 1 列，汉字 / 全角标点一定 2 列。
def _cw(ch):
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1


def _w(s):
    """字符串在控制台上的显示宽度。"""
    return sum(_cw(ch) for ch in str(s))


def _pad(s, w):
    """补齐 / 截断到恰好 w 列（超了从尾部截）。"""
    s = str(s)
    while s and _w(s) > w:
        s = s[:-1]
    return s + " " * max(0, w - _w(s))


def _tail(s, w):
    """保留尾部（路径的信息量在末尾），截掉的部分用 `<` 提示。"""
    s = str(s)
    if _w(s) <= w:
        return s
    out = ""
    for ch in reversed(s):
        if _w(out) + _cw(ch) > w - 1:
            break
        out = ch + out
    return "<" + out


def _hist_args(r):
    """这条记录**到底跑了什么参数** —— 去重是按它们算的，必须显示出来，
    否则"同包不同参数"的多条记录看起来就像没去重。"""
    if r.get("kind") == "pkg":
        p = r.get("params") or {}
        if not p:
            return ""
        if len(p) == 1 and "args" in p:      # rest:true 的包（比如 img）
            return str(p["args"])
        return " ".join("%s=%s" % (k, p[k]) for k in sorted(p))
    return " ".join(str(x) for x in (r.get("args") or []))


def _hist_name(r):
    if r.get("id"):
        return str(r["id"])
    # 路径调用：只显示文件名 —— 目录已经在右边那一列了，塞整条路径只会被截成
    # "C:\\Users\\Adminis" 这种没用的半截
    t = str(r.get("target") or "?").replace("/", "\\")
    return t.rsplit("\\", 1)[-1] or t


def _hist_failed(r):
    return r.get("exit") not in (0, None)


# 列宽（显示列）：序号 3 / 时间 8 / 名称 16 / 参数 20
_HIST_FIXED = 1 + 1 + 3 + 2 + 8 + 2 + 16 + 1 + 20 + 1


def _hist_head(width, with_args=True):
    """表头。跟数据行同一套列宽，才叫"规整"。"""
    head = " " * 2 + _pad("#", 3) + "  " + _pad("时间", 8) + "  " + _pad("名称", 16)
    if with_args:
        head += " " + _pad("参数", 20)
        room = width - 1 - _w(head) - 1
    else:
        room = width - 1 - _w(head) - 1
    return head + " " + _pad("目录", max(4, room))


def _hist_row(i, r, width, marker=" "):
    """一条记录排成一行，**显示宽度必须 ≤ width**（折行会让原地重画错位）。"""
    with_args = width - _HIST_FIXED >= 10
    line = "%s %3d  %s  %s" % (marker, i, _pad(_hist_time(r), 8),
                               _pad(_hist_name(r), 16))
    if with_args:
        line += " " + _pad(_hist_args(r), 20)
    room = width - 1 - _w(line) - (2 if _hist_failed(r) else 0)
    if room >= 6:
        line += " " + _pad(_tail(r.get("cwd") or "-", room), room)
    if _hist_failed(r):
        line += " !"
    return line if _w(line) <= width else _pad(line, width)


def _scroll_top(idx, total, vh):
    if total <= vh:
        return 0
    return max(0, min(idx - vh // 2, total - vh))


def _print_history(rows):
    width, _ = _term_size()
    out.print_cyan("最近 %d 条启动记录（已去重，同一件事只留最新一条）" % len(rows))
    print(_hist_head(width, width - _HIST_FIXED >= 10))
    for i, r in enumerate(rows, 1):
        print(_hist_row(i, r, width))
    print("\n想再跑一次上面某条：直接敲它的名字（比如 moss zeen），不用先 cd 过去。")
    return 0


def _history_browser(rows, table):
    """方向键浏览 + **回车一键重跑**（V-12）。

    ★ 重画用的是 **Win32 光标定位 + 整行补齐空格**，不用 ANSI 转义：
      实测在开了 VT 的控制台上，Python 的 `\\n` 有可能只下移不回车，
      于是 `\\033[A` 上移之后落在**半行**上、`\\033[K` 也只擦右边 ——
      整个列表就糊成一团（表头重复、行粘在一起）。
    """
    import msvcrt
    out.enable_ansi()                       # 只为配色，定位不靠它
    idx = 0
    block_y = 0

    def paint(redraw):
        nonlocal block_y
        width, height = _term_size()
        inner = width - 2                       # 两侧各留一列余量
        with_args = inner - _HIST_FIXED >= 10
        vh = max(3, min(height - 3, len(rows)))
        top = _scroll_top(idx, len(rows), vh)
        lines = ["  最近启动（已去重 %d 条）" % len(rows),
                 _hist_head(inner, with_args)]
        for k in range(vh):
            j = top + k
            if j < len(rows):
                lines.append(_hist_row(j + 1, rows[j], inner,
                                       ">" if j == idx else " "))
            else:
                lines.append("")
        lines.append("  方向键 选择    回车 重跑    Esc 退出")
        if redraw:
            out.gotoxy(0, block_y)
        else:
            out.clear_screen()
            pos = out.cursor_pos()
            block_y = pos[1] if pos else 0
        out.write_block(lines, width)

    paint(False)
    while True:
        try:
            ch = msvcrt.getwch()
        except KeyboardInterrupt:
            return 0
        except Exception:
            return 1
        if ch in ("\x1b", "q", "Q"):
            out.clear_screen()
            return 0
        if ch in ("\x00", "\xe0"):
            try:
                ch2 = msvcrt.getwch()
            except Exception:
                return 1
            _, height = _term_size()
            vh = max(3, min(height - 3, len(rows)))
            if ch2 in ("H", "A"):
                idx = max(0, idx - 1)
            elif ch2 in ("P", "B"):
                idx = min(len(rows) - 1, idx + 1)
            elif ch2 == "I":
                idx = max(0, idx - vh)
            elif ch2 == "Q":
                idx = min(len(rows) - 1, idx + vh)
            elif ch2 == "G":
                idx = 0
            elif ch2 == "O":
                idx = len(rows) - 1
            paint(True)
            continue
        if ch in ("\r", "\n"):
            # ★ 从历史进入程序：跑完就**彻底退出**，不再回到列表（`V-19`）。
            #   理由：从历史进入等于"再跑一次那个程序"，跟直接敲命令是一回事 ——
            #   程序结束就该回到 shell 提示符，而不是再弹一次列表。
            out.clear_screen()
            return cmd_rerun(idx + 1, table, rows=rows)


def cmd_history(n=None, table=None):
    rows = history.recent_unique()
    if not rows:
        out.print_cyan("[信息] 还没有任何启动记录。")
        return 0
    # 不带条数 + 真在控制台里 -> 交互式浏览（方向键 + 回车重跑）
    # 带了条数、或者输出被重定向 -> 老老实实打印（管道/脚本要的是文本）
    if n is None and table is not None and sys.stdout.isatty():
        return _history_browser(rows, table)
    if n is not None:
        rows = rows[:n]
    return _print_history(rows)


def cmd_rerun(idx, table, rows=None):
    """重跑历史里的第 N 条（序号以**去重后**的列表为准，和界面上看到的一致）。"""
    if rows is None:
        rows = history.recent_unique()
    if not (1 <= idx <= len(rows)):
        out.print_cyan("[错误] 序号超范围（1-%d）。" % len(rows))
        return 1
    return cmd_rerun_record(rows[idx - 1], table)


def cmd_rerun_record(r, table):
    """按一条历史记录重跑。"""
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


def cmd_spec():
    """打印**插件契约**。

    ★ 为什么要做成命令而不是"把契约塞进帮助文本"：
      · 帮助是给人扫的，塞两百行没人看，还会和契约文件漂移成两份；
      · 契约文件随 exe 分发，`moss --spec` 拿到的**永远和当前版本一致**；
      · 对 AI 来说，"跑一条命令拿到全文" 比"猜文件在哪" 可靠得多。
    """
    f = paths.SPEC_FILE
    if not f.is_file():
        out.print_cyan("[错误] 找不到插件契约：%s" % f)
        out.print_cyan("       发行版里它应该在 system/spec/ 下。")
        return 1
    try:
        print(f.read_text(encoding="utf-8"))
    except Exception as e:                                      # noqa: BLE001
        out.print_cyan("[错误] 契约文件读不出来：%s" % e)
        return 1
    return 0


# ---- `moss --new` 生成的骨架。用 __ID__ 占位，避免和代码里的花括号打架 ----
NEW_PKG_JSON = {
    "spec": 1,
    "id": "__ID__",
    "kind": "task",
    "version": "0.1.0",
    "name": {"zh-CN": "新建插件 __ID__"},
    "desc": {"zh-CN": "一句话说明这个插件干什么（会被列在 moss 的包列表里）"},
    "tags": [],
    "aliases": ["__ID__"],
    "runner": "python",
    "entry": {"file": "run.py"},
    "params": [
        {"name": "text", "type": "string", "default": "你好",
         "desc": "示例参数：要重复的内容"},
        {"name": "times", "type": "int", "default": 1, "desc": "示例参数：重复几遍"},
    ],
    "env": {"cwd": "", "elevated": False},
    "capabilities": {"run": ["python"], "net": [], "elevated": False},
    "output": {"mode": "json", "schema": {"text": "string", "times": "int"}},
      "ai": {"expose": False, "risk": "low"},
}

NEW_RUN_PY = '''# -*- coding: utf-8 -*-
"""__ID__ —— 由 `moss --new` 生成的骨架。

三件事，照抄就行：
  1. 参数从 `MOSS_PKG_PARAMS` 读（宿主按 pkg.json 的 params 解析好，以 JSON 注入）
  2. 数据写 `MOSS_PLUGIN_DATA_DIR`（**不要**写自己包目录 —— 升级包会冲掉）
  3. 结构化结果写 `MOSS_RESULT_FILE`（给人看的照常 print）
"""
import json
import os

# ---- 1. 读参数 ----
params = json.loads(os.environ.get("MOSS_PKG_PARAMS") or "{}")
text = str(params.get("text") or "你好")
try:
    times = max(1, min(int(params.get("times") or 1), 100))
except Exception:
    times = 1

# ---- 2. 数据目录（宿主只给路径，目录要自己建）----
data_dir = os.environ.get("MOSS_PLUGIN_DATA_DIR") or "."
os.makedirs(data_dir, exist_ok=True)

# ---- 干活 ----
for _ in range(times):
    print(text)

# ---- 3. 结构化结果 ----
result_file = os.environ.get("MOSS_RESULT_FILE")
if result_file:
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({"text": text, "times": times}, f, ensure_ascii=False)
'''

NEW_AGENT_MD = '''# __ID__ · 给 AI 看的说明

> 这个文件是**给 AI / Agent 读的**（人看 README.md）。写清楚"怎么调、有什么副作用、会怎么失败"，
> 别人才敢让它自动跑。

## 干什么
一句话：……

## 怎么调
```
moss :__ID__ text=你好 times=3
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `text` | string | 否 | 要重复的内容（默认"你好"） |
| `times` | int | 否 | 重复几遍（1-100，默认 1） |

## 返回（结构化）
`MOSS_RESULT_FILE` 里是 JSON：`{"text": ..., "times": ...}`

## 副作用
- 写文件：无 / 写到哪：……
- 联网：无
- 剪贴板：无

## 失败模式
- 参数非法 → 用默认值，退出码 0
'''


def cmd_new(pid, kind="task"):
    """生成一个能跑的插件骨架（`user_data/pkgs/<id>/`）。"""
    pid = str(pid or "").strip().lower()
    if not paths.valid_id(pid):
        out.print_cyan("[错误] id 不合法：'%s'（只允许 %s）" % (pid, paths.ID_RE.pattern))
        out.print_cyan("       规则：小写字母开头，只含小写字母/数字/-/_，不超过 32 字符。")
        return 1
    target = paths.USER_PKGS / pid
    if target.exists():
        out.print_cyan("[错误] 已经存在：%s" % target)
        return 1
    try:
        target.mkdir(parents=True, exist_ok=True)
        pkg = json.loads(json.dumps(NEW_PKG_JSON).replace("__ID__", pid))
        pkg["kind"] = kind
        (target / "pkg.json").write_text(
            json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (target / "run.py").write_text(NEW_RUN_PY.replace("__ID__", pid), encoding="utf-8")
        (target / "AGENT.md").write_text(NEW_AGENT_MD.replace("__ID__", pid), encoding="utf-8")
    except Exception as e:                                      # noqa: BLE001
        out.print_cyan("[错误] 生成失败：%s" % e)
        return 1
    out.print_cyan("生成好了：%s" % target)
    for n in ("pkg.json", "run.py", "AGENT.md"):
        print("     - %s" % n)
    out.print_cyan("下一步：")
    print("     1) 改 pkg.json 里的 name / desc / params")
    print("     2) 改 run.py 干活（参数读 MOSS_PKG_PARAMS，结果写 MOSS_RESULT_FILE）")
    print("     3) 跑：moss :%s 你好 3" % pid)
    # ★ 这一行是给"要界面的包"看的（`V-58` ✅）：默认方案是**网页界面 + ui.embed**，
    #   不是每个包自己 webview.create_window 开窗口 —— 写在这儿，因为"刚新建一个包"
    #   正是最该看到它的时候（给人看，也给 AI 看）。
    print("     4) 要界面？**别自己开窗口** —— 照 system/pkgs/bmi/ 抄一份网页界面，"
          "在 pkg.json 里声明")
    print("        \"ui\": {\"embed\": \"ui/index.html\"}：既能在 moss 的「界面」选项卡里"
          "内嵌跑，也能 moss :%s 自己开窗口" % pid)
    out.print_cyan("契约（字段、环境变量、数据放哪、界面怎么写）：moss --spec")
    return 0


def cmd_rename(name, new_id, table):
    """把一个包改名：**包目录 / 数据目录 / 清单里的 id 一起改**（`D-28`）。

    为什么要做成一条命令，而不是"自己在 pkg.json 里改个 id"：包目录名和 id 本来
    互不相干（`D-27`），手改必然只改一半 —— 目录叫 `a`、id 是 `b`，而界面里有几处
    按 id 拼路径的地方就会认错（进程认不出来、切层按钮不显示）。与其到处兜底，
    不如给一个"改名"的动作，把它俩**一起**改掉。

    ★ 新 id 写成**它现在的 id** 时（`moss --rename my-first first`），这条命令就是
      `D-27` 方案 C 里那个「把目录名对齐成 id」的动作：只改目录名，别的什么都不动
      （id 没变 ⇒ 数据目录不用动、清单不用重写）。
    """
    new_id = str(new_id or "").strip().lower()
    if not paths.valid_id(new_id):
        out.print_cyan("[错误] 新 id 不合法：'%s'（只允许 %s）" % (new_id, paths.ID_RE.pattern))
        return 1
    rec = registry.find_alias(name)
    if not rec:
        out.print_cyan("[错误] 没有这个包：'%s'。直接敲 `moss` 看有哪些。" % name)
        return 1
    old_id = str(rec["id"])
    pkg_dir = Path(rec["dir"])
    same_id = (new_id == old_id)
    # ★ 改成一个"和现在一样"的 id，不是没用的操作 —— `D-27` 方案 C 里它就是
    #   「把目录名对齐成 id」那个动作（目录名允许和 id 不一样，这条是现成的统一动作）。
    if same_id and pkg_dir.name == new_id:
        out.print_cyan("[信息] 名字本来就是 '%s'，目录名也是它，没改。" % old_id)
        return 0
    if not same_id and registry.find_alias(new_id):
        out.print_cyan("[错误] 已经有一个包叫 '%s' 了（换一个名字）。" % new_id)
        return 1

    layer = rec.get("layer")
    state_old = paths.pkg_state_dir(old_id)
    state_new = paths.pkg_state_dir(new_id)
    dir_new = pkg_dir.parent / new_id

    # ---- 先全部检查一遍，能不改就不改（改名最怕改一半）
    if dir_new.exists() and dir_new != pkg_dir:
        out.print_cyan("[错误] 目标目录已经存在：%s" % dir_new)
        return 1
    if not same_id and state_new.exists():
        out.print_cyan("[错误] 目标数据目录已经存在：%s" % state_new)
        return 1

    if same_id:
        out.print_cyan("将要只改目录名：%s → %s（id 不变，还是 '%s'）"
                       % (pkg_dir.name, new_id, old_id))
    else:
        out.print_cyan("将要改名：%s → %s（%s）" % (old_id, new_id,
                     dict((k, c) for k, c, _, _ in _LAYERS).get(layer, layer)))
    print("  %-10s %s" % ("包目录", pkg_dir))
    print("  %-10s %s" % ("        →", dir_new))
    if same_id:
        print("  %-10s （id 没变，数据目录不用动）" % "数据目录")
    elif state_old.is_dir():
        print("  %-10s %s" % ("数据目录", state_old))
        print("  %-10s %s" % ("        →", state_new))
    else:
        print("  %-10s （还没有数据目录，跳过）" % "数据目录")
    if layer == "system":
        out.print_cyan("  注意：这是出厂件，宿主升级时 system/ 会被整体替换 —— "
                       "改出来的名字到那时会变回去，还会多出一份。")

    done = []
    # ① 包目录（失败就整体停下：这一步没成，后面两步做了反而更乱）
    try:
        pkg_dir.rename(dir_new)
        done.append("包目录")
    except OSError as e:
        out.print_cyan("[错误] 包目录改不动：%s" % e)
        out.print_cyan("       可能是它正被占用（包还在跑 / 编辑器开着这个目录里的文件）。")
        return 1
    # ② 数据目录（id 没变就不用动 —— 数据目录是按 id 算的，`D-05`）
    if not same_id and state_old.is_dir():
        try:
            state_old.rename(state_new)
            done.append("数据目录")
        except OSError as e:
            out.print_cyan("[警告] 数据目录没改成：%s" % e)
            out.print_cyan("       包目录已经改了，数据还在 %s —— 手动挪过去即可。" % state_old)
    # ③ 清单里的 id（放最后：它才是"身份"，前两步都成了再落这一笔；id 没变就不用写）
    if not same_id:
        try:
            p = pkg_mod.load(dir_new)
            if p is None:
                raise ValueError("新目录里的 pkg.json 读不出来")
            p["id"] = new_id
            (dir_new / "pkg.json").write_text(
                json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            done.append("清单 id")
        except Exception as e:                                          # noqa: BLE001
            out.print_cyan("[警告] 清单没改成：%s" % e)
            out.print_cyan("       目录已经是 %s，把 pkg.json 里的 id 手动改成 '%s' 即可。"
                           % (dir_new, new_id))
    if same_id:
        out.print_cyan("已对齐：目录名 %s → %s（id 一直是 '%s'）"
                       % (pkg_dir.name, new_id, old_id))
        return 0
    out.print_cyan("已改名：%s → %s（改了 %s）" % (old_id, new_id, "、".join(done)))
    if layer == "user":
        out.print_cyan("       包调用现在要用 `moss :%s`（旧名字不再认识，除非你把它写进 aliases）。"
                       % new_id)
    return 0


def _dir_stats(p):
    """(文件数, 字节数)。"""
    n, size = 0, 0
    try:
        for f in Path(p).rglob("*"):
            if f.is_file():
                n += 1
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return n, size


def _human_size(n):
    if n >= 1048576:
        return "%.1f MB" % (n / 1048576.0)
    if n >= 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%d 字节" % n


def cmd_remove(name, table, assume_yes=False):
    """卸载一个包：**包本体 + 它产生的数据**。

    ★ 这是**永久删除**（不进回收站），所以"先列出要删什么 + 确认"这一步不能省。
    ★ 历史记录里提到它的条目**不动** —— 历史是流水账，不是资产。
    """
    rec = registry.find_alias(name)
    if not rec:
        out.print_cyan("[错误] 没有这个包：'%s'。直接敲 moss 看有哪些。" % name)
        return 1

    pid = rec["id"]
    layer = rec.get("layer")
    cn = dict((k, c) for k, c, _, _ in _LAYERS).get(layer, layer)
    pkg_dir = Path(rec["dir"])
    state_dir = paths.pkg_state_dir(pid)
    shadowed = rec.get("shadowed")          # 它遮住了哪一层的同名包

    targets = [(pkg_dir, "包本体")]
    if state_dir.is_dir():
        targets.append((state_dir, "它的数据"))

    out.conditional_clear_screen()
    out.print_cyan("将要卸载：%s（%s）" % (pid, cn))
    total = 0
    for p, label in targets:
        n, size = _dir_stats(p)
        total += size
        print("  %-8s %s" % (label, p))
        print("  %-8s %d 个文件，%s" % ("", n, _human_size(size)))
    print("  %-8s 合计 %s" % ("", _human_size(total)))
    if shadowed:
        out.print_cyan("  提示：它还遮住了 %s 层的同名包 —— 删掉之后那个会重新生效。"
                       % dict((k, c) for k, c, _, _ in _LAYERS).get(shadowed, shadowed))
    out.print_cyan("注意：这是永久删除（不进回收站），删除后无法恢复。")

    if not assume_yes:
        if not sys.stdin.isatty():
            out.print_cyan("[错误] 非交互环境请显式加 -y 确认。")
            return 1
        try:
            ans = input("确认？ [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in ("y", "yes"):
            out.print_cyan("[取消] 什么都没删。")
            return 0

    errors = []
    for p, label in targets:
        try:
            shutil.rmtree(str(p))
            print("  已删 %s" % p)
        except Exception as e:                                  # noqa: BLE001
            errors.append("%s（%s）：%s" % (label, p, e))

    if errors:
        out.print_cyan("有 %d 处没删干净：" % len(errors))
        for e in errors:
            print("  × %s" % e)
        return 1
    out.print_cyan("已卸载 %s。" % pid)
    return 0


def cmd_resolve(name, table):
    """只看解析结果，不执行。

    输出刻意按"层"分组 —— 因为真正的搜索语义是
    **第一层有候选就不再往上找**（照抄 pa.py:908 的 generate_search_paths 用法）。
    """
    out.print_cyan("[解析] moss %s —— 逐层向上搜索，第一层有候选就停" % name)
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
        print("       注意：只有装了对应 runner 的才算候选（moss --selfcheck 看 runner 表）。")
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

    # 配置：模板与默认值是否一致（防止"加了新键、忘了往带注释的模板里加"）
    print("  配置文件  : %s   %s" % (paths.USER_CONFIG,
                                     "存在" if paths.USER_CONFIG.is_file() else "（首次运行会创建）"))
    tpl = config.template_problems()
    if tpl:
        ok = False
        print("     ✗ 默认模板和默认值不一致（用户会看不到这些键）：")
        for p in tpl:
            print("       - %s" % p)
    else:
        print("     模板与默认值一致 ✔（用户打开 config.toml 能看到全部键 + 说明）")
        print("     裸名归谁  : %s   （path_mode=%r  plugin_mode=%r  no_chdir=%r  后台=%r）"
              % ("**跑包**" if config.bare_owner() == "package" else "找文件（路径调用）",
                 config.path_symbol(), config.plugin_symbol(),
                 config.no_chdir_symbol(), config.detach_symbol()))
    # 「设置」面板（`V-60`）能不能改全：面板清单必须和默认配置的键**一一对应**，
    # 漏一个用户就改不到、多一个点保存就写不进去。两边都查（`settings_problems`）。
    sp = config.settings_problems()
    if sp:
        ok = False
        print("     ✗ 设置面板的清单和默认配置对不上：")
        for p in sp:
            print("       - %s" % p)
    else:
        print("     设置面板  : %d 项，和默认配置一一对应 ✔"
              % sum(len(g["items"]) for g in config.settings_groups()))

    rts = runners_mod.list_runtimes()
    print("  自带运行时: %d 个" % len(rts))
    for r in rts:
        exe = (Path(r["dir"]) / r["interpreter"]) if r["interpreter"] else None
        good = bool(exe and exe.is_file())
        pin = " (默认)" if r["isDefault"] else ""
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
    layers = {}
    for r in recs:
        layers[r.get("layer") or "?"] = layers.get(r.get("layer") or "?", 0) + 1
    for r in recs:
        e = pkg_mod.entry_path(r["pkg"], Path(r["dir"]))
        ic = pkg_mod.icon_path(r["pkg"], Path(r["dir"]))
        print("     - %-12s [%-6s] runner=%-10s 入口=%-12s 图标=%s" % (
            r["id"], r.get("layer") or "?", r["pkg"].get("runner"),
            (e.name if e else ("inline" if pkg_mod.inline_code(r["pkg"]) else "✗ 缺失")),
            (ic.name if ic else "—")))
    # 目录名与 id 不一致（`D-27` 方案 C）：**不是错**，只是给你看一眼 —— 想统一的话
    # 有一条现成的动作（把新 id 写成它自己的 id）。一致时不打任何字，免得变成噪音。
    odd = [(registry.dir_of(r), r["id"]) for r in recs if registry.dir_mismatch(r)]
    if odd:
        print("  目录名≠id : %d 个 —— %s"
              % (len(odd), "；".join("%s（id=%s）" % (d, i) for d, i in odd)))
        print("              想统一：moss --rename <id> <id>（只改目录名，数据不动）")
    # 图标盘点（`F-29`）：有图标几个、谁没有、谁"声明了却读不到"（后者是真问题）
    have = [r["id"] for r in recs if pkg_mod.icon_path(r["pkg"], Path(r["dir"]))]
    lack = [r["id"] for r in recs if not pkg_mod.icon_path(r["pkg"], Path(r["dir"]))]
    print("  图标      : %d/%d 个包有图标%s"
          % (len(have), len(recs), ("；没有：" + "、".join(lack)) if lack else ""))
    for r in recs:
        prob = pkg_mod.icon_problem(r["pkg"], Path(r["dir"]))
        if prob:
            ok = False
            print("     ✗ %s: %s" % (r["id"], prob))
    # ★ 必须把"层"打出来：不然根本分不清哪些会随发行版发给用户
    #   （`system` = 出厂件，随 exe 分发；`user` = 本地安装的 / 商店装的，打包时排除）
    cd_ok, cd_why = shell.console_available()
    who = shell.parent_shell()
    print("  cd 注入   : %s   （%s）" % ("可用" if cd_ok else "✗ 不可用", cd_why))
    print("  父 shell  : %s   （沿父进程链: %s）"
          % (who or "✗ 没认出来",
             " ← ".join("%s" % n for n, _ in shell.parent_chain()[:5])))
    # ★ 启动方式（`G-19` ✅）：这一行决定"不带参数时会发生什么"
    print("  启动方式  : %s" % shell.launch_kind())
    print("              → 现在敲 moss（不带参数）会%s"
          % ("开界面" if shell.gui_mode() else "打用法 + 包列表"))
    ui_ok, ui_why = ui.available(table)
    print("  界面      : %s   （%s）" % ("可用" if ui_ok else "✗ 不可用", ui_why))
    print("              → 界面要跑包时调这个：%s" % " ".join(ui.host_cmd()))
    if not ui_ok:
        ok = False
    for label, p, has in shell.installed_state():
        print("  %-9s: %s   （%s）" % (label, "已装包装函数" if has else "未装包装函数", p))
    print("            装了包装函数的话，moss cd 在屏幕上不留任何回显；"
          "没装则用注入（命令会显示出来）")
    print("=" * 60)
    out.print_cyan("结论: %s" % ("自检通过" if ok else "✗ 自检失败"))
    return 0 if ok else 1


# ---------------------------------------------------------------- 界面
def cmd_ui(args):
    """开宿主界面（`G-19` ✅）。

    入口有三个，都落到这里：
      · `moss ui`（终端里显式要界面）
      · 双击 / 快捷方式 / 快速启动栏启动（没有控制台 → 只能开界面）
      · 以后常驻贴边面板（`U-10` ⬜）也走它
    界面本体在 `system/ui/`，用自带运行时跑 —— **不编进 exe**，改界面不用重新打包（`K-10`）。
    """
    return ui.launch(args)


# ---------------------------------------------------------------- cd
def handle_cd(target_str, print_only=False):
    """智能找目录并切换。

    ★ 三条路，区别在**谁来执行那条 cd**（详见 core/shell.py 的模块说明）：

      · `print_only=True`（**由环境变量 `MOSS_CD_PRINT=1` 触发**，包装函数设的就是它；
        `--print` 这个开关 2026-09-27 已去掉）：**只把绝对路径打到
        stdout**，别的什么都不打印。给 PowerShell 的包装函数用 —— 它拿到路径
        自己 `Set-Location`，于是**屏幕上没有任何回显**。

      · 否则：把 `Set-Location -LiteralPath '...'`（cmd 里是 `cd /d "..."`）
        当成**真键盘记录**注入当前控制台输入缓冲区，父 shell 读到就自己执行。
        零配置、不看窗口焦点、不碰剪贴板、中文不用旁路。
        ⚠️ 代价：那条命令会**显示在屏幕上**并进历史（这是已知取舍，E-25）。

      · 认不出父 shell / 没有真控制台：打印路径 + 提示装包装函数，**不猜不乱试**。

    ★ 为什么不能直接 chdir：**子进程改不了父 shell 的工作目录**，这是进程隔离，
      不是实现偷懒。所以只能"让 shell 自己执行"。
    """
    target_path = resolve.find_dir(target_str, Path.cwd())

    if not target_path:
        msg = "未找到目标目录: %s" % target_str
        if print_only:
            # 打印模式下错误必须走 stderr —— stdout 是给调用方捕获路径用的
            print("[错误] %s" % msg, file=sys.stderr)
            return 1
        out.conditional_clear_screen()
        out.print_cyan("[错误] %s" % msg)
        return 1

    abs_path = str(target_path.resolve())

    if print_only:
        # ★ 只吐这一行。调用方是 `$p = & moss cd @args`，
        #   多打一行横幅就会把路径污染掉（用户拿到的会是 "[执行] ..." 之类）。
        print(abs_path)
        return 0

    who = shell.parent_shell()
    if who is None:
        out.print_cyan("[错误] 认不出当前是哪个 shell（父进程链里既没有 PowerShell 也没有 cmd）。")
        out.print_cyan("目录是: %s" % abs_path)
        out.print_cyan("想彻底解决（而且屏幕上不留回显）: moss cd --install")
        return 1

    ok, why = shell.inject(shell.cd_command(who, abs_path))
    if not ok:
        out.print_cyan("[错误] 注入按键失败: %s" % why)
        out.print_cyan("目录是: %s" % abs_path)
        out.print_cyan("想彻底解决（而且屏幕上不留回显）: moss cd --install")
        return 1

    # 成功时**刻意什么都不打印**：那条命令本来就由 shell 显示在屏幕上（E-25 的已知代价），
    # 再打一行 "[切换目录] ..." 只是重复噪声。
    return 0


def cmd_cd_install():
    """把 `function moss` 写进 PowerShell 的 $PROFILE（零回显走这条路）。"""
    out.conditional_clear_screen()
    out.print_cyan("把 moss 的 cd 包装函数写进 PowerShell 配置（屏幕上不留回显）")
    results = shell.install_cd()
    bad = 0
    for label, path, result, err in results:
        flag = "✗" if err else "·"
        if err:
            bad += 1
        print("  %s %-22s %s" % (flag, label, result))
        print("      %s" % path)
    if bad:
        out.print_cyan("有 %d 个文件没写成功，上面有原因。" % bad)
        return 1
    out.print_cyan("装好了。新开一个 PowerShell 窗口才生效（老窗口执行 . $PROFILE 也行）。")
    out.print_cyan("之后 moss cd <目标> 屏幕上不会出现任何命令；"
                   "cmd 窗口没有等价物，仍走注入。")
    out.print_cyan("不想要了: moss cd --uninstall")
    return 0


def cmd_cd_uninstall():
    """把包装函数从 $PROFILE 里删掉，cd 回到"注入按键"。"""
    out.conditional_clear_screen()
    out.print_cyan("从 PowerShell 配置里删掉 cd 包装函数")
    results = shell.uninstall_cd()
    bad = 0
    removed = 0
    for label, path, result, err in results:
        if err:
            bad += 1
        if result == "已移除":
            removed += 1
        print("  %s %-22s %s" % ("✗" if err else "·", label, result))
        print("      %s" % path)
    if bad:
        out.print_cyan("有 %d 个文件没弄成功，上面有原因。" % bad)
        return 1
    if not removed:
        out.print_cyan("这两个配置文件里本来就没装过包装函数，没动它们。")
        return 0
    out.print_cyan("已移除。新开窗口后 moss cd 回到注入方式（命令会显示在屏幕上）。")
    return 0


# ---------------------------------------------------------------- 主入口
def main(argv):
    config.load()

    # 输入法把模式前缀打成全角时先还原（照抄 pa.py:857-859）
    if argv:
        argv = [config.restore_prefix(argv[0])] + list(argv[1:])

    paths.ensure_user_dirs()

    # 内建订阅者：历史（不是钩子！见 T-05）
    # ★ 两次记账：启动时先记一条，跑完再补一条（长驻程序跑着的时候也得看得见）
    events.BUS.on("before:run", history.on_before_run, name="history-start")
    events.BUS.on("after:run", history.on_after_run, name="history")

    table = runners_mod.load()

    # ---- 帮助（照抄 pa.py:861-866：先文档再列表） ----
    if not argv or argv[0] in ("-h", "--help", "help"):
        # ★ 不带参数时先看"程序是怎么被启动的"（`G-19` ✅）：
        #   双击 / 快捷方式 / 快速启动栏启动 → 没有控制台 → 打用法没人看得见，
        #   直接开界面。终端里敲 → 照旧打用法 + 包列表。
        if not argv and shell.gui_mode():
            return cmd_ui([])
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

    # ---- ui：宿主界面（`G-19` ✅；和 `cd` 一样是**宿主保留词**） ----
    # 保留字的理由：`moss ui` 要能和"找文件/跑包"区分开。`cd` 已经是这么做的
    # 先例；真要跑一个叫 ui 的包，用 `moss :ui`，路径调用用 `moss ./ui`。
    if first.lower() in ("ui", "--ui"):
        return cmd_ui(rest)

    # ---- cd（照抄 pa.py:876-881） ----
    if first.lower() == 'cd':
        if '--print' in rest:
            # 手敲 `--print` 已不再支持（零回显那条路留给**环境变量**）：
            # MOSS_CD_PRINT=1（`moss cd --install` 装好的包装函数就是这么调的），
            # 手动敲 `--print` 没有额外好处 —— 所以这里明说一句，别让它悄悄变成"目标路径"。
            out.print_cyan("[提示] moss cd --print 已经去掉了：")
            out.print_cyan("       零回显是靠包装函数（moss cd --install）设 MOSS_CD_PRINT=1 实现的，"
                           "不需要手动加开关。")
            out.print_cyan("       只想看解析出的路径：moss --resolve <名字>。")
            return 1
        args = list(rest)
        # `--install` / `--uninstall`：装/卸 PowerShell 的包装函数（③，零回显）
        if args and args[0] in ('--install', '--uninstall'):
            return cmd_cd_install() if args[0] == '--install' else cmd_cd_uninstall()
        # 环境变量 MOSS_CD_PRINT=1 → 只吐路径，不做注入。
        # 这条路是给包装函数用的（见 handle_cd 的说明）：包装函数设好变量再调 moss，
        # moss 就只输出路径让 shell 自己 cd。
        print_only = os.environ.get('MOSS_CD_PRINT') == '1'
        if args:
            return handle_cd(args[0], print_only=print_only)
        out.print_cyan("[错误] 'cd' 命令需要一个目标路径。用法: moss cd <目标>")
        out.print_cyan("       （想屏幕上不留回显: moss cd --install）")
        return 1

    # ---- moss 自己的选项 ----
    if first in ("--remove", "--uninstall"):
        args = [a for a in rest if a not in ("-y", "--yes")]
        yes = len(args) != len(rest)
        if not args:
            out.print_cyan("[错误] --remove 需要一个包名（别名或 id）。直接敲 moss 看有哪些。")
            return 1
        return cmd_remove(args[0], table, assume_yes=yes)
    if first == "--spec":
        return cmd_spec()
    if first == "--ui-payload":
        # 界面用的那份数据（JSON），**只有 JSON、没有横幅** —— 界面拿它刷新包列表。
        # 为什么要有：宿主在启动时把 payload 写成一个文件交给界面，那份文件是**快照**；
        # 新建 / 卸载一个包之后界面再读它还是旧的（列表里看不到新包，详情也拿不到目录）。
        # 所以界面需要一条"重新问一遍"的路 —— 这条就是。不给用户用，USAGE 里也不列。
        import json as _json
        from . import ui as _ui
        sys.stdout.write(_json.dumps(_ui.build_payload(), ensure_ascii=False))
        sys.stdout.flush()
        return 0
    if first == "--settings":
        # 界面那颗齿轮要读的东西（JSON，只有 JSON、没有横幅）。
        # 为什么走命令行而不是"界面自己读文件"：界面跑在自带运行时里、**不 import core**
        # （core 编在 exe 里，磁盘上没这个目录），而且那份 TOML 的解析规则、默认值、
        # 「什么算写错了」的判断全在 core 里 —— 界面自己再实现一遍就是两处真相。
        # 和 `--ui-payload`（`V-31`）同一条路。不给用户用，USAGE 里也不列。
        import json as _json
        sys.stdout.write(_json.dumps(config.settings_payload(), ensure_ascii=False))
        sys.stdout.flush()
        return 0
    if first == "--settings-set":
        # 参数是**一份 JSON 对象**：`{"symbols.plugin_mode": ":", "output.pid": true}`。
        # 只改这些键的值，注释和排版一字不动（`config.set_values`）。
        import json as _json
        if not rest:
            out.print_cyan("[错误] --settings-set 需要一份 JSON。")
            return 1
        try:
            pairs = _json.loads(rest[0])
        except ValueError as e:
            out.print_cyan("[错误] --settings-set 的参数不是 JSON：%s" % e)
            return 1
        if not isinstance(pairs, dict):
            out.print_cyan("[错误] --settings-set 要的是一个 JSON 对象（键 = 段.键）。")
            return 1
        r = config.set_values(pairs)
        sys.stdout.write(_json.dumps(r, ensure_ascii=False))
        sys.stdout.flush()
        return 0 if r.get("ok") else 1
    if first == "--rename":
        if len(rest) < 2:
            out.print_cyan("[错误] --rename 需要两个名字：旧的（id 或别名）和新的 id。")
            out.print_cyan("       例：moss --rename img pictures")
            return 1
        return cmd_rename(rest[0], rest[1], table)
    if first == "--new":
        if not rest:
            out.print_cyan("[错误] --new 需要一个包 id。例：moss --new my-first")
            return 1
        return cmd_new(rest[0])
    if first == "--selfcheck":
        return cmd_selfcheck(table)
    if first == "--history":
        n = None
        if rest:
            try:
                n = max(1, int(rest[0]))
            except ValueError:
                n = None
        return cmd_history(n, table)
    if first == "--resolve":
        if not rest:
            out.print_cyan("[错误] --resolve 需要一个名字。")
            return 1
        return cmd_resolve(rest[0], table)

    # 认不出来的选项给句人话，别掉进"找以 --xxx 开头的可运行目标"那种错误里
    # （`--list` / `--rerun` 已经去掉：前者 `moss` 本来就会列包，后者改由
    #   历史列表回车、或直接敲名字来做）
    if first.startswith("-"):
        out.print_cyan("[错误] 不认识的选项：%s" % first)
        out.print_cyan("       直接敲 moss 看用法和包列表。")
        return 1

    # ---- 分派到两个命名空间（`CL-12`：显式符号优先，裸名归谁由配置决定）----
    psym = config.plugin_symbol()
    psym_path = config.path_symbol()
    ncsym = config.no_chdir_symbol()

    # ① 带显式前缀的：前缀说了算（空串 = "这一类不带前缀"，不算前缀）
    if psym and first.startswith(psym):
        return _run_package(first.lstrip(psym).strip(), rest, table, detach)
    if psym_path and first.startswith(psym_path):
        return _run_path(first.lstrip(psym_path), rest, table, detach, change_dir=True)
    if ncsym and first.startswith(ncsym):
        return _run_path(first.lstrip(ncsym), rest, table, detach, change_dir=False)

    # ② 裸名（没带任何前缀）：归谁看配置 —— 谁的前缀是空串，裸名就归谁。
    #   默认 `path_mode = ""` → 裸名=路径调用（和以前一模一样）；
    #   把 `plugin_mode` 留空、`path_mode` 填个符号，就变成"裸名=跑包"（非程序员更顺手）。
    if config.bare_owner() == "package":
        rc = _run_package(first, rest, table, detach, quiet_missing=True)
        if rc is not None:
            return rc
        # 包里没有这个名字 → 继续按路径找（同一个名字两种身份，谁先命中算谁）
    return _run_path(first, rest, table, detach, change_dir=True)


def _run_package(alias, rest, table, detach, quiet_missing=False):
    """跑一个装好的包。`quiet_missing=True` 时"没这个包"返回 None（交给调用方回退路径）。

    `alias` 为空 = 光敲了一个前缀符号（`moss :`）：交互式选择器已经去掉
    （`H-11`），所以这里直接告诉用户该怎么写。
    """
    if not alias:
        psym = config.plugin_symbol()
        out.print_cyan("[错误] '%s' 后面要写包名。例：moss %simg" % (psym, psym))
        out.print_cyan("       直接敲 moss 看有哪些包。")
        return 1
    rec = registry.find_alias(alias)
    if not rec:
        if quiet_missing:
            return None
        out.print_cyan("[错误] 没有这个包：'%s'。直接敲 moss 看有哪些包。" % alias)
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


def _run_path(name, rest, table, detach, change_dir):
    """路径调用：在 cwd 往上找以 `name` 开头的可运行目标（`E-23` 判定链）。

    找不到时**再查一次历史**（`V-20`：人在别的目录，凭记忆敲 `moss zeen` 想进上次那个）；
    还是没有，就报错 —— 并且**顺带提示有没有同名的包**（`CL-12`：这是最省事的发现性改进，
    "moss img 少打个冒号"的人一眼就知道该怎么办）。
    """
    cand, why = resolve.find(name, Path.cwd(), table)
    if cand is None:
        if why == "用户取消":
            out.print_cyan("[取消] 已退出。")
            return 130
        rec = history.find_recent(name)
        if rec is not None:
            out.print_cyan("[历史] 文件系统里没有 '%s'，改用最近一次记录：%s  (cwd=%s)"
                           % (name, _hist_name(rec), rec.get("cwd") or "-"))
            return cmd_rerun_record(rec, table)
        out.print_cyan("[错误] 在 %s 及上层没找到以 '%s' 开头的可运行目标。"
                       % (Path.cwd(), name))
        print("       （只在装了对应 runner 的情况下才算候选：用 moss --resolve %s 看细节）"
              % name)
        # ★ 同名包提示：默认档位是"裸名=路径"，所以想跑包的人经常会漏掉前缀
        if registry.find_alias(name):
            psym = config.plugin_symbol()
            hint = ("%s%s" % (psym, name)) if psym else name
            out.print_cyan("[提示] 有个同名的包 '%s'：要跑它就敲 moss %s" % (name, hint))
        return 1

    out.print_cyan("[选中] %s  ← %s" % (cand["path"], why))
    inv = build_path_inv(cand, rest, via="cli", change_dir=change_dir)
    inv, err = _fill_interpreter(inv, table)
    if err:
        out.print_cyan("[错误] %s" % err)
        return 1
    return engine.run(inv, table, detach=detach)
