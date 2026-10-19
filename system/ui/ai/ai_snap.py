# -*- coding: utf-8 -*-
"""AI 工作台的**快照**那一段（`V-236`）：动手前先存一条，而且**只准清自己存的**。

你要的两条规矩，落在这儿：
  ① **动手前先存**：改的是**这个包**（用户包或出厂包），改坏了得能一键回退（存的时候把
     **那一次的任务原文**一起写进清单 —— 你自己说的"这样我就知道是干啥之前的代码了"）；
  ② **AI 只能清自己生成的**：不是"提醒它别删你的"，是**结构上删不动** ——
     删除只走 `BackupStore.delete_ai()`，那个函数先看清单里的 `by`，不是 `"ai"` 直接跳过。

★ 为什么这条快照不标 tag：`tags.json` 是 tag→id 的**映射**（一个 tag 只能指一条），
  AI 跑第二趟就把上一趟顶掉了 —— 它没法当"这条是 AI 的"的标记。
  真字段 `by` 才是判据（清单里，写在 `system/ui/backup.py` 的 `create()`）。

★★ `V-382`（你 2026-10-17 的原话：「你给我改代码也不先创建快照？现在整个都废了」）：
  查了会话记录，真相不是"没存"，是**存了又被它自己删了** —— 那几轮收尾都调了
  `snap_clean`（"别占着用户地方"）。所以现在的规矩改硬了：
    ① AI **没有任何删快照的工具**（`snap_clean` 整条从工具表里拿掉了，见 `ai_tools.py`）；
    ② 快照覆盖的是**真的被改的那个目录**（不再只看 workdir：以前 workdir 是 `pkgs/mu`
       却在改 `pkgs/autokey` 时，存下来的是 mu 那个空壳）；
    ③ 包**外面**的目录（用户让你"给我写个项目"那种）也存 —— 它有 `abs/` 这个根；
       但盘根 / 用户主目录 / 库本身 / 你自己的 tmp 不存（那是"备份整块盘"，不是备份）。
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

#: 存"动手前"那条时用的兜底注释（人一眼能认出来；但**判据是 `by` 字段**）
TITLE = "AI · 动手前"
NOTE = "[AI] 自动存的"
#: 标题里带多少字的提示词（`V-249`）—— 太长会把列表那行撑爆，剩下的在备注里看全文
TASK_IN_TITLE = 40


def _one_line(s):
    """压成一行（换行/连续空白都算一个空格），前后去干净。"""
    return " ".join(str(s or "").split())


def title_for(task):
    """标题 = **那次的任务原文**（前 40 字），不加任何前缀 —— `V-251` 你定的：
    「不用写 AI 动手前，不需要"动手前"几个字，以节省空间」。

    ★ 那怎么知道是 AI 存的？**列表那一行的「AI」徽章**（清单里的真字段 `by="ai"`），
      标题只是给人看的内容 —— 别把标识塞进标题里占地方。
    ★ 提示词可能是好几行、可能很长：压成一行 + 截断（`…` 收尾）；README 里说的
      "留空就用时间"由存储兜底（`backup.py`：`title or "备份 " + 时间`）。
    """
    t = _one_line(task)
    if not t:
        return ""
    if len(t) > TASK_IN_TITLE:
        t = t[:TASK_IN_TITLE].rstrip() + "…"
    return t


def note_for(task):
    """备注 = 那次的任务原文（全文，不截）；用户没写就退回一句短的固定话。"""
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


#: 一次"动手前"快照最多收多少个文件。过了就不存（宁可如实说"没退路"，
#: 也不能让 AI 一次改动把半块盘拷进备份库、还要用户等好几分钟）。
MAX_FILES = 20000


def _count_files(d, cap=MAX_FILES):
    """飞快数一下这个目录下有多少文件（数到 `cap` 就停 —— 只用来做"太大就不存"的判断）。"""
    n = 0
    for _cur, _dirs, names in os.walk(str(d)):
        n += len(names)
        if n > cap:
            return n
    return n


def too_broad(d):
    """这个目录**不该整个存**吗（存了就是"备份整块盘"）—— 回一句人话原因，或空串。

    ★ 为什么要这道闸：`V-382` 之后 AI 能备份 `user_data` / `system` **外面**的目录了
      （用户说"给我写个项目"经常就在外面）。没有这道闸的话，它对着 `D:\\` 或用户主目录
      按下去，就是几个 G 的拷贝 + 几分钟的白等。
    """
    try:
        p = Path(str(d)).resolve()
    except OSError:
        return "这个路径读不到"
    # ① 盘根 / 用户主目录 / 系统目录：一律不存
    if p.parent == p:
        return "这是盘根（整块盘不是一次备份的对象）"
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~") or "/")
    try:
        if p == home.resolve():
            return "这是你的用户主目录（太大，也不是一次备份的对象）"
    except OSError:
        pass
    # ② 我们自己的根：user_data / system / 安装根 下面那几个"一整层"的
    for r in (E.user_data(), E.HOME / "system", E.HOME):
        try:
            if p == Path(r).resolve():
                return "这是 `%s`（整层太大，要存就存它下面的某个包 / 目录）" % Path(r).name
        except OSError:
            continue
    for r in (E.user_data() / "pkgs", E.user_data() / "state",
              E.user_data() / "backups", E.user_data() / "trash",
              E.user_data() / "ai", E.HOME / "system" / "pkgs",
              E.HOME / "core", E.HOME / "system" / "ui",
              E.HOME / "system" / "runtimes"):
        try:
            if p == Path(r).resolve():
                return "这是 `%s`（整层太大，要存就存它下面的某个包 / 目录）" % r.name
        except OSError:
            continue
    # ③ 备份库自己（套娃）
    try:
        if str(p).lower().startswith(str((E.user_data() / "backups").resolve()).lower()):
            return "这是备份库自己（不能备份备份）"
    except OSError:
        pass
    return ""


def is_scratch(path):
    """这个路径是**AI 自己的中间产物**吗（tmp / 备份库 / 回收站）—— 是就不值得为它存快照。

    ★ 为什么要有：它跑诊断会先在 `MOSS_AI_TMP` 里写一个探针脚本。那一下要是也触发
      "动手前快照"，等于**每个只在做诊断的回合都白存一条**（跟 `V-269` 修掉的
      "问一句也存一条"是同一类浪费），而且真正的改动点反而离快照更远。
    """
    try:
        p = str(Path(str(path)).resolve()).lower()
    except OSError:
        return False
    for root in (E.user_data() / "backups", E.user_data() / "trash",
                 E.user_data() / "ai" / "tmp"):
        try:
            if p.startswith(str(Path(root).resolve()).lower()):
                return True
        except OSError:
            continue
    # `user_data/state/<包>/ai/tmp/…`（`V-314` 起临时空间按包分）
    try:
        st = str((E.user_data() / "state").resolve()).lower()
    except OSError:
        return False
    return p.startswith(st) and (os.sep + "ai" + os.sep + "tmp" + os.sep) in p


def _pkg_dir(d):
    """`d` 落在某个 `pkgs` 根下面 ⇒ 回**那个包目录**；否则回 None。"""
    for root in (E.user_data() / "pkgs", E.HOME / "system" / "pkgs"):
        try:
            rel = Path(str(d)).resolve().relative_to(Path(root).resolve())
        except (ValueError, OSError):
            continue
        if rel.parts:
            return Path(root) / rel.parts[0]
    return None


def scope_dir(path):
    """要改的那个东西属于**哪个目录**（快照就存它）。

    规律：落在某个 `pkgs` 根下面的，存**那个包目录**（不是它下面更深的子目录 ——
    恢复时你希望整个包一起回去）；其它的就存文件所在的那一层目录。
    """
    p = Path(str(path))
    try:
        if p.is_dir():
            return _pkg_dir(p) or p
    except OSError:
        return p
    # 文件（或还不存在的文件：新建）⇒ 看它父目录
    parent = p.parent
    got = _pkg_dir(parent)
    if got:
        return got
    return parent if parent.exists() else p


def snapshot_before(task, workdir, touched=None):
    """动手前给**这次真的会改到的地方**存一条（`by="ai"` + 那次的任务原文）。

    `touched`（`V-382` 新加）：第一处要写的**文件路径**。给了它就以它为准 ——
      · 改的是某个包里的文件 ⇒ 存那个包；
      · 改的是包**外面**的目录（"给我写个项目"）⇒ 存那个目录（`abs/` 那个根）；
      · 只写到自己的 tmp / 备份库 ⇒ 不值得存（`is_scratch`，调用方已经先挡了一道）。
    不给就退回老行为：存 `workdir`。

    返回 `{ok, id, group, sources, msg, retry}`；存不了也**不拦着**干活（AI 该干的活照干，
    只是没退路 —— 这句会如实回给模型，让它写进收工报告）。
    `retry=True` 的那一种（要改的东西**还不存在**，典型是"新建一个包 / 新写一个目录"）
    **不占掉这次机会**：等它真把东西建出来、下一次再动它之前，再存一次。
    不然一个新包从创建到改坏，全程一条快照都没有（真机上就是这么丢的）。

    ★ `V-347`：**出厂包（`system/pkgs/<id>`）也存** —— 既然放开了让它改，那就得给它退路。
    """
    wd = Path(str(workdir or ""))
    try:
        cands, will_exist = [], []
        if touched:
            d = scope_dir(touched)
            if d.is_dir():
                cands.append(d)
            else:
                will_exist.append(d)            # 要改的东西还没建出来 ⇒ 下一次再存
        if wd.is_dir():
            cands.append(wd)
        srcs, why_not = [], []
        seen = set()
        for d in cands:
            try:
                key = str(Path(d).resolve()).lower()
            except OSError:
                key = str(d).lower()
            if key in seen:
                continue
            seen.add(key)
            bad = too_broad(d)
            if bad:
                why_not.append(str(d) + "：" + bad)
                continue
            n = _count_files(d)
            if n > MAX_FILES:
                why_not.append("%s：文件太多（>%d 个）" % (d, MAX_FILES))
                continue
            srcs.append(str(Path(d).resolve()))
        if not srcs:
            # ★ 只要"要改的东西还没建出来"，就**留着这次机会**（新建包 / 新写一个目录）：
            #   这一刻没有任何"动手前的样子"可存，但等它建出来再动它之前就有了。
            #   ★ 别被 `why_not` 拦住（workdir 常常是 `user_data/pkgs` 那种整层 —— 那是
            #     "太宽不该存"，不是"永远不用存"；探针当场抓到过这一条）。
            if will_exist:
                return {"ok": False, "retry": True,
                        "msg": "要改的东西还没建出来（新建）—— 等它存在了再存动手前的快照"}
            if not wd.is_dir() and not touched:
                return {"ok": False, "msg": "这个目录还不存在（新建包）—— 不用存动手前的快照"}
            return {"ok": False,
                    "msg": ("没有可以存的地方" + ("（" + "；".join(why_not) + "）" if why_not else ""))}
        st = _store()
        man = st.create(srcs, title=title_for(task), note=note_for(task),
                        by="ai", by_task=str(task or "").strip())
        return {"ok": True, "id": man.get("id"), "group": man.get("group"),
                "sources": srcs, "files": (man.get("stats") or {}).get("files"),
                "msg": "存好了：%s（分组 %s，%s 个文件）"
                       % (man.get("id"), man.get("group"),
                          (man.get("stats") or {}).get("files"))}
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


def clean_ai(group="", bid=""):
    """清 AI 存过的快照。**只删 `by == "ai"` 的**（`delete_ai` 里那道闸）。"""
    try:
        st = _store()
        return st.delete_ai(bid=(str(bid or "") or None), group=(str(group or "") or None))
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "msg": "%s: %s" % (type(e).__name__, e)}


# ====================================================================== 开工那条
# ★★ `V-384`（你 2026-10-19 的原话：「它还是没有在开工前 自动创建镜像」）：
#   `V-269` 把快照从"开工就存"挪到了"第一次真要写之前" —— 理由是"问一句『你是哪个
#   大模型』也存一条"太浪费。但真机上的代价是：它先读十几分钟文件（18:05 开工、
#   18:16 才第一次写），你在那个窗口里点开「版本快照」**看到的是空的** ⇒ 只能判断成
#   "它压根没备份"。所以规矩改成：
#     ① **改一个已经存在的包 ⇒ 开工就存**（`snapshot_at_start`）；
#     ② 新建包 / 在包外面写项目 ⇒ 那一刻没有"动手前的样子"，仍然等第一次写之前存
#        （`snapshot_before` 的 retry）；
#     ③ 开工存的这条要是**这一跑一个字都没改**（既没改文件、也没跑过命令），收工时
#        收掉（`drop_untouched`）—— `V-269` 想省的"问答也留一条"仍然省着。
def is_pkg_dir(d):
    """这个目录是不是**一个包**（有 pkg.json）。"""
    try:
        return (Path(str(d)) / "pkg.json").is_file()
    except OSError:
        return False


def snapshot_at_start(task, workdir):
    """**开工就存**一条（`V-384`）。返回口径和 `snapshot_before` 一样，多一个 `at_start`。

    只对"已经在某个包目录里"的活生效：新建包（`workdir` 是 `pkgs` 整层）那一刻
    没有任何"动手前的样子"可存，强行存只会把整层 `pkgs` 拷进去。
    """
    wd = Path(str(workdir or ""))
    if not is_pkg_dir(wd):
        return {"ok": False, "skip": True,
                "msg": "这次不是改一个已经存在的包 —— 等它第一次动手之前再存"}
    got = snapshot_before(task, str(wd))
    got["at_start"] = True
    return got


def drop_untouched(bid, group=""):
    """把"开工那条空快照"收掉（这一跑一个字都没改）。**只删 `by == "ai"` 的。**"""
    if not bid:
        return {"ok": False, "msg": "没有快照 id"}
    try:
        st = _store()
        got = st.delete_ai(bid=str(bid), group=(str(group or "") or None))
        if isinstance(got, dict):
            got.setdefault("ok", True)
        return got or {"ok": True}
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
