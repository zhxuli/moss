import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from core import Api


def embedded_now():
    return str(os.environ.get("MOSS_UI_EMBED") or "").strip().lower() in ("1", "true", "yes")


# 只有独立窗口才有意义 / 纯内部件，界面不该调
HIDDEN = {"gui", "cli"}


class Embedded:
    def __init__(self, api=None):
        self.api = api or Api()

    def send(self, obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def _log(self, text):
        try:
            sys.stderr.write("[pip] %s\n" % text)
            sys.stderr.flush()
        except Exception:
            pass

    def handle(self, line):
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
        if not method or method.startswith("_") or method in HIDDEN:
            return {"id": mid, "ok": False, "error": "没有这个方法：%s" % method}
        fn = getattr(self.api, method, None)
        if not callable(fn):
            return {"id": mid, "ok": False, "error": "没有这个方法：%s" % method}
        try:
            return {"id": mid, "ok": True, "result": fn(params)}
        except Exception as e:
            self._log("%s 出错：%s: %s" % (method, type(e).__name__, e))
            return {"id": mid, "ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def loop(self):
        self._log("内嵌模式起来了（解释器 = %s）" % Api().env().get("runtime", {}).get("python"))
        for line in sys.stdin:
            line = (line or "").strip()
            if not line or not line.startswith("{"):
                continue
            self.send(self.handle(line))
        return 0
