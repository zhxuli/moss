/* moss 界面 · drop.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 拖文件进来（`V-35` ✅ / `V-38` ✅ / `V-39` ✅）
   一句话：**拖着文件或文件夹进窗口 ⇒ 只显示"收得下它"的包；划过谁就选中谁；到详情页的
   投放框上松手，按那个包自己声明的规矩跑起来。**

   ★ 路径**不是页面拿到的**：Chromium 不给页面 `File.path`（安全），页面只看得到文件名。
     真实路径由宿主（`system/ui/main.py` 的 `_on_files_dropped`）从 WebView2 的
     `AdditionalObjects` 里取出来，再调下面这个 `window.__mossDrop(items)` 交给我们。
     **拖动时**页面只知道"拖的是文件还是文件夹"（够用来筛列表）；**松手后**才知道真实路径。
   ★ 一个包"收什么、收到哪儿"全看它 `pkg.json` 里的 `drop` 声明（`V-38`）：
        "drop": { "dir": {"cwd": true}, "file": {"param": true, "quote": true, "base": false} }
     - `cwd`   = 把拖进来的**文件夹**当工作目录（拖的是文件 → 用文件所在的那个文件夹）
     - `param` = 把路径**追加到参数串末尾**（强制末尾，你定的）
     - `quote` = 加双引号（路径里有空白时无论如何都会加，不然宿主按空格拆词就拆坏了）
     - `base`  = 只给文件名，不给完整路径（配合 `cwd` 用）
     - `ext`   = **只收这几种扩展名**（`V-183` ✅，写在 `file` 里）。不写 = 什么文件都收。
       于是拖一个 .txt 进窗口时，`md5`（不限）亮、`img`（只收图片）**不亮** ——
       以前两个都亮，松手还会把 .txt 交给 img 去"处理"，纯属白跑一趟。
     **没写 `drop` 的包 = 完全不收拖入**（比如快捷翻译）—— 拖动时它连列表都不出现。 */
const DRAG = {on: false, kind: null, items: null, depth: 0, cmd: 0, hits: 0, framePid: null};
/* 上一次**拖进来**塞进参数框的那一段（"包 id + 那一段原文"）。
   为什么要记：拖进来的那一段是追加在末尾的，连着拖两次就会叠成一串 —— 实测叠起来之后
   md5 收到两条路径，于是判成字符串、算了个错的 MD5。下一次拖入时先把这一段摘掉。 */
const DROP_ARGS = {id: null, piece: ""};

/* 文件名 → 扩展名（小写、不带点）。认不出来给空串。
   ★ 点在**开头**的（`.gitignore`）算"没有扩展名"，不算扩展名 `gitignore` ——
     这是 Windows 资源管理器同一套规矩，照抄省得两边判得不一样。 */
/* ★ 名字**不能**叫 `extOf` —— `core.js` 里已经有一个 `extOf(entry)`（收对象、返回
   `{i,c,l}` 图标/配色/语言三件套）。经典脚本共享全局，这个文件又排在 `core.js`
   后面 ⇒ 后定义的那个会把前一个**整个盖掉**，而且不报错：`String({...})` 得到
   `"[object Object]"`，`lastIndexOf(".")` 是 -1，于是所有文件都判成"没有扩展名"，
   高亮语言永远是 `plaintext`、图标配色也一起丢（`V-249`，实测就是这么坏的）。 */
function extFromName(name){
  const n = String(name || "");
  const i = n.lastIndexOf(".");
  return i <= 0 ? "" : n.slice(i + 1).toLowerCase();
}
/* 这一条 `file` 规则收不收这个文件（`V-183`）。没写 `ext` = 什么都收。 */
function ruleTakesFile(rule, name){
  const ext = (rule && rule.ext) || [];
  if (!ext.length) return true;
  const e = extFromName(name);
  return !!e && ext.indexOf(e) >= 0;
}
/* 这次拖的到底是什么：尽量读出每个 item 的 {name, isDir}。
   ★ 拖动过程中页面**拿不到真实路径**（Chromium 的安全设计），但**名字**通常拿得到 ——
     扩展名判断就靠它。
   ★★ `V-188` 的真机教训（`_ui_drop.log` 里白纸黑字）：**WebView2 在 `dragenter` 那一刻
     什么都给不出来**（日志：`drag begin kind=unknown items=null`），于是"只收文件夹"的
     `tree` / `mark` / `sync` 全都露在列表里 —— 你看到的就是这个。所以：
     ① 三个来源挨个试：`webkitGetAsEntry()` → `getAsFile()`（这个名字是有的）→ `files`；
     ② **一项都读不出来就返回 null，并且过一会儿在 `dragover` 里再试一次**（见 `dragRetry`）
        —— Chromium 常常是到 `dragover` 才把内容填上；
     ③ 名字读到了但**分不清是文件还是文件夹**时，`isDir` 记 `null`（不是 false！）——
        `dropAccepts` 对 `null` 是"两种都算"，免得把拖文件夹的人挡住。
   有一个 item 完全读不出来 → 整个返回 null（宁可这次不筛，也别拿半份信息乱筛）。 */
