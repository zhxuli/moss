import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import core

def _moss_args():
    import json as _json
    raw = os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            got = str(_json.loads(raw).get("args") or "").strip()
            if got:
                return got
        except Exception:
            pass
    return (os.environ.get("MOSS_ARGS") or "").strip()

def main():
    try:
        from embed import Embedded, embedded_now
        if embedded_now():
            return Embedded().loop()
    except ImportError:
        pass

    line = _moss_args()
    if line:
        argv = [a for a in line.split() if a.strip()]
    else:
        argv = [a for a in sys.argv[1:] if a not in ("-c", "") and not a.endswith("main.py")]

    if not argv:
        interactive = str(os.environ.get("MOSS_INTERACTIVE") or "").strip() in ("1", "true", "yes")
        if interactive:
            core.gui()
            return 0
        code, text = core.Api().cli(["help"])
        print(text)
        return code
    if argv[0].lower() in ("gui", "-g", "--gui"):
        core.gui()
        return 0
    code, text = core.Api().cli(argv)
    if text:
        print(text)
    return code

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[提示] 操作已取消。")
