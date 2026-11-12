import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import core
from gui_web import Api

def embedded_now():
    return str(os.environ.get('MOSS_UI_EMBED') or '').strip().lower() in ('1', 'true', 'yes')

class Embedded:
    def __init__(self, api=None):
        self.api = api or Api()

    def send(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + '\n')
        sys.stdout.flush()

    def _log(self, text):
        try:
            sys.stderr.write('[exec] %s\n' % text)
            sys.stderr.flush()
        except Exception:
            pass

    def handle(self, line):
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
        if not callable(fn) or method.startswith('attach') or method == 'attach':
            return {'id': mid, 'ok': False, 'error': '没有这个方法：%s' % method}
        try:
            return {'id': mid, 'ok': True, 'result': fn(params)}
        except Exception as e:
            self._log('%s 出错：%s: %s' % (method, type(e).__name__, e))
            return {'id': mid, 'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}

    def loop(self):
        core.init_cmds_dir()
        self._log('内嵌模式起来了（数据目录 = %s）' % core.CMDS_DIR)
        for line in sys.stdin:
            line = (line or '').strip()
            if not line:
                continue
            self.send(self.handle(line))
        return 0
