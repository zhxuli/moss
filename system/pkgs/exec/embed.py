# -*- coding: utf-8 -*-
"""exec 的**内嵌模式**（`V-222`）：不开窗口，在 stdin/stdout 上跟 moss 说 JSON 行。

什么时候走这儿
--------------
宿主（moss）在「界面」选项卡里嵌这个包的页面时，会用
`MOSS_UI_EMBED=1` 把 `main.py` 起成一个**后端进程**，然后：

    宿主 → 我们（stdin）:   {"id": 1, "method": "cmd_list", "params": {}}
    我们 → 宿主（stdout）:   {"id": 1, "ok": true, "result": {...}}
    我们主动推（可选）:      {"event": "名字", "data": {...}}

页面那一侧由 `ui/moss-embed.js` 垫片负责：内嵌时 `moss.call(...)` 走 postMessage →
宿主 → 转到这里的 stdin；独立窗口时垫片直接调 `window.pywebview.api.<方法>(params)`。

★ 一句话：**同一份 `gui_web.Api`，两条路都吃** —— 都不在这儿另写业务。
★ 规矩（也是踩过的坑）：**别往 stdout 打别的东西**。宿主是按行读 JSON 的，
  不以 `{` 开头的行会被当成"输出"收进命令行（看得见但没用），而**带换行的多行 print
  会把一条 JSON 拆两半**。要留日志就 `print` 到 stderr，或者明确走 `_log()`。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import core                                                          # noqa: E402
from gui_web import Api                                              # noqa: E402


def embedded_now():
    """宿主是不是让我们跑内嵌模式（`MOSS_UI_EMBED=1`）。"""
    return str(os.environ.get('MOSS_UI_EMBED') or '').strip().lower() in ('1', 'true', 'yes')


class Embedded:
    """stdio 上的 JSON 行循环。"""

    def __init__(self, api=None):
        self.api = api or Api()

    # -- 说话 ----------------------------------------------------------
    def send(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    def _log(self, text):
        """给人看的日志走 stderr（**不污染** stdout 那条协议）。"""
        try:
            sys.stderr.write('[exec] %s\n' % text)
            sys.stderr.flush()
        except Exception:                                            # noqa: BLE001
            pass

    # -- 干活 ----------------------------------------------------------
    def handle(self, line):
        """处理一行请求，返回要回的那份对象（不直接写，方便探针直接调）。"""
        try:
            msg = json.loads(line)
        except ValueError:
            self._log('这不是 JSON：%s' % str(line)[:80])
            return {'ok': False, 'error': '这不是 JSON：%s' % str(line)[:80]}
        if not isinstance(msg, dict):
            return {'ok': False, 'error': '要一个 JSON 对象'}
        mid = msg.get('id')
        method = str(msg.get('method') or '')
        params = msg.get('params')
        if not isinstance(params, dict):
            params = {}
        if method.startswith('_'):
            return {'id': mid, 'ok': False, 'error': '没有这个方法：%s' % method}
        fn = getattr(self.api, method, None)
        # ★ 只认 Api 上**公开的**方法：`getattr` 会把 `_window` / `_runs` 这些也翻出来，
        #   真调到它们（比如 `run_poll` 少了 params）就是一串莫名其妙的报错。
        if not callable(fn) or method.startswith('attach') or method == 'attach':
            return {'id': mid, 'ok': False, 'error': '没有这个方法：%s' % method}
        try:
            return {'id': mid, 'ok': True, 'result': fn(params)}
        except Exception as e:                                       # noqa: BLE001
            self._log('%s 出错：%s: %s' % (method, type(e).__name__, e))
            return {'id': mid, 'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}

    def loop(self):
        """一行一行读到 EOF；宿主收走进程时 stdin 关闭，这里就结束（返回 0）。"""
        core.init_cmds_dir()
        self._log('内嵌模式起来了（数据目录 = %s）' % core.CMDS_DIR)
        for line in sys.stdin:
            line = (line or '').strip()
            if not line:
                continue
            self.send(self.handle(line))
        return 0
