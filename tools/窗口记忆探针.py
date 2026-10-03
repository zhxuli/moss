# -*- coding: utf-8 -*-
"""窗口记忆探针（`V-223`）：`system/ui/win_geom.py` 的**双屏 / 拔屏 / 最大化**行为。

为什么要单独一个探针
--------------------
"记住窗口大小和位置"看着是个一行功能，真正的坑全在**边界**上：
  · 坐标是**虚拟屏**的 —— 副屏摆在主屏左边时整片都是负数，写 `x < 0` 判坏就废了；
  · 显示器拔了 / 换了分辨率 ⇒ 上次存的位置在**不存在的屏**上，窗口会开在看不见的地方；
  · 最大化那一瞬间 `moved` 事件可能比 `maximized` 先到，拿事件参数存就会把
    `-8,-8,1936,1048`（最大化后的矩形）当成"正常位置"，**下一次开越开越大**；
  · 最小化时坐标是 `-32000` 那种，绝不能存。

所以分两半：
  A 纯逻辑（不开窗）：把上面这些情形一条条喂给 `resolve()` / `load()` / `save()`；
  B **真窗口**：起一个**隐藏的** pywebview 窗口（不会出现在屏幕上），用 Win32 去移动 /
    最大化 / 最小化它，看 `watch()` 是不是把这些都记对了 —— 事件链路是真的。

用法：
    .\\system\\runtimes\\python\\3.12\\python.exe tools\\窗口记忆探针.py
"""
import ctypes
import json
import os
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "system" / "ui"
sys.path.insert(0, str(UI))
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                    # noqa: BLE001
        pass

import win_geom as G                                                 # noqa: E402

RES = []
MONO = [{"rect": (0, 0, 3840, 2160), "work": (0, 0, 3840, 2112), "primary": True}]
DUAL = MONO + [{"rect": (-3840, 0, 0, 2160), "work": (-3840, 0, 0, 2112), "primary": False}]


def chk(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + detail) if detail else ""))


# ---------------------------------------------------------------- A 纯逻辑
def part_a(tmp):
    print("=" * 72)
    print("A：纯逻辑（不开窗）—— 双屏 / 拔屏 / 越界 / 坏文件")
    print("=" * 72)
    r = G.resolve({}, DUAL)
    chk("A 没存过 → 默认大小 + 居中（不给 x/y）",
        (r["width"], r["height"], r["x"], r["y"]) == (1280, 860, None, None), str(r))

    saved = {"x": -3000, "y": 200, "width": 1200, "height": 800}
    r = G.resolve(saved, DUAL)
    chk("★ A 双屏：存在**副屏**上（x 是负数）→ 原样用，不许当成坏的",
        (r["x"], r["y"], r["width"]) == (-3000, 200, 1200), str(r))
    r1 = G.resolve(saved, MONO)
    chk("★ A 拔了副屏：同一个存档 → 位置居中，但**大小还记着**",
        (r1["x"], r1["y"], r1["width"], r1["height"]) == (None, None, 1200, 800),
        str(r1) + " / " + r1["why"])

    r = G.resolve({"x": 99999, "y": 99999, "width": 1200, "height": 800}, DUAL)
    chk("A 位置跑到屏幕外 → 居中（大小保留）",
        (r["x"], r["y"], r["width"]) == (None, None, 1200), str(r))

    r = G.resolve({"x": 100, "y": 100, "width": 99999, "height": 99999}, DUAL)
    chk("A 大小超过整个虚拟屏 → 裁到虚拟屏（7680x2160）",
        (r["width"], r["height"]) == (7680, 2160), str(r))

    r = G.resolve({"x": 100, "y": 100, "width": 400, "height": 300}, DUAL)
    chk("A 存的大小比最小尺寸还小 → 判坏，回到默认",
        (r["width"], r["height"], r["x"]) == (1280, 860, None), str(r))

    r = G.resolve({"width": 1400, "height": 900}, DUAL)
    chk("A 只有大小没位置 → 按那个大小居中",
        (r["width"], r["height"], r["x"]) == (1400, 900, None), str(r))

    r = G.resolve({"x": 1280, "y": 650, "width": 1200, "height": 800, "maximized": True}, DUAL)
    chk("A 最大化标记会一起带回来", r["maximized"] is True and r["x"] == 1280, str(r))

    r = G.resolve({"x": -3000, "y": 200, "width": 1200, "height": 800}, [])
    chk("A 读不到显示器信息时 → 原样相信存档（别瞎裁）",
        (r["x"], r["y"]) == (-3000, 200), str(r))

    # 标题栏只露一点点：还抓得住就算数（横跨两块屏是合法用法，不该被拉回来）
    r = G.resolve({"x": -30, "y": 10, "width": 3000, "height": 900}, DUAL)
    chk("A 横跨两块屏的窗口 → 认（只要标题栏抓得住，不硬拉回来）",
        (r["x"], r["width"]) == (-30, 3000), str(r))

    print()
    print("  —— 存 / 读 ——")
    p = tmp / "_ui_window.json"
    geom = {"x": -3210, "y": 77, "width": 1234, "height": 777, "maximized": True}
    chk("A 原子写成功", G.save(p, geom) is True, "")
    chk("A 读回来一模一样（含负数 / 布尔）", G.load(p) == geom, str(G.load(p)))
    chk("A 写盘不留 .tmp 残渣", not Path(str(p) + ".tmp").exists(), "")
    p.write_text("{ 这不是 JSON", encoding="utf-8")
    chk("A 坏文件不炸（当没存过）", G.load(p) == {}, str(G.load(p)))
    G.save(p, geom)
    p.write_text("[1,2,3]", encoding="utf-8")
    chk("A 存成数组（不是对象）也当没存过", G.load(p) == {}, str(G.load(p)))


