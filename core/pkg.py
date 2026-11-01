# -*- coding: utf-8 -*-
"""包清单 `pkg.json` 的读写。

★ 一条硬规矩（`F-21`）：**未知字段必须原样保留。**

旧宿主读到新包，必须把不认识的字段一个字节不改地写回去 —— 否则
"新版本写的包被老版本打开一次就残废"。这在自我迭代系统里是慢性自杀。

反面教材就在旧项目里：`bin/soft/exec/core.py:275` 的 `normalize()`
返回固定字段字典，`user_data/exec/cmds/zeen.json` 里的 `"steps": []`
过一次界面保存就永久消失。

所以这里**绝不**用白名单重建字典 —— 只在原始字典上补默认值。
"""
import json
import os
import re
import sys
from pathlib import Path

SPEC = 1

#: 手写 `pkg.json` 最容易写错的两类形状 —— 都踩过 / 都会出事：
#:   `"entry": "run.py"`      少一层（该是对象）→ 后面 `entry.get()` 崩出 Python traceback，
#:                            用户看到的是 Python 栈，而不是"这里写错了"
#:   `"aliases": "img,image"` 该是数组 → 遍历字符串会**按字符**匹配，
#:                            `moss :i` 会静默命中 img（不崩，但更坏）
#: 所以这里**就地纠正 + 说一句**：手写友好，但绝不静默。
_DICT_FIELDS = ("entry", "capabilities", "output", "ai")
_LIST_FIELDS = ("tags", "aliases", "params")


def _fix_shape(pkg):
    """把"形状写错"的已知字段纠正回来；纠不了的删掉，让下面的默认值接手。"""
    for key in _DICT_FIELDS:
        v = pkg.get(key)
        if isinstance(v, dict):
            continue
        if key == "entry" and isinstance(v, str) and v.strip():
            pkg[key] = {"file": v.strip()}          # 手写最常见的一种，直接当 file 用
            print("[提示] pkg.json 的 entry 写成了字符串，已按 {\"file\": %r} 处理"
                  % v.strip(), file=sys.stderr)
            continue
        if v not in (None, ""):
            print("[警告] pkg.json 的 %s 应该是对象，已忽略它原来的值：%r"
                  % (key, v), file=sys.stderr)
        pkg.pop(key, None)
    for key in _LIST_FIELDS:
        v = pkg.get(key)
        if v is None or v == "":
            pkg.pop(key, None)
            continue
        if isinstance(v, str):                      # "img,image" → ["img", "image"]
            v = [x for x in v.replace("，", ",").replace(",", " ").split() if x]
            pkg[key] = v
            print("[提示] pkg.json 的 %s 写成了字符串，已按 %r 处理" % (key, v),
                  file=sys.stderr)
        elif not isinstance(v, list):
            print("[警告] pkg.json 的 %s 应该是数组，已忽略它原来的值：%r"
                  % (key, v), file=sys.stderr)
            pkg.pop(key, None)
            continue
        if key == "params":                         # ["text"] → [{"name": "text"}]
            fixed = []
            for p in v:
                if isinstance(p, dict):
                    fixed.append(p)
                elif isinstance(p, str) and p.strip():
                    fixed.append({"name": p.strip()})
                else:
                    print("[警告] pkg.json 的 params 里有一项形状不对，已丢掉：%r"
                          % (p,), file=sys.stderr)
            pkg[key] = fixed


def _example_value(v):
    """示例里 `k=v` 的 v 怎么写回一行命令（空格要引号，布尔用小写 —— 参数解析认这个）。"""
    if isinstance(v, bool):
        return "true" if v else "false"
    s = str(v)
    return '"%s"' % s if (" " in s or s == "") else s


