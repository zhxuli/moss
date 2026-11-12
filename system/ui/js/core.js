window.__errors = window.__errors || [];

function reportError(what, msg, stack){
  const line = what + "：" + msg + (stack ? ("\n" + stack) : "");
  try{ console.error(line); }catch(e){}
  if (typeof window.__mossTell === "function"){
    try{ window.__mossTell(line); }catch(e){}     
  }else{
    try{ window.__errors.push(line); }catch(e){}
  }
  try{ if (typeof toast === "function") toast("⚠ " + msg, true); }catch(e){}
}

function onVueError(err, vm, info){
  reportError("组件出错" + (info ? ("（" + info + "）") : ""),
              (err && err.message) || String(err), (err && err.stack) || "");
}

window.__mossFloatPid = (function () {
  const m = /^#float=([A-Za-z0-9_-]{1,32})$/.exec(location.hash || "");
  return m ? m[1] : "";
})();

function mountVue(comp, target, globals){
  const app = Vue.createApp(comp);
  app.config.errorHandler = onVueError;
  if (globals) Object.assign(app.config.globalProperties, globals);
  return app.mount(target);
}

let DATA = null, cur = null, tab = "detail";

let PSYM = ":";

let curH = null;
function isHist(o){ return !!o && !o.id && !!o.target; }   
function selObj(){ return curH || cur; }
let lastRun = null;

const ARGS = {};

const ID_RE = /^[a-z][a-z0-9_-]{0,31}$/;

let lastStaleReason = "";
const $ = s => document.querySelector(s);

