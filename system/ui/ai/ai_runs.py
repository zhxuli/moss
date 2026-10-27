# -*- coding: utf-8 -*-
"""AI 工作台的**任务记录**（`V-243` / `V-307`）：每次跑落一条盘，重启 moss 还看得见。

你说得对：「历史记录不保存是不行的」—— 原来这些全在 `AI["state"]` 里（内存），
moss 一重启就没了（任务原文、步骤流、结论、花了多少 token 全丢）。

★ `V-307` 改了两件事（都是你 2026-10-07 提的）：

  ① **按"干活的地方"分开放**（原来是所有包挤在一个 `user_data/ai/runs/` 里 ⇒
     你在 github 的 AI 页能看见 dazi / calc 的会话）。现在：
         · 包里的会话 ⇒ `user_data/state/<包id>/ai/runs/<时间>-<短id>.json`
           —— 那**就是**这个插件的用户目录（`MOSS_PLUGIN_DATA_DIR` 同一个地方），
             所以 `moss --rename 旧 新` 会把数据目录一起搬，**改名不影响会话**；
             删包 = 会话跟着走，不会留一地孤儿。
         · 「整个项目区」那种不针对某个包的 ⇒ `user_data/ai/runs/`（老地方，全局桶）。
     老记录第一次读的时候**自动按 `workdir` 归位**（`migrate_once()`，只搬一次、不删原件）。

  ② **每步都落盘**（`save_live()`）：原来只有"跑完"才写一次 ⇒ 你强制重启那次，
     那条记录整个没了。现在开工就写一条 `running=true` 的活记录、**每一步覆盖一次**
     （原子写：先 `.tmp` 再 `os.replace`），跑完再把 `running` 摘掉。
     重启后你看到的是一条标着「⚠ 上次没跑完」的记录（步骤流一块不少，能看、能接着聊）。
"""
import json
import os
import random
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import ai_edits as E                                     # noqa: E402

#: 每个目录最多留多少条（一条大概几 KB）
KEEP = 60


# ------------------------------------------------------------------ 放在哪儿
def pkg_of(workdir):
    """这次干活的地方是不是**某个包目录** —— 是就回**包 id**，不是回 `""`。

    只认"正好是 `<某个 pkgs 根>/<目录名>`"这一层（`state/<id>/` 就是它的数据目录）；
    更深的地方（`pkgs/<目录名>/ui/...`）也算这个包；`pkgs` 本身 = 整个项目区，不算包。
    ★ 两个 pkgs 根都认（`V-307`）：用户包（`user_data/pkgs`）和**出厂包**（`system/pkgs`）——
      出厂包虽然写不了，但你在它的 AI 页聊过的东西**也该只出现在它自己的历史里**，
      不该混进"整个项目区"那一桶。
    ★★ `V-314`：**目录名和 id 可能不一样**（`D-27`：包目录名和 id 本来互不相干），
      而数据目录是按 **id** 算的（`core/paths.py::pkg_state_dir`）——所以这里以
      `pkg.json` 里的 `id` 为准，读不出来才退回目录名。不这么做的话：目录叫 `a`、id 是 `b` 时，
      会话会落在 `state/a/`，而 `moss --rename`（它搬的是 `state/<id>`）就带不走它。
    """
    try:
        p = Path(str(workdir or "")).resolve()
    except OSError:
        return ""
    roots = []
    for r in (E.write_root(), E.HOME / "system" / "pkgs"):
        try:
            roots.append(Path(r).resolve())
        except OSError:
            pass
    for root in roots:
        try:
            rel = p.relative_to(root)
        except ValueError:
            continue
        parts = rel.parts
        if not parts:
            continue
        name = parts[0]
        if not _ok_id(name):
            continue
        # 以清单里的 id 为准（目录名和 id 不一致时，数据目录跟的是 id）
        pkg_id = name
        try:
            man = root / name / "pkg.json"
            if man.is_file():
                got = json.loads(man.read_text(encoding="utf-8"))
                cand = str((got or {}).get("id") or "").strip()
                if _ok_id(cand):
                    pkg_id = cand
        except Exception:                                            # noqa: BLE001
            pass
        return pkg_id
    return ""


