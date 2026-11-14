# -*- coding: utf-8 -*-
"""Pip 管理器 · 核心逻辑

管的是「moss 自带的那套 Python 运行时」里的第三方库 —— 具体哪一套由
``system/runtimes/default.json`` 里钉住的版本决定（用户层 ``user_data/runtimes``
存在就优先用它）。装东西一律装进那套运行时的 ``Lib/site-packages``。

只用标准库：这套代码本身就跑在它管的那个解释器里，不能假定它有 requests。
"""

import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
IS_WIN = os.name == "nt"

# 拿包详情用。第一个是官方；后面两个是「官方连不上时」的退路
JSON_URLS = (
    "https://pypi.org/pypi/%s/json",
    "https://mirrors.aliyun.com/pypi/web/json/%s",
    "https://pypi.tuna.tsinghua.edu.cn/pypi/%s/json",
)
WEB_SEARCH = "https://pypi.org/search/?q=%s"
UA = "moss-pip-manager/2.0"

# 卸载了它这套环境就废了
GUARD = {"pip"}

# ---------------------------------------------------------------- 路径

def data_dir():
    """宿主会注入 MOSS_PLUGIN_DATA_DIR；没有它时回落到 <moss>/user_data/state/<id>，
    **绝不**写进包目录（那会跟着重装一起丢）。"""
    v = os.environ.get("MOSS_PLUGIN_DATA_DIR")
    if v:
        d = Path(v)
    else:
        home = moss_home()
        d = (home / "user_data" / "state" / HERE.name) if home else (HERE / ".data")
    d.mkdir(parents=True, exist_ok=True)
    return d


def moss_home():
    v = os.environ.get("MOSS_HOME")
    if v:
        p = Path(v)
        if (p / "system" / "runtimes").is_dir():
            return p
    p = HERE
    for _ in range(8):
        if (p / "system" / "runtimes").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    return None


def _default_json(home):
    if not home:
        return {}
    try:
        return json.loads((home / "system" / "runtimes" / "default.json").read_text("utf-8"))
    except Exception:
        return {}


def _versions(home):
    """python 家族装了哪些版本（用户层在前，同名的只算一次）"""
    out = []
    if not home:
        return out
    for base in (home / "user_data" / "runtimes", home / "system" / "runtimes"):
        d = base / "python"
        if d.is_dir():
            for c in sorted(d.iterdir()):
                if c.is_dir() and c.name not in out:
                    out.append(c.name)
    return out


_RT = {"at": 0.0, "v": None}


def _own_runtime(force=False):
    """当前被管的那个运行时。带 5 秒缓存，界面一刷新就是好几次调用。"""
    if not force and _RT["v"] and time.time() - _RT["at"] < 5:
        return _RT["v"]

    home = moss_home()
    decl = _default_json(home)
    want = str(decl.get("python") or "").strip()
    versions = _versions(home)

    rdir = None
    ver = want
    for cand_ver in ([want] if want else []) + versions:
        for base in ((home / "user_data" / "runtimes") if home else (),
                     (home / "system" / "runtimes") if home else ()):
            c = base / "python" / cand_ver
            if c.is_dir():
                rdir, ver = c, cand_ver
                break
        if rdir:
            break

    py = None
    if rdir:
        for name in (("python.exe",) if IS_WIN else ("bin/python3", "bin/python", "python3")):
            c = rdir / name
            if c.exists():
                py = c
                break

    source = "system/runtimes"
    if py is None:
        py = Path(sys.executable)
        rdir = py.parent
        source = "当前进程的解释器（没找到自带运行时）"

    site = None
    for c in (rdir / "Lib" / "site-packages", rdir / "lib" / "site-packages",
              rdir / "Lib" / "site-packages"):
        if c.is_dir():
            site = c
            break
    if site is None:
        site = rdir / "Lib" / "site-packages"

    info = {
        "home": str(home) if home else "",
        "declared": want,
        "versions": versions,
        "version_dir": ver,
        "dir": str(rdir),
        "python": str(py),
        "site_packages": str(site),
        "source": source,
        "multi": len(versions) > 1,
    }
    _RT.update(at=time.time(), v=info)
    return info


# ---------------------------------------------------------------- 环境（可切换）
# 一份「用过哪些环境」的清单 + 当前选中的那个。自身那套永远在第一位（带星标），
# 别的虚拟环境是用户加进来的。切换只改「以后 pip 动哪一套」，不搬任何文件。

def _targets_file():
    return data_dir() / "targets.json"


def _detect_env(path):
    """从一个目录认出「这套 Python 在哪、包在哪」。
    认三种：venv（根目录有 pyvenv.cfg，解释器在 Scripts 或 bin）、
    Python 安装目录（python.exe 在根上）、以及直接拖进来的 python.exe。
    认不出就报错 —— 宁可不加，也别加进来一条问号。"""
    p = Path(str(path)).expanduser()
    if not p.exists():
        raise ValueError("这个路径不存在：%s" % p)
    p = p.resolve()
    if p.is_file():
        p = p.parent
    py = None
    for c in (p / "python.exe", p / "Scripts" / "python.exe",
              p / "bin" / "python3", p / "bin" / "python"):
        if c.is_file():
            py = c
            break
    if py is None:
        raise ValueError("这里没找到 python.exe：%s" % p)
    site = None
    for c in (p / "Lib" / "site-packages", p / "lib" / "site-packages"):
        if c.is_dir():
            site = c
            break
    if site is None:
        site = p / "Lib" / "site-packages"
    return {"path": str(p), "python": str(py), "site_packages": str(site)}


