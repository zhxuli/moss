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
    """连不上 / 回的不是 JSON / 模型没按约定说话 —— 都归这里，消息要能给人看。

    `retryable`（`V-270`）：**这一条是"网络抖了一下"，值得原样重发**（DNS 解析失败、
    连接被拒/被重置、TLS 握手失败…）。真机那次（2026-10-04 21:14~21:18）这台机器的
    DNS 抖了 4 分钟，连着 4 条任务全报 `[Errno 11001] getaddrinfo failed` —— 一句话都没发出去，
    却每条都当"跑失败了"。现在这种错**自己重试两回**，抖一下不至于把你这句任务作废。
    ★ 只有"请求根本没到对面"那类才算 retryable；HTTP 400/401、模型回的不是 JSON
      这些都**不重试** —— 重试它们只会重复烧 token。

    `timeout`（`V-388`）：**"一个字节都没收到"**，和"连不上"分开记。两种都值得重发一次，
      但对用户说的不是一回事：一个是"根本没发出去"，一个是"发出去了、对面一直没声音"。
      11-02 那两次"模型 180 秒还没回完"就是后者（见 `TIMEOUT_RETRIES`）。
    `status`：HTTP 状态码（只有 >=400 才有）—— 网关不认 `stream_options` / `stream`
      时靠它认出来，摘掉参数重发，不打扰用户。
    """

    def __init__(self, msg, retryable=False, timeout=False, status=0):
        super().__init__(msg)
        self.retryable = bool(retryable)
        self.timeout = bool(timeout)
        self.status = int(status or 0)


class Stopped(AiError):
    """用户按了停止（`V-242`：请求**中途**就能停，不用等它说完）。"""


#: `V-270`：连接层抖动的重试次数 / 每次等多久（首发之外再试 2 回）
RETRY_TIMES = 2
RETRY_WAITS = (1.5, 4.0)

#: ★ `V-388`：**"一个字节都没收到"再给一次机会**就够 —— 每多试一次就是又一个 timeout 秒。
#:   为什么值得重试：11-02 03:08 / 03:13 连着两次报"模型 180 秒还没回完"，
#:   而夹在中间那条小请求 7.1 秒就回来了（`user_data/state/temp-session/ai/runs/`）——
#:   典型的"连接被静默丢了"，重发一次就过去了。
TIMEOUT_RETRIES = 1

#: ★ `V-388`：**用流式**（`stream:true`）。这是这次"假超时"的根。
#:   非流式时服务端要等**整段回答生成完**才吐第一个字节：实测一次 16,639 token 的长回答，
#:   这中间线路上**静默 67 秒**（`deepseek-flash` 带 reasoning）。那段时间客户端没有任何证据
#:   能证明"它还活着"，只能拿一道总时长闸硬砍 ⇒ 带思考的模型一超 180 秒就被判死。
#:   流式之后首字节 0.1 秒、之后每个字都在动，这个窗口就不存在了。
#:   网关不吃流式（400）会自动退回非流式，见 `chat()` 里的降级。
STREAM = True


