# -*- coding: utf-8 -*-
"""dazi 探针（照 `tools/exec内嵌探针.py` 写）：把这个包的**四条路**都真跑一遍。

为什么单独写一个
----------------
`dazi` 是"带内嵌界面的包"（契约 §4.2）：一份网页界面，两种跑法 ——
内嵌时宿主用 `MOSS_UI_EMBED=1` 把它起成**后端进程**（在 stdin/stdout 上说 JSON 行），
独立窗口时走 pywebview 的 JS 桥。这条路最容易坏的是四件事，全都得用真东西验：

  A **静态对账**：页面会调的每个方法后端真的有吗？（少了就是"没有这个方法：X"，整条链当场死）
  B **内嵌协议**：参数形状、一行一个 JSON、出题/计分/落盘真跑一遍（数据目录指到临时目录）
  C **真宿主链路**：`moss.exe :dazi` + `MOSS_UI_EMBED=1`（宿主注入的环境变量才是真的）
  D **命令行那条路**：`moss :dazi stats / reset`（退出码分档）
  E **页面那半**：无头浏览器真渲染 `ui/index.html`，驱动它打几个字，对账
     "变色对不对、HUD 上的数字是不是**后端**给的、参数是不是一个对象"

用法：
    .\\system\\runtimes\\python\\3.12\\python.exe tools\\打字内嵌探针.py

★ 全程只碰临时目录：`MOSS_PLUGIN_DATA_DIR` 指到 `%TEMP%`，最后还会核对
  "真 user_data 里的东西一个字节都没变"（本项目 `V-133` / 探针工具的老规矩）。
"""
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = Path(os.environ.get("DAZI_PKG") or (ROOT / "user_data" / "pkgs" / "dazi"))
HOST = ROOT / "moss.exe"
# ★ 探针要 import 包里的 core/api/embed，别让它顺手在包目录里写 __pycache__
#   （本探针有一条断言就是"包目录里一个字节都没多"）。
sys.dont_write_bytecode = True
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                    # noqa: BLE001
        pass

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]

# ---------------------------------------------------------------- 页面那半的桩
#: 一个"真形状"的假后端：回的字段跟 `core.py` 一模一样，数字故意好认
#: （tick 回 42.0 / 88% / 321，finish 回 52.5 / 96% / 777）——
#: 这样"页面上显示的是后端给的数"就**可断言**了（页面自己算绝算不出这几个数）。
PAGE_STUB = r"""<script>
(function(){
  window.__perr = [];
  window.__calls = [];
  window.addEventListener("error", function(e){ window.__perr.push(String(e.message || e)); });
  window.addEventListener("unhandledrejection", function(e){
    window.__perr.push("unhandledrejection: " + String((e.reason && e.reason.message) || e.reason));
  });
  // ★ 把 Vue 的 errorHandler 挂上：**模板里引用一个不存在的变量**（比如写 `live.wpm`
  //   而 setup 里只 return 了 `g.live`）会让这一整块 render 抛错 —— 而 prod 版 Vue
  //   默认只丢给 console，`window.onerror` 都收不到，页面上就是"那一块凭空不见了"。
  //   这条是拿血换的：本包第一版就是这么坏的（HUD 整块没画出来，而"页内没有报错"却是绿的）。
  if (window.Vue && Vue.createApp){
    var _createApp = Vue.createApp;
    Vue.createApp = function(c){
      var app = _createApp.call(Vue, c);
      app.config.errorHandler = function(e){ window.__perr.push("vue: " + String((e && e.message) || e)); };
      return app;
    };
  }
  var WORDS = ["cat", "dog", "sun"];
  function statsPayload(){
    return {ok:true, embedded:false, apiVersion:1, version:"0.1.0（桩）",
      modes:[{id:"level", label:"闯关", desc:"（桩）一关一关来", timed:false, duration_ms:0},
             {id:"blitz", label:"60 秒挑战", desc:"（桩）", timed:true, duration_ms:60000}],
      levels: Array.from({length: 12}, function(_, i){
        return {level: i + 1, words: 13 + i, target_wpm: 15 + 3 * i, stars: 0}; }),
      max_level:12, cleared:0, stars:{}, modes_stat:{},
      best:{wpm:1.0, acc:1.0, score:1, combo:1},
      totals:{rounds:0, chars:0, keys:0, errors:0, ms:0},
      settings:{auto_next:true, sound:false},
      recent:[], top_mistakes:[],
      bank:{words:[10, 20], code:5, number:"每组 4~7 位"},
      data_dir:"（桩）state/dazi/data", updated:"",
      host:{pid:4242, python:"3.12.0（桩）", cwd:"（桩）"},
      appearance:{theme:"dark", accent:"#3f7dfb"}};
  }
  var R = {
    bootstrap: statsPayload(),
    stats: statsPayload(),
    info: {ok:true, pid:4242, python:"3.12.0（桩）", cwd:"（桩）", embedded:false},
    help: {ok:true, usage:"（桩）"},
    new_round: {ok:true, round_id:"stub-1", mode:"level", level:1, words:WORDS,
                duration_ms:0, target:{wpm:15, acc:0.9}, total:3, started_at:0},
    tick: function(p){ return {ok:true, wpm:42.0, acc:0.875, score:321,
                               combo:(p && p.combo) || 0, elapsed_ms:(p && p.elapsed_ms) || 0,
                               remain_ms:0, over:false}; },
    finish_round: function(){ return {ok:true, round_id:"stub-1", mode:"level", mode_label:"闯关",
      level:1, wpm:52.5, acc:0.96, score:777, stars:2, passed:true, target:15, elapsed_ms:8000,
      chars:9, keys:10, errors:1, words:3, best_combo:2,
      new_best:{wpm:true, score:false, combo:false}, level_up:true, cleared:1, unlocked:2,
      best:{wpm:52.5, score:777, combo:2, before:{wpm:1, score:1, combo:1}},
      top_mistakes:[{ch:"x", n:1}], totals:{rounds:1, chars:9, keys:10, errors:1, ms:8000}}; },
    save_settings: function(){ return {ok:true, settings:{auto_next:true, sound:true}}; },
    reset_stats: function(){ var s = statsPayload(); s.totals = {rounds:0, chars:0, keys:0, errors:0, ms:0}; return s; }
  };
  window.moss = {
    env: {embedded:false},
    on: function(){ return function(){}; },
    call: function(method, params){
      window.__calls.push({method:method, params: params === undefined ? null : params});
      var v = R[method];
      var got = (typeof v === "function") ? v(params || {}) : v;
      return Promise.resolve(got === undefined ? {ok:true} : got);
    }
  };
})();
</script>"""

