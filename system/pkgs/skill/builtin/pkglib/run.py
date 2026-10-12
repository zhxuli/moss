# -*- coding: utf-8 -*-
"""pkglib —— 把第三方库装进「某个插件包」自己的 `packages/` 目录。

为什么要有这只手：宿主自带的运行时是隔离的，里面装不了库（`pip install` 没地方落），
所以用到 fastapi / flask / requests 之外的库时，插件就卡住了。
这只手的做法是「把库装进插件自己」：`<插件目录>/packages/`，再生成一个 `deps.py`
垫片，插件入口里 `import deps` 一下，sys.path 就带上了那个目录 —— 插件仍是自包含的，
不污染宿主环境，重装插件时跟着包目录走（注意：包目录里的东西升级包会冲掉，
真想长期留着，装在 `MOSS_PLUGIN_DATA_DIR` 那侧，见 AGENT.md）。

参数（stdin 一行 JSON，也在 MOSS_PKG_PARAMS / MOSS_TOOL_ARGS）：
  pkg    要装的库，"fastapi uvicorn" 这样空格或逗号分隔
  into   装到哪个插件目录（绝对路径，或 user_data/pkgs/<id> 里的包 id）
  mode   install（默认）/ probe（看环境）/ list（看已装）
  index  pip 源，默认清华镜像
  python 指定解释器

只往 stdout 打**要给模型看的结论**；过程信息一律走 stderr。
"""
import glob
import json
import os
import shutil
import socket
import subprocess
import sys

DEFAULT_INDEX = "https://pypi.tuna.tsinghua.edu.cn/simple"
PKG_SUBDIR = "packages"
SHIM_NAME = "deps.py"

SHIM_SOURCE = '''# -*- coding: utf-8 -*-
"""由 pkglib 生成：把同目录下的 packages/ 加进 sys.path。

用法（插件入口最前面，必须在 import 第三方库之前）：
    import deps          # noqa: F401
    import fastapi       # 现在能导进来了
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_DEPS = os.path.join(_HERE, "packages")
if os.path.isdir(_DEPS) and _DEPS not in sys.path:
    sys.path.insert(0, _DEPS)
try:  # Windows 上带 .pyd/.dll 的包（cryptography 之类）要靠这个找到自己的 dll
    if os.path.isdir(_DEPS) and hasattr(os, "add_dll_directory"):
        os.add_dll_directory(_DEPS)
except Exception:
    pass
'''


# ---------- 小工具 ----------

def read_args():
    raw = ""
    try:
        raw = sys.stdin.read()
    except Exception:                                                  # noqa: BLE001
        raw = ""
    if not raw.strip():
        raw = (os.environ.get("MOSS_PKG_PARAMS")
               or os.environ.get("MOSS_TOOL_ARGS") or "{}")
    try:
        got = json.loads(raw) if raw.strip() else {}
    except ValueError:
        got = {}
    return got if isinstance(got, dict) else {}


def dbg(msg):
    sys.stderr.write(str(msg) + "\n")


def clean_env():
    """把自己跑出来的子进程（pip）身上的 MOSS_* 清掉 —— 免得污染别人的进程识别。"""
    return {k: v for k, v in os.environ.items() if not k.startswith("MOSS_")}


