const FM = Vue.reactive({
  ctx: null, st: {},

  rev: 0,
});
const HIST_PREFIX = "hist:";

function isHistKey(key){ return String(key || "").startsWith(HIST_PREFIX); }
function histByKey(key){ return HIST.find(x => histKey(x) === key) || null; }

function fmCtxKey(){ return cur ? cur.id : (curH ? histKey(curH) : "__all__"); }

function fmState(key){
  if (!key) key = "__all__";
  if (!FM.st[key]){
    FM.st[key] = {rel:null, hist:[], hpos:-1, entries:[], sel:new Set(), clip:null,
                  sort:{key:"name", dir:1}, tabs:[], active:"__browse__",
                  pkg: (!isHistKey(key) && key !== "__all__") ? key : null,
                  histCtx: isHistKey(key) ? key : null,
                  layers: {user:false, system:false},
                  search: fmSearchFresh()};
  }
  return FM.st[key];
}

function fmSearchFresh(){
  return {on:false, q:"", cs:false, re:false, word:false,
          busy:false, ran:false, err:"", note:"",
          files:[], open:{}, nFiles:0, nHits:0, scanned:0, skipped:0, ms:0,
          truncated:false, cut:[], seq:0};
}
function fmSearch(){ return fmState(FM.ctx).search; }

function fmLayerRels(key){
  const p = DATA.packages.find(x => x.id === key);
  const rel = p ? pkgRel(p) : null;
  if (!rel) return {user: "user/pkgs/" + key, system: "system/pkgs/" + key};
  const tail = rel.replace(/^(user|system)/, "");      
  return {user: "user" + tail, system: "system" + tail};
}
async function fmProbeLayers(key){
  if (!key || key === "__all__") return {user:true, system:true};
  if (isHistKey(key)) return {user:false, system:false};   
  const cand = fmLayerRels(key);
  const r = await pywebview.api.fs_exists([cand.user, cand.system]);
  const has = (r && r.has) || {};
  return {user: !!has[cand.user], system: !!has[cand.system]};
}
function fmDefaultRel(key){
  if (key === "__all__") return "user";
  if (isHistKey(key)){
    const it = histByKey(key);
    return (it && histDir(it)) || "user";
  }
  const p = DATA.packages.find(x => x.id === key);
  return (p && pkgRel(p)) || "user";
}
function fmLabel(key){
  if (key === "__all__") return "全部文件";
  if (isHistKey(key)){
    const it = histByKey(key);
    return "历史 · " + ((it && (it.name || it.target)) || key.slice(HIST_PREFIX.length));
  }
  const p = DATA.packages.find(x => x.id === key);
  return p ? (p.name + "（" + PSYM + p.id + "）") : key;
}
function isDirty(t){ return t && !t.binary && t.text !== t.original; }

function fmReRoot(oldRel, newRel){
  if (!oldRel || !newRel || oldRel === newRel) return false;
  let any = false;
  Object.keys(FM.st).forEach(k => {
    let touched = false;
    const fix = r => {
      if (typeof r === "string" && (r === oldRel || r.startsWith(oldRel + "/"))){
        touched = true;
        return newRel + r.slice(oldRel.length);
      }
      return r;
    };
    const s = FM.st[k];
    s.rel = fix(s.rel);
    s.hist = (s.hist || []).map(fix);
    (s.tabs || []).forEach(t => { t.rel = fix(t.rel); });
    if (touched){ s.stale = true; any = true; }
  });
  return any;
}
function fmActiveTab(){
  const s = fmState(FM.ctx);
  return s.tabs.find(t => t.rel === s.active) || null;
}

async function fmSelect(key, keepTab){
  FM.ctx = key;
  const s = fmState(key);
  s.layers = await fmProbeLayers(key);          

  if (FM.ctx !== key) return;
  if (!s.rel){
    const def = fmDefaultRel(key);
    const ok = await fmGoto(def, true, true);   
    if (FM.ctx !== key) return;

    if (!ok && isHistKey(key)){
      const it = histByKey(key);
      const alt = it && it.target ? dirRel(it.target.replace(/[\\/][^\\/]*$/, "")) : null;
      if (alt && alt !== def) await fmGoto(alt, true, true);
    }
  } else if (s.stale){
    s.stale = false;
    await fmGoto(s.rel, false, true);
  } else fmRender();
  if (!keepTab) setTab("file");
}

async function fmGoto(rel, push, quiet){
  const s = fmState(FM.ctx);
  const r = await pywebview.api.fs_list(rel);
  if (!r.ok){ toast("✗ " + r.msg, true); return false; }
  s.rel = r.rel || rel;
  s.path = r.path || "";            
  s.entries = r.entries || [];
  s.sel.clear();
  if (push !== false){
    s.hist = s.hist.slice(0, s.hpos + 1);
    s.hist.push(s.rel);
    s.hpos = s.hist.length - 1;
  }
  s.active = "__browse__";
  if (!quiet) setTab("file");
  fmRender();
  return true;
}
function fmHome(){
  const def = fmDefaultRel(FM.ctx);
  const s = fmState(FM.ctx);

  if (s.rel === def){ toast("已经在默认目录了：" + (s.path || def)); return; }
  fmGoto(def);
}

function fmRefresh(quiet){
  const s = fmState(FM.ctx);
  if (!s.rel) return;

  fmProbeLayers(FM.ctx).then(layers => { s.layers = layers; });
  const was = s.active;
  fmGoto(s.rel, false, !!quiet).then(ok => {
    if (ok && quiet && was !== "__browse__" && s.tabs.some(t => t.rel === was)){
      s.active = was;
      fmRender();
    }
  });
}

function diskChanged(rels){
  const list = (rels || []).map(r => dirRel(r) || String(r || ""));
  try{
    Object.keys(FM.st).forEach(k => { FM.st[k].stale = true; });
    FM.rev++;
    if (list.some(isPkgManifest) && typeof refreshPkgs === "function")
      refreshPkgs((cur && cur.id) || undefined, true);
    fmReloadPages(list);
    fmRefresh(true);

    if (typeof bkRefresh === "function") bkRefresh();
  }catch(e){}
  return list;
}

function fmReloadPages(rels){
  const dirty = [];
  const want = (rels || []).filter(Boolean);
  if (!want.length) return dirty;
  Object.keys(FM.st).forEach(k => {
    ((FM.st[k] || {}).tabs || []).forEach(t => {
      if (want.indexOf(t.rel) < 0) return;
      if (isDirty(t)){ dirty.push(t.rel); return; }   
      pywebview.api.fs_read(t.rel).then(r => {
        if (!r || !r.ok) return;
        t.text = r.text || ""; t.original = r.text || "";
        t.binary = !!(r.binary || r.too_big);
        t.note = r.binary ? "binary" : (r.too_big ? r.msg : "");

        t.encoding = r.encoding || "utf-8"; t.bom = r.bom || "";
        fmRender();
      }).catch(() => {});
    });
  });
  if (dirty.length)

    toast("这些文件在别处被改过了，你手上这份还没保存 —— 先看一眼再存：" +
          dirty.join("、"), true);
  return dirty;
}

function fmAtTop(rel){
  const r = String(rel || "");
  if (!r.includes("/")) return true;                    
  if (r === "abs") return true;
  if (/^abs\/[A-Za-z]:\/?$/.test(r)) return true;       
  return false;
}
function fmUp(){
  const rel = fmState(FM.ctx).rel || "";
  if (fmAtTop(rel)){ toast("已经到顶了：" + rel); return; }
  fmGoto(rel.split("/").slice(0, -1).join("/"));
}
function fmBack(){ const s = fmState(FM.ctx); if (s.hpos > 0){ s.hpos--; fmGoto(s.hist[s.hpos], false); } }
function fmFwd(){ const s = fmState(FM.ctx); if (s.hpos < s.hist.length - 1){ s.hpos++; fmGoto(s.hist[s.hpos], false); } }

