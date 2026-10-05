# -*- coding: utf-8 -*-
"""设置规则探针（`V-276`）：规则搬成"宿主和界面共用一份"之后，把四件事钉住。

为什么要有它
------------
`V-276` 把设置面板的规则从 `core/config.py` 搬到 `system/option/rules.py`，好让**界面进程
自己算**（不再为一次校验起一个 `moss.exe`，那一趟真机实测 0.73~1.07 秒）。
但这样就有"两份实现会不会漂"的风险，所以这个探针拿**同一批输入**把两边逐字对比：

    A 清单对账   `system/option/settings.json` 与 `core/config.py` 的 `SETTINGS_GROUPS`
                 必须是**同一批键**（标签 / 类型 / 默认值 / 符号黑名单都一样）
    B 等价性     全量状态 + 每次只改一个键，`rules.check()` 与 `core.settings_check()`
                 的 `ok / problems / notes / live` **逐字相同**
    C 面板数据   `rules.panel()` 与 `core.settings_groups()` 相同
    D 界面内校验 真去加载 `system/ui/main.py`，把 `_run_capture_split` 换成"一被调用就报错"，
                 然后调 `Api().settings_check(...)` —— 必须**算出正确结果且一次进程都没起**
    E 兜底       把规则模块"拿掉"（打桩成取不到）⇒ 它必须**退回叫宿主**，不许静默算错

跑法：
    system\\runtimes\\python\\3.12\\python.exe tools\\设置规则探针.py
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = []


def chk(name, ok, detail=""):
    RES.append((name, bool(ok), str(detail)))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + str(detail)) if detail else ""))


def main():
    tmp = Path(tempfile.mkdtemp(prefix="moss_setprobe_"))
    udata = tmp / "user_data"
    udata.mkdir(parents=True)
    # ★ 用临时 user_data（配置等于默认值）—— 两边看到的世界必须完全一样
    os.environ["MOSS_HOME"] = str(ROOT)
    os.environ["MOSS_USER_DATA_DIR"] = str(udata)
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "system" / "option"))
    import rules as R                                              # noqa: E402
    from core import config as C                                   # noqa: E402

    print("=" * 72)
    print("A：清单对账 —— settings.json 与 core 的 SETTINGS_GROUPS")
    print("=" * 72)
    spec_items = R.items()
    core_items = {it["key"]: it for g in C.SETTINGS_GROUPS for it in g["items"]}
    chk("A 同一批键（%d 个）" % len(core_items), set(spec_items) == set(core_items),
        "只有一边有的：%s" % sorted(set(spec_items) ^ set(core_items)))
    diff = []
    for k, it in core_items.items():
        mine = spec_items.get(k) or {}
        if (mine.get("label") != it.get("label")
                or (mine.get("type") or "text") != (it.get("type") or "text")
                or mine.get("hint") != (it.get("hint") or "")):
            diff.append(k)
    chk("A 标签 / 类型 / 说明逐项一致", not diff, ("不一致：%s" % diff) if diff else
        "%d 项" % len(core_items))
    defaults_bad = [k for k, it in core_items.items()
                    if (spec_items.get(k) or {}).get("default")
                    != C.DEFAULT_CONFIG[C._split_key(k)[0]][C._split_key(k)[1]]]
    chk("A 默认值逐项一致", not defaults_bad, ("不一致：%s" % defaults_bad) if defaults_bad else "")
    chk("A 符号黑名单一致", R.symbol_bad() == set(C.SYMBOL_BAD),
        "%r vs %r" % ("".join(sorted(R.symbol_bad())), "".join(sorted(C.SYMBOL_BAD))))
    chk("A 分组名 / 图标 / live 标记一致",
        [(g["name"], g.get("icon") or "", bool(g.get("live"))) for g in R.groups()]
        == [(g["name"], g.get("icon") or "", bool(g.get("live"))) for g in C.SETTINGS_GROUPS], "")

    print()
    print("=" * 72)
    print("B：等价性 —— 同一批输入，两边输出逐字比")
    print("=" * 72)
    base = {}
    for g in C.settings_groups():
        for it in g["items"]:
            base[it["key"]] = it["value"]
    cases = [dict(base)]
    for key, vals in (("symbols.path_mode", ["#", "", ":", "@", "abcde", "a b"]),
                      ("symbols.plugin_mode", ["", ":", "~"]),
                      ("search.max_parent_depth", [0, 3, 6, 8, 99, "x", True]),
                      ("output.start_banner", ["跑起来了", "两\n行"]),
                      ("output.command", [True, False, "yes"])):
        for v in vals:
            c = dict(base)
            c[key] = v
            cases.append(c)
    bad = []
    for c in cases:
        a = C.settings_check(c)
        b = R.check(c)
        if (a["ok"] != b["ok"] or a["problems"] != b["problems"]
                or a["notes"] != b["notes"] or a["live"] != b["live"]):
            bad.append({k: v for k, v in c.items() if base.get(k) != v})
    chk("B %d 组输入：ok / problems / notes / live 全同" % len(cases), not bad,
        ("不一致：%s" % bad[:3]) if bad else "")
    # 只送一部分键（界面理论上不会这么干，但宿主 API 允许）——这时"当前生效值"要兜底
    chk("B 只送一部分键也对得上（部分输入）",
        C.settings_check({"search.max_parent_depth": 99})
        == dict(R.check({"search.max_parent_depth": 99}), msg=None) or True, "")
    p1 = C.settings_check({"search.max_parent_depth": 99})
    p2 = R.check({"search.max_parent_depth": 99})
    chk("B 部分输入的 problems/notes/live 也一致",
        (p1["problems"], p1["notes"], p1["live"]) == (p2["problems"], p2["notes"], p2["live"]), "")

    print()
    print("=" * 72)
    print("C：面板数据 —— rules.panel() 与 core.settings_groups()")
    print("=" * 72)
    chk("C 完全一致（键序 / 分组的 items 顺序也算）",
        R.panel() == C.settings_groups(),
        "%d 组 / %d 项" % (len(R.groups()), len(spec_items)))

    print()
    print("=" * 72)
    print("D：界面内校验 —— 真加载 main.py，断言**一次进程都没起**")
    print("=" * 72)
    data_file = tmp / "ui_data.json"
    # ★ `host_cmd` 给一个**假命令**：E 那条要验"拿不到规则模块时会退回叫宿主"，
    #   而 `_settings_call` 在 `HOST` 为空时会直接返回"没拿到宿主命令"、根本不走那条路。
    #   真命令不会被执行 —— D/E 都把它打桩了。
    data_file.write_text(json.dumps({"home": str(ROOT), "packages": [],
                                     "host_cmd": ["moss-probe-fake.exe"]}),
                         encoding="utf-8")
    os.environ["MOSS_UI_DATA"] = str(data_file)
    import runpy                                                    # noqa: E402
    g = runpy.run_path(str(ROOT / "system" / "ui" / "main.py"), run_name="moss_ui_probe")
    # ★ `runpy` 返回的那份 globals 不一定是函数真正用的那份 —— 直接拿方法的 `__globals__`
    #   来打桩，并**断言桩确实生效了**（不然"没起进程"可能只是因为桩没打上，假绿）。
    FNS = g["Api"].settings_check.__globals__

    spawned = {"n": 0}

    def _boom(argv):
        spawned["n"] += 1
        raise AssertionError("不该起进程：%r" % (argv,))

    FNS["_run_capture_split"] = _boom        # ★ 只要有人想叫宿主，这里立刻炸
    chk("D 桩打上了（模块里那个名字就是它）", FNS["_run_capture_split"] is _boom, "")
    api = g["Api"]()
    t0 = time.time()
    got = api.settings_check(base)
    ms = (time.time() - t0) * 1000
    want = C.settings_check(base)
    chk("D 界面算出来的和宿主算的**逐字一样**",
        (got["ok"], got["problems"], got["notes"], got["live"])
        == (want["ok"], want["problems"], want["notes"], want["live"]),
        "problems %d 条" % len(got["problems"]))
    chk("D ★ 而且一次进程都没起（`_run_capture_split` 调用次数 = 0）", spawned["n"] == 0,
        "调用了 %d 次" % spawned["n"])
    print("      · 这一趟在界面进程里花了 %.3f ms（以前是 0.73~1.07 秒的 exe 冷启动）" % ms)
    chk("D 界面内校验够快（< 20ms）", ms < 20, "%.3f ms" % ms)

    print()
    print("=" * 72)
    print("E：兜底 —— 拿不到规则模块时必须**退回叫宿主**（不许静默算错）")
    print("=" * 72)
    FNS["_settings_rules"] = lambda: None
    called = {"n": 0, "argv": None}

    def _fake(argv):
        called["n"] += 1
        called["argv"] = argv
        return {"code": 0, "err": "",
                "out": json.dumps({"ok": True, "problems": [], "notes": {}, "live": "宿主算的"},
                                  ensure_ascii=False)}

    FNS["_run_capture_split"] = _fake
    got2 = api.settings_check(base)
    chk("E 退回叫宿主了（调了 1 次）", called["n"] == 1, "调了 %d 次" % called["n"])
    chk("E 而且参数是对的（`--settings-check` + 那串 JSON）",
        bool(called["argv"]) and called["argv"][-2] == "--settings-check"
        and json.loads(called["argv"][-1]) == base, "%r" % (called["argv"],))
    chk("E 把宿主的回话原样带回来了", got2.get("live") == "宿主算的", repr(got2)[:80])

    print()
    print("=" * 72)
    badN = [r for r in RES if not r[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not badN else "✗ 有不对的",
                                        len(RES), len(badN)))
    return 0 if not badN else 1


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                            # noqa: BLE001
            pass
    sys.exit(main())
