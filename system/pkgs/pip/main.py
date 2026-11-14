import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import core


def _moss_args():
    raw = os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            got = str(json.loads(raw).get("args") or "").strip()
            if got:
                return got
        except Exception:
            pass
    return (os.environ.get("MOSS_ARGS") or "").strip()


def _interactive():
    return str(os.environ.get("MOSS_INTERACTIVE") or "").strip().lower() in ("1", "true", "yes")


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # 内嵌界面：宿主给 MOSS_UI_EMBED=1，走 stdin/stdout 上的 JSON 行
    try:
        from embed import Embedded, embedded_now
        if embedded_now():
            return Embedded().loop()
    except ImportError:
        pass

    line = _moss_args()
    if line:
        try:
            import shlex
            argv = shlex.split(line)
        except Exception:
            argv = line.split()
    else:
        argv = [a for a in sys.argv[1:] if a not in ("-c", "") and not a.endswith("main.py")]

    if argv and argv[0].lower() in ("gui", "-g", "--gui", "ui"):
        return core.gui()

    if not argv:
        if _interactive():
            return core.gui()
        print(core.Api().cli(["env"])[1])
        return 0

    code, text = core.Api().cli(argv)
    if text:
        print(text)
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[提示] 已取消。")
