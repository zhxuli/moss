# -*- coding: utf-8 -*-
"""**技能**（`V-281`/`V-284`）：AI 自己造的能力 —— **就是一个包**，只是住在另一个根里。

你 2026-10-05 的话
------------------
> 「既然我们之前的 pkgs 的插件格式 能完全和 ai 技能兼容，那我们不应该直接使用原来的格式，
>   而把参数配置和路径稍稍不一样吗？这样的话我们还可以在它的技能和我们的插件之间相互转换，
>   我们还可以使用我们已经有的工具对文件进行卸载管理」
> 「技能里面 现在不需要再添加 `--` 了 —— 当时是为了和用户的插件隔离开，防止相互干扰，
>   但是技能无法干扰了，因为我们需要通过 `moss :skill` 参数来调用，所以干扰问题已经彻底解决了」

所以这一层**不另造格式**：技能 = `pkg.json` + 入口文件（跟插件一字不差，`spec("pkg.json")`
那份契约就是它的说明书），只是：

* **id 跟插件同一规格**（`shot`，小写字母开头）：技能**根本不走包解析那条路**
  （入口是 `moss :skill <动词> <名字>`，见 `system/pkgs/skill/`），两个命名空间碰不到一起，
  所以不需要任何前缀。
* **本体住在 `:skill` 插件自己的数据目录里**（跟 `:exec` 把命令放 `state/exec/cmds/` 一样）：

```
system/pkgs/skill/            管理器插件本身（跟 :exec 并排；出厂）
system/pkgs/skill/seed/shot/  出厂样例（**只留作"照它抄"的样板**：不会再自己长进数据目录，`V-288`/`V-289`）
system/pkgs/skill/builtin/<id>/  预制技能（随发行版打包，出厂即可用；同名 user 技能覆盖它）
user_data/state/skill/shot/   **技能本体**：一个目录（pkg.json + 入口 + icon.svg + 任意文件）
user_data/ai/skills_allow.json  **你的授权**（AI 写不到这儿 —— 见下面「声明 ≠ 授权」）
user_data/pkgs/<id>/            「转为插件」搬过去之后，它就是普通插件（插件页里看得见）
```
* **技能和插件两个圈子不互相出现**（`V-284`）：技能这一页只列技能；插件**不再自动进**
  AI 的工具表 —— AI 想用插件就走它一直就有的那条路 `run_moss(":包名 …")`。
  （账本 §16.3「只有 `ai.expose: true` 的插件才进工具列表」**留到商店/权限那轮**，那轮会有
  正经的授权界面；现在只留字段，不做工具面。）


声明 ≠ 授权（这条是旧设计必须补的）
-----------------------------------
账本 §16.6 原话是「验证通过 → `ai.expose = true`，进入可调用池」。那在"包是人写的 / 商店来的"
前提下是安全的；**现在 AI 自己能写文件、也就能自己写 `expose: true`** —— 它一写就给自己发了
通行证。所以拆成两半：

| | 谁写 | 作用 |
|---|---|---|
| `pkg.json` 的 `ai.expose` | 包自己（AI 也写得动） | **声明**"我能被 AI 调" |
| `user_data/ai/skills_allow.json` + 指纹 | **只有界面 / 只有你**（这文件不在 AI 的可写范围里） | **你的授权** |

指纹 = `pkg.json` + 入口文件 + 图标 的 sha1 ⇒ 它事后改一个字，授权自动作废、退回"待批准"。

技能自己的几个字段（都在 `ai` 块里，`additionalProperties: true`，不用改 schema）
-------------------------------------------------------------------------------
```jsonc
"ai": {
  "expose": true,          // 声明：我能被 AI 调（技能目录里必须 true）
  "why": "为什么要造它 / 它解决了什么问题",   // 详情页要显示的就是这句
  "risk": "low",           // 详情页也显示
  "timeout": 60,           // 单次最多跑多久（默认 60，最多 300）
  "examples": [ {"args": "…"} ]
}
```
图标：技能目录里的 `icon.svg`（跟插件一个规矩：相对包目录、不许跑出去）；缺了就画一个默认的，
并记一条**提醒**（不算写坏）。★ 图标是**它自己写的文件**，所以发给界面前要**洗一遍**
（去掉 `<script>` / `on*=` / `javascript:` —— 界面是把它 innerHTML 进去的）。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

#: 洗 SVG：只留画画要用的东西（这只够挡"图标里塞脚本"这种，不追求当完整消毒器用）
_SVG_BAD = re.compile(r"(<\s*script|<\s*foreignObject|<\s*iframe|<\s*use\b|on[a-z]+\s*=|javascript:)",
                      re.I)

HERE = Path(__file__).resolve().parent                     # system/ai
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

#: ★ 这个模块住在 `system/ai/`，是**技能那一层的唯一定义**：宿主界面进程（AI 工作台）
#: 和 `:skill` 插件进程 import 的是同一份 —— 两边不会各写一套然后漂移。
#: 所以它**只用标准库**（不 import `core`、也不 import `system/ui/**` 里的东西）：
#: 插件跑在自带运行时里，跨包 import 越少越不容易坏。
def _home():
    env = (os.environ.get("MOSS_HOME") or "").strip()
    return Path(env) if env else HERE.parents[1]           # system/ai → 安装根


HOME = _home()


def user_data():
    env = (os.environ.get("MOSS_USER_DATA_DIR") or "").strip()
    return Path(env) if env else (HOME / "user_data")

#: 技能 id：**跟插件 id 同一规格**（小写字母开头）。`V-284`：不再要求 `--` 前缀 ——
#: 那是早期为了"别污染用户的插件 id"加的，但现在技能**根本不走包解析那条路**
#: （`moss :skill <动词>` 才是入口，见 `system/pkgs/skill/`），两个命名空间碰不到一起，
#: 前缀就成了纯粹的噪音（你 2026-10-05 的原话：「干扰问题已经彻底解决了」）。
NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

TIMEOUT = 60
TIMEOUT_MAX = 300
TAIL_LINES = 60
TAIL_CHARS = 4000
FILE_CAP = 200


# ------------------------------------------------------------------ 技能住哪儿
def skill_dir():
    """技能本体住**插件自己的数据目录**里（`user_data/state/skill/`）。

    ★ 为什么是这儿（你 2026-10-05 定的）：跟 `:exec` 一个道理 —— 它管的那些命令就住在
      `user_data/state/exec/cmds/`。`:skill` 也是个普通插件，那它的东西就住它自己的数据目录。
      **只差一点**：exec 把代码**内联在 json 里**（`"code": "import sys…"`），技能是
      **一个目录**（`pkg.json` + 入口 + `icon.svg` + 随便什么文件）—— 就是插件那种多文件结构，
      所以技能和插件能互相搬。
    """
    return user_data() / "state" / "skill"


#: 出厂样例（"照它抄"的样板）住在 `:skill` 插件自带的 `seed/` 里：`<这里>/shot/`。
#: ★ `V-288`（你 2026-10-05 定的）：**不再往数据目录自动播种** —— 原来有个 `ensure_seed()`
#:   每次列技能都把缺的样例补回去（于是界面里删掉它、下次刷新又冒出来），界面上还有一颗
#:   「补回出厂样例」按钮、命令行还有 `moss :skill seed`；**这几个都已删除**（`V-289`）。
#:   想要样例就自己复制一份成 `user_data/state/skill/<名字>/` —— 这个常量只是告诉你样板在哪。
SEED_DIR = HOME / "system" / "pkgs" / "skill" / "seed"

#: 预制技能（随发行版一起打包、出厂即可用、无需用户允许）：`system/pkgs/skill/builtin/<id>/`。
#: 用户 `user_data/state/skill/<id>/` 里的同名技能会覆盖它（`roots()` 先 system 后 user）。
BUILTIN_DIR = HOME / "system" / "pkgs" / "skill" / "builtin"


def roots():
    """技能扫描根：system 预制技能 + user_data 用户技能（同名 user 覆盖 system）。

    技能和插件仍然不混：这里没有插件根，插件走 run_moss 的包调用那条路。
    """
    return [(BUILTIN_DIR, "system", "skill"),
            (skill_dir(), "user", "skill")]


def allow_path():
    """你的授权记在这儿（**不在技能目录里，也不在 state/skill 下**）。

    ★ 这是那道闸的地基：AI 能写技能本体（要让它自己造），所以授权表**必须**在它的可写范围
      之外 —— 否则它随手改一下这个文件就给自己发了通行证。
    """
    return user_data() / "ai" / "skills_allow.json"


def stats_path():
    """**调用统计**（每只被调了几次 + 最近一次调用时间）住这儿。

    ★ 为什么放在 `user_data/ai/`（跟授权表同一层）、而不是技能目录里：技能目录里的东西
      是"这个技能有哪些文件"的证据（详情页的文件清单就列它）—— 统计文件混进去会污染它；
      而且技能目录是 AI 写得到的地方，统计该跟授权一样待在外面。
    """
    return user_data() / "ai" / "skill_stats.json"


# ------------------------------------------------------------------ 运行方式（照 runners.json）
_RUNNERS = {"t": 0.0, "got": None}


def runners():
    """`system/runners.json` —— **跟插件同一张表**：技能的入口怎么跑由它说了算。"""
    now = time.time()
    if _RUNNERS["got"] is not None and now - _RUNNERS["t"] < 30:
        return _RUNNERS["got"]
    try:
        got = json.loads((HOME / "system" / "runners.json").read_text(encoding="utf-8"))
        got = {k: v for k, v in got.items() if not k.startswith("_")}
    except Exception:                                                  # noqa: BLE001
        got = {}
    _RUNNERS.update({"t": now, "got": got})
    return got


def _resolve_interp(tpl):
    if tpl.startswith("PATH:"):
        return shutil.which(tpl[5:]) or ""
    return tpl if Path(tpl).is_file() else ""


def _ver_key(name):
    return [int(x) for x in re.findall(r"\d+", str(name))] or [0]


def runtime_dir(family):
    """`{runtime}` 该指哪儿 = `<runtimes>/<家族>/<版本>/`（**用户层优先**）。

    ★ 为什么不能直接拼 `<runtimes>/python`：那里没有 `python.exe` —— 真的解释器在
      `<runtimes>/python/3.12/python.exe`。**第一版就是这么写错的**：`{runtime}\\python.exe`
      不存在 ⇒ 顺着模板退到 `PATH:python` ⇒ 拿**系统的 Python 3.13** 去跑技能
      （技能是给自带运行时写的：依赖都在那边、行为才一致）。
      规矩跟 core 的 `runners.runtime_dir()` 对齐：先看 `runtimes/default.json` 钉的版本，
      没钉就取版本号最大的那个。
    """
    fam = str(family or "")
    if not fam:
        return ""
    cands = []
    for _layer, base in (("user", user_data() / "runtimes"),
                         ("system", HOME / "system" / "runtimes")):
        d = base / fam
        if not d.is_dir():
            continue
        try:
            for v in sorted(d.iterdir()):
                if v.is_dir():
                    cands.append((v.name, v))
        except OSError:
            continue
    if not cands:
        return ""
    pinned = ""
    for f in (user_data() / "runtimes" / "default.json",
              HOME / "system" / "runtimes" / "default.json"):
        try:
            pinned = str(json.loads(f.read_text(encoding="utf-8")).get(fam) or "")
        except Exception:                                              # noqa: BLE001
            pinned = ""
        if pinned:
            break
    if pinned:
        for name, p in cands:
            if name == pinned:
                return str(p)
    return str(sorted(cands, key=lambda t: _ver_key(t[0]))[-1][1])


def _is_bundled(p):
    try:
        return str(p).lower().startswith(str(HOME / "system" / "runtimes").lower())
    except Exception:                                                  # noqa: BLE001
        return False


def runner_argv(pkg, pdir):
    """按 runner 表拼出启动命令（**跟插件走同一套规则**，含自带运行时的 bootstrap 垫片）。

    回 `(argv, 原因)` —— 拼不出来时第二个是一句人话。
    """
    rname = str((pkg or {}).get("runner") or "python")
    spec = runners().get(rname)
    if not spec:
        return [], "认不出 runner「%s」（system/runners.json 里没有这一门）" % rname
    if spec.get("builtin") == "openHtml":
        return [], "runner「html」是「用浏览器打开一个页面」，当不了 AI 的手"
    entry = str(((pkg or {}).get("entry") or {}).get("file") or "").strip()
    if not entry:
        return [], "pkg.json 里没写 entry.file（插件契约里有这一项）"
    f = pdir / entry
    if not f.is_file():
        return [], "入口文件不在：%s" % entry
    ctx = {"entry": str(f), "home": str(HOME), "cwd": str(pdir),
           "runtime": runtime_dir(spec.get("runtime"))}
    cands = spec.get("interpreters")
    if isinstance(cands, dict):
        cands = cands.get("package") or []
    interp = ""
    for tpl in (cands or []):
        try:
            interp = _resolve_interp(str(tpl).format(**ctx))
        except Exception:                                              # noqa: BLE001
            interp = ""
        if interp:
            break
    if cands and not interp:
        return [], "找不到解释器（%s）—— 这门 runner 跑不起来" % "、".join(str(c) for c in cands)
    ctx["interpreter"] = interp or ""
    rt = spec.get("runTarget")
    if isinstance(rt, dict):
        if any((pdir / str(m)).exists() for m in (rt.get("packageIf") or [])):
            ctx["runTarget"] = str(rt.get("package") or ".")
        else:
            ctx["runTarget"] = str(rt.get("default") or "{entry}").format(**ctx)
    else:
        ctx["runTarget"] = ctx["entry"]
    shim = spec.get("shim") or {}
    tpls = (shim.get("launch") if (shim and _is_bundled(interp)) else None) or spec.get("launch") or []
    if not tpls:
        return [], "runner「%s」没有可用的 launch 模板" % rname
    argv = []
    for t in tpls:
        try:
            argv.append(str(t).format(**ctx))
        except Exception:                                              # noqa: BLE001
            argv.append(str(t))
    return argv, ""


# ------------------------------------------------------------------ 指纹 / 授权
def _fp(blobs, sid):
    h = hashlib.sha1()
    h.update(str(sid).encode("utf-8"))
    for b in blobs:
        h.update(b"\0")
        h.update(b or b"")
    return h.hexdigest()[:16]


def allowed_map():
    try:
        got = json.loads(allow_path().read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except Exception:                                                  # noqa: BLE001
        return {}


def _save_allow(d):
    p = allow_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


# ------------------------------------------------------------------ 调用统计
def load_stats():
    """`{id: {"n": 次数, "at": "最近一次调用时间"}}`（读不出来就当空）。"""
    try:
        got = json.loads(stats_path().read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except Exception:                                                  # noqa: BLE001
        return {}


def _save_stats(d):
    p = stats_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def bump_stat(sid):
    """记一次调用：次数 +1、把"最近调用时间"写成现在。

    ★ 在 `run()` 真跑之前调它 —— **AI 调的、命令行调的、界面「运行测试」调的，都从 `run()`
      这一条路走**，所以一处埋点就全覆盖了（不管成没成功，只要真发起了就算一次）。
    """
    sid = str(sid or "").strip()
    if not sid:
        return
    d = load_stats()
    rec = d.get(sid) if isinstance(d.get(sid), dict) else {}
    rec["n"] = int(rec.get("n") or 0) + 1
    rec["at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    d[sid] = rec
    try:
        _save_stats(d)
    except OSError:
        pass


# ------------------------------------------------------------------ 运行日志（`V-301`）
def run_log_path():
    """技能**运行日志**：`user_data/ai/skill_runs.jsonl`（一行 = 一次运行）。

    ★ 放在技能目录**外面**（跟 stats / 授权表一层）：技能目录回答的是"这只技能有哪些文件"，
      运行日志不是它的文件。界面「运行日志面板」和"管理日志"都读这一份。
    """
    return user_data() / "ai" / "skill_runs.jsonl"


def _log_run(rec):
    """记一次运行（jsonl 追加）。日志是锦上添花 —— 坏了也不能影响这次调用。"""
    try:
        p = run_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:                                        # 别越攒越大：超 2MB 就裁到最近 400 行
            if p.stat().st_size > 2 * 1024 * 1024:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                p.write_text("\n".join(lines[-400:]) + "\n", encoding="utf-8")
        except OSError:
            pass
    except OSError:
        pass


def list_runs(sid=None, limit=50):
    """最近的运行记录（**新的在前**）。`sid` 给了就只看这只技能的。"""
    try:
        lines = run_log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    want = str(sid or "").strip()
    out = []
    for ln in reversed(lines):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(rec, dict):
            continue
        if want and str(rec.get("id") or "") != want:
            continue
        out.append(rec)
        if len(out) >= int(limit):
            break
    return out


def clear_runs(sid=None):
    """清运行日志：给了 `sid` 就只清它那几行，否则整个清空。回 `(ok, 说明)`。"""
    p = run_log_path()
    want = str(sid or "").strip()
    if not p.is_file():
        return True, "本来就没有日志"
    if not want:
        try:
            p.unlink()
            return True, "已清空运行日志"
        except OSError as e:
            return False, "删不掉：%s" % e
    try:
        keep = []
        for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                if str(json.loads(ln).get("id") or "") == want:
                    continue
            except ValueError:
                pass
            keep.append(ln)
        p.write_text(("\n".join(keep) + "\n") if keep else "", encoding="utf-8")
        return True, "已清掉「%s」的运行日志" % want
    except OSError as e:
        return False, "写不回去：%s" % e


# ------------------------------------------------------------------ 扫描
def _text(p):
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def clean_svg(svg):
    """洗一遍图标（`<script>` / `on*=` / `javascript:` 一律不要）。

    ★ 为什么必须洗：图标是**它自己写的文件**，而界面是把它 `innerHTML` 进去画的 ——
      不洗就等于让"技能"能往主界面里塞脚本。
    """
    s = str(svg or "")
    if _SVG_BAD.search(s):
        return ""                                  # 有脏东西就整个不用（退回默认图标）
    return s


def _i18n(v):
    """`name` / `desc` 在契约里是多语言的（`{"zh-CN": …}`），也可能直接给字符串。"""
    if isinstance(v, dict):
        return str(v.get("zh-CN") or v.get("en") or next(iter(v.values()), "") or "")
    return str(v or "")


def _stamp(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return ""


def _files_of(pdir):
    """这个技能目录里有什么（**跳过 `__pycache__` / `.pyc`** —— 那是跑出来的垃圾，不是它写的东西）。"""
    out = []
    try:
        for f in sorted(pdir.rglob("*")):
            if not f.is_file():
                continue
            rel = str(f.relative_to(pdir)).replace("\\", "/")
            if "__pycache__" in rel or rel.endswith((".pyc", ".pyo")):
                continue
            try:
                st = f.stat()
            except OSError:
                continue
            out.append({"rel": rel, "size": int(st.st_size), "mtime": _stamp(st.st_mtime)})
            if len(out) >= FILE_CAP:
                break
    except OSError:
        pass
    return out


def _load(d, layer, kind, stats_in=None):
    """读一只技能 / 一个可调用的插件 → 那一项（文件不全就带着 problems 回来）。"""
    sid = d.name
    stats = stats_in if stats_in is not None else load_stats()
    stat = stats.get(sid) if isinstance(stats.get(sid), dict) else {}
    probs, warns = [], []
    pj = d / "pkg.json"
    blank = {"id": sid, "name": sid, "layer": layer, "kind": kind, "dir": d,
             "pkg": {}, "desc": "", "why": "", "risk": "", "params": [], "entry": "",
             "timeout": TIMEOUT, "icon": None, "icon_svg": "", "files": _files_of(d),
             "created": "", "mtime": "", "allowed": False, "why_allow": "写坏了",
             "allowed_at": "", "fp": "", "argv": [], "run_err": "", "problems": [], "warns": [],
             "calls": int(stat.get("n") or 0), "last_called": str(stat.get("at") or "")}
    if not pj.is_file():
        blank["problems"] = ["缺 pkg.json —— 技能就是一个包，清单照插件契约写"
                             "（`spec(\"pkg.json\")`）"]
        return blank
    raw = pj.read_bytes()
    try:
        pkg = json.loads(raw.decode("utf-8", "replace"))
        pkg = pkg if isinstance(pkg, dict) else {}
    except ValueError as e:
        pkg = {}
        probs.append("pkg.json 读不出来（JSON 写坏了）：%s" % e)
    if kind == "skill" and not NAME_RE.match(sid):
        probs.append("技能 id 要**小写字母开头**、只允许小写字母/数字/`_`/`-`，最长 32 个字符"
                     "（现在是「%s」）" % sid)
    if str(pkg.get("id") or "") != sid:
        probs.append("pkg.json 里的 id（%s）和目录名（%s）不一样"
                     % (pkg.get("id") or "（空）", sid))
    if str(pkg.get("kind") or "") != "task":
        probs.append("技能的 kind 必须是 task（现在是「%s」）—— app 会开窗口，AI 的手不该开窗"
                     % (pkg.get("kind") or "（空）"))
    ai = pkg.get("ai") if isinstance(pkg.get("ai"), dict) else {}
    if kind == "skill" and not ai.get("expose"):
        warns.append("少了一句声明 `ai.expose: true`（技能目录里按规矩该有；现在它只是个声明，"
                     "不代表授权）")
    entry = str((pkg.get("entry") or {}).get("file") or "")
    argv, rerr = runner_argv(pkg, d)
    if rerr:
        probs.append(rerr)
    icon = d / "icon.svg"
    icon_svg = clean_svg(_text(icon)) if icon.is_file() else ""
    if not icon_svg:
        warns.append("没有 icon.svg（列表里用默认图标 —— 你希望它长什么样就画一个"
                     "；写了 `<script>` 之类的东西也会被当成没有）")
    if not _i18n(pkg.get("name")):
        probs.append("pkg.json 里没写 name（列表里就没名字了）")
    if not _i18n(pkg.get("desc")):
        warns.append("没写 desc（一句话说明它干什么用）")
    why = str(ai.get("why") or "").strip()
    if not why:
        warns.append("没写 `ai.why` —— 详情页要显示「当初为什么造它」，补一句")
    blobs = [raw]
    for extra in (entry, "icon.svg"):
        f = (d / extra) if extra else None
        blobs.append(f.read_bytes() if (f and f.is_file()) else b"")
    fp = _fp(blobs, sid)
    if layer == "system":
        allowed, why_allow = True, "出厂技能（AI 写不到这个根，随版本走）"
    else:
        rec = allowed_map().get(sid) or {}
        if rec.get("fp") and rec.get("fp") == fp:
            allowed, why_allow = True, "你已经允许过（%s）" % (rec.get("at") or "")
        elif rec:
            allowed, why_allow = False, "你允许之后它又改过 ⇒ 要重新允许"
        else:
            allowed, why_allow = False, "还没允许"
    try:
        st = d.stat()
        created, mtime = _stamp(st.st_ctime), _stamp(st.st_mtime)
    except OSError:
        created = mtime = ""
    out = dict(blank)
    out.update({"pkg": pkg, "desc": _i18n(pkg.get("desc")), "why": why,
                "risk": str(ai.get("risk") or ""), "params": list(pkg.get("params") or []),
                "entry": entry, "timeout": _clamp_timeout(ai.get("timeout")),
                "icon": icon if icon.is_file() else None, "icon_svg": icon_svg,
                "created": created, "mtime": mtime,
                "allowed": allowed, "why_allow": why_allow,
                "allowed_at": (allowed_map().get(sid) or {}).get("at") or "",
                "origin": (allowed_map().get(sid) or {}).get("from") or "",
                "fp": fp, "argv": argv, "run_err": rerr,
                "calls": int(stat.get("n") or 0), "last_called": str(stat.get("at") or ""),
                "problems": probs, "warns": warns})
    return out


def _clamp_timeout(t):
    try:
        t = int(t or 0)
    except (TypeError, ValueError):
        t = 0
    return max(5, min(TIMEOUT_MAX, t)) if t > 0 else TIMEOUT


def list_skills(roots_in=None):
    """`{id: 那一项}` —— **user 层同名盖 system 层**（跟包、跟技能一个规矩）。

    `roots_in` 只给探针用（造一组合成的根，别去动仓库里那两份出厂件）。
    """
    if roots_in is None:
        migrate_dashes()                     # `V-284`：老的 `--名字` 改成不带前缀（幂等）
    stats = load_stats()                     # 调用统计读一次，喂给每个 `_load`（别一个技能读一遍盘）
    out = {}
    for d, layer, kind in (roots_in if roots_in is not None else roots()):
        d = Path(d)
        if not d.is_dir():
            continue
        for sub in sorted(d.iterdir()):
            if not sub.is_dir():
                continue
            out[sub.name] = _load(sub, layer, kind, stats)
    return out


def usable(roots_in=None):
    """能进工具表：没毛病 + 已授权。"""
    out = {}
    for _sid, it in sorted(list_skills(roots_in).items()):
        if it["problems"] or not it["allowed"]:
            continue
        out.setdefault(it["name"], it)
    return out


def pending(roots_in=None):
    return {k: v for k, v in list_skills(roots_in).items()
            if not v["problems"] and not v["allowed"]}


def broken(roots_in=None):
    return {k: v for k, v in list_skills(roots_in).items() if v["problems"]}


def conflicts(roots_in=None):
    """**重名**（`--x` 和插件 `x` 都能用）—— 只留了先到的那只，另一只要报出来，别静默。"""
    seen, dup = {}, {}
    for sid, it in sorted(list_skills(roots_in).items()):
        if it["problems"] or not it["allowed"]:
            continue
        if it["name"] in seen:
            dup[sid] = {"id": sid, "name": it["name"], "kept": seen[it["name"]]["id"],
                        "dir": str(it["dir"])}
        else:
            seen[it["name"]] = it
    return dup


# ------------------------------------------------------------------ 给模型的两样
_SCHEMA_TYPE = {"int": "integer", "integer": "integer", "float": "number",
                "number": "number", "bool": "boolean", "boolean": "boolean"}


def specs_from(got):
    """`{名字: 那一项}` → 工具表里那几张（参数类型照 `pkg.json` 的 `params` 来）。"""
    rows = []
    for name in sorted(got or {}):
        it = got[name]
        props, req = {}, []
        for p in (it.get("params") or []):
            if not isinstance(p, dict) or not p.get("name"):
                continue
            props[str(p["name"])] = {
                "type": _SCHEMA_TYPE.get(str(p.get("type") or "string"), "string"),
                "description": _i18n(p.get("desc"))}
            if p.get("required"):
                req.append(str(p["name"]))
        rows.append({"type": "function", "function": {
            "name": name,
            "description": "%s（%s：%s）" % (it.get("desc") or it.get("name"),
                                           "插件" if it["kind"] == "pkg" else "技能", it.get("id")),
            "parameters": {"type": "object", "properties": props, "required": req}}})
    return rows


def specs(roots_in=None):
    return specs_from(usable(roots_in))


def note(got=None):
    """系统提示里那段"你已经有哪些技能"（一只都没有就一个字都不加）。"""
    got = usable() if got is None else got
    if not got:
        return ""
    rows = ["【我自己的技能】这些是**已经允许我用**的（工具表里就在，直接调）："]
    for name in sorted(got):
        it = got[name]
        ps = "、".join(str(p.get("name")) for p in (it.get("params") or [])
                       if isinstance(p, dict) and p.get("name"))
        rows.append("  · %s(%s) —— %s" % (name, ps or "无参数",
                                          it.get("desc") or it.get("why") or ""))
    rows.append("  · 缺什么能力：先 `skill(\"self-tool\")` 看怎么写，然后照**插件契约**把一个包写到 "
                "`%s/<名字>/`（id 小写字母开头、kind=task、带 icon.svg 和 `ai.why`）。"
                "写完**要用户点一次「允许」**，下一次跑才生效。" % skill_dir())
    return "\n".join(rows)


# ------------------------------------------------------------------ 跑一只技能
def _env(args, sid):
    keep = {"MOSS_HOME", "MOSS_USER_DATA_DIR", "MOSS_UI_DATA"}
    env = {k: v for k, v in os.environ.items()
           if not (k.startswith("MOSS_") and k not in keep)}
    env["MOSS_TOOL_NAME"] = str(sid)
    env["MOSS_TOOL_ARGS"] = json.dumps(args or {}, ensure_ascii=False)
    env["MOSS_PKG_ID"] = str(sid)
    env["MOSS_PKG_PARAMS"] = json.dumps(args or {}, ensure_ascii=False)
    env["MOSS_PLUGIN_DATA_DIR"] = str(user_data() / "state" / str(sid))
    env["MOSS_VIA"] = "ai"
    env["MOSS_ARGS"] = " ".join("%s=%s" % (k, v) for k, v in (args or {}).items())
    env.setdefault("PYTHONIOENCODING", "utf-8")
    # ★ `V-302`：**不缓冲输出** —— 交互式运行时（界面「运行测试」）输出是**流式**读的，
    #   子进程要是把 stdout 攒在缓冲区里，界面就一直"正在跑却什么都没有"（要等进程结束才吐）。
    env.setdefault("PYTHONUNBUFFERED", "1")
    return env


def tail(text, lines=TAIL_LINES, chars=TAIL_CHARS):
    s = str(text or "")
    if not s.strip():
        return "（没有输出）"
    ls = s.splitlines()
    cut = len(ls) > lines
    if cut:
        s = "\n".join(ls[-lines:])
    if len(s) > chars:
        s = s[-chars:]
    return ("……（前面还有 %d 行，已省略）\n" % (len(ls) - lines) if cut else "") + s


def run(name, args, roots_in=None, _detail=False):
    """真跑一只技能。默认回一段**给模型看**的文本（跟 `run_moss` 一个口径）；
    `_detail=True` 时回**结构化** dict（给界面「运行测试」用）。

    ★ 不论谁调（AI / 命令行 / 界面）都从这条路过 ⇒ 都在这里**记一条运行日志**。
    """
    want = str(name or "").strip()

    def _ret(text, ok=True, **kw):
        if not _detail:
            return text
        d = {"ok": bool(ok), "text": text, "id": str(kw.pop("id", want))}
        d.update(kw)
        return d

    got = usable(roots_in).get(want)
    if not got:
        hit = None
        for it in list_skills(roots_in).values():
            if it["id"] == want or it["name"] == want:
                hit = it
                break
        if hit and hit["problems"]:
            return _ret("[写坏了] 技能「%s」进不了工具表：%s" % (hit["id"], "；".join(hit["problems"])),
                        ok=False, id=hit["id"])
        if hit:
            return _ret("[没允许] 技能「%s」你造出来了、也写进盘了，但**用户还没点「允许」**"
                        "（%s）—— 这一次跑用不了。先干别的，或者跟用户说一声。"
                        % (hit["id"], hit["why_allow"]), ok=False, id=hit["id"])
        return _ret("[错误] 没有这个技能：%s（现在能用的：%s）"
                    % (want, "、".join(sorted(usable(roots_in))) or "（一只都没有）"), ok=False)
    argv = list(got.get("argv") or [])
    if not argv:
        return _ret("[跑不起来] %s" % (got.get("run_err") or "拼不出启动命令"),
                    ok=False, id=got["id"])
    cmd = argv + [str(v) for v in (args or {}).values() if isinstance(v, str) and v]
    bump_stat(got["id"])                    # 记一次调用（次数 +1 + 最近调用时间）
    at = time.strftime("%Y-%m-%d %H:%M:%S")
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, input=json.dumps(args or {}, ensure_ascii=False),
            cwd=str(got["dir"]), env=_env(args, got["id"]),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=int(got.get("timeout") or TIMEOUT),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        dur = round(time.time() - t0, 3)
        _log_run({"id": got["id"], "name": got.get("name") or "", "at": at, "args": args,
                  "code": None, "out": "", "err": "超时", "dur": dur, "cmd": cmd, "ok": False})
        return _ret("[超时] 技能「%s」跑了 %s 秒还没回 —— 被杀了。"
                    "（要更长就在 pkg.json 的 `ai.timeout` 里写，最多 %d 秒。）"
                    % (got["id"], got.get("timeout"), TIMEOUT_MAX),
                    ok=False, id=got["id"], code=None, out="", err="超时",
                    dur=dur, at=at, cmd=cmd, cwd=str(got["dir"]))
    except OSError as e:
        dur = round(time.time() - t0, 3)
        _log_run({"id": got["id"], "name": got.get("name") or "", "at": at, "args": args,
                  "code": None, "out": "", "err": str(e), "dur": dur, "cmd": cmd, "ok": False})
        return _ret("[跑不起来] %s\n  命令 = %r\n  目录 = %r" % (e, cmd, str(got["dir"])),
                    ok=False, id=got["id"], code=None, out="", err=str(e),
                    dur=dur, at=at, cmd=cmd, cwd=str(got["dir"]))
    out = (p.stdout or "").strip()
    err = (p.stderr or "").strip()
    dur = round(time.time() - t0, 3)
    _log_run({"id": got["id"], "name": got.get("name") or "", "at": at, "args": args,
              "code": p.returncode, "out": tail(out), "err": tail(err),
              "dur": dur, "cmd": cmd, "ok": p.returncode == 0})
    head = "技能「%s」退出码 %d" % (got["id"], p.returncode)
    if err:
        head += "\n[stderr]\n" + tail(err)
    return _ret(head + "\n" + tail(out), ok=(p.returncode == 0), id=got["id"],
                name=got.get("name") or "", code=p.returncode, out=out, err=err,
                dur=dur, at=at, cmd=cmd, cwd=str(got["dir"]))


def run_detail(name, args, roots_in=None):
    """给界面用的**结构化**运行结果（同时记一条运行日志）。"""
    return run(name, args, roots_in, _detail=True)


# ------------------------------------------------------------------ 设置里那几个动作
def allow(sid, yes=True, roots_in=None):
    """允许 / 撤销。**只对 user 层有意义**（出厂技能本来就允许）。"""
    got = list_skills(roots_in).get(str(sid or "").strip())
    if not got:
        return {"ok": False, "msg": "没有这只技能：%s" % sid}
    if got["layer"] == "system":
        return {"ok": False, "msg": "「%s」是出厂技能 —— 本来就能用，不用批准，也不该在这儿改。"
                                    % got["id"]}
    if got["problems"]:
        return {"ok": False, "msg": "先把它变成能跑的包再允许：%s" % "；".join(got["problems"])}
    d = allowed_map()
    if yes:
        d[got["id"]] = {"fp": got["fp"], "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    else:
        d.pop(got["id"], None)
    _save_allow(d)
    return {"ok": True, "id": got["id"], "allowed": bool(yes),
            "msg": ("允许了：%s —— 它**下一次**跑就能用（工具表是开工那一刻定的）" % got["id"])
                   if yes else ("撤销了：%s —— 它还留在盘上，但进不了工具表" % got["id"])}


def rm(sid, confirm=False, roots_in=None):
    """删掉一只**它自己造的技能**。

    出厂件删不得（哪怕带了 confirm）；**插件行也不许从这儿删** —— 技能这一层只管
    `user_data/state/skill/` 里那些；一个插件的去留是 `moss --remove`（宿主那套确认流程）的事。
    （这一条是排查"一只出厂包怎么从技能层被删掉"时顺手加的闸：不给技能层留"删到插件"的口子。）
    """
    got = list_skills(roots_in).get(str(sid or "").strip())
    if not got:
        return {"ok": False, "msg": "没有这只技能：%s" % sid}
    if got["kind"] != "skill":
        return {"ok": False, "msg": "「%s」是个**插件**（%s）—— 卸插件请用 `moss --remove %s`，"
                                    "技能这一层不删插件。" % (got["id"], got["dir"], got["id"])}
    if got["layer"] == "system":
        return {"ok": False, "msg": "「%s」是出厂技能，删不得（它是发行版的一部分）。"
                                    "要改就改仓库里那份。" % got["id"]}
    if not confirm:
        return {"ok": False, "need_confirm": True,
                "msg": "删掉技能「%s」？它的目录 %s（%d 个文件）会一起没。"
                       % (got["id"], got["dir"], len(got.get("files") or []))}
    try:
        shutil.rmtree(str(got["dir"]))
    except OSError as e:
        return {"ok": False, "msg": "删不掉：%s" % e}
    d = allowed_map()
    d.pop(got["id"], None)
    _save_allow(d)
    return {"ok": True, "id": got["id"], "msg": "删掉了：%s" % got["id"]}


def read(sid, limit=20000, roots_in=None):
    """看一眼它写了什么（详情页那个「文件内容」用它）。"""
    got = list_skills(roots_in).get(str(sid or "").strip())
    if not got:
        return {"ok": False, "msg": "没有这只技能：%s" % sid}
    out = {}
    for f in (got.get("files") or [])[:20]:
        p = Path(got["dir"]) / f["rel"]
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            out[f["rel"]] = "（读不出来：%s）" % e
            continue
        out[f["rel"]] = t[:limit] + ("\n……（截到 %d 字）" % limit if len(t) > limit else "")
    return {"ok": True, "id": got["id"], "name": got["name"], "dir": str(got["dir"]),
            "allowed": got["allowed"], "why_allow": got["why_allow"],
            "problems": got["problems"], "files": got.get("files") or [], "text": out}


# ------------------------------------------------------------------ 转成插件
def _taken_ids():
    """两层 pkgs 里已经占掉的 id / 目录名 / 别名。

    ★ 注意是 `roots()[1:]`（**两个 pkgs 根**）—— 第一版写的是 `roots()[2:]`，
      那时候根表里有四个；根表缩成三个之后，这一刀正好把 `system/pkgs` 切掉了 ⇒
      `--md5` 转插件时不报冲突（而 `md5` 明明已经占了）。探针当场抓住。
    """
    out = {}
    # ★ 根表里已经没有插件了（`V-284`）—— 转插件要查的是**两个 pkgs 根**，直接扫
    for d in (HOME / "system" / "pkgs", user_data() / "pkgs"):
        d = Path(d)
        if not d.is_dir():
            continue
        for sub in sorted(d.iterdir()):
            if not sub.is_dir():
                continue
            out.setdefault(sub.name.lower(), str(sub))
            try:
                pkg = json.loads((sub / "pkg.json").read_text(encoding="utf-8"))
            except Exception:                                          # noqa: BLE001
                continue
            for k in [pkg.get("id")] + list(pkg.get("aliases") or []):
                if k:
                    out.setdefault(str(k).lower(), str(sub))
    return out


def promote_plan(sid, new_id="", roots_in=None, builtin=()):
    """**只算不改**：把技能转成插件要做哪些事、id 会不会撞（设置里那个按钮先弹这个）。"""
    got = list_skills(roots_in).get(str(sid or "").strip())
    if not got:
        return {"ok": False, "msg": "没有这只技能：%s" % sid}
    if got["kind"] != "skill":
        return {"ok": False, "msg": "「%s」本来就是插件了（%s）" % (got["id"], got["dir"])}
    if got["layer"] == "system":
        return {"ok": False, "msg": "「%s」是出厂技能 —— 转成插件要动发行版那份，得人来。"
                                    % got["id"]}
    want = str(new_id or got["id"].lstrip("-")).strip().lower()
    problems = []
    if not NAME_RE.match(want):
        problems.append("插件 id 要用**小写字母开头**、只允许小写字母/数字/`_`/`-`，最长 32 个字符"
                        "（现在是「%s」）" % want)
    taken = _taken_ids()
    if want in taken:
        problems.append("插件 id「%s」已经被占了（%s）—— **你自己想一个新的**"
                        % (want, taken[want]))
    if want in set(builtin or ()):
        problems.append("「%s」和内置工具撞名了，换一个" % want)
    return {"ok": True, "id": got["id"], "new_id": want, "problems": problems,
            "can": not problems, "dir_from": str(got["dir"]),
            "dir_to": str((user_data() / "pkgs") / want),
            "files": len(got.get("files") or []), "why": got.get("why") or "",
            "desc": got.get("desc") or ""}


def promote(sid, confirm=False, new_id="", roots_in=None, builtin=()):
    """真转：搬目录 + 把 `pkg.json` 的 id 改成新名字（插件那边 id 必须 = 目录名）。

    ★ 转成插件之后它就是"用户的插件"了：AI 想用走 `run_moss(":新id …")`（那条路一直都在），
      所以这边**不留**技能那套授权记录（留着反而是个说不清的影子）。
    """
    plan = promote_plan(sid, new_id, roots_in, builtin)
    if not plan.get("ok"):
        return plan
    if not confirm:
        return {"ok": False, "need_confirm": True, "plan": plan,
                "msg": "转成插件是不可逆的一步（包会出现在插件列表里）：先确认"}
    if plan["problems"]:
        return {"ok": False, "msg": "；".join(plan["problems"]), "plan": plan}
    src, dst = Path(plan["dir_from"]), Path(plan["dir_to"])
    if dst.exists():
        return {"ok": False, "msg": "目标目录已经在了：%s" % dst}
    try:
        shutil.move(str(src), str(dst))
    except OSError as e:
        return {"ok": False, "msg": "搬不动：%s" % e}
    try:
        pj = dst / "pkg.json"
        pkg = json.loads(pj.read_text(encoding="utf-8"))
        pkg["id"] = plan["new_id"]
        pkg["aliases"] = [a for a in (pkg.get("aliases") or []) if str(a) != plan["id"]]
        ai = pkg.get("ai") if isinstance(pkg.get("ai"), dict) else {}
        ai["expose"] = True
        ai.setdefault("why", plan.get("why") or "")
        pkg["ai"] = ai
        pj.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as e:                                             # noqa: BLE001
        return {"ok": False,
                "msg": "包搬过去了，但 pkg.json 没改好：%s: %s" % (type(e).__name__, e)}
    d = allowed_map()
    d.pop(plan["id"], None)                    # 它已经不是技能了，把授权记录收掉
    _save_allow(d)
    return {"ok": True, "id": plan["id"], "new_id": plan["new_id"], "dir": str(dst),
            "msg": "转成插件了：%s —— 插件列表里现在能看到它（id「%s」）"
                   % (dst.name, plan["new_id"])}


# ------------------------------------------------------------------ `:skill` 那一页的数据
def _row(it, with_files=False):
    row = {"id": it["id"], "name": it["name"], "layer": it["layer"], "kind": it["kind"],
           "dir": str(it["dir"]), "desc": it.get("desc") or "", "why": it.get("why") or "",
           "risk": it.get("risk") or "", "allowed": it["allowed"], "why_allow": it["why_allow"],
           "params": [str(p.get("name")) for p in (it.get("params") or [])
                      if isinstance(p, dict) and p.get("name")],
           "entry": it.get("entry") or "", "timeout": it.get("timeout"),
           "icon_svg": it.get("icon_svg") or "",
           "origin": it.get("origin") or "",
           "created": it.get("created") or "", "mtime": it.get("mtime") or "",
           "calls": int(it.get("calls") or 0), "last_called": it.get("last_called") or "",
           "allowed_at": it.get("allowed_at") or "",
           "problems": list(it.get("problems") or []), "warns": list(it.get("warns") or []),
           "files_n": len(it.get("files") or [])}
    if with_files:
        row["files"] = it.get("files") or []
    return row


def migrate_dashes():
    """`V-284`：把早期带 `--` 前缀的技能目录**改名成不带前缀的**（只做一次，之后无操作）。

    为什么还要这一步：`--` 是上一轮加的，你这次说「不需要再添加 -- 了」—— 那已经存在的
    `--shot` 就得跟着改，不然界面上会留着一只"名字带两个短横"的怪东西。顺手把
    `pkg.json` 里的 `id` 和授权记录里的键一起搬过来（**不重算指纹**：文件内容没变，
    只是名字变了；指纹里含名字，所以这里按新名字重算一次）。
    """
    moved = []
    root = skill_dir()
    if not root.is_dir():
        return moved
    d = allowed_map()
    changed = False
    for sub in sorted(root.iterdir()):
        if not (sub.is_dir() and sub.name.startswith("--")):
            continue
        want = sub.name.lstrip("-")
        dst = root / want
        if not NAME_RE.match(want) or dst.exists():
            continue                       # 新名字不合法 / 已经有一个同名的：留着别动（下面会点名）
        try:
            sub.rename(dst)
        except OSError:
            continue
        try:
            pj = dst / "pkg.json"
            pkg = json.loads(pj.read_text(encoding="utf-8"))
            pkg["id"] = want
            pkg["aliases"] = [a for a in (pkg.get("aliases") or []) if str(a) != sub.name]
            pj.write_text(json.dumps(pkg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except Exception:                                              # noqa: BLE001
            pass
        rec = d.pop(sub.name, None)
        got = _load(dst, "user", "skill")
        if rec:
            rec["fp"] = got.get("fp") or ""
            d[want] = rec
            changed = True
        moved.append(sub.name + " → " + want)
    if changed:
        _save_allow(d)
    return moved


def doc(sid, roots_in=None):
    """这只技能**自己的说明书**（`AGENT.md`；没有就退回 `pkg.json` + 文件清单）。

    ★ 为什么要有它：AI 得能"看说明"才知道这东西怎么用 —— 命令行里就是
      `moss :skill doc <名字>`（你 2026-10-05 问的"有没有什么功能是查看某个插件的
      `AGENT.md` 内容的"）。人这边是详情页那颗「看说明」。
    """
    got = list_skills(roots_in).get(str(sid or "").strip())
    if not got:
        return {"ok": False, "msg": "没有这只技能：%s" % sid}
    d = Path(got["dir"])
    text = ""
    for name in ("AGENT.md", "README.md"):
        if (d / name).is_file():
            try:
                text = (d / name).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            if text:
                break
    if not text:
        files = "\n".join("  · %s（%d 字节）" % (f["rel"], f["size"])
                          for f in (got.get("files") or [])) or "  （空目录）"
        text = ("（这只技能里没有 AGENT.md —— 下面把清单和文件列出来）\n\n"
                "id      : %s\n它干什么: %s\n为什么造: %s\n参数    : %s\n入口    : %s\n文件:\n%s"
                % (got["id"], got.get("desc") or "（没写）", got.get("why") or "（没写）",
                   "、".join(str(p.get("name")) for p in (got.get("params") or [])
                             if isinstance(p, dict)) or "无",
                   got.get("entry") or "—", files))
    return {"ok": True, "id": got["id"], "name": got["name"], "dir": str(d), "text": text,
            "has_agent_md": (d / "AGENT.md").is_file()}


def rev():
    """技能状态的小指纹（`ai_poll` 每 700ms 拿它判断要不要重读界面那一行）。

    ★ 修用户报的：AI 先造技能、用户点允许，然后 AI 又改了它 —— 授权按指纹自动作废，
      宿主盘上的状态已经是"待批准"，但 AI 页那行还写着"已允许"（界面没重读）。
      指纹把每只技能的 `fp + allowed + why_allow` 都算进去，改一个字就变。
    """
    h = hashlib.sha1()
    try:
        for sid, it in sorted(list_skills().items()):
            h.update(str(sid).encode("utf-8", "replace"))
            h.update(b"\0")
            h.update(str(it.get("fp") or "").encode("utf-8", "replace"))
            h.update(b"\0")
            h.update(b"1" if it.get("allowed") else b"0")
            h.update(str(it.get("why_allow") or "").encode("utf-8", "replace"))
            h.update(b"\0")
    except Exception:                                                    # noqa: BLE001
        pass
    try:
        ap = allow_path()
        if ap.is_file():
            st = ap.stat()
            h.update(str(st.st_mtime_ns).encode("ascii", "replace"))
            h.update(str(st.st_size).encode("ascii", "replace"))
    except Exception:                                                    # noqa: BLE001
        pass
    return h.hexdigest()[:16]


def summary():
    """`:skill` 那一页要的全部数据（图标墙 + 详情都在里面；宿主 AI 页那一行也用它）。

    ★ `V-284`：**只有技能**（`skills`）—— 插件不出现在这儿（你说的"插件的东西不能放在技能这里"）。
      `broken` 还是那堆"写坏了、进不了工具表"的技能（界面上要能看见它们）。
    """
    got = list_skills()
    dup = conflicts()
    rows = [_row(v, with_files=True) for _k, v in sorted(got.items())]
    for r in rows:
        if r["id"] in dup:
            r["problems"] = list(r["problems"]) + [
                "重名：模型那边「%s」这个名字已经被 %s 用了 ⇒ 它进不了工具表"
                % (r["name"], dup[r["id"]]["kept"])]
    return {"ok": True,
            "skills": [r for r in rows if r["kind"] == "skill"],
            "broken": [r for r in rows if r["problems"]],
            "dirs": {"mine": str(skill_dir())},
            "allow_file": str(allow_path()),
            "n_usable": len(usable()), "n_pending": len(pending())}
