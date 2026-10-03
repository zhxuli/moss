# -*- coding: utf-8 -*-
"""跑完探针（`V-219`）：**"到底跑没跑完"只能看进程，不能看管道**。

为什么要有它
------------
用户报的：「程序已经退出了，界面还是显示一个红色的停止按钮；但我在命令行这里发一个回车，
它又提示**已经跑完了**的报错」。根因不是一个 bug，而是**两处口径不一致**：

  · `run_poll`（界面每 200ms 问一次，决定那颗按钮红不红）看的是 `_pump_output` 里
    **管道读到 EOF** 才算结束；
  · `run_input`（命令行那行回车）问的是**进程本身**（`proc.poll()`）。

而子进程的 stdout 是我们的管道、**孙进程会把写端继承下去** —— 最典型的就是 `.bat` 里那句
`start "" explorer.exe`（`suoluetu` 那个包就是这么写的）。于是 cmd.exe 早退了、
explorer.exe 还叼着管道 ⇒ 管道永不 EOF ⇒ 按钮永远红着，可回车又说"已经跑完了"。

这个探针拿**宿主自己那份 `_pump_output` / `run_poll` / `run_input`** 跑三个场景：

  A 普通命令（`cmd /c echo`）—— 必须正常收工（别把正常路径弄坏）；
  B 孙进程叼着管道（`start "" timeout 30`）—— 子进程退了之后必须**很快**说"跑完了"，
    而且必须和 `run_input` **说法一致**（这就是用户那个自相矛盾）；
  C 真·长驻（直接 `timeout 30`，不 start）—— 必须一直说"在跑"，并且 `run_stop` 停得掉
    （别把"真的还在跑"误判成跑完）。

用法：
    .\\system\\runtimes\\python\\3.12\\python.exe tools\\跑完探针.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                    # noqa: BLE001
        pass


def load_host():
    """把 `system/ui/main.py` 当模块加载（就是 moss 界面进程用的那一份）。"""
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


def start_run(mod, argv, tag):
    """照 `Api.run_start` 的样子起一次运行（只是把命令行换成我们自己的），复用它的读线程。"""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            stdin=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", bufsize=1,
                            creationflags=mod.NO_WINDOW)
    rid = uuid.uuid4().hex[:10]
    with mod.RUNS_LOCK:
        mod.RUNS[rid] = {"proc": proc, "lines": [], "code": None, "t0": time.time(),
                         "pid": proc.pid, "cmd": tag}
    threading.Thread(target=mod._pump_output, args=(rid,), daemon=True).start()
    return rid, proc


def wait_done(api, rid, timeout=4.0):
    """盯 run_poll，直到它说"跑完了"；返回 (是否按时收工, 退出码, 等了多久)。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = api.run_poll(rid)
        if r.get("ok") and not r.get("running"):
            return True, r.get("code"), time.time() - t0
        time.sleep(0.1)
    return False, None, time.time() - t0


def main():
    mod = load_host()
    api = mod.Api()
    res = []

    def chk(name, ok, detail=""):
        res.append((name, bool(ok), detail))
        print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + detail) if detail else ""))

    tmp = Path(tempfile.mkdtemp(prefix="moss_runprobe_"))

    print("=" * 72)
    print("A：普通命令（cmd /c echo）—— 正常路径不能坏")
    print("=" * 72)
    bat_a = tmp / "a.bat"
    bat_a.write_text("@echo off\r\necho PROBE-A-OK\r\n", encoding="gbk")
    rid, proc = start_run(mod, ["cmd", "/c", str(bat_a)], "a")
    ok, code, dt = wait_done(api, rid, 4.0)
    out = api.run_poll(rid).get("out", "")
    chk("A 正常命令按时收工", ok, "等了 %.2fs 退出码=%s" % (dt, code))
    chk("A 退出码 0", code == 0, str(code))
    chk("A 输出收到了（PROBE-A-OK）", "PROBE-A-OK" in out, out.strip().replace("\n", " | ")[:60])
    chk("A 和 run_input 的说法一致（都说跑完了）",
        api.run_input(rid, "x").get("ok") is False, api.run_input(rid, "x").get("msg", ""))

    print()
    print("=" * 72)
    print("B：子进程退了、**孙进程还在**（`start \"\" /b ping -n 30`）—— 收工不许拖泥带水")
    print("   ★ 说清楚这条验的是什么：它钉的是**不变量** ——「子进程一退，run_poll 就得说跑完了，")
    print("     而且不能和 run_input 打架」。我试过 `start`（新控制台 / `/min` / `/b`）、")
    print("     `close_fds=False` 起 GUI 孙进程，**都没能真把管道叼住**（Python 3.7+ 在 Windows 上")
    print("     用 handle-list 起子进程，孙进程拿不到那根管道）—— 所以「管道被叼住」这条我没复现出来。")
    print("     那为什么还要改：**判据本来就该是「进程退没退」，而不是「管道读没读到 EOF」** ——")
    print("     管道是别人（孙进程）能不能关的事，进程退出才是这件事本身。这条场景保证改了之后")
    print("     正常路径（有孙进程赖着的那种）也照样按时收工、说法一致。")
    print("   ★ 另外：不能给孙进程写 `>nul`（那就不继承我们的管道了），也不能用 `timeout` ——")
    print("     它在 stdin 被重定向时会立刻报错退出（顺带说明：用户那个 bat 里的 `timeout /t 2`")
    print("     在 moss 下其实**没等**）。")
    print("=" * 72)
    bat_b = tmp / "b.bat"
    bat_b.write_text("@echo off\r\necho PROBE-B-OK\r\nstart \"\" /b ping -n 30 127.0.0.1\r\n",
                     encoding="gbk")
    rid, proc = start_run(mod, ["cmd", "/c", str(bat_b)], "b")
    ok, code, dt = wait_done(api, rid, 5.0)
    chk("B 子进程退了之后**很快**说跑完了（不等管道 EOF）", ok, "等了 %.2fs 退出码=%s" % (dt, code))
    chk("B 退出码 0", code == 0, str(code))
    chk("B 输出收到了（PROBE-B-OK）", "PROBE-B-OK" in api.run_poll(rid).get("out", ""), "")
    ri = api.run_input(rid, "x")
    chk("B ★和 run_input 说法一致（不能一个说在跑、一个说跑完了）",
        ri.get("ok") is False, ri.get("msg", ""))
    mod._kill_tree(proc.pid)                 # 收尾：把那个 30 秒的孙进程也带走

    print()
    print("=" * 72)
    print("C：真·长驻（ping 30 次 ≈ 30 秒）—— 不许误判成跑完，而且要停得掉")
    print("=" * 72)
    rid, proc = start_run(mod, ["cmd", "/c", "ping -n 30 127.0.0.1"], "c")
    time.sleep(1.2)
    r = api.run_poll(rid)
    chk("C 还在跑就老老实实说在跑", r.get("running") is True, "running=%s" % r.get("running"))
    chk("C run_input 也说还在等（两边一致）", api.run_input(rid, "x").get("ok") is True, "")
    st = api.run_stop(rid)
    chk("C run_stop 停得掉", st.get("ok") is True, st.get("msg", ""))
    ok, code, dt = wait_done(api, rid, 4.0)
    chk("C 停完就报跑完了", ok, "等了 %.2fs" % dt)

    print()
    print("=" * 72)
    bad = [x for x in res if not x[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的", len(res), len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
