import http.client
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

class AiError(Exception):
    def __init__(self, msg, retryable=False, timeout=False, status=0):
        super().__init__(msg)
        self.retryable = bool(retryable)
        self.timeout = bool(timeout)
        self.status = int(status or 0)

class Stopped(AiError):
    pass

RETRY_TIMES = 2
RETRY_WAITS = (1.5, 4.0)

TIMEOUT_RETRIES = 1

STREAM = True

def retry_wait(attempt):
    n = max(int(attempt or 1) - 1, 0)
    return RETRY_WAITS[min(n, len(RETRY_WAITS) - 1)]

def from_env(need=True):
    base = (os.environ.get("MOSS_AI_BASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("MOSS_AI_API_KEY") or "").strip()
    model = (os.environ.get("MOSS_AI_MODEL") or "").strip()
    models = [m.strip() for m in (os.environ.get("MOSS_AI_MODELS") or "").split(",") if m.strip()]
    if need and not (base and model):
        raise AiError("还没配 AI：打开 moss 的「设置 → AI」挑一家（或 `moss --ai-profile-set 名字 "
                      "base_url=… model=…`）。当前 base_url=%r model=%r" % (base, model))
    return {"base_url": base, "api_key": key, "model": model,
            "models": models or ([model] if model else [])}

class Client:
    def __init__(self, base_url, api_key, model, timeout=180):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.model = str(model or "")
        self.timeout = timeout

    @classmethod
    def from_env(cls, model=None, timeout=180):
        cfg = from_env()
        return cls(cfg["base_url"], cfg["api_key"], model or cfg["model"], timeout=timeout)

    def chat(self, messages, tools=None, temperature=None, stop_check=None, on_wait=None,
             on_retry=None, on_delta=None, on_reasoning=None):
        body = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if temperature is not None:
            body["temperature"] = temperature
        want_stream = bool(STREAM)
        want_usage = bool(STREAM)
        net_fails = 0
        timed_out = 0
        fails = 0
        raw = ""
        while True:
            if want_stream:
                body["stream"] = True
            else:
                body.pop("stream", None)
            if want_stream and want_usage:
                body["stream_options"] = {"include_usage": True}
            else:
                body.pop("stream_options", None)
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            try:
                raw = self._post_watched(data, stop_check=stop_check, on_wait=on_wait,
                                         on_delta=on_delta, on_reasoning=on_reasoning,
                                         stream=want_stream)
                break
            except Stopped:
                raise
            except AiError as e:
                if stop_check and stop_check():
                    raise Stopped("用户按了停止")
                if e.status == 400 and body.get("stream_options"):
                    want_usage = False
                    continue
                if e.status == 400 and body.get("stream"):
                    want_stream = False
                    continue
                if e.timeout:
                    timed_out += 1
                    can = timed_out <= TIMEOUT_RETRIES
                    kind_total = TIMEOUT_RETRIES + 1
                else:
                    net_fails += 1
                    can = bool(e.retryable) and net_fails <= RETRY_TIMES
                    kind_total = RETRY_TIMES + 1
                if not can:
                    if e.timeout:
                        raise AiError("%s（连着 %d 次都这样 —— 请求可能已经发出去了，"
                                      "只是这条连接没回话。网络/代理稳一点后点「重新跑」就行）"
                                      % (e, TIMEOUT_RETRIES + 1), timeout=True)
                    if e.retryable:
                        raise AiError("%s（连着 %d 次都没连上 —— 网络/代理是不是断了？"
                                      "这次任务**一个字都没发出去**，网络好了点「重新跑」就行）"
                                      % (e, RETRY_TIMES + 1), retryable=True)
                    raise
                fails += 1
                wait = retry_wait(fails)
                if on_retry:
                    try:
                        on_retry(fails, kind_total, e)
                    except Exception:
                        pass
                slept = 0.0
                while slept < wait:
                    if stop_check and stop_check():
                        raise Stopped("用户按了停止")
                    time.sleep(0.2)
                    slept += 0.2
        try:
            obj = json.loads(raw)
        except ValueError:
            raise AiError("回的不是 JSON（前 300 字）：%s" % str(raw)[:300])
        return self._normalize(obj)

    def _post_watched(self, data, stop_check=None, on_wait=None, on_delta=None,
                      on_reasoning=None, stream=True):
        box = {}
        hb = {"t": time.time()}

        def work():
            try:
                box["got"] = (self._post_stream(data, hb=hb, on_delta=on_delta,
                                                on_reasoning=on_reasoning) if stream
                              else self._post(data, hb=hb))
            except BaseException as e:
                box["err"] = e

        th = threading.Thread(target=work, daemon=True)
        th.start()
        while True:
            th.join(0.1)
            if not th.is_alive():
                break
            if stop_check and stop_check():
                raise Stopped("用户按了停止")
            idle = time.time() - hb["t"]
            if idle > self.timeout:
                raise AiError("%d 秒一个字节都没收到（超时）—— 模型的回答还没开始回，"
                              "或者这条连接已经断了。" % self.timeout, timeout=True)
            if on_wait:
                try:
                    on_wait(round(idle, 1))
                except Exception:
                    pass
        if "err" in box:
            raise box["err"]
        return box.get("got")

    def _post(self, data, stop_check=None, on_wait=None, hb=None):
        u = urllib.parse.urlsplit(self.base_url)
        host, port = u.hostname, (u.port or (443 if u.scheme == "https" else 80))
        path = ((u.path or "").rstrip("/")) + "/chat/completions"
        headers = {"Content-Type": "application/json",
                   "Authorization": "Bearer " + self.api_key,
                   "Content-Length": str(len(data)),
                   "Accept": "application/json",
                   "Connection": "close"}
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = cls(host, port, timeout=max(60.0, float(self.timeout or 0) + 15.0))
        t0 = time.time()
        if hb is not None:
            hb["t"] = t0
        stop_now = {"v": False}
        watcher = None
        if stop_check:
            def _watch():
                while not stop_now["v"]:
                    try:
                        if stop_check():
                            stop_now["v"] = True
                            try:
                                s = getattr(conn, "sock", None)
                                if s is not None:
                                    s.shutdown(socket.SHUT_RDWR)
                            except Exception:
                                pass
                            try:
                                conn.close()
                            except Exception:
                                pass
                            return
                    except Exception:
                        return
                    time.sleep(0.2)
            watcher = threading.Thread(target=_watch, daemon=True)
            watcher.start()
        try:
            conn.request("POST", path, body=data, headers=headers)
            resp = conn.getresponse()
            if hb is not None:
                hb["t"] = time.time()
            if resp.status >= 400:
                detail = resp.read(400).decode("utf-8", "replace")
                raise AiError("HTTP %s：%s" % (resp.status, detail or resp.reason),
                              status=int(resp.status))
            parts, waited = [], False
            while True:
                if stop_check and (stop_now["v"] or stop_check()):
                    raise Stopped("用户按了停止")
                if hb is not None and time.time() - hb["t"] > self.timeout:
                    raise AiError("%d 秒一个字节都没收到（超时）—— 模型的回答还没开始回，"
                                  "或者这条连接已经断了。" % self.timeout, timeout=True)
                if on_wait and not waited:
                    waited = True
                    try:
                        on_wait(round(time.time() - t0, 1))
                    except Exception:
                        pass
                chunk = resp.read(8192)
                if not chunk:
                    break
                if hb is not None:
                    hb["t"] = time.time()
                parts.append(chunk)
            if stop_check and (stop_now["v"] or stop_check()):
                raise Stopped("用户按了停止")
            return b"".join(parts).decode("utf-8", "replace")
        except socket.timeout:
            raise AiError("%d 秒一个字节都没收到（超时）—— 模型的回答还没开始回，"
                          "或者这条连接已经断了。" % self.timeout, timeout=True)
        except Stopped:
            raise
        except (http.client.HTTPException, OSError) as e:
            if stop_now["v"] or (stop_check and stop_check()):
                raise Stopped("用户按了停止")
            raise AiError("没连上 / 断了：%s" % e, retryable=True)
        finally:
            stop_now["v"] = True
            try:
                conn.close()
            except Exception:
                pass

    def _post_stream(self, data, hb=None, on_delta=None, on_reasoning=None):
        u = urllib.parse.urlsplit(self.base_url)
        host, port = u.hostname, (u.port or (443 if u.scheme == "https" else 80))
        path = ((u.path or "").rstrip("/")) + "/chat/completions"
        headers = {"Content-Type": "application/json",
                   "Authorization": "Bearer " + self.api_key,
                   "Content-Length": str(len(data)),
                   "Accept": "text/event-stream",
                   "Connection": "close"}
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = cls(host, port, timeout=max(60.0, float(self.timeout or 0) + 15.0))
        if hb is not None:
            hb["t"] = time.time()
        try:
            conn.request("POST", path, body=data, headers=headers)
            resp = conn.getresponse()
            if hb is not None:
                hb["t"] = time.time()
            if resp.status >= 400:
                detail = resp.read(600).decode("utf-8", "replace")
                raise AiError("HTTP %s：%s" % (resp.status, detail or resp.reason),
                              status=int(resp.status))
            ctype = str(resp.getheader("Content-Type") or "").lower()
            if "event-stream" not in ctype:
                blob = resp.read()
                if hb is not None:
                    hb["t"] = time.time()
                return blob.decode("utf-8", "replace")
            parts, reasons, calls, usage, finish = [], [], {}, {}, ""
            while True:
                line = resp.readline()
                if not line:
                    break
                if hb is not None:
                    hb["t"] = time.time()
                s = line.strip()
                if not s or not s.startswith(b"data:"):
                    continue
                payload = s[5:].strip()
                if payload == b"[DONE]":
                    break
                try:
                    obj = json.loads(payload.decode("utf-8", "replace"))
                except ValueError:
                    continue
                if obj.get("error"):
                    err = obj.get("error")
                    msg = err.get("message") if isinstance(err, dict) else err
                    raise AiError("模型那边报错：%s" % (msg or payload[:200]))
                if obj.get("usage"):
                    usage = obj["usage"]
                for ch in (obj.get("choices") or []):
                    d = ch.get("delta") or {}
                    if d.get("content"):
                        parts.append(d["content"])
                        if on_delta:
                            try:
                                on_delta(d["content"])
                            except Exception:
                                pass
                    rc = d.get("reasoning_content") or d.get("reasoning")
                    if rc:
                        reasons.append(rc)
                        if on_reasoning:
                            try:
                                on_reasoning(rc)
                            except Exception:
                                pass
                    for tc in (d.get("tool_calls") or []):
                        idx = tc.get("index")
                        if idx is None:
                            idx = len(calls)
                        slot = calls.setdefault(idx, {"id": "", "type": "function",
                                                      "function": {"name": "", "arguments": ""}})
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["function"]["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["function"]["arguments"] += fn["arguments"]
                    if ch.get("finish_reason"):
                        finish = ch["finish_reason"]
            text = "".join(parts)
            reasoning = "".join(reasons)
            tc_list = []
            for idx in sorted(calls):
                c = calls[idx]
                if not c["function"]["name"]:
                    continue
                if not c["id"]:
                    c["id"] = "call_%d" % (len(tc_list) + 1)
                tc_list.append(c)
            if not (text or reasoning or tc_list or finish):
                raise AiError("模型没回内容（这一趟一个字节的正文都没收到）")
            msg = {"role": "assistant", "content": text}
            if reasoning:
                msg["reasoning_content"] = reasoning
            if tc_list:
                msg["tool_calls"] = tc_list
            return json.dumps({"choices": [{"message": msg,
                                            "finish_reason": finish or "stop"}],
                               "usage": usage}, ensure_ascii=False)
        except socket.timeout:
            raise AiError("%d 秒一个字节都没收到（超时）—— 模型的回答还没开始回，"
                          "或者这条连接已经断了。" % self.timeout, timeout=True)
        except Stopped:
            raise
        except (http.client.HTTPException, OSError) as e:
            raise AiError("没连上 / 断了：%s" % e, retryable=True)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _normalize(self, obj):
        choices = obj.get("choices") or []
        if not choices:
            err = (obj.get("error") or {}).get("message") if isinstance(obj.get("error"), dict) else obj.get("error")
            raise AiError("模型没回内容：%s" % (err or json.dumps(obj, ensure_ascii=False)[:300]))
        msg = choices[0].get("message") or {}
        text = msg.get("content") or ""
        reasoning = (msg.get("reasoning_content") or msg.get("reasoning")
                     or choices[0].get("reasoning_content") or choices[0].get("reasoning") or "")
        if not isinstance(reasoning, str):
            reasoning = str(reasoning)
        calls = []
        for c in (msg.get("tool_calls") or []):
            fn = c.get("function") or {}
            name = str(fn.get("name") or "").strip()
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except ValueError:
                    raise AiError("工具参数不是 JSON：%s" % str(args)[:200])
            if not isinstance(args, dict):
                args = {"value": args}
            if name:
                calls.append({"id": c.get("id") or ("call_%d" % (len(calls) + 1)),
                              "name": name, "args": args})
        if not calls:
            calls = parse_text_actions(text)
        return {"text": text, "reasoning": reasoning, "tool_calls": calls,
                "usage": obj.get("usage") or {},
                "native": bool(msg.get("tool_calls")), "message": msg, "raw": obj}

_FENCE = re.compile(r"```(?:json|action|tool)?\s*(\{.*?\})\s*```", re.S)

def parse_text_actions(text):
    out = []
    for m in _FENCE.finditer(text or ""):
        got = _action_from(m.group(1))
        if got:
            out.append(got)
    if out:
        return out
    s = (text or "").strip()
    if s.startswith("{") and s.endswith("}"):
        got = _action_from(s)
        if got:
            return [got]
    return []

def _action_from(blob):
    try:
        obj = json.loads(blob)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    name = str(obj.get("tool") or obj.get("name") or "").strip()
    if not name:
        return None
    args = obj.get("args")
    if args is None:
        args = obj.get("arguments")
    if not isinstance(args, dict):
        args = {k: v for k, v in obj.items() if k not in ("tool", "name", "args", "arguments")}
    return {"id": "text_%d" % (abs(hash(name + json.dumps(args, sort_keys=True))) % 100000),
            "name": name, "args": args}
