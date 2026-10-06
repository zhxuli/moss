# -*- coding: utf-8 -*-
"""短命令：把 `moss :img` 变成一条直接能敲的命令 `moimg`（`V-298`）。

思路
----
在**命令解析之前**落地 —— 往 PATH 上的一个目录里写一批小启动器（`.cmd`），
每个文件内容就一行：

    "…\\moss.exe" --pkg img %*

系统按 PATH 找到 `moimg.cmd`，把参数**原样**转发给 moss（实测：cmd 与 PowerShell
下参数、退出码都原样传递）。运行链路一个字没改 —— 只是"命令怎么被找到"多了一跳。

两个**总开关**（写在 `config.toml` 的 `[shortcut]`，界面「设置 → 短命令」里改）：

    mo  = true   生成 `mo`         → 就是 `moss`（`mo :img …`）
    pkg = true   生成 `mo<包名>`   → `moss :img`（`moimg …`）

为什么是 `.cmd` 而不是 shell 别名
--------------------------------
alias 是**整词替换**，`moimg` 不是 `mo`+`img` 拼出来的 —— 普通别名做不到融合短词。
`.cmd` 是系统级启动器：cmd 与 PowerShell 都认（git-bash 另说），
参数与退出码原样传递，删包就是删文件，没有"每个 shell 各装一份"的麻烦。

和其它模块的关系
----------------
· 开关状态读 `config.CONFIG`（`[shortcut]` 段）—— 唯一真相还是那份 config.toml；
· 包列表用 `registry.scan_all()` 现扫（和别处一个口径：磁盘是唯一真相）；
· 改 PATH 走 `HKCU\\Environment\\Path`（照 `path` 包的做法：只改用户级、不动 HKLM、
  改完广播 `WM_SETTINGCHANGE`）。
"""
import ctypes
import json
import os
import re
import sys
from pathlib import Path

from . import config, out, paths, registry

#: 前缀的**出厂默认值**（用户可以在 `config.toml` 的 `[shortcut].prefix` 里改）。
#: `<前缀>` = moss，`<前缀><包名>` = moss :包名。默认 `mo` 只是为降低撞系统命令的概率。
PREFIX = "mo"

#: 启动器放哪。放可写区（`user_data/` 下），不放安装根（那里可能只读）。
DIRNAME = "shortcuts"
#: 记着"我们生成了哪些"的账本 —— 删的时候**只看这里**，绝不误删别人的文件。
LEDGER_NAME = "_shortcuts.json"


def shortcuts_dir():
    return paths.USER_DIR / DIRNAME


def _ledger_file():
    return paths.STATE_DIR / LEDGER_NAME


def launcher_argv():
    """启动器该调用谁：打包后是 `moss.exe`，开发态是「解释器 + moss.py」。

    ★ 为什么不用 `sys.executable` 一把梭：nuitka onefile 下 `sys.executable` 是解包
      临时目录里的东西，不是安装根那个 `moss.exe`。而 `paths.HOME` 是稳的
      （它靠 `sys.argv[0]` 定位，见 `paths.py`）。
    """
    exe = paths.HOME / "moss.exe"
    if exe.is_file():
        return [str(exe)]
    entry = Path(sys.argv[0]).resolve()
    return [sys.executable, str(entry)]


def _shim_text(pkg_id):
    """`.cmd` 的内容。`pkg_id` 为空 = 那个 `mo`（就是原样跑 moss）。

    形式（例）：`@echo off` + `"…\\moss.exe" --pkg img %*`。
    ★ 只有启动器路径加引号（它可能有空格）；`--pkg` / 包 id 是安全字符，不加引号更清爽。
    ★ 末尾的 `%*` = 用户敲的那串参数**原样**（cmd 变量语法，所以要写 `%*`）。
      `@echo off` 免得把这条命令回显到控制台。
    """
    line = " ".join('"%s"' % a for a in launcher_argv())
    if pkg_id:
        line += " --pkg " + str(pkg_id)
    return "@echo off\r\n" + line + " %*\r\n"


def prefix():
    """当前的前缀（用户在设置里改过就用他的；坏字符就地洗掉，空则退回默认）。

    ★ 校验在 `config._check_values` / `rules.problems` 里（字母开头、只含字母/数字/-/_、
      1~8 个字符）—— 但这里**再兜一道**：万一配置被人手写坏了，也别生成一个非法文件名。
    """
    raw = str((config.CONFIG.get("shortcut") or {}).get("prefix") or PREFIX).strip()
    return re.sub(r"[^A-Za-z0-9_-]", "", raw) or PREFIX


def _desired():
    """按配置算出"应该有哪些短命令"：`{短名: 包id 或 None}`（None = 就是 moss）。"""
    sc = config.CONFIG.get("shortcut") or {}
    p = prefix()
    want = {}
    if sc.get("mo"):
        want[p] = None
    if sc.get("pkg"):
        for rec in registry.scan_all():
            want[p + str(rec["id"])] = str(rec["id"])
    return want


# ---------------------------------------------------------------- PATH（注册表，HKCU）
_HWND_BROADCAST = 0xFFFF
_WM_SETTINGCHANGE = 0x001A


def _broadcast():
    """告诉系统"环境变量变了" —— 新开的进程才会拿到新 PATH。"""
    try:
        ctypes.windll.user32.SendNotifyMessageW(
            _HWND_BROADCAST, _WM_SETTINGCHANGE, 0, ctypes.c_wchar_p("Environment"))
    except Exception:                                                     # noqa: BLE001
        pass


