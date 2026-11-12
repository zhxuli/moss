import ctypes
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from ctypes import wintypes as wt
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
if os.name == "nt":
    try:
        subprocess.run(["chcp", "65001"], shell=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

HOME = Path(__file__).resolve().parent.parent
REQUIRED = (3, 12)
DOC_SOURCE = "moss.py"
DOC_MARKER = "-m nuitka"

ICON_REL = "system/icon/moss.ico"
ICON = HOME / ICON_REL

ONEFILE_DIR_PREFIX = "moss"
STAGE_NAME = "moss.build"
OLD_PREFIX = "moss.exe.old-"
LEGACY_ALT = "moss.exe.exe"
MOSS_BUILD_DIR = Path(os.environ.get("LOCALAPPDATA")
                      or (Path.home() / "AppData" / "Local")) / "moss_build"
_FIXED_FLAGS = ("--onefile --lto=yes --remove-output --windows-icon-from-ico=" + ICON_REL +
                " --windows-console-mode=hide --onefile-cache-mode=cached"
                " --include-package=core")
_STAMP_RE = re.compile(r"moss_build[/\\]" + ONEFILE_DIR_PREFIX + r"-[0-9a-f]{4,}", re.I)
_STAMP_PLACEHOLDER = "moss_build/" + ONEFILE_DIR_PREFIX + "-<stamp>"

_STAMP_CACHE = []

def source_stamp():
    if _STAMP_CACHE:
        return _STAMP_CACHE[0]
    h = hashlib.sha1()
    files = [HOME / "moss.py", ICON]
    files += sorted((HOME / "core").rglob("*.py"))
    for f in files:
        try:
            h.update(f.relative_to(HOME).as_posix().encode("utf-8"))
            h.update(b"\0")
            h.update(f.read_bytes())
            h.update(b"\0")
        except OSError:
            continue
    h.update(_FIXED_FLAGS.encode("utf-8"))
    try:
        from nuitka import __version__ as _nv
    except Exception:
        _nv = "?"
    h.update(("\n|py=%s|nuitka=%s|at=%d" % (sys.version, _nv, time.time_ns())).encode("utf-8"))
    stamp = h.hexdigest()[:8]
    _STAMP_CACHE.append(stamp)
    return stamp

def exe_is_locked():
    exe = HOME / "moss.exe"
    if not exe.is_file():
        return False
    try:
        with open(str(exe), "r+b"):
            pass
        return False
    except OSError:
        return True

_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DETACHED = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
_NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

class InstallError(RuntimeError):
    pass

class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]

def _norm_path(p):
    return os.path.normcase(os.path.abspath(str(p)))

def pids_running(exe):
    want = _norm_path(exe)
    found = {}
    if os.name != "nt":
        return found
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    k32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PROCESSENTRY32W)]
    k32.QueryFullProcessImageNameW.argtypes = [ctypes.c_void_p, wt.DWORD,
                                               wt.LPWSTR, ctypes.POINTER(wt.DWORD)]

    snap = k32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if not snap or snap == ctypes.c_void_p(-1).value:
        return found
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = k32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            pid = int(entry.th32ProcessID)
            handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                try:
                    buf = ctypes.create_unicode_buffer(32768)
                    size = wt.DWORD(32768)
                    if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                        if _norm_path(buf.value) == want:
                            found[pid] = int(entry.th32ParentProcessID)
                finally:
                    k32.CloseHandle(handle)
            ok = k32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k32.CloseHandle(snap)
    return found

def kill_pids(pids):
    for pid in sorted(pids):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=_NO_WINDOW)

