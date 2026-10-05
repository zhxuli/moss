# -*- coding: utf-8 -*-
"""一次性工具：把 `core/config.py` 里那份面板清单（`SETTINGS_GROUPS`）导出成 `system/option/settings.json`。

★ 为什么要它：`V-276` 把"设置面板长什么样"从代码搬成**数据** —— 宿主和界面读同一份。
  这份 JSON 由本脚本生成（**别手改**；要改面板就改 `core/config.py` 里的 `SETTINGS_GROUPS`
  再跑一次这个脚本），免得两份清单悄悄漂开。

跑法：
    system\\runtimes\\python\\3.12\\python.exe tools\\导出设置清单.py          # 看一眼，不写
    system\\runtimes\\python\\3.12\\python.exe tools\\导出设置清单.py --write  # 真的写
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config as C                     # noqa: E402

OUT = ROOT / "system" / "option" / "settings.json"


def build():
    groups = []
    for g in C.SETTINGS_GROUPS:
        items = []
        for it in g["items"]:
            section, name = C._split_key(it["key"])
            items.append({
                "key": it["key"],
                "label": it["label"],
                "type": it.get("type") or "text",
                "hint": it.get("hint") or "",
                # 默认值取 `DEFAULT_CONFIG`（面板上"没动过"时该是多少）
                "default": C.DEFAULT_CONFIG[section][name],
            })
        groups.append({"name": g["name"], "icon": g.get("icon") or "",
                       "blurb": g.get("blurb") or "", "live": bool(g.get("live")),
                       "items": items})
    return {
        "_note": "由 tools/导出设置清单.py 从 core/config.py 的 SETTINGS_GROUPS 生成 —— 别手改",
        "version": 1,
        # 命令行里有特殊意思的字符（`--settings-check` 用它报错）
        "symbol_bad": "".join(sorted(C.SYMBOL_BAD)),
        "groups": groups,
    }


def main():
    data = build()
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    n_items = sum(len(g["items"]) for g in data["groups"])
    print("分组 %d 个 / 项目 %d 个 / %d 字节"
          % (len(data["groups"]), n_items, len(text.encode("utf-8"))))
    if "--write" not in sys.argv[1:]:
        print("（没写盘；要写就加 --write）")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="")
    print("已写入 %s" % OUT)
    return 0


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                            # noqa: BLE001
            pass
    sys.exit(main())
