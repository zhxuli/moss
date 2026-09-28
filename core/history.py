# -*- coding: utf-8 -*-
"""运行历史（V-11 ~ V-14）。

它由**内建订阅者**写，不依赖钩子（T-05 原则）：
    "审计不能依赖一个可以被禁用、可以被写坏、可以被卸载的东西。"

★ **两次记账**：启动时先记一条（`before:run`，`state="start"`），
  结束时再记一条（`after:run`，带 `exit`/`ms`），列表里靠去重合成一条。
  为什么要先记：长驻程序（服务器/界面）在跑着的时候不能"查无此人"。

★ **只记路径调用**（`should_record`）：插件调用（`moss :别名`）不进历史 ——
  插件没有目录问题，永远叫得起来，记下来只是噪声，还会淹掉真正有价值的那类。

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
    ★ 只算**路径调用**（见 `should_record`）：插件调用不进列表。
      老文件里已经写下的插件记录也在这里被滤掉 —— 不改动日志本身（日志是
      追加写的账，不该回头重写），只是"看的时候不算它"。
    ★ 被墓碑点名的（`forget`）同样在这里滤掉。
    """
    rows = recent(raw)
    dead = _forgotten(rows)
    rows = [r for r in rows if should_record(r) and dedup_key(r) not in dead]
    return dedup(rows)[:limit]


def should_record(entry):
    """这条要不要进历史？**只记路径调用**（`moss zeen` 这种）。

    ★ 为什么不记插件调用（`moss :img`）：插件**没有目录问题** —— 它永远能用
      `moss :别名` 叫起来，跟你在哪个目录无关，记下来只是噪声，还会把真正
      有价值的那类（"必须先 cd 过去才能跑"的路径调用）淹掉。
      这条是用户定的（第 24 版）："插件永远通过普通的方式唤醒"。
    ★ 墓碑自己不是一条历史（它只是"某条别看了"的标记），同样不算。
    """
    return (entry.get("kind") or "") not in ("pkg", TOMBSTONE)


# ---------------------------------------------------------------- 删除（墓碑）
# ★ 为什么不"重写文件把它抠掉"：这本账是**追加写**的（`append` 从不回头改），
#   重写会跟"正在跑的那次调用结束时要补一条"打架，也可能把时间序搞乱。
#   所以删除也**追加一条**：`{"kind":"tombstone","forget":"<去重键>"}`，
#   读的时候看见同键的墓碑就跳过 —— 账只增，效果是"这条没了"。
TOMBSTONE = "tombstone"


def forget(entry):
    """把一条历史"删掉"（追加一条墓碑）。entry 可以是记录本身，也可以是去重键。"""
    if not entry:
        return False
    key = entry if isinstance(entry, str) else dedup_key(entry)
    if not key:
        return False
    return append({"via": "ui", "kind": TOMBSTONE, "forget": key})


def _forgotten(rows):
    """这批原始记录里被墓碑点名的去重键。"""
    return {str(r.get("forget") or "") for r in rows
            if (r.get("kind") or "") == TOMBSTONE and r.get("forget")}


def match_keys(r):
    """这条记录能被哪些"名字"叫起来。

    两种都算（都转小写）：
      · 目标文件名与去扩展名 —— `moss main.py` / `moss main`
      · **cwd 的最后一段**   —— 你举的例子：`moss zeen` 叫起
        `main.py  cwd=D:\\python\\wwwroot\\ZeEn`

    （原来还认"包 id"，但插件记录已经不进历史了，这一项自然消失，见
    `should_record`。）
    """
    keys = set()
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
    if not should_record(inv):
        return None
    return append(_entry_from(inv, state="start"))


def on_after_run(payload):
    """内建订阅者：`after:run` → 收尾那条（带结果与耗时）。

    ⚠️ 这个函数是**内核行为**，不是钩子。见模块 docstring。
    """
    inv = (payload or {}).get("invocation") or {}
    if not should_record(inv):
        return None
    return append(_entry_from(inv, result=(payload or {}).get("result") or {}))
