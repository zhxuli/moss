# -*- coding: utf-8 -*-
"""技能界面**内嵌那条路**（iframe）的探针：专盯"`ready` 事件被错过 ⇒ 永远正在读"。

你 2026-10-05 报的（`V-287`）
-----------------------------
「这个程序很奇怪：启动以后一直显示正在读，但是只要点一下重试，马上就好。」

机制（跟快慢无关 —— 你当初那句判断是对的）
------------------------------------------
内嵌这一帧里，`index.html` 先执行 `moss-embed.js`，**它在 `setTimeout(0)` 里 `fire('ready')`**；
紧接着解析器去取 `app.js`（本地 http、`no-store`，一次真实往返）——**取的时候它要把事件循环
转起来**，于是那个已经到点的 `setTimeout(0)` 先跑掉了。可 `boot()` 是 `app.js` 里
`moss.on('ready', boot)` 挂上去的，此刻**还没挂** ⇒ 这一枪打空了：
`load()` 从来没运行过（`_booted` 一直 false）⇒ 页面停在「正在读……」，
6 秒后 `slowHint()` 弹出「重试」；人一点 ⇒ `load()` **第一次**真正发出去 ⇒ **马上就好**。

所以 `V-285`/`V-286` 那两版（把超时 / 重试做在 `load()` 里面）**治不到它**：`load()` 压根没跑。
`moss :skill gui`（独立窗口）能一次读出来，是因为那条路 `app.js` 另有"轮询桥"的兜底。

探针怎么钉
----------
一个**假宿主**（同源 http 上的 `host.html`）+ **真页面**（真 `index.html` / `moss-embed.js` /
`app.js`）。假宿主只做真宿主那一下：收到帧的 `call` → 隔几毫秒把结果 `postMessage` 回那一帧。
判据只有一条：**谁也不点**，墙上出不出图标；顺带记 1.2 秒 / 7 秒两个快照（后者看有没有被逼出
「重试」）。

* E1 亲现场：本机 http 取回就够触发（`--app-delay 0`）
* E2 机理对照：给 `app.js` 的取回加一点延时（`--app-delay 60`）⇒ 结论应当**一模一样**

跑法：`python tools\\技能内嵌探针.py`（只用无头 Edge，不开窗；不碰真 `user_data`）
"""
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "system" / "pkgs" / "skill" / "ui"
BROWSERS = [r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"]
#: 假宿主把 `load` 事件往后拖这么久（一张慢图片）—— `--dump-dom` 是**页面 load 之后**才吐，
#: 拖住它才拿得到"7 秒那个快照"。页面那侧是**实时**的：不用虚拟时间，虚拟时间会把这次竞态洗掉。
SLOW_MS = 8000
#: 1x1 全透明 PNG（就是拿来拖住 load 的，内容无所谓）
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c6300010000050001" "0d0a2db4"
    "0000000049454e44ae426082")
RES = []


def chk(name, ok, detail=""):
    RES.append((name, bool(ok), str(detail)))
    print("  %s %s%s" % ("OK  " if ok else "FAIL", name, ("   ← " + str(detail)) if detail else ""))


def browser():
    for b in BROWSERS:
        if Path(b).is_file():
            return b
    return None


#: 假宿主回的那份 payload（形状照 `Api.list` 来）—— 两只技能，墙上就该出两个图标
PAYLOAD = """{ok: true, n_usable: 1, dir: "X", broken: [],
 skills: [{id: "harness", name: "harness", layer: "user", kind: "skill", allowed: true,
           why_allow: "试出来的", origin: "", desc: "假宿主里的一只技能", why: "为了证明不再卡住",
           risk: "low", params: ["x"], entry: "run.py", timeout: 60, icon_svg: "",
           created: "2026-10-05 17:00:00", mtime: "", allowed_at: "", problems: [], warns: [],
           files_n: 2, dir: "X",
           files: [{rel: "pkg.json", size: 100, mtime: "2026-10-05 17:00:00"}]},
          {id: "waiting", name: "waiting", layer: "user", kind: "skill", allowed: false,
           why_allow: "还没允许", origin: "", desc: "还没允许的一只", why: "为了验状态",
           risk: "", params: [], entry: "run.py", timeout: 60, icon_svg: "",
           created: "", mtime: "", allowed_at: "", problems: [], warns: [], files_n: 0,
           dir: "X", files: []}]}"""

