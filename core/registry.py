# -*- coding: utf-8 -*-
"""包扫描：**磁盘是唯一真相**。

本模块只做一件事 —— 把两层的包扫出来：

    system/pkgs         只读出厂包（随 exe 分发）
    user_data/pkgs      用户自己写的 / 从商店装的

★ 没有 `registry.json` 了（`D-09` ❌ / `D-22` ✅，2026-09-27）。
  原来那份"安装状态账本"每次启动都重写一遍，而它里面的字段
  （`layer` / `version` / `origin` / `seenAt` / `lastStart` / `host`）
  **全是只写不读**，唯一被读的 `state` 又只有"禁用"一个用途 —— 而你不需要禁用。
  于是它成了一张命中率为 0 的缓存表：要么每次刷新（等于没缓存），
  要么不刷新（就会和磁盘不同步）。两条路都指向同一个结论：**别记账，现扫。**
  实测（200 个包）：全扫 54 ms，直探一个目录 0.28 ms。

遮蔽规则（H-08）：**用户层同名包遮蔽系统层，系统层原件保留**，不是替换。
"""
import sys

from . import paths, pkg as pkg_mod


def _scan_layer(base_dir, layer):
    """扫一层目录下的所有包。"""
    found = []
    if not base_dir.is_dir():
        return found
    for d in sorted(base_dir.iterdir()):
        if not d.is_dir():
            continue
        p = pkg_mod.load(d)
        if p is None:
            # ★ 目录在、清单读不出来，**绝不能静默跳过**。
            #   静默跳过的后果是：包从扫描结果里消失，用户看到"包不见了"，
            #   而真正的原因是自己那个 pkg.json 有个 JSON 语法错。
            #   这个坑真踩过（PowerShell 把 pkg.json 写坏 → img"消失"，查了半天）。
            if (d / "pkg.json").is_file():
                print("[警告] %s 的 pkg.json 解析失败（JSON 语法错误？），"
                      "这个包会被当成不存在。" % d, file=sys.stderr)
            continue
        # ★ id 不合法也要大声报出来（`F-26`）：它要当目录名用（`state/<id>/`），
        #   放过去的话数据会被写到奇怪的地方；宁可这个包不出现，也不能带病跑。
        if not paths.valid_id(p.get("id")):
            print("[警告] %s 的 id '%s' 不合法（只允许 %s），这个包会被当成不存在。"
                  % (d, p.get("id"), paths.ID_RE.pattern), file=sys.stderr)
            continue
        pkg_mod.display_name(p)
        found.append({"id": p["id"], "layer": layer, "dir": d, "pkg": p})
    return found


def layers():
    """扫描顺序 = 优先级**从低到高**（后扫的遮蔽先扫的）。

    层优先级：user > system
      · `system/pkgs` 是要随程序分发给所有用户的出厂包（只读，升级时整体替换）。
      · `user_data/pkgs` 是用户自己写的 / 从商店装的包 —— 同名时遮蔽 system。
      （2026-09-27 第 36 版：原来的第三层 `dev/` 已删，见 `D-16` 否决记录。）
    """
    return [(paths.SYSTEM_PKGS, "system"), (paths.USER_PKGS, "user")]


def scan_all():
    """把所有层的包扫出来，同名的后扫的遮蔽先扫的（H-08 遮蔽语义）。

    ★ 这是"现扫"：不查任何缓存。包列表、别名解析、`--selfcheck` 都走它。
      要快就快在**别每次都调它**（`moss :img` 这种精确名字应该直探目录），
      而不是拿一份每次启动都要刷新的表去省它。
    """
    by_id = {}
    for base, layer in layers():
        for rec in _scan_layer(base, layer):
            if rec["id"] in by_id:
                rec["shadowed"] = by_id[rec["id"]]["layer"]
            by_id[rec["id"]] = rec
    return sorted(by_id.values(), key=lambda r: r["id"])


def find_alias(alias):
    """按名字找包（id 或别名），用户层优先（遮蔽语义）。

    注意：实现上是**先全扫、再线性找**（`scan_all()` 在循环外求值），
    所以"找到就返回"只省下几次字符串比较，清单是一个不少读的 ——
    精确 id 和"查不存在的名字"代价完全一样（实测 200 包时都是 54 ms）。
    要省这一步得先按目录名直探两层，那是 `CL-11`（还没做）。
    """
    alias = (alias or "").strip().lower()
    if not alias:
        return None
    for rec in scan_all():
        names = [str(a).lower() for a in (rec["pkg"].get("aliases") or [])]
        if alias in names or alias == rec["id"].lower():
            return rec
    return None
