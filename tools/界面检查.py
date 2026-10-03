# -*- coding: utf-8 -*-
"""界面静态检查（`V-83` 起收进 `tools/`）。

为什么要有它：界面拆成 `js/*.js` + Vue 组件之后，有一批毛病**看不见**运行时异常、
截图也照不出来 —— 少绑一个处理器、`ico()` 写了个表里没有的图标名、模板里引用了
`pywebview.api` 里不存在的方法、`#id` 在 HTML 里被删了而 js 还在找它。
这些都能在这儿一眼拦下。跑法：

    .\\venv\\Scripts\\python.exe tools\\界面检查.py

（原来这份脚本是临时写在 `%TEMP%` 里的，`V-83` 这轮收进仓库，免得每次都要重写。）
"""
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


def chk(name, ok, detail=""):
    print(("  OK  " if ok else " FAIL ") + name + (("  " + str(detail)) if detail else ""))
    if not ok:
        fails.append(name)


# ---------------- 1. 抽出 <script> 里的 JS ----------------
# ★ 抽之前**先把 HTML 注释剥掉**：注释里写着的 `<script>`（说明文字）会被当成脚本开头，
#   非贪婪匹配于是从那儿一路吞到后面的 </script>，把说明文字当代码。
#   再只认**裸** `<script>`（带属性的 `<script src=...>` 排除掉）。
_html_nc = re.sub(r"<!--.*?-->", "", html, flags=re.S)
blocks = re.findall(r"<script>(.*?)</script>", _html_nc, re.S)
js = "\n".join(blocks)
# ★ `V-67`：界面拆成了 `js/*.js`（经典脚本、顺序加载）—— 检查得把那些文件也算进来，
#   否则 `$("#set-save")` 这类引用会被当成"找不到"（其实在 js/settings.js 里）。
for _name, _src in js_by_file.items():
    js += "\n" + _src