async function fmOpenPage(rel){
  const s = fmState(FM.ctx);
  let t = s.tabs.find(x => x.rel === rel);
  if (!t){
    const r = await pywebview.api.fs_read(rel);
    if (!r.ok){ toast("✗ " + r.msg, true); return; }
    const name = rel.split("/").pop();
    const ext = (name.split(".").pop() || "").toLowerCase();
    const meta = extOf({name: name, ext: ext});
    const kind = previewKindOf(name);
    t = {rel: rel, name: name, lang: meta.l || "plaintext",
         text: r.text || "", original: r.text || "",
         binary: !!(r.binary || r.too_big),
         note: r.binary ? "binary" : (r.too_big ? r.msg : ""),

         encoding: r.encoding || "utf-8", bom: r.bom || "",
         encodingNote: r.encoding_note || "",

         previewKind: kind, preview: !!kind && !r.binary && !r.too_big, previewBase: "",
         factory: rel.split("/")[0] === "system"};
    s.tabs.push(t);
  }
  s.active = rel;
  setTab("file");
  fmRender();

  fmFocusActiveSoon();
}

let _fmJumpSeq = 0;
async function fmOpenPageAt(rel, line){
  const s = fmState(FM.ctx);
  await fmOpenPage(rel);
  const t = s.tabs.find(x => x.rel === rel);
  if (!t) return;
  t.jump = {line: Math.max(1, line | 0), seq: ++_fmJumpSeq};
  fmRender();
}
function fmClosePage(rel){
  const s = fmState(FM.ctx);
  const t = s.tabs.find(x => x.rel === rel);
  if (!t) return;
  const doClose = () => {
    s.tabs = s.tabs.filter(x => x.rel !== rel);
    if (s.active === rel) s.active = s.tabs.length ? s.tabs[s.tabs.length - 1].rel : "__browse__";
    fmRender();
  };
  if (isDirty(t)) askConfirm("有未保存的改动", "“" + t.name + "” 改过但没保存，关掉就丢了。确定关吗？", doClose);
  else doClose();
}
function fmSave(t){
  if (!t || t.binary) return;
  pywebview.api.fs_write(t.rel, t.text, t.encoding || "utf-8", t.bom || "").then(r => {
    if (!r.ok){ toast("✗ " + r.msg, true); return; }

    t.original = t.text; fmPaintBar();

    if (isPkgManifest(t.rel)) refreshPkgs(null, true).then(() => afterManifestSaved(t.rel, t.text, r));
    else toast("已保存 " + t.rel + (r.factory ? "（出厂件）" : ""));
  });
}

function fmSearchOpen(on){
  const st = fmSearch();
  const to = (on === undefined) ? !st.on : !!on;
  st.on = to;
  if (!to) st.busy = false;
  fmRender();
  if (to) fmFocusSearchSoon();          
}

function fmFocusSearchSoon(){
  const go = () => {
    const el = document.querySelector("#fm-body .fbsearch input");
    if (el){ el.focus(); el.select(); }
  };
  const a = fmApp();
  if (a) a.$nextTick(go); else go();
}
function fmSearchClose(){ fmSearchOpen(false); }

function fmSearchOpt(key){
  const st = fmSearch();
  st[key] = !st[key];
  fmSearchMaybeRerun();
}
function fmSearchMaybeRerun(){
  const st = fmSearch();
  if (st.on && st.ran && String(st.q || "").trim()) fmSearchRun();
}
async function fmSearchRun(){
  const st = fmSearch(), s = fmState(FM.ctx);
  const q = String(st.q || "");
  if (!q.trim()){ toast("先输入要搜的内容"); return; }
  const seq = ++st.seq;
  const roots = [(s.rel || "user")];       
  st.busy = true; st.err = ""; st.note = ""; st.ran = true;
  st.files = []; st.open = {};
  st.nFiles = 0; st.nHits = 0; st.scanned = 0; st.skipped = 0; st.ms = 0;
  st.truncated = false; st.cut = [];
  fmRender();
  let r = null;
  try{
    r = await pywebview.api.fs_search(q, {roots: roots, cs: !!st.cs, re: !!st.re,
                                          word: !!st.word});
  }catch(e){
    r = {ok: false, msg: "搜索失败：" + ((e && e.message) || e)};
  }
  if (seq !== st.seq) return;             
  st.busy = false;
  if (!r || !r.ok){
    st.err = (r && r.msg) || "搜索失败";
    fmRender();
    return;
  }
  st.files = r.files || [];
  st.nFiles = r.n_files || 0;
  st.nHits = r.n_hits || 0;
  st.scanned = r.scanned || 0;
  st.skipped = r.skipped || 0;
  st.ms = r.ms || 0;
  st.truncated = !!r.truncated;
  st.cut = r.cut || [];
  st.note = r.note || "";

  st.open = {};
  if (st.files.length) st.open[st.files[0].rel] = true;
  fmRender();
}

function fmSearchJump(rel, line){ fmOpenPageAt(rel, line); }

function isPkgManifest(rel){
  return /(^|\/)pkg\.json$/i.test(String(rel || ""));
}
async function refreshPkgs(preferId, quiet){
  let fresh;
  try{ fresh = await pywebview.api.state(); }catch(e){ return; }
  if (!fresh || !fresh.packages) return;
  DATA = fresh;
  FM.rev++;                      
  renderList(); paintStates();

  if (cur){
    const id = cur.id;
    cur = DATA.packages.find(p => p.id === (preferId || id)) ||
          DATA.packages.find(p => p.id === id) || null;
    if (cur) renderDetail();
    else {                       
      cur = null; renderDetail();

      if (!quiet) toast("这个包已经不在列表里了（说明文件被删掉或改坏了）", true);
    }
  }
  fmPaintBar();                  

  if (typeof paintEmbedTab === "function") paintEmbedTab();

  const sr = fresh.stale_reason;
  if (sr && sr !== lastStaleReason){
    lastStaleReason = sr;
    toast("包列表没读出来，下面显示的还是上一次的：" + sr, true);
  } else if (!sr){
    lastStaleReason = "";
  }
}

async function afterManifestSaved(fileRel, text, saved){
  const okMsg = () => toast("已保存 " + fileRel + ((saved && saved.factory) ? "（出厂件）" : ""));
  if (DATA.stale_reason) return;                 
  const dirRel = String(fileRel).replace(/\/[^/]+$/, "");   
  const base = dirRel.split("/").pop() || "";
  const layer = dirRel.split("/")[0];            
  const p = DATA.packages.find(x => pkgRel(x) === dirRel);
  let why = "", newId = "";
  if (!p){
    try{ newId = String((JSON.parse(text) || {}).id || "").trim().toLowerCase(); }
    catch(e){ why = "这不是合法的 JSON（" + e.message + "）"; }
    if (!why && !ID_RE.test(newId))

      why = "id '" + newId + "' 不合法：只能用小写字母、数字、- 和 _，最长 32 个字，"
            + "而且要用字母开头";
    if (!why && DATA.packages.some(x => x.id === newId))
      why = "id '" + newId + "' 已经被别的包用了";
    if (!why) why = "moss 没认下这个包（清单读不出来）";
    toast("✗ 这个包没被接受：" + why, true);
    return;
  }
  if (p.id === base){ okMsg(); return; }         
  const oldData = "user/state/" + base, newData = "user/state/" + p.id;
  let moveData = false;
  try{
    const has = await pywebview.api.fs_exists([oldData, newData]);
    const h = (has && has.has) || {};
    moveData = !!h[oldData] && !h[newData];
  }catch(e){ moveData = false; }
  askConfirm("清单和包目录不一样了",
    "你把这个包的 id 改成了 <b>" + esc(p.id) + "</b>，但包目录还叫 <b>" + esc(base) + "</b>。" +
    (moveData ? "<br>另外旧数据目录 <b>user_data/state/" + esc(base) + "</b> 还在，" +
                "一起搬成 <b>state/" + esc(p.id) + "</b>。" : "") +
    "<br><br>要我把包目录名" + (moveData ? "（连同旧数据）" : "") +
    "一起改成 <b>" + esc(p.id) + "</b> 吗？",
    () => unifyPkgDir(p, dirRel, moveData, layer));
}

