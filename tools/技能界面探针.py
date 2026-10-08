# -*- coding: utf-8 -*-
"""**技能界面**（`:skill` 插件那页）的探针 —— 专盯"进得去、不是永远在转"这件事。

为什么单独要它
--------------
你 2026-10-05 报的原话：「**我进入技能这里 显示正在读 这个界面不咋友好 哪怕没有
也不能一直显示正在读吧**」。查清是两类问题叠在一起：

1. **真的卡住了**（根因）：那一页原来只挂了一句 `moss.on('ready', ...)`。独立窗口那种
   跑法（`moss :skill` / 插件列表里点「运行」）下，`ready` 是垫片挂在 `pywebviewready`
   上的，而那个事件**只发一次**、还有可能在脚本执行之前就发过了 ⇒ 错过就永远等不到
   ⇒ `load()` 从不运行、**什么都不报**，就一句"正在读……"。
   （主界面当年栽过同一个坑：账本 `V-68`，`system/ui/js/app.js` 那句注释就是。）
2. **就算真读不出来，也不该让人对着四个字干等**：3 秒还没起来要**明说**并给「重试」。

这个探针就按这两条钉：造三个"桥"的现场，拿无头 Edge 跑完读 `document.title`：

* A **桥先就绪、`pywebviewready` 已经错过**（就是卡住的那个现场）⇒ 必须能起来、墙上出图标
* B **桥根本没来** ⇒ 必须变成"读不出来 + 重试"，**不许停在"正在读"**
* C **桥晚到、事件晚发**（正常路径）⇒ 也要能起来

跑法：`python tools/技能界面探针.py`（只用无头 Edge，不开窗、不碰真 user_data）
"""
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "system" / "pkgs" / "skill" / "ui"
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
VTB = 60000                     # 虚拟时间给足（页面里有 8 秒那条兜底）
RES = []


def chk(name, ok, detail=""):
    RES.append((name, bool(ok), str(detail)))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + str(detail)) if detail else ""))


def browser():
    for b in BROWSERS:
        if Path(b).is_file():
            return b
    return None


