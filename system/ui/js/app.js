const FLOAT_PID = window.__mossFloatPid || "";
if (FLOAT_PID) document.body.classList.add("float");

async function initFloatMode(){
  const p = (DATA.packages || []).find(x => String(x.id) === FLOAT_PID);
  if (!p){
    document.body.innerHTML = '<div style="padding:24px;font:14px system-ui">' +
      '这个窗口是给包 ' + PSYM + FLOAT_PID + ' 开的，但没找到它。</div>';
    return;
  }
  document.title = (p.name || p.id) + " · moss";
  select(p.id);                 
  await embedOpen(p);           
  await pushWindowIcon(p);      
  uiLog("[浮动窗口] " + PSYM + p.id + " 帧=" + (embedRunning(p.id) ? "ok" : "没起来") +
        " 图标=" + ((p.icon_svg || p.icon) ? "有" : "没有") + " 地址=" + location.href);
}

function writeStartDiag(){
  try{
    pywebview.api.ui_log("[启动诊断] 宿主包数=" + DATA.packages.length
      + " 列表条目=" + document.querySelectorAll("#list .item").length
      + " 历史条目=" + document.querySelectorAll("#hist .hitem").length
      + " 桥=" + (window.pywebview && window.pywebview.api ? "有" : "无")
      + " 页内错误=" + (window.__errors || []).length
      + " 地址=" + location.href
      + " 窗口=" + window.innerWidth + "x" + window.innerHeight);
  }catch(e){}
}

function paintSwitchCounts(){
  const n = (typeof DATA !== "undefined" && DATA && DATA.packages) ? DATA.packages.length : 0;
  const h = (typeof HIST !== "undefined" && HIST) ? HIST.length : 0;
  const a = document.getElementById("sw-n-pkg"), b = document.getElementById("sw-n-hist");
  if (a) a.textContent = String(n);
  if (b) b.textContent = String(h);
}

let bootedOnce = false;
async function init(){
  if (!bootedOnce){ bootedOnce = true; setStatus("就绪"); }   
  DATA = await pywebview.api.state();

  if (DATA && DATA.symbols && DATA.symbols.plugin !== undefined) PSYM = DATA.symbols.plugin;

  if (FLOAT_PID){ await initFloatMode(); return; }

  document.querySelector("header .brand").title =
    "moss · " + DATA.home + " · 启动方式：" + DATA.launch_kind;
  renderList(); paintStates();

  loadListView();
  await loadHist();        
  setSide(side);           

  await Vue.nextTick();
  writeStartDiag();
  consoleKey = "__host__";
  paintConsole();
  pkgPollStart();          

  pkgWatchStart();

  const first = !FM.ctx;
  if (first) FM.ctx = "__all__";
  const s = fmState(FM.ctx || "__all__");
  const keep = (s.rel && !first) ? s.rel : "user";
  let r = await pywebview.api.fs_list(keep);
  if (!r || !r.ok) r = await pywebview.api.fs_list("user");
  if (r.ok){
    s.rel = r.rel; s.entries = r.entries || [];
    if (first){ s.hist = [s.rel]; s.hpos = 0; }
    else if (s.hist && s.hist.length){ s.hist[s.hpos] = s.rel; }   
  }
  fmRender();
  bindDropZone();          

  if (typeof paintEmbedTab === "function") paintEmbedTab();
  autostartRun();          
}
function paintStaticIcons(){
  const tabs = {"detail": ["info", "详情"], "console": ["terminal", "命令行"],
                "file": ["folder-tree", "文件管理"], "ai": ["moss-deepseek", "AI"]};
  Object.keys(tabs).forEach(k => {
    const b = document.querySelector('.tab[data-tab="' + k + '"]');
    if (b) b.innerHTML = ico(tabs[k][0], "i") + '<span>' + tabs[k][1] + '</span>';
  });
  $("#btn-selfcheck").innerHTML = ico("activity", "i");
  $("#btn-aside-mini").innerHTML = ico("chevron-right", "i");   

  $("#sw-pkg").innerHTML  = ico("package", "i") + '<span>插件</span>' +
                            '<b class="sw-n" id="sw-n-pkg"></b>';

  $("#sw-hist").innerHTML = ico("history", "i") + '<span>历史</span>' +
                            '<b class="sw-n" id="sw-n-hist"></b>';

  $("#btn-newpkg").innerHTML = ico("moss-plus", "i") + "<span>新建插件</span>";
  $("#btn-settings").innerHTML = ico("settings", "i");   

  $("#m-x").innerHTML = ico("x", "i");
  $("#btn-refresh").innerHTML   = ico("refresh-cw", "i");

}
$("#q").addEventListener("input", () => { if (side === "hist") renderHist(); else renderList(); });

