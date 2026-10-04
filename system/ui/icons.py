# -*- coding: utf-8 -*-
"""图标表：**从 `system/icon/svg/*.svg` 读出来**，注入成 `window.__MOSS_ICONS`。

为什么要有这个文件（`V-267`）
---------------------------
你原话：「你把很多 svg 图标放在了 moss 的代码中，这导致代码很臃肿，应该把所有的 svg
图标都迁移到文件当中去，以减少代码行数」。于是：

* **每个图标一个 `.svg` 文件**（`system/icon/svg/<名字>.svg`）—— 能直接打开看，
  也能被别的工具（`tools/取图标.py`）增补；**那 260 条 path 数据不再待在 `.js` 里**。
* `system/ui/vendor/lucide.js` 缩成二十来行的 `ico()`：它只认 `window.__MOSS_ICONS`
  这张表（`{名字: {vb, body}}`）。
* 谁来注入？**宿主**（`system/ui/main.py` 组装页面时）和**界面预览**（`tools/界面预览.py`）
  各自调这里的 `script_tag()` —— 一处实现、两处用，不会漂移。

★ 为什么放在 `system/ui/` 而不是 `core/`：`core/**` 是**编进 exe** 的（`K-10`），
  改它就得重新打包；这个纯属界面资产，放界面上改完重启就生效。
★ 文件里的 `<g>` **自带画笔**（描边族的 `fill="none" stroke=...`、自绘那几颗的
  `translate/scale` + 实心填充已经烤进文件）—— 所以 `ico()` 不需要再懂
  "这颗是实心还是描边、要不要缩放"这些参数。谁打开那个 .svg 看到的就是最终样子。
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent                 # system/ui
HOME = HERE.parent.parent                              # 安装根
SVG_DIR = HOME / "system" / "icon" / "svg"

#: 一次读盘就够（图标是静态资产；进程活着的期间不会变）
_CACHE = {}


def _parse_one(text):
    """一个 .svg 文件 → `{vb, body}`（body = 里面那段，连它自带的 `<g>` 画笔一起）。"""
    m = re.search(r"<svg\b[^>]*\bviewBox=\"([^\"]+)\"[^>]*>(.*)</svg>", text, re.S | re.I)
    if not m:
        return None
    return {"vb": m.group(1).strip(), "body": m.group(2).strip()}


def table():
    """`{名字: {vb, body}}`（读不到就空表 —— 界面照旧能开，只是图标是空白）。"""
    if "all" in _CACHE:
        return _CACHE["all"]
    out = {}
    try:
        for p in sorted(SVG_DIR.glob("*.svg")):
            got = _parse_one(p.read_text(encoding="utf-8"))
            if got:
                out[p.stem] = got
    except OSError:
        pass
    _CACHE["all"] = out
    return out


def names():
    """有哪些图标（`tools/界面检查.py` 拿它核对 `ico("…")` 里的名字是否存在）。"""
    return sorted(table().keys())


def script_tag():
    """一段 `<script>window.__MOSS_ICONS = {…}</script>`（组装页面时插在 `<body>` 后面）。"""
    data = json.dumps(table(), ensure_ascii=False, separators=(",", ":"))
    return ("<script>/* 图标表：由 system/icon/svg/*.svg 生成（`V-267`）—— 别手工编辑 */\n"
            "window.__MOSS_ICONS = %s;</script>" % data)
