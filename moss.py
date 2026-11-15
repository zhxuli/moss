# 打包命令（tools/build.py 会核对这一行，必须和实际命令一致）：
# venv\Scripts\python.exe -m nuitka --onefile --lto=yes --remove-output --assume-yes-for-downloads --onefile-tempdir-spec="{CACHE_DIR}/moss_build/moss-<stamp>" --onefile-cache-mode=cached --windows-icon-from-ico=system/icon/moss.ico --windows-console-mode=hide --include-package=core -o moss.build moss.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from core import out as _out
_out.ensure_utf8_console()

from core import cli

def main():
    try:
        return cli.main(sys.argv[1:])
    except KeyboardInterrupt:
        print("\n[提示] 操作已取消。")
        return 130

if __name__ == "__main__":
    sys.exit(main())