$("#btn-refresh").onclick = async () => {
  await init();
  await Vue.nextTick();
  const np = (DATA && DATA.packages ? DATA.packages.length : 0);
  const nh = (typeof HIST !== "undefined" && HIST ? HIST.length : 0);
  notice("已刷新", "插件：<b>" + np + "</b> 个<br>历史记录：<b>" + nh + "</b> 条" +
         "<br><br>列表已经是最新的了。",

         {tip: "刷新会重扫插件与历史（正在跑的包不受影响）"});
};

$("#sw-pkg").onclick = () => { setSide("pkg"); window.syncListBars && window.syncListBars(); };
$("#sw-hist").onclick = () => { setSide("hist"); window.syncListBars && window.syncListBars(); };
window.syncListBars && window.syncListBars();       
$("#btn-newpkg").onclick = cmdNewPkg;
document.querySelectorAll(".tab").forEach(b => b.onclick = () => {
  if (b.dataset.tab === "file") fmSelect(fmCtxKey());
  else if (b.dataset.tab === "embed"){                 
    if (embedSupported(cur) && !embedRunning(cur.id)) embedOpen(cur);
    else setTab("embed");
  }
  else setTab(b.dataset.tab);
});

$("#btn-settings").onclick = openSettings;

$("#m-cancel").onclick = closeModal;
$("#m-x").onclick = closeModal;   
$("#m-ok").onclick = () => { const cb = modalCb; closeModal(); if (cb) cb(); };

$("#m-ok2").onclick = () => { const cb = modalCb2; closeModal(); if (cb) cb(); };
$("#m-input").addEventListener("keydown", e => {
  if (e.key === "Enter"){ e.preventDefault(); $("#m-ok").click(); }
  if (e.key === "Escape") closeModal();
});
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });

const NP = {mode: "ai", sug: null, sugFor: "", busy: false};

function npVal(sel){
  const el = $(sel);
  return el ? String(el.value || "") : "";
}

function npSetStatus(text, bad){
  const el = $("#np-tip");
  if (!el) return;
  el.textContent = String(text || "");
  el.className = "np-tip" + (bad ? " bad" : "");
}

function npFill(v){
  [["#np-name", v.name], ["#np-id", v.id], ["#np-desc", v.desc], ["#np-task", v.task]]
    .forEach(([sel, val]) => { const el = $(sel); if (el) el.value = val == null ? "" : val; });
}

function npSetMode(mode){
  NP.mode = mode === "manual" ? "manual" : "ai";
  const ai = NP.mode === "ai";
  const va = $("#np-body-ai"), vm = $("#np-body-manual");
  if (va) va.style.display = ai ? "" : "none";
  if (vm) vm.style.display = ai ? "none" : "";
  const ta = $("#np-tab-ai"), tm = $("#np-tab-manual");
  if (ta) ta.className = ai ? "on" : "";
  if (tm) tm.className = ai ? "" : "on";

  if (!ai && NP.sug) npFill(NP.sug);
  const first = ai ? $("#np-idea") : $("#np-name");
  try{ if (first) first.focus(); }catch(e){}
}

function npBusy(on){
  NP.busy = !!on;
  ["#np-go", "#np-close", "#np-tab-ai", "#np-tab-manual"]
    .forEach(s => { const b = $(s); if (b) b.disabled = !!on; });
  const go = $("#np-go");
  if (go) go.textContent = on ? (NP.mode === "ai" ? "AI 正在想…" : "创建中…") : "创建";
}

