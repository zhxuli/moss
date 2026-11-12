import json
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "system" / "ui"
html = (UI / "index.html").read_text(encoding="utf-8")
main = (UI / "main.py").read_text(encoding="utf-8")
core_ui = (ROOT / "core" / "ui.py").read_text(encoding="utf-8")
js_files = sorted((UI / "js").glob("*.js"))
js_by_file = {f.name: f.read_text(encoding="utf-8") for f in js_files}

fails = []

def _safe(s):
    enc = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        return str(s).encode(enc, "replace").decode(enc, "replace")
    except Exception:
        return str(s).encode("ascii", "replace").decode("ascii")

def chk(name, ok, detail=""):
    print(_safe(("  OK  " if ok else " FAIL ") + name + (("  " + str(detail)) if detail else "")))
    if not ok:
        fails.append(name)

_html_nc = re.sub(r"<!--.*?-->", "", html, flags=re.S)
blocks = re.findall(r"<script>(.*?)</script>", _html_nc, re.S)
js = "\n".join(blocks)
for _name, _src in js_by_file.items():
    js += "\n" + _src
tmp_js = Path(tempfile.gettempdir()) / "moss_ui_extract.js"
tmp_js.write_text(js, encoding="utf-8")
r = subprocess.run(["node", "--check", str(tmp_js)], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
chk("node --check  JS 语法", r.returncode == 0, (r.stderr or "").strip()[:500])

_tpl_backtick = []
for _name, _src in js_by_file.items():
    for _m in re.finditer(r"<!--(?:(?!-->).)*-->", _src, re.S):
        if "`" in _m.group(0):
            _line = _src.count("\n", 0, _m.start()) + 1
            _tpl_backtick.append("%s:%d" % (_name, _line))
chk("模板里的 HTML 注释没有反引号", not _tpl_backtick,
    ("反引号会提前结束 template 字符串 —— 改掉：%s" % _tpl_backtick) if _tpl_backtick
    else "（反引号会提前结束模板字符串）")

_bare_meth = []

def _def_in(block, name):
    return re.search(r"^\s+(?:async\s+)?" + re.escape(name) + r"\s*\([^)]*\)\s*\{", block,
                     re.M) is not None

for _name, _src in js_by_file.items():
    _i_tpl = _src.find("template:")
    _i_comp = _src.find("computed: {")
    _i_meth = _src.find("methods: {")
    if min(_i_tpl, _i_comp, _i_meth) < 0:
        continue
    _marks = sorted({_i_tpl, _i_comp, _i_meth} |
                    {m.start() for m in re.finditer(
                        r"^  (?:watch|mounted|created|beforeMount|unmounted)\b", _src, re.M)})

    def _slice(start, _marks=_marks, _src=_src):
        nxt = [m for m in _marks if m > start]
        return _src[start:(min(nxt) if nxt else len(_src))]

    _tpl_src = _slice(_i_tpl)
    _comp_src = _slice(_i_comp)
    _meth_src = _slice(_i_meth)
    _called = set(re.findall(r"([A-Za-z_$][A-Za-z0-9_$]*)\s*\(", _tpl_src))
    _exprs = re.findall(r"\{\{([^}]*)\}\}", _tpl_src)
    _exprs += re.findall(
        r'(?:v-if|v-else-if|v-show|:class|:disabled|:title|:style)="([^"]*)"', _tpl_src)
    _bare = set()
    for _e in _exprs:
        _e = re.sub(r"'[^']*'|\"[^\"]*\"", " ", _e)
        _e = re.sub(r"\.[A-Za-z_$][A-Za-z0-9_$]*", " ", _e)
        _bare |= set(re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", _e))
    for _n in sorted(_bare):
        if _n in _called:
            continue
        if _def_in(_meth_src, _n) and not _def_in(_comp_src, _n):
            _bare_meth.append("%s: %s" % (_name, _n))
chk("模板里不带括号用的名字都是 computed（不是 methods）", not _bare_meth,
    ("这些只写在 methods 里 —— 模板裸用会渲染成函数本体：%s" % _bare_meth) if _bare_meth
    else "（computed 裸用 / methods 带括号）")

ids = re.findall(r'\bid="([^"]+)"', html)
dup = [k for k, v in Counter(ids).items() if v > 1]
chk("HTML 里的 id 唯一", not dup, ("重复：%s" % dup) if dup else "%d 个 id" % len(ids))

used = set(re.findall(r'\$\("#([A-Za-z0-9_\-]+)"\)', js))
used |= set(re.findall(r'querySelector\(\s*[\'"]#([A-Za-z0-9_\-]+)', js))
js_ids = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', js))
js_ids |= set(re.findall(r'\.id\s*=\s*["\']([A-Za-z0-9_\-]+)["\']', js))
missing = sorted(used - set(ids) - js_ids)
chk('$("#id") 都能找到', not missing, ("找不到：%s" % missing) if missing else "%d 个引用" % len(used))

_skill_dir = ROOT / "system" / "skills"
_skills = sorted(_skill_dir.glob("*/SKILL.md")) if _skill_dir.is_dir() else []
_skill_bad = []
for _f in _skills:
    _t = _f.read_text(encoding="utf-8", errors="replace")
    _m = re.match(r"\A---\s*\n(.*?)\n---\s*\n", _t, re.S)
    if not _m:
        _skill_bad.append("%s(没有 frontmatter)" % _f.parent.name)
        continue
    _head = _m.group(1)
    _name = re.search(r"^name:\s*(\S+)", _head, re.M)
    _desc = re.search(r"^description:\s*(\S+)", _head, re.M)
    if not _desc:
        _skill_bad.append("%s(缺 description)" % _f.parent.name)
    elif not _name or _name.group(1) != _f.parent.name:
        _skill_bad.append("%s(name 和目录名不一致)" % _f.parent.name)
chk("技能都有 frontmatter（name 与目录同名 + description）", not _skill_bad,
    ("有问题：%s" % _skill_bad) if _skill_bad else "%d 个技能" % len(_skills))

svg_dir = ROOT / "system" / "icon" / "svg"
have = set(p.stem for p in svg_dir.glob("*.svg"))
want = set(re.findall(r'\bico\(\s*"([a-z0-9\-]+)"', js))
bad = sorted(want - have)
chk("ico() 的图标名都有对应 .svg", not bad,
    ("缺：%s" % bad) if bad else "%d 个名 / 文件里 %d 个" % (len(want), len(have)))
_empty_svg = sorted(p.name for p in svg_dir.glob("*.svg")
                    if "<svg" not in p.read_text(encoding="utf-8", errors="replace"))
chk("图标文件都读得出内容", have and not _empty_svg,
    ("空/坏的：%s" % _empty_svg) if _empty_svg
    else ("目录都不见了：%s" % svg_dir) if not have else "%d 个 .svg" % len(have))

api_calls = set(re.findall(r'pywebview\.api\.([A-Za-z0-9_]+)\(', js))
api_defs = set(re.findall(r'^\s{4}def\s+([A-Za-z0-9_]+)\s*\(', main, re.M))
missing_api = sorted(api_calls - api_defs)
chk("pywebview.api.* 在 main.py 里有定义", not missing_api,
    ("缺：%s" % missing_api) if missing_api else "%d 个方法" % len(api_calls))

chk("core/ui.py 带 icon_exts", "icon_exts" in core_ui)
chk("界面后端读 icon_exts", "icon_exts" in main)
chk("界面后端有 abs 第三根", 'ABS_KEY = "abs"' in main and "_rel_page" in main)

for fn in ["setSide", "loadHist", "renderHist", "rerunHist", "rerunHistByKey",
           "rerunLast", "cmdNewPkg", "cmdRemovePkg", "paintHistStats", "histKey",
           "selectHist", "renderDetailHist", "histIconHTML", "histDir", "dirRel",
           "isHist", "selObj", "fmCtxKey", "isHistKey", "histByKey", "fmAtTop"]:
    chk("函数 %s" % fn, ("function %s(" % fn) in js or ("%s =" % fn) in js
        or ("const %s =" % fn) in js or ("let %s =" % fn) in js)
for bid in ["sw-pkg", "sw-hist", "btn-newpkg", "btn-remove", "btn-rerun"]:
    direct = ('$("#%s").onclick' % bid) in js
    in_tpl = re.search(r'<[^>]*\bid="%s"[^>]*@click=' % re.escape(bid), js) is not None
    chk("绑定 #%s" % bid, direct or in_tpl,
        "点法：%s" % ("$().onclick" if direct else ("模板 @click" if in_tpl else "无")))

for one in ["btn-run", "btn-vis"]:
    n = len(re.findall(r'id="%s"' % one, html))
    chk("id=%s 只定义一次" % one, n == 1, "出现 %d 次" % n)

chk("没有 pkgId 残留", "pkgId" not in js)
chk("没有 .hitem 专用的旧图标 corner-up-left 当历史兜底",
    'ico("corner-up-left", "i")))' not in js)
chk('历史切换用 history 图标', '"#sw-hist").innerHTML = ico("history"' in js)
chk("历史行不再直接 rerun（点=选中）",
    "onclick = () => rerunHist(it)" not in js and "selectHist(it)" in js)

bare = [n for n, s in js_by_file.items() if n != "core.js" and "Vue.createApp(" in s]
chk("Vue app 一律走 mountVue()（裸 createApp 只允许在 core.js）", not bare,
    ("这些文件里有裸的：%s" % bare) if bare else "OK")
chk("core.js 里有 mountVue + onVueError", "function mountVue(" in js_by_file.get("core.js", "")
    and "function onVueError(" in js_by_file.get("core.js", ""))

_top = {}
_dup_top = []
for _name, _src in js_by_file.items():
    for _m in re.finditer(r"^(?:function\s+([A-Za-z_$][\w$]*)|(?:const|let|var)\s+([A-Za-z_$][\w$]*))",
                          _src, re.M):
        _n = _m.group(1) or _m.group(2)
        if _n in _top:
            _dup_top.append("%s（%s + %s）" % (_n, _top[_n], _name))
        else:
            _top[_n] = _name
chk("js/*.js 顶层名字不重名", not _dup_top,
    ("被后加载的盖掉：%s" % _dup_top) if _dup_top else "%d 个顶层名" % len(_top))

_visible_bad = []
for _name, _src in js_by_file.items():
    for _m in re.finditer(r'\b(?:toast|setStatus|notice)\(\s*"((?:[^"\\]|\\.)*)"', _src):
        _s = _m.group(1)
        if "**" in _s:
            _visible_bad.append("%s：%s（** 星号）" % (_name, _s[:46]))
        if re.search(r"\bV-\d{2,3}\b", _s):
            _visible_bad.append("%s：%s（工单号）" % (_name, _s[:46]))
    for _m in re.finditer(r':?title="([^"]*)"', _src):
        _s = _m.group(1)
        if "**" in _s or re.search(r"\bV-\d{2,3}\b", _s):
            _visible_bad.append("%s：%s（title）" % (_name, _s[:46]))
chk("界面文案里没有 ** 星号 / 工单号", not _visible_bad,
    ("这些要改：%s" % _visible_bad[:6]) if _visible_bad
    else "扫了 toast/setStatus/notice 的第一个实参 + title")

for _t in (tmp_js,):
    _t.unlink(missing_ok=True)

print()
print("失败：%d" % len(fails))
if fails:
    print(json.dumps(fails, ensure_ascii=False, indent=2))
    sys.exit(1)
