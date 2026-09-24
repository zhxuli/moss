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

MAX_READ = 200


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