async function npCreate(){
  if (NP.busy) return;
  const aiMode = NP.mode === "ai";

  const andStart = aiMode;
  const idea = npVal("#np-idea").trim();
  let v = {id: npVal("#np-id"), name: npVal("#np-name"),
           desc: npVal("#np-desc"), task: npVal("#np-task")};
  if (aiMode){
    if (!idea){
      npSetStatus("先说一句你想让它干什么 —— 一句话就行", true);
      const t = $("#np-idea");
      try{ if (t) t.focus(); }catch(e){}
      return;
    }
    const cached = NP.sug && NP.sugFor === idea;
    if (!cached){
      npBusy(true);
      npSetStatus("AI 正在定 id / 名字 / 介绍…");
      let r = null;
      try{ r = await pywebview.api.ai_suggest_pkg(idea); }
      catch(e){ r = {ok: false, msg: "AI 调用失败：" + (e && e.message ? e.message : e)}; }
      npBusy(false);
      if (!r || !r.ok){
        npSetStatus((r && r.msg) || "AI 没给出结果", true);
        return;
      }
      NP.sug = r;
      NP.sugFor = idea;
      npFill(r);
      v = {id: r.id, name: r.name, desc: r.desc, task: r.task};
      npSetStatus("AI 定好了：" + r.id + " · " + r.name + "（切「手动」可以改）");
    } else {
      v = {id: NP.sug.id, name: NP.sug.name, desc: NP.sug.desc, task: NP.sug.task};
    }
  }
  const id = String(v.id || "").trim().toLowerCase();
  if (!/^[a-z][a-z0-9_-]{0,31}$/.test(id)){
    npSetStatus("包 ID 要小写字母开头，只含 a-z 0-9 - _（最长 32）", true);
    if (NP.mode === "ai") npSetMode("manual");
    return;
  }
  npBusy(true);
  let r2 = null;
  try{ r2 = await pywebview.api.new_pkg(id, v.name || "", v.desc || ""); }
  catch(e){ r2 = {ok: false, msg: "新建失败：" + (e && e.message ? e.message : e)}; }
  npBusy(false);
  if (!r2 || !r2.ok){
    npSetStatus((r2 && r2.msg) || "新建失败（没说明）", true);

    if (aiMode){ NP.sug = null; NP.sugFor = ""; }
    return;
  }
  closeModal();
  await init();                     
  select(id,  true);     
  toast("已新建 " + PSYM + id + (v.name ? " · " + v.name : ""));
  if (!andStart) return;

  let np = (DATA.packages || []).find(p => p.id === id) || null;
  if (!np || !np.dir){
    await refreshPkgs(id);
    np = (DATA.packages || []).find(p => p.id === id) || null;
  }
  if (!np || !np.dir){
    toast("新包建好了，但包列表里还没刷出来 —— 点一下左上角 ⟳ 再开工。", true);
    return;
  }
  if (!cur || cur.id !== id) select(id, true);   
  const task = String(v.task || "").trim() || String(v.desc || "").trim() || ("做一个「" + id + "」的包");
  setTab("ai");
  await new Promise(res => setTimeout(res, 250));   
  window.__AIR.task = task;

  try{ if (typeof aiScopeReset === "function") aiScopeReset(); }catch(e){}
  try{
    if (typeof aiStart === "function") await aiStart({dir: np.dir});
  }catch(e){
    toast("AI 没起得来：" + (e && e.message ? e.message : e), true);
  }
}

function cmdNewPkg(){
  const card = document.querySelector("#modal .card");
  if (card) card.classList.add("np-card");
  const box = $("#m-extra");
  if (!box) return;
  box.hidden = false;
  NP.mode = "ai"; NP.sug = null; NP.sugFor = ""; NP.busy = false;
  box.innerHTML = [
    '<div class="np">',
    '  <div class="np-head">',
    '    <div class="np-title">新建包</div>',
    '    <div class="np-head-r">',
    '      <div class="np-seg">',
    '        <button type="button" id="np-tab-ai" class="on">AI 创建</button>',
    '        <button type="button" id="np-tab-manual">手动</button>',
    '      </div>',
    '      <button type="button" class="np-close" id="np-close" title="关闭（Esc）"',
    '              aria-label="关闭">' + ico("x", "i") + '</button>',
    '    </div>',
    '  </div>',
    '  <div class="np-body" id="np-body-ai">',
    '    <textarea id="np-idea" rows="4" class="np-field np-area" spellcheck="false"',
    '      placeholder="用一句话描述你想让它干什么，AI 会自动补全名字、ID 和介绍..."></textarea>',
    '  </div>',
    '  <div class="np-body" id="np-body-manual" style="display:none">',
    '    <div class="np-grid">',
    '      <input id="np-name" class="np-field" placeholder="名字" autocomplete="off" spellcheck="false">',
    '      <input id="np-id" class="np-field np-mono" placeholder="包 ID (a-z, 0-9, - _)" autocomplete="off" spellcheck="false">',
    '    </div>',
    '    <input id="np-desc" class="np-field" placeholder="一句话介绍" autocomplete="off" spellcheck="false">',
    '    <textarea id="np-task" rows="3" class="np-field np-area" spellcheck="false"',
    '      placeholder="第一句任务（建完直接发给 AI）"></textarea>',
    '  </div>',
    '  <div class="np-tip" id="np-tip"></div>',
    '  <div class="np-foot">',
    '    <button type="button" class="np-btn dark" id="np-go">创建</button>',
    '  </div>',
    '</div>',
  ].join("\n");
  $("#np-tab-ai").onclick = () => npSetMode("ai");
  $("#np-tab-manual").onclick = () => npSetMode("manual");
  $("#np-close").onclick = () => { if (!NP.busy) closeModal(); };
  $("#np-go").onclick = () => npCreate();

  box.onkeydown = e => {
    if (e.key === "Escape" && !NP.busy){ e.stopPropagation(); closeModal(); }
  };
  $("#modal").classList.add("on");
  setTimeout(() => { const t = $("#np-idea"); try{ if (t) t.focus(); }catch(e){} }, 40);
}

