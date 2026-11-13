import os
import shutil
import subprocess
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

def verify_runtime(dst):
    exe = dst / "python.exe"
    if not exe.is_file():
        print("[错误] 没找到 python.exe —— 这份运行时不完整。")
        return False
    try:
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cp = subprocess.run([str(exe), "-m", "pip", "--version"], cwd=str(dst),
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=60, env=env)
    except Exception as e:
        print("[错误] 无法启动运行时：%r" % (e,))
        return False
    text = (cp.stdout or cp.stderr).strip()
    if cp.returncode == 0:
        print("[检查] python.exe -m pip 可用：%s" % text)
        return True
    print("[错误] python.exe -m pip 不可用：%s" % text)
    return False

def clean_caches(dst):
    dirs = 0
    files = 0
    for p in list(dst.rglob("__pycache__")):
        if p.is_dir():
            shutil.rmtree(p)
            dirs += 1
    for p in list(dst.rglob("*.pyc")) + list(dst.rglob("*.pyo")):
        if p.is_file():
            try:
                p.unlink()
                files += 1
            except OSError:
                pass
    if dirs or files:
        print("[清理] 删除运行时缓存：%d 个 __pycache__ / %d 个 pyc" % (dirs, files))

def repair_runtime(dst):
    scripts = dst / "Scripts"
    if scripts.is_dir():
        shutil.rmtree(scripts)
        print("[清理] 已删除 Scripts/（旧 exe 启动器写死了原路径，不能随运行时搬迁）")
    clean_caches(dst)
    return verify_runtime(dst)

def main():
    repair_only = "--repair" in sys.argv[1:]
    args = [a for a in sys.argv[1:] if a != "--repair"]
    if repair_only:
        dst = Path(args[0]) if args else DEFAULT_DST
        print("目标: %s" % dst)
        return 0 if repair_runtime(dst) else 1

    src = Path(args[0]) if args else DEFAULT_SRC
    dst = Path(args[1]) if len(args) > 1 else DEFAULT_DST

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

    if not repair_runtime(dst):
        return 1

    print()
    print("[完成] 自带运行时已就位：%s" % dst)
    print("       pip 请用：%s -m pip ..." % (dst / "python.exe"))
    print("       自检：moss --selfcheck")
    return 0

if __name__ == "__main__":
    sys.exit(main())