/* 扩展名 ↔ 浏览器给的类型（`V-189`）。真机探针实录：
     items=1 [{file|text/x-python|entry=null|file=null}] files=0 []
   —— 拖动中 WebView2 **只给 `kind` 和 `type`**，名字/entry/File 全是空的。所以：
     · **拖动时**按 `type`（MIME）判；**松手后**宿主给真名字，再按扩展名判一次（更准）。
     · 先把"类型 → 扩展名"表写清楚；表里没有的按大类兜底（image/ text/ audio/ video/）。 */
const MIME_EXT = {
  "text/plain": ["txt", "log", "ini", "cfg", "conf", "text", "bat", "cmd", "ps1", "sh"],
  "text/csv": ["csv"], "text/markdown": ["md", "markdown"],
  "text/x-python": ["py", "pyw"], "text/html": ["html", "htm"], "text/css": ["css"],
  "text/javascript": ["js", "mjs"], "application/json": ["json"],
  "application/xml": ["xml"], "text/xml": ["xml"],
  "image/png": ["png"], "image/jpeg": ["jpg", "jpeg"], "image/gif": ["gif"],
  "image/webp": ["webp"], "image/bmp": ["bmp"], "image/tiff": ["tif", "tiff"],
  "image/svg+xml": ["svg"], "image/x-icon": ["ico"], "image/vnd.microsoft.icon": ["ico"],
  "application/pdf": ["pdf"], "application/zip": ["zip"],
  "application/x-msdownload": ["exe", "dll"], "application/x-msdos-program": ["exe"],
  "application/msword": ["doc"], "application/vnd.ms-excel": ["xls"],
  "audio/mpeg": ["mp3"], "video/mp4": ["mp4"],
};
const MIME_GROUP = [
  ["image/", ["png", "jpg", "jpeg", "gif", "bmp", "webp", "ico", "tif", "tiff", "svg", "avif", "heic"]],
  ["text/", ["txt", "log", "ini", "cfg", "md", "markdown", "csv", "json", "xml", "yml", "yaml",
             "toml", "py", "pyw", "js", "mjs", "ts", "html", "htm", "css", "c", "h", "cpp",
             "hpp", "java", "go", "rs", "sh", "bat", "cmd", "ps1", "sql", "vue"]],
  ["audio/", ["mp3", "wav", "flac", "aac", "ogg", "m4a"]],
  ["video/", ["mp4", "mkv", "avi", "mov", "webm", "wmv", "flv"]],
];
/* 这个类型算不算 `extList` 里的扩展名。判不了返回 null（没有类型信息）。 */
function typeTakesExt(extList, mime){
  if (!mime) return null;
  const exact = MIME_EXT[mime];
  if (exact) return exact.some(e => extList.indexOf(e) >= 0);
  for (let i = 0; i < MIME_GROUP.length; i++){
    if (mime.indexOf(MIME_GROUP[i][0]) === 0)
      return MIME_GROUP[i][1].some(e => extList.indexOf(e) >= 0);
  }
  return false;                    // 类型认识、但不属于任何一类 ⇒ 不收（保守）
}

function entryOf(it){
  try{
    const en = it && it.webkitGetAsEntry ? it.webkitGetAsEntry() : null;
    if (en) return {name: en.name || "", isDir: !!en.isDirectory};
  }catch(err){}
  try{
    const f = it && it.getAsFile ? it.getAsFile() : null;
    if (f) return {name: f.name || "", isDir: false};      // 有 File ⇒ 确实是文件
  }catch(err){}
  return null;
}
function dropItems(e){
  try{
    const dt = e.dataTransfer;
    if (!dt) return null;
    const out = [];
    const items = dt.items || [];
    for (let i = 0; i < items.length; i++){
      const it = items[i] || {};
      const mime = String(it.type || "").toLowerCase();
      const got = entryOf(it);
      if (got) out.push({name: got.name, isDir: got.isDir, mime: mime});
      // ★ `V-189`：真机就是这一条 —— 拿不到名字/entry/File，但**类型是有的**
      //   （`.py` 给 `text/x-python`）。有类型就说明它是个**文件**，按类型筛得了。
      else if (it.kind === "file") out.push({name: "", isDir: null, mime: mime});
      else return null;
    }
    if (!out.length){
      const fs = dt.files || [];
      for (let i = 0; i < fs.length; i++) out.push({name: fs[i].name || "", isDir: false, mime: ""});
    }
    return out.length ? out : null;
  }catch(err){ return null; }
}
/* 拖动过程中到底能读到什么 —— 一行字，写进 `_ui_drop.log`（`V-188`）。
   下次真机上再拖一次，这一行就能说清"是没内容、还是没名字、还是分不清类型"。 */
