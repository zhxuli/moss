import itertools
import threading
import time

DEFAULT_TIMEOUT = 1800
TICK = 0.2

_seq = itertools.count(1)

class Asker:
    def __init__(self, publish=None, stop_check=None, timeout=DEFAULT_TIMEOUT):
        self.publish = publish
        self.stop_check = stop_check
        self.timeout = float(timeout or DEFAULT_TIMEOUT)
        self._lock = threading.Lock()
        self._ev = threading.Event()
        self._q = None
        self._ans = None
        self.asked = 0

    def ask(self, question, options=(), allow_text=True, kind="ask", why="",
            detail="", timeout=None):
        q = {
            "qid": "q%d-%d" % (int(time.time()), next(_seq)),
            "question": str(question or "").strip() or "（它没写问题）",
            "options": [self._opt(o) for o in (options or [])],
            "allow_text": bool(allow_text),
            "kind": str(kind or "ask"),
            "why": str(why or ""),
            "detail": str(detail or ""),
            "at": time.time(),
            "at_text": time.strftime("%H:%M:%S"),
        }
        with self._lock:
            if self._q is not None:
                return {"answered": False, "reason": "busy", "qid": q["qid"]}
            self._q, self._ans = q, None
            self._ev.clear()
            self.asked += 1
        if self.publish:
            try:
                self.publish(dict(q))
            except Exception:
                pass
        left = float(timeout or self.timeout)
        t0 = time.time()
        while True:
            if self._ev.wait(TICK):
                break
            if self.stop_check and self.stop_check():
                self.cancel("stopped")
                break
            if time.time() - t0 > left:
                self.cancel("timeout")
                break
        with self._lock:
            ans = self._ans
            qid = q["qid"]
            reason = "" if ans else ((self._q or {}).get("_reason") or "timeout")
            self._q, self._ans = None, None
            self._ev.clear()
        if self.publish:
            try:
                self.publish(None)
            except Exception:
                pass
        if ans:
            return dict(ans, answered=True, qid=qid, seconds=round(time.time() - t0, 1))
        return {"answered": False, "reason": reason, "qid": qid,
                "seconds": round(time.time() - t0, 1)}

    @staticmethod
    def _opt(o):
        if isinstance(o, dict):
            return {"label": str(o.get("label") or o.get("value") or "")[:120],
                    "value": str(o.get("value") or o.get("label") or "")[:200],
                    "desc": str(o.get("desc") or "")[:200]}
        return {"label": str(o)[:120], "value": str(o)[:200], "desc": ""}

    def submit(self, text="", choice="", by="user"):
        with self._lock:
            if self._q is None:
                return {"ok": False, "msg": "现在没有挂着的问题（可能已经超时了）"}
            if self._ans is not None:
                return {"ok": False, "msg": "这个问题已经收到回答，正在继续处理"}
            self._ans = {"text": str(text or ""), "choice": str(choice or ""), "by": str(by or "user")}
            self._ev.set()
        return {"ok": True, "msg": "答上了"}

    def cancel(self, reason="stopped"):
        with self._lock:
            if self._q is None:
                return {"ok": False, "msg": "没有挂着的问题"}
            q = self._q
            q["_reason"] = str(reason or "stopped")
            self._ans = None
            self._ev.set()
        return {"ok": True, "msg": "已经放它走了（%s）" % reason}

    def state(self):
        with self._lock:
            if self._q is None:
                return None
            q = dict(self._q)
        q["asking"] = round(time.time() - float(q.get("at") or time.time()), 1)
        q.pop("_reason", None)
        return q

    def busy(self):
        with self._lock:
            return self._q is not None
