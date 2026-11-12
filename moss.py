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
