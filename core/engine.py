# -*- coding: utf-8 -*-
"""执行引擎 `ExecEngine`（`E-01`）。

凡是"启动一个东西"要用到的事情，**只允许在这一个地方实现**：
    拼命令 / 选解释器 / 注入环境 / 起进程 / 处理 Ctrl-C / 收结构化结果 / 发事件

pa 的入口和以后 exec 工作台、AI 调用，全都走这里。

★ 照抄 pa.py 的部分（`E-20`）：
  · `kill_process_tree()` —— `pa.py:210` 原样搬
  · 环境的注入方式 —— `pa.py:234-238` 注入 `PA_*`，这里换成 `MOSS_*`
  · 前台执行直接继承控制台 —— `pa.py` 的 `interactive` 模式

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
from urllib.parse import quote

from . import events, paths, runners as runners_mod

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def kill_process_tree(pid):
    """照抄 pa.py:210。"""
    try:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=_NO_WINDOW)
    except Exception:
        pass


# ---------------------------------------------------------------- 构造
def build_argv(inv, spec):
    """按 runner 的 launch 模板拼命令。

    ★ `{runTarget}`：有些语言"跑单个文件"和"跑整个包"是两条路。
      最典型的是 Go —— 实测：
          `go run main.go`  只编译那一个文件，多文件项目直接
                            `undefined: xxx`；没有 go.mod 时它才管用
          `go run .`        跑整个包（多文件正确），但**必须有 go.mod**
      所以 runner 用 `runTarget` 字段声明这个判断，引擎只负责执行它 ——
      保持"执行方式变成数据"（F-19），不把某种语言的知识写死进引擎。
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

    argv = []
    for tpl in (spec.get("launch") or []):
        try:
            argv.append(tpl.format(**ctx))
        except Exception:
            argv.append(tpl)
    return argv


def build_env(inv):
    """给子进程的环境。照抄 pa.py 的注入方式，换成 MOSS_* 前缀。"""
    env = os.environ.copy()
    env["MOSS_HOME"] = str(paths.HOME)
    env["MOSS_USER_DATA_DIR"] = str(paths.USER_DIR)

    # 路径调用没有包名，用 cwd 的稳定哈希当身份；包调用用包 id
    key = inv.get("id") or ("path:" + str(inv.get("cwd") or ""))
    state = paths.state_dir_for(key)
    env["MOSS_PLUGIN_DATA_DIR"] = str(state)

    if inv.get("id"):
        env["MOSS_PKG_ID"] = str(inv["id"])
        env["MOSS_PKG_VERSION"] = str(inv.get("version") or "")
    env["MOSS_PKG_PARAMS"] = json.dumps(inv.get("params") or {}, ensure_ascii=False)
    env["MOSS_ARGS"] = " ".join(inv.get("args") or [])
    env["MOSS_VIA"] = inv.get("via") or "cli"
    if inv.get("venv"):
        env["MOSS_VENV"] = str(inv["venv"])

    # 结构化返回（F-12）：包把结果写进这个文件，宿主读回来当 data
    env["MOSS_RESULT_FILE"] = inv["_result_file"]
    return env


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
def run(inv, runners_table):
    """执行一次调用。inv 是 Invocation 字典。返回 exit code。

    流程对应 §21.2：第 6 步 before:run → 第 7/8 步执行 → 第 9 步 after:run。
    """
    spec = runners_table.get(inv.get("runner")) or {}
    inv = dict(inv)

    # 结果文件：包可以往里写 JSON，宿主读回来当 data
    fd, result_file = tempfile.mkstemp(prefix="moss_result_", suffix=".json")
    os.close(fd)
    inv["_result_file"] = result_file

    started = time.time()
    events.BUS.emit("before:run", {"invocation": inv})

    exit_code = 0
    data = None

    try:
        if spec.get("builtin"):
            exit_code, msg = _run_builtin(inv, spec)
            print(("[完成] " if exit_code == 0 else "[错误] ") + msg)
        else:
            argv = build_argv(inv, spec)
            if not argv:
                print("[错误] runner '%s' 没有可用的 launch 模板。" % inv.get("runner"))
                exit_code = 1
            else:
                cwd = inv.get("cwd") or os.getcwd()
                print("[执行] %s" % " ".join('"%s"' % a if " " in a else a for a in argv))
                print("[目录] %s" % cwd)
                # 必须先 flush：子进程会继承同一个控制台，不 flush 的话它的输出会插到前面去
                sys.stdout.flush()
                try:
                    proc = subprocess.Popen(argv, cwd=cwd, env=build_env(inv))
                    while proc.poll() is None:
                        time.sleep(0.05)
                    exit_code = proc.returncode or 0
                except KeyboardInterrupt:
                    print("\n[中断] 正在强力终止进程树...")
                    try:
                        kill_process_tree(proc.pid)
                    except Exception:
                        pass
                    exit_code = 130
                except FileNotFoundError as e:
                    print("[错误] 找不到可执行文件：%s" % e)
                    exit_code = 1
                except Exception as e:
                    print("[错误] 执行失败：%s" % e)
                    exit_code = 1
    finally:
        # 读结构化返回
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

        ms = int((time.time() - started) * 1000)
        events.BUS.emit("after:run", {
            "invocation": inv,
            "result": {"exit": exit_code, "ms": ms, "data": data},
        })

    if data is not None:
        print("[结果] %s" % json.dumps(data, ensure_ascii=False))
    return exit_code