def _one_example(it):
    """一条 `ai.examples` → `{"args": …}`；认不出来返回 None（并说一句）。"""
    if isinstance(it, str):
        return {"args": it.strip()}                 # 空串 = "不带参数地调一次"，也留着
    if not isinstance(it, dict):
        print("[警告] pkg.json 的 ai.examples 里有一项既不是字符串也不是对象，已丢掉：%r"
              % (it,), file=sys.stderr)
        return None
    args = it.get("args")
    if isinstance(args, str):
        return it
    if args is not None:                            # "args": 123 这种
        print("[警告] pkg.json 的 ai.examples 里的 args 应该是字符串，已按 %r 处理"
              % str(args), file=sys.stderr)
        return dict(it, args=str(args))
    # 没有 args → 其余键当 `k=v` 参数拼一行（第 3 代写法，见 _fix_ai 的注释）
    pairs = ["%s=%s" % (k, _example_value(v)) for k, v in it.items()
             if k not in ("note", "why", "desc") and not isinstance(v, (dict, list))]
    if not pairs:
        return {"args": ""}                         # `{}` / 只有 note = 不带参数的调用
    return dict(it, args=" ".join(pairs))


def _fix_ai(pkg):
    """`ai.examples` 的每一条**归一化成 `{"args": "…"}`**。

    ★ 手写清单长出了四代写法，都真实存在于本机：
        1. `{"args": "webp 60% 1200 *.png", "note": "…"}`   ← 契约里写的（`img`）
        2. `"--list"` / `":proxycheck undo"`                ← 直接写参数串（`higgs` / `cli-proxy-check`）
        3. `{"target": "8.8.8.8"}`                          ← 按参数名写 key=value（`ip` / `md5`）
        4. `{}`                                             ← "不带参数地调一次"（`ip`）
      下游（界面、`moss --info`）只认一种形状，而以前只认 1：于是 2 / 3 / 4 全被
      `e.get("args")` **静默吞掉** —— `higgs` 的 8 条示例在详情页和 `--ui-payload`
      里一条都不剩，**谁也没报错**。静默丢数据比报错坏得多，所以统一在这一层。
    ★ 字符串 → 对象**不打提示**（和 `params: ["text"]` 一样，是写法差异不是写错）；
      真的认不出来的形状才说一句。
    """
    raw = pkg.get("ai")
    if not isinstance(raw, dict):
        return
    items = raw.get("examples")
    if items is None or items == "":
        return
    ai = dict(raw)                                  # 别就地改调用方那份
    if not isinstance(items, list):
        items = [items]
    fixed = []
    for it in items:
        ex = _one_example(it)
        if ex is not None:
            fixed.append(ex)
    ai["examples"] = fixed
    pkg["ai"] = ai


def normalize(raw, pid=None):
    """补默认值。**入参的每一个字段都保留**，包括将来才认识的那些。"""
    pkg = dict(raw) if isinstance(raw, dict) else {}

    pkg["spec"] = int(pkg.get("spec") or SPEC)
    pkg["id"] = str(pkg.get("id") or pid or "").strip()
    pkg["kind"] = str(pkg.get("kind") or "task")
    pkg["version"] = str(pkg.get("version") or "0.0.0")
    _fix_shape(pkg)
    _fix_ai(pkg)
    pkg.setdefault("name", pkg["id"])
    pkg.setdefault("desc", "")
    pkg.setdefault("tags", [])
    pkg.setdefault("aliases", [])
    pkg.setdefault("runner", "")
    pkg.setdefault("entry", {})
    pkg.setdefault("params", [])
    pkg.setdefault("capabilities", {})
    pkg.setdefault("output", {"mode": "text"})
    pkg.setdefault("ai", {"expose": False})
    pkg["drop"] = normalize_drop(pkg.get("drop"))
    return pkg


