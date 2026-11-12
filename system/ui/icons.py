import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = HERE.parent.parent
SVG_DIR = HOME / "system" / "icon" / "svg"

_CACHE = {}

def _parse_one(text):
    m = re.search(r"<svg\b[^>]*\bviewBox=\"([^\"]+)\"[^>]*>(.*)</svg>", text, re.S | re.I)
    if not m:
        return None
    return {"vb": m.group(1).strip(), "body": m.group(2).strip()}

def table():
    if "all" in _CACHE:
        return _CACHE["all"]
    out = {}
    try:
        for p in sorted(SVG_DIR.glob("*.svg")):
            got = _parse_one(p.read_text(encoding="utf-8"))
            if got:
                out[p.stem] = got
    except OSError:
        pass
    _CACHE["all"] = out
    return out

def names():
    return sorted(table().keys())

def script_tag():
    data = json.dumps(table(), ensure_ascii=False, separators=(",", ":"))
    return ("<script>\n"
            "window.__MOSS_ICONS = %s;</script>" % data)
