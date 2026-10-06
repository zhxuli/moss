# -*- coding: utf-8 -*-
"""包界面检查：把带 `ui.embed` 的包的网页**单独渲染一遍**，看它到底能不能画出来（`V-209`）。

为什么需要它（补的是哪一个洞）：`tools/界面预览.py` 只跑 **moss 自己的界面**；包的那一页是塞在
**内嵌那一帧（iframe）**里的 —— 预览里那是**另一个源**，父页面读不到它里面（连截图里都只是个小方块）。
于是"包的页面里 Vue 模板写错了 / 某个字段没喂到就炸了"这类问题，之前**只有你手点才发现**。
这个工具把那一页**当普通页面单独打开**（垫片换成桩），跑完读 `document.title` 里的结论 ——
它是**真渲染**，所以模板语法错、computed 抛错、`v-for` 拼错都拦得住。

用法：
    .\\venv\\Scripts\\python.exe tools\\包界面检查.py              # 所有带 ui.embed 的包
    .\\venv\\Scripts\\python.exe tools\\包界面检查.py path bmi      # 只看这几个

★ 桩只保证"页面能跑起来"：`moss.call(...)` 一律回 `{ok:true}` 之类的空壳 —— 所以它**不验业务**
  （业务归各包自己的探针 / 真机手点）。它验的是"这一页渲染得出来、而且没有报错"。
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os_environ_home = str(ROOT)
import os                                                                # noqa: E402
os.environ.setdefault("MOSS_HOME", os_environ_home)

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
]

#: 垫片的替代品：一个"什么都答应"的假后端 + 错误收集。
#: ★ 结尾那个 `setTimeout` 把结论写进 `document.title` —— 和 moss 界面的预览工具同一个套路，
#:   `--dump-dom` 之后读 `<title>` 就知道过没过。
STUB = """<script>
(function(){
  /* ★ `__PKG__` 由 Python 侧换成"这一页是哪个包的"（`V-225`）——
     每个包一份**真形状**的假后端：渲染检查的价值就在"有数据时会不会崩"，
     回空壳等于只验了个空页面。 */
  var PKG = "__PKG__";
  window.__perr = [];
  window.__reported = [];      // 页面自己报回来的异常（`report_error`）—— 也算失败
  window.addEventListener("error", function(e){ window.__perr.push(String(e.message || e)); });
  window.addEventListener("unhandledrejection", function(e){
    window.__perr.push("unhandledrejection: " + String((e.reason && e.reason.message) || e.reason));
  });
  function ok(){ return {ok:true}; }
  // ★ 顺手把 Vue 的 errorHandler 也挂上（`vue.global.prod.js` **没有 `Vue.config`**，
  //   只能按 app 设）：不然"computed / 模板里抛错"会被 prod 版悄悄吞掉，页面上一个字都没有。
  if (window.Vue && Vue.createApp) {
    var _create = Vue.createApp;
    Vue.createApp = function(c){
      var app = _create.call(Vue, c);
      app.config.errorHandler = function(e){ window.__perr.push("vue: " + String((e && e.message) || e)); };
      return app;
    };
  }
  // ★ ESM 页面（exec / img 那种）模块加载/求值失败时只往控制台丢一条，这里补收一下
  window.addEventListener("error", function(e){
    if (e && e.target && e.target.tagName === "SCRIPT"){
      window.__perr.push("模块加载失败：" + (e.target.src || "?"));
    }
  }, true);

  var ACCENT = {theme:"light", accent:"#0078d4", "accent-fg":"#ffffff",
                "accent-press":"#0065b3", ring:"rgba(0,120,212,.45)",
                "field-focus":"rgba(0,120,212,.15)"};
  var PSTATES = function(){
    return {ok:true, count:0, paths:[], missing:[], self_dir:"", self_registered:false,
            data_dir:"（桩）", backup_dir:"（桩）", legacy_dir:""};
  };

  // ---- path / 其它老包（Vue 全局版）----
  var R_PATH = {
    info: {ok:true, pid:1, python:"?（桩）", embedded:false},
    state: PSTATES(),
    backup_list: {ok:true, items:[], state:PSTATES()},
    backup_preview: {ok:true, add:[], remove:[], paths:[], msg:""},
    now: {text:"00:00:00"}, subscribe: {subscribed:[]},
    bmi: {ok:true, bmi:22.5, level:"正常", advice:"（桩）", who:"（桩）", at:{text:"00:00:00"}}
  };

  // ---- exec（V-222）：ESM 页面，第一件事就是 bootstrap ----
  var R_EXEC = {
    bootstrap: {ok:true, apiVersion:2, embedded:false,
      dataDir:"（桩）user_data/state/exec/cmds", theme:"light", accent:ACCENT,
      picker: [{id:"python", label:"Python", types:["python"], icon:"code"},
               {id:"command", label:"命令行", types:["shell","powershell"], icon:"terminal"},
               {id:"path", label:"路径", types:["path"], icon:"folder"}],
      pickerDefault: {command:"shell"},
      newTypes: [{id:"python", label:"Python 片段", icon:"code", hint:"（桩）"},
                 {id:"shell", label:"CMD 命令", icon:"terminal", hint:"（桩）"}],
      types: {python:{label:"Python 片段", kind:"proc", lang:"python", multiline:true,
                      payload:"Python 代码", hint:"（桩）"},
              shell:{label:"CMD 命令", kind:"proc", lang:"bash", multiline:true,
                     payload:"命令", hint:"（桩）"},
              powershell:{label:"PowerShell", kind:"proc", lang:"powershell", multiline:true,
                          payload:"PowerShell 代码", hint:"（桩）"},
              path:{label:"文件 / 文件夹", kind:"builtin", payload:"路径", multiline:false}},
      afterActions: [{id:"none", label:"什么都不做"}],
      placeholders: [{token:"{args}", desc:"本次输入的参数"}, {token:"{date}", desc:"今天"}],
      commands: [
        {alias:"ping", type:"shell", description:"（桩）测延迟",
         code:"ping -n 4 127.0.0.1", codes:{shell:"ping -n 4 127.0.0.1"},
         cwd:"", env:"", elevated:false, after:"none"},
        {alias:"ip", type:"python", description:"（桩）看本机 IP",
         code:"import socket; print(socket.gethostname())",
         codes:{python:"import socket; print(socket.gethostname())"},
         cwd:"", env:"", elevated:false, after:"none"}]},
    cmd_list: {ok:true, commands:[]},
    cmd_save: {ok:true, alias:"probe"}, cmd_remove: {ok:true, alias:"probe"},
    run_start: {ok:true, id:"r1"},
    run_poll: {ok:true, running:false, returncode:0, output:"（桩）EXEC-OK\\n"},
    run_stop: {ok:true}, run_console: {ok:true},
    sys_reveal: {ok:true}, sys_copy: {ok:true}, sys_pick_path: {ok:true, path:""}
  };

  // ---- img（V-225）：ESM 页面，bootstrap 里 formats / saveModes 必须是**数组** ----
  var IMG_SCAN = {ok:true, dir:"（桩）", count:0, exts:[], files:[], message:""};
  var R_IMG = {
    bootstrap: {ok:true, apiVersion:1, embedded:false,
      config:{save_mode:"separate", output_format:"jpg", quality:80, width:"",
              ico_sizes:[16,32,48,256], output_dir:"", source_filter:{}, history:[]},
      history:[], sourceDir:"（桩）", scan:IMG_SCAN, dataDir:"（桩）state/img",
      formats:["jpg","png","webp","ico"], saveModes:["separate","source","source_delete"],
      icoSizes:[16,32,48,256], supportedExts:[".jpg",".png",".webp"], maxExpand:50,
      thumbLimit:100, thumbBox:240, historyLimit:20, theme:"light", accent:ACCENT, log:""},
    scan: IMG_SCAN, scan_files: {ok:true, files:[]}, thumbs: {ok:true, thumbs:[]},
    file_info: {ok:true, info:{path:"（桩）", exists:false, name:"（桩）"}},
    check_path: {ok:true, path:"（桩）", isdir:true, isfile:false, parent:"（桩）"},
    open_file: {ok:true}, reveal: {ok:true, opened:"（桩）", fellBack:false},
    pick_dir: {ok:true, path:""}, pick_files: {ok:true, files:[]},
    start: {ok:true, job:"j1", history:[], outputDir:"（桩）"},
    poll: {ok:true, running:false, done:true, total:0, processed:0, errors:0, log:""},
    cancel: {ok:true}, take_drop: {ok:true, pending:false}, push_drop: {ok:true},
    help: {ok:true, usage:"moss :img [格式] [质量%] [宽度px] [文件...] 输出位置",
           formats:["jpg","png","webp","ico"], description:"（桩）"},
    copy: {ok:true}, save_config: {ok:true}
  };

  // ---- fanyi（V-xxx）：网页版翻译器，onMounted 会问 targets / info / cache_info ----
  var R_FANYI = {
    info: {ok:true, pid:1, python:"?（桩）", cwd:"（桩）", embedded:false,
           data_dir:"（桩）", cache_path:"（桩）state/fanyi/cache/translation_cache.jsonl",
           cache_count:2, who:"（桩）"},
    targets: {ok:true, default:"auto",
      targets:[{value:"auto", label:"自动（中↔英）"}, {value:"zh-CN", label:"中文（简体）"},
               {value:"en", label:"English"}]},
    translate: {ok:true, source:"en", target:"zh-CN", original:"hello",
                translated:"你好", cached:false, at:"00:00:00", who:"（桩）"},
    read_clipboard: {ok:true, text:"（桩）剪贴板里的文字"},
    copy: {ok:true, why:""},
    cache_info: {ok:true, count:2, path:"（桩）", dir:"（桩）", who:"（桩）",
      history:[{src:"hello", dst:"你好", target:"zh-CN", at:"00:00:00"},
               {src:"world", dst:"世界", target:"zh-CN", at:"00:00:00"}]},
    cache_clear: {ok:true, removed:2, count:0},
    history: {ok:true, items:[{src:"hello", dst:"你好", target:"zh-CN", at:"00:00:00"}]},
    hotkey_status: {ok:true, running:false},
    hotkey_start: {ok:true, running:true, msg:"已启动"},
    hotkey_stop: {ok:true, running:false, msg:"已停止"}
  };

  var R = (PKG === "exec") ? R_EXEC : ((PKG === "img") ? R_IMG :
          ((PKG === "fanyi") ? R_FANYI : R_PATH));
  R.report_error = function(p){ window.__reported.push(String((p && p.text) || "")); return {ok:true}; };
  R.set_title = {ok:true};

  window.moss = {
    env: {embedded: false},
    on: function(){ return function(){}; },
    call: function(method, params){
      var v = R[method];
      if (typeof v === "function") return Promise.resolve(v(params));
      return Promise.resolve(v || ok());
    }
  };
  setTimeout(function(){
    document.title = window.__perr.length
      ? ("PERR " + window.__perr.length + " " + window.__perr[0].slice(0, 80))
      : (window.__reported.length
         ? ("BOOT-ERR " + window.__reported[0].slice(0, 80))
         : "RENDER-OK");
  }, 1500);
})();
</script>"""


def browser():
    for b in BROWSERS:
        if Path(b).is_file():
            return b
    return None


def embed_pkgs(want):
    """哪些包有 `ui.embed`（直接读磁盘上的 pkg.json，不拉宿主）。"""
    out = []
    for base in (ROOT / "system" / "pkgs", ROOT / "user_data" / "pkgs"):
        if not base.is_dir():
            continue
        for d in sorted(base.iterdir()):
            f = d / "pkg.json"
            if not f.is_file():
                continue
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
            except Exception:                                            # noqa: BLE001
                continue
            rel = str(((j.get("ui") or {}).get("embed")) or "")
            if rel and ((want and d.name in want) or not want):
                out.append((str(j.get("id") or d.name), d, d / rel))
    return out


def render(exe, page, tmp):
    prof = tmp / "_prof"
    shutil.rmtree(prof, ignore_errors=True)
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--no-default-browser-check", "--user-data-dir=" + str(prof),
           "--allow-file-access-from-files", "--window-size=1280,860",
           "--virtual-time-budget=8000", "--dump-dom",
           "file:///" + str(page).replace("\\", "/")]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=120)
    return r.stdout or ""


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                                # noqa: BLE001
            pass
    exe = browser()
    if not exe:
        print("[跳过] 这台机器上找不到 Edge/Chrome —— 这个检查要一个浏览器来渲染")
        return 0
    want = set(a for a in sys.argv[1:] if not a.startswith("-"))
    pkgs = embed_pkgs(want)
    if not pkgs:
        print("没有带 ui.embed 的包（或者你点的包都不带）")
        return 0
    print("浏览器 : %s" % exe)
    print("要检查 : %s" % "、".join(p[0] for p in pkgs))
    print("=" * 64)
    bad = 0
    for pid, pdir, page in pkgs:
        if not page.is_file():
            print("  %-10s FAIL  界面文件不存在：%s" % (pid, page))
            bad += 1
            continue
        tmp = Path(tempfile.mkdtemp(prefix="moss_pkgui_"))
        try:
            dst = tmp / pdir.name
            shutil.copytree(pdir, dst)
            target = dst / page.relative_to(pdir)
            html = target.read_text(encoding="utf-8")
            if '<script src="moss-embed.js"></script>' in html:
                html = html.replace('<script src="moss-embed.js"></script>',
                                  STUB.replace("__PKG__", pid))
            else:
                html = html.replace("</head>", STUB + "\n</head>", 1)
            target.write_text(html, encoding="utf-8")
            dom = render(exe, target, tmp)
            title = (re.search(r"<title>(.*?)</title>", dom, re.S) or [None, ""])[1].strip()
            body = re.search(r"(?s)<body[^>]*>(.*?)</body>", dom)
            inner = body.group(1) if body else dom
            visible = re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", inner)).strip()
            # ★ 判"真画出来了"要三条一起：① 没有报错（标题 RENDER-OK）② 有可见文字
            #   ③ 有若干带 class 的元素 —— 只判"DOM 够长"会把"空壳页面"也放过去（假绿）。
            ok = title == "RENDER-OK" and len(visible) >= 30 and inner.count('class="') >= 3
            print("  %-10s %s  %s  文字 %d 字  元素 %d 个  标题=%s"
                  % (pid, "OK  " if ok else "FAIL", "%d KB" % (len(dom) // 1024),
                     len(visible), inner.count('class="'), title[:60] or "（读不到）"))
            if not ok:
                bad += 1
                print("             可见文字片段：%s" % visible[:160])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print("=" * 64)
    print("结论：%s" % ("✅ 全部渲染正常（真渲染，模板/计算属性出错都会在这拦下）" if not bad
                        else "✗ %d 个包的页面没渲染出来" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
