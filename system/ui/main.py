#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""moss 界面 v0 —— 由 `moss.exe` 拉起，宿主把数据准备好后把**路径**放进 `MOSS_UI_DATA`。

三条硬规矩（都是被前几轮踩出来的）
----------------------------------
1. **这里不许 import core。** 发行版里 `core/` 编在 exe 里，磁盘上根本没有那个
   目录。所以界面要跑包时只能回头调 `MOSS_HOST_CMD`（就是 moss.exe 自己），
   和用户手敲命令走同一条路 —— 界面不另开一条执行通道。
2. **界面是渲染器，不认识 pkg.json。** 字段由宿主摊平成 JSON 喂进来
   （`core/ui.py:build_payload`）。包格式改了只改宿主一处。
3. `python.exe` 是控制台程序，而界面模式下宿主没有控制台 ⇒ 起子进程一律带
   `CREATE_NO_WINDOW`，否则点一下闪一个黑框（`E-27` ✅）。

v0 只做四件事：列包、看一个包的说明与参数、带参数跑并看输出、把包的界面开起来。
界面本身（`index.html`）以后随时改 —— 改它**不用重新打包 exe**，这正是把它
放在 exe 外面的理由（`K-10`）。
"""
import json
import os
import shlex
import shutil
import subprocess
from pathlib import Path

import webview

HERE = Path(__file__).resolve().parent
NO_WINDOW = 0x08000000          # CREATE_NO_WINDOW
DETACHED = 0x00000008           # DETACHED_PROCESS
DEVNULL = subprocess.DEVNULL


def _load_data():
    p = os.environ.get("MOSS_UI_DATA")
    if not p:
        raise SystemExit("缺少 MOSS_UI_DATA —— 这个界面只能由宿主拉起（moss ui / 双击 moss.exe）")
    return json.loads(Path(p).read_text(encoding="utf-8"))


DATA = _load_data()
HOST = [str(x) for x in (DATA.get("host_cmd") or [])]


def _split(text):
    """把参数框里那串文本拆成 argv。

    包参数本来就是"一个字符串"（`CL-02`），拼回去由宿主负责；这里只要拆得
    跟用户的直觉一致。带空格的路径用双引号括起来。
    """
    text = (text or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text)
    except ValueError:            # 引号没配对：别崩，按空白硬拆
        return text.split()


def _run_capture(argv):
    """跑一条宿主命令并把输出抓回来（合并 stdout+stderr，按 UTF-8 解）。"""
    try:
        r = subprocess.run(argv, capture_output=True, text=True,
                           encoding="utf-8", errors="replace",
                           creationflags=NO_WINDOW)
    except OSError as e:
        return {"code": -1, "out": "启动失败：%s" % e}
    return {"code": r.returncode, "out": (r.stdout or "") + (r.stderr or "")}


# ================================================================ 文件系统
# 界面里的「文件管理」选项卡要能像资源管理器那样操作。三条底线：
#
#   ① **只认两个根**：`user_data/`（用户资产）和 `system/`（出厂件）。
#   ② **路径必须落在根里面**：允许 `user/pkgs/x/main.py`，`../` 逃逸一律拒绝 ——
#      路径最终来自页面，不能假设它是善意的。
#   ③ **删除不是真删**：挪进 `user_data/trash/<时间戳>/<原路径>`（可恢复）。
#
# ★ `system/` 是**可写**的（2026-09-27 你定的："只读可不行"）。理由也站得住：
#   这个项目的玩法就是"自己改包"，而改包就得改代码；`system/pkgs/*` 虽然是出厂件，
#   但现在还没开始分发、改坏了 git 还能救。界面上**只提示不拦截**：
#   打开 `system/` 里的文件会顶一条"升级时会被整体替换"的提醒。
MAX_READ = 2 * 1024 * 1024          # 超过 2 MB 不给编辑（读出来看看就够）
TRASH_DIRNAME = "trash"

HOME = Path(os.environ.get("MOSS_HOME") or ".")
USER_DATA = Path(os.environ.get("MOSS_USER_DATA_DIR") or (HOME / "user_data"))

ROOTS = [
    {"key": "user", "label": "user_data", "path": USER_DATA, "writable": True,
     "why": "你的包 / 配置 / 数据"},
    {"key": "system", "label": "system", "path": HOME / "system", "writable": True,
     "why": "出厂件（随 moss.exe 分发）—— 能改，但升级时会被整体替换"},
]


def _root_by_key(key):
    for r in ROOTS:
        if r["key"] == key:
            return r
    return None


def _resolve(rel):
    """把 `user/pkgs/x/main.py` 解析成绝对路径，并确保没跑出根本身。

    返回 (root_dict, Path)；不合法就抛 ValueError（页面把 message 显示出来）。
    """
    rel = str(rel or "").replace("\\", "/").strip().strip("/")
    key, _, sub = rel.partition("/")
    root = _root_by_key(key)
    if root is None:
        raise ValueError("不认识的根 '%s'（只允许 %s）"
                         % (key, " / ".join(r["key"] for r in ROOTS)))
    base = Path(root["path"])
    try:
        base_r = base.resolve()
        target = (base / sub).resolve() if sub else base_r
    except OSError as e:
        raise ValueError("路径解析失败：%s" % e)
    if target != base_r and base_r not in target.parents:
        raise ValueError("路径跑到根外面去了：%s" % rel)
    return root, target


def _rel_of(path):
    """绝对路径 → 页面用的 `key/子路径`。"""
    p = Path(path).resolve()
    for r in ROOTS:
        base = Path(r["path"]).resolve()
        if p == base:
            return r["key"]
        if base in p.parents:
            return r["key"] + "/" + p.relative_to(base).as_posix()
    return None


def _trash(path):
    """把东西挪进 `user_data/trash/<时间戳>/<原相对路径>`（不真删）。"""
    import time
    rel = _rel_of(path)
    if not rel:
        raise ValueError("这东西不在两个根里面")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = USER_DATA / TRASH_DIRNAME / stamp / Path(rel.replace("/", os.sep))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = _unique(dest)
    shutil.move(str(path), str(dest))
    return rel, _rel_of(dest)


def _unique(path):
    """同名就按资源管理器的规矩加 (2)(3)：`a.txt` → `a (2).txt`。"""
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for i in range(2, 1000):
        cand = path.with_name("%s (%d)%s" % (stem, i, suffix))
        if not cand.exists():
            return cand
    raise OSError("同名文件太多了：%s" % path.name)


def _bad_name(name):
    return (not name) or any(c in name for c in '\\/:*?"<>|') or name in (".", "..")


class Api:
    """给页面用的接口。每个方法都是一个前端可 await 的调用。"""

    def state(self):
        return DATA

    def run(self, pid, args_text=""):
        """带参数跑一个包，输出回页面（会等它跑完）。"""
        return _run_capture(HOST + [":" + str(pid)] + _split(args_text))

    def open_ui(self, pid, args_text=""):
        """把包的界面开起来：**脱离**当前进程、不抓输出，所以不会卡住界面。"""
        argv = HOST + [":" + str(pid)] + _split(args_text)
        try:
            subprocess.Popen(argv, stdin=DEVNULL, stdout=DEVNULL, stderr=DEVNULL,
                             creationflags=NO_WINDOW | DETACHED, close_fds=True)
        except OSError as e:
            return {"ok": False, "msg": "启动失败：%s" % e}
        return {"ok": True, "msg": "已后台启动：" + " ".join(argv[1:])}

    def run_host(self, text):
        """跑一条宿主命令（自检用）：`--selfcheck` / `--history 20` 之类，不带包名。"""
        return _run_capture(HOST + _split(text))

    def open_path(self, path):
        try:
            os.startfile(str(path))        # noqa: S606  Windows 专用
            return {"ok": True, "msg": "已打开：" + str(path)}
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}

    # ------------------------------------------------ 文件浏览 / 编辑（v0.5）
    def fs_roots(self):
        """两个根（页面把它画成树的顶层）。"""
        return {"roots": [{"key": r["key"], "label": r["label"],
                           "path": str(r["path"]), "writable": r["writable"],
                           "why": r["why"],
                           "exists": Path(r["path"]).is_dir()} for r in ROOTS]}

    def fs_list(self, rel):
        """列一个目录。返回的每一项都带 `rel`，页面点它就能继续往下走。"""
        try:
            root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not p.exists():
            return {"ok": False, "msg": "没有这个东西：%s" % rel}
        if not p.is_dir():
            return {"ok": False, "msg": "不是目录：%s" % rel}
        entries = []
        try:
            for child in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower())):
                if child.name == "__pycache__":
                    continue
                try:
                    st = child.stat()
                    size, mtime = st.st_size, int(st.st_mtime)
                except OSError:
                    size, mtime = 0, 0
                entries.append({"name": child.name, "rel": _rel_of(child),
                                "dir": child.is_dir(), "size": size, "mtime": mtime,
                                "ext": child.suffix.lower().lstrip(".")})
        except OSError as e:
            return {"ok": False, "msg": "读目录失败：%s" % e}
        return {"ok": True, "rel": _rel_of(p), "entries": entries,
                "writable": root["writable"], "path": str(p)}

    def fs_read(self, rel):
        """读一个文件。二进制 / 超大只回报状态，不给编辑（免得把编辑器当十六进制用）。"""
        try:
            root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not p.is_file():
            return {"ok": False, "msg": "不是文件：%s" % rel}
        size = p.stat().st_size
        if size > MAX_READ:
            return {"ok": True, "binary": False, "too_big": True, "size": size,
                    "text": "", "writable": root["writable"],
                    "msg": "文件 %.1f MB，超过 %.1f MB，不给编辑" % (size / 1048576, MAX_READ / 1048576)}
        raw = p.read_bytes()
        if b"\x00" in raw[:8192]:
            return {"ok": True, "binary": True, "too_big": False, "size": size,
                    "text": "", "writable": False, "msg": "二进制文件，不给编辑"}
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", "replace")
        return {"ok": True, "binary": False, "too_big": False, "size": size,
                "text": text, "rel": _rel_of(p), "path": str(p),
                "writable": root["writable"],
                "mtime": int(p.stat().st_mtime)}

    def fs_write(self, rel, text):
        """写回文件。两个根都能写（`system/` 也放开了，见文件头那段说明）。"""
        try:
            root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if p.is_dir():
            return {"ok": False, "msg": "这是目录，不是文件"}
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".moss-tmp")
            # ★ newline="" 必须写：文本模式默认会把 \n 翻成 \r\n，于是
            #   "没改一个字、点一下保存" 也会把整个文件的行尾换掉（实测：写 "print(1)\n"
            #   读回来是 "print(1)\r\n"）。编辑器要原样进原样出。
            with open(tmp, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            os.replace(tmp, p)          # 原子替换：写一半断电也不会留半个文件
        except OSError as e:
            return {"ok": False, "msg": "写不进去：%s" % e}
        return {"ok": True, "msg": "已保存 %s" % rel, "size": p.stat().st_size,
                "mtime": int(p.stat().st_mtime),
                "factory": rel.split("/")[0] == "system"}

    def fs_mkdir(self, rel_parent, name):
        return self._fs_create(rel_parent, name, True)

    def fs_touch(self, rel_parent, name):
        return self._fs_create(rel_parent, name, False)

    def _fs_create(self, rel_parent, name, as_dir):
        try:
            _root, parent = _resolve(rel_parent)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        name = str(name or "").strip()
        if _bad_name(name):
            return {"ok": False, "msg": "名字不合法"}
        if not parent.is_dir():
            return {"ok": False, "msg": "父目录不存在：%s" % rel_parent}
        target = parent / name
        if target.exists():
            return {"ok": False, "msg": "已经有一个同名的了"}
        try:
            if as_dir:
                target.mkdir()
            else:
                with open(target, "w", encoding="utf-8", newline=""):
                    pass
        except OSError as e:
            return {"ok": False, "msg": "建不了：%s" % e}
        return {"ok": True, "rel": _rel_of(target), "msg": "已创建 %s" % name}

    def fs_rename(self, rel, new_name):
        try:
            _root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        new_name = str(new_name or "").strip()
        if _bad_name(new_name):
            return {"ok": False, "msg": "名字不合法"}
        target = p.with_name(new_name)
        if target.exists():
            return {"ok": False, "msg": "已经有一个同名的了"}
        try:
            p.rename(target)
        except OSError as e:
            return {"ok": False, "msg": "改不了名：%s" % e}
        return {"ok": True, "rel": _rel_of(target), "old": rel, "msg": "已改名为 %s" % new_name}

    def fs_delete(self, rels):
        """删除 = **挪进 user_data/trash/**（可恢复），不真删。收一个或多个。"""
        if isinstance(rels, str):
            rels = [rels]
        done, bad = [], []
        for rel in (rels or []):
            try:
                root, p = _resolve(rel)
            except ValueError as e:
                bad.append("%s：%s" % (rel, e))
                continue
            if p == Path(root["path"]).resolve():
                bad.append("%s：根本身不能删" % rel)
                continue
            try:
                _old, new = _trash(p)
                done.append(new)
            except (ValueError, OSError) as e:
                bad.append("%s：%s" % (rel, e))
        if not done:
            return {"ok": False, "msg": "；".join(bad) or "什么都没删"}
        msg = "已挪进回收站（%s）" % "、".join(done[:3])
        if len(done) > 3:
            msg += " 等 %d 项" % len(done)
        if bad:
            msg += "；有 %d 项没成：%s" % (len(bad), bad[0])
        return {"ok": True, "msg": msg, "trash": done, "bad": bad}

    def fs_copy(self, rels, dest_rel, cut=False):
        """复制 / 移动（`cut=True`）若干项到一个目录 —— 资源管理器的 Ctrl+C / Ctrl+X / Ctrl+V。

        同名不覆盖，按资源管理器的规矩起 `名字 (2).ext`。
        """
        if isinstance(rels, str):
            rels = [rels]
        try:
            _droot, dest = _resolve(dest_rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not dest.is_dir():
            return {"ok": False, "msg": "目标不是目录：%s" % dest_rel}
        made, bad = [], []
        for rel in (rels or []):
            try:
                _sroot, src = _resolve(rel)
            except ValueError as e:
                bad.append(str(e))
                continue
            if not src.exists():
                bad.append("%s 不存在" % rel)
                continue
            # 别把目录搬进它自己里面（资源管理器也是直接拒绝的）
            if src.is_dir() and (dest == src or src in dest.parents):
                bad.append("%s：不能把目录放进它自己里面" % src.name)
                continue
            target = _unique(dest / src.name)
            try:
                if cut:
                    shutil.move(str(src), str(target))
                elif src.is_dir():
                    shutil.copytree(str(src), str(target))
                else:
                    shutil.copy2(str(src), str(target))
                made.append(_rel_of(target))
            except (OSError, shutil.Error) as e:
                bad.append("%s：%s" % (src.name, e))
        if not made:
            return {"ok": False, "msg": "；".join(bad) or "什么都没做"}
        verb = "移动" if cut else "复制"
        msg = "已%s %d 项" % (verb, len(made))
        if bad:
            msg += "；有 %d 项没成：%s" % (len(bad), bad[0])
        return {"ok": True, "msg": msg, "made": made, "bad": bad}

    def fs_open_default(self, rel):
        """用系统默认程序打开（二进制文件、图片这些不该塞进编辑器）。"""
        try:
            _root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        if not p.exists():
            return {"ok": False, "msg": "没有这个东西：%s" % rel}
        try:
            os.startfile(str(p))        # noqa: S606  Windows 专用
        except OSError as e:
            return {"ok": False, "msg": "打不开：%s" % e}
        return {"ok": True, "msg": "已用默认程序打开 %s" % p.name}

    def fs_reveal(self, rel):
        """在资源管理器里选中它。"""
        try:
            _root, p = _resolve(rel)
        except ValueError as e:
            return {"ok": False, "msg": str(e)}
        try:
            subprocess.Popen(["explorer", "/select,", str(p)], creationflags=NO_WINDOW)
        except OSError as e:
            return {"ok": False, "msg": str(e)}
        return {"ok": True, "msg": "已在资源管理器中打开"}

    def quit(self):
        window.destroy()
        return {"ok": True}


window = webview.create_window(
    "moss",
    str(HERE / "index.html"),
    js_api=Api(),
    width=1280,
    height=860,
    min_size=(900, 600),
    # ★ text_select 默认是 **False**，页面上的字**选不中**（拖不动、也没法 Ctrl+C）——
    #   pywebview 的 `create_window(..., text_select: bool = False)`。
    #   命令行窗口最要紧的就是"能选中、能复制"，所以这里必须打开它；
    #   页面里也给 `#out` 写了 user-select:text，另外配了「复制全部」按钮。
    text_select=True,
)

if __name__ == "__main__":
    webview.start()
