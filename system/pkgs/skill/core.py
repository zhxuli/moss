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
import codecs
import os
import subprocess
import sys
import threading
import time
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
  moss :skill rm <名字>           删掉它（整个目录）
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


# ================================================================ 交互式运行（`V-302`）
#  「运行测试」不再是"一次跑完给你一段"，而是**起一个进程**：输出实时流去界面、
#  界面能把输入写进它的 stdin（技能里 `input()` 的那一问就接得上）、还能停。
#  ★ 参数走环境变量（`MOSS_PKG_PARAMS`，`S._env` 摆的）—— 这样 stdin 整条留给交互；
#    技能要读参数就读环境变量（`S.run` 那条路上也是既给 stdin 又给环境变量的）。
_RUNS = {}
_RUN_LOCK = threading.Lock()
_RID = [0]


def _emit(rid, text):
    if not text:
        return
    with _RUN_LOCK:
        r = _RUNS.get(rid)
        if not r:
            return
        r["out"].append(text)
        if len(r["out"]) > 8000:                         # 别把内存撑爆
            del r["out"][:3000]


def _maybe_close_stdin(rid):
    """给"卡在读 stdin 等 EOF"的技能兜底放行（`V-302`）。

    技能按老契约用 `sys.stdin.read()` 读参数 —— 那要**等 EOF**；而交互模式把 stdin 一直开着，
    它就永远卡住（"正在跑、没输出、不结束、没日志"）。折中：进程起来 1.2 秒后，
    若它**一个字都没吐、也没人往它 stdin 写过**，就判定它是在等 stdin ⇒ 关掉 stdin（EOF）放它跑。
    ★ 真·交互式的技能（`input('问一下')`）会在 1.2 秒内先把提示语打出来 ⇒ `out` 非空 ⇒ 不关。
    """
    with _RUN_LOCK:
        r = _RUNS.get(rid)
    if not r or r.get("code") is not None or r["out"] or r.get("sent_input"):
        return
    try:
        r["proc"].stdin.close()
    except Exception:                                                     # noqa: BLE001
        pass
    with _RUN_LOCK:
        r["stdin_closed"] = True


def _pump_run(rid):
    """读线程 —— **照 moss 主界面 `_pump_output` 那套**（`V-86` / `V-219` 的结论）：

    ① **按块读**（`os.read` 4096 + 增量 UTF-8 解码），不是 `for line in proc.stdout`；
    ② 攒到 `\\n` 就交一整块；
    ③ 手里那**没有换行的半行**（最典型：`input("你叫什么？ ")` 的提示语）超过 0.12 秒
       也先交出去 —— 不然界面上就是"跑起来了却什么都不问"（你报的正是这个）；
    ④ **子进程一退就算跑完，不等管道 EOF** —— 它拉起的孙进程可能叼着管道不放
       （`.bat` 里 `start explorer` 那种），否则 `run_poll` 会永远回"在跑"。
    """
    r = _RUNS.get(rid)
    if not r:
        return
    proc = r["proc"]
    pending = [""]
    stop = threading.Event()

    def ticker():
        while not stop.wait(0.12):
            with _RUN_LOCK:
                chunk, pending[0] = pending[0], ""
            _emit(rid, chunk)

    def watcher():
        try:
            proc.wait()
        except Exception:                                                 # noqa: BLE001
            return
        time.sleep(0.35)                                 # 让读线程把管道里剩的读完
        with _RUN_LOCK:
            if r.get("code") is None:
                r["code"] = proc.returncode

    threading.Thread(target=ticker, daemon=True).start()
    threading.Thread(target=watcher, daemon=True).start()

    dec = codecs.getincrementaldecoder("utf-8")("replace")
    try:
        fd = proc.stdout.fileno()
        while True:
            buf = os.read(fd, 4096)
            if not buf:
                break
            text = dec.decode(buf)
            if not text:
                continue
            with _RUN_LOCK:
                parts = (pending[0] + text).split("\n")
                pending[0] = parts.pop()
            if parts:
                _emit(rid, "\n".join(parts) + "\n")
    except Exception:                                                     # noqa: BLE001
        pass
    finally:
        stop.set()
        with _RUN_LOCK:
            chunk, pending[0] = pending[0], ""
        _emit(rid, chunk)
        try:
            proc.wait(timeout=5)
        except Exception:                                                 # noqa: BLE001
            pass
        with _RUN_LOCK:
            if r.get("code") is None:
                r["code"] = proc.returncode
        try:
            proc.stdout.close()
        except Exception:                                                 # noqa: BLE001
            pass
        try:                                             # 收尾记一条运行日志
            S._log_run({"id": r["sid"], "name": r["name"], "at": r["at"], "args": r["args"],
                        "code": r.get("code"), "out": S.tail("".join(r["out"])), "err": "",
                        "dur": round(time.time() - r["t0"], 3), "cmd": r["cmd"],
                        "ok": r.get("code") == 0})
        except Exception:                                                 # noqa: BLE001
            pass