def wait_unlocked(exe, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not exe_is_locked():
            return True
        time.sleep(0.2)
    return not exe_is_locked()

def restart_ui():
    exe = HOME / "moss.exe"
    try:
        proc = subprocess.Popen(
            [str(exe), "ui"], cwd=str(HOME),
            creationflags=_DETACHED | _NEW_GROUP,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True)
    except OSError as exc:
        return None, "重新启动失败：%s" % exc
    time.sleep(3.0)
    code = proc.poll()
    if code is None:
        return proc.pid, ""
    if code == 0:
        return proc.pid, ""
    return proc.pid, ("进程立刻退出了（退出码 %s）—— 手动双击 moss.exe 看看" % code)

def install_exe(staged, allow_kill=True):
    final = HOME / "moss.exe"

    if not exe_is_locked():
        os.replace(str(staged), str(final))
        return {"method": "replace", "killed": [], "restart": (None, "")}

    pids = pids_running(final)
    if not pids:
        raise InstallError(
            "%s 正被占着，但**认不出**是哪个进程（大概杀软，或者它是用管理员身份跑的）。\n"
            "       这次只留下 %s；手动关掉 moss 之后重跑一次打包即可。"
            % (final.name, staged.name))
    if not allow_kill:
        raise InstallError(
            "%s 正被 %d 个进程占着（%s），这次带了 --no-kill，所以一个都没动。\n"
            "       新产物留在 %s；关掉 moss 之后重跑一次打包即可。"
            % (final.name, len(pids), ", ".join(str(p) for p in sorted(pids)),
               staged.name))

    print("  · %s 正被 %d 个进程占着 —— 结束它们：%s"
          % (final.name, len(pids), ", ".join(str(p) for p in sorted(pids))))
    kill_pids(pids)
    if not wait_unlocked(final):
        restart_ui()
        raise InstallError("进程结束了但 %s 仍然换不进去（被杀软按住？）。已把界面重新拉起来。"
                           % final.name)
    try:
        os.replace(str(staged), str(final))
    except OSError as exc:
        restart_ui()
        raise InstallError("替换失败（%s）。已把界面重新拉起来。" % exc)
    return {"method": "kill", "killed": sorted(pids), "restart": (None, "")}

def sweep_old_exes():
    keep = _norm_path(HOME / "moss.exe")
    leftovers = sorted(HOME.glob(OLD_PREFIX + "*"))
    legacy = HOME / LEGACY_ALT
    if legacy.is_file():
        leftovers.append(legacy)
    for f in leftovers:
        if not f.is_file() or _norm_path(f) == keep:
            continue
        try:
            f.unlink()
            print("  清掉 %s" % f.name)
        except OSError:
            print("  %s 还被跑着的 moss 占着 —— 它退出之后，下次打包再清" % f.name)

def tempdir_spec(stamp):
    return "{CACHE_DIR}/moss_build/" + ONEFILE_DIR_PREFIX + "-" + stamp

def mask_stamp(s):
    return _STAMP_RE.sub(_STAMP_PLACEHOLDER, s)

def prune_old_cache(keep_name):
    if not MOSS_BUILD_DIR.is_dir():
        return 0, 0
    gone = kept = 0
    for d in sorted(MOSS_BUILD_DIR.iterdir()):
        if not d.is_dir():
            continue
        name = d.name
        if not (name.isdigit() or name.startswith(ONEFILE_DIR_PREFIX + "-")):
            continue
        if name == keep_name:
            kept += 1
            continue
        try:
            shutil.rmtree(str(d))
            gone += 1
        except OSError:
            print("  · 跳过一个清不掉的（大概正被运行中的 moss 占着）：%s" % name)
            kept += 1
    return gone, kept

def die(msg, code=1):
    print("[错误] %s" % msg)
    return code

def _normalize(s):
    s = s.replace("\\\\", "\\")
    return " ".join(s.replace('"', "").replace("'", "").split())

def check_doc_sync(cmd):
    doc_path = HOME / DOC_SOURCE
    if not doc_path.is_file():
        return "找不到 %s" % doc_path

    want = _normalize(mask_stamp(" ".join(cmd[3:])))
    found = None
    for line in doc_path.read_text(encoding="utf-8").splitlines():
        if DOC_MARKER in line:
            found = line.split(DOC_MARKER, 1)[1]
            break

    if found is None:
        return ("%s 的注释里找不到打包命令（要求必须留一份）。\n"
                "       应当有一行形如：venv\\Scripts\\python.exe -m nuitka ..."
                % DOC_SOURCE)

    got = _normalize(mask_stamp(found))
    if got != want:
        return ("%s 注释里的打包命令和 build.py 实际要跑的不一致 —— 不许漂移：\n"
                "       注释 : %s\n"
                "       实际 : %s\n"
                "       两处一起改。"
                % (DOC_SOURCE, got[:120], want[:120]))

    head = doc_path.read_text(encoding="utf-8")
    if "venv\\Scripts\\python.exe" not in head and "venv/Scripts/python.exe" not in head:
        return ("%s 注释里的解释器不是 venv\\Scripts\\python.exe —— "
                "用系统 python（3.13）会 FATAL。" % DOC_SOURCE)
    return None

def preflight():
    print("moss 打包")
    print("=" * 64)
    print("  安装根 : %s" % HOME)

    if not (HOME / "moss.py").is_file():
        return None, die("找不到 moss.py")
    if not ICON.is_file():
        return None, die("找不到 %s（图标文件，构建时嵌进 exe 的那个；"
                         "界面窗口的 favicon 也用它）" % ICON_REL)

    print("  构建器 : Python %d.%d.%d" % sys.version_info[:3])
    if sys.version_info[:2] != REQUIRED:
        return None, die("必须用 Python %d.%d 打包（nuitka 在 3.13 + MinGW 下不受支持）。\n"
                         "       正确用法：venv\\Scripts\\python.exe tools\\build.py\n"
                         "       venv 不存在：py -3.12 -m venv venv && "
                         "venv\\Scripts\\python.exe -m pip install nuitka" % REQUIRED)

    try:
        import nuitka
    except ImportError:
        return None, die("这个 Python 里没有 nuitka。装一下：\n"
                         "       %s -m pip install nuitka" % sys.executable)

    stamp = source_stamp()
    spec = tempdir_spec(stamp)
    locked = exe_is_locked()
    out_name = STAGE_NAME
    cmd = [
        sys.executable, "-m", "nuitka",
        "--onefile",
        "--lto=yes",
        "--remove-output",
        "--assume-yes-for-downloads",
        "--onefile-tempdir-spec=" + spec,
        "--onefile-cache-mode=cached",
        "--windows-icon-from-ico=" + ICON_REL,
        "--windows-console-mode=hide",
        "--include-package=core",
        "-o", out_name,
        "moss.py",
    ]

    err = check_doc_sync(cmd)
    if err:
        return None, die(err)

    print("  注释核对: ✔ %s 里的命令与本次要执行的一致" % DOC_SOURCE)
    print("  产物   : %s（编完换成 %s）"
          % (HOME / (STAGE_NAME + ".exe"), HOME / "moss.exe"))
    if locked:
        print("           ★ `moss.exe` 正被占着（界面开着）—— **不用你关**：")
        print("             编完先**结束**跑着它的进程，再替换，然后**自动把界面拉起来**（就是新版）。")
    else:
        print("           （没人占着：编完直接替换成 moss.exe）")
    print("  解包目录: %s（指纹 %s —— 每次打包换一个，旧的打包时清）"
          % (spec.replace("{CACHE_DIR}", str(MOSS_BUILD_DIR.parent)), stamp))
    print("  旧目录  : 打完包会清一遍（只清 %s 里我们自己那两种名字）" % MOSS_BUILD_DIR)
    print("=" * 64)
    print("实际执行的命令（唯一出处；%s 注释里那一份由上面核对保证同步）："
          % DOC_SOURCE)
    print("  %s -m nuitka %s" % (sys.executable, " ".join(cmd[3:])))
    print("=" * 64)
    return cmd, 0

def main():
    check_only = "--check" in sys.argv[1:]

    cmd, code = preflight()
    if cmd is None:
        return code

    if check_only:
        print("[检查模式] 前置检查全部通过，未执行打包。")
        return 0

    print("开始编译。首次运行会下载约 100MB 的 C 编译器到用户缓存（之后不再下载），")
    print("之后每次约 1-3 分钟。")
    print("=" * 64)
    sys.stdout.flush()

    staged = HOME / (STAGE_NAME + ".exe")
    if staged.exists():
        try:
            staged.unlink()
        except OSError:
            print("（%s 清不掉，先不管，接着编）" % staged.name)

    rc = subprocess.call(cmd, cwd=str(HOME))
    if rc != 0:
        return die("nuitka 返回 %d，打包失败。" % rc)
    if not staged.is_file():
        return die("nuitka 报成功，但 %s 不存在。" % staged.name)

    try:
        res = install_exe(staged, allow_kill="--no-kill" not in sys.argv[1:])
    except InstallError as exc:
        return die(str(exc))

    exe = HOME / "moss.exe"
    print()
    print("=" * 64)
    print("[完成] %s  (%.1f MB)" % (exe, exe.stat().st_size / 1048576))
    print("=" * 64)
    if res["method"] == "replace":
        print("（`moss.exe` 没人占着，编完直接替换 —— 下次启动就是新版）")
    else:
        print("★ 结束了在跑的那 %d 个进程，新 exe 已经就位（老文件是**真正删掉**的，没残渣）。"
              % len(res["killed"]))
        pid, note = restart_ui()
        if pid and not note:
            print("  界面已经**自动重新拉起来**了（pid=%s）—— 它跑的就是刚打的这一版，直接测。"
                  % pid)
        else:
            print("  ⚠ 界面没能自动拉起来（pid=%s）：%s" % (pid, note or "未知原因"))
            print("     手动双击 %s 即可。" % exe)

    print()
    print("擦掉盘上可能还躺着的旧产物（上一版热改名的 `moss.exe.old-*`、`V-380~V-383` 的 %s）："
          % LEGACY_ALT)
    sweep_old_exes()
    print()
    print("清理 onefile 的旧解包目录：%s" % MOSS_BUILD_DIR)
    gone, kept = prune_old_cache("%s-%s" % (ONEFILE_DIR_PREFIX, source_stamp()))
    print("  清掉 %d 个，留着 %d 个（留着的是当前指纹那份 + 清不掉的）" % (gone, kept))
    print("  ★ 换过指纹之后的**第一次**运行会解包一次（约 0.5 秒），之后就一直复用那份了。")
    print()
    print("接下来两步别省（nuitka onefile 下路径最容易翻车）：")
    print("  1) %s --selfcheck" % exe)
    print("  2) cd 到任意项目目录，用同一路径跑  %s m" % exe)
    print()
    print("发行时：moss.exe 必须和 system\\ 文件夹放在一起。")
    print("        user_data\\ 首次运行会自动创建。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
