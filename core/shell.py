# -*- coding: utf-8 -*-
"""`cd` 的两条落地路：注入按键（零配置）与装 shell 包装函数（无回显）。

★ 为什么要这么绕：**子进程改不了父 shell 的工作目录**。`os.chdir()` 只影响
  moss 自己，一退出就没了；`cmd /c cd` 同理 —— 微软没提供反向接口。
  所以"切过去"那条命令**只能由 shell 自己执行**，moss 能做的只有"让 shell 执行"。
  一共两条路：

    ① 注入按键（`parent_shell` / `inject`）
       把 `Set-Location -LiteralPath '...'` 当成**真键盘记录**塞进控制台输入缓冲区，
       shell 读到就自己执行。零配置、不看窗口焦点、不碰剪贴板、中文不用旁路。
       ⚠️ 代价：那条命令会**显示在屏幕上**并进历史（PSReadLine 自己重画输入行，
          `SetConsoleMode` 关 `ENABLE_ECHO_INPUT` 也没用）。

    ② 装 profile 包装函数（`install_cd` / `uninstall_cd`）
       往 PowerShell 的 `$PROFILE` 写一个 `function moss`：moss 只把路径打到
       stdout，shell 自己 `Set-Location`。**屏幕上什么都没有**，但要装一次。

  `MOSS_CD_PRINT=1` 是两条路之间的开关（包装函数设的就是它），见 `cli.handle_cd`。
  （手动用的 `--print` 开关 2026-09-27 去掉了 —— 零回显那条路本来就不靠它。）

★ 实测（2026-09-25，**同步形态** —— 与真实 `moss cd` 一致：shell 阻塞在子进程上，
  子进程注入完就退出，shell 之后才读键盘）：经典 conhost + PowerShell 5.1 /
  Windows Terminal·ConPTY + PowerShell 5.1 / conhost + cmd.exe / 中文目录真 cd，
  **全部成功**。

★ 注入能成功的三个关键（少一个就完全没反应）：
    · 每条记录要带**真实虚拟键码**（`VkKeyScanW`）和扫描码（`MapVirtualKeyW`）
    · 每个键要补一条**抬键**记录
    · 需要 Shift 的字符（`: \\ _ " '`）要带 `SHIFT_PRESSED` 状态
"""
import ctypes
import ctypes.wintypes as wt
import io
import os
import sys
from pathlib import Path

from . import paths

# ---------------------------------------------------------------- Win32 常量
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


# ================================================================ ① 注入按键
def _proc_map():
    """{pid: (父 pid, 进程名小写)}；失败返回空字典（不抛异常）。"""
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
    """从 moss 自己往上最多 max_depth 层，返回 [(进程名, pid), ...]。只用于自检。"""
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
    """沿父进程链往上找**最近**的那个 shell。返回 'powershell' / 'cmd' / None。"""
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
    """当前进程有没有一个"真控制台"的输入句柄（不是被重定向的管道）。"""
    h = _k32.CreateFileW("CONIN$", GENERIC_READ | GENERIC_WRITE,
                         FILE_SHARE_READ | FILE_SHARE_WRITE, None,
                         OPEN_EXISTING, 0, None)
    if not h or h == INVALID_HANDLE_VALUE:
        return False, "打不开 CONIN$（err=%d）" % ctypes.get_last_error()
    mode = wt.DWORD(0)
    if not _k32.GetConsoleMode(ctypes.c_void_p(h), ctypes.byref(mode)):
        return False, "当前输入不是控制台（被重定向了）"
    return True, "mode=0x%X" % mode.value