# ---------------------------------------------------------------- B 真窗口
def part_b(tmp):
    print()
    print("=" * 72)
    print("B：**真窗口**（隐藏的 pywebview 窗，用 Win32 驱动 —— 不会出现在你屏幕上）")
    print("=" * 72)
    try:
        import webview
    except Exception as e:                                               # noqa: BLE001
        chk("B 这台机器有 pywebview", False, str(e))
        return
    u32 = ctypes.WinDLL("user32", use_last_error=True)
    SW_MAXIMIZE, SW_RESTORE, SW_MINIMIZE = 3, 9, 6
    geomfile = tmp / "_ui_window_real.json"
    out = {"done": threading.Event()}

    win = webview.create_window("moss-wingeom-probe", html="<html><body>probe</body></html>",
                                width=1000, height=700, x=200, y=150,
                                min_size=(900, 600), hidden=True)

    def job():
        try:
            win.events.loaded.wait(20)
            time.sleep(0.5)
            hwnd = G._hwnd_of(win)
            chk("B 拿到窗口句柄", bool(hwnd), "hwnd=%s" % hwnd)
            chk("★ B 窗口**从没显示**过（探针不打扰你）",
                not u32.IsWindowVisible(ctypes.c_void_p(hwnd)), "")

            snap = G.rect_from_hwnd(hwnd)
            chk("B GetWindowPlacement 读得出几何",
                bool(snap) and (snap["w"], snap["h"]) == (1000, 700)
                and (snap["x"], snap["y"]) == (200, 150), str(snap))

            # 移动到**负数**坐标（副屏那侧）
            u32.MoveWindow(ctypes.c_void_p(hwnd), -1500, 120, 1000, 700, True)
            time.sleep(0.4)
            chk("★ B 移到负坐标后读得回来（副屏那侧）",
                (lambda s: bool(s) and (s["x"], s["y"]) == (-1500, 120))(G.rect_from_hwnd(hwnd)),
                str(G.rect_from_hwnd(hwnd)))

            # 上真的 watch —— 事件 → 延迟写盘
            st = G.watch(win, geomfile, delay=0.15)
            u32.MoveWindow(ctypes.c_void_p(hwnd), 320, 260, 1100, 720, True)
            time.sleep(0.8)
            got = G.load(geomfile)
            chk("★ B 真移动 → 事件链路把新的位置记下来了",
                (got.get("x"), got.get("y"), got.get("width")) == (320, 260, 1100), str(got))
            saved_n = st["saved"]

            u32.ShowWindow(ctypes.c_void_p(hwnd), SW_MAXIMIZE)
            time.sleep(0.9)
            got = G.load(geomfile)
            chk("★ B 最大化 → 记的是**最大化**这件事，坐标仍是「正常」那份（不是 -8,-8）",
                got.get("maximized") is True and (got.get("x"), got.get("width")) == (320, 1100),
                str(got))

            u32.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
            time.sleep(0.9)
            got = G.load(geomfile)
            chk("B 还原 → 最大化标记回到 false", got.get("maximized") is False, str(got))

            before = G.load(geomfile)
            n_before = st["saved"]
            u32.ShowWindow(ctypes.c_void_p(hwnd), SW_MINIMIZE)
            time.sleep(0.9)
            chk("★ B 最小化 → **不写盘**（那时候坐标是 -32000 那种）",
                st["saved"] == n_before and G.load(geomfile) == before,
                "saved %d → %d / %s" % (n_before, st["saved"], G.load(geomfile)))

            u32.ShowWindow(ctypes.c_void_p(hwnd), SW_RESTORE)
            time.sleep(0.3)
            u32.MoveWindow(ctypes.c_void_p(hwnd), -2222, -7, 1000, 700, True)
            time.sleep(0.8)
            got = G.load(geomfile)
            chk("★ B 连负坐标的 y 也存得住（-7）", got.get("y") == -7 and got.get("x") == -2222,
                str(got))

            st["flush"]()
            chk("B flush() 手动补一次也正常", G.load(geomfile).get("x") == -2222, "")

            # ★ 关窗那一刻的收尾：移动之后**不等**那 0.8 秒的延迟，直接 destroy ——
            #   `closing` 必须在窗口销毁**之前**把最后的位置补上（只靠 `closed` 就丢了）。
            G.save(geomfile, {"x": 0, "y": 0, "width": 900, "height": 600})
            u32.MoveWindow(ctypes.c_void_p(hwnd), -777, 88, 1000, 700, True)
            time.sleep(0.15)                     # 比 delay(0.15) 还短，逼它走 closing 那条
            win.destroy()
            time.sleep(0.5)
            got = G.load(geomfile)
            chk("★ B 关窗时会补最后一次（closing 早于销毁，别等 closed）",
                (got.get("x"), got.get("y")) == (-777, 88), str(got))
        except Exception as e:                                           # noqa: BLE001
            chk("B 真窗口这一段没抛错", False, "%s: %s" % (type(e).__name__, e))
        finally:
            try:
                win.destroy()
            except Exception:                                            # noqa: BLE001
                pass
            out["done"].set()

    webview.start(job)
    out["done"].wait(20)