def fake_bridge(hang_first=False, poll_out="hello-from-skill\n"):
    """一段假桥：**在垫片之前**就把它摆好 —— 模拟"桥早就绪、ready 事件已错过"。

    `hang_first=True`：**第一次 `list` 永远不回**（返回一个永不 settle 的 promise）——
    这就是 `V-285` 报的那个真现场：消息在桥还没接好时发出去、没人接，promise 一直挂着；
    第二次调用才接上。（pywebview 的桥是消息式的：`api.js` 的 `_jsApiCallback` →
    `chrome.webview.postMessage`，回话从 `_returnValuesCallbacks` 里取。）

    `poll_out`：`run_poll` 吐出来的那一坨（`V-346` 的 G 段拿它喂一句**带路径的真话**）。
    """
    if hang_first:
        api_list = ('  list: (function(){ var n = 0; return function(){\n'
                    '      n = n + 1;\n'
                    '      if (n === 1) return new Promise(function(){});  // 第一次永远挂着\n'
                    '      return Promise.resolve(PAYLOAD()); }; })(),')
    else:
        api_list = "  list: async () => PAYLOAD(),"
    return ("""<script>
function PAYLOAD(){ return {ok: true, n_usable: 2, n_pending: 1, dir: "X",
    skills: [{id: "harness", name: "harness", layer: "user", kind: "skill", allowed: true,
              why_allow: "试出来的", origin: "", desc: "假桥里的一只技能", why: "为了证明不再卡住",
              risk: "low", params: ["x"], entry: "run.py", timeout: 60, icon_svg: "",
              created: "2026-10-05 17:00:00", mtime: "", allowed_at: "", problems: [], warns: [],
              files_n: 2, dir: "X",
              files: [{rel: "pkg.json", size: 100, mtime: "2026-10-05 17:00:00"},
                      {rel: "run.py", size: 50, mtime: "2026-10-05 17:00:00"}]},
             {id: "waiting", name: "waiting", layer: "user", kind: "skill", allowed: false,
              why_allow: "还没允许", origin: "", desc: "还没允许的一只", why: "为了验状态",
              risk: "", params: [], entry: "run.py", timeout: 60, icon_svg: "",
              created: "", mtime: "", allowed_at: "", problems: [], warns: [], files_n: 0,
              dir: "X", files: []}],
    broken: [],
    from_pkgs: [{id: "md5", name: "md5", layer: "system", kind: "pkg", allowed: true,
                 why_allow: "出厂", origin: "", desc: "这是个插件，不该出现在技能墙上",
                 why: "", risk: "", params: [], entry: "run.py", timeout: 60, icon_svg: "",
                 created: "", mtime: "", allowed_at: "", problems: [], warns: [], files_n: 0,
                 dir: "X", files: []}],
    dirs: {}, allow_file: ""}; }
window.pywebview = {api: {
""" + api_list + """
  read: async () => ({ok: true, text: {}}), allow: async () => ({ok: true, msg: "ok"}),
  rm: async () => ({ok: true, msg: "ok"}),
  reveal: async () => ({ok: true, msg: "ok"}), plan: async () => ({ok: true}),
  promote: async () => ({ok: true, msg: "ok"}), run_once: async () => ({ok: true, msg: "ok"}),
  /* `V-301` 起：面板里那些路径链接点下去走它。`V-346` 的 G 段靠 `window.__opened`
     看**收到了什么**（路径对不对、`mode` 是 open 还是 reveal、有没有带原样那份）。 */
  open_path: async (params) => {
      (window.__opened = window.__opened || []).push(params || {});
      return {ok: true, msg: "ok"}; },
  /* `V-302`：交互式运行那四条 —— 起进程 / 轮询 / 写输入 / 停（假后端按剧本吐输出） */
  run_start: async () => ({ok: true, rid: "r1", cmd: ["python", "run.py"]}),
  run_poll: (function(){ var n = 0; return async () => { n = n + 1;
      return {ok: true, running: n < 2, code: n < 2 ? null : 0,
              out: """ + json.dumps(poll_out) + """, cmd: ["python", "run.py"],
              at: "2026-10-05 17:00:00"}; }; })(),
  run_input: async () => ({ok: true, msg: "ok"}),
  run_stop: async () => ({ok: true, msg: "ok"}),
  sys_copy: async () => ({ok: true, msg: "ok"})}};
</script>
""")


