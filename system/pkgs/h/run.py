# -*- coding: utf-8 -*-
"""moss :h —— 历史记录的一步重启（`moss --history` 的短名字版本）。

为什么要有它
------------
宿主早就能做到"不用先 cd 就能重启"：`core/history.py` 给每条路径调用都记下了
**target + cwd**。但 `moss --history` 两个毛病让它不好用：
  ① 名字难记难敲（九个字符，还得记住是 `--` 不是 `:`）；
  ② 只能先看列表、再用方向键一条条找 —— 你心里明明已经有名字了。
这里把入口缩成 `moss :h <名字>`：**敲得出名字，就直接切到那个目录再跑一次。**

它做什么
--------
    moss :h                   等于 moss --history（交回宿主：方向键列表 + 回车重跑）
    moss :h zeen              找最近一条 cwd 末段 / 目标文件名是 zeen 的记录，切过去跑
    moss :h z/m               逐级写法：目录段以 z 开头、目标以 m 开头（`/` `\\` 都行）
    moss :h wwwroot/zeen/main 段数随便加，越多越准（从磁盘根开始也认，比如 D:/python/...）

怎么真的"切过去再跑"
--------------------
★ 这里**不自己拼解释器**。`runner` 表、venv 识别、自带运行时的 bootstrap、MOSS_* 注入
  全在宿主 `core/engine.py` 里；插件在磁盘上根本 import 不到 core（发行版把 core 编进
  exe 了），再实现一遍就是第二处真相，而且第一个撞上的就是"ZeEn 这种要第三方库的项目
  被自带运行时跑起来 ModuleNotFoundError"。
所以做法是**回头调一次 moss 宿主**：`cwd=<记录里的 cwd>` + `moss <目标文件名>` ——
和用户亲手 `cd` 过去再敲完全同一条路（宿主自己解析、自己选解释器、自己记账）。

★ 起子进程前把 `MOSS_PKG_*` / `MOSS_PLUGIN_*` 那套清掉（插件契约 §8 第 16 条）：不清的话
  `MOSS_PKG_ID=h` 会一路漏给被重跑的程序，宿主会以为"h 一直还在跑"，点「停止」还可能误杀它。
  但**位置类的三个要留**（`MOSS_HOME` / `MOSS_USER_DATA_DIR` / `MOSS_HOST_CMD`）—— 见 `KEEP_ENV`。

数据从哪来
----------
`MOSS_USER_DATA_DIR/history/*.jsonl`（宿主 `core/history.py` 追加写的流水账）。
插件读不到 core，所以这里自己读 JSONL、自己去重 —— 规则**照抄宿主**：
  · 只算路径调用（`kind` 是 `pkg` / `tombstone` 的不算）；
  · 去重键 = kind + 目标 + params + args（不含 cwd），同一件事只留**最新**那条；
  · 被墓碑（用户在界面里删掉的）点名的，同样跳过。
"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

#: 列表最多显示多少条（去重之后）。跟宿主 `history.MAX_SHOW` 一致 ——
#: 两边的条数不一样，用户会以为"记录丢了"。
MAX_SHOW = 20
#: 为了凑够 MAX_SHOW 条去重后的记录，最多往回读多少条原始记录（照抄宿主）。
READ_RAW = 5000

TOMBSTONE = "tombstone"
#: 这些 kind 不进历史（照抄宿主 `history.should_record`）：插件调用没有目录问题，
#: 记下来只是噪声；墓碑只是"某条别看了"的标记，本身不是一条记录。
SKIP_KINDS = ("pkg", TOMBSTONE)


# ---------------------------------------------------------------- 环境
def _user_data():
    """`user_data/` 在哪。**只认环境变量**（契约 §4），猜路径是最后一步兜底。"""
    d = (os.environ.get("MOSS_USER_DATA_DIR") or "").strip()
    if d:
        return Path(d)
    home = (os.environ.get("MOSS_HOME") or "").strip()
    if home:
        p = Path(home) / "user_data"
        if p.is_dir():
            return p
    # 手工 `python run.py` 试的时候没有环境变量：本文件在 user_data/pkgs/h/ 下
    return Path(__file__).resolve().parents[2]


def _history_dir():
    d = (os.environ.get("MOSS_HISTORY_DIR") or "").strip()
    if d:
        return Path(d)
    return _user_data() / "history"


# ---------------------------------------------------------------- 读历史
def _dedup_key(r):
    """去重键 —— 和宿主 `history.dedup_key` 逐字一致（墓碑里存的就是它）。"""
    return "|".join([
        str(r.get("kind") or ""),
        str(r.get("id") or r.get("target") or ""),
        json.dumps(r.get("params") or {}, sort_keys=True, ensure_ascii=False),
        json.dumps(r.get("args") or [], ensure_ascii=False),
    ])


def _raw_rows(limit=READ_RAW):
    """最近的原始记录（新的在前，跨月文件也读）。读不出来的行直接跳过。"""
    rows = []
    try:
        files = sorted(_history_dir().glob("*.jsonl"), reverse=True)
    except OSError:
        return rows
    for f in files:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue          # 写了一半的行 / 手工编辑坏的：不因为它整个列表挂掉
            if not isinstance(r, dict):
                continue
            rows.append(r)
            if len(rows) >= limit:
                return rows
    return rows


def recent_rows(limit=MAX_SHOW):
    """去重后的最近记录（新的在前）。去重保留后出现的那条（带 exit/ms 的收尾条）。"""
    rows = _raw_rows()
    dead = {str(r.get("forget") or "") for r in rows
            if (r.get("kind") or "") == TOMBSTONE and r.get("forget")}
    rows = [r for r in rows
            if (r.get("kind") or "") not in SKIP_KINDS
            and r.get("target")
            and _dedup_key(r) not in dead]
    # ★ 先按 ts 从新到旧排一遍，不依赖文件里的顺序（宿主也是这么较真的）
    rows.sort(key=lambda r: str(r.get("ts") or ""), reverse=True)
    seen, out = set(), []
    for r in rows:
        k = _dedup_key(r)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out[:limit]


# ---------------------------------------------------------------- 名字匹配
def _segments(p):
    """把一条路径拆成段。`/` 和 `\\` 都当分隔符（Windows 习惯）。"""
    return [s for s in str(p or "").replace("\\", "/").split("/") if s]


def _leaf(target):
    return str(target or "").replace("\\", "/").rsplit("/", 1)[-1]


def _chain(rec):
    """一条记录对应的"路径链"：cwd 的所有段 + 目标文件名。

    例：cwd=`D:\\python\\wwwroot\\ZeEn`、target=`…\\main.py`
        → `['D:', 'python', 'wwwroot', 'ZeEn', 'main.py']`
    查询按这条链**逐段前缀匹配**，所以 `z/m` 命中它（ZeEn 以 z 开头、main 以 m 开头），
    `main.py` / `zeen` / `wwwroot/zeen/main` / `D:/python/wwwroot/ZeEn` 也都命中。
    """
    segs = _segments(rec.get("cwd"))
    leaf = _leaf(rec.get("target"))
    if leaf:
        segs.append(leaf)
    return segs


def _alignment(qsegs, chain):
    """查询在链上最好的落点。返回排序键 (尾对齐, 精确段数, 深度)，对不上返回 None。

    · **尾对齐优先**：`main` 更该命中"目标文件叫 main.py"的那条，而不是某个叫 main 的目录；
    · **精确段数**次之：用户把整段名字打全了（`zeen` vs `ZeEn`），比只打了个前缀可信；
    · **深度**再次之：段数相同时，落在更深层的更具体（`z/m` 更像 `…/wwwroot/ZeEn/m…`）。
    """
    n = len(qsegs)
    if n == 0 or len(chain) < n:
        return None
    best = None
    for i in range(len(chain) - n + 1):
        exact = 0
        ok = True
        for j in range(n):
            q = qsegs[j].lower()
            c = chain[i + j].lower()
            if not c.startswith(q):
                ok = False
                break
            if c == q:
                exact += 1
        if not ok:
            continue
        key = (1 if i + n == len(chain) else 0, exact, i)
        if best is None or key > best:
            best = key
    return best


def find(rows, query):
    """按名字找，返回**排好序**的命中记录（最该跑的在前）。

    排序：目标还在 > 尾对齐 > 精确段数 > 深度 > 时间新。
    "目标还在"放最前面：同名的那条已经删了的话，宁可去跑另一条还活着的。
    """
    qsegs = _segments(query)
    if not qsegs:
        return []
    hits = []
    for r in rows:
        key = _alignment(qsegs, _chain(r))
        if key is None:
            continue
        alive = 1 if (os.path.isfile(str(r.get("target") or ""))
                      and os.path.isdir(str(r.get("cwd") or ""))) else 0
        hits.append((alive,) + key + (str(r.get("ts") or ""), r))
    hits.sort(key=lambda x: x[:-1], reverse=True)
    return [x[-1] for x in hits]


# ---------------------------------------------------------------- 显示
def _width(s):
    """显示宽度：中文 / 全角占两列，排版才不会歪（宿主 `out` 里同一套算法）。"""
    w = 0
    for ch in str(s):
        w += 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1
    return w


def _pad(s, n):
    s = str(s)
    room = n - _width(s)
    if room <= 0:
        return s
    return s + " " * room


def _try(s, n):
    """按显示宽度截断到 n 列以内。"""
    out, w = "", 0
    for ch in str(s):
        cw = 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1
        if w + cw > n:
            break
        out += ch
        w += cw
    return out


def _hhmmss(rec):
    ts = str(rec.get("ts") or "")
    return ts[11:19] if len(ts) >= 19 else ts


def _where(rec):
    """一行"哪个目录里的什么"：给列表和命中提示共用。"""
    cwd = str(rec.get("cwd") or "-")
    args = " ".join(str(a) for a in (rec.get("args") or []))
    tail = ("  " + args) if args else ""
    return "%s%s      ← %s" % (_leaf(rec.get("target")) or "-", tail, cwd)


def print_list(rows, hint=True):
    """非交互地列出来（宿主不在 / 没有终端时的那条路）。"""
    if not rows:
        print("[信息] 还没有任何启动记录。先随便跑一个脚本，`moss :h` 就有东西了。")
        return 0
    print("最近 %d 条启动记录（已去重，同一件事只留最新一条）" % len(rows))
    for i, r in enumerate(rows, 1):
        line = "  %2d  %s  %s  %s" % (i, _hhmmss(r), _pad(_leaf(r.get("target")) or "-", 22),
                                      r.get("cwd") or "-")
        args = " ".join(str(a) for a in (r.get("args") or []))
        if args:
            line += "   " + _try(args, 40)
        print(line)
    if hint:
        print()
        print("直接敲名字就跑：moss :h <名字>     例：moss :h zeen / moss :h z/m")
        print("想用方向键挑：moss --history（或者 moss :h 后面什么都不加）")
    return 0


# ---------------------------------------------------------------- 调宿主
#: **不能清掉的 MOSS_\***：这三个是"位置 / 出口"，不是"我是谁"。
#: ★ 这条是本插件自己真机踩出来的：把 MOSS_HOME 一起清掉之后，**源码模式**的宿主
#:   （`MOSS_HOST_CMD = python moss.py`）会改用 `argv[0]` 重新算安装根 —— 于是它读的是
#:   另一个 `user_data`（配置、历史全错位），而 `--history` 那条路看起来"正常"，
#:   只有横幅少了两行、历史写进了别处才发现。打包后的 exe 不受影响，但没理由让它分叉。
KEEP_ENV = ("MOSS_HOME", "MOSS_USER_DATA_DIR", "MOSS_HOST_CMD")


def _clean_env():
    """给子进程的环境：清掉 `MOSS_PKG_*` / `MOSS_PLUGIN_*` 那套"我是某个包"的标记。

    ★ 不清的话 `MOSS_PKG_ID=h` 会一路漏给被重跑的程序（契约 §8 第 16 条），
      宿主会以为"h 一直还在跑"，界面上那颗「停止」还可能误杀它。
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("MOSS_") or k in KEEP_ENV}
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _parse_host_cmd(raw):
    """解析 `MOSS_HOST_CMD`。

    ★ 它是 **JSON 数组**（`core/ui.py` 用 `json.dumps([exe])` 塞的，`V-235` 真机踩过：
      当成命令行字符串去 `shlex.split` 会得到 `'[D:\\…\\moss.exe]'` ⇒ WinError 2）。
      所以**先 json**，再退回命令行字符串。解析不出来就返回 None（让上层换别的路）。
    """
    try:
        v = json.loads(raw)
    except ValueError:
        v = None
    if isinstance(v, list) and v:
        cmd = [str(x) for x in v]
    elif isinstance(v, str) and v.strip():
        cmd = [v.strip()]
    elif os.path.exists(raw.strip('"')):
        # 整条路径、没加引号、又正好存在 —— 直接当路径用。
        # ★ 别丢给 shlex：`C:\a\moss.exe` 过 posix 的 shlex 会变成 `C:amoss.exe`（反斜杠被吃）
        cmd = [raw.strip('"')]
    else:
        try:
            cmd = [str(x) for x in shlex.split(raw, posix=True)]
        except ValueError:
            return None
    if not cmd:
        return None
    first = cmd[0].strip('"')
    cmd[0] = first
    # 解析出来的第一段必须**真的叫得起来**；叫不起来就当作"没解析出来"，
    # 让上层退到 MOSS_HOME / PATH —— 别拖到最后撞一个 WinError 2。
    if os.path.dirname(first):
        if not os.path.exists(first):
            return None
    elif not shutil.which(first):
        return None
    return cmd


