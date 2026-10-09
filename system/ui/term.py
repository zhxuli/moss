# -*- coding: utf-8 -*-
"""system/ui/term.py —— 界面那个**常驻的 DOS 终端会话**（`V-348`）。

它解决什么
----------
原来「命令行」那块不是终端：`main.py::run_input` 只是**某个正在跑的包**的 stdin 管子，
包一退出管子就废了 ⇒「一旦停止运行就没法继续执行 dos 命令」。这里给界面一个**自己的、
不会随命令结束而死掉**的 shell：它一直活着，命令跑完回到提示符，接着敲就行。

两个后端（一个首选、一个兜底）
------------------------------
* **`conpty`**（首选）：`conpty.py` 那个真伪控制台 ⇒ cmd 有自己的提示符、行编辑、
  Tab 补全菜单、F7 历史，Ctrl+C 也是**真的中断信号**，彩色程序照常发 ANSI。
* **`pipe`**（兜底）：普通管道跑一个 `cmd.exe /Q`，也是**常驻**的（命令跑完它不退），
  但管道给不了控制台：cmd 不回显、没有行编辑 ⇒ 那部分由**界面自己画**（本地回显 +
  行编辑），Tab 补全菜单和 Ctrl+C 就没了。

★ **为什么要兜底、而且是"自测出来"的兜底**：`CreatePseudoConsole` 只在 Win10 1809+
  有，而且**在"自己就是伪控制台客户端"的进程里（嵌套 ConPTY，比如各种 agent 的
  shell 会话里）实测读不到子进程输出** —— 那时真起了 pty、子进程也确实挂在上面
  （问它 `mode con` 报的就是我们给的尺寸），可输出就是不进管道。所以 `start()` 会先跑
  一次**冒烟自测**（起个 pty 跑 `echo 标记`），拿不到标记就老老实实退回管道模式，
  并把这句原因交给界面显示（`note`）——**不许静默降级**。
  想强制指定：环境变量 `MOSS_TERM_BACKEND=conpty|pipe`。

接口（给 `main.py` 的 Api 用）
-----------------------------
    term.start(cols, rows)     起会话（已经有了就直接用）。返回状态 dict
    term.poll()                取走**上次之后新产生**的输出（没有就给空串）
    term.write(text)           敲键盘（`\\r` 就是回车；管道后端会自己补成 `\\r\\n`）
    term.resize(cols, rows)    窗口变了说一声
    term.stop()                结束这个会话（下次再开会重新起）
    term.state()               现在什么状态（模式 / 还活着吗 / 原因）
"""
import codecs
import ctypes
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

# ★ 同目录的兄弟模块也得能 import（`V-87` 的老坑）：自带运行时是**便携/嵌入**版，
#   `sys.path` 来自 `python312._pth`，**不会**自动带上"脚本所在目录" ⇒ 直接 `python term.py`
#   跑自检时 `import conpty` 会报 No module named。main.py 里也有一模一样的一行。
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

try:
    import conpty
except Exception as _e:                                                # noqa: BLE001
    conpty = None
    _CONPTY_IMPORT_ERR = repr(_e)
else:
    _CONPTY_IMPORT_ERR = ""

NO_WINDOW = 0x08000000                                  # CREATE_NO_WINDOW
#: 冒烟自测最多等这么久（拿不到标记就当这个环境用不了 ConPTY）
_SMOKE_TIMEOUT = 3.0
_SMOKE_MARK = "MOSS_TERM_SMOKE_OK"
#: 管道后端用它把码页切到 UTF-8，切完 cmd 会重打一次提示符；标记之前那一坨整段丢掉
_CP_MARK = "MOSS_CP_READY"
_CP_TIMEOUT = 3.0
#: 会话最多留这么多历史给"刚打开/刚刷新"的界面（不然刷新一下终端就空了）
_HISTORY_KEEP = 64 * 1024
#: ★ 管道兜底模式的**固有限制**，必须让用户看见（不许静默）：
#:   `cmd.exe` 在**没有控制台**（纯管道）时收到**多字节**（中文）输入，会先卡在 `More? `
#:   等续行、紧接着**自己崩退**（第二次往里写就是 `OSError: Invalid argument` —— 管道已断）。
#:   实测四组都一样：`utf-8`/`gbk` 输入 × `chcp 65001`/默认 `cp936` ⇒ 全都这样。
#:   所以这不是我编码错了，是管道模式给不了"控制台输入"这件事。真终端（ConPTY）没这问题。
#:   影响面：界面自己敲的 `moss --pkg <id>` 命令行是 ASCII（除非 moss 装在中文路径下）；
#:   你**手敲中文命令**才会撞上 —— 撞上时 shell 会退出，界面会说"再点一次会重新起一个"。
_PIPE_ASCII_ONLY = ("管道兜底模式只认 ASCII 命令（cmd 没控制台时收到中文会卡死并退出）"
                    " —— 要敲中文请用真终端模式")