def run(cmd, timeout=240):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", env=clean_env())
        return r.returncode, (r.stdout or ""), (r.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", "超时（%ds）：%s" % (timeout, " ".join(cmd))
    except Exception as e:                                             # noqa: BLE001
        return 125, "", "%s: %s" % (type(e).__name__, e)


def split_pkgs(s):
    items = []
    for chunk in str(s or "").replace(",", " ").replace(";", " ").split():
        chunk = chunk.strip()
        if chunk:
            items.append(chunk)
    return items


# ---------- 找到「目标插件目录」 ----------

def resolve_target(into):
    """into → 绝对路径。支持：绝对/相对已存在目录，或 user_data/pkgs/<id>、state/skill/<id>。"""
    raw = str(into or "").strip().strip('"').strip("'")
    if not raw:
        return None, "没给 into：要装的插件目录（绝对路径，或包 id）"
    if os.path.isdir(raw):
        return os.path.abspath(raw), None
    user_data = os.environ.get("MOSS_USER_DATA_DIR") or ""
    cands = []
    if user_data:
        cands += [os.path.join(user_data, "pkgs", raw),
                  os.path.join(user_data, "state", "skill", raw)]
    cands.append(os.path.join(os.getcwd(), raw))
    for c in cands:
        if os.path.isdir(c):
            return os.path.abspath(c), None
    return None, ("目录不存在：%s\n试过：\n  %s\n（给绝对路径，或 user_data/pkgs 下的包 id）"
                  % (raw, "\n  ".join(cands)))


# ---------- 找到「一个带 pip 的解释器」 ----------

def py_candidates(user_py):
    seen, out = set(), []

    def add(cmd):
        if not cmd:
            return
        exe = cmd[0]
        if not os.path.isfile(exe):
            return
        key = tuple(os.path.normcase(c) for c in cmd)
        if key in seen:
            return
        seen.add(key)
        out.append(list(cmd))

    if user_py:
        p = str(user_py).strip().strip('"')
        if os.path.isfile(p):
            add([p])
        else:
            add([shutil.which(p) or ""])
            for n in ("python", "python3", "py"):
                if n == p:
                    add([shutil.which(n) or ""])
    add([sys.executable] if sys.executable else [])

    venv = os.environ.get("MOSS_VENV")
    if venv:
        for rel in ("Scripts/python.exe", "bin/python", "bin/python3"):
            add([os.path.join(venv, *rel.split("/"))])

    for name in ("python", "python3"):
        w = shutil.which(name)
        if w:
            add([w])
    w = shutil.which("py")
    if w:
        add([w, "-3"])

    pats = [
        r"C:\Python*\python.exe",
        r"C:\Program Files\Python*\python.exe",
        r"C:\Program Files (x86)\Python*\python.exe",
        r"D:\python*\python.exe",
        r"D:\python*\*\python.exe",
        r"D:\Python*\python.exe",
        os.path.expanduser(r"~\AppData\Local\Programs\Python\Python*\python.exe"),
        os.path.expanduser(r"~\anaconda3\python.exe"),
        os.path.expanduser(r"~\miniconda3\python.exe"),
    ]
    for pat in pats:
        for p in sorted(glob.glob(pat), reverse=True):
            add([p])
    return out


def pip_version(base):
    code, out, err = run(base + ["-m", "pip", "--version"], timeout=60)
    if code == 0:
        return (out or err).strip().splitlines()[0].strip(), None
    return None, ((err or out).strip().splitlines() or [""])[-1][:200]


def pick_python(user_py, verbose=False):
    """回 (base, pipver, 报告行)。base 是能跑 `-m pip` 的命令前缀。"""
    report = []
    for base in py_candidates(user_py):
        ver, why = pip_version(base)
        shown = " ".join(base)
        if ver:
            report.append("  [有 pip] %s  →  %s" % (shown, ver))
            if verbose:
                print("\n".join(report))
            return base, ver, report
        report.append("  [无 pip] %s  →  %s" % (shown, why or "说不清"))
    return None, None, report


# ---------- 三个动作 ----------

def net_check(host, port=443, timeout=4):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "通"
    except Exception as e:                                             # noqa: BLE001
        return False, "%s" % e


def do_probe():
    print("== 解释器 ==")
    print("当前运行时：%s（%s）" % (sys.executable, sys.version.split()[0]))
    print("挑一个带 pip 的（第一个有 pip 的会被用）：")
    base, ver, report = pick_python("", verbose=True)
    if not report:
        print("  （一个候选都没找到）")
    print("\n== 能不能联网 ==")
    for host in ("pypi.tuna.tsinghua.edu.cn", "pypi.org"):
        ok, msg = net_check(host)
        print("  %s：%s" % (host, "通" if ok else "不通 —— " + msg))
    print("\n== 结论 ==")
    if base and ver:
        print("  可以装库，用：%s" % " ".join(base + ["-m", "pip", "install", "--target", "<插件>/packages", "<库名>"]))
    else:
        print("  没找到带 pip 的解释器 ⇒ 装不了库。")
        print("  兜底：装个 Python（勾 pip）或让 moss 用带 pip 的环境；也可以把库的 wheel 手动解压进 <插件>/packages/")
    return 0


def do_list(target):
    pkgs_dir = os.path.join(target, PKG_SUBDIR)
    if not os.path.isdir(pkgs_dir):
        print("还没装过：%s 不存在" % pkgs_dir)
        return 0
    names = []
    for n in sorted(os.listdir(pkgs_dir)):
        full = os.path.join(pkgs_dir, n)
        if n.endswith((".dist-info", ".egg-info")) or not os.path.isdir(full):
            continue
        if n.startswith("_"):
            continue
        names.append(n)
    shim = os.path.join(target, SHIM_NAME)
    print("目录：%s" % pkgs_dir)
    print("顶层包（%d 个）：%s" % (len(names), ", ".join(names) if names else "（空）"))
    print("垫片：%s" % ("有（%s）" % shim if os.path.isfile(shim) else "没有"))
    return 0


def do_install(target, pkgs, index, user_py):
    if not pkgs:
        print("没给要装的库。例子：pkg=fastapi uvicorn into=%s" % os.path.basename(target))
        return 2
    pkgs_dir = os.path.join(target, PKG_SUBDIR)
    try:
        os.makedirs(pkgs_dir, exist_ok=True)
    except Exception as e:                                             # noqa: BLE001
        print("建不了目录 %s：%s" % (pkgs_dir, e))
        return 3

    base, ver, report = pick_python(user_py)
    if not base:
        print("没找到带 pip 的解释器，装不了。环境探测：")
        print("\n".join(report))
        print("（要 pip：装个 Python 勾上 pip，或用 mode=probe 看看现状）")
        return 3

    src = (index or "").strip() or DEFAULT_INDEX
    cmd = base + ["-m", "pip", "install", "--no-input", "--disable-pip-version-check",
                  "--no-warn-script-location", "--upgrade", "--timeout", "30",
                  "--target", pkgs_dir]
    if src:
        cmd += ["-i", src]
    cmd += pkgs
    dbg("pip: " + " ".join(cmd))

    code, out, err = run(cmd, timeout=270)
    tail = [ln for ln in ((out or "") + "\n" + (err or "")).splitlines() if ln.strip()][-12:]
    print("pip 源：%s" % src)
    print("解释器：%s（%s）" % (" ".join(base), ver))
    print("装到：%s" % pkgs_dir)
    print("退出码：%s" % code)
    print("—— pip 输出末尾 ——")
    for ln in tail:
        print("  " + ln)

    if code != 0:
        print("\n没装成。常见原因：① 没网 / 源不通（换个 index）② 库名写错 ③ 需要编译工具（找 wheel 版）")
        return code

    # 写垫片
    shim = os.path.join(target, SHIM_NAME)
    wrote = False
    try:
        old = ""
        if os.path.isfile(shim):
            with open(shim, "r", encoding="utf-8") as f:
                old = f.read()
        if old != SHIM_SOURCE:
            with open(shim, "w", encoding="utf-8") as f:
                f.write(SHIM_SOURCE)
            wrote = True
    except Exception as e:                                             # noqa: BLE001
        print("垫片写不了（%s）：%s —— 请手工在入口里把 packages/ 插进 sys.path" % (shim, e))

    installed = sorted({n for n in os.listdir(pkgs_dir)
                        if os.path.isdir(os.path.join(pkgs_dir, n)) and not n.startswith("_")})
    print("\n装好了（%d 个顶层条目）：%s" % (len(installed), ", ".join(installed)))
    print("垫片 %s：%s" % (SHIM_NAME, "已更新" if wrote else "已存在（内容一致，没动）"))
    print("插件里这样用（入口最前面，必须在 import 这些库之前）：")
    print("    import deps   # noqa: F401")
    print("    " + " / ".join("import " + p.split("[")[0].replace("-", "_") for p in pkgs))
    return 0


def main():
    a = read_args()
    mode = str(a.get("mode") or "install").strip().lower()
    into = a.get("into") or a.get("target") or a.get("dir") or ""
    index = a.get("index") or a.get("src") or ""
    user_py = a.get("python") or a.get("py") or ""

    if mode in ("probe", "env", "check"):
        return do_probe()

    target, why = resolve_target(into)
    if not target:
        print(why)
        return 2

    if mode in ("list", "ls", "show"):
        return do_list(target)

    pkgs = split_pkgs(a.get("pkg") or a.get("packages") or a.get("name") or "")
    return do_install(target, pkgs, index, user_py)


if __name__ == "__main__":
    sys.exit(main())
