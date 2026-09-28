# -*- coding: utf-8 -*-
"""
dsh_bridge.py — 本机桥守护进程（DeepSeek Harness 远程访问的"本机半边"）

职责：
  1. 保持一条到 zeen.xin 服务器（或本地 localhost:8633）的 WebSocket 长连接
     （本机主动连出，NAT 穿透，断线自动重连）。
  2. 桥的身份 = zeen.xin 登录 token（用户自己粘贴进配置）；服务器用现有账号
     系统验证，按账号登记。服务器零新增秘密。
  3. 本机密码门：密码 scrypt 加盐哈希只存本机；无本机会话票据的请求 → 劫持
     返回"设置页"（密码框）。密码验证只在本机执行，通过后本机签发会话票据。
  4. 逐请求验票：每个转发请求必须携带本机签发的 dsh_session 票据。
  5. 请求转发到 127.0.0.1:3080（DSH），响应（含事件流、ZIP）分块流式回传。

依赖：aiohttp + httpx + websockets —— **都在 moss 自带运行时里**
（`system/runtimes/python/3.12/Lib/site-packages`），用户不需要自己装。
文件顶部那段「缺依赖就用旧项目 ZeEn venv 重新执行自己」的自举逻辑保留着，
但在 moss 下会被跳过（见那里的注释）。

用法（脚本名照抄旧文，命令名换成 moss）：
  moss :dsh                      # 前台运行。没配好会自动打开"设置页"，
                                 # 在浏览器里选服务器(localhost/zeen.xin)、填 token、设密码
  moss :dsh --no-browser         # 同上，但不自动开浏览器
                                 # ★ Ctrl+C 会**连同 DSH 本体(3080)一起干净退出**
  moss :dsh --set-token          # 更换 zeen token（账号变更/过期后）
  moss :dsh --set-password       # 更换本机密码
  moss :dsh --status             # 查看配置摘要
  moss :dsh --daemon             # 转后台守护运行（无窗口，日志写 dsh.log）
                                 # ★ 每次启动都会先结束 3080 上的旧 DSH 再重拉 ——
                                 #   因为 DSH 的会话令牌每次启动随机生成、不持久化，
                                 #   不是本桥拉起来的就永远换不到 cookie（隧道会 401）。
                                 #   代价：本地 DSH 网页闪断几秒，监护 5 秒内拉回来。

协议（与 AppVirtual_file/dsh.py 配对，JSON 文本消息）：
  桥 -> VPS: {"type":"hello","role":"bridge","token":"<zeen token>"}
  VPS -> 桥: {"type":"verify_password","id":...,"password":...}
  桥 -> VPS: {"type":"verify_password_result","id":...,"ok":true,"ticket":...,"ttl":...}
  VPS -> 桥: {"type":"tunnel_http","id":...,"method":...,"path":...,"headers":{...}}
             {"type":"tunnel_http_body","id":...,"dataBase64":...,"final":true}
  桥 -> VPS: {"type":"tunnel_http_start","id":...,"status":...,"headers":{...}}
             {"type":"tunnel_http_chunk","id":...,"dataBase64":...}
             {"type":"tunnel_http_end","id":...}
             {"type":"tunnel_http_error","id":...,"message":...}
  VPS -> 桥: {"type":"open_ws","id":...,"path":...,"headers":{...}}   （中继 WebSocket）
  桥 -> VPS: {"type":"ws_open_ack","id":...} / {"type":"ws_open_error","id":...,"message":...}
  双向:      {"type":"ws_frame","id":...,"data":...|"dataBase64":...} / {"type":"ws_close","id":...}
  任意:      {"type":"ping"} -> {"type":"pong"}
"""

# ---- 依赖自举：若当前解释器缺 aiohttp/httpx/websockets，自动用 ZeEn venv 重执行 ----
# （moss 宿主下这一段直接跳过，见下面 except 里的第一句）
# ★ import sys 必须放在 try **之前**：下面 except 块第一句就用 sys.path，
#   而旧代码把它写在 try 的最后一行 —— 一旦缺的是 aiohttp/httpx/websockets，
#   sys 根本还没导入，except 里立刻 NameError（旧项目里就有的坑，实测复现：
#   用缺依赖的解释器跑 → NameError: name 'sys' is not defined，而不是那句友好提示）。
import sys

try:
    import aiohttp  # noqa: F401
    import httpx    # noqa: F401
    import websockets  # noqa: F401
except ImportError:
    import os
    import subprocess
    # ★ moss 宿主判断：moss 跑包用的是**自带运行时**（system/runtimes/python/3.12/，
    #   里面 aiohttp / httpx / websockets 都装好了），并且按契约一定会注入
    #   MOSS_PLUGIN_DATA_DIR。所以只要这个变量在，就说明跑在 moss 里 —— 此时
    #   **绝不能**再去用旧项目的 ZeEn venv 重新执行自己：那是另一个解释器，会把
    #   MOSS_* 环境契约丢掉，还可能一直套娃下去。直接把缺依赖的 ImportError 抛出去，
    #   报错里会写清缺的是哪个模块。老 pa 没有这个变量，下面的老逻辑照旧生效。
    if os.environ.get("MOSS_PLUGIN_DATA_DIR"):
        raise
    # pa 用 exec(open(...).read()) 方式执行，__file__ 不可用。
    # pa 执行前会 sys.path.insert(0, 插件目录)，用它定位本工具（改文件夹名也不会失效）。
    _DIR = ""
    for _p in sys.path:
        if _p and os.path.isdir(_p) and os.path.exists(os.path.join(_p, "main.py")):
            _DIR = _p
            break
    if not _DIR:
        # 最后兜底：以**脚本自身所在目录**为准（moss 用 runpy.run_path 执行，
        # __file__ 一定可用；这段本来在旧宿主里也到不了，因为 pa 会先把插件目录
        # 塞进 sys.path）。原来写死的那个旧项目路径已随迁移作废，不能再指回去。
        _DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    _THIS = os.path.join(_DIR, "main.py")
    # 换哪个解释器来跑（三级，`P-15`）：
    #   ① 环境变量 DSH_PYTHON —— 想指定就用它，这是最明确的做法
    #   ② 当前解释器同目录的 python.exe（moss 自带运行时就在这，依赖是齐的）
    #   ③ 老项目的 ZeEn venv —— **仅当它真的存在**才用（旧机器上的兜底；
    #      迁移前这里写死的就是它，现在降级成最后一级，不再是无条件依赖）
    # 三级都不行就报清楚缺什么、该怎么办，而不是甩一个 NameError/FileNotFound。
    _CANDIDATES = []
    _env_py = os.environ.get("DSH_PYTHON")
    if _env_py:
        _CANDIDATES.append(("环境变量 DSH_PYTHON", _env_py))
    _CANDIDATES.append(("当前解释器同目录",
                        os.path.join(os.path.dirname(os.path.abspath(sys.executable or "")),
                                     "python.exe")))
    _CANDIDATES.append(("老项目的 ZeEn venv（兜底）",
                        r"D:\python\wwwroot\ZeEn\venv\Scripts\python.exe"))
    _VENV_PY = ""
    for _why, _p in _CANDIDATES:
        if _p and os.path.isfile(_p) and os.path.abspath(_p) != os.path.abspath(sys.executable or ""):
            _VENV_PY = _p
            print("检测到当前解释器缺依赖(aiohttp/httpx/websockets)，改用【%s】的解释器: %s"
                  % (_why, _p))
            break
    if not _VENV_PY:
        print("缺少依赖(aiohttp/httpx/websockets)，且没有可换的解释器。")
        print("  办法：设环境变量 DSH_PYTHON 指向一个装了这些库的 python.exe，")
        print("        或用 moss 自带运行时跑（moss :dsh 本来就是这么跑的）。")
        sys.exit(1)
    sys.exit(subprocess.call([_VENV_PY, _THIS] + sys.argv[1:]))

import argparse
import asyncio
import atexit
import base64
import getpass
import glob
import hashlib
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import webbrowser
from pathlib import Path

import httpx
import websockets
from aiohttp import web

LOG = logging.getLogger("dsh_bridge")

# 本地设置向导端口（仅本机访问）
SETUP_PORT = 8788

# ---- 数据目录：宿主 moss 注入的插件专属目录 (user_data/state/<包id>)；
#      PA_ 是老 pa 的变量，保留兜底；都没有时（独立运行/调试）退回脚本目录 ----
DATA_DIR = os.environ.get("MOSS_PLUGIN_DATA_DIR") or os.environ.get("PA_PLUGIN_DATA_DIR") or (
    os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd())

CONFIG_PATH = Path(DATA_DIR) / "dsh_bridge.json"

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64

DEFAULT_TARGET = "http://127.0.0.1:3080"

# ---- DSH 浏览器会话认证（进程令牌 → 签名 cookie）----
# DSH 的 Host API 与 WebSocket stream 都要求同一个浏览器会话：裸 GET /* 一律
# 401。令牌由 DSH 自己每次进程启动随机生成、绝不持久化，并带 ?token= 打印到
# stdout —— 而桥把 DSH 的 stdout 重定向到 dsh3080.log，所以令牌能从那份日志里
# 捡到，无需用户手动复制。取到令牌后按 DSH 的规则交换 cookie：
#   GET /?token=<令牌>  →  303 + Set-Cookie: dsh-auth-<sha256(host:port)>=...
# 该 cookie 绑定 authority（hostname+port），与桥写死的 Host 一致；之后每次转发
# 带上它即可。签名密钥在 $DSH_HOME/.credentials.yaml 里持久，所以 cookie 跨 DSH
# 重启仍有效，但令牌每次启动都变，故启动后重取一次。
# 只捕获 token= 后面的值本身（43 字符 base64url）。务必不要把整条 URL 捕获进来：
# DSH 只在 token 参数"恰好一个且完全匹配"时才交换，值多一个字就是 401。
DSH_TOKEN_RE = re.compile(r"dsh web:\s*http://\S*[?&]token=([A-Za-z0-9_-]+)")
DSH_LOG_TAIL_BYTES = 262144   # 只扫日志尾部：够覆盖最近一次启动，且不随日志增长变慢

# 本地设置向导端口（仅本机访问）
SETUP_PORT = 8788

CONFIG_PATH = Path(DATA_DIR) / "dsh_bridge.json"


# ---- 本机文件直传（不经 DSH）----
# 为什么放在桥这一层：DSH 原生的「打开」只在**桌面**上有效（服务端调本机
# explorer / 默认程序），手机经 zeen.xin 访问时点了什么也看不到。要补「非桌面」
# 的那一半，最合适的位置就是桥 —— 它本来就跑在工作电脑上、天然有读本机文件的
# 权限，也天然在请求路径上（服务端会剥掉 /dsh-ui 前缀，浏览器请求
# /dsh-ui/file.fetch 到这里正好是 /file.fetch），因此完全不需要 DSH 参与，
# 也不必给 DSH 装插件。
#
# 鉴权：**完全交给桥已有的两道**——zeen 登录 token + 二级密码票据（见
# on_tunnel_http，未持票的请求在更早一步就被换成设置页）。这里不再另加目录
# 白名单：能连上这台机器的人本来就能让 DSH 执行任意命令，限制可读目录挡不住
# 这种能力，只会挡住自己。需要时可用 cfg["file_roots"] 启用限定（见下）。
FILE_FETCH_PATH = "/file.fetch"

