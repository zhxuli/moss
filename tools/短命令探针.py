# -*- coding: utf-8 -*-
"""短命令探针（`V-298`）：`core/shortcut.py` 的生成 / 删除 / 对账 / 迁移。

全程**不碰真实注册表**（把 `_write_user_path` / `_user_path_list` 换成内存里的一份），
也不碰真实 `user_data`（把 `paths.USER_DIR` 指到临时目录）。包列表也打桩，
所以"新建 / 改名 / 卸包"这些生命周期用「换掉假包列表再 sync」来模拟。

用法：
    system\\runtimes\\python\\3.12\\python.exe tools\\短命令探针.py
"""
import json
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                     # noqa: BLE001
        pass

from core import config as C                                          # noqa: E402
from core import paths as P                                           # noqa: E402
from core import shortcut as SC                                       # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="moss_scprobe_"))
P.USER_DIR = TMP / "user_data"
P.STATE_DIR = P.USER_DIR / "state"
P.USER_DIR.mkdir(parents=True, exist_ok=True)
P.STATE_DIR.mkdir(parents=True, exist_ok=True)

SC.launcher_argv = lambda: ["C:\\fake\\moss.exe"]                     # 假启动器
PATHMEM = []                                                          # 内存里的 PATH
SC._user_path_list = lambda: list(PATHMEM)
SC._write_user_path = lambda items: (PATHMEM.__setitem__(slice(None), list(items)) or True)
FAKE = [{"id": "img"}, {"id": "fanyi"}, {"id": "tree"}]               # 假包列表
SC.registry.scan_all = lambda: [{"id": x["id"]} for x in FAKE]
DIR = SC.shortcuts_dir()

RES = []


def chk(name, ok, detail=""):
    RES.append((name, bool(ok), detail))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + detail) if detail else ""))


def set_toggles(mo=False, pkg=False):
    C.CONFIG.setdefault("shortcut", {})["mo"] = mo
    C.CONFIG["shortcut"]["pkg"] = pkg


def shim(name):
    f = DIR / (name + ".cmd")
    return f.read_text(encoding="utf-8", errors="replace") if f.is_file() else ""


print("=" * 72)
print("A：都没开 —— 什么都不做")
print("=" * 72)
set_toggles(False, False)
msgs = SC.sync()
chk("关着时不产生任何动作", msgs == [], str(msgs))
chk("目录里没有 .cmd", not list(DIR.glob("*.cmd")) if DIR.is_dir() else True, "")
chk("PATH 里没有我们的目录", str(DIR) not in PATHMEM, "")

print()
print("=" * 72)
print("B：打开 mo —— 生成 `mo`（就是 moss，不带 --pkg）")
print("=" * 72)
set_toggles(True, False)
msgs = SC.sync()
chk("报告生成了 mo", any("生成 mo.cmd" in m for m in msgs), str(msgs))
body = shim("mo")
chk("mo.cmd 内容 = 调启动器 + %*（没有 --pkg）",
    'C:\\fake\\moss.exe' in body and "--pkg" not in body and body.rstrip().endswith("%*"),
    repr(body))
chk("目录进了 PATH（内存那份）", str(DIR) in PATHMEM, str(PATHMEM))
chk("账本记着 mo", (SC._read_ledger().get("files") or {}).get("mo") is None, "")

print()
print("=" * 72)
print("C：打开 pkg —— 给每个包生成 mo<id>（带 --pkg <id>）")
print("=" * 72)
set_toggles(True, True)
msgs = SC.sync()
chk("生成了 moimg / mofanyi / motree",
    all((DIR / (n + ".cmd")).is_file() for n in ("moimg", "mofanyi", "motree")), str(msgs))
chk("moimg.cmd 里有 --pkg img",
    "--pkg img" in shim("moimg") and shim("moimg").rstrip().endswith("%*"), repr(shim("moimg")))
chk("mo 也在（两个开关都开）", (DIR / "mo.cmd").is_file(), "")