async function unifyPkgDir(p, dirRel, moveData, layer){
  consoleKey = "__host__";
  const cmd = "moss --rename " + p.id + " " + p.id;
  setConsole("__host__", "$ " + cmd, "运行中");
  const r = await pywebview.api.run_host("--rename " + p.id + " " + p.id);
  setConsole("__host__", "$ " + cmd + "\n\n" + (r.out || "(没有输出)"),
             r.code === 0 ? "完成" : ("退出码 " + r.code));
  if (r.code !== 0){
    toast("✗ 没统一成，看「命令行」里说了什么", true);
    setTab("console");
    return;
  }

  let note = "";
  if (moveData){
    const base = String(dirRel).split("/").pop();
    const rr = await pywebview.api.fs_rename("user/state/" + base, p.id);
    note = rr.ok ? "，旧数据也一起搬好了"
                 : ("（但旧数据没搬成：" + rr.msg + "）");
  }
  toast("已统一：包目录名 → " + p.id + note, note.indexOf("没搬成") >= 0);
  const newRel = (layer || "user") + "/pkgs/" + p.id;
  await refreshPkgs(p.id);
  fmReRoot(dirRel, newRel);                       
  if (DATA.packages.some(x => x.id === p.id)) select(p.id);
  else renderDetail();
}

function fmSorted(s){
  const {key, dir} = s.sort;
  return s.entries.slice().sort((a, b) => {
    if (a.dir !== b.dir) return a.dir ? -1 : 1;
    let x, y;
    if (key === "name"){ x = a.name.toLowerCase(); y = b.name.toLowerCase(); }
    else if (key === "mtime"){ x = a.mtime || 0; y = b.mtime || 0; }
    else if (key === "size"){ x = a.size || 0; y = b.size || 0; }
    else { x = typeLabel(a).toLowerCase(); y = typeLabel(b).toLowerCase(); }
    return x < y ? -1 * dir : (x > y ? 1 * dir : 0);
  });
}

const HL_PAD = 20;
const HL_MAX = 300000;          

function splitHlLines(html){
  const out = [];
  const stack = [];                       
  let cur = "";
  const re = /<span\b[^>]*>|<\/span>|\n|[^<\n]+|</g;
  let m;
  while ((m = re.exec(html)) !== null){
    const tk = m[0];
    if (tk === "\n"){
      out.push(cur + "</span>".repeat(stack.length));
      cur = stack.join("");               
    } else if (tk === "</span>"){
      stack.pop();
      cur += tk;
    } else if (tk.charAt(0) === "<" && tk.charAt(1) === "s"){
      stack.push(tk);
      cur += tk;
    } else {
      cur += tk;
    }
  }
  out.push(cur);
  return out;
}

function paintHl(t, code, win){
  const text = t.text || "";
  const can = text.length <= HL_MAX && window.hljs && t.lang && hljs.getLanguage(t.lang);
  if (!can){
    code.textContent = text + "\n";
    window.__hl = {mode: "plain", ms: 0, chars: text.length};
    return window.__hl;
  }
  const lines = text.split("\n");
  const n = lines.length;
  const a = win ? Math.max(0, (win.first | 0) - HL_PAD) : 0;
  const b = win ? Math.min(n - 1, (win.last | 0) + HL_PAD) : n - 1;
  const t0 = performance.now();
  let mid = "";
  try{
    mid = splitHlLines(hljs.highlight(lines.slice(a, b + 1).join("\n"),
                                      {language: t.lang, ignoreIllegals: true}).value).join("\n");
  }catch(e){ mid = ""; }
  const ms = performance.now() - t0;

  const before = a > 0 ? lines.slice(0, a).join("\n") + "\n" : "";
  const after = (b < n - 1 ? "\n" + lines.slice(b + 1).join("\n") : "") + "\n";
  if (!code.__parts){                       
    code.textContent = "";
    const pm = document.createElement("span");
    pm.className = "hlwin";
    code.append(document.createTextNode(""), pm, document.createTextNode(""));
    code.__parts = true;
  }
  const p1 = code.childNodes[0], pm = code.childNodes[1], p2 = code.childNodes[2];
  if (p1.nodeValue !== before) p1.nodeValue = before;       
  if (pm.__html !== mid){ pm.innerHTML = mid; pm.__html = mid; }
  if (p2.nodeValue !== after) p2.nodeValue = after;
  window.__hl = {mode: "window", ms: ms, chars: text.length, lines: n,
                 a: a, b: b, painted: b - a + 1};
  return window.__hl;
}

function hlInto(t, code){ return paintHl(t, code, null); }

function previewKindOf(name){
  const ext = String(name || "").split(".").pop().toLowerCase();
  if (ext === "md" || ext === "markdown") return "md";
  if (ext === "html" || ext === "htm") return "html";
  return "";
}

function mdSafeUrl(u){
  const s = String(u || "").trim();
  return /^(javascript|vbscript|data:text\/html)/i.test(s) ? "#" : s;
}

