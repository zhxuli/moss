import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = HERE.parent

DEFAULT_SRC = Path(r"D:\python\two\QuickTools\pa_soft\bin\runtime")
DEFAULT_DST = HOME / "system" / "runtimes" / "python" / "3.12"

def count(d):
    n = s = 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            n += 1
            try:
                s += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n, s

def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_DST

    print("源  : %s" % src)
    print("目标: %s" % dst)

    if not src.is_dir():
        print("[错误] 源目录不存在。")
        print("       如果你已经删掉了旧项目，请从备份或发行包里找这份 runtime。")
        return 1

    if dst.is_dir():
        n, s = count(dst)
        print("[提示] 目标已存在（%d 个文件 / %.1f MB），将覆盖。" % (n, s / 1048576))

    src_n, src_s = count(src)
    print("[源] %d 个文件 / %.1f MB" % (src_n, src_s / 1048576))

    dst.mkdir(parents=True, exist_ok=True)
    print("[复制中] ...")
    shutil.copytree(src, dst, dirs_exist_ok=True)

    dst_n, dst_s = count(dst)
    print("[目标] %d 个文件 / %.1f MB" % (dst_n, dst_s / 1048576))

    if dst_n != src_n:
        print("[错误] 文件数不一致：源 %d，目标 %d" % (src_n, dst_n))
        return 1

    exe = dst / "python.exe"
    if not exe.is_file():
        print("[错误] 没找到 python.exe —— 这份源看起来不是完整的 Python 发行版。")
        return 1

    print()
    print("[完成] 自带运行时已就位：%s" % exe)
    print("       自检：moss --selfcheck")
    return 0

if __name__ == "__main__":
    sys.exit(main())
