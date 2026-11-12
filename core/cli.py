import json
import os
import shutil
import sys
import unicodedata
from pathlib import Path

from . import (config, engine, events, history, out, paths, pkg as pkg_mod,
               registry, resolve, runners as runners_mod, shell,
               shortcut as shortcut_mod, ui)

USAGE = """moss —— 多语言启动器

用法:
  moss <名字> [参数...]        在当前目录（及向上几层）找匹配的脚本并运行
                               例: moss m        → main.py / main.go / main.html
                                   moss b/m      → 进 b 开头的子目录再找 m 开头
                                   moss s/t/main → 逐级往下
                               文件系统里找不到时，会去「历史」里找同名的那次调用
                               （例如 moss zeen 直接进上次那个 ZeEn），命中多个取最近的
  moss /<名字>                 同上，但不切换目录（在当前目录里跑）
  moss ~<名字>                 后台脱离运行，不阻塞当前控制台

  moss :<别名> [参数...]       运行一个已安装的包
                               例: moss :md5 hello

  moss ui                      打开界面（双击 moss.exe / 快捷方式 / 快速启动栏也是这个 ——
                               没有控制台时不开命令行，直接开界面）
  moss --ui                    同上（写全一点的形式，脚本里更显眼）

  moss cd <目标>               智能找目录并切过去（认出父 shell 后把命令注入控制台）
  moss cd --install            把 cd 包装函数写进 PowerShell 配置 → 屏幕上不留回显
  moss cd --uninstall          删掉那个包装函数

  moss --history               最近启动记录：方向键选择，回车直接再跑一次（去重，最多 20 条）
                               回车进入程序后，程序退出即结束，不会回到列表
  moss --history <条数>        只打印不交互（管道 / 脚本用这种）
  moss --remove <别名>         卸载一个包：包本体 + 它的数据（永久删除，需确认；-y 跳过）
  moss --ai-config              看当前那组 AI 参数（key 默认**打码**；`--ai-config-reveal` 才给全文）
  moss --ai-profile-set <组> k=v…  加/改一组 AI 参数（就三样：base_url / api_key / model ——
                               model 可以多个，逗号隔开；**明文**写 config.toml）
  moss --ai-presets             常见那几家的预制参数（DeepSeek / Gemini / OpenAI / Kimi /
                               通义千问 / 智谱 / 硅基流动 / 本地 Ollama）—— 面板上的「常用」就是它
  moss --ai-active <组>         选当前用哪一组          moss --ai-profile-del <组>  删一组
  moss --ai-rename <旧> <新>    给一组改名（整块搬，key 不用再读一遍）
  moss --ai-test [组]           **测试连接**：流式发一个最小请求，报状态码和第一个增量
  moss --ai-models [组]          **获取可用模型**：GET `{base_url}/models`，回一份模型清单
  moss --ai-ping [组] model=…    **测一个模型能不能用**：一次最小请求（几个 token），
                               回 JSON（ok / 毫秒 / 它回了什么）—— 设置面板「测试可用性」用它
  moss --ai-balance [组]         **查询余额**：DeepSeek / Kimi / OpenRouter / 硅基流动等已知接口
  moss --ai-import-legacy       把旧的 user_data/state/ai/config.json 导成一组
  moss --snap …                版本快照（备份 / 恢复 / 导出 / 差异）—— 给人和 AI 用；
                               `moss --snap --help` 看全部子命令（会动磁盘的要 --yes）
  moss --spec                  打印「插件契约」：怎么写一个插件（写插件 / AI 调用前请先读）
  moss --new <id>              生成一个能跑的插件骨架到 user_data/pkgs/<id>/
  moss --rename <旧> <新id>    给一个包改名：包目录 / 数据目录 / 清单里的 id 一起改
                               （新 id 写成它现在的 id，就是"把目录名对齐成 id"）
  moss --layer <包> [user|system]  把这个包的**目录**在 user_data/pkgs ↔ system/pkgs 之间搬：
                               system = 出厂层（升级会整体替换）/ user = 你自己的（升级不碰，
                               而且压住 system 层）。不写层 = 只看它现在在哪层。
                               数据目录按 id 算，**不跟着层走**。
  moss --alias [sync|status]   短命令：把 `moss :包名` 缩成 `mo<包名>`（`moimg` = `moss :img`）。
                               总开关在界面「设置 → 短命令」；sync = 手动对账，status = 看现状
  moss --resolve <名字>        只看解析结果，不执行（排障用：为什么选中它 / 为什么没找到）
  moss --info <包> [--json]    看**这一个包**：清单 / 参数表 / AI 示例 / 文档在哪
                               （AI、脚本要照着敲命令行，先读这个）
                               `--docs [readme|agent|all]` 打文档原文（不截断）
                               `--examples` 只列能直接粘的那几行；`--json` 只吐这一个包
  moss --selfcheck             自检：安装根 / runner 表 / 包 / 自带运行时 / cd 注入

说明:
  · 参数写法二选一：位置参数（按 params 顺序）或 key=value
  · 包可以把某个参数标成 rest:true，表示「剩下的参数全部交给这个包自己解释」
    （img 就是这种：moss :img webp 60% 1200 *.png）
  · 环境变量 MOSS_HOME / MOSS_PLUGIN_DATA_DIR 会注入给子进程
  · 配置在 user_data\\config.toml（带注释：命令前缀符号 / 输出横幅 / 清屏 /
    搜索层数 / Ctrl-C 策略 —— 打开那个文件就知道每一项是干什么的）
  · 裸名（不带前缀）归谁可以改：默认 moss m 找文件、moss :img 跑包；
    若主要用途是"跑装好的包"（不常写脚本），把 config.toml 里的 plugin_mode 留空、
    path_mode 填 ":" —— 于是 moss img 直接跑包，moss :img 才是找文件
  · 有没有参数决定干什么，有没有控制台决定怎么进来：
      终端里敲 moss           → 用法 + 包列表（命令行）
      终端里敲 moss ui        → 界面
      双击 / 快捷方式 / 快速启动栏 → 界面（没有控制台，命令行打给谁看呢）
      带参数（moss :img 60%） → 一律按参数干活，不看有没有控制台
"""

def _coerce(spec, value):
    t = (spec.get("type") or "string").lower()
    if value is None:
        return None
    try:
        if t == "int":
            return int(str(value).strip())
        if t == "float":
            return float(str(value).strip())
        if t == "bool":
            return str(value).strip().lower() in ("1", "true", "yes", "on", "y")
    except Exception:
        return spec.get("default")
    return str(value)

def _looks_like_kv_token(k):
    if not k:
        return False
    if not (k[0].isalpha() or k[0] == "_"):
        return False
    return all(ch.isalnum() or ch == "_" for ch in k)

def parse_params(pkg, args):
    spec = pkg.get("params") or []
    names = {str(p.get("name") or "").strip() for p in spec}
    named, positional = {}, []
    for a in args:
        k = a.partition("=")[0].strip() if ("=" in a and not a.startswith("=")) else ""
        if k and (k in names) and _looks_like_kv_token(k):
            named[k] = a.partition("=")[2]
        else:
            positional.append(a)

    params = {}
    for p in spec:
        n = p.get("name")
        if not n:
            continue
        params[n] = _coerce(p, named.get(n, p.get("default")))

    pi = 0
    for p in spec:
        n = p.get("name")
        if not n or n in named:
            continue
        if p.get("rest"):
            params[n] = _coerce(p, " ".join(positional[pi:]))
            pi = len(positional)
            continue
        if pi < len(positional):
            params[n] = _coerce(p, positional[pi])
            pi += 1
    return params

def build_pkg_inv(rec, params, via="cli"):
    pkg = rec["pkg"]
    pkg_dir = Path(rec["dir"])
    entry = pkg_mod.entry_path(pkg, pkg_dir)
    if entry is None and not pkg_mod.inline_code(pkg):
        return None, "包 '%s' 找不到入口文件（entry.file 指向的文件不存在）" % pkg["id"]

    env = pkg.get("env") or {}
    cwd = env.get("cwd") or os.getcwd()
    icon = pkg_mod.icon_path(pkg, pkg_dir)

    inv = {
        "kind": "pkg",
        "id": pkg["id"],
        "pkg_kind": pkg.get("kind"),
        "alias": pkg.get("aliases", [None])[0] if pkg.get("aliases") else pkg["id"],
        "version": pkg.get("version"),
        "runner": pkg.get("runner"),
        "target": str(entry) if entry else None,
        "inline": pkg_mod.inline_code(pkg),
        "cwd": cwd,
        "params": params,
        "args": [],
        "via": via,
        "pkg_dir": str(pkg_dir),
        "icon": str(icon) if icon else None,
    }
    req = (pkg.get("requires") or {}).get(pkg.get("runner"))
    if req:
        inv["runtimeRequirement"] = str(req)
    return inv, None

def build_path_inv(cand, args, via="cli", change_dir=True):
    cwd = str(Path.cwd()) if not change_dir else str(cand["base"])
    return {
        "kind": "path",
        "id": None,
        "runner": cand["runner"],
        "target": str(cand["path"]),
        "cwd": cwd,
        "interpreter": cand["probe"].get("interpreter"),
        "venv": cand["probe"].get("venv"),
        "params": {},
        "args": list(args),
        "via": via,
    }

def _fill_interpreter(inv, table):
    if inv.get("interpreter"):
        return inv, None

    spec = table.get(inv.get("runner"))
    if spec is None:
        return inv, ("不认识 runner '%s'。检查 system\\runners.json，"
                     "或往 user_data\\runners.json 里加一条。" % inv.get("runner"))

    kind = "package" if inv.get("kind") == "pkg" else "path"
    probe = runners_mod.probe(inv.get("runner"), spec, {
        "cwd": inv.get("cwd") or os.getcwd(),
        "home": str(paths.HOME),
        "entry": inv.get("target") or "",
    }, kind=kind, requirement=inv.get("runtimeRequirement"))
    if not probe.get("available"):
        return inv, ("这个包需要 '%s'，但本机用不了。\n"
                     "       原因：%s\n"
                     "       装好它，或往 user_data\\runners.json 里补一条可用的解释器路径。"
                     % (inv.get("runner"), probe.get("why")))
    inv["interpreter"] = probe.get("interpreter")
    inv["venv"] = probe.get("venv")
    return inv, None