function mdInline(text){
  let s = esc(String(text || ""));
  const codes = [];
  s = s.replace(/`([^`]+)`/g, (m, t) => {
    codes.push(t);
    return "\u0000C" + (codes.length - 1) + "\u0000";
  });
  s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g,
    (m, alt, u) => '<img src="' + mdSafeUrl(u) + '" alt="' + alt + '">');
  s = s.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g,
    (m, txt, u) => '<a href="' + mdSafeUrl(u) + '" target="_blank" rel="noopener noreferrer">' + txt + '</a>');
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/__([^_]+)__/g, "<strong>$1</strong>");
  s = s.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  s = s.replace(/\*([^*\n]+)\*/g, "<em>$1</em>");
  s = s.replace(/_([^_\n]+)_/g, "<em>$1</em>");
  s = s.replace(/\u0000C(\d+)\u0000/g, (m, i) => "<code>" + codes[+i] + "</code>");
  return s;
}

function renderMarkdown(src){
  const lines = String(src || "").replace(/\r\n?/g, "\n").split("\n");
  const out = [];
  let i = 0, list = "";
  const closeList = () => { if (list){ out.push("</" + list + ">"); list = ""; } };
  const blockStart = (ln) => /^\s*(#{1,6}\s|>\s?|```|~~~|[-*+]\s|\d+\.\s|---|\*\*\*|___)/.test(ln);
  while (i < lines.length){
    const line = lines[i];
    const fence = line.match(/^\s*(```+|~~~+)\s*([A-Za-z0-9_+.-]*)/);
    if (fence){
      closeList();
      const mark = fence[1].charAt(0), lang = fence[2] || "";
      const body = [];
      i++;
      while (i < lines.length && !new RegExp("^\\s*" + mark + "{3,}").test(lines[i])) body.push(lines[i++]);
      if (i < lines.length) i++;
      out.push('<pre><code' + (lang ? ' class="language-' + esc(lang) + '"' : "") + '>' +
               esc(body.join("\n")) + '</code></pre>');
      continue;
    }
    if (!line.trim()){ closeList(); i++; continue; }
    const h = line.match(/^\s*(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (h){ closeList(); const n = h[1].length; out.push("<h" + n + ">" + mdInline(h[2]) + "</h" + n + ">"); i++; continue; }
    if (/^\s*(?:---|\*\*\*|___)\s*$/.test(line)){ closeList(); out.push("<hr>"); i++; continue; }
    if (/^\s*>\s?/.test(line)){
      closeList();
      const q = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) q.push(lines[i++].replace(/^\s*>\s?/, ""));
      out.push("<blockquote>" + renderMarkdown(q.join("\n")) + "</blockquote>");
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line)){
      if (list !== "ul"){ closeList(); out.push("<ul>"); list = "ul"; }
      out.push("<li>" + mdInline(line.replace(/^\s*[-*+]\s+/, "")) + "</li>"); i++; continue;
    }
    if (/^\s*\d+\.\s+/.test(line)){
      if (list !== "ol"){ closeList(); out.push("<ol>"); list = "ol"; }
      out.push("<li>" + mdInline(line.replace(/^\s*\d+\.\s+/, "")) + "</li>"); i++; continue;
    }

    if (line.indexOf("|") >= 0 && i + 1 < lines.length &&
        /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(lines[i + 1]) && lines[i + 1].indexOf("-") >= 0){
      closeList();
      const cells = (ln) => ln.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map(x => x.trim());
      const head = cells(line);
      i += 2;
      let html = "<table><thead><tr>" + head.map(x => "<th>" + mdInline(x) + "</th>").join("") + "</tr></thead><tbody>";
      while (i < lines.length && lines[i].trim() && lines[i].indexOf("|") >= 0){
        html += "<tr>" + cells(lines[i++]).map(x => "<td>" + mdInline(x) + "</td>").join("") + "</tr>";
      }
      html += "</tbody></table>";
      out.push(html);
      continue;
    }
    closeList();
    const para = [line.trim()];
    i++;
    while (i < lines.length && lines[i].trim() && !blockStart(lines[i]) &&
           !(lines[i].indexOf("|") >= 0 && i + 1 < lines.length &&
             /^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$/.test(lines[i + 1]))){
      para.push(lines[i++].trim());
    }
    out.push("<p>" + para.map(mdInline).join(" ") + "</p>");
  }
  closeList();
  return out.join("\n") || '<p class="pv-empty">（空文件）</p>';
}

function previewVars(){
  const cs = getComputedStyle(document.documentElement);
  return ["--bg","--panel","--panel2","--fg","--fg2","--dim","--accent","--line","--line2","--code-bg","--hover","--fill"]
    .map(n => n + ":" + (cs.getPropertyValue(n) || "")).join(";");
}

function previewDocument(t, base){
  if (!t) return "";
  const kind = t.previewKind || previewKindOf(t.name);
  const b = String(base || "");
  if (kind === "md"){
    const css = ":root{" + previewVars() + "}" +
      "html,body{margin:0;background:var(--bg);color:var(--fg)}" +
      "body{padding:24px 30px;font:14px/1.75 -apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif}" +
      ".pv-body{max-width:980px;margin:0 auto;word-wrap:break-word}" +
      "h1,h2,h3,h4,h5,h6{line-height:1.35;margin:1.4em 0 .55em;color:var(--fg)}" +
      "h1{font-size:2em;border-bottom:1px solid var(--line2);padding-bottom:.3em}" +
      "h2{font-size:1.55em;border-bottom:1px solid var(--line2);padding-bottom:.22em}" +
      "p{margin:.7em 0}a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}" +
      "code{font-family:Consolas,'Cascadia Code',monospace;font-size:.92em;background:var(--code-bg);padding:.12em .35em;border-radius:5px}" +
      "pre{background:var(--code-bg);border:1px solid var(--line2);border-radius:10px;padding:14px 16px;overflow:auto}" +
      "pre code{background:none;padding:0}" +
      "blockquote{margin:.9em 0;padding:.2em 1em;border-left:3px solid var(--accent);color:var(--fg2);background:var(--panel2)}" +
      "table{border-collapse:collapse;margin:1em 0;width:100%}th,td{border:1px solid var(--line2);padding:6px 10px;text-align:left}" +
      "th{background:var(--panel2)}img{max-width:100%;height:auto;border-radius:6px}" +
      "hr{border:0;border-top:1px solid var(--line2);margin:1.5em 0}.pv-empty{color:var(--dim)}";
    const head = '<!doctype html><html><head><meta charset="utf-8">' +
      (b ? '<base href="' + esc(b) + '">' : "") +
      '<meta name="viewport" content="width=device-width,initial-scale=1"><style>' + css + '</style></head>';
    return head + '<body><div class="pv-body">' + renderMarkdown(t.text) + '</div></body></html>';
  }
  let raw = String(t.text || "");
  if (!b) return raw;
  const tag = '<base href="' + esc(b) + '">';
  if (/<head[^>]*>/i.test(raw)) return raw.replace(/<head[^>]*>/i, m => m + tag);
  if (/<html[^>]*>/i.test(raw)) return raw.replace(/<html[^>]*>/i, m => m + "<head>" + tag + "</head>");
  return tag + raw;
}

const MossFilePage = {
  name: "moss-file-page",
  props: {
    t: {type: Object, required: true},
    active: {type: Boolean, default: false},
  },
  template: `
<div class="fmpage" :class="{on: active}" :data-page="t.rel">
  <div class="outbar">
    <span :style="'color:' + meta.c + ';display:flex'" v-html='ico(meta.i, "i")'></span>
    <span class="mono">{{ t.rel }}</span>
    
    <span v-if="t.encodingNote" class="encnote">{{ t.encodingNote }}</span>
    <span class="dirtydot" :hidden="!dirty" title="有未保存的改动"></span>
    <span style="flex:1"></span>
    <button v-if="canPreview && !previewOn" class="iconbtn b-preview" title="浏览模式（渲染 Markdown / HTML）"
            v-html='ico("eye", "i")' @click="togglePreview"></button>
    <button v-if="canPreview && previewOn" class="iconbtn b-preview on" title="代码模式（继续编辑）"
            v-html='ico("code", "i")' @click="togglePreview"></button>
    <button class="iconbtn b-save" title="保存（Ctrl+S）" :disabled="!dirty"
            v-html='ico("save", "i")' @click="save"></button>
    <button class="iconbtn b-revert" title="放弃改动，重新读一遍"
            v-html='ico("undo-2", "i")' @click="revert"></button>
    <button class="iconbtn b-default" title="用系统默认程序打开"
            v-html='ico("external-link", "i")' @click="openDefault"></button>
    <button class="iconbtn b-reveal" title="在资源管理器里显示"
            v-html='ico("folder-open", "i")' @click="reveal"></button>
    <button class="iconbtn b-close" title="关闭这个选项卡"
            v-html='ico("x", "i")' @click="close"></button>
  </div>
  <div class="note" v-if="note" v-html="note"></div>
  <div class="editor" v-show="!previewOn">
    <pre aria-hidden="true" ref="pre"><code class="hljs" ref="code"></code></pre>
    <textarea spellcheck="false" wrap="off" ref="ta" :readonly="!!t.binary"
              :value="t.text" @input="onInput" @scroll="onScroll"
              @keydown="onKeydown"></textarea>
    <div class="gutter" ref="gutter" aria-hidden="true"></div>
  </div>
  <div class="previewpane" v-if="previewOn">
    <iframe class="preview-frame" :srcdoc="previewDoc" title="浏览模式"
            sandbox="allow-scripts allow-same-origin allow-forms allow-modals allow-popups"></iframe>
  </div>
</div>`,
  data(){
    return {_raf: 0};              
  },
  watch: {
    "t.text"(){ this.scheduleHl(); },

    active(v){ if (v){ this.scheduleHl(); if (this.previewOn) this.ensurePreview(); } },
    "t.preview"(v){ if (v) this.ensurePreview(); },

    "t.jump"(v){ if (v) this.$nextTick(() => this.jumpTo(v.line)); },
  },
  computed: {
    meta(){ return extOf({name: this.t.name, ext: (this.t.name.split(".").pop() || "").toLowerCase()}); },
    dirty(){ return isDirty(this.t); },
    canPreview(){ return !!this.t.previewKind && !this.t.binary; },
    previewOn(){ return !!this.t.preview && this.canPreview; },
    previewDoc(){ return this.previewOn ? previewDocument(this.t, this.t.previewBase) : ""; },
    note(){
      if (this.t.binary) return ico("binary", "i") + " 二进制文件，编辑不了；要看就用「默认程序打开」";
      if (this.t.note) return ico("alert-triangle", "i") + " " + this.t.note;
      if (this.t.factory) return ico("alert-triangle", "i") +
          " 这是出厂件（system/）—— 能改，但将来升级时会被整体替换";
      return "";
    },
  },
  mounted(){
    this.homeScroll();
    this.scheduleHl();
    if (this.previewOn) this.ensurePreview();

  },
  beforeUnmount(){
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = 0;
  },
  methods: {
    hlWindow(){
      const ta = this.$refs.ta, pre = this.$refs.pre;
      if (!ta) return null;
      const cs = pre ? getComputedStyle(pre) : null;
      const lh = (cs && parseFloat(cs.lineHeight)) || 20;
      const first = Math.max(0, Math.floor((ta.scrollTop || 0) / lh));
      const last = first + Math.ceil((ta.clientHeight || 0) / lh) + 1;
      return {first: first, last: last};
    },

    scheduleHl(){
      if (this._raf) return;
      this._raf = requestAnimationFrame(() => {
        this._raf = 0;
        this.paintHl();
      });
    },
    paintHl(){
      const code = this.$refs.code;
      if (!code) return;
      window.__hlWin = this.hlWindow();          
      paintHl(this.t, code, window.__hlWin);
      this.paintGutter();                        

      this.syncScroll();
    },

    paintGutter(){
      const g = this.$refs.gutter;
      if (!g) return;
      const text = this.t.text || "";
      const n = text.length ? text.split("\n").length : 1;
      if (this._gn !== n){
        this._gn = n;
        let s = "";
        for (let i = 1; i <= n; i++) s += i + "\n";
        g.textContent = s;
      }
      this.syncGutter();
    },

    syncGutter(){
      const g = this.$refs.gutter, ta = this.$refs.ta;
      if (g && ta) g.scrollTop = ta.scrollTop || 0;
    },

    syncScroll(){
      const ta = this.$refs.ta, pre = this.$refs.pre;
      if (!ta || !pre || !ta.clientHeight) return;
      pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft;
      this.syncGutter();
    },

    homeScroll(){
      const ta = this.$refs.ta;
      if (!ta) return;
      if (!ta.readOnly) ta.setSelectionRange(0, 0);
      ta.scrollTop = 0; ta.scrollLeft = 0;
      this.syncScroll();
    },

    jumpTo(line){
      const ta = this.$refs.ta;
      const lines = String(this.t.text || "").split("\n");
      const n = Math.max(1, Math.min(line | 0 || 1, lines.length));
      let off = 0;
      for (let i = 0; i < n - 1; i++) off += lines[i].length + 1;
      if (ta){
        if (!ta.readOnly){
          ta.setSelectionRange(off, off + (lines[n - 1] || "").length);
          ta.focus();
        }
        const cs = getComputedStyle(this.$refs.pre || ta);
        const lh = (cs && parseFloat(cs.lineHeight)) || 20;
        ta.scrollTop = Math.max(0, (n - 1) * lh - (ta.clientHeight || 0) / 2 + lh / 2);
        ta.scrollLeft = 0;
      }
      this.syncScroll();
      this.scheduleHl();
    },
    onInput(ev){
      this.t.text = ev.target.value;
      this.scheduleHl();
    },
    onScroll(){
      this.syncScroll();

      this.scheduleHl();
    },
    onKeydown(ev){
      const ta = this.$refs.ta;
      if (ev.key === "Tab"){
        ev.preventDefault();
        const p = ta.selectionStart;
        ta.value = ta.value.slice(0, p) + "    " + ta.value.slice(ta.selectionEnd);
        ta.selectionStart = ta.selectionEnd = p + 4;
        this.t.text = ta.value; this.paintHl();
      }
      if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "s"){
        ev.preventDefault(); fmSave(this.t);
      }
    },

    async ensurePreview(){
      const t = this.t;
      if (!t || !this.canPreview || t.previewBase || t._pvLoading) return;
      t._pvLoading = true;
      try{
        const got = await pywebview.api.fs_preview_url(t.rel);
        if (got && got.ok){ t.previewBase = got.base || ""; }
        else if (got && got.msg){ toast("预览资源加载不了：" + got.msg, true); }
      }catch(e){ toast("预览资源加载不了：" + (e && e.message ? e.message : e), true); }
      finally { t._pvLoading = false; }
    },
    togglePreview(){
      this.t.preview = !this.t.preview;
      if (this.t.preview) this.ensurePreview();
      fmRender();

      this.$nextTick(() => this.scheduleHl());
    },

    save(){ fmSave(this.t); },
    revert(){
      const t = this.t;
      askConfirm("放弃改动", "“" + t.name + "” 重新从磁盘读一遍，没保存的改动会丢。确定吗？", async () => {
        const r = await pywebview.api.fs_read(t.rel);
        if (!r.ok){ toast("✗ " + r.msg, true); return; }
        t.text = r.text || ""; t.original = r.text || "";

        this.$nextTick(() => this.scheduleHl());
      });
    },
    openDefault(){
      pywebview.api.fs_open_default(this.t.rel).then(r => toast(r.msg, !r.ok));
    },
    reveal(){
      pywebview.api.fs_reveal(this.t.rel).then(r => toast(r.msg, !r.ok));
    },
    close(){ fmClosePage(this.t.rel); },
  },
};

const MossFileBrowse = {
  name: "moss-file-browse",
  props: {
    s: {type: Object, required: true},
    active: {type: Boolean, default: false},
  },
  template: `
<div class="fmpage" :class="{on: active}" data-page="__browse__">
  <div class="fbnav">
    
    <button class="iconbtn b-home" :title="homeTitle" v-html='ico("home", "i")'
            @click="fmHome()"></button>
    <button class="iconbtn b-back" title="后退" :disabled="s.hpos <= 0"
            v-html='ico("corner-up-left", "i")' @click="fmBack()"></button>
    <button class="iconbtn b-fwd" title="前进" :disabled="s.hpos >= s.hist.length - 1"
            v-html='ico("corner-up-right", "i")' @click="fmFwd()"></button>
    <button class="iconbtn b-up" title="向上一级（Backspace）" :disabled="atTop"
            v-html='ico("arrow-up", "i")' @click="fmUp()"></button>
    <button class="iconbtn b-reload" title="刷新（F5）" v-html='ico("refresh-cw", "i")'
            @click="fmRefresh()"></button>
    
    <button class="iconbtn b-search" :class="{on: st.on}"
            title="按内容搜当前目录（Ctrl+F）"
            v-html='ico("search", "i")' @click="fmSearchOpen()"></button>
    

    <div class="crumbs"><template v-for="(c, i) in crumbs" :key="i"
      ><span v-if="i" class="sep">›</span
      ><span v-if="c.here" class="here">{{ c.label }}</span
      ><span v-else class="seg" :data-rel="c.rel" @click="fmGoto(c.rel)">{{ c.label }}</span
    ></template></div>
    <div class="layers">
      <span v-if="s.histCtx" class="hint"
            style="align-self:center;margin-top:0;white-space:nowrap"
            >历史调用所在的目录{{ hereLayer === "abs" ? "（在 user_data / system 之外）" : "" }}</span>
      <template v-else-if="!s.pkg">
        <button class="iconbtn" :class="{on: hereLayer === 'user'}" data-go="user"
                title="user_data 根目录" @click="fmGoto('user')">user_data</button>
        <button class="iconbtn" :class="{on: hereLayer === 'system'}" data-go="system"
                title="system 根目录" @click="fmGoto('system')">system</button>
      </template>
      <template v-else>
        <button v-if="s.layers.user" class="iconbtn" :class="{on: hereLayer === 'user'}"
                :data-go="cand.user"
                :title="'user_data 里这个包的目录（' + cand.user + '）'"
                @click="fmGoto(cand.user)">user_data</button>
        <button v-if="s.layers.system" class="iconbtn" :class="{on: hereLayer === 'system'}"
                :data-go="cand.system"
                :title="'system 里这个包的目录（' + cand.system + '）'"
                @click="fmGoto(cand.system)">system</button>
        <span v-if="!s.layers.user && !s.layers.system" class="hint"
              style="align-self:center;margin-top:0;white-space:nowrap">这个包只在当前目录里</span>
      </template>
    </div>
  </div>

  
  <div class="fbsearch" v-if="st.on">
    <span class="fbs-scope" title="搜这个目录和它的子目录">
      <span class="ic" v-html='ico("folder-search", "i")'></span
      ><span class="p">{{ s.rel || "user" }}</span>
    </span>
    <input class="fbs-q" v-model="st.q" spellcheck="false" autocomplete="off"
           placeholder="按内容搜…（回车开始）"
           @keydown.enter.prevent="runSearch" @keydown.esc.prevent="fmSearchClose()">
    <button class="fbs-t" :class="{on: st.cs}" title="区分大小写" @click="toggleOpt('cs')">Aa</button>
    <button class="fbs-t" :class="{on: st.word}" :disabled="st.re"
            title="全词匹配（不匹配词中间那一段）" @click="toggleOpt('word')">全词</button>
    <button class="fbs-t" :class="{on: st.re}" title="按正则表达式搜" @click="toggleOpt('re')">.*</button>
    <button class="fbs-go" :disabled="st.busy" @click="runSearch">{{ st.busy ? "搜索中…" : "搜索" }}</button>
    <button class="iconbtn b-search-x" title="关掉检索（Esc）" v-html='ico("x", "i")'
            @click="fmSearchClose()"></button>
  </div>

  <div class="fbtools">
    <button class="iconbtn b-newdir" title="新建文件夹" v-html='ico("folder-plus", "i")'
            @click="fmCmd('newdir')"></button>
    <button class="iconbtn b-newfile" title="新建文件" v-html='ico("file-plus", "i")'
            @click="fmCmd('newfile')"></button>
    <button class="iconbtn b-rename" title="重命名（F2）" :disabled="selN !== 1"
            v-html='ico("pencil", "i")' @click="fmCmd('rename')"></button>
    <button class="iconbtn warn b-del" title="删除（Delete）→ 挪进回收站" :disabled="!selN"
            v-html='ico("trash-2", "i")' @click="fmCmd('del')"></button>
    <span class="gap"></span>
    <button class="iconbtn b-copy" title="复制（Ctrl+C）" :disabled="!selN"
            v-html='ico("copy", "i")' @click="fmCmd('copy')"></button>
    <button class="iconbtn b-cut" title="剪切（Ctrl+X）" :disabled="!selN"
            v-html='ico("scissors", "i")' @click="fmCmd('cut')"></button>
    <button class="iconbtn b-paste" title="粘贴（Ctrl+V）" :disabled="!s.clip"
            v-html='ico("clipboard-paste", "i")' @click="fmCmd('paste')"></button>
    <span class="gap"></span>
    <button class="iconbtn b-default" title="用默认程序打开选中的东西" :disabled="!selN"
            v-html='ico("external-link", "i")' @click="fmCmd('default')"></button>
    <button class="iconbtn b-opendir" title="用 Windows 资源管理器打开这个文件夹"
            v-html='ico("folder-open", "i")' @click="fmCmd('opendir')"></button>
  </div>

  <div class="fbwrap" @contextmenu="wrapCtx">
    <table class="fb" v-if="!searchView"><thead><tr>
      <th data-sort="name" @click="sortBy('name')">名称<span v-if="s.sort.key === 'name'"
          class="arrow">{{ s.sort.dir === 1 ? "▲" : "▼" }}</span></th>
      <th data-sort="mtime" style="width:150px" @click="sortBy('mtime')">修改日期<span
          v-if="s.sort.key === 'mtime'" class="arrow">{{ s.sort.dir === 1 ? "▲" : "▼" }}</span></th>
      <th data-sort="type" style="width:110px" @click="sortBy('type')">类型<span
          v-if="s.sort.key === 'type'" class="arrow">{{ s.sort.dir === 1 ? "▲" : "▼" }}</span></th>
      <th data-sort="size" style="width:100px" @click="sortBy('size')">大小<span
          v-if="s.sort.key === 'size'" class="arrow">{{ s.sort.dir === 1 ? "▲" : "▼" }}</span></th>
    </tr></thead><tbody>
      <tr v-if="!rows.length"><td colspan="4" class="dim"
          style="padding:22px;text-align:center">这个文件夹是空的</td></tr>
      <tr v-for="(e, idx) in rows" :key="e.rel" class="row"
          :class="[{sel: s.sel.has(e.rel)}, bkDiffRow(e.rel)]"
          :data-rel="e.rel" :data-dir="e.dir ? 1 : 0" :title="bkDiffWhy(e.rel)"
          @click="rowClick(e, idx, $event)" @dblclick="rowDbl(e)"
          @contextmenu="rowCtx(e, idx, $event)">
        <td class="nmcell" v-html="fileIconHTML(e, false) + '<span>' + esc(e.name) + '</span>'"></td>
        <td class="dim">{{ fmtTime(e.mtime) }}</td>
        <td class="dim">{{ typeLabel(e) }}</td>
        <td class="num">{{ e.dir ? "" : humanSize(e.size) }}<span
            class="df-mark">{{ bkDiffMark(e.rel) }}</span><button v-if="!e.dir && bkHasSnap(e.rel)"
            class="iconbtn cmpbtn" title="和快照里那一份对比（弹出来两栏看）"
            @click.stop="cmp(e)" v-html='ico("git-branch", "i")'></button></td>
      </tr>
    </tbody></table>

    
    <div class="fbres" v-else>
      <div class="fbres-empty bad" v-if="st.err">{{ st.err }}</div>
      <div class="fbres-empty" v-else-if="st.busy">搜索中…</div>
      <div class="fbres-empty" v-else-if="!st.files.length">没有找到 “{{ st.q }}”{{ st.note ? "　（" + st.note + "）" : "" }}</div>
      <template v-else>
        <div class="fbres-file" v-for="f in st.files" :key="f.rel">
          <div class="fbres-head" :title="f.rel" @click="toggleFile(f)">
            <span class="caret">{{ st.open[f.rel] ? "▾" : "▸" }}</span>
            <span class="fname" v-html="fileIconHTML({name: f.name, ext: f.ext}, false) + '<span>' + esc(f.name) + '</span>'"></span>
            <span class="fdir">{{ f.dir }}</span>
            <span class="fcount">{{ f.n }}{{ f.more ? "+" : "" }} 行</span>
          </div>
          <template v-if="st.open[f.rel]">
            <div class="fbres-hit" v-for="(h, i) in f.hits" :key="i"
                 :title="'打开并跳到第 ' + h.line + ' 行'" @click="jump(f, h)">
              <span class="ln">{{ h.line }}</span>
              <span class="tx" v-html="hitHTML(h)"></span>
            </div>
          </template>
        </div>
      </template>
      <div class="fbres-more" v-if="st.truncated">结果没搜完：{{ cutText }}。换个更具体的词，或者进到更里面那层目录再搜。</div>
    </div>
  </div>

  <div class="fbstatus"><span class="info">{{ searchView ? searchInfo : infoText }}</span
    ><span class="clipinfo">{{ clipText }}</span></div>
</div>`,
  computed: {
    pkgsRev(){ return FM.rev; },
    segs(){ return (this.s.rel || "").split("/"); },
    crumbs(){
      let acc = "";
      return this.segs.map((seg, i) => {
        acc = i === 0 ? seg : acc + "/" + seg;
        const label = i === 0
          ? (seg === "user" ? "user_data" : (seg === "system" ? "system"
             : (seg === "abs" ? "此电脑" : seg)))
          : seg;
        return {label: label, rel: acc, here: (i === this.segs.length - 1) || (i === 0 && seg === "abs")};
      });
    },
    rows(){ return fmSorted(this.s); },
    hereLayer(){ return (this.s.rel || "").split("/")[0]; },
    homeTitle(){
      return isHistKey(FM.ctx) ? "回到这条调用当初的目录" : "回到默认目录（这个包的目录）";
    },

    atTop(){ return this.segs.length <= 1; },
    selN(){ return this.s.sel.size; },

    st(){ return this.s.search || fmSearchFresh(); },
    searchView(){ return !!this.st.on && !!this.st.ran; },

    cutText(){
      const st = this.st;
      const nm = r => (r === "user" ? "user_data" : (r === "system" ? "system" : r));
      const one = "一次最多扫 " + (st.scanned || 0) + " 个文件、回 " + (st.nHits || 0) + " 行命中";
      const cut = (st.cut || []).map(nm);
      return cut.length ? (one + "；" + cut.join("、") + " 还没扫完") : one;
    },
    searchInfo(){
      const st = this.st;
      if (st.busy) return "搜索中…";
      if (st.err) return st.err;
      let t = st.nFiles + " 个文件里 " + st.nHits + " 行命中" +
              " · 扫了 " + st.scanned + " 个文件";
      if (st.skipped) t += "（跳过 " + st.skipped + " 个非文本 / 太大）";
      t += " · " + st.ms + " ms · 范围 " + (this.s.rel || "user");
      if (st.note) t += " · " + st.note;
      if (st.truncated) t += " · 有地方没扫完";
      return t;
    },
    cand(){
      void this.pkgsRev;                    
      return this.s.pkg ? fmLayerRels(this.s.pkg) : {user: "", system: ""};
    },
    infoText(){
      const s = this.s, rows = this.rows, n = s.sel.size;
      const bytes = rows.filter(e => s.sel.has(e.rel) && !e.dir)
                        .reduce((a, e) => a + (e.size || 0), 0);
      return rows.length + " 项" +
        (n ? " · 选中 " + n + " 项" + (bytes ? "（" + humanSize(bytes) + "）" : "") : "") +
        " · " + (s.path || s.rel);
    },
    clipText(){
      const c = this.s.clip;
      return c ? ("剪贴板：" + c.rels.length + " 项" + (c.cut ? "（剪切）" : "（复制）")) : "";
    },
  },
  methods: {
    bkDiffRow: rel => bkDiffRow(rel),
    bkDiffWhy: rel => bkDiffWhy(rel),
    bkDiffMark: rel => bkDiffMark(rel),
    bkHasSnap: rel => bkHasSnap(rel),
    cmp(e){ bkCompareOpen(e.rel); },

    runSearch(){ fmSearchRun(); },
    toggleOpt(k){ fmSearchOpt(k); },
    toggleFile(f){
      const st = this.st;
      st.open[f.rel] = !st.open[f.rel];
    },
    jump(f, h){ fmSearchJump(f.rel, h.line); },

    hitHTML(h){
      const text = String(h.text || "");
      const cols = (h.cols || []).slice().sort((a, b) => a[0] - b[0]);
      let out = "", at = 0;
      cols.forEach(c => {
        const s0 = Math.max(0, c[0] | 0), len = Math.max(1, c[1] | 0);
        if (s0 < at || s0 > text.length) return;     
        out += esc(text.slice(at, s0)) + "<mark>" + esc(text.slice(s0, s0 + len)) + "</mark>";
        at = s0 + len;
      });
      return out + esc(text.slice(at));
    },

    sortBy(k){
      const s = this.s;
      s.sort = {key: k, dir: (s.sort.key === k ? -s.sort.dir : 1)};
    },

    rowClick(e, idx, ev){
      const s = this.s, rows = this.rows;
      if (ev.ctrlKey || ev.metaKey){
        s.sel.has(e.rel) ? s.sel.delete(e.rel) : s.sel.add(e.rel);
        s.lastIdx = idx;
      } else if (ev.shiftKey && s.lastIdx >= 0){
        const a = Math.min(s.lastIdx, idx), b = Math.max(s.lastIdx, idx);
        s.sel.clear();
        for (let i = a; i <= b; i++) s.sel.add(rows[i].rel);
      } else {
        s.sel.clear(); s.sel.add(e.rel); s.lastIdx = idx;
      }
    },
    rowDbl(e){ e.dir ? fmGoto(e.rel) : fmOpenPage(e.rel); },

    rowCtx(e, idx, ev){
      ev.preventDefault();
      const s = this.s;
      if (!s.sel.has(e.rel)){
        s.sel.clear(); s.sel.add(e.rel); s.lastIdx = idx;
      }
      showCtx(ev.clientX, ev.clientY, e.rel);
    },

    wrapCtx(ev){
      if (this.searchView) return;                 
      if (ev.target.closest("tr.row")) return;
      ev.preventDefault();
      this.s.sel.clear();
      showCtx(ev.clientX, ev.clientY, null);
    },
  },
};

const MossFileManager = {
  name: "moss-file-manager",

  components: {MossFileBrowse: MossFileBrowse, MossFilePage: MossFilePage},
  template: `
<div class="fm-main">
  <div id="fm-bar">
    <button class="fmtab" :class="{on: s.active === '__browse__'}" data-fm="__browse__"
            title="目录浏览（这一页不能关）" @click="s.active = '__browse__'">
      <span v-html='ico("folder", "i")'></span><span class="fname">{{ tabLabel }}</span>
    </button>
    <button v-for="t in s.tabs" :key="t.rel" class="fmtab" :class="{on: s.active === t.rel}"
            :data-fm="t.rel" :title="t.rel" @click="s.active = t.rel">
      <span :style="'color:' + tabIcon(t).c + ';display:flex'" v-html='ico(tabIcon(t).i, "i")'></span>
      <span class="fname">{{ t.name }}</span>
      <span v-if="isDirty(t)" class="fdot" title="有未保存的改动"></span>
      <span class="x" :data-close="t.rel" title="关闭" @click.stop="fmClosePage(t.rel)">×</span>
    </button>
  </div>
  <div class="fmwrap" id="fm-body">
    <moss-file-browse :s="s" :active="s.active === '__browse__'"></moss-file-browse>
    <moss-file-page v-for="t in s.tabs" :key="t.rel" :t="t"
                    :active="s.active === t.rel"></moss-file-page>
  </div>
</div>
<moss-file-snap></moss-file-snap>`,
  computed: {
    s(){ return FM.st[FM.ctx || "__all__"] || fmState(FM.ctx); },
    tabLabel(){
      void FM.rev;              
      return fmLabel(FM.ctx);
    },
  },
  methods: {
    tabIcon(t){
      return extOf({name: t.name, ext: (t.name.split(".").pop() || "").toLowerCase()});
    },
  },
};

const FM_TEMPLATE_HELPERS = {
  ico: ico, esc: esc, isDirty: isDirty,
  fileIconHTML: fileIconHTML, fmtTime: fmtTime, typeLabel: typeLabel, humanSize: humanSize,
  fmGoto: fmGoto, fmHome: fmHome, fmBack: fmBack, fmFwd: fmFwd, fmUp: fmUp,
  fmRefresh: fmRefresh, fmCmd: fmCmd, fmClosePage: fmClosePage,
  fmSearchOpen: fmSearchOpen, fmSearchClose: fmSearchClose,
};

let _fmApp = null;

function fmApp(){
  if (!_fmApp){
    const host = document.getElementById("pane-file");
    if (!host) return null;

    _fmApp = mountVue(MossFileManager, host, FM_TEMPLATE_HELPERS);
  }
  return _fmApp;
}
function fmRender(){ const a = fmApp(); if (a) a.$forceUpdate(); }
function fmPaintBar(){ const a = fmApp(); if (a) a.$forceUpdate(); }

function fmFocusActiveSoon(){
  const go = () => {
    const page = document.querySelector("#fm-body .fmpage.on");
    const ta = page && page.querySelector("textarea");
    if (ta && !ta.readOnly) ta.focus();
  };
  const a = fmApp();
  if (a) a.$nextTick(go); else go();
}

function showCtx(x, y, rel){
  const s = fmState(FM.ctx);
  const has = !!rel, one = s.sel.size === 1;
  const items = has
    ? [["folder-open", "打开", "open"],
       ["external-link", "用默认程序打开", "default"],
       ["app-window", "在资源管理器里显示", "reveal"],
       ["sep"],
       ["copy", "复制", "copy"], ["scissors", "剪切", "cut"],
       ["sep"],
       ["pencil", "重命名", "rename", one],
       ["trash-2", "删除（进回收站）", "del"]]
    : [["file-plus", "新建文件", "newfile"], ["folder-plus", "新建文件夹", "newdir"],
       ["sep"], ["clipboard-paste", "粘贴", "paste", !!s.clip],
       ["refresh-cw", "刷新", "reload"]];
  const menu = $("#ctxmenu");
  menu.innerHTML = items.map(it => {
    if (it[0] === "sep") return '<div class="sep"></div>';
    const dis = it[3] === false;
    return '<div class="mi' + (dis ? " dis" : "") + '" data-act="' + it[2] + '">' +
      ico(it[0], "i") + '<span>' + esc(it[1]) + '</span></div>';
  }).join("");
  menu.hidden = false;
  const w = menu.offsetWidth, h = menu.offsetHeight;
  menu.style.left = Math.min(x, window.innerWidth - w - 8) + "px";
  menu.style.top = Math.min(y, window.innerHeight - h - 8) + "px";
  menu.querySelectorAll(".mi").forEach(mi => {
    if (mi.classList.contains("dis")) return;
    mi.onclick = () => { hideCtx(); fmCmd(mi.dataset.act); };
  });
}
function hideCtx(){ $("#ctxmenu").hidden = true; }

function fmTargetDir(){
  const s = fmState(FM.ctx);
  const selArr = [...s.sel];
  if (selArr.length === 1){
    const e = s.entries.find(x => x.rel === selArr[0]);
    if (e && e.dir) return e.rel;
  }
  return s.rel;
}
async function fmCmd(act){
  const s = fmState(FM.ctx);
  const selArr = [...s.sel];
  if (act === "open"){
    if (selArr.length === 1){
      const e = s.entries.find(x => x.rel === selArr[0]);
      if (e && e.dir) fmGoto(e.rel); else if (e) fmOpenPage(e.rel);
    }
    return;
  }
  if (act === "default" || act === "reveal"){
    if (!selArr.length) return;
    const r = act === "default" ? await pywebview.api.fs_open_default(selArr[0])
                                : await pywebview.api.fs_reveal(selArr[0]);
    toast(r.msg, !r.ok);
    return;
  }
  if (act === "opendir"){
    const r = await pywebview.api.fs_open_default(s.rel);
    toast(r.msg, !r.ok);
    return;
  }
  if (act === "copy" || act === "cut"){
    if (!selArr.length) return;
    s.clip = {rels: selArr, cut: act === "cut"};
    fmRender();
    toast((act === "cut" ? "已剪切 " : "已复制 ") + selArr.length + " 项");
    return;
  }
  if (act === "paste"){
    if (!s.clip) return;
    const r = await pywebview.api.fs_copy(s.clip.rels, s.rel, s.clip.cut);
    toast(r.msg, !r.ok);
    if (r.ok && s.clip.cut) s.clip = null;
    fmRefresh();
    if (r.ok && (r.made || []).some(isPkgManifest)) refreshPkgs();   
    return;
  }
  if (act === "newfile" || act === "newdir"){
    const dir = fmTargetDir(), isDir = act === "newdir";
    askText(isDir ? "新建文件夹" : "新建文件", isDir ? "新建文件夹" : "untitled.py", async (name) => {
      const r = isDir ? await pywebview.api.fs_mkdir(dir, name)
                      : await pywebview.api.fs_touch(dir, name);
      toast(r.msg, !r.ok);
      if (r.ok){
        if (dir !== s.rel) await fmGoto(dir, true); else await fmRefresh();
        const s2 = fmState(FM.ctx);
        s2.sel.clear(); s2.sel.add(r.rel);
        if (!isDir) fmOpenPage(r.rel); else fmRender();
        if (isPkgManifest(r.rel)) refreshPkgs();     
      }
    });
    return;
  }
  if (act === "rename"){
    if (selArr.length !== 1){ toast("重命名一次只能一个", true); return; }
    const e = s.entries.find(x => x.rel === selArr[0]);
    askText("重命名", e ? e.name : "", async (name) => {
      const r = await pywebview.api.fs_rename(selArr[0], name);
      toast(r.msg, !r.ok);
      if (r.ok){
        const s2 = fmState(FM.ctx);
        const t = s2.tabs.find(x => x.rel === r.old);
        if (t){ t.rel = r.rel; t.name = r.rel.split("/").pop(); }
        s2.sel.clear(); s2.sel.add(r.rel);
        fmRefresh();
        if (isPkgManifest(r.old) || isPkgManifest(r.rel)) refreshPkgs();
      }
    });
    return;
  }
  if (act === "del"){
    if (!selArr.length) return;
    const names = s.entries.filter(e => s.sel.has(e.rel)).map(e => e.name);
    askConfirm("删除", "把 " + (names.length === 1 ? "“" + names[0] + "”" : names.length + " 项") +
      " 挪进 user_data/trash/（<b>不是永久删除</b>，能拿回来）。确定吗？", async () => {
        const r = await pywebview.api.fs_delete(selArr);
        toast(r.msg, !r.ok);
        if (r.ok){
          const s2 = fmState(FM.ctx);
          s2.tabs = s2.tabs.filter(t => !selArr.some(x => t.rel === x || t.rel.startsWith(x + "/")));
          if (!s2.tabs.some(t => t.rel === s2.active)) s2.active = "__browse__";
          s2.sel.clear();
          fmRefresh();
          if (selArr.some(isPkgManifest)) refreshPkgs();
        }
      });
    return;
  }
  if (act === "reload") fmRefresh();
}

document.addEventListener("keydown", (e) => {
  if ($("#modal").classList.contains("on")) return;
  const typing = /^(INPUT|TEXTAREA)$/.test((e.target.tagName || "").toUpperCase());
  if (tab === "file" && !typing){
    const s = fmState(FM.ctx), k = e.key;
    if (k === "Enter"){ e.preventDefault(); fmCmd("open"); return; }
    if (k === "F2"){ e.preventDefault(); fmCmd("rename"); return; }
    if (k === "Delete"){ e.preventDefault(); fmCmd("del"); return; }
    if (k === "Backspace"){ e.preventDefault(); fmUp(); return; }
    if (k === "F5"){ e.preventDefault(); fmRefresh(); return; }

    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "f"){
      e.preventDefault(); fmSearchOpen(true); return;
    }
    if (k === "Escape"){ hideCtx(); if (fmSearch().on) fmSearchOpen(false); return; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "c"){ e.preventDefault(); fmCmd("copy"); return; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "x"){ e.preventDefault(); fmCmd("cut"); return; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "v"){ e.preventDefault(); fmCmd("paste"); return; }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "w"){
      e.preventDefault();
      if (s.active !== "__browse__") fmClosePage(s.active);
      return;
    }
    if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "a"){
      e.preventDefault();
      s.entries.forEach(x => s.sel.add(x.rel));
      fmRender();
      return;
    }
  }
  if (e.key === "Escape" && $("#modal").classList.contains("on")) closeModal();

  const setBox = $("#settings");
  if (e.key === "Escape" && setBox && setBox.classList.contains("on")) closeSettings();
});
document.addEventListener("click", (e) => { if (!e.target.closest("#ctxmenu")) hideCtx(); });
window.addEventListener("blur", hideCtx);
