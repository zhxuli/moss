# -*- coding: utf-8 -*-
"""「命令行」那根输入行敲的命令探针（`V-371`）。

用户报的：「点 md5计算，再点 ip查询的命令行 …… 它也没法在这里直接操作这个命令行，
它提示 这个包现在没在跑 -- 先在详情里点运行」。修法：那一行交给宿主的 `cmd_start` ——
**另起一个一次性进程**在这个对象自己的目录里跑（不碰那条只有一条的常驻 shell，免得
把命令塞进"正在里面跑的那个包"的 stdin）。

这个探针钉的是**宿主那一侧**（预览里那个是假的，验不了进程）：

  ① `echo` 一行 ⇒ 真跑起来、输出收得到、退出码 0；
  ② `cd ..` ⇒ **不起进程**，只回新目录（每一份「命令行」自己记 cwd）；
  ③ `cd 不存在的目录` ⇒ 如实回 ok=False（不许假装成功）；
  ④ 以「跑包符号」开头的 ⇒ 交给 **moss 自己**（cmd.exe 里没有 PowerShell 那个包装函数）；
  ⑤ 长命令能**停掉**（`run_stop` 走的是同一套管子），停完 `run_poll` 说不在跑了。

★ 用法（进程会自己换成自带运行时再跑一遍）：
    python tools\\命令行探针.py
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
UI = ROOT / "system" / "ui"
MAIN = UI / "main.py"
EXE = ROOT / "moss.exe"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                     # noqa: BLE001
        pass


def runtime_python():
    """自带运行时里的那个 python（main.py 的依赖都在它里面）。"""
    base = ROOT / "system" / "runtimes" / "python"
    if base.is_dir():
        for d in sorted(base.iterdir(), reverse=True):
            for name in ("python.exe", "python"):
                p = d / name
                if p.is_file():
                    return p
    return None


def _reexec_under_runtime():
    """没跑在自带运行时里就换过去（系统那份可能没有 pywebview）。返回退出码或 None。"""
    if os.environ.get("_MOSS_CMDLINE_PROBE") == "1":
        return None
    py = runtime_python()
    if not py:
        return None
    try:
        if Path(sys.executable).resolve() == py.resolve():
            return None
    except OSError:
        return None
    env = dict(os.environ)
    env["_MOSS_CMDLINE_PROBE"] = "1"
    return subprocess.call([str(py), str(Path(__file__).resolve())], env=env)


def load_main():
    spec = importlib.util.spec_from_file_location("moss_ui_main", str(MAIN))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def wait_done(api, rid, seconds=20):
    """轮询到这一跑结束，攒出所有输出（返回 (code, out)）。"""
    out = ""
    t0 = time.time()
    while time.time() - t0 < seconds:
        r = api.run_poll(rid)
        if not r.get("ok"):
            return None, out
        out += r.get("out") or ""
        if not r.get("running"):
            return r.get("code"), out
        time.sleep(0.12)
    return "超时", out


def main():
    tmp = Path(tempfile.mkdtemp(prefix="moss_cmdprobe_"))
    os.environ["MOSS_HOME"] = str(ROOT)
    os.environ["MOSS_USER_DATA_DIR"] = str(tmp)
    r = subprocess.run([str(EXE), "--ui-payload"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    line = None
    for ln in reversed((r.stdout or "").strip().splitlines()):
        if ln.strip().startswith("{"):
            line = ln
            break
    payload = tmp / "payload.json"
    payload.write_text(line or "{}", encoding="utf-8")
    os.environ["MOSS_UI_DATA"] = str(payload)
    os.environ["MOSS_HOST_CMD"] = json.dumps([str(EXE)])

    m = load_main()
    api = m.Api()

    res = []

    def chk(name, ok, detail=""):
        res.append((name, bool(ok), detail))
        print("  %s %s%s" % ("OK  " if ok else "FAIL", name,
                             ("   ← " + detail) if detail else ""))

    work = str(tmp)          # 拿一个**真实存在**的目录当工作目录（不碰你的 user_data）

    print("=" * 72)
    print("① `echo` 一行：真跑起来、输出收得到、退出码 0")
    print("=" * 72)
    r1 = api.cmd_start(work, "echo hello-from-cmdline")
    chk("cmd_start 回了 ok + run_id", bool(r1.get("ok")) and bool(r1.get("run_id")), str(r1)[:110])
    code1, out1 = wait_done(api, r1.get("run_id"))
    chk("跑完了、退出码 0", code1 == 0, "code=%s" % (code1,))
    chk("输出里有那行字", "hello-from-cmdline" in out1, repr(out1[-80:]))

    print()
    print("=" * 72)
    print("② `cd ..`：**不起进程**，只回新目录（这一份自己的 cwd）")
    print("=" * 72)
    r2 = api.cmd_start(work, "cd ..")
    chk("回了 cd（不是 run_id）", r2.get("ok") is True and r2.get("cd") and not r2.get("run_id"),
        str(r2)[:110])
    chk("算出来的就是上一级", Path(str(r2.get("cd"))).resolve() == Path(work).resolve().parent,
        "%s vs %s" % (r2.get("cd"), Path(work).resolve().parent))
    r2b = api.cmd_start(str(r2.get("cd")), "cd")
    chk("`cd`（不带参数）= 原地", r2b.get("cd") and Path(str(r2b.get("cd"))).resolve() ==
        Path(str(r2.get("cd"))).resolve(), str(r2b)[:90])

    print()
    print("=" * 72)
    print("③ `cd 不存在的目录`：如实回失败（不许假装成功）")
    print("=" * 72)
    r3 = api.cmd_start(work, "cd 这个目录肯定不存在-zzz")
    chk("ok=False 且带了原因", r3.get("ok") is False and "没有这个目录" in str(r3.get("msg")),
        str(r3)[:110])

    print()
    print("=" * 72)
    print("④ 以「跑包符号」开头 ⇒ 交给 moss 自己（cmd 里没有你的包装函数）")
    print("=" * 72)
    r4 = api.cmd_start(work, ":zzz-根本没有这个包")
    chk("也回了 ok（真的去跑 moss 了）", bool(r4.get("ok")), str(r4)[:100])
    code4, out4 = wait_done(api, r4.get("run_id"))
    chk("输出是 **moss 自己**说的（不是 cmd 的「不是内部或外部命令」）",
        ("zzz" in out4) and ("不是内部或外部命令" not in out4) and ("系统找不到" not in out4),
        repr(out4[-140:]))

    print()
    print("=" * 72)
    print("⑤ 长命令能停掉（`run_stop` 走同一套管子）")
    print("=" * 72)
    r5 = api.cmd_start(work, "ping -n 30 127.0.0.1")
    rid5 = r5.get("run_id")
    time.sleep(0.6)
    mid = api.run_poll(rid5)
    chk("开始跑起来了", bool(mid.get("running")), str(mid)[:90])
    st = api.run_stop(rid5)
    chk("run_stop 回了 ok", bool(st.get("ok")), str(st)[:100])
    time.sleep(0.8)
    end = api.run_poll(rid5)
    chk("停完就不在跑了", end.get("ok") and not end.get("running"), str(end)[:100])

    print()
    print("=" * 72)
    print("⑥ 中文 / cmd 内建命令不乱码（控制台代码页随环境变 ⇒ 读线程自己判）")
    print("=" * 72)
    r6 = api.cmd_start(work, "echo 中文不乱码-abc")
    code6, out6 = wait_done(api, r6.get("run_id"))
    chk("echo 中文：原样回来了", "中文不乱码-abc" in out6, repr(out6[-80:]))
    r7 = api.cmd_start(work, "dir")
    code7, out7 = wait_done(api, r7.get("run_id"))
    chk("dir 跑得出东西", bool(out7.strip()) and code7 == 0, "code=%s 长度=%d" % (code7, len(out7)))
    chk("dir 的输出里**没有乱码替换符**（U+FFFD）", "\ufffd" not in out7, repr(out7[:90]))

    shutil.rmtree(tmp, ignore_errors=True)

    bad = [x for x in res if not x[1]]
    print()
    print("=" * 72)
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的",
                                     len(res), len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    rc = _reexec_under_runtime()
    if rc is not None:
        sys.exit(rc)
    sys.exit(main())
