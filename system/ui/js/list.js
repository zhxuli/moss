async function toggleVis(p){
  if (isHist(p)) return;                  
  const st = PST[p.id] || {windows: 0, visible: false};
  const r = st.visible ? await pywebview.api.pkg_hide(p.id)
                       : await pywebview.api.pkg_show(p.id);
  toast(r.msg, !r.ok);
  setTimeout(() => refreshPkgState(p), 400);
}

function pkgPollStart(){
  if (pstTimer) return;
  pstTimer = setInterval(refreshAllStates, 2500);
}

let side = "pkg";               

function setSide(which){
  side = which;
  $("#sw-pkg").classList.toggle("on", which === "pkg");
  $("#sw-hist").classList.toggle("on", which === "hist");
  $("#list").hidden = which !== "pkg";
  $("#hist").hidden = which !== "hist";
  $("#btn-newpkg").hidden = which !== "pkg";   
  $("#q").placeholder = which === "pkg" ? "搜索包名 / 说明 / 标签…"
                                        : "搜索历史（名字 / 参数 / 目录）…";
  if (which === "hist") loadHist().then(renderHist); else renderList();
}

let HIST = [];

async function loadHist(){
  try{
    const r = await pywebview.api.hist_list(60);
    HIST = (r && r.ok && r.items) || [];
  }catch(e){ HIST = []; }

  if (curH){
    const k = histKey(curH);
    curH = HIST.find(x => histKey(x) === k) || curH;
  }
}

function histKey(it){ return "hist:" + it.target + (it.args ? " " + it.args : ""); }
function histIconHTML(it, cls){
  const c = cls || "hico";
  if (it.icon_svg){ const s = safeSvg(it.icon_svg); if (s) return '<span class="' + c + '">' + s + '</span>'; }
  if (it.icon) return '<span class="' + c + '"><img src="' + it.icon + '" alt=""></span>';

  const nm = it.name || it.target || "";
  const e = extOf({name: nm, ext: (nm.split(".").pop() || "").toLowerCase()});
  return '<span class="' + c + '" style="color:' + e.c + '">' + ico(e.i, "i") + '</span>';
}

function dirRel(dir){
  const norm = s => String(s || "").replace(/\\/g, "/").replace(/\/+$/, "");
  const d = norm(dir);
  if (!d) return null;
  const dl = d.toLowerCase();
  for (const [key, base] of [["user", norm(DATA.user_data)],
                             ["system", norm(DATA.home) + "/system"]]){
    const bl = base.toLowerCase();
    if (dl === bl) return key;
    if (dl.startsWith(bl + "/")) return key + d.slice(base.length);
  }
  return "abs/" + d;
}
function histDir(it){
  const d = it.cwd || (it.target ? it.target.replace(/[\\/][^\\/]*$/, "") : "");
  return dirRel(d);
}

function renderHist(){
  bumpLists();
  try{ paintSwitchCounts(); }catch(e){}      
  Vue.nextTick(() => { try{ paintHistStats(); }catch(e){} });
}

function paintHistStats(){
  document.querySelectorAll(".hitem").forEach(el => {
    const key = el.dataset.key;
    const box = el.querySelector(".hstat");
    if (!box) return;
    const running = !!RUNS[key];
    el.dataset.state = running ? "running" : "idle";
    const it = HIST.find(x => histKey(x) === key);
    const gone = it && it.exists === false;

    if (gone && !running){
      box.innerHTML = "";
      return;
    }
    box.innerHTML = running
      ? '<button class="ic-run" title="正在跑 —— 点这里停掉它">' + ico("square", "i") + '</button>'
      : '<button class="idle" title="不选中，直接重跑这次调用">' + ico("play", "i") + '</button>';
    const b = box.querySelector("button");
    if (b) b.onclick = (ev) => {
      ev.stopPropagation();                    
      if (running) stopRun(key); else rerunHistByKey(key);
    };
  });
}

function rerunHistByKey(key, args){
  const it = HIST.find(x => histKey(x) === key);
  if (!it) return;

  if (curH !== it) selectHist(it,  true);
  rerunHist(it, args);
}

function selectHist(it, keepTab){
  curH = it; cur = null;
  consoleKey = histKey(it);
  renderList(); renderHist(); renderDetail(); paintConsole();
  if (!keepTab) setTab("detail");
  fmSelect(histKey(it),  true);     
}

async function rerunHist(it, args){
  const key = histKey(it);
  if (RUNS[key]) return;
  const a = args === undefined ? (it.args || "") : args;
  lastRun = {key: key, args: a, label: "moss /" + it.name};
  consoleKey = key;
  setConsole(key, "$ moss /" + it.name + (a ? " " + a : ""), "运行中");

  const r = await pywebview.api.path_start(it.target, it.cwd || "", a);
  if (!r.ok){
    setConsole(key, "$ moss /" + it.name + "\n\n启动失败：" + (r.msg || ""), "启动失败");
    toast("✗ " + (r.msg || "启动失败"), true);
    return;
  }
  const cmd = r.cmd || ("moss /" + it.name);
  setConsole(key, "$ " + cmd + (r.cwd ? "\n# 当前目录：" + r.cwd : ""), "运行中");
  RUNS[key] = {rid: r.run_id, cmd: cmd, timer: null, stopped: false,
               switched: false, tabAtStart: tab};
  paintHistStats();
  paintActions(selObj());
  pollRun(key);
}

function rerunLast(){
  if (!lastRun) return;
  if (lastRun.key) return rerunHistByKey(lastRun.key, lastRun.args);
  const p = DATA.packages.find(x => x.id === lastRun.id);
  if (!p){ toast("找不到 " + PSYM + lastRun.id + " 这个包了", true); return; }
  if (RUNS[p.id]) return;
  startRun(p, lastRun.args);
}

const LISTR = Vue.reactive({rev: 0, ready: false, filt: "all", sort: "name",
                            hfilt: "all", hsort: "time", born: {}, custom: []});

function _ls(k, d){ try{ return localStorage.getItem(k) || d; }catch(e){ return d; } }
function _lsSet(k, v){ try{ localStorage.setItem(k, v); }catch(e){} }

function lastRunOf(id){
  const v = parseInt(_ls("moss.lastrun." + id, "0"), 10) || 0;
  return v;
}
function noteRunning(ids){
  const now = Date.now();
  (ids || []).forEach(id => {
    if (now - lastRunOf(id) > 5000) _lsSet("moss.lastrun." + id, String(now));
  });
}

async function loadBornTimes(){
  const out = {};
  for (const rel of ["system/pkgs", "user/pkgs"]){
    try{
      const r = await pywebview.api.fs_list(rel);
      ((r && r.entries) || []).forEach(e => { if (e.dir) out[e.name] = e.mtime || 0; });
    }catch(e){}
  }
  LISTR.born = out;
  bumpLists();
}

const LB_ICONS = {
  filt:  {all: "layers", system: "package", user: "moss-user"},
  sort:  {name: "list-tree", born: "history", run: "activity", custom: "grip-vertical"},
  hfilt: {all: "layers", path: "file-code", pkg: "package"},
  hsort: {time: "history", name: "list-tree", kind: "file-type"},
};