def retry_wait(attempt):
    """第 `attempt` 次重发前等多久。界面那行"X 秒后重发"也用它 —— 别各算各的。"""
    n = max(int(attempt or 1) - 1, 0)
    return RETRY_WAITS[min(n, len(RETRY_WAITS) - 1)]


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
    def chat(self, messages, tools=None, temperature=None, stop_check=None, on_wait=None,
             on_retry=None, on_delta=None, on_reasoning=None):
        """发一次请求，回统一形状。

        ★★ `V-242` 真机踩到的：**按了停止停不下来**。原因就是这一句 `urlopen(...).read()`
          是**整段阻塞**的（超时 180 秒），而 loop 只在"每一轮开头"看停止标志
          ⇒ 用户看到的正是"它说下一轮才会停，然后就那么卡着，时间一直在走"。
        ★ 改法：不用 `urllib` 一把梭，改用 `http.client` **一小块一小块读**
          （socket 每 2 秒没数据就先醒一下），每块之间问一次"要不要停"。
          要停就**关掉连接**、抛 `Stopped` —— 停在 1~2 秒内，不再等满 180 秒。
        ★ `V-270`：**连接层的抖动自己重试**（DNS 解析失败/连接被重置…见 `AiError.retryable`）。
          重试之前先问一次"要不要停"；等待也是**一小段一小段睡**，按了停止立刻走。
          `on_retry(第几次, 一共几次, 原错误)` 给上层一个说话的机会（界面上会打一行"重试"）。
        ★ `V-388`：**默认走流式**（`STREAM`），并且"一个字节都没收到"也算可重试（`TIMEOUT_RETRIES`）。
          另外加了两条**无声降级**：网关嫌 `stream_options` / `stream` 不认识（HTTP 400）就摘掉
          再发，不让"换了个网关"变成"AI 用不了"。
        ★ `V-389`：`on_delta(增量正文)` / `on_reasoning(增量思考)` 现在 loop **真的接了**
          （以前只留了口子没人用 ⇒ 你看到的是"等全部收完才一次性出现"）。
          思考阶段可能长达一分钟且**正文一个字都没有**，所以两路分开报，界面才不会干等着。
        """
        body = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            # 让模型"该调工具就调"（有的网关认这个，认不得也无害）
            body["tool_choice"] = "auto"
        if temperature is not None:
            body["temperature"] = temperature
        want_stream = bool(STREAM)
        want_usage = bool(STREAM)          # 流式下顺手要一份 usage（不然 token 账只能靠估）
        net_fails = 0                      # 没连上（一个字节都没发出去）
        timed_out = 0                      # 发出去了，但一个字节都没收到
        fails = 0                          # 总共重发了几次（只用来算"等多久"和给界面看）
        raw = ""
        while True:
            # 每次重发都**按现在的开关重建**那两个字段 —— 降级之后必须真的从请求体里消失
            # （只把开关设 False 是不够的：上一轮写进去的键还在，网关照样 400）。
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
                # ① 网关不认某个可选参数 ⇒ 摘掉再来，**不算失败**（对用户无感）
                if e.status == 400 and body.get("stream_options"):
                    want_usage = False
                    continue
                if e.status == 400 and body.get("stream"):
                    want_stream = False        # 这家连流式都不吃：退回老路子
                    continue
                # ② 没连上 / 一个字节都没收到 ⇒ 各给有限的几次
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
                    except Exception:                                 # noqa: BLE001
                        pass
                slept = 0.0
                while slept < wait:                                   # 分段睡，能立刻停
                    if stop_check and stop_check():
                        raise Stopped("用户按了停止")
                    time.sleep(0.2)
                    slept += 0.2
        # ★ 归一化只在这一处（`V-388`：流式那条路交回来的也是"一段 JSON 文本"）
        try:
            obj = json.loads(raw)
        except ValueError:
            raise AiError("回的不是 JSON（前 300 字）：%s" % str(raw)[:300])
        return self._normalize(obj)

    def _post_watched(self, data, stop_check=None, on_wait=None, on_delta=None,
                      on_reasoning=None, stream=True):
        """把请求丢进工作线程，**主线程 0.1 秒一格地等** —— 这样"停止"立刻生效。

        ★ `V-245` 的教训：一开始我想"在同一个线程里分块读、中间查停止键"，还试过
          "另起线程 `close()` / `shutdown()` 去掐断阻塞的 `recv`" —— **在 Windows 上都不灵**
          （实测：掐了照样等满服务器那段睡眠；`socket.SocketIO` 还会因为一次超时把整个
          socket 报废，抛 `cannot read from timed out object`，真机就是栽在这句上）。
          现在这条路不跟 socket 语义较劲：**请求归工作线程，等不等归主线程**。
          代价：按下停止后，那个请求会**在后台自己结束**（daemon 线程，不拖住进程）。

        ★ `V-388`：**判死的依据改成"最后一个字节是多久以前"**（`hb`），不是"从发起算多久"。
          计时器叫 `hb`（heartbeat），由 `_post_stream` / `_post` 每收到一块就刷新一次。
          原来那道闸是"从 t0 算满 180 秒"，可在非流式下**线路上本来一个字节都没有**，
          等于给每一次长回答都设了死刑（`deepseek-flash` 写一个大文件能吐 1.6 万 token，
          实测 67 秒；带思考的更久）。现在只有**真的一个字节都不来**才判死。

        ★ 返回值**还是"一段原始 JSON 文本"**（`V-388` 特意没改这个契约）：流式那条路会把
          收到的块拼成一个"非流式回包"再 `json.dumps` 出去。这样 `chat()` 只有一处
          `json.loads` + `_normalize`，而外部/探针塞进来的假 `_post_watched` 也照旧能用。
        """
        box = {}
        hb = {"t": time.time()}

        def work():
            try:
                box["got"] = (self._post_stream(data, hb=hb, on_delta=on_delta,
                                                on_reasoning=on_reasoning) if stream
                              else self._post(data, hb=hb))
            except BaseException as e:                                    # noqa: BLE001
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
                except Exception:                                         # noqa: BLE001
                    pass
        if "err" in box:
            raise box["err"]
        return box.get("got")

    def _post(self, data, stop_check=None, on_wait=None, hb=None):
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

        ★ `V-388`：这条路现在是**兜底**（网关不吃流式时才走）。口径也跟着改了两处：
          ① 每收到一块就刷 `hb`（心跳），判死只看"多久没字节"，不看总时长；
          ② `socket.timeout` 标成 `timeout=True`（可重发一次），不再混进"没连上"。
        """
        u = urllib.parse.urlsplit(self.base_url)
        host, port = u.hostname, (u.port or (443 if u.scheme == "https" else 80))
        path = ((u.path or "").rstrip("/")) + "/chat/completions"
        headers = {"Content-Type": "application/json",
                   "Authorization": "Bearer " + self.api_key,
                   "Content-Length": str(len(data)),
                   "Accept": "application/json",
                   "Connection": "close"}          # 同上（`V-388`）：一次一条连接，别留 TIME_WAIT
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        # socket 超时比"判死的那个空转阈值"再宽一点：谁先醒谁负责报，但报的都是同一件事
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
                    except Exception:                                # noqa: BLE001
                        pass
                chunk = resp.read(8192)
                if not chunk:
                    break
                if hb is not None:
                    hb["t"] = time.time()
                parts.append(chunk)
            # ★ `V-245`：连接被"盯停止"的线程关掉时，读**可能**只是老老实实返回 EOF（不是抛错）
            #   —— 那样我们会拿到半截/空的 body，再当成"回的不是 JSON"。所以收尾前再认一次停止。
            if stop_check and (stop_now["v"] or stop_check()):
                raise Stopped("用户按了停止")
            return b"".join(parts).decode("utf-8", "replace")
        except socket.timeout:
            raise AiError("%d 秒一个字节都没收到（超时）—— 模型的回答还没开始回，"
                          "或者这条连接已经断了。" % self.timeout, timeout=True)
        except Stopped:
            raise
        except (http.client.HTTPException, OSError) as e:
            # ★ 连接被"盯停止"的线程掐掉时，这里抛的就是 OSError —— 认出它，报"用户按了停止"
            if stop_now["v"] or (stop_check and stop_check()):
                raise Stopped("用户按了停止")
            # ★ `V-270`：走到这儿说明**请求根本没到对面**（DNS 解析失败 / 连接被拒 / 被重置 /
            #   TLS 握手失败…）—— 这类是"网络抖了一下"，值得原样重发（`chat()` 会重试两回）。
            raise AiError("没连上 / 断了：%s" % e, retryable=True)
        finally:
            stop_now["v"] = True                     # 叫停 watcher
            try:
                conn.close()
            except Exception:                                            # noqa: BLE001
                pass

    def _post_stream(self, data, hb=None, on_delta=None, on_reasoning=None):
        """POST 一次，**按 SSE 一块一块收**（`V-388`）。

        为什么这是"假超时"的根：非流式时服务端要等**整段回答生成完**才吐第一个字节。
        实测（同一家 provider、同一个 key）一次 16,639 token 的长回答，这中间线路上
        **静默 67 秒**；改成流式后**首字节 0.1 秒**、20,804 个数据块、85.5 秒正常收尾。
        换句话说：非流式那 67 秒里，客户端没有任何证据能证明对面还活着，只能拿一道总时长闸
        硬砍 —— 而带思考的模型很容易超过 180 秒。

        解析只做三件事（其余一律交给 `_normalize`，归一化只留一份）：
          ① `delta.content` 拼正文；② `delta.reasoning_content` 拼思考过程；
          ③ 按 `index` 把 `delta.tool_calls` 的 `function.arguments` **碎片**拼回完整 JSON。
        最后拼成一个"非流式回包"的形状。网关不吐 SSE（直接给整包 JSON）时自动走整包那条。
        """
        u = urllib.parse.urlsplit(self.base_url)
        host, port = u.hostname, (u.port or (443 if u.scheme == "https" else 80))
        path = ((u.path or "").rstrip("/")) + "/chat/completions"
        headers = {"Content-Type": "application/json",
                   "Authorization": "Bearer " + self.api_key,
                   "Content-Length": str(len(data)),
                   "Accept": "text/event-stream",
                   # ★ `V-388`：**显式要求关连接**。我们是"一次请求一条连接"，本来也不用 keep-alive；
                   #   而流到 `[DONE]` 那一下通常是**客户端先关**，在 Windows 上会让本地端口留在
                   #   TIME_WAIT，下一次连接撞上同一个临时端口就直接 `WinError 10048`
                   #   （本地假网关实测：连第二条就"地址已被使用"）。让服务端先关，TIME_WAIT 落在对面。
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
                # 网关把流式吃掉了：直接吐整包 JSON —— 原样当"一段 JSON 文本"交回去
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
                    continue                     # 空行 / `: ping` 心跳 / `event:` 之类
                payload = s[5:].strip()
                if payload == b"[DONE]":
                    break
                try:
                    obj = json.loads(payload.decode("utf-8", "replace"))
                except ValueError:
                    continue                     # 半截/非 JSON 的块：跳过，下一块照收
                if obj.get("error"):
                    err = obj.get("error")
                    msg = err.get("message") if isinstance(err, dict) else err
                    raise AiError("模型那边报错：%s" % (msg or payload[:200]))
                if obj.get("usage"):
                    usage = obj["usage"]         # `stream_options.include_usage` 的收尾块
                for ch in (obj.get("choices") or []):
                    d = ch.get("delta") or {}
                    if d.get("content"):
                        parts.append(d["content"])
                        if on_delta:
                            try:
                                on_delta(d["content"])
                            except Exception:                    # noqa: BLE001
                                pass
                    rc = d.get("reasoning_content") or d.get("reasoning")
                    if rc:
                        reasons.append(rc)
                        if on_reasoning:
                            try:
                                on_reasoning(rc)
                            except Exception:                    # noqa: BLE001
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
            # ★ 交回去的是**一段 JSON 文本**（不是 dict）：`chat()` 那边只有一处
            #   `json.loads` + `_normalize`，探针塞进来的假 `_post_watched` 也照旧能用。
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
            except Exception:                                            # noqa: BLE001
                pass

    def _normalize(self, obj):
        choices = obj.get("choices") or []
        if not choices:
            err = (obj.get("error") or {}).get("message") if isinstance(obj.get("error"), dict) else obj.get("error")
            raise AiError("模型没回内容：%s" % (err or json.dumps(obj, ensure_ascii=False)[:300]))
        msg = choices[0].get("message") or {}
        text = msg.get("content") or ""
        # ★ 思考过程：DeepSeek Reasoner 等 OpenAI 兼容网关把思维链放在
        #   `message.reasoning_content`（也有网关叫 `reasoning`）。这里只收集，不参与工具循环。
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