#: `cmd.exe` 不带 `/K` 就是交互式；`/Q` 关掉命令回显
_CMD = "cmd.exe /Q"


def _oem_codec():
    """这台机器的 OEM 码页编解码器（中文 Windows 上是 cp936）。

    ★ 为什么必须知道它：**管道的另一头是 cmd**，它内部命令（`dir`、提示符、横幅）的字节
      是按**控制台输出码页**编的，不是 UTF-8。按 UTF-8 硬解 ⇒ 满屏 `\\ufffd`。
      切到 65001 之前的那一段，只能按它解。
    """
    try:
        cp = int(ctypes.windll.kernel32.GetOEMCP())
        return "cp%d" % cp if cp else "cp936"
    except Exception:                                                  # noqa: BLE001
        return "cp936"



# ================================================================ 后端一：真伪控制台
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


# ================================================================ 后端二：管道（兜底）
class _PipeBackend:
    """常驻的 `cmd.exe`，走普通管道。

    ★ 也是"常驻"的：`cmd.exe /Q` 不接 `/C`，它会一直在那儿等下一行 —— 命令跑完**不退出**，
      所以"停下来还能继续敲"这件事在这里同样成立。
    ★ 首件事是把代码页切到 65001（UTF-8）：否则中文系统上管道里出来的是 GBK 字节，
      按 UTF-8 解就是乱码（这一条在中文 Windows 上是必然踩到的）。
    ★ 送进去的行要 `\\r\\n`：管道的另一端是"按行"读的，光给 `\\r` 它不认。
    """
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
        self._cp_ready = False          # 码页切到 UTF-8 了没有
        self._oem_tail = ""             # 切换之前那一段（按 OEM 码页解，先攒着）
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
        """读管道，**分两段解码**：切码页之前按 OEM，之后按 UTF-8。

        ★ 为什么值得这么麻烦：cmd 启动时会先吐两行中文横幅 + 一个提示符，那些字节是
          **OEM 码页（中文机器上 cp936）**的；`chcp 65001` 之后才是 UTF-8。一段用错就是
          满屏乱码 —— 而这正好是用户打开终端**第一眼**看到的内容。
        ★ 切换点靠一个 ASCII 哨兵（`echo 标记`）认：ASCII 在两种码页里字节相同，认不错。
          认到标记就把**标记之前那一整段丢掉**（横幅 + 老提示符 + 被回显的那条命令）——
          cmd 跑完 chcp 会**重新打一次提示符**，那一次已经是 UTF-8，干净。
        """
        dec_utf8 = codecs.getincrementaldecoder("utf-8")("replace")
        dec_oem = codecs.getincrementaldecoder(_oem_codec())("replace")
        fd = self.proc.stdout.fileno()
        t0 = time.time()
        while True:
            try:
                # ★ 用 os.read 直接读这个管道：**有多少给多少**（不会等 64KB 攒满）。
                #   换成 `pipe.read(n)` 会按 n 字节一次系统调用，输出一多就卡成幻灯片。
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
                    # 等不到标记（老系统？chcp 被挡了？）就别把用户的终端扣着：
                    # 把已经拿到的按 OEM 解出来的东西照实交出去，然后一律按 UTF-8 走。
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
            # Ctrl+C 在管道模式里**给不了**（没有控制台就没有中断信号）——
            # 宁可如实说"给不了"，也不假装成功（家规：不许静默失败）。
            return False
        if not data:
            return True
        # 管道那头的 cmd 是"按行"读的：`\r` 和 `\r\n` 都算一行结束，裸 `\n` 不算。
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
        return False                    # 管道没有"控制台尺寸"这回事（界面那边照样按自己宽度画）

    def alive(self):
        return self.proc.poll() is None

    def close(self):
        try:
            if self.proc.poll() is None:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=NO_WINDOW)
        except Exception:                                              # noqa: BLE001
            pass
        for h in (self.proc.stdin, self.proc.stdout):
            try:
                if h:
                    h.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=2)
        except Exception:                                              # noqa: BLE001
            pass
        with self._cv:
            self._eof = True
            self._cv.notify_all()