# 显示页：手机上点开是排版好的页面（图片/文本直接看，右上角可下载），
# 而不是 raw 的 JSON 或二进制。查看器模板与工作区里那份同源，便于你改样式。
FILE_VIEW_PATH = "/file.view"
FILE_VIEWER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file_viewer.html")
# 显示页要用的前端资源目录（viewer/*.js|css）。file_viewer.html 里那些
# file.fetch?path= 链接用的是占位符 __VIEWER_DIR__，在这里替换成**本包真实目录**
# 的 URL 编码形式 —— 迁移前它们是写死的旧项目绝对路径，包一搬就全 404。
FILE_VIEWER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")

# 可直接内联展示的文本类扩展名（超出大小上限则只给下载按钮）。
VIEW_TEXT_EXT = {
    "txt", "md", "markdown", "json", "csv", "log", "xml", "yml", "yaml",
    "html", "htm", "css", "js", "mjs", "ts", "tsx", "jsx", "py", "sh", "bat",
    "ps1", "ini", "conf", "toml", "sql", "gitignore", "env",
}
# 图片扩展名（内联显示）。
VIEW_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico", "avif"}
# 内联上限：文本 1MB、图片 12MB；超过就只给下载按钮，避免手机加载卡死。
VIEW_TEXT_LIMIT = 1 * 1024 * 1024
VIEW_IMAGE_LIMIT = 12 * 1024 * 1024

# 本机文件直传的分块大小。
# 隧道对面（zeen 上的 uvicorn，见 ZeEn/main.py 的 uvicorn.run）单条 WebSocket 消息
# 默认上限 ws_max_size = 16 MiB；而直传要把内容 base64（×4/3）塞进一条
# tunnel_http_chunk，所以整包发的话超过约 12 MiB 的文件就会被对面以
# 1009 (message too big) 断开连接。4 MiB 一块 → 单条消息约 5.3 MiB，留足余量。
FILE_CHUNK = 4 * 1024 * 1024

# 方便起见按扩展名给内容类型；认不出交给 mimetypes，再不行 octet-stream。
FILE_MIME = {
    "pdf": "application/pdf",
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
    "webp": "image/webp", "svg": "image/svg+xml", "bmp": "image/bmp", "ico": "image/x-icon",
    "txt": "text/plain; charset=utf-8", "md": "text/plain; charset=utf-8",
    "json": "application/json; charset=utf-8", "csv": "text/csv; charset=utf-8",
    "xml": "application/xml; charset=utf-8", "yml": "text/yaml; charset=utf-8",
    "yaml": "text/yaml; charset=utf-8", "log": "text/plain; charset=utf-8",
    "html": "text/html; charset=utf-8", "css": "text/css; charset=utf-8",
    "js": "text/javascript; charset=utf-8", "ts": "text/plain; charset=utf-8",
    "py": "text/plain; charset=utf-8", "sh": "text/plain; charset=utf-8",
    "zip": "application/zip", "gz": "application/gzip", "tar": "application/x-tar",
    "mp4": "video/mp4", "webm": "video/webm",
    "mp3": "audio/mpeg", "wav": "audio/wav", "ogg": "audio/ogg", "m4a": "audio/mp4",
}

# 浏览器能直接渲染的类型走 inline（点开即预览），其余强制下载。
FILE_INLINE_EXT = {
    "pdf", "png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico",
    "mp4", "webm", "mp3", "wav", "ogg", "m4a",
    # html 也内联：便于在手机上直接打开本机生成的页面（诊断页、报表等）。
    "html", "htm",
}


def file_roots() -> list:
    """取配置里可选的目录白名单（已规范化）。未配置 = 不限制。"""
    raw = load_config().get("file_roots")
    if not isinstance(raw, list):
        return []
    roots = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            continue
        try:
            roots.append(os.path.realpath(item))
        except Exception:
            continue
    return roots


def path_within(child: str, root: str) -> bool:
    """child 是否位于 root 之内（两者都应已规范化）。"""
    if child == root:
        return True
    return child.startswith(root.rstrip("\\/") + os.sep)


def resolve_file_request(raw_path: str):
    """把请求里的路径解析成本机绝对路径；不是可读的常规文件就返回 None。

    默认**不限制目录**：只要能通过桥的鉴权（zeen 登录 + 二级密码票据），就能取
    本机文件 —— 与「此人本可让 DSH 执行任意命令」的实际权限一致，限制目录没有
    安全收益，只会挡住自己。

    若确实想限定范围，在 cfg["file_roots"] 里列目录即可：此时只有这些目录
    （及其子目录）内的文件可取，相对路径按这些根解析，`..` 与符号链接逃逸会被
    规范化后拦下。
    """
    target = str(raw_path).strip().strip('"')
    if not target:
        return None
    roots = file_roots()
    if not roots:
        # 不限制：只接受绝对路径（相对路径没有基准，无法解释）。
        if not os.path.isabs(target):
            return None
        canonical = os.path.realpath(target)
        return canonical if os.path.isfile(canonical) else None
    for root in roots:
        candidate = target if os.path.isabs(target) else os.path.join(root, target)
        try:
            canonical = os.path.realpath(candidate)
        except Exception:
            continue
        if not path_within(canonical, root):
            continue
        if not os.path.isfile(canonical):
            continue
        return canonical
    return None


def file_headers(absolute: str) -> dict:
    """构造直传响应的头：内容类型、文件名（含中文）、长度、ETag。"""
    ext = os.path.splitext(absolute)[1].lstrip(".").lower()
    ctype = FILE_MIME.get(ext)
    if ctype is None:
        guessed, _ = mimetypes.guess_type(absolute)
        ctype = guessed or "application/octet-stream"
    try:
        size = os.path.getsize(absolute)
    except OSError:
        size = 0
    name = os.path.basename(absolute) or "download"
    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in '"\\' else "_" for ch in name)
    kind = "inline" if ext in FILE_INLINE_EXT else "attachment"
    try:
        with open(absolute, "rb") as fh:
            head = fh.read(65536)
        etag = hashlib.md5(head).hexdigest() + "-" + str(size)
    except OSError:
        etag = "0-" + str(size)
    return {
        "content-type": ctype,
        "content-disposition": f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{urllib.parse.quote(name)}",
        "content-length": str(size),
        "cache-control": "no-store",
        "x-content-type-options": "nosniff",
        "etag": '"' + etag + '"',
    }


def human_size(n: int) -> str:
    """人类可读的大小，用于显示页。"""
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


def html_escape(text: str) -> str:
    """最小化 HTML 转义，用于把文件内容放进 <pre>。"""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_view_page(absolute: str, request_path: str) -> bytes:
    """把文件渲染成手机友好的显示页（图片/文本内联 + 下载按钮）。

    @param absolute - 本机绝对路径。
    @param request_path - 浏览器请求里带的原始 path 参数，用于生成下载链接。
    """
    ext = os.path.splitext(absolute)[1].lstrip(".").lower()
    size = os.path.getsize(absolute)
    name = os.path.basename(absolute) or "file"
    raw_url = f"{FILE_FETCH_PATH}?path={urllib.parse.quote(request_path)}"

    if ext in VIEW_IMAGE_EXT and size <= VIEW_IMAGE_LIMIT:
        ctype = FILE_MIME.get(ext) or "image/png"
        with open(absolute, "rb") as fh:
            import base64 as _b64
            data_uri = f"data:{ctype};base64," + _b64.b64encode(fh.read()).decode("ascii")
        body = f'<img src="{data_uri}" alt="{html_escape(name)}">'
    elif ext in VIEW_TEXT_EXT and size <= VIEW_TEXT_LIMIT:
        with open(absolute, "r", encoding="utf-8", errors="replace") as fh:
            body = "<pre>" + html_escape(fh.read()) + "</pre>"
    elif ext in VIEW_TEXT_EXT or ext in VIEW_IMAGE_EXT:
        body = f'<div class="empty">文件过大（{human_size(size)}），请用右上角按钮下载</div>'
    else:
        body = f'<div class="empty">此类型无法在浏览器中预览（{html_escape(ext or "无扩展名")}），请下载后查看</div>'

    try:
        with open(FILE_VIEWER, "r", encoding="utf-8") as fh:
            template = fh.read()
    except OSError:
        template = ("<!doctype html><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<body style='font:15px sans-serif;padding:14px'>"
                    "<h3>__NAME__</h3><p>__SIZE__ · <a href='__RAW__' download>下载</a></p>__BODY__</body>")

    page = (template
            .replace("__VIEWER_DIR__", urllib.parse.quote(FILE_VIEWER_DIR, safe=""))
            .replace("__TITLE__", html_escape(name))
            .replace("__NAME__", html_escape(name))
            .replace("__SIZE__", human_size(size))
            .replace("__RAW__", raw_url)
            .replace("__BODY__", body))
    return page.encode("utf-8")


def cookie_value(set_cookie: str) -> str:
    """从一个 Set-Cookie 值里取出 '名=值'（丢弃属性）。

    DSH 的 cookie 名与值都是 cookie-safe base64url，因此按第一个分号截断即可。
    """
    return set_cookie.split(";", 1)[0].strip()


