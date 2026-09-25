# -*- coding: utf-8 -*-
"""运行历史（V-11 ~ V-14）。

它由**内建订阅者**写，不依赖钩子（T-05 原则）：
    "审计不能依赖一个可以被禁用、可以被写坏、可以被卸载的东西。"

记录里最关键的两个字段是 **target 和 cwd** ——
没有 cwd，就实现不了"不用先 cd 就能重启"（V-11）。
"""
import json
from datetime import datetime

from . import paths

# 列表里最多显示多少条（**去重之后**的条数）；为了凑够这些，最多往回读多少原始记录。
MAX_SHOW = 20
READ_RAW = 5000


def _file_for_now():
    return paths.HISTORY_DIR / (datetime.now().strftime("%Y-%m") + ".jsonl")


def append(entry):
    """追加一条。一行一个 JSON（jsonl），追加写，永不重写整个文件。"""
    try:
        paths.ensure_user_dirs()
        entry = dict(entry)
        entry.setdefault("ts", datetime.now().isoformat(timespec="seconds"))
        with open(_file_for_now(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return True
    except Exception:
        return False


def _iter_files():
    if not paths.HISTORY_DIR.is_dir():
        return []
    return sorted(paths.HISTORY_DIR.glob("*.jsonl"), reverse=True)


def recent(n=20):
    """最近 n 条，新的在前。跨月文件也读。"""
    out = []
    for f in _iter_files():
        try:
            with open(f, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
        except Exception:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
            if len(out) >= n:
                return out
    return out


def dedup_key(r):
    """去重的键：**同一件事只算一条**。

    键 = `kind` + （包 id 或目标路径）+ 参数 + 透传参数。

    ★ **不含 cwd**：路径调用的目标本身就是绝对路径（不同项目天然区分开）；
      包调用则按"哪个包 + 什么参数"算同一件事 —— 你在 A 目录和 B 目录都跑过
      `moss :hello`，列表里只该出现一条，重跑时用**最新那条记录里的 cwd** 回去。
    """
    return "|".join([
        str(r.get("kind") or ""),
        str(r.get("id") or r.get("target") or ""),
        json.dumps(r.get("params") or {}, sort_keys=True, ensure_ascii=False),
        json.dumps(r.get("args") or [], ensure_ascii=False),
    ])


def dedup(rows):
    """同一件事只留**最新**那条（保留后出现的、丢掉先出现的）。

    ★ 内部先按 `ts` 从新到旧排一遍 —— **不依赖调用方给的顺序**。
      为什么较真：这个规则一旦被反着喂数据就会**悄悄**变成"留旧的"，
      而列表看起来照样正常，很难发现。多一次排序换掉这个隐患，值。
    """
    ordered = sorted(rows, key=lambda r: str(r.get("ts") or ""), reverse=True)
    seen = set()
    out = []
    for r in ordered:
        k = dedup_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


def recent_unique(limit=MAX_SHOW, raw=READ_RAW):
    """去重后的最近记录（新的在前），最多 limit 条。

    为了凑够 limit 条**去重后**的记录，原始记录要多往回读一些（raw 条）。
    """
    return dedup(recent(raw))[:limit]


def on_after_run(payload):
    """内建订阅者：`after:run` → 写一条历史。

    ⚠️ 这个函数是**内核行为**，不是钩子。见模块 docstring。
    """
    inv = (payload or {}).get("invocation") or {}
    result = (payload or {}).get("result") or {}
    return append({
        "via": inv.get("via", "cli"),
        "kind": inv.get("kind"),
        "id": inv.get("id"),
        "target": inv.get("target"),
        "cwd": inv.get("cwd"),
        "runner": inv.get("runner"),
        "args": inv.get("args") or [],
        "params": inv.get("params") or {},
        "exit": result.get("exit"),
        "ms": result.get("ms"),
    })
