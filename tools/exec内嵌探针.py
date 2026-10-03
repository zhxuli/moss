# -*- coding: utf-8 -*-
"""exec 界面探针（`V-222`）：把 exec **两条路都跑一遍** —— 内嵌后端 + 页面那侧。

为什么单独写一个
----------------
exec 原来是"自己开一扇 pywebview 窗"的包（`gui_web.py`），页面里的桥直接调
`window.pywebview.api.<方法>(位置参数)`。改成能内嵌之后，多了一条路：
宿主用 `MOSS_UI_EMBED=1` 把它起成**后端进程**，在 stdin/stdout 上说 JSON 行
（`{"id":1,"method":"cmd_list","params":{}}` → `{"id":1,"ok":true,"result":{…}}`）。

这条路上最容易坏的三件事，全都得用真东西验：

  ① **参数形状**：垫片两种环境都只传**一个对象**，所以 `Api` 的方法必须是 `(params=None)`；
     页面侧也得真的把 `{alias, args}` 这种对象发出去（不是位置参数）；
  ② **stdout 干净**：宿主按行读 JSON —— 里面混进多行日志就把协议撕了；
  ③ **别碰用户真数据**：整个探针把 `MOSS_PLUGIN_DATA_DIR` 指到临时目录。

所以文件分两半：
  A–E：**后端**（进程内喂 JSON 行 + 真起 `moss.exe :exec` 走一遍宿主链路）；
  F  ：**页面**（无头浏览器真渲染 exec 的 ESM 页面，驱动它去调后端，
       把每次调用的**参数形状**记下来对账 —— 独立窗口那条路也一并验了）。

用法：
    .\\system\\runtimes\\python\\3.12\\python.exe tools\\exec内嵌探针.py
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
PKG = ROOT / "system" / "pkgs" / "exec"
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

#: 页面那半用的桩：**照垫片"独立窗口"那条分支的行为**（`window.moss.call` → 后端一个对象），
#: 同时把每次调用的 `(方法, 参数)` 记下来 —— 这就是"参数形状"的对账依据。
PAGE_STUB = r"""<script>
(function(){
  window.__perr = [];
  window.addEventListener("error", function(e){ window.__perr.push(String(e.message || e)); });
  window.addEventListener("unhandledrejection", function(e){
    window.__perr.push("unhandledrejection: " + String((e.reason && e.reason.message) || e.reason));
  });
  window.__calls = [];
  var ACCENT = {theme:"light", accent:"#0078d4", "accent-fg":"#ffffff", "accent-press":"#0065b3",
                ring:"rgba(0,120,212,.45)", "field-focus":"rgba(0,120,212,.15)"};
  var R = {
    bootstrap: {ok:true, apiVersion:2, embedded:false, dataDir:"（桩）/state/exec/cmds",
      theme:"light", accent:ACCENT,
      picker:[{id:"command", label:"命令行", types:["shell"], icon:"terminal"}],
      pickerDefault:{command:"shell"},
      newTypes:[{id:"shell", label:"CMD 命令", icon:"terminal", hint:"（桩）"}],
      types:{shell:{label:"CMD 命令", kind:"proc", lang:"bash", multiline:true,
                    payload:"命令", hint:"（桩）"}},
      afterActions:[{id:"none", label:"什么都不做"}],
      placeholders:[{token:"{args}", desc:"本次输入的参数"}],
      commands:[{alias:"ping", type:"shell", description:"（桩）", code:"ping -n 2 127.0.0.1",
                 codes:{shell:"ping -n 2 127.0.0.1"}, cwd:"", env:"", elevated:false,
                 after:"none"}]},
    cmd_list: {ok:true, commands:[{alias:"ping", type:"shell", description:"（桩）",
                code:"ping -n 2 127.0.0.1", codes:{shell:"ping -n 2 127.0.0.1"},
                cwd:"", env:"", elevated:false, after:"none"}]},
    cmd_save: {ok:true, alias:"ping"},
    cmd_remove: {ok:true, alias:"ping"},
    run_start: {ok:true, id:"r1"},
    run_poll: {ok:true, running:false, returncode:0, output:"（桩）PAGE-OK\n"},
    run_stop: {ok:true},
    run_console: {ok:true},
    sys_reveal: {ok:true},
    sys_copy: {ok:true},
    sys_pick_path: {ok:true, path:"D:\\stub"}
  };
  // 垫片（独立窗口那条）就是这么调的：`fn(params || {})`
  window.pywebview = {api: new Proxy({}, {get: function(_t, name){
    if (typeof name !== "string") return undefined;
    return function(params){ window.__calls.push({method:name, params:params});
                             return Promise.resolve(R[name] || {ok:true}); };
  }})};
  window.moss = {env:{embedded:false}, on:function(){return function(){};},
    call:function(method, params){
      window.__calls.push({method:method, params:params});
      return Promise.resolve(R[method] || {ok:true});
    }};
})();
</script>"""

#: 驱动：等 ESM 页面挂载 → 驱动几次交互 → 把结论写进标题与 `<pre id="probe">`
PAGE_DRIVER = r"""<script>
(async function(){
  var RES = [];
  function chk(name, ok, detail){ RES.push({name:name, ok:!!ok, detail:String(detail == null ? "" : detail)}); }
  function sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
  for (var i = 0; i < 100 && !window.__execApp; i++) await sleep(60);
  await sleep(200);
  var app = window.__execApp;
  if (!app){
    RES.push({name:"页面挂上了（window.__execApp）", ok:false, detail:"等不到 App"});
  } else {
    // ★ 不清空 `__calls`：页面**挂载时自己就会问 bootstrap**，那一下也得算数
    var atMount = window.__calls.length;
    async function drive(label, fn){
      try { await fn(); } catch(e){ RES.push({name:label + " 没抛错", ok:false,
                                               detail:String(e && e.message || e)}); }
      await sleep(120);
    }
    await drive("runCommand", function(){ return app.runCommand(); });
    await drive("stopRun", function(){ return app.stopRun(); });
    await drive("openConsole", function(){ return app.openConsole(); });
    await drive("reveal", function(){ return app.reveal(); });
    await drive("pickInto", function(){ return app.pickInto("file"); });
    await drive("save", function(){ return app.save(); });
    await drive("doDelete", function(){ return app.doDelete(); });

    var by = {};
    window.__calls.forEach(function(c){ (by[c.method] = by[c.method] || []).push(c.params); });
    function shape(name, want){
      var got = by[name] ? by[name][0] : undefined;
      var isObj = got && typeof got === "object" && !Array.isArray(got);
      var keys = isObj ? Object.keys(got).sort().join(",") : String(got);
      chk(name + " 的参数是**一个对象**且字段对（" + want + "）", isObj && keys === want,
          "收到：" + keys);
    }
    chk("页面挂载时自己就问了一次 bootstrap（还没等人点）", atMount >= 1,
        "挂载时的调用数 = " + atMount);
    shape("bootstrap", "");
    shape("run_start", "alias,args");
    shape("run_stop", "id");
    shape("run_poll", "id");
    shape("run_console", "alias,args");
    shape("cmd_save", "item,original_alias");
    shape("cmd_remove", "alias");
    shape("sys_reveal", "");
    shape("sys_pick_path", "kind");
    chk("★ 没有哪一次是把参数当**位置参数**发出去的（全是对象）",
        window.__calls.every(function(c){ return c.params && typeof c.params === "object"; }),
        JSON.stringify(window.__calls.map(function(c){ return c.method; })));
    chk("页面里没有报错", !window.__perr.length, (window.__perr[0] || "").slice(0, 100));
    chk("页面真画出来了（有命令卡片/侧栏节点）",
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


def page_phase(tmp):
    """F：无头浏览器真渲染 exec 的页面，驱动它去调后端，对账**参数形状**。"""
    exe = next((b for b in BROWSERS if Path(b).is_file()), None)
    if not exe:
        print("  [跳过] 这台机器上找不到 Edge/Chrome —— 页面那半验不了")
        return True, 0, 0
    dst = tmp / "exec_page"
    shutil.copytree(PKG, dst, ignore=shutil.ignore_patterns("__pycache__"))
    page = dst / "ui" / "index.html"
    html = page.read_text(encoding="utf-8")
    if '<script src="moss-embed.js"></script>' not in html:
        print("  [失败] exec 的 index.html 里没有垫片那一行 —— 页面侧没接上")
        return False, 0, 1
    html = html.replace('<script src="moss-embed.js"></script>', PAGE_STUB)
    html = html.replace("</body>", PAGE_DRIVER + "\n</body>")
    page.write_text(html, encoding="utf-8")
    prof = tmp / "_prof_page"
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--no-default-browser-check", "--user-data-dir=" + str(prof),
           "--allow-file-access-from-files", "--window-size=1280,900",
           "--virtual-time-budget=30000", "--dump-dom",
           "file:///" + str(page).replace("\\", "/")]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    dom = r.stdout or ""
    import re
    m = re.search(r'(?s)<pre id="probe">(.*?)</pre>', dom)
    title = (re.search(r"<title>(.*?)</title>", dom, re.S) or [None, ""])[1].strip()
    if not m:
        print("  ✗ 页面那半没跑到最后（读不到结论）—— 标题=%s" % (title or "（空）"))
        return False, 0, 1
    import html as _html
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

    tmp = Path(tempfile.mkdtemp(prefix="moss_execprobe_"))
    real_dir = Path(os.environ.get("MOSS_HOME") or ROOT) / "user_data" / "state" / "exec"
    real_before = sorted(p.name for p in real_dir.glob("cmds/*.json")) if real_dir.is_dir() else []

    os.environ["MOSS_PLUGIN_DATA_DIR"] = str(tmp)
    os.environ["MOSS_UI_EMBED"] = "1"
    sys.path.insert(0, str(PKG))

    # 清掉可能已经被导入的 exec 模块（数据目录是 import 时算的）
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
    chk("A bootstrap 回 ok", r.get("ok") is True, json.dumps(r, ensure_ascii=False)[:120])
    chk("A bootstrap 带齐页面要的字段",
        all(k in b for k in ("apiVersion", "commands", "picker", "newTypes", "types",
                             "afterActions", "placeholders", "dataDir", "theme", "accent")),
        "有的字段：" + ",".join(sorted(b.keys())))
    chk("A bootstrap 自证是内嵌（页面/探针都靠它）", b.get("embedded") is True, str(b.get("embedded")))
    chk("A 数据目录指向临时目录（没碰用户真数据）", str(tmp) in str(b.get("dataDir")), str(b.get("dataDir")))
    chk("A 外观那套也算出来了（强调色/深浅）",
        isinstance(b.get("accent"), dict) and bool(b["accent"].get("accent")),
        json.dumps(b.get("accent"), ensure_ascii=False)[:100])

    print()
    print("=" * 72)
    print("B：增删改查 + 跑一条命令（走 Api 真逻辑）")
    print("=" * 72)
    item = {"alias": "probe-exec", "type": "shell", "description": "探针用的",
            "code": "echo EXEC-PROBE-OK", "codes": {"shell": "echo EXEC-PROBE-OK"},
            "cwd": "", "env": "", "elevated": False, "after": "none"}
    r = ask("cmd_save", {"item": item, "original_alias": None})
    chk("B cmd_save 存下来了", (r.get("result") or {}).get("ok") is True and
        (r.get("result") or {}).get("alias") == "probe-exec",
        json.dumps(r.get("result"), ensure_ascii=False)[:100])
    chk("B 落盘在**临时**数据目录里", (tmp / "cmds" / "probe-exec.json").is_file(), str(tmp))
    r = ask("cmd_list")
    names = [c.get("alias") for c in ((r.get("result") or {}).get("commands") or [])]
    chk("B cmd_list 里能看到它", "probe-exec" in names, str(names))

    r = ask("run_start", {"alias": "probe-exec", "args": ""})
    rid = (r.get("result") or {}).get("id")
    chk("B run_start 回了 run id", bool(rid), json.dumps(r.get("result"), ensure_ascii=False)[:100])
    state, waited = {}, 0.0
    while waited < 8:
        state = (ask("run_poll", {"id": rid}).get("result") or {})
        if not state.get("running"):
            break
        time.sleep(0.12)
        waited += 0.12
    chk("B 跑完了（run_poll 不再说 running）", state.get("running") is False, json.dumps(state, ensure_ascii=False)[:110])
    chk("B 退出码 0", state.get("returncode") == 0, str(state.get("returncode")))
    chk("B 输出收到了（EXEC-PROBE-OK）", "EXEC-PROBE-OK" in (state.get("output") or ""),
        repr((state.get("output") or "")[:60]))
    chk("B 拿一个不存在的 run id 问，是 ok:false 而不是崩",
        ask("run_poll", {"id": "nope"}).get("result", {}).get("ok") is False, "")

    r = ask("cmd_remove", {"alias": "probe-exec"})
    chk("B cmd_remove 删掉了", (r.get("result") or {}).get("ok") is True and
        not (tmp / "cmds" / "probe-exec.json").is_file(), "")

    print()
    print("=" * 72)
    print("C：坏输入 / 未知方法 —— 只能回一句 ok:false，不能把循环打断")
    print("=" * 72)
    chk("C 未知方法回 ok:false", ask("不存在的名字").get("ok") is False, "")
    chk("C 下划线开头的方法也不给调", ask("_window").get("ok") is False, "")
    bad = em.handle("这不是 JSON")
    chk("C 坏 JSON 回一句人话（不抛）", bad.get("ok") is False and "JSON" in str(bad.get("error")), str(bad)[:80])
    ok_after = ask("cmd_list").get("ok") is True
    chk("C 出过错之后还能继续干活", ok_after is True, "")

    print()
    print("=" * 72)
    print("D：**真起一个宿主进程**（`moss.exe :exec` + `MOSS_UI_EMBED=1`，就是 embed_start 那条）")
    print("   ★ 为什么要经 moss.exe、不能直接 `python main.py`：moss 自带运行时是**隔离模式**，")
    print("     直接跑脚本时它连「脚本所在目录」都不在 sys.path 上（`import core` 会炸）——")
    print("     这正是 system/bootstrap.py 存在的理由。走 moss.exe 才是真链路。")
    print("=" * 72)
    env = dict(os.environ)
    env["MOSS_UI_EMBED"] = "1"
    env["MOSS_PLUGIN_DATA_DIR"] = str(tmp)
    env["MOSS_PKG_PARAMS"] = json.dumps({"args": ""})
    host = ROOT / "moss.exe"
    proc = subprocess.Popen([str(host), ":exec"],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace", bufsize=1, env=env,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for req in ({"id": 7, "method": "bootstrap", "params": {}},
                {"id": 8, "method": "cmd_list", "params": {}}):
        proc.stdin.write(json.dumps(req) + "\n")
    proc.stdin.flush()

    got, raw_lines, deadline = {}, [], time.time() + 25
    import threading
    box = []

    def reader():
        for ln in proc.stdout:
            box.append(ln.rstrip("\n"))
            if len([x for x in box if x.lstrip().startswith("{")]) >= 2:
                break

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    while time.time() < deadline and len(box) < 2:
        time.sleep(0.1)
        if proc.poll() is not None and not box:
            break
    time.sleep(0.4)                                       # 再等一小下，把尾巴收全
    raw_lines = list(box)
    try:
        proc.stdin.close()
    except Exception:                                                # noqa: BLE001
        pass
    try:
        proc.wait(timeout=10)
    except Exception:                                                # noqa: BLE001
        proc.kill()

    json_lines, junk = [], []
    for ln in raw_lines:
        if ln.lstrip().startswith("{"):
            try:
                json_lines.append(json.loads(ln))
            except ValueError:
                json_lines.append(None)
        elif ln.strip():
            junk.append(ln)
    for obj in json_lines:
        if obj:
            got[obj.get("id")] = obj
    chk("D 两条请求都回了 JSON（一行一条）", set(got) >= {7, 8},
        "拿到的 id：" + str(sorted(k for k in got if k is not None)))
    chk("D **每一行以 `{` 开头的都是合法 JSON**（协议没被撕）",
        bool(json_lines) and all(json_lines), repr(raw_lines)[:200])
    chk("D bootstrap 那条 ok 且自证内嵌",
        (got.get(7) or {}).get("ok") is True and
        ((got.get(7) or {}).get("result") or {}).get("embedded") is True, "")
    chk("D cmd_list 那条 ok", (got.get(8) or {}).get("ok") is True, "")
    chk("D 那些**不是** JSON 的行（宿主横幅 / 我们自己的日志）不影响协议 —— 宿主会当输出收走",
        all(not j.startswith('{"id"') for j in junk),
        "非 JSON 行 %d 条，例如：%s" % (len(junk), (junk[0][:60] if junk else "")))
    chk("D 我们那句日志也确实到了管道里（给命令行看的）",
        any("内嵌模式起来了" in j for j in junk), "")
    chk("D stdin 关掉就自己退出（宿主收进程那一下）", proc.returncode == 0, str(proc.returncode))

    print()
    print("=" * 72)
    print("E：**用户真数据没被碰**")
    print("=" * 72)
    real_after = sorted(q.name for q in real_dir.glob("cmds/*.json")) if real_dir.is_dir() else []
    chk("E 真·命令目录一个文件都没变", real_before == real_after,
        "%s → %s" % (len(real_before), len(real_after)))

    print()
    print("=" * 72)
    print("F：**页面那半**（无头浏览器真渲染 exec 的 ESM 页面，驱动它去调后端）")
    print("   ★ 这一半验的是「参数形状」：垫片两种环境都只传一个对象，页面也必须发对象 ——")
    print("     独立窗口那条路（`window.pywebview.api[方法](params)`）一起验到了。")
    print("=" * 72)
    ok_page, n_page, bad_page = page_phase(tmp)
    res.append(("F 页面那半（%d 条）" % n_page, ok_page, "失败 %d" % bad_page if not ok_page else ""))

    shutil.rmtree(tmp, ignore_errors=True)

    print()
    print("=" * 72)
    badN = [x for x in res if not x[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not badN else "✗ 有不对的", len(res), len(badN)))
    return 0 if not badN else 1


if __name__ == "__main__":
    sys.exit(main())
