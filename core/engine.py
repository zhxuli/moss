import json
import os
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

from . import appearance, config, events, out, paths, runners as runners_mod, shell as shell_mod

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)

def kill_process_tree(pid):
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=_NO_WINDOW)
    except Exception:
        pass

def _is_bundled_runtime(interp):
    if not interp:
        return False
    try:
        p = Path(interp).resolve()
    except Exception:
        return False
    for base in (paths.SYSTEM_RUNTIMES, paths.USER_RUNTIMES):
        try:
            p.relative_to(base.resolve())
            return True
        except ValueError:
            continue
    return False

def build_argv(inv, spec):
    ctx = {
        "interpreter": inv.get("interpreter") or "",
        "entry": str(inv.get("target") or ""),
        "cwd": inv.get("cwd") or "",
        "home": str(paths.HOME),
    }

    rt = spec.get("runTarget") or {}
    if rt:
        markers = rt.get("packageIf") or []
        base = inv.get("cwd") or os.getcwd()
        if markers and runners_mod.has_marker_near(base, markers):
            ctx["runTarget"] = rt.get("package") or "."
        else:
            raw = str(rt.get("default") or "{entry}")
            try:
                ctx["runTarget"] = raw.format(**ctx)
            except Exception:
                ctx["runTarget"] = ctx["entry"]
    else:
        ctx["runTarget"] = ctx["entry"]

    shim = spec.get("shim") or {}
    use_shim = bool(shim) and _is_bundled_runtime(inv.get("interpreter"))
    templates = (shim.get("launch") if use_shim else None) or (spec.get("launch") or [])

    argv = []
    for tpl in templates:
        try:
            argv.append(tpl.format(**ctx))
        except Exception:
            argv.append(tpl)

    argv.extend(str(a) for a in (inv.get("args") or []))
    return argv

def build_env(inv):
    env = os.environ.copy()
    try:
        _pname, _prof = config.ai_active_profile()
        if _prof:
            env["MOSS_AI_PROFILE"] = str(_pname)
            for _k, _envk in (("base_url", "MOSS_AI_BASE_URL"), ("api_key", "MOSS_AI_API_KEY")):
                if _prof.get(_k) not in (None, ""):
                    env[_envk] = str(_prof.get(_k))
            _models = config.ai_models(_prof)
            if _models:
                env["MOSS_AI_MODEL"] = _models[0]
                env["MOSS_AI_MODELS"] = ",".join(_models)
    except Exception:
        pass
    env["MOSS_HOME"] = str(paths.HOME)
    env["MOSS_USER_DATA_DIR"] = str(paths.USER_DIR)

    if inv.get("id"):
        data = paths.pkg_state_dir(inv["id"])
    else:
        data = paths.path_state_dir(inv.get("cwd") or "")
    env["MOSS_PLUGIN_DATA_DIR"] = str(data)
    env["MOSS_PLUGIN_CACHE_DIR"] = str(data / "cache")
    env["MOSS_PLUGIN_LOG_DIR"] = str(data / "logs")
    env["MOSS_PLUGIN_TMP_DIR"] = str(data / "tmp")

    if inv.get("id"):
        env["MOSS_PKG_ID"] = str(inv["id"])
        env["MOSS_PKG_VERSION"] = str(inv.get("version") or "")
    env["MOSS_PKG_PARAMS"] = json.dumps(inv.get("params") or {}, ensure_ascii=False)
    env["MOSS_ARGS"] = " ".join(inv.get("args") or [])
    env["MOSS_VIA"] = inv.get("via") or "cli"
    if inv.get("icon"):
        env["MOSS_PKG_ICON"] = str(inv["icon"])
    if inv.get("venv"):
        env["MOSS_VENV"] = str(inv["venv"])
    env["MOSS_RESULT_FILE"] = inv["_result_file"]

    env["MOSS_APPEARANCE"] = appearance.as_env()

    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env

def _hide_window(inv):
    ext = ""
    if inv.get("target"):
        ext = Path(inv["target"]).suffix.lower()
    if inv.get("kind") == "pkg" and inv.get("pkg_kind") == "app":
        return ext in (".pyw", ".exe")
    return ext == ".pyw"

def _run_builtin(inv, spec):
    what = spec.get("builtin")
    target = str(inv.get("target") or "")
    if what == "openHtml":
        if not target:
            return 1, "没有可打开的页面"
        webbrowser.open(Path(target).resolve().as_uri())
        return 0, "已用默认浏览器打开：%s" % target
    if what == "openUrl":
        url = target or inv.get("inline") or ""
        if url and not url.startswith(("http://", "https://", "file://")):
            url = "https://" + url
        webbrowser.open(url)
        return 0, "已打开：%s" % url
    if what == "openPath":
        p = os.path.expandvars(os.path.expanduser(target))
        if not os.path.exists(p):
            return 1, "路径不存在：%s" % p
        os.startfile(p)
        return 0, "已打开：%s" % p
    return 1, "不认识的 builtin：%s" % what

