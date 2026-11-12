import os
import runpy
import sys

def main():
    if len(sys.argv) < 2:
        print("[bootstrap] 用法: python bootstrap.py <目标脚本> [参数...]")
        return 2

    script = sys.argv[1]

    sys.argv = [script] + sys.argv[2:]

    script_dir = os.path.dirname(os.path.abspath(script))
    if script_dir and script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    runpy.run_path(script, run_name="__main__")
    return 0

if __name__ == "__main__":
    sys.exit(main())