def target_list():
    """记住的环境（自身那套永远在，且永远第一）。清单读不出来就当只有自身那套。"""
    own_rt = _own_runtime()
    own = {"id": "own", "path": own_rt["dir"], "label": "moss 自带运行时",
           "own": True, "ok": True, "python": own_rt["python"],
           "site_packages": own_rt["site_packages"]}
    try:
        data = json.loads(_targets_file().read_text("utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    items = [own]
    seen = {os.path.normcase(os.path.abspath(own["path"]))}
    for it in (data.get("items") or []):
        raw = str(it.get("path") or "").strip()
        if not raw:
            continue
        try:
            key = os.path.normcase(os.path.abspath(raw))
        except Exception:
            key = raw
        if key in seen:
            continue
        seen.add(key)
        rec = {"id": str(it.get("id") or raw), "path": raw,
               "label": str(it.get("label") or Path(raw).name or raw),
               "own": False, "ok": True, "python": "", "site_packages": ""}
        try:
            got = _detect_env(raw)
            rec.update(python=got["python"], site_packages=got["site_packages"])
        except Exception as e:
            rec["ok"] = False
            rec["error"] = str(e)
        items.append(rec)
    return items, str(data.get("current") or "own")


def _write_targets(items, current):
    keep = [{"id": i["id"], "path": i["path"], "label": i["label"]}
            for i in items if not i.get("own")]
    _targets_file().write_text(
        json.dumps({"current": current, "items": keep}, ensure_ascii=False, indent=1),
        encoding="utf-8")


def active_target():
    """现在该动哪一套。选中的那个没了 / 认不出来了，就回落到自身那套。"""
    items, cur = target_list()
    for it in items:
        if it["id"] == cur and it.get("ok"):
            return it
    return items[0]


_RT_ACTIVE = {"at": 0.0, "v": None, "id": None}


def runtime(force=False):
    """「当前选中的」那套运行时的 python / site-packages。
    所有 pip 调用都从这里拿解释器 —— 切环境就是换这里，别处一个字不用改。"""
    t = active_target()
    if t.get("own"):
        info = dict(_own_runtime(force))
        info.update(id="own", label=t["label"], own=True)
        return info
    if (not force and _RT_ACTIVE["v"] and _RT_ACTIVE["id"] == t["id"]
            and time.time() - _RT_ACTIVE["at"] < 5):
        return _RT_ACTIVE["v"]
    try:
        got = _detect_env(t["path"])
    except Exception as e:
        raise RuntimeError("这个环境用不了：%s（%s）" % (t.get("label"), e))
    info = {"home": "", "declared": "", "versions": [], "version_dir": "",
            "dir": got["path"], "python": got["python"],
            "site_packages": got["site_packages"], "source": t.get("label") or "",
            "multi": False, "id": t["id"], "label": t.get("label"), "own": False}
    _RT_ACTIVE.update(at=time.time(), v=info, id=t["id"])
    return info


def set_target(tid):
    items, _ = target_list()
    for it in items:
        if it["id"] == tid:
            _write_targets(items, it["id"])
            invalidate()
            return it
    raise ValueError("没有这个环境：%s" % tid)


def add_target(path, label=""):
    got = _detect_env(path)
    items, cur = target_list()
    want = os.path.normcase(os.path.abspath(got["path"]))
    for it in items:
        if os.path.normcase(os.path.abspath(it["path"])) == want:
            raise ValueError("这个已经在列表里了：%s" % it["label"])
    rec = {"id": "t%d" % int(time.time() * 1000), "path": got["path"],
           "label": str(label or Path(got["path"]).name or got["path"]),
           "own": False, "ok": True, "python": got["python"],
           "site_packages": got["site_packages"]}
    items.append(rec)
    _write_targets(items, cur)
    return rec


def remove_target(tid):
    if str(tid) == "own":
        raise ValueError("自身那套不给删")
    items, cur = target_list()
    left = [i for i in items if i["id"] != tid]
    if len(left) == len(items):
        raise ValueError("没有这个环境：%s" % tid)
    if cur == tid:
        cur = "own"
    _write_targets(left, cur)
    invalidate()
    return True


_PICK_PS = (
    "Add-Type -AssemblyName System.Windows.Forms | Out-Null;"
    "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
    "$d.Description = '%s';"
    "$d.ShowNewFolderButton = $true;"
    "if ($d.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)"
    " { [Console]::Out.Write($d.SelectedPath) }"
)


def pick_dir(title="选一个目录"):
    """弹系统自带的「选文件夹」。不依赖这个运行时里装没装 tkinter。
    用户取消 → 返回 ok=False / cancelled=True（这不算出错）。"""
    safe = str(title or "选一个目录").replace("'", "''")
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-STA", "-Command", _PICK_PS % safe],
            capture_output=True, timeout=600, env=py_env())
    except Exception as e:
        return {"ok": False, "cancelled": False,
                "error": "选目录的窗口起不来（%s: %s）—— 可以直接把文件夹拖进来，或者手填路径" % (type(e).__name__, e)}
    out = _txt(p.stdout).strip()
    if out:
        return {"ok": True, "path": out, "cancelled": False}
    return {"ok": False, "cancelled": True, "path": "",
            "error": "没选（或者选择框被系统挡住了）"}


def py_env():
    e = os.environ.copy()
    e["PYTHONIOENCODING"] = "utf-8"
    e["PYTHONUTF8"] = "1"
    e["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    e.pop("PIP_REQUIRE_VIRTUALENV", None)
    src = source()
    if src["url"]:
        e["PIP_INDEX_URL"] = src["url"]
        host = urllib.parse.urlsplit(src["url"]).hostname
        if host:
            e["PIP_TRUSTED_HOST"] = host
    return e


# ---------------------------------------------------------------- 源（镜像）

# 全是 pip 标准的 --index-url / PIP_INDEX_URL，不是我们另发明的协议
SOURCES = {
    "pypi": ("官方 PyPI", "https://pypi.org/simple"),
    "tuna": ("清华 TUNA", "https://pypi.tuna.tsinghua.edu.cn/simple"),
    "aliyun": ("阿里云", "https://mirrors.aliyun.com/pypi/simple"),
    "ustc": ("中科大 USTC", "https://mirrors.ustc.edu.cn/pypi/simple"),
}


def _source_file():
    return data_dir() / "source.json"


def source():
    """装包用的源。默认 auto = 跟 pip 自己的配置（pip.ini），我们不覆盖它。"""
    try:
        data = json.loads(_source_file().read_text("utf-8"))
    except Exception:
        data = {}
    key = str(data.get("use") or "auto").strip().lower()
    if key in SOURCES:
        name, url = SOURCES[key]
        return {"use": key, "name": name, "url": url, "auto": False}
    return {"use": "auto", "name": "跟 pip 自己的配置", "url": "", "auto": True}


def set_source(key):
    key = str(key or "").strip().lower()
    if key in ("auto", "default", "pip", ""):
        try:
            _source_file().unlink()
        except Exception:
            pass
        return source()
    if key not in SOURCES:
        raise ValueError("没有这个源：%s（可选 %s、auto）"
                         % (key, "、".join(SOURCES)))
    _source_file().write_text(json.dumps({"use": key}), encoding="utf-8")
    return source()


def pip_config():
    """pip 自己认为用的是哪个源 —— 只读，不改它。"""
    try:
        rc, out, err = run_pip(["config", "list"], timeout=60)
        return (out or err).strip()
    except Exception as e:
        return "%s: %s" % (type(e).__name__, e)


def _txt(b):
    if not b:
        return ""
    if isinstance(b, str):
        return b
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except Exception:
            pass
    return b.decode("utf-8", "replace")


# ---------------------------------------------------------------- 问解释器

_PYV = {"at": 0.0, "v": None}


def python_version(force=False):
    """本进程就跑在那个解释器里（界面和 CLI 都是），所以直接读 sys.version。

    只有当「本进程」和「被管的那套运行时」不是同一个解释器时，才起子进程去问 ——
    否则白花 40ms 以上。实测：起子进程 36ms / 直接读 0ms。
    """
    if (not force and _PYV["v"] and time.time() - _PYV["at"] < 300
            and _PYV.get("py") == runtime()["python"]):
        return _PYV["v"]

    same = (os.path.normcase(os.path.abspath(sys.executable)) ==
            os.path.normcase(os.path.abspath(runtime()["python"])))
    if same:
        v = sys.version.split()[0]
    else:
        try:
            p = subprocess.run(
                [runtime()["python"], "-c", "import sys;print(sys.version.split()[0])"],
                capture_output=True, timeout=60, env=py_env())
            v = _txt(p.stdout).strip()
        except Exception as e:
            v = "读不出来（%s）" % e
    _PYV.update(at=time.time(), v=v, py=runtime()["python"])
    return v


_PIPV = {"at": 0.0, "v": None}


def pip_info(force=False):
    """{'ok': bool, 'version': '26.2.1', 'text': '...'}

    pip 的版本从它自己的 dist-info 里读（0.7ms），不再起 `pip --version`（389ms）。
    只有读不到时才退回去起子进程。
    """
    if (not force and _PIPV["v"] and time.time() - _PIPV["at"] < 60
            and _PIPV.get("py") == runtime()["python"]):
        return _PIPV["v"]

    out = {"ok": False, "version": "", "text": ""}
    try:
        import importlib.metadata as md
        # dist-info 这条路只能读「本进程」那套；管的是别的虚拟环境就得去问它自己
        if os.path.normcase(os.path.abspath(sys.executable)) != \
                os.path.normcase(os.path.abspath(runtime()["python"])):
            raise LookupError("不是本进程的解释器")
        v = md.version("pip")
        if v:
            out.update(ok=True, version=v,
                       text="pip %s (from %s)" % (v, runtime()["python"]))
    except Exception:
        pass

    if not out["ok"]:                      # 兜底：dist-info 读不到就问 pip 自己
        try:
            p = subprocess.run([runtime()["python"], "-m", "pip", "--version"],
                               capture_output=True, timeout=120, env=py_env())
            text = (_txt(p.stdout) + _txt(p.stderr)).strip()
            out["text"] = text
            out["ok"] = p.returncode == 0
            m = re.search(r"pip\s+([0-9][^\s]*)", text)
            if m:
                out["version"] = m.group(1)
        except Exception as e:
            out["text"] = "%s: %s" % (type(e).__name__, e)

    _PIPV.update(at=time.time(), v=out, py=runtime()["python"])
    return out


def run_pip(args, timeout=600):
    cmd = [runtime()["python"], "-m", "pip"] + [str(a) for a in args]
    p = subprocess.run(cmd, capture_output=True, timeout=timeout, env=py_env())
    return p.returncode, _txt(p.stdout), _txt(p.stderr)


# ---------------------------------------------------------------- 已装 / 可升级

_INST = {"at": 0.0, "v": None, "key": None}


def _site_key():
    """site-packages 的「指纹」：目录 mtime + 子项数量。

    装了 / 卸了包，这个值就会变 —— 用它当缓存有效期，装完立刻能看到新列表，
    没变就不用重扫。
    """
    site = Path(runtime()["site_packages"])
    try:
        st = site.stat()
        n = 0
        with os.scandir(site) as it:
            for _ in it:
                n += 1
        # 带上「哪一套环境」：两套环境包数一样多、时间戳又撞上时别串了列表
        return (runtime().get("id"), st.st_mtime_ns, n)
    except Exception:
        return None


def installed(force=False):
    """已安装的包。**直接读 site-packages 里的 *.dist-info，不起 pip 子进程。**

    实测：`pip list` 532ms（每次都要启动一个 Python + 加载 pip），
         `importlib.metadata` 120ms，
         直接扫 dist-info 目录 0.3ms ← 用这个。
    dist-info 的目录名格式是 `名字-版本.dist-info`，本身就是一份索引，
    没必要为此再跑一遍 pip。
    """
    key = _site_key()
    if (not force and _INST["v"] is not None
            and _INST["key"] == key and time.time() - _INST["at"] < 300):
        return _INST["v"]

    site = Path(runtime()["site_packages"])
    items = []
    if site.is_dir():
        try:
            with os.scandir(site) as it:
                for e in it:
                    if not (e.name.endswith(".dist-info") and e.is_dir()):
                        continue
                    stem = e.name[:-len(".dist-info")]
                    # 名字里可能有连字符，版本一定在最后一个连字符之后
                    i = stem.rfind("-")
                    if i <= 0:
                        continue
                    name, ver = stem[:i], stem[i + 1:]
                    if not name:
                        continue
                    items.append({"name": name, "version": ver})
        except Exception:
            items = []

    if not items:                       # 目录读不出来时兜底用 pip
        rc, out, err = run_pip(["list", "--format=json"], timeout=300)
        if rc != 0:
            raise RuntimeError((err or out).strip() or "pip list 失败")
        rows = json.loads(out or "[]")
        items = [{"name": str(r.get("name") or ""), "version": str(r.get("version") or "")}
                 for r in rows if r.get("name")]

    items.sort(key=lambda r: r["name"].lower())
    _INST.update(at=time.time(), v=items, key=key)
    return items


def invalidate():
    """装 / 卸 / 升之后清掉缓存（下次读就是新的）。"""
    _INST["at"] = 0.0
    _INST["v"] = None
    _INST["key"] = None
    _PIPV["v"] = None
    _PYV["v"] = None
    _RT_ACTIVE.update(at=0.0, v=None, id=None)


def outdated():
    rc, out, err = run_pip(["list", "--outdated", "--format=json"], timeout=600)
    if rc != 0:
        raise RuntimeError((err or out).strip() or "pip list --outdated 失败")
    rows = json.loads(out or "[]")
    items = [{"name": str(r.get("name") or ""),
              "version": str(r.get("version") or ""),
              "latest": str(r.get("latest_version") or "")}
             for r in rows if r.get("name")]
    items.sort(key=lambda r: r["name"].lower())
    return items


# ---------------------------------------------------------------- 按名字查包


def lookup(text):
    """按包名查 —— 走的就是 pip 自己那条路（PyPI 的 /pypi/<名字>/json）。

    「搜关键词」官方早关了：XML-RPC search 直接回
    "PyPI no longer supports 'pip search'"，网页 /search 是 JS 挑战。
    所以这儿不猜包名，只做「这个名字对不对」—— 知道名字就能装；
    不知道叫什么，点界面上的按钮去官方网页搜（那是唯一还开着的入口）。
    """
    names = [n for n in re.split(r"[\s,]+", str(text or "").strip()) if n]
    if not names:
        return {"q": "", "items": [], "missing": [], "found": 0}

    have = {}
    try:
        have = {r["name"].lower(): r["version"] for r in installed()}
    except Exception:
        pass

    got = details(names[:20])
    items, missing = [], []
    for it in got["items"]:
        if it.get("error"):
            e = str(it.get("error") or "")
            if "没有叫" in e:
                missing.append(it.get("name") or "")
            else:
                missing.append("%s（%s）" % (it.get("name") or "", e))
        else:
            it["installed"] = have.get(str(it.get("name", "")).lower(), "")
            items.append(it)
    return {"q": str(text).strip(), "items": items, "missing": missing, "found": len(items)}


# ---------------------------------------------------------------- PyPI 详情

_DETAIL = {}
_DETAIL_T = {}


def detail(name):
    key = str(name).strip().lower()
    if key in _DETAIL and time.time() - _DETAIL_T.get(key, 0) < 900:
        return _DETAIL[key]
    quoted = urllib.parse.quote(str(name).strip())
    d = None
    last = None
    for tpl in JSON_URLS:
        try:
            req = urllib.request.Request(tpl % quoted,
                                         headers={"User-Agent": UA,
                                                  "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=15) as r:
                d = json.loads(_txt(r.read()))
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError("PyPI 上没有叫「%s」的包" % str(name).strip())
            last = e
        except Exception as e:
            last = e
    if d is None:
        raise RuntimeError("%s: %s" % (type(last).__name__, last))
    i = d.get("info") or {}
    urls = i.get("project_urls") or {}
    out = {
        "name": i.get("name") or str(name),
        "version": i.get("version") or "",
        "summary": (i.get("summary") or "").strip(),
        "requires_python": i.get("requires_python") or "",
        "home": (i.get("project_url") or i.get("home_page")
                 or urls.get("Homepage") or urls.get("Source") or ""),
    }
    _DETAIL[key] = out
    _DETAIL_T[key] = time.time()
    return out


def details(names):
    names = [str(n).strip() for n in (names or []) if str(n).strip()][:40]
    if not names:
        return {"items": []}
    from concurrent.futures import ThreadPoolExecutor

    def one(n):
        try:
            return detail(n)
        except Exception as e:
            return {"name": n, "error": "%s: %s" % (type(e).__name__, e)}

    with ThreadPoolExecutor(max_workers=8) as ex:
        items = list(ex.map(one, names))
    return {"items": items}


# ---------------------------------------------------------------- 后台任务（装 / 卸 / 升级）

class Job:
    def __init__(self, kind, label):
        self.kind = kind
        self.label = label
        self.lines = []
        self.done = False
        self.ok = None
        self.rc = None
        self.t0 = time.time()
        self.lock = threading.Lock()

    def add(self, s):
        with self.lock:
            self.lines.append(s)
            if len(self.lines) > 5000:
                del self.lines[:2000]

    def snap(self):
        with self.lock:
            return {"kind": self.kind, "label": self.label, "lines": list(self.lines),
                    "done": self.done, "ok": self.ok, "rc": self.rc,
                    "elapsed": round(time.time() - self.t0, 1)}


_JOBS = {}
_JOBS_LOCK = threading.Lock()
_JOB_SEQ = [0]


def _new_job(kind, label):
    with _JOBS_LOCK:
        _JOB_SEQ[0] += 1
        jid = "j%d" % _JOB_SEQ[0]
        job = Job(kind, label)
        _JOBS[jid] = job
        while len(_JOBS) > 20:                      # 只留最近 20 个
            for k in list(_JOBS.keys())[:-20]:
                _JOBS.pop(k, None)
    return jid, job


def job_snap(jid):
    with _JOBS_LOCK:
        job = _JOBS.get(str(jid))
    if not job:
        return {"error": "没有这个任务：%s" % jid, "done": True}
    snap = job.snap()
    snap["id"] = jid
    return snap


def start_job(action, names=None):
    names = [str(n).strip() for n in (names or []) if str(n).strip()]
    action = str(action or "").strip().lower()

    if action in ("install", "add") and not names:
        return {"ok": False, "error": "要装哪个？给我至少一个包名。"}
    if action in ("uninstall", "remove") and not names:
        return {"ok": False, "error": "要卸哪个？给我至少一个包名。"}
    if action in ("uninstall", "remove"):
        bad = [n for n in names if n.lower() in GUARD]
        if bad:
            return {"ok": False, "error": "不能卸掉 %s —— 卸了这套环境就没法装东西了。" % "、".join(bad)}

    label = {"install": "安装", "add": "安装", "upgrade": "升级", "upgrade-all": "全部升级",
             "uninstall": "卸载", "remove": "卸载", "check": "检查依赖"}.get(action, action)
    if names:
        label += " " + " ".join(names[:3]) + ("…" if len(names) > 3 else "")

    jid, job = _new_job(action, label)

    def worker():
        try:
            argv = None
            if action in ("install", "add"):
                argv = ["install"] + names
            elif action == "upgrade":
                argv = ["install", "--upgrade"] + names
            elif action in ("uninstall", "remove"):
                argv = ["uninstall", "-y"] + names
            elif action == "check":
                argv = ["check"]
            elif action == "upgrade-all":
                job.add("[..] 先看看哪些能升（要连 PyPI 查一遍）…")
                rows = outdated()
                todo = [r["name"] for r in rows if r["name"].lower() not in GUARD]
                if not todo:
                    job.add("[好] 全都是最新的，没有要升的。")
                    job.ok, job.rc, job.done = True, 0, True
                    return
                job.add("[..] 要升的有 %d 个：%s" % (len(todo), "、".join(todo)))
                argv = ["install", "--upgrade"] + todo
            else:
                job.add("!! 不认识的动作：%s" % action)
                job.ok, job.rc, job.done = False, 2, True
                return

            job.add("$ python -m pip " + " ".join(argv))
            p = subprocess.Popen([runtime()["python"], "-m", "pip"] + argv,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 env=py_env(), bufsize=0)
            buf = b""
            while True:
                chunk = p.stdout.read(4096)
                if not chunk:
                    break
                parts = re.split(rb"[\r\n]+", buf + chunk)
                buf = parts.pop()
                for seg in parts:
                    line = _txt(seg).strip()
                    if line:
                        job.add(line)
            if buf.strip():
                job.add(_txt(buf).strip())
            rc = p.wait()
            job.rc = rc
            job.ok = rc == 0
            job.add("[完] 退出码 %d%s" % (rc, "" if rc == 0 else " —— 看上面哪行报的错"))
        except Exception as e:
            job.add("!! %s: %s" % (type(e).__name__, e))
            job.ok, job.rc = False, -1
        finally:
            job.done = True
            invalidate()                           # 装/卸/升完了，列表和 pip 版本都得重读
            _RT["at"] = 0.0

    threading.Thread(target=worker, daemon=True).start()
    return {"ok": True, "job": jid, "label": label}


# ---------------------------------------------------------------- 导出

def export(target=None):
    rc, out, err = run_pip(["freeze"], timeout=300)
    if rc != 0:
        raise RuntimeError((err or out).strip() or "pip freeze 失败")
    lines = [ln for ln in out.splitlines() if ln.strip()]
    text = "\n".join(lines) + "\n"
    if not target:
        path = data_dir() / "requirements.txt"
    else:
        path = Path(str(target)).expanduser()
        if path.is_dir() or str(target).endswith(("\\", "/")):
            path = path / "requirements.txt"      # 给的是目录：往里面放一个 requirements.txt
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return {"path": str(path), "text": text, "count": len(lines)}


# ---------------------------------------------------------------- 给界面用的 API

class Api:
    """界面的所有方法都长这样：def x(self, params=None)"""

    def env(self, params=None):
        """界面启动只调这一个 —— 环境 + 已装列表一次拿全，前端不用再问第二遍。"""
        rt = runtime()
        items = []
        err = None
        try:
            items = installed()
        except Exception as e:
            err = "%s: %s" % (type(e).__name__, e)

        out = {
            "runtime": rt,
            "python_version": python_version(),
            "pip": pip_info(),
            "source": source(),
            "sources": {k: {"name": v[0], "url": v[1]} for k, v in SOURCES.items()},
            "data_dir": str(data_dir()),
            "count": len(items) if err is None else None,
            "items": items,          # ← 一次带走，省掉一次往返
        }
        if err:
            out["error"] = err
        return out

    def installed(self, params=None):
        items = installed()
        return {"items": items, "count": len(items)}

    def outdated(self, params=None):
        items = outdated()
        return {"items": items, "count": len(items)}

    def lookup(self, params=None):
        p = params or {}
        return lookup(p.get("q") or "")

    def source(self, params=None):
        """不带 use = 只看；带 use = 切过去（'auto' 或源名字）"""
        p = params or {}
        use = p.get("use")
        if use:
            return {"source": set_source(use), "config": pip_config()}
        return {"source": source(), "config": pip_config(), "sources": SOURCES}

    def web_search(self, params=None):
        """关键词搜包只能去官方网页（唯一还开着的入口）—— 帮他开浏览器。"""
        p = params or {}
        q = str(p.get("q") or "").strip()
        url = WEB_SEARCH % urllib.parse.quote(q) if q else "https://pypi.org/search/"
        try:
            if IS_WIN:
                os.startfile(url)          # noqa: S606
            else:
                subprocess.Popen(["xdg-open", url])
            return {"ok": True, "url": url}
        except Exception as e:
            return {"ok": False, "url": url, "error": "%s: %s" % (type(e).__name__, e)}

    def start(self, params=None):
        p = params or {}
        got = start_job(p.get("action") or "", p.get("names") or [])
        if not got.get("ok"):
            raise RuntimeError(got.get("error") or "起不来这个任务")
        return got

    def job(self, params=None):
        p = params or {}
        snap = job_snap(p.get("id") or "")
        if p.get("tail"):
            snap["lines"] = snap.get("lines", [])[-int(p["tail"]):]
        return snap

    def export(self, params=None):
        p = params or {}
        return export(p.get("path") or None)

    def delete_export(self, params=None):
        """删掉一个导出的 requirements.txt。只删 .txt/.in 这种导出文件，
        路径也不许指到插件目录或运行时里 —— 这个按钮是给「删我刚才导出的那个」用的。"""
        p = params or {}
        raw = str(p.get("path") or "").strip()
        if not raw:
            raise ValueError("要删哪个文件？")

        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            path = path.resolve()
        except Exception:
            pass

        if not path.exists():
            return {"ok": True, "path": str(path), "missing": True}
        if not path.is_file():
            raise ValueError("这不是文件：%s" % path)
        if path.suffix.lower() not in (".txt", ".in"):
            raise ValueError("只删 requirements 文件（.txt / .in），这个不是：%s" % path.name)

        # 别让人（或误传的参数）把包目录、运行时删了
        for guard in (HERE, Path(runtime()["dir"])):
            try:
                path.relative_to(guard.resolve())
            except ValueError:
                continue
            raise ValueError("不能删这里面的文件：%s" % path)

        path.unlink()
        return {"ok": True, "path": str(path), "missing": False}

    # ---- 环境清单（自身那套 + 用户加的虚拟环境）
    def targets(self, params=None):
        items, cur = target_list()
        return {"items": items, "current": cur, "active": active_target()["id"]}

    def use_env(self, params=None):
        it = set_target(str((params or {}).get("id") or ""))
        return {"ok": True, "item": it}

    def add_env(self, params=None):
        p = str((params or {}).get("path") or "").strip()
        if not p:
            raise ValueError("要加哪个目录？")
        return {"ok": True, "item": add_target(p, (params or {}).get("label") or "")}

    def remove_env(self, params=None):
        remove_target(str((params or {}).get("id") or ""))
        return {"ok": True}

    def choose_dir(self, params=None):
        return pick_dir(str((params or {}).get("title") or "选一个目录"))

    def open_path(self, params=None):
        p = str((params or {}).get("path") or "").strip() or runtime()["dir"]
        if not os.path.isdir(p):
            return {"ok": False, "error": "这个目录不存在：%s" % p}
        try:
            if IS_WIN:
                os.startfile(p)  # noqa: S606
            else:
                subprocess.Popen(["xdg-open", p])
            return {"ok": True, "path": p}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e)}

    def open_dir(self, params=None):
        """在资源管理器里打开 site-packages（只对独立窗口/本机有意义）"""
        target = runtime()["site_packages"]
        try:
            if IS_WIN:
                os.startfile(target)          # noqa: S606
            else:
                subprocess.Popen(["xdg-open", target])
            return {"ok": True, "path": target}
        except Exception as e:
            return {"ok": False, "error": "%s: %s" % (type(e).__name__, e), "path": target}

    # ------------------------------------------------------------ CLI

    def cli(self, argv):
        """CLI 就是 python -m pip 的前门 —— 参数一个不改地丢给 pip。

        只有下面这几个是 pip 自己**没有**的（或者语义正好相反），先接住：
          env / source / export / web / gui
        其余全部原样透传：install、uninstall、list、show、freeze、download、
        cache、config、wheel、index versions、--version …… pip 加新命令这儿自动就有。
        """
        argv = [str(a) for a in (argv or []) if str(a) != ""]

        if not argv:
            return 0, self._env_text()

        verb = argv[0].lower()
        rest = argv[1:]

        if verb in ("env", "info", "status"):
            if rest:
                try:
                    return self._env_cli(rest)
                except Exception as e:                 # 路径不对这类错误要说人话，别抛栈
                    return 2, str(e)
            return 0, self._env_text()

        # 拖一个文件夹进来 = 加一套环境。宿主会把路径当参数交过来，
        # 所以这里认「一个存在的目录」，别让它掉进 pip 的参数里。
        if len(argv) == 1:
            try:
                if os.path.isdir(argv[0]):
                    return self._env_cli(["add", argv[0]])
            except Exception:
                pass

        # list --outdated 走我们自己那条（一次性交给 pip，拿到 JSON 再排成表），
        # 不原样透传 —— 透传只把 JSON 丢到终端，rc 还可能被中间环节吃掉。
        if verb == "list" and any(a in ("--outdated", "-o", "--uptodate") for a in rest):
            if "--format=json" in rest or "--format" in rest:
                return self._passthrough(argv)
            t0 = time.time()
            try:
                rows = outdated()
            except Exception as e:
                return 1, "查不了：%s" % e
            if not rows:
                return 0, "全都是最新的（用时 %.1f 秒）" % (time.time() - t0)
            lines = ["%d 个包能升级（一次交给 pip 查完，用时 %.1f 秒）" % (
                len(rows), time.time() - t0), ""]
            w = max(len(r["name"]) for r in rows) + 2
            for r in rows:
                lines.append("  %-*s%s  →  %s" % (w, r["name"], r["version"], r["latest"]))
            lines.append("")
            lines.append("升级一个：moss :pip upgrade <包>    全都升：moss :pip upgrade-all")
            return 0, "\n".join(lines)

        if verb in ("source", "mirror"):
            return self._source_cli(rest)

        # pip 自己的 search 早被官方关了（XML-RPC 直接报 no longer supports），
        # 这条只做「名字对不对」的精确查，算是补一个 pip 没有的
        if verb in ("search", "find"):
            return self._search_cli(rest)

        if verb in ("web", "browse"):
            return self._web_cli(rest)

        # pip freeze 打到终端；要给个文件名的话顺手写出去（pip 自己得靠 shell 重定向）
        if verb in ("export", "requirements"):
            got = export(rest[0] if rest else None)
            return 0, "[导出] %d 行 -> %s" % (got["count"], got["path"])

        # pip 没有 upgrade 这个动词（是 install --upgrade），留个习惯写法
        if verb in ("upgrade", "update"):
            return self._passthrough(["install", "--upgrade"] + rest)

        # 卸 pip 会把这套环境废掉 —— 只拦这一个
        if verb in ("uninstall", "remove"):
            bad = [a for a in rest if a.lower() in GUARD]
            if bad:
                return 1, "不能卸掉 %s —— 卸了这套环境就没法装东西了。" % "、".join(bad)
            if verb == "remove":
                rest = ["uninstall", "-y"] + rest
            return self._passthrough(rest)

        return self._passthrough(argv)

    def _passthrough(self, argv):
        """原样交给 pip：输出直接流到终端（不攒内存），退出码就是 pip 的退出码。"""
        cmd = [runtime()["python"], "-m", "pip"] + [str(a) for a in argv]
        p = subprocess.Popen(cmd, env=py_env())
        p.wait()
        invalidate()                           # 可能是 install/uninstall，列表得重读
        return p.returncode, ""

    def _source_cli(self, rest):
        if not rest:
            cur = source()
            lines = ["[装包用的源] %s" % cur["name"]]
            if cur["url"]:
                lines.append("  " + cur["url"])
            lines.append("")
            lines.append("可切换：")
            lines.append("  auto    跟 pip 自己的配置（pip.ini 里写什么就用什么）")
            for key, (name, url) in SOURCES.items():
                lines.append("  %-8s%s  %s" % (key, name, url))
            lines.append("")
            lines.append("切：moss :pip source tuna    切回来：moss :pip source auto")
            cfg = pip_config()
            if cfg:
                lines.append("")
                lines.append("pip 自己当前的配置：")
                for ln in cfg.splitlines():
                    lines.append("  " + ln)
            return 0, "\n".join(lines)
        if len(rest) > 1:
            return 2, "一次只能切一个源。"
        got = set_source(rest[0])
        if got["auto"]:
            return 0, "[好] 改回跟 pip 自己的配置走。"
        return 0, "[好] 装包改用 %s\n  %s" % (got["name"], got["url"])

    def _search_cli(self, rest):
        if not rest:
            return 2, "要查哪个包？例：moss :pip search requests（多个用空格分开）"
        got = lookup(" ".join(rest))
        lines = []
        for it in got["items"]:
            mark = "  [已装 %s]" % it["installed"] if it.get("installed") else ""
            lines.append("%s %s%s" % (it.get("name"), it.get("version") or "", mark))
            if it.get("summary"):
                lines.append("   " + it["summary"])
            if it.get("requires_python"):
                lines.append("   Python %s" % it["requires_python"])
        for bad in got["missing"]:
            lines.append("[没有] %s" % bad)
        lines.append("")
        if got["items"]:
            lines.append("装它：moss :pip install " +
                         " ".join(i.get("name") or "" for i in got["items"]))
        else:
            lines.append("PyPI 上找不到这个名字。想按关键词找？"
                         "moss :pip web <词> 会打开官方搜索页。")
        return 0, "\n".join(lines)

    def _web_cli(self, rest):
        q = " ".join(rest)
        url = WEB_SEARCH % urllib.parse.quote(q) if q else "https://pypi.org/search/"
        try:
            if IS_WIN:
                os.startfile(url)      # noqa: S606
            else:
                subprocess.Popen(["xdg-open", url])
        except Exception as e:
            return 1, "打不开浏览器：%s: %s\n地址：%s" % (type(e).__name__, e, url)
        return 0, "已经在浏览器里打开（PyPI 的关键词搜索只有网页这一条路）：\n  " + url

    def _env_cli(self, rest):
        """env use <id|路径> / env add <路径> / env rm <id> —— 只记住，不搬文件。"""
        sub = str(rest[0] if rest else "").lower()
        arg = " ".join(str(x) for x in rest[1:]).strip()
        if sub in ("use", "switch"):
            if not arg:
                return 2, "要切到哪个？先 moss :pip env 看清单"
            want = os.path.normcase(os.path.abspath(arg))
            for it in target_list()[0]:
                if it["id"] == arg or os.path.normcase(os.path.abspath(it["path"])) == want:
                    set_target(it["id"])
                    return 0, "已经切到：%s\n  %s" % (it["label"], it["path"])
            return 2, "没有这个环境：%s" % arg
        if sub in ("add", "open"):
            if not arg:
                return 2, "要加哪个目录？"
            it = add_target(arg)
            set_target(it["id"])          # 加进来就是要用它，直接切过去
            return 0, "已添加并切换：%s\n  %s\n（切回自身那套：moss :pip env use own）" % (
                it["label"], it["path"])
        if sub in ("rm", "remove", "del"):
            if not arg:
                return 2, "要删哪条记录？先 moss :pip env 看清单"
            remove_target(arg)
            return 0, "记录已删（硬盘上那个环境没动）"
        return 2, "不认识的：env %s（能用 use / add / rm）" % sub

    def _env_text(self):
        rt = runtime()
        info = pip_info()
        try:
            n = len(installed())
        except Exception:
            n = "?"
        src = source()
        lines = [
            "[环境] %s%s" % ("★ " if rt.get("own") else "", rt.get("label") or "moss 自带运行时"),
            "-" * 68,
            "  解释器      %s" % rt["python"],
            "  版本        Python %s · pip %s" % (python_version(), info.get("version") or "没装"),
            "  第三方库装在 %s" % rt["site_packages"],
            "  已装        %s 个包" % n,
            "  运行时目录  %s" % rt["dir"],
            "  挑选依据    %s（default.json 钉的是 %s）" % (
                rt["source"], rt["declared"] or "没写"),
        ]
        if rt["multi"]:
            lines.append("  注意        这台机器装了多个版本（%s），本工具**只动上面这一个**"
                         % "、".join(rt["versions"]))
        lines.append("")
        lines.append("  装包用的源  %s" % src["name"])
        lines.append("")
        lines.append("命令行就是 python -m pip：moss :pip install <包>，或者 moss :pip --help")
        lines.append("多出来的几条（pip 没有）：moss :pip source / search / export / web / gui")
        lines.append("")
        lines.append("  记得的环境（★ 是自身那套，切用 moss :pip env use <id>）")
        for it in target_list()[0]:
            mark = "★" if it.get("own") else ("·" if it.get("ok") else "✗")
            here = "   ← 当前" if it["id"] == rt.get("id") else ""
            lines.append("  %s %-30s %s%s" % (mark, it["label"], it["path"], here))
        return "\n".join(lines)


HELP = """
Pip 管理器 · 管 moss 自带 Python 运行时里的第三方库

命令行 = python -m pip 的前门：**除了下面这几个，参数一个不改地交给 pip**。
所以 pip 的文档（pip install / download / cache / config / wheel / freeze …）
在这儿逐字通用，`moss :pip --help` 就是 pip 自己的帮助。

  多出来的（pip 自己没有）：
  moss :pip                     看这套环境（解释器 / 版本 / 装了多少包 / 用的哪个源）
  moss :pip env                 同上
  moss :pip source [名字]       看 / 切装包用的源（auto / tuna / aliyun / ustc / pypi）
  moss :pip export [文件]       导出 requirements.txt（pip 的 freeze 得靠 shell 重定向）
  moss :pip search <名字…>      查名字对不对（pip 的 search 已被官方关掉，这个只做精确查）
  moss :pip web [词]            按关键词找包 → 打开 PyPI 官方搜索页
  moss :pip gui                 开界面

  和 pip 一样（例子）：
  moss :pip install requests            moss :pip uninstall -y rich
  moss :pip install "名字==1.2.3"       moss :pip list --outdated
  moss :pip show requests               moss :pip download requests -d .
  moss :pip cache dir                   moss :pip config list
  moss :pip index versions requests     moss :pip --version
  moss :pip install -U <包…>            （= 升级；upgrade 这个简写也认，会转成 install --upgrade）

唯一被拦的是 `uninstall pip` —— 卸了这套环境就装不了东西了。
"""


def gui():
    import webview

    page = HERE / "ui" / "index.html"
    webview.create_window("Pip 管理器", str(page), js_api=Api(),
                          width=1120, height=780, min_size=(820, 560))
    webview.start()
    return 0