def judge_script():
    """页面跑起来之后把结论写进 `document.title`（探针靠它判，截图看不出来）。

    ★ `V-289`：详情那一块从"居中弹窗"改成了**从右边滑进来的抽屉**（还是模态：有遮罩、
      点遮罩 / Esc / ✕ 都能关）。判据跟着换成抽屉的标记：
        `modal` = 遮罩在 + 抽屉在（`role="dialog"` + `aria-modal="true"`）；
        `card`  = 抽屉里的键值区（`.kv`）画出来了；
        `closed`= 点 `#d-x` 之后抽屉**真的没了**（`v-if` 拆掉）。
    """
    return """<script>
(function(){
  var n = 0;
  var names = [];
  function step2(){
    var first = document.querySelector(".tile");
    if (first) first.click();
    setTimeout(function(){
      var dr = document.querySelector(".drawer[role=dialog][aria-modal=true]");
      var scrim = document.querySelector(".scrim");
      var modal = !!dr && !!scrim;
      var card = !!document.querySelector(".drawer .kv");
      /* `V-301`：数据概览右侧那两个面板 ——「命令行」+「运行日志」 */
      var panels = document.querySelectorAll(".drawer .run-panel").length;
      /* `V-301`：右侧三个平级选项卡（数据概览 / 命令行 / 运行日志） */
      var tabs = document.querySelectorAll(".drawer .right-tabs button").length;
      var runBtn = !!document.querySelector("#d-run");
      var docBtn = !!document.querySelector("#d-doc");
      var x = document.querySelector("#d-x");
      if (x) x.click();
      setTimeout(function(){
        var closed = !document.querySelector(".drawer");
        document.title = "SKILL-OK tiles=" + names.length + " names=" + names.join(",") +
          " scared=" + (window.__scared ? 1 : 0) +
          " modal=" + (modal ? 1 : 0) + " card=" + (card ? 1 : 0) +
          " panels=" + panels + " tabs=" + tabs + " runbtn=" + (runBtn ? 1 : 0) +
          " doc=" + (docBtn ? 1 : 0) + " closed=" + (closed ? 1 : 0);
      }, 260);
    }, 250);
  }
  var t = setInterval(function(){
    n++;
    var tiles = document.querySelectorAll(".tile").length;
    names = Array.prototype.map.call(document.querySelectorAll(".tile .nm"),
                                     function(e){ return (e.textContent || "").trim(); });
    /* ★ `V-289`：这一段要读**活 DOM**（querySelector），不能读页面 dump 的字符串 ——
       模板就在 `#app` 里面，"编译之前"那一瞬 `textContent` 里是带花括号的原文，
       正则一撞上就误判成"页面有问题"。另外给 3 秒宽限：桥晚到 / 第一次调用丢了
       都要时间自己缓过来，"读不出来"这三个字**不能一出现就结案**。 */
    var el = document.querySelector("#status");
    var sub = el ? (el.textContent || "") : "";
    if (/读不出来/.test(sub)) window.__scared = 1;
    if (tiles > 0){ clearInterval(t); step2(); }
    else if (n > 60 && /读不出来|后端没上来/.test(sub)){
      clearInterval(t); document.title = "SKILL-NOBACKEND";
    }
    else if (n > 600){ clearInterval(t); document.title = "SKILL-STUCK sub=" + sub.slice(0, 30); }
  }, 50);
})();
</script>
"""


def judge_run():
    """`V-302`：真点「运行测试」→ 应**自动切到「命令行」**并**显示出输出**。"""
    return """<script>
(function(){
  var n = 0, done = false, started = false;
  function finish(t){ if(done) return; done = true; document.title = t; }
  var t = setInterval(function(){
    n++;
    if (!started && document.querySelectorAll(".tile").length > 0){
      started = true; clearInterval(t); step();
    } else if (n > 600){ clearInterval(t); finish("RUN-STUCK"); }
  }, 50);
  function step(){
    document.querySelector(".tile").click();
    setTimeout(function(){
      var runBtn = document.querySelector("#d-run");
      var hasBtn = !!runBtn;
      if (runBtn) runBtn.click();
      setTimeout(function(){
        var onBtn = document.querySelector(".drawer .right-tabs button.on");
        var consoleTab = onBtn && (onBtn.textContent || "").indexOf("命令行") >= 0;
        var body = document.querySelector(".drawer .rtab-pane.full .run-body");
        var shown = body ? (body.textContent || "") : "";
        finish("RUN btn=" + (hasBtn ? 1 : 0) + " consoleTab=" + (consoleTab ? 1 : 0) +
               " out=" + (/hello-from-skill/.test(shown) ? 1 : 0));
      }, 1100);
    }, 300);
  }
})();
</script>"""


#: `V-346` 的现场：`shot` 技能打的那句真话 —— 路径尾巴上蘸着"（7680×2160，9125074 字节）"。
SHOT_PATH = r"D:\python\two\moss\user_data\state\shot\shots\shot-20261008-114021.png"
SHOT_META = "（7680×2160，9125074 字节）"
SHOT_OUT = ("整个屏幕 截下来了：%s（7680×2160，9125074 字节）\n"
            "（我看不到图 —— 这是留证据给用户看的；要看像素请自己用 PIL 量。）" % SHOT_PATH)