def run(inv, runners_table, detach=False):
    spec = runners_table.get(inv.get("runner")) or {}
    inv = dict(inv)
    cfg = config.output_cfg()

    out.conditional_clear_screen()

    fd, result_file = tempfile.mkstemp(prefix="moss_result_", suffix=".json")
    os.close(fd)
    inv["_result_file"] = result_file

    started = time.time()
    events.BUS.emit("before:run", {"invocation": inv})

    exit_code = 0
    data = None
    proc = None
    result_emitted = False

    def _emit_after(code):
        nonlocal result_emitted
        if result_emitted:
            return
        result_emitted = True
        nonlocal data
        try:
            if os.path.getsize(result_file) > 0:
                with open(result_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
        except Exception:
            data = None
        try:
            os.remove(result_file)
        except Exception:
            pass
        events.BUS.emit("after:run", {
            "invocation": inv,
            "result": {"exit": code, "ms": int((time.time() - started) * 1000), "data": data},
        })

    try:
        if spec.get("builtin"):
            exit_code, msg = _run_builtin(inv, spec)
            out.print_cyan(("[完成] " if exit_code == 0 else "[错误] ") + msg)

        else:
            argv = build_argv(inv, spec)
            if not argv:
                out.print_cyan("[错误] runner '%s' 没有可用的 launch 模板。" % inv.get("runner"))
                exit_code = 1
            else:
                cwd = inv.get("cwd") or os.getcwd()
                cmd_str = ' '.join('"%s"' % c for c in argv)
                symbol = cfg.get("symbol", "")
                if cfg.get("start_banner"):
                    out.print_cyan(cfg["start_banner"])
                if cfg.get("start_time"):
                    out.print_cyan("%s  %s  %s" % (
                        symbol, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)), symbol))
                if cfg.get("command"):
                    out.print_cyan("[执行] %s" % cmd_str)
                if cfg.get("directory"):
                    out.print_cyan("[目录] %s" % cwd)
                sys.stdout.flush()

                cflags = 0
                if _hide_window(inv):
                    cflags |= _NO_WINDOW
                if shell_mod.gui_mode():
                    cflags |= _NO_WINDOW
                if detach:
                    cflags |= _DETACHED | _NEW_GROUP

                kwargs = {"cwd": cwd, "creationflags": cflags, "env": build_env(inv)}
                if detach:
                    kwargs["stdin"] = subprocess.DEVNULL
                    kwargs["stdout"] = subprocess.DEVNULL
                    kwargs["stderr"] = subprocess.DEVNULL

                try:
                    proc = subprocess.Popen(argv, **kwargs)

                    if cfg.get("pid"):
                        out.print_cyan("[PID] %s" % proc.pid)
                    print(out.RESET, end='')

                    if detach:
                        out.print_cyan("[后台脱离] 程序已剥离并转入独立后台运行，当前控制台已释放！")
                        _emit_after(None)
                        return 0

                    force_kill = config.force_kill()
                    gentle_done = False
                    while True:
                        try:
                            while proc.poll() is None:
                                time.sleep(0.1)
                            break
                        except KeyboardInterrupt:
                            if (not force_kill) and not gentle_done:
                                out.print_cyan("\n[中断] 温和模式: 尝试优雅停止...")
                                try:
                                    proc.terminate()
                                except Exception:
                                    pass
                                time.sleep(0.6)
                                if proc.poll() is None:
                                    gentle_done = True
                                    out.print_cyan("[提示] 进程未退出; 再按一次 Ctrl+C 将强制结束。")
                                else:
                                    out.print_cyan("[完成] 进程已优雅停止。")
                                    break
                            else:
                                out.print_cyan("\n[中断] 正在强力终止进程树...")
                                kill_process_tree(proc.pid)
                                out.print_cyan("[完成] 进程已终止。")
                                exit_code = 130
                                break
                    if exit_code == 0:
                        exit_code = proc.returncode or 0
                except FileNotFoundError as e:
                    out.print_cyan("[执行错误] 找不到可执行文件：%s" % e)
                    exit_code = 1
                except Exception as e:
                    out.print_cyan("[执行错误] %s" % e)
                    exit_code = 1

    except KeyboardInterrupt:
        if proc:
            out.print_cyan("\n[中断] 正在强力终止进程树...")
            kill_process_tree(proc.pid)
            out.print_cyan("[完成] 进程已终止。")
        else:
            out.print_cyan("\n[中断] 操作已取消。")
        exit_code = 130

    finally:
        _emit_after(exit_code)

    if data is not None:
        print("[结果] %s" % json.dumps(data, ensure_ascii=False))

    ended = time.time()
    symbol = cfg.get("symbol", "")
    if cfg.get("duration"):
        out.print_cyan("[运行总长] %.2f 秒" % (ended - started))
    if cfg.get("end_time"):
        out.print_cyan("%s  %s  %s" % (
            symbol, time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ended)), symbol))
    if cfg.get("end_banner"):
        out.print_cyan(cfg["end_banner"])

    return exit_code