class CookieAuth:
    """持有 DSH 的会话 cookie，并在令牌变化时重新交换。

    main.py 里一切「桥 → 3080」的请求都必须先经过这里，因为 DSH 在 Host
    RPC 分发前统一做 authority 绑定的 cookie 校验，缺失即 401。
    """

    def __init__(self, target: str):
        self.target = target.rstrip("/")
        self.cookie: str | None = None   # "dsh-auth-xxx=yyy"
        self.token: str | None = None    # 上次成功交换用的进程令牌

    def apply(self, headers: dict) -> None:
        """把会话 cookie 附加到一份出站请求头（已存在则合并，不覆盖）。"""
        if not self.cookie:
            return
        existing = headers.get("cookie") or headers.get("Cookie")
        headers["cookie"] = f"{existing}; {self.cookie}" if existing else self.cookie

    def has_cookie(self, headers: dict) -> bool:
        """判断浏览器请求是否已带上 DSH 需要的那个 authority 绑定的 cookie。

        必须精确比对 cookie 名（dsh-auth-<sha256(host:port)>），不能只看前缀：
        浏览器里可能存着**别的 authority** 的同前缀 cookie（例如曾在
        localhost:3080 直连过），只按前缀判断会误以为"已经有 cookie 了"而跳过
        下发，于是永远 401。只看名字不看值——值可能属于上一个 DSH 进程却依然
        有效（签名密钥持久），也可能是伪造的，都交给 DSH 自己裁决。
        """
        if not self.cookie:
            return False
        name = self.cookie.split("=", 1)[0]
        raw = headers.get("cookie") or headers.get("Cookie") or ""
        return name in raw

    def set_cookie_header(self, max_age_days: int = 30) -> str | None:
        """合成一份可直接下发给浏览器的 Set-Cookie（交给浏览器持有）。

        浏览器这条腿原先完全没有凭据：桥的会话 cookie 只加在"桥→DSH"的出站
        请求上，DSH 现在却要求每个 Host API 与页面请求都带它，于是浏览器侧的
        请求一律 401、页面空白。桥既然已经持有有效 cookie，就在这里把它下发给
        浏览器，后续 /api/*、/assets/* 与 WebSocket 会自动带上，再经隧道送达 DSH。

        刻意不依赖转发 DSH 自己的 Set-Cookie：httpx 0.28 的 get_list 只保留最后
        一条，多 cookie 会丢。这里用桥已验证过的那一份，并按浏览器场景调整属性：
        去掉 Domain/Secure（隧道内是回环 HTTP），补 Path=/。cookie 名保持 DSH 原
        有的 authority 绑定名不动，这样 DSH 侧的校验照旧通过。
        """
        if not self.cookie:
            return None
        parts = [self.cookie, "Path=/", f"Max-Age={max_age_days * 24 * 3600}", "HttpOnly", "SameSite=Strict"]
        return "; ".join(parts)

    def _latest_token(self) -> str | None:
        """从 DSH 启动日志尾部取出当前进程的 ?token=。

        只认最后一次出现的那条：DSH 每次启动都会新打印一行，倒序扫到第一条
        就是当下在跑的进程。文件被轮转/清空或 DSH 尚未完成启动时为 None。
        """
        try:
            with open(DSH_3080_LOG, "rb") as f:
                f.seek(0, os.SEEK_END)
                size = f.tell()
                f.seek(max(0, size - DSH_LOG_TAIL_BYTES))
                tail = f.read().decode("utf-8", "replace")
        except OSError:
            return None
        matches = DSH_TOKEN_RE.findall(tail)
        return matches[-1] if matches else None

    async def refresh(self, http: httpx.AsyncClient | None = None, force: bool = False) -> bool:
        """确保拿到一份可用 cookie；返回是否已持有。

        @param http - 复用的 AsyncClient；不传则临时建一个（仅启动探活用）。
        @param force - 忽略令牌去重，强制重新交换（收到 401 后用）。
        """
        token = self._latest_token()
        if token is None:
            return self.cookie is not None
        if not force and token == self.token and self.cookie is not None:
            return True
        owned = http is None
        client = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0), trust_env=False,
                                           follow_redirects=False)
        try:
            # DSH 只在 GET / 且恰好一个 token 参数时交换，并回 303 + Set-Cookie。
            resp = await client.get(f"{self.target}/", params={"token": token})
            if resp.status_code in (303, 302, 301, 307, 308):
                set_cookie = resp.headers.get("set-cookie")
                if set_cookie:
                    self.cookie = cookie_value(set_cookie)
                    self.token = token
                    LOG.info("DSH 会话 cookie 已刷新（%s）", self.cookie.split("=", 1)[0])
                    return True
            LOG.warning("DSH 令牌交换未拿到 cookie: HTTP %s", resp.status_code)
        except Exception as exc:
            LOG.warning("DSH 令牌交换失败: %s", exc)
        finally:
            if owned:
                await client.aclose()
        return self.cookie is not None


SERVER_CHOICES = {
    "1": ("本地测试", "ws://localhost:8633"),
    "2": ("线上使用", "wss://zeen.xin"),
}
DSH_UI_PATH = "/dsh-ui/"
AUTH_PATH = "/__dsh_auth__"

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "content-length",
    "accept-encoding",
}

# 会被 httpx 改写/解压的实体头，绝不能照抄回浏览器：httpx 的 aiter_bytes()
# 默认自动解压 gzip/deflate/br，但响应头里仍保留原 content-encoding，原样转发
# 会让浏览器按 gzip 解一份明文而失败（响应体被丢弃、页面空白）。
DECODED_ENTITY_HEADERS = {"content-encoding", "content-length"}

# ---- 工具目录：动态定位（宿主注入的插件目录 / 直接运行时脚本目录），不硬编码 ----
def _find_tool_dir() -> str:
    for _p in sys.path:
        if _p and os.path.isdir(_p) and os.path.exists(os.path.join(_p, "main.py")):
            return _p
    return os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ""


TOOL_DIR = _find_tool_dir()


# ---- 页面文件（独立 HTML，每次请求读取 → 改文件即时生效）----
DHSR_DIR = TOOL_DIR


def _load_page(name: str) -> str:
    path = os.path.join(DHSR_DIR, name)
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception as exc:
        print(f"[dsh] 页面文件缺失: {path} ({exc})")
        return "<h1>页面文件缺失</h1>"


# ---------------------------------------------------------------- 密码与票据
def hash_password(password: str, salt: bytes | None = None) -> dict:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    return {"algo": "scrypt", "n": SCRYPT_N, "r": SCRYPT_R, "p": SCRYPT_P,
            "dklen": SCRYPT_DKLEN,
            "salt": base64.b64encode(salt).decode("ascii"),
            "hash": base64.b64encode(digest).decode("ascii")}


def verify_password(password: str, pw_field: dict) -> bool:
    try:
        salt = base64.b64decode(pw_field["salt"])
        expected = base64.b64decode(pw_field["hash"])
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                n=pw_field.get("n", SCRYPT_N), r=pw_field.get("r", SCRYPT_R),
                                p=pw_field.get("p", SCRYPT_P), dklen=pw_field.get("dklen", SCRYPT_DKLEN))
        return secrets.compare_digest(digest, expected)
    except Exception:
        return False


class TicketStore:
    def __init__(self, ttl: int):
        self.ttl = ttl
        self._tickets: dict[str, float] = {}

    def issue(self) -> str:
        ticket = secrets.token_urlsafe(32)
        self._tickets[ticket] = time.time() + self.ttl
        return ticket

    def validate(self, ticket: str | None) -> bool:
        if not ticket:
            return False
        expiry = self._tickets.get(ticket)
        if expiry is None:
            return False
        if time.time() > expiry:
            self._tickets.pop(ticket, None)
            return False
        return True


class VerifyRateLimiter:
    def __init__(self, max_attempts: int, window: int, lockout: int):
        self.max_attempts = max_attempts
        self.window = window
        self.lockout = lockout
        self._attempts: list[float] = []
        self._locked_until = 0.0

    def locked(self) -> bool:
        return time.time() < self._locked_until

    def record_failure(self) -> bool:
        if self.locked():
            return False
        now = time.time()
        self._attempts = [t for t in self._attempts if now - t < self.window]
        self._attempts.append(now)
        if len(self._attempts) >= self.max_attempts:
            self._locked_until = now + self.lockout
            self._attempts.clear()
            LOG.warning("too many failed password attempts; locked for %ss", self.lockout)
            return False
        return True

    def reset(self) -> None:
        self._attempts.clear()
        self._locked_until = 0.0