def _user_path_list():
    """当前用户 PATH（拆成一条条）。系统 PATH 在 HKLM，我们**不动**。"""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
        return [p.strip() for p in str(value).split(";") if p.strip()]
    except Exception:                                                     # noqa: BLE001
        return []


def _same_path(a, b):
    try:
        return os.path.normpath(str(a)).lower() == os.path.normpath(str(b)).lower()
    except Exception:                                                     # noqa: BLE001
        return str(a).lower() == str(b).lower()


def _path_has(d):
    return any(_same_path(p, d) for p in _user_path_list())


def _system_path_list():
    """系统 PATH（HKLM）—— **只读**，只用来判断"moss 是不是已经能被找到"。"""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment") as key:
            value, _ = winreg.QueryValueEx(key, "Path")
        return [p.strip() for p in str(value).split(";") if p.strip()]
    except Exception:                                                     # noqa: BLE001
        return []


def moss_on_path():
    """moss **现在（持久地）能不能被找到**：用户 PATH 或系统 PATH 里有它的安装目录。

    ★ 只认**注册表里的 PATH**（会持久生效的那两个），**不算当前进程的环境 PATH**
      （`V-299` 实测教训）：用户以前加过、后来删了，但**没重启**，当前环境里还留着
      旧 PATH —— 只看环境会显示"在"，可一重启就没了。开关要说的是"**重启也在**"，
      否则用户以为"能用"就不再管它，重启后又没了（这就是那次误删的现场）。
    """
    home = str(paths.HOME)
    if _path_has(home):                                   # 当前用户 PATH（我们唯一会改的那处）
        return True
    return any(_same_path(p, home) for p in _system_path_list())   # 系统 PATH（只读）


def _write_user_path(items):
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, ";".join(items))
        _broadcast()
        return True
    except Exception:                                                     # noqa: BLE001
        return False


# ---------------------------------------------------------------- 账本
def _read_ledger():
    try:
        data = json.loads(_ledger_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:                                                     # noqa: BLE001
        return {}


def _write_ledger(data):
    paths.ensure_user_dirs()
    _ledger_file().write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")


# ---------------------------------------------------------------- 同步
def sync():
    """让磁盘现实和配置一致（**幂等**）。返回这次真做了什么的清单（人话）。

    被这几处调用：改设置（`--settings-set`）、建包 / 改名 / 卸包
    （`--new` / `--rename` / `--remove`）、以及手动 `moss --alias sync`。
    两边都对什么都不做（已经一致）时返回空列表。
    """
    if os.name != "nt":
        return []                                   # 短命令只在 Windows 上做
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

    # ① 生成 / 更新 shim
    new_files = {}
    for name, pid in sorted(want.items()):
        fn = d / (name + ".cmd")
        # ★ 用**字节**比较 / 写：`.cmd` 必须是 CRLF，而 `read_text` 会把 CRLF 归一成 LF
        #   —— 拿文本比就永远"不一样"，于是每次 sync 都重写一遍（不幂等，实测踩过）。
        want = _shim_text(pid).encode("utf-8")
        try:
            if (not fn.is_file()) or fn.read_bytes() != want:
                fn.write_bytes(want)
                msgs.append("生成 %s.cmd  →  %s" % (name, ("moss %s %s" % (config.plugin_symbol(), pid))
                                                    if pid else "moss"))
        except OSError as e:
            msgs.append("写不了 %s：%s" % (fn, e))
            continue
        new_files[name] = pid

    # ② 删掉"不再需要"的 —— **只看账本记着的**，绝不碰别人的同名文件
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

    # ③ PATH：有短命令就确保目录在里面；一个都不剩就把它摘掉
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

    # ③.5 moss 自己的目录（`V-299`，`[path].moss`）：让 `moss` 命令在任何终端能用。
    #      ★ 只删**我们自己加进去的那条**（账本记着 `moss_dir`）—— 用户自己早就加过的，
    #        关开关时不去动它。
    home = str(paths.HOME)
    want_moss = bool((config.CONFIG.get("path") or {}).get("moss"))
    we_added = (str(ledger.get("moss_dir") or "") == home)
    if want_moss and not moss_on_path():          # 已经在（系统/环境）PATH 里就不重复加
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
        we_added = False                     # 关了就不再是我们管的了

    # ④ 账本：永远反映"现在生成了哪些" + "moss 目录是不是我们加的"
    new_ledger = {"dir": d_str, "launcher": launcher_argv(), "files": new_files,
                  "moss_dir": (home if we_added else None)}
    if new_ledger != ledger:
        _write_ledger(new_ledger)
    return msgs


def status():
    """给界面 / 排障看的现状（纯数据）。"""
    sc = config.CONFIG.get("shortcut") or {}
    d = shortcuts_dir()
    ledger = _read_ledger()
    files = sorted((ledger.get("files") or {}).keys())
    return {"prefix": prefix(), "mo": bool(sc.get("mo")), "pkg": bool(sc.get("pkg")),
            "dir": str(d), "on_path": _path_has(d), "files": files,
            "moss": bool((config.CONFIG.get("path") or {}).get("moss")),
            "moss_dir": str(paths.HOME), "moss_on_path": moss_on_path()}


# ---------------------------------------------------------------- CLI
def cmd_alias(argv):
    """`moss --alias sync|status` —— 手动对账 / 看现状。

    ★ 开关本身不在这儿：它俩是 config.toml 的 `[shortcut]`（界面「设置 → 短命令」里改）。
      这里只负责"让现实追上配置"和"看一眼现在什么样"。
    """
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
        return 0
    out.print_cyan("[错误] 不认识的 --alias 子命令：%s（有：sync / status）" % verb)
    return 1