const LB_LABELS = {
  filt:  {all: "全部", system: "系统", user: "用户"},
  sort:  {name: "名字", born: "加入时间", run: "最后运行", custom: "自定义"},
  hfilt: {all: "全部", path: "路径", pkg: "包"},
  hsort: {time: "时间", name: "名字", kind: "类型"},
};
const LB_LS = {filt: "moss.filt", sort: "moss.sort", hfilt: "moss.hfilt", hsort: "moss.hsort"};

function paintListBars(){
  ["#bar-list", "#bar-hist"].forEach(sel => {
    const bar = $(sel);
    if (!bar) return;

    bar.querySelectorAll(".dd-i").forEach(b => {
      const g = b.dataset.g, v = b.dataset.v;
      if (!g || !v) return;
      const ic = (LB_ICONS[g] || {})[v];
      const lb = (LB_LABELS[g] || {})[v] || v;
      b.innerHTML = ico(ic, "i") + '<span>' + esc(lb) + '</span>' + ico("check", "i dd-chk");
      b.classList.toggle("on", LISTR[g] === v);
    });

    bar.querySelectorAll(".dd-t").forEach(t => {
      const g = t.dataset.dd, v = LISTR[g];
      const ic = (LB_ICONS[g] || {})[v];
      const lb = (LB_LABELS[g] || {})[v] || v;
      t.innerHTML = ico(ic, "i") + '<span>' + esc(lb) + '</span>' + ico("chevron-down", "i caret");
    });
  });
}

function paintBarActs(){
  const put = (sel, ic) => { const b = $(sel); if (b && !b.querySelector("svg")) b.innerHTML = ico(ic, "i"); };
  put("#btn-refresh", "refresh-cw");
  put("#btn-newpkg", "file-plus");
  put("#btn-refresh-h", "refresh-cw");
  put("#btn-openfile", "play-circle");
  const rh = $("#btn-refresh-h"), r = $("#btn-refresh");
  if (rh && r) rh.onclick = () => r.click();          
  const of = $("#btn-openfile");
  if (of) of.onclick = () => openFileAndRun();
}

async function openFileAndRun(){
  let r;
  try{ r = await pywebview.api.pick_file(); }
  catch(e){ toast("挑文件失败：" + (e && e.message || e), true); return; }

  if (!r || !r.ok){ if (r && !r.cancelled && r.msg && r.msg.indexOf("取消") < 0) toast(r.msg, true); return; }
  const p = String(r.path || "");
  const name = p.split(/[\\/]/).pop() || p;
  const cwd = p.replace(/[\\/][^\\/]*$/, "");

  rerunHist({name: name, target: p, cwd: cwd, args: "", ts: new Date().toISOString(),
             kind: "path", key: "__openfile:" + p}, "");
}
function initListBars(){
  LISTR.filt = _ls("moss.filt", "all");    LISTR.sort = _ls("moss.sort", "name");
  LISTR.hfilt = _ls("moss.hfilt", "all");  LISTR.hsort = _ls("moss.hsort", "time");

  document.querySelectorAll(".listbar .dd-i").forEach(b => {
    b.onclick = () => {
      LISTR[b.dataset.g] = b.dataset.v;           
      _lsSet(LB_LS[b.dataset.g] || "moss.lb", b.dataset.v);
      paintListBars();
      bumpLists();
      if (b.dataset.g === "sort") saveListView();          
      if (b.dataset.g === "sort" && b.dataset.v === "born") loadBornTimes();
    };
  });
  paintListBars();
  paintBarActs();
  loadBornTimes();

}

async function loadListView(){
  try{
    const r = await pywebview.api.list_state();
    if (!r || !r.ok) return;
    const known = new Set((DATA && DATA.packages ? DATA.packages : []).map(p => p.id));
    LISTR.custom = Array.isArray(r.ids) ? r.ids.filter(id => known.has(id)) : [];
    if (r.sort) LISTR.sort = r.sort;
    paintListBars(); bumpLists();
  }catch(e){}
}
function saveListView(){
  try{ pywebview.api.list_state_set((LISTR.custom || []).slice(), LISTR.sort); }catch(e){}
}
function bumpLists(){ LISTR.rev++; }

let _pdrag = null;               
let _listDragging = false;

const LISTDR = Vue.reactive({dragId: null});

function _nm(id){
  const p = (DATA.packages || []).find(x => x.id === id);
  return (p && (p.name || p.id)) || id;
}
function _dragLog(msg){
  try{ console.log("[排序] " + msg); }catch(e){}
  try{ pywebview.api.ui_log("[排序] " + msg); }catch(e){}
}

function _allIdsInView(){
  const dirName = p => String(p.name || p.id || "").toLowerCase();
  const bornOf = p => LISTR.born[(p.dir || "").split(/[\\/]/).pop()] || 0;
  return (DATA.packages || []).slice().sort((a, b) => {
    if (LISTR.sort === "custom"){
      const ia = LISTR.custom.indexOf(a.id), ib = LISTR.custom.indexOf(b.id);
      const ka = ia < 0 ? 1e9 : ia, kb = ib < 0 ? 1e9 : ib;
      if (ka !== kb) return ka - kb;
    } else if (LISTR.sort === "born"){
      const d = bornOf(b) - bornOf(a); if (d) return d;
    } else if (LISTR.sort === "run"){
      const d = lastRunOf(b.id) - lastRunOf(a.id); if (d) return d;
    }
    return dirName(a) < dirName(b) ? -1 : (dirName(a) > dirName(b) ? 1 : 0);
  }).map(p => p.id);
}
function _rowAtY(clientY){
  const rows = [].slice.call(document.querySelectorAll("#list .item"));
  for (const el of rows){
    const r = el.getBoundingClientRect();
    if (clientY >= r.top && clientY <= r.bottom) return el;
  }
  return null;
}
function _reorderLive(clientY){
  const from = _pdrag && _pdrag.id;
  if (!from) return false;
  const vis = [].slice.call(document.querySelectorAll("#list .item")).map(el => el.dataset.id);
  const others = [].slice.call(document.querySelectorAll("#list .item"))
    .filter(el => el.dataset.id !== from);
  let ti = others.length;                            
  for (let i = 0; i < others.length; i++){
    const r = others[i].getBoundingClientRect();
    if (clientY < r.top + r.height / 2){ ti = i; break; }
  }
  const v = vis.filter(id => id !== from);
  v.splice(ti, 0, from);
  if (v.join(",") === vis.join(",")) return false;   
  const full = _allIdsInView();
  const visset = new Set(vis);
  const slots = [];
  full.forEach((id, i) => { if (visset.has(id)) slots.push(i); });
  const out = full.slice();
  slots.forEach((slot, k) => { out[slot] = v[k]; });
  LISTR.custom = out;
  LISTR.sort = "custom";
  paintListBars();
  bumpLists();
  return true;
}