# ---------------------------------------------------------------- 配置命令
def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def save_config(cfg: dict) -> None:
    # 懒加载：只有真正写配置时才创建数据目录
    os.makedirs(DATA_DIR, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")


def read_password(prompt: str) -> str:
    env_pw = os.environ.get("DSH_BRIDGE_PASSWORD")
    if env_pw:
        return env_pw
    return getpass.getpass(prompt)


def choose_server(cfg: dict) -> str:
    print("桥连接哪台服务器？")
    for k, (name, url) in SERVER_CHOICES.items():
        mark = " (当前)" if cfg.get("server") == url else ""
        print(f"  [{k}] {name}  {url}{mark}")
    choice = input("请输入 1 或 2: ").strip() or "2"
    return SERVER_CHOICES.get(choice, SERVER_CHOICES["2"])[1]


def cmd_setup() -> int:
    cfg = load_config() or {}
    print("===== dsh-bridge 首次安装 =====")
    server = choose_server(cfg)
    token = input("粘贴你的 zeen.xin 登录 token（浏览器登录后从 Cookie 的 token 里复制）: ").strip()
    if len(token) < 20:
        print("错误：token 太短，请检查是否复制完整")
        return 1
    pw1 = read_password("设置本机密码（手机远程解锁用，≥6位）: ")
    if len(pw1) < 6:
        print("错误：密码长度至少 6 位")
        return 1
    pw2 = read_password("再次输入确认: ")
    if pw1 != pw2:
        print("错误：两次输入不一致")
        return 1
    cfg.update({
        "server": server,
        "token": token,
        "target": DEFAULT_TARGET,
        "ticket_ttl": 12 * 3600,
        "verify": {"max_attempts": 5, "window_seconds": 30, "lockout_seconds": 300},
        "request_timeout": 300,
        "password": hash_password(pw1),
    })
    save_config(cfg)
    print("已保存。启动：python dsh_bridge.py")
    print(f"  服务器: {server}")
    return 0


def cmd_set_token() -> int:
    cfg = load_config()
    if not cfg:
        print("未配置：请运行 moss :dsh 打开设置向导")
        return 1
    token = input("粘贴新的 zeen.xin 登录 token: ").strip()
    if len(token) < 20:
        print("错误：token 太短")
        return 1
    cfg["token"] = token
    save_config(cfg)
    print("token 已更新（重启桥生效）")
    return 0


def cmd_set_password() -> int:
    cfg = load_config()
    if not cfg:
        print("未配置：请运行 moss :dsh 打开设置向导")
        return 1
    pw1 = read_password("新的本机密码（≥6位）: ")
    if len(pw1) < 6:
        print("错误：密码长度至少 6 位")
        return 1
    pw2 = read_password("再次输入确认: ")
    if pw1 != pw2:
        print("错误：两次输入不一致")
        return 1
    cfg["password"] = hash_password(pw1)
    save_config(cfg)
    print("本机密码已更新（重启桥生效；所有已签发票据将失效）")
    return 0


def cmd_status() -> int:
    cfg = load_config()
    if not cfg:
        print("未配置：请运行 moss :dsh 打开设置向导（http://127.0.0.1:8788/）")
        return 1
    print(f"server      : {cfg.get('server')}")
    print(f"target      : {cfg.get('target')}")
    print(f"zeen token  : {cfg.get('token','')[:24]}...(长度{len(cfg.get('token',''))})")
    print(f"ticket_ttl  : {cfg.get('ticket_ttl')}s")
    print(f"password    : {'已设置' if cfg.get('password') else '未设置!'}")
    return 0


# ---------------------------------------------------------------- 桥主体
def ticket_from_headers(headers: dict) -> str | None:
    cookie = headers.get("cookie") or headers.get("Cookie")
    if not cookie:
        return None
    for part in cookie.split(";"):
        part = part.strip()
        if part.startswith("dsh_session="):
            return part[len("dsh_session="):]
    return None


def filter_response_headers(headers) -> dict:
    """过滤回传给浏览器的响应头。

    必须剔除 httpx 已经改写过的实体头，否则浏览器会按一个不成立的声明去解析
    响应体。实测踩过的坑：DSH 以 gzip + chunked 回首页，httpx 的 aiter_bytes()
    默认自动解压，但 resp.headers 里**仍带着 content-encoding: gzip**；桥若原样
    下发，浏览器拿到的是明文却按 gzip 去解 → Failed to fetch → 响应体被整个
    丢弃 → 页面空白（status 却仍是 200，排查时极具迷惑性）。
    content-length / transfer-encoding 同理：解压后长度已变、传输已由隧道自己
    分块，都不能照抄。
    """
    out = {}
    for k, v in headers.items():
        kl = k.lower()
        if kl in HOP_BY_HOP or kl in DECODED_ENTITY_HEADERS:
            continue
        out[k] = v
    return out


class Bridge:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.tickets = TicketStore(int(cfg.get("ticket_ttl", 43200)))
        lim = cfg.get("verify", {})
        self.limiter = VerifyRateLimiter(
            max_attempts=int(lim.get("max_attempts", 5)),
            window=int(lim.get("window_seconds", 30)),
            lockout=int(lim.get("lockout_seconds", 300)),
        )
        self.request_timeout = float(cfg.get("request_timeout", 300))
        # DSH 会话认证：桥转发与 WS 中继都要带 cookie，否则被 401 拦掉。
        self.dsh_auth = CookieAuth(str(cfg.get("target", DEFAULT_TARGET)))
        self.ws = None
        self.connected = False
        self._connect_task: asyncio.Task | None = None
        self._http: httpx.AsyncClient | None = None
        self._pending: dict[str, dict] = {}
        self._ws_conns: dict[str, object] = {}

    def start_connecting(self) -> None:
        """触发 WS 连接（设置页"连接"按钮调用；幂等）。"""
        if self._connect_task is not None and not self._connect_task.done():
            return
        self._connect_task = asyncio.create_task(self.run_forever())

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=httpx.Timeout(self.request_timeout),
                                           trust_env=False)
        return self._http

    async def send(self, msg: dict) -> None:
        if self.ws is None:
            return
        await self.ws.send(json.dumps(msg, ensure_ascii=False))

    # ---- 消息处理 ----
    async def on_verify_password(self, msg: dict) -> None:
        req_id = msg.get("id")
        password = msg.get("password") or ""
        if self.limiter.locked():
            await self.send({"type": "verify_password_result", "id": req_id,
                             "ok": False, "message": "尝试过于频繁，请稍后再试"})
            return
        if not verify_password(password, self.cfg.get("password") or {}):
            self.limiter.record_failure()
            await self.send({"type": "verify_password_result", "id": req_id,
                             "ok": False, "message": "密码错误"})
            return
        self.limiter.reset()
        ticket = self.tickets.issue()
        LOG.info("password OK; issued ticket ttl=%ss", self.tickets.ttl)
        await self.send({"type": "verify_password_result", "id": req_id,
                         "ok": True, "ticket": ticket, "ttl": self.tickets.ttl})

    async def on_tunnel_http(self, msg: dict) -> None:
        """隧道请求：登记分块累积；无票据的普通请求直接劫持返回设置页。"""
        req_id = msg.get("id")
        method = str(msg.get("method", "GET")).upper()
        path = msg.get("path") or "/"
        headers = msg.get("headers") or {}
        kind = "auth" if (method == "POST" and path.startswith(AUTH_PATH)) else "tunnel"
        # 本机文件直传 / 显示页：走桥自己读盘，不转发给 DSH（见 FILE_FETCH_PATH 处说明）。
        if path.split("?", 1)[0] == FILE_FETCH_PATH:
            kind = "file"
        elif path.split("?", 1)[0] == FILE_VIEW_PATH:
            kind = "fileview"
        if kind == "tunnel" and not self.tickets.validate(ticket_from_headers(headers)):
            await self._reply(req_id, 200, {"content-type": "text/html; charset=utf-8"},
                              _load_page("unlock.html").encode("utf-8"))
            return
        self._pending[req_id] = {"method": method, "path": path,
                                 "headers": headers, "parts": [], "kind": kind}

    async def on_tunnel_http_body(self, msg: dict) -> None:
        req_id = msg.get("id")
        entry = self._pending.get(req_id)
        if entry is None:
            return
        data = msg.get("dataBase64")
        if data:
            entry["parts"].append(base64.b64decode(data))
        if msg.get("final"):
            self._pending.pop(req_id, None)
            if entry["kind"] == "auth":
                asyncio.create_task(self._handle_auth(req_id, entry))
            elif entry["kind"] == "file":
                asyncio.create_task(self._handle_file(req_id, entry))
            elif entry["kind"] == "fileview":
                asyncio.create_task(self._handle_file_view(req_id, entry))
            else:
                asyncio.create_task(self._forward(req_id, entry))

    async def _handle_file(self, req_id: str, entry: dict) -> None:
        """本机文件直传：桥自己读盘回传原始字节，不经过 DSH。

        已在 on_tunnel_http 过了票据校验（zeen 登录 + 二级密码票据）。路径解析
        默认不限制目录（见 resolve_file_request）；不可读的目标一律 404。
        """
        method = entry["method"]
        if method not in ("GET", "HEAD"):
            await self._reply(req_id, 405, {"allow": "GET, HEAD"}, b"")
            return
        raw_path = entry["path"]
        if "?" in raw_path:
            raw_path = raw_path.split("?", 1)[0]
        query = urllib.parse.urlparse(entry["path"]).query
        wanted = urllib.parse.parse_qs(query).get("path", [""])[0]
        target = resolve_file_request(wanted)
        if target is None:
            # 诊断日志：把"收到的原始参数"和"各级解析结果"都打出来。
            # 这样"文件其实在、但被拒"这类情况能一眼看出卡在哪一步，
            # 不必再靠猜（尤其 Windows 上 isabs/realpath/isfile 的分歧）。
            roots = file_roots()
            diag = {
                "want": wanted,
                "isabs": os.path.isabs(wanted) if wanted else None,
                "roots": roots or "(未配置=不限制)",
                "realpath": None,
                "exists": None,
                "isfile": None,
                "isdir": None,
            }
            if wanted:
                try:
                    diag["realpath"] = os.path.realpath(wanted)
                except Exception as exc:
                    diag["realpath"] = f"realpath 失败: {exc}"
                try:
                    diag["exists"] = os.path.exists(wanted)
                    diag["isfile"] = os.path.isfile(wanted)
                    diag["isdir"] = os.path.isdir(wanted)
                except Exception as exc:
                    diag["exists"] = f"检查失败: {exc}"
            LOG.info("file.fetch 拒绝: %s", diag)
            await self._reply(req_id, 404, {"content-type": "text/plain; charset=utf-8"},
                              "file not found".encode("utf-8"))
            return
        headers = file_headers(target)
        if method == "HEAD":
            await self._reply(req_id, 200, headers, b"")
            return
        await self._reply_file(req_id, target, headers)

    async def _reply_file(self, req_id: str, target: str, headers: dict) -> None:
        """把一个本机文件直传给隧道，**分块**发送。

        为什么必须分块：对面 uvicorn 的单条 WS 消息上限是 ws_max_size（默认 16 MiB），
        整包直传要先 base64（×4/3）再塞进一条 tunnel_http_chunk —— 于是超过约 12 MiB
        的文件会被对面以 1009 (message too big) 断开，桥随后退避重连
        （日志里的 "connection error: received 1009 ...; retry in 32s"）。
        按 FILE_CHUNK 分块后单条消息约 5.3 MiB；顺带两个好处：浏览器能边收边用
        （音视频不必等整包到齐），读盘也不再阻塞事件循环。
        """
        try:
            await self.send({"type": "tunnel_http_start", "id": req_id,
                             "status": 200, "headers": headers})
        except Exception as exc:
            LOG.warning("file.fetch 起始帧发送失败 %s: %s", target, exc)
            return
        sent, blocks = 0, 0
        try:
            with open(target, "rb") as fh:
                while True:
                    # read 是阻塞调用，丢到线程里，别卡住整个事件循环
                    part = await asyncio.to_thread(fh.read, FILE_CHUNK)
                    if not part:
                        break
                    sent += len(part)
                    blocks += 1
                    await self.send({"type": "tunnel_http_chunk", "id": req_id,
                                     "dataBase64": base64.b64encode(part).decode("ascii")})
        except Exception as exc:
            # 已经发过 start/chunk，状态码改不了了，只能通知对面中止这次响应
            LOG.warning("file.fetch 直传中断 %s（已发 %d 字节）: %s", target, sent, exc)
            try:
                await self.send({"type": "tunnel_http_error", "id": req_id,
                                 "message": f"read failed: {exc}"[:200]})
            except Exception:
                pass
            return
        try:
            await self.send({"type": "tunnel_http_end", "id": req_id})
        except Exception as exc:
            LOG.warning("file.fetch 结束帧发送失败 %s: %s", target, exc)
            return
        LOG.info("file.fetch 直传 %s (%d 字节 / %d 块)", target, sent, blocks)

    async def _handle_file_view(self, req_id: str, entry: dict) -> None:
        """显示页：把文件渲染成手机友好的 HTML（图片/文本内联 + 下载按钮）。

        与 _handle_file 读同一份盘、走同一套鉴权，区别只在响应体是排版好的
        页面而不是原始字节 —— 这样在手机浏览器里点开就能看，不必先下载。
        """
        if entry["method"] not in ("GET", "HEAD"):
            await self._reply(req_id, 405, {"allow": "GET, HEAD"}, b"")
            return
        query = urllib.parse.urlparse(entry["path"]).query
        wanted = urllib.parse.parse_qs(query).get("path", [""])[0]
        target = resolve_file_request(wanted)
        if target is None:
            body = ("<!doctype html><meta charset='utf-8'>"
                    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                    "<body style='font:15px sans-serif;padding:20px'>文件不存在或不可读</body>")
            LOG.info("file.view 拒绝: %r", wanted)
            await self._reply(req_id, 404, {"content-type": "text/html; charset=utf-8"},
                              body.encode("utf-8"))
            return
        try:
            page = build_view_page(target, wanted)
        except OSError as exc:
            LOG.warning("file.view 渲染失败 %s: %s", target, exc)
            await self._reply(req_id, 500, {"content-type": "text/plain; charset=utf-8"},
                              "render failed".encode("utf-8"))
            return
        LOG.info("file.view 显示 %s (%d 字节页面)", target, len(page))
        await self._reply(req_id, 200, {
            "content-type": "text/html; charset=utf-8",
            "content-length": str(len(page)),
            "cache-control": "no-store",
            "x-content-type-options": "nosniff",
        }, page)

    async def _handle_auth(self, req_id: str, entry: dict) -> None:
        """设置页密码验证：成功 → Set-Cookie 会话票据。"""
        body = b"".join(entry["parts"]) or b"{}"
        try:
            password = (json.loads(body.decode("utf-8")) or {}).get("password") or ""
        except Exception:
            password = ""
        if self.limiter.locked():
            ok, message, ticket = False, "尝试过于频繁，请稍后再试", None
        elif not verify_password(password, self.cfg.get("password") or {}):
            self.limiter.record_failure()
            ok, message, ticket = False, "密码错误", None
        else:
            self.limiter.reset()
            ticket = self.tickets.issue()
            ok, message = True, ""
        headers = {"content-type": "application/json; charset=utf-8"}
        if ok:
            secure = "Secure; " if (entry["headers"].get("x-forwarded-proto") == "https") else ""
            headers["set-cookie"] = (
                f"dsh_session={ticket}; Path=/; Max-Age={self.tickets.ttl}; "
                f"HttpOnly; SameSite=Lax; {secure}".replace(" ;", "").strip()
            )
            LOG.info("setup auth OK")
        await self._reply(req_id, 200, headers,
                          json.dumps({"ok": ok, "message": message}, ensure_ascii=False).encode())

    async def _reply(self, req_id: str, status: int, headers: dict, body: bytes) -> None:
        try:
            await self.send({"type": "tunnel_http_start", "id": req_id,
                             "status": status, "headers": headers})
            await self.send({"type": "tunnel_http_chunk", "id": req_id,
                             "dataBase64": base64.b64encode(body).decode("ascii")})
            await self.send({"type": "tunnel_http_end", "id": req_id})
        except Exception as exc:
            LOG.warning("reply %s failed: %s", req_id, exc)

    async def _send_http(self, req_id: str, method: str, target: str,
                         headers: dict, body: bytes | None,
                         browser_headers: dict | None = None) -> int | None:
        """转发一次并流式回传；返回响应状态码，连接层失败返回 None。

        @param browser_headers - 浏览器原始请求头；根页面成功时据此决定是否
          把会话 cookie 下发给浏览器（见 CookieAuth.set_cookie_header）。
        """
        try:
            async with self.http.stream(method, target, headers=headers, content=body) as resp:
                out_headers = filter_response_headers(resp.headers)
                self.hand_off_cookie(target, resp.status_code, browser_headers, out_headers)
                await self.send({"type": "tunnel_http_start", "id": req_id,
                                 "status": resp.status_code,
                                 "headers": out_headers})
                async for chunk in resp.aiter_bytes():
                    await self.send({"type": "tunnel_http_chunk", "id": req_id,
                                     "dataBase64": base64.b64encode(chunk).decode("ascii")})
                await self.send({"type": "tunnel_http_end", "id": req_id})
                return resp.status_code
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("forward %s %s failed: %s", method, target, exc)
            await self.send({"type": "tunnel_http_error", "id": req_id,
                             "message": str(exc)[:200]})
            return None

    def hand_off_cookie(self, target: str, status: int,
                        browser_headers: dict | None, out_headers: dict) -> None:
        """把 DSH 会话 cookie 下发给浏览器（仅在根页面成功响应时）。

        只在 path 恰为 "/" 且响应 2xx/3xx 时下发：那是 DSH 的界面入口，其余
        请求（/api/*、/assets/*）本就该复用浏览器已持有的 cookie，不能重复下发。
        浏览器已带 cookie 时也不下发，避免每个请求都刷一次响应头。
        """
        if browser_headers is None:
            return
        path = urllib.parse.urlparse(target).path
        if path != "/" or not (200 <= status < 400):
            return
        if self.dsh_auth.has_cookie(browser_headers):
            return
        cookie = self.dsh_auth.set_cookie_header()
        if cookie is None:
            return
        out_headers["set-cookie"] = cookie
        LOG.info("已向浏览器下发 DSH 会话 cookie（%s）", self.dsh_auth.cookie.split("=", 1)[0])

    def _forward_headers(self, entry: dict) -> dict:
        """构造出站头：伪装回环 + 附上 DSH 会话 cookie。

        DSH 的浏览器信任围栏只放行"看起来来自本机"的请求，所以 Host 改为回环、
        剥离 Origin；但必须保留 Sec-Fetch-Site（同源请求为 same-origin）——
        DSH 围栏只拒 cross-site，而 vision-toolkit 等插件的同源检查依赖
        sec-fetch-site 判同源。桥端逐请求验票据兜底安全。
        认证那一层另由 DSH 的 cookie 负责（见 CookieAuth）。
        """
        headers = {}
        for k, v in entry["headers"].items():
            kl = k.lower()
            if kl in HOP_BY_HOP or kl in ("host", "origin",
                                          "sec-fetch-mode", "sec-fetch-dest", "sec-fetch-user"):
                continue
            headers[k] = v
        if headers.get("sec-fetch-site") in (None, "", "cross-site"):
            headers["sec-fetch-site"] = "same-origin"
        headers["Host"] = "127.0.0.1:3080"
        self.dsh_auth.apply(headers)
        return headers

    async def _forward(self, req_id: str, entry: dict) -> None:
        method = entry["method"]
        path = entry["path"]
        body = b"".join(entry["parts"]) if entry["parts"] else None
        target = f"{self.cfg.get('target', DEFAULT_TARGET)}{path}"
        headers = self._forward_headers(entry)
        status = await self._send_http(req_id, method, target, headers, body, entry["headers"])
        # DSH 进程重启会换掉启动令牌，旧 cookie 仍然有效（密钥持久），但若密钥
        # 被轮换/cookie 过期，这里就是唯一的自愈点：重取令牌并重试一次。
        if status == 401:
            LOG.info("转发收到 401，重取 DSH 会话 cookie 后重试: %s %s", method, path)
            if await self.dsh_auth.refresh(self.http, force=True):
                headers = self._forward_headers(entry)
                await self._send_http(req_id, method, target, headers, body)
            else:
                LOG.warning("重取 DSH 会话 cookie 失败，%s %s 仍为 401", method, path)

    # ---- WebSocket 中继 ----
    async def on_open_ws(self, msg: dict) -> None:
        req_id = msg.get("id")
        if not self.tickets.validate(ticket_from_headers(msg.get("headers") or {})):
            await self.send({"type": "ws_open_error", "id": req_id, "message": "unauthorized"})
            return
        path = msg.get("path") or "/"
        skip = {"origin", "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest",
                "sec-fetch-user", "sec-websocket-key", "sec-websocket-version",
                "sec-websocket-extensions", "sec-websocket-protocol"}
        headers = {k: v for k, v in (msg.get("headers") or {}).items()
                   if k.lower() not in HOP_BY_HOP and k.lower() not in skip}
        # WS upgrade 同样过 DSH 的会话校验：没有 cookie 会直接握手失败。
        self.dsh_auth.apply(headers)
        target = f"ws://127.0.0.1:3080{path}"
        try:
            ws = await websockets.connect(target, additional_headers=headers,
                                          max_size=64 * 1024 * 1024, open_timeout=5)
        except Exception as exc:
            LOG.warning("open_ws %s failed: %s", path, exc)
            await self.send({"type": "ws_open_error", "id": req_id, "message": str(exc)[:200]})
            return
        self._ws_conns[req_id] = ws
        await self.send({"type": "ws_open_ack", "id": req_id})
        # 泵 3080 事件流。3080 断开时立即关闭浏览器端连接：
        # DSH 前端自带指数退避重连（client-connection），会重新订阅事件流并恢复状态。
        # 桥若替前端保持连接，前端以为还连着就不重连，事件流却断了 → UI 卡死(按钮禁用)。
        asyncio.create_task(self._ws_pump_up(req_id, ws))

    async def _ws_pump_up(self, req_id: str, ws) -> None:
        """泵 3080 → 浏览器；断开即通知前端（前端自己重连恢复状态）。"""
        try:
            async for data in ws:
                if isinstance(data, str):
                    await self.send({"type": "ws_frame", "id": req_id, "data": data})
                else:
                    await self.send({"type": "ws_frame", "id": req_id,
                                     "dataBase64": base64.b64encode(data).decode("ascii")})
        except Exception as exc:
            LOG.debug("ws pump up end: %s", exc)
        finally:
            # 通知前端连接丢失 → 前端自动重连（3080 被监护拉起后重连即恢复）
            self._ws_conns.pop(req_id, None)
            try:
                await self.send({"type": "ws_close", "id": req_id})
                await ws.close()
            except Exception:
                pass

    async def on_ws_frame(self, msg: dict) -> None:
        ws = self._ws_conns.get(msg.get("id"))
        if ws is None:
            return
        try:
            if "data" in msg:
                await ws.send(msg["data"])
            elif "dataBase64" in msg:
                await ws.send(base64.b64decode(msg["dataBase64"]))
        except Exception:
            pass

    async def on_ws_close(self, msg: dict) -> None:
        ws = self._ws_conns.pop(msg.get("id"), None)
        if ws is not None:
            try:
                await ws.close()
            except Exception:
                pass

    def close_all_ws(self) -> None:
        for ws in list(self._ws_conns.values()):
            try:
                ws.close()
            except Exception:
                pass
        self._ws_conns.clear()

    async def handle_message(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        mtype = msg.get("type")
        if mtype == "ping":
            await self.send({"type": "pong"})
        elif mtype == "verify_password":
            await self.on_verify_password(msg)
        elif mtype == "tunnel_http":
            await self.on_tunnel_http(msg)
        elif mtype == "tunnel_http_body":
            await self.on_tunnel_http_body(msg)
        elif mtype == "open_ws":
            await self.on_open_ws(msg)
        elif mtype == "ws_frame":
            await self.on_ws_frame(msg)
        elif mtype == "ws_close":
            await self.on_ws_close(msg)
        elif mtype == "hello_ack":
            LOG.info("server hello_ack: %s", msg)

    async def run_once(self, server_url: str) -> None:
        LOG.info("connecting %s ...", server_url)
        try:
            async with websockets.connect(server_url, max_size=64 * 1024 * 1024) as ws:
                self.ws = ws
                await self.send({"type": "hello", "role": "bridge",
                                 "token": self.cfg.get("token", "")})
                LOG.info("connected, waiting for tunnel requests")
                self.connected = True
                async for raw in ws:
                    await self.handle_message(raw)
        finally:
            self.ws = None
            self.connected = False
            self.close_all_ws()

    async def run_forever(self) -> None:
        cfg = load_config()
        if not cfg or not cfg.get("token") or not cfg.get("password"):
            LOG.error("未安装：请先运行  python dsh_bridge.py --setup")
            return
        server_url = bridge_ws_url(cfg.get("server", SERVER_CHOICES["2"][1]))
        backoff = 2.0
        while True:
            try:
                await self.run_once(server_url)
                backoff = 2.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOG.warning("connection error: %s; retry in %.0fs", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
            await asyncio.sleep(1)


# 桥注册路径（配置里只写服务器主机，路径由程序拼接）
BRIDGE_WS_PATH = "/dsh/bridge/ws"

_IP4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}")


def _looks_like_ip(host: str) -> bool:
    """localhost / 127.x / 任意 IPv4 字面量 都算 IP（走 ws://）。"""
    host = host.split(":")[0].strip()
    return host == "localhost" or host.startswith("127.") or bool(_IP4_RE.match(host))


def normalize_server(raw: str) -> str:
    """宽容解析 server 配置，杜绝"少写/写错"问题：
    - 只需写主机：zeen.xin / zeen.xin/ / localhost:8633 / 192.168.31.2:8633
    - 协议自动：IP（含 localhost）→ ws://；域名 → wss://
    - 误写 http/https/ws/wss 也自动规范化
    - 带/不带尾斜杠、带/不带 /dsh/bridge/ws 均可
    """
    s = (raw or "").strip().rstrip("/")
    if not s:
        return ""
    if s.endswith(BRIDGE_WS_PATH):
        s = s[: -len(BRIDGE_WS_PATH)].rstrip("/")
    s = s.replace("https://", "wss://").replace("http://", "ws://")
    if "://" not in s:
        s = ("ws://" if _looks_like_ip(s) else "wss://") + s
    elif s.startswith("ws://") and not _looks_like_ip(s[len("ws://"):]):
        s = "wss://" + s[len("ws://"):]
    return s


def bridge_ws_url(server: str) -> str:
    """拼上固定的桥路径（兼容已带路径的写法）。"""
    s = normalize_server(server)
    if s.endswith(BRIDGE_WS_PATH):
        return s
    return s.rstrip("/") + BRIDGE_WS_PATH


def ws_to_http(ws_url: str) -> str:
    """ws/wss -> http/https 主机地址（供官方 API 用）。"""
    base = normalize_server(ws_url).replace("wss://", "https://").replace("ws://", "http://")
    if base.endswith(BRIDGE_WS_PATH):
        base = base[: -len(BRIDGE_WS_PATH)]
    return base





class SetupServer:
    """本地设置向导（仅 127.0.0.1）：二级密码 + 官方登录 + 连接。
    登录完全走 zeen.xin 官方 API（/safe/code 验证码 + /user/login），不涉及任何服务器秘密。"""

    def __init__(self, bridge: "Bridge"):
        self.bridge = bridge
        self.app = web.Application()
        self.app.router.add_get("/", self.page)
        self.app.router.add_get("/setup", self.page)
        self.app.router.add_get("/setup/status", self.status)
        self.app.router.add_get("/setup/code", self.code)
        self.app.router.add_post("/setup/password", self.password)
        self.app.router.add_post("/setup/login", self.login)
        self.app.router.add_post("/setup/select", self.select)
        self.app.router.add_post("/setup/connect", self.connect)

    def _http_base(self) -> str:
        return ws_to_http(self.bridge.cfg.get("server", "ws://localhost:8633"))

    async def page(self, request):
        return web.Response(text=_load_page("setup.html"), content_type="text/html")

    async def status(self, request):
        cfg = self.bridge.cfg
        return web.json_response({
            "password_set": bool(cfg.get("password")),
            "token_set": bool(cfg.get("token")),
            "user": cfg.get("user", ""),
            "server": cfg.get("server", ""),
            "connected": self.bridge.connected,
        })

    async def code(self, request):
        """转发官方验证码接口 GET /safe/code（失败时返回明确原因，不崩溃）。"""
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=15) as c:
                r = await c.get(self._http_base() + "/safe/code")
                if r.status_code != 200:
                    return web.json_response({"ok": False,
                                              "message": f"主站返回 {r.status_code}（请确认主站已启动且未在重启）"})
                try:
                    data = r.json()
                except Exception:
                    return web.json_response({"ok": False,
                                              "message": "主站响应异常（非 JSON，可能服务未就绪）"})
                return web.json_response(data)
        except httpx.ConnectError:
            return web.json_response({"ok": False, "message": "无法连接主站，请确认主站已启动"})
        except Exception as exc:
            return web.json_response({"ok": False,
                                      "message": f"获取验证码失败：{str(exc)[:80]}"})

    async def password(self, request):
        data = await request.json()
        pw = (data.get("password") or "").strip()
        if len(pw) < 6:
            return web.json_response({"ok": False, "message": "密码至少 6 位"})
        self.bridge.cfg["password"] = hash_password(pw)
        save_config(self.bridge.cfg)
        return web.json_response({"ok": True})

    async def login(self, request):
        """官方登录：POST /user/login，成功则记录服务器签发的 token。
        注意：系统前端登录会把密码先算 md5 再提交（库里存 md5），这里保持一致。"""
        data = await request.json()
        raw_pw = str(data.get("password") or "")
        data["password"] = hashlib.md5(raw_pw.encode("utf-8")).hexdigest()
        async with httpx.AsyncClient(trust_env=False, timeout=15) as c:
            r = await c.post(self._http_base() + "/user/login", json=data)
            try:
                body = r.json()
            except Exception:
                return web.json_response({"ok": False, "message": "服务器响应异常"})
            if body.get("ret") != 1:
                return web.json_response({"ok": False, "message": body.get("msg", "登录失败")})
            token = r.cookies.get("token") or ""
            if not token:
                return web.json_response({"ok": False, "message": "未收到登录 token"})
            self.bridge.cfg["token"] = token
            self.bridge.cfg["user"] = str(data.get("name", ""))
            save_config(self.bridge.cfg)
            LOG.info("official login OK: user=%s", data.get("name"))
            return web.json_response({"ok": True, "user": data.get("name")})

    async def select(self, request):
        """只切换服务器（登录/连接都跟随），不触发连接。"""
        data = await request.json()
        server = (data.get("server") or "").strip()
        if not server.startswith(("ws://", "wss://")):
            return web.json_response({"ok": False, "message": "非法地址"})
        self.bridge.cfg["server"] = server
        save_config(self.bridge.cfg)
        LOG.info("server selected: %s", server)
        return web.json_response({"ok": True})

    async def connect(self, request):
        data = await request.json()
        server = (data.get("server") or "").strip()
        if server:
            if not server.startswith(("ws://", "wss://")):
                return web.json_response({"ok": False, "message": "非法地址"})
            self.bridge.cfg["server"] = server
            save_config(self.bridge.cfg)
        if not self.bridge.cfg.get("token"):
            return web.json_response({"ok": False, "message": "请先完成第 2 步登录"})
        if not self.bridge.cfg.get("password"):
            return web.json_response({"ok": False, "message": "请先完成第 1 步设置密码"})
        self.bridge.start_connecting()
        return web.json_response({"ok": True, "message": "连接已触发，请查看状态"})