# ================================================================ 打开路径（`V-346`）
#: 从右往左退的时候**可以切**的那些字符（标点 / 括号 / 引号 / 空白）。
#: **故意不含 `\` `/`** —— 在分隔符上切会切出 `D:` 这种盘符相对路径，那不是个地方。
_CUTS = "，。；：！？、（）【】《》「」『』,;:.()[]{}<>\"'` \t"


def _exists(p):
    try:
        return p.exists()
    except OSError:                                     # 盘拔了 / 名字非法 / 权限不够
        return False


def _open_target(raw, shown=""):
    """把界面上报来的**候选路径**收敛到真存在的那一段 → `(Path 或 None, 剪过没有)`。

    界面上那条路径是从**一整段文字**里正则抠出来的，尾巴上常蘸着说明文字
    （`…114021.png（7680×2160，9125074 字节）` 里的 `（7680×2160，9125074`）。
    前端 `paths.js` 已经收了一道，这里是**第二道、也是最硬的一道：判据是文件系统本身**。

    顺序（`shown` 是前端修剪过的样子，`raw` 是它抠出来的原样）：
      ① **原样先试** —— 文件名里真带全角括号（`报告（旧）.txt`）时，前端可能剪过头，
         但原样是存在的 ⇒ 以**原样**为准（这才是那段文字真正指的东西）；
      ② 都不存在 ⇒ **按标点从右往左退**，退到第一个真存在的为止；
      ③ 还不行 ⇒ 退到**最长的存在祖先**（跟老行为一致：至少把上级目录打开）。
    """
    seen, cands = set(), []
    for one in (raw, shown):
        s = str(one or "").strip().strip('"')
        if not s or s in seen:
            continue
        seen.add(s)
        p = Path(s)
        cands.append(p if p.is_absolute() else (HOME / p))   # `user_data/…` 按 moss 根解析
    if not cands:
        return None, False
    for p in cands:                                     # ① 原样
        if _exists(p):
            return p, False
    for p in cands:                                     # ② 从右往左按标点退
        s = str(p)
        for i in range(len(s) - 1, 0, -1):
            if s[i] not in _CUTS:
                continue
            cut = s[:i].rstrip(_CUTS)
            if len(cut) < 3 or cut.endswith(":"):       # `D:` / `C:` 不是个地方
                continue
            if _exists(Path(cut)):
                return Path(cut), True
    q = cands[-1].parent                                # ③ 最长的存在祖先
    while q != q.parent:
        if _exists(q):
            return q, True
        q = q.parent
    return None, False


