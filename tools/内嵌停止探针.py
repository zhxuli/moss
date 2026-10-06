# -*- coding: utf-8 -*-
"""内嵌停止探针（`V-297`）：界面点「停止」时，**只该有一个提示**。

用户报的现象：「每次终止一个进程，它老是有两个提示」——
一个是「已停掉这个包的内嵌进程」（`embed_stop` 回的那句，`embed.js` 弹），
另一个是「这个包的内嵌进程结束了（退出码 1）」（`_pump_embed` 收尾发的
`window.__mossEmbedGone`）。强杀必然是非 0，第二个是**重复**的。

修法是宿主动手：`embed_stop` 先往 `EMBED_STOPPED` 记一笔，`_pump_embed` 收尾看到它
就**不发** `__mossEmbedGone`。这个探针就钉这两条：

  ① 主动停止  ⇒ **不发** `__mossEmbedGone`（否则界面又会多弹一句）；
  ② 自己退出  ⇒ 仍然**要发** `__mossEmbedGone`（别把"进程没了"这条通知整个关掉）。

★ 断言必须能抓住回归：把 `main.py` 里 `was_stopped` 那两处逻辑注掉再跑，
   ① 必须变红（绿不了才算数 —— 这条规矩见 `AGENTS.md`）。

★ 用法（进程会自己换成自带运行时再跑一遍）：
    python tools\\内嵌停止探针.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
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
    if os.environ.get("_MOSS_STOP_PROBE") == "1":
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
    env["_MOSS_STOP_PROBE"] = "1"
    return subprocess.call([str(py), str(Path(__file__).resolve())], env=env)


def load_main():
    spec = importlib.util.spec_from_file_location("moss_ui_main", str(MAIN))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    # ---- 摆好"真启动"那几样环境（照 tools/界面自检.py 的路子）----
    tmp = Path(tempfile.mkdtemp(prefix="moss_stopprobe_"))
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

    main_mod = load_main()

    calls = []
    main_mod._js = lambda win, code: calls.append(code)      # 记下所有"往页面塞 JS"

    def start_embed(pid, code_expr):
        proc = subprocess.Popen(
            [sys.executable, "-c", code_expr],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        main_mod.EMBED[pid] = {"proc": proc, "lines": []}
        threading.Thread(target=main_mod._pump_embed, args=(pid, proc),
                         daemon=True).start()
        return proc

    res = []

    def chk(name, ok, detail=""):
        res.append((name, bool(ok), detail))
        print("  %s %s%s" % ("OK  " if ok else "FAIL", name,
                             ("   ← " + detail) if detail else ""))

    print("=" * 72)
    print("① 主动点「停止」：不该再发 __mossEmbedGone（否则第二个提示就是从这儿来的）")
    print("=" * 72)
    calls.clear()
    start_embed("t1", "import time; time.sleep(60)")
    time.sleep(0.4)
    rr = main_mod.Api().embed_stop("t1")
    time.sleep(1.4)
    gone1 = [c for c in calls if "__mossEmbedGone" in c]
    chk("embed_stop 回 ok", (rr or {}).get("ok") is True, str(rr))
    chk("★ 主动停止：**不发** __mossEmbedGone", not gone1,
        "却发了：" + (gone1[0][:90] if gone1 else ""))
    chk("停掉之后 EMBED_STOPPED 也清干净了（不留着）",
        len(main_mod.EMBED_STOPPED) == 0, str(len(main_mod.EMBED_STOPPED)))

    print()
    print("=" * 72)
    print("② 进程**自己**退出：仍然要发 __mossEmbedGone（通知没被整个关掉）")
    print("=" * 72)
    calls.clear()
    start_embed("t2", "import sys; sys.exit(3)")
    time.sleep(1.4)
    gone2 = [c for c in calls if "__mossEmbedGone" in c]
    chk("★ 自己退出：**要发** __mossEmbedGone", bool(gone2),
        "一条都没发（通知被误关了）")
    chk("带上了正确的退出码 3（不是 1）",
        any('"t2", 3)' in c for c in gone2), str(gone2[:1]))
    chk("t1（被停掉的）那条通知没有混进来",
        not any('"t1"' in c for c in calls), str(calls[:2]))

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