# ================================================================ ② 启动方式
# ★ 「从终端敲的」和「双击/快捷方式启动的」怎么分（`G-19` ✅，2026-09-27 实测）。
#   主判据就是**父链上有没有 shell + 控制台是不是"为本进程新建并藏起来的"**。
#   （`G-18` ✅ 的档位从 attach 改成了 hide：attach 的产物是 GUI 子系统，
#     而 PowerShell 对 GUI 子系统的 exe **不等** —— `moss cd` / `--history` /
#     命令行菜单都要靠"shell 在等它"才成立。见那一行的实测数据。）
#   打包（`G-18` ✅ 最终档 = `hide`）：终端里敲 → 用的是终端那个控制台（shell 会等）；
#       双击 / 快捷方式 / 快速启动栏 → 控制台是**为它新建**的，然后被 bootstrap 藏起来。
#   第 55/56 版实测数据（探针见那两天的对话记录）：
#       终端启动            控制台窗口=有且可见   sys.stdout 不是 None
#       CREATE_NEW_CONSOLE  有               不是 None
#       pythonw（GUI 子系统） 无              **是 None**
#       经 explorer.exe 打开  无（双击那条路） **是 None**
#       hide 档 + explorer    有但**不可见**  不是 None   ← 现在就是这条
#   为什么不用 GetConsoleProcessList（"这个控制台上还挂着谁"）：它只能当旁证 ——
#   venv 的 python.exe 会再套一层（实测新建控制台时该数是 2 不是 1）。
_console_memo = []


def has_console():
    """moss 自己有没有真控制台。**一个进程里只问一次**（启动方式不会变）。

    注意：`hide` 档下**双击启动也有控制台**（console 子系统 → Windows 建一个，
    然后 bootstrap 把它藏起来）。所以"有没有控制台"只回答一半问题，
    要判"是不是被双击启动"得看 `gui_mode()`。
    """
    if not _console_memo:
        _console_memo.append(bool(console_available()[0]))
    return _console_memo[0]


_hidden_memo = []


def console_is_hidden():
    """本进程的控制台窗口是不是**被藏起来的**（= 它是为本进程新建的，不是挂到已有控制台）。

    `--windows-console-mode=hide` 的 bootstrap 在"本进程独占这个控制台"时调
    `ShowWindow(SW_HIDE)`（nuitka `OnefileBootstrap.c:1037` / `HelpersConsole.c:200`，
    判据是 `GetConsoleProcessList() <= 1`，那时子进程还没生出来，所以判得准）。
    于是：双击 / 快捷方式 / 快速启动栏启动 → **窗口不可见**；
    终端里敲 → 那个窗口是终端自己的（可见，哪怕最小化也算可见）→ 不藏。
    """
    if not _hidden_memo:
        hidden = False
        if os.name == "nt":
            try:
                _k32.GetConsoleWindow.restype = ctypes.c_void_p   # 不设的话 64 位下句柄会被截断
                _user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
                hwnd = _k32.GetConsoleWindow()
                hidden = bool(hwnd) and not bool(_user32.IsWindowVisible(hwnd))
            except Exception:
                hidden = False
        _hidden_memo.append(hidden)
    return _hidden_memo[0]


def gui_mode():
    """是不是"被当成界面程序启动的"（双击 / 快捷方式 / 快速启动栏）—— `G-19` ✅。

    三步判，顺序不能换：
      ① **父进程链上有 shell** → 就是终端里敲出来的，**直接否掉**。
         这一条必须排在最前面：Windows Terminal / VS Code / ConEmu 用的是
         **ConPTY**，那种会话里 `GetConsoleWindow()` 拿到的是 conhost 的
         **隐藏**窗口 —— 光看"窗口藏没藏"会把 WT 里的终端也判成双击（实测会）。
      ② 没有 shell、**根本没有控制台**（attach / disable 档的处境）→ 是。
      ③ 没有 shell、有控制台但**窗口是被藏起来的**（hide 档双击：bootstrap
         发现这控制台是给自己新建的，`ShowWindow(SW_HIDE)`）→ 是。

    终端里三问全落在①上，所以 `moss`（不带参数）照旧打用法 + 包列表。
    """
    if parent_shell() is not None:
        return False
    return (not has_console()) or console_is_hidden()