def _ok_id(pid):
    """包 id 的规矩（`core/paths.py:ID_RE`）—— 不合法就当它不是包目录。"""
    pid = str(pid or "")
    if not pid or pid.startswith("_"):
        return False
    if not (pid[0].islower() and pid.isascii()):
        return False
    return all(ch.isalnum() or ch in "_-" for ch in pid)


def scope_dir(workdir=""):
    """这条会话的落盘目录（按"干活的地方"分）。"""
    pid = pkg_of(workdir)
    if pid:
        return E.user_data() / "state" / pid / "ai" / "runs"
    return E.user_data() / "ai" / "runs"


def scope_of(workdir="", pid=""):
    """给界面 / 记录用的一份"这是谁的会话"：`{kind, id, dir, label}`。

    `pid` 显式给就不去推（宿主手里有包表，给得更准）。
    ★ 注意这里**别**把 `pid` 再喂回 `scope_dir()` —— 那个函数收的是**干活目录**，
      而 `pid` 是个 id（"md5" 不是路径 ⇒ 它会算成"不针对任何包" ⇒ 落到全局桶。
      探针 J 段当场抓到过这个自相矛盾）。
    """
    pid = str(pid or "").strip() or pkg_of(workdir)
    if pid:
        return {"kind": "pkg", "id": pid,
                "dir": E.user_data() / "state" / pid / "ai" / "runs", "label": "包 " + pid}
    return {"kind": "all", "id": "", "dir": E.user_data() / "ai" / "runs", "label": "整个项目区"}


def dir_path(scope=None):
    r"""`scope` 可以是这四种：`scope_of()` 的返回值 / 包 id / **干活目录的路径** / 空。
    ★ 为什么要认路径：`save(rec)` 不带 scope 时是按 `rec["workdir"]` 归档的。
      ★★ 这里踩过一次（探针当场抓住）：把 `C:\…\pkgs\zz` 这种**绝对路径**当"包 id"
        拼进去，`Path / 绝对路径` 会**把前面整段丢掉**（pathlib 的规矩）⇒ 记录被写到
        `pkgs/zz/ai/runs/` 里去了，而读的时候按 `state/<id>/ai/runs` 找 ⇒ **存了读不回来**。
        所以"带分隔符/盘符的字符串"一律按 workdir 解。
    """
    if isinstance(scope, dict):
        d = scope.get("dir")
        if d:
            return Path(d)
        if scope.get("id"):
            return E.user_data() / "state" / str(scope["id"]) / "ai" / "runs"
        return E.user_data() / "ai" / "runs"
    s = str(scope or "").strip()
    if not s or s == "all":
        return E.user_data() / "ai" / "runs"
    if ("\\" in s) or ("/" in s) or (":" in s):
        return scope_dir(s)                      # 像个路径 ⇒ 按"干活的地方"解
    return E.user_data() / "state" / s / "ai" / "runs"


# ------------------------------------------------------------------ 归位（按"活干在哪个包"）
def _common_pkg(files):
    """这些路径**全部**落在同一个包里 ⇒ 回那个包 id；跨包 / 有一处不在包里 ⇒ 空串。

    `files` 是这一跑动过（新建 / 改过）的文件，`pkg_of()` 认得"包目录里的任何东西"。
    """
    ids = set()
    for f in files or []:
        pid = pkg_of(f)
        if not pid:
            return ""
        ids.add(pid)
    return next(iter(ids)) if len(ids) == 1 else ""


