import ctypes
import hashlib
import json
import os
import re
import sys
from pathlib import Path

from . import config, out, paths, registry

PREFIX = "mo"

DIRNAME = "shortcuts"
LEDGER_NAME = "_shortcuts.json"
LEDGER_FP = "fp"

def shortcuts_dir():
    return paths.USER_DIR / DIRNAME

def _ledger_file():
    return paths.STATE_DIR / LEDGER_NAME

def launcher_argv():
    exe = paths.HOME / "moss.exe"
    if exe.is_file():
        return [str(exe)]
    entry = Path(sys.argv[0]).resolve()
    return [sys.executable, str(entry)]

def _shim_text(pkg_id):
    line = " ".join('"%s"' % a for a in launcher_argv())
    if pkg_id:
        line += " --pkg " + str(pkg_id)
    return "@echo off\r\n" + line + " %*\r\n"

def prefix():
    raw = str((config.CONFIG.get("shortcut") or {}).get("prefix") or PREFIX).strip()
    return re.sub(r"[^A-Za-z0-9_-]", "", raw) or PREFIX

def _desired():
    sc = config.CONFIG.get("shortcut") or {}
    p = prefix()
    want = {}
    if sc.get("mo"):
        want[p] = None
    if sc.get("pkg"):
        for rec in registry.scan_all():
            want[p + str(rec["id"])] = str(rec["id"])
    return want

def _pkg_sig():
    rows = []
    for base in (paths.SYSTEM_PKGS, paths.USER_PKGS):
        try:
            entries = list(os.scandir(base))
        except OSError:
            continue
        for e in entries:
            try:
                if not e.is_dir():
                    continue
            except OSError:
                continue
            try:
                pm = os.stat(os.path.join(e.path, "pkg.json")).st_mtime_ns
            except OSError:
                pm = 0
            rows.append([e.name, pm])
    rows.sort()
    return rows