#: 驱动：等 Vue 挂上 → 点「开始练习」→ 真敲键盘（dispatchEvent）→ 对账 DOM 与调用形状
PAGE_DRIVER = r"""<script>
(async function(){
  var RES = [];
  function chk(name, ok, detail){ RES.push({name:name, ok:!!ok, detail:String(detail == null ? "" : detail)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  function q(sel){ return document.querySelector(sel); }
  function txt(sel){ var e = q(sel); return e ? e.textContent.replace(/\s+/g, " ").trim() : ""; }
  function key(k){ window.dispatchEvent(new KeyboardEvent("keydown", {key:k, bubbles:true, cancelable:true})); }
  // ★ 页面是**异步**渲染的（Vue 的更新在微任务里、无头浏览器还有虚拟时间那一套）：
  //   固定 sleep 会让"其实画出来了"被误判成失败。所以一律**轮询等待**，并把时间线记下来
  //   （真要失败时，日志里能看出"到底是没画，还是慢了一拍"）。
  function waitFor(sel, ms){
    var t0 = Date.now();
    return new Promise(function(res){
      (function tick(){
        if (document.querySelector(sel)) return res(true);
        if (Date.now() - t0 > ms) return res(false);
        setTimeout(tick, 25);
      })();
    });
  }
  var T0 = Date.now(), TL = [];
  function waitText(sel, needle, ms){
    var t0 = Date.now();
    return new Promise(function(res){
      (function tick(){
        if (txt(sel).indexOf(needle) >= 0) return res(true);
        if (Date.now() - t0 > ms) return res(false);
        setTimeout(tick, 25);
      })();
    });
  }
  function snap(label){
    var m = document.querySelector("main");
    TL.push({at: label, ms: Date.now() - T0, main: (m && m.className) || "（没有 main）",
             strip: !!document.querySelector(".stage .strip"),
             hud: !!document.querySelector('[data-k="wpm"]'),
             len: document.body.innerHTML.length, calls: window.__calls.length});
  }

  for (var i = 0; i < 200 && !q(".mode-card"); i++) await sleep(50);
  chk("页面挂上了（模式卡片画出来了）", !!q(".mode-card"), txt(".mode-card"));
  await sleep(300);                                   // 等 bootstrap 的 promise 落地
  var by = {};
  function collect(){
    by = {};
    window.__calls.forEach(function(c){ (by[c.method] = by[c.method] || []).push(c.params); });
  }
  collect();
  chk("挂载时自己就问了一次 bootstrap（还没等人点）", !!by.bootstrap,
      JSON.stringify(window.__calls.map(function(c){ return c.method; })));
  chk("页面画出了 12 个关卡格 + 模式卡片", document.querySelectorAll(".lv").length >= 12,
      "关卡格 " + document.querySelectorAll(".lv").length + " 个");
  snap("挂载后");

  q('[data-k="start"]').click();
  var playing = await waitFor(".stage .strip", 4000);
  snap("点开始之后");
  chk("点「开始练习」进了打字页（题画出来了）", playing, "等到=" + playing + " 时间线=" + JSON.stringify(TL));
  // HUD 上的数要**等后端回话**（页面自己半秒问一次 tick）—— 等不到才算失败
  var hudOk = await waitText('[data-k="wpm"]', "42.0", 5000);
  chk("★ HUD 上的数字是**后端**给的（桩回 42.0 / 88% / 321）",
      hudOk && txt('[data-k="acc"]').indexOf("88") === 0 && txt('[data-k="score"]').indexOf("321") === 0,
      "WPM=" + txt('[data-k="wpm"]') + " ACC=" + txt('[data-k="acc"]') + " 分=" + txt('[data-k="score"]'));
  chk("题画在条上（当前词 = cat）", txt(".word.now") === "cat", "now=" + txt(".word.now"));

  key("c"); key("a"); await sleep(150);
  chk("打对的字符变绿（.word.now .ch.ok = 2）",
      document.querySelectorAll(".word.now .ch.ok").length === 2,
      "ok=" + document.querySelectorAll(".word.now .ch.ok").length);
  chk("光标停在下一个字符上（.ch.cur = 1）",
      document.querySelectorAll(".word.now .ch.cur").length === 1, "");

  key("t"); await sleep(200);
  chk("一个词打完自动跳下一个（现在是 dog）", txt(".word.now") === "dog", "now=" + txt(".word.now"));
  key("x"); await sleep(150);
  chk("打错变红（.word.now .ch.bad = 1）", document.querySelectorAll(".word.now .ch.bad").length === 1,
      "bad=" + document.querySelectorAll(".word.now .ch.bad").length);
  chk("打错把连击清零（HUD 连击 = 0）", txt('[data-k="combo"]').indexOf("0") === 0,
      "连击=" + txt('[data-k="combo"]'));
  key("Backspace"); await sleep(150);
  chk("退格能把错字符删掉", document.querySelectorAll(".word.now .ch.bad").length === 0, "");

  key("d"); key("o"); key("g"); await sleep(200);
  key("s"); key("u"); key("n"); 
  var verdict = await waitFor('[data-k="verdict"]', 4000);
  snap("三个词打完之后");
  chk("词打完了自动结算（出现结算面板）", verdict, "verdict=" + txt('[data-k="verdict"]') +
      " 时间线=" + JSON.stringify(TL.slice(-2)));
  chk("结算数字也是后端给的（52.5 / 96% / 777）",
      txt('[data-k="done-wpm"]').indexOf("52.5") === 0 && txt('[data-k="done-acc"]').indexOf("96") === 0 &&
      txt('[data-k="done-score"]').indexOf("777") === 0,
      "WPM=" + txt('[data-k="done-wpm"]') + " ACC=" + txt('[data-k="done-acc"]') +
      " 分=" + txt('[data-k="done-score"]'));
  chk("星级按后端的 stars=2 画（★★☆）", txt('[data-k="stars"]') === "★★☆", txt('[data-k="stars"]'));
  chk("过关文案也在（passed=true）", txt('[data-k="verdict"]').indexOf("过关") >= 0, txt('[data-k="verdict"]'));

  collect();
  function shape(name, want){
    var got = by[name] ? by[name][0] : undefined;
    var isObj = got && typeof got === "object" && !Array.isArray(got);
    var keys = isObj ? Object.keys(got).sort().join(",") : String(got);
    chk(name + " 的参数是**一个对象**且字段对（" + want + "）", isObj && keys === want, "收到：" + keys);
  }
  shape("new_round", "level,mode");
  shape("tick", "chars,combo,elapsed_ms,errors,keys,round_id");
  shape("finish_round", "best_combo,chars,elapsed_ms,errors,keys,mistakes,round_id,words");
  chk("★ 没有哪一次是把参数当**位置参数**发出去的（全是对象）",
      window.__calls.every(function(c){ return c.params && typeof c.params === "object"; }),
      JSON.stringify(window.__calls.map(function(c){ return c.method; })));
  chk("一局走完问过后端这几步：bootstrap → new_round → tick → finish_round → stats",
      ["bootstrap", "new_round", "tick", "finish_round", "stats"].every(function(m){ return !!by[m]; }),
      JSON.stringify(Object.keys(by)));
  chk("页面里没有报错", !window.__perr.length, (window.__perr[0] || "").slice(0, 140));

  var bad = RES.filter(function(r){ return !r.ok; });
  var box = document.createElement("pre");
  box.id = "probe";
  box.textContent = JSON.stringify({ok: bad.length === 0, n: RES.length, bad: bad.length,
                                    perr: window.__perr, timeline: TL, res: RES});
  document.body.appendChild(box);
  document.title = (bad.length === 0 && !window.__perr.length)
    ? ("PAGE-OK " + RES.length) : ("PAGE-FAIL " + (bad.length + window.__perr.length));
})();
</script>"""