_LAYERS = (
    ("user", "用户插件", "你自己写的 / 从商店装的，升级不碰", paths.USER_PKGS),
    ("system", "系统插件", "随 moss 分发，升级时整体替换", paths.SYSTEM_PKGS),
)

def _pkg_rows(recs):
    by_layer = {}
    for r in recs:
        by_layer.setdefault(r["layer"], []).append(r)
    return by_layer

def cmd_list(table, skip_clear=False):
    if not skip_clear:
        out.conditional_clear_screen()
    recs = registry.scan_all()
    if not recs:
        out.print_cyan("[信息] 还没有安装任何包。包放在 %s" % paths.SYSTEM_PKGS)
        return 0

    by_layer = _pkg_rows(recs)
    out.print_cyan("已安装的包（%d）—— 按层分组" % len(recs))
    print("  优先级：用户插件 > 系统插件"
          "（同名时高优先级遮蔽低优先级，低层原件保留）")
    for key, cn, why, where in _LAYERS:
        rows = by_layer.get(key)
        if not rows:
            continue
        print()
        print("  【%s】%s%s" % (cn, why, ("　" + str(where)) if where else ""))
        print("    %-16s %-7s %-7s %s" % ("别名", "类型", "版本", "说明"))
        print("    " + "-" * 68)
        for r in rows:
            p = r["pkg"]
            alias = ",".join(p.get("aliases") or []) or p["id"]
            tail = ""
            if r.get("shadowed"):
                tail += "  [它遮住了 %s 层的同名包]" % r["shadowed"]
            print("    %-16s %-7s %-7s %s%s" % (
                alias[:16], p.get("kind", ""), str(p.get("version", ""))[:7],
                str(p.get("desc", ""))[:34], tail))
    return 0

def _term_size():
    size = out.console_size()
    if size:
        return max(20, size[0]), max(8, size[1])
    try:
        s = shutil.get_terminal_size((100, 30))
        return max(20, s.columns), max(8, s.lines)
    except Exception:
        return 100, 30

def _hist_time(r):
    ts = str(r.get("ts") or "")
    return ts[11:19] if len(ts) >= 19 else ts

def _cw(ch):
    return 2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1

def _w(s):
    return sum(_cw(ch) for ch in str(s))

def _pad(s, w):
    s = str(s)
    while s and _w(s) > w:
        s = s[:-1]
    return s + " " * max(0, w - _w(s))

def _tail(s, w):
    s = str(s)
    if _w(s) <= w:
        return s
    out = ""
    for ch in reversed(s):
        if _w(out) + _cw(ch) > w - 1:
            break
        out = ch + out
    return "<" + out

def _hist_args(r):
    if r.get("kind") == "pkg":
        p = r.get("params") or {}
        if not p:
            return ""
        if len(p) == 1 and "args" in p:
            return str(p["args"])
        return " ".join("%s=%s" % (k, p[k]) for k in sorted(p))
    return " ".join(str(x) for x in (r.get("args") or []))

def _hist_name(r):
    if r.get("id"):
        return str(r["id"])
    t = str(r.get("target") or "?").replace("/", "\\")
    return t.rsplit("\\", 1)[-1] or t

def _hist_failed(r):
    return r.get("exit") not in (0, None)

_HIST_FIXED = 1 + 1 + 3 + 2 + 8 + 2 + 16 + 1 + 20 + 1

def _hist_head(width, with_args=True):
    head = " " * 2 + _pad("#", 3) + "  " + _pad("时间", 8) + "  " + _pad("名称", 16)
    if with_args:
        head += " " + _pad("参数", 20)
        room = width - 1 - _w(head) - 1
    else:
        room = width - 1 - _w(head) - 1
    return head + " " + _pad("目录", max(4, room))

def _hist_row(i, r, width, marker=" "):
    with_args = width - _HIST_FIXED >= 10
    line = "%s %3d  %s  %s" % (marker, i, _pad(_hist_time(r), 8),
                               _pad(_hist_name(r), 16))
    if with_args:
        line += " " + _pad(_hist_args(r), 20)
    room = width - 1 - _w(line) - (2 if _hist_failed(r) else 0)
    if room >= 6:
        line += " " + _pad(_tail(r.get("cwd") or "-", room), room)
    if _hist_failed(r):
        line += " !"
    return line if _w(line) <= width else _pad(line, width)