def launcher_name(max_depth=12):
    """父进程链上**第一个不是本程序**的进程名（小写）。找不到返回 ''。

    只用于自检与提示 —— 判断"从终端启动"以 `has_console()` 为准，不要拿它当判据：
    `explorer.exe` 是双击，但 `moss.exe` 被别的程序（编辑器、任务计划）拉起时
    父进程名五花八门，逐个列举必然漏。
    """
    me = os.getpid()
    for name, pid in parent_chain(max_depth):
        if pid == me:
            continue
        return name
    return ""


def launch_kind():
    """给自检和提示用的一句话：终端 / 界面（双击那条路）/ 管道。"""
    if not has_console():
        return "界面（没有控制台 —— 双击 / 快捷方式 / 快速启动栏）"
    if console_is_hidden():
        return "界面（控制台被新建后藏起来了 —— 双击 / 快捷方式 / 快速启动栏）"
    shell_name = parent_shell()
    if shell_name:
        return "终端（父 shell: %s）" % shell_name
    return "有控制台，但父链上没有 shell（可能是别的程序拉起的）"


def cd_command(shell_name, path):
    """按 shell 生成那条"切目录"的命令。"""
    if shell_name == "cmd":
        return 'cd /d "%s"' % path
    # PowerShell：单引号里把 ' 翻倍就是转义，其余字符（中文 / 空格 / 反斜杠）原样
    return "Set-Location -LiteralPath '%s'" % str(path).replace("'", "''")


def inject(text):
    """把 text + 回车当成真键盘记录注入当前控制台。返回 (ok, 说明)。

    ⚠️ 必须在**父 shell 阻塞等 moss 的时候**调用：moss 写进输入缓冲区、退出，
       shell 之后自己读到并执行 —— 这正是 `moss cd` 的形态，已实测。
    """
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
    """一条命令 -> 一串"像真键盘"的记录（按下 + 抬起，带键码/扫描码/Shift 状态）。"""
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


# ==================================================== ② profile 包装函数
MARK_BEGIN = "# >>> moss cd wrapper (generated by `moss cd --install`; do not edit) >>>"
MARK_END = "# <<< moss cd wrapper <<<"

# __CALL__ 会被替换成"怎么调起 moss"（打包后是 exe，开发时是 python + moss.py）
WRAPPER = """\
# >>> moss cd wrapper (generated by `moss cd --install`; do not edit) >>>
# A child process cannot change this shell's working directory, so `moss cd`
# cannot do it either. This function asks moss for the path (moss prints exactly
# one line) and changes directory here, in the shell itself:
#   * no simulated keystrokes, no clipboard, no window focus needed
#   * nothing shows up on screen and nothing goes into your history
# Every other `moss xxx` call is passed straight through to the exe.
function moss {
    param([Parameter(ValueFromRemainingArguments = $true)]$args)
    if ($args.Count -ge 2 -and $args[0] -eq 'cd' -and
        $args[1] -notin @('--install', '--uninstall', '--print')) {
        $env:MOSS_CD_PRINT = '1'
        try { $out = @(& __CALL__ @args) }
        finally { Remove-Item Env:\\MOSS_CD_PRINT -ErrorAction SilentlyContinue }
        $code = $LASTEXITCODE
        if ($code -eq 0 -and $out.Count -gt 0) {
            # last non-empty line only: a stray notice must not be taken for a path
            $target = @($out | Where-Object { "$_" -ne '' })
            if ($target.Count -gt 0) { Set-Location -LiteralPath $target[-1] }
        }
        return
    }
    & __CALL__ @args
}
# <<< moss cd wrapper <<<
"""


def _ps_quote(s):
    return "'" + str(s).replace("'", "''") + "'"


def _self_path():
    """程序自己是谁 —— 用 `sys.argv[0]`（理由见 core/paths.py 开头）。"""
    return Path(sys.argv[0]).resolve()


