const EMB = {alive: {}, tick: null, floated: {}};

function embedSupported(p){ return !!(p && p.ui && p.ui.embed); }

async function embedUrl(p){
  const r = await pywebview.api.embed_url(p.id);
  if (!r || !r.ok){ toast("✗ 界面加载不了：" + ((r && r.msg) || ""), true); return null; }
  return r.url;
}
function embedPidOfWin(win){
  const ids = Object.keys(EMB.alive);
  for (let i = 0; i < ids.length; i++){
    const f = EMB.alive[ids[i]].frame;
    if (f && f.contentWindow === win) return ids[i];
  }
  return null;
}
async function embedFrameFor(p){
  const rec0 = EMB.alive[p.id];
  if (rec0 && rec0.frame) return rec0.frame;
  const url = await embedUrl(p);
  if (!url) return null;
  const f = document.createElement("iframe");
  f.dataset.pid = p.id;
  f.src = url;
  f.style.cssText = "width:100%;height:100%;border:0;display:none;background:#fff";
  document.querySelector("#embed-wrap").appendChild(f);
  EMB.alive[p.id] = {frame: f, ready: false, url: url};
  return f;
}
function embedShow(pid){
  const wrap = document.querySelector("#embed-wrap");
  if (wrap) wrap.querySelectorAll("iframe").forEach(f => {
    f.style.display = (f.dataset.pid === pid) ? "block" : "none";
  });

  Object.keys(EMB.alive).forEach(id => pushEmbedEvent(id, "visible", {visible: id === pid}));
}

async function embedOpen(p, opts){
  const o = opts || {};
  if (!embedSupported(p)) return;
  const rec = EMB.alive[p.id];
  if (!rec){                                   
    const r = await pywebview.api.embed_start(p.id, o.cwd || "", o.args || "");
    if (!r || !r.ok){ toast("✗ 起不来：" + ((r && r.msg) || ""), true); return; }
    const f = await embedFrameFor(p);
    if (!f){ await pywebview.api.embed_stop(p.id); return; }   
    embedTick(true);
  }
  embedShow(p.id);
  paintEmbedTab();
  if (!o.keepTab) setTab("embed");
}
async function embedStop(pid, quiet){
  if (!pid) return;
  const r = await pywebview.api.embed_stop(pid);
  if (!quiet) toast(r && r.ok ? "已停掉这个包的界面" : ((r && r.msg) || "没在跑"), !(r && r.ok));
  const rec = EMB.alive[pid];
  if (rec && rec.frame) rec.frame.remove();     
  delete EMB.alive[pid];
  delete EMB.floated[pid];                      
  if (!Object.keys(EMB.alive).length) embedTick(false);
  embedShow(Object.keys(EMB.alive)[0] || null);  
  paintEmbedTab(); paintActions(selObj()); EMBR.rev++;
  setTimeout(refreshAllStates, 400);            
}
function embedRunning(pid){ return !!EMB.alive[String(pid)]; }

function pushEmbedEvent(pid, name, data){
  const rec = EMB.alive[pid];
  const f = rec && rec.frame;
  if (!f || !f.contentWindow) return;
  try{ f.contentWindow.postMessage({moss: 1, kind: "event", name: name, data: data}, "*"); }
  catch(e){}
}

window.__mossEmbedFromBackend = function(pid, line){
  const rec = EMB.alive[String(pid)];
  const f = rec && rec.frame;
  if (!f || !f.contentWindow) return;
  let msg = null;
  try{ msg = JSON.parse(line); }catch(e){ return; }
  try{
    if (msg.event) f.contentWindow.postMessage({moss: 1, kind: "event",
                                                name: msg.event, data: msg.data}, "*");
    else f.contentWindow.postMessage({moss: 1, kind: "result", id: msg.id, ok: msg.ok,
                                      result: msg.result, error: msg.error}, "*");
  }catch(e){}
};
window.__mossEmbedGone = function(pid, code){
  pid = String(pid);
  if (EMB.alive[pid]){
    const rec = EMB.alive[pid];
    if (rec.frame) rec.frame.remove();
    delete EMB.alive[pid];
    delete EMB.floated[pid];
    if (!Object.keys(EMB.alive).length) embedTick(false);
    toast("这个包的界面已经结束（退出码 " + code + "）", code !== 0);
    paintEmbedTab(); paintActions(selObj()); EMBR.rev++;
  }
};