HOST = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>HOST</title></head>
<body>
<!-- ★ 这张慢图片不是装饰：`--dump-dom` 是**页面 load 之后**才吐 DOM，
     把它拖到 8 秒，页面里那两个快照（1.2 秒 / 7 秒）才来得及被读走。 -->
<img src="/slow.png?ms=%%SLOW%%" alt="" style="display:none">
<iframe id="f" src="/child/index.html" style="width:900px;height:460px;border:0"></iframe>
<script>
/* 假宿主：真宿主那一下（收到帧的 call → embed_send → 后端 → 结果 postMessage 回**那一帧**）。
   这里只留"隔几毫秒回一句"—— 后端往返本来就是几毫秒。 */
var PAYLOAD = %PAYLOAD%;
var CALLS = 0;                 // ★ 数一下**帧到底发过几次请求**（= Python 那边 print 能打几次）
window.addEventListener('message', function (ev) {
  var m = ev.data;
  if (!m || m.moss !== 1) return;
  if (m.kind === 'call') {
    CALLS++;
    var f = document.getElementById('f');
    setTimeout(function () {
      f.contentWindow.postMessage({moss: 1, kind: 'result', id: m.id, ok: true,
                                   result: PAYLOAD}, '*');
    }, 4);
  } else if (m.kind === 'ready') {
    // 真宿主还会推 theme / visible —— 那两条跟"起不起来"无关，这里不推
  }
});

