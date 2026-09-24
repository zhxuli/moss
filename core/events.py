# -*- coding: utf-8 -*-
"""极简事件总线。

设计原则（T-05）：**审计与状态内建（订阅事件），扩展靠钩子。**
  · 内核自己的服务（历史、台账）作为**内建订阅者**挂上去，不依赖钩子
  · 用户钩子是**额外的可玩性**，默认非阻塞、有超时、失败不中断主流程

M1 只做进程内事件；钩子的外部调用留到后面的版本。
"""


class Bus:
    def __init__(self):
        self._subs = {}          # event -> [(name, fn, blocking)]
        self.trace = []          # 本次运行的简单轨迹，便于 --selfcheck 排查

    def on(self, event, fn, name=None, blocking=False):
        self._subs.setdefault(event, []).append((name or getattr(fn, "__name__", "?"), fn, blocking))

    def emit(self, event, payload=None):
        """广播事件。返回 [(订阅者名, 结果或异常)]，供排查用。"""
        results = []
        for name, fn, blocking in self._subs.get(event, []):
            try:
                results.append((name, fn(payload)))
            except Exception as e:
                results.append((name, "ERROR: %s" % e))
                if blocking:
                    raise
        self.trace.append((event, results))
        return results


BUS = Bus()