window.__mossFloatDock = async function(pid){
  pid = String(pid);
  EMB.floated[pid] = false;
  EMBR.rev++;
  const p = (DATA.packages || []).find(x => String(x.id) === pid);
  if (p && embedSupported(p) && !EMB.alive[pid]){
    await embedOpen(p, {keepTab: true});       
    toast("已收回主窗口");
  }
};
window.__mossFloatClosed = function(pid){
  pid = String(pid);
  EMB.floated[pid] = false;
  const rec = EMB.alive[pid];
  if (rec && rec.frame) rec.frame.remove();
  delete EMB.alive[pid];
  if (!Object.keys(EMB.alive).length) embedTick(false);
  embedShow(Object.keys(EMB.alive)[0] || null);
  paintEmbedTab(); paintActions(selObj()); EMBR.rev++;

  toast("这个包已经停了");
};

window.__mossFloatFailed = async function(pid, msg){
  pid = String(pid);
  EMB.floated[pid] = false;
  delete EMB.alive[pid];
  paintEmbedTab();
  toast("✗ " + (msg || "窗口没打开，已经退回这一页"), true);
  const p = (DATA.packages || []).find(x => String(x.id) === pid);
  if (p && embedSupported(p)) await embedOpen(p, {keepTab: true});
  paintEmbedTab(); EMBR.rev++;
};

window.addEventListener("message", async (ev) => {
  const m = ev.data;
  if (!m || m.moss !== 1) return;
  const pid = embedPidOfWin(ev.source);
  if (!pid) return;
  if (m.kind === "call"){
    const r = await pywebview.api.embed_send(pid, JSON.stringify(
      {id: m.id, method: m.method, params: m.params || {}}));
    if (r && !r.ok){
      const rec = EMB.alive[pid];
      if (rec && rec.frame && rec.frame.contentWindow) rec.frame.contentWindow.postMessage(
        {moss: 1, kind: "result", id: m.id, ok: false, error: (r.msg || "送不到后端")}, "*");
    }
  } else if (m.kind === "ready"){
    if (EMB.alive[pid]) EMB.alive[pid].ready = true;
    pushEmbedEvent(pid, "theme", {dark: matchMedia("(prefers-color-scheme: dark)").matches});
    pushEmbedEvent(pid, "visible", {visible: tab === "embed" && !!cur && cur.id === pid});
    paintEmbedTab();
  } else if (m.kind === "drag"){
    if (typeof frameDrag === "function") frameDrag(pid, m.phase);
  }
});

function paintEmbedTab(){
  const tabBtn = document.querySelector('.tab[data-tab="embed"]');
  const ok = embedSupported(cur);
  if (tabBtn){
    tabBtn.hidden = !ok;

    const label = ok ? (cur.ui.title || cur.name || "界面") : "界面";
    const key = (ok ? cur.id : "") + "|" + label;
    if (tabBtn.dataset.painted !== key){
      tabBtn.dataset.painted = key;
      const own = ok && typeof iconInner === "function" ? iconInner(cur) : "";
      tabBtn.innerHTML = (own ? '<span class="tab-ico">' + own + "</span>"
                              : ico("app-window", "i")) +
                         '<span class="tab-name"></span>';
      tabBtn.querySelector(".tab-name").textContent = label;
    }
  }
  paintEmbedActions(ok);
  if (!ok && tab === "embed") setTab("detail");
  EMBR.rev++;
}

function paintEmbedActions(ok){
  const rl = $("#btn-embed-reload"), fl = $("#btn-embed-window");
  if (!rl || !fl) return;
  const has = !!ok && !!cur;
  const alive = has && embedRunning(cur.id);
  const floated = has && !!EMB.floated[cur.id];
  rl.hidden = !has;
  fl.hidden = !has;
  rl.disabled = !alive;
  fl.disabled = floated;
  if (!rl.dataset.done){                    
    rl.dataset.done = "1";
    rl.innerHTML = ico("refresh-cw", "i");
    rl.onclick = () => embedReloadHere();
    fl.innerHTML = ico("app-window", "i");
    fl.onclick = () => embedFloatHere();
  }
  rl.title = alive ? "重新加载这个包的界面" : "这个包的界面还没在跑";
  fl.title = floated ? "已经弹成独立窗口了（在那边点最小化就收回）"
                     : "把这一页弹成独立窗口（那边点最小化＝收回，点关闭＝结束）";
}

function embedReloadHere(){
  const rec = embedSupported(cur) ? EMB.alive[cur.id] : null;
  if (rec && rec.frame) rec.frame.src = rec.frame.src;
}

