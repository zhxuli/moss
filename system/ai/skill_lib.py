import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_SVG_BAD = re.compile(r"(<\s*script|<\s*foreignObject|<\s*iframe|<\s*use\b|on[a-z]+\s*=|javascript:)",
                      re.I)

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

def _home():
    env = (os.environ.get("MOSS_HOME") or "").strip()
    return Path(env) if env else HERE.parents[1]

HOME = _home()

def user_data():
    env = (os.environ.get("MOSS_USER_DATA_DIR") or "").strip()
    return Path(env) if env else (HOME / "user_data")

NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

TIMEOUT = 60
TIMEOUT_MAX = 300
TAIL_LINES = 60
TAIL_CHARS = 4000
FILE_CAP = 200

def skill_dir():
    return user_data() / "state" / "skill"

SEED_DIR = HOME / "system" / "pkgs" / "skill" / "seed"

BUILTIN_DIR = HOME / "system" / "pkgs" / "skill" / "builtin"

def roots():
    return [(BUILTIN_DIR, "system", "skill"),
            (skill_dir(), "user", "skill")]

def allow_path():
    return user_data() / "ai" / "skills_allow.json"

def _pkg_id(workdir=""):
    try:
        p = Path(str(workdir or "")).resolve()
    except (OSError, ValueError):
        return ""
    for root in (user_data() / "pkgs", HOME / "system" / "pkgs"):
        try:
            rel = p.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        if not rel.parts:
            continue
        name = rel.parts[0]
        pid = name
        try:
            man = root / name / "pkg.json"
            if man.is_file():
                got = json.loads(man.read_text(encoding="utf-8"))
                cand = str((got or {}).get("id") or "").strip()
                if cand:
                    pid = cand
        except Exception:
            pass
        return pid
    return ""

def _mode_path(workdir=""):
    pid = _pkg_id(workdir)
    if pid:
        return user_data() / "state" / pid / "ai" / "mode.json"
    return user_data() / "ai" / "mode.json"

