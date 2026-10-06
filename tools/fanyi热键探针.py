# -*- coding: utf-8 -*-
"""fanyi 全局热键探针（不烧 token、不动真剪贴板/键鼠）。

验三件事：
  1. **双击判定**：`Hotkey.feed_ctrl()` 两次快按算一次双击；冷却期内不算；注入的 Ctrl 不算。
  2. **真钩子能装能卸**：`start()` 真调 `SetWindowsHookEx(WH_KEYBOARD_LL)`，`stop()` 卸掉。
  3. **动作流程**（monkeypatch 掉键鼠/剪贴板/翻译）：Ctrl+A → Ctrl+X → 翻译 → Ctrl+V，
     成功留译文、失败粘回原文并还原剪贴板。

跑法：
    python tools\\fanyi热键探针.py
"""
import importlib.util
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("MOSS_HOME", str(ROOT))
_TMP = tempfile.mkdtemp(prefix="moss_fanyi_hk_")
os.environ["MOSS_PLUGIN_DATA_DIR"] = _TMP
os.environ["MOSS_PLUGIN_CACHE_DIR"] = os.path.join(_TMP, "cache")


def load_main():
    spec = importlib.util.spec_from_file_location(
        "fanyi_main", str(ROOT / "system" / "pkgs" / "fanyi" / "main.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fails = []


def chk(name, ok, detail=""):
    print(("  OK  " if ok else " FAIL ") + name + (("  " + str(detail)) if detail else ""))
    if not ok:
        fails.append(name)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                                # noqa: BLE001
            pass
    m = load_main()
    print("fanyi 热键探针（pid %d）" % os.getpid())
    print("=" * 60)

    # 1) 双击判定
    hk = m.Hotkey(lambda: None)
    chk("第一次 Ctrl 不触发", hk.feed_ctrl() is False)
    chk("紧接的第二次 Ctrl 触发", hk.feed_ctrl() is True)

    hk2 = m.Hotkey(lambda: None)
    hk2.feed_ctrl()
    hk2.feed_ctrl()                          # 触发
    hk2._last_fire = time.time()             # 假装刚刚触发过 → 进冷却
    hk2._last_ctrl = 0.0
    chk("冷却期内不再触发", hk2.feed_ctrl() is False)

    hk3 = m.Hotkey(lambda: None)
    hk3.feed_ctrl()
    chk("注入的 Ctrl 不算（不递归）", hk3.feed_ctrl(injected=True) is False)

    # 2) 真钩子装/卸
    hk4 = m.Hotkey(lambda: None)
    r = hk4.start()
    chk("装键盘钩子成功", r.get("ok") is True, r)
    time.sleep(0.2)
    chk("钩子线程活着（消息循环没崩）", hk4._thread is not None and hk4._thread.is_alive())
    chk("工作线程活着", hk4._worker is not None and hk4._worker.is_alive())
    chk("status=运行中", hk4.status().get("running") is True)
    hk4.stop()
    chk("卸钩子后 status=停了", hk4.status().get("running") is False)
    # ★ 这一条是"整机键盘卡死"那个 bug 的护栏：HHOOK 必须 64 位、卸钩必须成功
    chk("卸钩子真的成功（HHOOK 没被截断）", hk4._unhook_ok is True, hk4._unhook_ok)

    # 3) 动作流程（全 monkeypatch，不碰真剪贴板/键鼠）
    pressed = []
    state = {"clip": "原来的剪贴板"}
    m.clipboard_get = lambda: (state["clip"], None)

    def fake_set(t):
        state["clip"] = t
        return True, None

    m.clipboard_set = fake_set

    def press(mod, key):
        pressed.append((mod, key))
        if key == m.VK_X:                    # 模拟"剪切选中文字"
            state["clip"] = "hello"

    m._press_combo = press
    m.do_translate = lambda text, target: {"ok": True, "translated": "TRANSLATED:" + text,
                                           "source": "en", "target": "en"}
    ev1 = []
    m.perform_translation_action(lambda p, d: ev1.append((p, d)))
    chk("成功：按了 Ctrl+A", (m.VK_CONTROL, m.VK_A) in pressed)
    chk("成功：按了 Ctrl+X", (m.VK_CONTROL, m.VK_X) in pressed)
    chk("成功：按了 Ctrl+V", (m.VK_CONTROL, m.VK_V) in pressed)
    chk("成功：剪贴板留译文", state["clip"] == "TRANSLATED:hello", state["clip"])
    chk("成功：上报 done", any(p == "done" for p, _ in ev1))

    # 失败路径
    pressed.clear()
    state["clip"] = "orig"
    m.do_translate = lambda text, target: {"ok": False, "why": "没网"}
    ev2 = []
    m.perform_translation_action(lambda p, d: ev2.append((p, d)))
    chk("失败：上报 fail", any(p == "fail" for p, _ in ev2))
    chk("失败：按了 Ctrl+V 粘回", (m.VK_CONTROL, m.VK_V) in pressed)
    chk("失败：还原了原剪贴板", state["clip"] == "orig", state["clip"])

    print("=" * 60)
    print("失败：%d" % len(fails))
    for f in fails:
        print("  - " + f)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