#: 「拖进来」声明（`V-38` ✅）。每条命令能做两件事：
#:   `cwd`   把拖进来的目录当**工作目录**（拖的是文件时 = 它所在的文件夹）
#:   `param` 把路径**追加到参数串末尾**（强制末尾 —— 你定的）
#: 再有 `quote`（加不加双引号）、`base`（只给文件名不给完整路径）。
#:  ★ `quote` **默认是 True**（`V-41` ✅）：Windows 路径里全是反斜杠，而界面把参数串
#:    交给宿主时要过一次 `shlex` —— **不加引号的 `C:\a\b.ico` 会被吃掉所有反斜杠**
#:    （实测：`shlex.split(r"C:\Users\x\y.ico")` → `['C:Usersxy.ico']`），包那边就当成
#:    一段字符串了。要"原样不引号"的包，写 `"quote": false` 明说。
#:  ★ `ext`（`V-183` ✅）只写在 `file` 那一项里：**"我只收这几种扩展名"**。
#:    不写 = 什么文件都收（老包一个字都不用改）。`md5` 这种不限的就不写；
#:    `img` 写 `["jpg","jpeg","png","bmp","gif","tiff","webp"]` ⇒ 拖个 .txt 进窗口时
#:    它**不再亮起来**（以前它和 md5 一起亮，松手还会去跑一个处理不了的图）。
#:    匹配在**界面那侧**做（拖动时只能拿到"文件叫什么"，见 `system/ui/js/drop.js`）；
#:    宿主只负责把声明原样带到界面的 payload 里。
_DROP_KINDS = ("file", "dir")
_DROP_KEYS = ("cwd", "param", "quote", "base", "ext")
_DROP_BOOL_KEYS = ("cwd", "param", "quote", "base")

#: 扩展名里允许的字符。点会在归一化时去掉，空格 / 斜杠 / 通配符都不行 ——
#: 带这些的基本都是写错了，报一声再丢掉，别留一条永远匹配不上的规则。
_EXT_OK = re.compile(r"^[a-z0-9_+-]+$")


def _norm_ext(raw, where):
    """把 `ext` 归一化成"小写、不带点"的列表（`V-183`）。

    ★ **不写 / 空 / 全是垃圾 = `[]` = 什么文件都收**（向后兼容）。
      为什么不把空数组当成"什么都不收"：那样写错一个字（`"ext": []`）会让整个包
      **静默地**不再收任何文件 —— 这种哑巴失败最难查。真要不收文件，写 `"file": false`。
    ★ `"*"` = 明确写"什么都收"，意思和 `[]` 一样（写出来更像人话）。
    """
    if raw is None or raw == "" or raw is False:
        return []
    items = raw if isinstance(raw, list) else [raw]          # 写成单个字符串也认
    out = []
    for it in items:
        if not isinstance(it, str):
            print("[警告] %s 里的扩展名应该是字符串，已忽略：%r" % (where, it), file=sys.stderr)
            continue
        e = it.strip().lower().lstrip(".")
        if not e:
            continue
        if e == "*":
            print("[提示] %s 里写了 *（什么都收）—— 和「不写 ext」是一回事" % where,
                  file=sys.stderr)
            return []
        if not _EXT_OK.match(e):
            print("[警告] %s 里的扩展名 %r 含有不认识的字符（点/空格/斜杠都不行），已忽略"
                  % (where, it), file=sys.stderr)
            continue
        if e not in out:
            out.append(e)
    return out


def _norm_drop_rule(rule, where, kind):
    """`file` / `dir` 里那一条。`False` / 空 → None（这一种不收）。"""
    if rule is None or rule is False or rule == "":
        return None
    if rule is True:                       # `"dir": true` → 收，但没说怎么用 → 当"进参数"
        return {"cwd": False, "param": True, "quote": True, "base": False, "ext": []}
    if not isinstance(rule, dict):
        print("[警告] %s 里的这一项应该是对象或 false，已忽略：%r" % (where, rule),
              file=sys.stderr)
        return None
    out = dict((k, bool(rule.get(k))) for k in _DROP_BOOL_KEYS)
    out["quote"] = True if rule.get("quote") is None else bool(rule.get("quote"))
    if kind == "file":
        out["ext"] = _norm_ext(rule.get("ext"), where)
    elif "ext" in rule:
        print("[提示] %s 是文件夹那一项，写 ext 没意义（文件夹没有扩展名），已忽略" % where,
              file=sys.stderr)
    for k in rule:
        if k not in _DROP_KEYS:
            print("[提示] %s 里多了一个不认识的键 %r，已忽略" % (where, k), file=sys.stderr)
    if not out["cwd"] and not out["param"]:
        out["param"] = True                # 收了却什么都没说 → 当"进参数"，别让它白收
    return out