def _scroll_top(idx, total, vh):
    if total <= vh:
        return 0
    return max(0, min(idx - vh // 2, total - vh))

def _print_history(rows):
    width, _ = _term_size()
    out.print_cyan("最近 %d 条启动记录（已去重，同一件事只留最新一条）" % len(rows))
    print(_hist_head(width, width - _HIST_FIXED >= 10))
    for i, r in enumerate(rows, 1):
        print(_hist_row(i, r, width))
    print("\n想再跑一次上面某条：直接敲它的名字（比如 moss zeen），不用先 cd 过去。")
    return 0

def _history_browser(rows, table):
    import msvcrt
    out.enable_ansi()
    idx = 0
    block_y = 0

    def paint(redraw):
        nonlocal block_y
        width, height = _term_size()
        inner = width - 2
        with_args = inner - _HIST_FIXED >= 10
        vh = max(3, min(height - 3, len(rows)))
        top = _scroll_top(idx, len(rows), vh)
        lines = ["  最近启动（已去重 %d 条）" % len(rows),
                 _hist_head(inner, with_args)]
        for k in range(vh):
            j = top + k
            if j < len(rows):
                lines.append(_hist_row(j + 1, rows[j], inner,
                                       ">" if j == idx else " "))
            else:
                lines.append("")
        lines.append("  方向键 选择    回车 重跑    Esc 退出")
        if redraw:
            out.gotoxy(0, block_y)
        else:
            out.clear_screen()
            pos = out.cursor_pos()
            block_y = pos[1] if pos else 0
        out.write_block(lines, width)

    paint(False)
    while True:
        try:
            ch = msvcrt.getwch()
        except KeyboardInterrupt:
            return 0
        except Exception:
            return 1
        if ch in ("\x1b", "q", "Q"):
            out.clear_screen()
            return 0
        if ch in ("\x00", "\xe0"):
            try:
                ch2 = msvcrt.getwch()
            except Exception:
                return 1
            _, height = _term_size()
            vh = max(3, min(height - 3, len(rows)))
            if ch2 in ("H", "A"):
                idx = max(0, idx - 1)
            elif ch2 in ("P", "B"):
                idx = min(len(rows) - 1, idx + 1)
            elif ch2 == "I":
                idx = max(0, idx - vh)
            elif ch2 == "Q":
                idx = min(len(rows) - 1, idx + vh)
            elif ch2 == "G":
                idx = 0
            elif ch2 == "O":
                idx = len(rows) - 1
            paint(True)
            continue
        if ch in ("\r", "\n"):
            out.clear_screen()
            return cmd_rerun(idx + 1, table, rows=rows)

def cmd_history(n=None, table=None):
    rows = history.recent_unique()
    if not rows:
        out.print_cyan("[信息] 还没有任何启动记录。")
        return 0
    if n is None and table is not None and sys.stdout.isatty():
        return _history_browser(rows, table)
    if n is not None:
        rows = rows[:n]
    return _print_history(rows)

def cmd_rerun(idx, table, rows=None):
    if rows is None:
        rows = history.recent_unique()
    if not (1 <= idx <= len(rows)):
        out.print_cyan("[错误] 序号超范围（1-%d）。" % len(rows))
        return 1
    return cmd_rerun_record(rows[idx - 1], table)

def cmd_rerun_record(r, table):
    out.print_cyan("[重跑] 来自历史：%s" % (r.get("id") or r.get("target")))
    if r.get("kind") == "pkg" and r.get("id"):
        rec = registry.find_alias(r["id"])
        if not rec:
            out.print_cyan("[错误] 包 '%s' 已经不在了。" % r["id"])
            return 1
        inv, err = build_pkg_inv(rec, r.get("params") or {}, via="history")
        if err:
            out.print_cyan("[错误] %s" % err)
            return 1
    else:
        target = r.get("target")
        cwd = r.get("cwd") or os.getcwd()
        if not target or not os.path.isfile(target):
            out.print_cyan("[错误] 目标已经不在了：%s" % target)
            return 1
        inv = {
            "kind": "path", "id": None, "runner": r.get("runner"),
            "target": target, "cwd": cwd,
            "params": {}, "args": r.get("args") or [], "via": "history",
        }
    inv, err = _fill_interpreter(inv, table)
    if err:
        out.print_cyan("[错误] %s" % err)
        return 1
    return engine.run(inv, table)

def cmd_spec():
    f = paths.SPEC_FILE
    if not f.is_file():
        out.print_cyan("[错误] 找不到插件契约：%s" % f)
        out.print_cyan("       发行版里它应该在 system/spec/ 下。")
        return 1
    try:
        print(f.read_text(encoding="utf-8"))
    except Exception as e:
        out.print_cyan("[错误] 契约文件读不出来：%s" % e)
        return 1
    return 0

NEW_PKG_JSON = {
    "spec": 1,
    "id": "__ID__",
    "kind": "task",
    "version": "0.1.0",
    "name": {"zh-CN": "新建插件 __ID__"},
    "desc": {"zh-CN": "一句话说明这个插件干什么（会被列在 moss 的包列表里）"},
    "tags": [],
    "aliases": ["__ID__"],
    "runner": "python",
    "entry": {"file": "run.py"},
    "params": [
        {"name": "text", "type": "string", "default": "你好",
         "desc": "示例参数：要重复的内容"},
        {"name": "times", "type": "int", "default": 1, "desc": "示例参数：重复几遍"},
    ],
    "env": {"cwd": "", "elevated": False},
    "capabilities": {"run": ["python"], "net": [], "elevated": False},
    "output": {"mode": "json", "schema": {"text": "string", "times": "int"}},
      "ai": {"expose": False, "risk": "low"},
}

NEW_RUN_PY = '''import json
import os

params = json.loads(os.environ.get("MOSS_PKG_PARAMS") or "{}")
text = str(params.get("text") or "你好")
try:
    times = max(1, min(int(params.get("times") or 1), 100))
except Exception:
    times = 1

data_dir = os.environ.get("MOSS_PLUGIN_DATA_DIR") or "."
os.makedirs(data_dir, exist_ok=True)

for _ in range(times):
    print(text)

result_file = os.environ.get("MOSS_RESULT_FILE")
if result_file:
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump({"text": text, "times": times}, f, ensure_ascii=False)
'''

NEW_AGENT_MD = '''# __ID__ · 给 AI 看的说明

> 这个文件是**给 AI / Agent 读的**（人看 README.md）。写清楚"怎么调、有什么副作用、会怎么失败"，
> 别人才敢让它自动跑。

## 干什么
一句话：……

## 怎么调
```
moss :__ID__ text=你好 times=3
```

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `text` | string | 否 | 要重复的内容（默认"你好"） |
| `times` | int | 否 | 重复几遍（1-100，默认 1） |

## 返回（结构化）
`MOSS_RESULT_FILE` 里是 JSON：`{"text": ..., "times": ...}`

## 副作用
- 写文件：无 / 写到哪：……
- 联网：无
- 剪贴板：无

## 失败模式
- 参数非法 → 用默认值，退出码 0
'''

NEW_ICON_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48" role="img">
  <rect x="4" y="4" width="40" height="40" rx="12" fill="#EEF3F9"/>
  <path d="M24 12.5 34 18.5v11L24 35.5 14 29.5v-11z" fill="#fff" stroke="#7C93B0"
        stroke-width="2.2" stroke-linejoin="round"/>
  <path d="M14 18.5 24 24.5l10-6M24 24.5v11" fill="none" stroke="#7C93B0"
        stroke-width="2.2" stroke-linejoin="round"/>
</svg>
'''

def _shortcut_sync(verbose=True):
    try:
        from . import shortcut as _sc
        msgs = _sc.sync()
        if verbose:
            for m in msgs:
                out.print_cyan("[短命令] " + m)
    except Exception:
        pass

def cmd_new(pid, kind="task", name="", desc=""):
    pid = str(pid or "").strip().lower()
    if not paths.valid_id(pid):
        out.print_cyan("[错误] id 不合法：'%s'（只允许 %s）" % (pid, paths.ID_RE.pattern))
        out.print_cyan("       规则：小写字母开头，只含小写字母/数字/-/_，不超过 32 字符。")
        return 1
    try:
        clash = registry.find_alias(pid)
    except Exception:
        clash = None
    if clash:
        clash_id = str(clash.get("id") or "")
        layer_cn = "系统" if clash.get("layer") == "system" else "用户"
        if clash_id == pid:
            out.print_cyan("[错误] id '%s' 已经被%s层的包占用了：%s"
                           % (pid, layer_cn, clash.get("dir")))
        else:
            out.print_cyan("[错误] id '%s' 和%s层包 '%s' 的别名冲突：%s"
                           % (pid, layer_cn, clash_id, clash.get("dir")))
        out.print_cyan("       换一个 id 再试（不能和已有包的 id / 别名重名）。")
        return 1
    target = paths.USER_PKGS / pid
    if target.exists():
        out.print_cyan("[错误] 已经存在：%s" % target)
        return 1
    stale = _set_aside_stale_state(pid)
    try:
        target.mkdir(parents=True, exist_ok=True)
        pkg = json.loads(json.dumps(NEW_PKG_JSON).replace("__ID__", pid))
        pkg["kind"] = kind
        if str(name or "").strip():
            pkg["name"] = dict(pkg.get("name") or {}, **{"zh-CN": str(name).strip()})
        if str(desc or "").strip():
            pkg["desc"] = dict(pkg.get("desc") or {}, **{"zh-CN": str(desc).strip()})
        (target / "pkg.json").write_text(
            json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (target / "run.py").write_text(NEW_RUN_PY.replace("__ID__", pid), encoding="utf-8")
        (target / "AGENT.md").write_text(NEW_AGENT_MD.replace("__ID__", pid), encoding="utf-8")
        (target / "icon.svg").write_text(NEW_ICON_SVG, encoding="utf-8")
    except Exception as e:
        out.print_cyan("[错误] 生成失败：%s" % e)
        return 1
    out.print_cyan("生成好了：%s" % target)
    for n in ("pkg.json", "run.py", "AGENT.md", "icon.svg"):
        print("     - %s" % n)
    out.print_cyan("下一步：")
    print("     1) 改 pkg.json 里的 name / desc / params")
    print("     2) 改 run.py 干活（参数读 MOSS_PKG_PARAMS，结果写 MOSS_RESULT_FILE）")
    print("     3) 跑：moss :%s 你好 3" % pid)
    print("     4) 要界面？**别自己开窗口** —— 照 system/pkgs/skill/ 抄一份网页界面，"
          "在 pkg.json 里声明")
    print("        \"ui\": {\"embed\": \"ui/index.html\"}：既能在 moss 的「界面」选项卡里"
          "内嵌跑，也能 moss :%s 自己开窗口" % pid)
    print("     5) 图标就是包目录里的 icon.svg（列表 / 详情页那颗，骨架里已经放了一颗中性的）"
          " —— 换成跟这个包干什么相配的图形")
    out.print_cyan("契约（字段、环境变量、数据放哪、界面怎么写）：moss --spec")
    _shortcut_sync()
    return 0

def _set_aside_stale_state(pid):
    d = paths.pkg_state_dir(pid)
    try:
        if not d.is_dir():
            return ""
    except OSError:
        return ""
    import time as _t
    keep = d.with_name("%s.prev-%s" % (d.name, _t.strftime("%Y%m%d-%H%M%S")))
    try:
        d.rename(keep)
    except OSError as e:
        out.print_cyan("[警告] 上一个同名包的数据目录没挪开：%s" % e)
        return ""
    out.print_cyan("注意：这个 id 以前用过，`%s` 里还留着它的数据（AI 会话 / 运行记录 / "
                   "临时文件）—— 已经挪到 `%s`，新包从干净的开始。" % (pid, keep.name))
    return str(keep)

def cmd_rename(name, new_id, table):
    new_id = str(new_id or "").strip().lower()
    if not paths.valid_id(new_id):
        out.print_cyan("[错误] 新 id 不合法：'%s'（只允许 %s）" % (new_id, paths.ID_RE.pattern))
        return 1
    rec = registry.find_alias(name)
    if not rec:
        out.print_cyan("[错误] 没有这个包：'%s'。直接敲 `moss` 看有哪些。" % name)
        return 1
    old_id = str(rec["id"])
    pkg_dir = Path(rec["dir"])
    same_id = (new_id == old_id)
    if same_id and pkg_dir.name == new_id:
        out.print_cyan("[信息] 名字本来就是 '%s'，目录名也是它，没改。" % old_id)
        return 0
    if not same_id and registry.find_alias(new_id):
        out.print_cyan("[错误] 已经有一个包叫 '%s' 了（换一个名字）。" % new_id)
        return 1

    layer = rec.get("layer")
    state_old = paths.pkg_state_dir(old_id)
    state_new = paths.pkg_state_dir(new_id)
    dir_new = pkg_dir.parent / new_id

    if dir_new.exists() and dir_new != pkg_dir:
        out.print_cyan("[错误] 目标目录已经存在：%s" % dir_new)
        return 1
    state_stale = bool(not same_id and state_new.exists())

    if same_id:
        out.print_cyan("将要只改目录名：%s → %s（id 不变，还是 '%s'）"
                       % (pkg_dir.name, new_id, old_id))
    else:
        out.print_cyan("将要改名：%s → %s（%s）" % (old_id, new_id,
                     dict((k, c) for k, c, _, _ in _LAYERS).get(layer, layer)))
    print("  %-10s %s" % ("包目录", pkg_dir))
    print("  %-10s %s" % ("        →", dir_new))
    if same_id:
        print("  %-10s （id 没变，数据目录不用动）" % "数据目录")
    elif state_old.is_dir():
        print("  %-10s %s" % ("数据目录", state_old))
        print("  %-10s %s" % ("        →", state_new))
    else:
        print("  %-10s （还没有数据目录，跳过）" % "数据目录")
    if layer == "system":
        out.print_cyan("  注意：这是出厂件，宿主升级时 system/ 会被整体替换 —— "
                       "改出来的名字到那时会变回去，还会多出一份。")

    done = []
    try:
        pkg_dir.rename(dir_new)
        done.append("包目录")
    except OSError as e:
        out.print_cyan("[错误] 包目录改不动：%s" % e)
        out.print_cyan("       可能是它正被占用（包还在跑 / 编辑器开着这个目录里的文件）。")
        return 1
    if not same_id and state_old.is_dir():
        try:
            if state_stale:
                import time as _t
                keep = state_new.with_name("%s.prev-%s"
                                           % (state_new.name, _t.strftime("%Y%m%d-%H%M%S")))
                state_new.rename(keep)
                out.print_cyan("  目标数据目录里原来有东西（上一个同名包留下的）—— "
                               "已经挪到 %s" % keep.name)
            state_old.rename(state_new)
            done.append("数据目录")
        except OSError as e:
            out.print_cyan("[警告] 数据目录没改成：%s" % e)
            out.print_cyan("       包目录已经改了，数据还在 %s —— 手动挪过去即可。" % state_old)
    if not same_id:
        try:
            p = json.loads((dir_new / "pkg.json").read_text(encoding="utf-8"))
            if not isinstance(p, dict):
                raise ValueError("新目录里的 pkg.json 不是一个对象")
            p["id"] = new_id
            if "name" in p:
                p["name"] = _swap_ids(p.get("name"), old_id, new_id)
            al = p.get("aliases")
            if isinstance(al, list):
                p["aliases"] = [new_id if str(a).lower() == old_id.lower() else a for a in al]
            (dir_new / "pkg.json").write_text(
                json.dumps(p, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            done.append("清单 id")
        except Exception as e:
            out.print_cyan("[警告] 清单没改成：%s" % e)
            out.print_cyan("       目录已经是 %s，把 pkg.json 里的 id 手动改成 '%s' 即可。"
                           % (dir_new, new_id))
        for doc_name in ("AGENT.md", "README.md"):
            doc = dir_new / doc_name
            if not doc.is_file():
                continue
            try:
                raw = doc.read_bytes()
                enc = "utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8"
                try:
                    text = raw.decode(enc)
                except UnicodeDecodeError as e:
                    out.print_cyan("[警告] %s 不是 UTF-8，没替换旧 id：%s" % (doc_name, e))
                    continue
                new_text = text.replace(old_id, new_id)
                if new_text != text:
                    doc.write_bytes(new_text.encode(enc))
                    done.append(doc_name)
            except OSError as e:
                out.print_cyan("[警告] %s 里的旧 id 没换成：%s" % (doc_name, e))
    if same_id:
        out.print_cyan("已对齐：目录名 %s → %s（id 一直是 '%s'）"
                       % (pkg_dir.name, new_id, old_id))
        _shortcut_sync()
        return 0
    out.print_cyan("已改名：%s → %s（改了 %s）" % (old_id, new_id, "、".join(done)))
    print("       显示名 / 别名 / AGENT.md / README.md 里的旧 id 也一起换过了"
          "（出现 `%s` 的地方全文换成 `%s`）。" % (old_id, new_id))
    if layer == "user":
        out.print_cyan("       包调用现在要用 `moss :%s`（旧名字不再认识，除非你把它写进 aliases）。"
                       % new_id)
    _shortcut_sync()
    return 0

def cmd_layer(name, target=None, table=None):
    if not target:
        rec = registry.find_alias(name)
        if not rec:
            out.print_cyan("[错误] 没有这个包：'%s'。直接敲 `moss` 看有哪些。" % name)
            return 1
        layer = rec.get("layer")
        other = "system" if layer == "user" else "user"
        print("  %-8s %s" % ("包", rec["id"]))
        print("  %-8s %s（%s）" % ("层", layer,
                                   dict((k, c) for k, c, _, _ in _LAYERS).get(layer, layer)))
        print("  %-8s %s" % ("目录", rec["dir"]))
        print("  %-8s %s（按 id 算，不跟着层走）" % ("数据目录", paths.pkg_state_dir(rec["id"])))
        if rec.get("shadowed"):
            print("  %-8s 另一层（%s）也有同名包，这一份现在压着那一份 —— 换层会撞车。"
                  % ("注意", rec["shadowed"]))
        out.print_cyan("换到另一层：moss --layer %s %s" % (rec["id"], other))
        return 0

    target = str(target).strip().lower()
    if target not in ("user", "system"):
        out.print_cyan("[错误] 层只有两种：user / system（给的是 '%s'）。" % target)
        out.print_cyan("       用法：moss --layer <包> [user|system]（不写层 = 只看现在在哪层）")
        return 2
    rec = registry.find_alias(name)
    if not rec:
        out.print_cyan("[错误] 没有这个包：'%s'。直接敲 `moss` 看有哪些。" % name)
        return 1

    pid = str(rec["id"])
    src_layer = rec.get("layer")
    src_dir = Path(rec["dir"])
    dirname = src_dir.name
    dst_dir = (paths.SYSTEM_PKGS if target == "system" else paths.USER_PKGS) / dirname

    if src_layer == target:
        out.print_cyan("[信息] '%s' 本来就在 %s 层：%s" % (pid, target, src_dir))
        return 0

    if dst_dir.exists():
        out.print_cyan("[错误] 目标层已经有这个目录：%s" % dst_dir)
        out.print_cyan("       先把它删掉，或者用 `moss --rename %s <新id>` 换个身份再搬。" % pid)
        return 1
    for r in registry.scan_all():
        if r.get("layer") == target and r["id"] == pid:
            out.print_cyan("[错误] %s 层已经有一个叫 '%s' 的包：%s" % (target, pid, r["dir"]))
            out.print_cyan("       两层不能同时有同 id 的包（那叫遮蔽，不叫搬家）—— "
                           "先把那个删掉 / 改名。")
            return 1

    out.print_cyan("将要换层：%s  %s → %s（id 不变）" % (pid, src_layer, target))
    print("  %-10s %s" % ("包目录", src_dir))
    print("  %-10s %s" % ("        →", dst_dir))
    print("  %-10s %s" % ("数据目录", paths.pkg_state_dir(pid)))
    if target == "system":
        out.print_cyan("  注意：放进 system 层等于声明「这是出厂件」—— moss 升级时 system/ 会被"
                       "整体替换，你对它的改动到那时会被冲掉。")
    else:
        out.print_cyan("  放进 user 层：升级不碰它，而且它会压住 system 层的同名包。")

    try:
        src_dir.rename(dst_dir)
    except OSError as e:
        out.print_cyan("[提示] 直接改名没成（%s），改用复制 + 删。" % e)
        try:
            shutil.move(str(src_dir), str(dst_dir))
        except Exception as e2:
            out.print_cyan("[错误] 搬不动：%s" % e2)
            out.print_cyan("       常见原因：① 安装目录只读 / 需要管理员；② 这个包还在跑"
                           "（先在界面上停掉）；③ 目录被资源管理器或编辑器占着。")
            out.print_cyan("       检查一下这两处：%s ／ %s" % (src_dir, dst_dir))
            return 1

    out.print_cyan("换层完成：'%s' 现在在 %s 层" % (pid, target))
    print("       %s" % dst_dir)
    out.print_cyan("       调用方式一个字没变：moss %s%s" % (config.plugin_symbol(), pid))
    _shortcut_sync()
    return 0

def _swap_ids(value, old_id, new_id):
    if isinstance(value, str):
        return value.replace(old_id, new_id)
    if isinstance(value, dict):
        return dict((k, _swap_ids(v, old_id, new_id)) for k, v in value.items())
    if isinstance(value, list):
        return [_swap_ids(v, old_id, new_id) for v in value]
    return value

def _dir_stats(p):
    n, size = 0, 0
    try:
        for f in Path(p).rglob("*"):
            if f.is_file():
                n += 1
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
    except Exception:
        pass
    return n, size

def _human_size(n):
    if n >= 1048576:
        return "%.1f MB" % (n / 1048576.0)
    if n >= 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%d 字节" % n

def _ai_mask(p):
    q = dict(p or {})
    k = str(q.get("api_key") or "")
    q["api_key"] = (k[:4] + "…" + k[-4:]) if len(k) > 10 else ("（已设置）" if k else "（空）")
    return q

def cmd_ai_config(kv, reveal=False):
    import json as _json
    name, prof = config.ai_active_profile()
    prof = dict(prof) if reveal else _ai_mask(prof)
    kids = " ".join(kv or [])
    want = ""
    for tok in (kv or []):
        if tok.startswith("--profile="):
            want = tok.split("=", 1)[1]
    if want:
        p2 = config.ai_profiles().get(want)
        if p2 is None:
            out.print_cyan("[错误] 没有这一组：%s" % want)
            return 1
        name = want
        prof = dict(p2) if reveal else _ai_mask(p2)
    print(_json.dumps({"ok": True, "active": config.ai_active_name(), "profile": name,
                       "params": prof, "profiles": sorted(config.ai_profiles()),
                       "summary": _ai_summary()},
                      ensure_ascii=False, indent=2))
    return 0

def _ai_summary():
    out = {}
    for nm, pr in config.ai_profiles().items():
        out[nm] = {"base_url": str(pr.get("base_url") or ""),
                   "model": config.ai_models(pr),
                   "key": _ai_mask(pr).get("api_key") or "",
                   "has_key": bool(str(pr.get("api_key") or ""))}
    return out

def cmd_ai_presets():
    import json as _json
    print(_json.dumps({"ok": True, "presets": config.AI_PRESETS}, ensure_ascii=False, indent=2))
    return 0

def _ai_profile_from_argv(argv):
    profs = config.ai_profiles()
    name, over = "", {}
    for tok in (argv or []):
        if "=" in tok:
            k, _, v = tok.partition("=")
            k = k.strip()
            if k in config.AI_FIELDS:
                over[k] = v
        elif not name:
            name = tok
    name = name or config.ai_active_name()
    p = dict(profs.get(name) or {})
    for k, v in over.items():
        if k == "model":
            p["model"] = [x.strip() for x in str(v).replace("\\n", ",").split(",") if x.strip()]
        else:
            p[k] = v
    return name, p

def _ai_http_get(url, api_key=""):
    import urllib.request
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    if api_key:
        req.add_header("Authorization", "Bearer " + str(api_key))
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.status, r.read().decode("utf-8", "replace")

def _json_dumps(obj):
    import json as _json
    try:
        return _json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)[:2000]

def _ai_models_from_json(raw):
    import json as _json
    data = _json.loads(raw)
    arr = []
    if isinstance(data, list):
        arr = data
    elif isinstance(data, dict):
        for key in ("data", "models", "result"):
            if isinstance(data.get(key), list):
                arr = data[key]
                break
    out = []
    for it in arr:
        if isinstance(it, str):
            mid = it
        elif isinstance(it, dict):
            mid = it.get("id") or it.get("name") or it.get("model")
        else:
            mid = ""
        mid = str(mid or "").strip()
        if mid and mid not in out:
            out.append(mid)
    return out

def _ai_balance_text(obj):
    if not isinstance(obj, dict):
        return "", str(obj)[:500]
    infos = obj.get("balance_infos")
    if isinstance(infos, list) and infos:
        bits = []
        for it in infos:
            if not isinstance(it, dict):
                continue
            cur = str(it.get("currency") or "CNY")
            total = it.get("total_balance", it.get("balance", ""))
            extra = []
            if it.get("topped_up_balance") not in (None, ""):
                extra.append("充值 %s" % it.get("topped_up_balance"))
            if it.get("granted_balance") not in (None, ""):
                extra.append("赠送 %s" % it.get("granted_balance"))
            bits.append(("%s %s" % (cur, total)).strip() +
                        ("（%s）" % " / ".join(extra) if extra else ""))
        avail = obj.get("is_available")
        text = "余额：" + "；".join(bits)
        if avail is not None:
            text += " · 账户" + ("可用" if avail else "不可用")
        return text, _json_dumps(obj)
    data = obj.get("data") if isinstance(obj.get("data"), dict) else obj
    if isinstance(data, dict):
        for key in ("total_balance", "available_balance", "balance", "credit", "credits",
                    "remaining", "remain", "amount", "cash_balance", "voucher_balance"):
            if data.get(key) not in (None, ""):
                cur = data.get("currency") or data.get("unit") or ""
                return "余额：%s%s" % (("%s " % cur) if cur else "", data.get(key)), _json_dumps(obj)
    return "", _json_dumps(obj)

def cmd_ai_models(argv):
    import json as _json
    name, p = _ai_profile_from_argv(argv)
    base = str(p.get("base_url") or "").rstrip("/")
    if not base:
        print(_json.dumps({"ok": False, "msg": "还没有接口地址，先填 Base URL。"}, ensure_ascii=False))
        return 1
    url = base + "/models"
    try:
        code, raw = _ai_http_get(url, p.get("api_key") or "")
        models = _ai_models_from_json(raw)
        if not models:
            print(_json.dumps({"ok": False, "msg": "接口通了，但没从返回里认出模型列表。",
                               "detail": raw[:2000]}, ensure_ascii=False))
            return 4
        print(_json.dumps({"ok": True, "models": models, "count": len(models),
                           "msg": "获取到 %d 个模型" % len(models)}, ensure_ascii=False))
        return 0
    except Exception as e:
        detail = ""
        try:
            import urllib.error
            if isinstance(e, urllib.error.HTTPError):
                detail = e.read(1000).decode("utf-8", "replace")
        except Exception:
            pass
        print(_json.dumps({"ok": False, "msg": "获取模型失败：%s" % e, "detail": detail},
                          ensure_ascii=False))
        return 4

def _ai_balance_urls(base):
    import urllib.parse
    u = urllib.parse.urlsplit(base)
    root = "%s://%s" % (u.scheme, u.netloc)
    host = (u.hostname or "").lower()
    out = []
    if "deepseek" in host:
        out.append(root + "/user/balance")
    if "moonshot" in host:
        out.append(root + "/v1/users/me/balance")
        out.append(base + "/users/me/balance")
    if "openrouter" in host:
        out.append(root + "/api/v1/credits")
    if "siliconflow" in host:
        out.append(base + "/user/info")
    return out

def cmd_ai_balance(argv):
    import json as _json
    name, p = _ai_profile_from_argv(argv)
    base = str(p.get("base_url") or "").rstrip("/")
    if not base:
        print(_json.dumps({"ok": False, "msg": "还没有接口地址，先填 Base URL。"}, ensure_ascii=False))
        return 1
    urls = _ai_balance_urls(base)
    if not urls:
        print(_json.dumps({"ok": False, "msg": "这家还没有已知的余额查询接口（DeepSeek / Kimi / "
                                                "OpenRouter / 硅基流动有）。"}, ensure_ascii=False))
        return 4
    last = ""
    for url in urls:
        try:
            _code, raw = _ai_http_get(url, p.get("api_key") or "")
            obj = _json.loads(raw)
            text, detail = _ai_balance_text(obj)
            if text:
                print(_json.dumps({"ok": True, "msg": text, "detail": detail}, ensure_ascii=False))
                return 0
            last = "接口通了，但这家的返回格式不认识：%s" % raw[:300]
        except Exception as e:
            last = str(e)
    print(_json.dumps({"ok": False, "msg": "查余额失败：%s" % last}, ensure_ascii=False))
    return 4

def cmd_ai_profile_set(argv):
    if not argv:
        out.print_cyan("[错误] 用法：--ai-profile-set <组名> base_url=… model=… api_key=…")
        return 1
    name, rest = argv[0], argv[1:]
    fields = {}
    for item in rest:
        if "=" not in item:
            continue
        k, _, v = item.partition("=")
        k = k.strip()
        if k not in config.AI_FIELDS:
            continue
        fields[k] = v
    nm, cur = config.ai_profile_set(name, fields)
    shown = {k: (" / ".join(cur[k]) if isinstance(cur[k], list) else cur[k])
             for k in sorted(cur)}
    out.print_cyan("已存：%s（%s）" % (nm, "；".join("%s=%s" % (k, v) for k, v in shown.items())))
    return 0

def cmd_ai_profile_del(name):
    left = config.ai_profile_del(name)
    out.print_cyan("删了「%s」；剩下的组：%s" % (name, " / ".join(left) or "（没有）"))
    return 0

def cmd_ai_rename(argv):
    if len(argv) < 2:
        out.print_cyan("[错误] 用法：--ai-rename <旧组名> <新组名>")
        return 1
    nm = config.ai_rename(argv[0], argv[1])
    if not nm:
        out.print_cyan("[错误] 没改成：旧的那组不存在，或者新名字已经被别的组占了。")
        return 1
    out.print_cyan("改名完成：%s → %s" % (argv[0], nm))
    return 0

def cmd_ai_active(name):
    config.ai_set_active(name)
    out.print_cyan("当前那组 = %s" % name)
    return 0

def cmd_ai_test(argv):
    import json as _json
    import urllib.request
    profs = config.ai_profiles()
    name, over = "", {}
    for tok in (argv or []):
        if "=" in tok:
            _k, _, _v = tok.partition("=")
            if _k.strip() in config.AI_FIELDS:
                over[_k.strip()] = _v
        elif not name:
            name = tok
    name = name or config.ai_active_name()
    p = dict(profs.get(name) or {})
    for _k, _v in over.items():
        if _k == "model":
            p["model"] = [_x.strip() for _x in _v.replace("\\n", ",").split(",") if _x.strip()]
        else:
            p[_k] = _v
    if not p:
        out.print_cyan("[错误] 没有这一组：%s（先 --ai-profile-set 配一个，或者直接给 base_url=… model=…）"
                       % (name or "（空）"))
        return 1
    base = str(p.get("base_url") or "").rstrip("/")
    models = config.ai_models(p)
    if not base or not models:
        out.print_cyan("[错误] 这一组还没填 base_url / model（model 可以写多个，逗号隔开）。")
        return 1
    model = models[0]
    body = _json.dumps({"model": model, "stream": True, "max_tokens": 8,
                        "messages": [{"role": "user", "content": "只回两个字：收到"}]},
                       ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + str(p.get("api_key") or "")})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            code, first = r.status, ""
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith("data:"):
                    first = line[5:].strip()
                    break
        out.print_cyan("连上了：HTTP %s（模型 %s）· 流式第一个增量 = %s"
                       % (code, model, (first or "（空）")[:200]))
        return 0
    except Exception as e:
        out.print_cyan("[错误] 没连上 / 报错：%s" % e)
        return 4

def _ai_err_line(raw):
    import json as _json
    txt = str(raw or "").strip()
    msg = ""
    if txt:
        try:
            obj = _json.loads(txt)
        except Exception:
            obj = None
        if isinstance(obj, dict):
            err = obj.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message") or err.get("msg") or err.get("type") or "")
            elif isinstance(err, str):
                msg = err
            if not msg:
                for k in ("message", "msg", "detail", "error_description"):
                    if obj.get(k):
                        msg = str(obj[k])
                        break
    msg = " ".join((msg or txt).split())
    for cut in (" (request_id", "(request_id"):
        i = msg.find(cut)
        if i > 0:
            msg = msg[:i].strip()
            break
    return msg[:120] + ("…" if len(msg) > 120 else "")

def _ai_delta_text(chunk):
    import json as _json
    s = str(chunk or "").strip()
    if not s:
        return ""
    try:
        obj = _json.loads(s)
    except Exception:
        return ""
    try:
        ch = obj["choices"][0]
    except Exception:
        return ""
    if isinstance(ch, dict):
        for key in ("delta", "message"):
            v = ch.get(key)
            if isinstance(v, str) and v:
                return v[:80]
            if not isinstance(v, dict):
                continue
            if v.get("content"):
                return str(v["content"])[:80]
            if v.get("reasoning_content"):
                return "（思考）" + str(v["reasoning_content"])[:70]
        if ch.get("text"):
            return str(ch["text"])[:80]
    return ""

def cmd_ai_ping(argv):
    import json as _json
    import time
    import urllib.error
    import urllib.request

    name, p = _ai_profile_from_argv(argv)
    models = config.ai_models(p)
    model = models[0] if models else ""
    base = str(p.get("base_url") or "").rstrip("/")
    t0 = time.time()

    def done(ok, code=0, sample="", msg=""):
        print(_json_dumps({"ok": bool(ok), "model": model,
                           "ms": int((time.time() - t0) * 1000),
                           "code": int(code or 0), "sample": sample, "msg": msg}))
        return 0

    if not base:
        return done(False, msg="这一组还没填接口地址")
    if not model:
        return done(False, msg="没有给模型名")
    body = _json.dumps({"model": model, "stream": True, "max_tokens": 4, "temperature": 0,
                        "messages": [{"role": "user", "content": "只回两个字：收到"}]},
                       ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(base + "/chat/completions", data=body,
                                 headers={"Content-Type": "application/json",
                                          "Authorization": "Bearer " + str(p.get("api_key") or "")})
    code, sample, frames = 0, "", 0
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            code = int(r.status)
            ctype = str(r.headers.get("Content-Type") or "").lower()
            if "event-stream" not in ctype:
                body = r.read().decode("utf-8", "replace")
                sample = _ai_delta_text(body)
            else:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    if not data:
                        continue
                    txt = _ai_delta_text(data)
                    if txt:
                        sample = txt
                        break
                    frames += 1
                    if frames >= 40:
                        break
    except urllib.error.HTTPError as e:
        code = int(e.code)
        raw = ""
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        return done(False, code=code, msg=_ai_err_line(raw) or ("HTTP %s" % code))
    except Exception as e:
        return done(False, msg=str(e)[:160])
    if 200 <= code < 300:
        return done(True, code=code, sample=sample or "（回了空的）", msg="能通")
    return done(False, code=code, msg="HTTP %s" % code)

def cmd_remove(name, table, assume_yes=False):
    rec = registry.find_alias(name)
    if not rec:
        out.print_cyan("[错误] 没有这个包：'%s'。直接敲 moss 看有哪些。" % name)
        return 1

    pid = rec["id"]
    layer = rec.get("layer")
    cn = dict((k, c) for k, c, _, _ in _LAYERS).get(layer, layer)
    pkg_dir = Path(rec["dir"])
    state_dir = paths.pkg_state_dir(pid)
    shadowed = rec.get("shadowed")

    targets = [(pkg_dir, "包本体")]
    if state_dir.is_dir():
        targets.append((state_dir, "它的数据"))

    out.conditional_clear_screen()
    out.print_cyan("将要卸载：%s（%s）" % (pid, cn))
    total = 0
    for p, label in targets:
        n, size = _dir_stats(p)
        total += size
        print("  %-8s %s" % (label, p))
        print("  %-8s %d 个文件，%s" % ("", n, _human_size(size)))
    print("  %-8s 合计 %s" % ("", _human_size(total)))
    if shadowed:
        out.print_cyan("  提示：它还遮住了 %s 层的同名包 —— 删掉之后那个会重新生效。"
                       % dict((k, c) for k, c, _, _ in _LAYERS).get(shadowed, shadowed))
    out.print_cyan("注意：这是永久删除（不进回收站），删除后无法恢复。")

    if not assume_yes:
        if not sys.stdin.isatty():
            out.print_cyan("[错误] 非交互环境请显式加 -y 确认。")
            return 1
        try:
            ans = input("确认？ [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans not in ("y", "yes"):
            out.print_cyan("[取消] 什么都没删。")
            return 0

    errors = []
    for p, label in targets:
        try:
            shutil.rmtree(str(p))
            print("  已删 %s" % p)
        except Exception as e:
            errors.append("%s（%s）：%s" % (label, p, e))

    if errors:
        out.print_cyan("有 %d 处没删干净：" % len(errors))
        for e in errors:
            print("  × %s" % e)
        return 1
    out.print_cyan("已卸载 %s。" % pid)
    _shortcut_sync()
    return 0

def cmd_resolve(name, table):
    out.print_cyan("[解析] moss %s —— 逐层向上搜索，第一层有候选就停" % name)
    depth = config.max_parent_depth()
    hit_base, hit_cands = None, []
    for base in resolve.search_bases(Path.cwd(), depth):
        cands = resolve.candidates_at(base, name, table, depth)
        if cands and hit_base is None:
            hit_base, hit_cands = base, cands
        flag = "  ★ 命中，停在这一层" if (cands and base == hit_base) else ""
        print("  %s   候选 %d 个%s" % (base, len(cands), flag))
        for c in cands:
            if c["marker_hits"]:
                d = c.get("marker_dist")
                where = "本目录" if d == 0 else ("上层 %d 级" % d if d is not None else "?")
                marks = "  项目标记: %s（%s）" % (",".join(c["marker_hits"]), where)
            else:
                marks = ""
            print("      %-16s runner=%-10s %s%s"
                  % (c["path"].name, c["runner"], c["probe"].get("why"), marks))
        if hit_base is not None:
            break

    if hit_base is None:
        out.print_cyan("\n[结论] 在 %s 及向上 %d 层内没找到以 '%s' 开头的可运行目标。"
                       % (Path.cwd(), depth, name))
        print("       注意：只有装了对应 runner 的才算候选（moss --selfcheck 看 runner 表）。")
        return 1

    try:
        cand, why = resolve.disambiguate(hit_cands, hit_base, name, depth)
    except resolve.Aborted:
        out.print_cyan("\n[结论] 需要你选择，但当前不是交互环境（或你取消了）。")
        return 1
    out.print_cyan("\n[结论] 选中 %s\n       依据：%s" % (cand["path"], why))
    return 0

def cmd_info(args):
    want_json = False
    want_examples = False
    docs_key = None
    name = ""
    rest = list(args)
    i = 0
    while i < len(rest):
        a = rest[i]
        if a in ("--json", "-j"):
            want_json = True
        elif a in ("--examples", "-e"):
            want_examples = True
        elif a == "--docs" or a.startswith("--docs="):
            keys = ("readme", "usage", "agent", "all")
            if a.startswith("--docs="):
                v = a.split("=", 1)[1]
            elif (i + 1 < len(rest) and not rest[i + 1].startswith("-")
                  and (name or rest[i + 1].lower() in keys)):
                v = rest[i + 1]
                i += 1
            else:
                v = "all"
            docs_key = (v or "all").strip().lower()
            if docs_key not in keys:
                out.print_cyan("[错误] --docs 只认 readme / usage / agent / all，收到 %r" % (v,))
                return 1
        elif a.startswith("-"):
            out.print_cyan("[错误] --info 不认识的选项：%s" % a)
            out.print_cyan("       用法：moss --info <包名> [--json] [--docs readme|agent|all]")
            return 1
        elif not name:
            name = a
        else:
            out.print_cyan("[错误] --info 一次只看一个包：多余的 %r" % (a,))
            return 1
        i += 1

    if not name:
        out.print_cyan("[错误] --info 需要一个包名。例：moss --info higgs")
        out.print_cyan("       看有哪些包：直接敲 moss。")
        return 1
    rec = registry.find_alias(name)
    if rec is None:
        out.print_cyan("[错误] 没有这个包：'%s'。看有哪些包：直接敲 moss。" % name)
        return 1

    p = dict(rec["pkg"])
    pkg_mod.display_name(p)
    pid = str(p.get("id") or rec["id"])
    psym = config.plugin_symbol()
    invoke = ("moss %s%s" % (psym, pid)).strip()
    ai = p.get("ai") if isinstance(p.get("ai"), dict) else {}
    examples = []
    for e in (ai.get("examples") or []):
        if isinstance(e, dict):
            a = str(e.get("args") or "").strip()
            note = str(e.get("note") or "").strip()
        else:
            a, note = str(e).strip(), ""
        if not any(a == x[0] for x in examples):
            examples.append((a, note))

    def _cmd_of(a):
        a = str(a or "").strip()
        low = a.lower()
        if low == "moss" or low.startswith("moss "):
            return a
        if psym and a.startswith(psym):
            return "moss " + a
        return ("%s %s" % (invoke, a)).strip() if a else invoke

    if want_examples:
        if not examples:
            out.print_cyan("[提示] 这个包的 pkg.json 里没写 ai.examples。")
            return 1
        for a, _note in examples:
            print(_cmd_of(a))
        return 0

    if docs_key:
        wants = pkg_mod.DOCS_KEYS if docs_key == "all" else (docs_key,)
        got = pkg_mod.docs_of(p, rec["dir"], limit=None)
        picked = [(k, got[k]) for k in wants if k in got]
        if not picked:
            out.print_cyan("[提示] 这个包没声明 %s。在 pkg.json 里加一行就有："
                           % " / ".join(wants))
            out.print_cyan('       "docs": {"readme": "README.md", "agent": "AGENT.md"}')
            return 1
        for k, d in picked:
            if len(picked) > 1:
                print("=== %s（%s，%d 字符）===" % (k, d["file"], d["size"]))
            sys.stdout.write(d["text"])
            if not d["text"].endswith("\n"):
                print()
        sys.stdout.flush()
        return 0

    docs = pkg_mod.docs_of(p, rec["dir"], limit=ui.DOCS_MAX)

    if want_json:
        payload = {
            "ok": True,
            "id": pid,
            "layer": rec["layer"],
            "dir": str(rec["dir"]),
            "invoke": invoke,
            "examples": [{"cmd": _cmd_of(a), "args": a, "note": n} for (a, n) in examples],
            "docs": docs,
            "pkg": p,
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        sys.stdout.flush()
        return 0

    layer_name = "用户插件" if rec["layer"] == "user" else "系统插件"
    head = "%s —— %s" % (pid, p.get("name") or pid) if (p.get("name") or "") not in ("", pid) else pid
    print("%s  v%s · %s · %s" % (head, p.get("version") or "?", p.get("kind") or "?", layer_name))

    def row(label, value):
        print("  %s%s" % (_pad(label, 8), value))

    row("目录", rec["dir"])
    if p.get("aliases"):
        row("别名", ", ".join(str(a) for a in p["aliases"]))
    if p.get("tags"):
        row("标签", ", ".join(str(t) for t in p["tags"]))
    row("调用", invoke + " <参数…>" + ("   （不填参数 = 看它自己的用法）" if not examples else ""))
    if p.get("desc"):
        row("说明", p["desc"])

    params = [x for x in (p.get("params") or []) if isinstance(x, dict) and x.get("name")]
    if params:
        print("\n  参数（%d）" % len(params))
        for x in params:
            bits = [str(x.get("type") or "string")]
            if x.get("rest"):
                bits.append("rest")
            if x.get("required"):
                bits.append("必填")
            if x.get("default") not in (None, ""):
                bits.append("默认 %r" % (x.get("default"),))
            print("    %s%s  [%s]" % (_pad(x["name"], 12), str(x.get("desc") or "").strip(),
                                     " · ".join(bits)))
    else:
        print("\n  参数：没有（这个包不看命令行参数）")

    if ai.get("expose") or ai.get("why"):
        bits = ["expose=%s" % str(bool(ai.get("expose"))).lower()]
        if ai.get("risk"):
            bits.append("risk=%s" % ai["risk"])
        if ai.get("timeout"):
            bits.append("timeout=%ss" % ai["timeout"])
        print("\n  AI（%s）" % ", ".join(bits))
        if ai.get("why"):
            print("    %s%s" % (_pad("为什么", 8), ai["why"]))
        if examples:
            for n, (a, note) in enumerate(examples):
                line = _cmd_of(a) + (("      # " + note) if note else "")
                print("    %s%s" % (_pad("示例", 8) if n == 0 else " " * 8, line))
        else:
            print("    %s（没写 ai.examples）" % _pad("示例", 8))

    if docs:
        print("\n  文档")
        for k in pkg_mod.DOCS_KEYS:
            if k in docs:
                print("    %s %6d 字符   → moss --info %s --docs %s"
                      % (_pad(docs[k]["file"], 14), docs[k]["size"], pid, k))
    else:
        print("\n  文档：没声明（pkg.json 的 docs 里加 readme / agent 就有）")
    print("\n  JSON：moss --info %s --json      示例：moss --info %s --examples" % (pid, pid))
    return 0

def cmd_selfcheck(table):
    ok = True
    out.print_cyan("moss 自检")
    print("=" * 60)
    info = paths.describe()
    print("  调用名    : %s" % info["invocation"])
    print("  安装根    : %s   %s" % (info["home"], "存在" if paths.HOME.is_dir() else "✗ 不存在"))
    ok &= paths.HOME.is_dir()
    print("  system/   : %s   %s" % (info["system"], "存在" if paths.SYSTEM_DIR.is_dir() else "✗ 不存在"))
    ok &= paths.SYSTEM_DIR.is_dir()
    print("  user_data/: %s   %s" % (info["user"], "存在" if paths.USER_DIR.is_dir() else "（首次运行会创建）"))
    print("  runner 表 : %d 个 runner —— %s"
          % (len(table), ", ".join(sorted(table.keys())) or "（空！）"))
    ok &= bool(table)

    print("  配置文件  : %s   %s" % (paths.USER_CONFIG,
                                     "存在" if paths.USER_CONFIG.is_file() else "（首次运行会创建）"))
    tpl = config.template_problems()
    if tpl:
        ok = False
        print("     ✗ 默认模板和默认值不一致（用户会看不到这些键）：")
        for p in tpl:
            print("       - %s" % p)
    else:
        print("     模板与默认值一致 ✔")
        print("     裸名归谁  : %s   （path_mode=%r  plugin_mode=%r  no_chdir=%r  后台=%r）"
              % ("**跑包**" if config.bare_owner() == "package" else "找文件（路径调用）",
                 config.path_symbol(), config.plugin_symbol(),
                 config.no_chdir_symbol(), config.detach_symbol()))
    sp = config.settings_problems()
    if sp:
        ok = False
        print("     ✗ 设置面板的清单和默认配置对不上：")
        for p in sp:
            print("       - %s" % p)
    else:
        print("     设置面板  : %d 项，和默认配置一一对应 ✔"
              % sum(len(g["items"]) for g in config.settings_groups()))

    rts = runners_mod.list_runtimes()
    print("  自带运行时: %d 个" % len(rts))
    for r in rts:
        exe = (Path(r["dir"]) / r["interpreter"]) if r["interpreter"] else None
        good = bool(exe and exe.is_file())
        pin = " (默认)" if r["isDefault"] else ""
        print("     - %-8s %-9s [%s]%s  %s"
              % (r["family"], r["version"], r["layer"], pin,
                 "✔" if good else "✗ 缺解释器 " + r["interpreter"]))
    if not rts:
        print("     （没有自带运行时，包会退化到用系统解释器）")
    for fam in runners_mod.runtime_families():
        if not runners_mod.default_version(fam):
            print("     ⚠ 家族 '%s' 没有在 default.json 里钉默认版本" % fam)

    recs = registry.scan_all()
    print("  包        : %d 个" % len(recs))
    layers = {}
    for r in recs:
        layers[r.get("layer") or "?"] = layers.get(r.get("layer") or "?", 0) + 1
    for r in recs:
        e = pkg_mod.entry_path(r["pkg"], Path(r["dir"]))
        ic = pkg_mod.icon_path(r["pkg"], Path(r["dir"]))
        print("     - %-12s [%-6s] runner=%-10s 入口=%-12s 图标=%s" % (
            r["id"], r.get("layer") or "?", r["pkg"].get("runner"),
            (e.name if e else ("inline" if pkg_mod.inline_code(r["pkg"]) else "✗ 缺失")),
            (ic.name if ic else "—")))
    odd = [(registry.dir_of(r), r["id"]) for r in recs if registry.dir_mismatch(r)]
    if odd:
        print("  目录名≠id : %d 个 —— %s"
              % (len(odd), "；".join("%s（id=%s）" % (d, i) for d, i in odd)))
        print("              想统一：moss --rename <id> <id>（只改目录名，数据不动）")
    have = [r["id"] for r in recs if pkg_mod.icon_path(r["pkg"], Path(r["dir"]))]
    lack = [r["id"] for r in recs if not pkg_mod.icon_path(r["pkg"], Path(r["dir"]))]
    print("  图标      : %d/%d 个包有图标%s"
          % (len(have), len(recs), ("；没有：" + "、".join(lack)) if lack else ""))
    for r in recs:
        prob = pkg_mod.icon_problem(r["pkg"], Path(r["dir"]))
        if prob:
            ok = False
            print("     ✗ %s: %s" % (r["id"], prob))
    cd_ok, cd_why = shell.console_available()
    who = shell.parent_shell()
    print("  cd 注入   : %s   （%s）" % ("可用" if cd_ok else "✗ 不可用", cd_why))
    print("  父 shell  : %s   （沿父进程链: %s）"
          % (who or "✗ 没认出来",
             " ← ".join("%s" % n for n, _ in shell.parent_chain()[:5])))
    print("  启动方式  : %s" % shell.launch_kind())
    print("              → 现在敲 moss（不带参数）会%s"
          % ("开界面" if shell.gui_mode() else "打用法 + 包列表"))
    ui_ok, ui_why = ui.available(table)
    print("  界面      : %s   （%s）" % ("可用" if ui_ok else "✗ 不可用", ui_why))
    print("              → 界面要跑包时调这个：%s" % " ".join(ui.host_cmd()))
    if not ui_ok:
        ok = False
    wv_ok, wv_why = ui.webview2_status(table)
    if wv_ok is None:
        print("  渲染内核  : ?   %s" % wv_why)
    else:
        print("  渲染内核  : %s   （%s）"
              % ("WebView2 / Chromium" if wv_ok else "✗ 会退回 IE 内核（界面只有静态文字）",
                 wv_why))
        if not wv_ok:
            ok = False
            print("              → 装 WebView2 运行时（约 205 MB）：%s" % ui.WEBVIEW2_URL)
    for label, p, has in shell.installed_state():
        print("  %-9s: %s   （%s）" % (label, "已装包装函数" if has else "未装包装函数", p))
    print("            装了包装函数的话，moss cd 在屏幕上不留任何回显；"
          "没装则用注入（命令会显示出来）")
    print("=" * 60)
    out.print_cyan("结论: %s" % ("自检通过" if ok else "✗ 自检失败"))
    return 0 if ok else 1

def cmd_ui(args):
    return ui.launch(args)

def handle_cd(target_str, print_only=False):
    target_path = resolve.find_dir(target_str, Path.cwd())

    if not target_path:
        msg = "未找到目标目录: %s" % target_str
        if print_only:
            print("[错误] %s" % msg, file=sys.stderr)
            return 1
        out.conditional_clear_screen()
        out.print_cyan("[错误] %s" % msg)
        return 1

    abs_path = str(target_path.resolve())

    if print_only:
        print(abs_path)
        return 0

    who = shell.parent_shell()
    if who is None:
        out.print_cyan("[错误] 认不出当前是哪个 shell（父进程链里既没有 PowerShell 也没有 cmd）。")
        out.print_cyan("目录是: %s" % abs_path)
        out.print_cyan("想彻底解决（而且屏幕上不留回显）: moss cd --install")
        return 1

    ok, why = shell.inject(shell.cd_command(who, abs_path))
    if not ok:
        out.print_cyan("[错误] 注入按键失败: %s" % why)
        out.print_cyan("目录是: %s" % abs_path)
        out.print_cyan("想彻底解决（而且屏幕上不留回显）: moss cd --install")
        return 1

    return 0

def cmd_cd_install():
    out.conditional_clear_screen()
    out.print_cyan("把 moss 的 cd 包装函数写进 PowerShell 配置（屏幕上不留回显）")
    results = shell.install_cd()
    bad = 0
    for label, path, result, err in results:
        flag = "✗" if err else "·"
        if err:
            bad += 1
        print("  %s %-22s %s" % (flag, label, result))
        print("      %s" % path)
    if bad:
        out.print_cyan("有 %d 个文件没写成功，上面有原因。" % bad)
        return 1
    out.print_cyan("装好了。新开一个 PowerShell 窗口才生效（老窗口执行 . $PROFILE 也行）。")
    out.print_cyan("之后 moss cd <目标> 屏幕上不会出现任何命令；"
                   "cmd 窗口没有等价物，仍走注入。")
    out.print_cyan("不想要了: moss cd --uninstall")
    return 0

def cmd_cd_uninstall():
    out.conditional_clear_screen()
    out.print_cyan("从 PowerShell 配置里删掉 cd 包装函数")
    results = shell.uninstall_cd()
    bad = 0
    removed = 0
    for label, path, result, err in results:
        if err:
            bad += 1
        if result == "已移除":
            removed += 1
        print("  %s %-22s %s" % ("✗" if err else "·", label, result))
        print("      %s" % path)
    if bad:
        out.print_cyan("有 %d 个文件没弄成功，上面有原因。" % bad)
        return 1
    if not removed:
        out.print_cyan("这两个配置文件里本来就没装过包装函数，没动它们。")
        return 0
    out.print_cyan("已移除。新开窗口后 moss cd 回到注入方式（命令会显示在屏幕上）。")
    return 0

def main(argv):
    config.load()

    if argv:
        argv = [config.restore_prefix(argv[0])] + list(argv[1:])

    paths.ensure_user_dirs()

    for _msg in shortcut_mod.sync_if_stale():
        print("[短命令] " + _msg, file=sys.stderr)

    events.BUS.on("before:run", history.on_before_run, name="history-start")
    events.BUS.on("after:run", history.on_after_run, name="history")

    table = runners_mod.load()

    if not argv or argv[0] in ("-h", "--help", "help"):
        if not argv and shell.gui_mode():
            return cmd_ui([])
        out.conditional_clear_screen()
        print(USAGE)
        print()
        return cmd_list(table, skip_clear=True)

    first = argv[0]
    rest = argv[1:]

    detach = False
    dsym = config.detach_symbol()
    if first.startswith(dsym):
        detach = True
        first = first[len(dsym):]

    if first.lower() in ("ui", "--ui"):
        return cmd_ui(rest)

    if first.lower() == 'cd':
        if '--print' in rest:
            out.print_cyan("[提示] moss cd --print 已经去掉了：")
            out.print_cyan("       零回显是靠包装函数（moss cd --install）设 MOSS_CD_PRINT=1 实现的，"
                           "不需要手动加开关。")
            out.print_cyan("       只想看解析出的路径：moss --resolve <名字>。")
            return 1
        args = list(rest)
        if args and args[0] in ('--install', '--uninstall'):
            return cmd_cd_install() if args[0] == '--install' else cmd_cd_uninstall()
        print_only = os.environ.get('MOSS_CD_PRINT') == '1'
        if args:
            return handle_cd(args[0], print_only=print_only)
        out.print_cyan("[错误] 'cd' 命令需要一个目标路径。用法: moss cd <目标>")
        out.print_cyan("       （想屏幕上不留回显: moss cd --install）")
        return 1

    if first in ("--remove", "--uninstall"):
        args = [a for a in rest if a not in ("-y", "--yes")]
        yes = len(args) != len(rest)
        if not args:
            out.print_cyan("[错误] --remove 需要一个包名（别名或 id）。直接敲 moss 看有哪些。")
            return 1
        return cmd_remove(args[0], table, assume_yes=yes)
    if first in ("--ai-config", "--ai"):
        return cmd_ai_config(rest)
    if first == "--ai-config-reveal":
        return cmd_ai_config(rest, reveal=True)
    if first == "--ai-presets":
        return cmd_ai_presets()
    if first == "--ai-profile-set":
        return cmd_ai_profile_set(rest)
    if first == "--ai-profile-del":
        return cmd_ai_profile_del(rest[0] if rest else "")
    if first == "--ai-active":
        return cmd_ai_active(rest[0] if rest else "")
    if first == "--ai-rename":
        return cmd_ai_rename(rest)
    if first == "--ai-test":
        return cmd_ai_test(rest)
    if first == "--ai-ping":
        return cmd_ai_ping(rest)
    if first == "--ai-models":
        return cmd_ai_models(rest)
    if first == "--ai-balance":
        return cmd_ai_balance(rest)
    if first == "--ai-import-legacy":
        nm = config.ai_import_legacy()
        out.print_cyan(("导进来了，组名 %s" % nm) if nm else "没找到旧的 state/ai/config.json")
        return 0
    if first in ("--snap", "--snapshot"):
        from . import snap as _snap
        return _snap.cmd_snap(rest, table)
    if first == "--spec":
        return cmd_spec()
    if first == "--ui-payload":
        import json as _json
        from . import ui as _ui
        sys.stdout.write(_json.dumps(_ui.build_payload(), ensure_ascii=False))
        sys.stdout.flush()
        return 0
    if first == "--settings":
        import json as _json
        sys.stdout.write(_json.dumps(config.settings_payload(), ensure_ascii=False))
        sys.stdout.flush()
        return 0
    if first == "--settings-set":
        import json as _json
        if not rest:
            out.print_cyan("[错误] --settings-set 需要一份 JSON。")
            return 1
        try:
            pairs = _json.loads(rest[0])
        except ValueError as e:
            out.print_cyan("[错误] --settings-set 的参数不是 JSON：%s" % e)
            return 1
        if not isinstance(pairs, dict):
            out.print_cyan("[错误] --settings-set 要的是一个 JSON 对象（键 = 段.键）。")
            return 1
        r = config.set_values(pairs)
        if r.get("ok"):
            try:
                from . import shortcut as _sc
                msgs = _sc.sync()
                if msgs:
                    r["shortcut"] = msgs
            except Exception:
                pass
        sys.stdout.write(_json.dumps(r, ensure_ascii=False))
        sys.stdout.flush()
        return 0 if r.get("ok") else 1
    if first == "--settings-check":
        import json as _json
        if not rest:
            out.print_cyan("[错误] --settings-check 需要一份 JSON。")
            return 1
        try:
            pairs = _json.loads(rest[0])
        except ValueError as e:
            out.print_cyan("[错误] --settings-check 的参数不是 JSON：%s" % e)
            return 1
        if not isinstance(pairs, dict):
            out.print_cyan("[错误] --settings-check 要的是一个 JSON 对象（键 = 段.键）。")
            return 1
        sys.stdout.write(_json.dumps(config.settings_check(pairs), ensure_ascii=False))
        sys.stdout.flush()
        return 0
    if first in ("--layer", "--move-layer"):
        if not rest:
            out.print_cyan("[错误] --layer 需要一个包名。")
            out.print_cyan("       看现状：moss --layer <包>        换层：moss --layer <包> system|user")
            return 2
        return cmd_layer(rest[0], rest[1] if len(rest) > 1 else None, table)
    if first == "--rename":
        if len(rest) < 2:
            out.print_cyan("[错误] --rename 需要两个名字：旧的（id 或别名）和新的 id。")
            out.print_cyan("       例：moss --rename img pictures")
            return 1
        return cmd_rename(rest[0], rest[1], table)
    if first == "--new":
        pos, kv = [], {}
        for tok in rest:
            if "=" in tok:
                k, _, v = tok.partition("=")
                if k.strip().lower() in ("name", "desc", "kind"):
                    kv[k.strip().lower()] = v
                    continue
            pos.append(tok)
        if not pos:
            out.print_cyan("[错误] --new 需要一个包 id。例：moss --new my-first")
            out.print_cyan("       也可以带上名字/介绍：moss --new my-first name=截图归档 desc=一句话")
            return 1
        return cmd_new(pos[0], kv.get("kind") or "task",
                       kv.get("name") or "", kv.get("desc") or "")
    if first == "--selfcheck":
        return cmd_selfcheck(table)
    if first == "--history":
        n = None
        if rest:
            try:
                n = max(1, int(rest[0]))
            except ValueError:
                n = None
        return cmd_history(n, table)
    if first == "--info":
        return cmd_info(rest)
    if first == "--resolve":
        if not rest:
            out.print_cyan("[错误] --resolve 需要一个名字。")
            return 1
        return cmd_resolve(rest[0], table)

    if first == "--pkg":
        if not rest:
            out.print_cyan("[错误] --pkg 需要一个包名。")
            return 1
        return _run_package(rest[0], rest[1:], table, detach=False)
    if first == "--alias":
        from . import shortcut as _sc
        return _sc.cmd_alias(rest)
    if first == "--cd-status":
        import json as _json
        try:
            st = shell.installed_state()
        except Exception:
            st = []
        sys.stdout.write(_json.dumps({
            "ok": True,
            "any": any(bool(v) for (_l, _p, v) in st),
            "profiles": [{"label": l, "path": str(p), "installed": bool(v)}
                         for (l, p, v) in st],
        }, ensure_ascii=False))
        sys.stdout.flush()
        return 0

    if first.startswith("-"):
        out.print_cyan("[错误] 不认识的选项：%s" % first)
        out.print_cyan("       直接敲 moss 看用法和包列表。")
        return 1

    psym = config.plugin_symbol()
    psym_path = config.path_symbol()
    ncsym = config.no_chdir_symbol()

    if psym and first.startswith(psym):
        return _run_package(first.lstrip(psym).strip(), rest, table, detach)
    if psym_path and first.startswith(psym_path):
        return _run_path(first.lstrip(psym_path), rest, table, detach, change_dir=True)
    if ncsym and first.startswith(ncsym):
        return _run_path(first.lstrip(ncsym), rest, table, detach, change_dir=False)

    if config.bare_owner() == "package":
        rc = _run_package(first, rest, table, detach, quiet_missing=True)
        if rc is not None:
            return rc
    return _run_path(first, rest, table, detach, change_dir=True)

def _run_package(alias, rest, table, detach, quiet_missing=False):
    if not alias:
        psym = config.plugin_symbol()
        out.print_cyan("[错误] '%s' 后面要写包名。例：moss %simg" % (psym, psym))
        out.print_cyan("       直接敲 moss 看有哪些包。")
        return 1
    rec = registry.find_alias(alias)
    if not rec:
        if quiet_missing:
            return None
        out.print_cyan("[错误] 没有这个包：'%s'。直接敲 moss 看有哪些包。" % alias)
        return 1
    params = parse_params(rec["pkg"], rest)
    inv, err = build_pkg_inv(rec, params, via="cli")
    if err:
        out.print_cyan("[错误] %s" % err)
        return 1
    inv, err = _fill_interpreter(inv, table)
    if err:
        out.print_cyan("[错误] %s" % err)
        return 1
    return engine.run(inv, table, detach=detach)

def _run_path(name, rest, table, detach, change_dir):
    cand, why = resolve.find(name, Path.cwd(), table)
    if cand is None:
        if why == "用户取消":
            out.print_cyan("[取消] 已退出。")
            return 130
        rec = history.find_recent(name)
        if rec is not None:
            out.print_cyan("[历史] 文件系统里没有 '%s'，改用最近一次记录：%s  (cwd=%s)"
                           % (name, _hist_name(rec), rec.get("cwd") or "-"))
            return cmd_rerun_record(rec, table)
        out.print_cyan("[错误] 在 %s 及上层没找到以 '%s' 开头的可运行目标。"
                       % (Path.cwd(), name))
        print("       （只在装了对应 runner 的情况下才算候选：用 moss --resolve %s 看细节）"
              % name)
        if registry.find_alias(name):
            psym = config.plugin_symbol()
            hint = ("%s%s" % (psym, name)) if psym else name
            out.print_cyan("[提示] 有个同名的包 '%s'：要跑它就敲 moss %s" % (name, hint))
        return 1

    out.print_cyan("[选中] %s  ← %s" % (cand["path"], why))
    inv = build_path_inv(cand, rest, via="cli", change_dir=change_dir)
    inv, err = _fill_interpreter(inv, table)
    if err:
        out.print_cyan("[错误] %s" % err)
        return 1
    return engine.run(inv, table, detach=detach)
