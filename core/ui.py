import base64
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import config, engine, out, paths, pkg as pkg_mod, registry, runners as runners_mod
from . import shell as shell_mod

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

DOCS_MAX = 24000

UI_DIR = paths.SYSTEM_DIR / "ui"
UI_MAIN = UI_DIR / "main.py"
UI_PAGE = UI_DIR / "index.html"

_MIME = {".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp",
         ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
         ".bmp": "image/bmp", ".ico": "image/x-icon"}
_ICON_MAX_BYTES = 200 * 1024

def _icon(pkg, pkg_dir):
    p = pkg_mod.icon_path(pkg, pkg_dir)
    if not p:
        return "", ""
    try:
        raw = p.read_bytes()
    except OSError:
        return "", ""
    if not raw or len(raw) > _ICON_MAX_BYTES:
        return "", ""
    suffix = p.suffix.lower()
    if suffix == ".svg":
        return "", raw.decode("utf-8", "replace")
    mime = _MIME.get(suffix, "application/octet-stream")
    return "data:%s;base64,%s" % (mime, base64.b64encode(raw).decode("ascii")), ""

def _python(table):
    spec = (table or {}).get("python") or {}
    info = runners_mod.probe("python", spec, {"cwd": str(paths.HOME)}, kind="package")
    return info.get("interpreter"), info.get("why")

def _has_webview(exe):
    if not exe:
        return False
    root = Path(exe).resolve().parent
    cands = [
        root / "Lib" / "site-packages" / "webview" / "__init__.py",
        root / ".." / "Lib" / "site-packages" / "webview" / "__init__.py",
        root / "lib" / "site-packages" / "webview" / "__init__.py",
    ]
    return any(c.is_file() for c in cands)

def available(table=None):
    if not UI_MAIN.is_file():
        return False, "缺文件：%s" % UI_MAIN
    if not UI_PAGE.is_file():
        return False, "缺文件：%s" % UI_PAGE
    if table is None:
        table = runners_mod.load()
    exe, why = _python(table)
    if not exe:
        return False, "找不到能跑界面的 Python（%s）" % (why or "没配解释器")
    if not _has_webview(exe):
        return False, ("界面缺一个组件（pywebview），跑不起来。\n"
                       "用 moss 自带的 Python 跑界面就行；%s 里没有这个组件。" % exe)
    return True, exe

WEBVIEW2_URL = "https://developer.microsoft.com/microsoft-edge/webview2/"

def webview2_status(table=None):
    if table is None:
        table = runners_mod.load()
    exe, why = _python(table)
    if not exe:
        return None, "找不到能跑界面的 Python（%s）" % (why or "没配解释器")
    try:
        p = subprocess.run([exe, str(UI_MAIN), "--check-webview2"],
                           cwd=str(paths.HOME), capture_output=True, timeout=25,
                           creationflags=_NO_WINDOW)
    except Exception as e:
        return None, "问不出来：%s" % e
    out = (p.stdout or b"").decode("utf-8", "replace")
    for line in reversed(out.strip().splitlines()):
        try:
            data = json.loads(line)
        except Exception:
            continue
        if isinstance(data, dict) and "ok" in data:
            return bool(data.get("ok")), str(data.get("detail") or "")
    err = (p.stderr or b"").decode("utf-8", "replace").strip().splitlines()
    return None, ("界面进程没回话（退出码 %s）%s"
                  % (p.returncode, ("：" + err[-1]) if err else ""))

def host_cmd():
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv else ""
    exe = os.path.abspath(sys.executable or "")
    if argv0.lower().endswith(".py") and os.path.isfile(argv0):
        return [exe, argv0]
    if os.path.isfile(argv0):
        return [argv0]
    return [exe]

def _docs_of(pkg, pkg_dir):
    return pkg_mod.docs_of(pkg, pkg_dir, limit=DOCS_MAX)

def _ui_of(pkg, pkg_dir):
    raw = pkg.get("ui")
    if not isinstance(raw, dict):
        return None
    rel = str(raw.get("embed") or "").strip()
    if not rel:
        return None
    full = (Path(pkg_dir) / rel).resolve() if not os.path.isabs(rel) else Path(rel)
    if not full.is_file():
        print("[警告] %s 声明了界面 %r，但文件不存在（这个包不会有「界面」选项卡）"
              % (pkg_dir, rel), file=sys.stderr)
        return None
    title = raw.get("title")
    if isinstance(title, dict):
        title = title.get("zh-CN") or title.get("en") or ""
    return {"embed": str(full), "title": str(title or "")}

