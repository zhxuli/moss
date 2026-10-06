# -*- coding: utf-8 -*-
"""技能运行日志探针（`V-301`）：结构化运行结果 + 运行日志（记 / 读 / 清）。

只碰临时 `user_data`（`MOSS_USER_DATA_DIR`）——**不碰真实的技能目录**。
造一只最小的 python 技能（入口把 stdin 原样回显、写一句 stderr、退出码 3），真跑一遍。

用法：
    system\\runtimes\\python\\3.12\\python.exe tools\\技能运行日志探针.py
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TMP = Path(tempfile.mkdtemp(prefix="moss_skilllog_"))
os.environ["MOSS_HOME"] = str(ROOT)
os.environ["MOSS_USER_DATA_DIR"] = str(TMP)
os.environ["MOSS_PLUGIN_DATA_DIR"] = str(TMP / "state" / "skill")

sys.path.insert(0, str(ROOT / "system" / "ai"))
import skill_lib as S                                                   # noqa: E402

RES = []


def chk(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + str(detail)) if detail else ""))


# ---- 造一只最小技能 ----
d = TMP / "state" / "skill" / "probe-echo"
d.mkdir(parents=True)
(d / "pkg.json").write_text(json.dumps({
    "spec": 1, "id": "probe-echo", "kind": "task", "version": "1.0.0",
    "name": {"zh-CN": "探针回显"}, "desc": {"zh-CN": "把参数回显（探针用）"},
    "runner": "python", "entry": {"file": "run.py"},
    "params": [{"name": "msg", "type": "string", "required": False, "desc": "一句话"}],
    "ai": {"expose": True, "risk": "low", "timeout": 30, "why": "探针"},
}, ensure_ascii=False), encoding="utf-8")
(d / "run.py").write_text(
    "import sys\n"
    "data = sys.stdin.read()\n"
    "sys.stderr.write('diag line\\n')\n"
    "print('echo:' + data)\n"
    "sys.exit(3)\n", encoding="utf-8")
S.allow("probe-echo", True)

print("=" * 72)
print("A：run_detail 回结构化结果（界面「命令行面板」用它）")
print("=" * 72)
r = S.run_detail("probe-echo", {"msg": "hi"})
chk("ok=False（退出码 3）", r.get("ok") is False, str(r.get("ok")))
chk("带 code=3", r.get("code") == 3, str(r.get("code")))
chk("带 out（echo:…）", "echo:" in (r.get("out") or ""), repr((r.get("out") or "")[:60]))
chk("带 err（diag line）", "diag line" in (r.get("err") or ""), repr((r.get("err") or "")[:60]))
chk("带 cwd / cmd / at / dur", bool(r.get("cwd")) and isinstance(r.get("cmd"), list)
    and bool(r.get("at")) and r.get("dur") is not None, "")

print()
print("=" * 72)
print("B：运行日志记下来了（界面「运行日志面板」读它）")
print("=" * 72)
chk("日志文件存在", S.run_log_path().is_file(), str(S.run_log_path()))
runs = S.list_runs("probe-echo")
chk("list_runs 有一条、id 对", len(runs) >= 1 and runs[0].get("id") == "probe-echo",
    json.dumps(runs[:1], ensure_ascii=False)[:120])
chk("那条里有 code=3 / out / at",
    bool(runs) and runs[0].get("code") == 3 and "echo:" in (runs[0].get("out") or ""), "")
chk("别的技能看不到它（按 id 过滤）", S.list_runs("别的技能") == [], "")

print()
print("=" * 72)
print("C：run()（给模型的文本）照旧返回文本，**也**记日志")
print("=" * 72)
before = len(S.list_runs("probe-echo"))
txt = S.run("probe-echo", {"msg": "again"})
chk("回的是**文本**（不是 dict）", isinstance(txt, str) and "退出码 3" in txt, repr(str(txt)[:60]))
chk("又多记了一条", len(S.list_runs("probe-echo")) == before + 1, "")

print()
print("=" * 72)
print("D：clear_runs（界面「清空日志」用它）")
print("=" * 72)
ok, msg = S.clear_runs("probe-echo")
chk("清掉这只技能的", ok is True and S.list_runs("probe-echo") == [], msg)

print()
print("=" * 72)
print("E：`:skill` 插件那层的 Api（run_once / runs / clear_runs）")
print("=" * 72)
sys.path.insert(0, str(ROOT / "system" / "pkgs" / "skill"))
import core as C                                                        # noqa: E402
api = C.Api()
rr = api.run_once({"id": "probe-echo", "args": {"msg": "api"}})
chk("Api.run_once 回结构化（code / out / msg）",
    rr.get("code") == 3 and "echo:" in (rr.get("out") or "") and bool(rr.get("msg")), repr(str(rr)[:90]))
chk("Api.run_once 带 at / cwd", bool(rr.get("at")) and bool(rr.get("cwd")), "")
runs2 = api.runs({"id": "probe-echo"})
chk("Api.runs 读得回来", (runs2.get("ok") is True) and len(runs2.get("runs") or []) >= 1,
    json.dumps(runs2, ensure_ascii=False)[:90])
cl = api.clear_runs({"id": "probe-echo"})
chk("Api.clear_runs 清掉了", cl.get("ok") is True and S.list_runs("probe-echo") == [], str(cl.get("msg")))

print()
print("=" * 72)
print("F：交互式运行（`V-302`）—— run_start / run_poll / run_input / run_stop")
print("=" * 72)


def _mkskill(sid, code):
    dd = TMP / "state" / "skill" / sid
    dd.mkdir(parents=True, exist_ok=True)
    (dd / "pkg.json").write_text(json.dumps({
        "spec": 1, "id": sid, "kind": "task", "version": "1.0.0",
        "name": {"zh-CN": sid}, "desc": {"zh-CN": "探针用"},
        "runner": "python", "entry": {"file": "run.py"},
        "ai": {"expose": True, "risk": "low", "timeout": 30, "why": "探针"},
    }, ensure_ascii=False), encoding="utf-8")
    (dd / "run.py").write_text(code, encoding="utf-8")
    S.allow(sid, True)


# 一只会"问一句、等你答"的技能
# ★ 用 `input('ASK:name?')` —— 提示语**不带换行**（这是关键：`for line in proc.stdout`
#   那种"按行读"会把没有换行的提示语一直攥着不交，界面看起来才"什么都没问"）
_mkskill("probe-ask",
         "name = input('ASK:name?')\n"
         "print('GOT:' + name)\n")

r = api.run_start({"id": "probe-ask"})
chk("run_start 回了一个 rid", r.get("ok") is True and bool(r.get("rid")), str(r)[:80])
rid = r.get("rid")
out = ""
for _ in range(80):
    p = api.run_poll({"rid": rid})
    out = p.get("out") or ""
    if "ASK:name?" in out:
        break
    time.sleep(0.1)
chk("能看到它的**提问**（输出是实时流过来的）", "ASK:name?" in out, repr(out[:60]))
chk("这时它还在跑（没被一次跑完）", api.run_poll({"rid": rid}).get("running") is True, "")
api.run_input({"rid": rid, "line": "张三"})
code = None
for _ in range(80):
    p = api.run_poll({"rid": rid})
    out = p.get("out") or ""
    if not p.get("running"):
        code = p.get("code")
        break
    time.sleep(0.1)
chk("输入**喂进去了**（输出里有 GOT:张三）", "GOT:张三" in out, repr(out[:80]))
chk("跑完了、退出码 0", code == 0, str(code))
chk("这次交互式运行也记进日志了",
    any(x.get("id") == "probe-ask" for x in S.list_runs("probe-ask")), "")
_st = S.load_stats().get("probe-ask") or {}
chk("★ 最近调用时间 / 次数也更新了（`bump_stat` 生效）",
    bool(_st.get("at")) and int(_st.get("n") or 0) >= 1, str(_st))
chk("★ 列表里那一行的 last_called 也带着它",
    bool((S.list_skills().get("probe-ask") or {}).get("last_called")),
    str((S.list_skills().get("probe-ask") or {}).get("last_called")))

# 一只长跑的：验「停」
_mkskill("probe-sleep", "import time\ntime.sleep(60)\n")
r2 = api.run_start({"id": "probe-sleep"})
rid2 = r2.get("rid")
time.sleep(0.4)
chk("长跑那只在跑", api.run_poll({"rid": rid2}).get("running") is True, "")
api.run_stop({"rid": rid2})
stopped = False
for _ in range(60):
    if not api.run_poll({"rid": rid2}).get("running"):
        stopped = True
        break
    time.sleep(0.1)
chk("run_stop 真的把它停掉了", stopped, "")

# ★ 像 `now` / `shot` 那样用 `sys.stdin.read()` 读参数的技能：交互模式下它会等 EOF 卡住 ——
#   应被"1.2 秒没消息就自动关 stdin"兜底放行（`V-302` 你报的现场）
_mkskill("probe-readall",
         "import sys\nraw = sys.stdin.read()\nprint('GOTLEN:' + str(len(raw)))\n")
r3 = api.run_start({"id": "probe-readall"})
rid3 = r3.get("rid")
out3, code3 = "", None
for _ in range(60):
    p = api.run_poll({"rid": rid3})
    out3 = p.get("out") or ""
    if not p.get("running"):
        code3 = p.get("code")
        break
    time.sleep(0.1)
chk("★ 读**全部** stdin 的技能也能跑完（卡住时自动关 stdin 放行）",
    "GOTLEN:" in out3 and code3 == 0, repr(out3[:60]) + " code=" + str(code3))

shutil.rmtree(TMP, ignore_errors=True)
bad = [x for x in RES if not x[1]]
print()
print("=" * 72)
print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的", len(RES), len(bad)))
sys.exit(0 if not bad else 1)