function dropProbe(e){
  try{
    const dt = e.dataTransfer || {};
    const items = dt.items || [];
    const bits = [];
    for (let i = 0; i < Math.min(items.length, 6); i++){
      const it = items[i] || {};
      let en = null, f = null;
      try{ en = it.webkitGetAsEntry ? it.webkitGetAsEntry() : null; }catch(err){}
      try{ f = it.getAsFile ? it.getAsFile() : null; }catch(err){}
      bits.push("{" + (it.kind || "?") + "|" + (it.type || "-") + "|entry=" +
                (en ? (en.isDirectory ? "dir:" : "file:") + en.name : "null") +
                "|file=" + (f ? f.name : "null") + "}");
    }
    const fs = dt.files || [];
    return "items=" + items.length + " [" + bits.join(" ") + "] files=" + fs.length +
           " [" + [].slice.call(fs, 0, 6).map(x => x.name).join(" ") + "]";
  }catch(err){ return "probe 自己也炸了: " + err; }
}
/* 拖的是文件、文件夹，还是两样都有（说不清给 null）。
   `V-189`：真机拿不到名字，但只要 `type` 有值就说明**是文件**。 */
function dropKindOf(items){
  if (!items || !items.length) return null;
  const isFile = it => it.isDir === false || (it.isDir === null && !!it.mime);
  if (items.some(it => it.isDir === null && !it.mime)) return null;   // 类型都没有 → 说不清
  const dir = items.some(it => it.isDir === true), file = items.some(isFile);
  return (dir && file) ? null : (dir ? "dir" : "file");
}
function dragHasFiles(e){
  return !!(e.dataTransfer && (e.dataTransfer.types || []).indexOf("Files") >= 0);
}
/* 一条命令收不收**这一个** item（`V-189`）。三种情况分清楚：
   · 知道是文件夹 → 只看 `dir`；
   · 知道是文件（有名字，或只有 MIME 也算知道是文件）→ 只看 `file` + 扩展名/类型；
   · 什么都不知道（连类型都没有，多半是文件夹）→ 只有当它收文件夹时才算亮。 */
function itemAccepts(cmd, it){
  if (!cmd) return false;
  if (it.isDir === true) return !!cmd.dir;
  const rule = cmd.file;
  const mime = it.mime || "";
  if (it.isDir === false) return !!rule && ruleTakesFile(rule, it.name);   // 名字说了算
  if (mime && !rule) return false;                    // 有类型 ⇒ 是文件；这包不收文件
  if (rule && !((rule.ext || []).length)) return true; // 不限扩展名 ⇒ 是文件就收
  if (rule && mime){
    const ok = typeTakesExt(rule.ext || [], mime);
    if (ok !== null) return ok;                       // 类型明确 ⇒ 就按它判
  }
  return !!cmd.dir;      // 判不了 ⇒ 收文件夹的包才亮（别把"拖文件夹"的人挡住）
}
/* 这个包收不收"这一次拖的东西"。`items` 为 null（读不出来）时一律算收 —— 宁可多列几个，
   也别在认不出来的时候把人挡住。`V-183` 起扩展名/类型也算进来：**每一个**都得对得上。 */
function dropAccepts(p, items){
  if (!p || !p.drop || !p.drop.length) return false;
  if (!items || !items.length) return true;      // 不知道拖的是什么 → 两种都算
  return p.drop.some(c => items.every(it => itemAccepts(c, it)));
}
/* 这个包对"拖进来的是文件/文件夹"能做什么。以后一个包可以有多条命令（多个投放框）。 */
function dropCommandsFor(p, isDir){
  const k = isDir ? "dir" : "file";
  return ((p && p.drop) || []).filter(c => c[k]).map(c => ({label: c.label || "运行", rule: c[k]}));
}
function dropKindName(kind){ return kind === "dir" ? "文件夹" : (kind === "file" ? "文件" : "文件/文件夹"); }

/* ---------------------------------------------------------------- 内嵌那一帧上的拖放（`V-204`）
   ★ 问题：拖动时鼠标压在内嵌界面（那一帧 iframe）上时，浏览器的 `dragover`/`drop` **全给了
     那一帧** —— 跨文档的拖放事件**不会冒泡到父页面**。而"真实路径"只有父页面这侧才拿得到
     （路径是 Python 从 WebView2 里取出来再送进来的），于是：**界面型包的界面盖住右栏时，
     往里拖任何东西都会石沉大海**（`path` 就是这么中的）。
   ★ 办法：那一帧自己会报信（垫片看到拖动就 postMessage `kind:"drag"`），我们收到就铺一张
     **透明罩子**盖住整扇窗，把后面的 `dragover`/`drop` 接到我们这层来 —— 于是既有的那条路
     （`__mossDrop` → 收得下就送进那一帧 / 收不下就走命令行）原样生效。
   ★ 罩子平时 `pointer-events:none`（不挡任何点击），只在有帧报拖动时才打开。 */