async function cmdRemovePkg(p){
  const st = ico("alert-triangle", "i");

  let bkLine = "";
  try{
    const b = await pywebview.api.backup_group_info(p.id);
    if (b && b.ok && b.backups)

      bkLine = "<br>· 备份库里还有它的 <b>" + b.backups + "</b> 次旧快照（占 " +
               humanSize(b.store_bytes) + "，<b>不会跟着删</b>；要清就在文件管理右边那栏" +
               "「版本快照」里删掉它）";
  }catch(e){}
  askConfirm("卸载这个包",
    "将<b>永久删除</b>（不进回收站）：<br>· 包本体 " + p.dir + "<br>" +
    "· 它的数据 user_data/state/" + p.id + "（如果有）<br><br>" +
    "层：" + p.layer + (p.layer === "system" ? "（出厂件 —— 删了升级时会回来）" : "") +
    bkLine +
    "<br>确定吗？",
    async () => {
      consoleKey = "__host__";
      setConsole("__host__", "$ moss --remove " + p.id + " -y", "运行中");
      const r = await pywebview.api.run_host("--remove " + p.id + " -y");
      setConsole("__host__", "$ moss --remove " + p.id + " -y\n\n" + (r.out || "(没有输出)") +
                 "\n" + runTail(r.code, r.out, false), "退出码 " + r.code);
      toast(r.code === 0 ? ("已卸载 " + PSYM + p.id) : "✗ 卸载失败，看「命令行」", r.code !== 0);
      setTab("console");                  
      if (r.code === 0){ cur = null; await init(); renderDetail(); }
    });
}

$("#btn-selfcheck").onclick = async () => {
  consoleKey = "__host__";                
  setTab("console");
  setConsole("__host__", "$ moss --selfcheck", "运行中");
  const t0 = performance.now();
  const r = await pywebview.api.run_host("--selfcheck");
  const ms = Math.round(performance.now() - t0);
  setConsole("__host__",
             "$ moss --selfcheck\n\n" + (r.out || "(没有输出)") + "\n[退出码] " + r.code,
             "退出码 " + r.code + " · " + (ms / 1000).toFixed(2) + " 秒");
};

paintStaticIcons();

function asideMiniOn(){ return $("main").classList.contains("mini"); }
function setAsideMini(on){
  if (on) rememberAsideW();
  $("main").classList.toggle("mini", !!on);
  $("main").classList.remove("hover-aside");
  try{ localStorage.setItem("moss.asideMini", on ? "1" : "0"); }catch(e){}
}

function rememberAsideW(){
  const a = $("main > aside");
  if (!a) return;
  const box = Math.round(a.getBoundingClientRect().width);
  const inline = parseInt(a.style.width, 10);
  const w = (inline > 60 ? inline : (box > 60 ? box : 0));
  if (!w) return;
  $("main").style.setProperty("--aside-w", w + "px");
  try{ localStorage.setItem("moss.asideW", String(w)); }catch(e){}
}
$("#btn-aside-mini").onclick = () => setAsideMini(!asideMiniOn());

{
  const a = $("main > aside");
  if (a){
    a.addEventListener("mouseenter", () => {
      if (asideMiniOn()){ rememberAsideW(); $("main").classList.add("hover-aside"); }
    });
    a.addEventListener("mouseleave", () => $("main").classList.remove("hover-aside"));

    a.addEventListener("pointerup", () => { if (asideMiniOn()) rememberAsideW(); });
  }
}
try{
  const savedW = parseInt(localStorage.getItem("moss.asideW"), 10);
  if (savedW > 60) $("main").style.setProperty("--aside-w", savedW + "px");
  setAsideMini(localStorage.getItem("moss.asideMini") === "1");
}catch(e){}

bindColResize($("#grip-aside"), $("main > aside"), +1, 200,
              () => Math.round((window.innerWidth || 1200) * 0.5), 300);

let _booted = false;
async function boot(){
  if (_booted) return;
  _booted = true;
  try{
    await init();
  }catch(e){
    reportError("界面初始化失败", (e && e.message) || String(e), (e && e.stack) || "");
  }
}

window.addEventListener("pywebviewready", boot);

(function waitBridge(n){
  if (window.pywebview && window.pywebview.api && window.pywebview.api.state){ boot(); return; }
  if (n > 120) return;                 
  setTimeout(() => waitBridge(n + 1), 50);
})(0);