function _measureTops(){
  const out = {};
  document.querySelectorAll("#list .item").forEach(el => {
    if (_pdrag && el.dataset.id === _pdrag.id) return;   
    el.style.transition = ""; el.style.transform = "";
    out[el.dataset.id] = el.getBoundingClientRect().top;
  });
  return out;
}
function _flipAnimate(before){
  document.querySelectorAll("#list .item").forEach(el => {
    const id = el.dataset.id;
    if (_pdrag && id === _pdrag.id) return;            
    const oldTop = before[id];
    if (oldTop == null) return;
    const dy = oldTop - el.getBoundingClientRect().top;
    if (Math.abs(dy) < 0.5) return;
    el.style.transition = "none";
    el.style.transform = "translateY(" + dy + "px)";
    requestAnimationFrame(() => {
      el.style.transition = "transform .22s cubic-bezier(.16,1,.3,1)";
      el.style.transform = "";
    });
  });
}

function _followDrag(clientY){
  if (!_pdrag) return;
  const el = document.querySelector('#list .item[data-id="' + _pdrag.id + '"]');
  if (!el) return;
  el.style.transform = "none";                         
  const r = el.getBoundingClientRect();
  const dy = clientY - (r.top + r.height / 2);
  el.style.transform = "translateY(" + dy + "px) scale(1.04)";
  el.style.zIndex = 6;
}
function _finalizeDrag(){
  document.removeEventListener("pointermove", _onDragMove);
  document.removeEventListener("pointerup", _onDragEnd);
  document.removeEventListener("pointercancel", _onDragEnd);
  LISTDR.dragId = null;
  document.querySelectorAll("#list .item").forEach(el => {
    el.style.transition = ""; el.style.transform = ""; el.style.zIndex = "";
  });
  try{ document.body.style.userSelect = ""; }catch(_){}
  _pdrag = null;
  setTimeout(() => { _listDragging = false; }, 0);     
}
function _onDragMove(e){
  if (!_pdrag || e.pointerId !== _pdrag.pid) return;
  if (!_pdrag.moved){
    if (Math.abs(e.clientY - _pdrag.y0) < 4) return;   
    _pdrag.moved = true; _listDragging = true;
    LISTDR.dragId = _pdrag.id;
    try{ document.body.style.userSelect = "none"; }catch(_){}
    _dragLog("开始拖 " + _pdrag.id + "(" + _nm(_pdrag.id) + ")");
  }
  e.preventDefault();
  const before = _measureTops();                       
  const changed = _reorderLive(e.clientY);
  if (changed) Vue.nextTick(() => { if (_pdrag){ _flipAnimate(before); _followDrag(e.clientY); } });
  else _followDrag(e.clientY);
}
function _onDragEnd(e){
  if (!_pdrag || (e.pointerId != null && e.pointerId !== _pdrag.pid)) return;
  const moved = _pdrag.moved;
  _finalizeDrag();
  if (moved){ saveListView(); _dragLog("松手 -> " + (LISTR.custom || []).join(",")); }
}
function initListDrag(){
  const list = $("#list");
  if (!list || list.__dragBound) return;
  list.__dragBound = true;
  list.addEventListener("pointerdown", (e) => {
    if (e.button != null && e.button !== 0) return;

    if (e.target.closest && e.target.closest("button")) return;

    const item = _rowAtY(e.clientY) || (e.target.closest && e.target.closest(".item"));
    if (!item) return;

    _finalizeDrag();                                 
    _pdrag = {id: item.dataset.id, y0: e.clientY, moved: false, pid: e.pointerId, item: item};
    (function(){
      const r = item.getBoundingClientRect();
      const listEl = document.querySelector("#list");
      const lr = listEl ? listEl.getBoundingClientRect() : {top: -1, bottom: -1};
      const idx = Array.prototype.indexOf.call(document.querySelectorAll("#list .item"), item);
      const txt = (item.textContent || "").replace(/\s+/g, " ").trim().slice(0, 22);
      _dragLog("按下 " + item.dataset.id + " 序号=" + idx
               + " e.y=" + Math.round(e.clientY) + " e.offsetY=" + Math.round(e.offsetY || 0)
               + " 行rect=" + Math.round(r.top) + "~" + Math.round(r.bottom)
               + " #list=" + Math.round(lr.top) + "~" + Math.round(lr.bottom)
               + " scrollTop=" + (listEl ? listEl.scrollTop : "?")
               + " win=" + window.innerHeight + " scrollY=" + Math.round(window.scrollY)
               + " target=" + (e.target ? (e.target.tagName + "." + (e.target.className || "")) : "?")
               + " 指针下=" + (function(){
                   const efp = document.elementFromPoint(e.clientX, e.clientY);
                   if (!efp) return "?";
                   const it = efp.closest && efp.closest(".item");
                   return it ? ("item:" + it.dataset.id) : (efp.tagName + "." + (efp.className || ""));
                 })()
               + " 行文[" + txt + "]");
    })();

    document.addEventListener("pointermove", _onDragMove);
    document.addEventListener("pointerup", _onDragEnd);
    document.addEventListener("pointercancel", _onDragEnd);
  });
}
try{ initListDrag(); }catch(e){}

function renderList(){
  LISTR.ready = !!(DATA && DATA.packages);
  bumpLists();

  try{ paintSwitchCounts(); }catch(e){}

  Vue.nextTick(() => { try{ paintRowStats(); }catch(e){} });
}
function safeSvg(text){
  try{
    const doc = new DOMParser().parseFromString(text, "image/svg+xml");
    if (doc.querySelector("parsererror")) return "";
    doc.querySelectorAll("script,foreignObject,iframe").forEach(n => n.remove());
    doc.querySelectorAll("*").forEach(n => {
      [...n.attributes].forEach(a => {
        if (/^on/i.test(a.name) || /^(href|xlink:href)$/i.test(a.name)) n.removeAttribute(a.name);
      });
    });
    const svg = doc.documentElement;
    svg.removeAttribute("width"); svg.removeAttribute("height");
    return svg.outerHTML;
  }catch(e){ return ""; }
}

function iconFallbackHue(p){
  const s = String((p && (p.id || p.name)) || "?");
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
}
function iconFallbackChar(p){
  const nm = String((p && (p.name || p.id)) || "?").trim();
  const ch = Array.from(nm)[0] || "?";
  return ch;
}
function iconInner(p){
  if (p && p.icon_svg){ const s = safeSvg(p.icon_svg); if (s) return s; }
  if (p && p.icon) return '<img src="' + p.icon + '" alt="">';
  return "";
}
function iconHTML(p, cls){
  const inner = iconInner(p);
  if (inner) return '<span class="' + cls + '">' + inner + '</span>';

  return '<span class="' + cls + ' ico-fb" style="--fb-h:' + iconFallbackHue(p) + '">' +
         esc(iconFallbackChar(p)) + '</span>';
}

function iconBigHTML(p){
  const inner = iconInner(p);
  if (inner) return inner;
  return '<span class="dp-fb" style="--fb-h:' + iconFallbackHue(p) + '">' +
         esc(iconFallbackChar(p)) + '</span>';
}
function pkgRel(p){
  return relOfDir(p && p.dir);
}

function relOfDir(dir){
  const norm = s => String(s || "").replace(/\\/g, "/").replace(/\/+$/, "");
  const d = norm(dir), userd = norm(DATA.user_data), sysroot = norm(DATA.home) + "/system";
  if (!d) return null;
  if (d === userd || d.startsWith(userd + "/")) return "user" + d.slice(userd.length);
  if (d === sysroot || d.startsWith(sysroot + "/")) return "system" + d.slice(sysroot.length);
  return null;
}