# ---- 单实例接管：PID 文件 + 端口兜底，确保只有一个 dsh、7×24 可用 ----
PID_FILE = os.path.join(DATA_DIR, "dsh.pid")


def pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True, timeout=10).stdout
        return f"PID {pid}" in out or str(pid) in out
    except Exception:
        return False


def find_port_pids(port: int) -> list[int]:
    """找出占用指定端口的进程 PID（Windows netstat）。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True,
                             text=True, timeout=10).stdout
    except Exception as exc:
        LOG.warning("netstat failed: %s", exc)
        return []
    pids = []
    for line in out.splitlines():
        if f":{port}" in line and "LISTENING" in line.upper():
            parts = line.split()
            if parts and parts[-1].isdigit():
                pid = int(parts[-1])
                if pid not in pids and pid != os.getpid():
                    pids.append(pid)
    return pids


def kill_and_wait(pid: int) -> None:
    """杀掉 pid 并等待进程确实消失（最多 3 秒）。"""
    try:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)],
                       capture_output=True, timeout=10)
    except Exception as exc:
        LOG.warning("结束 pid %s 失败: %s", pid, exc)
    for _ in range(6):
        if not pid_alive(pid):
            return
        time.sleep(0.5)


def wait_port_free(port: int, timeout: float = 5.0) -> bool:
    """等待端口不再被监听（旧实例被杀后端口释放）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not find_port_pids(port):
            return True
        time.sleep(0.3)
    return False