def _state_fp():
    sc = config.CONFIG.get("shortcut") or {}
    blob = json.dumps({
        "prefix": prefix(),
        "mo": bool(sc.get("mo")),
        "pkg": bool(sc.get("pkg")),
        "launcher": launcher_argv(),
        "pkgs": _pkg_sig(),
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()

_HWND_BROADCAST = 0xFFFF
_WM_SETTINGCHANGE = 0x001A

def _broadcast():
    try:
        ctypes.windll.user32.SendNotifyMessageW(
            _HWND_BROADCAST, _WM_SETTINGCHANGE, 0, ctypes.c_wchar_p("Environment"))
    except Exception:
        pass

def _user_path_list():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
        return [p.strip() for p in str(value).split(";") if p.strip()]
    except Exception:
        return []

def _same_path(a, b):
    try:
        return os.path.normpath(str(a)).lower() == os.path.normpath(str(b)).lower()
    except Exception:
        return str(a).lower() == str(b).lower()

def _path_has(d):
    return any(_same_path(p, d) for p in _user_path_list())

def _system_path_list():
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
        return [p.strip() for p in str(value).split(";") if p.strip()]
    except Exception:
        return []

def moss_on_path():
    home = str(paths.HOME)
    if _path_has(home):
        return True
    return any(_same_path(p, home) for p in _system_path_list())

def _write_user_path(items):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(items))
        _broadcast()
        return True
    except Exception:
        return False

def _read_ledger():
    try:
        data = json.loads(_ledger_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def _write_ledger(data):
    paths.ensure_user_dirs()
    _ledger_file().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")

def sync():
    if os.name != "nt":
        return []
    want = _desired()
    d = shortcuts_dir()
    ledger = _read_ledger()
    old_files = dict(ledger.get("files") or {})
    msgs = []

    if want and not d.is_dir():
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return ["建不了目录 %s：%s" % (d, e)]

    new_files = {}
    for name, pid in sorted(want.items()):
        fn = d / (name + ".cmd")
        want_text = _shim_text(pid).encode("utf-8")
        try:
            if (not fn.is_file()) or fn.read_bytes() != want_text:
                fn.write_bytes(want_text)
                msgs.append("生成 %s.cmd  →  %s" % (name, ("moss %s %s" % (config.plugin_symbol(), pid))
                                                    if pid else "moss"))
        except OSError as e:
            msgs.append("写不了 %s：%s" % (fn, e))
            continue
        new_files[name] = pid

    for name in sorted(old_files):
        if name in new_files:
            continue
        fn = d / (name + ".cmd")
        try:
            if fn.is_file():
                fn.unlink()
                msgs.append("删除 %s.cmd" % name)
        except OSError as e:
            msgs.append("删不掉 %s：%s" % (fn, e))

    d_str = str(d)
    has = _path_has(d)
    if want and not has:
        if _write_user_path(_user_path_list() + [d_str]):
            msgs.append("已把 %s 加进 PATH（新开一个终端才生效）" % d_str)
        else:
            msgs.append("改注册表失败，没能把 %s 加进 PATH" % d_str)
    elif (not want) and has:
        left = [p for p in _user_path_list() if not _same_path(p, d_str)]
        if _write_user_path(left):
            msgs.append("已把 %s 从 PATH 移除" % d_str)

    home = str(paths.HOME)
    want_moss = bool((config.CONFIG.get("path") or {}).get("moss"))
    we_added = (str(ledger.get("moss_dir") or "") == home)
    if want_moss and not moss_on_path():
        if _write_user_path(_user_path_list() + [home]):
            msgs.append("已把 %s 加进 PATH（新开一个终端才生效，不用重启电脑）" % home)
            we_added = True
        else:
            msgs.append("改注册表失败，没能把 %s 加进 PATH" % home)
    elif not want_moss:
        if we_added and _path_has(home):
            left = [p for p in _user_path_list() if not _same_path(p, home)]
            if _write_user_path(left):
                msgs.append("已把 %s 从 PATH 移除（新开一个终端才生效）" % home)
        we_added = False

    new_ledger = {"dir": d_str, "launcher": launcher_argv(), "files": new_files,
                  "moss_dir": (home if we_added else None), LEDGER_FP: _state_fp()}
    if new_ledger != ledger:
        _write_ledger(new_ledger)
    return msgs

def sync_if_stale():
    if os.name != "nt":
        return []
    sc = config.CONFIG.get("shortcut") or {}
    if not (sc.get("mo") or sc.get("pkg")):
        try:
            leftovers = next(iter(shortcuts_dir().glob("*.cmd")), None) is not None
        except OSError:
            leftovers = False
        return sync() if leftovers else []
    try:
        if str(_read_ledger().get(LEDGER_FP) or "") == _state_fp():
            return []
    except Exception:
        pass
    return sync()

def status():
    sc = config.CONFIG.get("shortcut") or {}
    d = shortcuts_dir()
    ledger = _read_ledger()
    files = sorted((ledger.get("files") or {}).keys())
    return {"prefix": prefix(), "mo": bool(sc.get("mo")), "pkg": bool(sc.get("pkg")),
            "dir": str(d), "on_path": _path_has(d), "files": files,
            "moss": bool((config.CONFIG.get("path") or {}).get("moss")),
            "moss_dir": str(paths.HOME), "moss_on_path": moss_on_path()}

def cmd_alias(argv):
    verb = (argv[0].lower() if argv else "status")
    if verb in ("sync", "apply"):
        msgs = sync()
        if not msgs:
            out.print_cyan("[短命令] 已经是最新的，没有要改的。")
        else:
            for m in msgs:
                out.print_cyan("[短命令] " + m)
        return 0
    if verb in ("status", "list"):
        s = status()
        p = s["prefix"]
        out.print_cyan("短命令现状")
        print("  moss 在 PATH 里        : %s   （%s）"
              % ("是" if s["moss_on_path"] else "否", s["moss_dir"]))
        print("  前缀                  : %s" % p)
        print("  %s = moss              : %s" % (p, "开" if s["mo"] else "关"))
        print("  %s<包名> = moss :包名  : %s" % (p, "开" if s["pkg"] else "关"))
        print("  目录                  : %s%s"
              % (s["dir"], "（已在 PATH 里）" if s["on_path"] else "（不在 PATH 里）"))
        print("  已生成 %d 个           : %s"
              % (len(s["files"]), ", ".join(s["files"]) if s["files"] else "（无）"))
        print("  启动自愈              : 每次 moss 启动都会比一次指纹 —— 包列表变了就自动补上"
              "（手工丢包 / 拷包 / AI 写包都不用再手动 sync）")
        return 0
    out.print_cyan("[错误] 不认识的 --alias 子命令：%s（有：sync / status）" % verb)
    return 1