function layerBadge(p){
  const layer = String((p && p.layer) || "");
  const to = layer === "system" ? "user" : "system";
  const why = to === "system"
    ? "把它的目录搬进 system 层（出厂件：升级时 system/ 会整体替换，改动可能被冲掉）"
    : "把它的目录搬进 user_data 层（你自己的：升级不碰，而且压住 system 层的同名包）";
  const blocked = !!(p && p.shadowed);
  const tip = blocked
    ? ("另一层（" + p.shadowed + "）已经有同名包了 —— 先把那个删掉或改名，才能换层")
    : (layer + " 层 —— " + why);
  return '<button type="button" class="dp-badge dp-layer" id="btn-layer-move"' +
      ' data-to="' + esc(to) + '"' + (blocked ? ' disabled data-blocked="1"' : "") +
      ' title="' + esc(tip) + '" aria-label="' + esc(tip) + '">' +
      '<span class="dp-layer-now">' + esc(layer) + ' 层</span>' +
      '<span class="dp-layer-go">' + ico("layers", "i") + '→ ' + esc(to) + '</span>' +
    '</button>';
}

function scrollSelIntoView(){
  const list = $("#list");
  if (!list || !list.clientHeight) return;       
  const el = list.querySelector(".item.sel");
  if (!el) return;                                
  const lr = list.getBoundingClientRect(), r = el.getBoundingClientRect();
  if (r.top >= lr.top && r.bottom <= lr.bottom) return;       
  const pad = 6;
  if (r.top < lr.top) list.scrollTop += (r.top - lr.top) - pad;         
  else list.scrollTop += (r.bottom - lr.bottom) + pad;                  
}

