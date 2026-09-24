# -*- coding: utf-8 -*-
"""隔离解释器的引导脚本 —— 让脚本所在目录进入 sys.path。

为什么需要它
------------
自带运行时（`system/runtimes/python/3.12/`）是 **Python 嵌入式发行版**，
目录里有 `python312._pth`。`._pth` 存在时 CPython 进入**隔离模式**：

    1. `sys.path` 完全由那个文件决定，**不会**把脚本所在目录加进去
    2. `PYTHONPATH` 环境变量被**忽略**

后果：任何 `import` 同目录其他模块的脚本都会 `ModuleNotFoundError`。
实测确认（三种方案只有这个管用）：

    python script.py                 -> ModuleNotFoundError: No module named 'sib'
    PYTHONPATH=... python script.py  -> 仍然失败
    ._pth 里启用 import site          -> 仍然失败
    python bootstrap.py script.py     -> ✅ OK

venv 和系统 Python **不需要**它（它们本来就会把脚本目录加进 sys.path），
所以 runner 只在"用的是自带运行时"时才切到这个引导。

用法
----
    python bootstrap.py <目标脚本> [参数...]

它等价于"正常地跑那个脚本"：`__name__` 是 `__main__`、`__file__` 是脚本路径、
`sys.argv` 是 `[脚本路径, 参数...]`。
"""
import os
import runpy
import sys


def main():
    if len(sys.argv) < 2:
        print("[bootstrap] 用法: python bootstrap.py <目标脚本> [参数...]")
        return 2

    script = sys.argv[1]

    # 参数：把脚本路径从 argv 里换成目标脚本（等价 python script.py a b）
    sys.argv = [script] + sys.argv[2:]

    # 关键的一步：把脚本所在目录放到 sys.path 最前面
    script_dir = os.path.dirname(os.path.abspath(script))
    if script_dir and script_dir not in sys.path:
        sys.path.insert(0, script_dir)

    # runpy 比 exec 更贴近"正常跑一个脚本"：
    # 会正确设置 __name__ / __file__ / __spec__，也支持包内的 __main__
    runpy.run_path(script, run_name="__main__")
    return 0


if __name__ == "__main__":
    sys.exit(main())
