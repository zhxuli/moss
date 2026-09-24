# -*- coding: utf-8 -*-
"""安装根与各个目录的定位。

★ 照抄 pa.py（E-20 照抄原则）。pa.py 用 `Path(sys.argv[0]).resolve().parent`
  定位安装根，打包成 exe 之后运行良好 —— 原样搬过来，不做"改进"。

为什么要这样写（这是 pa.py 已验证过的结论，不是我的发明）：
  · 不能用 `__file__`  —— nuitka onefile 下它指向临时解包目录，不是安装目录
  · 不能用 cwd        —— 用户会在任意目录下敲 `moss m`
  · `sys.argv[0]`     —— 无论直接跑脚本还是跑打包后的 exe，它都指向程序本身
"""
import hashlib
import sys
from pathlib import Path

# 照抄 pa.py:21 —— 程序被改名了也要能工作（pa.exe / moss.exe 都认）
INVOCATION_NAME = Path(sys.argv[0]).stem if len(sys.argv) > 0 else "moss"

HOME = Path(sys.argv[0]).resolve().parent

# 只读出厂层（随 exe 一起分发，打包时带上）
SYSTEM_DIR = HOME / "system"
SYSTEM_PKGS = SYSTEM_DIR / "pkgs"
SYSTEM_RUNNERS = SYSTEM_DIR / "runners.json"

# 可写用户层（打包时整体排除）
USER_DIR = HOME / "user_data"
USER_PKGS = USER_DIR / "pkgs"
USER_RUNNERS = USER_DIR / "runners.json"
USER_CONFIG = USER_DIR / "config.json"
REGISTRY_FILE = USER_DIR / "registry.json"
HISTORY_DIR = USER_DIR / "history"
STATE_DIR = USER_DIR / "state"


def ensure_user_dirs():
    """懒创建：只有真要写数据时才建目录。

    照抄 skill.md 里的"懒加载"规范 —— 拒绝产生空目录污染。
    """
    for d in (USER_DIR, USER_PKGS, STATE_DIR, HISTORY_DIR):
        d.mkdir(parents=True, exist_ok=True)


def state_dir_for(key):
    """给一个稳定 key（cwd 或包 id）分配状态目录。

    用哈希而不是原样路径：路径里的反斜杠、冒号、中文都不适合做目录名。
    """
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    return STATE_DIR / h


def describe():
    return {
        "invocation": INVOCATION_NAME,
        "home": str(HOME),
        "system": str(SYSTEM_DIR),
        "user": str(USER_DIR),
    }