def looks_like_bridge(pid: int) -> bool:
    """那个 pid 是不是「另一个 dsh 桥」，而不是系统把 PID 复用给了别的程序。

    只在"按 PID 文件接管旧实例"时用：PID 会被系统复用，旧 PID 文件里那个号很可能已经
    是无关程序了 —— 那时直接 taskkill 就是**误杀**。所以要求命令行里同时出现 dsh 与
    main.py/bootstrap.py（桥自己的写法）。取不到命令行就返回 False（宁可不动手）。
    """
    cmd = process_cmdline(pid).lower()
    if not cmd:
        return False
    return ("dsh" in cmd) and (("main.py" in cmd) or ("bootstrap.py" in cmd))


def release_pid_file() -> None:
    """退出时把自己的 PID 文件删掉。

    原来它**只写不删**：下次启动会照着那个陈旧 pid 去"接管"，一旦系统把这个号
    复用给别的程序，就会误杀无关进程（`looks_like_bridge` 是第一道闸，这里是第二道）。
    """
    try:
        if os.path.exists(PID_FILE) and Path(PID_FILE).read_text().strip() == str(os.getpid()):
            os.remove(PID_FILE)
    except Exception:
        pass


def cleanup_on_exit(reason: str) -> None:
    """退出收尾（Ctrl+C、正常结束、解释器退出都会走这里）：清 PID 文件 + 收掉本桥拉起的 DSH。

    ★ Ctrl+C 本身已经会送到 DSH（见 `start_dsh_process` 的注释），这里只是**兜底**：
      万一 DSH 自己装了 SIGINT 处理器不肯退、或者桥是被 taskkill/崩溃弄死的，就用这里收掉。
      只动 `SPAWNED_DSH_PIDS` 里的（= 本桥亲手拉起的），不碰别人的 DSH。
    """
    release_pid_file()
    while SPAWNED_DSH_PIDS:
        pid = SPAWNED_DSH_PIDS.pop()
        if not pid_alive(pid):
            continue
        if not looks_like_dsh(pid):        # 认不出就别动（防 PID 复用误杀）
            continue
        LOG.info("收尾（%s）：结束本桥拉起的 DSH pid=%s", reason, pid)
        kill_and_wait(pid)
    # 还留在 3080 上的，说明不是本桥拉起的 —— 说清楚，别让人以为"没退干净"
    for pid in find_port_pids(DSH_TARGET_PORT):
        if pid != os.getpid():
            LOG.warning("3080 上还有别人的 DSH（pid=%s），没动它", pid)


