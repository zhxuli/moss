# -*- coding: utf-8 -*-
"""img 的**内嵌模式**（`V-225`）：不开窗口，在 stdin/stdout 上跟 moss 说 JSON 行。

什么时候走这儿
--------------
宿主（moss）在「界面」选项卡里嵌这个包的页面时，会用 `MOSS_UI_EMBED=1` 把 `main.py`
起成一个**后端进程**，然后：

    宿主 → 我们（stdin）:   {"id": 1, "method": "scan", "params": {"dir": "D:\\pics"}}
    我们 → 宿主（stdout）:   {"id": 1, "ok": true, "result": {...}}

页面那一侧由 `ui/moss-embed.js` 垫片负责：内嵌时 `moss.call(...)` 走 postMessage →
宿主 → 转到这里的 stdin；独立窗口时垫片直接调 `window.pywebview.api.<方法>(params)`
（那一路由 `ui/src/bridge.js` 按同一套**字段名**发参数 ⇒ 一份 `Api` 两条路都吃）。

★ 拖放这条**在内嵌时走宿主**：真路径只有宿主拿得到（Chromium 不给页面 `File.path`）。
  宿主把它作为 `drop` 事件送给页面，页面再 `push_drop` 塞回这里 —— 于是
  `take_drop()` 那条老管线（`core.expand_dropped` 判文件夹/清单、按配置过滤、记历史）
  **一个字都不用改**就用上了。

★ 规矩：**stdout 只许出 JSON 行**。日志走 `_log()`（stderr）—— 宿主对不是 `{` 开头的行会当
  "输出"收进命令行（无害），但把一条 JSON 拆成两行就真把协议撕了。
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

    #: 这些方法**不给页面调**（内部用的，或者只在独立窗口那条路上有意义）。
    #  ★ `push_drop` **不在**这张表里（`V-227`）：它是页面**自己**往回塞路径的那条路 ——
    #    内嵌时真路径只有宿主拿得到，宿主用 `drop` 事件送进页面，页面必须能把它
    #    `push_drop` 交给后端，后面 `take_drop` 那条老管线才跑得起来。
    #    把它挡掉 = 拖进来什么都不发生（真机上就是一句"没有这个方法 push_drop"）。
    #    （`exec` 那份 embed.py 挡着它，因为 exec 根本没有 take_drop / push_drop 这条线。）
    HIDDEN = ('attach', '_scan', '_remember', '_on_closing', 'save_config', 'set_title')

    def __init__(self, api=None):
        self.api = api or Api()

    def send(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    def _log(self, text):
        """给人看的日志走 stderr（**不污染** stdout 那条协议）。"""
        try:
            sys.stderr.write('[img] %s\n' % text)
            sys.stderr.flush()
        except Exception:                                            # noqa: BLE001
            pass

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
        if method.startswith('_') or method in self.HIDDEN:
            return {'id': mid, 'ok': False, 'error': '没有这个方法：%s' % method}
        fn = getattr(self.api, method, None)
        if not callable(fn):
            return {'id': mid, 'ok': False, 'error': '没有这个方法：%s' % method}
        try:
            return {'id': mid, 'ok': True, 'result': fn(params)}
        except Exception as e:                                       # noqa: BLE001
            self._log('%s 出错：%s: %s' % (method, type(e).__name__, e))
            return {'id': mid, 'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}

    def loop(self):
        """一行一行读到 EOF；宿主收走进程时 stdin 关闭，这里就结束（返回 0）。"""
        # 数据目录先建出来（配置 / 历史 / 缩略图缓存都写这儿；跟独立窗口那条一样）
        try:
            os.makedirs(core.DATA_DIR, exist_ok=True)
        except OSError:
            pass
        self._log('内嵌模式起来了（数据目录 = %s）' % core.DATA_DIR)
        for line in sys.stdin:
            line = (line or '').strip()
            if not line:
                continue
            self.send(self.handle(line))
        return 0
