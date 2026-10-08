# -*- coding: utf-8 -*-
"""更名跟随 / 退出收进程 / 自动启动 —— 三合一探针（`V-354` ~ `V-356`）。

为什么要有它
------------
这三件事的判据全在**界面进程**里（`system/ui/main.py`），而且都是"看不见的机制"：
  · **更名跟随**判错 = 界面停在一张死页上（用户报的就是这个："老的失效 新的没自动打开"）；
  · **退出收进程**判错有两个方向 —— 收不干净（留一地 moss/python 孤儿），或者**收过头**
    （把 explorer.exe / 用户的浏览器一起杀了，`V-220` 那两起真事故就是这么来的）；
  · **自动启动**判错 = 一开界面就乱跑东西 / 参数丢了。
所以下面**全用真目录 + 真进程**跑一遍，一条条断言（不是读代码"看着对"）。

跑法（自带运行时那个 python，它带 psutil）：
    .\\system\\runtimes\\python\\3.12\\python.exe tools\\更名跟随探针.py

★ 全程把 `MOSS_HOME` / `MOSS_USER_DATA_DIR` 指到一个**临时目录** —— 一根手指都不碰真
  `user_data/`（AGENTS.md 那条硬规矩）。
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / "system" / "runtimes" / "python" / "3.12" / "python.exe"
if not PY.is_file():
    PY = Path(sys.executable)

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                    # noqa: BLE001
        pass

FAILS = []


def chk(name, ok, detail=""):
    print(("  OK  " if ok else " FAIL ") + name + (("  " + str(detail)) if detail else ""))
    if not ok:
        FAILS.append(name)


# ---------------------------------------------------------------- 临时安装根（不碰真 user_data）
TMP = Path(tempfile.mkdtemp(prefix="moss-watch-probe-"))
UD = TMP / "user_data"
(UD / "pkgs").mkdir(parents=True, exist_ok=True)
(TMP / "system" / "pkgs").mkdir(parents=True, exist_ok=True)
os.environ["MOSS_HOME"] = str(TMP)
os.environ["MOSS_USER_DATA_DIR"] = str(UD)
os.environ["MOSS_HOST_CMD"] = json.dumps([str(PY), str(ROOT / "moss.py")])

sys.path.insert(0, str(ROOT))
from core import ui as core_ui                                           # noqa: E402


def mk_pkg(pid, name):
    d = UD / "pkgs" / pid
    d.mkdir(parents=True, exist_ok=True)
    (d / "pkg.json").write_text(
        json.dumps({"spec": 1, "id": pid, "name": name, "kind": "task"},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return d


def write_man(pid_dir, pid, name=None, broken=False):
    man = pid_dir / "pkg.json"
    if broken:
        man.write_text("{ 这不是 JSON", encoding="utf-8")
        return
    data = json.loads(man.read_text(encoding="utf-8"))
    data["id"] = pid
    if name is not None:
        data["name"] = name
    man.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_ui():
    """按 `tools/包状态探针.py` 那套把界面后端**加载**起来（不开窗口、不进主循环）。"""
    payload = core_ui.build_payload()
    fd, tmp = tempfile.mkstemp(prefix="moss-ui-probe-", suffix=".json")
    os.close(fd)
    Path(tmp).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.environ["MOSS_UI_DATA"] = tmp
    spec = importlib.util.spec_from_file_location("moss_ui_main",
                                                 ROOT / "system" / "ui" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


print("临时安装根：%s" % TMP)
M = load_ui()
api = M._API
print()

# ================================================================ A · 更名跟随（`V-355`）
print("A 更名跟随（指纹 / 兜底 / 真没了 / 清单读坏了）")
mk_pkg("aaa", "甲")
mk_pkg("bbb", "乙")
base = M._pkg_watch_poll()
chk("A1 第一次只立基线（什么都不报）",
    base["renamed"] == [] and base["gone"] == [] and base["changed"] is False, base)

# 真改名：和 `moss --rename aaa zzz` 一模一样 —— 目录名 + 清单里的 id 一起改
(UD / "pkgs" / "aaa").rename(UD / "pkgs" / "zzz")
write_man(UD / "pkgs" / "zzz", "zzz")
got = M._pkg_watch_poll()
chk("A2 改名认出来了（依据=指纹一致）",
    got["renamed"] == [["aaa", "zzz", "指纹一致"]], got)
chk("A2b 走掉的那个不算'没了'", got["gone"] == [], got)

# 兜底那条：清单内容也改了（指纹对不上）⇒ 一个走、一个来，照样认得出
(UD / "pkgs" / "bbb").rename(UD / "pkgs" / "ccc")
write_man(UD / "pkgs" / "ccc", "ccc", name="丙")
got = M._pkg_watch_poll()
chk("A3 指纹对不上时按新旧 id 推断（用户提的那条兜底）",
    got["renamed"] == [["bbb", "ccc", "按新旧 id 推断"]], got)

# 真删掉（目录都没了）⇒ 报 gone，界面据此把死页收掉
shutil.rmtree(UD / "pkgs" / "zzz")
got = M._pkg_watch_poll()
chk("A4 包真没了 ⇒ gone", got["gone"] == ["zzz"] and got["renamed"] == [], got)

# 目录还在、只是清单被写坏了（编辑器正开着那种）⇒ **不许**报"没了"
(UD / "pkgs" / "ccc" / "pkg.json").write_text("{ 这不是 JSON", encoding="utf-8")
got = M._pkg_watch_poll()
chk("A5 清单读坏了但目录还在 ⇒ 不报'没了'（不吓人）", got["gone"] == [], got)
mk_pkg("ccc", "丙")                      # 还原成好清单，接着跑 B 段
M._pkg_watch_poll()
print()

# ================================================================ B · 退出收进程（`V-354`）
print("B 退出收进程（真进程：起一个假包进程，看它收不收得掉）")
pdir = UD / "pkgs" / "probe"
pdir.mkdir(parents=True, exist_ok=True)
(pdir / "main.py").write_text("import time\ntime.sleep(180)\n", encoding="utf-8")
env = dict(os.environ)
env["MOSS_PKG_ID"] = "probe"
proc = subprocess.Popen([str(PY), str(pdir / "main.py")], env=env,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.5)
chk("B1 假包进程起来了（命令行里带 /pkgs/probe/）",
    proc.poll() is None, "pid=%s" % proc.pid)
M.DATA = {"packages": [{"id": "probe", "dir": str(pdir), "name": "探针假包"}]}
killed = M._kill_all_pkg_procs()
time.sleep(1.0)
chk("B2 收进程：假包进程被收掉了", proc.poll() is not None, "killed=%s" % (killed,))
chk("B3 没收自己（界面进程还活着）", os.getpid() not in killed, killed)
try:
    proc.kill()
except Exception:                                                        # noqa: BLE001
    pass

# 反向控制：一个**跟我没有进程关系**的进程，而且它身上也带着 `MOSS_PKG_ID=probe`
# —— 正好验两件事：只认包目录（不认环境变量）、只收自己的子孙。
# ★ 怎么让它"跟我没关系"：让一个**短命的中间进程**去起它，中间进程一退，它的父 pid
#   就成了死号 ⇒ 它不在"我的进程树"里（不然新的第 ④ 条会把它当"我拉起的"收掉 ——
#   那是对的行为，但这一条想验的是"别人的进程一根手指都不碰"）。
pidfile = TMP / "bystander.pid"
launcher = ("import os, subprocess, sys, time\n"
            "p = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'],\n"
            "                     env=dict(os.environ, MOSS_PKG_ID='probe'))\n"
            "open(%r, 'w').write(str(p.pid))\n"
            "time.sleep(0.4)\n" % str(pidfile))
subprocess.run([str(PY), "-c", launcher], timeout=30,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1.0)
try:
    import psutil
except ImportError:
    psutil = None
try:
    bpid = int(pidfile.read_text(encoding="utf-8").strip())
except Exception:                                                        # noqa: BLE001
    bpid = 0
chk("B4 反向控制：不相干的进程（带 MOSS_PKG_ID 但不在包目录里）一个都没碰",
    bool(bpid) and (psutil.pid_exists(bpid) if psutil else True), "pid=%s" % bpid)
if bpid and psutil:
    try:
        psutil.Process(bpid).kill()
    except Exception:                                                    # noqa: BLE001
        pass
print()

# ================================================================ C · 新设置项 + 自动启动
print("C 新设置项（config.toml 里的 ui.kill_pkgs_on_exit）")
(UD / "config.toml").write_text("[ui]\nkill_pkgs_on_exit = true\n", encoding="utf-8")
M._CFG_CACHE["data"] = None
chk("C1 读得到（true）", M._cfg("ui", "kill_pkgs_on_exit", False) is True)
(UD / "config.toml").write_text("[symbols]\nplugin_mode = \":\"\n", encoding="utf-8")
M._CFG_CACHE["data"] = None
chk("C2 文件里没这一项 ⇒ 交回默认 false",
    M._cfg("ui", "kill_pkgs_on_exit", False) is False)
(UD / "config.toml").unlink()
M._CFG_CACHE["data"] = None
chk("C3 配置文件不在也不炸（回默认）", M._cfg("ui", "kill_pkgs_on_exit", False) is False)
(UD / "config.toml").write_text("[ui]\nkill_pkgs_on_exit = false\n", encoding="utf-8")
M._CFG_CACHE["data"] = None
chk("C4 显式 false 就是 false（别把假值当'没读到'）",
    M._cfg("ui", "kill_pkgs_on_exit", True) is False)
print()

print("D 自动启动（存 / 读 / 落盘 / 脏数据）")
M.DATA = {"packages": [{"id": "probe", "name": "探针假包", "kind": "task"}]}
r = api.autostart_set([{"kind": "pkg", "id": "probe", "args": "60%"},
                       {"kind": "hist", "id": "D:/x/main.py", "cwd": "D:/x",
                        "name": "main.py"}])
chk("D1 存得进去（整表存回）", bool(r.get("ok")), r)
g = api.autostart_get()
chk("D2 读回来一模一样（两条 + 参数 + cwd；`V-358` 起没有总开关）",
    len(g["items"]) == 2 and "on" not in g
    and g["items"][0]["id"] == "probe" and g["items"][0]["args"] == "60%"
    and g["items"][1]["kind"] == "hist" and g["items"][1]["cwd"] == "D:/x", g)
chk("D3 候选里有包表", any(p["id"] == "probe" for p in g["packages"]), g["packages"])
f = json.loads((UD / "state" / "_ui_autostart.json").read_text(encoding="utf-8"))
chk("D4 落盘在 state/_ui_autostart.json（不是 config.toml）", len(f["items"]) == 2, f)
r = api.autostart_set([{"kind": "pkg", "id": ""}, {"kind": "pkg", "id": "probe"}])
chk("D5 空 id 丢掉、只留能跑的", len(r["items"]) == 1 and r["items"][0]["id"] == "probe", r)
(UD / "state" / "_ui_autostart.json").write_text("{ 坏文件", encoding="utf-8")
g = api.autostart_get()
chk("D6 文件读坏了 ⇒ 当没配（不是崩）", g["ok"] is True and g["items"] == [], g)
print()

# ================================================================ E · 真跑一次 moss --rename
# `V-357`（你 2026-10-09 提的）：「我们给他一个新的名字 那么 你需要也改它的 name …
# 必须运行一个替换功能 相当于 python 的 replace(老id, 新id)」。
# ★ 这一段**不模拟**，真去跑宿主的 `moss --rename`（源码形态：`python moss.py --rename`）——
#   因为那件事的真相在 `core/cli.py::cmd_rename` 里，模拟一遍等于什么都没验。
print("E 真跑一次 moss --rename（显示名 / 别名里的旧 id 一起换；指纹还得认得出来）")
old_dir = mk_pkg("oldname", "新建插件 oldname")
man = json.loads((old_dir / "pkg.json").read_text(encoding="utf-8"))
# 真骨架那种形状（`core/cli.py::NEW_PKG_JSON`）：`name` 是**多语言表**，而且 id 就写在里面。
# 顺手多给一门语言 —— 换名只该换 id，别的语言不许丢。
man["name"] = {"zh-CN": "新建插件 oldname", "en": "New plugin oldname"}
man["desc"] = {"zh-CN": "一句话说明这个插件干什么"}
man["aliases"] = ["oldname", "myoldname"]
(old_dir / "pkg.json").write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
M._pkg_watch_poll()                      # 立基线（这时它还叫 oldname）
fp_before = M._pkg_ident(old_dir / "pkg.json", "user", "oldname")
env2 = dict(os.environ)                  # MOSS_HOME / MOSS_USER_DATA_DIR 已经指到临时目录
host = subprocess.run([str(PY), str(ROOT / "moss.py"), "--rename", "oldname", "newname"],
                      cwd=str(ROOT), env=env2, capture_output=True, text=True,
                      encoding="utf-8", errors="replace")
new_dir = UD / "pkgs" / "newname"
chk("E1 moss --rename 跑成功（退出码 0）", host.returncode == 0,
    (host.stdout or "") + (host.stderr or ""))
chk("E2 包目录搬过去了、旧目录没了",
    new_dir.is_dir() and not old_dir.exists(), "new=%s old存在=%s" % (new_dir, old_dir.exists()))
data = json.loads((new_dir / "pkg.json").read_text(encoding="utf-8"))
chk("E3 清单 id 换成了新 id", data.get("id") == "newname", data.get("id"))
chk("E4 显示名里的旧 id 也被换了（多语言表逐条 replace，别的语言不许丢）",
    (data.get("name") or {}) == {"zh-CN": "新建插件 newname", "en": "New plugin newname"},
    data.get("name"))
chk("E5 别名：整条等于旧 id 的换成新 id，别的别名一个字不动",
    data.get("aliases") == ["newname", "myoldname"], data.get("aliases"))
chk("E6 desc 没被误伤（只动 name / 别名）",
    (data.get("desc") or {}).get("zh-CN") == "一句话说明这个插件干什么", data.get("desc"))
fp_after = M._pkg_ident(new_dir / "pkg.json", "user", "newname")
chk("E7 改名前后**指纹一模一样**（不然「指纹一致」那条判据就废了）",
    bool(fp_before) and fp_before == fp_after, "%s → %s" % (fp_before, fp_after))
got = M._pkg_watch_poll()
chk("E8 界面这边把这次真改名认成「指纹一致」",
    got["renamed"] == [["oldname", "newname", "指纹一致"]], got)
print()

shutil.rmtree(TMP, ignore_errors=True)
print("=" * 70)
print("失败：%d" % len(FAILS))
if FAILS:
    print(json.dumps(FAILS, ensure_ascii=False, indent=2))
sys.exit(1 if FAILS else 0)