function select(id, keepTab){
  const prevId = cur ? cur.id : null;
  cur = DATA.packages.find(p => p.id === id) || null;
  curH = null;                                
  consoleKey = cur ? cur.id : "__host__";     
  renderList(); renderHist(); renderDetail(); paintConsole();
  if (!keepTab) setTab("detail");

  if (cur) fmSelect(cur.id,  true);
  paintEmbedTab();                            

  if (cur && cur.id !== prevId) Vue.nextTick(() => { try{ scrollSelIntoView(); }catch(e){} });
}
function renderDetailHTML(){
  const who = selObj();
  if (!who) return '<div class="empty">左边选一个包，或者一条历史</div>';
  if (isHist(who)) return renderDetailHistHTML(who);
  const p = cur, params = p.params || [];
  const prop = (k, v) => '<div class="dp-prop"><span class="prop-k">' + esc(k) +
    '</span><span class="prop-v">' + v + '</span></div>';

  const dirText = String(p.dir || "");
  let html = '<div class="dwrap"><div class="dp-card dp-head">' +
      '<div class="dp-icon">' + iconBigHTML(p) + '</div>' +
      '<div class="dp-info">' +
        '<h1 title="' + esc(p.name) + '">' + esc(p.name) +
          '<span class="dp-badges dmeta">' +
            '<span class="dp-badge">' + esc(PSYM + p.id) + '</span>' +
            '<span class="dp-badge">v' + esc(p.version || "?") + '</span>' +
            '<span class="dp-badge">' + esc(p.kind || "task") + '</span>' +
            layerBadge(p) +
            (p.shadowed ? '<span class="dp-badge">遮住了 ' + esc(p.shadowed) + ' 层的同名包' +
                          '</span>' : '') +
          '</span></h1>' +
        (p.desc
          ? '<div class="dp-desc dp-tip" data-tip="此说明将被列在 moss 的包列表里，方便快速识别。">' +
            esc(p.desc) + '<span class="dp-tip-ico">' + ico("info", "i") + '</span></div>'
          : '') +
        '<div class="dp-divider"></div>' +

        '<div class="dp-path">' +
          '<span class="dp-path-ico">' + ico("folder", "i") + '</span>' +
          '<span class="dp-path-text" id="pkg-dir" title="' + esc(dirText) + '">' +
            esc(dirText || "（没拿到目录）") + '</span>' +
          '<div class="dp-path-actions">' +
            '<button class="dp-path-btn dp-tip" id="btn-copy-dir" data-tip="复制路径">' +
              ico("copy", "i") + '</button>' +
            '<button class="dp-path-btn dp-tip" id="btn-open-dir" data-tip="打开目录">' +
              ico("folder-open", "i") + '</button>' +
          '</div>' +
        '</div>';

  const props = [];
  if ((p.aliases || []).length)
    props.push(prop("别名 (Alias)", (p.aliases || []).map(a => '<span class="mono">:' + esc(a) +
      '</span>').join('&nbsp; ')));
  if ((p.tags || []).length)
    props.push(prop("标签", (p.tags || []).map(t => '<span class="tag">' + esc(t) +
      '</span>').join("")));
  if (p.ai_expose)
    props.push(prop("AI", '可调用 <span class="soft">· 风险 ' +
      esc(p.ai_risk || "?") + '</span>'));

  params.forEach(pa => {
    const tip = [
      String(pa.desc || "").trim(),
      pa.rest ? "余下全给它" : "",
      String(pa.placeholder || "").trim() ? ("示例: " + String(pa.placeholder).trim()) : "",
    ].filter(Boolean).join(" · ");
    props.push('<div class="dp-prop"><span class="prop-k">参数 ' + esc(String(pa.name || "")) +
      '</span><span class="prop-v' + (tip ? ' dp-tip' : '') + '"' +
      (tip ? ' data-tip="' + esc(tip) + '"' : '') + '>' +
      '<span class="mono">' + esc(pa.type || "string") + '</span>' +
      '<span class="dp-badge">' + (pa.required ? "必填" : "可留空") + '</span></span></div>');
  });

  const dirBase = (String(p.dir || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop()) || "";
  const oddDir = dirBase && dirBase !== p.id;
  if (oddDir)
    props.push(prop("目录名", '<span class="mono">' + esc(dirBase) + '</span>' +
      '<span class="soft">· 与 id 不同（右边可以一键统一）</span>'));
  if (props.length)
    html += '<div class="dp-props">' + props.join("") + '</div>';
  html += '</div></div>';

  html += '<div class="dp-card"><div class="dp-cmdbar">' +
      '<span class="dp-cmd-ico">' + ico("terminal", "i") + '</span>' +
      '<span class="dp-cmd-prefix">moss ' + esc(PSYM + p.id) + '</span>' +

      '<span class="argbox">' +
        '<input id="args" placeholder="点击输入附加参数并回车执行..." value="' +
          esc(ARGS[p.id] || "") + '">' +
        '<button class="argclear" id="btn-args-clear" title="清空参数" hidden>' +
          ico("x", "i") + '</button>' +
      '</span>' +

      '<div class="dp-split" id="run-split">' +
        '<button class="dp-split-main" id="btn-runsplit"' +
          ' title="运行这个包，输出进「命令行」">' +
          ico("play", "i") + '<span>运行</span></button>' +
        '<span class="dp-split-divider"></span>' +
        '<button class="dp-split-arrow" id="btn-split-arrow" title="更多运行方式">' +
          ico("chevron-down", "i") + '</button>' +
        '<div class="dp-split-menu" id="run-split-menu">' +
          '<button class="dp-split-item" id="btn-run-newwin"' +
            ' title="新窗口运行：后台把包自己的界面开起来，不等它">' +
            ico("app-window", "i") + '<span>独立运行</span></button>' +
        '</div>' +
      '</div>' +
    '</div>' +

    '<span hidden id="preview"></span>';

  const exs = (p.examples || []).map(x => String(x || "")).filter(x => x.trim());
  if (exs.length){
    html += '<div class="dp-hint">常用的参数（点一下填进上面的框）：<span class="chips">' +
      exs.map(e => '<button class="chip" data-args="' + esc(e) + '">' + esc(e) +
        '</button>').join("") + '</span></div>';
  }
  html += '</div>';

  const docReadme = (p.docs && p.docs.readme) || null;
  if (docReadme && docReadme.text){
    html += '<div class="dp-card"><details class="dp-doc" open>' +
        '<summary class="dp-doc-sum">' +
          '<span class="dp-doc-ico">' + ico("book-open", "i") + '</span>' +
          '<span class="dp-doc-title">使用说明</span>' +
          '<span class="dp-doc-file mono">' + esc(docReadme.file || "") + '</span>' +
          (docReadme.truncated ? '<span class="dp-badge">太长，只显示前面一段</span>' : '') +
        '</summary>' +
        '<pre class="dp-doc-body">' + esc(docReadme.text) + '</pre>' +
      '</details></div>';
  }

  const renameBtn = '<button class="dp-ghost" id="btn-rename" title="给这个包改名（moss --rename）">' +
      ico("pencil", "i") + '<span>更名</span></button>';
  html += '<div class="dp-card"><div class="dp-list">' +
      '<div class="dp-item">' +
        '<div class="dp-item-info">' +
          '<span class="dp-item-ico">' + ico("text-cursor-input", "i") + '</span>' +
          '<div class="dp-item-text"><h4>更改标识符' +
            '<span class="dp-tip dp-tip-ico" data-tip="将同步修改包目录名、数据目录及清单中的 id">' +
              ico("circle-alert", "i") + '</span></h4>' +
            '<p>修改插件的唯一 ID 和文件夹名称</p></div>' +
        '</div>' +
        '<div class="dp-item-acts">' +
          (oddDir
            ? '<button class="dp-ghost" id="btn-align" title="只把包目录名改成 id —— ' +
              '数据目录和清单都不动">' + ico("folder-tree", "i") + '<span>对齐目录名</span></button>'
            : '') +
          renameBtn + '</div>' +
      '</div>' +

      autoSectionHTML("pkg", p.id, {}) +

      parasiteSectionHTML(p.id) +
      '<div class="dp-item">' +
        '<div class="dp-item-info">' +
          '<span class="dp-item-ico danger">' + ico("trash-2", "i") + '</span>' +
          '<div class="dp-item-text"><h4 class="danger">卸载此插件' +
            '<span class="dp-tip dp-tip-ico" data-tip="永久删除：包本体 + 数据">' +
              ico("circle-alert", "i") + '</span></h4>' +
            '<p>将永久抹除数据，此操作无法撤销</p></div>' +
        '</div>' +
        '<button class="dp-ghost danger" id="btn-remove" title="卸载这个包（moss --remove）">' +
          ico("trash-2", "i") + '<span>卸载</span></button>' +
      '</div>' +
    '</div></div></div>';
  return html;
}

function runSplitMenu(show){
  const menu = $("#run-split-menu"), grp = $("#run-split");
  if (!menu || !grp) return;
  const want = (show === undefined) ? !menu.classList.contains("show") : !!show;
  menu.classList.toggle("show", want);
  grp.classList.toggle("open", want);
}
function runSplitClose(){ runSplitMenu(false); }

if (!window.__mossRunSplitBound){
  window.__mossRunSplitBound = true;
  document.addEventListener("click", (e) => {
    const grp = $("#run-split");
    if (grp && !grp.contains(e.target)) runSplitClose();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") runSplitClose();
  });
}

function wireDetail(){
  const who = selObj();
  if (!who) return;
  if (isHist(who)) return wireDetailHist(who);
  const p = cur;

  const box = $("#pane-detail");
  const host = box;

  if (host && host.dataset.wiredRev === String(DETAILR.rev)) return;
  if (host) host.dataset.wiredRev = String(DETAILR.rev);
  const aclr = $("#btn-args-clear");            
  const upd = () => {
    $("#preview").textContent = "moss " + PSYM + p.id +
      ($("#args").value.trim() ? " " + $("#args").value.trim() : "");
    ARGS[p.id] = $("#args").value;              
    if (aclr) aclr.hidden = !$("#args").value;  
  };
  if (aclr) aclr.onclick = () => {
    $("#args").value = "";
    upd();
    $("#args").focus();                         
  };
  $("#args").addEventListener("input", upd);
  $("#args").addEventListener("keydown", (e) => {
    if (e.key === "Enter"){ e.preventDefault(); startRun(p, $("#args").value); }
  });
  upd();

  box.querySelectorAll(".chip[data-args]").forEach(c => {
    c.onclick = () => { $("#args").value = c.dataset.args || ""; upd(); };
  });

  paintActions(p);
  $("#btn-run").onclick = () => clickRun(p);
  $("#btn-vis").onclick = () => toggleVis(p);
  refreshPkgState(p);

  $("#btn-runsplit").onclick = () => { runSplitClose(); clickRun(p); };
  $("#btn-split-arrow").onclick = (ev) => { ev.stopPropagation(); runSplitMenu(); };
  $("#btn-run-newwin").onclick = async () => {
    runSplitClose();
    const r = await pywebview.api.open_ui(p.id, $("#args").value);
    if (r && r.ok === false) toast(r.msg || "启动失败", true);

    paintRowStats();
    setTimeout(() => refreshPkgState(p), 1500);
    setTimeout(() => refreshPkgState(p), 3500);
  };
  $("#btn-remove").onclick = () => cmdRemovePkg(p);
  $("#btn-rename").onclick = () => cmdRenamePkg(p);
  if ($("#btn-align")) $("#btn-align").onclick = () => cmdAlignPkgDir(p);

  if ($("#btn-copy-dir")) $("#btn-copy-dir").onclick = () => copyDirPath(p.dir);

  if ($("#btn-layer-move")) $("#btn-layer-move").onclick = (ev) => {
    ev.stopPropagation();
    if (p.shadowed){ toast("✗ 另一层（" + p.shadowed + "）已经有同名包，先处理它", true); return; }
    cmdMoveLayer(p);
  };
  if ($("#btn-open-dir")) $("#btn-open-dir").onclick = async () => {
    const rel = pkgRel(p);
    const r = rel ? await pywebview.api.fs_open_default(rel)
                  : await pywebview.api.open_path(String(p.dir || ""));
    toast(r.msg || (r.ok ? "已打开" : "打不开"), !r.ok);
  };
  autoWire("pkg", p.id, {});          
  parasiteWire(p.id);                 
}

async function copyDirPath(text){
  const s = String(text || "");
  if (!s){ toast("没有可复制的路径", true); return; }
  try{
    if (navigator.clipboard && navigator.clipboard.writeText){
      await navigator.clipboard.writeText(s);
      toast("已复制：" + s);
      return;
    }
  }catch(e){  }
  toast("复制不了，路径：" + s, true);
}

async function cmdAlignPkgDir(p){
  const oldRel = pkgRel(p);              
  consoleKey = "__host__";
  const cmd = "moss --rename " + p.id + " " + p.id;
  setConsole("__host__", "$ " + cmd, "运行中");
  const r = await pywebview.api.run_host("--rename " + p.id + " " + p.id);
  setConsole("__host__", "$ " + cmd + "\n\n" + (r.out || "(没有输出)"),
             r.code === 0 ? "完成" : ("退出码 " + r.code));
  if (r.code !== 0){
    toast("✗ 没对齐成，看「命令行」里说了什么", true);
    setTab("console");
    return;
  }
  toast("包目录名已对齐成 " + PSYM + p.id);

  await refreshPkgs(p.id);
  const np = DATA.packages.find(x => x.id === p.id);
  fmReRoot(oldRel, np ? pkgRel(np) : null);
  if (np) select(p.id);
  else renderDetail();
}

async function cmdMoveLayer(p){
  const to = p.layer === "user" ? "system" : "user";
  const toText = to === "system"
    ? "system/pkgs（出厂层：moss 升级时 system/ 会被整体替换，你对它的改动可能被冲掉）"
    : "user_data/pkgs（你自己的层：升级不碰它，而且它会压住 system 层的同名包）";
  askConfirm2("给这个包换一层",
    "<b>" + esc(p.id) + "</b> 现在在 <b>" + esc(p.layer) + "</b> 层。<br><br>" +
    "要把它整个目录挪到 <b>" + toText + "</b> 吗？" +
    "<br><br>· 调用方式一个字不变（moss " + esc(PSYM + p.id) + "）" +
    "<br>· 数据目录 <b>user_data/state/" + esc(p.id) + "</b> 不动",
    {label: to === "system" ? "搬进 system 层" : "搬回 user 层",
     danger: to === "system",
     cb: async () => {
      const oldRel = pkgRel(p);                  
      consoleKey = "__host__";
      const cmd = "moss --layer " + p.id + " " + to;
      setConsole("__host__", "$ " + cmd, "运行中");
      const r = await pywebview.api.run_host("--layer " + p.id + " " + to);
      setConsole("__host__", "$ " + cmd + "\n\n" + (r.out || "(没有输出)"),
                 r.code === 0 ? "完成" : ("退出码 " + r.code));
      if (r.code !== 0){
        toast("✗ 没搬成，看「命令行」里说了什么", true);
        setTab("console");
        return;
      }
      await refreshPkgs(p.id);                   
      const np = DATA.packages.find(x => x.id === p.id);
      fmReRoot(oldRel, np ? pkgRel(np) : null);  
      if (np) select(p.id); else renderDetail();
      toast("已挪到 " + to + " 层" +
            (to === "system" ? "（升级时会被整体替换，想留住就再搬回 user）" : ""));
     }});
}

async function cmdRenamePkg(p){
  askText("给这个包改名", p.id, async (newId) => {
    newId = String(newId || "").trim().toLowerCase();
    if (!newId || newId === p.id) return;
    const oldRel = pkgRel(p);            

    const oldId = String(p.id);
    consoleKey = "__host__";
    const cmd = "moss --rename " + oldId + " " + newId;
    setConsole("__host__", "$ " + cmd, "运行中");
    const r = await pywebview.api.run_host("--rename " + oldId + " " + newId);
    setConsole("__host__", "$ " + cmd + "\n\n" + (r.out || "(没有输出)"),
               r.code === 0 ? "完成" : ("退出码 " + r.code));
    if (r.code !== 0){
      toast("✗ 改名失败，看「命令行」里说了什么", true);
      setTab("console");
      return;
    }

    await pkgFollowId(oldId, newId);

    try{
      const br = await pywebview.api.backup_rename_group(oldId, newId);
      if (br && br.ok && br.renamed) console.info("备份分组已改名：" + (br.msg || ""));
      else if (br && !br.ok) console.warn("备份分组没改成：" + (br.msg || ""));
    }catch(e){ console.warn("备份分组没改成：", e); }

    await refreshPkgs(newId);            
    const np = DATA.packages.find(x => x.id === newId);
    fmReRoot(oldRel, np ? pkgRel(np) : null);
    if (np) select(newId);
    else renderDetail();

    if (np) await followIntoAi(newId);
    toast("已改名为 " + PSYM + newId + "（显示名里的旧名字也一起换了）");
  });
}

async function followIntoAi(id){
  try{
    if (typeof aiLoadRuns !== "function") return false;
    await aiLoadRuns();                                  
    const A = window.__AIR || {};
    if (!(A.runs || []).length) return false;
    if (typeof setTab === "function") setTab("ai");
    return true;
  }catch(e){ return false; }
}

async function pkgFollowId(oldId, newId){
  if (!oldId || !newId || oldId === newId) return;
  if (ARGS[oldId] !== undefined){ ARGS[newId] = ARGS[oldId]; delete ARGS[oldId]; }
  if (RUNS[oldId]){ RUNS[newId] = RUNS[oldId]; delete RUNS[oldId]; }
  if (consoleKey === oldId) consoleKey = newId;
  try{ await autoRename(oldId, newId); }catch(e){  }

  try{ await parasiteRename(oldId, newId); }catch(e){  }
}

let renameTimer = null;
let renameTickBusy = false;

function pkgWatchStart(){
  if (renameTimer || FLOAT_PID) return;      
  renameTimer = setInterval(pkgWatchTick, 2500);
  setTimeout(pkgWatchTick, 900);             
}

async function pkgWatchTick(){
  if (renameTickBusy) return;
  renameTickBusy = true;
  let r = null;
  try{ r = await pywebview.api.pkg_watch(); }catch(e){ r = null; }
  renameTickBusy = false;
  if (!r || !r.ok) return;
  const rens = r.renamed || [];
  for (let i = 0; i < rens.length; i++)
    await followRename(rens[i][0], rens[i][1], rens[i][2], rens[i][3]);
  if ((r.gone || []).length) await followGone(r.gone);
  else if (r.changed && !rens.length) await refreshPkgs(cur ? cur.id : null, true);
}

async function followRename(oldId, newId, how, oldDir){
  if (!oldId || !newId || oldId === newId) return;
  const wasOpen = !!(cur && cur.id === oldId);
  const oldRel = relOfDir(oldDir) || (wasOpen ? pkgRel(cur) : null);

  await pkgFollowId(oldId, newId);

  try{
    const br = await pywebview.api.backup_rename_group(oldId, newId);
    if (br && !br.ok) console.warn("备份分组没改成：" + (br.msg || ""));
  }catch(e){ console.warn("备份分组没改成：", e); }

  const hadEmbed = (typeof embedRunning === "function") && embedRunning(oldId);
  if (hadEmbed) await embedStop(oldId, true);
  await refreshPkgs(newId);
  const np = (DATA.packages || []).find(x => x.id === newId);
  if (oldRel && np) fmReRoot(oldRel, pkgRel(np));
  if (wasOpen && np){
    select(newId,  true);         
    if (hadEmbed && embedSupported(np)) await embedOpen(np, {keepTab: true});

    await followIntoAi(newId);
  }

  toast("已跟随改名：" + PSYM + oldId + " → " + PSYM + newId);
}

async function followGone(ids){
  const wasOpen = !!(cur && ids.some(x => x === cur.id));
  await refreshPkgs(null, true);       
  const names = ids.map(x => PSYM + x).join("、");
  if (wasOpen) toast("这个包已经不在了：" + names, true);
  else toast("有包不在了：" + names);
}

function renderDetailHistHTML(it){
  const when = (it.ts || "").replace("T", " ");
  const gone = it.exists === false;
  const prop = (k, v) => '<div class="dp-prop"><span class="prop-k">' + esc(k) +
    '</span><span class="prop-v">' + v + '</span></div>';

  const rows = [];
  if (it.cwd) rows.push(prop("工作目录", '<span class="mono">' + esc(it.cwd) + '</span>' +
    (it.cwd_exists === false ? '<span class="soft">· 这个目录也不在了</span>' : '')));
  if (it.args) rows.push(prop("参数", '<span class="mono">' + esc(it.args) + '</span>'));
  if (when) rows.push(prop("时间", esc(when)));
  if (it.exit !== null && it.exit !== undefined)
    rows.push(prop("上次退出码", esc(String(it.exit))));
  const dirText = String(it.target || "");
  let html = '<div class="dwrap"><div class="dp-card dp-head">' +
      '<div class="dp-icon">' + histIconHTML(it, "") + '</div>' +
      '<div class="dp-info">' +
        '<h1 title="' + esc(it.name) + '">' + esc(it.name) +
          '<span class="dp-badges dmeta">' +
            '<span class="dp-badge">历史</span>' +
            (it.exists === false ? '<span class="dp-badge">文件不在了</span>' : '') +
          '</span></h1>' +
        '<div class="dp-divider"></div>' +
        '<div class="dp-path">' +
          '<span class="dp-path-ico">' + ico("file-text", "i") + '</span>' +
          '<span class="dp-path-text" id="pkg-dir" title="' + esc(dirText) + '">' +
            esc(dirText || "（这条没有目标路径）") + '</span>' +
          '<div class="dp-path-actions">' +
            '<button class="dp-path-btn dp-tip" id="btn-copy-dir" data-tip="复制路径">' +
              ico("copy", "i") + '</button>' +
            '<button class="dp-path-btn dp-tip" id="btn-open-dir" data-tip="打开所在目录">' +
              ico("folder-open", "i") + '</button>' +
          '</div>' +
        '</div>' +
        (rows.length ? '<div class="dp-props">' + rows.join("") + '</div>' : '') +
      '</div></div>';
  if (gone){
    html += '<div class="dp-card"><div class="warnbox">' + ico("alert-triangle", "i") +
      '<span>这个文件已经不在了，跑不了。记录还留着，想清掉就点下面那个按钮。</span></div></div>';
  }
  html += '<div class="dp-card"><div class="dp-cmdbar">' +
      '<span class="dp-cmd-ico">' + ico("terminal", "i") + '</span>' +
      '<span class="dp-cmd-prefix">moss /' + esc(it.name) + '</span>' +

      '<span class="argbox">' +
        '<input id="hargs" placeholder="点击输入附加参数并回车执行..." value="' +
          esc(it.args || "") + '"' + (gone ? " disabled" : "") + '>' +

        '<button class="argclear" id="btn-hargs-clear" title="清空参数" hidden>' +
          ico("x", "i") + '</button>' +
      '</span>' +
      '<button class="dp-primary" id="btn-run2"' + (gone ? " disabled" : "") + '>' +
        ico("play", "i") + '<span>运行</span></button>' +
    '</div><span hidden id="hpreview"></span></div>';

  html += '<div class="dp-card"><div class="dp-list">' +
      autoSectionHTML("hist", it.target, {cwd: it.cwd || "", name: it.name || "",
                                          args: it.args || ""}) +
      '<div class="dp-item">' +
        '<div class="dp-item-info">' +
          '<span class="dp-item-ico">' + ico("folder-open", "i") + '</span>' +
          '<div class="dp-item-text"><h4>打开所在目录</h4>' +
            '<p>用资源管理器打开它当初跑的那个目录</p></div>' +
        '</div>' +
        '<button class="dp-ghost" id="btn-opendir" title="用 Windows 资源管理器打开它所在的目录">' +
          ico("folder-open", "i") + '<span>打开</span></button>' +
      '</div>' +
      '<div class="dp-item">' +
        '<div class="dp-item-info">' +
          '<span class="dp-item-ico danger">' + ico("trash-2", "i") + '</span>' +
          '<div class="dp-item-text"><h4 class="danger">删除这条记录</h4>' +
            '<p>只删这条记录，那个文件本身不动</p></div>' +
        '</div>' +
        '<button class="dp-ghost danger" id="btn-forget" title="从历史里删掉这条记录">' +
          ico("trash-2", "i") + '<span>删除</span></button>' +
      '</div>' +
    '</div></div></div>';
  return html;
}

function wireDetailHist(it){
  const host = $("#pane-detail");
  if (host && host.dataset.wiredRev === String(DETAILR.rev)) return;
  if (host) host.dataset.wiredRev = String(DETAILR.rev);
  const inp = $("#hargs"), aclr = $("#btn-hargs-clear");   
  const upd = () => {
    const a = inp.value.trim();

    $("#hpreview").textContent = "moss /" + it.name + (a ? " " + a : "");

    if (aclr) aclr.hidden = !inp.value || inp.disabled;
  };
  if (aclr) aclr.onclick = () => {
    inp.value = "";
    upd();
    if (!inp.disabled) inp.focus();             
  };
  $("#hargs").addEventListener("input", upd);
  $("#hargs").addEventListener("keydown", (e) => {
    if (e.key === "Enter"){ e.preventDefault(); rerunHist(it, $("#hargs").value); }
  });
  upd();

  paintActions(it);
  $("#btn-run").onclick = () => clickRun(it);
  $("#btn-vis").onclick = () => {};            
  $("#btn-run2").onclick = () => rerunHist(it, $("#hargs").value);
  $("#btn-opendir").onclick = () => {
    pywebview.api.fs_open_default(histDir(it)).then(r => toast(r.msg, !r.ok));
  };
  $("#btn-forget").onclick = () => cmdForgetHist(it);

  if ($("#btn-copy-dir")) $("#btn-copy-dir").onclick = () => copyDirPath(it.target);

  autoWire("hist", it.target, {cwd: it.cwd || "", name: it.name || "",
                               args: it.args || ""});
}

function renderDetailHist(it, box){
  const html = renderDetailHistHTML(it);
  if (box) box.innerHTML = html;
  wireDetailHist(it);
}

async function cmdForgetHist(it){
  const r = await pywebview.api.hist_forget(it.key || "");
  toast(r.ok ? ("已删掉这条记录：" + it.name) : ("✗ " + (r.msg || "删不掉")), !r.ok);
  if (!r.ok) return;
  if (curH && histKey(curH) === histKey(it)) curH = null;
  await loadHist();
  renderHist();
  renderDetail();
}

const MossList = {
  name: "moss-list",
  data(){ return { R: LISTR, L: LISTDR }; },
  computed: {
    rows(){
      this.R.rev;                                  

      if (!this.R.ready) return [];
      const f = $("#q").value.trim().toLowerCase();
      const all = DATA.packages.filter(p => !f ||
        [p.id, p.name, p.desc, (p.tags||[]).join(" "), (p.aliases||[]).join(" ")]
          .join(" ").toLowerCase().includes(f));

      const byLayer = this.R.filt === "all" ? all : all.filter(p => p.layer === this.R.filt);

      const dirName = p => String(p.name || p.id || "").toLowerCase();
      const bornOf = p => this.R.born[(p.dir || "").split(/[\\/]/).pop()] || 0;
      const sortKey = this.R.sort;
      const sorted = byLayer.slice().sort((a, b) => {
        if (sortKey === "custom"){                    
          const ia = this.R.custom.indexOf(a.id), ib = this.R.custom.indexOf(b.id);
          const ka = ia < 0 ? 1e9 : ia, kb = ib < 0 ? 1e9 : ib;   
          if (ka !== kb) return ka - kb;
        } else if (sortKey === "born"){
          const d = bornOf(b) - bornOf(a);
          if (d) return d;
        } else if (sortKey === "run"){
          const d = lastRunOf(b.id) - lastRunOf(a.id);
          if (d) return d;
        }
        return dirName(a) < dirName(b) ? -1 : (dirName(a) > dirName(b) ? 1 : 0);
      });

      return (DRAG.on && !DRAG.framePid) ? sorted.filter(p => dropAccepts(p, DRAG.items)) : sorted;
    },
    emptyHTML(){
      this.R.rev;
      if (DRAG.on && DRAG.framePid) return "没有匹配的包";   
      return DRAG.on
        ? ("没有包收「" + dropKindName(DRAG.kind) + "」" + dropWhyNone(DRAG.items))
        : "没有匹配的包";
    },
  },
  methods: {
    selId(){ return cur ? cur.id : null; },
    stateOf(id){ return rowStateOf(id); },          

    isAutoRun(id){
      try{ return autoPkgIds().has(String(id)); }catch(e){ return false; }
    },
    rowHTML(p){
      return '<span class="drag-grip" title="拖动排序">' + ico("grip-vertical", "i") + '</span>' +
        iconHTML(p, "ico") +
        '<div style="min-width:0;flex:1">' +
          '<div class="nm">' + esc(p.name) + '</div>' +
          '<div class="ds">' + esc(PSYM + p.id) + '</div></div>' +
        '<span class="rowstat"></span>';
    },
    pick(id){
      if (_listDragging) return;

      const prev = cur && cur.id;
      select(id);
      parasiteOnPick(id, prev);
    },   
  },
  template: `
    <template v-if="R.ready">
      <div v-if="!rows.length" class="empty">{{ emptyHTML }}</div>
      <template v-else>
        <div v-for="p in rows" :key="p.id" class="item"
             :class="{sel: p.id === selId(), dragging: L.dragId === p.id,
                      'pkg-autorun': isAutoRun(p.id)}"
             :data-id="p.id" :data-state="stateOf(p.id)"
             :title="isAutoRun(p.id) ? '已设置自动运行' : ''"
             @click="pick(p.id)" v-html="rowHTML(p)"></div>
      </template>
    </template>`,
};

const MossHist = {
  name: "moss-hist",
  data(){ return { R: LISTR }; },
  computed: {
    rows(){
      this.R.rev;                                  
      const f = $("#q").value.trim().toLowerCase();
      const hit = HIST.filter(it => !f ||
        [it.name, it.target, it.args, it.cwd].join(" ").toLowerCase().includes(f));

      const kindOf = it => (it.kind === "pkg" || it.kind === "plugin") ? "pkg" : "path";
      const byKind = this.R.hfilt === "all" ? hit : hit.filter(it => kindOf(it) === this.R.hfilt);
      const key = this.R.hsort;
      return byKind.slice().sort((a, b) => {
        if (key === "time" || key === "kind"){          
          const ta = String(a.ts || ""), tb = String(b.ts || "");
          if (ta !== tb) return ta < tb ? 1 : -1;
        }
        const na = String(a.name || "").toLowerCase(), nb = String(b.name || "").toLowerCase();
        return na < nb ? -1 : (na > nb ? 1 : 0);
      });
    },
    emptyHTML(){
      this.R.rev;              
      return HIST.length ? "没有匹配的历史"
        : ('还没有历史。<br>这里记的是<b>直接跑文件</b>的那种调用（<span class="mono">moss zeen</span>）；'
           + '<br>跑插件不进历史。');
    },
  },
  methods: {
    keyOf(it){ return histKey(it); },
    stateOf(it){ return RUNS[histKey(it)] ? "running" : "idle"; },
    dead(it){ return it.exists === false; },
    titleOf(it){ return this.dead(it) ? ("这个文件已经不在了：" + (it.target || "")) : null; },
    rowHTML(it){
      const when = (it.ts || "").replace("T", " ").slice(5, 16);
      return histIconHTML(it) +
        '<div class="hmain">' +
          '<div class="hname">' + esc(it.name) +
            (it.args ? ' <span class="sub">' + esc(it.args) + '</span>' : "") + '</div>' +
          '<div class="hsub">' + esc(it.cwd || "") + '　·　' + esc(when) + '</div>' +
        '</div>' +
        '<span class="hstat"></span>';
    },
    pick(it){ selectHist(it); },                   
  },
  template: `
    <div v-if="!rows.length" class="empty" v-html="emptyHTML"></div>
    <template v-else>
      <div v-for="it in rows" :key="keyOf(it)" class="hitem"
           :class="{sel: curH && keyOf(it) === keyOf(curH), dead: dead(it)}"
           :data-key="keyOf(it)" :data-state="stateOf(it)" :title="titleOf(it)"
           @click="pick(it)" v-html="rowHTML(it)"></div>
    </template>`,
};

mountVue(MossList, "#list");
mountVue(MossHist, "#hist");

const DETAILR = Vue.reactive({rev: 0});
function renderDetail(){ DETAILR.rev++; }

const MossDetail = {
  name: "moss-detail",
  data(){ return { R: DETAILR }; },
  computed: {
    html(){ this.R.rev; return renderDetailHTML(); },   
  },
  mounted(){ wireDetail(); },
  updated(){ wireDetail(); },

  template: '<div style="display:contents" v-html="html"></div>',
};
mountVue(MossDetail, "#pane-detail");

window.syncListBars = function(){
  const pkg = !$("#list").hidden;
  const bl = $("#bar-list"), bh = $("#bar-hist");
  if (bl) bl.hidden = !pkg;
  if (bh) bh.hidden = pkg;
  initListBarsOnce();
};
let _barsDone = false;
function initListBarsOnce(){ if (_barsDone) return; _barsDone = true; try{ initListBars(); }catch(e){} }
