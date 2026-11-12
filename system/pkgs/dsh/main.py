import sys

try:
    import aiohttp
    import httpx
    import websockets
except ImportError:
    import os
    import subprocess
    if os.environ.get("MOSS_PLUGIN_DATA_DIR"):
        raise
    _DIR = ""
    for _p in sys.path:
        if _p and os.path.isdir(_p) and os.path.exists(os.path.join(_p, "main.py")):
            _DIR = _p
            break
    if not _DIR:
        _DIR = os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()
    _THIS = os.path.join(_DIR, "main.py")
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

SETUP_PORT = 8788

DATA_DIR = (os.environ.get("MOSS_PLUGIN_DATA_DIR")
            or os.environ.get("PA_PLUGIN_DATA_DIR")
            or os.path.join(os.environ.get("MOSS_HOME") or os.path.expanduser("~"),
                            "user_data", "state", "dsh"))

CONFIG_PATH = Path(DATA_DIR) / "dsh_bridge.json"

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_DKLEN = 64

DEFAULT_TARGET = "http://127.0.0.1:3080"

DSH_TOKEN_RE = re.compile(r"dsh web:\s*http://\S*[?&]token=([A-Za-z0-9_-]+)")
DSH_LOG_TAIL_BYTES = 262144

SETUP_PORT = 8788

CONFIG_PATH = Path(DATA_DIR) / "dsh_bridge.json"

FILE_FETCH_PATH = "/file.fetch"

FILE_VIEW_PATH = "/file.view"
FILE_VIEWER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "file_viewer.html")
FILE_VIEWER_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "viewer")

VIEW_TEXT_EXT = {
    "txt", "md", "markdown", "json", "csv", "log", "xml", "yml", "yaml",
    "html", "htm", "css", "js", "mjs", "ts", "tsx", "jsx", "py", "sh", "bat",
    "ps1", "ini", "conf", "toml", "sql", "gitignore", "env",
}
VIEW_IMAGE_EXT = {"png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico", "avif"}
VIEW_TEXT_LIMIT = 1 * 1024 * 1024
VIEW_IMAGE_LIMIT = 12 * 1024 * 1024

FILE_CHUNK = 4 * 1024 * 1024

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

FILE_INLINE_EXT = {
    "pdf", "png", "jpg", "jpeg", "gif", "webp", "svg", "bmp", "ico",
    "mp4", "webm", "mp3", "wav", "ogg", "m4a",
    "html", "htm",
}

def file_roots() -> list:
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
    if child == root:
        return True
    return child.startswith(root.rstrip("\\/") + os.sep)

def resolve_file_request(raw_path: str):
    target = str(raw_path).strip().strip('"')
    if not target:
        return None
    roots = file_roots()
    if not roots:
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
    value = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"

def html_escape(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

def build_view_page(absolute: str, request_path: str) -> bytes:
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
    return set_cookie.split(";", 1)[0].strip()

class CookieAuth:
    def __init__(self, target: str):
        self.target = target.rstrip("/")
        self.cookie: str | None = None
        self.token: str | None = None

    def apply(self, headers: dict) -> None:
        if not self.cookie:
            return
        existing = headers.get("cookie") or headers.get("Cookie")
        headers["cookie"] = f"{existing}; {self.cookie}" if existing else self.cookie

    def has_cookie(self, headers: dict) -> bool:
        if not self.cookie:
            return False
        name = self.cookie.split("=", 1)[0]
        raw = headers.get("cookie") or headers.get("Cookie") or ""
        return name in raw

    def set_cookie_header(self, max_age_days: int = 30) -> str | None:
        if not self.cookie:
            return None
        parts = [self.cookie, "Path=/", f"Max-Age={max_age_days * 24 * 3600}", "HttpOnly", "SameSite=Strict"]
        return "; ".join(parts)

    def _latest_token(self) -> str | None:
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
        token = self._latest_token()
        if token is None:
            return self.cookie is not None
        if not force and token == self.token and self.cookie is not None:
            return True
        owned = http is None
        client = http or httpx.AsyncClient(timeout=httpx.Timeout(10.0), trust_env=False,
                                           follow_redirects=False)
        try:
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

DECODED_ENTITY_HEADERS = {"content-encoding", "content-length"}

def _find_tool_dir() -> str:
    for _p in sys.path:
        if _p and os.path.isdir(_p) and os.path.exists(os.path.join(_p, "main.py")):
            return _p
    return os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else ""

TOOL_DIR = _find_tool_dir()

DHSR_DIR = TOOL_DIR

def _load_page(name: str) -> str:
    path = os.path.join(DHSR_DIR, name)
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception as exc:
        print(f"[dsh] 页面文件缺失: {path} ({exc})")
        return "<h1>页面文件缺失</h1>"

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

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))