def host_cmd():
    """找到 moss 宿主本身。返回 argv 列表，找不到返回 None。

    顺序：`MOSS_HOST_CMD`（界面那条路给的就是它）→ `MOSS_HOME` 下的 moss.exe /
    moss.py（源码运行时）→ PATH 里的 moss。
    ★ `moss.py` 要用 `sys.executable` 跑 —— 插件本来就跑在自带运行时里。
    """
    raw = (os.environ.get("MOSS_HOST_CMD") or "").strip()
    if raw:
        cmd = _parse_host_cmd(raw)
        if cmd:
            return cmd

    home = (os.environ.get("MOSS_HOME") or "").strip()
    if home:
        base = Path(home)
        for name in ("moss.exe", "moss.cmd", "moss.bat"):
            p = base / name
            if p.is_file():
                return [str(p)]
        p = base / "moss.py"
        if p.is_file():
            return [sys.executable, str(p)]

    found = shutil.which("moss")
    if found:
        return [found]
    return None


def _interactive():
    """边上有人真的在按键盘吗（宿主判断 `--history` 用不用方向键列表也是这一条）。"""
    try:
        return bool(sys.stdout.isatty() and sys.stdin.isatty())
    except Exception:                                             # noqa: BLE001
        return False


def _call(argv, cwd=None):
    try:
        return subprocess.call(argv, cwd=cwd, env=_clean_env())
    except OSError as e:                                          # noqa: BLE001
        print("[错误] 起不来：%s" % e)
        print("       命令：%s" % " ".join('"%s"' % c for c in argv))
        return 2


