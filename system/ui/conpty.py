# -*- coding: utf-8 -*-
"""system/ui/conpty.py —— 在 Windows 上开一个**真的伪控制台**（ConPTY），拿它跑 cmd.exe。

为什么需要它（`V-348`）
----------------------
界面那个「命令行」原来不是终端：它是一块 `<pre>` + 下面**一根固定死的 input**，而那根
input 只是"某个正在跑的包"的 stdin 管子（`main.py::run_input`）—— 包一退出，管子就废了，
于是"停下来就不能再敲命令"。要一比一像 DOS，后端必须有一个**不会随命令结束而死掉**的
shell，而且它得以为自己接的是真控制台：有提示符、有行编辑、有 Tab 补全菜单、能收 Ctrl+C。

为什么是 ConPTY 而不是普通管道
------------------------------
管道给不了"真控制台"：cmd 走管道时不回显、不做行编辑、方向键/Tab 全哑、彩色程序也不发
ANSI（没有 console 可附加）——那套只能靠前端"本地回显"硬仿。ConPTY 是 Win10 1809+ 的
官方接口，跟 WebView2 要求的系统版本**一条线**，不额外提高门槛。

为什么不装 `pywinpty`（明明有现成 cp312 轮子）
--------------------------------------------
家规（`AGENTS.md`「别做的事」）写着**别装第三方依赖来解决界面问题**。这里真正用到的只有
kernel32 里三个函数（`CreatePseudoConsole` / `ResizePseudoConsole` / `ClosePseudoConsole`）
加一个 `CreateProcessW` —— 纯 `ctypes` 就够，而装 `pywinpty` 要多带一份**二进制**
（`winpty.dll` + `winpty-agent.exe`，还得管它跟 exe 一起分发），不划算。

接口（就五个动作）
------------------
    p = ConPty.spawn("cmd.exe", cols=100, rows=30, cwd=r"D:\\x")
    p.write("dir\\r")          # 敲键盘：原样送进控制台输入（控制台自己负责回显）
    p.read(0.1)               # 取**已有**的输出；没有就给空串，**绝不阻塞**
    p.resize(cols, rows)      # 窗口变了必须说一声，否则 TUI / 进度条会错位
    p.close()                 # 关掉（连它拉起的子进程一起收）

★ 约定：`read()` 交出去的是**已经解码好的文本**（ConPTY 吐 UTF-8），且**原样保留 ANSI
  转义序列** —— 那是给 xterm.js 看的，这一层**不做任何清洗**（谁要想看纯文本，那是调用方
  的事：界面上"复制全部输出"走的是另外那条路）。
"""
import codecs
import ctypes
import ctypes.wintypes as wintypes
import os
import threading
import time

_K32 = ctypes.WinDLL("kernel32", use_last_error=True)

#: `CreateProcessW` 的 flag：告诉它 `STARTUPINFO` 其实是 `STARTUPINFOEXW`（要带属性表）
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
#: 属性表里的那一项：`hPC` 就是伪控制台（值来自 Windows SDK 的 wincon.h）
_PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
_INFINITE = 0xFFFFFFFF
_STILL_ACTIVE = 259


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR), ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD), ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE), ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("StartupInfo", _STARTUPINFOW), ("lpAttributeList", ctypes.c_void_p)]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]