def save_config(cfg: dict) -> None:
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
        self.dsh_auth = CookieAuth(str(cfg.get("target", DEFAULT_TARGET)))
        self.ws = None
        self.connected = False
        self._connect_task: asyncio.Task | None = None
        self._http: httpx.AsyncClient | None = None
        self._pending: dict[str, dict] = {}
        self._ws_conns: dict[str, object] = {}

    def start_connecting(self) -> None:
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
        req_id = msg.get("id")
        method = str(msg.get("method", "GET")).upper()
        path = msg.get("path") or "/"
        headers = msg.get("headers") or {}
        kind = "auth" if (method == "POST" and path.startswith(AUTH_PATH)) else "tunnel"
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
                    part = await asyncio.to_thread(fh.read, FILE_CHUNK)
                    if not part:
                        break
                    sent += len(part)
                    blocks += 1
                    await self.send({"type": "tunnel_http_chunk", "id": req_id,
                                     "dataBase64": base64.b64encode(part).decode("ascii")})
        except Exception as exc:
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
        if status == 401:
            LOG.info("转发收到 401，重取 DSH 会话 cookie 后重试: %s %s", method, path)
            if await self.dsh_auth.refresh(self.http, force=True):
                headers = self._forward_headers(entry)
                await self._send_http(req_id, method, target, headers, body)
            else:
                LOG.warning("重取 DSH 会话 cookie 失败，%s %s 仍为 401", method, path)

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
        asyncio.create_task(self._ws_pump_up(req_id, ws))

    async def _ws_pump_up(self, req_id: str, ws) -> None:
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

BRIDGE_WS_PATH = "/dsh/bridge/ws"

_IP4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}")

def _looks_like_ip(host: str) -> bool:
    host = host.split(":")[0].strip()
    return host == "localhost" or host.startswith("127.") or bool(_IP4_RE.match(host))

def normalize_server(raw: str) -> str:
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
    s = normalize_server(server)
    if s.endswith(BRIDGE_WS_PATH):
        return s
    return s.rstrip("/") + BRIDGE_WS_PATH

def ws_to_http(ws_url: str) -> str:
    base = normalize_server(ws_url).replace("wss://", "https://").replace("ws://", "http://")
    if base.endswith(BRIDGE_WS_PATH):
        base = base[: -len(BRIDGE_WS_PATH)]
    return base

class SetupServer:
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

PID_FILE = os.path.join(DATA_DIR, "dsh.pid")

def pid_alive(pid: int) -> bool:
    try:
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                             capture_output=True, text=True, timeout=10).stdout
        return f"PID {pid}" in out or str(pid) in out
    except Exception:
        return False

def find_port_pids(port: int) -> list[int]:
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
    t0 = time.time()
    while time.time() - t0 < timeout:
        if not find_port_pids(port):
            return True
        time.sleep(0.3)
    return False

def looks_like_bridge(pid: int) -> bool:
    cmd = process_cmdline(pid).lower()
    if not cmd:
        return False
    return ("dsh" in cmd) and (("main.py" in cmd) or ("bootstrap.py" in cmd))

def release_pid_file() -> None:
    try:
        if os.path.exists(PID_FILE) and Path(PID_FILE).read_text().strip() == str(os.getpid()):
            os.remove(PID_FILE)
    except Exception:
        pass

