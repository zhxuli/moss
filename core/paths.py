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
import os
import re
import sys
from pathlib import Path

# 照抄 pa.py:21 —— 程序被改名了也要能工作（pa.exe / moss.exe 都认）
INVOCATION_NAME = Path(sys.argv[0]).stem if len(sys.argv) > 0 else "moss"

# 安装根。
#
# ★ 照抄 pa.py（E-20）：用 `sys.argv[0]` 定位 —— 无论直接跑脚本还是跑打包后的
#   exe，它都指向程序本身。不能用 `__file__`（nuitka onefile 下指向临时解包目录），
#   也不能用 cwd（用户会在任意目录下敲 `moss m`）。
#
# ★ 加一层兜底：如果环境里已经有 MOSS_HOME，就用它。
#   为什么需要：argv[0] 的口径只对"入口程序"成立。任何 import core 的辅助脚本
#   （开发工具、测试脚本）如果不在安装根，算出来的 HOME 就是错的。
#   宿主给子进程注入 MOSS_HOME，所以这个兜底和主路径口径一致，不会打架。
_env_home = os.environ.get("MOSS_HOME")
HOME = Path(_env_home).resolve() if _env_home else Path(sys.argv[0]).resolve().parent

# 只读出厂层（随 exe 一起分发，打包时带上）
SYSTEM_DIR = HOME / "system"
SYSTEM_PKGS = SYSTEM_DIR / "pkgs"
SYSTEM_RUNNERS = SYSTEM_DIR / "runners.json"
# 对外承诺：插件契约（随 exe 分发，人和 AI 都读它）。`moss --spec` 打印的就是它。
SPEC_DIR = SYSTEM_DIR / "spec"
SPEC_FILE = SPEC_DIR / "插件契约.md"
SPEC_SCHEMA = SPEC_DIR / "pkg.schema.json"

# 自带运行时（解释器）。一个运行时一个目录，**目录名 = runner 里 "runtime" 字段的值**。
# 为什么是复数 `runtimes`：旧项目叫 `bin/runtime`，但里面其实只有 Python，
# 从文件夹名字上看不出来。以后要加 Node / Lua，这里是它们的家。
SYSTEM_RUNTIMES = SYSTEM_DIR / "runtimes"

# 可写用户层（打包时整体排除）
USER_DIR = HOME / "user_data"
USER_PKGS = USER_DIR / "pkgs"
USER_RUNNERS = USER_DIR / "runners.json"
USER_CONFIG = USER_DIR / "config.json"
REGISTRY_FILE = USER_DIR / "registry.json"
HISTORY_DIR = USER_DIR / "history"
STATE_DIR = USER_DIR / "state"
# 宿主自己的"目录记忆"（那个目录上次选了哪个候选）—— **跟插件数据分开放**。
# 它不是"某个插件的数据"，以前混在 state/ 里，和插件数据平级、都是哈希名，谁也分不清。
RESOLVE_DIR = USER_DIR / "resolve"
# 用户层可以覆盖同名运行时（以后做"组件下载"时装到这里）
USER_RUNTIMES = USER_DIR / "runtimes"

# 开发层：**只在开发机上存在**。
# 发行版里没有 dev/ 目录（打包只带 pa.exe + system/），所以用户永远看不到它。
# 演示包、测试固件一律放这里，**绝不进 system/pkgs** ——
# system/pkgs 是要随程序分发给所有用户的东西。
DEV_DIR = HOME / "dev"
DEV_PKGS = DEV_DIR / "pkgs"


def ensure_user_dirs():
    """懒创建：只有真要写数据时才建目录。

    照抄 skill.md 里的"懒加载"规范 —— 拒绝产生空目录污染。
    """
    for d in (USER_DIR, USER_PKGS, STATE_DIR, HISTORY_DIR):
        d.mkdir(parents=True, exist_ok=True)


# 包 id 的**唯一权威规则**（`F-26`）。
#   为什么要钉死：从 2026-09-27 起 `state/<id>/` 直接拿 id 当目录名，
#   不校验的话一个 `id: "../../x"` 就能把数据写到别处去。
ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def valid_id(pid):
    return bool(ID_RE.match(str(pid or "")))


def _short_hash(key):
    return hashlib.sha1(str(key).encode("utf-8")).hexdigest()[:12]


def _readable_tag(key):
    """把一段路径变成**看得懂**的目录名前缀（`D:\\a\\b` → `D--a-b`）。

    ★ 它只负责"能看懂"，**不负责唯一性** —— 唯一性交给后面拼上去的短哈希。
      所以这里可以放心截断、放心替换非法字符。
    为什么要有它：光用哈希命名（`0b5ffe4aad83`）时，你在 `user_data` 里
    看到一个目录根本不知道是谁的，删除、排障、清缓存都无从下手。
    """
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(key))
    s = s.strip(" .-")            # 首尾的点和空格在 Windows 目录名里非法/会被吞
    if len(s) > 60:
        s = s[-60:]               # 深路径保留**尾部**：认项目靠的是最后几段
    return s or "dir"


def _readable_dir(key):
    return "%s__%s" % (_readable_tag(key), _short_hash(key))


def pkg_state_dir(pid):
    """包的数据目录 = `user_data/state/<id>/`。

    ★ 目录名**就是包 id**，不再用哈希 —— 以前是 `state/978ea7af39ad/`，
      在磁盘上根本看不出这是谁的包，删包、备份、排障都无从下手。
    ★ id 不合法时**退回哈希并放进 `_bad/`**：这里必须自己兜住，
      因为目录名是直接拼出来的（`F-26` 的安全边界）。
    """
    pid = str(pid or "")
    if not valid_id(pid):
        return STATE_DIR / "_bad" / _short_hash(pid)
    return STATE_DIR / pid


def path_state_dir(key):
    """**路径调用**（没有包 id）的数据目录：`user_data/state/_path/<目录名>__<短哈希>/`。

    用"看得懂的前缀 + 短哈希"而不是纯哈希：路径里有反斜杠、冒号、中文，
    不能原样当目录名，但**全换成哈希就等于看不懂是谁的**（`_path/ed028ad05bf1`）。
    放 `_path/` 下面是为了跟"按包 id 命名"的那些一眼区分开。
    """
    return STATE_DIR / "_path" / _readable_dir(key)


def resolve_dir_for(key):
    """宿主的目录记忆（`choices.json`）落在哪：`user_data/resolve/<目录名>__<短哈希>/`。"""
    return RESOLVE_DIR / _readable_dir(key)


def describe():
    return {
        "invocation": INVOCATION_NAME,
        "home": str(HOME),
        "system": str(SYSTEM_DIR),
        "user": str(USER_DIR),
    }