async function embedFloatHere(){
  const p = embedSupported(cur) ? cur : null;
  if (!p) return;
  const rec = EMB.alive[p.id];
  if (rec && rec.frame) rec.frame.remove();
  delete EMB.alive[p.id];
  if (!Object.keys(EMB.alive).length) embedTick(false);
  EMB.floated[p.id] = true;
  paintEmbedTab();
  const r = await pywebview.api.ui_float(p.id);
  if (!r || !r.ok){                     
    EMB.floated[p.id] = false;
    toast("✗ " + ((r && r.msg) || "弹不出来"), true);
    await embedOpen(p, {keepTab: true});
    return;
  }
  toast(r.msg);
  paintEmbedTab();
}

const EMBR = Vue.reactive({rev: 0});

const MossEmbed = {
  name: "moss-embed",
  data(){ return { R: EMBR }; },
  computed: {
    p(){ this.R.rev; return embedSupported(cur) ? cur : null; },
    aliveN(){ this.R.rev; return Object.keys(EMB.alive).length; },

    floatedHere(){ this.R.rev; const p = this.p; return !!(p && EMB.floated[p.id]); },
  },
  methods: {
    async floatBack(){
      const p = this.p;
      if (!p) return;
      const r = await pywebview.api.ui_dock(p.id);
      EMB.floated[p.id] = false;
      await embedOpen(p, {keepTab: true});
      if (r && r.msg) toast(r.msg);
    },

    async floatStop(){
      const p = this.p;
      if (!p) return;
      await pywebview.api.ui_float_stop(p.id);
    },
  },
  template: `
    <div id="embed-wrap">
      <div id="embed-floated" v-if="floatedHere" @click="floatBack()">
        <span v-html='ico("app-window", "i")'></span>
        <span>已经弹到窗口里了 —— 点这里收回（或点那个窗口的最小化）</span>
      </div>
      <div id="embed-empty" class="empty" v-show="!aliveN && !floatedHere">
        还没跑 —— 点右上角「运行」就在这一页里开起来</div>
    </div>`,
};

async function pushWindowIcon(p){
  try{
    if (!p) return;
    let src = "";
    if (p.icon_svg){
      const svg = String(p.icon_svg)
        .replace(/currentColor/g, "#0071e3")
        .replace(/width="24"/, 'width="256"').replace(/height="24"/, 'height="256"');
      src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    } else if (p.icon){
      src = p.icon;                       
    }
    if (!src) return;
    const img = new Image();
    await new Promise((res, rej) => { img.onload = res; img.onerror = rej; img.src = src; });
    const S = 256, pad = Math.round(S * 0.06);
    const cv = document.createElement("canvas");
    cv.width = cv.height = S;
    const g = cv.getContext("2d");
    g.drawImage(img, pad, pad, S - pad * 2, S - pad * 2);
    const b64 = (cv.toDataURL("image/png").split(",")[1] || "");
    if (b64) await pywebview.api.set_win_icon(p.id, b64);
  }catch(e){}
}

async function embedPollConsole(){
  const ids = Object.keys(EMB.alive);
  for (let i = 0; i < ids.length; i++){
    const r = await pywebview.api.embed_take(ids[i]);
    if (r && r.ok && r.text){
      const b = consoleBuf(ids[i]);
      setConsole(ids[i], ((b.text || "") + r.text), b.info || "内嵌运行中");
    }
  }
}

function embedTick(on){
  if (on && !EMB.tick) EMB.tick = setInterval(embedPollConsole, 1000);
  if (!on && EMB.tick){ clearInterval(EMB.tick); EMB.tick = null; }
}
async function clickRun(p){
  if (isHist(p)){
    const key = histKey(p);
    if (RUNS[key]){ await stopRun(key); return; }
    rerunHist(p, argsInput() ? argsInput().value : undefined);
    return;
  }
  const st0 = PST[p.id] || {};

  if (RUNS[p.id]){ await stopRun(p.id); return; }
  if (embedSupported(p)){
    if (embedRunning(p.id)){ await embedStop(p.id); return; }
    if (st0.running){                      
      const r = await pywebview.api.pkg_stop(p.id);
      toast(r.msg, !r.ok);
      paintRowStats();
      setTimeout(refreshAllStates, 400);
      return;
    }
    await embedOpen(p);
    return;
  }
  const st = PST[p.id] || {};
  if (st.running){                       
    const r = await pywebview.api.pkg_stop(p.id);
    toast(r.msg, !r.ok);
    paintRowStats();
    setTimeout(() => refreshPkgState(p), 400);
    return;
  }
  startRun(p, argsInput() ? argsInput().value : "");
}

