# -*- coding: utf-8 -*-
"""`:skill` 的逻辑 + 给界面用的 `Api`。

两件事说清楚
------------
1. **规矩不在这儿**：技能那一层（扫描 / 校验 / 指纹 / 授权 / 跑 / 转插件）全在
   `system/ai/skill_lib.py` —— **宿主 AI 工作台和这个插件 import 的是同一份**，
   所以两边不会各写一套然后漂移。
2. **技能本体住这个插件的数据目录**（`MOSS_PLUGIN_DATA_DIR` = `user_data/state/skill/`），
   跟 `:exec` 把命令放 `state/exec/cmds/` 一个道理。区别只在：**每个技能是一个目录**
   （`pkg.json` + 入口 + `icon.svg` + 随便什么文件），不是把代码塞进 JSON。

界面那一侧（`ui/app.js`）只认这几个方法，所以这里的方法名就是界面协议。
"""
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

HOME = Path(os.environ.get("MOSS_HOME") or HERE.parents[2])
_AI = str(HOME / "system" / "ai")
if _AI not in sys.path:
    sys.path.insert(0, _AI)

import skill_lib as S                                                  # noqa: E402

#: 用法：`moss :skill` 不带参数、或者 `moss :skill help` 打这一份。
#: ★ 写给**人和 AI** 都看得懂：AI 靠它知道有哪些动词、怎么查说明、怎么跑一只。
HELP = """技能（AI 给自己造的能力）—— 用法

  moss :skill                     打这一份用法 + 列出全部技能（**不开窗**）
  moss :skill gui                 打开管理器界面（图标墙 / 详情 / 转为插件 / 删除）
  moss :skill list                列出来（名字 · 状态 · 一句话说明）
  moss :skill show <名字>         看详情：为什么造它 / 参数 / 入口 / 时间 / 文件清单
  moss :skill doc <名字>          看**这只技能自己的说明书**（它目录里的 AGENT.md；
                                  没有的话就把 pkg.json 的要点和文件清单列出来）
  moss :skill run <名字> [k=v …]  跑一次（参数用 k=v；值里有空格就整体加引号）
  moss :skill allow <名字>        允许 AI 用它        moss :skill revoke <名字>  撤销
  moss :skill rm <名字>           删掉它（整个目录）   moss :skill seed           补回出厂样例
  moss :skill plan <名字> [新id]  看"转成插件"会不会撞 id
  moss :skill promote <名字> [新id]  真转成插件（搬进 user_data/pkgs，从此是普通插件）

说明
  · 技能本体在 user_data/state/skill/<名字>/（一个目录 = pkg.json + 入口 + icon.svg）。
  · **批准那几下（allow / revoke / rm / promote）必须人来做** —— AI 拿 run_moss 调会被拒。
  · 不带参数时：界面里点「运行」→ 开窗口；命令行 / AI 调 → 只打这一份用法（对 AI 友好）。
"""


def data_dir():
    """这个插件的数据目录（宿主注入；没注入就按约定推）。"""
    d = (os.environ.get("MOSS_PLUGIN_DATA_DIR") or "").strip()
    return Path(d) if d else (HOME / "user_data" / "state" / "skill")


def _human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024
    return "%.1f GB" % n


