# -*- coding: utf-8 -*-
"""AI 工作台的**快照**那一段（`V-236`）：动手前先存一条，而且**只准清自己存的**。

你要的两条规矩，落在这儿：
  ① **动手前先存**：改的是用户的包，改坏了得能一键回退（存的时候把**那一次的任务原文**
     一起写进清单 —— 你自己说的"这样我就知道是干啥之前的代码了"）；
  ② **AI 只能清自己生成的**：不是"提醒它别删你的"，是**结构上删不动** ——
     删除只走 `BackupStore.delete_ai()`，那个函数先看清单里的 `by`，不是 `"ai"` 直接跳过。

★ 为什么这条快照不标 tag：`tags.json` 是 tag→id 的**映射**（一个 tag 只能指一条），
  AI 跑第二趟就把上一趟顶掉了 —— 它没法当"这条是 AI 的"的标记。
  真字段 `by` 才是判据（清单里，写在 `system/ui/backup.py` 的 `create()`）。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent                   # system/ui/ai
UI = HERE.parent                                         # system/ui
if str(UI) not in sys.path:
    sys.path.insert(0, str(UI))
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E                                     # noqa: E402

#: 存"动手前"那条时用的标题前缀/兜底注释（人一眼能认出来；但**判据是 `by` 字段**）
TITLE = "AI · 动手前"
NOTE = "[AI] 工作台动手前自动存的"
#: 标题里带多少字的提示词（`V-249`）—— 太长会把列表那行撑爆，剩下的在备注里看全文
TASK_IN_TITLE = 40


def _one_line(s):
    """压成一行（换行/连续空白都算一个空格），前后去干净。"""
    return " ".join(str(s or "").split())


def title_for(task):
    """`AI · 动手前：<提示词前 40 字>` —— 只写"动手前"你根本认不出这是干啥之前的代码。

    ★ 提示词是用户自己敲的，可能好几行、可能很长，所以：压成一行 + 截断（`…` 收尾）。
    ★ 截断**只截标题**：备注里放全文（`note_for`），要看清就去看备注/悬停。
    """
    t = _one_line(task)
    if not t:
        return TITLE
    if len(t) > TASK_IN_TITLE:
        t = t[:TASK_IN_TITLE].rstrip() + "…"
    return "%s：%s" % (TITLE, t)


def note_for(task):
    """备注 = 那次的任务原文（全文，不截）；用户没写就退回原来那句固定话。"""
    return _one_line(task) or NOTE


def _store():
    import backup as B                                   # noqa: PLC0415
    return B.BackupStore(E.user_data() / "backups", _rel_of, _resolve)


def _rel_of(p):
    """页面 rel（`user/...` / `system/...` / `abs/...`）—— 和宿主 `_resolve` 一套口径。"""
    import backup as B                                   # noqa: PLC0415
    for name, root in (("user", E.user_data()),
                       ("system", E.HOME / "system")):
        try:
            rel = os.path.relpath(str(p), str(root))
        except ValueError:
            continue
        if not rel.startswith("..") and not os.path.isabs(rel):
            return "%s/%s" % (name, rel.replace("\\", "/"))
    return "abs/" + str(p).replace(":", "").replace("\\", "/")


def _resolve(rel):
    """rel → 绝对路径（给 `create()` 用；它对来源要求绝对路径）。"""
    s = str(rel or "").replace("\\", "/")
    low = s.lower()
    if low.startswith("user/"):
        return E.user_data() / s[5:]
    if low.startswith("system/"):
        return E.HOME / "system" / s[7:]
    if low.startswith("abs/"):
        return Path(s[4:].replace("/", os.sep))
    raise ValueError("认不出这个 rel：%s" % rel)


def snapshot_before(task, workdir):
    """动手前给**这个包**存一条（`by="ai"` + 那次的任务原文）。

    只在"改一个已经存在的包"时存：新建包没什么可回退的（那目录本来就没有）。
    返回 `{ok, id, group, msg}`；存不了也**不拦着**干活（AI 该干的活照干，只是没退路）。
    """
    wd = Path(str(workdir or ""))
    try:
        if not wd.is_dir():
            return {"ok": False, "msg": "这个目录还不存在（新建包）—— 不用存动手前的快照"}
        rel = _rel_of(wd)
        if not str(rel).lower().startswith("user/"):
            return {"ok": False, "msg": "只给 `user_data/` 里的包存快照（外面的人来管）"}
        st = _store()
        srcs = [str(wd.resolve())]
        man = st.create(srcs, title=title_for(task), note=note_for(task),
                        by="ai", by_task=str(task or "").strip())
        return {"ok": True, "id": man.get("id"), "group": man.get("group"),
                "msg": "存好了：%s（分组 %s）" % (man.get("id"), man.get("group"))}
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


def clean_ai(group="", bid=""):
    """清 AI 存过的快照。**只删 `by == "ai"` 的**（`delete_ai` 里那道闸）。"""
    try:
        st = _store()
        return st.delete_ai(bid=(str(bid or "") or None), group=(str(group or "") or None))
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


def ai_count(group=""):
    """这一组里有几条是 AI 存的（界面那个"清掉 AI 的 (N)"要用）。"""
    try:
        got = [b for b in _store().list_backups(group=(str(group or "") or None))
               if str(b.get("by") or "") == "ai"]
        return len(got)
    except Exception:                                                 # noqa: BLE001
        return 0