def _rehome(rec):
    """★ 活干在**另一个包**里 ⇒ 把这条记录整个归到那个包（`V-421`）。

    什么时候会发生（2026-10-21 真事）：界面的"在哪干活"是**从当前选中的包推出来的**；
    「新建包 → 切过去 → 自动开工」这条链上只要有一拍错位，AI 就会**在 A 包里开工、
    却把 B 包整个建出来**。结果整段会话挂在了 A 名下 —— 用户回到新包的 AI 页，
    看到的是"还没有跑过"（真事：会话挂在 `ip` 下，文件全在 `keytest` 里）。

    判据刻意收得很窄 —— **只在"动过的文件全都在同一个包、且那个包就是新建的那个"时才搬**：
      · 跨包的（AI 顺手修了两个包）不猜；
      · 落在临时目录 / 技能（`state/skill/<名字>`）的不动（`pkg_of` 本来就认不出它们）；
      · 已经在正确包里 ⇒ 原样返回（绝大多数情况）。
    """
    try:
        rec = dict(rec or {})
        pid_now = pkg_of(rec.get("workdir"))
        pid_new = _common_pkg(rec.get("files"))
        if not pid_new or pid_new == pid_now:
            return rec, False
        for root in (E.user_data() / "pkgs", E.HOME / "system" / "pkgs"):
            d = Path(root) / pid_new
            if d.is_dir():
                old = str(rec.get("workdir") or "")
                rec["workdir"] = str(d)
                rec["scope"] = "pkg"
                rec["scope_id"] = pid_new
                rec["rehomed_from"] = rec.get("rehomed_from") or old
                return rec, True
    except Exception:                                                 # noqa: BLE001
        pass
    return dict(rec or {}), False


def _drop_stale(rid, keep):
    """把同一个 id 落在**别的桶**里的旧副本删掉（归位之后会留下一个）。

    只在这一跑确实被归位过（`rehomed_from`）时调用 —— 平时不动别人的文件。
    """
    keep = str(keep)
    for d in _all_dirs():
        if str(d) == keep:
            continue
        p = Path(d) / (str(rid) + ".json")
        try:
            if p.is_file():
                p.unlink()
        except OSError:
            pass


def _all_dirs():
    """所有可能的桶：全局那个 + 每个包数据目录下的 `ai/runs`。"""
    out = [E.user_data() / "ai" / "runs"]
    st = E.user_data() / "state"
    try:
        if st.is_dir():
            for d in st.iterdir():
                p = d / "ai" / "runs"
                if p.is_dir():
                    out.append(p)
    except OSError:
        pass
    return out


def _new_id():
    return "%s-%04x" % (time.strftime("%Y%m%d-%H%M%S"), random.randint(0, 0xffff))


def new_id():
    """先把 id 定下来（开工那一刻），这样"每步落盘"和"最后的正式记录"是同一个文件。"""
    return _new_id()


# ------------------------------------------------------------------ 写
def _write(path, rec):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)             # 原子替换：写一半断电也不会留半个文件


def save(rec, scope=None):
    """存一条（跑完那次）。回 `{ok, id}`（存不上也不抛 —— 干活要紧）。"""
    try:
        rec, moved = _rehome(rec)
        rec.setdefault("id", _new_id())
        rec.setdefault("finished", time.time())
        rec["running"] = False
        # ★ 被归位了就以**归位后的包**为准（调用方给的 scope 是"开工那一刻的包"）
        d = dir_path(rec.get("workdir") if moved
                     else (scope if scope is not None else rec.get("workdir")))
        d.mkdir(parents=True, exist_ok=True)
        _write(d / (rec["id"] + ".json"), rec)
        if moved:
            _drop_stale(rec["id"], d)
        _prune(d)
        return {"ok": True, "id": rec["id"], "dir": str(d)}
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "id": "", "msg": "%s: %s" % (type(e).__name__, e)}