def cleanup_on_exit(reason: str) -> None:
    release_pid_file()
    while SPAWNED_DSH_PIDS:
        pid = SPAWNED_DSH_PIDS.pop()
        if not pid_alive(pid):
            continue
        if not looks_like_dsh(pid):
            continue
        LOG.info("收尾（%s）：结束本桥拉起的 DSH pid=%s", reason, pid)
        kill_and_wait(pid)
    for pid in find_port_pids(DSH_TARGET_PORT):
        if pid != os.getpid():
            LOG.warning("3080 上还有别人的 DSH（pid=%s），没动它", pid)

def ensure_single_instance() -> None:
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

    for pid in find_port_pids(SETUP_PORT):
        if pid == os.getpid():
            continue
        if looks_like_bridge(pid):
            LOG.warning("接管：结束占用端口 %s 的 pid=%s", SETUP_PORT, pid)
            kill_and_wait(pid)
        else:
            LOG.warning("端口 %s 被不是 dsh 桥的 pid=%s 占着，不动它", SETUP_PORT, pid)

    if not wait_port_free(SETUP_PORT):
        LOG.warning("端口 %s 仍在占用，继续启动（绑定阶段会自动重试）", SETUP_PORT)

    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        Path(PID_FILE).write_text(str(os.getpid()))
    except Exception:
        pass

def spawn_daemon() -> int:
    log_path = os.path.join(DATA_DIR, "dsh.log")
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

DSH_TARGET_PORT = 3080
DSH_START_COOLDOWN = 30
DSH_3080_LOG = os.path.join(DATA_DIR, "dsh3080.log")

def find_dsh_launchers() -> list:
    cmds = []
    node = shutil.which("node")
    if node:
        found = []
        cache_root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "npm-cache", "_npx")
        if os.path.isdir(cache_root):
            found += glob.glob(os.path.join(cache_root, "*", "node_modules",
                                            "@deepseek-ai", "dsh", "lib", "bin.js"))
        global_bin = os.path.join(os.environ.get("APPDATA", ""), "npm",
                                  "node_modules", "@deepseek-ai", "dsh", "lib", "bin.js")
        if os.path.exists(global_bin):
            found.append(global_bin)
        if found:
            found.sort(key=os.path.getmtime, reverse=True)
            cmds.append([node, found[0], "web"])
    if shutil.which("npx"):
        cmds.append(["npx", "@deepseek-ai/dsh", "web"])
    cmds.append(["npx", "@deepseek-ai/dsh", "web"])
    return cmds

DSH_LAUNCHERS = find_dsh_launchers()

def _dsh_cwd() -> str:
    env = os.environ.get("DSH_BRIDGE_CWD")
    if env and os.path.isdir(env):
        LOG.info("DSH 工作目录 = %s（来自环境变量 DSH_BRIDGE_CWD）", env)
        return env
    legacy = r"D:\soft\deepseek-harness"
    if os.path.isdir(legacy):
        return legacy
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

SPAWNED_DSH_PIDS: list = []

def start_dsh_process() -> None:
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
    pids = [p for p in find_port_pids(DSH_TARGET_PORT) if p != os.getpid()]
    if not pids:
        return True
    LOG.info("清掉 3080 上的旧 DSH: pid=%s", pids)
    killed = False
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
    LOG.info("3080 监护已启动（每 5 秒探测，异常自动拉起）")
    last_start = 0.0
    was_alive = False
    restarted = False
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
            token_ok = False
            for attempt in range(6):
                if await bridge.dsh_auth.refresh(bridge.http):
                    token_ok = True
                    break
                await asyncio.sleep(1.0)
            if token_ok:
                pass
            elif not restarted:
                restarted = True
                if restart_dsh("换不到 DSH 会话 cookie，说明它不是本桥拉起的"):
                    last_start = 0.0
                    was_alive = False
            else:
                LOG.warning("未能取到 DSH 会话 cookie，将在收到 401 时重试")
        await asyncio.sleep(5)

def _moss_args():
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

    if args.daemon:
        return spawn_daemon()

    restart_dsh("启动时先清掉 3080 上的旧 DSH")
    ensure_single_instance()

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
    setup = SetupServer(bridge)
    runner = web.AppRunner(setup.app, access_log=None)
    await runner.setup()
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