let CATCHER = null;
function catcherEl(){
  if (CATCHER && CATCHER.isConnected) return CATCHER;
  CATCHER = document.createElement("div");
  CATCHER.id = "dropcatcher";
  // ★ **罩子本身不画任何东西**（`V-206`）：它只负责"把拖放事件接到我们这侧，好拿到真实路径"。
  //   画大提示的活儿归**那一帧自己** —— 它才知道这一松手会发生什么（"加进 PATH" / "转成 webp"…），
  //   我们这边只知道"交给 :pid"。上一版两边各画一个虚线框，屏幕上就是**两个"松手"**，
  //   看着像两个不一样的选项（`V-205` 踩的）；现在大的只有一个（页面那个），
  //   我们只在左上角那条细条上说一句"拖到「X」的界面上了"。
  document.body.appendChild(CATCHER);
  return CATCHER;
}
function frameDrag(pid, phase){
  const el = catcherEl();
  if (phase === "over"){
    if (DRAG.framePid === pid && el.classList.contains("on")) return;
    DRAG.framePid = pid;
    el.classList.add("on");
    // ★ 告诉那一帧"我接住了，别再报离开"（`V-205`）：罩子一盖上去，它就会收到一次
    //   `dragleave`（鼠标下的元素被换掉了）—— 它照着报 `out`，我们就收罩子；罩子一收，
    //   它又收到 `dragenter` 再报 `over` ⇒ **来回抖**（你看到的"有时候"就是这个）。
    pushEmbedEvent(pid, "captured", {});
    // ★ `V-227`：**把我们自己那个投放框收掉**。这一拖是给那一帧的，不是给我们跑命令行的；
    //   那个框（`.dz-box`，z-index 70）盖在 iframe 上，和帧里页面自己画的提示**同时可见**
    //   ⇒ 用户看到**两个"松手"框**（`V-206` 只解决了罩子那一个，这个漏了）。
    if (DRAG.on){
      renderList();          // 这一拖是冲着**那一帧**去的 ⇒ 左边列表**不筛**（`V-205`）
      paintDragBar();        // 条上改说"松手就交给 :pid 的界面"
      paintDropZone(false);  // 我们那颗"松手 = 运行 …"的框：这一拖不归它，收起来
    }
    uiLog("frame drag: " + PSYM + pid + " 上有人在拖 —— 铺罩子接住（真实路径只有我们这侧拿得到）");
  } else {
    el.classList.remove("on");
    if (DRAG.framePid === pid) DRAG.framePid = null;
    // 离开那一帧了：回到"按声明筛"的正常行为，投放框也按当前选中的包重新算
    if (DRAG.on){ renderList(); paintDragBar(); paintDropZone(false); }
    uiLog("frame drag: " + PSYM + pid + " 上没东西了 —— 收罩子");
  }
}
/* 一个包都没收的时候，说人话解释"差在哪"（`V-183`）—— 最典型的就是"只差扩展名"：
   拖个 .txt 进窗口，md5 收、img 不收，得让人一眼看出 img 为什么没出现。 */
function dropWhyNone(items){
  // `V-189`：真机上拿不到名字，所以不能只看"有没有扩展名" —— 只要拖的里有**文件**项，
  // 就把"只收某几种"的那些包点出来，让人知道差在哪。
  if (!(items || []).some(it => it.isDir !== true)) return "";
  const said = [];
  for (const p of ((DATA && DATA.packages) || [])){
    const c = ((p && p.drop) || []).find(x => x.file && x.file.ext && x.file.ext.length);
    if (!c) continue;
    said.push(PSYM + p.id + " 只收 " + c.file.ext.join(" / "));
    if (said.length >= 2) break;
  }
  return said.length ? "（" + said.join("；") + "）" : "";
}

/* ---- 拖动的开始 / 结束 ---- */
function dragBegin(e){
  if (DRAG.on) return;
  DRAG.on = true;
  DRAG.items = dropItems(e);                    // [{name, isDir}]（isDir 可能是 null）或 null
  DRAG.kind = dropKindOf(DRAG.items);
  DRAG.hits = 0;
  DRAG.cmd = 0;
  DRAG.probed = false;
  document.body.classList.add("dragging");
  uiLog("drag begin kind=" + (DRAG.kind || "unknown") +
        " items=" + JSON.stringify(DRAG.items) +
        " accepts=" + DATA.packages.filter(p => dropAccepts(p, DRAG.items)).length +
        "   探针 " + dropProbe(e));              // `V-188`：真机上到底读得到什么
  renderList();                                 // ★ 只列收得下它的包
  paintDragBar();
  // 当前这个包要是就收得下，投放框**立刻**出现（不用等你先划到别处再划回来）
  paintDropZone(false);
}
/* `V-188`：`dragenter` 那一刻 WebView2 什么都给不出来（真机日志：`items=null`），
   而 Chromium 往往要等到 `dragover` 才把内容填上 —— 所以**每次 dragover 都再试一次**，
   一读到就立刻重筛列表、重画（只读到时记一次日志，免得日志长成山）。 */