def part_c(tmp):
    """C：**真·宿主那份 `system/ui/main.py`** 的装配 —— 它到底有没有把存下来的几何喂给
    `create_window`。

    ★ 把 `MOSS_USER_DATA_DIR` 指到临时目录再 import：几何文件、内联页都落在临时目录里，
      **不碰你的真配置**（也不会真开窗：pywebview 要到 `webview.start()` 才有原生窗口）。
    """
    import importlib.util
    import json as _json
    print()
    print("=" * 72)
    print("C：真·main.py 的装配（临时 user_data；只 import，不 start —— 不会开窗）")
    print("=" * 72)
    home = tmp / "home"
    udata = home / "user_data"
    (udata / "state").mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)

    cases = [
        ("存了副屏的位置", {"x": -3000, "y": 200, "width": 1200, "height": 800},
         {"x": -3000, "y": 200, "w": 1200, "h": 800, "maximized": False}),
        ("存的位置已经没屏了", {"x": 99999, "y": 99999, "width": 1300, "height": 900},
         {"x": None, "y": None, "w": 1300, "h": 900, "maximized": False}),
        ("存的是最大化", {"x": 100, "y": 120, "width": 1500, "height": 950, "maximized": True},
         {"x": 100, "y": 120, "w": 1500, "h": 950, "maximized": True}),
    ]
    for i, (name, saved, want) in enumerate(cases):
        geom_file = udata / "state" / G.WIN_GEOM_NAME
        G.save(geom_file, saved)
        payload = {"home": str(home), "user_data": str(udata), "host_cmd": ["moss.exe"],
                   "launch_kind": "probe", "icon_exts": [".svg"], "packages": []}
        pfile = tmp / ("payload%d.json" % i)
        pfile.write_text(_json.dumps(payload), encoding="utf-8")
        os.environ["MOSS_HOME"] = str(home)
        os.environ["MOSS_USER_DATA_DIR"] = str(udata)
        os.environ["MOSS_UI_DATA"] = str(pfile)
        for m in ("win_geom", "moss_ui_main_probe%d" % i):
            sys.modules.pop(m, None)
        spec = importlib.util.spec_from_file_location("moss_ui_main_probe%d" % i, UI / "main.py")
        M = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(M)
        except Exception as e:                                           # noqa: BLE001
            chk("C[%s] main.py 能 import" % name, False, "%s: %s" % (type(e).__name__, e))
            continue
        w = M.window
        got = {"x": w.initial_x, "y": w.initial_y, "w": w.initial_width,
               "h": w.initial_height, "maximized": bool(w.maximized)}
        chk("★ C[%s] 装配出来的窗口参数对得上" % name, got == want, "拿到 %s / 期望 %s" % (got, want))
        chk("C[%s] 最小尺寸还是 900x600" % name, tuple(w.min_size) == (900, 600), str(w.min_size))
        chk("C[%s] 几何文件指向临时目录（没碰真配置）" % name,
            str(M._WIN_GEOM_FILE).startswith(str(udata)), str(M._WIN_GEOM_FILE))
        chk("C[%s] 存盘盯梢挂上了（记的路径一致）" % name,
            isinstance(getattr(M, "_GEOM_WATCH", None), dict)
            and str(M._GEOM_WATCH.get("path")) == str(M._WIN_GEOM_FILE), "")
        try:
            w.destroy()                       # 别留着这些没 start 的 Window 对象
        except Exception:                                                # noqa: BLE001
            pass


def main():
    tmp = Path(tempfile.mkdtemp(prefix="moss_wingeom_"))
    try:
        print("这台机器的显示器（真的，不是编的）：")
        for s in G.screens():
            print("   %s  rect=%s  work=%s" % ("主屏" if s["primary"] else "副屏",
                                               s["rect"], s["work"]))
        part_a(tmp)
        if "--logic-only" not in sys.argv:
            part_b(tmp)
            part_c(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 72)
    bad = [x for x in RES if not x[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的", len(RES), len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
