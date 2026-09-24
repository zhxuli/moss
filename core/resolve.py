# -*- coding: utf-8 -*-
"""路径解析与多候选消歧（`E-16`）。

`moss m` 要回答的是：**用户说的这个 `m`，到底指哪个文件、用哪个 runner 跑？**

★ 照抄 pa.py 的搜索方式（`E-20` 照抄原则）：
  · 从 cwd 开始，逐层向上最多 `max_parent_depth` 层（`pa.py:316`）
  · 名字**前缀**匹配（`m` 命中 `main.py`，`pa.py:738`）
  · 目录则往下找默认入口 `main|run|app|index`（`pa.py:404`）
  · **找到了就不再往上找**
  pa.py 这部分工作良好，原样保留。

★ 但消歧方式改了，因为旧方式有个真问题：
  旧（`pa.py:767-793`）：多个候选 → 打印"请重新输入正确的指令"然后退出 → 用户得重敲一遍
  新：**四级消歧，尽量不打扰用户**（`E-16` / `E-18`）

四级顺序（越靠前越不打扰）：
  1. **可用性过滤** —— 没装 Go，`main.go` 直接出局（`E-15`）
  2. 唯一候选直接跑
  3. **项目标记** —— 有 `go.mod` 就是 Go 项目（`E-17`）
  4. **记住上次的选择**
  5. 还不行才问用户，并且**选完就跑**（`E-18`）+ 记住这次选择
"""
import json

from . import config, paths, runners as runners_mod

DEFAULT_ENTRY_STEMS = ("main", "run", "app", "index")


def search_bases(cwd, depth=None):
    """从 cwd 逐层向上。照抄 pa.py:316 generate_search_paths。"""
    depth = config.max_parent_depth() if depth is None else depth
    cur = cwd.resolve()
    for _ in range(depth + 1):
        yield cur
        if cur.parent == cur:
            break
        cur = cur.parent


def _probe_for(base, target, rname, spec):
    return runners_mod.probe(rname, spec, {
        "cwd": str(base),
        "home": str(paths.HOME),
        "entry": str(target),
    })


def _marker_hits(base, spec, depth):
    """这个 runner 的"项目标记"在 base 或它上面几层里存在吗？"""
    want = runners_mod.markers_of(spec)
    if not want:
        return []
    hits = []
    for d in search_bases(base, depth):
        for m in want:
            if (d / m).exists():
                hits.append(m)
    return sorted(set(hits))


def collect(base, name, runners, depth):
    """在 base 这一层收集候选。返回候选列表（已被可用性过滤）。"""
    cands = []
    prefix = name.lower()
    try:
        entries = sorted(base.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return cands

    for entry in entries:
        if not entry.name.lower().startswith(prefix):
            continue

        if entry.is_file():
            rname, spec = runners_mod.by_ext(runners, entry.suffix)
            if not spec:
                continue
            probe = _probe_for(base, entry, rname, spec)
            if not probe["available"]:
                continue
            cands.append({
                "path": entry, "runner": rname, "spec": spec,
                "probe": probe, "base": base, "from_dir": None,
                "marker_hits": _marker_hits(base, spec, depth),
            })

        elif entry.is_dir():
            # 目录 → 往下找默认入口（照抄 pa.py:404 find_plugin_executable 的思路）
            try:
                inner = sorted(entry.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            for f in inner:
                if not f.is_file() or f.stem.lower() not in DEFAULT_ENTRY_STEMS:
                    continue
                rname, spec = runners_mod.by_ext(runners, f.suffix)
                if not spec:
                    continue
                probe = _probe_for(entry, f, rname, spec)
                if not probe["available"]:
                    continue
                cands.append({
                    "path": f, "runner": rname, "spec": spec,
                    "probe": probe, "base": entry, "from_dir": entry.name,
                    "marker_hits": _marker_hits(entry, spec, depth),
                })
    return cands


# ---------------------------------------------------------------- 记忆
def _memory_file(base):
    return paths.state_dir_for(str(base.resolve())) / "choices.json"


def load_memory(base):
    f = _memory_file(base)
    if f.is_file():
        try:
            with open(f, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            pass
    return {}


def save_memory(base, name, chosen_name):
    paths.ensure_user_dirs()
    d = _memory_file(base).parent
    d.mkdir(parents=True, exist_ok=True)
    mem = load_memory(base)
    mem[name.lower()] = chosen_name
    with open(_memory_file(base), "w", encoding="utf-8") as f:
        json.dump(mem, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 消歧
class Aborted(Exception):
    """用户取消了选择（比如按了 Ctrl-C 或输入非法）。"""


def _describe(c):
    extra = ""
    if c["marker_hits"]:
        extra = "  ← 项目标记: " + ", ".join(c["marker_hits"])
    via = c["probe"].get("why") or ""
    return "%-14s [%s]  %s%s" % (c["path"].name, c["runner"], via, extra)


def _ask(cands, base, name):
    """让用户选，**选完就跑**（E-18），并把选择记住。"""
    print("[选择] '%s' 有 %d 个可用的目标：" % (name, len(cands)))
    for i, c in enumerate(cands, 1):
        print("   %d) %s" % (i, _describe(c)))
    print("   0) 取消")
    try:
        raw = input("请输入序号并回车（默认 1）: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise Aborted()
    if raw == "0":
        raise Aborted()
    if not raw:
        idx = 0
    else:
        try:
            idx = int(raw) - 1
        except ValueError:
            raise Aborted()
    if not (0 <= idx < len(cands)):
        raise Aborted()
    chosen = cands[idx]
    save_memory(base, name, chosen["path"].name)
    return chosen, "用户选择"


def disambiguate(cands, base, name, depth):
    """返回 (候选, 依据)。四级消歧，尽量不打扰用户。"""
    # 2 · 精确名字匹配（stem 完全等于输入）
    perfect = [c for c in cands if c["path"].stem.lower() == name.lower()]
    if len(perfect) == 1:
        return perfect[0], "精确名字匹配"
    if len(cands) == 1:
        return cands[0], "唯一可用候选"

    # 3 · 项目标记
    ranked = sorted(cands, key=lambda c: (-len(c["marker_hits"]), c["path"].name.lower()))
    top = ranked[0]
    if top["marker_hits"] and (len(ranked) == 1 or len(top["marker_hits"]) > len(ranked[1]["marker_hits"])):
        return top, "项目标记 " + ", ".join(top["marker_hits"])

    # 4 · 记忆
    last = (load_memory(base).get(name.lower()) or "")
    if last:
        for c in cands:
            if c["path"].name.lower() == last.lower():
                return c, "上次选过"

    # 5 · 问
    return _ask(cands, base, name)


def find(name, cwd, runners, depth=None):
    """按 pa.py 的方式逐层搜索，返回 (候选, 依据) 或 (None, None)。"""
    for base in search_bases(cwd, depth):
        if not base.is_dir():
            continue
        cands = collect(base, name, runners, depth)
        if not cands:
            continue
        try:
            return disambiguate(cands, base, name, depth)
        except Aborted:
            return None, "用户取消"
    return None, None


def probe_all(cwd, name, runners, depth=None):
    """调试用：把每一层的候选都列出来，不做消歧。"""
    rows = []
    for base in search_bases(cwd, depth):
        for c in collect(base, name, runners, depth):
            rows.append((str(base), c))
    return rows
