#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面预览：把 `system/ui` 复制到临时目录、注入一套假 API，用**无头浏览器**截图。

为什么要有它
------------
静态检查（`node --check`、id 唯一、`pywebview.api.*` 与后端对账）**看不出运行时异常、
也看不出"丑"**。2026-09-28 那轮就吃了亏：`fmState()` 里一个变量名撞车，让
**整个「文件管理」打不开**，而所有静态检查都是绿的 —— 把页面真渲染出来一看才发现。
（pywebview 自己的 `evaluate_js` 在这台机器上会 `0xC0000005`，所以走浏览器这条路。）

它做什么
--------
1. 把 `system/ui/` 整份**复制**到 `%TEMP%\\moss_ui_preview\\`
   （★ 仓库一个字节都不碰 —— 别在真界面目录里塞预览用的假文件）；
2. 往副本的 `index.html` 里插一段假 `pywebview.api` + 一个"场景"脚本；
3. 每个场景用一个**独立的浏览器 profile** 跑一次
   （同一个 profile 下第二次启动会把命令行转交给已在跑的实例，
     `--screenshot` 就不生效了 —— 会截出上一个场景的残留，实测踩过）；
4. 截图落在 `%TEMP%\\moss_ui_shots\\<场景>.png`。

为什么仓库里不放截图：它只是**给人看**的中间产物，不是交付物。

用法
----
    venv\\Scripts\\python.exe tools\\界面预览.py                 # 全部场景
    venv\\Scripts\\python.exe tools\\界面预览.py pkg hist        # 只截这两个

场景（写进 URL 的 `#` 后面）
    pkg              选一个包，停在「详情」
    pkg-console      选一个包，「命令行」
    pkg-file         选一个包，「文件管理」
    pkg-file-open    选一个包，「文件管理」里再打开一个文件（编辑器那一页）
    hist             切到「历史」，选中第一条，停在「详情」
    hist-file        同上，切到「文件管理」（看 `abs/` 那个第三根）
    hist-console     同上，切到「命令行」
    edit-manifest    打开 md5 的 pkg.json → 改名 → 保存（看左边列表有没有跟着变）
    edit-manifest-detail  同上，最后停在「详情」

★ 它**不替代**人肉点一遍：假 API 只喂了够渲染的数据，真正的运行/停止/写文件
  还是要在真界面里试。
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ★ 必须显式告诉 `core.paths` 安装根在哪：它是按 `sys.argv[0]` 定位的，从 `tools/` 里跑会算成
#   `tools/` ⇒ 扫到 0 个包，mock 里只剩那个合成包 ⇒ drop 这些场景全挂（`V-79` 踩过，
#   当时还以为是组件化改坏了）。
os.environ.setdefault("MOSS_HOME", str(ROOT))
SRC = ROOT / "system" / "ui"
PRE = Path(__import__("tempfile").gettempdir()) / "moss_ui_preview"
SHOTS = Path(__import__("tempfile").gettempdir()) / "moss_ui_shots"

BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
]

SCENES = ["pkg", "pkg-console", "pkg-file", "pkg-file-open", "pkg-odd-dir",
          "pkg-renamed-file", "pkg-align-file", "pkg-edit-id", "pkg-edit-bad-id",
          "btn-detail", "err-path", "args-clear", "backup", "backup-restore", "backup-sync", "backup-export", "backup-groups",
          "drop-hot", "drop-dir", "drop-file", "console-input", "embed", "pane-resize",
          "flat-buttons", "backup-diff", "refresh-keep-ctx", "compare", "hist-snap", "modal-kinds", "snap-modal",
          "statusbar", "settings", "settings-exec", "settings-format", "settings-adv",
          "settings-bad", "settings-warn", "settings-tip",
          "hist", "hist-console", "hist-file",
          "edit-manifest", "edit-manifest-detail"]


def browser():
    for b in BROWSERS:
        if Path(b).is_file():
            return b
    return None


