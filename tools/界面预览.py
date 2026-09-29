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
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
          "drop-hot", "drop-run",
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

    payload = core_ui.build_payload()

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
    return {"payload": payload, "hist": hist, "fs": fs,
            # 拖文件那个场景要的样本：故意用**带空格**的文件名，顺便验引号
            "dropDir": str(ROOT),
            "dropFile": str(ROOT / "一个 带空格的图片.png")}


MOCK_JS = r"""
<script>
/* ==== 预览用的假 API（只在临时副本里；真界面里没有这一段）==== */
(function(){
  const M = __MOCK__;
  const state = M.payload, HIST = M.hist, FS = M.fs;
  const sleep = ms => new Promise(r => setTimeout(r, ms));
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
    run_poll: async () => ({ok: true, running: false, code: 0,
      out: "[执行] md5\n[目录] " + state.home + "\n\n900150983cd24fb0d6963f7d28e17f72\n"}),
    run_stop: async () => ({ok: true, msg: "(预览) 已停止"}),
    path_start: async () => ({ok: true, run_id: "r1", pid: 1,
      cmd: "moss /main.py", cwd: "D:\\python\\wwwroot\\ZeEn"}),
    run_host: async (text) => {
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
    quit: async () => ({ok: true}),
  }};
  async function scenario(){
    const h = (location.hash || "#pkg").slice(1);
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
          if (inp){ inp.value = want; document.querySelector("#m-ok").click(); }
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
        if (asked) document.querySelector("#m-ok").click();   // 点"确定" = 统一
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
      if (h === "drop-hot"){
        // 只看"拖上来时"长什么样（不松手）：接收区 + 运行按钮都要亮
        const usable = p => { try{ return !!FS[pkgRel(p)]; }catch(e){ return false; } };
        const p0 = state.packages.find(x => x.layer === "user" && usable(x)) ||
                   state.packages.find(usable) || null;
        if (!p0){ document.title = "NO-USABLE-PKG"; return; }
        select(p0.id);
        setTab("detail");
        await sleep(400);
        const e = new Event("dragenter", {bubbles: true});
        e.dataTransfer = {types: ["Files"], dropEffect: ""};
        document.querySelector("#pane-detail").dispatchEvent(e);
        await sleep(200);
        document.title = "READY";
      }
      // ★ 拖文件进来（`V-35`）：拖动时区域/按钮高亮；松手后＝以它为当前目录跑这个包。
      //   真实的 OS 拖动没法自动化（得人拿鼠标拖），所以这里拆成两半测：
      //   拖动那半用**合成事件**（带 types:["Files"]），松手那半直接调那个落地口
      //   `window.__mossDrop(...)`（真机上由宿主从 WebView2 取到真实路径后调用它）。
      if (h === "drop-run"){
        const usable = p => { try{ return !!FS[pkgRel(p)]; }catch(e){ return false; } };
        const p0 = state.packages.find(x => x.layer === "user" && usable(x)) ||
                   state.packages.find(usable) || null;
        if (!p0){ document.title = "NO-USABLE-PKG"; return; }
        select(p0.id);
        setTab("detail");
        await sleep(400);
        const pane = document.querySelector("#pane-detail");
        const zone = document.querySelector("#dropzone");
        const btn = document.querySelector("#btn-run");
        const dragEv = t => {
          const e = new Event(t, {bubbles: true});
          e.dataTransfer = {types: ["Files"], dropEffect: ""};
          return e;
        };
        // ① 拖上来（文件管理那一页开着时不该亮 —— 那不是"详情报"）
        setTab("file");
        await sleep(150);
        pane.dispatchEvent(dragEv("dragenter"));
        await sleep(80);
        const hotOnFileTab = zone.classList.contains("on");
        setTab("detail");
        await sleep(150);
        // ② 拖到详情报上：区域 + 按钮都得亮
        pane.dispatchEvent(dragEv("dragenter"));
        pane.dispatchEvent(dragEv("dragover"));
        await sleep(120);
        const zoneOn = zone.classList.contains("on");
        const paneHot = pane.classList.contains("hot");
        const btnHot = btn.classList.contains("hot");
        const subText = (document.querySelector("#dz-sub") || {}).textContent || "";
        // ③ 松手：宿主把真实路径送进来（这里直接调落地口）
        const dir = M.dropDir, file = M.dropFile;
        window.__mossDrop([{path: file, isDir: false, dir: dir}]);
        await sleep(700);
        const zoneOff = !zone.classList.contains("on");
        const paneOff = !pane.classList.contains("hot");
        const argsVal = (document.querySelector("#args") || {}).value || "";
        const run = (M.runs || [])[0] || {};
        const ok = !hotOnFileTab && zoneOn && paneHot && btnHot && zoneOff && paneOff &&
                   argsVal === '"' + file + '"' && run.cwd === dir && run.pid === p0.id;
        document.querySelector("#meta").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") + " 高亮=" + (zoneOn && paneHot && btnHot ? 1 : 0) +
          " 收尾=" + (zoneOff && paneOff ? 1 : 0) + " cwd=" + (run.cwd === dir ? 1 : 0);
        document.querySelector("#fm-body").innerHTML = "";    // 别把界面挡着
        document.querySelector("#dropzone").className = "";
        document.querySelector("#out").textContent =
          "DIAG " + (ok ? "OK" : "FAIL") +
          "\n拖动时高亮（详情报上）  = 区域 " + zoneOn + " / 面板 " + paneHot + " / 运行按钮 " + btnHot +
          "\n文件管理那一页开着时高亮吗 = " + hotOnFileTab + "   （不该亮）" +
          "\n浮层上写的话 = " + subText.slice(0, 90) +
          "\n松手后高亮收干净了吗 = 区域 " + zoneOff + " / 面板 " + paneOff +
          "\n参数框里放的是 = " + argsVal +
          "\n真的跑了吗 = pid=" + (run.pid || "-") + "  cwd=" + (run.cwd || "-") +
          "    （期望 pid=" + p0.id + "  cwd=" + dir + "）";
        if (ok) setTab("console");
        document.title = ok ? "READY" : "DROP-FAIL";
      }
    } catch(e){ document.title = "SCENARIO-ERR " + e.message; return; }
    await sleep(350);
    if (document.title !== "STALE-PATH") document.title = "READY";
  }
  window.addEventListener("load", () => {
    setTimeout(() => window.dispatchEvent(new Event("pywebviewready")), 10);
    setTimeout(scenario, 350);
  });
})();
</script>
"""


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

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
    scenes = [a for a in sys.argv[1:] if not a.startswith("-")] or SCENES
    # `--size=1280,1200`：整页比一屏高时用得上（看看卡片下面是什么样）
    size = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--size=")),
                "1280,860")
    # `--dark`：让 `prefers-color-scheme: dark` 生效 —— 深色那套令牌是另一份值，
    # 不单独看一眼很容易只在浅色下"看着没事"。
    dark = "--dark" in sys.argv[1:]
    print("浏览器 : %s" % exe)
    print("临时副本: %s" % PRE)
    print("窗口    : %s%s" % (size, "  （深色）" if dark else ""))
    print("=" * 64)
    bad = 0
    for sc in scenes:
        out = SHOTS / (sc + ".png")
        prof = PRE / ("_profile_" + sc)
        shutil.rmtree(prof, ignore_errors=True)
        cmd = [exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
               "--no-first-run", "--no-default-browser-check",
               "--user-data-dir=" + str(prof), "--allow-file-access-from-files",
               "--window-size=" + size, "--virtual-time-budget=6000",
               "--screenshot=" + str(out), url + "#" + sc]
        if dark:
            cmd.insert(2, "--force-dark-mode")
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=120)
        shutil.rmtree(prof, ignore_errors=True)
        ok = out.is_file() and out.stat().st_size > 2000
        if not ok:
            bad += 1
        print("  %-16s %s  %s" % (sc, "OK" if ok else "FAIL",
                                  ("%.0f KB" % (out.stat().st_size / 1024)) if out.is_file()
                                  else (r.stderr or "")[-160:]))
    print("=" * 64)
    print("截图：%s" % SHOTS)
    print("★ 用 read_image 看图。仓库没被改动；临时副本可以随时删。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