print()
print("=" * 72)
print("D：再 sync 一次 —— 幂等（磁盘已经对上了，不该有任何动作）")
print("=" * 72)
msgs = SC.sync()
chk("幂等：没有要改的", msgs == [], str(msgs))

print()
print("=" * 72)
print("E：别人的文件不许动；卸掉一个包要跟着删它的短命令")
print("=" * 72)
(DIR / "manual.cmd").write_text("@echo off\r\necho 别人的\r\n", encoding="utf-8")
FAKE.pop()                                    # 模拟"卸掉 tree"
msgs = SC.sync()
chk("motree.cmd 被删掉", not (DIR / "motree.cmd").is_file(), str(msgs))
chk("别人的 manual.cmd 还在", (DIR / "manual.cmd").is_file(), "")
chk("moimg / mofanyi 还在", (DIR / "moimg.cmd").is_file() and (DIR / "mofanyi.cmd").is_file(), "")

print()
print("=" * 72)
print("F：两个开关都关 —— 删光我们的、摘掉 PATH，别人的仍不碰")
print("=" * 72)
set_toggles(False, False)
msgs = SC.sync()
chk("我们的 .cmd 全没了", not list(DIR.glob("mo*.cmd")), str(sorted(p.name for p in DIR.glob("*.cmd"))))
chk("别人的 manual.cmd 还在", (DIR / "manual.cmd").is_file(), "")
chk("目录已从 PATH 移除", str(DIR) not in PATHMEM, str(PATHMEM))
chk("账本里 files 空了", not (SC._read_ledger().get("files") or {}), "")

print()
print("=" * 72)
print("G：老配置缺 [shortcut] —— set_values 要能自动补段并写进去（只增不改）")
print("=" * 72)
cfg = TMP / "config.toml"
cfg.write_text('[symbols]\npath_mode = ""\nplugin_mode = ":"\n', encoding="utf-8")
r = C.set_values({"shortcut.mo": True}, path=cfg)
chk("保存成功（老文件里没有 [shortcut] 也认）", r.get("ok") is True, json.dumps(r, ensure_ascii=False))
txt = cfg.read_text(encoding="utf-8")
chk("文件里补出了 [shortcut] 段", "[shortcut]" in txt, "")
try:
    data = tomllib.loads(txt)
    got_ok = data["shortcut"]["mo"] is True and data["shortcut"]["pkg"] is False
except Exception as e:                                                # noqa: BLE001
    data, got_ok = {}, False
    chk("读回来的 TOML 能解析", False, repr(e))
chk("mo 写成了 true、pkg 保持 false", got_ok, str(data.get("shortcut")))
chk("原有内容没被动过（plugin_mode 还是 :）", (data.get("symbols") or {}).get("plugin_mode") == ":", "")

print()
print("=" * 72)
print("H：前缀可改（`V-298`）—— 换前缀要一起换文件名，坏字符要洗掉")
print("=" * 72)
C.CONFIG["shortcut"]["prefix"] = "x"
set_toggles(True, True)
msgs = SC.sync()
chk("换成 x 后生成 x / ximg / xfanyi",
    all((DIR / (n + ".cmd")).is_file() for n in ("x", "ximg", "xfanyi")), str(msgs))
chk("旧的 mo*.cmd 被清掉", not list(DIR.glob("mo*.cmd")),
    str(sorted(p.name for p in DIR.glob("*.cmd"))))
C.CONFIG["shortcut"]["prefix"] = "a b!"          # 带空格/符号：prefix() 就地洗
chk("坏前缀洗成安全字符（a b! → ab）", SC.prefix() == "ab", SC.prefix())
C.CONFIG["shortcut"]["prefix"] = "!!!"           # 全洗没了：退回出厂默认
chk("全坏前缀退回默认 mo", SC.prefix() == "mo", SC.prefix())
C.CONFIG["shortcut"]["prefix"] = "mo"
set_toggles(False, False)
SC.sync()

shutil.rmtree(TMP, ignore_errors=True)

bad = [x for x in RES if not x[1]]
print()
print("=" * 72)
print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的", len(RES), len(bad)))
sys.exit(0 if not bad else 1)
