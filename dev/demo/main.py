# -*- coding: utf-8 -*-
"""dev/demo 的 Python 入口 —— 用来演示 `moss m` 的多语言消歧。

这个目录里同时放了 main.py / main.go / main.html，
还有一个 go.mod —— 所以 `moss m` 会借助"项目标记"判定为 Go 项目，选中 main.go。
把 go.mod 改名或删掉，就会变成需要询问的多候选情况。
"""
import os

print("这是 dev/demo/main.py")
print("  当前目录 : %s" % os.getcwd())
print("  MOSS_HOME: %s" % os.environ.get("MOSS_HOME", "（未注入）"))
print("  数据目录 : %s" % os.environ.get("MOSS_PLUGIN_DATA_DIR", "（未注入）"))
