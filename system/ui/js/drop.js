const DRAG = {on: false, kind: null, items: null, depth: 0, cmd: 0, hits: 0, framePid: null};

const DROP_ARGS = {id: null, piece: ""};

function extFromName(name){
  const n = String(name || "");
  const i = n.lastIndexOf(".");
  return i <= 0 ? "" : n.slice(i + 1).toLowerCase();
}

function ruleTakesFile(rule, name){
  const ext = (rule && rule.ext) || [];
  if (!ext.length) return true;
  const e = extFromName(name);
  return !!e && ext.indexOf(e) >= 0;
}

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

function typeTakesExt(extList, mime){
  if (!mime) return null;
  const exact = MIME_EXT[mime];
  if (exact) return exact.some(e => extList.indexOf(e) >= 0);
  for (let i = 0; i < MIME_GROUP.length; i++){
    if (mime.indexOf(MIME_GROUP[i][0]) === 0)
      return MIME_GROUP[i][1].some(e => extList.indexOf(e) >= 0);
  }
  return false;                    
}

function entryOf(it){
  try{
    const en = it && it.webkitGetAsEntry ? it.webkitGetAsEntry() : null;
    if (en) return {name: en.name || "", isDir: !!en.isDirectory};
  }catch(err){}
  try{
    const f = it && it.getAsFile ? it.getAsFile() : null;
    if (f) return {name: f.name || "", isDir: false};      
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

function dropKindOf(items){
  if (!items || !items.length) return null;
  const isFile = it => it.isDir === false || (it.isDir === null && !!it.mime);
  if (items.some(it => it.isDir === null && !it.mime)) return null;   
  const dir = items.some(it => it.isDir === true), file = items.some(isFile);
  return (dir && file) ? null : (dir ? "dir" : "file");
}
function dragHasFiles(e){
  return !!(e.dataTransfer && (e.dataTransfer.types || []).indexOf("Files") >= 0);
}

function itemAccepts(cmd, it){
  if (!cmd) return false;
  if (it.isDir === true) return !!cmd.dir;
  const rule = cmd.file;
  const mime = it.mime || "";
  if (it.isDir === false) return !!rule && ruleTakesFile(rule, it.name);   
  if (mime && !rule) return false;                    
  if (rule && !((rule.ext || []).length)) return true; 
  if (rule && mime){
    const ok = typeTakesExt(rule.ext || [], mime);
    if (ok !== null) return ok;                       
  }
  return !!cmd.dir;      
}

function dropAccepts(p, items){
  if (!p || !p.drop || !p.drop.length) return false;
  if (!items || !items.length) return true;      
  return p.drop.some(c => items.every(it => itemAccepts(c, it)));
}

function dropCommandsFor(p, isDir){
  const k = isDir ? "dir" : "file";
  return ((p && p.drop) || []).filter(c => c[k]).map(c => ({label: c.label || "运行", rule: c[k]}));
}
function dropKindName(kind){ return kind === "dir" ? "文件夹" : (kind === "file" ? "文件" : "文件/文件夹"); }

let CATCHER = null;
function catcherEl(){
  if (CATCHER && CATCHER.isConnected) return CATCHER;
  CATCHER = document.createElement("div");
  CATCHER.id = "dropcatcher";

  document.body.appendChild(CATCHER);
  return CATCHER;
}
function frameDrag(pid, phase){
  const el = catcherEl();
  if (phase === "over"){
    if (DRAG.framePid === pid && el.classList.contains("on")) return;
    DRAG.framePid = pid;
    el.classList.add("on");

    pushEmbedEvent(pid, "captured", {});

    if (DRAG.on){
      renderList();          
      paintDragBar();        
      paintDropZone(false);  
    }
    uiLog("frame drag: " + PSYM + pid + " 上有人在拖 —— 铺罩子接住（真实路径只有我们这侧拿得到）");
  } else {
    el.classList.remove("on");
    if (DRAG.framePid === pid) DRAG.framePid = null;

    if (DRAG.on){ renderList(); paintDragBar(); paintDropZone(false); }
    uiLog("frame drag: " + PSYM + pid + " 上没东西了 —— 收罩子");
  }
}

function dropWhyNone(items){
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

function dragBegin(e){
  if (DRAG.on) return;
  DRAG.on = true;
  DRAG.items = dropItems(e);                    
  DRAG.kind = dropKindOf(DRAG.items);
  DRAG.hits = 0;
  DRAG.cmd = 0;
  DRAG.probed = false;
  document.body.classList.add("dragging");
  uiLog("drag begin kind=" + (DRAG.kind || "unknown") +
        " items=" + JSON.stringify(DRAG.items) +
        " accepts=" + DATA.packages.filter(p => dropAccepts(p, DRAG.items)).length +
        "   探针 " + dropProbe(e));              
  renderList();                                 
  paintDragBar();

  paintDropZone(false);
}

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

const DRAGR = Vue.reactive({rev: 0, kind: null});

function paintDragBar(){
  const bar = $("#dragbar");
  if (bar) bar.hidden = !DRAG.on;
  DRAGR.rev++;
}

function paintDropZone(over, isDir, kind){
  const p = cur;
  const k = (kind !== undefined && kind !== null) ? kind : (isDir ? "dir" : DRAG.kind);
  DRAGR.kind = k;
  const cmds = DRAG.on && p ? dropCommandsFor(p, k === "dir") : [];

  const want = !!(DRAG.on && !DRAG.framePid && cmds.length && dropAccepts(p, DRAG.items));  
  DRAGR.rev++;                                  

  const zone = $("#dropzone"), pane = $("#pane-detail"), btn = $("#btn-run");
  if (zone){
    zone.classList.toggle("on", want);
    zone.classList.toggle("over", !!(want && over));
  }
  if (pane) pane.classList.toggle("hot", want);
  if (btn) btn.classList.toggle("hot", want);       
}
function dropZoneWhy(p, rule, kind){
  const what = rule.cwd && rule.param ? "当工作目录，并把这个路径追加到参数末尾"
             : (rule.cwd ? "当工作目录" : "追加到参数末尾");
  const which = kind === "dir" ? "这个文件夹" : (kind === "file" ? "这个文件" : "它");

  const only = (rule.ext && rule.ext.length) ? "（只收 " + rule.ext.join(" / ") + "）" : "";
  return PSYM + p.id + " —— 把" + which + what +
         (rule.base ? "（只给文件名）" : "") + (rule.quote ? "（加引号）" : "") + only;
}

const MossDragBar = {
  name: "moss-dragbar",
  data(){ return { R: DRAGR }; },
  computed: {
    html(){
      this.R.rev;
      if (!DRAG.on) return "";

      if (DRAG.framePid){
        const fp = (DATA && DATA.packages || []).find(x => x.id === DRAG.framePid) || {};
        const takes = dropAccepts(fp, DRAG.items);

        return ico("copy", "i") +
          (takes
            ? '<span>拖到 <b>' + (fp.name || DRAG.framePid) + '</b> 的界面上了：松手就交给它' +
              '（<b>' + esc(PSYM) + '</b>' + DRAG.framePid + '）—— 这一次不跑命令行</span>'
            : '<span><b>' + (fp.name || DRAG.framePid) + '</b> 的界面不收拖进来的东西' +
              ' —— 松手不会有反应</span>');
      }
      const n = DATA ? DATA.packages.filter(p => dropAccepts(p, DRAG.items)).length : 0;

      if (!DRAG.items) return ico("copy", "i") +
        '<span>这次没读出拖的是什么（读不到文件名）：先把收拖入的 <b>' + n +
        '</b> 个包都列出来，松手时会再判一次</span>';
      return ico("copy", "i") +
        '<span>拖进来的是<b>' + dropKindName(DRAG.kind) + '</b>：只列出收得下它的 <b>' + n +
        '</b> 个包' + (n ? " —— 划过哪个就选哪个" : "（一个都没有）" + dropWhyNone(DRAG.items)) +
        '</span>';
    },
  },

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

function bindDropZone(){
  const pane = $("#pane-detail");
  if (!pane) return;
  document.addEventListener("dragenter", e => {
    if (!dragHasFiles(e)) return;
    DRAG.depth++;
    if (!DRAG.on) dragBegin(e);
    e.preventDefault();
  });

  document.addEventListener("dragover", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    dragRetry(e);                 
  });

  document.addEventListener("drop", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();
    uiLog("page drop: files=" + ((e.dataTransfer.files || []).length));
    setTimeout(() => { if (DRAG.on) dragEnd(); }, 1200);   
  });

  const list = $("#list");
  if (list) list.addEventListener("dragover", e => {
    if (!DRAG.on) return;
    e.preventDefault();                 
    const row = e.target && e.target.closest ? e.target.closest(".item") : null;
    if (!row) return;
    const id = row.dataset.id;
    if (id && (!cur || cur.id !== id)){
      select(id);                       
      paintDropZone(false);
    }
  });
  pane.addEventListener("dragover", e => {
    if (!dragHasFiles(e)) return;
    e.preventDefault();                 
    if (e.dataTransfer) e.dataTransfer.dropEffect = "copy";
    const box = e.target && e.target.closest ? e.target.closest(".dz-box") : null;
    if (box){ const i = +box.dataset.cmd || 0; if (i !== DRAG.cmd){ DRAG.cmd = i; paintDropZone(true); } }

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
    e.preventDefault();                 
    pane.classList.remove("dover");

  });

  window.addEventListener("dragend", dragEnd);
  window.addEventListener("blur", dragEnd);
  document.addEventListener("dragleave", e => { if (!e.relatedTarget) dragEnd(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") dragEnd(); });
}

window.__mossDrop = function(items){
  const cmdIdx = DRAG.cmd;

  const framePid = DRAG.framePid;
  dragEnd();
  if (!items || !items.length){ uiLog("host drop: 没有路径（WebView2 没给）"); return; }

  try{
    if (typeof window.__mossSndDrop === "function" && window.__mossSndDrop(items)){
      uiLog("host drop: 被设置里的音效行收下了");
      return;
    }
  }catch(e){ uiLog("host drop: 音效钩子抛了 " + e); }

  try{
    if (typeof window.__mossDropHook === "function" && window.__mossDropHook(items)){
      uiLog("host drop: 被页面钩子收下了（备份导出目标之类）");
      return;
    }
  }catch(e){ uiLog("host drop: 钩子抛了 " + e); }

  try{
    if (typeof window.__mossAiDrop === "function" && window.__mossAiDrop(items)){
      uiLog("host drop: 被 AI 的放行清单收下了");
      return;
    }
  }catch(e){ uiLog("host drop: AI 钩子抛了 " + e); }

  try{
    if (typeof window.__mossAutoDrop === "function" && window.__mossAutoDrop(items)){
      uiLog("host drop: 被「自动运行」的工作路径框收下了");
      return;
    }
  }catch(e){ uiLog("host drop: 自动运行钩子抛了 " + e); }
  const p = cur;
  const it = items[0];
  uiLog("host drop: " + JSON.stringify(items));

  const asItems = items.map(x => ({name: x.name || x.path || "", isDir: !!x.isDir}));
  if (p && p.drop && p.drop.length && !dropAccepts(p, asItems)){
    const c = (p.drop || []).find(x => x.file && x.file.ext && x.file.ext.length);
    toast("✗ " + PSYM + p.id + " 不收 " + asItems.map(x => x.name).join("、").slice(0, 48) +
          (c ? " —— 它只收 " + c.file.ext.join(" / ") : ""), true);
    DROP_ARGS.id = null;
    return;
  }

  const many = items.length > 1
    ? ("（拖进来 " + items.length + " 个，先用第一个 " + (it.name || it.path) + "）") : "";

  const target = (framePid && DATA.packages.find(x => x.id === framePid)) || p;
  if (target && embedRunning(target.id) && dropAccepts(target, asItems)){
    const send = items.map(x => String(x.path || "")).filter(Boolean);
    pushEmbedEvent(target.id, "drop", {items: send});
    uiLog("host drop → 内嵌界面 " + PSYM + target.id + " " + JSON.stringify(send));
    toast("把 " + send.length + " 个路径交给了 " + PSYM + target.id + " 的界面" + many);
    return;
  }
  const cmds = dropCommandsFor(p, it.isDir);
  if (!p || !cmds.length){
    toast("✗ " + (p ? (PSYM + p.id + " 不收" + (it.isDir ? "文件夹" : "文件"))
                    : "先选一个包") + " —— 拖动时只列收得下它的包", true);
    return;
  }
  const cmd = cmds[Math.min(cmdIdx || 0, cmds.length - 1)].rule;

  const box = argsInput();
  let base = box ? box.value : "";
  if (DROP_ARGS.id && base.endsWith(DROP_ARGS.piece))
    base = base.slice(0, base.length - DROP_ARGS.piece.length);
  base = base.trim();
  let cwd = "";
  if (cmd.cwd) cwd = it.isDir ? it.path : it.dir;      
  let piece = "";
  if (cmd.param){
    let v = cmd.base ? (it.name || "") : it.path;

    if (cmd.quote !== false) v = '"' + v + '"';
    piece = v;
  }
  const args = (base + (piece ? " " + piece : "")).trim();
  if (piece) DROP_ARGS.id = p.id, DROP_ARGS.piece = piece;
  else DROP_ARGS.id = null;
  if (box){ box.value = args; box.dispatchEvent(new Event("input")); }
  toast((cwd ? "以 " + cwd + " 为当前目录" : "按当前参数") +
        (piece ? (cmd.base ? "、只把文件名交给它" : "") : "") + "运行 " + PSYM + p.id + many);
  startRun(p, args, cwd);
};

function uiLog(text){
  try{ pywebview.api.ui_log(String(text || "")); }catch(e){}
}

mountVue(MossDragBar, "#dragbar", {ico: ico});
mountVue(MossDropZone, "#dropzone");
