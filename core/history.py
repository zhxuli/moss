# -*- coding: utf-8 -*-
"""运行历史（V-11 ~ V-14）。

它由**内建订阅者**写，不依赖钩子（T-05 原则）：
    "审计不能依赖一个可以被禁用、可以被写坏、可以被卸载的东西。"

★ **两次记账**：启动时先记一条（`before:run`，`state="start"`），
  结束时再记一条（`after:run`，带 `exit`/`ms`），列表里靠去重合成一条。
  为什么要先记：长驻程序（服务器/界面）在跑着的时候不能"查无此人"。

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


def match_keys(r):
    """这条记录能被哪些"名字"叫起来。

    三种都算（都转小写）：
      · 包 id / 别名        —— `moss img` 能叫起 `moss :img`
      · 目标文件名与去扩展名 —— `moss main.py` / `moss main`
      · **cwd 的最后一段**   —— 你举的例子：`moss zeen` 叫起
        `main.py  cwd=D:\\python\\wwwroot\\ZeEn`
    """
    keys = set()
    if r.get("id"):
        keys.add(str(r["id"]).lower())
    t = r.get("target")
    if t:
        base = str(t).replace("/", "\\").rsplit("\\", 1)[-1]
        if base:
            keys.add(base.lower())
            if "." in base:
                keys.add(base.rsplit(".", 1)[0].lower())
    cwd = r.get("cwd")
    if cwd:
        seg = str(cwd).rstrip("\\/").replace("/", "\\").rsplit("\\", 1)[-1]
        if seg:
            keys.add(seg.lower())
    return keys


def find_recent(name):
    """按名字在最近的记录里找**最新**的那一条；找不到返回 None。

    "匹配到多个就进最近的一个" —— `recent_unique()` 本来就是新的在前，
    所以第一个命中的就是最近的。
    """
    want = str(name or "").strip().lower()
    if not want:
        return None
    for r in recent_unique():
        if want in match_keys(r):
            return r
    return None


def _entry_from(inv, result=None, state=None):
    """把一次 Invocation 变成一条历史记录。"""
    entry = {
        "via": inv.get("via", "cli"),
        "kind": inv.get("kind"),
        "id": inv.get("id"),
        "target": inv.get("target"),
        "cwd": inv.get("cwd"),
        "runner": inv.get("runner"),
        "args": inv.get("args") or [],
        "params": inv.get("params") or {},
    }
    if result is not None:
        entry["exit"] = result.get("exit")
        entry["ms"] = result.get("ms")
    if state:
        entry["state"] = state
    return entry


def on_before_run(payload):
    """内建订阅者：`before:run` → **先记一条**（`state="start"`）。

    ★ 为什么必须"先记"：长驻程序（服务器 / 界面 / 后台服务）在它**跑着的那段时间**里，
      只靠"结束时记账"就**根本看不到它** —— 实测：启动 uvicorn 之后
      `moss --history` 里没有它，用户以为记录坏了。
      跑完再补一条，两条靠去重合成一条（去重保留**后出现**的那条，
      正好就是带 `exit`/`ms` 的那条）。

    ⚠️ 这个函数也是**内核行为**，不是钩子（`T-05`）。
    """
    inv = (payload or {}).get("invocation") or {}
    return append(_entry_from(inv, state="start"))


def on_after_run(payload):
    """内建订阅者：`after:run` → 收尾那条（带结果与耗时）。

    ⚠️ 这个函数是**内核行为**，不是钩子。见模块 docstring。
    """
    inv = (payload or {}).get("invocation") or {}
    return append(_entry_from(inv, result=(payload or {}).get("result") or {}))