def normalize_drop(raw):
    """把 `drop` 归一化成**一个命令的数组**（`V-38`）。

    ★ 两种写法都收：单个对象（一条命令，最常见）或数组（一个包有多种拖入命令）。
      归一化成数组之后，界面那边只有一种形状要处理 —— 以后加第二种命令不用改界面。
    ★ **不写 / 空 = 这个包完全不收拖入**（比如「快捷翻译」），返回 `[]`。
    """
    if raw is None or raw == "" or raw is False:
        return []
    items = raw if isinstance(raw, list) else [raw]
    out = []
    for i, it in enumerate(items):
        where = "pkg.json 的 drop[%d]" % i
        if not isinstance(it, dict):
            print("[警告] %s 应该是对象，已忽略：%r" % (where, it), file=sys.stderr)
            continue
        cmd = {"label": str(it.get("label") or "运行")}
        for kind in _DROP_KINDS:
            cmd[kind] = _norm_drop_rule(it.get(kind), where, kind)
        if cmd["file"] is None and cmd["dir"] is None:
            print("[警告] %s 里 file / dir 一个都没写（或都写了 false），这条命令没用，"
                  "已忽略" % where, file=sys.stderr)
            continue
        for k in it:
            if k not in _DROP_KINDS and k != "label":
                print("[提示] %s 里多了一个不认识的键 %r，已忽略" % (where, k), file=sys.stderr)
        out.append(cmd)
    return out