class Api:
    """界面能调的方法（`window.pywebview.api.<名字>(params)` / 内嵌时走垫片）。"""

    # ---------------------------------------------------------------- 读
    def list(self, params=None):
        """图标墙要的一切：**只有技能**（`V-284`：插件不出现在这一页）。"""
        got = S.summary()
        for r in got["skills"]:
            r["files_h"] = "%d 个文件 · %s" % (
                r["files_n"],
                _human(sum(f.get("size") or 0 for f in (r.get("files") or []))))
        got["dir"] = str(data_dir())
        return got

    def read(self, params=None):
        """看某个技能里写的文件（详情页那个「文件」折叠）。"""
        sid = str((params or {}).get("id") or "")
        got = S.read(sid)
        if got.get("ok"):
            got["files_h"] = [dict(f, size_h=_human(f.get("size"))) for f in got.get("files") or []]
        return got

    def plan(self, params=None):
        """转成插件之前先算一遍（id 会不会撞）—— 界面弹确认框用它。"""
        p = dict(params or {})
        return S.promote_plan(str(p.get("id") or ""), str(p.get("new_id") or ""))

    def doc(self, params=None):
        """这只技能**自己的说明书**（`AGENT.md`；没有就退回 pkg.json + 文件清单）。

        ★ AI 就是靠它"看说明"的（命令行里 `moss :skill doc <名字>`）。
        """
        p = dict(params or {})
        return S.doc(str(p.get("id") or ""))

    def help(self, params=None):
        """用法（命令行/AI 调的时候不带参数就打这一份）。"""
        return {"ok": True, "text": HELP}

    def reveal(self, params=None):
        """在资源管理器里打开这个技能的目录。"""
        d = Path(str((params or {}).get("dir") or data_dir()))
        if not d.is_dir():
            return {"ok": False, "msg": "目录不在：%s" % d}
        try:
            os.startfile(str(d))                                       # noqa: S606  Windows
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}
        return {"ok": True, "msg": "打开了：%s" % d}

    def run_once(self, params=None):
        """在这儿**试跑一次**（跟 AI 调它走的是同一条路：stdin JSON → stdout）。

        ★ 只在**已经允许**的技能上给按（没允许的那条路本来就不通）—— 这里不绕闸。
        """
        p = dict(params or {})
        sid = str(p.get("id") or "")
        args = p.get("args") if isinstance(p.get("args"), dict) else {}
        got = S.list_skills().get(sid)
        if not got:
            return {"ok": False, "msg": "没有这只技能：%s" % sid}
        out = S.run(got["name"], args)
        return {"ok": True, "msg": out}

    # ---------------------------------------------------------------- 写（都要人点）
    def allow(self, params=None):
        p = dict(params or {})
        return S.allow(str(p.get("id") or ""), bool(p.get("yes", True)))

    def rm(self, params=None):
        p = dict(params or {})
        return S.rm(str(p.get("id") or ""), bool(p.get("confirm")))

    def promote(self, params=None):
        p = dict(params or {})
        return S.promote(str(p.get("id") or ""), bool(p.get("confirm")),
                         str(p.get("new_id") or ""))

    def seed(self, params=None):
        """把出厂样例补回来（你删了 `--shot` 之后想要它，点这个）。"""
        made = S.ensure_seed()
        return {"ok": True, "made": made,
                "msg": ("补回来了：%s" % "、".join(made)) if made else "出厂样例都在，不用补"}

    # ---------------------------------------------------------------- 命令行那边共用的
    def cli(self, args):
        """`moss :skill <动词>` 的实现（`main.py` 调它）。

        回 `(退出码, 要打印的文本)`。★ 动词跟界面上的动作**一一对应**：
        允许 / 撤销 / 删除 / 转插件这几下在界面上点，或者在这儿敲。
        """
        a = [str(x) for x in (args or []) if str(x).strip()]
        verb = (a[0].lower() if a else "")
        rest = a[1:]
        # ★ 不带参数 / `help` / `--help`：打用法 + 列表。**不开窗**（AI 调这一下不该弹个窗口）。
        if verb in ("", "help", "-h", "--help", "?"):
            return 0, HELP.rstrip() + "\n\n" + self._list_text()
        if verb in ("list", "ls"):
            return 0, self._list_text()
        if verb in ("show", "info") and rest:
            got = S.list_skills().get(rest[0])
            if not got:
                return 1, "没有这只技能：%s" % rest[0]
            us = [str(p.get("name")) for p in (got.get("params") or []) if isinstance(p, dict)]
            return 0, ("%s\n  名字   : %s\n  说明   : %s\n  为什么 : %s\n"
                       "  状态   : %s —— %s\n  入口   : %s\n  参数   : %s\n  目录   : %s\n"
                       "  创建   : %s\n  改过   : %s\n  允许于 : %s\n  文件   : %d 个\n"
                       "（看它自己的说明书：moss :skill doc %s）"
                       % (got["id"], got["name"], got.get("desc") or "（没写）",
                          got.get("why") or "（没写）",
                          "可用" if got["allowed"] else "待批准", got.get("why_allow") or "",
                          got.get("entry") or "", "、".join(us) or "无",
                          got["dir"], got.get("created") or "", got.get("mtime") or "",
                          got.get("allowed_at") or "—", len(got.get("files") or []), got["id"]))
        if verb in ("doc", "readme", "agent") and rest:
            got = S.doc(rest[0])
            return (0, got.get("text") or "") if got.get("ok") else (1, str(got.get("msg")))
        if verb in ("allow", "revoke") and rest:
            return self._say(S.allow(rest[0], verb == "allow"))
        if verb in ("rm", "remove", "del", "delete") and rest:
            return self._say(S.rm(rest[0], True))
        if verb == "promote" and rest:
            return self._say(S.promote(rest[0], True, rest[1] if len(rest) > 1 else ""))
        if verb == "plan" and rest:
            p = S.promote_plan(rest[0])
            if not p.get("ok"):
                return 1, str(p.get("msg"))
            if p["problems"]:
                return 1, "不能转：%s" % "；".join(p["problems"])
            return 0, "可以转：%s → %s（搬去 %s）" % (p["id"], p["new_id"], p["dir_to"])
        if verb == "seed":
            made = S.ensure_seed()
            return 0, ("补回来了：%s" % "、".join(made)) if made else "出厂样例都在，不用补"
        if verb in ("run", "try") and rest:
            got = S.list_skills().get(rest[0])
            if not got:
                return 1, "没有这只技能：%s" % rest[0]
            # ★ 参数：`k=v` 那几段拆成一份 dict 交给技能（跟 AI 调它走的是同一条路）
            params = {}
            for one in rest[1:]:
                k, sep, v = str(one).partition("=")
                if sep:
                    params[k.strip()] = v
            print(S.run(got["name"], params))
            return 0, ""
        return 2, "认不出这个动词：%s\n\n%s" % (verb, HELP.rstrip())

    # ---------------------------------------------------------------- 内部
    def _say(self, got):
        return (0 if got.get("ok") else 1), str(got.get("msg") or got)

    def _list_text(self):
        got = S.summary()
        rows = ["[技能] %d 只（能用的 %d）· 目录 %s"
                % (len(got["skills"]), got["n_usable"], data_dir()), "-" * 62]
        for r in got["skills"]:
            mark = "可用" if r["allowed"] else ("写坏" if r["problems"] else "待批准")
            rows.append(" %-14s %-6s %s" % (r["id"], mark, (r["desc"] or r["why"] or "")[:44]))
        if not got["skills"]:
            rows.append(" （一只都没有 —— AI 缺能力时会自己造一只，造好会出现在这儿）")
        rows.append("-" * 62)
        rows.append("看说明：moss :skill doc <名字>；详情：moss :skill show <名字>；"
                    "跑一次：moss :skill run <名字> [k=v …]")
        return "\n".join(rows)


def gui():
    """独立窗口（`moss :skill` 不带参数、又没有内嵌时）：同一份 ui/index.html。"""
    import webview                                                     # noqa: PLC0415
    page = HERE / "ui" / "index.html"
    win = webview.create_window("技能", str(page), js_api=Api(),
                                width=1080, height=740, min_size=(760, 520))
    webview.start()
    return win
