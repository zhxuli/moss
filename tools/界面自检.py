# -*- coding: utf-8 -*-
"""界面自检：**按真启动方式**把 `system/ui/main.py` 装一遍，再点几个接口。

为什么要有它（`V-87` 的血）：真启动是

    <HOME>/system/runtimes/python/3.12/python.exe  <HOME>/system/ui/main.py

而那份 Python 是**便携/嵌入版** —— 它的 `sys.path` 来自 `python312._pth`，
**不会**把"脚本所在目录"放进去。于是 `main.py` 里 `import backup`（同目录的兄弟模块）
在真机上直接 `No module named 'backup'`，而我的探针全都没发现：探针是用 `runpy` 跑、
而且**自己插过** `sys.path.insert(0, system/ui)`（venv 那份 Python 也会自动带上脚本目录）。
⇒ 「我的验证环境和真启动不是一个世界」（`V-76` 第②条）又栽了一次。

这个工具就专门补那个洞：**不动 `sys.path`**，用"按文件路径装载"的方式装 main.py，
看它自己有没有把 `HERE` 插进来、兄弟模块 import 通不通、几个只读接口能不能调。
不开窗口、不改任何数据（只调只读接口）。

用法：
    .\\venv\\Scripts\\python.exe tools\\界面自检.py
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "system" / "ui"
MAIN = UI / "main.py"
EXE = ROOT / "moss.exe"

HELPER = r'''# -*- coding: utf-8 -*-
"""（临时）按真启动那份 sys.path 装载 main.py 并点几个接口。

★ `main.py` 的路径由环境变量传进来：这个临时脚本写在 %TEMP% 里，不能靠 __file__
   去推（用「上级目录 + ui/main.py」那种推法在 %TEMP% 下根本不存在 —— 第一版就这么错的）。
★ 这段文字里**别出现反斜杠**：它会被原样写成普通字符串里的转义序列（踩过：反斜杠加 u
   直接 SyntaxError —— 连"提醒别用反斜杠"那句话本身都栽在这上面）。