def load(pkg_dir):
    """从目录读 pkg.json。读不出来返回 None（不抛，交给调用方决定怎么办）。"""
    f = pkg_dir / "pkg.json"
    if not f.is_file():
        return None
    try:
        with open(f, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None
    return normalize(raw, pkg_dir.name)


def save(pkg_dir, pkg):
    pkg_dir.mkdir(parents=True, exist_ok=True)
    with open(pkg_dir / "pkg.json", "w", encoding="utf-8") as f:
        json.dump(pkg, f, ensure_ascii=False, indent=2)


#: `docs` 认哪几个键（`V-388`）。**白名单**：别的键原样留在清单里，只是不往界面/命令里带。
DOCS_KEYS = ("readme", "usage", "agent")


def docs_of(pkg, pkg_dir, limit=None):
    """包里声明的「说明」文件：`"docs": {"readme": "README.md"}` → 读成文本。

    ★ 只认 `DOCS_KEYS` 那几个键；声明的是**相对包目录**的路径（绝对路径也认）。
      这里**不做越界拦截** —— 说明文件是给人和 AI 读的文字，不是能跑的东西，
      跟 `entry` / `icon` 的威胁模型不一样（那两个会把路径交给 shell / 当图放进页面）。
    ★ `limit` 是**给载荷用的**上限（界面每次整份拿 payload，见 `core/ui.py:DOCS_MAX`）；
      `None` = 全文 —— `moss --info --docs` 要的是原文，截一半反而更坏。
    ★ 声明了但文件还没写 → **跳过**（不报错、不留空块）：那是正常的中间状态。
    ★ 唯一的一份实现：界面（`payload.docs`）和 `moss --info` 都走这里，
      免得"界面上看得到、命令行读不到"。
    """
    raw = pkg.get("docs")
    if not isinstance(raw, dict):
        return {}
    got = {}
    for key in DOCS_KEYS:
        rel = str(raw.get(key) or "").strip()
        if not rel:
            continue
        full = Path(rel) if os.path.isabs(rel) else (Path(pkg_dir) / rel)
        try:
            if not full.is_file():
                continue
            text = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        got[key] = {
            "file": rel,
            # ★ 规范成 `/`：payload 会被界面拿去显示，也可能被别的系统读走
            "text": text if limit is None else text[:limit],
            "truncated": bool(limit is not None and len(text) > limit),
            "size": len(text),
        }
    return got


def entry_path(pkg, pkg_dir):
    """清单里的 entry 指向哪个文件。`inline` 形式没有文件，返回 None。"""
    entry = pkg.get("entry") or {}
    rel = entry.get("file")
    if not rel:
        return None
    p = (pkg_dir / rel).resolve()
    # 安全：entry 不许跑出包目录（防 `..` 越界）
    try:
        p.relative_to(pkg_dir.resolve())
    except ValueError:
        return None
    return p if p.is_file() else None


#: 包图标认哪些扩展名（`F-29`）。
#:   顺序 = **清单里没写 `icon` 时的自动发现顺序**：矢量 → 无损 → 有损 → ico → 动图/位图。
#:   为什么认这么多：显示图标的界面是 WebView2（Chromium），这些格式它全吃得下；
#:   而 `.ico` 留着是因为将来做 Windows 外壳（快捷方式 / 文件关联）时**只有它管用**。
ICON_EXTS = (".svg", ".png", ".webp", ".jpg", ".jpeg", ".ico", ".gif", ".bmp")


def icon_path(pkg, pkg_dir):
    """这个包的图标文件（绝对路径）；没有 / 写坏了返回 None。

    两种写法都认：
      · 清单里写 `"icon": "assets/logo.svg"` —— 显式指定，放哪、叫什么都行
      · **什么都不写** —— 自动在包目录里找 `icon.svg` / `icon.png` / `icon.webp` / …
        （按 `ICON_EXTS` 的顺序，命中第一个就用）→ 作者零配置，文件名对了就行

    安全规矩跟 `entry.file` 一样：**不许跑出包目录**（防 `..` 越界），
    而且扩展名必须在 `ICON_EXTS` 白名单里（否则一个 `.exe` 也能当"图标"声明进来）。
    """
    name = pkg.get("icon")
    cands = [str(name)] if name else ["icon" + e for e in ICON_EXTS]
    try:
        root = Path(pkg_dir).resolve()
    except OSError:
        return None
    for rel in cands:
        try:
            p = (root / rel).resolve()
            p.relative_to(root)                     # 越界 → 跳过
        except (ValueError, OSError):
            continue
        if p.is_file() and p.suffix.lower() in ICON_EXTS:
            return p
    return None


def icon_problem(pkg, pkg_dir):
    """自检用：**显式声明**了 `icon` 却读不出来时，给一句人话；没声明就返回 None。

    为什么不返回"没图标"当问题：不写 `icon`、也没有 `icon.*` 文件是**合法的**
    （很多命令行包不需要图标）。但**写了却读不到**是真问题 —— 那是作者以为加了、
    实际界面上什么都没有，必须说出来。
    """
    name = pkg.get("icon")
    if not name:
        return None
    if icon_path(pkg, pkg_dir) is not None:
        return None
    ext = Path(str(name)).suffix.lower()
    if ext and ext not in ICON_EXTS:
        return "icon 声明的扩展名不认识：%s（认这些：%s）" % (name, " ".join(ICON_EXTS))
    return "icon 声明的文件找不到（或跑出了包目录）：%s" % name


def inline_code(pkg):
    entry = pkg.get("entry") or {}
    code = entry.get("inline")
    return code if isinstance(code, str) and code else None


def display_name(pkg, lang="zh-CN"):
    """name / desc 允许是字符串，也允许是 {lang: text} 的多语言对象（F-23）。"""
    for key in ("name", "desc"):
        v = pkg.get(key)
        if isinstance(v, dict):
            pkg[key] = v.get(lang) or next(iter(v.values()), "")
        elif v is None:
            pkg[key] = ""
    return pkg


def find_params(pkg):
    """把命令行的位置参数 / key=value 映射到 params 声明上（类型化参数，F-08）。"""
    out = {}
    spec = pkg.get("params") or []
    for p in spec:
        if "name" in p:
            out[p["name"]] = p.get("default")
    return out