def ensure_single_instance() -> None:
    """启动前接管：优先按 PID 文件杀掉上一个 dsh，再以端口兜底，最后写自己的 PID。"""
    # 1) PID 文件精确接管
    if os.path.exists(PID_FILE):
        try:
            old_pid = int(Path(PID_FILE).read_text().strip())
        except Exception:
            old_pid = None
        if old_pid and old_pid != os.getpid() and pid_alive(old_pid):
            if looks_like_bridge(old_pid):
                LOG.warning("接管：结束旧实例 pid=%s", old_pid)
                kill_and_wait(old_pid)
            else:
                LOG.warning("PID 文件里的 pid=%s 不是 dsh 桥，不接管它", old_pid)

    # 2) 端口兜底（PID 文件失效/缺失时，8788 被占则杀占用者）
    for pid in find_port_pids(SETUP_PORT):
        if pid == os.getpid():
            continue
        if looks_like_bridge(pid):          # 同样先认进程，别杀错
            LOG.warning("接管：结束占用端口 %s 的 pid=%s", SETUP_PORT, pid)
            kill_and_wait(pid)
        else:
            LOG.warning("端口 %s 被不是 dsh 桥的 pid=%s 占着，不动它", SETUP_PORT, pid)

    # 2.5) 等端口释放（旧实例被杀后）
    if not wait_port_free(SETUP_PORT):
        LOG.warning("端口 %s 仍在占用，继续启动（绑定阶段会自动重试）", SETUP_PORT)

    # 3) 写入自己的 PID
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        Path(PID_FILE).write_text(str(os.getpid()))
    except Exception:
        pass


def spawn_daemon() -> int:
    """--daemon：转为后台守护运行（pythonw 无窗口，日志写 dsh.log）。"""
    log_path = os.path.join(DATA_DIR, "dsh.log")
    # 无窗口解释器：优先用**当前运行时自己的** pythonw.exe —— 自带运行时
    # (system/runtimes/python/3.12) 里就有一个，依赖 aiohttp/httpx/websockets 也齐。
    # 旧代码写死的是旧项目那台 venv 里的 pythonw.exe，迁移后它指向外面、
    # 别人机器上根本没有 —— 所以降级成兜底（老宿主下行为不变）。
    # 无窗口解释器（三级，`P-15`）：① 环境变量 DSH_PYTHONW
    #                              ② 当前运行时同目录的 pythonw.exe（自带运行时里就有）
    #                              ③ 老项目的 ZeEn venv —— 仅当它存在才用（兜底）
    venv_py = os.environ.get("DSH_PYTHONW") or ""
    if not (venv_py and os.path.isfile(venv_py)):
        venv_py = os.path.join(os.path.dirname(sys.executable or ""), "pythonw.exe")
    if not os.path.isfile(venv_py):
        _legacy_pw = r"D:\python\wwwroot\ZeEn\venv\Scripts\pythonw.exe"
        if os.path.isfile(_legacy_pw):
            LOG.warning("没有 pythonw.exe，退回 ZeEn venv: %s", _legacy_pw)
            venv_py = _legacy_pw
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(log_path, "ab") as errf:
            subprocess.Popen(
                [venv_py, os.path.join(TOOL_DIR, "main.py"), "--no-browser"],
                creationflags=flags, close_fds=True,
                stdin=subprocess.DEVNULL, stdout=errf, stderr=subprocess.STDOUT,
            )
    except Exception as exc:
        print(f"[dsh] 后台启动失败: {exc}")
        return 1
    print(f"[dsh] 已在后台运行（日志: {log_path}），停止：taskkill /F /PID 或杀 8788 进程")
    return 0


# ---- 3080 监护：DSH 本体不在就跑起来，被关闭自动重启 ----
DSH_TARGET_PORT = 3080
DSH_START_COOLDOWN = 30   # 启动冷却（秒），避免启动失败时每 5 秒刷命令
DSH_3080_LOG = os.path.join(DATA_DIR, "dsh3080.log")
# DSH_CWD（拉起 DSH 本体时的工作目录）不在这里写死 —— 见下面 DSH_LAUNCHERS
# 之后的 _dsh_cwd()：它要从探测到的启动器反推，所以只能等探测完再算。


def find_dsh_launchers() -> list:
    """动态探测 DSH 启动命令（可移植，不写死机器路径）：
    1) node.exe + npx 缓存里的 dsh bin.js（最常见）
    2) node.exe + npm 全局安装的 dsh
    3) npx（PATH 里有则用，shell 执行兼容 .cmd）"""
    cmds = []
    node = shutil.which("node")
    if node:
        # 1) npx 缓存：%LOCALAPPDATA%\npm-cache\_npx\<hash>\node_modules\@deepseek-ai\dsh\lib\bin.js
        found = []
        cache_root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "npm-cache", "_npx")
        if os.path.isdir(cache_root):
            found += glob.glob(os.path.join(cache_root, "*", "node_modules",
                                            "@deepseek-ai", "dsh", "lib", "bin.js"))
        # 2) 全局安装：%APPDATA%\npm\node_modules\@deepseek-ai\dsh\lib\bin.js
        global_bin = os.path.join(os.environ.get("APPDATA", ""), "npm",
                                  "node_modules", "@deepseek-ai", "dsh", "lib", "bin.js")
        if os.path.exists(global_bin):
            found.append(global_bin)
        if found:
            found.sort(key=os.path.getmtime, reverse=True)
            cmds.append([node, found[0], "web"])
    # 3) npx 兜底
    if shutil.which("npx"):
        cmds.append(["npx", "@deepseek-ai/dsh", "web"])
    # 最后兜底（依赖 PATH，尽力而为）
    cmds.append(["npx", "@deepseek-ai/dsh", "web"])
    return cmds


DSH_LAUNCHERS = find_dsh_launchers()


def _dsh_cwd() -> str:
    r"""拉起 DSH 本体时，用哪个目录当它的工作目录（= DSH 那边看到的"工作区"）。

    旧代码写死成这台机器上 DSH 的检出目录（`D:\soft\deepseek-harness`，**本机就是靠它**）。
    写死在别人机器上就跑不起来，所以改成三级，**本机行为一个字不变**：
      ① 环境变量 `DSH_BRIDGE_CWD`（想固定工作区就设它 —— 这是最明确的做法）
      ② 老路径还存在 → 就用它（本机命中这一条，和迁移前完全一样）
      ③ 都没有 → 从探测到的 DSH 启动器反推它自己的安装目录（可移植兜底）

    注意 ③ 的含义：它给的是「DSH 装在哪」，**不一定**是「你想让它以哪个目录为工作区」。
    所以换到别的机器上，建议用 ① 明确指定，别指望 ③ 猜对。
    """
    env = os.environ.get("DSH_BRIDGE_CWD")
    if env and os.path.isdir(env):
        LOG.info("DSH 工作目录 = %s（来自环境变量 DSH_BRIDGE_CWD）", env)
        return env
    legacy = r"D:\soft\deepseek-harness"
    if os.path.isdir(legacy):
        # 这台机器上 DSH 的检出目录；**本机就走这一条**，行为与迁移前一致。
        return legacy
    # ③ 别人机器上的兜底：用「你敲 moss :dsh 时所在的那个目录」。
    #    为什么不从启动器反推：那会得到 node_modules\@deepseek-ai\dsh 这种安装目录，
    #    拿它当工作区既怪又难找；而「我在哪个目录启动的」是命令行工具的通用直觉。
    cwd = os.getcwd()
    LOG.info("DSH 工作目录 = %s（当前目录）", cwd)
    return cwd


DSH_CWD = _dsh_cwd()


def port_alive(port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


#: 本桥**亲自**拉起来的 DSH 进程 pid。退出时要把它们收掉（见 cleanup_on_exit），
#: 但绝不会去动"别的桥留下的"或"你手动起的" DSH —— 那些不在这个表里。
SPAWNED_DSH_PIDS: list = []


def start_dsh_process() -> None:
    """启动 DSH 本体（日志进 dsh3080.log）。

    ★ 这里**故意不加** `CREATE_NEW_PROCESS_GROUP`（2026-09-27 按你的要求改）：
      带上它，子进程会**免疫 Ctrl+C** —— 于是你按 Ctrl+C 只停掉桥，DSH 还在后台跑、
      网页照样打得开，看起来就是"没退出"（这就是你遇到的那个现象）。
      去掉之后，Ctrl+C 会同时送到 DSH，node 收到就退出 —— **一次 Ctrl+C 全部干净退出**。
      （stdout 仍然写进日志文件，所以去掉这个标志不会让 DSH 的输出刷到终端上。）
    """
    for cmd in DSH_LAUNCHERS:
        try:
            if not os.path.exists(cmd[0]):
                continue
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(DSH_3080_LOG, "ab") as logf:
                proc = subprocess.Popen(
                    cmd, cwd=DSH_CWD,
                    stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
                )
            SPAWNED_DSH_PIDS.append(proc.pid)
            LOG.warning("已发出 DSH 启动命令: %s %s (pid=%s)",
                        cmd[0], cmd[1] if len(cmd) > 1 else "", proc.pid)
            return
        except Exception as exc:
            LOG.warning("启动 DSH 失败(%s): %s", cmd[0], exc)


def process_image_name(pid: int) -> str:
    """取进程镜像名（tasklist）。取不到返回空串。"""
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=15).stdout
    except Exception as exc:
        LOG.warning("tasklist 查 pid %s 失败: %s", pid, exc)
        return ""
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    if not lines:
        return ""
    return lines[0].split(",")[0].strip().strip('"').lower()


def process_cmdline(pid: int) -> str:
    """取进程命令行（PowerShell CIM，尽力而为）。取不到返回空串。"""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f'(Get-CimInstance Win32_Process -Filter "ProcessId={pid}").CommandLine'],
            capture_output=True, text=True, timeout=25).stdout
        return (out or "").strip()
    except Exception as exc:
        LOG.warning("取 pid %s 的命令行失败: %s", pid, exc)
        return ""


def looks_like_dsh(pid: int) -> bool:
    """3080 上那个进程是不是 DSH 本体。**拿不准就返回 False（宁可不动手）。**

    ★ 为什么非要先确认：3080 上跑的也可能是别的东西，或者是你**自己手动起的** DSH。
      杀错进程比"远端 401"严重得多 —— 所以只认正面证据：镜像名是 node.exe，
      并且命令行里出现 dsh 或 bin.js（取不到命令行就直接判 False，不动手）。
    """
    name = process_image_name(pid)
    if name != "node.exe":
        LOG.warning("pid %s 不是 node.exe（%r），不当 DSH 处理", pid, name or "取不到")
        return False
    cmd = process_cmdline(pid)
    low = cmd.lower()
    if not low:
        LOG.error("pid %s 取不到命令行，无法确认是 DSH，不动手", pid)
        return False
    if ("dsh" not in low) and ("bin.js" not in low):
        LOG.warning("pid %s 的命令行里没有 dsh/bin.js，不当 DSH 处理", pid)
        return False
    return True


def ancestor_pids(pid: int, limit: int = 20) -> set:
    """从 pid 往上找出它的**所有祖先进程**。

    用途只有一个（`P-17`）：判断「3080 上那个 DSH 是不是我自己所在的这棵树」。
    因为 DSH 可能是被**我们自己的父进程**拉起来的 —— 典型场景就是你在 DSH 自己开出来的
    终端里敲 `moss :dsh`，这时杀掉 3080 会把**你自己这个会话**一起断掉。

    实现：一条 PowerShell 命令一次走完父链（比每层单独调一次 CIM 快得多）。
    取不到就返回空集合 —— 那种情况下当作"不是祖先"（不误伤正常路径），
    但别的守卫（认进程、看端口）仍然在。
    """
    script = ('$p = %d; for ($i = 0; $i -lt %d; $i++) { '
              '$q = (Get-CimInstance Win32_Process -Filter "ProcessId=$p" '
              '-ErrorAction SilentlyContinue).ParentProcessId; '
              'if (-not $q) { break }; Write-Output $q; $p = $q }' % (pid, limit))
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                             capture_output=True, text=True, timeout=25).stdout
    except Exception as exc:
        LOG.warning("取祖先进程失败: %s", exc)
        return set()
    pids = set()
    for ln in (out or "").splitlines():
        s = ln.strip()
        if s.isdigit():
            pids.add(int(s))
    return pids