"""
import importlib.util
import json
import os
import sys

main_py = os.environ["MOSS_SELFTEST_MAIN"]
path0 = sys.path[0] if sys.path else None
spec = importlib.util.spec_from_file_location("moss_ui_main", main_py)
main = importlib.util.module_from_spec(spec)
spec.loader.exec_module(main)
out = {"path0": path0, "path_after": sys.path[:2], "here": str(main.HERE)}
try:
    import backup
    out["sibling_import"] = "OK SPEC=%s" % getattr(backup, "SPEC", "?")
except Exception as e:
    out["sibling_import"] = "FAIL %r" % (e,)
api = main.Api()
# ★ 只挑**只读**接口点一点（`V-138` 加了 `ai_config`：它要壳到 exe 跑一条
#   `--ai-config`，正好验证"界面进程不许 import core、只能叫宿主"这条路上
#   新加的几个 AI 接口通不通）。
for name in ("backup_list", "fs_roots", "ai_config", "ai_presets"):
    try:
        r = getattr(api, name)()
        out[name] = ("ok=%s" % r.get("ok")) if isinstance(r, dict) else str(type(r))
    except Exception as e:
        out[name] = "FAIL %r" % (e,)
# ---- `V-277`：自包含页面走**虚拟地址 + 内存**，老路径该被挡，且不落盘 ----
srv = main._EMBED_SRV
port, token = srv.get("port"), srv.get("token") or ""
html = main._LIVE.get("html") or ""
out["live_kb"] = round(len(html.encode("utf-8")) / 1024.0, 1)
out["live_has_icons"] = "window.__MOSS_ICONS" in html
out["live_has_note"] = "在内存里" in html


def _req(method, path):
    import http.client
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        c.request(method, path)
        r = c.getresponse()
        return r.status, dict(r.getheaders()), r.read()
    finally:
        c.close()


try:
    st, hd, body = _req("GET", "/%s/%s" % (token, main.LIVE_NAME))
    out["live_get"] = st
    out["live_ctype"] = hd.get("Content-Type", "")
    out["live_same"] = (body == html.encode("utf-8"))
except Exception as e:
    out["live_get"] = "FAIL %r" % (e,)
try:
    st2, hd2, body2 = _req("HEAD", "/%s/%s" % (token, main.LIVE_NAME))
    out["live_head"] = st2
    out["live_head_len"] = int(hd2.get("Content-Length") or -1) == len(html.encode("utf-8"))
except Exception as e:
    out["live_head"] = "FAIL %r" % (e,)
try:
    out["multifile"] = _req("GET", "/%s/system/ui/index.html" % token)[0]
except Exception as e:
    out["multifile"] = "FAIL %r" % (e,)
print(json.dumps(out, ensure_ascii=False))
'''


def runtime_python():
    """自带运行时里的那个 python（真启动用的就是它）。"""
    base = ROOT / "system" / "runtimes" / "python"
    if base.is_dir():
        for d in sorted(base.iterdir(), reverse=True):
            for name in ("python.exe", "python"):
                p = d / name
                if p.is_file():
                    return p
    return None


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    py = runtime_python()
    if not py:
        print("[错误] 找不到自带运行时（system/runtimes/python/*/python.exe）")
        return 1
    if not (UI / "backup.py").is_file():
        print("[提示] system/ui/backup.py 不在 —— 那 `import backup` 这条就跳过看结果")
    print("自带运行时 : %s" % py)
    print("main.py    : %s" % MAIN)

    # 宿主给界面的那几样环境（真启动时是 core/ui.py 摆的）
    payload = Path(tempfile.gettempdir()) / "moss_ui_selftest_payload.json"
    r = subprocess.run([str(EXE), "--ui-payload"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", cwd=str(ROOT))
    line = None
    for ln in reversed((r.stdout or "").strip().splitlines()):
        if ln.strip().startswith("{"):
            line = ln
            break
    if line:
        payload.write_text(line, encoding="utf-8")

    tmp_helper = Path(tempfile.gettempdir()) / "moss_ui_selftest_run.py"
    tmp_helper.write_text(HELPER, encoding="utf-8")
    env = dict(os.environ)
    env.update({"MOSS_HOME": str(ROOT), "MOSS_USER_DATA_DIR": str(ROOT / "user_data"),
                "MOSS_UI_DATA": str(payload), "MOSS_HOST_CMD": json.dumps([str(EXE)]),
                "MOSS_SELFTEST_MAIN": str(MAIN), "PYTHONIOENCODING": "utf-8"})
    try:
        rr = subprocess.run([str(py), str(tmp_helper)], capture_output=True, text=True,
                            encoding="utf-8", errors="replace", cwd=str(ROOT),
                            env=env, timeout=120)
    finally:
        tmp_helper.unlink(missing_ok=True)
        payload.unlink(missing_ok=True)

    tail = [ln for ln in (rr.stdout or "").strip().splitlines() if ln.strip().startswith("{")]
    info = {}
    if tail:
        try:
            info = json.loads(tail[-1])
        except Exception:                                              # noqa: BLE001
            pass
    print("=" * 64)
    if not info:
        print("[失败] 自检脚本没回结果。stdout/stderr 尾巴：")
        print((rr.stdout or "")[-800:])
        print((rr.stderr or "")[-800:])
        return 1
    print("sys.path[0]（真启动那份）: %s" % info.get("path0"))
    print("装载 main 之后 sys.path[:2] : %s" % (info.get("path_after"),))
    print("main.HERE                   : %s" % info.get("here"))
    print("兄弟模块 import             : %s" % info.get("sibling_import"))
    print("backup_list()               : %s" % info.get("backup_list"))
    print("fs_roots()                  : %s" % info.get("fs_roots"))
    print("ai_config()                 : %s" % info.get("ai_config"))
    print("ai_presets()                : %s" % info.get("ai_presets"))
    print("-" * 64)
    print("★ `V-277` 自包含页面（虚拟地址 + 内存，不落盘）：")
    print("  内存里那份                   : %s KB · 带图标表=%s · 带说明=%s"
          % (info.get("live_kb"), info.get("live_has_icons"), info.get("live_has_note")))
    print("  GET  虚拟地址 __ui_live.html : %s（%s）字节一致=%s"
          % (info.get("live_get"), info.get("live_ctype"), info.get("live_same")))
    print("  HEAD 虚拟地址                : %s · Content-Length 对得上=%s"
          % (info.get("live_head"), info.get("live_head_len")))
    print("  多文件那条路 index.html      : %s" % info.get("multifile"))
    ok = (str(info.get("sibling_import", "")).startswith("OK")
          and info.get("backup_list") == "ok=True"
          # ★ `V-138` / `V-139`：AI 那几个接口要能**壳到 exe**（界面进程不许 import core）——
          #   这两个回了 ok=True 就说明 `--ai-config` / `--ai-presets` 这条路是通的。
          and info.get("ai_config") == "ok=True"
          and info.get("ai_presets") == "ok=True"
          and str(UI) in [str(p) for p in (info.get("path_after") or [])]
          and info.get("live_has_icons") is True and info.get("live_has_note") is True
          and info.get("live_get") == 200 and "text/html" in str(info.get("live_ctype"))
          and info.get("live_same") is True
          and info.get("live_head") == 200 and info.get("live_head_len") is True
          and info.get("multifile") == 200)
    print("=" * 64)
    print("✅ 真启动环境下界面后端可用" if ok else "✗ 有问题：看上面几行")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