function snap() {
  var d = null;
  try { d = document.getElementById('f').contentDocument; } catch (e) { return 'no-doc'; }
  if (!d) return 'no-doc';
  /* ★ `V-289`：状态字那一段从 `#sub` 改名成 `#status`（现在还会显示技能数和目录） */
  var sub = d.querySelector('#status');
  var text = sub ? (sub.textContent || '') : '(no-sub)';
  return 'calls=' + CALLS + ' tiles=' + d.querySelectorAll('.tile').length +
         ' retry=' + (d.querySelector('#btn-retry') ? 1 : 0) +
         ' sub=' + JSON.stringify(text.replace(/\\s+/g, ' ').trim());
}
var first = '', late = '';
setTimeout(function () { first = snap(); }, 1200);
setTimeout(function () {
  late = snap();
  document.title = 'V first[' + first + '] late[' + late + ']';
}, 7000);
document.title = 'V 太早了';
</script>
</body></html>
"""


def build(tmp, app_delay, shim=None, app=None):
    """造现场：真页面 + 假宿主。`shim` / `app` 给了就换成那份（红测用：临时塞旧版本）。

    ★ `V-289`：`ui/` 拆成了 `ui/src/**`（Vue 3 那几个文件）+ `ui/style/*.css`，
      所以这里**整份 `ui/` 递归拷过来**（以前是写死一串文件名 —— 加一个文件就漏一个）。
    """
    (tmp / "child").mkdir(parents=True, exist_ok=True)
    shutil.copytree(str(UI), str(tmp / "child"), dirs_exist_ok=True)
    if shim:
        shutil.copy(str(shim), str(tmp / "child" / "moss-embed.js"))
    if app:
        shutil.copy(str(app), str(tmp / "child" / "src" / "app.js"))
    (tmp / "host.html").write_text(
        HOST.replace("%%SLOW%%", str(SLOW_MS)).replace("%PAYLOAD%", PAYLOAD),
        encoding="utf-8", newline="")
    return tmp / "host.html"


class Handler(SimpleHTTPRequestHandler):
    """静态文件（照 moss 那个内嵌服务：`Cache-Control: no-store`）+ 两条人造延时。"""

    def __init__(self, *a, app_delay=0, **kw):
        self.app_delay = app_delay
        super().__init__(*a, **kw)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")        # 跟 moss 的内嵌服务一致
        super().end_headers()

    def do_GET(self):                                        # noqa: N802
        if self.path.startswith("/slow.png"):
            m = re.search(r"ms=(\d+)", self.path)
            time.sleep((int(m.group(1)) if m else SLOW_MS) / 1000.0)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(PNG)))
            self.end_headers()
            self.wfile.write(PNG)
            return
        if self.app_delay and self.path.endswith("/child/src/app.js"):
            time.sleep(self.app_delay / 1000.0)              # ★ 就是"取回 app.js 花的那一下"
        return super().do_GET()

    def log_message(self, *a):                               # 别刷屏
        pass


def serve(d, app_delay):
    srv = ThreadingHTTPServer(("127.0.0.1", 0),
                              partial(Handler, directory=str(d), app_delay=app_delay))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def run(exe, url, prof):
    shutil.rmtree(prof, ignore_errors=True)
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--no-first-run", "--no-default-browser-check",
           "--user-data-dir=" + str(prof), "--window-size=1100,620",
           "--dump-dom", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=180)
    except Exception as e:                                             # noqa: BLE001
        return "（跑不起来：%s）" % e
    m = re.search(r"<title>(.*?)</title>", r.stdout or "", re.S)
    return (m.group(1).strip() if m else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app-delay", type=int, default=0,
                    help="给 app.js 的取回加多少毫秒（0＝本机真实取回；60＝机理对照）")
    ap.add_argument("--shim", default="", help="换一份 moss-embed.js（红测：塞旧的那份）")
    ap.add_argument("--app", default="", help="换一份 app.js（红测：塞旧的那份）")
    args = ap.parse_args()
    exe = browser()
    if not exe:
        print("[错误] 找不到 Edge / Chrome")
        return 1
    if not (UI / "index.html").is_file():
        print("[错误] 找不到 %s" % (UI / "index.html"))
        return 1
    print("浏览器：%s" % exe)
    print("=" * 72)
    print("E：**内嵌那一帧**（iframe）—— 谁也不点，墙上该自己出图标")
    print("   （app.js 取回延时 %dms%s%s）"
          % (args.app_delay,
             "；垫片用的是 " + args.shim if args.shim else "",
             "；app.js 用的是 " + args.app if args.app else ""))
    print("=" * 72)
    tmp = Path(tempfile.gettempdir()) / "moss_skill_embed_probe"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        build(tmp, args.app_delay, args.shim or None, args.app or None)
        srv, port = serve(tmp, args.app_delay)
        try:
            title = run(exe, "http://127.0.0.1:%d/host.html" % port, tmp / "_prof")
        finally:
            srv.shutdown()
            srv.server_close()
        print("     %s" % (title or "（没读到标题）"))
        f = re.search(r"first\[(.*?)\]", title or "")
        l = re.search(r"late\[(.*?)\]", title or "")
        f1, l1 = (f.group(1) if f else ""), (l.group(1) if l else "")
        chk("E ★★★ 不点任何东西，1.2 秒时墙上就该有图标（这就是你报的那条）",
            "tiles=2" in f1, f1 or title)
        chk("E ★★★ 而且**第一次请求确实发出去了**（`calls=1`；坏的时候是 `calls=0` —— "
            "Python 那边连一次 `list` 都没收到，print 当然打不出来）",
            "calls=1" in f1, f1 or title)
        chk("E ★★ 也不许停在「正在读」（`load()` 必须**自己**跑起来）",
            "正在读" not in f1 and "正在读" not in l1, "%s ｜ %s" % (f1, l1))
        chk("E ★★ 更不该被逼出「重试」那颗按钮（有它＝得人手点，就是你看见的）",
            "retry=0" in f1 and "retry=0" in l1, "%s ｜ %s" % (f1, l1))
        chk("E 7 秒时最后那句提示是正常的（数量 + 目录），不是兜底话",
            "tiles=2" in l1 and "正在读" not in l1 and "读不出来" not in l1, l1 or title)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print()
    print("=" * 72)
    bad = [r for r in RES if not r[1]]
    print("结论：%s（%d 条，失败 %d）" % ("✅ 全过" if not bad else "✗ 有不对的", len(RES), len(bad)))
    if args.app_delay == 0:
        print("机理对照（结论应当一模一样）：python tools\\技能内嵌探针.py --app-delay 60")
    return 0 if not bad else 1


if __name__ == "__main__":
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                              # noqa: BLE001
            pass
    sys.exit(main())
