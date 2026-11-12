import ctypes
import ctypes.wintypes as wt
import io
import os
import re
import sys
from pathlib import Path

from . import paths

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
KEY_EVENT = 0x0001
VK_RETURN = 0x0D
SHIFT_PRESSED = 0x0010
LEFT_CTRL_PRESSED = 0x0008
LEFT_ALT_PRESSED = 0x0002
TH32CS_SNAPPROCESS = 0x00000002
MAX_PATH = 260
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

SHELLS = {"powershell.exe": "powershell", "pwsh.exe": "powershell", "cmd.exe": "cmd"}

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)

class _Char(ctypes.Union):
    _fields_ = [("UnicodeChar", ctypes.c_wchar), ("AsciiChar", ctypes.c_char)]

class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [("bKeyDown", wt.BOOL), ("wRepeatCount", wt.WORD),
                ("wVirtualKeyCode", wt.WORD), ("wVirtualScanCode", wt.WORD),
                ("uChar", _Char), ("dwControlKeyState", wt.DWORD)]

class _Event(ctypes.Union):
    _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("_pad", ctypes.c_byte * 16)]

class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", wt.WORD), ("Event", _Event)]

class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", ctypes.c_wchar * MAX_PATH)]

_k32.CreateFileW.restype = ctypes.c_void_p
_k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p,
                             wt.DWORD, wt.DWORD, ctypes.c_void_p]
_k32.WriteConsoleInputW.restype = wt.BOOL
_k32.WriteConsoleInputW.argtypes = [ctypes.c_void_p, ctypes.POINTER(INPUT_RECORD),
                                    wt.DWORD, ctypes.POINTER(wt.DWORD)]
_k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
_k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
_user32.VkKeyScanW.restype = ctypes.c_short
_user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
_user32.MapVirtualKeyW.restype = ctypes.c_uint
_user32.MapVirtualKeyW.argtypes = [ctypes.c_uint, ctypes.c_uint]

def _proc_map():
    out = {}
    snap = _k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return out
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = _k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            out[entry.th32ProcessID] = (entry.th32ParentProcessID,
                                        (entry.szExeFile or "").lower())
            ok = _k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        _k32.CloseHandle(snap)
    return out

def parent_chain(max_depth=12):
    procs = _proc_map()
    chain = []
    pid = os.getpid()
    for _ in range(max_depth):
        item = procs.get(pid)
        if not item:
            break
        ppid, name = item
        chain.append((name or "?", pid))
        if not ppid or ppid == pid:
            break
        pid = ppid
    return chain

def parent_shell(max_depth=12):
    procs = _proc_map()
    me = os.getpid()
    pid = me
    for _ in range(max_depth):
        item = procs.get(pid)
        if not item:
            return None
        ppid, name = item
        if pid != me and name in SHELLS:
            return SHELLS[name]
        if not ppid or ppid == pid:
            return None
        pid = ppid
    return None

def console_available():
    h = _k32.CreateFileW("CONIN$", GENERIC_READ | GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                         OPEN_EXISTING, 0, None)
    if not h or h == INVALID_HANDLE_VALUE:
        return False, "打不开 CONIN$（err=%d）" % ctypes.get_last_error()
    mode = wt.DWORD(0)
    if not _k32.GetConsoleMode(ctypes.c_void_p(h), ctypes.byref(mode)):
        return False, "当前输入不是控制台（被重定向了）"
    return True, "mode=0x%X" % mode.value

_console_memo = []

def has_console():
    if not _console_memo:
        _console_memo.append(bool(console_available()[0]))
    return _console_memo[0]

_hidden_memo = []

def console_is_hidden():
    if not _hidden_memo:
        hidden = False
        if os.name == "nt":
            try:
                _k32.GetConsoleWindow.restype = ctypes.c_void_p
                _user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
                hwnd = _k32.GetConsoleWindow()
                hidden = bool(hwnd) and not bool(_user32.IsWindowVisible(hwnd))
            except Exception:
                hidden = False
        _hidden_memo.append(hidden)
    return _hidden_memo[0]

def gui_mode():
    if parent_shell() is not None:
        return False
    return (not has_console()) or console_is_hidden()

