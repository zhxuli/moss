# -*- coding: utf-8 -*-
"""AI 工作台的**任务记录**（`V-243`）：每次跑完落一条盘，重启 moss 还看得见。

你说得对：「历史记录不保存是不行的」—— 原来这些全在 `AI["state"]` 里（内存），
moss 一重启就没了（任务原文、步骤流、结论、花了多少 token 全丢）。
存 `user_data/ai/runs/<时间>-<短id>.json`，一条一个文件（不会一条坏掉全废），
按时间倒序读，超过 `KEEP` 条就把最老的删掉。
"""
import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E                                     # noqa: E402

#: 最多留多少条（一条大概几 KB；60 条 ≈ 几百 KB）
KEEP = 60


def dir_path():
    return E.user_data() / "ai" / "runs"


def _new_id():
    return "%s-%04x" % (time.strftime("%Y%m%d-%H%M%S"), random.randint(0, 0xffff))


def save(rec):
    """存一条。回 `{ok, id}`（存不上也不抛 —— 干活要紧，记录丢了只是少个回顾）。"""
    try:
        rec = dict(rec or {})
        rec.setdefault("id", _new_id())
        rec.setdefault("finished", time.time())
        d = dir_path()
        d.mkdir(parents=True, exist_ok=True)
        (d / (rec["id"] + ".json")).write_text(
            json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
        _prune()
        return {"ok": True, "id": rec["id"]}
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "id": "", "msg": "%s: %s" % (type(e).__name__, e)}


def _prune():
    try:
        files = sorted(dir_path().glob("*.json"))
        for old in files[:-KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


def _load(path):
    try:
        got = json.loads(path.read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else None
    except Exception:                                                 # noqa: BLE001
        return None


def list_runs(limit=30, with_steps=False):
    """按时间倒序列出（默认**不带步骤流**，那个大；列表只需要一行摘要）。"""
    d = dir_path()
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json"), reverse=True)[:max(1, int(limit or 30))]:
        rec = _load(p)
        if not rec:
            continue
        row = {k: rec.get(k) for k in ("id", "task", "workdir", "ok", "reason", "summary",
                                       "caveats", "usage", "files", "snapshot", "seconds",
                                       "started_text", "finished", "model", "max_tokens",
                                       # ★ `V-269`：`kind` 也要跟着回界面 —— 列表那一行靠它
                                       #   把纯问答画成「💬 你是哪个大模型?」而不是「✅ …」
                                       "kind", "stopped", "continued_from")}
        # ★ `V-251`：这条能不能**接着聊**（＝ 存了对话本身）。列表**不带 `messages`**
        #   （那是整条会话，几百 KB）—— 界面只拿这个布尔值，真接着聊时把 id 交回宿主。
        row["cont"] = bool(rec.get("messages"))
        row["msgs"] = len(rec.get("messages") or [])
        row["steps"] = len(rec.get("steps") or [])
        if with_steps:
            row["steps_detail"] = rec.get("steps") or []
        out.append(row)
    return out


def get(run_id):
    """读一条完整的（含步骤流）—— 界面上点「看」用它。"""
    p = dir_path() / ("%s.json" % str(run_id or ""))
    return _load(p) if p.is_file() else None


def delete(run_id):
    try:
        (dir_path() / ("%s.json" % str(run_id or ""))).unlink(missing_ok=True)
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "msg": str(e)}


def clear():
    """全清（界面上给一颗"清空历史"，删前自己确认）。"""
    n = 0
    try:
        for p in dir_path().glob("*.json"):
            p.unlink(missing_ok=True)
            n += 1
    except OSError:
        pass
    return {"ok": True, "removed": n}
