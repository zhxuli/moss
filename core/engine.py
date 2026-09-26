# -*- coding: utf-8 -*-
"""执行引擎 `ExecEngine`（`E-01`）。

凡是"启动一个东西"要用到的事情，**只允许在这一个地方实现**：
    拼命令 / 选解释器 / 注入环境 / 起进程 / 处理 Ctrl-C / 收结构化结果 / 发事件

pa 的入口和以后 exec 工作台、AI 调用，全都走这里。

★ 照抄 pa.py 的部分（`E-20` 照抄原则）：
  · `kill_process_tree()`             —— pa.py:210
  · `execute_command_robust()` 的全套 —— pa.py:219-313
      清屏 / 起止横幅 / [执行] / [目录] / [PID] / 后台脱离 / 温和 Ctrl-C /
      [运行总长] / 结束时间
  · 环境的注入方式                    —— pa.py:234-238（`PA_*` → `MOSS_*`）

★ 统一中间表示 `Invocation`（`E-12`）：所有入口都归一到它再进引擎。
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path

from . import appearance, config, events, out, paths, runners as runners_mod

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)


def kill_process_tree(pid):
    """照抄 pa.py:210-216。"""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=_NO_WINDOW)
    except Exception:
        pass


# ---------------------------------------------------------------- 构造
def _is_bundled_runtime(interp):
    """这个解释器是不是我们自带的运行时？

    自带的是 Python **嵌入式发行版**（带 `._pth`），处于隔离模式：
    不会把脚本目录加进 sys.path，PYTHONPATH 也被忽略。
    所以只有它需要走 `system/bootstrap.py` 引导。
    venv / 系统 Python 不需要，照旧直接跑（照抄 pa.py 项目模式的行为）。
    """
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
    """按 runner 的 launch 模板拼命令。

    ★ `{runTarget}`：有些语言"跑单个文件"和"跑整个包"是两条路。
      最典型的是 Go —— 实测：
          `go run main.go`  只编译那一个文件，多文件项目直接
                            `undefined: xxx`；没有 go.mod 时它才管用
          `go run .`        跑整个包（多文件正确），但**必须有 go.mod**
      所以 runner 用 `runTarget` 字段声明这个判断，引擎只负责执行它 ——
      保持"执行方式变成数据"（F-19），不把某种语言的知识写死进引擎。

    ★ `shim`：自带运行时是嵌入式发行版（`._pth` = 隔离模式），
      不会把脚本目录加进 sys.path —— 同目录 import 会失败，PYTHONPATH 也没用。
      所以 runner 可以声明：用自带运行时跑脚本时改走 `system/bootstrap.py`。
    """
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

    # 透传用户参数（照抄 pa.py execute_target 的 `+ args`）
    argv.extend(str(a) for a in (inv.get("args") or []))
    return argv


def build_env(inv):
    """给子进程的环境。照抄 pa.py:234-238 的注入方式，换成 MOSS_* 前缀。"""
    env = os.environ.copy()
    env["MOSS_HOME"] = str(paths.HOME)
    env["MOSS_USER_DATA_DIR"] = str(paths.USER_DIR)

    # 这个包的数据目录。★ 包调用的目录名**就是包 id**（`state/<id>/`，一眼看得出
    # 归属）；路径调用没有 id，退到 `state/_path/<短哈希>/`。
    if inv.get("id"):
        data = paths.pkg_state_dir(inv["id"])
    else:
        # 路径调用：key 直接用 cwd（以前拼过 `path:` 前缀避免和包 id 撞，
        # 现在两者分别在 `state/<id>` 和 `state/_path/` 下，前缀没必要了 ——
        # 留着还会漏进目录名里变成 `path-D--python-...`）
        data = paths.path_state_dir(inv.get("cwd") or "")
    env["MOSS_PLUGIN_DATA_DIR"] = str(data)
    # 约定好的子目录（设计与决策 §6.1）。★ 宿主**不预建**它们：包用哪个自己建，
    # 免得给每个跑过一次的包都留一堆空目录（paths.py 的"懒创建"原则）。
    env["MOSS_PLUGIN_CACHE_DIR"] = str(data / "cache")
    env["MOSS_PLUGIN_LOG_DIR"] = str(data / "logs")
    env["MOSS_PLUGIN_TMP_DIR"] = str(data / "tmp")

    if inv.get("id"):
        env["MOSS_PKG_ID"] = str(inv["id"])
        env["MOSS_PKG_VERSION"] = str(inv.get("version") or "")
    env["MOSS_PKG_PARAMS"] = json.dumps(inv.get("params") or {}, ensure_ascii=False)
    env["MOSS_ARGS"] = " ".join(inv.get("args") or [])
    env["MOSS_VIA"] = inv.get("via") or "cli"
    if inv.get("venv"):
        env["MOSS_VENV"] = str(inv["venv"])
    env["MOSS_RESULT_FILE"] = inv["_result_file"]

    # 系统外观（深浅模式 + 强调色）。包跑在自带运行时里，是独立进程，
    # **不能 import 宿主的 core**，所以这类"每台机器不同的动态值"走环境变量 ——
    # 和 MOSS_HOME / MOSS_PKG_PARAMS 同一个套路。WebView 界面用它注入 CSS 变量。
    env["MOSS_APPEARANCE"] = appearance.as_env()

    # ★ 让子进程的 stdio 编码跟宿主的控制台一致。
    #   宿主启动时把控制台代码页切成了 UTF-8（`out.ensure_utf8_console`），
    #   但 Python 子进程**输出到管道时**不看控制台代码页，只看 locale ——
    #   于是子进程写 GBK、宿主写 UTF-8，同一屏里两套编码，接管道时必花屏
    #   （实测：直接看是好的，`moss :img webp > log.txt` 就乱）。
    #   用 setdefault：用户自己设过就尊重他的。
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


def _hide_window(inv):
    """要不要隐藏子进程的窗口。照抄 pa.py:394 的规则。

    path 调用：只有 `.pyw` 藏窗口（pa.py main() 里 ext=='.pyw' → background）
    包调用  ：`kind=app` 的 `.pyw` / `.exe` 藏窗口
              （pa.py handle_plugin_mode 里 type=='soft' → background）
    """
    ext = ""
    if inv.get("target"):
        ext = Path(inv["target"]).suffix.lower()
    if inv.get("kind") == "pkg" and inv.get("pkg_kind") == "app":
        return ext in (".pyw", ".exe")
    return ext == ".pyw"


# ---------------------------------------------------------------- 内置动作
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
        os.startfile(p)          # noqa: S606  (Windows 专用，照抄旧项目做法)
        return 0, "已打开：%s" % p
    return 1, "不认识的 builtin：%s" % what


# ---------------------------------------------------------------- 主流程
def run(inv, runners_table, detach=False):
    """执行一次调用。inv 是 Invocation 字典。返回 exit code。

    流程照抄 pa.py:219-313 execute_command_robust：
      清屏 → 起始横幅 → 起进程 → [PID] →（脱离 or 等结束）
      → 结束横幅（总长 / 结束时间 / end_banner）
    """
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
                # pa.py:225 —— 含空格的参数加引号只为显示好看
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
                # 子进程继承同一个控制台，不 flush 它的输出会插到前面去
                sys.stdout.flush()

                cflags = 0
                if _hide_window(inv):
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

    # pa.py:307-313 收尾横幅
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
