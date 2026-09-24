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
from pathlib import Path

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


def _marker_info(base, spec, depth):
    """找这个 runner 的"项目标记"，返回 (最近距离, [标记名...])。

    距离 0 = 就在候选所在目录；1 = 父目录；以此类推。None = 一个都没有。

    ★ 为什么要记【距离】，而不是只记"有没有"：
      标记要往上找（在 `proj/src/` 里跑要能找到 `proj/go.mod`），
      但往上找会捞到**祖先目录里不相关的标记** —— 比如你的家目录或某个
      上层仓库里有个 `venv`，那所有 Python 候选都会莫名拿一分，
      把真正的项目类型（比如同目录的 `go.mod`）淹掉。

      实测就撞上了：在 `moss/dev/demo` 里判定时，`main.py` 因为上层
      `moss/venv/` 也拿到命中，和同目录有 `go.mod` 的 `main.go` 打平，
      结果该直接选 `main.go` 的却去问用户了。

      **就近的标记才算数** —— 这也是 go / cargo / npm 这类工具的做法：
      往上走，第一个声明自己是项目的目录就定了。
    """
    want = runners_mod.markers_of(spec)
    if not want:
        return None, []
    names, nearest = [], None
    for dist, d in enumerate(search_bases(base, depth)):
        for m in want:
            if (d / m).exists():
                names.append(m)
                if nearest is None or dist < nearest:
                    nearest = dist
    return nearest, sorted(set(names))


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
            mdist, mhits = _marker_info(base, spec, depth)
            cands.append({
                "path": entry, "runner": rname, "spec": spec,
                "probe": probe, "base": base, "from_dir": None,
                "marker_hits": mhits, "marker_dist": mdist,
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
                mdist, mhits = _marker_info(entry, spec, depth)
                cands.append({
                    "path": f, "runner": rname, "spec": spec,
                    "probe": probe, "base": entry, "from_dir": entry.name,
                    "marker_hits": mhits, "marker_dist": mdist,
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


def _describe(c, root=None):
    """一行描述一个候选。

    root 给定时，会在文件名前带上**相对 root 的目录** ——
    多级路径（`moss s/t`）里候选可能来自不同子目录，
    只显示文件名的话用户根本分不清该选哪个。
    """
    label = c["path"].name
    if root is not None:
        try:
            rel = c["base"].resolve().relative_to(Path(root).resolve())
            if str(rel) not in (".", ""):
                label = "%s\\%s" % (rel, label)
        except Exception:
            pass

    extra = ""
    if c["marker_hits"]:
        d = c.get("marker_dist")
        where = "本目录" if d == 0 else ("上层 %d 级" % d if d is not None else "?")
        extra = "  ← 项目标记: %s（%s）" % (", ".join(c["marker_hits"]), where)
    via = c["probe"].get("why") or ""
    return "%-30s [%s]  %s%s" % (label, c["runner"], via, extra)


def _ask(cands, base, name):
    """让用户选，**选完就跑**（E-18），并把选择记住。"""
    print("[选择] '%s' 有 %d 个可用的目标：" % (name, len(cands)))
    for i, c in enumerate(cands, 1):
        print("   %d) %s" % (i, _describe(c, base)))
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

    # 3 · 项目标记（**就近优先**：同目录的标记压过上层祖先目录里的）
    def _score(c):
        dist = c.get("marker_dist")
        if dist is None:
            return (999, 0)                 # 没有标记，排最后
        return (dist, -len(c["marker_hits"]))   # 距离越小越好；同距离标记多者优先

    ranked = sorted(cands, key=lambda c: (_score(c), c["path"].name.lower()))
    top = ranked[0]
    if top["marker_hits"] and (len(ranked) == 1 or _score(top) < _score(ranked[1])):
        where = "本目录" if top["marker_dist"] == 0 else "上层 %d 级" % top["marker_dist"]
        return top, "项目标记 %s（%s）" % (", ".join(top["marker_hits"]), where)

    # 4 · 记忆
    last = (load_memory(base).get(name.lower()) or "")
    if last:
        for c in cands:
            if c["path"].name.lower() == last.lower():
                return c, "上次选过"

    # 5 · 问
    return _ask(cands, base, name)


def split_path_expr(expr):
    """把 `b/m`、`s/t/main` 这种写法拆成段。

    ★ 照抄 pa.py:720 —— `resolve_target` 是按 `/` 拆段、逐级往下走的。
      我在重写解析器时把这个能力丢了，只留了"单段前缀匹配"，
      结果 `moss b/m` 报"没找到以 'b/m' 开头的目标"。**这是违反 E-20 照抄原则的。**
      反斜杠也当分隔符（Windows 习惯）。
    """
    return [p for p in str(expr).replace("\\", "/").split("/") if p]


def _match_dirs(base, head):
    """在当前层找名字以 head 开头的目录。精确同名优先。"""
    try:
        entries = list(base.iterdir())
    except OSError:
        return []
    dirs = [e for e in entries if e.is_dir() and e.name.lower().startswith(head.lower())]
    exact = [d for d in dirs if d.name.lower() == head.lower()]
    return exact if len(exact) == 1 else sorted(dirs, key=lambda p: p.name.lower())


def _walk(base, parts, runners, depth):
    """按路径段逐级往下走，最后一段交给 collect 收候选。

    非最后一段**必须**是目录（照抄 pa.py 的语义）；
    最后一段可以是文件，也可以是目录（是目录就往里找默认入口）。
    """
    head, rest = parts[0], parts[1:]
    if not rest:
        return collect(base, head, runners, depth)
    out = []
    for d in _match_dirs(base, head):
        out.extend(_walk(d, rest, runners, depth))
    return out


def candidates_at(base, name, runners, depth):
    """在 base 这一层收候选。自动区分单段（`m`）和路径式多段（`b/m`、`s/t/main`）。

    ⚠️ 外面（比如 `--resolve`）**必须用这个**，不要直接调 `collect` ——
       否则多段写法会收不到候选，出现"能跑但 --resolve 说找不到"的矛盾。
    """
    parts = split_path_expr(name)
    if len(parts) >= 2:
        return _walk(base, parts, runners, depth)
    return collect(base, name, runners, depth)


def find(name, cwd, runners, depth=None):
    """逐层搜索，返回 (候选, 依据) 或 (None, None)。

    单个词（`moss m`）和带斜杠的路径式（`moss b/m`、`moss s/t/main`）都支持。
    """
    for base in search_bases(cwd, depth):
        if not base.is_dir():
            continue
        cands = candidates_at(base, name, runners, depth)
        if not cands:
            continue
        try:
            # 多段时用完整表达式做记忆键和提示，这样 `b/m` 和 `x/m` 不会互相串
            return disambiguate(cands, base, name, depth)
        except Aborted:
            return None, "用户取消"
    return None, None


def probe_all(cwd, name, runners, depth=None):
    """调试用：把每一层的候选都列出来，不做消歧。"""
    rows = []
    for base in search_bases(cwd, depth):
        for c in candidates_at(base, name, runners, depth):
            rows.append((str(base), c))
    return rows