def js_syntax_problem(js):
    """用 node 检查一段 JS 的语法。没问题返回 ""，有问题返回那几行报错。

    没装 node 就直接放过（这工具本来只是个"截图看看"的辅助，不该因此罢工）。
    """
    node = shutil.which("node")
    if not node:
        return ""
    fd, name = __import__("tempfile").mkstemp(suffix=".js")
    os.close(fd)
    tmp = Path(name)
    try:
        # `MOCK_JS` 是**带 `<script>` 标签的一整段**（要塞回 HTML 里），查语法得先把
        # 标签剥掉，否则 node 只会说"Unexpected token '<'"
        body = js.split("<script>", 1)[-1].rsplit("</script>", 1)[0]
        tmp.write_text(body, encoding="utf-8")
        r = subprocess.run([node, "--check", str(tmp)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode == 0:
            return ""
        lines = (r.stderr or "").strip().splitlines()
        return "\n  ".join(lines[:6])
    except Exception:
        return ""
    finally:
        tmp.unlink(missing_ok=True)


def mock_data():
    """真数据：包列表来自宿主、历史来自那本账、文件列表拿两处真目录做样本。"""
    sys.path.insert(0, str(ROOT))
    from core import history as core_history      # noqa: PLC0415
    from core import ui as core_ui                # noqa: PLC0415
    from core import config as core_config         # noqa: PLC0415

    payload = core_ui.build_payload()
    # ★ 「设置」面板那份数据**用真的**（宿主怎么给，预览就怎么给）：这样截图里
    #   看到的分组 / 标签 / 控件类型就是真界面上会看到的，不是这里编的。
    settings = core_config.settings_payload()

    hist = []
    for r in core_history.recent_unique():
        t = str(r.get("target") or "")
        if not t:
            continue
        cwd = str(r.get("cwd") or "")
        hist.append({"ts": str(r.get("ts") or ""), "kind": str(r.get("kind") or ""),
                     "id": str(r.get("id") or ""), "target": t, "name": Path(t).name or t,
                     "cwd": cwd, "args": " ".join(r.get("args") or []),
                     "exit": r.get("exit"), "icon": "", "icon_svg": "",
                     # 照真后端的算法给：目标没了的历史条目在界面上要画成灰的
                     "exists": Path(t).is_file(),
                     "cwd_exists": bool(cwd) and Path(cwd).is_dir(),
                     "key": "preview"})

    fs = {}
    samples = [("system/pkgs/md5", ROOT / "system/pkgs/md5"),
               ("system/pkgs/bmi", ROOT / "system/pkgs/bmi"),
               ("user", ROOT / "user_data"),
               ("abs/D:/python/wwwroot/ZeEn", Path(r"D:\python\wwwroot\ZeEn"))]
    # ★ 用户层每个包的目录也当样本（改名 / 对齐目录名那两个场景要在里面找文件）。
    #   从 payload 里现取 —— 目录名和 id 可能不一样（`D-27`），照 id 硬拼会拼错。
    for _p in (payload.get("packages") or []):
        if _p.get("layer") != "user" or not _p.get("dir"):
            continue
        _d = Path(_p["dir"])
        if _d.is_dir():
            samples.append(("user/pkgs/" + _d.name, _d))
    for rel, sub in samples:
        if not sub.is_dir():
            continue
        entries = []
        for p in sorted(sub.iterdir(), key=lambda c: (not c.is_dir(), c.name.lower()))[:40]:
            try:
                size, mtime = (p.stat().st_size if p.is_file() else 0), int(p.stat().st_mtime)
            except OSError:
                size, mtime = 0, 0
            entries.append({"name": p.name, "rel": rel + "/" + p.name, "dir": p.is_dir(),
                            "size": size, "mtime": mtime,
                            "ext": p.suffix.lower().lstrip(".")})
        fs[rel] = {"ok": True, "rel": rel, "entries": entries, "writable": True,
                   "path": str(sub)}

    # ★ 预览里**总是**现造一个用户层的包：目录名 `preview-my-first`、id `first` ——
    #   目录名 != id，正好就是 `D-27` 那两个分支要的情形（改名之后文件管理还认不认路
    #   `V-30`、手改 id 之后要不要统一目录名 `V-32`/`V-33`）。
    #   ★ 为什么从"只在 `user_data/pkgs/` 为空时才造"改成**总是造**（`V-81`）：你在界面上
    #   新建了一个包（`user_data/pkgs/my-first`，id 也叫 `my-first`）之后，这几个场景就
    #   悄悄换了对象 —— 找不到 id `first` 就退回 `packages[0]`（`ai`，一个系统包、目录名
    #   还正好等于 id），于是 `pkg-renamed-file` 判 FAIL / `pkg-odd-dir` 其实没试到那条
    #   分支，而**界面代码一个字没动**。场景绑在自己这份固定数据上，才不受你本机装了什么影响。
    udir = str(Path(payload["user_data"]) / "pkgs" / "preview-my-first")
    payload["packages"].append({
        "id": "first", "name": "预览：第一个包",
        "desc": "预览用的用户层包（目录名 preview-my-first，故意和 id 不一样）",
        "kind": "task", "version": "0.1.0", "layer": "user", "dir": udir,
        "aliases": [], "tags": [], "params": [], "drop": [], "ui": None, "docs": {},
        "ai_expose": False, "ai_risk": "", "examples": [], "icon": "", "icon_svg": ""})
    fs["user/pkgs/preview-my-first"] = {
        "ok": True, "rel": "user/pkgs/preview-my-first", "writable": True, "path": udir,
        "entries": [
            {"name": "pkg.json", "rel": "user/pkgs/preview-my-first/pkg.json", "dir": False,
             "size": 320, "mtime": 0, "ext": "json"},
            {"name": "run.py", "rel": "user/pkgs/preview-my-first/run.py", "dir": False,
             "size": 210, "mtime": 0, "ext": "py"}]}

    return {"payload": payload, "hist": hist, "fs": fs, "settings": settings,
            # 工具自己的场景清单：页面拿它对一下"这个场景名到底有没有实现"。
            "scenes": SCENES,
            # `--early-ready`：让 mock 在 js/*.js 之前就发 ready（`V-68` 的竞态场景）
            "earlyReady": ("--early-ready" in sys.argv[1:]),
            # 拖文件那个场景要的样本：故意用**带空格**的文件名，顺便验引号
            "dropDir": str(ROOT),
            "dropFile": str(ROOT / "一个 带空格的图片.png"),
            # 再给一个**没有空格**的：验"无论如何都要加引号"（`V-41`）
            "dropFile2": str(ROOT / "download.ico")}


MOCK_JS = r"""
<script>
/* ==== 预览用的假 API（只在临时副本里；真界面里没有这一段）==== */
(function(){
  const M = __MOCK__;
  const state = M.payload, HIST = M.hist, FS = M.fs;
  // ★ `--early-ready`：**在这里**（js/*.js 之前）就把 ready 发掉 —— 复现真机上
  //   "pywebview 的 ready 早于 `js/app.js` 挂监听"那条竞态（`V-68`）。
  if (M.earlyReady) window.dispatchEvent(new Event("pywebviewready"));
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  // ★ 场景名对不上任何分支就别装没事（`V-88`）：每个分支都会标记 `_sceneMatched`，
  //   跑完还是 false 就在标题里报 `SCENE-NAME-ERR`（不然"加了个工具里没有的场景名"会假通过）。
  let _sceneMatched = false;

  /* ---- 备份（`V-87`）的假后端 ------------------------------------------------
     ★ 真后端是"内容寻址"（`system/ui/backup.py`）：指纹 = 内容哈希，内容按指纹存一份。
       预览里没有文件**内容**（假文件系统只有名字 / 大小 / 时间），所以指纹按**大小**造一个
       稳定的假指纹 —— 够用来验"同样的内容不再存第二份"、"删了要回收"、"恢复要算
       覆盖 / 新建"这些**逻辑**，以及整个界面。真机那条路由真后端探针兜着。 */
  const bkFp = size => ("f" + String(size | 0).padStart(8, "0") + "0".repeat(31)).slice(0, 40);
  function bkWalk(rel, out, seen){
    const hit = FS[rel];
    if (!hit) return;
    (hit.entries || []).forEach(e => {
      if (/__pycache__|\.pyc$|\/\.git\//.test(e.rel)) return;
      if (e.dir){ bkWalk(e.rel, out, seen); return; }
      if (seen.has(e.rel)) return;
      seen.add(e.rel);
      out.push({rel: e.rel, fp: bkFp(e.size), size: e.size || 0, mtime: e.mtime || 0});
    });
  }
  function bkEntry(rel){
    const parent = rel.split("/").slice(0, -1).join("/");
    const nm = rel.split("/").pop();
    const hit = FS[parent];
    return hit ? ((hit.entries || []).find(e => e.name === nm) || null) : null;
  }
  function bkPlan(id, rels, only, sync){
    const b = (M.bk || []).find(x => x.id === id);
    if (!b) return {ok: false, msg: "(预览) 没有这次备份"};
    const want = rels ? new Set(rels) : null;
    const rows = [];
    b.files.forEach(e => {
      if (want && !want.has(e.rel)) return;
      const now = bkEntry(e.rel);
      let action, why = "";
      if (!now){ action = "create"; }
      else if ((now.size || 0) === e.size){ action = "same"; why = "和备份里一模一样"; }
      else { action = "overwrite"; why = "现在的内容和备份里不一样"; }
      if (only === "missing" && action === "overwrite"){ action = "skip"; why = "这次只补缺的"; }
      if (only === "changed" && action === "same"){ action = "skip"; why = "已经一样"; }
      rows.push({rel: e.rel, action: action, why: why, fp: e.fp, size: e.size});
    });
    // ★ 同步模式：现在有、备份里没有的 ⇒ extra（恢复时"挪进回收站"）
    if (sync && !want){
      const known = new Set(b.files.map(e => e.rel));
      (b.sources || []).forEach(src => {
        const walk = rel => {
          const hit = FS[rel];
          if (!hit) return;
          (hit.entries || []).forEach(e => {
            if (/__pycache__|\.pyc$/.test(e.rel)) return;
            if (e.dir){ walk(e.rel); return; }
            if (known.has(e.rel) || rows.some(r => r.rel === e.rel)) return;
            rows.push({rel: e.rel, action: "extra", why: "现在多出来的（同步模式会挪进回收站）",
                       fp: "", size: e.size || 0});
          });
        };
        walk(src);
      });
    }
    const counts = {};
    rows.forEach(r => { counts[r.action] = (counts[r.action] || 0) + 1; });
    return {ok: true, id: id, title: b.title, rows: rows, counts: counts, empty_dirs: [],
            sources: b.sources || []};
  }
  /* 导出：预览里没有"真写文件"，只把"要写到哪儿、写几个"算出来记在 M 上，供场景断言。 */
  function bkExportRel(b, rel){
    const srcs = b.sources || [];
    const hits = srcs.filter(x => rel === x || rel.indexOf(String(x).replace(/\/+$/, "") + "/") === 0);
    const s0 = hits.sort((a, c) => c.length - a.length)[0];
    if (!s0) return rel.split("/").pop();
    const tail = rel.slice(s0.length).replace(/^\/+/, "");
    if (srcs.length > 1){
      const head = String(s0).replace(/\/+$/, "").split("/").pop();
      return tail ? head + "/" + tail : head;
    }
    return tail || rel.split("/").pop();
  }
  function bkExportPlan(id, target, subpath, rels){
    const b = (M.bk || []).find(x => x.id === id);
    if (!b) return {ok: false, msg: "(预览) 没有这次备份"};
    const want = rels ? new Set(rels) : null;
    const sub = String(subpath || "").replace(/^[\/\\]+|[\/\\]+$/g, "");
    const root = String(target || "").replace(/[\/\\]+$/, "") + (sub ? ("/" + sub) : "");
    const mine = b.files.filter(e => !want || want.has(e.rel));
    const done = (M.bkExported && M.bkExported.root === root && M.bkExported.relPaths) || [];
    const over = mine.filter(e => done.indexOf(bkExportRel(b, e.rel)) >= 0).length;
    return {ok: true, root: root, new: mine.length - over, overwrite: over,
            files: mine.length, samples: [], bytes: mine.reduce((s, e) => s + e.size, 0)};
  }
  /* 按来源猜分组（和真后端 group_for_sources 一个规则，够预览用） */
  function bkGroupOf(rels){
    const srcs = (rels || []).map(String);
    for (const s0 of srcs){
      const parts = s0.replace(/\\/g, "/").split("/");
      if (parts.length >= 3 && (parts[1] === "pkgs" || parts[1] === "state")) return parts[2];
    }
    for (const s0 of srcs) if (s0 === "user" || s0 === "system") return "@" + s0;
    if (srcs.length){
      const f = srcs[0].replace(/\/+$/, "");
      const tail = f.split("/").pop() || "misc";
      return (f.indexOf("abs/") === 0 ? "@abs-" : "@dir-") + tail;
    }
    return "@misc";
  }
  function bkSweep(dryRun, group){
    const refs = new Set();
    (M.bk || []).forEach(b => b.files.forEach(e => refs.add(e.fp)));
    M.bkObj = M.bkObj || {};
    let removed = 0, freed = 0, kept = 0;
    Object.keys(M.bkObj).forEach(fp => {
      if (refs.has(fp)){ kept++; return; }
      const sz = M.bkObj[fp] || 0;
      if (!dryRun) delete M.bkObj[fp];
      removed++; freed += sz;
    });
    return {ok: true, dry_run: !!dryRun, removed: removed, freed: freed, kept: kept,
            referenced: refs.size,
            msg: (dryRun ? "能回收 " : "回收了 ") + removed + " 个对象"};
  }

  window.pywebview = { api: {
    state: async () => state,
    hist_list: async () => ({ok: true, items: HIST}),
    hist_forget: async () => ({ok: true, msg: "(预览) 已删掉这条记录"}),
    pkg_states: async (ids) => {                       // 造两个"在跑"的，好看绿色停止图标
      const out = {};
      (ids || []).forEach((id, i) => { out[id] = {running: i === 1 || i === 4,
        windows: i === 1 ? 1 : 0, visible: false}; });
      return {ok: true, states: out};
    },
    pkg_state: async () => ({ok: true, running: false, windows: 0, visible: false}),
    run_start: async (pid, args, cwd) => {
      (M.runs = M.runs || []).push({pid: pid, args: args, cwd: cwd});
      return {ok: true, run_id: "r1", pid: 1};
    },
    // 拖放那条线的日志（真后端写 user_data/state/_ui_drop.log）；预览里攒着看
    ui_log: async (text) => { (M.uiLogs = M.uiLogs || []).push(String(text || "")); return {ok: true}; },
    run_poll: async () => ({ok: true, running: false, code: 0,
      out: "[执行] md5\n[目录] " + state.home + "\n\n900150983cd24fb0d6963f7d28e17f72\n"}),
    run_stop: async () => ({ok: true, msg: "(预览) 已停止"}),
    // ---- 内嵌界面（`V-48`）那四个接口。预览里"包的后端"是假的：就地回几条，
    //      协议跟真的一模一样（真后端是那个包的进程，在 stdio 上说 JSON 行）----
    embed_start: async (pid) => {
      M.embed = {pid: pid, t: setInterval(() => {
        const d = new Date();
        window.__mossEmbedFromBackend(pid, JSON.stringify({event: "time", data: {
          text: d.toTimeString().slice(0, 8),
          date: d.toISOString().slice(0, 10), week: "一二三四五六日"[d.getDay()],
          who: "(预览) 假后端"}}));
      }, 1000)};
      return {ok: true, pid: 4242};
    },
    embed_send: async (pid, line) => {
      let req = {};
      try { req = JSON.parse(line); } catch(e){}
      const reply = (result) => window.__mossEmbedFromBackend(pid, JSON.stringify(
        {id: req.id, ok: true, result: result}));
      const d = new Date();
      if (req.method === "info") reply({pid: 4242, python: "3.12（预览）", cwd: "(预览)", embedded: true});
      else if (req.method === "now") reply({text: d.toTimeString().slice(0, 8),
        date: d.toISOString().slice(0, 10), week: "一二三四五六日"[d.getDay()],
        who: "(预览) 假后端"});
      else if (req.method === "subscribe") reply({subscribed: ["time"]});
      else if (req.method === "bmi") {
        const h = (req.params.height || 0) / 100, w = req.params.weight || 0;
        const v = Math.round((w / (h * h)) * 100) / 100;
        const lv = v < 18.5 ? ["偏瘦", "多吃点，别熬夜。"] : v < 24 ? ["正常", "保持住。"]
                 : v < 28 ? ["超重", "少喝奶茶，多走路。"] : ["肥胖", "认真考虑一下运动和饮食吧。"];
        reply({ok: true, bmi: v, level: lv[0], advice: lv[1],
               who: "(预览) 假后端", at: {text: d.toTimeString().slice(0, 8)}});
      } else reply(null);
      return {ok: true};
    },
    embed_stop: async () => { if (M.embed && M.embed.t) clearInterval(M.embed.t);
                              M.embed = null; return {ok: true, msg: "(预览) 已停"}; },
    embed_state: async () => ({ok: true, running: !!M.embed}),
    embed_take: async () => ({ok: true, text: ""}),
    // 真后端给的是 http://127.0.0.1:<随机端口>/<token>/…（V-55：WebView2 里不能
    // iframe 一个 file:// 页面）。预览跑在 Edge 上、file:// 能显示，所以这里直接给
    // 文件地址 —— 界面那侧流程一样，只是引擎限制不同（那点由 WebView2 探针管）。
    embed_url: async (pid) => {
      const p = state.packages.find(x => x.id === pid) || {};
      const path = ((p.ui || {}).embed || "").replace(/\\/g, "/");
      return path ? {ok: true, url: "file:///" + encodeURI(path)}
                  : {ok: false, msg: "(预览) 这个包没有界面文件"};
    },
    // 给正在跑的进程喂一行（`V-43`）：真后端写进它的 stdin，这里记下来
    run_input: async (rid, line) => {
      (M.inputs = M.inputs || []).push({rid: rid, line: line});
      return {ok: true};
    },
    path_start: async () => ({ok: true, run_id: "r1", pid: 1,
      cmd: "moss /main.py", cwd: "D:\\python\\wwwroot\\ZeEn"}),
    run_host: async (text) => {
      // ★ 宿主命令全部记一笔（`V-81`）：场景要能判定"界面到底有没有把这条命令交给宿主"
      //   —— 以前只判"截图生成了没有"，按钮压根没绑上也是 OK。
      (M.host = M.host || []).push(String(text || ""));
      // ★ `--rename <旧> <新id>`：假宿主**真的**把包改名 —— id / dir 都改，
      //   假文件系统里那个目录也一起搬。这样才能验"改名之后文件管理还认不认路"。
      const m = /^\s*--rename\s+(\S+)\s+(\S+)\s*$/.exec(String(text || ""));
      if (m){
        const p = state.packages.find(x => x.id === m[1]);
        if (!p) return {ok: true, code: 1, out: "[错误] 没有这个包：" + m[1]};
        const slash = s => String(s).replace(/\\/g, "/");
        const oldDir = slash(p.dir).replace(/\/+$/, "");
        const newDir = oldDir.replace(/[^/]+$/, m[2]);
        const relOf = d => {
          const u = slash(state.user_data).replace(/\/+$/, "");
          const sy = slash(state.home).replace(/\/+$/, "") + "/system";
          if (d === u || d.startsWith(u + "/")) return "user" + d.slice(u.length);
          if (d === sy || d.startsWith(sy + "/")) return "system" + d.slice(sy.length);
          return null;
        };
        const from = relOf(oldDir), to = relOf(newDir);
        p.id = m[2];
        p.dir = p.dir.replace(/[^\\/]+$/, m[2]);
        if (from && to && from !== to){
          Object.keys(FS).forEach(k => {
            if (k === from || k.startsWith(from + "/")){
              const nk = to + k.slice(from.length);
              const v = FS[k];
              v.rel = nk;
              (v.entries || []).forEach(e => { e.rel = to + e.rel.slice(from.length); });
              FS[nk] = v; delete FS[k];
            }
          });
        }
        document.title = "RENAMED";
        return {ok: true, code: 0, out: "(预览) 已改名：" + m[1] + " → " + m[2]};
      }
      return {ok: true, code: 0, out: "(预览) 自检输出"};
    },
    // ---- 「设置」（`V-60` / `V-63`）那几条：真后端去叫宿主 `--settings` /
    //      `--settings-check` / `--settings-set`；预览里给真数据 + 一份**简化过的**
    //      校验（真规则在 core/config.py，真机上由宿主算 —— 这里只为了看界面长什么样）。
    settings: async () => ({ok: true, path: M.settings.path, groups: M.settings.groups,
                            msg: ""}),
    settings_check: async (vals) => {
      M.values = vals;                       // 记住"页面现在是什么值"（保存时要用）
      const probs = [];
      const p = vals["symbols.path_mode"] || "", g = vals["symbols.plugin_mode"] || "";
      if (!p && !g) probs.push({key: "symbols.path_mode", level: "error",
        also: ["symbols.plugin_mode"],
        why: "「路径调用」和「跑包」不能同时留空 —— 那样裸名（moss m）算哪一种就说不清了"});
      const used = {}, label = {};
      [["symbols.path_mode", "路径调用"], ["symbols.no_chdir_mode", "跑路径但不切目录"],
       ["symbols.plugin_mode", "跑装好的包"], ["symbols.no_force_kill_mode", "后台脱离运行"]]
        .forEach(pair => {
          const v = vals[pair[0]] || "";
          if (!v) return;
          if (used[v]) probs.push({key: pair[0], level: "error", also: [used[v]],
            why: "和「" + label[v] + "」用了同一个符号 " + v + " —— 命令含义会有歧义"});
          else { used[v] = pair[0]; label[v] = pair[1]; }
        });
      const n = vals["symbols.no_chdir_mode"] || "", d = vals["symbols.no_force_kill_mode"] || "";
      const notes = {
        "symbols.path_mode": p ? ("现在：moss " + p + "m = 找文件") : "现在：裸名 moss m = 找文件",
        "symbols.plugin_mode": g ? ("现在：moss " + g + "img = 跑包") : "现在：裸名 moss img = 跑包",
        "symbols.no_chdir_mode": n ? ("现在：moss " + n + "m = 不切目录")
                                   : "现在：这一类不带前缀（用裸名或路径前缀）",
        "symbols.no_force_kill_mode": d ? ("现在：moss " + d + "m = 后台脱离")
                                        : "现在：这一类不带前缀"};
      const depth = parseInt(vals["search.max_parent_depth"], 10) || 3;
      notes["search.max_parent_depth"] = "现在：从当前目录起，连自己带父目录一共 " +
        (depth + 1) + " 个目录（当前 + 往上 " + depth + " 级）";
      if (depth >= 6) probs.push({key: "search.max_parent_depth", level: "warn", also: [],
        why: "找得有点远（一共 " + (depth + 1) + " 个目录）—— 容易撞上上层项目里的同名文件，"
             + "撞上就会停下来问你"});
      const live = (!p && !g)
        ? "⚠ 两个都留空 —— 裸名（moss m）到底算找文件还是跑包，说不清了"
        : ("现在：裸名 moss m 归「" + ((p && !g) ? "跑包" : "找文件") + "」" +
           (p ? " ｜ moss " + p + "m 找文件" : "") + (g ? " ｜ moss " + g + "img 跑包" : "") +
           (n ? " ｜ moss " + n + "m 不切目录" : "") + (d ? " ｜ moss " + d + "m 后台脱离" : ""));
      return {ok: !probs.some(x => x.level === "error"), problems: probs, notes: notes,
              live: live, msg: ""};
    },
    settings_save: async (pairs) => {
      M.saved = pairs;
      // 真宿主是"把这几项叠在当前文件上"再校验；这里叠在最后一次检查时的全量值上
      const merged = Object.assign({}, M.values || {}, pairs);
      const ck = await window.pywebview.api.settings_check(merged);
      return {ok: ck.ok, problems: ck.problems, notes: ck.notes, live: ck.live, msg: ""};
    },
    open_ui: async () => ({ok: true, msg: "(预览) 已打开"}),
    pkg_stop: async () => ({ok: true, msg: "(预览) 已停止"}),
    pkg_hide: async () => ({ok: true, msg: "(预览) 已隐藏"}),
    pkg_show: async () => ({ok: true, msg: "(预览) 已显示"}),
    fs_list: async (rel) => {
      (M.ls = M.ls || []).push(String(rel));              // 记一笔：谁在什么时候列了哪儿
      // ★ 必须回一份**深拷贝**：真宿主是跨进程的 JSON，界面拿到的永远是全新对象。
      //   直接把这里的对象递出去，界面和"假文件系统"就共享了同一份 entries ——
      //   以后假文件系统里改一个 `rel`，界面上那份也**悄悄跟着变**，于是
      //   "改名后路径没跟着搬"这种毛病在预览里永远看不出来（踩过）。
      const hit = FS[rel];
      return hit ? JSON.parse(JSON.stringify(hit))
                 : {ok: true, rel: rel, entries: [], writable: true, path: rel};
    },
    // ★ 这里**照着真宿主的行为来**：路径不存在就是「不是文件」。
    //   以前这个假 API 对任何路径都回同一段内容，于是"改名后双击旧路径"这种毛病
    //   在预览里永远看不出来（producer 说没事、真机上说不是文件）。
    //   ★★ 而且 `pkg.json` 必须回**这个包真清单的 JSON**（带 id！）——
    //   回一段假的 python 代码，编辑清单那些场景解析出来就没有 id，
    //   假后端会照着 `F-26` 把这个包丢掉，整个场景看起来像"包没了"（踩过）。
    fs_read: async (rel) => {
      const parent = String(rel || "").split("/").slice(0, -1).join("/");
      if (!FS[parent]){
        M.readFail = rel;
        return {ok: false, msg: "不是文件：" + rel};
      }
      M.readOk = rel;
      let text = "import hashlib\n\n\ndef run():\n    print('预览')\n";
      if (/pkg\.json$/i.test(String(rel))){
        const dirName = String(rel).split("/").slice(-2)[0];
        const p = state.packages.find(x => String(x.dir || "")
                     .replace(/\\/g, "/").replace(/\/+$/, "").split("/").pop() === dirName);
        text = JSON.stringify({spec: 1, id: (p && p.id) || dirName, kind: "task",
                               version: (p && p.version) || "0.1.0",
                               name: (p && p.name) || dirName,
                               desc: (p && p.desc) || ""}, null, 2) + "\n";
      }
      return {ok: true, text: text, binary: false, too_big: false,
              rel: rel, path: rel, writable: true};
    },
    // ★ 写 pkg.json 时真的改掉那份假 payload（模拟宿主重新扫盘）——
    //   这样才能验证"存了清单之后界面会重新解析"这条路。
    //   ★★ 注意这里**只改清单里的字段，不动目录**：真宿主就是这样 —— 手工把 id
    //      改掉之后，包目录还叫原来的名字（`D-27` 容许的不一致），要统一得另外动手。
    fs_write: async (rel, text) => {
      if (/(^|\/)pkg\.json$/i.test(rel || "")){
        const parts = String(rel).split("/");
        const dirName = parts[parts.length - 2];
        const at = x => String(x.dir || "")
          .replace(/\\/g, "/").replace(/\/+$/, "").split("/").pop() === dirName;
        const p = state.packages.find(at);
        if (!p) return {ok: true, msg: "(预览) 已保存"};
        // ★ 照真宿主的扫描规矩来（`F-26`）：清单读不出来 / id 不合法 ⇒ **这个包
        //   会被当成不存在**。假后端也得这么做，否则"存了个非法 id"在预览里
        //   看起来没事，而真机上包直接没了。
        let j = null;
        try{ j = JSON.parse(text); }catch(e){
          state.packages = state.packages.filter(x => x !== p);
          M.dropped = "JSON 坏";
          document.title = "BADJSON";
          return {ok: true, msg: "(预览) 已保存"};
        }
        const id = String((j && j.id) || "");
        if (!/^[a-z][a-z0-9_-]{0,31}$/.test(id)){
          state.packages = state.packages.filter(x => x !== p);
          M.dropped = "id 不合法";
          document.title = "BADID";
          return {ok: true, msg: "(预览) 已保存"};
        }
        p.id = id;
        if (j.name) p.name = j.name;
        if (j.desc) p.desc = j.desc;
        document.title = "WROTE";
      }
      return {ok: true, msg: "(预览) 已保存"};
    },
    fs_mkdir: async () => ({ok: true, msg: "(预览) 已创建"}),
    fs_touch: async () => ({ok: true, msg: "(预览) 已创建"}),
    fs_rename: async (rel, newName) => {
      // 真的在假文件系统里搬一下（场景要验「旧数据目录跟着一起搬」）
      const from = String(rel || "");
      const to = from.replace(/[^/]+$/, String(newName || ""));
      if (!FS[from]) return {ok: false, msg: "(预览) 没有这个东西：" + from};
      if (FS[to]) return {ok: false, msg: "(预览) 已经有一个同名的了"};
      const v = FS[from];
      delete FS[from];
      v.rel = to;
      (v.entries || []).forEach(e => { e.rel = to + e.rel.slice(from.length); });
      FS[to] = v;
      (M.moves = M.moves || []).push(from + " → " + to);
      return {ok: true, rel: to, old: from, msg: "(预览) 已改名"};
    },
    fs_delete: async () => ({ok: true, msg: "(预览) 已挪进回收站"}),
    fs_copy: async () => ({ok: true, msg: "(预览) 已复制"}),
    // 照真宿主来：说有就是真有（假文件系统的键就是那些目录 / 文件）
    fs_exists: async (rels) => {
      const has = {};
      (rels || []).forEach(r => { has[r] = !!FS[r]; });
      return {ok: true, has: has};
    },
    fs_open_default: async () => ({ok: true, msg: "(预览) 已打开"}),
    fs_reveal: async () => ({ok: true, msg: "(预览) 已定位"}),
    fs_roots: async () => ({roots: []}),
    // ---- 备份（`V-87`）-----------------------------------------------------
    backup_list: async (group) => {
      const gwant = String(group || "");
      const all = (M.bk || []).filter(b => !gwant || (b.group || "@misc") === gwant);
      const items = all.map(b => ({
        id: b.id, group: b.group || "@misc", title: b.title, note: b.note, created: b.created,
        created_text: b.created_text, sources: b.sources,
        files: b.files.length, bytes: b.files.reduce((s, e) => s + e.size, 0),
        new_objects: b.new_objects, new_bytes: b.new_bytes, skipped: 0, errors: 0}));
      const allBytes = items.reduce((s, i) => s + i.bytes, 0);
      const objs = M.bkObj || {};
      const storeBytes = Object.keys(objs).reduce((s, fp) => s + (objs[fp] || 0), 0);
      const byGroup = {};
      (M.bk || []).forEach(b => {
        const g = b.group || "@misc";
        byGroup[g] = byGroup[g] || {group: g, backups: 0, files: 0, bytes: 0,
                                    objects: 0, store_bytes: 0, saved: 0, last: ""};
        byGroup[g].backups++;
        byGroup[g].files += b.files.length;
        byGroup[g].bytes += b.files.reduce((s, e) => s + e.size, 0);
        byGroup[g].last = b.created_text;
      });
      Object.keys(byGroup).forEach(g => {
        byGroup[g].store_bytes = byGroup[g].bytes;
        byGroup[g].objects = byGroup[g].files;
      });
      return {ok: true, items: items.slice().reverse(), groups: Object.keys(byGroup)
                .map(g => byGroup[g]),
              stat: {ok: true, backups: items.length,
                     files: items.reduce((s, i) => s + i.files, 0), all_bytes: allBytes,
                     objects: Object.keys(objs).length, store_bytes: storeBytes,
                     saved: Math.max(0, allBytes - storeBytes),
                     groups: Object.keys(byGroup).length,
                     root: "(预览) user_data/backups"}};
    },
    backup_create: async (rels, title, note) => {
      M.bk = M.bk || [];
      M.bkObj = M.bkObj || {};
      const files = [], seen = new Set();
      (rels || []).forEach(r => bkWalk(r, files, seen));
      const before = Object.keys(M.bkObj).length;
      let newBytes = 0;
      files.forEach(e => {
        if (!(e.fp in M.bkObj)){ M.bkObj[e.fp] = e.size; newBytes += e.size; }
      });
      const n = M.bk.length + 1;
      const b = {id: "20260930-0000" + String(n).padStart(2, "0") + "-bk" + n,
                 group: bkGroupOf(rels || []),
                 title: title || ("(预览) 备份 " + n), note: note || "",
                 created: Date.now() / 1000,
                 created_text: "(预览) " + new Date().toTimeString().slice(0, 8),
                 sources: rels || [], files: files,
                 new_objects: Object.keys(M.bkObj).length - before, new_bytes: newBytes};
      M.bk.push(b);
      return {ok: true, id: b.id, group: b.group, created_text: b.created_text,
              stats: {files: files.length, bytes: files.reduce((s, e) => s + e.size, 0),
                      new_objects: b.new_objects, new_bytes: newBytes,
                      empty_dirs: 0, skipped: 0, errors: 0},
              msg: "(预览) 备份好了：" + files.length + " 个文件"};
    },
    backup_manifest: async (id) => {
      const b = (M.bk || []).find(x => x.id === id);
      if (!b) return {ok: false, msg: "(预览) 没有这次备份：" + id};
      return Object.assign({ok: true, spec: 1, hash: "fake(预览)", exclude: [],
                            empty_dirs: [], skipped: [], errors: [],
                            stats: {files: b.files.length}},
                           JSON.parse(JSON.stringify(b)));
    },
    /* `V-94`：差异视图要知道"现在这份和快照里那份一不一样" —— 假后端按同一个 `bkFp(大小)`
       算（和 `backup_manifest` 里写清单时用的是同一个函数，所以"没动过"的文件必然一致）。 */
    backup_ignore: async () => ({ok: true, name: "snapshot.ignore",
      path: "D:\\\\python\\\\two\\\\moss\\\\user_data\\\\snapshot.ignore",
      exists: true, count: 2, user: ["*.log", "build/"],
      builtin: ["__pycache__", "*.pyc", ".git", "/user/trash"]}),
    backup_ignore_save: async (text) => ({ok: true, path: "(预览) snapshot.ignore",
      count: String(text || "").split("\n").filter(x => x.trim() && x.trim()[0] !== "#").length}),
    backup_preview: async (rels) => ({ok: true, n_in: 4, n_out: 2, include: [],
      exclude: ["user/pkgs/md5/x.log", "user/pkgs/md5/build/inner.txt"],
      rules: ["*.log", "build/"], builtin: ["__pycache__", "*.pyc"]}),
    backup_fp: async (rels, dirs) => {
      const fps = {}, sizes = {}, dsz = {};
      (dirs || []).forEach(d => {
        dsz[d] = (FS[d] && FS[d].entries || []).reduce((s, e) => s + (e.dir ? 0 : (e.size || 0)), 0);
      });
      (rels || []).forEach(r => {
        const e = (FS[r] && FS[r].entries || []).find(x => x.rel === r) ||
                  Object.keys(FS).map(k => (FS[k].entries || []).find(x => x.rel === r))
                        .filter(Boolean)[0] ||
                  M.bkFlat[r];
        if (e){ fps[r] = bkFp(e.size); sizes[r] = e.size || 0; }
      });
      return {ok: true, fps: fps, sizes: sizes, dirs: dsz};
    },
    backup_blob: async (fp) => {
      const objs = M.bkObj || {};
      if (!(fp in objs)) return {ok: false, msg: "(预览) 对象缺失：" + fp};
      const size = objs[fp] || 0;
      if (size > 200000)
        return {ok: true, binary: false, size: size, truncated: true, fp: fp, text: "(预览) 太大\n"};
      return {ok: true, binary: false, size: size, truncated: false, fp: fp,
              text: "(预览) 这一段内容块（指纹 " + String(fp).slice(0, 10) + "、大小 " +
                    size + " 字节）\\n\\n同一个内容只存这一份。\\n"};
    },
    backup_plan: async (id, rels, only, sync) => bkPlan(id, rels, only || "all", !!sync),
    backup_restore: async (id, rels, only, sync) => {
      const plan = bkPlan(id, rels, only || "all", !!sync);
      if (!plan.ok) return plan;
      const b = (M.bk || []).find(x => x.id === id);
      const restored = [], skipped = [], errors = [];
      const trashed = [];
      plan.rows.forEach(r => {
        if (r.action === "same" || r.action === "skip"){ skipped.push(r.rel); return; }
        if (r.action === "extra"){
          // "挪进回收站"：预览里就从假文件系统里挪走，并记账（真后端是挪进 user_data/trash）
          (M.bkTrashed = M.bkTrashed || []).push(r.rel);
          const par = r.rel.split("/").slice(0, -1).join("/");
          const nm = r.rel.split("/").pop();
          const h = FS[par];
          if (h) h.entries = (h.entries || []).filter(e => e.name !== nm);
          trashed.push(r.rel);
          return;
        }
        if (r.action === "error"){ errors.push(r.rel); return; }
        const parent = r.rel.split("/").slice(0, -1).join("/");
        const nm = r.rel.split("/").pop();
        const hit = FS[parent];
        if (!hit){ errors.push(r.rel); return; }
        hit.entries = hit.entries || [];
        const at = hit.entries.findIndex(e => e.name === nm);
        if (r.action === "overwrite" && at >= 0){
          // 覆盖前留一份 `.bak`（真后端也这么干）
          const bak = nm + ".bak";
          if (!hit.entries.some(e => e.name === bak))
            hit.entries.push({name: bak, rel: parent + "/" + bak, dir: false,
                              size: hit.entries[at].size || 0, mtime: 0,
                              ext: (bak.split(".").pop() || "").toLowerCase()});
        }
        const e = {name: nm, rel: r.rel, dir: false, size: r.size, mtime: 0,
                   ext: (nm.split(".").pop() || "").toLowerCase()};
        if (at >= 0) hit.entries[at] = e; else hit.entries.push(e);
        restored.push(r.rel);
      });
      return {ok: true, id: id, restored: restored, skipped: skipped, errors: errors,
              dirs: [], trashed: trashed,
              counts: {restored: restored.length, skipped: skipped.length,
                       errors: errors.length, dirs: 0, trashed: trashed.length},
              msg: "(预览) 恢复 " + restored.length + " 个、跳过 " + skipped.length +
                   " 个、挪走 " + trashed.length + " 个"};
    },
    backup_presets: async (rels) => ({ok: true, presets: [
      {id: "media", label: "视频 / 音频", pat: ["*.mp4", "*.mov"], hit: 2, why: "又大又不常改", sample: ["a.mp4", "b.mov"]},
      {id: "logs", label: "日志", pat: ["*.log"], hit: 1, why: "跑起来才产生", sample: ["run.log"]},
      {id: "venv", label: "虚拟环境", pat: ["venv"], hit: 0, why: "能重建", sample: []}],
      group: "md5"}),
    backup_group_ignore: async (g) => ({ok: true, group: g, path: "(预览)", rules: []}),
    backup_group_hint: async (rels) => ({ok: true, group: bkGroupOf(rels || [])}),
    backup_group_info: async (group) => {
      const mine = (M.bk || []).filter(b => (b.group || "@misc") === String(group || ""));
      const bytes = mine.reduce((s, b) => s + b.files.reduce((x, e) => x + e.size, 0), 0);
      return {ok: true, group: String(group || ""), backups: mine.length, bytes: bytes,
              store_bytes: bytes, last: (mine[0] || {}).created_text || ""};
    },
    backup_rename_group: async (oldG, newG) => {
      let n = 0;
      (M.bk || []).forEach(b => {
        if ((b.group || "@misc") === String(oldG || "")){ b.group = String(newG || ""); n++; }
      });
      return {ok: true, renamed: n, msg: "(预览) 分组改名 " + oldG + " → " + newG};
    },
    backup_drop_group: async (group) => {
      const g = String(group || "");
      const before = (M.bk || []).length;
      M.bk = (M.bk || []).filter(b => (b.group || "@misc") !== g);
      return {ok: true, removed: before - M.bk.length, freed: 0,
              msg: "(预览) 已删掉分组「" + g + "」"};
    },
    backup_export_plan: async (id, target, subpath, rels) =>
      bkExportPlan(id, target, subpath, rels),
    backup_export: async (id, target, subpath, rels, keepBak) => {
      const b = (M.bk || []).find(x => x.id === id);
      if (!b) return {ok: false, msg: "(预览) 没有这次备份"};
      const plan = bkExportPlan(id, target, subpath, rels);
      const want = rels ? new Set(rels) : null;
      const mine = b.files.filter(e => !want || want.has(e.rel));
      const relPaths = mine.map(e => bkExportRel(b, e.rel));
      M.bkExported = {root: plan.root, relPaths: relPaths, keepBak: !!keepBak,
                      files: mine.length};
      return {ok: true, id: id, root: plan.root, written: relPaths, bytes: plan.bytes,
              bak: keepBak ? relPaths.map(x => x + ".bak") : [], errors: [],
              counts: {written: relPaths.length, errors: 0, bak: keepBak ? relPaths.length : 0},
              msg: "(预览) 导出 " + relPaths.length + " 个到 " + plan.root};
    },
    pick_dir: async () => ({ok: true, path: "D:\\预览选的目录"}),
    backup_delete: async (id) => {
      M.bk = M.bk || [];
      const at = M.bk.findIndex(x => x.id === id);
      if (at < 0) return {ok: false, msg: "(预览) 没有这次备份：" + id};
      M.bk.splice(at, 1);
      const r = bkSweep(false);
      r.deleted = id;
      return r;
    },
    backup_gc: async (dryRun) => bkSweep(!!dryRun),
    backup_check: async (id) => {
      const objs = M.bkObj || {};
      const rows = (M.bk || []).filter(b => !id || b.id === id).map(b => {
        const miss = b.files.filter(e => !(e.fp in objs)).map(e => e.rel);
        return {id: b.id, missing: miss.length, sample: miss.slice(0, 5)};
      });
      return {ok: true, rows: rows};
    },
    quit: async () => ({ok: true}),
  }};
  async function scenario(){
    const h = (location.hash || "#pkg").slice(1);
    // ★ 场景名对不上工具里那份清单 ⇒ 直接判错（`V-88`）。为什么要有这一条：我加个
    //   "工具里还没有的场景名"跑一下，所有 if 都不匹配、标题停在初值，`--check` 会
    //   报 OK/READY —— **假通过**比报错更坏。（第一版按"每个分支打标记"做，漏掉了
    //   `h.startsWith(...)` / `if (a || b){` / 单行 if 那几种写法，一片假失败，撤了。）
    if ((M.scenes || []).length && (M.scenes || []).indexOf(h) < 0){
      document.title = "SCENE-NAME-ERR " + h;
      const _m0 = document.querySelector("#meta");
      if (_m0) _m0.textContent = "SCENE-NAME-ERR —— 工具里没有这个场景：" + h +
        "（清单里的前几个：" + (M.scenes || []).slice(0, 6).join(", ") + "）";
      return;
    }
    // 设输入框的值并派发 `input`（`v-model` 只认事件，直接改 .value 它不知道）
    const bkSet = (sel, val) => {
      const el = document.querySelector(sel);
      if (!el) throw new Error("找不到输入框：" + sel);
      el.value = val;
      el.dispatchEvent(new Event("input", {bubbles: true}));
    };
    try {
      if (h.startsWith("hist")){
        setSide("hist");
        await sleep(250);
        if (HIST.length) selectHist(HIST[0]);
        if (h === "hist-file") setTab("file");
        if (h === "hist-console") setTab("console");
      } else {
        // `pkg-odd-dir`：专门挑一个「目录名 != id」的包看那个分支（`D-27` 方案 C）；
        // 仓库里现成的例子是 user_data/pkgs/my-first（id=first）。没有就退回 md5。
        const base = x => String(x.dir || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();
        const p = (h === "pkg-odd-dir"
                    ? (state.packages.find(x => base(x) && base(x) !== x.id)
                       || state.packages.find(x => x.id === "md5"))
                    : state.packages.find(x => x.id === "md5")) || state.packages[0];
        select(p.id);
        if (h === "pkg-file") setTab("file");
        if (h === "pkg-file-open"){
                  setTab("file");
          await sleep(350);
          await fmOpenPage("system/pkgs/md5/run.py");
        }
        if (h === "pkg-console") setTab("console");
        if (h === "edit-manifest" || h === "edit-manifest-detail"){
          // 打开清单 → 改名 → 保存：左边列表应该跟着变
          setTab("file");
          await sleep(350);
          await fmOpenPage("system/pkgs/md5/pkg.json");
          await sleep(250);
          const t = fmActiveTab();
          if (!t){ document.title = "NO-TAB"; return; }
          let j = {};
          try{ j = JSON.parse(t.text); }catch(e){}
          j.name = "已改名的 MD5";
          t.text = JSON.stringify(j, null, 2);
          fmSave(t);
          await sleep(600);
          if (h === "edit-manifest-detail") setTab("detail");   // 看详情那边跟不跟着变
        }
      }
      // ★ 改名之后文件管理还认不认路：先站进这个包的目录，走一遍真改名，
      //   再回文件管理双击一个文件 —— 路径没跟着搬的话宿主会说「不是文件」。
      if (h === "pkg-renamed-file" || h === "pkg-align-file"){
        const baseOf = x => String(x.dir || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();
        let p0;
        if (h === "pkg-align-file"){
                  // 仓库里那个真例子（my-first / id=first）已经被对齐过了 —— 预览里**现造一个**
          // 「目录名 != id」的包，否则这条分支没得试。（只改这份临时副本里的假 payload。）
          p0 = state.packages.find(x => baseOf(x) && baseOf(x) !== x.id) || null;
          if (!p0){
            p0 = {id: "oddir", name: "预览：目录名不一致", desc: "目录名 odd-dirname，id 是 oddir",
                  kind: "task", layer: "user", version: "0.1.0", params: [], aliases: [],
                  tags: [], docs: {}, ai_expose: false, icon: "", icon_svg: "",
                  dir: state.user_data + "\\pkgs\\odd-dirname"};
            state.packages.push(p0);
            FS["user/pkgs/odd-dirname"] = {ok: true, rel: "user/pkgs/odd-dirname",
              writable: true, path: p0.dir, entries: [
                {name: "pkg.json", rel: "user/pkgs/odd-dirname/pkg.json", dir: false,
                 size: 928, mtime: 0, ext: "json"},
                {name: "run.py", rel: "user/pkgs/odd-dirname/run.py", dir: false,
                 size: 1118, mtime: 0, ext: "py"}]};
          }
        } else {
          p0 = state.packages.find(x => x.id === "first") || state.packages[0];
        }
        select(p0.id);
        setTab("file");
        await sleep(400);
        const want = h === "pkg-align-file" ? p0.id : "first2";
        if (h === "pkg-align-file"){
                  cmdAlignPkgDir(p0);                       // 对齐目录名：不弹模态，直接跑
        } else {
          cmdRenamePkg(p0);                         // 改名：弹模态，替用户填好再点确定
          await sleep(150);
          const inp = document.querySelector("#m-input");
          if (inp){ inp.value = want; (document.querySelector("#m-ok") || {click(){}}).click(); }
        }
        await sleep(1200);
        setTab("file");
        await sleep(500);
        const key = h === "pkg-align-file" ? p0.id : want;
        const s = FM.st[key];
        const rels = ((s && s.entries) || []).map(e => e.rel);
        const target = rels.find(r => /pkg\.json$/.test(r)) || rels[0];
        if (target) await fmOpenPage(target);
        await sleep(300);
        const t = fmActiveTab();
        const ok = !!(t && t.rel === target) && !M.readFail;
        const relOld = /odd-dirname/.test(String((s && s.rel) || ""));
        const entOld = rels.some(r => /odd-dirname/.test(String(r)));
        const short = x => String(x).replace("user/pkgs/", "").replace("system/pkgs/", "sys/");
        const diag = "DIAG " + (ok ? "OK" : "FAIL") +
          "\nrel      = " + ((s && s.rel) || "-") +
          "\nentries  = " + JSON.stringify(rels) +
          "\nhist     = " + JSON.stringify((s && s.hist) || []) +
          "\ntarget   = " + (target || "-") +
          "\ntab      = " + ((t && t.rel) || "-") +
          "\nreadFail = " + (M.readFail || "无") +
          "\nstale    = " + (s && s.stale ? "1" : "0") +
          "\nfs_list  = " + (M.ls || []).map(short).join(" > ");
        // 顶栏那点宽度只能放一句短的；完整那份写进下面的大白区（截图看得清）
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " rO=" + (relOld ? 1 : 0) + " eO=" + (entOld ? 1 : 0) +
          " n=" + rels.length + " rf=" + (M.readFail ? 1 : 0);
        document.querySelector("#fm-body").innerHTML =
          '<pre style="padding:18px 22px;font-size:13px;line-height:1.7;white-space:pre-wrap">' +
          diag.replace(/&/g, "&amp;").replace(/</g, "&lt;") + '</pre>';
        document.title = ok ? "READY" : "STALE-PATH";
      }
      // ★ 你说的那条路：打开 pkg.json → 把 id 改了 → 点保存。
      //   期望：界面重新解析、**发现不配套就问一句**、点"统一"之后目录名跟着改、
      //   旧数据目录一起搬、文件管理里的路径也换成新的（双击还能编辑）。
      if (h === "pkg-edit-id"){
              // 出错了要看得见：场景里的异常 / Promise 拒绝都收进来（否则只能瞎猜）
        M.errs = [];
        window.addEventListener("error", e => M.errs.push("ERR " + e.message));
        window.addEventListener("unhandledrejection",
          e => M.errs.push("REJ " + ((e.reason && e.reason.message) || e.reason)));
        const origAms = window.afterManifestSaved;
        window.afterManifestSaved = async function(a, b){
          M.amsRan = true;
          try{ return await origAms(a, b); }
          catch(e){ M.amsErr = String((e && e.message) || e); throw e; }
        };
        const baseOf = x => String(x.dir || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();
        // 必须挑一个**假文件系统里真有的**包（不然连 pkg.json 都打不开）
        const usable = p => { try{ return !!FS[pkgRel(p)]; }catch(e){ return false; } };
        const p0 = state.packages.find(x => x.layer === "user" && usable(x)) ||
                   state.packages.find(usable) || null;
        if (!p0){ document.title = "NO-USABLE-PKG"; return; }
        const oldDir = baseOf(p0);
        // 造一个"旧数据目录"，看"一起搬"那条路
        FS["user/state/" + oldDir] = {ok: true, rel: "user/state/" + oldDir, writable: true,
                                      path: "(预览)", entries: []};
        select(p0.id);
        setTab("file");
        await sleep(400);
        await fmOpenPage("user/pkgs/" + oldDir + "/pkg.json");
        await sleep(300);
        const t = fmActiveTab();
        // ★ 打不开就得**说出来**（`V-63`）：原来这里没护栏，`t` 是 null 时
        //   直接抛 "Cannot set properties of null"，场景标题只留一句 SCENARIO-ERR，
        //   看不出是"假文件系统里没这个包"还是"界面坏了"。
        if (!t){
          document.querySelector("#meta").textContent =
            "SCENARIO-ERR 打不开 user/pkgs/" + oldDir + "/pkg.json（假的 FS 里没这个目录？）"
            + " fs_read 失败过=" + (M.readFail || "无");
          document.title = "NO-TAB";
          return;
        }
        let j = {};
        try{ j = JSON.parse(t.text); }catch(e){}
        j.id = "zzz9";
        t.text = JSON.stringify(j, null, 2);
        fmSave(t);
        await sleep(1400);                       // 存盘 → 重问包表 → 对账 → 弹框
        const modal = document.querySelector("#modal");
        const asked = !!(modal && modal.classList.contains("on"));
        const box = document.querySelector("#m-text");
        const askText = box ? String(box.textContent || "") : "";
        if (asked) (document.querySelector("#m-ok") || {click(){}}).click();   // 点"确定" = 统一
        await sleep(1600);
        const np = state.packages.find(x => x.id === "zzz9");
        const newDir = baseOf(np || {});
        const s2 = FM.st["zzz9"];
        const rels2 = ((s2 && s2.entries) || []).map(e => e.rel);
        const tgt = rels2.find(r => /pkg\.json$/.test(r)) || rels2[0];
        if (tgt) await fmOpenPage(tgt);
        await sleep(400);
        const t2 = fmActiveTab();
        const ok = asked && !!np && newDir === "zzz9" &&
                   !!FS["user/pkgs/zzz9"] && !FS["user/pkgs/" + oldDir] &&
                   !!FS["user/state/zzz9"] && !FS["user/state/" + oldDir] &&
                   !!(t2 && /zzz9/.test(String(t2.rel))) && !M.readFail;
        const diag = "DIAG " + (ok ? "OK" : "FAIL") +
          "\n问了没有 = " + asked + "\n问的话  = " + askText.replace(/\s+/g, " ").slice(0, 160) +
          "\n新包     = " + (np ? np.id + "  dir=" + newDir : "（没有）") +
          "\n包目录   = zzz9 在=" + !!FS["user/pkgs/zzz9"] +
          "  旧 " + oldDir + " 还在=" + !!FS["user/pkgs/" + oldDir] +
          "\n数据目录 = zzz9 在=" + !!FS["user/state/zzz9"] +
          "  旧 " + oldDir + " 还在=" + !!FS["user/state/" + oldDir] +
          "\n搬动记录 = " + JSON.stringify(M.moves || []) +
          "\n文件管理 = " + ((s2 && s2.rel) || "-") + " 列了 " + rels2.length +
          " 项  打开=" + (t2 ? t2.rel : "失败") + "  读失败=" + (M.readFail || "无") +
          "\n对账跑了 = " + (M.amsRan ? 1 : 0) + "  对账里的错 = " + (M.amsErr || "无") +
          "\n页面错误 = " + JSON.stringify(M.errs || []);
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 问了=" + (asked ? 1 : 0) +
          " 新包=" + (np ? newDir : "-") + " 打开=" + (t2 ? 1 : 0);
        document.querySelector("#fm-body").innerHTML =
          '<pre style="padding:18px 22px;font-size:13px;line-height:1.7;white-space:pre-wrap">' +
          diag.replace(/&/g, "&amp;").replace(/</g, "&lt;") + '</pre>';
        document.title = ok ? "READY" : "EDIT-ID-FAIL";
      }
      // ★ 反面：把 id 改成**非法**的（`F-26` 不允许数字开头）。期望：宿主不收这个包
      //   （它从列表里消失），界面**说清楚为什么**，而不是默默让它不见、更不是
      //   傻乎乎地"统一"成一个非法目录名。
      if (h === "pkg-edit-bad-id"){
              const baseOf = x => String(x.dir || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop();
        const usable = p => { try{ return !!FS[pkgRel(p)]; }catch(e){ return false; } };
        const p0 = state.packages.find(x => x.layer === "user" && usable(x)) ||
                   state.packages.find(usable) || null;
        if (!p0){ document.title = "NO-USABLE-PKG"; return; }
        const oldDir = baseOf(p0);
        select(p0.id);
        setTab("file");
        await sleep(400);
        await fmOpenPage("user/pkgs/" + oldDir + "/pkg.json");
        await sleep(300);
        const t = fmActiveTab();
        if (!t){
          document.querySelector("#meta").textContent =
            "SCENARIO-ERR 打不开 user/pkgs/" + oldDir + "/pkg.json（假的 FS 里没这个目录？）"
            + " fs_read 失败过=" + (M.readFail || "无");
          document.title = "NO-TAB";
          return;
        }
        let j = {};
        try{ j = JSON.parse(t.text); }catch(e){}
        j.id = "3";
        t.text = JSON.stringify(j, null, 2);
        fmSave(t);
        await sleep(1400);
        const modalOn = document.querySelector("#modal").classList.contains("on");
        const gone = !state.packages.some(x => baseOf(x) === oldDir);
        const toasts = [].slice.call(document.querySelectorAll("#toasts .toast"))
                         .map(e => e.textContent).join(" ｜ ");
        const ok = !modalOn && gone && /不合法/.test(toasts);
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 弹框=" + (modalOn ? 1 : 0) +
          " 包没了=" + (gone ? 1 : 0);
        document.querySelector("#fm-body").innerHTML =
          '<pre style="padding:18px 22px;font-size:13px;line-height:1.7;white-space:pre-wrap">' +
          ("DIAG " + (ok ? "OK" : "FAIL") +
           "\n宿主把包丢了吗 = " + gone + "   （假后端记的是：" + (M.dropped || "没丢") + "）" +
           "\n还弹框问「统一」吗 = " + modalOn + "   （非法 id 不该问，应该直接说清楚）" +
           "\n界面说的话 = " + (toasts || "（什么都没说 —— 这就是毛病）") +
           "\n目录还在吗 = " + !!FS["user/pkgs/" + oldDir] + "  （包目录没动，是对的）")
            .replace(/&/g, "&amp;").replace(/</g, "&lt;") + '</pre>';
        document.title = ok ? "READY" : "BAD-ID-FAIL";
      }
      // ★ 拖入三件套（`V-35`/`V-38`/`V-39`）：真实的 OS 拖动没法自动化（得人拿鼠标拖），
      //   所以拆成能测的两半 ——
      //     ① 拖动那半：用**合成事件**（带 types:["Files"]，items 里给一个
      //        `webkitGetAsEntry()`，跟真拖动一样能看出是文件还是文件夹）
      //     ② 松手那半：直接调落地口 `window.__mossDrop([...])`
      //        （真机上由宿主从 WebView2 取到真实路径后调用它）
      // ★ 内嵌界面（`V-48`）：拿**真包的页面**（`ui.embed` 指到 system/pkgs/bmi/ui/index.html）
      //   走一遍完整回路 —— Vue3 应用 + 垫片 + postMessage + 壳的转发 + （假）后端。
      //   验的正是"标题栏多出第四个选项卡、里面真的能算、切走再回来还在"。
      if (h === "embed"){
              const p0 = state.packages.find(x => x.ui && x.ui.embed) || null;
        if (!p0){ document.title = "NO-EMBED-PKG";
                  document.querySelector("#meta").textContent = "SCENARIO-ERR 没有带 ui 声明的包";
                  return; }
        select(p0.id);
        await sleep(400);
        const tabBtn = document.querySelector('.tab[data-tab="embed"]');
        const tabShown = !!(tabBtn && !tabBtn.hidden);
        await embedOpen(p0);                       // = 点「运行」
        await sleep(2500);                          // 等 iframe 加载 + Vue 挂载 + 问后端
        const frame = document.querySelector("#embed-wrap iframe[data-pid='" + p0.id + "']");
        let inner = null;
        try { inner = frame.contentDocument; }catch(e){ inner = null; }
        // file:// 的 iframe 是"另一个源"，父页面**读不到**里面（这正是隔离）——
        // 所以这里只验"壳这一侧"，里面的内容靠截图看。
        const shown = document.querySelector("#pane-embed").classList.contains("on");
        // 切走再切回来：iframe 不该被卸载（你要的"切走还在跑"）
        const srcBefore = frame.getAttribute("src");
        setTab("file");
        await sleep(300);
        setTab("embed");
        await sleep(300);
        const srcAfter = frame.getAttribute("src");
        const sameFrame = (srcBefore === srcAfter) && !!srcAfter && srcAfter !== "about:blank";
        const ok = tabShown && shown && sameFrame;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 选项卡=" + (tabShown ? 1 : 0) +
          " 显示了=" + (shown ? 1 : 0) + " 切走不卸载=" + (sameFrame ? 1 : 0);
        document.title = ok ? "READY" : "EMBED-FAIL";
      }
      // ★ 底部状态栏（`V-61`）：真跑一个包（走 clickRun 那条路），看最下面那行字
      //   有没有跟着变 —— 它靠的是 `toast()` 里那一句 `setStatus`，不是场景自己写的。
      // ★ 历史上下文里的快照分组（`V-112`）：该是 @dir-xxx / @abs-xxx，不是 @user
      if (h === "hist-snap"){
        setSide("hist");
        await sleep(500);
        const it = (HIST || []).find(x => x.cwd || x.target) || (HIST || [])[0];
        if (!it){ document.title = "HIST-NONE"; return; }
        select(null, it);
        await sleep(400);
        setTab("file");
        await sleep(600);
        const title = (document.querySelector(".bk-snap .bk-snap-title") || {}).title || "";
        const g = bkGroupForCtx();
        const okGroup = /^@(dir|abs)-/.test(g) || g === "@user" || g === "@misc";
        const notUser = g !== "@user" || /^user$/.test(bkScopeRels()[0] || "");
        document.querySelector("#meta").textContent =
          "DIAG " + (okGroup && notUser ? "OK" : "FAIL") + " 分组=" + JSON.stringify(g) +
          " 来源=" + JSON.stringify(bkScopeRels()) + " 悬浮提示=" + JSON.stringify(title.slice(0, 120));
        document.title = (okGroup && notUser) ? "READY" : "HISTGROUP-FAIL";
        return;
      }
      // ★ 创建快照的模态框 + 文件列表收起/展开（`V-122`）
      if (h === "snap-modal"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id); setTab("file"); await sleep(600);
        // V-126：预设现在是前端拿当前这一层算的 ⇒ 先在这一层造两个能命中的东西
        const rel0 = (FM.ctx && pkgRel(DATA.packages.find(x => x.id === FM.ctx))) || "system/pkgs/md5";
        FS[rel0].entries.push({name: "run.log", rel: rel0 + "/run.log", dir: false, size: 12, mtime: 0, ext: "log"});
        FS[rel0].entries.push({name: "venv", rel: rel0 + "/venv", dir: true, size: 0, mtime: 0, ext: ""});
        fmRefresh();
        await sleep(1200);
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(800);
        const win = document.querySelector("#snapwin");
        const chips0 = document.querySelectorAll("#snapwin .snap-chip").length;   // 默认**只该有命中的**
        const hot = document.querySelectorAll("#snapwin .snap-chip.hot").length;
        const more = document.querySelector("#snapwin #snap-more");
        if (more) more.click();                      // 点「更多」把没匹配到的展开
        await sleep(150);
        const chips = document.querySelectorAll("#snapwin .snap-chip").length;
        const keep = !document.querySelector("#snapwin #snap-keep");   // V-129：勾选已删，这里该是"不存在"
        // V-127：两颗按钮要在、且真的管用
        const fillBtn = document.querySelector("#snapwin #snap-fill");
        const clrBtn = document.querySelector("#snapwin #snap-clear");
        if (fillBtn) fillBtn.click();
        await sleep(150);
        const filledVal = ((document.querySelector("#snapwin #snap-rules") || {}).value || "");
        const filled = filledVal.length > 0;
        // V-128：只该写"检测到的" —— 场景里放了 run.log + venv/ ⇒ 只该有 *.log 和 venv
        // 按行精确比（别用 indexOf：`venv` 里就含着 `env` 三个字母，第一版断言就是这么写错的）
        const filledLines = filledVal.split("\n").map(x => x.trim()).filter(Boolean).sort().join(",");
        const noRedundant = filledLines === "*.log,venv";
        if (clrBtn) clrBtn.click();
        await sleep(150);
        const cleared = ((document.querySelector("#snapwin #snap-rules") || {}).value || "") === "";
        const rules0 = (document.querySelector("#snapwin #snap-rules") || {}).value || "";
        const c0 = document.querySelector("#snapwin .snap-chip");
        if (c0) c0.click();
        await sleep(150);
        const rules1 = (document.querySelector("#snapwin #snap-rules") || {}).value || "";
        (document.querySelector("#snapwin #snap-cancel") || {click(){}}).click();
        await sleep(200);
        const closed = !document.querySelector("#snapwin");
        // 折叠：先存一条，再收起、展开
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(700);
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(1500);
        const rows1 = document.querySelectorAll(".bk-snap .bk-file").length;
        (document.querySelector(".bk-snap .b-bkfoldfiles") || {click(){}}).click();
        await sleep(300);
        const rows2 = document.querySelectorAll(".bk-snap .bk-file").length;
        const foldedHint = !!document.querySelector(".bk-snap .bk-folded");
        (document.querySelector(".bk-snap .b-bkfoldfiles") || {click(){}}).click();
        await sleep(300);
        const rows3 = document.querySelectorAll(".bk-snap .bk-file").length;
        const ok = !!win && chips0 === hot && hot >= 2 && chips > chips0 && keep &&
                   !!fillBtn && !!clrBtn && filled && noRedundant && cleared &&
                   rules0 === "" && rules1.length > 0 && closed &&
                   rows1 > 0 && rows2 === 0 && foldedHint && rows3 === rows1;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 窗口=" + !!win + " 预设=" + chips + " 命中项=" + hot +
          " 记住勾=" + keep + " 点选后规则=" + JSON.stringify(rules1.slice(0, 24)) +
          " 关掉=" + closed + " 行数=" + [rows1, rows2, rows3].join("/") + " 收起提示=" + foldedHint;
        document.title = ok ? "READY" : "SNAPMODAL-FAIL";
        snapClose();
        return;
      }
      // ★ 两种编辑框不能串（`V-119`）：开过"多行"（过滤规则）之后，普通确认框不该把它带出来
      if (h === "modal-kinds"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id); setTab("file"); await sleep(400);
        askText("过滤规则（多行）", "*.log\nbuild/", function(){}, {multiline: true});
        await sleep(250);
        const ta1 = document.querySelector("#m-textarea");
        const shownMulti = !!ta1 && ta1.hidden === false && ta1.value.indexOf("*.log") >= 0;
        closeModal();
        await sleep(200);
        askConfirm("删除", "确定吗？", function(){});
        await sleep(250);
        const ta2 = document.querySelector("#m-textarea");
        const in2 = document.querySelector("#m-input");
        const confirmClean = !!ta2 && ta2.hidden === true && !!in2 && in2.hidden === true;
        closeModal();
        document.querySelector("#meta").textContent =
          "DIAG " + (shownMulti && confirmClean ? "OK" : "FAIL") +
          " 多行框出现=" + shownMulti + " 确认框里多行框藏好=" + confirmClean;
        document.title = (shownMulti && confirmClean) ? "READY" : "MODAL-FAIL";
        return;
      }
      // ★ 文件对比窗口（`V-109`）：文件列表 hover 出对比图标 → 点了弹两栏对比。
      if (h === "compare"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        setTab("file");
        await sleep(600);
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(900);
        bkSet("#snapwin #snap-title", "对比用");
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(1300);
        const rel = (FM.ctx && pkgRel(DATA.packages.find(x => x.id === FM.ctx))) || "system/pkgs/md5";
        const d = BKD.diff && BKD.diff.byRel ? BKD.diff.byRel : {};
        const one = Object.keys(d).find(k => d[k] && d[k].snap && !d[k].dir);
        const btn = document.querySelector("#fm-body tr.row .cmpbtn");
        const hasBtn = !!btn;
        await bkCompareOpen(one || (rel + "/AGENT.md"));
        await sleep(700);
        const win = document.querySelector("#cmpwin");
        const rows = document.querySelectorAll("#cmpwin .cmp-row").length;
        const stat = (document.querySelector("#cmpwin .cmp-stat") || {}).textContent || "";
        const hd = [].slice.call(document.querySelectorAll("#cmpwin .cmp-row.cmp-hd .cmp-tx"))
                     .map(x => x.textContent.trim());
        const shot = rows > 0 && !!win && /一致/.test(stat) && hd.length === 2;
        document.querySelector("#meta").textContent =
          "DIAG " + (shot ? "OK" : "FAIL") + " 图标=" + hasBtn + " 窗口=" + !!win +
          " 行=" + rows + " 统计=" + JSON.stringify(stat) + " 表头=" + JSON.stringify(hd);
        document.title = shot ? "READY" : "CMP-FAIL";
        cmpClose();
        return;
      }
      // ★ 刷新包列表**不能把文件管理的路径顶掉**（`V-98`，你 2026-09-30 报的）。
      //   那颗 ⟳ 的处理器就是 `init()`，它以前无条件把 ctx 按回 `__all__`、路径按回 `user/`。
      if (h === "refresh-keep-ctx"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        setTab("file");
        await sleep(600);
        const before = FM.ctx + "|" + ((FM.st[FM.ctx] || {}).rel || "");
        const path0 = ((document.querySelector("#fm-body .crumbs") || {}).textContent || "").trim();
        (document.querySelector("#btn-refresh") || {click(){}}).click();
        await sleep(1600);
        const after = FM.ctx + "|" + ((FM.st[FM.ctx] || {}).rel || "");
        const path1 = ((document.querySelector("#fm-body .crumbs") || {}).textContent || "").trim();
        const ok = before === after && path0 === path1 && /md5/.test(path0);
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 刷新前=" + JSON.stringify(before) +
          " 刷新后=" + JSON.stringify(after) + " 路径=" + JSON.stringify([path0, path1]);
        document.title = ok ? "READY" : "REFRESH-FAIL";
        return;
      }
      // ★ 差异视图（`V-94`）：左边=现在、右边=快照，四种状态四种色；"变了"用同一个琥珀色，
      //   谁大谁更深（左边大 ⇒ 左深右浅）。这条场景把四种状态**一次全造出来**再逐个查类名。
      if (h === "backup-diff"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        setTab("file");
        await sleep(600);
        const rel = (FM.ctx && pkgRel(DATA.packages.find(x => x.id === FM.ctx))) || "system/pkgs/md5";
        const es = FS[rel].entries;
        const big = es.find(e => !e.dir);
        if (!big){ document.title = "DIFF-NO-FILE"; return; }
        es.push({name: "空的.txt", rel: rel + "/空的.txt", dir: false, size: 0, mtime: 0, ext: "txt"});
        // ① 存快照（此时：big 和"空的.txt"都在快照里）
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(900);
        bkSet("#snapwin #snap-title", "差异用");
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(1200);
        // ② 造四种状态：变大的 / 快照里有现在没了的 / 后加的 / 空的（空的已在快照里）
        big.size = (big.size || 0) + 4096;
        const gone = es.find(e => !e.dir && e.name !== big.name && e.name !== "空的.txt");
        FS[rel].entries = FS[rel].entries.filter(e => e !== gone);
        FS[rel].entries.push({name: "新加的.txt", rel: rel + "/新加的.txt", dir: false,
                              size: 12, mtime: 0, ext: "txt"});
        fmRefresh();
        await sleep(1500);
        const q = s => document.querySelector(s);
        const cls = s => ((q(s) || {}).className || "");
        const deepLeft = cls('#fm-body tr.row[data-rel$="/' + big.name + '"]');
        const deepRight = cls('.bk-snap .bk-file[data-rel$="/' + big.name + '"]');
        const goneRight = cls('.bk-snap .bk-file[data-rel$="/' + gone.name + '"]');
        const goneLeft = cls('#fm-body tr.row[data-rel$="/' + gone.name + '"]');
        const newLeft = cls('#fm-body tr.row[data-rel$="/新加的.txt"]');
        const newRight = cls('.bk-snap .bk-file[data-rel$="/新加的.txt"]');
        const emptyBoth = cls('.bk-snap .bk-file[data-rel$="/空的.txt"]');
        const path = (q(".bk-snap .bk-mpath") || {}).textContent || "";
        const has = (s, c) => (" " + s + " ").indexOf(" " + c + " ") >= 0;
        const ok = path.indexOf(rel) >= 0 &&
                   has(deepLeft, "df-chg") && has(deepLeft, "df-deep") &&
                   has(deepRight, "df-chg") && has(deepRight, "df-soft") &&
                   has(goneRight, "df-gone") && !goneLeft &&
                   has(newLeft, "df-new") && !newRight &&
                   has(emptyBoth, "df-empty");
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 路径=" + JSON.stringify(path) +
          " 变大(左/右)=" + JSON.stringify([deepLeft, deepRight]) +
          " 快照独有(右)=" + JSON.stringify(goneRight) +
          " 后加(左/右)=" + JSON.stringify([newLeft, newRight]) +
          " 空文件(右)=" + JSON.stringify(emptyBoth);
        document.title = ok ? "READY" : "DIFF-FAIL";
        return;
      }
      // ★ 「整份界面里的按钮，一个描边都不许有」（`V-92`，你的原话："所有按钮全都带一个外边框"）。
      //   这条场景是**通用闸**：把设置面板和一个两个动词的确认框都摆出来（那两处的按钮平时看不见），
      //   然后遍历 document 里**每一个** `<button>` 量 border-width；顺手量所有输入框。
      //   ★ 硬判据 = 描边必须为 0；底色只报出来（"选中的那一档"还留一层灰底表示选中，
      //     那是**状态**不是**外观**，要不要也去掉由你定）。
      if (h === "flat-buttons"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        setTab("file");
        await sleep(500);
        (document.querySelector("#btn-settings") || {click(){}}).click();
        await sleep(800);
        askConfirm2("量一下", "两个动词的弹框", {label: "只写回", cb: function(){}},
                    {label: "一模一样", cb: function(){}});
        await sleep(350);
        const px = v => parseFloat(v) || 0;
        const label = b => (b.id || String(b.className || "") || b.tagName);
        const bordered = [], filled = [], inBordered = [];
        [].slice.call(document.querySelectorAll("button")).forEach(function(b){
          const cs = getComputedStyle(b);
          const w = Math.max(px(cs.borderTopWidth), px(cs.borderBottomWidth),
                             px(cs.borderLeftWidth), px(cs.borderRightWidth));
          if (w > 0) bordered.push(label(b) + "=" + cs.borderTopWidth);
          const bg = cs.backgroundColor;
          if (bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") filled.push(label(b) + "=" + bg);
        });
        [].slice.call(document.querySelectorAll("input,textarea")).forEach(function(i){
          const cs = getComputedStyle(i);
          if (px(cs.borderTopWidth) > 0) inBordered.push(label(i) + "=" + cs.borderTopWidth);
        });
        // 你点名的两处：弹框里的动词按钮、快照边栏里的按钮
        const modalBg = [].slice.call(document.querySelectorAll(".card .btns button"))
          .map(b => getComputedStyle(b).backgroundColor);
        const modalFlat = modalBg.every(c => c === "rgba(0, 0, 0, 0)" || c === "transparent");
        const total = document.querySelectorAll("button").length;
        const inputs = document.querySelectorAll("input").length;
        closeModal();
        closeSettings();
        await sleep(200);
        const ok = bordered.length === 0 && inBordered.length === 0 && modalFlat && total > 20;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 按钮=" + total + " 有描边的=" + bordered.length +
          (bordered.length ? ("（" + bordered.slice(0, 6).join(" ") + "）") : "") +
          " 输入框=" + inputs + " 有描边的=" + inBordered.length +
          (inBordered.length ? ("（" + inBordered.slice(0, 4).join(" ") + "）") : "") +
          " 弹框动词无底色=" + modalFlat +
          " ｜ 还带底色的（选中的那一档）=" + JSON.stringify(filled.slice(0, 8));
        document.title = ok ? "READY"
          : ("FLAT-FAIL 描边" + bordered.length + "[" + bordered.slice(0, 3).join(" ") + "]" +
             " 输入" + inBordered.length + " 弹框" + modalFlat);
        return;
      }
      // ★ 两处"拖着调宽"（`V-92`）：左侧列表 + 版本快照边栏。那条细线 `.grip` 平时是透明的，
      //   这里直接派发 pointer 事件模拟拖动（合成的 pointerId 下 `setPointerCapture` 会抛，
      //   代码里已经 try 住了；这条也顺便把"拖完要能继续用"验了）。
      if (h === "pane-resize"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        setTab("file");
        await sleep(500);
        const aside = document.querySelector("main > aside");
        const snap = document.querySelector(".bk-snap");
        const gA = document.querySelector("#grip-aside");
        const gB = document.querySelector(".bk-snap .b-bkgrip");
        const w = el => Math.round(el.getBoundingClientRect().width);
        const near = (a, b) => Math.abs(a - b) <= 3;          // 边框/取整留 3px 余量
        const drag = async (grip, x0, x1) => {
          const o = {bubbles: true, button: 0, pointerId: 7, isPrimary: true};
          grip.dispatchEvent(new PointerEvent("pointerdown", Object.assign({clientX: x0}, o)));
          grip.dispatchEvent(new PointerEvent("pointermove", Object.assign({clientX: x1}, o)));
          grip.dispatchEvent(new PointerEvent("pointerup", Object.assign({clientX: x1}, o)));
          await sleep(150);
        };
        const a0 = w(aside), s0 = w(snap);
        await drag(gA, 100, 180);                              // 往右拖 80 ⇒ 左边列变宽
        const a1 = w(aside);
        gA.dispatchEvent(new MouseEvent("dblclick", {bubbles: true}));
        await sleep(150);
        const a2 = w(aside);
        await drag(gB, 900, 820);                              // 边栏那条在**左边**：往左拖 ⇒ 变宽
        const s1 = w(snap);
        gB.dispatchEvent(new MouseEvent("dblclick", {bubbles: true}));
        await sleep(150);
        const s2 = w(snap);
        const ok = !!gA && !!gB && near(a0, 300) && a1 >= a0 + 70 && near(a2, 300) &&
                   near(s0, 320) && s1 >= s0 + 70 && near(s2, 320);
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 左列=" + [a0, a1, a2].join("/") +
          " 边栏=" + [s0, s1, s2].join("/") + " 细线=" + (!!gA) + (!!gB);
        document.title = ok ? "READY" : "RESIZE-FAIL";
        return;
      }
      if (h === "statusbar"){
              const p0 = state.packages.find(x => x.id === "img" && !(x.ui && x.ui.embed))
                   || state.packages.find(x => !(x.ui && x.ui.embed)) || state.packages[0];
        select(p0.id);
        setTab("detail");
        await sleep(300);
        const before = (document.querySelector("#status-text") || {}).textContent || "";
        await clickRun(p0);                       // = 点右上角「运行」
        await sleep(900);
        const during = (document.querySelector("#status-text") || {}).textContent || "";
        // 收尾（假 run_poll 立刻说"跑完了"）
        await sleep(700);
        const after = (document.querySelector("#status-text") || {}).textContent || "";
        const bar = document.querySelector("#statusbar");
        const gear = document.querySelector("#btn-settings");
        // ★ 那条"不要边框"（`V-62`）：齿轮必须是**光图标** —— 描边 0、
        //   底色透明（`.iconbtn` 默认是白底 + 1px 描边，钉在状态栏上像个方块）。
        const gs = gear ? getComputedStyle(gear) : {};
        const gearBorder = gear ? gs.borderTopWidth : "?";
        const gearBg = gear ? gs.backgroundColor : "?";
        const bare = (gearBorder === "0px") &&
                     (gearBg === "rgba(0, 0, 0, 0)" || gearBg === "transparent");
        const ok = !!bar && !!gear && !!gear.querySelector("svg") && bare &&
                   during.indexOf("moss :" + p0.id) >= 0 && after.indexOf("退出码") >= 0;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 起点=" + JSON.stringify(before.slice(0, 12)) +
          " 跑时=" + JSON.stringify(during.slice(0, 26)) +
          " 收尾=" + JSON.stringify(after.slice(0, 30)) +
          " 齿轮边框=" + gearBorder + " 底色=" + gearBg;
        document.title = ok ? "READY" : "STATUS-FAIL";
      }
      // ★ 「设置」面板（`V-60` / `V-63` / `V-66`）：左边分类、右边只显示当前那一组。
      //   打开 → 看结构（分类 4 个、输入是两列带标签的格子）→ 切到"执行提示"看开关 →
      //   改一项 → 保存该能点 → 存了 → 再打开留给截图。
      if (h === "settings"){
              await openSettings();
        await sleep(700);
        const navs = document.querySelectorAll("#set-nav .set-navitem").length;
        const panes = document.querySelectorAll("#set-body .set-pane").length;
        const activePane = (document.querySelector("#set-body .set-pane.on") || {}).dataset || {};
        const inputs = document.querySelectorAll("#set-body .set-pane.on .inp").length;
        const labels = document.querySelectorAll("#set-body .set-pane.on .set-lbl").length;
        const infos = document.querySelectorAll("#set-body .set-pane.on .set-info").length;
        const liveBox = !!document.querySelector("#set-live");
        const hasX = !!document.querySelector("#set-close svg");
        const save0 = document.querySelector("#set-save");
        const disabledAtStart = save0.disabled;
        // 切到"执行提示"看一眼开关（顺便验分类能切）
        const nav2 = document.querySelectorAll("#set-nav .set-navitem")[1];
        if (nav2) nav2.click();
        await sleep(250);
        const pane2 = (document.querySelector("#set-body .set-pane.on") || {}).dataset || {};
        const switches = document.querySelectorAll("#set-body .set-pane.on .sw").length;
        const back = document.querySelectorAll("#set-nav .set-navitem")[0];
        if (back) back.click();
        await sleep(200);
        // 改一项：符号框（这一格是"标签在上、控件在下"的两列网格）
        const sym = document.querySelector(
          '#set-body .set-pane.on .set-field[data-key="symbols.no_chdir_mode"] .inp');
        if (sym){ sym.value = "@"; sym.dispatchEvent(new Event("input", {bubbles: true})); }
        await sleep(700);
        const stateMoved = (document.querySelector("#set-state") || {}).textContent || "";
        const enabledAfter = !document.querySelector("#set-save").disabled;
        await saveSettings();
        await sleep(500);
        const saved = M.saved || {};
        const closedAfterSave = !document.querySelector("#settings").classList.contains("on");
        await openSettings();                     // 再打开：留给截图看个完整的
        await sleep(700);
        const opened = document.querySelector("#settings").classList.contains("on");
        const ok = navs === 4 && panes === 4 && activePane.group === "快捷命令" &&
                   pane2.group === "执行提示" && switches === 7 && inputs === 4 &&
                   labels === 4 && infos === 4 && liveBox && hasX && disabledAtStart &&
                   enabledAfter && /改了 1 项/.test(stateMoved) && closedAfterSave && opened &&
                   Object.keys(saved).length === 1 && saved["symbols.no_chdir_mode"] === "@";
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 分类=" + navs + " 面板=" + panes +
          " 首屏=" + activePane.group + " 次屏=" + pane2.group + " 开关=" + switches +
          " 输入=" + inputs + " 标签=" + labels + " ?=" + infos + " 预览行=" + (liveBox ? 1 : 0) +
          " ×=" + (hasX ? 1 : 0) + " 存了=" + JSON.stringify(saved);
        document.title = ok ? "READY" : ("SETTINGS-FAIL 分类=" + navs + " 面板=" + panes +
          " 首屏=" + activePane.group + " 次屏=" + pane2.group + " 开关=" + switches +
          " 输入=" + inputs + " 标签=" + labels + " ?=" + infos + " 预览=" + liveBox +
          " ×=" + hasX + " 起灰=" + disabledAtStart + " 改亮=" + enabledAfter +
          " 挪=" + /改了 1 项/.test(stateMoved) + " 关=" + closedAfterSave + " 开=" + opened +
          " 存=" + Object.keys(saved).length + " 值=" + saved["symbols.no_chdir_mode"]);
      }
      // 三个分类各留一张图（`V-66`：一次只看一组，得分别看一眼长什么样）
      if (h === "settings-exec" || h === "settings-format" || h === "settings-adv"){
        const want = {"settings-exec": "执行提示", "settings-format": "输出格式",
                      "settings-adv": "高级设置"}[h];
        await openSettings();
        await sleep(600);
        setActive(want);
        await sleep(500);
        const pane = document.querySelector("#set-body .set-pane.on");
        const on = !!pane && pane.dataset.group === want;
        const n = pane ? pane.querySelectorAll(".set-item, .set-field").length : 0;
        const ok = on && n > 0;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 分组=" + (pane ? pane.dataset.group : "-") +
          " 项数=" + n;
        document.title = ok ? "READY" : ("PANE-FAIL " + (pane ? pane.dataset.group : "-"));
      }
      // ★ 冲突那一路（`V-63` / `V-66`）：把「跑包」的前缀清空 ⇒ 和「路径调用」同时留空。
      //   期望：那两项飘红 + 导航上"快捷命令"点一个小红点 + 脚上一句话 + **保存禁用**。
      if (h === "settings-bad"){
              await openSettings();
        await sleep(700);
        const inp = document.querySelector(
          '#set-body .set-pane.on .set-field[data-key="symbols.plugin_mode"] .inp');
        if (inp){ inp.value = ""; inp.dispatchEvent(new Event("input", {bubbles: true})); }
        await sleep(800);
        let redCount = 0, reason = "";
        document.querySelectorAll("#set-body .set-pane.on .set-item, #set-body .set-pane.on .set-field")
          .forEach(b => {
            if (b.classList.contains("bad")) redCount++;
            const w = b.querySelector('[data-role="prob"]');
            if (w && w.textContent) reason += " " + w.textContent;
          });
        const dot = document.querySelector("#set-nav .set-navitem.has-bad");
        const live = document.querySelector("#set-live");
        const liveBad = !!live && live.classList.contains("bad");
        const st = (document.querySelector("#set-state") || {}).textContent || "";
        const disabled = document.querySelector("#set-save").disabled;
        const ok = redCount === 2 && /不能同时留空/.test(reason) && !!dot && liveBad &&
                   /冲突/.test(st) && disabled;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 红了几项=" + redCount +
          " 导航红点=" + (dot ? 1 : 0) + " 预览红=" + (liveBad ? 1 : 0) +
          " 保存禁用=" + (disabled ? 1 : 0) + " 脚上=" + JSON.stringify(st.slice(0, 30));
        document.title = ok ? "READY" : ("SETTINGS-BAD-FAIL 红=" + redCount +
          " 点=" + (dot ? 1 : 0) + " 预览红=" + liveBad + " 禁=" + disabled +
          " 脚=" + JSON.stringify(st.slice(0, 24)));
      }
      // ★ 提醒那一路（`V-63`）：只提醒、**不拦保存**（黄的不是红的）。
      if (h === "settings-warn"){
              await openSettings();
        await sleep(600);
        setActive("高级设置");
        await sleep(300);
        const num = document.querySelector("#set-body .set-pane.on .step .num");
        if (num){ num.value = "8"; num.dispatchEvent(new Event("change", {bubbles: true})); }
        await sleep(800);
        const item = num ? num.closest(".set-field") : null;
        const yellow = !!item && item.classList.contains("warn");
        const why = item ? (item.querySelector('[data-role="prob"]') || {}).textContent || "" : "";
        const dot = document.querySelector("#set-nav .set-navitem.has-warn");
        const st = (document.querySelector("#set-state") || {}).textContent || "";
        const canSave = !document.querySelector("#set-save").disabled;
        const ok = yellow && /提醒/.test(why) && !!dot && canSave && /改了 1 项/.test(st);
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 黄=" + (yellow ? 1 : 0) +
          " 导航黄点=" + (dot ? 1 : 0) + " 能存=" + (canSave ? 1 : 0) +
          " ｜" + JSON.stringify(why.slice(0, 30));
        document.title = ok ? "READY" : ("SETTINGS-WARN-FAIL 黄=" + yellow +
          " 点=" + !!dot + " 能存=" + canSave + " 脚=" + JSON.stringify(st.slice(0, 20)));
      }
      // ★ 说明挂在 `?` 上（`V-66`）：把鼠标放到"向上查找层数"那个 `?` 上，看提示弹不弹。
      if (h === "settings-tip"){
              await openSettings();
        await sleep(600);
        setActive("高级设置");
        await sleep(300);
        const key = "search.max_parent_depth";
        const q = document.querySelector(
          '#set-body .set-pane.on .set-info[data-tip-key="' + key + '"]');
        if (q) q.dispatchEvent(new MouseEvent("mouseover", {bubbles: true}));
        await sleep(300);
        const tip = document.querySelector("#tip");
        const byHover = !!tip && !tip.hidden;
        // ★ 兜底：再**直接调一次** showTip —— 这样能分清"是 hover 那条路没通"还是
        //   "提示本身画不出来"（上一版这个场景就是这么定位的）
        if (!byHover){ try { showTip(key); } catch(e){ M.tipErr = String(e && e.message || e); } }
        await sleep(250);
        const shown = !!tip && !tip.hidden;
        const txt = shown ? (tip.textContent || "") : "";
        const ok = shown && /最多看几个目录/.test(txt) && /一共 4 个目录/.test(txt) && !!q;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 提示=" + (shown ? 1 : 0) +
          " hover=" + (byHover ? 1 : 0) + " 直接调=" + (shown && !byHover ? 1 : 0) +
          " ?=" + (q ? 1 : 0) + " 错=" + (M.tipErr || "无") + " ｜" +
          JSON.stringify(txt.replace(/\s+/g, " ").slice(0, 50));
        document.title = ok ? "READY" : ("TIP-FAIL 显示=" + shown + " hover=" + byHover +
          " ?=" + !!q + " 错=" + (M.tipErr || "无"));
      }
      // ★ 备份那一页（`V-87`）：建一次 → 列表/清单出来 → 看内容 → 再来一次（该全去重）
      //   → 删掉一次并回收。判定都落在**能看见的东西**上（DOM 里的文字/条数）。
      // ★ 版本快照边栏（`V-91`）：建两次 → 展开看文件/内容 → 删一次（去重靠"内容块"不变验证）
      if (h === "backup"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        setTab("file");
        await sleep(500);
        const snap = document.querySelector(".bk-snap");
        const inSide = !!snap;
        const newBtn = document.querySelector(".bk-snap .b-bknew");
        if (!newBtn){ document.title = "SNAP-NO-BTN"; return; }
        // ① 存第一个快照
        newBtn.click();
        await sleep(900);
        const formShown = !!document.querySelector("#snapwin");
        const igShown = (document.querySelector("#snapwin #snap-hint") || {}).textContent || "";
        // ★ 这两样只在**表单开着**的时候存在：一定要在这儿抓，别等场景末尾（那时表单已经关了 —— 
        //   我第一版就写在末尾，结果 pre 永远是 false）。
        const preShown = !!document.querySelector("#snapwin .snap-pres");
        bkSet("#snapwin #snap-title", "预览快照 A");
        bkSet("#snapwin #snap-note", "第一次");
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(900);
        const nodes1 = document.querySelectorAll(".bk-snap .bk-tl-item").length;   // 含"当前工作区"
        // ★ 时间轴第一条**永远是**「当前工作区」（那张卡没有 `data-bk`），所以标题要挑有 id 的那条
        const firstTitle = (document.querySelector(".bk-snap .bk-tl-item[data-bk] .bk-card-top b")
                            || {}).textContent || "";
        const tip1 = (document.querySelector(".bk-snap-foot .bk-hint") || {}).title || "";
        // ② 展开它看文件（存完自己就展开了 → 已经开着就别再点，再点一下是"收起"）
        if (!document.querySelector(".bk-snap .bk-tl-item[data-bk] .bk-files")){
          (document.querySelector(".bk-snap .bk-tl-item[data-bk] .bk-card") || {click(){}}).click();
          await sleep(700);
        }
        const fileRows = document.querySelectorAll(".bk-snap .bk-file").length;
        const heads = [].slice.call(document.querySelectorAll(".bk-snap .bk-files .bk-hint"))
          .map(t => (t.textContent || "").trim());
        // ③ 看内容
        const vbtn = document.querySelector(".bk-snap .b-bkview");
        if (vbtn) vbtn.click();
        await sleep(600);
        const viewText = (document.querySelector(".bk-snap .bk-view-text") || {}).textContent || "";
        // ④ 再存一个（内容全重复 ⇒ 内容块数不该变）
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(900);
        bkSet("#snapwin #snap-title", "预览快照 B");
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(1000);
        const nodes2 = document.querySelectorAll(".bk-snap .bk-tl-item").length;
        const tip2 = (document.querySelector(".bk-snap-foot .bk-hint") || {}).title || "";
        // ⑤ 删掉最新那个
        (document.querySelector(".bk-snap .b-bkdel") || {click(){}}).click();
        await sleep(500);
        const confirmShown = !!document.querySelector("#m-ok");
        (document.querySelector("#m-ok") || {click(){}}).click();
        await sleep(1100);
        const nodes3 = document.querySelectorAll(".bk-snap .bk-tl-item").length;
        const tip3 = (document.querySelector(".bk-snap-foot .bk-hint") || {}).title || "";
        const flags = {
          side: inSide, form: formShown, n1: nodes1 === 2,
          ig: /分组/.test(igShown),
          pre: preShown, titleA: /预览快照 A/.test(firstTitle),
          rows: fileRows > 0, view: /这一段内容块/.test(viewText),
          cnt1: /快照：1 次/.test(tip1) && /内容块 4 个/.test(tip1),
          n2: nodes2 === 3, cnt2: /快照：2 次/.test(tip2) && /内容块 4 个/.test(tip2),
          confirm: confirmShown, n3: nodes3 === 2, cnt3: /快照：1 次/.test(tip3),
        };
        const ok = Object.keys(flags).every(k => flags[k]);
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 边栏=" + inSide + " 表单=" + formShown +
          " 节点=" + [nodes1, nodes2, nodes3].join("/") + " 行=" + fileRows +
          " 计数=" + JSON.stringify(heads) + " 看内容=" + /这一段内容块/.test(viewText) +
          " ｜ tip1=" + JSON.stringify(tip1.slice(0, 60)) +
          " ｜ tip2=" + JSON.stringify(tip2.slice(0, 60));
        document.title = ok ? "READY"
          : ("SNAP-FAIL " + Object.keys(flags).filter(k => !flags[k]).join(","));
        return;
      }
      // ★ 合并恢复（`V-91` 边栏版）：改坏一个、删掉一个 → 「恢复」（合并）
      if (h === "backup-restore"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        setTab("file");
        await sleep(500);
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(900);
        bkSet("#snapwin #snap-title", "恢复用");
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(1000);
        const rel = (FM.ctx && pkgRel(DATA.packages.find(x => x.id === FM.ctx))) || "system/pkgs/md5";
        const st = FS[rel];
        const files = ((st && st.entries) || []).filter(e => !e.dir);
        if (files.length < 2){ document.title = "BK-NO-FILES"; return; }
        const bad = files[0], gone = files[1];
        const origSize = bad.size || 0;
        FS[rel].entries.find(e => e.rel === bad.rel).size = origSize + 999;   // 伪造"内容变了"
        FS[rel].entries = FS[rel].entries.filter(e => e.rel !== gone.rel);    // 删掉一个
        // ★ `V-92`：滑块没了（"向 git 看齐"）—— 这里没有多出来的文件 ⇒ 应该**只有一个动词**，
        //   第二个按钮（`#m-ok2`）必须是藏着的。
        const goBtn = document.querySelector(".bk-snap .bk-card [data-bk-act='restore']");
        if (!goBtn){ document.title = "BK-NO-BTN"; return; }
        goBtn.click();
        await sleep(700);
        const modalText = ((document.querySelector(".card p") || {}).textContent || "")
          .replace(/\s+/g, " ");
        const shown = !!document.querySelector("#m-ok");
        const altHidden = !!document.querySelector("#m-ok2") &&
                          document.querySelector("#m-ok2").hidden === true;
        (document.querySelector("#m-ok") || {click(){}}).click();
        await sleep(1200);
        const backNow = (FS[rel].entries || []).some(e => e.rel === gone.rel);
        const fixed = (FS[rel].entries || []).find(e => e.rel === bad.rel);
        const bakMade = (FS[rel].entries || []).some(e => e.rel === bad.rel + ".bak");
        const cached = Object.keys(FM.st).every(k => FM.st[k].stale === true);
        const ok = shown && altHidden && /补/.test(modalText) && /回退/.test(modalText) &&
                   backNow && fixed && (fixed.size === origSize) && bakMade && cached;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 框=" + shown + " 单动词=" + altHidden +
          " 补的回来了=" + backNow +
          " 覆盖回来了=" + !!fixed + (fixed ? ("（" + fixed.size + " vs " + origSize + "）") : "") +
          " .bak=" + bakMade + " 缓存作废=" + cached +
          " ｜ " + JSON.stringify(modalText.slice(0, 120));
        document.title = ok ? "READY" : "BK-RESTORE-FAIL";
        return;
      }
      // ★ 两个动词（`V-92`，向 git 看齐）：现在多出来的 → 弹框里两个按钮，
      //   `#m-ok` =「只写回」（git restore，多出来的留着）、`#m-ok2` =「一模一样」
      //   （git reset --hard，挪进回收站）。这里点第二个，验"多出来的真被挪走"。
      if (h === "backup-sync"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        setTab("file");
        await sleep(500);
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(900);
        bkSet("#snapwin #snap-title", "同步用");
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(1000);
        const rel = (FM.ctx && pkgRel(DATA.packages.find(x => x.id === FM.ctx))) || "system/pkgs/md5";
        FS[rel].entries.push({name: "后来加的.txt", rel: rel + "/后来加的.txt", dir: false,
                              size: 11, mtime: 0, ext: "txt"});
        const goBtn = document.querySelector(".bk-snap .bk-card [data-bk-act='restore']");
        const segGone = !document.querySelector(".bk-snap [data-bk-mode]");
        if (!goBtn){ document.title = "SYNC-NO-BTN"; return; }
        goBtn.click();
        await sleep(700);
        const modalText = ((document.querySelector(".card p") || {}).textContent || "")
          .replace(/\s+/g, " ");
        const alt = document.querySelector("#m-ok2");
        const shown = !!document.querySelector("#m-ok");
        const two = !!alt && alt.hidden === false && /一模一样/.test(alt.textContent || "");
        alt.click();                                   // = 一模一样（git reset --hard）
        await sleep(1300);
        const gone = !(FS[rel].entries || []).some(e => e.name === "后来加的.txt");
        const trashed = (M.bkTrashed || []).some(x => /后来加的\.txt$/.test(x));
        const ok = shown && two && segGone && /回收站/.test(modalText) && gone && trashed;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 框=" + shown + " 两个动词=" + two +
          " 滑块没了=" + segGone + " 说了回收站=" + /回收站/.test(modalText) +
          " 挪走了=" + gone + " 走回收站=" + trashed +
          " ｜ " + JSON.stringify(modalText.slice(0, 130));
        document.title = ok ? "READY" : "SYNC-FAIL";
        return;
      }
      // ★ 导出（`V-91` 边栏版）：目标用弹窗问；把文件夹"拖"到边栏上也当目标
      if (h === "backup-export"){
        const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        setTab("file");
        await sleep(500);
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(900);
        bkSet("#snapwin #snap-title", "导出用");
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(1000);
        // ① 拖文件夹到边栏上（真路径由宿主送来，这里直接叫那个钩子）
        BK.dropOver = true;
        const took = window.__mossDropHook([{path: "D:\\\\拖进来的目录", isDir: true,
                                             dir: "D:\\\\", name: "拖进来的目录"}]);
        await sleep(200);
        const dropOk = took === true && /拖进来的目录/.test(String(BK.exportTo));
        // ② 点「导出」→ 弹窗里把目标接上 /2/
        const exBtn = document.querySelector(".bk-snap .bk-card [data-bk-act='export']");
        if (!exBtn){ document.title = "EXPORT-NO-BTN"; return; }
        exBtn.click();
        await sleep(600);
        const inputShown = !!document.querySelector("#m-input");
        const mi = document.querySelector("#m-input");
        mi.value = "D:\\\\拖进来的目录/2/";
        (document.querySelector("#m-ok") || {click(){}}).click();
        await sleep(700);
        const modalText = ((document.querySelector(".card p") || {}).textContent || "")
          .replace(/\s+/g, " ");
        const shown = !!document.querySelector("#m-ok");
        (document.querySelector("#m-ok") || {click(){}}).click();
        await sleep(1200);
        const ex = M.bkExported || {};
        const paths = ex.relPaths || [];
        const ok = dropOk && inputShown && shown && /原文件不动/.test(modalText) &&
                   String(ex.root || "").replace(/\\\\/g, "/").replace(/\/+$/, "").endsWith("/2") &&
                   paths.length > 0;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 拖进来=" + dropOk + " 弹窗=" + inputShown +
          " 落到=" + ex.root + " 文件数=" + paths.length +
          "（例 " + JSON.stringify(paths.slice(0, 2)) + "）" +
          " ｜ " + JSON.stringify(modalText.slice(0, 110));
        document.title = ok ? "READY" : "EXPORT-FAIL";
        return;
      }
      // ★ 边栏跟着"当前选中的对象"走（`V-91`）：换包 = 换一组快照；删整组只动那一组
      if (h === "backup-groups"){
        const pA = state.packages.find(x => x.id === "md5") || state.packages[0];
        const pB = state.packages.find(x => x.id === "bmi") || state.packages[1] || pA;
        // A 存一个
        select(pA.id);
        setTab("file");
        await sleep(500);
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(900);
        bkSet("#snapwin #snap-title", "A 的快照");
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(1000);
        const aNodes = document.querySelectorAll(".bk-snap .bk-tl-item").length;
        const aLabel = (document.querySelector(".bk-snap .bk-card.flat .bk-card-sub") || {})
          .textContent || "";
        // 换到 B：边栏该换一组（空）
        select(pB.id);
        setTab("file");
        await sleep(900);
        const bNodes = document.querySelectorAll(".bk-snap .bk-tl-item").length;
        const bLabel = (document.querySelector(".bk-snap .bk-card.flat .bk-card-sub") || {})
          .textContent || "";
        // B 存一个
        (document.querySelector(".bk-snap .b-bknew") || {click(){}}).click();
        await sleep(900);
        bkSet("#snapwin #snap-title", "B 的快照");
        (document.querySelector("#snapwin #snap-save") || {click(){}}).click();
        await sleep(1000);
        const bNodes2 = document.querySelectorAll(".bk-snap .bk-tl-item").length;
        // 回 A：应该还是 A 那一个
        select(pA.id);
        setTab("file");
        await sleep(900);
        const aNodes2 = document.querySelectorAll(".bk-snap .bk-tl-item").length;
        const aTitle = (document.querySelector(".bk-snap .bk-tl-item[data-bk] .bk-card-top b")
                        || {}).textContent || "";
        // 删掉 A 这一组（foot 那颗垃圾桶）
        (document.querySelector(".bk-snap .b-bkdropgroup") || {click(){}}).click();
        await sleep(700);
        const modal = ((document.querySelector(".card p") || {}).textContent || "")
          .replace(/\s+/g, " ");
        const shown = !!document.querySelector("#m-ok");
        (document.querySelector("#m-ok") || {click(){}}).click();
        await sleep(1100);
        const aNodes3 = document.querySelectorAll(".bk-snap .bk-tl-item").length;
        // 切到 B：它那一组还在
        select(pB.id);
        setTab("file");
        await sleep(900);
        const bLeft = document.querySelectorAll(".bk-snap .bk-tl-item").length;
        const ok = aNodes === 2 && bNodes === 1 && bNodes2 === 2 && aNodes2 === 2 &&
                   /A 的快照/.test(aTitle) && shown && /文件夹/.test(modal) &&
                   aNodes3 === 1 && bLeft === 2;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " A=" + [aNodes, aNodes2, aNodes3].join("/") +
          " B=" + [bNodes, bNodes2, bLeft].join("/") + " A标题=" + JSON.stringify(aTitle) +
          " 框=" + shown + " 标签=" + JSON.stringify([aLabel.trim(), bLabel.trim()]) +
          " ｜ " + JSON.stringify(modal.slice(0, 90));
        document.title = ok ? "READY" : "GROUPS-FAIL";
        return;
      }
      // ★ 参数框右边那颗"一键清空"（`V-86`）：没内容时**不该出现**，打字后出现，
      //   点一下要清空 + 预览行跟着变 + 光标回到框里。
      if (h === "args-clear"){
              const p0 = state.packages.find(x => x.id === "md5") || state.packages[0];
        select(p0.id);
        await sleep(400);
        const inp = document.querySelector("#args");
        const btn = document.querySelector("#btn-args-clear");
        if (!inp || !btn){ document.title = "ARGS-NO-ELEMENT"; return; }
        const hiddenWhenEmpty = btn.hidden;
        const invisibleWhenEmpty = getComputedStyle(btn).display === "none";
        // 打字 → 按钮该浮出来 + 预览行跟着变
        inp.value = "a.png -o D:\\out";
        inp.dispatchEvent(new Event("input", {bubbles: true}));
        await sleep(150);
        const shown = !btn.hidden && getComputedStyle(btn).display !== "none";
        const preview1 = (document.querySelector("#preview") || {}).textContent || "";
        // 点它 → 输入框空、预览行回到只有命令名、按钮又藏起来、光标在框里
        btn.click();
        await sleep(150);
        const cleared = inp.value === "";
        const preview2 = (document.querySelector("#preview") || {}).textContent || "";
        const hiddenAgain = btn.hidden;
        const focused = document.activeElement === inp;
        const ok = hiddenWhenEmpty && invisibleWhenEmpty && shown &&
                   /a\.png/.test(preview1) && cleared && !/a\.png/.test(preview2) &&
                   hiddenAgain && focused && !(window.__errors || []).length;
        document.querySelector("#meta").textContent = "DIAG " + (ok ? "OK" : "FAIL") +
          " 空时藏=" + hiddenWhenEmpty + "/" + invisibleWhenEmpty +
          " 打字后露=" + shown + " 清空=" + cleared + " 又藏=" + hiddenAgain +
          " 光标回框=" + focused +
          " 预览=" + JSON.stringify([preview1, preview2]);
        document.title = ok ? "READY" : "ARGS-CLEAR-FAIL";
        return;
      }

      // ★ 命令行那行输入（`V-43`）：包 `input()` 问你话时能答。
      //   真的 stdin 那条链由宿主侧测试证明；这里只验界面这半：
      //   在跑 → 输入行可用；发一行 → 回显进输出 + 调了 run_input；跑完 → 又禁用。
      if (h === "console-input"){
              const p0 = state.packages.find(x => x.id === "img") || state.packages[0];
        select(p0.id);
        setTab("console");
        await sleep(300);
        const inp = document.querySelector("#stdin"), btn = document.querySelector("#btn-send");
        const beforeDisabled = inp.disabled;
        // 造一个"正在跑"：直接塞进 RUNS 再刷一下（预览的假 run_poll 会立刻结束）
        RUNS[p0.id] = {rid: "r1", cmd: "moss :" + p0.id, timer: null,
                              stopped: false, switched: false, tabAtStart: "console"};
        setConsole(p0.id, "$ moss :" + p0.id + "\n输出到哪？（没有默认值，请自己选）\n" +
          "   1) 覆盖原图\n   2) 删除原图\n   3) 新文件夹\n", "运行中");
        await sleep(200);
        const liveOk = !inp.disabled && !btn.disabled;
        inp.value = "3";
        (document.querySelector("#btn-send") || {click(){}}).click();
        await sleep(400);
        const sent = (M.inputs || [])[0] || {};
        const echoed = (document.querySelector("#out").textContent || "").includes("3");
        const cleared = inp.value === "";
        // 跑完了 → 输入行该禁用
        delete RUNS[p0.id];
        paintInbar(p0.id);
        await sleep(150);
        const afterDisabled = inp.disabled;
        const ok = beforeDisabled && liveOk && sent.line === "3" && sent.rid === "r1" &&
                   echoed && cleared && afterDisabled;
        // ★ 截图要拍的是"活着"那一眼：把在跑的状态摆回去（问题 + 我答的那行都在），
        //   判定结果放顶栏（短），别用诊断文字盖住要看的东西。
        RUNS[p0.id] = {rid: "r1", cmd: "moss :" + p0.id, timer: null,
                              stopped: false, switched: false, tabAtStart: "console"};
        setConsole(p0.id, "$ moss :" + p0.id + "\n输出到哪？（没有默认值，请自己选）\n" +
          "   1) 覆盖原图 —— 直接写回源目录，同名文件会被覆盖\n" +
          "   2) 删除原图 —— 转换成功后删除源文件，无法撤销\n" +
          "   3) 新文件夹 —— 输出到 compressed_output\\，原图不动\n3\n", "运行中");
        await sleep(250);
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 没跑时禁用=" + beforeDisabled +
          " 在跑时可用=" + liveOk + " 发出=" + (sent.line === "3" ? 1 : 0) +
          " 回显=" + echoed + " 清空=" + cleared + " 跑完禁用=" + afterDisabled;
        document.title = ok ? "READY" : "STDIN-FAIL";
      }

      if (h === "drop-hot"){

              // 只看"拖上来时"长什么样（不松手）：列表只列收得下的 + 详情页浮出投放框
        const dragEv = isDir => {
          const e = new Event("dragenter", {bubbles: true});
          e.dataTransfer = {types: ["Files"], dropEffect: "",
            items: [{webkitGetAsEntry: () => ({isDirectory: isDir, name: "x"})}]};
          return e;
        };
        select("md5");
        setTab("detail");
        await sleep(400);
        document.dispatchEvent(dragEv(false));
        await sleep(250);
        document.title = "READY";
      }
      if (h === "drop-dir" || h === "drop-file"){
        const isDirDrag = h === "drop-dir";
        const wantId = isDirDrag ? "tree" : "md5";
        const pane = document.querySelector("#pane-detail");
        const dz = document.querySelector("#dropzone");
        const dragEv = (t, isDir) => {
          const e = new Event(t, {bubbles: true});
          e.dataTransfer = {types: ["Files"], dropEffect: "",
            items: [{webkitGetAsEntry: () => ({isDirectory: isDir, name: "x"})}]};
          return e;
        };
        // 先站在一个**不收**这类东西的包上（快捷翻译没有参数、也不收拖入）
        select("fanyi");
        setTab("detail");
        await sleep(350);
        const beforeIds = [].slice.call(document.querySelectorAll("#list .item"))
                            .map(e => e.dataset.id);
        // ① 拖进来：列表应该只列"收得下它"的包
        document.dispatchEvent(dragEv("dragenter", isDirDrag));
        await sleep(300);
        const afterIds = [].slice.call(document.querySelectorAll("#list .item"))
                           .map(e => e.dataset.id);
        const filtered = afterIds.length > 0 && afterIds.every(id => {
          const p = state.packages.find(x => x.id === id);
          return p && p.drop && p.drop.some(c => isDirDrag ? c.dir : c.file);
        });
        const hidFanyi = afterIds.indexOf("fanyi") < 0;
        const bar = document.querySelector("#dragbar");
        const barText = (bar && !bar.hidden) ? bar.textContent : "";
        // ② 划过目标那一行 → 应该自动选中它，并浮出投放框
        const row = [].slice.call(document.querySelectorAll("#list .item"))
                      .find(e => e.dataset.id === wantId);
        let hovered = false, boxText = "", boxOn = false;
        if (row){
          row.dispatchEvent(dragEv("dragover", isDirDrag));
          await sleep(300);
          hovered = !!(cur && cur.id === wantId);   // `cur` 是主脚本里的顶层 let，
                                                    // 不是 window 的属性（别写 self.cur）
          boxOn = dz.classList.contains("on");
          const big = dz.querySelector(".dz-big"), sub = dz.querySelector(".dz-sub");
          boxText = (big ? big.textContent : "") + " / " + (sub ? sub.textContent : "");
        }
        // ③ 松手：宿主把真实路径送过来
        const p0 = state.packages.find(x => x.id === wantId);
        const argsBefore = (document.querySelector("#args") || {}).value || "";
        const dropPath = isDirDrag ? M.dropDir : M.dropFile;
        const html = {path: dropPath, isDir: isDirDrag,
                      dir: isDirDrag ? dropPath : M.dropDir,
                      name: isDirDrag ? dropPath.split(/[\\/]/).pop()
                                      : dropPath.split(/[\\/]/).pop()};
        window.__mossDrop([html]);
        await sleep(800);
        const argsAfter = (document.querySelector("#args") || {}).value || "";
        const run = (M.runs || [])[0] || {};
        const zoneOff = !dz.classList.contains("on");
        // ④ 再拖一次（**没有空格**的路径）：验两件事 ——
        //    a) 连着拖不会把上一次那段叠在参数里（你实测叠成两条路径，md5 就判成字符串了）
        //    b) 不加引号的 Windows 路径会被 shlex 吃光反斜杠，所以**无论如何都要加引号**
        let twice = "", twiceRun = {};
        if (!isDirDrag){
          const p2 = M.dropFile2;                       // 例：…\download.ico（没有空格）
          window.__mossDrop([{path: p2, isDir: false, dir: M.dropDir,
                              name: p2.split(/[\\/]/).pop()}]);
          await sleep(700);
          twice = (document.querySelector("#args") || {}).value || "";
          twiceRun = (M.runs || [])[1] || {};
        }
        // 期望：tree = 只改工作目录、参数一个字不动；md5 = 工作目录是文件所在目录、
        //       参数只给**引号包着的文件名**（包自己按 cwd 拼）
        const wantCwd = isDirDrag ? dropPath : M.dropDir;
        const wantArgs = isDirDrag ? argsBefore
          : '"' + dropPath.split(/[\\/]/).pop() + '"';
        const ok = filtered && hidFanyi && !!barText && hovered && boxOn && zoneOff &&
                   run.pid === wantId && (run.cwd || "") === wantCwd &&
                   argsAfter === wantArgs &&
                   (isDirDrag || (twice === '"' + M.dropFile2.split(/[\\/]/).pop() + '"' &&
                                  (twiceRun.cwd || "") === M.dropDir));
        const diag = "DIAG " + (ok ? "OK" : "FAIL") +
          "\n拖动前列表  = " + beforeIds.length + " 个（含 fanyi=" + (beforeIds.indexOf("fanyi") >= 0) + "）" +
          "\n拖动后列表  = " + afterIds.length + " 个：" + afterIds.join(",") +
          "\n只列收得下的 = " + filtered + "   不收的藏起来了吗 = " + hidFanyi +
          "\n左边那条提示 = " + barText.replace(/\s+/g, " ").slice(0, 80) +
          "\n划过 " + wantId + " 自动选中 = " + hovered + "   投放框出现 = " + boxOn +
          "\n框上写的话  = " + boxText.replace(/\s+/g, " ").slice(0, 120) +
          "\n松手后框收了吗 = " + zoneOff +
          "\n参数框 之前/之后 = " + JSON.stringify(argsBefore) + " → " + JSON.stringify(argsAfter) +
          "\n跑起来了吗  = pid=" + (run.pid || "-") + "  args=" + JSON.stringify(run.args || "") +
          "  cwd=" + JSON.stringify(run.cwd || "") +
          (isDirDrag ? "" :
            "\n再拖一次    = args=" + JSON.stringify(twice) + "  cwd=" +
            JSON.stringify(twiceRun.cwd || "") +
            "\n（连着拖不该叠起来；没有空格的路径也必须加引号，不然反斜杠会被 shlex 吃光）") +
          "\n页面日志    = " + JSON.stringify(M.uiLogs || []);
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 筛=" + (filtered && hidFanyi ? 1 : 0) +
          " 选中=" + (hovered ? 1 : 0) + " 框=" + (boxOn ? 1 : 0) + " 跑=" + (run.pid === wantId ? 1 : 0);
        document.querySelector("#out").textContent = diag;
        document.querySelector("#dropzone").className = "";
        if (ok) setTab("console");
        document.title = ok ? "READY" : "DROP-FAIL";
      }
      // ★ 报错这条路本身也要能自证（`V-81`）：故意造一个"计算属性里抛错"的组件（和
      //   `MossList.rows` 读 `DATA.packages` 抛的那个是同一类），看它有没有被
      //   `Vue.config.errorHandler` 收进 `window.__errors`。
      //   为什么要这条：那道"有错就判 PAGE-ERR"的闸要是本身收不到错，坏代码照样过 ——
      //   我更怕这个（你正是从 devtools 里看到一条我这边"零错误"的报错）。
      if (h === "err-path"){
              const before = (window.__errors || []).length;
        const div = document.createElement("div");
        document.body.appendChild(div);
        // 用**界面自己那条路**（`mountVue`）建一个"computed 里抛错"的组件 —— 和
        // `MossList.rows` 读 `DATA.packages` 抛的那个是同一类、同一条通路。
        let mounted = "ok";
        try{
          mountVue({ computed: { boom(){ throw new Error("自测：故意在 computed 里扔的错"); } },
                     template: "<div>{{ boom }}</div>" }, div);
        }catch(e){ mounted = "抛出到外面:" + e.message; }
        await sleep(250);
        div.remove();
        const errs = window.__errors || [];
        const got = errs.length - before;
        const first = String(errs[before] || "");
        const ok = got > 0 && /组件出错|自测/.test(first);
        window.__errPathOK = ok;                 // 别把这条"故意错的"算到最后那道闸头上
        document.querySelector("#meta").textContent = "ERR-PATH " + (ok ? "OK" : "FAIL") +
          " 收到 " + got + " 条（" + mounted + "）：" + first.replace(/\n/g, " ").slice(0, 150);
        document.title = ok ? "READY" : "ERRPATH-FAIL";
        return;
      }

      // ★ 点**真按钮**（`V-81`）：详情页那串按钮是 `wireDetail()` 挨个 `.onclick` 绑上去的，
      //   只要它中途抛一次异常，**它后面那些按钮就全没绑上**，而界面一个字都不报 ——
      //   表现就是"更名和卸载坏了"。这条场景把"每个按钮都绑上了没有 + 点了到底有没有
      //   把命令交给宿主"变成一次判定（以前只判"截图生成了没有"，全死也是 OK）。
      if (h === "btn-detail"){
              const p0 = state.packages.find(x => x.id === "first") ||
                   state.packages.find(x => x.layer === "user") || state.packages[0];
        const oldId = p0.id, newId = oldId + "9";
        select(oldId);
        await sleep(400);
        M.host = [];
        const dead = ["btn-run", "btn-vis", "btn-openui", "btn-rename", "btn-remove"]
          .filter(i => { const el = document.getElementById(i);
                         return !el || typeof el.onclick !== "function"; });
        // 更名：点真按钮 → 弹窗里填新 id → 确定
        const rn = document.getElementById("btn-rename");
        if (rn) rn.click();
        await sleep(250);
        const inp = document.getElementById("m-input");
        const mok = document.getElementById("m-ok");
        if (!inp || !mok){ document.title = "BTN-NO-MODAL"; return; }
        inp.value = newId; mok.click();
        await sleep(1600);
        const renamed = M.host.some(t => new RegExp("^--rename\\s+" + oldId + "\\s+" + newId + "$")
                                          .test(t.trim()));
        const gotNew = !!state.packages.find(x => x.id === newId);
        const lostOld = !state.packages.find(x => x.id === oldId);
        // 卸载：改名之后界面**又重画过一遍**，正好试试接线跟没跟上
        const rm = document.getElementById("btn-remove");
        if (rm) rm.click();
        await sleep(250);
        const mok2 = document.getElementById("m-ok");
        if (!mok2){ document.title = "BTN-NO-CONFIRM"; return; }
        mok2.click();
        await sleep(1200);
        const removed = M.host.some(t => new RegExp("^--remove\\s+" + newId + "\\s+-y$")
                                          .test(t.trim()));
        const errs = window.__errors || [];
        const ok = !dead.length && renamed && gotNew && lostOld && removed;
        document.querySelector("#meta").textContent = "DIAG " + (ok ? "OK" : "FAIL") +
          " 没绑上的按钮=" + (dead.join(",") || "无") + " 更名=" + (renamed ? 1 : 0) +
          " 卸载=" + (removed ? 1 : 0) + " 页内错=" + errs.length +
          " 宿主命令=" + JSON.stringify(M.host);
        document.title = ok ? "READY"
          : ("BTN-FAIL 死=" + (dead.join(",") || "无") + " 更名=" + (renamed ? 1 : 0) +
             " 卸载=" + (removed ? 1 : 0) + " 页内错=" + errs.length + " " +
             String(errs[0] || "").slice(0, 70));
        return;
      }
    } catch(e){
      // ★ 场景里出错要**看得见**：光设 document.title 是看不见的（截图不看标题栏），
      //   而工具只检查"图片有没有生成" ⇒ 出错也报 OK（踩过：`window.RUNS` 那次）。
      //   所以同时把错误写进顶栏，截图里一眼就能看到。
      document.title = "SCENARIO-ERR " + e.message;
      const _m = document.querySelector("#meta");
      if (_m) _m.textContent = "SCENARIO-ERR " + e.message;
      return;
    }
    await sleep(350);
    // ★ 页面里只要攒下过错误（`window.__errors`：内联那段捕获 + Vue 的 errorHandler 都往
    //   这里写），这个场景就不算过 —— 否则"某块静悄悄地死了"又会溜过去（`V-81`）。
    const _pe = window.__errors || [];
    // ★ 只有"还停在初始标题"时才盖成 READY —— 以前这行会把场景自己设的
    //   `...-FAIL` 一起盖掉，于是"截图里有 FAIL、工具还说 OK"（`V-63` 顺手修）。
    if (!/FAIL|ERR|STALE/.test(document.title)){
      if (_pe.length && !window.__errPathOK){
        document.title = "PAGE-ERR " + _pe.length + " " + String(_pe[0]).slice(0, 90);
        const _m2 = document.querySelector("#meta");
        if (_m2) _m2.textContent = "PAGE-ERR\n" + _pe.slice(0, 3).join("\n").slice(0, 400);
      } else {
        document.title = "READY";
      }
    }
  }
  window.addEventListener("load", () => {
    // `--early-ready`：**在页面脚本挂监听之前**就把 ready 发掉（`V-68` 那条竞态）。
    // 真机上 pywebview 完全可能这么干（尤其界面拆成多个外部脚本之后）。
    if (!M.earlyReady) window.dispatchEvent(new Event("pywebviewready"));
    setTimeout(scenario, 350);
  });
})();
</script>
"""


def dom_title(exe, url, size, dark):
    """把页面跑完后的 `<title>` 抠出来（`--dump-dom`）。

    ★ 为什么值得多花一次浏览器启动：每个场景判完都会把结论写进 `document.title`
      （`READY` / `xxx-FAIL`），但**光看截图是看不出标题栏的** —— 以前工具只检查
      "图片生成没有"，所以场景失败也会报 OK（踩过）。有了这个，`--check` 才能当真用。
    """
    cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
           "--no-first-run", "--no-default-browser-check",
           "--user-data-dir=" + str(PRE / "_profile_dom"), "--allow-file-access-from-files",
           "--window-size=" + size, "--virtual-time-budget=12000", "--dump-dom", url]
    if dark:
        cmd.insert(2, "--force-dark-mode")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120)
    except Exception:                                                 # noqa: BLE001
        return None
    m = re.search(r"<title>(.*?)</title>", r.stdout or "", re.S)
    return (m.group(1).strip() if m else None)


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    args = sys.argv[1:]
    exe = browser()
    if not exe:
        print("[错误] 找不到 Edge / Chrome，没法无头截图。")
        return 1
    if not (SRC / "index.html").is_file():
        print("[错误] 找不到 %s" % (SRC / "index.html"))
        return 1

    if PRE.exists():
        shutil.rmtree(PRE, ignore_errors=True)
    shutil.copytree(SRC, PRE)
    page = (PRE / "index.html").read_text(encoding="utf-8")
    anchor = "\n<script>\n/* ====="
    if page.count(anchor) != 1:
        print("[错误] 在 index.html 里找不到主脚本锚点（命中 %d 次）—— 界面结构改过了？"
              % page.count(anchor))
        return 1
    inject = MOCK_JS.replace("__MOCK__", json.dumps(mock_data(), ensure_ascii=False))
    # ★ 注入的这段假后端**先过一遍语法检查**。踩过：脚本里少一个引号 / 多一对引号，
    #   浏览器整段不执行 ⇒ `init()` 压根没跑 ⇒ 截出来是一张**白板**（页面还在、
    #   列表空着），而工具只会说"OK 18 KB"。这种坑不拦一下，每次都要从头猜。
    bad = js_syntax_problem(inject)
    if bad:
        print("[错误] 注入的假后端有 JS 语法错（浏览器会整段不执行 ⇒ 截图是白板）：\n  %s"
              % bad)
        return 1
    (PRE / "index.html").write_text(page.replace(anchor, inject + anchor),
                                    encoding="utf-8", newline="")

    SHOTS.mkdir(parents=True, exist_ok=True)
    url = (PRE / "index.html").as_uri()
    scenes = [a for a in args if not a.startswith("-")] or SCENES
    # `--size=1280,1200`：整页比一屏高时用得上（看看卡片下面是什么样）
    size = next((a.split("=", 1)[1] for a in args if a.startswith("--size=")), "1280,860")
    # `--dark`：让 `prefers-color-scheme: dark` 生效 —— 深色那套令牌是另一份值，
    # 不单独看一眼很容易只在浅色下"看着没事"。
    dark = "--dark" in args
    # `--check`：多跑一次 `--dump-dom`，把场景写进 `document.title` 的**结论**读出来 ——
    # "图片生成了"不等于"场景判过了"。
    check = "--check" in args
    print("浏览器 : %s" % exe)
    print("临时副本: %s" % PRE)
    print("窗口    : %s%s%s" % (size, "  （深色）" if dark else "",
                                "  （--check：读标题里的结论）" if check else ""))
    print("=" * 64)
    bad = 0
    for sc in scenes:
        out = SHOTS / (sc + ".png")
        prof = PRE / ("_profile_" + sc)
        shutil.rmtree(prof, ignore_errors=True)
        cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
               "--no-first-run", "--no-default-browser-check",
               "--user-data-dir=" + str(prof), "--allow-file-access-from-files",
               "--window-size=" + size, "--virtual-time-budget=12000",
               "--screenshot=" + str(out), url + "#" + sc]
        if dark:
            cmd.insert(2, "--force-dark-mode")
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=120)
        shutil.rmtree(prof, ignore_errors=True)
        ok = out.is_file() and out.stat().st_size > 2000
        verdict = ""
        if check:
            shutil.rmtree(PRE / "_profile_dom", ignore_errors=True)
            title = dom_title(exe, url + "#" + sc, size, dark)
            good = bool(title) and not re.search(r"FAIL|ERR|STALE", title or "")
            verdict = "  标题=%s" % (title or "（读不到）")
            ok = ok and good
        if not ok:
            bad += 1
        print("  %-16s %s  %s%s" % (sc, "OK" if ok else "FAIL",
                                   ("%.0f KB" % (out.stat().st_size / 1024)) if out.is_file()
                                   else (r.stderr or "")[-160:], verdict))
    print("=" * 64)
    print("截图：%s" % SHOTS)
    print("★ 用 read_image 看图。仓库没被改动；临时副本可以随时删。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
