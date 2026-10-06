# -*- coding: utf-8 -*-
"""`:skill` 的**内嵌模式**：不开窗口，在 stdin/stdout 上跟 moss 说 JSON 行。

跟 `exec/embed.py` 一模一样的一套协议（抄过来的，`V-48`/`V-222`）：

    宿主 → 我们（stdin）:   {"id": 1, "method": "list", "params": {}}
    我们 → 宿主（stdout）:   {"id": 1, "ok": true, "result": {...}}

★ 规矩（也是踩过的坑）：**别往 stdout 打别的东西**。宿主按行读 JSON，不以 `{` 开头的行
  会被当成命令行的输出（看得见但没用），而**带换行的多行 print 会把一条 JSON 拆两半**。
  要留日志就写 stderr。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core import Api                                                 # noqa: E402


def embedded_now():
    """宿主是不是让我们跑内嵌模式（`MOSS_UI_EMBED=1`）。"""
    return str(os.environ.get("MOSS_UI_EMBED") or "").strip().lower() in ("1", "true", "yes")


class Embedded:
    def __init__(self, api=None):
        self.api = api or Api()

    def send(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def _log(self, text):
        try:
            sys.stderr.write("[skill] %s\n" % text)
            sys.stderr.flush()
        except Exception:                                              # noqa: BLE001
            pass

    def handle(self, line):
        """处理一行请求，返回要回的那份对象（不直接写，方便探针直接调）。"""
        try:
            msg = json.loads(line)
        except ValueError:
            return {"ok": False, "error": "这不是 JSON：%s" % str(line)[:80]}
        if not isinstance(msg, dict):
            return {"ok": False, "error": "要一个 JSON 对象"}
        mid = msg.get("id")
        method = str(msg.get("method") or "")
        params = msg.get("params")
        if not isinstance(params, dict):
            params = {}
        if method.startswith("_") or method in ("gui", "cli"):
            return {"id": mid, "ok": False, "error": "没有这个方法：%s" % method}
        fn = getattr(self.api, method, None)
        if not callable(fn):
            return {"id": mid, "ok": False, "error": "没有这个方法：%s" % method}
        try:
            return {"id": mid, "ok": True, "result": fn(params)}
        except Exception as e:                                         # noqa: BLE001
            self._log("%s 出错：%s: %s" % (method, type(e).__name__, e))
            return {"id": mid, "ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def loop(self):
        """一行一行读到 EOF；宿主收走进程时 stdin 关闭，这里就结束（返回 0）。"""
        self._log("内嵌模式起来了（技能目录 = %s）" % Api().list().get("dir"))
        for line in sys.stdin:
            line = (line or "").strip()
            if not line:
                continue
            self.send(self.handle(line))
        return 0
