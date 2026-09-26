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


def _probe_by_dirname(name):
    """**按目录名直接取一个包**，不读其它任何目录的清单。返回 None = 没探到。

    这是 `CL-11` 的快路径：`moss :img` 这种最常见的情况，根本用不着把两层的
    清单全读一遍。实测（临时造 200 个包）：全扫 = 读 210 个清单 / 54 ms，
    直探 = 读 1 个清单 / 0.28 ms。

    为什么是这么写的 —— 三个坑，都得先想清楚：
      ① **顺序必须"用户层优先"**。`layers()` 是按"从低到高"返回的
         （system → user，后扫的遮蔽先扫的）。直探要是照抄那个顺序，
         `moss :img` 会先命中 system 层的 img，用户放在 user 层的同名包
         永远轮不到 —— `H-08`「用户层遮蔽系统层」当场失效。
         所以这里 `reversed()`，改成 user → system。
      ② **命中后要确认"这个名字真的是它的 id 或别名之一"**。约定上目录名 == 包 id，
         但**不强制**（id 是从 `pkg.json` 里读的，`F-26` 只管格式、不管目录名）。
         不确认就会出现"按目录名能跑、按名字找不到"的前后不一致，
         那种 bug 比"慢"难查得多。确认之后语义和全扫**完全一致**，只是少读了清单。
         顺带好处：目录名恰好就写成别名的包（少见）也会一起变快。
      ③ **坏清单不在这里处理**。`pkg.load()` 读不出来（JSON 语法错）或 id 不合法时
         直接放弃这一层，交给后面的全扫 —— 让 `_scan_layer` 去打那条真正的告警
         （「pkg.json 解析失败」/「id 不合法」）。在这里再实现一遍告警只会重复，
         而且会打两次。
    """
    if not name:
        return None
    for base, layer in reversed(layers()):          # ① user 层先试（见上）
        d = base / name                             # 直接拿名字当目录名试
        if not d.is_dir():
            continue                                # 这层没有同名目录，试下一层
        p = pkg_mod.load(d)                         # ★ 只读这一个清单
        if p is None or not paths.valid_id(p.get("id")):
            continue                                # ③ 坏了 / id 非法 → 交给全扫去报
        pkg_mod.display_name(p)                     # 和 _scan_layer 一致：多语言的 name/desc 要摊平
        pid = str(p.get("id") or "").lower()
        aliases = [str(x).lower() for x in (p.get("aliases") or [])]
        if name != pid and name not in aliases:
            continue                                # ② 名字对不上 → 不算命中，继续找
        rec = {"id": p["id"], "layer": layer, "dir": d, "pkg": p}
        # 遮蔽信息：快路径只命中一个包，不会像 scan_all() 那样顺手算出 shadowed。
        # 而 `--remove` 要用它打那句「它还遮住了 system 层的同名包 —— 删掉之后
        # 那个会重新生效」，所以 user 层命中时补一次 is_dir（约 0.05 ms，可忽略）。
        # 这里用 **id** 而不是 name 去拼路径：name 可能是别名，而 system 层
        # 那个包的目录名是它自己的 id。
        if layer == "user" and (paths.SYSTEM_PKGS / p["id"]).is_dir():
            rec["shadowed"] = "system"
        return rec
    return None


def find_alias(alias):
    """按名字找包（id 或别名）。用户层优先（遮蔽语义，`H-08`）。

    两条路（`CL-11`）：
      ① **直探**：把名字当目录名，去 `user_data/pkgs/<名字>` 和
         `system/pkgs/<名字>` 各读**一个**清单。命中就直接返回 ——
         这是 `moss :img` / `moss --remove img` / 历史重跑这些常见路径。
      ② **全扫兜底**：`scan_all()` 读两层的**全部**清单再线性找。
         别名（`:image` → img）和"目录名≠包 id"的包只能这么找 ——
         别名写在各包自己的 `pkg.json` 里，不读清单就不可能知道 image 是 img。
         探不到**不等于没有这个包**，所以这一步不能省。

    ★ 顺便说清一个以前没说透的事实：在全扫里"找到就返回"根本省不了什么 ——
      `scan_all()` 是在 `for` 开始前**一次性求值**的，清单早就全读完了，
      `return` 只省下后面几次字符串比较。所以真正能加速的做法只有一个：
      **别做全扫**。
    """
    name = (alias or "").strip().lower()
    if not name:
        return None
    rec = _probe_by_dirname(name)                   # ① 快路径
    if rec is not None:
        return rec
    for rec in scan_all():                          # ② 兜底（逻辑与以前一字不差）
        names = [str(a).lower() for a in (rec["pkg"].get("aliases") or [])]
        if name in names or name == rec["id"].lower():
            return rec
    return None
