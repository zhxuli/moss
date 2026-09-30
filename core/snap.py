# -*- coding: utf-8 -*-
"""moss · **版本快照**的命令行（`V-100`）—— 一条给人和 AI 用的备份 / 恢复通道。

为什么要有它（你 2026-09-30 的原话）：「我们这个版本快照功能 必须得支持命令行 这是我们为后面
接入AI系统 做的前期准备 方便AI能备份 恢复的 防止把项目改崩掉」。

★ 底层**直接用界面那一份存储**（`system/ui/backup.py` 的 `BackupStore`）—— 一份实现两处用，
  不在 CLI 里重写第二遍"内容寻址 + 标记清除回收"。那个文件**没有编进 exe**（`K-10`：只编 `core/`），
  所以以后改存储逻辑不用重打包；但**加这条命令本身要重打包**（`tools/build.py`）。
★ 语义照 `V-92` 定的"向 git 看齐"：
    `restore`            = `git restore`：缺的补上、不一样的回退（覆盖前留 `.bak`），多出来的**不动**
    `restore --sync`     = `git reset --hard` / `clean`：连多出来的也挪进回收站（不真删）
★ 给 AI 的两条安全约束（你自己也认过）：
    ① 会改文件 / 删东西的动作**没有 `--yes` 一律不执行**（只把"会干什么"打出来）；
    ② 退出码分档，别让 AI 去猜中文输出：
        0 成功 / 2 用法错（含"缺 --yes"）/ 3 没有可做的东西 / 4 执行出错
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

from . import out
from . import paths

TRASH_DIRNAME = "trash"
MAX_SCAN_FILES = 20000          # 超过这个数就要求 --yes（防止有人对着一个大目录按下去）
EXIT_OK, EXIT_USE, EXIT_NOTHING, EXIT_FAIL = 0, 2, 3, 4


# ---------------------------------------------------------------- 根 / rel / 回收站
def _roots():
    """两个真根：`user/` = `user_data`，`system/` = 安装目录下那个 `system/`。"""
    return [("user", paths.USER_DIR), ("system", paths.SYSTEM_DIR)]


def _rel_of(path):
    p = Path(path)
    try:
        p = p.resolve()
    except OSError:
        pass
    for key, root in _roots():
        try:
            return key + "/" + p.relative_to(root.resolve()).as_posix()
        except ValueError:
            continue
    # 根外面（`abs/`）：和界面同一条规则，只是 CLI 这边很少用到
    return "abs/" + p.as_posix().lstrip("/")


def _resolve(rel):
    rel = str(rel or "").replace("\\", "/").strip().strip("/")
    key, _, sub = rel.partition("/")
    if key == "abs":
        return Path(sub.replace("/", os.sep))
    for k, root in _roots():
        if k == key:
            return (root / sub.replace("/", os.sep)) if sub else root
    raise ValueError("不认识的根 '%s'（只允许 user / system / abs）" % key)


def _trash(path):
    """挪进 `user_data/trash/<时间戳>/…`（不真删）—— 和界面同一个目的地。"""
    rel = _rel_of(path).replace(":", "")
    dest = paths.USER_DIR / TRASH_DIRNAME / time.strftime("%Y%m%d-%H%M%S") / Path(rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    n = dest
    i = 1
    while n.exists():
        n = dest.with_name(dest.name + "-%d" % i)
        i += 1
    shutil.move(str(path), str(n))
    return str(n)


def _store():
    """把界面那份 `BackupStore` 拉进来（同一个实现，不抄第二遍）。"""
    ui = str(paths.SYSTEM_DIR / "ui")
    if ui not in sys.path:
        sys.path.insert(0, ui)
    import backup as _b                                              # noqa: PLC0415
    return _b


# ---------------------------------------------------------------- 小工具
def _j(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024
    return "%d B" % n


def _flatten(argv):
    """把 `--k v` / `--k=v` / `--flag` 拆成 (位置参数, 选项字典, 开关集合)。"""
    pos, opt, flag = [], {}, set()
    FLAGS = {"--json", "--sync", "--yes", "-y", "--all", "--keep-bak", "--help", "-h"}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--") and "=" in a:
            k, _, v = a.partition("=")
            opt[k] = v
        elif a in FLAGS:
            flag.add("--yes" if a == "-y" else a)
        elif a.startswith("--"):
            if i + 1 >= len(argv):
                raise ValueError("%s 后面缺一个值" % a)
            opt[a] = argv[i + 1]
            i += 1
        else:
            pos.append(a)
        i += 1
    return pos, opt, flag


def _group_of(rels, opt):
    """这一组叫什么：`--group` 优先；不然按来源猜（和界面同一个规则）。"""
    if opt.get("--group"):
        return opt["--group"]
    b = _store()
    return b.group_for_sources([r for r in rels if r])


def _need_yes(flag, what):
    if "--yes" in flag:
        return True
    out.print_cyan("这步会真的动磁盘：%s" % what)
    out.print_cyan("确认要干就再加一个 --yes（AI 调用也必须显式给，免得误改）："
                   "moss --snap … --yes")
    return False


# ---------------------------------------------------------------- 差异（`V-94` 那套语义）
def _diff(b, st, bid, group, rel=""):
    """把"这次快照"和"现在"在同一个目录下比一比：一致 / 变了 / 只有快照有 / 只有现在有 / 空。
    左边 = 现在（磁盘），右边 = 快照。和界面上那套颜色是**同一套判定**：
    先比大小（便宜），大小一样才比指纹。"""
    m = st.manifest(bid, group)
    pfx = (rel or "").strip("/")
    pfx = (pfx + "/") if pfx else ""
    snap_files, snap_dirs = {}, {}
    for e in (m.get("files") or []):
        r = str(e.get("rel") or "")
        if pfx and not r.startswith(pfx):
            continue
        rest = r[len(pfx):]
        if not rest:
            continue
        if "/" in rest:
            d = rest.split("/", 1)[0]
            snap_dirs[d] = snap_dirs.get(d, 0) + (e.get("size") or 0)
        else:
            snap_files[rest] = e
    for d in (m.get("empty_dirs") or []):
        r = str(d or "")
        if pfx and not r.startswith(pfx):
            continue
        rest = r[len(pfx):]
        if rest and "/" not in rest:
            snap_dirs.setdefault(rest, 0)

    base = _resolve(pfx.rstrip("/")) if pfx else None
    now = {}
    if base is not None and base.is_dir():
        for c in sorted(base.iterdir()):
            # ★ `V-110`：**这里也要套过滤规则** —— 不套的话，被排除的东西（`__pycache__`、
            #   `*.tmp`、`venv/`…）会被当成"现在多出来的"显示出来（你实测那条 `+ __pycache__/`）。
            #   配 `--sync` 更糟：会把它当"多的"挪进回收站。和存储那边的 `_extras` 同一个坑。
            try:
                if st._skip_dir_name(c.name, is_dir=c.is_dir()) or st._skip_rel(_rel_of(c)):
                    continue
            except Exception:                                       # noqa: BLE001
                pass
            now[c.name] = c
    rows = []
    names = sorted(set(list(now.keys()) + list(snap_files.keys()) + list(snap_dirs.keys())))
    for n in names:
        cur, sf, sd = now.get(n), snap_files.get(n), snap_dirs.get(n)
        in_snap = (sf is not None) or (sd is not None)
        cur_dir = bool(cur is not None and cur.is_dir())
        now_size = None
        if cur is not None and not cur_dir:
            try:
                now_size = cur.stat().st_size
            except OSError:
                now_size = None
        snap_size = (sf.get("size") or 0) if sf is not None else sd
        if cur is not None and in_snap:
            if cur_dir or sf is None:
                state = "same" if now_size is None else ("same" if now_size == snap_size else "diff")
                deep = "" if state == "same" else ("now" if (now_size or 0) > (snap_size or 0) else "snap")
            elif now_size != snap_size:
                state, deep = "diff", ("now" if now_size > snap_size else "snap")
            else:
                state, deep = "same", ""
                try:
                    if b.hash_file(cur)[0] != (sf.get("fp") or ""):
                        state = "diff"
                except Exception:                                   # noqa: BLE001
                    pass
        elif cur is not None:
            state, deep = "now-only", ""
        else:
            state, deep = "snap-only", ""
        if state == "same" and not cur_dir and now_size == 0:
            state = "empty"
        rows.append({"name": n, "dir": cur_dir or (sd is not None),
                     "state": state, "deep": deep, "now": now_size, "snap": snap_size})
    rows.sort(key=lambda r: (not r["dir"], r["name"]))
    return {"ok": True, "group": group, "id": bid, "title": m.get("title") or bid,
            "rel": pfx.rstrip("/"), "rows": rows,
            "counts": {k: sum(1 for r in rows if r["state"] == k)
                       for k in ("same", "diff", "snap-only", "now-only", "empty")}}


# ---------------------------------------------------------------- 子命令
def _cmd_list(opt, flag):
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    g = opt.get("--group") or ""
    js = "--json" in flag
    if g:
        items = st.list_backups(g)
        if js:
            print(_j({"ok": True, "group": g, "items": items, "stat": st.stat(g)}))
        else:
            if not items:
                out.print_cyan("「%s」还没有快照。" % g)
            for it in items:
                print("  %-24s %-10s %s  %s" % (it.get("id"), _size(it.get("bytes")),
                                                (it.get("title") or "")[:40],
                                                (it.get("created_text") or "")[5:19]))
        return EXIT_OK
    rows = st.groups_summary()
    if js:
        print(_j({"ok": True, "groups": rows}))
    else:
        if not rows:
            out.print_cyan("备份库里还没有快照（moss --snap save 存一个）。")
        for r in rows:
            print("  %-24s %3d 次  %9s  %s" % (r.get("group"), r.get("backups") or 0,
                                               _size(r.get("bytes")), r.get("last") or ""))
    return EXIT_OK


def _cmd_save(pos, opt, flag, subj_srcs=()):
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    # ★ `create()` 要的是**绝对路径**（它自己再算 rel）—— 我第一版把 rel 传进去了，
    #   于是它去 walk 一个不存在的相对路径 ⇒ 存出来是个**空快照**（diff 里全是"我有多"）。
    srcs = list(subj_srcs) or [str(Path(p).resolve()) for p in (pos or [str(Path.cwd())])]
    # ★ 先说话再干活（你实测"没反应"就是这个）：大目录要哈希很久，一声不吭看着就是卡死。
    out.print_cyan("正在扫描 %d 个来源…（大目录会慢，先数一遍文件）" % len(srcs))
    n_files = 0
    for sp in srcs:
        for _cur, _dirs, _names in os.walk(sp):
            n_files += len(_names)
            if n_files > MAX_SCAN_FILES:
                break
        if n_files > MAX_SCAN_FILES:
            break
    if n_files > MAX_SCAN_FILES and "--yes" not in flag:
        out.print_cyan("这个范围太大了（已经数到 %d 个文件以上）——大概率不是你想要的。"
                       "要真存就加 --yes，或者换个目录 / 用 `moss --snap save :<包名>`。"
                       % MAX_SCAN_FILES)
        return EXIT_USE
    out.print_cyan("开始存快照（扫到 %d 个文件，按过滤规则挑着存）…" % n_files)
    rels = [_rel_of(Path(s)) for s in srcs]
    g = _group_of(rels, opt)
    try:
        m = st.create(srcs, opt.get("--title") or "", opt.get("--note") or "", group=g)
    except Exception as e:                                          # noqa: BLE001
        out.print_cyan("[错误] 存快照失败：%s" % e)
        return EXIT_FAIL
    tag = opt.get("--tag") or ""
    if tag:
        t = _load_tags(st, g)
        t[str(tag)] = m.get("id")
        _save_tags(st, g, t)
    if "--json" in flag:
        print(_j({"ok": True, "id": m.get("id"), "group": m.get("group"),
                  "title": m.get("title"), "tag": tag or None, "stats": m.get("stats")}))
    else:
        s = m.get("stats") or {}
        out.print_cyan("快照已存：%s（%s）—— %s 个文件、%s；新增 %s 块"
                       % (m.get("id"), m.get("group"), s.get("files", 0),
                          _size(s.get("bytes")), s.get("new_objects", 0)))
    return EXIT_OK



def _subject(ref, table=None):
    """`--snap` 的"对象"：可以给**插件名**（`:md5` 或 `md5`），也可以给路径。

    ★ 为什么要有它（你 2026-09-30 问的）："你要备份和恢复某个插件 你命令里面得有插件的名字吧
      但是我看到 你并没有在命令里面 放插件的名字"。对 —— 第一版只能按路径/`--group` 推，
      用起来别扭；现在 `moss --snap save :md5` 这样写，和 `moss :md5` / `moss --remove :md5` 一个习惯。
    给插件名时：**组 = 包 id**，来源 = 包目录 + 它自己的数据目录（和界面 `bkScopeRels()` 同一套）。"""
    ref = str(ref or "").strip()
    if not ref:
        return None, []
    looks_path = ("/" in ref or "\\" in ref or ref in (".", "..") or Path(ref).exists())
    if not looks_path:
        from . import registry
        rec = registry.find_alias(ref[1:] if ref.startswith(":") else ref)
        if rec:
            pid = rec["id"]
            srcs = [str(c) for c in (paths.USER_PKGS / pid, paths.SYSTEM_PKGS / pid) if c.is_dir()]
            st = paths.pkg_state_dir(pid)
            if st.is_dir():
                srcs.append(str(st))
            if srcs:
                return pid, srcs
    return None, [ref]

def _pick(b, st, key, group):
    """`<id>` / `latest` / 省略 ⇒ 最近那一次。★ 存储里没有 `find()`：id 靠 `ids()` 找，
    `latest` 得先知道是哪一组（给了 `--group`，或者当前目录能猜出组）。"""
    g = group or None
    key = str(key or "")
    if key and key not in ("latest", "last"):
        if g and key in st.ids(g):
            return key, g
        tg, tid = _find_tag(st, key)                # ★ `V-107` C：先当**标签**找
        if tid:
            return tid, (g or tg)
        for gg in st.groups():                      # 再当 id 全库找一遍
            if key in st.ids(gg):
                return key, (g or gg)
        return None, g
    if not g:
        # 没给组：拿当前目录猜（在某个包里跑 `--snap diff latest` 是最常见的用法）
        try:
            g = _group_of([_rel_of(Path.cwd())], {})
        except Exception:                                           # noqa: BLE001
            g = None
    if not g:
        return None, None
    ids = st.ids(g)
    return (ids[0] if ids else None), g


def _cmd_show(pos, opt, flag):
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    bid, g = _pick(b, st, pos[0] if pos else "", opt.get("--group") or "")
    if not bid:
        out.print_cyan("[错误] 没找到这次快照（用 moss --snap list 看有哪些）。")
        return EXIT_NOTHING
    m = st.manifest(bid, g)
    if "--json" in flag:
        print(_j(m))
        return EXIT_OK
    print("%s  %s  %s" % (m.get("id"), m.get("title") or "", m.get("created_text") or ""))
    for e in (m.get("files") or []):
        print("  %-10s %s" % (_size(e.get("size")), e.get("rel")))
    return EXIT_OK


def _cmd_diff(pos, opt, flag):
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    bid, g = _pick(b, st, pos[0] if pos else "", opt.get("--group") or "")
    if not bid:
        out.print_cyan("[错误] 没找到这次快照。")
        return EXIT_NOTHING
    rel = opt.get("--rel") or ""
    if pos[1:]:
        rel = _rel_of(Path(pos[1]))
    if not rel:
        # 没给目录就按当前目录猜；猜不出来（在仓库根那种"根外面"）就用快照自己的第一个来源
        cand = _rel_of(Path.cwd())
        rel = cand if cand.startswith(("user/", "system/")) else ""
    if not rel:
        rel = ((st.manifest(bid, g).get("sources") or [""])[0])
    d = _diff(b, st, bid, g, rel)
    if "--json" in flag:
        print(_j(d))
        return EXIT_OK
    print("%s  %s  ← 现在 vs 快照（%s）" % (d["id"], d["rel"] or "（根）", d["title"]))
    for r in d["rows"]:
        mark = {"same": "  ", "diff": "≠ ", "snap-only": "- ", "now-only": "+ ",
                "empty": "· "}[r["state"]]
        nowtxt = "—" if r["now"] is None else _size(r["now"])
        print("  %s%-28s %10s / %10s" % (mark, r["name"] + ("/" if r["dir"] else ""),
                                          nowtxt, _size(r["snap"])))
    c = d["counts"]
    out.print_cyan("一致 %d · 变了 %d · 快照有我没了 %d · 我有多 %d · 空 %d"
                   % (c["same"], c["diff"], c["snap-only"], c["now-only"], c["empty"]))
    return EXIT_OK


def _cmd_restore(pos, opt, flag):
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    bid, g = _pick(b, st, pos[0] if pos else "", opt.get("--group") or "")
    if not bid:
        out.print_cyan("[错误] 没找到这次快照。")
        return EXIT_NOTHING
    sync = "--sync" in flag
    only = opt.get("--only") or "changed"
    plan = st.plan(bid, None, only, sync=True, group=g)
    c = plan.get("counts") or {}
    if not (c.get("overwrite") or c.get("create") or c.get("extra")):
        out.print_cyan("不用恢复：现在和这次快照已经一样了。")
        return EXIT_NOTHING
    extra = c.get("extra") or 0
    if not _need_yes(flag, "%s：补 %d、回退 %d、跳过 %d%s"
                     % (plan.get("title") or bid, c.get("create") or 0,
                        c.get("overwrite") or 0, c.get("skip") or 0,
                        ("、挪走 %d（进回收站）" % extra) if (sync and extra) else "")):
        return EXIT_USE
    r = st.restore(bid, None, only, sync=sync, group=g)
    if "--json" in flag:
        print(_j(r))
    else:
        cc = r.get("counts") or {}
        out.print_cyan("恢复完：补 %s · 挪走 %s%s"
                       % (cc.get("restored", 0), cc.get("trashed", 0),
                          (" · 出错 %s" % cc.get("errors")) if cc.get("errors") else ""))
    return EXIT_OK if not (r.get("counts") or {}).get("errors") else EXIT_FAIL


def _cmd_export(pos, opt, flag):
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    if len(pos) < 2:
        out.print_cyan("[错误] 用法：moss --snap export <id|latest> <目标目录>")
        return EXIT_USE
    bid, g = _pick(b, st, pos[0], opt.get("--group") or "")
    if not bid:
        out.print_cyan("[错误] 没找到这次快照。")
        return EXIT_NOTHING
    target = opt.get("--to") or pos[1]
    if not _need_yes(flag, "往 %s 写文件（原文件不动）" % target):
        return EXIT_USE
    r = st.export(bid, target, keep_bak=("--keep-bak" in flag), group=g)
    if "--json" in flag:
        print(_j(r))
    else:
        out.print_cyan("导出 %s 个文件 → %s" % ((r.get("counts") or {}).get("written", 0), r.get("root")))
    return EXIT_OK


def _cmd_rm(pos, opt, flag):
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    g = opt.get("--group") or ""
    if "--all" in flag:
        if not g:
            out.print_cyan("[错误] --all 要配 --group <包id>（删整组）。")
            return EXIT_USE
        info = st.stat(g)
        if not _need_yes(flag, "删掉「%s」的**全部**快照（%s 次、%s）"
                               % (g, info.get("backups", 0), _size(info.get("store_bytes")))):
            return EXIT_USE
        r = st.drop_group(g)
        out.print_cyan(r.get("msg") or "删完了")
        return EXIT_OK
    bid, g = _pick(b, st, pos[0] if pos else "", g)
    if not bid:
        out.print_cyan("[错误] 没找到这次快照。")
        return EXIT_NOTHING
    if not _need_yes(flag, "删掉快照 %s（没人引用的内容块一并回收）" % bid):
        return EXIT_USE
    r = st.delete(bid, g)
    out.print_cyan("已删掉（回收 %s 块）" % r.get("removed", 0))
    return EXIT_OK


def _cmd_gc(opt, flag):
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    g = opt.get("--group") or ""
    pre = st.gc(True, g)
    if not pre.get("removed"):
        out.print_cyan("没有可回收的内容块。")
        return EXIT_NOTHING
    if not _need_yes(flag, "回收 %s 块没人引用的内容（约 %s）"
                           % (pre.get("removed"), _size(pre.get("freed")))):
        return EXIT_USE
    r = st.gc(False, g)
    out.print_cyan(r.get("msg") or "清理完了")
    return EXIT_OK



def _find_in(b, st, bid, group, want):
    """在清单里找一条：先当**完整 rel** 比，再当**结尾**比（`pkg.json` 这种短写法也认）。
    返回 (rel, fp, size) 或 None。"""
    m = st.manifest(bid, group)
    want = str(want or "").replace("\\", "/").strip("/")
    files = m.get("files") or []
    hit = next((e for e in files if str(e.get("rel") or "") == want), None)
    if hit is None:
        tail = "/" + want if want else ""
        cands = [e for e in files if tail and str(e.get("rel") or "").endswith(tail)]
        if len(cands) == 1:
            hit = cands[0]
        elif len(cands) > 1:
            return {"err": "有 %d 个文件都以 '%s' 结尾，写全一点：%s"
                           % (len(cands), want, " / ".join(str(e.get("rel")) for e in cands[:6]))}
    if hit is None:
        return None
    return {"rel": hit.get("rel"), "fp": hit.get("fp"), "size": hit.get("size") or 0}




# ---------------------------------------------------------------- 标签（`V-107` C）
def _tags_file(st, g):
    return st.group_dir(g) / "tags.json"


def _load_tags(st, g):
    """一个组的标签：`{标签: 快照id}`。坏文件当空（不让它拦住备份这件事）。"""
    try:
        f = _tags_file(st, g)
        if f.is_file():
            d = json.loads(f.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:                                                   # noqa: BLE001
        pass
    return {}


def _save_tags(st, g, d):
    try:
        f = _tags_file(st, g)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, f)
    except Exception as e:                                              # noqa: BLE001
        out.print_cyan("⚠ 标签没能写下来：%s" % e)


def _find_tag(st, name):
    for g in st.groups():
        t = _load_tags(st, g)
        if name in t:
            return g, t[name]
    return None, None


def _cmd_tags(pos, opt, flag):
    """`moss --snap tags [对象]` —— 看钉过哪些标签。"""
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    g = opt.get("--group") or ""
    outd = {}
    for gg in ([g] if g else st.groups()):
        t = _load_tags(st, gg)
        if t:
            outd[gg] = t
    if "--json" in flag:
        print(_j(outd))
        return EXIT_OK
    if not outd:
        out.print_cyan("还没有标签（存的时候加 `--tag 名字` 就钉一个）。")
        return EXIT_NOTHING
    for gg, t in outd.items():
        print("  %s" % gg)
        for k, v in t.items():
            print("    %-18s → %s" % (k, v))
    return EXIT_OK

def _split_id(pos, group):
    """`cat` / `ls` 的位置参数怎么理解：第一个要是 **id / latest** 就当 id，否则当**路径**，
    快照取"最近那一次" —— 插件名已经被 `cmd_snap` 拿掉了，`cat :md5 pkg.json` 到这儿只剩
    `pkg.json`，那是**路径**不是 id（第一版就是这么错的：它去找一个叫 "pkg.json" 的快照）。"""
    if pos and (str(pos[0]) in ("latest", "last") or re.match(r"^\d{8}-\d{6}-", str(pos[0]))):
        return pos[0], pos[1:]
    return "latest", pos

def _cmd_cat(pos, opt, flag):
    """`moss --snap cat <对象> <快照里的路径>` —— **吐出内容**（不是路径）。

    ★ 为什么给内容、不给"真实路径"（你问的那个）：① AI 要的是"这个文件当时写了什么"，
      内容一到手就能对着现在的版本比、就知道包是怎么废的；② **备份库里的东西是"按指纹命名"的**
      （`objects/<前两位>/<指纹>`），把那个内部路径交给 AI 等于把**只读资产**变成一个可写目标 ——
      它一改，那次快照就废了。吐内容这条路**天生不给可写目标**。
    ★ 真要落到磁盘（人要拿走一份）也行：`--save-to <目录>`，而且要 `--yes`（和 export 同规矩）。"""
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    key, rest = _split_id(pos, opt.get("--group") or "")
    bid, g = _pick(b, st, key, opt.get("--group") or "")
    if not bid:
        out.print_cyan("[错误] 没找到这次快照（moss --snap list 看有哪些）。")
        return EXIT_NOTHING
    if not rest:
        out.print_cyan("[错误] 用法：moss --snap cat <对象> <快照里的路径>")
        return EXIT_USE
    got = _find_in(b, st, bid, g, rest[0])
    if got is None:
        out.print_cyan("[错误] 这次快照里没有 '%s'（moss --snap ls 看有哪些）。" % pos[1])
        return EXIT_NOTHING
    if isinstance(got, dict) and got.get("err"):
        out.print_cyan("[错误] %s" % got["err"])
        return EXIT_USE
    r = st.read_blob(got["fp"], group=g)
    if not r.get("ok"):
        out.print_cyan("[错误] 读不出来：%s" % r.get("msg"))
        return EXIT_FAIL
    if opt.get("--save-to"):
        if not _need_yes(flag, "把这一份写到 %s（原快照不动）" % opt["--save-to"]):
            return EXIT_USE
        dest = Path(opt["--save-to"]) / Path(str(got["rel"]).replace("/", os.sep)).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((r.get("text") or "").encode("utf-8") if not r.get("binary") else b"")
        out.print_cyan("写好了：%s" % dest)
        return EXIT_OK
    if "--json" in flag:
        print(_j({"ok": True, "id": bid, "group": g, "rel": got["rel"], "fp": got["fp"],
                  "size": got["size"], "binary": bool(r.get("binary")),
                  "truncated": bool(r.get("truncated")), "text": r.get("text")}))
        return EXIT_OK
    if r.get("binary"):
        out.print_cyan("（二进制文件：%s，指纹 %s；要原样拿走用 --save-to <目录> --yes）"
                       % (_size(got["size"]), got["fp"]))
        return EXIT_OK
    sys.stdout.write(r.get("text") or "")
    if r.get("truncated"):
        out.print_cyan("\n…（太长，截断了；要全的要 --save-to <目录> --yes）")
    return EXIT_OK


def _cmd_ls(pos, opt, flag):
    """`moss --snap ls <对象> [目录]` —— 列这次快照里有什么（**路径**，只读）。"""
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    key, rest = _split_id(pos, opt.get("--group") or "")
    bid, g = _pick(b, st, key, opt.get("--group") or "")
    if not bid:
        out.print_cyan("[错误] 没找到这次快照。")
        return EXIT_NOTHING
    pfx = str(rest[0]).replace(chr(92), "/").strip("/") if rest else ""
    m = st.manifest(bid, g)
    rows = [e for e in (m.get("files") or [])
            if not pfx or str(e.get("rel") or "").startswith(pfx + "/") or str(e.get("rel")) == pfx]
    if "--json" in flag:
        print(_j({"ok": True, "id": bid, "group": g, "rel": pfx, "files": rows,
                  "empty_dirs": m.get("empty_dirs") or []}))
        return EXIT_OK
    if not rows:
        out.print_cyan("这次快照里没有 %s 下的东西。" % (pfx or "任何"))
        return EXIT_NOTHING
    for e in rows:
        print("  %-10s %s" % (_size(e.get("size")), e.get("rel")))
    return EXIT_OK


def _cmd_check(pos, opt, flag):
    """`moss --snap check [对象]` —— 把内容块按**指纹**逐个验一遍。

    ★ 这一条就是"怎么防止 AI 把备份改坏"的答案：备份库里的内容是**按指纹命名**的，
      谁改了一个字节，指纹就对不上 —— `check` 当场指出来（退出码 4）。改坏了**看得见**，
      比"悄悄坏了、等真要恢复时才发现"强得多。"""
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    g = opt.get("--group") or ""
    bid = None
    if pos:
        bid, g = _pick(b, st, pos[0], g)
        if not bid:
            out.print_cyan("[错误] 没找到这次快照。")
            return EXIT_NOTHING
    r = st.check(bid, g or None)
    rows = r.get("rows") or []
    if "--json" in flag:
        print(_j(r))
    else:
        for x in rows:
            bad = x.get("broken") or x.get("missing")
            print("  %-24s %s" % (x.get("id"), "坏" if x.get("broken") else
                                  ("缺 %s 块" % x.get("missing") if x.get("missing") else "好")))
    # ★ `V-102`：`st.check()` 只答“缺没缺”；**“被改过”得自己把内容块再哈希一遍跟指纹比**。
    #   这就是“AI 把备份改坏了看得见”的那条保证 —— 内容块是**按指纹命名**的，改一个字节就对不上。
    tampered = []
    for x in ([bid] if bid else st.ids(g or None)):
        try:
            m = st.manifest(x, g or None)
        except Exception:                                           # noqa: BLE001
            continue
        gg = m.get("group") or g
        for e in (m.get("files") or []):
            fp = e.get("fp")
            if not fp:
                continue
            try:
                p = st.object_path(gg, fp)
                if (not p.is_file()) or b.hash_file(p)[0] != fp:
                    tampered.append({"id": x, "fp": fp, "rel": e.get("rel")})
            except Exception:                                       # noqa: BLE001
                tampered.append({"id": x, "fp": fp, "rel": e.get("rel")})
    bad = [x for x in rows if x.get("broken") or x.get("missing")]
    if "--json" in flag:
        print(_j({"ok": not (bad or tampered), "rows": rows, "tampered": tampered}))
    if bad or tampered:
        if tampered:
            out.print_cyan("⚠ 有 %d 个内容块**内容和指纹对不上**（被改过）：%s"
                           % (len(tampered),
                              " / ".join(str(t.get("rel")) for t in tampered[:5])))
        out.print_cyan("⚠ 有 %d 次快照的内容块对不上（被改过或者丢了）。" % max(len(bad), 1))
        return EXIT_FAIL
    out.print_cyan("校验通过：%d 次快照的内容块都在、指纹都对得上。" % len(rows))
    return EXIT_OK


def _cmd_ignore(opt, flag):
    """`moss --snap ignore` —— **告诉用户"快照会按什么规则过滤"**：文件在哪、现在生效哪些。

    为什么要这条命令：过滤是"看不见的行为"（文件被悄悄排掉了，用户会以为快照漏了东西）。
    所以除了写进 `--snap --help`，还要有一条"你随时能问"的命令。"""
    b = _store()
    f = paths.USER_DIR / b.IGNORE_NAME
    user = []
    if f.is_file():
        try:
            user = b.parse_ignore(f.read_text(encoding="utf-8", errors="replace"))
        except Exception:                                           # noqa: BLE001
            user = []
    builtin = list(b.DEFAULT_EXCLUDES) + ["/" + p for p in b.PATH_EXCLUDES]
    if "--json" in flag:
        print(_j({"ok": True, "path": str(f), "exists": f.is_file(),
                  "user": user, "builtin": builtin}))
        return EXIT_OK
    print("快照过滤规则：")
    print("  你的规则文件：%s%s" % (f, "" if f.is_file() else "（还没有；第一次存快照时会自动生成模板）"))
    if user:
        for r in user:
            print("    %s" % r)
    else:
        print("    （空的 —— 现在只按内置那几条排）")
    print("  内置（永远生效，改不掉）：%s" % " / ".join(builtin))
    print("  兼容（和 .gitignore 一个意思）：")
    print("    *.log          按名字（任意层级的同名文件/目录）")
    print("    build/         末尾带 / = 只排目录（连带里面的东西）")
    print("    ?ache          一个字符（? = 一个非 / 字符）")
    print("    **/deep.txt    任意层级下的 deep.txt（** 跨目录）")
    print("    logs/**        某个目录下的全部（含子目录）")
    print("    /user/state/tmp  开头带 / = 从 user_data 根锚定")
    print("    user/pkgs/old/   中间带 / 的按相对 user_data 的路径")
    print("    !keep.log      反向保留（前面被排掉的，这个要回来）")
    print("    [0-9]*.tmp     方括号字符集      # 注释、空行忽略")
    print("  不兼容（我们没照 git 做，别指望）：")
    print("    · 子目录里各自的 .gitignore 继承（只有 snapshot.ignore 这一个文件）")
    print("    · 转义写法（\\#、\\!）没法排一个真的以 # 开头的名字")
    print("    · 大小写敏感 —— 我们一律不区分大小写")
    print("    · git 那条「被排掉的目录里不能再 ! 放回来」—— 我们允许放回来（更宽松）")
    return EXIT_OK


def _cmd_revert(pos, opt, flag):
    """`moss --snap revert <对象> [id|标签]` —— **一键「对比 + 回退」**（AI 最常用的动作）。

    ① 先算差异、逐条打出「比这次快照变了什么」；
    ② 再按 `git restore` 那套对齐：缺的补上、不一样的回退（覆盖前留 `.bak`），**多出来的不动**
       （要「一模一样」加 `--sync`：多出来的挪进回收站）；
    ③ 不带 `--yes` 只打印（会动磁盘的动作都这个规矩）。"""
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    gg0 = opt.get("--group") or ""
    tg, tid = _find_tag(st, str(pos[0])) if pos else (None, None)
    if tid:
        bid, g, rest = tid, (gg0 or tg), pos[1:]
    else:
        key, rest = _split_id(pos, gg0)
        bid, g = _pick(b, st, key, gg0)
    if not bid:
        out.print_cyan("[错误] 没找到这次快照（moss --snap list 看有哪些）。")
        return EXIT_NOTHING
    rel = rest[0] if rest else ""
    if not rel:
        cand = _rel_of(Path.cwd())
        rel = cand if cand.startswith(("user/", "system/")) else ""
    if not rel:
        rel = ((st.manifest(bid, g).get("sources") or [""])[0])
    d = _diff(b, st, bid, g, rel)
    changed = [r for r in d["rows"] if r["state"] != "same"]
    print("回退到：%s  %s  ← 现在 vs 快照（%s）" % (d["id"], d["rel"] or "（根）", d["title"]))
    if not changed:
        out.print_cyan("和这次快照一模一样，不用回退。")
        return EXIT_NOTHING
    for r in changed:
        mark = {"diff": "≠ ", "snap-only": "- ", "now-only": "+ ", "empty": "· "}[r["state"]]
        print("  %s%-28s %10s / %10s" % (mark, r["name"] + ("/" if r["dir"] else ""),
                                          _size(r["now"]), _size(r["snap"])))
    sync = "--sync" in flag
    plan = st.plan(bid, None, "changed", sync=True, group=g)
    pc = plan.get("counts") or {}
    out.print_cyan("要动的：补 %s · 回退 %s · 跳过 %s%s"
                   % (pc.get("create", 0), pc.get("overwrite", 0), pc.get("skip", 0),
                      (" · 挪走 %s（进回收站）" % pc.get("extra", 0)) if sync else ""))
    if "--yes" not in flag:
        out.print_cyan("确认就再加一个 --yes（要「一模一样」再加 --sync：多出来的挪进回收站）")
        return EXIT_USE
    r = st.restore(bid, None, "changed", sync=sync, group=g)
    cc = r.get("counts") or {}
    if "--json" in flag:
        print(_j({"ok": True, "id": bid, "group": g, "counts": cc, "changed": changed}))
    else:
        out.print_cyan("回退完：补 %s · 挪走 %s%s"
                       % (cc.get("restored", 0), cc.get("trashed", 0),
                          (" · 出错 %s" % cc.get("errors")) if cc.get("errors") else ""))
    return EXIT_OK if not cc.get("errors") else EXIT_FAIL


def _cmd_grep(pos, opt, flag):
    """`moss --snap grep <对象> <关键词> [目录]` —— 在**快照里**搜内容（只读）。

    为什么要有：包被改废了，AI 想知道"原来这行是怎么写的" —— 不用把整包拉出来，
    直接在快照里搜；命中的是"那一次存下来的内容"。"""
    b = _store()
    st = b.BackupStore(paths.USER_DIR / "backups", _rel_of, _resolve, trash=_trash)
    key, rest = _split_id(pos, opt.get("--group") or "")
    if not rest:
        out.print_cyan("[错误] 用法：moss --snap grep <对象> <关键词> [目录]")
        return EXIT_USE
    want = rest[0]
    sub = str(rest[1]).replace("\\", "/").strip("/") if len(rest) > 1 else ""
    pat = str(opt.get("--find") or want).lower()
    bid, g = _pick(b, st, key, opt.get("--group") or "")
    if not bid:
        out.print_cyan("[错误] 没找到这次快照。")
        return EXIT_NOTHING
    m = st.manifest(bid, g)
    hits, scanned, skipped = [], 0, 0
    for e in (m.get("files") or []):
        rel = str(e.get("rel") or "")
        if sub and not rel.startswith(sub + "/") and rel != sub:
            continue
        fp = e.get("fp")
        if not fp:
            continue
        r = st.read_blob(fp, group=g)
        if not r.get("ok") or r.get("binary"):
            skipped += 1
            continue
        scanned += 1
        for i, line in enumerate((r.get("text") or "").splitlines(), 1):
            if pat in line.lower():
                hits.append({"rel": rel, "line": i, "text": line[:400]})
    if "--json" in flag:
        print(_j({"ok": True, "id": bid, "group": g, "pattern": want,
                  "scanned": scanned, "hits": hits}))
        return EXIT_OK if hits else EXIT_NOTHING
    for h in hits:
        print("%s:%d: %s" % (h["rel"], h["line"], h["text"]))
    out.print_cyan("扫了 %d 个文本文件，命中 %d 行%s"
                   % (scanned, len(hits), ("（另有 %d 个二进制/读不了，跳过）" % skipped) if skipped else ""))
    return EXIT_OK if hits else EXIT_NOTHING

USAGE_SNAP = """moss --snap …                版本快照（备份/恢复）—— 给人和 AI 用的一条通道

  moss --snap <子命令> [对象] …          对象 = **插件名**（`:md5` / `md5`）或一个路径
  moss --snap list [对象] [--group <包id>]  列出快照（不给对象就是按组汇总）
  moss --snap save [对象] [路径…] [--title T] [--note N] [--tag 名字] [--group G]\n                                         加 --tag = 钉一个点（revert 时可以按标签回）\n  moss --snap revert <对象> [id|标签] [--sync] [--yes]\n                                         一键「对比 + 回退」：先列「变了什么」，再按只写回对齐\n  moss --snap tags [对象]                看钉过哪些标签\n  moss --snap grep <对象> <关键词> [目录]  在**快照里**搜内容（只读；包改废了就查原来怎么写的）
                                         存一次快照；不给路径 = 当前目录
  moss --snap show <id|latest>           看那一次的清单（有哪些文件）
  moss --snap diff <id|latest> [目录]    和**现在**比：一致/变了/快照有我没了/我有多/空
  moss --snap restore <id|latest> [--only changed|missing|all] [--sync] [--yes]
                                         恢复；默认"只写回"（多出来的不动）
                                         --sync = 一模一样（多出来的挪进回收站）
  moss --snap export <id|latest> <目录> [--keep-bak] [--yes]
                                         导出到某个文件夹（原文件不动）
  moss --snap rm <id|latest> [--yes]     删掉一次
  moss --snap rm --group <包id> --all [--yes]   删掉这个包的全部
  moss --snap ls <对象> [目录]           这次快照里有什么（路径 + 大小）\n  moss --snap cat <对象> <路径> [--save-to <目录> --yes]\n                                         看快照里**某个文件的内容**（包废了就看它原来写了什么）\n                                         ★ 默认只吐内容、**不给可写路径**；要落到磁盘得显式 --save-to --yes\n  moss --snap check [对象]               按**指纹**逐个校验内容块（被改过 / 丢了当场看得见）\n  moss --snap ignore                     看过滤规则（哪些文件不会被存进去）—— 规则文件是\n                                         user_data/snapshot.ignore，写法同 .gitignore 的常用那几条\n  moss --snap gc [--group G] [--yes]     回收没人引用的内容块

  · 会动磁盘的动作（restore / export / rm / gc）**必须显式 --yes**，否则只打印"会干什么"
  · 加 --json 得到结构化输出（AI 用）；退出码：0 成功 / 2 用法错 / 3 没东西可做 / 4 出错"""

HELP = {"--help", "-h"}


def cmd_snap(argv, table=None):
    """`moss --snap <子命令> …` —— 返回退出码（见文件头）。"""
    try:
        pos, opt, flag = _flatten(argv)
    except ValueError as e:
        out.print_cyan("[错误] %s" % e)
        return EXIT_USE
    if not pos or flag & HELP or pos[0] in HELP:
        print(USAGE_SNAP)
        return EXIT_OK
    sub, rest = pos[0], pos[1:]
    # ★ `V-101`：第一个位置参数先当"对象"认一下（`:md5` 这种插件名）—— 认出来就记进 `--group`，
    #   并把它自己的来源交给 `save`；剩下的位置参数才是 id / 目录。
    subj_group, subj_srcs = None, []
    if rest:
        subj_group, subj_srcs = _subject(rest[0], table)
        if subj_group:
            rest = rest[1:]
            opt["--group"] = subj_group
    try:
        if sub == "list":
            return _cmd_list(opt, flag)
        if sub == "save":
            return _cmd_save(rest, opt, flag, subj_srcs)
        if sub == "show":
            return _cmd_show(rest, opt, flag)
        if sub == "diff":
            return _cmd_diff(rest, opt, flag)
        if sub == "restore":
            return _cmd_restore(rest, opt, flag)
        if sub == "export":
            return _cmd_export(rest, opt, flag)
        if sub in ("rm", "del", "delete"):
            return _cmd_rm(rest, opt, flag)
        if sub == "gc":
            return _cmd_gc(opt, flag)
        if sub in ("cat", "file", "read"):
            return _cmd_cat(rest, opt, flag)
        if sub in ("ls", "files"):
            return _cmd_ls(rest, opt, flag)
        if sub in ("check", "verify"):
            return _cmd_check(rest, opt, flag)
        if sub in ("ignore", "filters"):
            return _cmd_ignore(opt, flag)
        if sub in ("revert", "undo"):
            return _cmd_revert(rest, opt, flag)
        if sub == "tags":
            return _cmd_tags(rest, opt, flag)
        if sub in ("grep", "find"):
            return _cmd_grep([rest[0]] + rest[1:] if rest else [], opt, flag)
    except Exception as e:                                          # noqa: BLE001
        out.print_cyan("[错误] 快照命令出错：%s" % e)
        return EXIT_FAIL
    out.print_cyan("[错误] 不认识的子命令 '%s'。" % sub)
    print(USAGE_SNAP)
    return EXIT_USE
