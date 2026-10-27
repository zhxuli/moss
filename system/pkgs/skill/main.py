#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""技能（skill）—— 技能管理器（跟 `:exec` 一个路子，只是管的是 AI 的技能）。

  moss :skill                    打开管理器（图形界面）
  moss :skill list               在控制台列出全部技能
  moss :skill show <id>          看某一只的详情
  moss :skill allow <id>         允许它被 AI 调用（**这个动作必须由人来做**）
  moss :skill revoke <id>        撤销
  moss :skill rm <id>            删掉它（整个目录）
  moss :skill plan <id>          看"转成插件"会有什么问题（id 会不会撞）
  moss :skill promote <id> [新id] 真的转成插件（去掉 `--` 搬进 user_data/pkgs）
  moss :skill run <id>           在这儿试跑一次

技能本体分两层：
  · user_data/state/skill/<id>/       用户层：AI 自己造的技能，要用户允许。
  · system/pkgs/skill/builtin/<id>/   预制层：随发行版打包的出厂技能，默认已允许；
                                  同名 user 技能会覆盖它。
每个技能是一个目录（pkg.json + 入口 + icon.svg）—— 就是插件那种多文件结构，所以技能和插件能互相搬。
规矩在 system/ai/skill_lib.py。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import core                                                          # noqa: E402


def _moss_args():
    """moss 把包参数放在 `MOSS_PKG_PARAMS` / `MOSS_ARGS` 里（跟 exec 同一套读法）。"""
    import json as _json
    raw = os.environ.get("MOSS_PKG_PARAMS")
    if raw:
        try:
            got = str(_json.loads(raw).get("args") or "").strip()
            if got:
                return got
        except Exception:                                              # noqa: BLE001
            pass
    return (os.environ.get("MOSS_ARGS") or "").strip()


def main():
    # ★ 宿主让我们跑"内嵌界面"时**绝不开窗**（放在最前面：这条路上参数都不用看）
    try:
        from embed import Embedded, embedded_now
        if embedded_now():
            return Embedded().loop()
    except ImportError:
        pass

    line = _moss_args()
    if line:
        argv = [a for a in line.split() if a.strip()]
    else:
        argv = [a for a in sys.argv[1:] if a not in ("-c", "") and not a.endswith("main.py")]

    # ★★ 不带参数时**开不开窗，看是谁在调**（你 2026-10-05 定的："对 AI 友好，又不能影响
    #    我们在窗口打开"）：
    #      · 界面里点「运行」→ 宿主会加 `MOSS_INTERACTIVE=1`（说明有人在看着，下面还有输入行）
    #        ⇒ **开窗口**（跟以前一样）；
    #      · 命令行 / AI 通过 run_moss 调 ⇒ 没有人看着 ⇒ **只打用法和列表**（不开窗）。
    #    另外 `moss :skill gui` 是显式开窗，任何时候都能用。
    if not argv:
        interactive = str(os.environ.get("MOSS_INTERACTIVE") or "").strip() in ("1", "true", "yes")
        if interactive:
            core.gui()
            return 0
        code, text = core.Api().cli(["help"])
        print(text)
        return code
    if argv[0].lower() in ("gui", "-g", "--gui"):
        core.gui()
        return 0
    code, text = core.Api().cli(argv)
    if text:
        print(text)
    return code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[提示] 操作已取消。")
