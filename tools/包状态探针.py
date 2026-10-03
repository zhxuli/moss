# -*- coding: utf-8 -*-
"""包状态探针（`V-220`）：**"这个包在不在跑"到底怎么认的？** —— 认错的代价是杀掉桌面。

为什么要有它（用户报的两件事）：
  · 「我尝试重启了 moss，这个还是显示停止按钮」—— 重启 moss 也还在 ⇒ 判断**不在界面里**，
    而是**进程层面**认出来的；
  · 「当我手动点停止，explorer.exe 会被停止，这也不太正常」—— 真凶就在这句里。

根因：`MOSS_PKG_ID` 是**注入到进程环境**里的，包拉起的**任何**子进程都会**继承**它（`P-18`）。
`suoluetu` 那个包的 .bat 里有 `start "" explorer.exe` ⇒ **explorer.exe 带着 `MOSS_PKG_ID=suoluetu`**，
而它**有窗口** ⇒ 老代码里 `_pkg_pids` 的第三条把它算成"suoluetu 在跑"，于是：
  ① 重启 moss 也照样显示「停止」（那是进程层面的判断）；
  ② 点「停止」⇒ `pkg_stop` 把 explorer.exe 一起杀了 —— **桌面和任务栏当场没了**。
（顺带：DSH 那条线上你的浏览器 Maxthon、node、pwsh 全带着 `MOSS_PKG_ID=dsh` ⇒ `dsh` 永远"在跑"，
"停止"下去就是把这些一起杀。）

现在这一条加了硬条件：**有窗口的进程，可执行文件必须真在包目录里**才算这个包。

这个探针造三个场面，全部用**真进程**：
  A 包自己的进程（`bootstrap.py …\\pkgs\\path\\main.py`，带 `MOSS_PKG_ID=path`）→ **必须算**；
  B 只是**继承了环境变量**的长驻窗口程序（notepad.exe 带 `MOSS_PKG_ID=suoluetu`）→ **必须不算**
    （老代码算 ⇒ 这就是"杀掉 explorer"的那条路）；
  C 包目录里的 exe（有窗口）→ **必须算**（正向控制，别为了修 B 把真界面判丢了）。

用法：
    .\\system\\runtimes\\python\\3.12\\python.exe tools\\包状态探针.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                    # noqa: BLE001
        pass


def load_host():
    os.environ["MOSS_HOME"] = str(ROOT)
    from core import ui as core_ui
    fd, tmp = tempfile.mkstemp(prefix="moss-ui-probe-", suffix=".json")
    os.close(fd)
    payload = core_ui.build_payload()
    Path(tmp).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.environ["MOSS_UI_DATA"] = tmp
    os.environ["MOSS_USER_DATA_DIR"] = str(payload["user_data"])
    os.environ["MOSS_HOST_CMD"] = json.dumps(core_ui.host_cmd(), ensure_ascii=False)
    import importlib.util
    spec = importlib.util.spec_from_file_location("moss_ui_main", ROOT / "system" / "ui" / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def spawn_windowed(exe, env, title):
    """起一个**真有顶层窗口**的进程（最小化的控制台窗）—— `_top_windows` 要的是
    "顶层 + 有标题"的窗口；notepad/mspaint 在 Win11 里是**商店应用的壳**，会立刻退出，
    拿它们当"有窗口的进程"验不出来（踩过一次）。"""
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7                          # SW_SHOWMINNOACTIVE：最小化、不抢焦点
    return subprocess.Popen([exe, "/k", "title " + title], env=env,
                            creationflags=subprocess.CREATE_NEW_CONSOLE, startupinfo=si)


def main():
    mod = load_host()
    api = mod.Api()
    import psutil
    res = []

    def chk(name, ok, detail=""):
        res.append((name, bool(ok), detail))
        print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + detail) if detail else ""))

    tmp = Path(tempfile.mkdtemp(prefix="moss_stateprobe_"))
    env = dict(os.environ)
    py = str(ROOT / "system" / "runtimes" / "python" / "3.12" / "python.exe")
    boot = str(ROOT / "system" / "bootstrap.py")
    pkg_main = str(ROOT / "system" / "pkgs" / "path" / "main.py")
    started = []

    try:
        print("=" * 72)
        print("A：包自己的进程（bootstrap.py …\\pkgs\\path\\main.py）—— 必须算")
        print("=" * 72)
        e = dict(env)
        e["MOSS_PKG_ID"] = "path"
        e["MOSS_UI_EMBED"] = "1"
        a = subprocess.Popen([py, boot, pkg_main], env=e, stdin=subprocess.PIPE,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        started.append(a)
        time.sleep(1.5)
        pids = mod._pkg_pids("path")
        chk("A 认出包自己的进程", a.pid in pids, "pids=%s" % sorted(pids))
        chk("A pkg_state 说在跑", api.pkg_state("path").get("running") is True, "")
        chk("A pkg_state 说是**谁**在跑（带命令行）",
            bool(api.pkg_state("path").get("procs")), "")

        print()
        print("=" * 72)
        print("B：只是**继承了 MOSS_PKG_ID** 的窗口程序（最小化控制台，冒充 suoluetu）—— 必须不算")
        print("=" * 72)
        e = dict(env)
        e["MOSS_PKG_ID"] = "suoluetu"           # 假装它是 suoluetu 包拉起来的（.bat 里 start 出来）
        b = spawn_windowed("cmd.exe", e, "MOSS-PROBE-B")
        started.append(b)
        time.sleep(2.0)
        wins_b = [w for w in mod._top_windows() if w["pid"] == b.pid]
        pids = mod._pkg_pids("suoluetu")
        chk("B 确实是个有窗口的进程（不然这条验的是空气）", b.pid in [w["pid"] for w in wins_b],
            "窗口 %d 个" % len(wins_b))
        chk("B 带标签的窗口程序**不算**这个包在跑", b.pid not in pids,
            "pid=%d pids=%s" % (b.pid, sorted(pids)))
        st = api.pkg_state("suoluetu")
        chk("B pkg_state 说没在跑（重启 moss 也就不会再显示「停止」）",
            st.get("running") is False, "running=%s pids=%s" % (st.get("running"), st.get("pids")))
        chk("B 于是 pkg_stop 也不会去杀它（不会再把桌面/浏览器带走）",
            b.pid not in mod._pkg_pids("suoluetu"), "")

        print()
        print("=" * 72)
        print("C：包目录里的 exe（有窗口）—— 必须算（正向控制，别为修 B 把真界面判丢）")
        print("=" * 72)
        # 造一个假包目录：里面放一份 cmd.exe 当"包自己的程序"
        pkgdir = tmp / "suoluetu"
        pkgdir.mkdir(parents=True, exist_ok=True)
        exe_in = pkgdir / "app.exe"
        shutil.copyfile(r"C:\Windows\System32\cmd.exe", exe_in)
        real_dirs = mod._pkg_dirs
        mod._pkg_dirs = lambda pid: ([str(pkgdir)] if str(pid) == "suoluetu" else real_dirs(pid))
        e = dict(env)
        e["MOSS_PKG_ID"] = "suoluetu"
        c = spawn_windowed(str(exe_in), e, "MOSS-PROBE-C")
        started.append(c)
        time.sleep(2.0)
        pids = mod._pkg_pids("suoluetu")
        chk("C 包目录里的 exe 算这个包（有窗口）", c.pid in pids, "pid=%d pids=%s" % (c.pid, sorted(pids)))
        mod._pkg_dirs = real_dirs

        print()
        print("=" * 72)
        print("D：真机现状（`dsh` 那条线）—— 用户浏览器/node/pwsh 不该再被算成 dsh")
        print("=" * 72)
        tagged, counted = [], []
        for pr in psutil.process_iter(["pid", "name"]):
            try:
                if (pr.environ() or {}).get("MOSS_PKG_ID") != "dsh":
                    continue
            except Exception:
                continue
            tagged.append((pr.pid, pr.info["name"]))
        dpids = mod._pkg_pids("dsh")
        for pid, name in tagged:
            if pid in dpids and str(name).lower() not in ("python.exe", "pythonw.exe"):
                counted.append((pid, name))
        chk("D 带 dsh 标签的**别的程序**不再被算进去", not counted,
            "还算进去的：" + (", ".join("%s(%s)" % (n, p) for p, n in counted) or "无"))
    finally:
        for p in started:
            try:
                mod._kill_tree(p.pid)
            except Exception:                                        # noqa: BLE001
                pass
        subprocess.run(["taskkill", "/f", "/im", "notepad.exe"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 72)
    bad = [x for x in res if not x[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的", len(res), len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
