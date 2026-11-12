import codecs
import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import conpty
except Exception as _e:
    conpty = None
    _CONPTY_IMPORT_ERR = repr(_e)
else:
    _CONPTY_IMPORT_ERR = ""

NO_WINDOW = 0x08000000
_SMOKE_TIMEOUT = 3.0
_SMOKE_MARK = "MOSS_TERM_SMOKE_OK"
_CP_MARK = "MOSS_CP_READY"
_CP_TIMEOUT = 3.0
_HISTORY_KEEP = 64 * 1024
_PIPE_ASCII_ONLY = ("管道兜底模式只认 ASCII 命令（cmd 没控制台时收到中文会卡死并退出）"
                    " —— 要敲中文请用真终端模式")
_CMD = "cmd.exe /Q"

def _oem_codec():
    try:
        cp = int(ctypes.windll.kernel32.GetOEMCP())
        return "cp%d" % cp if cp else "cp936"
    except Exception:
        return "cp936"

class _ConPtyBackend:
    mode = "conpty"

    def __init__(self, cols, rows, cwd, env):
        self.p = conpty.ConPty.spawn(_CMD, cols=cols, rows=rows, cwd=cwd, env=env)

    def write(self, text):
        return self.p.write(text)

    def drain(self):
        return self.p.read(0)

    def resize(self, cols, rows):
        return self.p.resize(cols, rows)

    def alive(self):
        return self.p.alive()

    def close(self):
        self.p.close()

class _PipeBackend:
    mode = "pipe"

    def __init__(self, cols, rows, cwd, env):
        self.proc = subprocess.Popen(
            ["cmd.exe", "/Q"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, cwd=cwd, env=env, bufsize=0,
            creationflags=NO_WINDOW)
        self._buf = []
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._eof = False
        self._cp_ready = False
        self._oem_tail = ""
        self._reader = threading.Thread(target=self._pump, name="moss-term-pipe",
                                        daemon=True)
        self._reader.start()
        self.write("chcp 65001>nul & echo %s\r\n" % _CP_MARK)

    def _push(self, text):
        if not text:
            return
        with self._cv:
            self._buf.append(text)
            self._cv.notify_all()

    def _pump(self):
        dec_utf8 = codecs.getincrementaldecoder("utf-8")("replace")
        dec_oem = codecs.getincrementaldecoder(_oem_codec())("replace")
        fd = self.proc.stdout.fileno()
        t0 = time.time()
        while True:
            try:
                chunk = os.read(fd, 65536)
            except (OSError, ValueError):
                chunk = b""
            if not chunk:
                break
            if not self._cp_ready:
                self._oem_tail += dec_oem.decode(chunk)
                if _CP_MARK in self._oem_tail:
                    self._cp_ready = True
                    self._oem_tail = ""
                    continue
                if time.time() - t0 > _CP_TIMEOUT:
                    self._cp_ready = True
                    self._push(self._oem_tail)
                    self._oem_tail = ""
                continue
            self._push(dec_utf8.decode(chunk))
        if self._oem_tail:
            self._push(self._oem_tail)
            self._oem_tail = ""
        else:
            self._push(dec_utf8.decode(b"", final=True))
        with self._cv:
            self._eof = True
            self._cv.notify_all()

    def write(self, text):
        if self.proc.poll() is not None:
            return False
        data = str(text)
        if data and not data.replace("\x03", "").strip():
            return False
        if not data:
            return True
        line = data.replace("\r\n", "\r").replace("\n", "\r").replace("\r", "\r\n")
        try:
            self.proc.stdin.write(line.encode("utf-8", "replace"))
            self.proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def drain(self):
        with self._cv:
            if not self._buf:
                return ""
            text = "".join(self._buf)
            self._buf.clear()
            return text

    def resize(self, cols, rows):
        return False

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        try:
            if self.proc.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=NO_WINDOW)
        except Exception:
            pass
        for h in (self.proc.stdin, self.proc.stdout):
            try:
                if h:
                    h.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            pass
        with self._cv:
            self._eof = True
            self._cv.notify_all()