# ================================================================ 会话（单例）
def _shell_env(home):
    """给这个 shell 备环境。

    ★ **把 `moss.exe` 那个目录塞进 PATH**：这样在界面终端里直接敲 `moss :img` 就能用 ——
      不然还得手打全路径（这条也是"以后把跑包并进这个终端"的前提）。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # `MOSS_HOST_CMD` 是 JSON（core/ui.py 的 host_cmd() 塞的，形如 ["…\\moss.exe"]）；
    # 解析失败就算了 —— PATH 里少一个目录不影响用，别为它把终端起不来。
    host = []
    try:
        import json
        raw = os.environ.get("MOSS_HOST_CMD") or ""
        parsed = json.loads(raw) if raw else None
        if isinstance(parsed, list):
            host = [str(x) for x in parsed]
    except Exception:                                                  # noqa: BLE001
        host = []
    dirs = [d for d in (os.path.dirname(h) for h in host if h) if d]
    # ★ 安装根也进 PATH：`moss.exe` 就躺在那里 —— 这样你在终端里能直接敲 `moss :img`。
    #   （源码运行时 host 是 `<python> moss.py`，dirname 是 `venv\Scripts`，那儿没有 moss。）
    if home:
        dirs.append(str(home))
    if dirs:
        env["PATH"] = os.pathsep.join(dirs + [env.get("PATH", "")])
    return env


def _pick_backend(cols, rows, cwd, env):
    """挑后端：能上 ConPTY 就上，冒烟不过就退回管道。返回 (类, 原因)。"""
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
    # ---- 冒烟自测：真起一个 pty，看 echo 的标记回不回得来 ----
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
        self.history = ""               # 给"刚打开界面/刚刷新"的那一下看的历史

    # ---------------------------------------------------------------- 起 / 收
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
            except Exception:                                          # noqa: BLE001
                pass

    # ---------------------------------------------------------------- 动作
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
            except Exception:                                          # noqa: BLE001
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
        except Exception:                                              # noqa: BLE001
            return False

    def alive(self):
        b = self.backend
        if b is None:
            return False
        try:
            return bool(b.alive())
        except Exception:                                              # noqa: BLE001
            return False

    def state(self):
        return {"ok": self.backend is not None, "mode": self.mode, "note": self.note,
                "alive": self.alive(), "cols": self.cols, "rows": self.rows,
                "pid": getattr(getattr(self.backend, "p", None), "pid", None)
                       or getattr(getattr(self.backend, "proc", None), "pid", None)}


_SESSION = None
_LOCK = threading.RLock()


def start(cols=100, rows=30, cwd=None, home=None):
    """起（或复用）那个常驻 shell。返回状态 dict；起了新的会带 `fresh=True`。"""
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
        except Exception as e:                                         # noqa: BLE001
            return {"ok": False, "mode": "", "note": "起不来：%s" % e,
                    "alive": False, "fresh": True, "history": ""}
        _SESSION = s
        st = s.state()
        st["fresh"] = True
        st["history"] = s.history
        return st


def poll():
    """取走上次之后新产生的输出（顺便把历史记上）。"""
    with _LOCK:
        s = _SESSION
    if s is None:
        return {"ok": False, "out": "", "alive": False, "mode": "", "note": ""}
    out = s.drain()
    st = s.state()
    st.update({"out": out})
    return st


def run(cmdline):
    """把**一整条命令行**敲进终端（末尾自动补回车）。返回 `{ok, cmd, mode, msg}`。

    `V-352`：界面点「运行」就走这条 —— 让包**跑在这个 shell 里**，而不是另起一根管道。
    ※ 为什么非这样不可：真终端（ConPTY）的流里带**绝对光标定位**（`[4;1H` 这种），
      把管道里的文本倒进同一块屏，两股流会互相覆盖（用户当场看到"输出被替换了"，
      `V-351` 那一版就是这么坏的）。跑在 shell 里就**只有一股流**，从根上没这问题。
    """
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
        # 管道模式给不了 Ctrl+C（没有控制台可以发中断信号）—— 如实说一句，
        # 别让界面以为发出去了（家规：不许静默假装成功）。
        # `V-367`：别解释"后端/控制台"这些内部构造，只说这个模式做不到什么
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
    """收掉这个会话（下次 `start` 会重新起）：给"重启终端"用，也方便自检收尾。"""
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


# ================================================================ 自己验自己
if __name__ == "__main__":                                             # pragma: no cover
    # 这个自检是给"人在真终端里跑"的（控制台可能是 GBK），打印别因为一个替换字符就炸
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:                                                  # noqa: BLE001
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