def _write_result(payload):
    f = (os.environ.get("MOSS_RESULT_FILE") or "").strip()
    if not f:
        return
    try:
        Path(f).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


# ---------------------------------------------------------------- 主流程
def _show_history(rows):
    """不带名字：交回宿主的 `--history`（方向键列表 + 回车重跑，等于把老命令接住）。

    宿主那边跑不起来（老版本没这个参数 / 找不到宿主）就自己打印一份 ——
    `:h` 光秃秃一个也必须有用，不能因为"找不到 moss.exe"就什么都不给。
    """
    host = host_cmd()
    if host and _interactive():
        rc = _call(host + ["--history"])
        if rc == 0:
            return 0
    return print_list(rows)


def _run_cwd(rec):
    """该在哪个目录里把这次重跑拉起来。返回 (目录, 提示或 None)。

    正常记录（`moss zeen`）里 cwd **就是**目标文件所在的目录，两者一致；
    但历史上还有一种是「不切目录」的记录（`moss /x`，`change_dir=False`）——
    那时 cwd 是**调用者**当时的目录，目标在别处。照记录的 cwd 去 `moss <文件名>`，
    会去那个目录里找同前缀的**另一个** main.py（或者压根找不到）——两种都不对。
    这时退到目标所在目录，并且**明说一句**：宁可行为跟当初不完全一样，也不能悄悄跑错文件。
    """
    cwd = str(rec.get("cwd") or "")
    target = str(rec.get("target") or "")
    parent = os.path.dirname(os.path.abspath(target)) if target else cwd
    try:
        same = os.path.normcase(os.path.abspath(cwd)) == os.path.normcase(parent)
    except OSError:
        same = False
    if same:
        return cwd, None
    return parent, ("这条记录当时是「不切目录」跑的（moss /…）：目标不在 %s 里，"
                    "改用目标所在目录。" % cwd)