def restart_dsh(reason: str) -> bool:
    """结束 3080 上那个 DSH 并等端口释放。返回「端口确实空出来了」。

    ★ 为什么要杀它重拉：DSH 的会话令牌是**每次进程启动随机生成、绝不持久化**的，
      它只带 ?token= 打到"拉起它的那个进程"的 stdout（也就是本桥的 dsh3080.log）。
      所以 3080 上那个 DSH 若不是本桥拉起来的（上一个桥、或旧项目的桥留下的），
      本桥**永远换不到 cookie**，转发一律 401 —— 除了杀掉重拉没有别的办法。

    ★ 本地网页会闪断几秒：DSH 一停，你浏览器里那个页面就断了；监护会在下一轮
      （最多 5 秒）把它重新拉起来，刷新页面即可。会话落在磁盘上，不会丢。
    """
    pids = [p for p in find_port_pids(DSH_TARGET_PORT) if p != os.getpid()]
    if not pids:
        return True
    LOG.info("清掉 3080 上的旧 DSH: pid=%s", pids)
    killed = False
    # ★ 自保（`P-17`）：如果 3080 上那个 DSH 是**本进程的祖先**，说明我们正跑在它里面
    #   （比如你在 DSH 自己开出来的终端/会话里敲 `moss :dsh`）—— 杀掉它会把你自己
    #   这个会话一起断掉（实测：2026-09-27 我就在这上面栽了两次）。这种一律跳过。
    my_ancestors = ancestor_pids(os.getpid())
    for pid in pids:
        if pid in my_ancestors:
            LOG.error("3080 上的 DSH 是本进程的祖先（pid=%s），跳过不杀；"
                      "要重启请换独立窗口跑", pid)
            continue
        if looks_like_dsh(pid):
            kill_and_wait(pid)
            killed = True
    if not killed:
        LOG.error("3080 上那个进程不是 DSH，没动它（远端会 401，请自己处理）")
        return False
    if not wait_port_free(DSH_TARGET_PORT, timeout=8.0):
        LOG.warning("3080 还没释放")
        return False
    return True


async def watch_3080(bridge: "Bridge") -> None:
    """每 5 秒探测 3080；不在运行则拉起（带 30 秒启动冷却）。

    同时在端口刚变为存活时主动交换一次 DSH 会话 cookie：DSH 每次启动都会换
    新的进程令牌，而桥的转发必须带上对应 cookie，否则一律 401。这里先换好，
    首个隧道请求就不用先吃一次 401 再重试。
    """
    LOG.info("3080 监护已启动（每 5 秒探测，异常自动拉起）")
    last_start = 0.0
    was_alive = False
    restarted = False        # ★ 本次运行只自动重启一次 DSH，免得和监护互相打架
    while True:
        alive = port_alive(DSH_TARGET_PORT)
        if not alive:
            was_alive = False
            now = time.time()
            if now - last_start >= DSH_START_COOLDOWN:
                LOG.warning("检测到 DSH(%s) 未运行，自动启动中...", DSH_TARGET_PORT)
                start_dsh_process()
                last_start = now
        elif not was_alive:
            was_alive = True
            # DSH 启动后要等 webserver 绑定并打印 token 行，故重试数次。
            token_ok = False
            for attempt in range(6):
                if await bridge.dsh_auth.refresh(bridge.http):
                    token_ok = True
                    break
                await asyncio.sleep(1.0)
            if token_ok:
                pass
            elif not restarted:
                # ── 换不到 cookie：说明 3080 上那个 DSH **不是本桥拉起来的** ──
                # 令牌每次启动随机生成、绝不持久化，只打在拉起它的那个桥的日志里；
                # 本桥拿不到 → 转发必然 401（本地网页不受影响，走的是它自己的 cookie）。
                # 唯一的解法就是杀掉它、让本桥自己重新拉一个（新令牌会进本桥的日志）。
                restarted = True
                if restart_dsh("换不到 DSH 会话 cookie，说明它不是本桥拉起的"):
                    last_start = 0.0        # 跳过启动冷却，下一轮立刻拉新的
                    was_alive = False       # 让下一轮走"不在运行 → 拉起"那条路
            else:
                LOG.warning("未能取到 DSH 会话 cookie，将在收到 401 时重试")
        await asyncio.sleep(5)


def _moss_args():
    """从宿主环境变量里取「包参数」（写法照抄 system/pkgs/exec/main.py 的 _moss_args）。

    moss 宿主**不会**把用户参数塞进 sys.argv（core/cli.py build_pkg_inv 里
    args 恒为 []），参数按 pkg.json 的 params 解析好，以 JSON 放进
    MOSS_PKG_PARAMS；MOSS_ARGS 是原始串（包调用时通常是空串）。
    有就返回切好的参数表，没有返回 None —— 那就走原来的 sys.argv 逻辑，
    所以 `python main.py --status` 这种直接调试照旧能用。
    """
    # ★ 只有"宿主确实给了参数"才算数：**空串要当成没给**，继续往下走、最后退回
    #   sys.argv。踩过的坑（2026-09-27）：moss 起子进程时会注入 MOSS_PKG_PARAMS，
    #   而 DSH 自己是被桥拉起来的 —— 于是**整个 DSH 会话树里都留着这个变量**
    #   （值通常是 {"args": ""}）。旧写法在这里直接返回 []（空列表 = "宿主说了，
    #   没有参数"），于是 sys.argv 永远轮不到：在 DSH 会话里直接跑
    #   `python main.py --help` 会被当成"无参数"→ 前台启动桥。
    raw = os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            got = str(json.loads(raw).get("args") or "").strip()
            if got:
                return got.split()
        except Exception:
            pass
    raw = (os.environ.get("MOSS_ARGS") or "").strip()
    if raw:
        return raw.split()
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="dsh-bridge 本机桥")
    parser.add_argument("--set-token", action="store_true", help="更换 zeen token（粘贴模式）")
    parser.add_argument("--set-password", action="store_true", help="更换二级密码（命令行模式）")
    parser.add_argument("--status", action="store_true", help="查看配置摘要")
    parser.add_argument("--no-browser", action="store_true", help="启动时不自动打开设置页")
    parser.add_argument("--daemon", action="store_true", help="转为后台守护运行（无窗口，日志写 dsh.log）")
    parser.add_argument("--restart-dsh", action="store_true",
                        help="启动前先结束 3080 上的 DSH，让本桥重新拉起一个"
                             "（默认启动时就会这么做；这个开关只是写明确）")
    # 参数来源：优先宿主环境变量，读不到再退回 argv（= 原来的行为）
    host_args = _moss_args()
    args = parser.parse_args(host_args if host_args is not None else None)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        handlers=[logging.StreamHandler(sys.stdout)])

    if args.set_token:
        return cmd_set_token()
    if args.set_password:
        return cmd_set_password()
    if args.status:
        return cmd_status()

    # --daemon：转为后台守护后返回（pythonw 无窗口，日志进 dsh.log）
    if args.daemon:
        return spawn_daemon()

    # 默认前台运行：日志直接在终端可见，Ctrl+C 停止
    # （spawn_daemon 拉起的实例也走这里——pythonw 无终端，等效后台常驻）
    # ★ 每次启动都先清掉 3080 上的旧 DSH（`P-14`）：
    #   DSH 的会话令牌**每次进程启动随机生成、绝不持久化**，只带 ?token= 打进
    #   "拉起它的那个进程"的日志。3080 上那个若不是本桥拉起来的（上一个桥、旧项目的桥、
    #   或你自己手动起的），本桥永远换不到 cookie，隧道请求一律 401。
    #   与其去分辨归属，不如每次都用本桥自己拉起来的那个 —— 代价是本地 DSH 网页闪断
    #   几秒（会话落在磁盘上，不会丢），监护最多 5 秒内把它拉回来。
    #   `--restart-dsh` 因此成了"同义开关"（保留：写明确、也方便脚本里表达意图）。
    #   守卫仍然在：认不出那个进程是 DSH（镜像名/命令行）就只报错、绝不动手。
    restart_dsh("启动时先清掉 3080 上的旧 DSH")
    ensure_single_instance()

    # 退出收尾：不管怎么退（Ctrl+C、正常结束、异常），都要清 PID 文件 + 收掉自己拉起的 DSH。
    # atexit 是兜底（正常返回/异常退出都会跑到），下面两条是让日志里能看出"是哪条路退的"。
    atexit.register(cleanup_on_exit, "解释器退出")

    try:
        bridge = Bridge(load_config())
        asyncio.run(_serve_setup(bridge, args.no_browser))
        cleanup_on_exit("正常运行结束")
    except KeyboardInterrupt:
        LOG.info("stopped（Ctrl+C）")
        cleanup_on_exit("Ctrl+C")
    except Exception as exc:
        LOG.exception("运行异常退出: %s", exc)
        cleanup_on_exit("异常退出")
    return 0


async def _serve_setup(bridge: Bridge, no_browser: bool) -> None:
    """启动本地设置向导 + （配置齐全时）自动连接。"""
    setup = SetupServer(bridge)
    runner = web.AppRunner(setup.app, access_log=None)  # 关闭 aiohttp 访问日志，避免刷屏
    await runner.setup()
    # 绑定 8788：失败自动重试（接管后端口可能未完全释放）
    site = None
    for attempt in range(5):
        try:
            site = web.TCPSite(runner, "127.0.0.1", SETUP_PORT)
            await site.start()
            break
        except OSError as exc:
            LOG.warning("8788 绑定失败(%s)，%s 秒后重试 (%s/5)", exc, attempt + 1, attempt + 1)
            await asyncio.sleep(1 + attempt)
    if site is None:
        raise RuntimeError(f"端口 {SETUP_PORT} 绑定失败（被占用）")
    LOG.info("桥设置向导: http://127.0.0.1:%s/", SETUP_PORT)

    # 3080 监护：DSH 本体不在就跑起来，被关闭自动重启
    asyncio.create_task(watch_3080(bridge))

    cfg = load_config()
    if cfg.get("token") and cfg.get("password"):
        LOG.info("配置齐全，自动连接 %s", cfg.get("server"))
        bridge.start_connecting()
    elif not no_browser:
        webbrowser.open(f"http://127.0.0.1:{SETUP_PORT}/")
        LOG.info("未完成配置：已打开设置向导，请依次完成 1服务器 2密码 3登录 4连接")

    await asyncio.Event().wait()


if __name__ == "__main__":
    sys.exit(main())