function dragRetry(e){
  if (!DRAG.on || DRAG.items) return;
  const got = dropItems(e);
  if (!got) return;
  DRAG.items = got;
  DRAG.kind = dropKindOf(got);
  if (!DRAG.probed){
    DRAG.probed = true;
    uiLog("drag 补读到 kind=" + (DRAG.kind || "unknown") + " items=" + JSON.stringify(got) +
          " accepts=" + DATA.packages.filter(p => dropAccepts(p, got)).length);
  }
  renderList();
  paintDragBar();
  paintDropZone(false);
}
function dragEnd(){
  if (!DRAG.on){ paintDropZone(false); return; }
  DRAG.on = false; DRAG.kind = null; DRAG.items = null; DRAG.depth = 0; DRAG.cmd = 0;
  // 拖动结束：把罩子收掉，并告诉那一帧"拖完了"（它那边画的提示框要自己收，
  // `V-204`：罩子把 drop 接走之后，那一帧就再也收不到 drop 事件了）。
  if (DRAG.framePid){
    const el = CATCHER;
    if (el) el.classList.remove("on");
    pushEmbedEvent(DRAG.framePid, "dragend", {});
    uiLog("frame drag: 收掉罩子（" + PSYM + DRAG.framePid + "）");
    DRAG.framePid = null;
  }
  document.body.classList.remove("dragging");
  renderList();
  paintDragBar();
  paintDropZone(false);
}
/* 左上角那条提示：拖动中只显示收得下它的包 —— 免得你对着一个不收的包干瞪眼 */
/* ★ `V-85` 起这两块（`#dragbar` 提示 + `#dropzone` 投放框）的内容由 **Vue 组件**画：
   状态还是这份 `DRAG`，只是"变了就喊一声"（`DRAGR.rev`），外面照旧调这两个同名门面。
   ★ 为什么 `#dragbar` 的显隐还留在这儿一行命令式：`hidden` 是**这个元素自己的**属性，
     组件是挂在他**里面**的（管不到外面那个壳）。 */
const DRAGR = Vue.reactive({rev: 0, kind: null});

function paintDragBar(){
  const bar = $("#dragbar");
  if (bar) bar.hidden = !DRAG.on;
  DRAGR.rev++;
}

/* ---- 投放框（`V-39`）：只在"当前这个包收得下"的时候出现 ---- */
function paintDropZone(over, isDir, kind){
  const p = cur;
  const k = (kind !== undefined && kind !== null) ? kind : (isDir ? "dir" : DRAG.kind);
  DRAGR.kind = k;
  const cmds = DRAG.on && p ? dropCommandsFor(p, k === "dir") : [];
  // ★ `V-227`：`DRAG.framePid` 有值时，这一拖是**给那一帧的界面**的（罩子那条路）——
  //   我们这颗"松手 = 运行 …"的框**必须收起来**：它盖在 iframe 上（z-index 70），
  //   和帧里页面自己画的提示同时可见，用户看到的就是**两个"松手"框**。
  //   放在这里（而不是每处调用点）是因为 `dragover` 里还会反复重算 —— 单点判最稳。
  const want = !!(DRAG.on && !DRAG.framePid && cmds.length && dropAccepts(p, DRAG.items));  // `V-183`：扩展名不对也不出框
  DRAGR.rev++;                                  // 框里的内容（`.dz-box` 那几个）由组件画
  // ★ 下面这几处 class 挂在**别的元素**上（`#dropzone` 自己 / 详情页 / 右上角那颗「运行」）——
  //   它们不是组件的根，维持命令式，和改造前逐行一致。
  const zone = $("#dropzone"), pane = $("#pane-detail"), btn = $("#btn-run");
  if (zone){
    zone.classList.toggle("on", want);
    zone.classList.toggle("over", !!(want && over));
  }
  if (pane) pane.classList.toggle("hot", want);
  if (btn) btn.classList.toggle("hot", want);       // 右上角那个「运行」跟着亮
}
function dropZoneWhy(p, rule, kind){
  const what = rule.cwd && rule.param ? "当工作目录，并把这个路径追加到参数末尾"
             : (rule.cwd ? "当工作目录" : "追加到参数末尾");
  const which = kind === "dir" ? "这个文件夹" : (kind === "file" ? "这个文件" : "它");
  // `V-183`：框上顺便说清"它只收哪几种"——松手前就知道，别等跑起来才发现格式不对
  const only = (rule.ext && rule.ext.length) ? "（只收 " + rule.ext.join(" / ") + "）" : "";
  return PSYM + p.id + " —— 把" + which + what +
         (rule.base ? "（只给文件名）" : "") + (rule.quote ? "（加引号）" : "") + only;
}

/* 拖拽那两块的组件（`V-85`）—— 一个画左边那条提示，一个画详情页上的投放框。
   两块共用一份举牌信号：它们的数据都来自 `DRAG` / `cur`（普通变量，不是响应式的）。 */
