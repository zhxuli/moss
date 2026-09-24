# -*- coding: utf-8 -*-
"""安装状态 `user_data/registry.json`。

它是"装了哪些包、什么状态"的**单一事实来源**（D-09），
但它**可以被重建** —— 启动时与磁盘对账（`sync`）：
  · 磁盘上有、registry 里没有  → 补进去
  · registry 里有、磁盘上没了  → 标记 orphan（不静默删，留着让人看见）

遮蔽规则（H-08）：**用户层同名包遮蔽系统层，系统层原件保留**，不是替换。
"""
import json
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
    added, missing = [], []

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
            reg["packages"][pid]["layer"] = rec["layer"]
            reg["packages"][pid]["version"] = rec["pkg"].get("version")

    for pid in list(reg["packages"].keys()):
        if pid not in on_disk:
            reg["packages"][pid]["state"] = "orphan"
            missing.append(pid)

    reg["host"]["version"] = HOST_VERSION
    reg["host"]["lastStart"] = datetime.now().isoformat(timespec="seconds")
    save(reg)
    return added, missing


def is_enabled(reg, pid):
    rec = reg["packages"].get(pid)
    return bool(rec) and rec.get("state", "enabled") == "enabled"
