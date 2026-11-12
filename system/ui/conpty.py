import codecs
import ctypes
import ctypes.wintypes as wintypes
import os
import threading
import time

_K32 = ctypes.WinDLL("kernel32", use_last_error=True)

_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
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
    k = _K32

    k.CreatePseudoConsole.argtypes = [COORD, wintypes.HANDLE, wintypes.HANDLE,
                                      wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    k.CreatePseudoConsole.restype = ctypes.c_long

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
    def __init__(self, hpcon, in_fd, out_fd, proc, pid):
        self._hpcon = hpcon
        self._in_fd = in_fd
        self._out_fd = out_fd
        self._proc = proc
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

    @classmethod
    def spawn(cls, cmdline="cmd.exe", cols=100, rows=30, cwd=None, env=None):
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
            cmd_buf = ctypes.create_unicode_buffer(cmdline)
            env_buf = None
            flags = _EXTENDED_STARTUPINFO_PRESENT
            if env is not None:
                env_buf = ctypes.create_unicode_buffer(_env_block(env))
                flags |= 0x00000400
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
        _close_handle(pi.hThread)

        import msvcrt
        in_fd = msvcrt.open_osfhandle(
            ctypes.cast(in_write, ctypes.c_void_p).value, os.O_WRONLY | os.O_BINARY)
        out_fd = msvcrt.open_osfhandle(
            ctypes.cast(out_read, ctypes.c_void_p).value, os.O_RDONLY | os.O_BINARY)
        return cls(hpcon, in_fd, out_fd, pi, int(pi.dwProcessId))

    def _pump(self):
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
        with self._cv:
            if not self._buf and not self._eof and timeout:
                self._cv.wait(timeout)
            if not self._buf:
                return ""
            text = "".join(self._buf)
            self._buf.clear()
            return text

    def wait_output(self, timeout=0.0):
        return self.read(timeout)

    def write(self, data):
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
        if self._proc is None:
            return False
        code = wintypes.DWORD(0)
        if not _K32.GetExitCodeProcess(self._proc.hProcess, ctypes.byref(code)):
            return False
        return code.value == _STILL_ACTIVE

    def close(self, kill=True):
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
    items = []
    for k, v in env.items():
        if not k or "=" in str(k):
            continue
        items.append("%s=%s" % (k, v))
    return "\0".join(items) + "\0\0"

if __name__ == "__main__":
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
