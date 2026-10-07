# -*- coding: utf-8 -*-
"""**问用户**（`V-308`）：AI 在跑到一半时停下来问一句 —— 用户不答，它不动。

用户 2026-10-07 的原话：「它似乎从来不会问我问题 或者让我做选择题 是我们没有设计这个功能吗？
按说 如果有什么它拿不准的 那应该先咨询我」。

所以这一层就干一件事：把"loop 线程**阻塞**在这里等人"做成一个可复用的东西。两种用法：

  · `kind="ask"`     —— 拿不准就问（`ask` 工具）：给几个选项 + 可选自由输入；
  · `kind="confirm"` —— 危险操作点头（`ai_mode.danger_of` 判出来的那些）：允许 / 拒绝。

★ 三条边界（都是这台机器上真会出问题的地方）：
  1. **用户按停止 = 立刻放行**（回 `answered=False`），绝不能让 loop 卡在一个没人回答的
     问题上 —— 那正是"按了停止还是卡死"的另一种形态（`V-242`）。
  2. **有超时**：默认 30 分钟。超时回 `timeout=True`，模型会收到"用户没回"，它该怎么收尾怎么收尾。
  3. **`submit()` 可以在任何线程调**（宿主那个 pywebview 线程）—— 只碰 Event 和一把小锁。
"""
import itertools
import threading
import time

#: 默认等多久（秒）—— 用户可能去干别的了，别永远挂着
DEFAULT_TIMEOUT = 1800
#: 等的时候每一格醒多久（要能立刻看见"停止"）
TICK = 0.2

_seq = itertools.count(1)


class Asker:
    """一次跑一个。`publish(问题 dict)` 把问题交给界面（宿主写进 `AI["state"]["ask"]`）。"""

    def __init__(self, publish=None, stop_check=None, timeout=DEFAULT_TIMEOUT):
        self.publish = publish
        self.stop_check = stop_check
        self.timeout = float(timeout or DEFAULT_TIMEOUT)
        self._lock = threading.Lock()
        self._ev = threading.Event()
        self._q = None            # 现在挂着的问题（None = 没在问）
        self._ans = None          # 用户给的答案
        self.asked = 0            # 一共问过几次（界面/记录用）

    # ---------------------------------------------------------------- 问
    def ask(self, question, options=(), allow_text=True, kind="ask", why="",
            detail="", timeout=None):
        """挂一个问题，**阻塞**到用户回答 / 停止 / 超时。回：

            {"answered": True,  "text": "用户打的字", "choice": "用户点的那个", "qid": "…"}
            {"answered": False, "reason": "stopped"|"timeout"|"busy", "qid": "…"}
        """
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
            if self._q is not None:            # 同一时刻只挂一个问题（不该发生）
                return {"answered": False, "reason": "busy", "qid": q["qid"]}
            self._q, self._ans = q, None
            self._ev.clear()
            self.asked += 1
        if self.publish:
            try:
                self.publish(dict(q))
            except Exception:                                        # noqa: BLE001
                pass
        # ★ 等的时候一小格一小格醒：按了停止 <=0.2 秒就能走（跟 client 那条一个心思）
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
                self.publish(None)               # 清掉界面上的那张卡
            except Exception:                                        # noqa: BLE001
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

    # ---------------------------------------------------------------- 答 / 取消
    def submit(self, text="", choice="", by="user"):
        """用户答了（宿主线程调）。回一句给界面看的结果。"""
        with self._lock:
            if self._q is None:
                return {"ok": False, "msg": "现在没有挂着的问题（可能已经超时了）"}
            if self._ans is not None:
                return {"ok": False, "msg": "这个问题已经收到回答，正在继续处理"}
            self._ans = {"text": str(text or ""), "choice": str(choice or ""), "by": str(by or "user")}
            self._ev.set()
        return {"ok": True, "msg": "答上了"}

    def cancel(self, reason="stopped"):
        """停止 / 超时：让它别再等（回 `answered=False`）。"""
        with self._lock:
            if self._q is None:
                return {"ok": False, "msg": "没有挂着的问题"}
            q = self._q
            q["_reason"] = str(reason or "stopped")
            self._ans = None
            self._ev.set()
        return {"ok": True, "msg": "已经放它走了（%s）" % reason}

    # ---------------------------------------------------------------- 给界面看
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