def _run_record(rec, extra):
    target = str(rec.get("target") or "")
    leaf = _leaf(target)
    args = [str(a) for a in (rec.get("args") or [])] + list(extra)
    cwd, note = _run_cwd(rec)

    argv = host_cmd()
    if not argv:
        print("[错误] 找不到 moss 宿主：既没有 MOSS_HOST_CMD，MOSS_HOME 下也没有 moss.exe。")
        print("       自己敲：cd /d \"%s\"" % cwd)
        print("               moss %s%s" % (leaf, (" " + " ".join(args)) if args else ""))
        return 2

    if note:
        print("[提示] %s" % note)
    print("[历史] %s  →  %s" % (leaf or "-", target))
    print("[目录] %s" % cwd)
    if args:
        print("[参数] %s" % " ".join(args))
    sys.stdout.flush()

    rc = _call(argv + [leaf] + args, cwd=cwd)
    _write_result({"query": "", "target": target, "cwd": cwd,
                   "runner": rec.get("runner") or "", "exit": rc})
    return rc


def main():
    params = {}
    try:
        params = json.loads(os.environ.get("MOSS_PKG_PARAMS") or "{}") or {}
    except ValueError:
        params = {}
    query = str(params.get("target") or "").strip()
    extra = str(params.get("extra") or "").split()

    rows = recent_rows()

    if not query:
        return _show_history(rows)

    hits = find(rows, query)
    if not hits:
        print("[错误] 历史里没有叫 '%s' 的记录。" % query)
        if rows:
            print("       最近跑过这些（`moss :h <名字>` 直接重跑其中一条）：")
            for r in rows[:5]:
                print("         %s" % _where(r))
        print("       ★ 只记**路径调用**（`moss zeen` 这种）；`moss :包名` 不进历史。")
        _write_result({"query": query, "target": "", "cwd": "", "runner": "", "exit": 1})
        return 1

    best = hits[0]
    target = str(best.get("target") or "")
    cwd = str(best.get("cwd") or "")

    # 目标/目录没了的两种死法要说清是哪一种，别丢一句 WinError 2
    if not os.path.isdir(cwd):
        print("[错误] 记录里的目录已经不在了：%s" % cwd)
        print("       目标：%s" % target)
        if len(hits) > 1:
            print("       还有 %d 条同名记录，试试把名字写细一点（moss :h z/m）。" % (len(hits) - 1))
        _write_result({"query": query, "target": target, "cwd": cwd, "runner": "", "exit": 1})
        return 1
    if not os.path.isfile(target):
        print("[错误] 目标文件已经不在了：%s" % target)
        if len(hits) > 1:
            print("       还有 %d 条同名记录，试试把名字写细一点（moss :h z/m）。" % (len(hits) - 1))
        _write_result({"query": query, "target": target, "cwd": cwd, "runner": "", "exit": 1})
        return 1

    # 命中多条时把"还有哪些"摆出来 —— 取最近的一条是规矩，但也得让人看得见别的可能
    if len(hits) > 1:
        print("[提示] '%s' 命中 %d 条，取最近的一条；想跑别的把名字写细一点："
              % (query, len(hits)))
        for r in hits[1:4]:
            print("         %s" % _where(r))

    rc = _run_record(best, extra)
    _write_result({"query": query, "target": target, "cwd": cwd,
                   "runner": best.get("runner") or "", "exit": rc})
    return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[提示] 操作已取消。")
        sys.exit(130)