def _shell_env(home):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    host = []
    try:
        import json
        raw = os.environ.get("MOSS_HOST_CMD") or ""
        parsed = json.loads(raw) if raw else None
        if isinstance(parsed, list):
            host = [str(x) for x in parsed]
    except Exception:
        host = []
    dirs = [d for d in (os.path.dirname(h) for h in host if h) if d]
    if home:
        dirs.append(str(home))
    if dirs:
        env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
    return env

def _pick_backend(cols, rows, cwd, env):
    forced = (os.environ.get("MOSS_TERM_BACKEND") or "").strip().lower()
    if forced == "pipe":
        return _PipeBackend, "按 MOSS_TERM_BACKEND=pipe 强制走管道模式。" + _PIPE_ASCII_ONLY
    if conpty is None:
        return _PipeBackend, ("取不到 conpty 模块（%s）。" % _CONPTY_IMPORT_ERR) + _PIPE_ASCII_ONLY
    ok, why = conpty.available()
    if not ok:
        return _PipeBackend, why + "。" + _PIPE_ASCII_ONLY
    if forced == "conpty":
        return _ConPtyBackend, "按 MOSS_TERM_BACKEND=conpty 强制走真终端"
    try:
        probe = conpty.ConPty.spawn('cmd.exe /Q /C "echo %s"' % _SMOKE_MARK,
                                    cols=cols, rows=rows, cwd=cwd, env=env)
    except OSError as e:
        return _PipeBackend, ("ConPTY 起不来（%s）。" % e) + _PIPE_ASCII_ONLY
    got = ""
    t0 = time.time()
    try:
        while time.time() - t0 < _SMOKE_TIMEOUT:
            got += probe.read(0.1)
            if _SMOKE_MARK in got:
                break
    finally:
        probe.close()
    if _SMOKE_MARK in got:
        return _ConPtyBackend, ""
    return _PipeBackend, ("这个环境里 ConPTY 读不到子进程输出（子进程确实挂上了，"
                          "但输出不进管道 —— 常见于嵌套伪控制台），已退回管道模式。"
                          + _PIPE_ASCII_ONLY)

class _Session:
    def __init__(self, cols, rows, cwd, home):
        self.cols, self.rows = cols, rows
        self.cwd, self.home = cwd, home
        self.lock = threading.Lock()
        self.backend = None
        self.mode = ""
        self.note = ""
        self.t0 = time.time()
        self.history = ""

    def open(self):
        env = _shell_env(self.home)
        cls, note = _pick_backend(self.cols, self.rows, self.cwd, env)
        self.mode, self.note = cls.mode, note
        self.backend = cls(self.cols, self.rows, self.cwd, env)
        return self

    def close(self):
        with self.lock:
            b, self.backend = self.backend, None
        if b is not None:
            try:
                b.close()
            except Exception:
                pass

    def write(self, text):
        b = self.backend
        if b is None:
            return False
        return b.write(text)

    def drain(self):
        b = self.backend
        out = ""
        if b is not None:
            try:
                out = b.drain() or ""
            except Exception:
                out = ""
        if out:
            self.history = (self.history + out)[-_HISTORY_KEEP:]
        return out

    def resize(self, cols, rows):
        self.cols, self.rows = cols, rows
        b = self.backend
        if b is None:
            return False
        try:
            return b.resize(cols, rows)
        except Exception:
            return False

    def alive(self):
        b = self.backend
        if b is None:
            return False
        try:
            return bool(b.alive())
        except Exception:
            return False

    def state(self):
        return {"ok": self.backend is not None, "mode": self.mode, "note": self.note,
                "alive": self.alive(), "cols": self.cols, "rows": self.rows,
                "pid": getattr(getattr(self.backend, "p", None), "pid", None)
                       or getattr(getattr(self.backend, "proc", None), "pid", None)}

_SESSION = None
_LOCK = threading.RLock()

