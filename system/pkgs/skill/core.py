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

import skill_lib as S

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
  · 技能本体分两层：user_data/state/skill/<名字>/（用户层，要允许）+ system/pkgs/skill/builtin/<名字>/（预制层，出厂即用；同名 user 覆盖）。
  · **批准那几下（allow / revoke / rm / promote）必须人来做** —— AI 拿 run_moss 调会被拒。
  · 不带参数时：界面里点「运行」→ 开窗口；命令行 / AI 调 → 只打这一份用法（对 AI 友好）。
"""

def data_dir():
    d = (os.environ.get("MOSS_PLUGIN_DATA_DIR") or "").strip()
    return Path(d) if d else (HOME / "user_data" / "state" / "skill")

def _human(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return ("%.0f %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024
    return "%.1f GB" % n

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
        if len(r["out"]) > 8000:
            del r["out"][:3000]

def _maybe_close_stdin(rid):
    with _RUN_LOCK:
        r = _RUNS.get(rid)
    if not r or r.get("code") is not None or r["out"] or r.get("sent_input"):
        return
    try:
        r["proc"].stdin.close()
    except Exception:
        pass
    with _RUN_LOCK:
        r["stdin_closed"] = True

def _pump_run(rid):
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
        except Exception:
            return
        time.sleep(0.35)
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
    except Exception:
        pass
    finally:
        stop.set()
        with _RUN_LOCK:
            chunk, pending[0] = pending[0], ""
        _emit(rid, chunk)
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        with _RUN_LOCK:
            if r.get("code") is None:
                r["code"] = proc.returncode
        try:
            proc.stdout.close()
        except Exception:
            pass
        try:
            S._log_run({"id": r["sid"], "name": r["name"], "at": r["at"], "args": r["args"],
                        "code": r.get("code"), "out": S.tail("".join(r["out"])), "err": "",
                        "dur": round(time.time() - r["t0"], 3), "cmd": r["cmd"],
                        "ok": r.get("code") == 0})
        except Exception:
            pass

_CUTS = "，。；：！？、（）【】《》「」『』,;:.()[]{}<>\"'` \t"

def _exists(p):
    try:
        return p.exists()
    except OSError:
        return False

def _open_target(raw, shown=""):
    seen, cands = set(), []
    for one in (raw, shown):
        s = str(one or "").strip().strip('"')
        if not s or s in seen:
            continue
        seen.add(s)
        p = Path(s)
        cands.append(p if p.is_absolute() else (HOME / p))
    if not cands:
        return None, False
    for p in cands:
        if _exists(p):
            return p, False
    for p in cands:
        s = str(p)
        for i in range(len(s) - 1, 0, -1):
            if s[i] not in _CUTS:
                continue
            cut = s[:i].rstrip(_CUTS)
            if len(cut) < 3 or cut.endswith(":"):
                continue
            if _exists(Path(cut)):
                return Path(cut), True
    q = cands[-1].parent
    while q != q.parent:
        if _exists(q):
            return q, True
        q = q.parent
    return None, False

class Api:
    def list(self, params=None):
        got = S.summary()
        for r in got["skills"]:
            r["files_h"] = "%d 个文件 · %s" % (
                r["files_n"],
                _human(sum(f.get("size") or 0 for f in (r.get("files") or []))))
        got["dir"] = str(data_dir())
        return got

    def read(self, params=None):
        sid = str((params or {}).get("id") or "")
        got = S.read(sid)
        if got.get("ok"):
            got["files_h"] = [dict(f, size_h=_human(f.get("size"))) for f in got.get("files") or []]
        return got

    def plan(self, params=None):
        p = dict(params or {})
        return S.promote_plan(str(p.get("id") or ""), str(p.get("new_id") or ""))

    def doc(self, params=None):
        p = dict(params or {})
        return S.doc(str(p.get("id") or ""))

    def help(self, params=None):
        return {"ok": True, "text": HELP}

    def reveal(self, params=None):
        d = Path(str((params or {}).get("dir") or data_dir()))
        if not d.is_dir():
            return {"ok": False, "msg": "目录不在：%s" % d}
        try:
            os.startfile(str(d))
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}
        return {"ok": True, "msg": "打开了：%s" % d}

    def sys_copy(self, params=None):
        text = str((params or {}).get("text") or "")
        if not text:
            return {"ok": False, "msg": "没有要复制的内容"}
        try:
            import tkinter
            r = tkinter.Tk()
            r.withdraw()
            r.clipboard_clear()
            r.clipboard_append(text)
            r.update()
            r.destroy()
        except Exception as e:
            return {"ok": False, "msg": "复制失败：%s: %s" % (type(e).__name__, e)}
        return {"ok": True, "msg": "已复制"}

    def run_once(self, params=None):
        p = dict(params or {})
        sid = str(p.get("id") or "")
        args = p.get("args") if isinstance(p.get("args"), dict) else {}
        got = S.list_skills().get(sid)
        if not got:
            return {"ok": False, "msg": "没有这只技能：%s" % sid}
        r = S.run_detail(got["name"], args)
        r["msg"] = r.get("text") or ""
        return r

    def _find_usable(self, sid):
        for it in S.usable().values():
            if str(it.get("id")) == str(sid):
                return it
        return None

    def run_start(self, params=None):
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
        S.bump_stat(sid)
        threading.Thread(target=_pump_run, args=(rid,), daemon=True).start()
        threading.Timer(1.2, _maybe_close_stdin, args=(rid,)).start()
        return {"ok": True, "rid": rid, "cmd": argv}

    def run_poll(self, params=None):
        p = dict(params or {})
        rid = str(p.get("rid") or "")
        with _RUN_LOCK:
            r = _RUNS.get(rid)
        if not r:
            return {"ok": False, "msg": "没有这个运行：%s" % rid}
        return {"ok": True, "running": r.get("code") is None, "code": r.get("code"),
                "out": "".join(r["out"]), "cmd": r["cmd"], "at": r["at"]}

    def run_input(self, params=None):
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
            r["sent_input"] = True
        try:
            r["proc"].stdin.write((line + "\n").encode("utf-8"))
            r["proc"].stdin.flush()
        except (BrokenPipeError, OSError, ValueError) as e:
            return {"ok": False, "msg": "写不进去：%s" % e}
        return {"ok": True}

    def run_stop(self, params=None):
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
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        return {"ok": True, "msg": "已停掉"}

    def runs(self, params=None):
        p = dict(params or {})
        sid = str(p.get("id") or "")
        limit = int(p.get("limit") or 60)
        return {"ok": True, "runs": S.list_runs(sid or None, limit),
                "log": str(S.run_log_path())}

    def clear_runs(self, params=None):
        p = dict(params or {})
        sid = str(p.get("id") or "")
        ok, msg = S.clear_runs(sid or None)
        return {"ok": ok, "msg": msg, "log": str(S.run_log_path())}

    def open_path(self, params=None):
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
                os.startfile(str(path))
                what = "打开了"
            elif str(path.parent) == str(path):
                os.startfile(str(path))
                what = "打开了"
            else:
                subprocess.Popen('explorer /select,"%s"' % path)
                what = "打开了所在文件夹"
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}
        msg = "%s：%s" % (what, path)
        if trimmed:
            msg += "（路径尾巴上那段说明文字已经去掉）"
        return {"ok": True, "msg": msg}

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

    def cli(self, args):
        a = [str(x) for x in (args or []) if str(x).strip()]
        verb = (a[0].lower() if a else "")
        rest = a[1:]
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
            params = {}
            for one in rest[1:]:
                k, sep, v = str(one).partition("=")
                if sep:
                    params[k.strip()] = v
            print(S.run(got["name"], params))
            return 0, ""
        return 2, "认不出这个动词：%s\n\n%s" % (verb, HELP.rstrip())

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
    import webview
    page = HERE / "ui" / "index.html"
    win = webview.create_window("技能", str(page), js_api=Api(),
                                width=1080, height=740, min_size=(760, 520))
    webview.start()
    return win
