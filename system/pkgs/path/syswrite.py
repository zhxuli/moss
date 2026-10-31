# -*- coding: utf-8 -*-
"""**提权写机器级 PATH 的小工人**（`V-389`）—— 只干这一件事，干完就退。

调用方式（由 `main.py` 的 `run_elevated()` 用 UAC 拉起来）：

    pythonw.exe syswrite.py <payload.json> <result.json>

* `payload.json` = `{"paths": ["...", "..."]}`（主进程用**普通权限**写的，它传过来的）
* `result.json`  = `{"ok": true/false, "msg": "…"}`（这里写的，主进程读它）

★ 为什么单独一个文件、单独一次提权：把整个界面进程提到管理员，等于让浏览器内核也拿到
  管理员权限，风险大得多。提权的范围**只有"把一个注册表值设成这一串"**，跑完立刻退出。
★ 不碰用户级（`HKCU`）那条：那是 `main.py` 的活儿。这里只写 `HKLM` 那一条。
★ 保持原来的值类型：`REG_EXPAND_SZ` 还是 `REG_EXPAND_SZ` —— 写成 `REG_SZ` 的话，
  `%SystemRoot%\\system32` 这种会**变成死字符串**（不会被展开），PATH 就悄悄坏了。
"""
import ctypes
import json
import sys
import winreg

KEY = winreg.HKEY_LOCAL_MACHINE
SUB = r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A


def broadcast():
    """告诉系统"环境变量变了"（新开的进程才会拿到新 PATH）。"""
    try:
        ctypes.windll.user32.SendNotifyMessageW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, ctypes.c_wchar_p('Environment'))
    except Exception:                                  # noqa: BLE001
        pass                                           # 广播失败不影响"值已经写进去了"


def main(argv):
    if len(argv) < 3:
        return 2
    payload_file, result_file = argv[1], argv[2]
    res = {"ok": False, "msg": "没写：原因不明"}
    try:
        with open(payload_file, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        paths = [str(p).strip() for p in (data.get('paths') or []) if str(p).strip()]
    except Exception as e:                             # noqa: BLE001
        paths = None
        res = {"ok": False, "msg": "读不懂要写的内容：%s" % e}

    if paths is not None:
        try:
            with winreg.OpenKey(KEY, SUB, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                try:                                   # 原来是哪种类型就还写哪种
                    _, typ = winreg.QueryValueEx(key, 'Path')
                except OSError:
                    typ = winreg.REG_EXPAND_SZ
                if typ not in (winreg.REG_SZ, winreg.REG_EXPAND_SZ):
                    typ = winreg.REG_EXPAND_SZ
                winreg.SetValueEx(key, 'Path', 0, typ, ';'.join(paths))
            broadcast()
            res = {"ok": True, "msg": "已写入系统 PATH：%d 条" % len(paths)}
        except PermissionError:
            res = {"ok": False, "msg": "没有管理员权限，写不了系统 PATH（这次什么都没改）"}
        except OSError as e:
            res = {"ok": False, "msg": "写 HKLM 失败：%s（这次什么都没改）" % e}

    try:
        with open(result_file, 'w', encoding='utf-8') as fh:
            json.dump(res, fh, ensure_ascii=False)
    except OSError:
        pass
    return 0 if res.get('ok') else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