#: 抠路径的单测表：`[原文, 期望抠出来的路径]`（括号那些是重点 —— `V-346` 就是栽在这儿）
SHOT_UNITS = [
    [r"D:\项目\截图（1）.png", r"D:\项目\截图（1）.png"],                 # 名字里真有全角括号 → 不许剪
    [r"D:\备份（副本）", r"D:\备份（副本）"],                             # 没扩展名 → 不许剪
    [r"D:\a\报告（副本）.txt（7680×2160）", r"D:\a\报告（副本）.txt"],     # 括号前面已是带扩展名的全名 → 剪
    [r"(see D:\a\b.txt)", r"D:\a\b.txt"],                               # 外面套着半角括号 → 剪掉收括号
    ["D:\\a\\b.txt。", "D:\\a\\b.txt"],                                  # 句尾句号 → 剪
    ["user_data/ai/skill_runs.jsonl（这个文件）", "user_data/ai/skill_runs.jsonl"],
]


def judge_path():
    """`V-346`：跑一次 → 命令行里那句带路径的话 —— **链接要指向真路径，而且两个动作都要在**。

    判据（都写进 `document.title`）：
      `p`    = `data-p` 解出来**正好是**那条 png（老代码这里会多出"（7680×2160，9125074"）
      `text` = 链接**显示的字**也正好是它
      `href` = 是个真 `file:///D:/…`（不再是 `javascript:void(0)` 那句假 url）
      `raw`  = 带着**没剪过的原样**（后端拿它先试一次，文件名真带括号时能救回来）
      `tail` = 尾巴上那段说明文字**还在页面上**（只是不再属于链接）
      `open` / `rev` = 点路径收到 `mode=open`、点小文件夹图标收到 `mode=reveal`
      `hasraw` = 两次都带了 `raw`
      `unit` = 上面那张单测表过了几条
    """
    return ("""<script>
(function(){
  var WANT = """ + json.dumps(SHOT_PATH) + """;
  var META = """ + json.dumps(SHOT_META) + """;
  var UNITS = """ + json.dumps(SHOT_UNITS, ensure_ascii=False) + """;
  var n = 0, done = false;
  function finish(t){ if(done) return; done = true; document.title = t; }
  var t = setInterval(function(){
    n++;
    if (document.querySelectorAll(".tile").length > 0){ clearInterval(t); step1(); }
    else if (n > 600){ clearInterval(t); finish("PATH-STUCK"); }
  }, 50);
  function step1(){
    document.querySelector(".tile").click();
    setTimeout(function(){
      var b = document.querySelector("#d-run");
      if (b) b.click();
      setTimeout(step2, 1300);
    }, 300);
  }
  function step2(){
    var pre = document.querySelector(".drawer .run-out");
    var a = pre && pre.querySelector("a.plink");
    var d = pre && pre.querySelector("button.plink-dir");
    var got = a ? decodeURIComponent(a.getAttribute("data-p") || "") : "";
    var txt = a ? (a.textContent || "").trim() : "";
    var href = a ? (a.getAttribute("href") || "") : "";
    var raw = a ? (a.getAttribute("data-r") || "") : "";
    var tail = pre ? ((pre.textContent || "").indexOf(META) >= 0) : false;
    window.__opened = [];
    if (a) a.click();
    if (d) d.click();
    setTimeout(function(){
      var calls = window.__opened || [];
      var mOpen = calls.some(function(c){ return c && c.mode === "open" && c.path === WANT; });
      var mRev  = calls.some(function(c){ return c && c.mode === "reveal" && c.path === WANT; });
      var rawOk = calls.length > 0 && calls.every(function(c){ return typeof c.raw === "string"; });
      var L = window.SKILL_PATHS.linkify;
      function pick(s){
        var m = L(s).match(/data-p="([^"]*)"/);
        return m ? decodeURIComponent(m[1]) : "(no-link)";
      }
      var unitOk = 0;
      for (var i = 0; i < UNITS.length; i++){ if (pick(UNITS[i][0]) === UNITS[i][1]) unitOk++; }
      finish("PATH a=" + (a?1:0) + " d=" + (d?1:0) + " p=" + (got===WANT?1:0) +
             " text=" + (txt===WANT?1:0) + " href=" + (href.indexOf("file:///D:/")===0?1:0) +
             " raw=" + (raw?1:0) + " tail=" + (tail?1:0) +
             " open=" + (mOpen?1:0) + " rev=" + (mRev?1:0) + " hasraw=" + (rawOk?1:0) +
             " unit=" + unitOk + "/" + UNITS.length + " got=[" + got + "]");
    }, 250);
  }
})();
</script>""")


