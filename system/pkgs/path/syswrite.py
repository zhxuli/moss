import ctypes
import json
import sys
import winreg

KEY = winreg.HKEY_LOCAL_MACHINE
SUB = r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A

def broadcast():
    try:
        ctypes.windll.user32.SendNotifyMessageW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, ctypes.c_wchar_p('Environment'))
    except Exception:
        pass

def main(argv):
    if len(argv) < 3:
        return 2
    payload_file, result_file = argv[1], argv[2]
    res = {"ok": False, "msg": "没写：原因不明"}
    try:
        with open(payload_file, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        paths = [str(p).strip() for p in (data.get('paths') or []) if str(p).strip()]
    except Exception as e:
        paths = None
        res = {"ok": False, "msg": "读不懂要写的内容：%s" % e}

    if paths is not None:
        try:
            with winreg.OpenKey(KEY, SUB, 0, winreg.KEY_READ | winreg.KEY_WRITE) as key:
                try:
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
