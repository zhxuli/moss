import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from core import config as C

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
                "placeholder": it.get("placeholder") or "",
                "default": C.DEFAULT_CONFIG[section][name],
            })
        groups.append({"name": g["name"], "icon": g.get("icon") or "",
                       "blurb": g.get("blurb") or "", "live": bool(g.get("live")),
                       "items": items})
    return {
        "_note": "由 tools/导出设置清单.py 从 core/config.py 的 SETTINGS_GROUPS 生成 —— 别手改",
        "version": 1,
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
        except Exception:
            pass
    sys.exit(main())
