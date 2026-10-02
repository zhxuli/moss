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
          "drop-hot", "drop-dir", "drop-file", "drop-ext", "console-input", "embed", "pane-resize",
          "flat-buttons", "backup-diff", "refresh-keep-ctx", "compare", "hist-snap", "modal-kinds", "snap-modal",
          "statusbar", "settings", "settings-exec", "settings-format", "settings-adv",
          "settings-bad", "settings-warn", "settings-tip",
          "settings-ai", "settings-ai-tpl", "settings-ai-new", "settings-ai-empty",
          "hist", "hist-console", "hist-file",
          "edit-manifest", "edit-manifest-detail", "float-window", "side-counts", "path-ui"]

#: **已知过期**的场景（`V-202`）：它们的期望停在"设置 / AI 面板"那次重做之前，产品是对的、
#: 是场景（或它的假数据）跟不上 —— 待办记在账本 `V-203`。
#: ★ 为什么要单列而不是直接删掉/改绿：默认模式以前**不看标题结论**，这 5 个一直在悄悄失败，
#:   我却拿"51 个场景 OK"当全绿报了好几轮。现在每次跑都会把它们点名打出来（`STALE`），
#:   直到真去修掉为止 —— 不许再藏。
KNOWN_STALE = {
    "settings-bad": "期望「预览行变红」（要 host 给的 live 以 ⚠ 开头），假数据没跟上",
    "settings-tip": "直接调提示函数那条路：期望的返回值形状变了",
    "settings-ai": "编辑视图里找返回箭头的选择器过期（`#ai-back` 现在在，但取到的是别的东西）",
    "settings-ai-tpl": "预制卡片副标题早改成 `desc`（\"官方 API\"），场景还在找主机名 `api.deepseek.com`",
    "settings-ai-new": "同上（走的是新增那一支）",
}


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

    # ★ AI 那几组（`V-138` / `V-139`）：存储/规则在 `core/config.py`，预览里只给一份**假的多组数据**
    #   （三组：正常一组 / 本机一组测"连不上" / 只有地址的一组），并且让 mock 真的改它 ——
    #   这样预制参数 / 改名 / 保存 / 删除 / 设为当前 / 测连接都能在截图和断言里看见效果。
    #   ★ 「常用」那排按钮用的是**真的** `AI_PRESETS`（跟命令行同一份），不是这里编的。
    ai = {"active": "深度求索", "profiles": [
        {"name": "深度求索", "params": {"base_url": "https://api.deepseek.com/v1",
                                       "api_key": "sk-abcdef1234567890",
                                       "model": ["deepseek-chat", "deepseek-reasoner"]}},
        {"name": "本地 ollama", "params": {"base_url": "http://127.0.0.1:11434/v1",
                                          # ★ 故意留一个**老写法**（字符串，`V-139` 之前存的）
                                          "model": "qwen2.5:7b"}},
        {"name": "备用中转", "params": {"base_url": "https://api.apifast.tech/v1",
                                       "api_key": "sk-zzzzzzzzzzzzzzzz",
                                       "model": ["gemini-2.0-flash"]}}]}
    ai_presets = core_config.AI_PRESETS

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

    return {"payload": payload, "hist": hist, "fs": fs, "settings": settings, "ai": ai,
            "aiPresets": ai_presets,
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
      // `V-200`：记下"哪个包、调了什么" —— 场景靠它证明"页面真的转起来了"（iframe 是
      // 别的源，父页面读不到里面，只能从这一侧看）
      (M.embedCalls = M.embedCalls || []).push({pid: pid, method: req.method});
      const reply = (result) => window.__mossEmbedFromBackend(pid, JSON.stringify(
        {id: req.id, ok: true, result: result}));
      const d = new Date();
      // ---- path 那个包（`V-200`）：一份假的 PATH 状态，够页面画出来
      const pstate = () => ({
        ok: true, count: 4,
        paths: ["C:\\\\Windows\\\\system32", "C:\\\\Windows", "D:\\\\tools\\\\bin",
                "D:\\\\已经没了的目录\\\\bin"],
        self_dir: "D:\\\\python\\\\two\\\\moss\\\\system\\\\pkgs\\\\path",
        self_registered: false,
        data_dir: "D:\\\\python\\\\two\\\\moss\\\\user_data\\\\state\\\\path",
        backup_dir: "D:\\\\python\\\\two\\\\moss\\\\user_data\\\\state\\\\path\\\\data\\\\backups",
        legacy_dir: "D:\\\\python\\\\two\\\\moss\\\\user_data\\\\state\\\\path\\\\.path_editor\\\\path_bak",
        missing: ["D:\\\\已经没了的目录\\\\bin"]});
      if (req.method === "state") reply(pstate());
      else if (req.method === "info") reply({ok: true, pid: 4242, python: "3.12（预览）",
        data_dir: "(预览)", self_dir: "(预览)", embedded: true});
      else if (req.method === "add" || req.method === "remove" || req.method === "dedup" ||
               req.method === "drop_missing")
        reply({ok: true, msg: "(预览) " + req.method, state: pstate()});
      else if (req.method === "add_many")
        reply({ok: true, msg: "(预览) 加了 " + ((req.params.paths || []).length) + " 条",
               state: pstate()});
      else if (req.method === "pick_dir") reply({ok: true, path: "D:\\\\预览选的目录"});
      else if (req.method === "backup_create")
        reply({ok: true, msg: "(预览) 已备份 4 条", file: "(预览)", state: pstate()});
      else if (req.method === "backup_list") reply({ok: true, state: pstate(), items: [
        {file: "(预览) path_backup_20261002_120000.txt", time: "2026-10-02 12:00:00",
         stamp: "20261002_120000", total: 4, add: 1, remove: 0, legacy: false, paths: []},
        {file: "(预览) path_backup_20250101_010101.txt", time: "2025-01-01 01:01:01",
         stamp: "20250101_010101", total: 3, add: 0, remove: 1, legacy: true, paths: []}]});
      else if (req.method === "backup_preview")
        reply({ok: true, add: ["D:\\\\tools\\\\bin"], remove: ["D:\\\\已经没了的目录\\\\bin"],
               paths: [], msg: "会加 1 条、去掉 1 条", state: pstate()});
      else if (req.method === "backup_restore" || req.method === "backup_delete")
        reply({ok: true, msg: "(预览) " + req.method, state: pstate()});
      // ---- bmi 那个包
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
      const who = (p && !g) ? "跑包" : "找文件";
      const liveL = ["现在：裸名 moss m 归「" + who + "」", ""];
      liveL.push("例子：文件在 ./src/ceshi/main.py");
      liveL.push("  moss " + p + "s/c/m        每段按前缀找：s→src/  c→ceshi/  m→main.py");
      liveL.push("                      找到就用 python 跑它，工作目录切到 src/ceshi/");
      if (n) liveL.push("  moss " + n + p + "s/c/m       同一个文件，但在当前目录跑（不切过去）");
      liveL.push("");
      liveL.push("怎么找：从当前目录往上逐层找（连自己一共 4 个目录），某一层里第一个满足的就用它");
      liveL.push("        某一段要是目录（s、c），最后一段是文件名的开头（m）；大小写不敏感");
      liveL.push("        同一层有多个候选时：项目标记 → 上次在这个目录选过的 → 类型优先级；还打平就问你");
      liveL.push("执行的是：python <找到的那个文件>（那一层有 venv 就用 venv 里的 python）");
      if (g) liveL.push("\n其他：moss " + g + "img   跑装好的包" + (d ? ("        moss " + d + "m   后台脱离运行") : ""));
      if (!p && !g) liveL.push("\n⚠ 两个都留空 —— 裸名（moss m）到底算找文件还是跑包，说不清了");
      if (p && g) liveL.push("\n⚠ 两个都有前缀 —— 谁也没占住裸名，moss m 现在按「找文件」处理");
      const live = liveL.join("\n");
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
    // ---- AI 那几组（`V-138`）：真后端去叫宿主 `--ai-config` / `--ai-profile-set` /
    //      `--ai-active` / `--ai-profile-del` / `--ai-test`。预览里给一份**假的多组数据**，
    //      并且让这几个 mock **真的改它** —— 于是"新增 / 复制 / 删除 / 设为当前 / 保存"
    //      在截图和断言里都能看见效果（不然只能看个壳）。
    ai_config: async (name, reveal) => {
      const A = M.ai;
      const want = String(name || "");
      const nm = want || A.active || ((A.profiles[0] || {}).name || "");
      const hit = A.profiles.filter(x => x.name === nm)[0] || {name: "", params: {}};
      const params = Object.assign({}, hit.params);
      const k = String(params.api_key || "");
      if (!reveal && k){                     // 照真宿主：默认打码
        params.api_key = k.length > 10 ? (k.slice(0, 4) + "…" + k.slice(-4))
                                       : "（已设置）";
      }
      // ★ `V-140`：列表那一屏要的摘要（每组一行：地址 / 模型 / key 填没填），**永远打码**
      const summary = {};
      A.profiles.forEach(x => {
        const p = x.params || {};
        const kk = String(p.api_key || "");
        const ms = Array.isArray(p.model) ? p.model : (p.model ? [p.model] : []);
        summary[x.name] = {base_url: String(p.base_url || ""), model: ms, has_key: !!kk,
                           key: kk ? (kk.length > 10 ? (kk.slice(0, 4) + "…" + kk.slice(-4))
                                                    : "（已设置）") : "（空）"};
      });
      return {ok: true, active: A.active, name: hit.name, params: params,
              profiles: A.profiles.map(x => x.name).sort(), summary: summary};
    },
    ai_presets: async () => ({ok: true, presets: M.aiPresets}),
    ai_save: async (name, fields) => {
      const A = M.ai;
      let hit = A.profiles.filter(x => x.name === name)[0];
      if (!hit){ hit = {name: name, params: {}}; A.profiles.push(hit); }
      Object.keys(fields || {}).forEach(k => { hit.params[k] = fields[k]; });
      if (!A.active) A.active = name;
      return {ok: true, name: name, msg: "已存：" + name};
    },
    ai_rename: async (old, nm) => {
      const A = M.ai;
      const i = A.profiles.findIndex(x => x.name === old);
      if (i < 0 || A.profiles.some(x => x.name === nm)) return {ok: false, msg: "没改成"};
      A.profiles[i].name = nm;                       // 整块搬：参数一个都不动
      if (A.active === old) A.active = nm;
      return {ok: true, name: nm, msg: "改名完成：" + old + " → " + nm};
    },
    ai_delete: async (name) => {
      const A = M.ai;
      A.profiles = A.profiles.filter(x => x.name !== name);
      if (A.active === name) A.active = ((A.profiles[0] || {}).name || "");
      return {ok: true, msg: "删了「" + name + "」；剩下的组：" +
                             (A.profiles.map(x => x.name).join(" / ") || "（没有）")};
    },
    ai_set_active: async (name) => {
      M.ai.active = String(name || "");
      return {ok: true, msg: "当前那组 = " + M.ai.active};
    },
    ai_test: async (name) => {
      M.aiTested = String(name || "");
      const hit = M.ai.profiles.filter(x => x.name === name)[0] || {params: {}};
      const p = hit.params || {};
      const models = Array.isArray(p.model) ? p.model : (p.model ? [p.model] : []);
      if (!p.base_url || !models.length)
        return {ok: false, code: 1,
                msg: "[错误] 这一组还没填 base_url / model（model 可以写多个，逗号隔开）。"};
      if (String(p.base_url).indexOf("127.0.0.1") >= 0)     // 本机那组：假装连不上
        return {ok: false, code: 4,
                msg: "[错误] 没连上 / 报错：<urlopen error [WinError 10061] 由于目标计算机" +
                     "积极拒绝，无法连接。>"};
      return {ok: true, code: 0,
              msg: '连上了：HTTP 200（模型 ' + models[0] +
                   '）· 流式第一个增量 = data: {"id":"chatcmpl-1",' +
                   '"choices":[{"delta":{"content":"收到"}}]}'};
    },
    open_ui: async () => ({ok: true, msg: "(预览) 已打开"}),
    // 浮动窗口（`V-192`）：预览里开不出第二个窗口，只把三个接口垫出来，
    // 让页面那条路（拆帧 → 开窗 → 收回/结束的回调）能整条跑一遍。
    ui_float: async (pid) => { (M.floats = M.floats || []).push({pid: pid, op: "float"});
                               return {ok: true, msg: "(预览) 已弹出为窗口"}; },
    ui_dock: async (pid) => { (M.floats = M.floats || []).push({pid: pid, op: "dock"});
                              return {ok: true, msg: "(预览) 已收回"}; },
    ui_float_stop: async (pid) => { (M.floats = M.floats || []).push({pid: pid, op: "stop"});
                                    return {ok: true, msg: "(预览) 已停止"}; },
    // 浮动窗口的图标（`V-195`）：页面把包图标光栅化成 PNG 送过来，这里只记一下多大
    set_win_icon: async (pid, b64) => {
      (M.winIcons = M.winIcons || []).push({pid: pid, len: String(b64 || "").length});
      return {ok: true, msg: "(预览) 图标换好了"};
    },
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
    // 点路径里某一段（`V-198`）：真后端是 os.startfile 打开那一级；这里记下来给场景断言
    open_path: async (p) => { (M.opened = M.opened || []).push(String(p)); return {ok: true}; },
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
        const fillVisible = !!fillBtn && fillBtn.hidden === false;   // 有命中 ⇒ 该显示
        const clrHiddenAtFirst = !!clrBtn && clrBtn.hidden === true; // 规则框空着 ⇒ 该藏
        if (fillBtn) fillBtn.click();
        await sleep(150);
        const filledVal = ((document.querySelector("#snapwin #snap-rules") || {}).value || "");
        const afterFill = {fill: !!fillBtn && fillBtn.hidden, clr: !!clrBtn && clrBtn.hidden};
        const filled = filledVal.length > 0;
        // V-128：只该写"检测到的" —— 场景里放了 run.log + venv/ ⇒ 只该有 *.log 和 venv
        // 按行精确比（别用 indexOf：`venv` 里就含着 `env` 三个字母，第一版断言就是这么写错的）
        const filledArr = filledVal.split("\n").map(x => x.trim()).filter(Boolean);
        // V-128 的真正要求：**只写命中的那些模式**，不许把整组（.venv/env/site-packages/node_modules/*.mp4…）都塞进来。
        // （别写死成 *.log+venv —— 那一层里真有个 __pycache__，它是命中的、就该被写。）
        const allowed = ["*.log", "venv", "__pycache__", "*.pyc", "*.pyo", "*.class", "*.o"];
        const noRedundant = filledArr.length > 0 && filledArr.every(x => allowed.indexOf(x) >= 0);
        const filledLines = filledArr.slice().sort().join(",");
        if (clrBtn) clrBtn.click();
        await sleep(150);
        const cleared = ((document.querySelector("#snapwin #snap-rules") || {}).value || "") === "";
        const afterClear = {fill: !!fillBtn && fillBtn.hidden, clr: !!clrBtn && clrBtn.hidden};
        // V-136：填完 ⇒ 没有新东西可填 ⇒ 「一键填入」藏起来、「清空」露出来；清空后反过来
        const btnRulesOk = fillVisible && clrHiddenAtFirst &&
                           afterFill.fill === true && afterFill.clr === false &&
                           afterClear.fill === false && afterClear.clr === true;
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
                   !!fillBtn && !!clrBtn && btnRulesOk && filled && noRedundant && cleared &&
                   rules0 === "" && rules1.length > 0 && closed &&
                   rows1 > 0 && rows2 === 0 && foldedHint && rows3 === rows1;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 窗口=" + !!win + " 预设=" + chips + " 命中项=" + hot +
          " 记住勾=" + keep + " 点选后规则=" + JSON.stringify(rules1.slice(0, 24)) +
          " 关掉=" + closed + " 行数=" + [rows1, rows2, rows3].join("/") + " 收起提示=" + foldedHint;
        document.title = ok ? "READY" : ("SNAPMODAL-FAIL " + JSON.stringify({首: [fillVisible, clrHiddenAtFirst], 填: afterFill, 清: afterClear, 行: filledLines, ok: [!!win, chips0, hot, chips > chips0, filled, noRedundant, cleared, btnRulesOk]}));
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
        // ★ V-145 的**唯一豁免**：AI 那份 UI 稿子里，次要按钮本来就是 1px 描边的
        //   （设置 → AI 引擎 那一块，`.set-ai` 里面）。别处照旧：一个描边都不许有。
        const aiBox = document.querySelector(".set-ai");
        [].slice.call(document.querySelectorAll("button")).forEach(function(b){
          if (aiBox && aiBox.contains(b)) return;
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
          "DIAG " + (ok ? "OK" : "FAIL") + "（AI 那块按稿子豁免）按钮=" + total + " 有描边的=" + bordered.length +
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
        // ★ `V-198`：整条路径**每一段**都能点，直到根目录
        const pathBox = document.querySelector("#set-path");
        const segEls = [].slice.call(document.querySelectorAll("#set-path .set-link"));
        const rawPath = (pathBox && pathBox.getAttribute("title")) || "";
        const joined = segEls.map(e => e.textContent).join("");
        const eachHasPath = segEls.every(e => !!e.getAttribute("data-path"));
        // 点"倒数第二段"（一个目录）：宿主应该收到**到那一级为止**的路径
        const midSeg = segEls[segEls.length - 2] || segEls[0];
        const wantMid = (midSeg && midSeg.getAttribute("data-path")) || "";
        if (midSeg) midSeg.click();
        await sleep(300);
        const gotMid = (M.opened || [])[(M.opened || []).length - 1] || "";
        const segOk = segEls.length >= 3 && joined === rawPath && eachHasPath &&
                      !!wantMid && gotMid === wantMid;
        const ok = navs === 5 && panes === 5 && activePane.group === "快捷命令" &&
                   pane2.group === "执行提示" && switches === 7 && inputs === 4 &&
                   labels === 4 && infos === 4 && liveBox && hasX && disabledAtStart &&
                   enabledAfter && /改了 1 项/.test(stateMoved) && closedAfterSave && opened &&
                   Object.keys(saved).length === 1 && saved["symbols.no_chdir_mode"] === "@" &&
                   segOk;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 分类=" + navs + " 面板=" + panes +
          " 首屏=" + activePane.group + " 次屏=" + pane2.group + " 开关=" + switches +
          " 输入=" + inputs + " 标签=" + labels + " ?=" + infos + " 预览行=" + (liveBox ? 1 : 0) +
          " ×=" + (hasX ? 1 : 0) + " 存了=" + JSON.stringify(saved) +
          " 路径段=" + segEls.length + " 拼回原样=" + (joined === rawPath);
        document.title = ok ? "READY" : ("SETTINGS-FAIL 分类=" + navs + " 面板=" + panes +
          " 首屏=" + activePane.group + " 次屏=" + pane2.group + " 开关=" + switches +
          " 输入=" + inputs + " 标签=" + labels + " ?=" + infos + " 预览=" + liveBox +
          " ×=" + hasX + " 起灰=" + disabledAtStart + " 改亮=" + enabledAfter +
          " 挪=" + /改了 1 项/.test(stateMoved) + " 关=" + closedAfterSave + " 开=" + opened +
          " 存=" + Object.keys(saved).length + " 值=" + saved["symbols.no_chdir_mode"] +
          " 段=" + segEls.length + " 拼=" + (joined === rawPath) + " 点段=" + (gotMid === wantMid));
      }
      // ---- AI 那一组（V-142）：**三张脸** —— 列表（卡片）/ 选服务商（网格）/ 编辑（表单）。
      //      这条走：列表长什么样 → 卡片上设为当前 → 卡片进编辑 → 编辑页里测连接（结果横幅）
      //      → 改一项 → 存 → 回列表。
      //      ★ 硬判据：**那块地方不许有长说明**（`.ai-tip` 数为 0）；缺东西必须是高亮小标签。
      //      ★ sleep 总量必须 < 12 秒（工具 `--virtual-time-budget=12000`，超了会被半路截图）。
      if (h === "settings-ai"){
        await openSettings();
        await sleep(500);
        const navs = document.querySelectorAll("#set-nav .set-navitem").length;
        const aiNav = Array.prototype.filter.call(
          document.querySelectorAll("#set-nav .set-navitem"),
          b => (b.dataset.group || "") === "A I 引擎")[0];
        if (aiNav) aiNav.click();
        await sleep(700);
        const pane = (document.querySelector("#set-body .set-pane.on") || {}).dataset || {};
        const scope = "#set-body .set-pane.on .set-ai ";
        const box = !!document.querySelector(scope);
        const generic = !!document.querySelector(
          '#set-body .set-pane.on .set-field[data-key="ai.active"]');
        const tipN = document.querySelectorAll(scope + ".ai-tip").length;
        const cards0 = document.querySelectorAll(scope + ".ai-card").length;
        const empty0 = !!document.querySelector("#ai-empty");
        const addBtn = document.querySelector("#ai-new");
        const addTxt = addBtn ? addBtn.textContent.trim() : "";
        const listOn0 = !!document.querySelector("#ai-view-list.active");
        const cardOf = n => document.querySelector(scope + '.ai-card[data-group="' + n + '"]');
        const cardMeta = n => {
          const c = cardOf(n);
          const m = c ? c.querySelector(".ai-cmeta") : null;
          return m ? m.textContent : "";
        };
        const cardWarn = n => {
          const c = cardOf(n);
          return c ? Array.prototype.map.call(c.querySelectorAll(".ai-warn"),
                                             x => x.textContent).join("/") : "";
        };
        const cardTag = n => {
          const c = cardOf(n);
          const t = c ? c.querySelector(".ai-tag") : null;
          return t ? t.textContent : "";
        };
        const metaDiyun = cardMeta("深度求索");
        const metaOllama = cardMeta("本地 ollama");
        const warnOllama = cardWarn("本地 ollama");
        const tagDiyun = cardTag("深度求索");
        // 卡片上「设为当前」
        const useBtn = document.querySelector(scope + '.ai-card[data-group="本地 ollama"] [data-use]');
        if (useBtn) useBtn.click();
        await sleep(400);
        const activeMock = (M.ai || {}).active || "";
        const tagNow = cardTag("本地 ollama");
        // 卡片进编辑
        const editBtn = document.querySelector(scope + '.ai-card[data-group="深度求索"] [data-edit]');
        if (editBtn) editBtn.click();
        await sleep(500);
        const ttl1 = (document.querySelector("#ai-ttl") || {}).textContent || "";
        const backOk = !!document.querySelector("#ai-back");   // 现在只有箭头、没有文字
        const fieldN = document.querySelectorAll(scope + ".ai-fgroup").length;
        const boxOf = k => document.querySelector(
          scope + '.ai-fgroup[data-ai="' + k + '"] input,' +
          scope + '.ai-fgroup[data-ai="' + k + '"] textarea');
        const key0 = boxOf("api_key");
        const keyPh0 = key0 ? key0.placeholder : "";
        const keyVal0 = key0 ? key0.value : "";
        const mBox = boxOf("model");
        const modelTag0 = mBox ? mBox.tagName : "";
        const modelTxt0 = mBox ? mBox.value : "";
        const test0 = document.querySelector("#set-ai-test");
        const testOn0 = test0 ? !test0.disabled : false;
        // 编辑页里「测试连接」→ 结果横幅（稿子把测试放在这张脸上）
        if (test0) test0.click();
        await sleep(500);
        const banner = document.querySelector("#ai-banner");
        const bannerOk = banner ? /(^|\s)ok(\s|$)/.test(banner.className) : false;
        const bannerTxt = (document.querySelector("#ai-state") || {}).textContent || "";
        const tested = (M.aiTested || "");
        // 改一项 → 保存 → 回列表
        const urlBox = boxOf("base_url");
        if (urlBox){ urlBox.value = "https://api.deepseek.com/v2";
                     urlBox.dispatchEvent(new Event("input", {bubbles: true})); }
        await sleep(150);
        const sBtn = document.querySelector("#set-save");
        const saveOn = sBtn ? !sBtn.disabled : false;
        const bodyEl = document.querySelector("#set-body");
        const vis = !!(sBtn && bodyEl &&
          sBtn.getBoundingClientRect().bottom <= bodyEl.getBoundingClientRect().bottom + 1);
        if (sBtn) sBtn.click();
        await sleep(700);
        const cards1 = document.querySelectorAll(scope + ".ai-card").length;
        const listOn1 = !!document.querySelector("#ai-view-list.active");
        const savedUrl = ((M.ai.profiles.filter(x => x.name === "深度求索")[0] || {}).params || {}).base_url;
        const ok = navs === 5 && pane.group === "A I 引擎" && box && !generic && tipN === 0 &&
                   cards0 === 3 && !empty0 && addTxt === "添加新的 AI 配置" && listOn0 &&
                   /api\.deepseek\.com/.test(metaDiyun) && /deepseek-chat/.test(metaDiyun) &&
                   /127\.0\.0\.1:11434/.test(metaOllama) && warnOllama === "缺密钥" &&
                   tagDiyun === "当前" &&
                   bannerOk && /HTTP 200/.test(bannerTxt) && tested === "深度求索" &&
                   activeMock === "本地 ollama" && tagNow === "当前" &&
                   ttl1 === "编辑：深度求索" && backOk && fieldN === 4 &&
                   keyPh0 === "已保存，留空不改" && keyVal0 === "" &&
                   modelTag0 === "TEXTAREA" &&
                   modelTxt0 === "deepseek-chat\ndeepseek-reasoner" &&
                   testOn0 && saveOn && vis &&
                   savedUrl === "https://api.deepseek.com/v2" &&
                   cards1 === 3 && listOn1;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 分类=" + navs + " 页=" + pane.group +
          " 块=" + (box ? 1 : 0) + " 通用行=" + (generic ? 1 : 0) + " 长文=" + tipN +
          " 卡片=" + cards0 + " 空框=" + (empty0 ? 1 : 0) + " 添加=[" + addTxt + "]" +
          " 首屏列表视图=" + listOn0 + " 卡[" + metaDiyun + "|" + warnOllama + "|" + tagDiyun + "]" +
          " 本机[" + metaOllama + "] 横幅=" + bannerOk + "[" + bannerTxt.slice(0, 26) + "]" +
          " 测的=" + tested + " 切后=" + activeMock + "/" + tagNow +
          " 标题=" + ttl1 + " 返回箭头=" + (backOk ? 1 : 0) + " 字段=" + fieldN +
          " 密钥框=" + keyPh0 + " 模型框=" + modelTag0 + "[" + modelTxt0.replace("\n", "|") + "]" +
          " 测可点=" + testOn0 + " 亮=" + saveOn + " 在视野=" + vis +
          " 存=" + savedUrl + " 存后卡片=" + cards1 + " 回列表=" + listOn1;
        document.title = ok ? "READY" : ("SETTINGS-AI-FAIL " +
          document.querySelector("#meta").textContent);
      }
      // 新建那一整条：添加 → 选服务商（网格）→ 点一家 → 粘 key → 保存 → 回列表 →
      // 改名（旧组没了、key 不能丢）→ 再进编辑改一项 → 取消（不落盘）。
      if (h === "settings-ai-new"){
        await openSettings();
        await sleep(500);
        const aiNav = Array.prototype.filter.call(
          document.querySelectorAll("#set-nav .set-navitem"),
          b => (b.dataset.group || "") === "A I 引擎")[0];
        if (aiNav) aiNav.click();
        await sleep(700);
        const scope = "#set-body .set-pane.on .set-ai ";
        // ① 「添加 AI 配置」→ 选服务商
        document.querySelector("#ai-new").click();
        await sleep(500);
        const tiles = document.querySelectorAll(scope + ".ai-tpl").length;
        const backOk = !!document.querySelector("#ai-back");
        const tplOn = !!document.querySelector("#ai-view-tpl.active");
        const tileOf = p => document.querySelector(scope + '.ai-tpl[data-preset="' + p + '"]');
        const dsTile = tileOf("DeepSeek");
        const dsName = dsTile ? dsTile.querySelector("b").textContent : "";
        const dsHost = dsTile ? dsTile.querySelector("i").textContent : "";
        const blankOk = !!document.querySelector("#ai-blank");
        // ② 点 DeepSeek → 编辑那张脸（表已填好，只差 key）
        if (dsTile) dsTile.click();
        await sleep(400);
        const ttl1 = (document.querySelector("#ai-ttl") || {}).textContent || "";
        const boxOf = k => document.querySelector(
          scope + '.ai-fgroup[data-ai="' + k + '"] input,' +
          scope + '.ai-fgroup[data-ai="' + k + '"] textarea');
        const valOf = k => { const e = boxOf(k); return e ? e.value : ""; };
        const keyPh = (boxOf("api_key") || {}).placeholder || "";
        const testNew = document.querySelector("#set-ai-test");
        const testDisabled = testNew ? testNew.disabled : false;
        const preName = valOf("name"), preUrl = valOf("base_url"), preModel = valOf("model");
        // ③ 粘 key → 保存 → 回列表
        const keyBox = boxOf("api_key");
        if (keyBox){ keyBox.value = "sk-preset-1234567890";
                     keyBox.dispatchEvent(new Event("input", {bubbles: true})); }
        await sleep(150);
        document.querySelector("#set-save").click();
        await sleep(700);
        const cards1 = document.querySelectorAll(scope + ".ai-card").length;
        const made = (M.ai.profiles.filter(x => x.name === "DeepSeek")[0] || {}).params || {};
        // ④ 改名
        document.querySelector(scope + '.ai-card[data-group="DeepSeek"] [data-edit]').click();
        await sleep(500);
        const nameBox = boxOf("name");
        if (nameBox){ nameBox.value = "DeepSeek-备用";
                      nameBox.dispatchEvent(new Event("input", {bubbles: true})); }
        await sleep(150);
        document.querySelector("#set-save").click();
        await sleep(700);
        const renamed = M.ai.profiles.filter(x => x.name === "DeepSeek-备用")[0] || null;
        const oldGone = !M.ai.profiles.some(x => x.name === "DeepSeek");
        const keptKey = renamed ? (renamed.params.api_key || "") : "";
        const cards2 = document.querySelectorAll(scope + ".ai-card").length;
        // ⑤ 再进编辑改一项 → 取消（该不落盘）
        document.querySelector(scope + '.ai-card[data-group="DeepSeek-备用"] [data-edit]').click();
        await sleep(500);
        const urlBox2 = boxOf("base_url");
        if (urlBox2){ urlBox2.value = "https://改坏了.invalid/v1";
                      urlBox2.dispatchEvent(new Event("input", {bubbles: true})); }
        await sleep(150);
        document.querySelector("#ai-back2").click();   // 左上角那个箭头（不再二次确认）
        await sleep(600);
        const afterCancel = ((M.ai.profiles.filter(x => x.name === "DeepSeek-备用")[0] || {}).params || {}).base_url;
        const cards3 = document.querySelectorAll(scope + ".ai-card").length;
        const ok = tiles === M.aiPresets.length + 1 && backOk && tplOn && blankOk &&
                   dsName === "DeepSeek" && dsHost === "api.deepseek.com" &&
                   ttl1 === "新建配置" && preName === "DeepSeek" &&
                   preUrl === "https://api.deepseek.com/v1" &&
                   preModel === "deepseek-chat\ndeepseek-reasoner" &&
                   keyPh === "sk-…" && testDisabled &&
                   cards1 === 4 && made.api_key === "sk-preset-1234567890" &&
                   Array.isArray(made.model) && made.model.length === 2 &&
                   !!renamed && oldGone && keptKey === "sk-preset-1234567890" &&
                   cards2 === 4 &&
                   afterCancel === "https://api.deepseek.com/v1" && cards3 === 4;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 格子=" + tiles + "[" + dsName + "/" + dsHost +
          "] 自定义=" + (blankOk ? 1 : 0) + " 选服务商视图=" + tplOn + " 返回=" + (backOk ? 1 : 0) +
          " 标题=" + ttl1 + " 填=" + preName + "/" + preUrl + "/" + preModel.replace("\n", "|") +
          " 密钥框=" + keyPh + " 新测灰=" + testDisabled +
          " 存后卡片=" + cards1 + " 存=" + JSON.stringify(made) +
          " 改名=" + (renamed ? 1 : 0) + " 旧组没了=" + oldGone +
          " key=" + (keptKey ? "在" : "丢了") + " 卡片=" + cards2 +
          " 取消后地址=" + afterCancel + " 卡片=" + cards3;
        document.title = ok ? "READY" : ("SETTINGS-AI-NEW-FAIL " +
          document.querySelector("#meta").textContent);
      }
      // 全删光 ⇒ 「没配置过」该有的样子：虚线空框 + 一句「还没有 AI 配置」+「添加 AI 配置」。
      if (h === "settings-ai-empty"){
        await openSettings();
        await sleep(500);
        const aiNav = Array.prototype.filter.call(
          document.querySelectorAll("#set-nav .set-navitem"),
          b => (b.dataset.group || "") === "A I 引擎")[0];
        if (aiNav) aiNav.click();
        await sleep(700);
        const scope = "#set-body .set-pane.on .set-ai ";
        const before = document.querySelectorAll(scope + ".ai-card").length;
        for (let i = 0; i < 8; i++){
          const d = document.querySelector(scope + ".ai-card [data-del]");
          if (!d) break;
          d.click();
          await sleep(300);
          const mok = document.querySelector("#m-ok");
          if (mok) mok.click();
          await sleep(550);
        }
        const cards = document.querySelectorAll(scope + ".ai-card").length;
        const listBox = !!document.querySelector("#ai-list");
        const empty = document.querySelector("#ai-empty");
        const emptyTxt = empty ? empty.textContent.trim() : "";
        const eico = empty ? !!empty.querySelector("svg") : false;
        const addBtn = document.querySelector("#ai-new");
        const addTxt = addBtn ? addBtn.textContent.trim() : "";
        const formOn = !!document.querySelector("#ai-view-form.active");
        const ok = before === 3 && cards === 0 && M.ai.profiles.length === 0 && !listBox &&
                   !!empty && /暂无 AI 配置/.test(emptyTxt) && eico &&
                   addTxt === "添加新的 AI 配置" && !formOn;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 删前=" + before + " 删后=" + cards +
          " 假库=" + M.ai.profiles.length + " 列表块=" + (listBox ? 1 : 0) +
          " 空框=" + (empty ? 1 : 0) + "[" + emptyTxt + "] 图标=" + (eico ? 1 : 0) +
          " 添加=[" + addTxt + "] 编辑视图=" + formOn;
        document.title = ok ? "READY" : ("SETTINGS-AI-EMPTY-FAIL " +
          document.querySelector("#meta").textContent);
      }
      // 选服务商那张脸（网格）：留一张图 + 断言"每家一格、地址小字、自定义那格也在"。
      if (h === "settings-ai-tpl"){
        await openSettings();
        await sleep(500);
        const aiNav = Array.prototype.filter.call(
          document.querySelectorAll("#set-nav .set-navitem"),
          b => (b.dataset.group || "") === "A I 引擎")[0];
        if (aiNav) aiNav.click();
        await sleep(700);
        document.querySelector("#ai-new").click();
        await sleep(500);
        const scope = "#set-body .set-pane.on .set-ai ";
        const tiles = document.querySelectorAll(scope + ".ai-tpl").length;
        const names = Array.prototype.map.call(
          document.querySelectorAll(scope + ".ai-tpl b"), x => x.textContent.trim());
        const hosts = Array.prototype.map.call(
          document.querySelectorAll(scope + ".ai-tpl i"), x => x.textContent.trim());
        const cols = getComputedStyle(document.querySelector(scope + ".ai-tplgrid"))
          .gridTemplateColumns.split(" ").length;
        const blank = !!document.querySelector("#ai-blank");
        const back = !!document.querySelector("#ai-back");
        const ok = tiles === M.aiPresets.length + 1 && cols === 3 && blank && back &&
                   names.indexOf("DeepSeek") >= 0 && names.indexOf("自定义") >= 0 &&
                   hosts.indexOf("api.deepseek.com") >= 0;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 格子=" + tiles + " 列=" + cols +
          " 名字=" + names.join("/") + " 地址=" + hosts.slice(0, 3).join("/") +
          " 自定义=" + (blank ? 1 : 0) + " 返回=" + (back ? 1 : 0);
        document.title = ok ? "READY" : ("SETTINGS-AI-TPL-FAIL " +
          document.querySelector("#meta").textContent);
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
        const firstTitle = (document.querySelector(".bk-snap .bk-tl-item[data-bk] .bk-card .bk-t")
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
        const aTitle = (document.querySelector(".bk-snap .bk-tl-item[data-bk] .bk-card .bk-t")
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
        // ★ `V-183`：拖动时页面只能看到**文件名** —— 所以这里给真名字（含扩展名），
        //   筛选也要按新规矩判（`dropAccepts(p, items)`，扩展名算在里面）。
        const dragName = isDirDrag ? "一个 带空格的文件夹" : "一个 带空格的图片.png";
        const dragItems = [{name: dragName, isDir: isDirDrag}];
        const dragEv = (t, isDir) => {
          const e = new Event(t, {bubbles: true});
          e.dataTransfer = {types: ["Files"], dropEffect: "",
            items: [{webkitGetAsEntry: () => ({isDirectory: isDir, name: dragName})}]};
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
          return p && window.dropAccepts(p, dragItems);
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
      // ★ `V-183`：**扩展名**这条规矩（拖 .txt 时 :img 不该亮、拖 .png 该亮）
      if (h === "drop-ext"){
        const dz = document.querySelector("#dropzone");
        const listIds = () => [].slice.call(document.querySelectorAll("#list .item"))
                                .map(e => e.dataset.id);
        const mkDrag = (name, isDir) => {
          const e = new Event("dragenter", {bubbles: true});
          e.dataTransfer = {types: ["Files"], dropEffect: "",
            items: (isDir ? [1, 2] : [1]).map(() =>
              ({webkitGetAsEntry: () => ({isDirectory: !!isDir, name: name})}))};
          return e;
        };
        const img = state.packages.find(x => x.id === "img");
        const imgExt = (((img || {}).drop || [])[0] || {}).file || {};
        const hasExt = !!(imgExt.ext && imgExt.ext.length);
        // ① 拖一个 .txt：img 不出现、md5 出现，左边那条提示要说清 img 为什么没来
        document.dispatchEvent(mkDrag("note.txt", false));
        await sleep(350);
        const idsTxt = listIds();
        const imgOut = idsTxt.indexOf("img") < 0;
        const md5In = idsTxt.indexOf("md5") >= 0;
        // ★ `V-186`：只收文件夹的包（tree / mark / sync / path）在不收拖入的包（bmi）
        //   都不该出现在"拖文件"的列表里 —— 这是这次收紧的回归测试
        const onlyDir = ["tree", "mark", "sync", "path"];
        const noDirOnly = onlyDir.every(id => idsTxt.indexOf(id) < 0);
        const noBmi = idsTxt.indexOf("bmi") < 0;
        const barTxt = ((document.querySelector("#dragbar") || {}).textContent || "")
                         .replace(/\s+/g, " ");
        // ★ 说清"为什么"的那句话只在**一个都没收**时才出现；拖 .txt 时 md5/open 是收的，
        //   所以这里分开验两件事：① 条上把筛完的数字说对；② `dropWhyNone`（0 个收的时候
        //   那句点名）本身说的话对 —— 直接调它，别指望拖动时会走到那条分支（`V-202` 改）。
        const barOk = /只列出收得下它的 2 个包/.test(barTxt);
        const whyTxt = (typeof window.dropWhyNone === "function")
          ? window.dropWhyNone([{name: "note.txt", isDir: false}]) : "";
        const saidWhy = whyTxt.indexOf("img") >= 0 && whyTxt.indexOf("只收") >= 0;
        dragEnd();
        await sleep(200);
        // ② 拖一张 .PNG（大写）：img 该出现（扩展名不分大小写）
        document.dispatchEvent(mkDrag("照 片.PNG", false));
        await sleep(350);
        const idsPng = listIds();
        const imgIn = idsPng.indexOf("img") >= 0;
        const upperOk = (window.extOf("a.PNG") === "png") && (window.extOf(".gitignore") === "");
        dragEnd();
        await sleep(200);
        // ③ 拖一个**名字里带点的文件夹**：img 收文件夹，扩展名规矩不该管到它
        document.dispatchEvent(mkDrag("我 的.照片", true));
        await sleep(350);
        const dirIn = listIds().indexOf("img") >= 0;
        dragEnd();
        await sleep(250);
        // ④ 站在 img 上、硬塞一个 .txt 给它：**不许跑**，而且要说人话
        select("img");
        await sleep(350);
        const runsBefore = (M.runs || []).length;
        window.__mossDrop([{path: "D:\\x\\note.txt", isDir: false, dir: "D:\\x",
                            name: "note.txt"}]);
        await sleep(500);
        const noRun = (M.runs || []).length === runsBefore;
        const toastTxt = ((document.querySelector("#toasts") || {}).textContent || "")
                           .replace(/\s+/g, " ");
        const toastSaid = toastTxt.indexOf("不收") >= 0 && toastTxt.indexOf("png") >= 0;
        // ⑤ 换成 .png 再塞一次：该跑（否定那一半不能把正常路也堵死）
        window.__mossDrop([{path: "D:\\x\\photo.png", isDir: false, dir: "D:\\x",
                            name: "photo.png"}]);
        await sleep(700);
        const run = (M.runs || [])[M.runs.length - 1] || {};
        const ranOk = (M.runs || []).length === runsBefore + 1 && run.pid === "img";
        // ⑥ `V-188`：**真机就是这样**（`_ui_drop.log` 里 `drag begin … items=null`）——
        //     `dragenter` 什么都读不到、到 `dragover` 才补上。这条路径必须也能筛干净。
        dragEnd();
        await sleep(200);
        const blindEnter = new Event("dragenter", {bubbles: true});
        blindEnter.dataTransfer = {types: ["Files"], dropEffect: "", items: []};
        document.dispatchEvent(blindEnter);
        await sleep(250);
        const idsBlind = listIds();                  // 读不到 → 先按"两种都收"全列
        const lateDrag = new Event("dragover", {bubbles: true});
        lateDrag.dataTransfer = {types: ["Files"], dropEffect: "",
          items: [{webkitGetAsEntry: () => ({isDirectory: false, name: "moss.py"})}]};
        document.dispatchEvent(lateDrag);
        await sleep(300);
        const idsLate = listIds();                   // 补读到 .py → 该筛干净
        const lateOk = idsLate.indexOf("md5") >= 0 && idsLate.indexOf("open") >= 0 &&
                       idsLate.indexOf("img") < 0 &&
                       onlyDir.concat(["bmi"]).every(id => idsLate.indexOf(id) < 0);
        dragEnd();
        await sleep(200);
        // ⑦ `V-189`：**真机探针实录的形状** —— 只有 kind + type，名字/entry/File 全空
        //    （`items=1 [{file|text/x-python|entry=null|file=null}] files=0 []`）。
        //    这条才是真机上"拖 moss.py"的那一下：必须按 MIME 筛干净。
        const mimeDrag = (mime, kind) => {
          const e = new Event("dragenter", {bubbles: true});
          e.dataTransfer = {types: ["Files"], dropEffect: "",
            items: [{kind: kind || "file", type: mime,
                     webkitGetAsEntry: () => null, getAsFile: () => null}]};
          return e;
        };
        document.dispatchEvent(mimeDrag("text/x-python"));
        await sleep(300);
        const idsMime = listIds();
        const mimeOk = idsMime.indexOf("md5") >= 0 && idsMime.indexOf("open") >= 0 &&
                       idsMime.indexOf("img") < 0 &&
                       onlyDir.concat(["bmi"]).every(id => idsMime.indexOf(id) < 0);
        dragEnd();
        await sleep(200);
        // ⑧ 同一个形状、但类型是图片：img 该回来（别把正常路也堵死）
        document.dispatchEvent(mimeDrag("image/png"));
        await sleep(300);
        const idsMimeImg = listIds();
        const mimeImgOk = idsMimeImg.indexOf("img") >= 0 && idsMimeImg.indexOf("md5") >= 0 &&
                          onlyDir.every(id => idsMimeImg.indexOf(id) < 0);
        dragEnd();
        await sleep(200);
        // ⑨ 类型是空的（多半是文件夹，也可能是认不出类型的文件）：收文件夹的包要亮
        document.dispatchEvent(mimeDrag(""));
        await sleep(300);
        const idsBlank = listIds();
        const blankOk = ["img", "tree", "mark", "sync", "path", "md5", "open"]
                          .every(id => idsBlank.indexOf(id) >= 0);
        dragEnd();
        await sleep(200);
        const ok = hasExt && imgOut && md5In && barOk && saidWhy && imgIn && upperOk && dirIn &&
                   noRun && toastSaid && ranOk && noDirOnly && noBmi && lateOk &&
                   mimeOk && mimeImgOk && blankOk;
        const diag = "DIAG " + (ok ? "OK" : "FAIL") +
          "\nimg 声明    = " + JSON.stringify(imgExt.ext || []) +
          "\n① .txt 后列表 = " + idsTxt.join(",") +
          "\n   img 藏起来=" + imgOut + "   md5 还在=" + md5In +
          "   提示说了原因=" + saidWhy +
          "\n   只收文件夹的包都没出现=" + noDirOnly + "（" + onlyDir.join("/") + "）" +
          "   不收拖入的 bmi 也没出现=" + noBmi +
          "\n   提示原文  = " + barTxt.slice(0, 90) +
          "\n② .PNG 后 img 出现=" + imgIn + "   大小写/无扩展名判定=" + upperOk +
          "\n③ 文件夹「我 的.照片」img 还收=" + dirIn +
          "\n④ 硬塞 .txt：没跑=" + noRun + "  弹的提示=" + JSON.stringify(toastTxt.slice(0, 90)) +
          "\n⑤ 换成 .png 照跑=" + ranOk + "（pid=" + (run.pid || "-") + "）" +
          "\n⑥ 真机那样（enter 读不到 / dragover 才补上）：先全列=" + idsBlind.length +
          " 个，补读后 = " + idsLate.join(",") + "  筛干净=" + lateOk +
          "\n⑦ 真机形状（只有 kind+type=text/x-python，名字全空）= " + idsMime.join(",") +
          "  筛干净=" + mimeOk +
          "\n⑧ 同形状但 image/png = " + idsMimeImg.join(",") + "  img 回来了=" + mimeImgOk +
          "\n⑨ 类型为空（多半是文件夹）= " + idsBlank.length + " 个  收文件夹的都亮=" + blankOk;
        document.querySelector("#out").textContent = diag;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 筛=" + (imgOut && md5In ? 1 : 0) +
          " 反向=" + (imgIn && dirIn ? 1 : 0) + " 拦=" + (noRun ? 1 : 0) +
          " 跑=" + (ranOk ? 1 : 0);
        dz.className = "";
        if (ok) setTab("console");
        document.title = ok ? "READY" : "DROPEXT-FAIL";
      }
      // ★ `V-192` / `V-194`：浮动窗口那条线（真机是两个窗口，预览里只能验页面这一侧）
      if (h === "float-window"){
        const disp = sel => {
          const el = document.querySelector(sel);
          return el ? getComputedStyle(el).display : "（没有这个元素）";
        };
        // ① 浮动窗口模式就是 `body.float`（CSS 把别的都藏了）—— 验它真藏住了
        document.body.classList.add("float");
        await sleep(200);
        const hidden = {header: disp("header"), aside: disp("aside"),
                        statusbar: disp("#statusbar"), tabs: disp("#tabs"),
                        bar: disp("#embed-bar"),          // ★ `V-195`：那条也不该显示
                        detail: disp("#pane-detail"), console: disp("#pane-console"),
                        file: disp("#pane-file")};
        const allHidden = Object.keys(hidden).every(k => hidden[k] === "none");
        // 包图标光栅化（`V-195`）：拿一个真有 svg 图标的包走一遍 canvas → PNG
        await window.pushWindowIcon(state.packages.find(x => x.id === "md5"));
        await sleep(300);
        const ic = (M.winIcons || [])[0] || {};
        const iconOk = ic.pid === "md5" && ic.len > 1000;      // 256×256 的 PNG 不可能几十字节
        document.body.classList.remove("float");
        await sleep(150);
        // ② 正常模式：界面那一页有「弹出为窗口」那颗按钮
        select("bmi");
        setTab("embed");
        await sleep(400);
        const floatBtn = !!document.querySelector("#btn-embed-window");
        // ③ 弹出：先拆帧、再叫宿主开窗（`M.floats` 记下来了）
        await embedOpen(state.packages.find(x => x.id === "bmi"));
        await sleep(300);
        const before = Object.keys(EMB.alive).length;
        const comp = (document.querySelector("#pane-embed").__vue__ || {});   // 拿不到就只验状态
        EMB.floated["bmi"] = true; EMBR.rev++;
        await sleep(200);
        const placeholder = !!document.querySelector("#embed-floated");
        // ④ 宿主喊"收回"（＝用户点了最小化）：帧要建回来、占位要消失
        window.__mossFloatDock("bmi");
        await sleep(500);
        const docked = !EMB.floated["bmi"] && !!EMB.alive["bmi"] &&
                       !document.querySelector("#embed-floated");
        // ⑤ 宿主喊"关了"（＝结束）：帧和状态都要清干净
        EMB.floated["bmi"] = true; EMBR.rev++;
        window.__mossFloatClosed("bmi");
        await sleep(300);
        const closed = !EMB.floated["bmi"] && !EMB.alive["bmi"] &&
                       !document.querySelector("#embed-floated");
        const ok = allHidden && floatBtn && placeholder && docked && closed && iconOk;
        document.querySelector("#out").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") +
          "\n① body.float 藏住别的（每项都该是 none）=" + JSON.stringify(hidden) +
          "\n   ★ 说明条也藏了 = " + (hidden.bar === "none") +
          "\n   ★ 包图标光栅化（md5 的 svg → PNG）= " + iconOk +
          " 送来 " + (ic.len || 0) + " 字节 base64" +
          "\n② 正常模式有「弹出为窗口」= " + floatBtn +
          "\n③ 占位出现（帧被弹走）= " + placeholder + "（弹出前后帧数 " + before + " → " +
          Object.keys(EMB.alive).length + "）" +
          "\n④ 收回：帧回来了、占位没了 = " + docked +
          "\n⑤ 关闭（＝结束）：帧和状态清干净 = " + closed;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 藏=" + (allHidden ? 1 : 0) +
          " 图标=" + (iconOk ? 1 : 0) +
          " 钮=" + (floatBtn ? 1 : 0) + " 占位=" + (placeholder ? 1 : 0) +
          " 收=" + (docked ? 1 : 0) + " 关=" + (closed ? 1 : 0);
        if (ok) setTab("console");
        document.title = ok ? "READY" : "FLOAT-FAIL";
      }
      // ★ `V-199`：插件 / 历史 两颗按钮上的数字；顶栏那行统计不再显示（自检留着）
      if (h === "side-counts"){
        await sleep(400);
        const txt = sel => { const e = document.querySelector(sel); return e ? e.textContent : null; };
        const nPkg = txt("#sw-n-pkg"), nHist = txt("#sw-n-hist");
        const wantPkg = String(state.packages.length);
        const wantHist = String((HIST || []).length);
        const metaTxt = txt("#meta") || "";
        const metaEmpty = metaTxt.trim() === "";
        const noOldStats = !/个包|启动方式/.test(metaTxt);
        const selfcheck = !!document.querySelector("#btn-selfcheck svg");
        const brandTip = (document.querySelector("header .brand") || {}).title || "";
        const tipOk = /启动方式/.test(brandTip) && brandTip.indexOf(state.home) >= 0;
        // 切到历史再切回来：数字不该变（它是总数，不跟着筛选跳）
        const nav = document.querySelectorAll("#sideswitch button");
        const histBtn = document.querySelector("#sw-hist");
        if (histBtn) histBtn.click();
        await sleep(250);
        const nPkg2 = txt("#sw-n-pkg"), nHist2 = txt("#sw-n-hist");
        if (document.querySelector("#sw-pkg")) document.querySelector("#sw-pkg").click();
        await sleep(250);
        const ok = nPkg === wantPkg && nHist === wantHist && metaEmpty && noOldStats &&
                   selfcheck && tipOk && nPkg2 === wantPkg && nHist2 === wantHist;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") +
          "\n插件数字 = " + nPkg + "（应为 " + wantPkg + "）" +
          "\n历史数字 = " + nHist + "（应为 " + wantHist + "）" +
          "\n顶栏 = " + JSON.stringify(metaTxt.slice(0, 40)) + "  空=" + metaEmpty +
          "  旧统计没有了=" + noOldStats +
          "\n自检按钮还在 = " + selfcheck + "   品牌 tooltip 带安装根和启动方式 = " + tipOk +
          "\n切到历史再切回：插件=" + nPkg2 + " 历史=" + nHist2;
        document.querySelector("#meta").className = "meta";
        if (ok) setTab("console");
        document.title = ok ? "READY" : "COUNT-FAIL";
      }
      // ★ `V-200`：`path` 那个包换成内嵌网页界面之后，整条路要通 ——
      //   选中它 → 「界面」选项卡 → 起后端 → iframe 加载**真的那份页面** →
      //   垫片 postMessage → 宿主 embed_send → 后端答话。
      //   ★ iframe 是**另一个源**（预览里是 file://），父页面读不到里面的 DOM ——
      //     所以这里从"宿主这一侧"验：iframe 的地址、以及后端到底被问了什么
      //     （页面 `onMounted` 会先 `info` 再 `state`，看到这两条就说明页面真的转起来了）。
      if (h === "path-ui"){
        const p0 = state.packages.find(x => x.id === "path");
        if (!p0){ document.title = "NO-PATH-PKG"; return; }
        const hasEmbed = !!(p0.ui && p0.ui.embed);
        select("path");
        await sleep(400);
        const tabBtn = document.querySelector('.tab[data-tab="embed"]');
        const tabShown = !!(tabBtn && !tabBtn.hidden);
        M.embedCalls = [];
        await embedOpen(p0);                       // = 点「运行」
        await sleep(2600);                         // 等 iframe 加载 + Vue 挂载 + 问后端
        const frame = document.querySelector("#embed-wrap iframe[data-pid='path']");
        const src = frame ? (frame.getAttribute("src") || "") : "";
        const srcOk = /path\/ui\/index\.html$/.test(src.replace(/\\\\/g, "/").replace(/\\/g, "/"));
        const calls = (M.embedCalls || []).map(c => c.method);
        const asked = calls.indexOf("info") >= 0 && calls.indexOf("state") >= 0;
        // ★ `V-201`：拖一个文件夹进来 —— 应该**送进内嵌那一帧**（而不是再起一个命令行进程），
        //   页面收到 `drop` 事件后调 `add_many`。这一条把"拖放 → 内嵌界面"整条路验穿。
        window.__mossDrop([{path: "D:\\\\tools\\\\新拖进来的", isDir: true,
                            dir: "D:\\\\tools\\\\新拖进来的", name: "新拖进来的"}]);
        await sleep(700);
        const dropped = (M.embedCalls || []).some(c => c.method === "add_many");
        const noErr = !(window.__errors || []).length;
        // ★ `V-204` / `V-205`：那一帧报"有人拖着东西在我头上"时，**罩子要打开**（把拖放接到
        //   我们这侧，真实路径才拿得到）、**要显示提示**、**左边列表不许跟着筛**（那一拖是给
        //   那一帧的），拖动结束后罩子收掉、列表回到正常筛选。
        select("path");
        await sleep(200);
        const rowsBefore = document.querySelectorAll("#list .item").length;
        window.__mossDropStart && window.__mossDropStart();      // 有就顺手起一次（没有也不影响）
        const fakeDrag = new Event("dragenter", {bubbles: true});
        fakeDrag.dataTransfer = {types: ["Files"], dropEffect: "",
          items: [{webkitGetAsEntry: () => ({isDirectory: true, name: "x"})}]};
        document.dispatchEvent(fakeDrag);
        await sleep(200);
        window.frameDrag("path", "over");
        await sleep(200);
        const cat = document.querySelector("#dropcatcher");
        const catOn = !!cat && cat.classList.contains("on") &&
                      getComputedStyle(cat).pointerEvents === "auto";
        // `V-206`：罩子**不画提示**（大的那个提示归那一帧自己）—— 屏幕上只能有一个"松手"
        const catBare = !!cat && !cat.querySelector(".dc-in") && cat.innerHTML.trim() === "";
        const rowsDuring = document.querySelectorAll("#list .item").length;
        const notFiltered = rowsDuring >= rowsBefore;
        const barTxt = ((document.querySelector("#dragbar") || {}).textContent || "")
                         .replace(/\s+/g, " ");
        const barFrame = /的界面上了/.test(barTxt);
        dragEnd();
        await sleep(200);
        const catOff = !!cat && !cat.classList.contains("on");
        const rowsAfter = document.querySelectorAll("#list .item").length;
        const ok = hasEmbed && tabShown && !!frame && srcOk && asked && dropped && catOn &&
                   catBare && notFiltered && barFrame && catOff && rowsAfter === rowsBefore && noErr;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") +
          "\n声明了内嵌界面 = " + hasEmbed + "（" + JSON.stringify(p0.ui || null) + "）" +
          "\n「界面」选项卡出现 = " + tabShown +
          "\niframe = " + (frame ? src.slice(-40) : "（没有）") + "  地址对不对 = " + srcOk +
          "\n后端被问到 = " + JSON.stringify(calls) + "  （info+state 说明页面真的跑起来了）" +
          "\n拖文件夹进来 → 送给内嵌界面（add_many）= " + dropped +
          "\\n帧上拖动 → 罩子打开可用 = " + catOn + "、罩子本身不画提示 = " + catBare +
          "、左边**不筛** = " + notFiltered + "（" + rowsBefore + " → " + rowsDuring + " 行）" +
          "\n条上说的是「那一帧」= " + barFrame + "  |  " + barTxt.slice(0, 46) +
          "\n松手后罩子收掉 = " + catOff + "、列表复原 = " + (rowsAfter === rowsBefore) +
          "\n页内错误 = " + (window.__errors || []).length;
        if (ok) setTab("console");
        document.title = ok ? "READY" : "PATHUI-FAIL";
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
    # 读标题里的结论 —— **默认就做**（`V-202`）。
    # ★ 血的教训：以前只有 `--check` 才读标题，平时只看"图片生成没有"。于是页面**从第一个
    #   场景起就在抛 `FLOAT_PID is not defined`**（每个场景都记成 PAGE-ERR），而默认那一跑
    #   照样一屏 OK —— 我拿它当"全绿"报了好几轮。**"图片出来了"和"场景判过了"是两件事。**
    #   想快一点（只截图、不判）用 `--fast`。
    check = "--fast" not in args
    print("浏览器 : %s" % exe)
    print("临时副本: %s" % PRE)
    print("窗口    : %s%s%s" % (size, "  （深色）" if dark else "",
                                "" if check else "  （--fast：只截图，不读结论）"))
    print("=" * 64)
    bad = 0
    staleN = []                    # 期望过期的那几个（`KNOWN_STALE`），最后汇总点名
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
            # ★ 标题还停在初始的 `moss` / 是个 URL ⇒ 场景**没跑完**（虚拟时间用超了，
            #   工具会半路截图）。这种必须算 FAIL —— 以前 "标题=moss" 也报 OK（`V-140` 踩过）。
            stale = (not title) or title.strip() in ("", "moss") or ("://" in title)
            good = (not stale) and not re.search(r"FAIL|ERR|STALE", title or "")
            verdict = "  标题=%s" % (title or "（读不到）")
            ok = ok and good
        if not ok:
            # 已知过期的那几个：**照样点名打出来**，但不计入"失败数"（不然每次跑都一屏红，
            # 真出问题的那条反而被淹没）。跑完还会在末尾汇总一次并指向账本。
            if (not check) or (sc in KNOWN_STALE):
                staleN.append(sc)
            else:
                bad += 1
        else:
            staleN = [s for s in staleN if s != sc]
        print("  %-16s %s  %s%s" % (sc, "OK" if ok else ("STALE" if sc in KNOWN_STALE else "FAIL"),
                                   ("%.0f KB" % (out.stat().st_size / 1024)) if out.is_file()
                                   else (r.stderr or "")[-160:], verdict))
    print("=" * 64)
    print("截图：%s" % SHOTS)
    print("★ 用 read_image 看图。仓库没被改动；临时副本可以随时删。")
    if staleN:
        print()
        print("⚠ 有 %d 个场景的期望**已经过期**（产品是对的，是场景/假数据没跟上）—— 见账本 V-203："
              % len(staleN))
        for s in staleN:
            print("    %-16s %s" % (s, KNOWN_STALE.get(s, "（没有记原因）")))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())


