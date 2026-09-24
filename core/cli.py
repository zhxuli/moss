# -*- coding: utf-8 -*-
"""CLI 分发。

输入分三类（§21.2 第 1 步 / §21.5）：
    moss :hello ...   包调用   —— 别名解析
    moss --list 等    内置命令
    moss m            路径调用 —— 路径解析（§21）

★ 内建订阅者在这里挂上（`T-05`）：历史服务订阅 `after:run`。
  它是**内核行为**，不是钩子 —— 审计不能依赖一个可以被禁用/写坏的东西。
"""
import json
import os
import sys
from pathlib import Path

from . import config, engine, events, history, paths, pkg as pkg_mod, registry, resolve, runners as runners_mod

USAGE = """moss —— 多语言启动器

用法:
  moss <名字> [参数...]        在当前目录（及向上几层）找匹配的脚本并运行
                               例: moss m      → 找 main.py / main.go / main.html
                               （多语言同时是候选，靠可用性 + 项目标记 + 记忆消歧）
  moss :<别名> [参数...]       运行一个已安装的包
                               例: moss :hello who=moss times=2

  moss --list                  列出已安装的包
  moss --history [条数]        看最近的启动记录（默认 10 条）
  moss --rerun <序号>          重跑历史里的第 N 条（不用先 cd 回去）
  moss --resolve <名字>        只看解析结果，不执行
  moss --selfcheck             自检：安装根 / runner 表 / 包目录是否可读
  moss -h | --help             本帮助

说明:
  · 参数写法二选一：位置参数（按 params 顺序）或 key=value
  · 环境变量 MOSS_HOME / MOSS_PLUGIN_DATA_DIR 会注入给子进程
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
    """把命令行参数映射到包声明的 params 上（类型化参数，F-08）。"""
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
        if pi < len(positional):
            params[n] = _coerce(p, positional[pi])
            pi += 1

    if pi < len(positional) and pkg.get("entry", {}).get("file"):
        pass  # 多余的位置参数忽略；M1 不做"透传所有参数"
    return params


# ---------------------------------------------------------------- 调用构造
def build_pkg_inv(rec, params, via="cli"):
    pkg = rec["pkg"]
    pkg_dir = Path(rec["dir"])
    entry = pkg_mod.entry_path(pkg, pkg_dir)
    if entry is None and not pkg_mod.inline_code(pkg):
        return None, "包 '%s' 找不到入口文件（entry.file 指向的文件不存在）" % pkg["id"]

    spec = runners_mod.load().get(pkg.get("runner")) or {}
    env = pkg.get("env") or {}
    cwd = env.get("cwd") or os.getcwd()

    inv = {
        "kind": "pkg",
        "id": pkg["id"],
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
    return inv, None


def build_path_inv(cand, args, via="cli"):
    """路径调用：target = 找到的文件，cwd = 它所在的目录（照抄 pa.py 的 change_dir=True 语义）。"""
    return {
        "kind": "path",
        "id": None,
        "runner": cand["runner"],
        "target": str(cand["path"]),
        "cwd": str(cand["base"]),
        "interpreter": cand["probe"].get("interpreter"),
        "venv": cand["probe"].get("venv"),
        "params": {},
        "args": list(args),
        "via": via,
    }


def _fill_interpreter(inv, table):
    """给调用补上解释器（跑之前或重跑时都可能需要）。"""
    if inv.get("interpreter"):
        return inv
    spec = table.get(inv.get("runner")) or {}
    probe = runners_mod.probe(inv.get("runner"), spec, {
        "cwd": inv.get("cwd") or os.getcwd(),
        "home": str(paths.HOME),
        "entry": inv.get("target") or "",
    })
    inv["interpreter"] = probe.get("interpreter")
    inv["venv"] = probe.get("venv")
    return inv


# ---------------------------------------------------------------- 子命令
def cmd_list(table):
    recs = registry.scan_all()
    if not recs:
        print("[信息] 还没有安装任何包。包放在 %s" % paths.SYSTEM_PKGS)
        return 0
    print("已安装的包（%d）：" % len(recs))
    print("  %-12s %-8s %-6s %-7s %s" % ("别名", "类型", "版本", "层", "说明"))
    print("  " + "-" * 66)
    for r in recs:
        p = r["pkg"]
        alias = ",".join(p.get("aliases") or []) or p["id"]
        layer = r["layer"] + ("→遮蔽" + r["shadowed"] if r.get("shadowed") else "")
        print("  %-12s %-8s %-6s %-7s %s" % (
            alias[:12], p.get("kind", ""), str(p.get("version", ""))[:6], layer,
            str(p.get("desc", ""))[:34]))
    return 0


def cmd_history(n):
    rows = history.recent(n)
    if not rows:
        print("[信息] 还没有任何启动记录。")
        return 0
    print("最近 %d 条启动记录：" % len(rows))
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
        print("[错误] 序号超范围（1-%d）。" % len(rows))
        return 1
    r = rows[idx - 1]
    print("[重跑] 来自历史：%s" % (r.get("id") or r.get("target")))

    if r.get("kind") == "pkg" and r.get("id"):
        rec = registry.find_alias(r["id"])
        if not rec:
            print("[错误] 包 '%s' 已经不在了。" % r["id"])
            return 1
        inv, err = build_pkg_inv(rec, r.get("params") or {}, via="history")
        if err:
            print("[错误] %s" % err)
            return 1
    else:
        target = r.get("target")
        cwd = r.get("cwd") or os.getcwd()
        if not target or not os.path.isfile(target):
            print("[错误] 目标已经不在了：%s" % target)
            return 1
        spec = table.get(r.get("runner")) or {}
        inv = {
            "kind": "path", "id": None, "runner": r.get("runner"),
            "target": target, "cwd": cwd,
            "params": {}, "args": r.get("args") or [], "via": "history",
        }
        _fill_interpreter(inv, table)
    return engine.run(inv, table)


def cmd_resolve(name, table):
    """只看解析结果，不执行。

    输出刻意按"层"分组 —— 因为真正的搜索语义是
    **第一层有候选就不再往上找**（照抄 pa.py:908 的 generate_search_paths 用法）。
    """
    print("[解析] `moss %s` —— 逐层向上搜索，第一层有候选就停" % name)
    depth = config.max_parent_depth()
    hit_base, hit_cands = None, []
    for base in resolve.search_bases(Path.cwd(), depth):
        cands = resolve.collect(base, name, table, depth)
        if cands and hit_base is None:
            hit_base, hit_cands = base, cands
        flag = "  ★ 命中，停在这一层" if (cands and base == hit_base) else ""
        print("  %s   候选 %d 个%s" % (base, len(cands), flag))
        for c in cands:
            marks = ("  项目标记: " + ",".join(c["marker_hits"])) if c["marker_hits"] else ""
            print("      %-16s runner=%-10s %s%s"
                  % (c["path"].name, c["runner"], c["probe"].get("why"), marks))
        if hit_base is not None:
            break

    if hit_base is None:
        print("\n[结论] 在 %s 及向上 %d 层内没找到以 '%s' 开头的可运行目标。" % (Path.cwd(), depth, name))
        print("       注意：只有装了对应 runner 的才算候选（`moss --selfcheck` 看 runner 表）。")
        return 1

    try:
        cand, why = resolve.disambiguate(hit_cands, hit_base, name, depth)
    except resolve.Aborted:
        print("\n[结论] 需要你选择，但当前不是交互环境（或你取消了）。")
        return 1
    print("\n[结论] 选中 %s\n       依据：%s" % (cand["path"], why))
    return 0


def cmd_selfcheck(table):
    """打包后烟测用（S-05）：把关键路径全部读一遍。"""
    ok = True
    print("moss 自检")
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
    recs = registry.scan_all()
    print("  包        : %d 个" % len(recs))
    for r in recs:
        e = pkg_mod.entry_path(r["pkg"], Path(r["dir"]))
        print("     - %-12s runner=%-10s 入口=%s" % (
            r["id"], r["pkg"].get("runner"),
            (e.name if e else ("inline" if pkg_mod.inline_code(r["pkg"]) else "✗ 缺失"))))
    print("=" * 60)
    print("结论: %s" % ("✅ 自检通过" if ok else "✗ 自检失败"))
    return 0 if ok else 1


# ---------------------------------------------------------------- 主入口
def main(argv):
    config.load()

    # 输入法把模式前缀打成全角时先还原（照抄 pa.py:859）
    if argv:
        argv = [config.restore_prefix(argv[0])] + list(argv[1:])

    paths.ensure_user_dirs()

    # 内建订阅者：历史（不是钩子！见 T-05）
    events.BUS.on("after:run", history.on_after_run, name="history")

    table = runners_mod.load()
    reg = registry.load()
    registry.sync(reg)

    if not argv:
        print(USAGE)
        return cmd_list(table)

    first = argv[0]
    rest = argv[1:]

    if first in ("-h", "--help", "help"):
        print(USAGE)
        return 0
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
            print("[错误] --rerun 需要一个序号。先看 `moss --history`。")
            return 1
        try:
            return cmd_rerun(int(rest[0]), table)
        except ValueError:
            print("[错误] --rerun 的序号必须是数字。")
            return 1
    if first == "--resolve":
        if not rest:
            print("[错误] --resolve 需要一个名字。")
            return 1
        return cmd_resolve(rest[0], table)

    # ---- 包调用 ----
    symbol = config.plugin_symbol()
    if first.startswith(symbol):
        alias = first.lstrip(symbol).strip()
        if not alias:
            print("[错误] %s 后面要跟包别名。用 `moss --list` 看有哪些。" % symbol)
            return 1
        rec = registry.find_alias(alias)
        if not rec:
            print("[错误] 没有这个包：'%s'。用 `moss --list` 看有哪些。" % alias)
            return 1
        if not registry.is_enabled(reg, rec["id"]):
            print("[错误] 包 '%s' 已被禁用。" % rec["id"])
            return 1
        params = parse_params(rec["pkg"], rest)
        inv, err = build_pkg_inv(rec, params, via="cli")
        if err:
            print("[错误] %s" % err)
            return 1
        _fill_interpreter(inv, table)
        return engine.run(inv, table)

    # ---- 路径调用 ----
    cand, why = resolve.find(first, Path.cwd(), table)
    if cand is None:
        if why == "用户取消":
            print("[取消] 已退出。")
            return 130
        print("[错误] 在 %s 及上层没找到以 '%s' 开头的可运行目标。" % (Path.cwd(), first))
        print("       （只在装了对应 runner 的情况下才算候选：用 `moss --resolve %s` 看细节）" % first)
        return 1
    print("[选中] %s  ← %s" % (cand["path"], why))
    inv = build_path_inv(cand, rest, via="cli")
    return engine.run(inv, table)