const MossDragBar = {
  name: "moss-dragbar",
  data(){ return { R: DRAGR }; },
  computed: {
    html(){
      this.R.rev;
      if (!DRAG.on) return "";
      // ★ 拖到内嵌那一帧上了（`V-205`）：**这一拖不是"找包"**，是给那个包的界面。
      //   所以条上说清"松手交给谁"，左边列表也**不筛**（别让人以为列表坏了）。
      if (DRAG.framePid){
        const fp = (DATA && DATA.packages || []).find(x => x.id === DRAG.framePid) || {};
        const takes = dropAccepts(fp, DRAG.items);
        // 只在这里说一句（大的那个提示由**那一帧自己**画，`V-206`：两边都画就是两个"松手"）。
        return ico("copy", "i") +
          (takes
            ? '<span>拖到 <b>' + (fp.name || DRAG.framePid) + '</b> 的界面上了：松手就交给它' +
              '（<b>' + esc(PSYM) + '</b>' + DRAG.framePid + '）—— 这一次不跑命令行</span>'
            : '<span><b>' + (fp.name || DRAG.framePid) + '</b> 的界面不收这个（它没声明收拖入）' +
              ' —— 松手不会有反应</span>');
      }
      const n = DATA ? DATA.packages.filter(p => dropAccepts(p, DRAG.items)).length : 0;
      // `V-188`：这一次到底读没读到 —— 读不到就**明说**，别让人以为筛选坏了
      if (!DRAG.items) return ico("copy", "i") +
        '<span>这次没读出拖的是什么（读不到文件名）：先把收拖入的 <b>' + n +
        '</b> 个包都列出来，松手时会再判一次</span>';
      return ico("copy", "i") +
        '<span>拖进来的是<b>' + dropKindName(DRAG.kind) + '</b>：只列出收得下它的 <b>' + n +
        '</b> 个包' + (n ? " —— 划过哪个就选哪个" : "（一个都没有）" + dropWhyNone(DRAG.items)) +
        '</span>';
    },
  },
  // `display:contents`：这层壳不参与布局（`#dragbar` 是 flex，多一层会改变量）
  template: '<div style="display:contents" v-html="html"></div>',
};

const MossDropZone = {
  name: "moss-dropzone",
  data(){ return { R: DRAGR }; },
  computed: {
    cmd(){ this.R.rev; return +DRAG.cmd || 0; },
    boxes(){
      this.R.rev;
      const p = cur, k = this.R.kind;
      const cmds = (DRAG.on && p) ? dropCommandsFor(p, k === "dir") : [];
      return cmds.map(c => ({label: c.label, why: dropZoneWhy(p, c.rule, k)}));
    },
  },
  template: `
    <div v-for="(c, i) in boxes" :key="i" class="dz-box" :class="{on: i === cmd}" :data-cmd="i">
      <div class="dz-big">松手 = {{ c.label }}</div>
      <div class="dz-sub">{{ c.why }}</div>
    </div>`,
};