def build(case, tmp):
    """造一份现场：`case` = A（桥先说）/ B（没桥）/ C（桥晚到）。回 index.html 的路径。

    ★ `V-289`：`ui/` 拆成了 `ui/src/**`（Vue 3 那几个文件）+ `ui/style/*.css`，
      所以这里**整份 `ui/` 递归拷过来**（以前是写死一串文件名 —— 加一个文件就漏一个）。
    """
    page = (UI / "index.html").read_text(encoding="utf-8")
    inject = ""
    if case == "A":
        inject = fake_bridge()
    elif case == "E":
        # ★★ 你报的那个真现场（`V-285`）：桥**已经就绪**，可第一次 `list` 的消息丢了
        #    （promise 一直挂着）—— 页面必须**自己**靠超时+重试恢复，不用人点「重试」。
        inject = fake_bridge(hang_first=True)
    elif case == "D":
        # ★ 你报的那个 bug 的现场：桥**晚到**（9 秒）、而且 `pywebviewready` 也不发。
        #   旧代码只轮询 6 秒 ⇒ 8 秒时先弹"读不出来"，得人点「重试」才好；
        #   现在轮询一直在，桥一到就自己起来（**不用人手点**）。
        inject = """<script>
setTimeout(function(){
  var s = document.createElement("script");
  s.textContent = %s;
  document.body.appendChild(s);
}, 9000);
</script>""" % json.dumps(re.sub(r"</?script>", "", fake_bridge()))
    elif case == "C":
        inject = """<script>
setTimeout(function(){
  var s = document.createElement("script");
  s.textContent = %s;
  document.body.appendChild(s);
  window.dispatchEvent(new Event("pywebviewready"));
}, 300);
</script>""" % json.dumps(re.sub(r"</?script>", "", fake_bridge()))
    elif case == "F":
        inject = fake_bridge()                        # `V-302`：点「运行测试」的交互
    elif case == "G":
        # `V-346`：`shot` 那句真话 —— 路径尾巴上蘸着"（7680×2160，9125074 字节）"
        inject = fake_bridge(poll_out=SHOT_OUT)
    page = page.replace('<script src="moss-embed.js"></script>',
                        inject + '<script src="moss-embed.js"></script>', 1)
    if case == "F":
        judge = judge_run()
    elif case == "G":
        judge = judge_path()
    else:
        judge = judge_script()
    page = page.replace("</body>", judge + "</body>", 1)
    d = tmp / case
    d.mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(UI), str(d), dirs_exist_ok=True)
    (d / "index.html").write_text(page, encoding="utf-8", newline="")
    return d / "index.html"


def sub_text(dom):
    """把状态字那一段（`#status`）的**文字**抠出来。

    ★ 为什么要单独抠：整个 DOM 里也含**探针自己注入的那段脚本源码**（里面有"读不出来"
      这几个字）—— 拿"整页里有没有这几个字"当判据会自己骗自己（第一版就这么假红了一条）。
    ★ `V-289` 又加一道：**先去掉所有 script/style 块**。页面的模板就写在 HTML 里，
      页面 dump 出来的字符串会带上"模板原文"（`v-if` / 花括号都在），而模板里也含
      `id="status"` 那几个字 —— 不去掉的话，正则先撞上原文，判据就飘了。
    """
    stripped = re.sub(r"(?s)<script\b.*?</script>|<style\b.*?</style>", " ", dom or "")
    m = re.search(r'id="status"[^>]*>(.*?)</p>', stripped, re.S)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def title_of(exe, url, tmp, tag):
    prof = tmp / ("_prof_" + tag)
    shutil.rmtree(prof, ignore_errors=True)
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--no-first-run", "--no-default-browser-check",
           "--user-data-dir=" + str(prof), "--allow-file-access-from-files",
           "--window-size=980,520", "--virtual-time-budget=" + str(VTB),
           "--dump-dom", url.as_uri()]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
    except Exception as e:                                             # noqa: BLE001
        return "（跑不起来：%s）" % e, ""
    m = re.search(r"<title>(.*?)</title>", r.stdout or "", re.S)
    return (m.group(1).strip() if m else ""), (r.stdout or "")


