# -*- coding: utf-8 -*-
"""单候选演示：这个目录只有一个 main.py，`moss m` 应该不问直接跑。"""
import os

print("这是 dev/demo_py/main.py（单候选，不该被询问）")
print("  当前目录 : %s" % os.getcwd())
print("  MOSS_HOME: %s" % os.environ.get("MOSS_HOME", "（未注入）"))