def console_clients():
    if os.name != "nt":
        return []
    try:
        _k32.GetConsoleProcessList.argtypes = [ctypes.POINTER(wt.DWORD), wt.DWORD]
        _k32.GetConsoleProcessList.restype = wt.DWORD
        buf = (wt.DWORD * 64)()
        n = int(_k32.GetConsoleProcessList(buf, 64))
        if n <= 0 or n > 64:
            return []
        return [int(buf[i]) for i in range(n)]
    except Exception:
        return []

def console_is_only_ours():
    if not has_console():
        return False
    procs = _proc_map()
    for pid in console_clients():
        name = str((procs.get(pid) or (0, ""))[1] or "").lower()
        if name in SHELLS:
            return False
    return True

def launcher_name(max_depth=12):
    me = os.getpid()
    for name, pid in parent_chain(max_depth):
        if pid == me:
            continue
        return name
    return ""

def launch_kind():
    if not has_console():
        return "界面（没有控制台 —— 双击 / 快捷方式 / 快速启动栏）"
    if console_is_hidden():
        return "界面（控制台被新建后藏起来了 —— 双击 / 快捷方式 / 快速启动栏）"
    shell_name = parent_shell()
    if shell_name:
        return "终端（父 shell: %s）" % shell_name
    return "有控制台，但父链上没有 shell（可能是别的程序拉起的）"

def cd_command(shell_name, path):
    if shell_name == "cmd":
        return 'cd /d "%s"' % path
    return "Set-Location -LiteralPath '%s'" % str(path).replace("'", "''")

def inject(text):
    h = _k32.CreateFileW("CONIN$", GENERIC_READ | GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                         OPEN_EXISTING, 0, None)
    if not h or h == INVALID_HANDLE_VALUE:
        return False, "打不开控制台输入句柄（err=%d）" % ctypes.get_last_error()

    mode = wt.DWORD(0)
    if not _k32.GetConsoleMode(ctypes.c_void_p(h), ctypes.byref(mode)):
        return False, "当前不是真正的控制台（输入被重定向了）"

    recs = _records_for(text + "\r")
    arr = (INPUT_RECORD * len(recs))(*recs)
    written = wt.DWORD(0)
    ok = _k32.WriteConsoleInputW(ctypes.c_void_p(h), arr, len(recs),
                                 ctypes.byref(written))
    if not ok:
        return False, "WriteConsoleInput 失败（err=%d）" % ctypes.get_last_error()
    if written.value != len(recs):
        return False, "只写进去 %d/%d 条记录" % (written.value, len(recs))
    return True, "%d 条" % written.value

def _record(ch, vk, scan, cks, down):
    r = INPUT_RECORD()
    r.EventType = KEY_EVENT
    r.Event.KeyEvent.bKeyDown = 1 if down else 0
    r.Event.KeyEvent.wRepeatCount = 1
    r.Event.KeyEvent.wVirtualKeyCode = vk
    r.Event.KeyEvent.wVirtualScanCode = scan
    r.Event.KeyEvent.uChar.UnicodeChar = ch
    r.Event.KeyEvent.dwControlKeyState = cks
    return r

def _records_for(text):
    out = []
    for ch in text:
        if ch == "\r":
            vk, shift = VK_RETURN, 0
        else:
            vks = _user32.VkKeyScanW(ch)
            vk, shift = (0, 0) if vks == -1 else (vks & 0xFF, (vks >> 8) & 0xFF)
        scan = _user32.MapVirtualKeyW(vk, 0) if vk else 0
        cks = 0
        if shift & 1:
            cks |= SHIFT_PRESSED
        if shift & 2:
            cks |= LEFT_CTRL_PRESSED
        if shift & 4:
            cks |= LEFT_ALT_PRESSED
        out.append(_record(ch, vk, scan, cks, True))
        out.append(_record(ch, vk, scan, cks, False))
    return out

MARK_BEGIN = "$global:MossCdWrapperBegin = $true"
MARK_END = "$global:MossCdWrapperEnd = $true"
LEGACY_BLOCK_RE = re.compile(
    r"(?ms)^# >>>[^\n]*moss cd wrapper[^\n]*>>>[ \t]*\r?\n.*?^# <<<[^\n]*moss cd wrapper[^\n]*<<<[ \t]*(?:\r?\n|$)")

