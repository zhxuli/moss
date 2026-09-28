#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""moss 界面 v0 —— 由 `moss.exe` 拉起，宿主把数据准备好后把**路径**放进 `MOSS_UI_DATA`。

三条硬规矩（都是被前几轮踩出来的）
----------------------------------
1. **这里不许 import core。** 发行版里 `core/` 编在 exe 里，磁盘上根本没有那个
   目录。所以界面要跑包时只能回头调 `MOSS_HOST_CMD`（就是 moss.exe 自己），
   和用户手敲命令走同一条路 —— 界面不另开一条执行通道。
2. **界面是渲染器，不认识 pkg.json。** 字段由宿主摊平成 JSON 喂进来
   （`core/ui.py:build_payload`）。包格式改了只改宿主一处。
3. `python.exe` 是控制台程序，而界面模式下宿主没有控制台 ⇒ 起子进程一律带
   `CREATE_NO_WINDOW`，否则点一下闪一个黑框（`E-27` ✅）。

v0 只做四件事：列包、看一个包的说明与参数、带参数跑并看输出、把包的界面开起来。
界面本身（`index.html`）以后随时改 —— 改它**不用重新打包 exe**，这正是把它
放在 exe 外面的理由（`K-10`）。
"""
import json
import os
import shlex
import subprocess
from pathlib import Path

import webview

HERE = Path(__file__).resolve().parent
NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW
DETACHED = 0x00000008           # DETACHED_PROCESS
DEVNULL = subprocess.DEVNULL


def _load_data():
    p = os.environ.get("MOSS_UI_DATA")
    if not p:
        raise SystemExit("缺少 MOSS_UI_DATA —— 这个界面只能由宿主拉起（moss ui / 双击 moss.exe）")
    return json.loads(Path(p).read_text(encoding="utf-8"))


DATA = _load_data()
HOST = [str(x) for x in (DATA.get("host_cmd") or [])]


def _split(text):
    """把参数框里那串文本拆成 argv。

    包参数本来就是"一个字符串"（`CL-02`），拼回去由宿主负责；这里只要拆得
    跟用户的直觉一致。带空格的路径用双引号括起来。
    """
    text = (text or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError:            # 引号没配对：别崩，按空白硬拆
        return text.split()


def _run_capture(argv):
    """跑一条宿主命令并把输出抓回来（合并 stdout+stderr，按 UTF-8 解）。"""
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW)
    except OSError as e:
        return {"code": -1, "out": "启动失败：%s" % e}
    return {"code": r.returncode, "out": (r.stdout or "") + (r.stderr or "")}


class Api:
    """给页面用的接口。每个方法都是一个前端可 await 的调用。"""

    def state(self):
        return DATA

    def run(self, pid, args_text=""):
        """带参数跑一个包，输出回页面（会等它跑完）。"""
        return _run_capture(HOST + [":" + str(pid)] + _split(args_text))

    def open_ui(self, pid, args_text=""):
        """把包的界面开起来：**脱离**当前进程、不抓输出，所以不会卡住界面。"""
        argv = HOST + [":" + str(pid)] + _split(args_text)
        try:
            subprocess.Popen(argv, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
                             creationflags=NO_WINDOW | DETACHED, close_fds=True)
        except OSError as e:
            return {"ok": False, "msg": "启动失败：%s" % e}
        return {"ok": True, "msg": "已后台启动：" + " ".join(argv[1:])}

    def run_host(self, text):
        """跑一条宿主命令（自检用）：`--selfcheck` / `--history 20` 之类，不带包名。"""
        return _run_capture(HOST + _split(text))

    def open_path(self, path):
        try:
            os.startfile(str(path))        # noqa: S606  Windows 专用
            return {"ok": True, "msg": "已打开：" + str(path)}
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}

    def quit(self):
        window.destroy()
        return {"ok": True}


window = webview.create_window(
    "moss",
    str(HERE / "index.html"),
    js_api=Api(),
    width=1280,
    height=860,
    min_size=(900, 600),
    # ★ text_select 默认是 **False**，页面上的字**选不中**（拖不动、也没法 Ctrl+C）——
    #   pywebview 的 `create_window(..., text_select: bool = False)`。
    #   命令行窗口最要紧的就是"能选中、能复制"，所以这里必须打开它；
    #   页面里也给 `#out` 写了 user-select:text，另外配了「复制全部」按钮。
    text_select=True,
)

if __name__ == "__main__":
    webview.start()