/* ---- 页面这一侧的拖动事件（真实路径不在这里，见文件头的说明）---- */
function bindDropZone(){
  const pane = $("#pane-detail");
  if (!pane) return;
  document.addEventListener("dragenter", e => {
    if (!dragHasFiles(e)) return;
    DRAG.depth++;
    if (!DRAG.on) dragBegin(e);
    e.preventDefault();
  });
  // ★ 这一行是"在详情页松手却被浏览器打开文件"的解药（`V-42` ✅）：
  //   HTML 的规矩是 —— **只有 `dragover` 被 preventDefault，drop 事件才会发**；
  //   不 preventDefault 的话浏览器就执行它自己的默认动作（把那个文件/文件夹**打开**）。
  //   为什么以前只挂在具体元素上不够：投放框 `#dropzone` 是 `#pane-detail` 的**兄弟**
  //   （不是子节点），鼠标落在框上时，drag 事件根本不经过 `#pane-detail` —— 于是那条
  //   preventDefault 从来没执行过。挂在 `document` 上就没有这个死角（拖动一定会冒泡到它）。
  document.addEventListener("dragover", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    dragRetry(e);                 // `V-188`：dragenter 读不到就在这里补读（这一下是关键）
  });
  // 松手之后把界面收拾干净（不管落在哪儿）。真正的路径由宿主从另一条路送进
  // `window.__mossDrop`，这里只负责"别留着一堆高亮"。
  document.addEventListener("drop", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    uiLog("page drop: files=" + ((e.dataTransfer.files || []).length));
    setTimeout(() => { if (DRAG.on) dragEnd(); }, 1200);   // 给宿主那条路一点时间
  });
  // ★ 列表那一列：划过哪个包就选中它（省得你再回去点一下）。
  //   拖动过程中鼠标事件是不发的，只有 drag 事件 —— 所以用 dragover。
  const list = $("#list");
  if (list) list.addEventListener("dragover", e => {
    if (!DRAG.on) return;
    e.preventDefault();                 // 允许在列表上松手（松在这儿不跑，见 drop）
    const row = e.target && e.target.closest ? e.target.closest(".item") : null;
    if (!row) return;
    const id = row.dataset.id;
    if (id && (!cur || cur.id !== id)){
      select(id);                       // 自动激活（它的详情页会跟着出现投放框）
      paintDropZone(false);
    }
  });
  pane.addEventListener("dragover", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();                 // 这一条是"好看"用的；真正管用的是 document 那条
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    const box = e.target && e.target.closest ? e.target.closest(".dz-box") : null;
    if (box){ const i = +box.dataset.cmd || 0; if (i !== DRAG.cmd){ DRAG.cmd = i; paintDropZone(true); } }
    // ★ 记一笔（`V-85` 查明的，**没改**）：`#dropzone` 是 `#pane-detail` 的**兄弟**（`V-42`），
    //   框里的事件根本不经过这个 pane ⇒ 这一段里的 `paintDropZone(true)` 实际到不了，
    //   CSS 里那条 `#dropzone.over .dz-box{transform:scale(1.02)…}` 也就一直没亮过。
    //   想让它亮，得单独给 `#dropzone` 挂 dragover（还得防连发重画）—— 那是**改行为**，
    //   不混在这一轮"纯搬运"里，等哪轮专门做。
    pane.classList.add("dover");
  });
  pane.addEventListener("dragleave", e => {
    if (!dragHasFiles(e)) return;
    DRAG.depth = Math.max(0, DRAG.depth - 1);
    if (!e.relatedTarget) dragEnd();
    pane.classList.remove("dover");
  });
  pane.addEventListener("drop", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();                 // 真实路径由宿主送过来，这里只收拾界面
    pane.classList.remove("dover");
    // ★ 先别拆投放框：宿主的路径是另一条路送来的（几毫秒后到 `__mossDrop`）
  });
  // 拖出窗口 / 按 Esc 也要收干净，不然那块高亮会一直挂着
  window.addEventListener("dragend", dragEnd);
  window.addEventListener("blur", dragEnd);
  document.addEventListener("dragleave", e => { if (!e.relatedTarget) dragEnd(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") dragEnd(); });
}

/* 宿主把真实路径送过来（drag & drop 的落地口）。items: [{path, isDir, dir, name}, …]
   ★ 到这一步我们才知道真实路径，也才知道拖的到底是文件还是文件夹（以宿主说的为准）。 */
window.__mossDrop = function(items){
  const cmdIdx = DRAG.cmd;
  // ★ 拖放是**冲着哪一帧**去的，得在 `dragEnd()` 之前记下来（`V-205`：罩子那条路上，
  //   用户是把东西拖到内嵌界面上的，目标就是那一帧 —— 不是"当前选中的包"）。
  const framePid = DRAG.framePid;
  dragEnd();
  if (!items || !items.length){ uiLog("host drop: 没有路径（WebView2 没给）"); return; }
  // ★ `V-88`：拖进来的路径**先问一下有没有"别人更想要"**（比如备份那一页的「导出到」
  //   那一行：把文件夹拖上去 = 导出目标）。钩子收下了就到此为止，别再去跑包。
  //   真路径只有宿主知道（Chromium 不给 `File.path`），所以这条"落地口"必须留个插口。
  try{
    if (typeof window.__mossDropHook === "function" && window.__mossDropHook(items)){
      uiLog("host drop: 被页面钩子收下了（备份导出目标之类）");
      return;
    }
  }catch(e){ uiLog("host drop: 钩子抛了 " + e); }
  // ★ `V-307`：AI 工作台那一页的「放行清单」也是一个落地口 —— 拖一个文件夹到 AI 页上 =
  //   把它加进放行清单（用户原话："允许通过添加或者拖动的方式 增加放行的路径"）。
  //   ★ 为什么另起一个名字（不再共用一个 `__mossDropHook`）：那个是**全局唯一**的槽，
  //     已经被「版本快照 → 导出到」占着；两边都往上挂就是"看谁后挂"（`V-88` 的坑）。
  //     AI 那一页自己被卸载时会把钩子摘掉，所以它只会收下"当时确实在 AI 页且面板开着"的拖入。
  try{
    if (typeof window.__mossAiDrop === "function" && window.__mossAiDrop(items)){
      uiLog("host drop: 被 AI 的放行清单收下了");
      return;
    }
  }catch(e){ uiLog("host drop: AI 钩子抛了 " + e); }
  // ★ `V-364`：详情页「自动运行」那一行的**工作路径**框也是一个落地口 ——
  //   拖一个文件夹上去 = 把它设成这个包自动运行时的当前目录（用户原话：
  //   "还可以单独设置工作路径 它可以通过点选 或者鼠标拖动或者输入的方式来完成"）。
  //   ★ 同样另起一个名字（不抢 `__mossDropHook`：那个槽是「版本快照 → 导出到」占着的）；
  //     它自己只在"这次拖的落点确实是那个框"时才收（内部有个 `dragOn` 旗子）。
  try{
    if (typeof window.__mossAutoDrop === "function" && window.__mossAutoDrop(items)){
      uiLog("host drop: 被「自动运行」的工作路径框收下了");
      return;
    }
  }catch(e){ uiLog("host drop: 自动运行钩子抛了 " + e); }
  const p = cur;
  const it = items[0];
  uiLog("host drop: " + JSON.stringify(items));
  // ★ `V-183`：真路径到手之后**再判一次**。拖动时那次筛有认不出来的时候（拿不到文件名
  //   就一律放行），这里用的是宿主给的**真实名字**，判得准 —— 不匹配就说清为什么，
  //   绝不把 .txt 塞给"只收图片"的 img 去白跑一趟。
  const asItems = items.map(x => ({name: x.name || x.path || "", isDir: !!x.isDir}));
  if (p && p.drop && p.drop.length && !dropAccepts(p, asItems)){
    const c = (p.drop || []).find(x => x.file && x.file.ext && x.file.ext.length);
    toast("✗ " + PSYM + p.id + " 不收 " + asItems.map(x => x.name).join("、").slice(0, 48) +
          (c ? " —— 它只收 " + c.file.ext.join(" / ") : ""), true);
    DROP_ARGS.id = null;
    return;
  }
  if (items.length > 1)
    toast("拖进来 " + items.length + " 个，先用第一个：" + (it.name || it.path));
  // ★ `V-201` / `V-205`：目标帧**优先**是"拖过去的那一帧"（罩子那条路），没有才看当前选中的包。
  //   这一帧的内嵌界面正跑着、而且它收得下 ⇒ 把真实路径**送给那一帧**，而不是再起一个
  //   命令行进程（拖文件夹给 `path` 这种界面型包，用户的意图是"加进列表里"）。
  //   事件名 `drop` 是垫片里早就留好的口子（`moss.on('drop')`，见契约 §内嵌界面）。
  const target = (framePid && DATA.packages.find(x => x.id === framePid)) || p;
  if (target && embedRunning(target.id) && dropAccepts(target, asItems)){
    const send = items.map(x => String(x.path || "")).filter(Boolean);
    pushEmbedEvent(target.id, "drop", {items: send});
    uiLog("host drop → 内嵌界面 " + PSYM + target.id + " " + JSON.stringify(send));
    toast("把 " + send.length + " 个路径交给了 " + PSYM + target.id + " 的界面");
    return;
  }
  const cmds = dropCommandsFor(p, it.isDir);
  if (!p || !cmds.length){
    toast("✗ " + (p ? (PSYM + p.id + " 不收" + (it.isDir ? "文件夹" : "文件"))
                    : "先选一个包") + " —— 拖动时只列收得下它的包", true);
    return;
  }
  const cmd = cmds[Math.min(cmdIdx || 0, cmds.length - 1)].rule;
  // 参数串 = "你自己打的那些" + "这次拖进来的那一段"。上一次**拖进来的**那一段先摘掉，
  // 免得连着拖两次叠成一串（实测过：叠起来之后 md5 收到两条路径，判成字符串算了）。
  const box = argsInput();
  let base = box ? box.value : "";
  if (DROP_ARGS.id && base.endsWith(DROP_ARGS.piece))
    base = base.slice(0, base.length - DROP_ARGS.piece.length);
  base = base.trim();
  let cwd = "";
  if (cmd.cwd) cwd = it.isDir ? it.path : it.dir;      // 拖的是文件 → 用它所在的文件夹
  let piece = "";
  if (cmd.param){
    let v = cmd.base ? (it.name || "") : it.path;
    // ★ 一律加引号（除非声明里明写 `"quote": false`）：Windows 路径里全是反斜杠，
    //   而参数串到宿主那边要过一次 `shlex` —— 不加引号的 `C:\a\b.ico` 会被吃成
    //   `C:ab.ico`（实测），包就只能当字符串算了（`V-41`）。
    if (cmd.quote !== false) v = '"' + v + '"';
    piece = v;
  }
  const args = (base + (piece ? " " + piece : "")).trim();
  if (piece) DROP_ARGS.id = p.id, DROP_ARGS.piece = piece;
  else DROP_ARGS.id = null;
  if (box){ box.value = args; box.dispatchEvent(new Event("input")); }
  toast((cwd ? "以 " + cwd + " 为当前目录" : "按当前参数") +
        (piece ? (cmd.base ? "、只把文件名交给它" : "") : "") + "运行 " + PSYM + p.id);
  startRun(p, args, cwd);
};

/* 拖放这条线自己的日志（`user_data/state/_ui_drop.log`）。
   `V-40` 就是"拖了没反应、什么都不知道" —— 有这条日志，一次就能分清是页面没收到拖动、
   还是 WebView2 没给路径。失败不影响功能（纯记事）。 */
function uiLog(text){
  try{ pywebview.api.ui_log(String(text || "")); }catch(e){}
}

/* ---------------------------------------------------------------- 挂载（放最后）
   ★ 同前面几块：等 `DRAG` / `DRAGR` 这些 `const` 都声明完再挂（`mountVue()` 当场渲染）。 */
mountVue(MossDragBar, "#dragbar", {ico: ico});
mountVue(MossDropZone, "#dropzone");