def full_access(workdir=""):
    try:
        raw = json.loads(_mode_path(workdir).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return False
        if "full_access" in raw:
            return bool(raw.get("full_access"))
        for it in (raw.get("allow") or []):
            if (isinstance(it, dict) and str(it.get("path") or "") == "*"
                    and it.get("write") and "完全权限" in str(it.get("why") or "")):
                return True
    except Exception:
        pass
    return False

def stats_path():
    return user_data() / "ai" / "skill_stats.json"

_RUNNERS = {"t": 0.0, "got": None}

def runners():
    now = time.time()
    if _RUNNERS["got"] is not None and now - _RUNNERS["t"] < 30:
        return _RUNNERS["got"]
    try:
        got = json.loads((HOME / "system" / "runners.json").read_text(encoding="utf-8"))
        got = {k: v for k, v in got.items() if not k.startswith("_")}
    except Exception:
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
        except Exception:
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
    except Exception:
        return False

def runner_argv(pkg, pdir):
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
        except Exception:
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
        except Exception:
            argv.append(str(t))
    return argv, ""

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
    except Exception:
        return {}

def _save_allow(d):
    p = allow_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

def load_stats():
    try:
        got = json.loads(stats_path().read_text(encoding="utf-8"))
        return got if isinstance(got, dict) else {}
    except Exception:
        return {}

def _save_stats(d):
    p = stats_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")

def bump_stat(sid):
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

def run_log_path():
    return user_data() / "ai" / "skill_runs.jsonl"

def _log_run(rec):
    try:
        p = run_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        try:
            if p.stat().st_size > 2 * 1024 * 1024:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                p.write_text("\n".join(lines[-400:]) + "\n", encoding="utf-8")
        except OSError:
            pass
    except OSError:
        pass

def list_runs(sid=None, limit=50):
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

def _text(p):
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

def clean_svg(svg):
    s = str(svg or "")
    if _SVG_BAD.search(s):
        return ""
    return s

def _i18n(v):
    if isinstance(v, dict):
        return str(v.get("zh-CN") or v.get("en") or next(iter(v.values()), "") or "")
    return str(v or "")

def _stamp(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError):
        return ""

def _files_of(pdir):
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

def _load(d, layer, kind, stats_in=None, workdir=""):
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
    elif full_access(workdir):
        allowed, why_allow = True, "完全权限：自动批准（新建 / 修改也照此）"
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

def list_skills(roots_in=None, workdir=""):
    if roots_in is None:
        migrate_dashes()
    stats = load_stats()
    out = {}
    for d, layer, kind in (roots_in if roots_in is not None else roots()):
        d = Path(d)
        if not d.is_dir():
            continue
        for sub in sorted(d.iterdir()):
            if not sub.is_dir():
                continue
            out[sub.name] = _load(sub, layer, kind, stats, workdir=workdir)
    return out

def usable(roots_in=None, workdir=""):
    out = {}
    for _sid, it in sorted(list_skills(roots_in, workdir=workdir).items()):
        if it["problems"] or not it["allowed"]:
            continue
        out.setdefault(it["name"], it)
    return out

def pending(roots_in=None, workdir=""):
    return {k: v for k, v in list_skills(roots_in, workdir=workdir).items()
            if not v["problems"] and not v["allowed"]}

def broken(roots_in=None, workdir=""):
    return {k: v for k, v in list_skills(roots_in, workdir=workdir).items() if v["problems"]}

def conflicts(roots_in=None, workdir=""):
    seen, dup = {}, {}
    for sid, it in sorted(list_skills(roots_in, workdir=workdir).items()):
        if it["problems"] or not it["allowed"]:
            continue
        if it["name"] in seen:
            dup[sid] = {"id": sid, "name": it["name"], "kept": seen[it["name"]]["id"],
                        "dir": str(it["dir"])}
        else:
            seen[it["name"]] = it
    return dup

_SCHEMA_TYPE = {"int": "integer", "integer": "integer", "float": "number",
                "number": "number", "bool": "boolean", "boolean": "boolean"}

def specs_from(got):
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

def specs(roots_in=None, workdir=""):
    return specs_from(usable(roots_in, workdir=workdir))

def note(got=None, workdir=""):
    got = usable(workdir=workdir) if got is None else got
    if not got:
        return ""
    rows = ["【我自己的技能】这些是**已经允许我用**的（工具表里就在，直接调）："]
    for name in sorted(got):
        it = got[name]
        ps = "、".join(str(p.get("name")) for p in (it.get("params") or [])
                       if isinstance(p, dict) and p.get("name"))
        rows.append("  · %s(%s) —— %s" % (name, ps or "无参数",
                                          it.get("desc") or it.get("why") or ""))
    if full_access(workdir):
        rows.append("  · 缺什么能力：先 `skill(\"self-tool\")` 看怎么写，然后照**插件契约**把一个包写到 "
                    "`%s/<名字>/`（id 小写字母开头、kind=task、带 icon.svg 和 `ai.why`）。"
                    "★ 当前是**完全权限**：新建 / 修改技能会自动视为已批准，**不要停下来等用户点「允许」**。"
                    "本次工具表仍是开工时定死的；要立即试跑就用 `run_moss(\":skill run <名字> …\")`。"
                    % skill_dir())
    else:
        rows.append("  · 缺什么能力：先 `skill(\"self-tool\")` 看怎么写，然后照**插件契约**把一个包写到 "
                    "`%s/<名字>/`（id 小写字母开头、kind=task、带 icon.svg 和 `ai.why`）。"
                    "写完**要用户点一次「允许」**，下一次跑才生效。" % skill_dir())
    return "\n".join(rows)

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
    bump_stat(got["id"])
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
    full = "技能「%s」退出码 %d" % (got["id"], p.returncode)
    if err:
        full += "\n[stderr]\n" + err
    full += "\n" + out
    return _ret(full, ok=(p.returncode == 0), id=got["id"],
                name=got.get("name") or "", code=p.returncode, out=out, err=err,
                dur=dur, at=at, cmd=cmd, cwd=str(got["dir"]))

def run_detail(name, args, roots_in=None):
    return run(name, args, roots_in, _detail=True)

def allow(sid, yes=True, roots_in=None):
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

def _taken_ids():
    out = {}
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
            except Exception:
                continue
            for k in [pkg.get("id")] + list(pkg.get("aliases") or []):
                if k:
                    out.setdefault(str(k).lower(), str(sub))
    return out

def promote_plan(sid, new_id="", roots_in=None, builtin=()):
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
    except Exception as e:
        return {"ok": False,
                "msg": "包搬过去了，但 pkg.json 没改好：%s: %s" % (type(e).__name__, e)}
    d = allowed_map()
    d.pop(plan["id"], None)
    _save_allow(d)
    return {"ok": True, "id": plan["id"], "new_id": plan["new_id"], "dir": str(dst),
            "msg": "转成插件了：%s —— 插件列表里现在能看到它（id「%s」）"
                   % (dst.name, plan["new_id"])}

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
            continue
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
        except Exception:
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
    except Exception:
        pass
    try:
        ap = allow_path()
        if ap.is_file():
            st = ap.stat()
            h.update(str(st.st_mtime_ns).encode("ascii", "replace"))
            h.update(str(st.st_size).encode("ascii", "replace"))
    except Exception:
        pass
    return h.hexdigest()[:16]

def summary():
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