const EXT = {
  py:{i:"file-code",c:"#3572A5",l:"python"}, pyw:{i:"file-code",c:"#3572A5",l:"python"},
  js:{i:"file-code",c:"#c9a227",l:"javascript"}, mjs:{i:"file-code",c:"#c9a227",l:"javascript"},
  ts:{i:"file-code",c:"#2b7489",l:"typescript"}, go:{i:"file-code",c:"#00ADD8",l:"go"},
  rs:{i:"file-code",c:"#dea584",l:"rust"}, c:{i:"file-code",c:"#7a7a7a",l:"c"},
  h:{i:"file-code",c:"#7a7a7a",l:"c"}, cpp:{i:"file-code",c:"#f34b7d",l:"cpp"},
  java:{i:"file-code",c:"#b07219",l:"java"}, cs:{i:"file-code",c:"#178600",l:"csharp"},
  php:{i:"file-code",c:"#7a86b8",l:"php"}, rb:{i:"file-code",c:"#cc342d",l:"ruby"},
  lua:{i:"file-code",c:"#000080",l:"lua"}, sql:{i:"database",c:"#e38c00",l:"sql"},
  html:{i:"globe",c:"#e34c26",l:"xml"}, htm:{i:"globe",c:"#e34c26",l:"xml"},
  xml:{i:"code",c:"#8a8a8a",l:"xml"}, svg:{i:"palette",c:"#ffb13b",l:"xml"},
  css:{i:"palette",c:"#563d7c",l:"css"}, scss:{i:"palette",c:"#c6538c",l:"scss"},
  less:{i:"palette",c:"#1d365d",l:"less"},
  json:{i:"braces",c:"#c9a227",l:"json"}, jsonc:{i:"braces",c:"#c9a227",l:"json"},
  md:{i:"book-open",c:"#6e7781",l:"markdown"}, markdown:{i:"book-open",c:"#6e7781",l:"markdown"},
  txt:{i:"file-text",c:"#6e7781",l:"plaintext"}, log:{i:"file-text",c:"#6e7781",l:"plaintext"},
  bat:{i:"terminal",c:"#8a8a8a",l:"dos"}, cmd:{i:"terminal",c:"#8a8a8a",l:"dos"},
  ps1:{i:"terminal",c:"#2f6fb5",l:"powershell"}, psm1:{i:"terminal",c:"#2f6fb5",l:"powershell"},
  sh:{i:"terminal",c:"#4f9d3a",l:"bash"}, bash:{i:"terminal",c:"#4f9d3a",l:"bash"},
  toml:{i:"settings",c:"#9c4221",l:"ini"}, ini:{i:"settings",c:"#9c4221",l:"ini"},
  cfg:{i:"settings",c:"#9c4221",l:"ini"}, conf:{i:"settings",c:"#9c4221",l:"ini"},
  yml:{i:"settings",c:"#cb171e",l:"yaml"}, yaml:{i:"settings",c:"#cb171e",l:"yaml"},
  png:{i:"file-image",c:"#a074c4"}, jpg:{i:"file-image",c:"#a074c4"},
  jpeg:{i:"file-image",c:"#a074c4"}, gif:{i:"file-image",c:"#a074c4"},
  webp:{i:"file-image",c:"#a074c4"}, bmp:{i:"file-image",c:"#a074c4"},
  ico:{i:"file-image",c:"#a074c4"},
  exe:{i:"binary",c:"#8a8a8a"}, dll:{i:"binary",c:"#8a8a8a"}, pyd:{i:"binary",c:"#8a8a8a"},
  zip:{i:"file-archive",c:"#e0a800"}, "7z":{i:"file-archive",c:"#e0a800"},
  rar:{i:"file-archive",c:"#e0a800"}, gz:{i:"file-archive",c:"#e0a800"},
  mp3:{i:"file-audio",c:"#1f9d55"}, wav:{i:"file-audio",c:"#1f9d55"},
  mp4:{i:"file-video",c:"#d64545"}, mkv:{i:"file-video",c:"#d64545"},
  csv:{i:"file-spreadsheet",c:"#1f9d55"}, xlsx:{i:"file-spreadsheet",c:"#1f9d55"},
  key:{i:"file-key",c:"#c9a227"}, pem:{i:"file-key",c:"#c9a227"},
  license:{i:"copyright",c:"#6e7781"},
};
const NO_EXT = {
  LICENSE:{i:"copyright",c:"#6e7781",l:"plaintext"},
  "pkg.json":{i:"braces",c:"#c9a227",l:"json"},
  ".gitignore":{i:"file-cog",c:"#8a8a8a",l:"plaintext"},
  ".gitattributes":{i:"file-cog",c:"#8a8a8a",l:"plaintext"},
};
function extOf(entry){
  const name = (entry.name || "").toLowerCase();
  if (NO_EXT[name]) return Object.assign({ext:""}, NO_EXT[name]);
  return Object.assign({ext: entry.ext || ""}, EXT[entry.ext] || {i:"file", c:"#8a8a8a"});
}
function fileIconHTML(entry, open){
  if (entry.dir) return '<span style="color:#e0a800;display:flex">' +
    ico(open ? "folder-open" : "folder", "i") + '</span>';
  const e = extOf(entry);
  return '<span style="color:' + e.c + ';display:flex">' + ico(e.i, "i") + '</span>';
}
function typeLabel(entry){
  if (entry.dir) return "文件夹";
  const e = entry.ext || "";
  return e ? (e.toUpperCase() + " 文件") : "文件";
}
function humanSize(n){
  if (n == null) return "";
  if (n < 1024) return n + " B";
  if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
  return (n / 1048576).toFixed(1) + " MB";
}
function fmtTime(sec){
  if (!sec) return "";
  const d = new Date(sec * 1000), p = n => String(n).padStart(2, "0");
  return d.getFullYear() + "/" + p(d.getMonth() + 1) + "/" + p(d.getDate()) + " " +
         p(d.getHours()) + ":" + p(d.getMinutes());
}
function escapeHtml(s){
  return String(s == null ? "" : s)
    .replace(/[&<>"]/g, m => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[m]));
}
const esc = escapeHtml;

function bindColResize(grip, el, sign, min, max, def){
  if (!grip || !el) return;
  const hi = () => (typeof max === "function" ? max() : max);
  const clamp = w => Math.max(min, Math.min(hi(), Math.round(w)));
  grip.addEventListener("pointerdown", e => {
    if (e.button !== 0) return;
    e.preventDefault();
    const x0 = e.clientX, w0 = el.getBoundingClientRect().width;
    try{ grip.setPointerCapture(e.pointerId); }catch(err){}
    grip.classList.add("on");
    document.body.classList.add("colres");
    const move = ev => { el.style.width = clamp(w0 + sign * (ev.clientX - x0)) + "px"; };
    const done = () => {
      grip.removeEventListener("pointermove", move);
      grip.removeEventListener("pointerup", done);
      grip.removeEventListener("pointercancel", done);
      grip.classList.remove("on");
      document.body.classList.remove("colres");
      try{ grip.releasePointerCapture(e.pointerId); }catch(err){}
    };
    grip.addEventListener("pointermove", move);
    grip.addEventListener("pointerup", done);
    grip.addEventListener("pointercancel", done);
  });
  grip.addEventListener("dblclick", () => { el.style.width = clamp(def) + "px"; });
}

const BKD = Vue.reactive({diff: null, title: ""});

function bkDiffRow(rel){
  const d = BKD.diff && BKD.diff.byRel ? BKD.diff.byRel[rel] : null;
  if (!d) return null;
  if (d.state === "now-only") return {"df-new": true};
  if (d.state === "diff") return d.deep === "now" ? {"df-chg": true, "df-deep": true}
                                                  : {"df-chg": true, "df-soft": true};
  if (d.state === "empty") return {"df-empty": true};
  if (d.state === "snap-only" || d.state === "gone") return {"df-gone": true};
  return null;                                  
}

function bkDiffMark(rel){
  const d = BKD.diff && BKD.diff.byRel ? BKD.diff.byRel[rel] : null;
  if (!d) return "";
  if (d.state === "now-only") return "+";
  if (d.state === "snap-only") return "−";      
  if (d.state === "diff") return d.deep === "now" ? "↑" : (d.deep === "snap" ? "↓" : "≠");
  return "";
}
function bkDiffWhy(rel){
  const d = BKD.diff && BKD.diff.byRel ? BKD.diff.byRel[rel] : null;
  if (!d || d.state === "same") return "";
  return "和快照（" + (BKD.title || "选中的那次") + "）比：" + d.why;
}

function bkHasSnap(rel){
  const d = (typeof BKD !== "undefined" && BKD.diff && BKD.diff.byRel) ? BKD.diff.byRel[rel] : null;
  return !!(d && d.snap && d.snap.fp);
}
