# -*- coding: utf-8 -*-
"""hello 包 —— 演示两件新东西：

  1. **类型化参数**（pkg.json 的 params）：宿主把参数以 JSON 放进 MOSS_PKG_PARAMS
  2. **结构化返回**（pkg.json 的 output）：把结果写进 MOSS_RESULT_FILE，
     宿主读回来当 data —— 这样 AI / 界面拿到的是结构化数据，
     而不是去解析人类可读的 print 文本。

真正的代码是文件，不是 JSON 里的转义字符串（F-03）——
这就是为什么这个文件能被编辑器高亮、被 git 逐行 diff、被 AI 直接改。
"""
import json
import os

# ---- 读参数（宿主注入的 JSON） ----
raw = os.environ.get("MOSS_PKG_PARAMS") or "{}"
try:
    params = json.loads(raw)
except Exception:
    params = {}

who = str(params.get("who") or "世界")
try:
    times = int(params.get("times") or 1)
except Exception:
    times = 1
times = max(1, min(times, 100))

# ---- 干活 ----
greeting = "你好，%s！" % who
for _ in range(times):
    print(greeting)

# ---- 结构化返回 ----
result = {"who": who, "times": times, "greeting": greeting, "lang": "python"}

result_file = os.environ.get("MOSS_RESULT_FILE")
if result_file:
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)

# ---- 把宿主注入的东西打出来，方便确认环境对不对 ----
print()
print("参数来源 : MOSS_PKG_PARAMS = %s" % raw)
print("数据目录 : %s" % os.environ.get("MOSS_PLUGIN_DATA_DIR", "（未注入）"))
print("安装根   : %s" % os.environ.get("MOSS_HOME", "（未注入）"))
