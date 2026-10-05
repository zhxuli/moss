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
VTB = 30000                     # 虚拟时间给足（页面里有 8 秒那条兜底）
RES = []


def chk(name, ok, detail=""):
    RES.append((name, bool(ok), str(detail)))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + str(detail)) if detail else ""))


def browser():
    for b in BROWSERS:
        if Path(b).is_file():
            return b
    return None


def fake_bridge():
    """一段假桥：**在垫片之前**就把它摆好 —— 模拟"桥早就绪、ready 事件已错过"。"""
    return """<script>
window.pywebview = {api: {
  list: async () => ({ok: true, n_usable: 2, n_pending: 1, dir: "X",
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
    dirs: {}, allow_file: ""}),
  read: async () => ({ok: true, text: {}}), allow: async () => ({ok: true, msg: "ok"}),
  rm: async () => ({ok: true, msg: "ok"}), seed: async () => ({ok: true, msg: "ok"}),
  reveal: async () => ({ok: true, msg: "ok"}), plan: async () => ({ok: true}),
  promote: async () => ({ok: true, msg: "ok"}), run_once: async () => ({ok: true, msg: "ok"})}};
</script>
"""


def judge_script():
    """页面跑起来之后把结论写进 `document.title`（探针靠它判，截图看不出来）。"""
    return """<script>
(function(){
  var n = 0;
  var names = [];
  function step2(){
    var first = document.querySelector(".tile");
    if (first) first.click();
    setTimeout(function(){
      var d = document.querySelector("#detail");
      var modal = !!d && !d.hidden && d.classList.contains("modal");
      var card = !!document.querySelector("#detail-card .kv");
      var docBtn = !!document.querySelector("#d-doc");
      var x = document.querySelector("#d-x");
      if (x) x.click();
      setTimeout(function(){
        var closed = !!document.querySelector("#detail") &&
                     document.querySelector("#detail").hidden;
        document.title = "SKILL-OK tiles=" + names.length + " names=" + names.join(",") +
          " modal=" + (modal ? 1 : 0) + " card=" + (card ? 1 : 0) +
          " doc=" + (docBtn ? 1 : 0) + " closed=" + (closed ? 1 : 0);
      }, 120);
    }, 250);
  }
  var t = setInterval(function(){
    n++;
    var tiles = document.querySelectorAll(".tile").length;
    names = Array.prototype.map.call(document.querySelectorAll(".tile .nm"),
                                     function(e){ return (e.textContent || "").trim(); });
    var sub = ((document.querySelector("#sub") || {}).textContent || "");
    if (tiles > 0){ clearInterval(t); step2(); }
    else if (/读不出来|后端没上来/.test(sub)){ clearInterval(t); document.title = "SKILL-NOBACKEND"; }
    else if (n > 600){ clearInterval(t); document.title = "SKILL-STUCK sub=" + sub.slice(0, 30); }
  }, 50);
})();
</script>
"""


def build(case, tmp):
    """造一份现场：`case` = A（桥先说）/ B（没桥）/ C（桥晚到）。回 index.html 的路径。"""
    page = (UI / "index.html").read_text(encoding="utf-8")
    inject = ""
    if case == "A":
        inject = fake_bridge()
    elif case == "C":
        inject = """<script>
setTimeout(function(){
  var s = document.createElement("script");
  s.textContent = %s;
  document.body.appendChild(s);
  window.dispatchEvent(new Event("pywebviewready"));
}, 300);
</script>""" % json.dumps(re.sub(r"</?script>", "", fake_bridge()))
    page = page.replace('<script src="moss-embed.js"></script>',
                        inject + '<script src="moss-embed.js"></script>', 1)
    page = page.replace("</body>", judge_script() + "</body>", 1)
    d = tmp / case
    d.mkdir(parents=True, exist_ok=True)
    for f in ("moss-embed.js", "app.js", "style.css"):
        shutil.copy(str(UI / f), str(d / f))
    (d / "index.html").write_text(page, encoding="utf-8", newline="")
    return d / "index.html"


def sub_text(dom):
    """把 `#sub` 那一段的**文字**抠出来。

    ★ 为什么要单独抠：整个 DOM 里也含**探针自己注入的那段脚本源码**（里面有"读不出来"
      这几个字）—— 拿"整页里有没有这几个字"当判据会自己骗自己（第一版就这么假红了一条）。
    """
    m = re.search(r'id="sub"[^>]*>(.*?)</p>', dom or "", re.S)
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
    chk("A ★★ 详情是**模态框**（点一格 → 弹出 → ✕ 关得掉）",
        "modal=1" in ta and "card=1" in ta and "closed=1" in ta, ta)
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