WRAPPER = """\
$global:MossCdWrapperBegin = $true
function moss {
    param([Parameter(ValueFromRemainingArguments = $true)]$args)
    if ($args.Count -ge 2 -and $args[0] -eq 'cd' -and
        $args[1] -notin @('--install', '--uninstall', '--print')) {
        $env:MOSS_CD_PRINT = '1'
        try { $out = @(& __CALL__ @args) }
        finally { Remove-Item Env:\\MOSS_CD_PRINT -ErrorAction SilentlyContinue }
        $code = $LASTEXITCODE
        if ($code -eq 0 -and $out.Count -gt 0) {
            $target = @($out | Where-Object { "$_" -ne '' })
            if ($target.Count -gt 0) { Set-Location -LiteralPath $target[-1] }
        }
        return
    }
    & __CALL__ @args
}
$global:MossCdWrapperEnd = $true
"""

def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"

def _self_path():
    return Path(sys.argv[0]).resolve()

def _call_expr():
    self_path = _self_path()
    if self_path.suffix.lower() == ".exe":
        return _ps_quote(self_path)
    return "%s %s" % (_ps_quote(Path(sys.executable).resolve()), _ps_quote(self_path))

def wrapper_text():
    return WRAPPER.replace("__CALL__", _call_expr())

def _documents_dir():
    try:
        class GUID(ctypes.Structure):
            _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                        ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]

        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF,
                   (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        ole32 = ctypes.WinDLL("ole32", use_last_error=True)
        shell32.SHGetKnownFolderPath.argtypes = [ctypes.POINTER(GUID), wt.DWORD,
                                                 wt.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_long
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        buf = ctypes.c_void_p()
        if shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None,
                                        ctypes.byref(buf)) == 0 and buf.value:
            path = ctypes.wstring_at(buf.value)
            ole32.CoTaskMemFree(buf)
            if path:
                return Path(path)
    except Exception:
        pass
    return Path(os.path.expanduser("~")) / "Documents"

def profile_paths():
    docs = _documents_dir()
    return [("PowerShell 7", docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1"),
            ("Windows PowerShell 5.1",
             docs / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1")]

def _read_text(path):
    try:
        with io.open(str(path), "r", encoding="utf-8-sig") as f:
            return f.read()
    except UnicodeDecodeError:
        with io.open(str(path), "r", encoding="mbcs", errors="replace") as f:
            return f.read()

def _write_text(path, text):
    with io.open(str(path), "w", encoding="utf-8-sig", newline="") as f:
        f.write(text)

def _wrapper_bounds(text):
    i = text.find(MARK_BEGIN)
    if i != -1:
        j = text.find(MARK_END, i)
        if j != -1:
            return i, j + len(MARK_END)
    match = LEGACY_BLOCK_RE.search(text)
    if match:
        return match.start(), match.end()
    return -1, -1

def _upsert_block(text, block):
    i, j = _wrapper_bounds(text)
    if i != -1:
        if text[i:j].strip() == block.strip():
            return text, "unchanged"
        return text[:i] + block.rstrip("\n") + text[j:], "updated"
    sep = "" if (not text or text.endswith(("\n", "\r"))) else "\r\n"
    return text + sep + block, "added"

def install_cd():
    block = wrapper_text()
    results = []
    for label, path in profile_paths():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            old = _read_text(path) if path.exists() else ""
            new, action = _upsert_block(old, block)
            if action == "unchanged":
                results.append((label, path, "已是最新", None))
                continue
            _write_text(path, new)
            results.append((label, path, "已写入" if action == "added" else "已更新", None))
        except Exception as e:
            results.append((label, path, "失败: %s" % e, str(e)))
    return results

def uninstall_cd():
    results = []
    for label, path in profile_paths():
        if not path.exists():
            results.append((label, path, "没有这个文件", None))
            continue
        try:
            old = _read_text(path)
            i, j = _wrapper_bounds(old)
            if i == -1:
                results.append((label, path, "没装过", None))
                continue
            new = old[:i] + old[j:]
            _write_text(path, new.lstrip("\r\n"))
            results.append((label, path, "已移除", None))
        except Exception as e:
            results.append((label, path, "失败: %s" % e, str(e)))
    return results

def installed_state():
    out = []
    for label, path in profile_paths():
        try:
            has = path.exists() and _wrapper_bounds(_read_text(path))[0] != -1
        except Exception:
            has = False
        out.append((label, path, has))
    return out
