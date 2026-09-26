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
import sys

SPEC = 1

#: 手写 `pkg.json` 最容易写错的两类形状 —— 都踩过 / 都会出事：
#:   `"entry": "run.py"`      少一层（该是对象）→ 后面 `entry.get()` 崩出 Python traceback，
#:                            用户看到的是栈，不是"你这里写错了"
#:   `"aliases": "img,image"` 该是数组 → 遍历字符串会**按字符**匹配，
#:                            `moss :i` 会静默命中 img（不崩，但更坏）
#: 所以这里**就地纠正 + 说一句**：手写友好，但绝不静默。
_DICT_FIELDS = ("entry", "capabilities", "output", "ai", "origin")
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


def normalize(raw, pid=None):
    """补默认值。**入参的每一个字段都保留**，包括将来才认识的那些。"""
    pkg = dict(raw) if isinstance(raw, dict) else {}

    pkg["spec"] = int(pkg.get("spec") or SPEC)
    pkg["id"] = str(pkg.get("id") or pid or "").strip()
    pkg["kind"] = str(pkg.get("kind") or "task")
    pkg["version"] = str(pkg.get("version") or "0.0.0")
    _fix_shape(pkg)
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
    pkg.setdefault("origin", {"by": "builtin"})
    return pkg


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