function argsInput(){ return $("#args") || $("#hargs"); }

async function startRun(p, args, cwd, opts){
  if (RUNS[p.id]) return;                
  const o = opts || {};

  if (embedSupported(p) && !o.rawRun){
    await embedOpen(p, {keepTab: !!o.keepTab, args: args || "", cwd: cwd || ""});
    return;
  }
  const cmd = "moss " + PSYM + p.id + ((args || "").trim() ? " " + args.trim() : "");
  lastRun = {id: p.id, args: args, label: cmd};
  consoleKey = p.id;                     

  if (!o.noTerm && typeof termRunPackage === "function" && await termRunPackage(p, args, cwd)) return;
  setConsole(p.id, "$ " + cmd, "运行中");
  const r = await pywebview.api.run_start(p.id, args || "", cwd || "");
  if (!r.ok){
    setConsole(p.id, "$ " + cmd + "\n\n启动失败：" + (r.msg || ""), "启动失败");
    toast("✗ " + (r.msg || "启动失败"), true);
    return;
  }
  RUNS[p.id] = {rid: r.run_id, cmd: cmd, timer: null, stopped: false,
                switched: false, tabAtStart: tab};   
  setStatus("正在跑 " + cmd);                       
  paintInbar(p.id);                      

  if (tab === "console")
    setTimeout(() => { const i = $("#stdin"); if (i && !i.disabled) i.focus(); }, 60);
  refreshPkgState(p);                    
  pollRun(p.id);
}

function hasRealOutput(text){
  return String(text || "").split(/\r?\n/).map(l => l.trim()).some(l =>
    l && !/^\[(执行|目录|PID|运行总长|结果)\]/.test(l) &&
    !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(l));
}

function maybeAutoSwitch(id, run, outText){
  if (run.switched || !hasRealOutput(outText)) return;
  run.switched = true;
  if (tab === run.tabAtStart){
    consoleKey = id;
    setTab("console");
  }
}

function pollRun(id){
  const run = RUNS[id];
  if (!run) return;
  run.timer = setTimeout(async () => {
    if (!RUNS[id]) return;
    const r = await pywebview.api.run_poll(run.rid);
    if (!r.ok){ finishRun(id, -1, ""); return; }
    setConsole(id, "$ " + run.cmd + "\n\n" + (r.out || "（还没有输出）"), "运行中");
    maybeAutoSwitch(id, run, r.out);
    if (r.running) pollRun(id);
    else finishRun(id, r.code, r.out);
  }, 200);
}

function finishRun(id, code, text){
  const run = RUNS[id];
  if (!run) return;
  clearTimeout(run.timer);
  delete RUNS[id];
  const stopped = !!run.stopped;
  maybeAutoSwitch(id, run, text);        

  if (!stopped)
    setStatus("跑完了 " + run.cmd + " · 退出码 " + code, code !== 0);
  setConsole(id, "$ " + run.cmd + "\n\n" + (text || "(这个包没有输出)") + "\n" +
             runTail(code, text, stopped),

             stopped ? "已停止" : ("退出码 " + code));

  paintRowStats();

  if ((cur && cur.id === id) || (curH && histKey(curH) === id)) renderDetail();
  paintInbar(id);                        
  paintActions(selObj());
  paintHistStats();

  setTimeout(refreshAllStates, 600);
  if (side === "hist") loadHist().then(() => { renderHist(); });
}

function runTail(code, text, stopped){
  if (stopped) return "[已停止]（这次是点了停止 —— 不是故障）";
  const body = String(text || "").split(/\r?\n/).map(l => l.trim()).filter(l =>
    l && !/^\[(执行|目录|PID|运行总长|结果)\]/.test(l) &&
    !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(l)).join("");
  if (code !== 0 && !body) return "[退出码] " + code + "（它没有输出任何错误信息）";
  return "[退出码] " + code;
}

async function stopRun(id){
  const run = RUNS[id];
  if (!run) return;

  if (run.term && typeof termStop === "function"){
    const r0 = await termStop(id);
    toast(r0.msg, !r0.ok);
    return;
  }
  const r = await pywebview.api.run_stop(run.rid);
  toast(r.msg, !r.ok);
  run.stopped = true;                    
  setTimeout(refreshAllStates, 400);
}

mountVue(MossEmbed, "#pane-embed", {ico: ico});
