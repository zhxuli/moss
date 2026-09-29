# -*- coding: utf-8 -*-
"""BMI 计算器 —— **示例包**：一份界面代码，两种跑法。

    moss :bmi                 不带参数 → 自己开一个窗口（不依赖 moss 的界面）
    在 moss 界面里点「运行」   → 内嵌到 moss 的「界面」选项卡里跑

两种跑法**共用同一份** `ui/index.html`（Vue 3 写的），靠 `ui/moss-embed.js` 这个垫片
自动分流：被嵌进 moss 的时候走 postMessage，独立窗口的时候走 pywebview 的 js_api。
界面上的**所有数据都来自这个文件**（Python）—— 时间、BMI、分级，前端只负责显示。

内嵌模式（宿主要求的）约定（`V-51`）：
  · 宿主起这个包时会给 `MOSS_UI_EMBED=1`；
  · 这时**别开窗口**，改成在 stdin/stdout 上说话，一行一个 JSON **对象**；
  · 收到 `{"id": 1, "method": "bmi", "params": {"height": 175, "weight": 70}}`
    就回 `{"id": 1, "ok": true, "result": {...}}`；
  · 想主动推给界面就用 `{"event": "time", "data": {...}}`（没有 id）；
  · 宿主自己的横幅是 `[执行] / [目录] / [PID]` 这种**数组样子的行**，
    界面那侧只认 `{` 开头的行，所以两边不会串（宿主一行都不用改）。
"""
import json
import os
import sys
import threading
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
UI = os.path.join(HERE, 'ui', 'index.html')
TITLE = 'BMI 计算器（moss 示例包）'

#: BMI 分级（中国标准，示例用；前端不参与判断，全在这里定）
LEVELS = [
    (18.5, '偏瘦', '多吃点，别熬夜。'),
    (24.0, '正常', '保持住。'),
    (28.0, '超重', '少喝奶茶，多走路。'),
    (999.0, '肥胖', '认真考虑一下运动和饮食吧。'),
]


def calc_bmi(height_cm, weight_kg):
    """后端算 BMI。返回一份**给界面用的现成结果**（分级也在这边定）。"""
    try:
        h = float(height_cm) / 100.0
        w = float(weight_kg)
    except (TypeError, ValueError):
        return {'ok': False, 'why': '身高体重都得是数字'}
    if h <= 0.5 or h > 2.8:
        return {'ok': False, 'why': '身高（cm）大概是 50～280 之间吧'}
    if w <= 2 or w > 500:
        return {'ok': False, 'why': '体重（kg）大概是 2～500 之间吧'}
    bmi = w / (h * h)
    level, advice = '肥胖', ''
    for limit, name, tip in LEVELS:
        if bmi < limit:
            level, advice = name, tip
            break
    return {
        'ok': True,
        'bmi': round(bmi, 2),
        'level': level,
        'advice': advice,
        'who': 'Python（pid %d）' % os.getpid(),   # 让界面能证明"这是后端算的"
        'at': now_payload(),
    }


def now_payload():
    """当前时间 —— 这一份是**给界面显示的**（前端自己 `new Date()` 拿不到后端时间）。"""
    t = datetime.now()
    return {
        'text': t.strftime('%H:%M:%S'),
        'date': t.strftime('%Y-%m-%d'),
        'week': '一二三四五六日'[t.weekday()],
        'ts': time.time(),
        'who': 'Python（pid %d）' % os.getpid(),
    }


# ---------------------------------------------------------------- 内嵌模式（stdio）
class Embedded:
    """在 stdin/stdout 上说话的那一半。方法名跟界面里 `moss.call("名字")` 一一对应。"""

    def __init__(self):
        self._subs = set()
        self._lock = threading.Lock()
        self._stop = False

    # ---- 可以被界面调的方法
    def now(self, params=None):
        return now_payload()

    def bmi(self, params=None):
        p = params or {}
        return calc_bmi(p.get('height'), p.get('weight'))

    def subscribe(self, params=None):
        """界面说"我要实时时间" —— 之后由**后端主动推**（`{"event": "time"}`）。"""
        with self._lock:
            self._subs.add(str((params or {}).get('event') or 'time'))
        return {'subscribed': sorted(self._subs)}

    def unsubscribe(self, params=None):
        with self._lock:
            self._subs.discard(str((params or {}).get('event') or 'time'))
        return {'subscribed': sorted(self._subs)}

    def info(self, params=None):
        return {'pid': os.getpid(), 'python': sys.version.split()[0],
                'cwd': os.getcwd(), 'embedded': True}

    # ---- 输出
    def send(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    def _ticker(self):
        """每秒钟推一次时间（订阅了才推）。停下来是因为 stdin 关了/进程要退了。"""
        while not self._stop:
            time.sleep(1.0)
            with self._lock:
                subs = set(self._subs)
            if 'time' in subs:
                self.send({'event': 'time', 'data': now_payload()})

    def loop(self):
        threading.Thread(target=self._ticker, daemon=True).start()
        for line in sys.stdin:
            line = (line or '').strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                self.send({'event': 'error', 'data': {'why': '这不是 JSON：%s' % line[:80]}})
                continue
            mid, method = msg.get('id'), str(msg.get('method') or '')
            fn = getattr(self, method, None)
            if not callable(fn) or method.startswith('_'):
                self.send({'id': mid, 'ok': False, 'error': '没有这个方法：%s' % method})
                continue
            try:
                result = fn(msg.get('params'))
                self.send({'id': mid, 'ok': True, 'result': result})
            except Exception as e:                                       # noqa: BLE001
                self.send({'id': mid, 'ok': False, 'error': '%s: %s' % (type(e).__name__, e)})
        self._stop = True


# ---------------------------------------------------------------- 独立窗口模式
def run_window():
    """不带参数时：自己开一个窗口（和别的 GUI 包一样，`CLI-01`）。"""
    import webview                                            # noqa: PLC0415

    class Api:
        def now(self):
            return now_payload()

        def bmi(self, params=None):
            return calc_bmi((params or {}).get('height'), (params or {}).get('weight'))

        def info(self, params=None):
            return {'pid': os.getpid(), 'python': sys.version.split()[0],
                    'cwd': os.getcwd(), 'embedded': False}

    window = webview.create_window(TITLE, url=UI, js_api=Api(),
                                   width=980, height=720, min_size=(720, 560))
    webview.start()
    return 0


def main():
    if str(os.environ.get('MOSS_UI_EMBED') or '').strip() in ('1', 'true', 'yes'):
        Embedded().loop()          # 内嵌：不开窗口，在 stdio 上答话
        return 0
    return run_window()            # 独立：自己开窗口


if __name__ == '__main__':
    sys.exit(main())
