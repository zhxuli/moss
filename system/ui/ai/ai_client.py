# -*- coding: utf-8 -*-
"""跟模型说话那 20 行（`V-230`）：**OpenAI 兼容的 `/chat/completions`，只用标准库**。

为什么不引框架（LangChain / litellm / Aider 本体）
--------------------------------------------------
自带运行时是**隔离**的（`sys.path` 连脚本目录都不带）、要能离线、要随 `moss.exe` 一起发。
引一个框架 = 拖一串依赖进来，而我们要的东西其实只有"发一个 JSON、收回一段 JSON"。
（`--ai-test` 那条路已经证明 `urllib` + 流式就够用。）

★ `tools`（function calling）是**首选**；但有些模型/网关不吃它，所以还留了
  一条**文本协议兜底**：模型在正文里回一个 ```json {"tool": "...", "args": {...}}``` 块，
  这里把它认成一次工具调用（`parse_text_actions`）。两条路对 loop 是同一个形状。
"""
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
    """连不上 / 回的不是 JSON / 模型没按约定说话 —— 都归这里，消息要能给人看。"""


class Stopped(AiError):
    """用户按了停止（`V-242`：请求**中途**就能停，不用等它说完）。"""


def from_env(need=True):
    """从宿主注入的 `MOSS_AI_*` 拿一套参数（契约里就是这么给的，**别去读 config.toml**）。"""
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
    """一个模型就一个 client。`chat()` 回统一形状：`{text, tool_calls, usage, raw}`。"""

    def __init__(self, base_url, api_key, model, timeout=180):
        self.base_url = str(base_url or "").rstrip("/")
        self.api_key = str(api_key or "")
        self.model = str(model or "")
        self.timeout = timeout

    @classmethod
    def from_env(cls, model=None, timeout=180):
        cfg = from_env()
        return cls(cfg["base_url"], cfg["api_key"], model or cfg["model"], timeout=timeout)

    # ---------------------------------------------------------------- 发一次请求
    def chat(self, messages, tools=None, temperature=None, stop_check=None, on_wait=None):
        """发一次请求，回统一形状。

        ★★ `V-242` 真机踩到的：**按了停止停不下来**。原因就是这一句 `urlopen(...).read()`
          是**整段阻塞**的（超时 180 秒），而 loop 只在"每一轮开头"看停止标志
          ⇒ 用户看到的正是"它说下一轮才会停，然后就那么卡着，时间一直在走"。
        ★ 改法：不用 `urllib` 一把梭，改用 `http.client` **一小块一小块读**
          （socket 每 2 秒没数据就先醒一下），每块之间问一次"要不要停"。
          要停就**关掉连接**、抛 `Stopped` —— 停在 1~2 秒内，不再等满 180 秒。
        """
        body = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            # 让模型"该调工具就调"（有的网关认这个，认不得也无害）
            body["tool_choice"] = "auto"
        if temperature is not None:
            body["temperature"] = temperature
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        raw = self._post_watched(data, stop_check=stop_check, on_wait=on_wait)
        try:
            obj = json.loads(raw)
        except ValueError:
            raise AiError("回的不是 JSON（前 300 字）：%s" % raw[:300])
        return self._normalize(obj)

    def _post_watched(self, data, stop_check=None, on_wait=None):
        """把请求丢进工作线程，**主线程 0.2 秒一格地等** —— 这样"停止"立刻生效。

        ★ `V-245` 的教训：一开始我想"在同一个线程里分块读、中间查停止键"，还试过
          "另起线程 `close()` / `shutdown()` 去掐断阻塞的 `recv`" —— **在 Windows 上都不灵**
          （实测：掐了照样等满服务器那段睡眠；`socket.SocketIO` 还会因为一次超时把整个
          socket 报废，抛 `cannot read from timed out object`，真机就是栽在这句上）。
          现在这条路不跟 socket 语义较劲：**请求归工作线程，等不等归主线程**。
          代价：按下停止后，那个请求会**在后台自己结束**（daemon 线程，不拖住进程）。
        """
        box = {}
        t0 = time.time()

        def work():
            try:
                box["raw"] = self._post(data)
            except BaseException as e:                                    # noqa: BLE001
                box["err"] = e

        th = threading.Thread(target=work, daemon=True)
        th.start()
        while True:
            th.join(0.2)
            if not th.is_alive():
                break
            if stop_check and stop_check():
                raise Stopped("用户按了停止")
            if time.time() - t0 > self.timeout:
                raise AiError("模型 %d 秒还没回完（超时）—— 可能是网络卡了，或者这次问得太长。"
                              % self.timeout)
            if on_wait:
                try:
                    on_wait(round(time.time() - t0, 1))
                except Exception:                                         # noqa: BLE001
                    pass
        if "err" in box:
            raise box["err"]
        return box.get("raw") or ""

    def _post(self, data, stop_check=None, on_wait=None):
        """POST 一次。**能中途停**（另起一个线程盯停止键，要停就把连接关掉）。

        ★★ `V-245` 修的是 `V-242` 引入的一个更阴的 bug：上一版我给 socket 设 2 秒超时、
          `resp.read()` 超时就 `continue` 再读 —— 听着合理，其实**被 Python 破了**：
          `http.client` 底下那个 reader 是 `socket.SocketIO`，它**一旦超时过就置
          `_timeout_occurred`，之后任何读都直接抛 `OSError: cannot read from timed out object`**。
          于是"模型正常花 3 秒才回话"也会变成 `没连上 / 断了：cannot read from timed out object`
          （真机就是这么报的）。
        ★ 现在的做法：socket 超时回到 **60 秒**（够慢模型用了，正经常规值），
          **停止用一个 daemon 线程盯着** —— 每 0.2 秒问一次 `stop_check()`，要停就 `conn.close()`，
          阻塞中的 `read()` 立刻抛错 ⇒ 我们在下面认出"这是用户按的停止"，抛 `Stopped`。
          既**停得快**（≤0.2 秒），又**不污染 socket**。
        """
        u = urllib.parse.urlsplit(self.base_url)
        host, port = u.hostname, (u.port or (443 if u.scheme == "https" else 80))
        path = ((u.path or "").rstrip("/")) + "/chat/completions"
        headers = {"Content-Type": "application/json",
                   "Authorization": "Bearer " + self.api_key,
                   "Content-Length": str(len(data)),
                   "Accept": "application/json"}
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        conn = cls(host, port, timeout=max(30.0, float(self.timeout or 0)))
        t0 = time.time()
        stop_now = {"v": False}
        watcher = None
        if stop_check:
            def _watch():
                while not stop_now["v"]:
                    try:
                        if stop_check():
                            stop_now["v"] = True
                            # ★ `V-245`：**光 close() 叫不醒阻塞中的 recv**（Windows 上尤其如此，
                            #   实测还是要等服务器把数据发完）。`shutdown()` 会发 FIN/RST，
                            #   阻塞的读立刻返回 ⇒ 停止才是真的"立刻"。
                            try:
                                s = getattr(conn, "sock", None)
                                if s is not None:
                                    s.shutdown(socket.SHUT_RDWR)
                            except Exception:                     # noqa: BLE001
                                pass
                            try:
                                conn.close()
                            except Exception:                     # noqa: BLE001
                                pass
                            return
                    except Exception:                             # noqa: BLE001
                        return
                    time.sleep(0.2)
            watcher = threading.Thread(target=_watch, daemon=True)
            watcher.start()
        try:
            conn.request("POST", path, body=data, headers=headers)
            resp = conn.getresponse()
            if resp.status >= 400:
                detail = resp.read(400).decode("utf-8", "replace")
                raise AiError("HTTP %s：%s" % (resp.status, detail or resp.reason))
            parts, waited = [], False
            while True:
                if stop_check and (stop_now["v"] or stop_check()):
                    raise Stopped("用户按了停止")
                if time.time() - t0 > self.timeout:
                    raise AiError("模型 %d 秒还没回完（超时）—— 可能是网络卡了，或者这次问得太长。"
                                  % self.timeout)
                if on_wait and not waited:
                    waited = True
                    try:
                        on_wait(round(time.time() - t0, 1))
                    except Exception:                                # noqa: BLE001
                        pass
                chunk = resp.read(8192)
                if not chunk:
                    break
                parts.append(chunk)
            # ★ `V-245`：连接被"盯停止"的线程关掉时，读**可能**只是老老实实返回 EOF（不是抛错）
            #   —— 那样我们会拿到半截/空的 body，再当成"回的不是 JSON"。所以收尾前再认一次停止。
            if stop_check and (stop_now["v"] or stop_check()):
                raise Stopped("用户按了停止")
            return b"".join(parts).decode("utf-8", "replace")
        except socket.timeout:
            raise AiError("连接等太久了（%s 秒没有任何数据）—— 网络或服务端卡住了。" % conn.timeout)
        except Stopped:
            raise
        except (http.client.HTTPException, OSError) as e:
            # ★ 连接被"盯停止"的线程掐掉时，这里抛的就是 OSError —— 认出它，报"用户按了停止"
            if stop_now["v"] or (stop_check and stop_check()):
                raise Stopped("用户按了停止")
            raise AiError("没连上 / 断了：%s" % e)
        finally:
            stop_now["v"] = True                     # 叫停 watcher
            try:
                conn.close()
            except Exception:                                            # noqa: BLE001
                pass

    def _normalize(self, obj):
        choices = obj.get("choices") or []
        if not choices:
            err = (obj.get("error") or {}).get("message") if isinstance(obj.get("error"), dict) else obj.get("error")
            raise AiError("模型没回内容：%s" % (err or json.dumps(obj, ensure_ascii=False)[:300]))
        msg = choices[0].get("message") or {}
        text = msg.get("content") or ""
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
        return {"text": text, "tool_calls": calls, "usage": obj.get("usage") or {},
                "native": bool(msg.get("tool_calls")), "message": msg, "raw": obj}


#: 文本协议兜底：```json {"tool": "...", "args": {...}}```（也认 ```action / 裸 JSON 对象）
_FENCE = re.compile(r"```(?:json|action|tool)?\s*(\{.*?\})\s*```", re.S)


def parse_text_actions(text):
    """从正文里抠出工具调用（模型不吃 `tools` 参数时的兜底路）。"""
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