def save_live(rec, scope=None):
    """**跑到一半也存**（`V-307`）：`running=true`，界面据此标「上次没跑完」。

    每一步写一次（几 KB，原子替换）—— 你强制重启那次丢的正是这条。
    """
    try:
        rec, moved = _rehome(rec)
        rid = str(rec.get("id") or "").strip()
        if not rid:
            return {"ok": False, "id": "", "msg": "没有 id"}
        rec["running"] = True
        rec.setdefault("started", time.time())
        rec["updated"] = time.time()
        d = dir_path(rec.get("workdir") if moved
                     else (scope if scope is not None else rec.get("workdir")))
        _write(d / (rid + ".json"), rec)
        if moved:
            _drop_stale(rid, d)
        return {"ok": True, "id": rid, "dir": str(d)}
    except Exception as e:                                            # noqa: BLE001
        return {"ok": False, "id": "", "msg": "%s: %s" % (type(e).__name__, e)}


def _prune(d):
    try:
        files = sorted(Path(d).glob("*.json"))
        for old in files[:-KEEP]:
            old.unlink(missing_ok=True)
    except OSError:
        pass


# ------------------------------------------------------------------ 读
def _load(path):
    try:
        got = json.loads(Path(path).read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else None
    except Exception:                                                 # noqa: BLE001
        return None


def _file_of(run_id, scope=None):
    rid = str(run_id or "").strip()
    if not rid:
        return None
    cand = [dir_path(scope)] if scope is not None else []
    cand += _all_dirs()
    seen = set()
    for d in cand:
        if str(d) in seen:
            continue
        seen.add(str(d))
        p = Path(d) / (rid + ".json")
        if p.is_file():
            return p
    return None


def _bucket_pkg_dir(d):
    """`state/<id>/ai/runs` ⇒ **那个包现在的目录**（认不出来就空串）。

    ★ `V-384`：包改过名之后，桶跟着 `--rename` 一起搬到了新 id 下，所以"桶名"
      就是**现在的** id —— 拿它去包根下找，就能把过期的 `workdir` 纠回来。
    """
    try:
        st = (E.user_data() / "state").resolve()
        parts = Path(d).resolve().relative_to(st).parts
    except (OSError, ValueError):
        return ""
    if not parts:
        return ""
    pid = parts[0]
    for root in (E.user_data() / "pkgs", E.HOME / "system" / "pkgs"):
        try:
            p = Path(root) / pid
        except OSError:
            continue
        if p.is_dir():
            return str(p)
    return ""


def _fix_workdir(rec, d):
    """记录里的 `workdir` 过期了（包改过名 / 目录搬过）⇒ **按桶**纠正回来。

    ★ `V-384`（你 2026-10-19 报的"改完名没有自动进入 AI 对话"里有这一半）：
      会话文件跟着 `--rename` 搬到了 `state/<新id>/ai/runs/`，可 JSON 里的 `workdir`
      还写着旧目录 ⇒ 界面按新目录去"认领这条会话"就认不上（历史列得出来、接不上）。
      `state/<id>/ai/runs/` 这个位置本身就说明"这是 <id> 的会话"，所以按桶纠正是对的。
    """
    wd = str(rec.get("workdir") or "")
    try:
        if wd and Path(wd).is_dir():
            return rec
    except OSError:
        pass
    now = _bucket_pkg_dir(d)
    if not now:
        return rec
    rec = dict(rec)
    rec["workdir"] = now
    rec["workdir_fixed"] = True
    return rec


def list_runs(limit=30, with_steps=False, scope=None, everywhere=False):
    """按时间倒序列出（默认**不带步骤流**，那个大；列表只需要一行摘要）。

    `scope`：只看这个桶（界面按"干活的地方"分会话就靠它）。
    `everywhere=True`：所有桶合起来看（排障 / 跨包找一条记录用）。
    """
    dirs = _all_dirs() if everywhere else [dir_path(scope)]
    rows = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.glob("*.json"):
            rec = _load(p)
            if not rec:
                continue
            rows.append(_fix_workdir(rec, d))
    rows.sort(key=lambda r: str(r.get("id") or ""), reverse=True)
    out = []
    for rec in rows[:max(1, int(limit or 30))]:
        row = {k: rec.get(k) for k in ("id", "task", "workdir", "ok", "reason", "summary",
                                       "caveats", "usage", "files", "snapshot", "seconds",
                                       # ★ `V-382`：快照没存上的原因（界面上要告一句"没退路"）
                                       "snapshot_note",
                                       "started_text", "finished", "model", "max_tokens",
                                       "kind", "stopped", "continued_from", "running",
                                       "updated")}
        row["cont"] = bool(rec.get("messages"))
        row["msgs"] = len(rec.get("messages") or [])
        row["steps"] = len(rec.get("steps") or [])
        # ★ `V-307`：**上次没跑完**（moss 被强制关掉 / 崩了）—— 界面要把它标出来，
        #   不能让它看起来像"跑完了但没结果"。
        row["interrupted"] = bool(rec.get("running"))
        if with_steps:
            row["steps_detail"] = rec.get("steps") or []
        out.append(row)
    return out


def get(run_id, scope=None):
    """读一条完整的（含步骤流）—— 界面上点「看」用它。"""
    p = _file_of(run_id, scope)
    if not p:
        return None
    rec = _load(p)
    return _fix_workdir(rec, p.parent) if rec else None


def messages(run_id, scope=None):
    """这条会话喂给模型的**完整提示词历史**（`V-307`：界面上「看提示词」用它）。

    回 `{ok, messages, task, at, model, count, bytes, note}`。
    ★ 老记录（`V-251` 之前）没存 `messages` —— 那时候只有步骤流，如实说，别装作有。
    """
    rec = get(run_id, scope) or {}
    msgs = [m for m in (rec.get("messages") or []) if isinstance(m, dict)]
    blob = json.dumps(msgs, ensure_ascii=False)
    return {"ok": bool(msgs), "messages": msgs, "task": rec.get("task") or "",
            "at": rec.get("started_text") or "", "model": rec.get("model") or "",
            "count": len(msgs), "bytes": len(blob.encode("utf-8")),
            "note": "" if msgs else "这条是更早的记录 —— 那时候还没存对话，接不上",
            "workdir": rec.get("workdir") or "", "id": str(run_id or "")}


def delete(run_id, scope=None):
    p = _file_of(run_id, scope)
    try:
        if p:
            p.unlink(missing_ok=True)
        return {"ok": True}
    except OSError as e:
        return {"ok": False, "msg": str(e)}


def clear(scope=None):
    """清空（界面上给一颗"清空历史"，删前自己确认）。不给 scope = 清这个桶。"""
    n = 0
    d = dir_path(scope)
    try:
        if d.is_dir():
            for p in d.glob("*.json"):
                p.unlink(missing_ok=True)
                n += 1
    except OSError:
        pass
    return {"ok": True, "removed": n, "dir": str(d)}


# ------------------------------------------------------------------ 老记录归位
def migrate_once():
    """把老的 `user_data/ai/runs/*.json` 按 `workdir` 搬进各自的包目录（只搬一次）。

    判据是 `user_data/ai/.runs_scoped` 这个记号文件；搬完写它。**搬不动的原地不动**
    （读的时候 `_all_dirs()` 也认老地方，所以搬失败不影响使用）。
    """
    ud = E.user_data()
    marker = ud / "ai" / ".runs_scoped"
    if marker.exists():
        return {"ok": True, "skipped": True, "moved": 0}
    src = ud / "ai" / "runs"
    moved, failed = 0, 0
    try:
        if src.is_dir():
            for p in list(src.glob("*.json")):
                rec = _load(p)
                if not rec:
                    continue
                pid = pkg_of(rec.get("workdir"))
                if not pid:
                    continue
                dst = ud / "state" / pid / "ai" / "runs" / p.name
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists():
                        shutil.move(str(p), str(dst))
                    else:
                        p.unlink(missing_ok=True)
                    moved += 1
                except OSError:
                    failed += 1
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("%s\nmoved=%d failed=%d\n" % (
                time.strftime("%Y-%m-%d %H:%M:%S"), moved, failed), encoding="utf-8")
        except OSError:
            pass
    except OSError:
        pass
    return {"ok": True, "skipped": False, "moved": moved, "failed": failed}