def _bind():
    """把要用到的几个 kernel32 函数**逐个签好名**。

    ★ 必须显式给 `argtypes` / `restype`：64 位下 HANDLE 是 8 字节，不声明的话 ctypes 默认
      按 C int（4 字节）传 —— 拿到的高位会被截掉，表现是"随机地起不来/读到脏数据"。
      HANDLE 在这里一律当 `c_void_p` 用（`wintypes.HANDLE` 就是它）。
    """
    k = _K32

    k.CreatePseudoConsole.argtypes = [COORD, wintypes.HANDLE, wintypes.HANDLE,
                                      wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    k.CreatePseudoConsole.restype = ctypes.c_long                    # HRESULT

    k.ResizePseudoConsole.argtypes = [wintypes.HANDLE, COORD]
    k.ResizePseudoConsole.restype = ctypes.c_long

    k.ClosePseudoConsole.argtypes = [wintypes.HANDLE]
    k.ClosePseudoConsole.restype = None

    k.CreatePipe.argtypes = [ctypes.POINTER(wintypes.HANDLE),
                             ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p,
                             wintypes.DWORD]
    k.CreatePipe.restype = wintypes.BOOL

    k.InitializeProcThreadAttributeList.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                                    wintypes.DWORD,
                                                    ctypes.POINTER(ctypes.c_size_t)]
    k.InitializeProcThreadAttributeList.restype = wintypes.BOOL

    k.UpdateProcThreadAttribute.argtypes = [ctypes.c_void_p, wintypes.DWORD,
                                            ctypes.c_size_t, ctypes.c_void_p,
                                            ctypes.c_size_t, ctypes.c_void_p,
                                            ctypes.c_void_p]
    k.UpdateProcThreadAttribute.restype = wintypes.BOOL

    k.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    k.DeleteProcThreadAttributeList.restype = None

    k.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p,
                                 ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.LPCWSTR,
                                 ctypes.POINTER(_STARTUPINFOEXW),
                                 ctypes.POINTER(_PROCESS_INFORMATION)]
    k.CreateProcessW.restype = wintypes.BOOL

    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL

    k.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k.GetExitCodeProcess.restype = wintypes.BOOL

    k.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k.TerminateProcess.restype = wintypes.BOOL


_bound = False


def available():
    """这台机器能不能开 ConPTY（返回 (能不能, 说明)）。

    ★ Win10 1809（build 17763）之前 `kernel32` 里**根本没有** `CreatePseudoConsole`。
      那种机器上界面照旧要能开 —— 所以这里只"报告"，由调用方决定退路（`term.py` 会退回
      普通管道 + 前端本地回显），**不许**在这里抛异常把界面拖死。
    """
    global _bound
    if not _bound:
        try:
            _bind()
        except AttributeError as e:
            return False, "这个 Windows 的 kernel32 里没有 ConPTY（需要 Win10 1809+）：%s" % e
        _bound = True
    return True, ""


def _close_handle(h):
    if h:
        try:
            _K32.CloseHandle(h)
        except OSError:
            pass