# ---------------------------------------------------------------- 小工具
def browser():
    for b in BROWSERS:
        if Path(b).is_file():
            return b
    return None


def file_fingerprint(d):
    """目录里每个文件的 sha1（只看内容，不看 mtime）—— 用来证"真数据一个字节都没变"。

    `__pycache__` / `*.pyc` 不算：那是 import 的副产品，不是"包多写了数据"。
    """
    out = {}
    d = Path(d)
    if not d.is_dir():
        return out
    for p in sorted(d.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(d))
        if "__pycache__" in rel or rel.endswith(".pyc"):
            continue
        try:
            out[rel] = hashlib.sha1(p.read_bytes()).hexdigest()
        except OSError:
            out[rel] = "?"
    return out


def run(cmd, env=None, timeout=90, stdin_text=""):
    """跑一条命令，把它的 stdout+stderr **落进临时文件**再读回来。

    ★ 为什么不用 `capture_output=True`：这个会话的沙箱**不许开管道** ——
      subprocess 一建 pipe 就 `PermissionError: [WinError 5] 拒绝访问`
      （Node 的 spawn 默认 stdio:'pipe' 也一样，这是沙箱的已知边界）。
      改用"重定向到文件"，语义完全一样：stdin 给一个文件，写完就是 EOF，
      所以"stdin 关了进程就自己退出"这件事照样验得到。
    """
    d = scratch("moss_dazirun_")
    try:
        inp, outp = d / "in.txt", d / "out.txt"
        inp.write_text(stdin_text or "", encoding="utf-8")
        with open(inp, "r", encoding="utf-8") as fi, \
                open(outp, "w", encoding="utf-8") as fo:
            p = subprocess.run([str(x) for x in cmd], stdin=fi, stdout=fo,
                               stderr=subprocess.STDOUT, env=env, timeout=timeout,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, outp.read_text(encoding="utf-8", errors="replace")
    finally:
        shutil.rmtree(d, ignore_errors=True)


def scratch(tag):
    """造一个临时目录。

    ★ **不能用 `tempfile.mkdtemp()`**：它是用 `os.mkdir(name, 0o700)` 建的，而在这台
      机器上那样建出来的目录**连自己都写不进去**（写文件报 PermissionError / WinError 5，
      事后 `os.chmod` 也拒 —— 见避坑库）。自己用**默认 mode** 建就没事。
    """
    base = Path(tempfile.gettempdir())
    for _ in range(50):
        d = base / ("%s%d_%x" % (tag, os.getpid(), random.randrange(1 << 24)))
        try:
            d.mkdir()
            return d
        except FileExistsError:
            continue
    raise RuntimeError("造不出临时目录：%s" % base)


def main():
    res = []

    def chk(name, ok, detail=""):
        res.append((name, bool(ok), detail))
        print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + detail) if detail else ""))

    if not PKG.is_dir():
        print("[错误] 找不到这个包：%s" % PKG)
        return 1
    if not HOST.is_file():
        print("[提示] 没有 moss.exe，C/D 两段（真宿主链路）会跳过 —— 先 tools\\build.py")

    tmp = scratch("moss_daziprobe_")
    real_state = ROOT / "user_data" / "state" / "dazi"
    real_before = file_fingerprint(real_state)
    pkg_before = file_fingerprint(PKG)
    env = dict(os.environ)
    env["MOSS_PLUGIN_DATA_DIR"] = str(tmp)
    env["MOSS_UI_EMBED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    os.environ.update({"MOSS_PLUGIN_DATA_DIR": str(tmp), "MOSS_UI_EMBED": "1"})

    # ================================================================ A
    print("=" * 74)
    print("A：静态对账（页面会调的方法，后端真的有吗 / 声明跟事实一致吗）")
    print("=" * 74)
    manifest = json.loads((PKG / "pkg.json").read_text(encoding="utf-8"))
    ui = (PKG / manifest["ui"]["embed"]).read_text(encoding="utf-8")
    appjs = (PKG / "ui" / "app.js").read_text(encoding="utf-8")
    chk("id 合法（小写字母开头，≤32）", re.match(r"^[a-z][a-z0-9_-]{0,31}$", manifest["id"]) is not None,
        manifest["id"])
    chk("声明了内嵌界面 ui.embed", bool((manifest.get("ui") or {}).get("embed")),
        json.dumps(manifest.get("ui"), ensure_ascii=False))
    chk("界面文件真的在", (PKG / manifest["ui"]["embed"]).is_file(), manifest["ui"]["embed"])
    chk("入口文件真的在", (PKG / manifest["entry"]["file"]).is_file(), manifest["entry"]["file"])
    chk("没声明 drop（这包不收拖入，声明了就是假能力）", "drop" not in manifest, "")
    # ★ 别用 `ui.index("app.js")` 这种朴素判断 —— 顶上那句注释里就写着"垫片必须在 app.js
    #   之前"，先命中的是**注释**（`V-195` 那类坑的同族）。只认真正的 <script src=…> 标签。
    m_shim = re.search(r'<script[^>]*src=["\']moss-embed\.js["\']', ui)
    m_app = re.search(r'<script[^>]*src=["\']app\.js["\']', ui)
    chk("★ 垫片在 index.html 里、且排在 app.js 之前",
        bool(m_shim) and bool(m_app) and m_shim.start() < m_app.start(),
        "垫片@%s app@%s" % (m_shim.start() if m_shim else "没有",
                            m_app.start() if m_app else "没有"))
    sys.path.insert(0, str(PKG))
    for _m in ("core", "api", "embed"):
        sys.modules.pop(_m, None)
    import api as api_mod                                              # noqa: E402
    called = sorted(set(re.findall(r"moss\.call\(\s*['\"]([A-Za-z0-9_]+)['\"]", appjs)))
    missing = [m for m in called if not callable(getattr(api_mod.Api, m, None))]
    chk("★ 页面会调的方法后端都有（少了就是「没有这个方法」）", not missing,
        ("缺：%s" % missing) if missing else "页面会调 %d 个：%s" % (len(called), "、".join(called)))
    no_params = [m for m in called if getattr(api_mod.Api, m).__code__.co_argcount < 2]
    chk("★ 这些方法都收得下那一个参数（垫片只传一个对象）", not no_params, str(no_params))
    chk("界面里没有裸的 file:// 外链 / CDN（离线要能跑）",
        not re.search(r'(src|href)=["\']https?://', ui), "")
    # ★ 独立窗口那条路的入口：`moss :dazi` 走的就是它。这里只验"import 得动、函数在"
    #   —— 关键是 **import 时不许碰 webview**（碰了就等于没窗口也要先把 pywebview 拉起来）。
    try:
        import gui_web                                                # noqa: E402
        ok_win = callable(getattr(gui_web, "run_window", None))
    except Exception as e:                                           # noqa: BLE001
        ok_win, _why = False, "%s: %s" % (type(e).__name__, e)
    chk("A 独立窗口那条路的入口 import 得动（`moss :dazi` 用）", ok_win, "" if ok_win else _why)

    # ================================================================ B
    print()
    print("=" * 74)
    print("B：内嵌协议 + 一局真跑（进程内喂 JSON 行，数据目录 = 临时目录）")
    print("=" * 74)
    import embed as embed_mod                                          # noqa: E402
    import core as core_mod                                            # noqa: E402
    em = embed_mod.Embedded()
    chk("B 认得出自己该跑内嵌（MOSS_UI_EMBED=1）", embed_mod.is_embedded() is True, "")

    def ask(method, params=None):
        return em.handle(json.dumps({"id": 1, "method": method, "params": params or {}},
                                    ensure_ascii=False))

    r = ask("bootstrap")
    b = r.get("result") or {}
    need = ("apiVersion", "modes", "levels", "max_level", "cleared", "settings", "best", "totals",
            "bank", "data_dir", "embedded", "host")
    chk("B bootstrap 回了 ok 且字段齐", r.get("ok") is True and all(k in b for k in need),
        "缺：" + str([k for k in need if k not in b]))
    chk("B bootstrap 自证是内嵌", b.get("embedded") is True, str(b.get("embedded")))
    chk("B 数据目录落在**临时**目录里（没碰用户真数据）", str(tmp) in str(b.get("data_dir")),
        str(b.get("data_dir")))
    chk("B 四个模式都在", len(b.get("modes") or []) == 4,
        "、".join(m.get("id", "?") for m in (b.get("modes") or [])))

    r = ask("new_round", {"mode": "level", "level": 1})
    rd = r.get("result") or {}
    words = rd.get("words") or []
    chk("B new_round 出题（数量 = core.level_word_count(1)）",
        r.get("ok") is True and len(words) == core_mod.level_word_count(1),
        "拿到 %d 个" % len(words))
    chk("B 题不紧挨着重复", all(words[i] != words[i + 1] for i in range(len(words) - 1)), "")
    chk("B 关卡目标跟着关卡走（第 1 关 15 WPM）", (rd.get("target") or {}).get("wpm") == 15,
        json.dumps(rd.get("target"), ensure_ascii=False))

    r = ask("tick", {"round_id": rd.get("round_id"), "elapsed_ms": 60000, "chars": 100,
                     "keys": 110, "errors": 10, "combo": 3})
    t = r.get("result") or {}
    chk("B tick 的 WPM 算得对（100 字 / 1 分钟 = 20.0）", abs(float(t.get("wpm") or 0) - 20.0) < 0.05,
        str(t.get("wpm")))
    chk("B tick 的准确率算得对（100/110 = 90.9%）", abs(float(t.get("acc") or 0) - 0.9091) < 0.001,
        str(t.get("acc")))
    chk("B 关卡模式没有剩余时间（不计时）", t.get("remain_ms") == 0 and t.get("over") is False,
        json.dumps(t, ensure_ascii=False)[:80])

    # 玩一局：把这一关的词全"打对"
    chars = sum(len(w) for w in words)
    r = ask("finish_round", {"round_id": rd.get("round_id"), "elapsed_ms": 30000,
                             "keys": chars + 2, "errors": 2, "chars": chars, "words": len(words),
                             "best_combo": 5, "mistakes": [{"want": "t", "n": 2}]})
    fin = r.get("result") or {}
    chk("B finish_round 结算成功", r.get("ok") is True, json.dumps(r, ensure_ascii=False)[:120])
    chk("B 过关判定 + 星级（30 秒打完 %d 字 → 够第 1 关）" % chars,
        fin.get("passed") is True and int(fin.get("stars") or 0) >= 1,
        "wpm=%s stars=%s" % (fin.get("wpm"), fin.get("stars")))
    chk("B 结算顺手解锁下一关", fin.get("unlocked") == 2 and fin.get("level_up") is True,
        "unlocked=%s level_up=%s" % (fin.get("unlocked"), fin.get("level_up")))
    stats_file = tmp / "data" / "stats.json"
    chk("★ B 成绩真落盘了（临时目录里出现 data/stats.json）", stats_file.is_file(), str(stats_file))
    if stats_file.is_file():
        saved = json.loads(stats_file.read_text(encoding="utf-8"))
        chk("B 盘上那局记得对（recent[0] 的 WPM 和结算一致）",
            bool(saved.get("recent")) and saved["recent"][0]["wpm"] == fin.get("wpm"),
            json.dumps((saved.get("recent") or [{}])[0], ensure_ascii=False)[:110])
        chk("B 易错字符也记下来了", (saved.get("mistakes") or {}).get("t") == 2,
            json.dumps(saved.get("mistakes"), ensure_ascii=False))
        chk("B 存档是完整 JSON（原子写没写坏）", isinstance(saved.get("totals"), dict), "")
    r = ask("stats")
    chk("B stats 里能看到刚才那局", ((r.get("result") or {}).get("totals") or {}).get("rounds") == 1,
        str(((r.get("result") or {}).get("totals"))))

    r = ask("save_settings", {"settings": {"sound": True}})
    chk("B save_settings 存下来了", (r.get("result") or {}).get("settings", {}).get("sound") is True,
        json.dumps(r.get("result"), ensure_ascii=False)[:90])
    chk("B 设置真写进盘里了（重新 bootstrap 也能看到）",
        ((ask("bootstrap").get("result") or {}).get("settings") or {}).get("sound") is True, "")

    chk("B reset_stats 不带 confirm 会被拒（危险动作要显式确认）",
        ask("reset_stats", {}).get("result", {}).get("ok") is False, "")
    chk("B 带了 confirm 才清", (ask("reset_stats", {"confirm": True}).get("result") or {}).get("totals", {}).get("rounds") == 0, "")

    print()
    print("=" * 74)
    print("C：坏输入 / 未知方法 —— 只能回一句 ok:false，不能把循环打断")
    print("=" * 74)
    chk("C 未知方法回 ok:false", ask("不存在的名字").get("ok") is False, "")
    chk("C 下划线开头的方法不给调（内部件）", ask("_private").get("ok") is False, "")
    bad = em.handle("这不是 JSON")
    chk("C 坏 JSON 回一句人话（不抛）",
        bad.get("ok") is False and "JSON" in str(bad.get("error")), str(bad)[:70])
    chk("C 模式名不认识 → 回 ok:false 而不是崩",
        ask("new_round", {"mode": "没有这个模式"}).get("result", {}).get("ok") is False, "")
    chk("C 出过错之后还能继续干活", ask("bootstrap").get("ok") is True, "")

    # ================================================================ D
    host_ok = False
    if HOST.is_file():
        print()
        print("=" * 74)
        print("D：**真起一个宿主进程**（`moss.exe :dazi` + MOSS_UI_EMBED=1 —— 就是界面点「运行」那条）")
        print("   ★ 为什么要经 moss.exe：宿主注入的环境变量 / 数据目录才是真的口径")
        print("=" * 74)
        reqs = [{"id": 11, "method": "bootstrap", "params": {}},
                {"id": 12, "method": "new_round", "params": {"mode": "blitz"}},
                {"id": 13, "method": "tick", "params": {"round_id": "x", "elapsed_ms": 1000,
                                                        "keys": 5, "errors": 0, "chars": 5}},
                {"id": 14, "method": "info", "params": {}}]
        code, out = run([HOST, ":dazi"], env=env, timeout=120,
                        stdin_text="".join(json.dumps(q) + "\n" for q in reqs))
        raw = (out or "").splitlines()
        got = {}
        for ln in raw:
            if ln.lstrip().startswith("{"):
                try:
                    got[json.loads(ln).get("id")] = json.loads(ln)
                except ValueError:
                    got["坏行"] = None
        junk = [x for x in raw if x.strip() and not x.lstrip().startswith("{")]
        json_lines = [x for x in raw if x.lstrip().startswith("{")]
        chk("D 四条请求都回了（按 id 对上）", set(got) >= {11, 12, 13, 14},
            "拿到 id：" + str(sorted(k for k in got if isinstance(k, int))))
        chk("D **每一行以 `{` 开头的都是合法 JSON**（协议没被撕）",
            bool(json_lines) and all(json.loads(x) for x in json_lines),
            repr(raw)[:160])
        chk("D bootstrap 那条 ok 且自证内嵌",
            (got.get(11) or {}).get("ok") is True and
            ((got.get(11) or {}).get("result") or {}).get("embedded") is True,
            json.dumps(got.get(11), ensure_ascii=False)[:120])
        chk("D 出题那条也通了（经宿主这一路）", (got.get(12) or {}).get("ok") is True, "")
        chk("D 我们那几行 `[dazi] …` 日志确实到了管道里（给「命令行」页看的）",
            any("[dazi]" in j for j in junk), "非 JSON 行 %d 条，例如：%s" %
            (len(junk), (junk[0][:70] if junk else "")))
        chk("D stdin 读完（EOF）就自己退出，退出码 0", code == 0, str(code))
        host_ok = True

        print()
        print("=" * 74)
        print("E：命令行那条路（退出码分档 —— 0 成功 / 2 用法错）")
        print("=" * 74)
        # ★ 这里必须**把 MOSS_UI_EMBED 摘掉**：留着的话宿主会把它一起传下去，
        #   包一看到就走"内嵌模式"（不开窗、在 stdio 上等人喂 JSON）—— 参数和退出码
        #   全都不作数，E 这一整段就是在白验（第一版就是这么被骗过去的）。
        env_cli = {k: v for k, v in env.items() if k != "MOSS_UI_EMBED"}
        c, out = run([HOST, ":dazi", "stats"], env=env_cli, timeout=120)
        chk("E `moss :dazi stats` 退出码 0", c == 0, "code=%s out=%r" % (c, out[:70]))
        chk("E stats 打出了成绩总览", "打字练习" in out and "最佳" in out,
            out[:200].replace("\n", " | "))
        c, out = run([HOST, ":dazi", "reset"], env=env_cli, timeout=120)
        chk("E `reset` 不带 --yes → 用法错退出码 2（什么都没动）", c == 2,
            "code=%s out=%r" % (c, out[:200]))
        chk("E 那句提示告诉用户怎么真清", "--yes" in out, out[:120].replace("\n", " | "))
        c, out = run([HOST, ":dazi", "不认识的参数"], env=env_cli, timeout=120)
        chk("E 不认识的参数 → 退出码 2 + 打用法", c == 2 and "moss :dazi" in out, "code=%s" % c)

    # ================================================================ F
    print()
    print("=" * 74)
    print("F：**页面那半**（无头浏览器真渲染 ui/index.html，驱动它真打几个字）")
    print("   ★ 验的是：变色对不对、HUD/结算上的数字是不是**后端**给的、参数是不是一个对象")
    print("=" * 74)
    exe = browser()
    page_ok, page_n, page_bad = False, 0, 1
    if not exe:
        # ★ "没验到"就报"没验到"：以前这种跳过不进 res，结论会照样报"全过"（假绿）。
        print("  [没验] 这台机器上找不到 Edge/Chrome —— 页面那半**没验**")
        res.append(("F 页面那半（没验：找不到浏览器）", False, "装个 Edge/Chrome 再跑"))
    else:
        dst = tmp / "ui"
        shutil.copytree(PKG, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        page = dst / "ui" / "index.html"
        html = page.read_text(encoding="utf-8")
        if '<script src="moss-embed.js"></script>' not in html:
            print("  [失败] index.html 里没有垫片那一行 —— 页面侧没接上")
            res.append(("F 页面那半（垫片那行没了）", False, "index.html 里找不到垫片 <script>"))
        else:
            html = html.replace('<script src="moss-embed.js"></script>', PAGE_STUB)
            html = html.replace("</body>", PAGE_DRIVER + "\n</body>")
            page.write_text(html, encoding="utf-8")
            prof = tmp / "_prof_page"
            cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                   "--no-default-browser-check", "--user-data-dir=" + str(prof),
                   "--allow-file-access-from-files", "--window-size=1280,900",
                   "--virtual-time-budget=20000", "--dump-dom",
                   "file:///" + str(page).replace("\\", "/")]
            # ★ 同上：不开管道 —— `--dump-dom` 的结果落到文件里再读（stderr 单独一个文件）
            domf, errf = tmp / "dom.html", tmp / "browser.err"
            with open(domf, "w", encoding="utf-8", errors="replace") as fo, \
                    open(errf, "w", encoding="utf-8", errors="replace") as fe:
                subprocess.run(cmd, stdout=fo, stderr=fe, stdin=subprocess.DEVNULL, timeout=240,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            dom = domf.read_text(encoding="utf-8", errors="replace")
            err = errf.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'(?s)<pre id="probe">(.*?)</pre>', dom)
            title = (re.search(r"<title>(.*?)</title>", dom, re.S) or [None, ""])[1].strip()
            if not m:
                # ★ 这里**必须**记一条失败：以前这种"没跑到最后"只在屏幕上打一行、
                #   不进 res，于是结论照样报"全过" —— 假绿（比没验还糟）。
                print("  ✗ 页面那半没跑到最后（读不到结论）—— 标题=%s" % (title or "（空）"))
                why = "标题=%s" % (title or "（空）")
                if not (dom or "").strip():
                    print("     DOM 是空的 ⇒ 浏览器根本没起来。它的 stderr 头几行：")
                    for _ln in err.splitlines()[:4]:
                        print("       " + _ln[:150])
                    why = "浏览器没起来（DOM 是空的）：" + (err.splitlines() or ["?"])[0][:90]
                res.append(("F 页面那半（没跑到最后）", False, why))
            else:
                import html as _html
                box = json.loads(_html.unescape(m.group(1)))
                for it in box["res"]:
                    print("  %s %s%s" % ("OK  " if it["ok"] else "FAIL", it["name"],
                                         ("   ← " + it["detail"]) if (not it["ok"] and it["detail"]) else ""))
                if box["perr"]:
                    print("  页面报错：%s" % box["perr"][:2])
                page_ok = bool(box["ok"] and not box["perr"])
                page_n, page_bad = box["n"], box["bad"]
                if not page_ok:
                    print("  时间线（页面几时画到哪一步）：")
                    for it in (box.get("timeline") or [])[:8]:
                        print("    %5dms  main=%-12s 有strip=%-5s 有HUD=%-5s 长度 %-7s 调用 %s  ← %s"
                              % (it.get("ms", 0), it.get("main", "?"), it.get("strip", "?"),
                                 it.get("hud", "?"), it.get("len", "?"), it.get("calls", "?"),
                                 it.get("at", "")))
                res.append(("F 页面那半（%d 条）" % page_n, page_ok,
                            "失败 %d" % page_bad if not page_ok else ""))

    # ================================================================ G
    print()
    print("=" * 74)
    print("G：**用户真数据没被碰**")
    print("=" * 74)
    chk("G 真·user_data/state/dazi 一个文件都没变", file_fingerprint(real_state) == real_before,
        "%d → %d 个文件" % (len(real_before), len(file_fingerprint(real_state))))
    pkg_after = file_fingerprint(PKG)
    chk("G 包目录里也没多出东西（数据不写包目录）", pkg_after == pkg_before,
        "多了：" + str(sorted(set(pkg_after) - set(pkg_before))[:4]))

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 74)
    badN = [x for x in res if not x[1]]
    print("结论：%s（%d 条，失败 %d）%s" %
          ("✅ 全过" if not badN else "✗ 有不对的", len(res), len(badN),
           "" if host_ok else "  [注] 没跑真宿主那两段"))
    for name, _ok, detail in badN:
        print("   ✗ %s %s" % (name, detail))
    return 0 if not badN else 1


if __name__ == "__main__":
    sys.exit(main())
