# -*- coding: utf-8 -*-
"""AI 的"改文件"那部分：**search/replace 引擎** + **写权限守卫**（`V-230` / `V-231`）。

为什么不让模型重写整个文件（你选的 D①）
----------------------------------------
· **省 token**：一个 200 行的文件改 3 行，输出几十 token 就够；整文件重写要几千。
· **不容易丢内容**：长文件"重写"时模型常在中间悄悄丢一段（它自己看不出来）。
代价是"找不到那段"会失败 —— 所以这里把失败**写清楚**（给候选行号、给最像的几行），
让模型下一轮能自己修好，而不是瞎改别处。

★ 写权限（v1，`C①`）：**只允许写 `user_data/pkgs/**`**。
  读不设这个限制（要读 `system/pkgs/bmi` 当样板、要读契约），但**写只有那一个地方** ——
  改坏了删包重来，碰不到出厂件，这也是"v1 不碰 system/ / 不碰 core/"的落地。
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent                      # system/ui/ai
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _home():
    """moss 安装根：优先环境变量，其次从本文件位置往上推（`system/ui/ai/` → 三层）。"""
    env = (os.environ.get("MOSS_HOME") or "").strip()
    if env:
        return Path(env)
    return HERE.parents[2]


HOME = _home()


def user_data():
    env = (os.environ.get("MOSS_USER_DATA_DIR") or "").strip()
    return Path(env) if env else (HOME / "user_data")


#: v1 允许写的唯一地方（`user_data/pkgs/**`）
def write_root():
    return user_data() / "pkgs"


def inside(path, root):
    """`path` 是不是在 `root` 里面（用 realpath 比，挡 `..` 和符号链接）。"""
    try:
        p = os.path.realpath(str(path))
        r = os.path.realpath(str(root))
    except OSError:
        return False
    return p == r or p.startswith(r + os.sep)


def check_writable(path):
    """能写就回 None，不能写就回一句**给人看的原因**（会被原样回给模型）。"""
    root = write_root()
    if not inside(path, root):
        return ("[拒绝] v1 只允许写 `%s` 下面的文件；`%s` 不在里面。"
                "（要改出厂件/宿主：那是第二阶段的事，现在必须由人来做。）" % (root, path))
    return None


def read_roots():
    """允许**读**的范围：干活的那棵树 + 契约 + 样板包。

    ★ 为什么要管读（`V-232` 实测）：第一次真跑，模型为了搞清"包到底写到哪了"，
      跑去读 `core/paths.py` / `moss.py` / `config.toml` / 甚至我自己的 `ai_tools.py`
      —— 12 轮里大半花在这上面，**输入 token 137k**，活还没干完。
      把"能读哪儿"框住，比在提示词里写"别乱读"硬得多（提示词是劝，这个是拦）。
    """
    return [write_root(),                                    # user_data/pkgs/**
            HOME / "system" / "spec",                        # 契约（唯一真相）
            HOME / "system" / "pkgs"]                        # 样板包（照 bmi 抄）


def check_readable(path, scope=None):
    """能读就回 None，不能读就回原因。

    `scope`：**这次干活的目录**（`Tools` 会把 workdir 传进来）。
    传了它，`user_data/pkgs` 下面**别的包**就不给看了 —— 真机上它把同级的
    `ask` / `dazi` / `unwx` 挨个翻了一遍，用户的原话是"我选的干活的地方是 calc，
    它怎么疯狂地读取一堆其他的内容"。样板请去 `system/pkgs/`（那是故意留的样板）。

    ★ `V-235` 补的一条：**契约只能通过 `spec` 工具读**，不许 `read_file` 整篇读。
      真机那次模型拿 `read_file` 一段段啃契约（645 行、来回好几趟），14 步烧掉
      **26.5 万输入 token** —— `spec` 工具本来就是"按小节切、切完还有上限"的那条路。
    """
    if scope:
        sc = Path(scope)
        root = write_root()
        # 只在"路径确实落在 user_data/pkgs 下面、但不在 scope 里"时拦 —— 别的地方交给下面的规则
        if inside(path, root) and not inside(path, sc):
            return ("[拒绝] 这次干活的地方是 `%s` —— **只在这个包下面看**。"
                    "`%s` 是**别的包**，不归这次任务管（样板请看 `system/pkgs/bmi`，那是留给你抄的）。"
                    % (sc, path))
    if inside(path, HOME / "system" / "spec"):
        return ("[拒绝] 契约不要用 read_file 整篇读 —— 用 `spec` 工具按小节取："
                "`spec(\"\")` 看目录、`spec(\"拖放\")` / `spec(\"pkg.json\")` / `spec(\"避坑\")` 取某一节。"
                "（整篇读会把上下文撑爆、把轮次烧光。）")
    for root in read_roots():
        if inside(path, root):
            return None
    return ("[拒绝] 只允许读这三处：`%s`（自己写的包）、`system/spec/`（契约，**用 spec 工具**）、"
            "`system/pkgs/`（样板包）。`%s` 不在里面 —— 要了解宿主实现请**问人**，"
            "别读源码（那是浪费轮次和 token）。" % (write_root(), path))


def read_text(path, offset=1, limit=400):
    """带行号读一段（行号照 `read` 工具的习惯从 1 开始）。

    ★ 读出来**统一成 `\\n`**（CRLF 的文件也显示成 `\\n`）—— 因为模型是"照抄看见的东西"
      来写 `find` 的，显示的和匹配的必须是同一份文本（这条是探针抓出来的：文件是 CRLF 时
      `find` 用 `\\n` 永远匹配不上）。
    """
    p = Path(path)
    if not p.is_file():
        return None, "没有这个文件：%s" % p
    bad = check_readable(p)
    if bad:
        return None, bad
    try:
        raw = p.read_bytes()
    except OSError as e:
        return None, "读不了：%s" % e
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    lines = text.split("\n")
    start = max(1, int(offset or 1))
    stop = min(len(lines), start - 1 + max(1, int(limit or 400)))
    out = ["%5d| %s" % (i + 1, lines[i]) for i in range(start - 1, stop)]
    head = "（共 %d 行，这是 %d-%d 行）" % (len(lines), start, stop) if lines else "（空文件）"
    return "\n".join([head] + out), None


def _split_lines(text):
    return text.split("\n")


def _crlf(raw):
    return b"\r\n" in raw


def apply_edit(path, find, replace, replace_all=False):
    """把 `find` 换成 `replace`。回 `{ok, replaced, error, hint}`。

    ★ 多命中且没写 `replace_all` ⇒ **拒绝**（`V-229` 那类"改错地方"的事故就是这么来的）。
    ★ 零命中 ⇒ 给**候选行号 + 最像的几行**（模型下一轮能自己对齐）。
    """
    p = Path(path)
    bad = check_writable(p)
    if bad:
        return {"ok": False, "error": bad}
    if not p.is_file():
        return {"ok": False, "error": "没有这个文件：%s（新建文件用 write_file）" % p}
    raw = p.read_bytes()
    # ★ 匹配用**统一成 \n** 的文本（模型照 `read_file` 看到的样子抄 find），
    #   写回去时再还原成原来的换行风格（Windows 上编辑过的文件常是 CRLF，别整文件翻新）。
    text = raw.decode("utf-8", "replace").replace("\r\n", "\n")
    find = str(find or "").replace("\r\n", "\n")
    replace = str(replace or "").replace("\r\n", "\n")
    if not find:
        return {"ok": False, "error": "find 不能是空的（要替换整段就用 write_file）"}
    n = text.count(find)
    if n == 0:
        return {"ok": False, "replaced": 0,
                "error": "没找到那段。**一个字都不能差**（缩进、空行都算）。",
                "hint": _miss_hint(text, find)}
    if n > 1 and not replace_all:
        lines = [i + 1 for i, ln in enumerate(_split_lines(text)) if find.split("\n")[0] and ln.find(find.split("\n")[0]) >= 0]
        return {"ok": False, "replaced": 0,
                "error": "这一段出现了 %d 次，不肯猜你要改哪一个：要么把 find 写长一点"
                         "（带上前后文到唯一），要么显式给 replace_all=true。" % n,
                "hint": "候选行号：%s" % (lines[:12] or "（按首行没定位到，建议多带几行上下文）")}
    new = text.replace(find, replace) if replace_all else text.replace(find, replace, 1)
    try:
        # 原来的换行风格照旧（Windows 上编辑过的文件常是 CRLF，别整文件翻新）
        if _crlf(raw):
            p.write_bytes(new.replace("\n", "\r\n").encode("utf-8"))
        else:
            p.write_bytes(new.encode("utf-8"))
    except OSError as e:
        return {"ok": False, "error": "写不进去：%s" % e}
    return {"ok": True, "replaced": (n if replace_all else 1)}


def write_new(path, content, overwrite=False):
    """写一个文件。

    ★ 已存在时**默认拒绝**（改已有的用 `apply_edit`，别整文件覆盖 —— 那样最容易悄悄丢内容）。
      但 `V-242` 真机踩到一个死角：模型想**整篇重写** `AGENT.md`，被拒之后就没路可走了
      （它没有"覆盖"这个动作可调）。所以给它一条明路：**显式 `overwrite=true`** 才允许覆盖。
    """
    p = Path(path)
    bad = check_writable(p)
    if bad:
        return {"ok": False, "error": bad}
    if p.exists() and not overwrite:
        return {"ok": False, "error":
                "文件已经在了：%s\n"
                "· 改几行 ⇒ 用 `edit_file`（精确替换，最稳）；\n"
                "· 要**整篇重写** ⇒ 再调一次 `write_file`，并显式带上 `overwrite=true`。" % p}
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(str(content or "").encode("utf-8"))
    except OSError as e:
        return {"ok": False, "error": "写不进去：%s" % e}
    return {"ok": True, "bytes": len(str(content or "").encode("utf-8")),
            "overwrote": bool(overwrite and p.exists())}


def _miss_hint(text, find):
    """没找到时给三样东西：首行出现的行号、最像的几行、常见原因。"""
    import difflib
    lines = _split_lines(text)
    first = (find.split("\n")[0] or "").strip()
    hit = [i + 1 for i, ln in enumerate(lines) if first and first in ln]
    close = difflib.get_close_matches(first, [ln.strip() for ln in lines], n=3, cutoff=0.55)
    bits = []
    if hit:
        bits.append("你给的第一行出现在第 %s 行" % hit[:8])
    if close:
        bits.append("最像的行：%s" % " / ".join(repr(c) for c in close))
    bits.append("常见原因：缩进对不上（空格/制表符）、文件是 CRLF、这段是**改过之后**的样子")
    return "；".join(bits)