tmp_js = Path(tempfile.gettempdir()) / "moss_ui_extract.js"
tmp_js.write_text(js, encoding="utf-8")
r = subprocess.run(["node", "--check", str(tmp_js)], capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
chk("node --check  JS 语法", r.returncode == 0, (r.stderr or "").strip()[:500])

# ---------------- 1b. 模板里的 HTML 注释不许有反引号（`V-195` 加的一道闸）----------------
# ★ 为什么值得单列一条：Vue 组件的 `template:` 是**模板字符串**，里面每一对反引号都会
#   提前结束这个字符串 —— 而"在 HTML 注释里引用一下 `V-194`"这种写法我**踩了三次**
#   （`node --check` 报的是一句莫名其妙的 `Unexpected identifier`，得往回找才知道是注释）。
#   这条闸把话说在前面：`<!-- ... `xxx` ... -->` 一律拦下。
_tpl_backtick = []
for _name, _src in js_by_file.items():
    for _m in re.finditer(r"<!--(?:(?!-->).)*-->", _src, re.S):
        if "`" in _m.group(0):
            _line = _src.count("\n", 0, _m.start()) + 1
            _tpl_backtick.append("%s:%d" % (_name, _line))
chk("模板里的 HTML 注释没有反引号", not _tpl_backtick,
    ("反引号会提前结束 template 字符串 —— 改掉：%s" % _tpl_backtick) if _tpl_backtick
    else "（反引号会提前结束模板字符串）")

# ---------------- 2. id 唯一 ----------------
ids = re.findall(r'\bid="([^"]+)"', html)
dup = [k for k, v in Counter(ids).items() if v > 1]
chk("HTML 里的 id 唯一", not dup, ("重复：%s" % dup) if dup else "%d 个 id" % len(ids))

# ---------------- 3. JS 里用到的 #id 都存在 ----------------
used = set(re.findall(r'\$\("#([A-Za-z0-9_\-]+)"\)', js))
used |= set(re.findall(r'querySelector\(\s*[\'"]#([A-Za-z0-9_\-]+)', js))
js_ids = set(re.findall(r'id="([A-Za-z0-9_\-]+)"', js))       # JS 里动态拼出来的 / 模板里的
# ★ 还有 `el.id = "xxx"` 这种写法（`V-63` 的 `#set-live` 就是这么造出来的）
js_ids |= set(re.findall(r'\.id\s*=\s*["\']([A-Za-z0-9_\-]+)["\']', js))
missing = sorted(used - set(ids) - js_ids)
chk('$("#id") 都能找到', not missing, ("找不到：%s" % missing) if missing else "%d 个引用" % len(used))

# ---------------- 4. 图标名都在 lucide 表里 ----------------
lucide = (UI / "vendor" / "lucide.js").read_text(encoding="utf-8")
have = set(re.findall(r'^"([a-z0-9\-]+)":\s*"', lucide, re.M))
have |= set(re.findall(r'^"([a-z0-9\-]+)":\s*\{', lucide, re.M))   # 实心那族（`V-96`）
want = set(re.findall(r'\bico\(\s*"([a-z0-9\-]+)"', js))
bad = sorted(want - have)
chk("ico() 的图标名都存在", not bad,
    ("缺：%s" % bad) if bad else "%d 个名 / 表里 %d 个" % (len(want), len(have)))

# ---------------- 5. 界面调的 api 方法，main.py 里都有 ----------------
api_calls = set(re.findall(r'pywebview\.api\.([A-Za-z0-9_]+)\(', js))
api_defs = set(re.findall(r'^\s{4}def\s+([A-Za-z0-9_]+)\s*\(', main, re.M))
missing_api = sorted(api_calls - api_defs)
chk("pywebview.api.* 在 main.py 里有定义", not missing_api,
    ("缺：%s" % missing_api) if missing_api else "%d 个方法" % len(api_calls))

# ---------------- 6. 宿主/后端该有的东西 ----------------
chk("core/ui.py 带 icon_exts", "icon_exts" in core_ui)
chk("界面后端读 icon_exts", "icon_exts" in main)
chk("界面后端有 abs 第三根", 'ABS_KEY = "abs"' in main and "_rel_page" in main)

# ---------------- 7. 关键函数/绑定别丢 ----------------
for fn in ["setSide", "loadHist", "renderHist", "rerunHist", "rerunHistByKey",
           "rerunLast", "cmdNewPkg", "cmdRemovePkg", "paintHistStats", "histKey",
           "selectHist", "renderDetailHist", "histIconHTML", "histDir", "dirRel",
           "isHist", "selObj", "fmCtxKey", "isHistKey", "histByKey", "fmAtTop"]:
    chk("函数 %s" % fn, ("function %s(" % fn) in js or ("%s =" % fn) in js
        or ("const %s =" % fn) in js or ("let %s =" % fn) in js)
# ★ `V-83`：页面搬进 Vue 组件之后，"按钮有没有绑上"不再只有 `$("#x").onclick` 一种写法 ——
#   模板里写 `@click=…` 也算绑上了。所以两种都认（不然组件化一下这检查就假报失败，
#   而我第一版就是拿它当"跑一次就放心"的护栏）。
for bid in ["sw-pkg", "sw-hist", "btn-newpkg", "btn-remove", "btn-rerun"]:
    direct = ('$("#%s").onclick' % bid) in js
    in_tpl = re.search(r'<[^>]*\bid="%s"[^>]*@click=' % re.escape(bid), js) is not None
    chk("绑定 #%s" % bid, direct or in_tpl,
        "点法：%s" % ("$().onclick" if direct else ("模板 @click" if in_tpl else "无")))

# ---------------- 8. 只能有一个 #btn-run / #btn-vis 定义（老坑） ----------------
for one in ["btn-run", "btn-vis"]:
    n = len(re.findall(r'id="%s"' % one, html))
    chk("id=%s 只定义一次" % one, n == 1, "出现 %d 次" % n)

# ---------------- 9. 旧写法不该留 ----------------
chk("没有 pkgId 残留", "pkgId" not in js)
chk("没有 .hitem 专用的旧图标 corner-up-left 当历史兜底",
    'ico("corner-up-left", "i")))' not in js)
chk('历史切换用 history 图标', '"#sw-hist").innerHTML = ico("history"' in js)
# ★ `V-79` 起历史列表是 Vue 组件：点击绑在模板上（@click=pick(it)）+ 方法里 selectHist(it)，
#   不再是 `d.onclick = …` 那种写法。断言改成看"有没有 selectHist(it)、有没有直接 rerun"。
chk("历史行不再直接 rerun（点=选中）",
    "onclick = () => rerunHist(it)" not in js and "selectHist(it)" in js)

# ---------------- 10. 组件里的异常必须报得出来（`V-81` 的血） ----------------
# 裸 `Vue.createApp(...).mount(...)` 建的 app **不会**报错到界面上（Vue 默认只写控制台，
# 而这个界面没有控制台；`vue.global.prod.js` 里连 `Vue.config` 都没有）。
# 所以：除了 `core.js` 里 `mountVue` 自己那一处，别处一律不准出现裸的 `Vue.createApp(`。
bare = [n for n, s in js_by_file.items() if n != "core.js" and "Vue.createApp(" in s]
chk("Vue app 一律走 mountVue()（裸 createApp 只允许在 core.js）", not bare,
    ("这些文件里有裸的：%s" % bare) if bare else "OK")
chk("core.js 里有 mountVue + onVueError", "function mountVue(" in js_by_file.get("core.js", "")
    and "function onVueError(" in js_by_file.get("core.js", ""))

# ---------------- 11. 全局不许重名（`V-249` 的血） ----------------
# ★ 为什么值得单列：`js/*.js` 是**经典脚本**、共享同一个全局作用域，后加载的文件里
#   一个同名 `function` 会把前面那个**整个盖掉**，而且**一句错都不报**。
#   实测（`V-249`）：`drop.js` 里判扩展名的 `extOf(name)` 盖掉了 `core.js` 里返回
#   `{i,c,l}` 的 `extOf(entry)` —— 于是 `String({...})` 得到 "[object Object]"，
#   所有文件都"没有扩展名"，代码高亮永远 `plaintext`、图标配色一起丢，界面上却
#   只是"看着不对"，控制台干干净净。所以：顶层 `function` / `const|let|var` 一律查重。
#   ★ 认的是**行首无缩进**的声明 —— 组件方法、内部闭包里的同名不算（那些是各自作用域的）。
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

for _t in (tmp_js,):
    _t.unlink(missing_ok=True)

print()
print("失败：%d" % len(fails))
if fails:
    print(json.dumps(fails, ensure_ascii=False, indent=2))
    sys.exit(1)