def _call_expr():
    """生成 PowerShell 里"调起 moss"的那段表达式。

    ⚠️ 这里连着踩了两个坑，别退回任何一种写法：

      1. **不能用 `sys.executable`**：nuitka **onefile** 下它指向临时解包目录里的
         python.exe（实测写进 profile 的是
         `...\\moss_build\\134348164530128307\\python.exe`）—— exe 一退出那目录就没了。

      2. **不能用 `sys.frozen` 判断"是不是 exe"**：那是 PyInstaller 的口径，
         **nuitka 不设这个属性**。第一版修完仍然写错，就是因为这个。

    判据只用 `sys.argv[0]` 的后缀：`.exe` 就自己调自己，`.py` 才需要 python 带上它。
    """
    self_path = _self_path()
    if self_path.suffix.lower() == ".exe":
        return _ps_quote(self_path)
    return "%s %s" % (_ps_quote(Path(sys.executable).resolve()), _ps_quote(self_path))


def wrapper_text():
    return WRAPPER.replace("__CALL__", _call_expr())


def _documents_dir():
    """取"文档"目录。走 SHGetKnownFolderPath（OneDrive 重定向也认），失败退回 ~\\Documents。"""
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
    """★ PowerShell 7 与 Windows PowerShell 5.1 用的是**两个不同的** $PROFILE。"""
    docs = _documents_dir()
    return [("PowerShell 7", docs / "PowerShell" / "Microsoft.PowerShell_profile.ps1"),
            ("Windows PowerShell 5.1",
             docs / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1")]


def _read_text(path):
    try:
        with io.open(str(path), "r", encoding="utf-8-sig") as f:
            return f.read()
    except UnicodeDecodeError:
        # 本来就不是 UTF-8（比如 5.1 时代的 ANSI 文件）：别把人家原有内容弄坏
        with io.open(str(path), "r", encoding="mbcs", errors="replace") as f:
            return f.read()


def _write_text(path, text):
    """⚠️ 必须带 UTF-8 BOM：5.1 读无 BOM 的 .ps1 会按 ANSI 解，中文注释会解坏。"""
    with io.open(str(path), "w", encoding="utf-8-sig", newline="") as f:
        f.write(text)


def _upsert_block(text, block):
    """把标记块插进去 / 整块替换。返回 (新文本, 'added'|'updated'|'unchanged')。"""
    i = text.find(MARK_BEGIN)
    j = text.find(MARK_END)
    if i != -1 and j > i:
        j += len(MARK_END)
        if text[i:j].strip() == block.strip():
            return text, "unchanged"
        return text[:i] + block.rstrip("\n") + text[j:], "updated"
    sep = "" if (not text or text.endswith(("\n", "\r"))) else "\r\n"
    return text + sep + block, "added"


def install_cd():
    """把包装函数写进两个 profile。返回 [(标签, 路径, 结果, 错误)]。"""
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
        except Exception as e:                                  # noqa: BLE001
            results.append((label, path, "失败: %s" % e, str(e)))
    return results


def uninstall_cd():
    """把包装函数从两个 profile 里删掉。返回格式同 install_cd。"""
    results = []
    for label, path in profile_paths():
        if not path.exists():
            results.append((label, path, "没有这个文件", None))
            continue
        try:
            old = _read_text(path)
            if MARK_BEGIN not in old:
                results.append((label, path, "没装过", None))
                continue
            i = old.find(MARK_BEGIN)
            j = old.find(MARK_END, i)
            new = old[:i] + (old[j + len(MARK_END):] if j != -1 else "")
            _write_text(path, new.lstrip("\r\n"))
            results.append((label, path, "已移除", None))
        except Exception as e:                                  # noqa: BLE001
            results.append((label, path, "失败: %s" % e, str(e)))
    return results


def installed_state():
    """自检用：[(标签, 路径, 已装?)]。"""
    out = []
    for label, path in profile_paths():
        try:
            has = path.exists() and MARK_BEGIN in _read_text(path)
        except Exception:                                       # noqa: BLE001
            has = False
        out.append((label, path, has))
    return out