def build_payload():
    pkgs = []
    for rec in registry.scan_all():
        p = rec["pkg"]
        pkg_mod.display_name(p)
        ai = p.get("ai") or {}
        icon_uri, icon_svg = _icon(p, rec["dir"])
        item = {
            "id": p.get("id") or rec["id"],
            "name": p.get("name") or rec["id"],
            "desc": p.get("desc") or "",
            "kind": p.get("kind") or "",
            "version": str(p.get("version") or ""),
            "layer": rec["layer"],
            "dir": str(rec["dir"]),
            "aliases": [str(a) for a in (p.get("aliases") or [])],
            "tags": [str(t) for t in (p.get("tags") or [])],
            "params": p.get("params") or [],
            "drop": p.get("drop") or [],
            "ui": _ui_of(p, rec["dir"]),
            "docs": _docs_of(p, rec["dir"]),
            "ai_expose": bool(ai.get("expose")),
            "ai_risk": str(ai.get("risk") or ""),
            "examples": [str(e.get("args") or "") for e in (ai.get("examples") or [])
                         if isinstance(e, dict)],
            "icon": icon_uri,
            "icon_svg": icon_svg,
        }
        if rec.get("shadowed"):
            item["shadowed"] = rec["shadowed"]
        pkgs.append(item)
    return {
        "home": str(paths.HOME),
        "user_data": str(paths.USER_DIR),
        "host_cmd": host_cmd(),
        "launch_kind": shell_mod.launch_kind(),
        "icon_exts": list(pkg_mod.ICON_EXTS),
        "symbols": {
            "plugin": config.plugin_symbol(),
            "path": config.path_symbol(),
            "no_chdir": config.no_chdir_symbol(),
            "detach": config.detach_symbol(),
        },
        "packages": pkgs,
    }

def _alert(text):
    if not (shell_mod.gui_mode() or _own_console_launch()):
        out.print_cyan(text)
        return
    try:
        ctypes.windll.user32.MessageBoxW(None, text, "moss", 0x40)
    except Exception:
        pass

NO_CONSOLE_ENV = "MOSS_NO_CONSOLE"

def _launch_note(text):
    try:
        p = paths.STATE_DIR / "_ui_launch.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.is_file() and p.stat().st_size > 32 * 1024:
            keep = p.read_text(encoding="utf-8", errors="replace")[-16 * 1024:]
            p.write_text(keep, encoding="utf-8")
        with open(p, "a", encoding="utf-8") as f:
            f.write("%s pid=%s %s\n" % (time.strftime("%H:%M:%S"), os.getpid(), text))
    except Exception:
        pass

def _own_console_launch():
    try:
        return bool(shell_mod.console_is_only_ours())
    except Exception:
        return False

def launch(args=None):
    table = runners_mod.load()
    ok, why = available(table)
    if not ok:
        _alert("打不开界面：%s" % why)
        return 1

    exe, _ = _python(table)
    fd, tmp = tempfile.mkstemp(prefix="moss-ui-", suffix=".json")
    os.close(fd)
    tmp_path = Path(tmp)
    leave_now = _own_console_launch()
    keeps_payload = False
    try:
        tmp_path.write_text(json.dumps(build_payload(), ensure_ascii=False),
                            encoding="utf-8")
        env = os.environ.copy()
        env["MOSS_HOME"] = str(paths.HOME)
        env["MOSS_USER_DATA_DIR"] = str(paths.USER_DIR)
        env["MOSS_UI_DATA"] = str(tmp_path)
        env["MOSS_HOST_CMD"] = json.dumps(host_cmd(), ensure_ascii=False)
        env["PYTHONIOENCODING"] = "utf-8"

        argv = [exe, str(UI_MAIN)] + list(args or [])
        gui = shell_mod.gui_mode()
        flags = _NO_WINDOW if (gui or leave_now) else 0
        try:
            proc = subprocess.Popen(argv, cwd=str(paths.HOME), env=env,
                                    creationflags=flags)
        except OSError as e:
            _alert("界面启动失败：%s" % e)
            return 1

        _launch_note("launch args=%r gui_mode=%s own_console=%s flags=0x%X pid=%s"
                     % (list(args or []), gui, leave_now, flags, proc.pid))
        if leave_now:
            keeps_payload = True
            return 0

        try:
            while proc.poll() is None:
                time.sleep(0.1)
        except KeyboardInterrupt:
            engine.kill_process_tree(proc.pid)
            return 130
        return proc.returncode or 0
    finally:
        if not keeps_payload:
            try:
                tmp_path.unlink()
            except OSError:
                pass