class Api:
    """界面能调的方法（`window.pywebview.api.<名字>(params)` / 内嵌时走垫片）。"""

    # ---------------------------------------------------------------- 读
    def list(self, params=None):
        """墙要的一切：**只有技能**（`V-284`：插件不出现在这一页）。

        界面 `load()`（启动和点「重试」都走它）发来的 `list` 最后落到这儿，
        查找本体是 `S.summary()`（扫技能目录）。
        """
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

    def sys_copy(self, params=None):
        """把一段文字放进剪贴板（界面上点"复制路径"用它）。

        ★ 为什么后端也要有一份：**独立窗口**（pywebview 的 WebView2）里
          `navigator.clipboard` 在非安全上下文下常常是不给的，而 tkinter 那条路
          一直通 —— 界面那边是"三条路依次退"（见 `ui/src/api.js` 的 `copy`），
          这里是最靠得住的那一条。
        """
        text = str((params or {}).get("text") or "")
        if not text:
            return {"ok": False, "msg": "没有要复制的内容"}
        try:
            import tkinter                                                   # noqa: PLC0415
            r = tkinter.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(text)
            r.update()
            r.destroy()
        except Exception as e:                                               # noqa: BLE001
            return {"ok": False, "msg": "复制失败：%s: %s" % (type(e).__name__, e)}
        return {"ok": True, "msg": "已复制"}

    def run_once(self, params=None):
        """在这儿**试跑一次**（跟 AI 调它走的是同一条路：stdin JSON → stdout）。

        ★ 只在**已经允许**的技能上给按（没允许的那条路本来就不通）—— 这里不绕闸。
        ★ `V-301`：回**结构化**结果（`text`/`out`/`err`/`code`/`dur`/`at`/`cmd`）——
          界面的「命令行面板」就靠它显示这次跑了什么、输出是什么（以前只回一句 `msg`，
          界面只能弹一行 toast）。同时 `S.run` 会记一条运行日志（「运行日志面板」读它）。
        """
        p = dict(params or {})
        sid = str(p.get("id") or "")
        args = p.get("args") if isinstance(p.get("args"), dict) else {}
        got = S.list_skills().get(sid)
        if not got:
            return {"ok": False, "msg": "没有这只技能：%s" % sid}
        r = S.run_detail(got["name"], args)
        r["msg"] = r.get("text") or ""       # 兼容旧界面 / toast 那一行
        return r

    # ---------------------------------------------------------------- 交互式运行（`V-302`）
    def _find_usable(self, sid):
        for it in S.usable().values():
            if str(it.get("id")) == str(sid):
                return it
        return None

    def run_start(self, params=None):
        """起一个技能进程**交互式**跑（`V-302`）：输出实时流、能给 stdin 写输入、能停。

        ★ 参数走 `MOSS_PKG_PARAMS` 环境变量（`S._env` 摆的）—— **stdin 整条留给交互**；
          技能要参数就读环境变量（技能 `input()` 的那一问才接得上）。没允许 / 写坏的不给跑。
        """
        p = dict(params or {})
        sid = str(p.get("id") or "")
        args = p.get("args") if isinstance(p.get("args"), dict) else {}
        it = self._find_usable(sid)
        if not it:
            return {"ok": False, "msg": "没有可用技能：%s（没允许、写坏了、或不存在）" % sid}
        argv = list(it.get("argv") or [])
        if not argv:
            return {"ok": False, "msg": "拼不出启动命令：%s" % (it.get("run_err") or "")}
        try:
            # ★ 二进制管道（**不用** text 模式）—— 读线程要 `os.read` 按块读、自己解码
            #   （跟主界面 `_pump_output` 一致：半行提示语也能及时出来）。
            proc = subprocess.Popen(
                argv, cwd=str(it["dir"]), env=S._env(args, sid),
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            return {"ok": False, "msg": "起不来：%s" % e}
        with _RUN_LOCK:
            _RID[0] += 1
            rid = "skill-%d" % _RID[0]
            _RUNS[rid] = {"proc": proc, "out": [], "code": None,
                          "sid": sid, "name": it.get("name") or sid, "args": args,
                          "at": time.strftime("%Y-%m-%d %H:%M:%S"), "t0": time.time(),
                          "cmd": argv}
        S.bump_stat(sid)                                  # 记一次调用（次数 +1 + 最近时间）
        threading.Thread(target=_pump_run, args=(rid,), daemon=True).start()
        # ★ 兜底：技能要是卡在读 stdin 等 EOF，1.2 秒后自动把 stdin 关掉放它跑
        threading.Timer(1.2, _maybe_close_stdin, args=(rid,)).start()
        return {"ok": True, "rid": rid, "cmd": argv}

    def run_poll(self, params=None):
        """看这个运行现在怎么样了（输出 / 还在不在跑 / 退出码）。"""
        p = dict(params or {})
        rid = str(p.get("rid") or "")
        with _RUN_LOCK:
            r = _RUNS.get(rid)
        if not r:
            return {"ok": False, "msg": "没有这个运行：%s" % rid}
        # ★ 「在跑」以**退出码**为准（`code is None` = 还在跑）：子进程一退就算完，
        #   不等管道 EOF（孙进程可能叼着管道不放）。
        return {"ok": True, "running": r.get("code") is None, "code": r.get("code"),
                "out": "".join(r["out"]), "cmd": r["cmd"], "at": r["at"]}

    def run_input(self, params=None):
        """往这个运行的 stdin 写一行（技能 `input()` 的那一问就接上了）。"""
        p = dict(params or {})
        rid = str(p.get("rid") or "")
        line = str(p.get("line") or "")
        with _RUN_LOCK:
            r = _RUNS.get(rid)
        if not r or r.get("code") is not None:
            return {"ok": False, "msg": "这个技能没在跑了"}
        if r.get("stdin_closed"):
            return {"ok": False, "msg": "它没在等输入（stdin 已经关了）"}
        with _RUN_LOCK:
            r["sent_input"] = True                        # 有人真写过输入 ⇒ 别再自动关 stdin
        try:
            r["proc"].stdin.write((line + "\n").encode("utf-8"))
            r["proc"].stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            return {"ok": False, "msg": "写不进去：%s" % e}
        return {"ok": True}

    def run_stop(self, params=None):
        """停掉这个交互式运行（连子孙一起）。"""
        p = dict(params or {})
        rid = str(p.get("rid") or "")
        with _RUN_LOCK:
            r = _RUNS.get(rid)
        if not r:
            return {"ok": False, "msg": "没有这个运行"}
        proc = r["proc"]
        try:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:                                                 # noqa: BLE001
            pass
        try:
            proc.kill()
        except Exception:                                                 # noqa: BLE001
            pass
        return {"ok": True, "msg": "已停掉"}

    def runs(self, params=None):
        """运行日志（新的在前）。`id` 给了就只看这只技能的。"""
        p = dict(params or {})
        sid = str(p.get("id") or "")
        limit = int(p.get("limit") or 60)
        return {"ok": True, "runs": S.list_runs(sid or None, limit),
                "log": str(S.run_log_path())}

    def clear_runs(self, params=None):
        """清运行日志：`id` 给了就只清它那几行，否则全清（界面上「清空日志」用它）。"""
        p = dict(params or {})
        sid = str(p.get("id") or "")
        ok, msg = S.clear_runs(sid or None)
        return {"ok": ok, "msg": msg, "log": str(S.run_log_path())}

    def open_path(self, params=None):
        """打开一个文件 / 目录（详情里那些可点的路径用它）。`V-346` 起有**两种开法**：

        · `mode="reveal"` → **在资源管理器里打开它所在的文件夹**并选中它
          （`explorer /select,`；**目录**就是打开它上一级、并选中它）—— 默认；
        · `mode="open"`   → **直接打开**：文件交给默认程序，目录就打开它。

        两条保险（`V-346`）：路径按 `raw` → `path` 依次试、不在就**按标点从右往左退**
        （`_open_target`）—— 因为界面那条路径是从一整段文字里抠出来的，尾巴上常带说明文字。
        """
        p = dict(params or {})
        raw = str(p.get("path") or "").strip().strip('"')
        if not raw:
            return {"ok": False, "msg": "没有路径"}
        mode = "open" if str(p.get("mode") or "").lower() == "open" else "reveal"
        path, trimmed = _open_target(str(p.get("raw") or raw), raw)
        if path is None:
            return {"ok": False, "msg": "路径不在：%s" % raw}
        try:
            if mode == "open":
                os.startfile(str(path))                 # noqa: S606  Windows：文件走默认程序 / 目录就打开它
                what = "打开了"
            elif str(path.parent) == str(path):         # 盘根（`D:\`）没有"上一级"可开 —— 直接开它
                os.startfile(str(path))                 # noqa: S606  Windows
                what = "打开了"
            else:
                # `explorer /select,` 这条命令**两种都对**：文件 = 开所在目录并选中它；
                # 目录 = 开它上一级并选中它。正好是那颗小文件夹图标要的意思。
                subprocess.Popen('explorer /select,"%s"' % path)     # noqa: S603,S607
                what = "打开了所在文件夹"
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}
        msg = "%s：%s" % (what, path)
        if trimmed:
            msg += "（路径尾巴上那段说明文字已经去掉）"
        return {"ok": True, "msg": msg}

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
