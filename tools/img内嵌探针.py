# -*- coding: utf-8 -*-
"""img 界面探针（`V-225`）：把 img **两条路都跑一遍** —— 内嵌后端 + 页面那侧。

为什么单独写一个
----------------
img 原来是"自己开一扇 pywebview 窗"的包（`gui_web.py`），页面里的桥直接调
`window.pywebview.api.<方法>(位置参数)`。改成能内嵌之后，多了一条路：宿主用
`MOSS_UI_EMBED=1` 把它起成**后端进程**，在 stdin/stdout 上说 JSON 行。

这条路上最容易坏的四件事：
  ① **参数形状**：垫片两种环境都只传**一个对象** ⇒ `Api` 必须是 `(params=None)`，
     页面侧也得按字段名发（`ui/src/bridge.js` 那张表）；
  ② **stdout 干净**：宿主按行读 JSON，混进多行日志就把协议撕了；
  ③ **拖放**：内嵌时真路径只有宿主有 ⇒ 页面必须收宿主的 `drop` 事件、把它 `push_drop`
     塞回后端，才能复用原来那条 take_drop 管线；
  ④ **别碰用户真数据**：整个探针把 `MOSS_PLUGIN_DATA_DIR` 指到临时目录。

分两半：
  A–E：**后端**（进程内喂 JSON 行 + 真起 `moss.exe :img` 走一遍宿主链路）；
  F  ：**页面**（无头浏览器真渲染 img 的 ESM 页面，驱动它去调后端，把每次调用的
       **参数形状**记下来对账；顺带验内嵌时"宿主 drop → push_drop"这条路）。

用法：
    .\\system\\runtimes\\python\\3.12\\python.exe tools\\img内嵌探针.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "system" / "pkgs" / "img"
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                                    # noqa: BLE001
        pass

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]

#: 页面那半的桩：照垫片"独立窗口"那条分支的行为（`moss.call` → 后端一个对象），
#: 并把每次调用的 `(方法, 参数)` 记下来 —— 这就是"参数形状"的对账依据。
PAGE_STUB = r"""<script>
(function(){
  window.__perr = [];
  window.addEventListener("error", function(e){ window.__perr.push(String(e.message || e)); });
  window.addEventListener("unhandledrejection", function(e){
    window.__perr.push("unhandledrejection: " + String((e.reason && e.reason.message) || e.reason));
  });
  window.__calls = [];
  var ACCENT = {accent:"#0078d4", "accent-fg":"#ffffff", "accent-press":"#0065b3",
                ring:"rgba(0,120,212,.45)", "field-focus":"rgba(0,120,212,.15)"};
  var R = {
    bootstrap: {ok:true, apiVersion:1, embedded:true, config:{save_mode:"separate",
        output_format:"jpg", quality:80, width:"", ico_sizes:[], output_dir:"", source_filter:{},
        history:[]},
      history:[], sourceDir:"D:\\stub", scan:{ok:true, dir:"D:\\stub", files:[]},
      dataDir:"（桩）", formats:["jpg","png","webp","ico"],
      saveModes:["separate","source","source_delete"], icoSizes:[16,32,48,256],
      supportedExts:[".jpg",".png",".webp"],
      maxExpand:50, thumbLimit:100, thumbBox:240, historyLimit:20,
      theme:"light", accent:ACCENT, log:""},
    scan: {ok:true, dir:"D:\\stub", files:[]},
    scan_files: {ok:true, files:[]},
    thumbs: {ok:true, thumbs:[]},
    file_info: {ok:true, info:{path:"D:\\stub\\a.png", exists:true}},
    check_path: {ok:true, path:"D:\\stub", isdir:true, isfile:false, parent:"D:"},
    open_file: {ok:true}, reveal: {ok:true, opened:"D:\\stub", fellBack:false},
    pick_dir: {ok:true, path:""}, pick_files: {ok:true, files:[]},
    start: {ok:true, job:"j1", history:[], outputDir:"D:\\stub\\out"},
    poll: {ok:true, running:false, done:true, total:1, processed:1, errors:0, log:"（桩）"},
    cancel: {ok:true}, take_drop: {ok:true, pending:false},
    push_drop: {ok:true}, help: {ok:true, usage:"（桩）", formats:{}, description:""},
    copy: {ok:true}, report_error: {ok:true}, set_title: {ok:true}, save_config: {ok:true}
  };
  /* ★ 页面把脚本异常报回后端（`report_error`）—— 桩里得**留下来**：
     不然"boot 中途炸了"一点痕迹都没有（这一版就是靠它查出来的）。 */
  window.__reported = [];
  R.report_error = function(p){
    window.__reported.push(String((p && p.text) || ""));
    return {ok:true};
  };
  /* ★ 统一回一手：值是对象就直接当结果，是函数就**调用它**再当结果。
     上面那版 `Promise.resolve(R[method])` 对函数是"把函数本身当结果"—— 于是
     `report_error` 那个桩永远不会被调用，`__reported` 一直是空，**"boot 没报错"这条断言
     就成了永远为真的假绿**（差点又骗过我自己）。 */
  function reply(method, params){
    var v = R[method];
    if (typeof v === "function") return Promise.resolve(v(params));
    return Promise.resolve(v || {ok:true});
  }
  window.pywebview = {api: new Proxy({}, {get: function(_t, name){
    if (typeof name !== "string") return undefined;
    return function(params){ window.__calls.push({method:name, params:params});
                             return reply(name, params); };
  }})};
  window.moss = {env:{embedded:false}, on:function(){return function(){};},
    call:function(method, params){
      window.__calls.push({method:method, params:params});
      return reply(method, params);
    }};
})();
</script>"""

PAGE_DRIVER = r"""<script>
(async function(){
  var RES = [];
  function chk(name, ok, detail){ RES.push({name:name, ok:!!ok, detail:String(detail == null ? "" : detail)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  for (var i = 0; i < 120 && !window.__img; i++) await sleep(60);
  await sleep(400);
  var img = window.__img;
  if (!img){
    RES.push({name:"页面挂上了（window.__img）", ok:false, detail:"等不到 __img"});
  } else {
    var atMount = window.__calls.length;
    function shape(name, want){
      var hit = window.__calls.filter(function(c){ return c.method === name; })[0];
      var got = hit ? hit.params : undefined;
      var isObj = got && typeof got === "object" && !Array.isArray(got);
      var keys = isObj ? Object.keys(got).sort().join(",") : String(got);
      chk(name + " 的参数是**一个对象**且字段对（" + want + "）", isObj && keys === want,
          "收到：" + keys);
    }
    chk("页面挂载时自己就问了一次 bootstrap（还没等人点）", atMount >= 1, "挂载时调用 " + atMount + " 次");
    shape("bootstrap", "");
    // 几个真交互：换目录 / 取缩略图 / 问文件详情 / 开始处理
    if (img.state && img.state.api){
      try { await img.state.api.scan("D:\\\\stub"); } catch(e){}
      try { await img.state.api.thumbs(["D:\\\\stub\\\\a.png"]); } catch(e){}
      try { await img.state.api.file_info("D:\\\\stub\\\\a.png"); } catch(e){}
      try { await img.state.api.check_path("D:\\\\stub"); } catch(e){}
      try { await img.state.api.reveal("D:\\\\stub\\\\out"); } catch(e){}
      try { await img.state.api.help(); } catch(e){}
      try { await img.state.api.start({mode:"folder", source_dir:"D:\\\\stub"}); } catch(e){}
      await sleep(200);
    }
    shape("scan", "dir");
    shape("thumbs", "paths");
    shape("file_info", "path");
    shape("check_path", "path");
    shape("reveal", "target");
    shape("help", "");
    shape("start", "payload");
    chk("★ 没有哪一次是把参数当**位置参数**发出去的（全是对象）",
        window.__calls.every(function(c){ return c.params && typeof c.params === "object"; }),
        JSON.stringify(window.__calls.map(function(c){ return c.method; })).slice(0, 200));
    chk("页面里没有报错", !window.__perr.length, (window.__perr[0] || "").slice(0, 120));
    chk("★ boot 一路跑到底（没有 report_error —— 中途炸了这里就看得见）",
        !(window.__reported || []).length, (window.__reported || [])[0] || "");
    chk("页面真画出来了（有按钮/卡片之类的元素）",
        document.querySelectorAll(".window, [class]").length >= 5, "");
  }
  var bad = RES.filter(function(r){ return !r.ok; });
  var box = document.createElement("pre");
  box.id = "probe";
  box.textContent = JSON.stringify({ok: bad.length === 0, n: RES.length, bad: bad.length,
                                    perr: window.__perr, res: RES});
  document.body.appendChild(box);
  document.title = (bad.length === 0 && !window.__perr.length)
    ? "PAGE-OK " + RES.length : "PAGE-FAIL " + (bad.length + window.__perr.length);
})();
</script>"""

#: 内嵌拖放那半：桩里模拟"宿主送真路径进来"（`moss.on('drop')`），
#: 断言页面会把它 `push_drop` 给后端，而且参数是一个对象。
DROP_STUB = PAGE_STUB.replace(
    'window.moss = {env:{embedded:false}, on:function(){return function(){};},',
    'window.__handlers = {};\n'
    '  window.moss = {env:{embedded:true}, on:function(n, cb){ (window.__handlers[n] = '
    'window.__handlers[n] || []).push(cb); return function(){}; },')

DROP_DRIVER = r"""<script>
(async function(){
  var RES = [];
  function chk(name, ok, detail){ RES.push({name:name, ok:!!ok, detail:String(detail == null ? "" : detail)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  for (var i = 0; i < 120 && !window.__img; i++) await sleep(60);
  await sleep(500);
  var img = window.__img;
  if (!img){
    RES.push({name:"页面挂上了", ok:false, detail:"等不到 __img"});
  } else {
    // 内嵌：页面应该已经挂上宿主那条 drop
    var hs = (window.__handlers && window.__handlers["drop"]) || [];
    var diag = "handlers=" + JSON.stringify(Object.keys(window.__handlers || {})) +
               " env=" + JSON.stringify(window.moss && window.moss.env) +
               " calls=" + JSON.stringify(window.__calls.map(function(c){ return c.method; })) +
               " reported=" + JSON.stringify(window.__reported || []) +
               " status=" + (document.getElementById("status") || {}).textContent;
    chk("内嵌时挂上了宿主的 drop（垫片的 moss.on('drop')）", hs.length >= 1, diag);
    window.__calls = [];
    hs.forEach(function(f){ f({items: ["D:\\stub\\a.png", "D:\\stub\\b.jpg"]}); });
    await sleep(400);
    var push = window.__calls.filter(function(c){ return c.method === "push_drop"; });
    chk("★ 宿主给的**真路径**被 push_drop 塞回后端", push.length === 1,
        JSON.stringify(window.__calls.map(function(c){ return c.method; })));
    var got = push[0] && push[0].params;
    chk("★ push_drop 的参数是**一个对象**且字段是 paths",
        !!got && typeof got === "object" && Object.keys(got).join(",") === "paths",
        JSON.stringify(got));
    chk("两条路径原样传过去（没少、没变形）",
        !!got && Array.isArray(got.paths) && got.paths.length === 2 &&
        got.paths[0] === "D:\\stub\\a.png", JSON.stringify(got && got.paths));
    chk("塞回去之后**接着走原来那条 take_drop 轮询**（管线没丢）",
        window.__calls.some(function(c){ return c.method === "take_drop"; }),
        JSON.stringify(window.__calls.map(function(c){ return c.method; })));

    /* ---- `V-226`：拖动时那张提示，松手之后必须收掉 ----------------------------
       真机上报的就是这个：拖动时提示出来了，**松手之后它还挂在那儿**。
       机制（和 `path` 当时一模一样的那个坑）：
         · 宿主铺罩子接住这一拖 ⇒ 这一帧收到一次**假的** `dragleave`（鼠标下元素被换掉）；
         · 罩子把 `drop` 接走 ⇒ 这一帧**再也收不到 `drop`**，页面自己那条"松手就收"的
           出口永远不会触发；
         · 只有宿主发的 `captured` / `dragend` 能告诉页面"到底怎么回事"。
       所以这三条断言都要：假 leave 不算数、真 dragend 必须收、宿主 drop 也算落地。 */
    function veil(){ var v = document.getElementById("dropVeil"); return v ? !v.hidden : null; }
    function dragEv(type, dt){
      /* 派发在 `document.body` 上（**不是 window**）：真实的拖放事件 target 一定是个元素，
         页面那条 `wrap.contains(e.target)` 也正是这个前提 —— 派到 window 上会先抛
         TypeError，测出来的就是"我自己造的假事件"，不是页面的毛病。 */
      document.body.dispatchEvent(new DragEvent(type, {bubbles:true, cancelable:true,
                                                       dataTransfer:dt, relatedTarget:null}));
    }
    function fireHost(name, data){
      ((window.__handlers && window.__handlers[name]) || []).forEach(function(f){ f(data || {}); });
    }
    var dt = new DataTransfer();
    dt.items.add(new File(["x"], "a.png", {type:"image/png"}));
    /* 场景 1（**真机上发生的就是这个**）：宿主接住 → 罩子把 drop 接走 → 页面再也收不到
       `drop`，而且那次"假 leave"真机上**不一定送得到**（送不送取决于浏览器）。
       所以"松手要收提示"这件事只能靠宿主的 `dragend` —— 这一条是这次的主角。 */
    dragEv("dragenter", dt);
    dragEv("dragover", dt);
    await sleep(60);
    chk("拖动时页面自己出提示（大遮罩 `#dropVeil` 出现）", veil() === true, "veil=" + veil());
    fireHost("captured", {});                 // 宿主：我铺罩子接住了（没有随后那次 leave）
    await sleep(60);
    chk("宿主接住之后提示还在（`captured` 本身不该把它收掉）", veil() === true, "veil=" + veil());
    fireHost("dragend", {});                  // 宿主：这一拖结束了
    await sleep(60);
    chk("★ 松手（宿主的 `dragend`）之后提示必须收掉 —— 真机就是卡在这一步",
        veil() === false, "veil=" + veil());

    /* 场景 2（`V-205` 那条口径）：罩子盖上来**确实**送了一次假 `dragleave` 时，
       页面不许信它 —— 信了提示会提前消失，再盖回来就来回抖。 */
    dragEv("dragover", dt);
    await sleep(40);
    fireHost("captured", {});
    dragEv("dragleave", dt);
    await sleep(60);
    chk("宿主接住（captured）期间，那次**假的** dragleave 不许把提示收掉（`V-205` 口径）",
        veil() === true, "veil=" + veil());
    fireHost("dragend", {});
    await sleep(60);
    chk("★ 这一轮松手之后同样收掉（假 leave 没把它提前收掉）", veil() === false, "veil=" + veil());

    /* 场景 3：宿主不走 dragend、直接把真路径送进来（`drop`）那一支，也得收。 */
    dragEv("dragover", dt);
    await sleep(40);
    chk("再拖一次提示又出来（不是被永久关掉了）", veil() === true, "veil=" + veil());
    fireHost("drop", {items:["D:\\stub\\c.png"]});
    await sleep(150);
    chk("宿主把真路径送进来（`drop`）之后提示同样收掉", veil() === false, "veil=" + veil());

    /* 场景 4：**只认系统文件** —— 页面里拖选一段文字不该把"松手就转换"那层提示叫出来。 */
    var dt2 = new DataTransfer();
    dt2.setData("text/plain", "拖的是文字，不是文件");
    dragEv("dragenter", dt2);
    dragEv("dragover", dt2);
    await sleep(60);
    chk("拖的不是系统文件（`types` 里没有 Files）⇒ 不出提示", veil() === false, "veil=" + veil());
    chk("页面里没有报错", !window.__perr.length, (window.__perr[0] || "").slice(0, 120));
    chk("★ boot 一路跑到底（没有 report_error）",
        !(window.__reported || []).length, (window.__reported || [])[0] || "");
  }
  var bad = RES.filter(function(r){ return !r.ok; });
  var box = document.createElement("pre");
  box.id = "probe";
  box.textContent = JSON.stringify({ok: bad.length === 0, n: RES.length, bad: bad.length,
                                    perr: window.__perr, res: RES});
  document.body.appendChild(box);
  document.title = (bad.length === 0 && !window.__perr.length)
    ? "DROP-OK " + RES.length : "DROP-FAIL " + (bad.length + window.__perr.length);
})();
</script>"""


def page_phase(tmp, stub, driver, name, title_ok):
    """真渲染 img 的页面（ESM）→ 读结论。"""
    exe = next((b for b in BROWSERS if Path(b).is_file()), None)
    if not exe:
        print("  [跳过] 这台机器上找不到 Edge/Chrome —— 页面那半验不了")
        return True, 0, 0
    dst = tmp / ("img_" + name)
    shutil.copytree(PKG, dst, ignore=shutil.ignore_patterns("__pycache__"))
    page = dst / "ui" / "index.html"
    html = page.read_text(encoding="utf-8")
    if '<script src="moss-embed.js"></script>' not in html:
        print("  [失败] img 的 index.html 里没有垫片那一行 —— 页面侧没接上")
        return False, 0, 1
    html = html.replace('<script src="moss-embed.js"></script>', stub)
    html = html.replace("</body>", driver + "\n</body>")
    page.write_text(html, encoding="utf-8")
    prof = tmp / ("_prof_" + name)
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--no-default-browser-check", "--user-data-dir=" + str(prof),
           "--allow-file-access-from-files", "--window-size=1280,900",
           "--virtual-time-budget=30000", "--dump-dom",
           "file:///" + str(page).replace("\\", "/")]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    dom = r.stdout or ""
    import html as _html
    import re
    m = re.search(r'(?s)<pre id="probe">(.*?)</pre>', dom)
    t = (re.search(r"<title>(.*?)</title>", dom, re.S) or [None, ""])[1].strip()
    if not m:
        print("  ✗ 没跑到最后（读不到结论）—— 标题=%s" % (t or "（空）"))
        return False, 0, 1
    box = json.loads(_html.unescape(m.group(1)))
    for it in box["res"]:
        print("  %s %s%s" % ("OK  " if it["ok"] else "FAIL", it["name"],
                             ("   ← " + it["detail"]) if (not it["ok"] and it["detail"]) else ""))
    if box["perr"]:
        print("  页面报错：%s" % box["perr"][:2])
    return bool(box["ok"] and not box["perr"]), box["n"], box["bad"]


def main():
    res = []

    def chk(name, ok, detail=""):
        res.append((name, bool(ok), detail))
        print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + detail) if detail else ""))

    tmp = Path(tempfile.mkdtemp(prefix="moss_imgprobe_"))
    real_dir = Path(os.environ.get("MOSS_HOME") or ROOT) / "user_data" / "state" / "img"
    real_cfg = real_dir / "config.json"
    real_before = real_cfg.read_bytes() if real_cfg.is_file() else None

    os.environ["MOSS_PLUGIN_DATA_DIR"] = str(tmp / "state")
    os.environ["MOSS_UI_EMBED"] = "1"
    sys.path.insert(0, str(PKG))
    for m in ("core", "gui_web", "embed"):
        sys.modules.pop(m, None)
    import embed as E                                                 # noqa: E402

    print("=" * 72)
    print("A：进程内直接喂 JSON 行（`Embedded.handle`）")
    print("=" * 72)
    em = E.Embedded()
    chk("A 认得出自己该跑内嵌（MOSS_UI_EMBED=1）", E.embedded_now() is True, "")

    def ask(method, params=None):
        return em.handle(json.dumps({"id": 1, "method": method, "params": params or {}},
                                    ensure_ascii=False))

    r = ask("bootstrap")
    b = r.get("result") or {}
    chk("A bootstrap 回 ok", r.get("ok") is True, json.dumps(r, ensure_ascii=False)[:100])
    chk("A bootstrap 带齐页面要的字段",
        all(k in b for k in ("apiVersion", "config", "history", "sourceDir", "scan", "dataDir",
                             "formats", "saveModes", "icoSizes", "supportedExts", "maxExpand",
                             "thumbLimit", "theme", "accent")),
        "有的字段：" + ",".join(sorted(b.keys()))[:200])
    chk("A bootstrap 自证是内嵌", b.get("embedded") is True, str(b.get("embedded")))
    chk("A 数据目录指向临时目录（没碰用户真数据）", str(tmp) in str(b.get("dataDir")), str(b.get("dataDir")))

    print()
    print("=" * 72)
    print("B：真干活（scan / check_path / thumbs / help），参数都是**一个对象**")
    print("=" * 72)
    d = str(tmp / "pics")
    os.makedirs(d, exist_ok=True)
    # 拖放那条链要一个**真存在**的图片文件：`take_drop` 那条老管线会查存在性 / 按配置过滤，
    # 随便编个路径它会照实回"清单是空的"（第一版就是这么假绿的）。
    dropme = tmp / "拖进来.png"
    try:
        from PIL import Image
        Image.new("RGB", (24, 24), (10, 160, 90)).save(str(dropme))
    except Exception:                                                 # noqa: BLE001
        dropme.write_bytes(bytes.fromhex(                                 # 1×1 PNG，兜底
            "89504e470d0a1a0a0000000d494844520000000100000001080600000"
            "01f15c4890000000a49444154789c6360000002000100ffff03000006"
            "000557bfabd40000000049454e44ae426082"))
    try:
        from PIL import Image
        Image.new("RGB", (40, 30), (200, 30, 30)).save(os.path.join(d, "a.png"))
        Image.new("RGB", (80, 60), (30, 30, 200)).save(os.path.join(d, "b.png"))
        made = True
    except Exception as e:                                            # noqa: BLE001
        made = False
        print("  （PIL 用不了，跳过图片相关的两条：%s）" % e)

    r = ask("scan", {"dir": d})
    got = r.get("result") or {}
    chk("B scan 认出这个目录里的两张图",
        got.get("ok") is True and got.get("count") == 2 and len(got.get("files") or []) == 2,
        json.dumps({k: v for k, v in got.items() if k != "files"}, ensure_ascii=False)[:160])
    if made:
        chk("B scan 列出了刚造的两张图", len(got.get("files") or []) == 2,
            str([f.get("name") for f in (got.get("files") or [])]))
        r = ask("thumbs", {"paths": [os.path.join(d, "a.png")]})
        th = ((r.get("result") or {}).get("thumbs") or [])
        chk("B thumbs 回了一张缩略图（data URL）",
            len(th) == 1 and str(th[0].get("data") or "").startswith("data:image/"),
            str(th)[:80])
    r = ask("check_path", {"path": d})
    chk("B check_path 说是目录", (r.get("result") or {}).get("isdir") is True, "")
    r = ask("help")
    chk("B help 回了用法（从 cli.py 取的）", bool((r.get("result") or {}).get("usage")), "")
    chk("B 传错形状也不炸（params 不是 dict）", em.handle(
        json.dumps({"id": 2, "method": "scan", "params": "不是对象"})).get("ok") is not False
        or True, "")     # 这一条只看"不抛异常"，返回值随便

    print()
    print("=" * 72)
    print("C：坏输入 / 未知方法 / 内部方法 —— 只回 ok:false，循环不断")
    print("=" * 72)
    chk("C 未知方法回 ok:false", ask("不存在的名字").get("ok") is False, "")
    chk("C 下划线开头不给调", ask("_window").get("ok") is False, "")
    chk("C 内部方法（set_title / save_config）不给页面调",
        all(ask(m).get("ok") is False for m in ("set_title", "save_config")), "")
    # ★ `V-227` 真机上抓到的：`push_drop` 一开始被当成"内部方法"挡掉了 ⇒ 宿主把真路径送进页面、
    #   页面往回塞时回一句"没有这个方法 push_drop"，拖放**整条死掉**（`path` 却好好的）。
    #   它是页面**自己**的通道，必须给调 —— 而且必须真能走通（塞进去 → `take_drop` 取得出）。
    r = ask("push_drop", {"paths": [str(dropme)]})
    chk("C ★ `push_drop` 页面**必须**能调（它是页面把宿主给的真路径塞回来的那条路）",
        r.get("ok") is True, json.dumps(r, ensure_ascii=False)[:120])
    r = ask("take_drop")
    got = r.get("result") or {}
    chk("C ★ 塞进去之后 `take_drop` 取得到（拖放那条管线真的通了）",
        got.get("pending") is True and
        any("拖进来.png" in str(f.get("path") or "") for f in (got.get("files") or [])),
        json.dumps({k: v for k, v in got.items() if k != "history"}, ensure_ascii=False)[:160])
    bad = em.handle("这不是 JSON")
    chk("C 坏 JSON 回一句人话（不抛）", bad.get("ok") is False and "JSON" in str(bad.get("error")),
        str(bad)[:80])
    chk("C 出过错之后还能继续干活", ask("help").get("ok") is True, "")

    print()
    print("=" * 72)
    print("D：**真起一个宿主进程**（`moss.exe :img` + `MOSS_UI_EMBED=1`，就是 embed_start 那条）")
    print("=" * 72)
    env = dict(os.environ)
    env["MOSS_UI_EMBED"] = "1"
    env["MOSS_PLUGIN_DATA_DIR"] = str(tmp / "state")
    env["MOSS_PKG_PARAMS"] = json.dumps({"args": ""})
    proc = subprocess.Popen([str(ROOT / "moss.exe"), ":img"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for req in ({"id": 7, "method": "bootstrap", "params": {}}, {"id": 8, "method": "help", "params": {}}):
        proc.stdin.write(json.dumps(req) + "\n")
    # ★ `V-227`：**拖放那条线要走真的宿主进程验一遍**（就是"宿主 drop → 页面 push_drop → 后端"
    #   那条）。上一版只把参数形状对了账、用的是桩，于是"push_drop 被 HIDDEN 挡掉"没被抓到 ——
    #   真机上一句"没有这个方法 push_drop"，拖进来什么都不发生。
    proc.stdin.write(json.dumps({"id": 9, "method": "push_drop",
                                 "params": {"paths": [str(dropme)]}}) + "\n")
    proc.stdin.write(json.dumps({"id": 10, "method": "take_drop", "params": {}}) + "\n")
    proc.stdin.flush()
    box, deadline = [], time.time() + 30
    import threading

    def reader():
        for ln in proc.stdout:
            box.append(ln.rstrip("\n"))
            if len([x for x in box if x.lstrip().startswith("{")]) >= 4:
                break

    threading.Thread(target=reader, daemon=True).start()
    while time.time() < deadline and len(box) < 4:
        time.sleep(0.1)
        if proc.poll() is not None and not box:
            break
    time.sleep(0.4)
    try:
        proc.stdin.close()
    except Exception:                                                # noqa: BLE001
        pass
    try:
        proc.wait(timeout=10)
    except Exception:                                                # noqa: BLE001
        proc.kill()
    json_lines, junk, got_ids = [], [], {}
    for ln in box:
        if ln.lstrip().startswith("{"):
            try:
                json_lines.append(json.loads(ln))
            except ValueError:
                json_lines.append(None)
        elif ln.strip():
            junk.append(ln)
    for obj in json_lines:
        if obj:
            got_ids[obj.get("id")] = obj
    chk("D 两条请求都回了 JSON", set(got_ids) >= {7, 8},
        "拿到的 id：" + str(sorted(k for k in got_ids if k is not None)))
    chk("D ★ 真宿主进程里 `push_drop` 也能调（`V-227`）",
        (got_ids.get(9) or {}).get("ok") is True,
        json.dumps(got_ids.get(9), ensure_ascii=False)[:140])
    td = (got_ids.get(10) or {}).get("result") or {}
    chk("D ★ 真宿主里 push_drop → take_drop 拿得到那条路径（拖放整条链真的通）",
        td.get("pending") is True and
        any("拖进来.png" in str(f.get("path") or "") for f in (td.get("files") or [])),
        json.dumps({k: v for k, v in td.items() if k != "history"}, ensure_ascii=False)[:160])
    chk("D **每一行以 `{` 开头的都是合法 JSON**（协议没被撕）",
        bool(json_lines) and all(json_lines), repr(box)[:180])
    chk("D bootstrap 那条 ok 且自证内嵌",
        (got_ids.get(7) or {}).get("ok") is True and
        ((got_ids.get(7) or {}).get("result") or {}).get("embedded") is True, "")
    chk("D 非 JSON 行（宿主横幅 / 我们的日志）不影响协议",
        all(not j.startswith('{"id"') for j in junk), "非 JSON %d 条" % len(junk))
    chk("D stdin 关掉就自己退出（宿主收进程那一下）", proc.returncode == 0, str(proc.returncode))

    print()
    print("=" * 72)
    print("E：**用户真数据没被碰**")
    print("=" * 72)
    real_after = real_cfg.read_bytes() if real_cfg.is_file() else None
    chk("E 真·config.json 一个字节都没变", real_before == real_after,
        "之前 %s / 现在 %s" % (len(real_before or b""), len(real_after or b"")))

    print()
    print("=" * 72)
    print("F：**页面那半**（无头浏览器真渲染 img 的 ESM 页面）")
    print("   ★ 验的是「参数形状」：垫片两种环境都只传一个对象，页面也必须按字段名发 ——")
    print("     独立窗口那条路（`window.pywebview.api[方法](params)`）一起验到了。")
    print("=" * 72)
    ok1, n1, b1 = page_phase(tmp, PAGE_STUB, PAGE_DRIVER, "page", "PAGE-OK")
    res.append(("F1 页面：参数形状（%d 条）" % n1, ok1, "失败 %d" % b1 if not ok1 else ""))
    print()
    print("  —— F2：内嵌时**拖放**走宿主那条（真路径 → push_drop → 老管线）——")
    ok2, n2, b2 = page_phase(tmp, DROP_STUB, DROP_DRIVER, "drop", "DROP-OK")
    res.append(("F2 页面：内嵌拖放（%d 条）" % n2, ok2, "失败 %d" % b2 if not ok2 else ""))

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 72)
    badN = [x for x in res if not x[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not badN else "✗ 有不对的", len(res), len(badN)))
    return 0 if not badN else 1


if __name__ == "__main__":
    sys.exit(main())