class ConPty:
    """一个挂在自己专属伪控制台上的子进程（cmd.exe / powershell.exe / 任何控制台程序）。"""

    def __init__(self, hpcon, in_fd, out_fd, proc, pid):
        self._hpcon = hpcon
        self._in_fd = in_fd            # 我们**写**这一头 → 控制台读
        self._out_fd = out_fd          # 我们**读**这一头 ← 控制台写
        self._proc = proc              # PROCESS_INFORMATION
        self.pid = pid
        self._buf = []
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self._closed = False
        self._eof = False
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._reader = threading.Thread(target=self._pump, name="moss-conpty-read",
                                        daemon=True)
        self._reader.start()

    # ---------------------------------------------------------------- 起一个（唯一的构造口）
    @classmethod
    def spawn(cls, cmdline="cmd.exe", cols=100, rows=30, cwd=None, env=None):
        """开一个伪控制台并把 `cmdline` 挂上去。失败一律抛 `OSError`（带人话的原因）。"""
        ok, why = available()
        if not ok:
            raise OSError(why)
        cols = max(2, int(cols or 100))
        rows = max(2, int(rows or 30))

        in_read, in_write = wintypes.HANDLE(), wintypes.HANDLE()
        out_read, out_write = wintypes.HANDLE(), wintypes.HANDLE()
        if not _K32.CreatePipe(ctypes.byref(in_read), ctypes.byref(in_write), None, 0):
            raise OSError("CreatePipe(输入) 失败：%s" % ctypes.get_last_error())
        if not _K32.CreatePipe(ctypes.byref(out_read), ctypes.byref(out_write), None, 0):
            _close_handle(in_read)
            _close_handle(in_write)
            raise OSError("CreatePipe(输出) 失败：%s" % ctypes.get_last_error())

        hpcon = wintypes.HANDLE()
        hr = _K32.CreatePseudoConsole(COORD(cols, rows), in_read, out_write, 0,
                                      ctypes.byref(hpcon))
        if hr != 0:
            for h in (in_read, in_write, out_read, out_write):
                _close_handle(h)
            raise OSError("CreatePseudoConsole 失败（HRESULT=0x%08X）" % (hr & 0xFFFFFFFF))

        # ★ 控制台自己已经拿着 in_read / out_write 的两份句柄了 —— 我们这两份**必须马上关**，
        #   否则输出那头永远等不到 EOF（我们手里也攥着一个"写端"，读端就永远不结束）。
        _close_handle(in_read)
        _close_handle(out_write)

        attr = ctypes.c_void_p()
        size = ctypes.c_size_t(0)
        _K32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        attr = ctypes.cast(buf, ctypes.c_void_p)
        if not _K32.InitializeProcThreadAttributeList(attr, 1, 0, ctypes.byref(size)):
            _close_handle(in_write)
            _close_handle(out_read)
            _K32.ClosePseudoConsole(hpcon)
            raise OSError("InitializeProcThreadAttributeList 失败：%s"
                          % ctypes.get_last_error())
        hpc_val = ctypes.cast(hpcon, ctypes.c_void_p)
        try:
            if not _K32.UpdateProcThreadAttribute(
                    attr, 0, _PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                    hpc_val, ctypes.sizeof(wintypes.HANDLE), None, None):
                raise OSError("UpdateProcThreadAttribute 失败：%s" % ctypes.get_last_error())

            si = _STARTUPINFOEXW()
            si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
            si.lpAttributeList = attr
            pi = _PROCESS_INFORMATION()
            # ★ 命令行必须放**可写缓冲**：`CreateProcessW` 有权就地改这个串（它会写坏只读内存）
            cmd_buf = ctypes.create_unicode_buffer(cmdline)
            env_buf = None
            flags = _EXTENDED_STARTUPINFO_PRESENT
            if env is not None:
                env_buf = ctypes.create_unicode_buffer(_env_block(env))
                flags |= 0x00000400                       # CREATE_UNICODE_ENVIRONMENT
            ok = _K32.CreateProcessW(None, cmd_buf, None, None, False, flags,
                                     ctypes.cast(env_buf, ctypes.c_void_p) if env_buf else None,
                                     str(cwd) if cwd else None, ctypes.byref(si),
                                     ctypes.byref(pi))
            if not ok:
                raise OSError("CreateProcessW 失败：%s" % ctypes.get_last_error())
        except OSError:
            _K32.DeleteProcThreadAttributeList(attr)
            _close_handle(in_write)
            _close_handle(out_read)
            _K32.ClosePseudoConsole(hpcon)
            raise
        _K32.DeleteProcThreadAttributeList(attr)
        _close_handle(pi.hThread)              # 线程句柄用不上；进程句柄留着问"还活着吗"

        import msvcrt
        in_fd = msvcrt.open_osfhandle(
            ctypes.cast(in_write, ctypes.c_void_p).value, os.O_WRONLY | os.O_BINARY)
        out_fd = msvcrt.open_osfhandle(
            ctypes.cast(out_read, ctypes.c_void_p).value, os.O_RDONLY | os.O_BINARY)
        return cls(hpcon, in_fd, out_fd, pi, int(pi.dwProcessId))

    # ---------------------------------------------------------------- 读（后台线程攒着）
    def _pump(self):
        """后台把控制台输出读进内存。★ 必须**单独一个线程**：那块读是阻塞的，
        而界面每几十毫秒就来问一次"有没有新东西" —— 在调用线程里读会把整个界面卡住。"""
        while True:
            try:
                chunk = os.read(self._out_fd, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            text = self._decoder.decode(chunk)
            if not text:
                continue
            with self._cv:
                self._buf.append(text)
                self._cv.notify_all()
        with self._cv:
            self._eof = True
            self._cv.notify_all()

    def read(self, timeout=0.0):
        """取走**此刻已经攒下的**输出（取完就没了）。`timeout` 秒内没有新东西就给空串。

        ★ 语义是"增量"：调用方自己按序拼起来就是完整输出 —— 这样界面只要把每次拿到的
          这段喂给 xterm.js 就行，既不会重画，也不用搬整份历史。
        """
        with self._cv:
            if not self._buf and not self._eof and timeout:
                self._cv.wait(timeout)
            if not self._buf:
                return ""
            text = "".join(self._buf)
            self._buf.clear()
            return text

    def wait_output(self, timeout=0.0):
        """等一小会儿再取（跟 `read` 同一件事，只是名字把"我打算等"说明白）。"""
        return self.read(timeout)

    # ---------------------------------------------------------------- 写 / 改尺寸 / 关
    def write(self, data):
        """把按键原样送进控制台。字符串按 UTF-8 编码（控制台那侧是 UTF-8 代码页）。

        ★ Ctrl+C 不用另开一条路：xterm.js 会把 Ctrl+C 发成 `\\x03`，写进来就是
          "控制台收到了一个 Ctrl+C 按键" —— 该中断前台程序的中断它。比 `taskkill` 干净。
        """
        if self._closed:
            return False
        raw = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        try:
            os.write(self._in_fd, raw)
            return True
        except OSError:
            return False

    def resize(self, cols, rows):
        if self._closed:
            return False
        hr = _K32.ResizePseudoConsole(self._hpcon,
                                      COORD(max(2, int(cols)), max(2, int(rows))))
        return hr == 0

    @property
    def closed(self):
        return self._closed

    def alive(self):
        """那个子进程还在不在（ConPTY 自己不算，问的是 cmd.exe）。"""
        if self._proc is None:
            return False
        code = wintypes.DWORD(0)
        if not _K32.GetExitCodeProcess(self._proc.hProcess, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE

    def close(self, kill=True):
        """收工：关伪控制台 → 关两个管道 → （还没死就）杀掉子进程。

        ★ 顺序有讲究：先 `ClosePseudoConsole`，控制台那侧一关，读端就等得到 EOF；
          反过来先关管道的话，ConPTY 可能还在往里写，reader 线程会拿到脏错误。
        """
        if self._closed:
            return
        self._closed = True
        try:
            _K32.ClosePseudoConsole(self._hpcon)
        except OSError:
            pass
        self._hpcon = None
        for fd in (self._in_fd, self._out_fd):
            try:
                if fd is not None:
                    os.close(fd)
            except OSError:
                pass
        self._in_fd = self._out_fd = None
        if self._proc is not None:
            if kill and self.alive():
                try:
                    _K32.TerminateProcess(self._proc.hProcess, 1)
                except OSError:
                    pass
            _close_handle(self._proc.hProcess)
            self._proc = None
        with self._cv:
            self._eof = True
            self._cv.notify_all()
        self._reader.join(timeout=2.0)


def _env_block(env):
    """把 dict 拼成 `CreateProcessW` 要的那种"双 NUL 结尾的 KEY=VALUE\\0"块。"""
    items = []
    for k, v in env.items():
        if not k or "=" in str(k):
            continue
        items.append("%s=%s" % (k, v))
    return "\0".join(items) + "\0\0"


# ---------------------------------------------------------------- 自己验自己（`python conpty.py`）
if __name__ == "__main__":                                             # pragma: no cover
    import sys
    ok, why = available()
    print("ConPTY 可用：" if ok else "ConPTY 不可用：", why or "是")
    if not ok:
        sys.exit(2)
    p = ConPty.spawn("cmd.exe /Q", cols=100, rows=30, cwd=str(os.environ.get("TEMP") or "."))
    print("已起 cmd.exe，pid =", p.pid)
    time.sleep(0.6)
    print("--- 启动横幅 ---")
    print(repr(p.read(0.3))[:600])
    p.write("echo MOSS_CONPTY_OK\r")
    p.write("cd\r")
    time.sleep(0.8)
    out = p.read(0.5)
    print("--- 敲完两条命令之后 ---")
    print(repr(out)[:1200])
    print("--- 判据 ---")
    print("echo 有回显：", "MOSS_CONPTY_OK" in out)
    print("还有提示符（说明 shell 活着）：", out.rstrip().endswith(">") or ">" in out)
    p.resize(120, 40)
    print("resize OK：", p.alive())
    p.close()
    print("关掉之后 alive() =", p.alive())
