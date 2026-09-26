# -*- coding: utf-8 -*-
"""安装状态 `user_data/registry.json`。

它是"装了哪些包、什么状态"的**单一事实来源**（D-09），
但它**可以被重建** —— 启动时与磁盘对账（`sync`）：
  · 磁盘上有、registry 里没有  → 补进去
  · registry 里有、磁盘上没了  → 标记 orphan（不静默删，留着让人看见）

遮蔽规则（H-08）：**用户层同名包遮蔽系统层，系统层原件保留**，不是替换。
"""
import json
import sys
from datetime import datetime

from . import paths, pkg as pkg_mod

HOST_VERSION = "0.1.0"
SPEC = 1


def _default():
    return {
        "spec": SPEC,
        "host": {"version": HOST_VERSION, "lastStart": None},
        "packages": {},
    }


def load():
    if paths.REGISTRY_FILE.is_file():
        try:
            with open(paths.REGISTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("spec", SPEC)
                data.setdefault("host", {"version": HOST_VERSION})
                data.setdefault("packages", {})
                return data
        except Exception:
            pass
    return _default()


def save(reg):
    paths.ensure_user_dirs()
    with open(paths.REGISTRY_FILE, "w", encoding="utf-8") as f:
        json.dump(reg, f, ensure_ascii=False, indent=2)


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
            #   静默跳过的后果是：包从扫描结果里消失 → sync 把它判成 orphan
            #   → is_enabled 判 false → 用户看到「包已被禁用」，而真正的原因
            #   是自己那个 pkg.json 有个 JSON 语法错。这个坑真踩过（PowerShell
            #   把 pkg.json 写坏 → img 被"禁用"，查了半天）。
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

    层优先级：dev > user > system
      · `dev` 层只在开发机上存在（`dev/pkgs`）。发行版里没有 `dev/` 目录，
        所以用户永远看不到它 —— 演示包、测试固件放这里，**绝不进 `system/pkgs`**。
      · `system/pkgs` 是要随程序分发给所有用户的出厂包。
    """
    out = [(paths.SYSTEM_PKGS, "system"), (paths.USER_PKGS, "user")]
    if paths.DEV_PKGS.is_dir():
        out.append((paths.DEV_PKGS, "dev"))
    return out


def scan_all():
    """把所有层的包扫出来，同名的后扫的遮蔽先扫的（H-08 遮蔽语义）。"""
    by_id = {}
    for base, layer in layers():
        for rec in _scan_layer(base, layer):
            if rec["id"] in by_id:
                rec["shadowed"] = by_id[rec["id"]]["layer"]
            by_id[rec["id"]] = rec
    return sorted(by_id.values(), key=lambda r: r["id"])


def find_alias(alias):
    """按别名找包。用户层优先（遮蔽语义）。"""
    alias = (alias or "").strip().lower()
    if not alias:
        return None
    for rec in scan_all():
        names = [str(a).lower() for a in (rec["pkg"].get("aliases") or [])]
        if alias in names or alias == rec["id"].lower():
            return rec
    return None


def sync(reg):
    """与磁盘对账。返回 (added, missing)。"""
    on_disk = {rec["id"]: rec for rec in scan_all()}
    added, missing, restored = [], [], []

    for pid, rec in on_disk.items():
        if pid not in reg["packages"]:
            reg["packages"][pid] = {
                "layer": rec["layer"],
                "state": "enabled",
                "origin": (rec["pkg"].get("origin") or {}).get("by", "builtin"),
                "version": rec["pkg"].get("version"),
                "seenAt": datetime.now().isoformat(timespec="seconds"),
            }
            added.append(pid)
        else:
            # ★ 包又回到磁盘上了 —— 必须把 orphan 恢复成 enabled。
            #   原来这里只更新 layer/version，**从不改 state**，于是 orphan
            #   成了一个"一旦进去就出不来"的状态：哪怕包完完整整地在那儿，
            #   也永远显示「已被禁用」。（真踩过：pkg.json 被写坏 → img 变 orphan
            #   → 修好 pkg.json 之后依然起不来。）
            #   只恢复 orphan；用户**主动**禁用过的是 "disabled"，那种不动。
            if reg["packages"][pid].get("state") == "orphan":
                reg["packages"][pid]["state"] = "enabled"
                restored.append(pid)
            reg["packages"][pid]["layer"] = rec["layer"]
            reg["packages"][pid]["version"] = rec["pkg"].get("version")

    for pid in list(reg["packages"].keys()):
        if pid not in on_disk:
            reg["packages"][pid]["state"] = "orphan"
            missing.append(pid)

    reg["host"]["version"] = HOST_VERSION
    reg["host"]["lastStart"] = datetime.now().isoformat(timespec="seconds")
    save(reg)
    if restored:
        print("[提示] 这些包之前被标成 orphan，现在磁盘上又有了，已恢复启用：%s"
              % "、".join(restored))
    return added, missing


def is_enabled(reg, pid):
    rec = reg["packages"].get(pid)
    return bool(rec) and rec.get("state", "enabled") == "enabled"