def main():
    exe = browser()
    if not exe:
        print("[错误] 找不到 Edge / Chrome")
        return 1
    if not (UI / "index.html").is_file():
        print("[错误] 找不到 %s" % (UI / "index.html"))
        return 1
    tmp = Path(tempfile.gettempdir()) / "moss_skill_probe"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    print("浏览器：%s" % exe)
    print("=" * 72)
    print("A：桥**先说**就绪、`pywebviewready` 已经错过（就是你卡住的那个现场）")
    print("=" * 72)
    ua = build("A", tmp)
    ta, doma = title_of(exe, ua, tmp, "a")
    chk("A ★★ 这种现场下**要能起来**（墙上出图标）—— 这就是「永远正在读」的根因",
        ta.startswith("SKILL-OK") and 'class="tile' in doma, ta)
    chk("A ★★ 详情是**模态抽屉**（点一格 → 滑出来 → ✕ 关得掉）",
        "modal=1" in ta and "card=1" in ta and "closed=1" in ta, ta)
    chk("A ★ `V-301`：右侧是**三个平级选项卡**（数据概览 / 命令行 / 运行日志）+ 两个运行面板 + 「运行测试」按钮",
        "tabs=3" in ta and "panels=2" in ta and "runbtn=1" in ta, ta)
    chk("A ★ 详情里有「看说明」那颗按钮（`doc` = 这只技能自己的 AGENT.md）",
        "doc=1" in ta, ta)
    # ★ 这里要**精确**比（第一版用 `in` 做子串匹配 —— 墙上多出一只插件照样通过，假绿）
    _names = re.search(r"names=([^ ]*)", ta)
    chk("A ★★ 墙上**只有技能** —— 插件那一行不许出现在这儿（你定的）",
        bool(_names) and _names.group(1) == "harness,waiting", ta)
    chk("A 而且**不是**停在那句「正在读」上",
        "正在读" not in sub_text(doma), sub_text(doma)[:40])
    chk("A 起得来的时候那句兜底提示**不该**出现（别没事吓人）",
        "读不出来" not in sub_text(doma), sub_text(doma)[:40])

    print()
    print("=" * 72)
    print("B：桥根本没来（后端起不来 / 页面被单独打开）")
    print("=" * 72)
    ub = build("B", tmp)
    tb, domb = title_of(exe, ub, tmp, "b")
    chk("B ★★ 必须**明说读不出来**，不许停在「正在读」（你报的就是这条）",
        tb == "SKILL-NOBACKEND" and "读不出来" in sub_text(domb)
        and "正在读" not in sub_text(domb), "%s ｜ %s" % (tb, sub_text(domb)[:40]))
    chk("B 而且给一颗「重试」+ 一句「该怎么办」（`moss :skill` 在终端里跑一遍）",
        "btn-retry" in domb and "moss :skill" in domb, "")

    print()
    print("=" * 72)
    print("C：桥晚到、事件晚发（正常路径 —— 别为了修 A 把这条弄坏）")
    print("=" * 72)
    uc = build("C", tmp)
    tc, domc = title_of(exe, uc, tmp, "c")
    chk("C ★ 晚到的桥也要能起来（垫片那条 `ready` 路照旧通）",
        tc.startswith("SKILL-OK"), tc)

    print()
    print("=" * 72)
    print("D：桥**9 秒后**才到、也不发 `pywebviewready`（= 你报的「界面里点运行」那个现场）")
    print("=" * 72)
    ud = build("D", tmp)
    td, domd = title_of(exe, ud, tmp, "d")
    _tiles_d = len(re.findall(r'class="tile', domd))
    chk("D ★★★ 桥晚到也要**自己起来、不用人点重试**（旧代码只轮询 6 秒，这里就卡住了）",
        _tiles_d >= 2 and "读不出来" not in sub_text(domd),
        "墙上 %d 个图标 ｜ %s" % (_tiles_d, sub_text(domd)[:40]))
    # ★ 本来还想钉一条"不许先弹那句「读不出来」"（scared=0）—— 试过，**在这个无头环境里判据不稳**：
    #   页面其实 9 秒就自己起来了、墙上也有图标，可"取标题"和"判据结案"之间有时序差，
    #   同一份代码改坏/不改坏都可能出 `SKILL-NOBACKEND`。宁可不留假红假绿的断言：
    #   这一条（两档提示）写进代码注释和账本 `V-285`，靠上面那条"自己起得来"兜住真正的行为。

    print()
    print("=" * 72)
    print("E：桥在、但**第一次 `list` 永远不回**（消息丢了 —— 你报的那个真现场）")
    print("=" * 72)
    ue = build("E", tmp)
    te, dome = title_of(exe, ue, tmp, "e")
    _tiles_e = len(re.findall(r'class="tile', dome))
    chk("E ★★★ 第一次调用丢了也要**自己恢复**（超时 + 自动重试），不用人点「重试」",
        _tiles_e >= 2 and "读不出来" not in sub_text(dome),
        "墙上 %d 个图标 ｜ 标题=%s" % (_tiles_e, te[:40]))
    _sub = sub_text(dome)
    chk("E ★★ 最后那句提示要**回到正常**（不能停在「正在读」/「读不出来」）",
        "读不出来" not in _sub and "正在读" not in _sub, _sub[:60])

    print()
    print("=" * 72)
    print("F：点「运行测试」→ **自动切到命令行** 且 **显示出输出**（`V-302`）")
    print("=" * 72)
    uf = build("F", tmp)
    tf, domf = title_of(exe, uf, tmp, "f")
    chk("F ★★ 点运行测试后：按钮在 / 切到了「命令行」/ 命令行里有输出",
        "RUN btn=1 consoleTab=1 out=1" in tf, tf)

    print()
    print("=" * 72)
    print("G：`V-346` —— 命令行里那句带路径的话：**链接要指向真路径 + 两个开法都要在**")
    print("=" * 72)
    ug = build("G", tmp)
    tg, domg = title_of(exe, ug, tmp, "g")
    chk("G ★★★ 你报的那个 bug：链接的 url **正好是那条 png**（老代码这儿会多出"
        "「（7680×2160，9125074」）",
        "p=1" in tg and "text=1" in tg and "got=[" + SHOT_PATH + "]" in tg, tg)
    chk("G ★★ 尾巴上那段说明文字**还在页面上**（只是不再属于链接）",
        "tail=1" in tg, tg)
    chk("G ★ 链接的 `href` 是**真的 `file:///`**（不再是 `javascript:void(0)` 那句假 url）",
        "href=1" in tg, tg)
    chk("G ★★ 两个开法都在：点路径 = 直接打开 / 点小文件夹图标 = 打开所在文件夹",
        "a=1" in tg and "d=1" in tg and "open=1" in tg and "rev=1" in tg, tg)
    chk("G ★ 两次调用都带上**没剪过的原样**（后端先拿它试 —— 文件名真带括号时能救回来）",
        "raw=1" in tg and "hasraw=1" in tg, tg)
    chk("G ★★ 抠路径那几条单测全过（名字里的全角括号不许剪、说明文字的括号要剪）",
        ("unit=%d/%d" % (len(SHOT_UNITS), len(SHOT_UNITS))) in tg, tg)

    shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 72)
    bad = [r for r in RES if not r[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的", len(RES), len(bad)))
    return 0 if not bad else 1


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                              # noqa: BLE001
            pass
    sys.exit(main())