def start(cols=100, rows=30, cwd=None, home=None):
    global _SESSION
    cols = max(20, min(500, int(cols or 100)))
    rows = max(5, min(200, int(rows or 30)))
    with _LOCK:
        if _SESSION is not None and _SESSION.alive():
            _SESSION.resize(cols, rows)
            st = _SESSION.state()
            st["fresh"] = False
            st["history"] = ""
            return st
        if _SESSION is not None:
            _SESSION.close()
            _SESSION = None
        s = _Session(cols, rows, str(cwd or home or os.getcwd()),
                     str(home or cwd or os.getcwd()))
        try:
            s.open()
        except Exception as e:
            return {"ok": False, "mode": "", "note": "起不来：%s" % e,
                    "alive": False, "fresh": True, "history": ""}
        _SESSION = s
        st = s.state()
        st["fresh"] = True
        st["history"] = s.history
        return st

def poll():
    with _LOCK:
        s = _SESSION
    if s is None:
        return {"ok": False, "out": "", "alive": False, "mode": "", "note": ""}
    out = s.drain()
    st = s.state()
    st.update({"out": out})
    return st

def run(cmdline):
    with _LOCK:
        s = _SESSION
    if s is None:
        return {"ok": False, "msg": "终端还没起"}
    line = str(cmdline or "").strip("\r\n")
    if not line.strip():
        return {"ok": False, "msg": "空命令"}
    ok = bool(s.write(line + "\r"))
    return {"ok": ok, "cmd": line, "mode": s.mode}

def write(text):
    with _LOCK:
        s = _SESSION
    if s is None:
        return {"ok": False, "msg": "终端还没起"}
    ok = bool(s.write(text))
    if not ok and s.mode == "pipe" and "\x03" in str(text):
        return {"ok": False, "mode": s.mode,
                "msg": "当前是简化终端，拦不了 Ctrl+C —— 想中断就切到真终端再按"}
    return {"ok": ok, "mode": s.mode}

def resize(cols, rows):
    with _LOCK:
        s = _SESSION
    if s is None:
        return {"ok": False, "msg": "终端还没起"}
    return {"ok": bool(s.resize(int(cols), int(rows)))}

def stop():
    global _SESSION
    with _LOCK:
        s, _SESSION = _SESSION, None
    if s is not None:
        s.close()
    return {"ok": True, "msg": "终端已结束"}

def state():
    with _LOCK:
        s = _SESSION
    if s is None:
        return {"ok": False, "mode": "", "note": "还没起过", "alive": False}
    return s.state()

if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:
        pass
    home = os.environ.get("MOSS_HOME") or str(_HERE.parent.parent)
    print("home =", home)
    st = start(100, 30, cwd=home, home=home)
    print("start ->", {k: v for k, v in st.items() if k != "history"})
    if not st.get("ok"):
        sys.exit(2)
    time.sleep(1.2)
    print("--- 启动输出 ---")
    print(repr(poll()["out"])[:600])

    write("echo TERM_ECHO_1\r")
    time.sleep(1.0)
    out1 = poll()["out"]
    print("--- echo 之后 ---")
    print(repr(out1)[:600])

    write("cd\r")
    time.sleep(0.8)
    out2 = poll()["out"]
    print("--- cd 之后（还活着就应该有提示符）---")
    print(repr(out2)[:400])

    st2 = state()
    write("echo 中文往返测试\r")
    time.sleep(0.9)
    out3 = poll()["out"]
    print("--- 中文那一句 ---")
    print(repr(out3)[:300])

    print("--- 判据 ---")
    print("模式：", st2["mode"], "| 备注：", st2["note"] or "（无）")
    print("① echo 有回显：", "TERM_ECHO_1" in (out1 + out2))
    print("② 第二条命令之后还活着（能接着敲）：", st2["alive"])
    print("③ cd 之后有输出（提示符回来了）：", bool(out2.strip()))
    print("④ 中文不乱码：", "中文往返测试" in out3,
          "" if st2["mode"] == "conpty" else "（管道兜底模式的**已知限制**，不是回退：%s）"
          % _PIPE_ASCII_ONLY)
    stop()
    print("收工")
