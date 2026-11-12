const CONSOLE = {};             
let consoleKey = null;          

const HOST_SEED = "每个包有自己的一份命令行，互不串台 —— 在左边选谁就显示谁。\n" +
  "· 右上角「运行」= 跑这个包，输出落进它自己那份（可以同时跑好几个）\n" +
  "· 运行中再点同一个按钮 = 停止；左侧列表行尾那颗绿色停止图标也能停\n" +
  "· 「自检」的输出单独算一份（就是现在这份）";

function consoleBuf(key){
  const k = key || "__host__";
  if (!CONSOLE[k]) CONSOLE[k] = {text: k === "__host__" ? HOST_SEED : "",
                                 raw: k === "__host__" ? HOST_SEED : "", info: "还没跑过"};
  return CONSOLE[k];
}
function consoleTitle(key){
  if (!key) return "moss";
  if (key === "__host__") return "moss 自检";

  if (key.startsWith("hist:")) return "历史 · " + key.slice(5).split(" ")[0].split(/[\\/]/).pop();
  const p = DATA && DATA.packages.find(x => x.id === key);
  return p ? (p.name + "（" + PSYM + key + "）") : key;
}

const CONSOLER = Vue.reactive({rev: 0, flash: ""});
function paintConsole(){
  CONSOLER.flash = "";                   
  CONSOLER.rev++;

  const k = consolePaneKey();
  if (k !== MOSS_TERM.mirrorKey){
    MOSS_TERM.mirrorKey = k;
    MOSS_TERM.mirror[k] = consoleBuf(k).raw || "";
  }

  termAutoStart();

  const pane = $("#pane-console");
  if (termViewing() && MOSS_TERM.term){
    if (pane && !pane.classList.contains("term")) pane.classList.add("term");
    if (pane){
      const vis = !!pane.offsetParent;

      if (vis && !MOSS_TERM.vis) MOSS_TERM.term.focus();
      MOSS_TERM.vis = vis;
    }
    termFitSoon();
  }else{
    if (pane && pane.classList.contains("term")) pane.classList.remove("term");   

    MOSS_TERM.vis = false;
  }
}

const TERMLIVE = {};
function paintInbar(key){
  CONSOLER.rev++;

  const k = key || consolePaneKey();
  const live = !!RUNS[k];
  const was = !!TERMLIVE[k];
  TERMLIVE[k] = live;
  if (termViewing() && k === consolePaneKey() && MOSS_TERM.term){
    MOSS_TERM.term.focus();
    MOSS_TERM.hotUntil = Date.now() + 3000;
  }

  if (was && !live && MOSS_TERM.on && MOSS_TERM.started && MOSS_TERM.owner === k) termWrite("\r");
}
function consolePaneKey(){ return consoleKey || "__host__"; }

function consoleInbarPlaceholder(key){
  if (RUNS[key]) return RUNS[key].term
    ? "这个包跑在终端里 —— 就在那块终端里敲"
    : "包在等你的回答就敲在这里，回车发送（比如 1 / 2 / 3）";
  if (key === "__host__") return "在这儿敲命令，回车执行（像普通命令行那样）";
  return consoleCwd(key)
    ? ("在这儿敲命令，回车就在" + consoleCwdLabel(key) + "里跑")
    : "在这儿敲命令，回车执行（像普通命令行那样）";
}

function consoleCwd(key){
  if (!key || key === "__host__") return "";
  const b = consoleBuf(key);
  if (b.cwd) return String(b.cwd);                    
  const p = ((typeof DATA !== "undefined" && DATA && DATA.packages) || [])
              .find(x => x.id === key);
  if (p && p.dir) return String(p.dir);
  const it = ((typeof HIST !== "undefined" && HIST) || [])
               .find(x => (typeof histKey === "function") && histKey(x) === key);
  return (it && it.cwd) ? String(it.cwd) : "";
}
function consoleCwdLabel(key){
  const isPkg = ((typeof DATA !== "undefined" && DATA && DATA.packages) || [])
                  .some(x => x.id === key);
  return isPkg ? "这个包的目录" : "那次调用当初的目录";
}

const MossConsole = {
  name: "moss-console",
  data(){ return { R: CONSOLER }; },
  computed: {
    key(){ this.R.rev; return consolePaneKey(); },
    buf(){ this.R.rev; return consoleBuf(this.key); },

    text(){ this.R.rev; return this.buf.text || ""; },

    line(){
      this.R.rev;
      if (this.R.flash) return this.R.flash;

      if (termViewing()) return "DOS 终端（常驻） · " + termHintText();
      return consoleTitle(this.key) + " · " + (this.buf.info || "");
    },
    live(){
      this.R.rev;

      return !!RUNS[this.key] || !this.term;
    },
    ph(){ this.R.rev; return consoleInbarPlaceholder(this.key); },

    term(){ this.R.rev; return termViewing(); },
    termHint(){ this.R.rev;
      return termViewing()
        ? ("切回这个包自己的输出（现在是 DOS 终端 · " + termHintText() + "）")
        : "切到 DOS 终端"; },
  },
  mounted(){ this.autoscroll(); },
  updated(){ this.autoscroll(); },
  methods: {
    autoscroll(){
      const el = this.$refs.out;
      if (!el) return;
      const sig = this.key + "\u0000" + this.text.length + "\u0000" + (this.R.flash ? 1 : 0);
      if (sig === this._sig) return;
      this._sig = sig;
      el.scrollTop = el.scrollHeight;
    },
    clearOut(){ if (termViewing()) return termClear(); setConsole(this.key, "", "还没跑过"); },
    copyOut(){ copyOut(); },
    rerun(){ rerunLast(); },
    send(){ sendConsoleLine(); },
    toggleTerm(){ termToggle(); },
  },

  template: `
    <div class="outbar">
      <span id="outinfo">{{ line }}</span>
      <span style="flex:1"></span>
      <button id="btn-term" class="iconbtn" :class="{on: term}" v-html='ico("terminal", "i")'
              :title="termHint" @click="toggleTerm()"></button>
      <button id="btn-copy" class="iconbtn" title="复制全部输出" v-html='ico("copy", "i")' @click="copyOut()"></button>
      <button id="btn-rerun" class="iconbtn" title="再跑一次刚才那条命令" v-html='ico("rotate-cw", "i")' @click="rerun()"></button>
      <button id="btn-clear" class="iconbtn" title="清空输出" v-html='ico("eraser", "i")' @click="clearOut()"></button>
    </div>
    <pre id="out" ref="out">{{ text }}</pre>
    <div id="termhost" ref="termhost"></div>
    <div id="inbar" :class="{off: !live}">
      <span class="ps1">›</span>
      <input id="stdin" :placeholder="ph" autocomplete="off" spellcheck="false"
             :disabled="!live" @keydown.enter.prevent="send()">
      <button id="btn-send" class="btn" :disabled="!live" @click="send()">发送</button>
    </div>`,
};

async function sendStdin(){
  const key = consoleKey || "__host__";
  const inp = $("#stdin");
  if (!inp || inp.disabled) return;
  const run = RUNS[key];

  if (!run || run.term) return;
  const line = inp.value;
  inp.value = "";
  const b = consoleBuf(key);
  setConsole(key, (b.text || "").replace(/\n?$/, "\n") + line + "\n", b.info);
  const r = await pywebview.api.run_input(run.rid, line);
  if (!r || !r.ok) toast("✗ " + ((r && r.msg) || "发不出去"), true);
}

async function sendConsoleLine(){
  const key = consolePaneKey();
  const inp = $("#stdin");
  if (!inp) return;
  const run = RUNS[key];
  if (run && !run.term){ await sendStdin(); return; }
  const line = String(inp.value || "");
  if (!line.trim()) return;
  inp.value = "";

  if (run && run.term){
    MOSS_TERM.owner = key;
    if (!(await termOpen(false, true))) return;
    const echo0 = MOSS_TERM.mode !== "conpty";
    if (echo0) termShow(line + "\r\n");
    termSubmitLine(line, "shell");
    MOSS_TERM.hotUntil = Date.now() + 3000;
    return;
  }

  let r = null;
  try{ r = await pywebview.api.cmd_start(consoleCwd(key), line, key); }catch(e){ r = null; }
  const b = consoleBuf(key);
  if (!r || !r.ok){
    setConsole(key, (b.text || "") + (b.text ? "\n" : "") +
                    "✗ " + ((r && r.msg) || "跑不起来") + "\n", "失败");
    return;
  }
  if (r.cd !== undefined && r.cd !== null){
    b.cwd = String(r.cd || "");                       
    setConsole(key, (b.text || "") + (b.text ? "\n" : "") + "$ cd\n" + b.cwd + "\n", "就绪");
    return;
  }
  RUNS[key] = {rid: r.run_id, cmd: r.cmd || line, manual: true, stopped: false,
               switched: true, tabAtStart: tab};
  setConsole(key, "$ " + (r.cmd || line) + "\n", "运行中");
  paintInbar(key);
  paintRowStats();
  paintActions(selObj());
  pollRun(key);                                       
}
function setConsole(key, text, info){
  const b = consoleBuf(key);
  b.raw = String(text == null ? "" : text);      
  b.text = stripAnsi(text);
  if (info !== undefined && info !== null) b.info = info;

  termMirror(key, b.raw);
  if ((consoleKey || "__host__") === (key || "__host__")) paintConsole();
}
function out(text, info){ setConsole(consoleKey || "__host__", text, info); }

async function copyOut(){
  const text = termViewing() ? (MOSS_TERM.text || "")
                            : ($("#out") ? $("#out").textContent : "");
  let ok = false;
  try { await navigator.clipboard.writeText(text); ok = true; } catch(e){ ok = false; }
  if (!ok){
    try{
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      ok = document.execCommand("copy");
      document.body.removeChild(ta);
    }catch(e){ ok = false; }
  }
  CONSOLER.flash = ok ? ("已复制 " + text.length + " 个字符")
                      : "复制失败（可以手动选中后 Ctrl+C）";
  CONSOLER.rev++;
}

const RUNS = {};                
const PST = {};                 
let pstTimer = null;

async function refreshPkgState(p){
  if (!p){ paintActions(null); return; }
  try{
    const r = await pywebview.api.pkg_states([p.id]);
    if (r && r.ok && r.states && r.states[p.id]) PST[p.id] = r.states[p.id];
  }catch(e){}
  paintActions(p);
  paintRowStats();
}

async function refreshAllStates(){
  if (!DATA) return;
  try{
    const r = await pywebview.api.pkg_states(DATA.packages.map(x => x.id));
    if (r && r.ok) Object.assign(PST, r.states || {});
  }catch(e){}
  paintRowStats();
  paintHistStats();
  paintActions(selObj());
}

function rowStateOf(id){
  const st = PST[id] || {};
  return st.running ? "running" : "idle";
}

function paintRowStats(){
  try{
    const runningIds = Object.keys(PST || {}).filter(k => (PST[k] || {}).running);
    if (typeof noteRunning === "function") noteRunning(runningIds);
  }catch(e){}
  document.querySelectorAll(".item").forEach(el => {
    const id = el.dataset.id;
    const box = el.querySelector(".rowstat");
    if (!box) return;
    const running = rowStateOf(id) === "running";
    box.innerHTML = running
      ? '<button class="ic-run" title="正在运行 —— 点这里停掉它' + esc(runningHint(id)) + '">' +
        ico("square", "i") + '</button>'
      : '<button class="idle" title="运行这个包（﻿' + esc(PSYM + id) + '）">' + ico("play", "i") + '</button>';
    const b = box.querySelector("button");
    if (b) b.onclick = (ev) => {
      ev.stopPropagation();                       
      if (running) stopFromList(id); else runFromList(id);
    };
  });
}

async function runFromList(id){
  const p = DATA.packages.find(x => x.id === id);
  if (!p) return;
  if (RUNS[id]) return;
  const st = PST[id] || {};
  if (st.running){ toast(PSYM + id + " 已经在跑了"); return; }
  if (!cur || cur.id !== id) select(id,  true);
  startRun(p, "");
}

async function stopFromList(id){
  let r;
  if (RUNS[id] && RUNS[id].term){          
    r = await termStop(id);
    toast(r.msg, !r.ok);
    return;
  }
  if (RUNS[id]){
    r = await pywebview.api.run_stop(RUNS[id].rid);
    RUNS[id].stopped = true;
  } else if (typeof embedRunning === "function" && embedRunning(id)){
    await embedStop(id);
    return;
  } else {
    r = await pywebview.api.pkg_stop(id);
    paintRowStats();
  }
  toast(r.msg, !r.ok);
  setTimeout(refreshAllStates, 400);
}

function runningHint(id){
  const st = PST[id] || {};
  const ps = st.procs || [];
  if (!ps.length) return "";
  const p = ps[0];
  const more = ps.length > 1 ? (" …还有 " + (ps.length - 1) + " 个") : "";
  return "\n· pid " + p.pid + (p.started ? "（起于 " + p.started + "）" : "") +
         "\n· " + String(p.cmd || "").slice(0, 120) + more;
}

function pkgRunning(p){
  if (!p) return false;
  return !!(RUNS[p.id] || (embedSupported(p) && embedRunning(p.id)) ||
            ((PST[p.id] || {}).running));
}

function paintActions(p){
  const b = $("#btn-run"), v = $("#btn-vis");
  if (!b || !v) return;

  if (isHist(p)){
    const running = !!RUNS[histKey(p)];
    const gone = p.exists === false;

    b.disabled = gone && !running;
    b.innerHTML = ico(running ? "square" : "play", running ? "i ic-run" : "i") +
                  '<span>' + (running ? "停止" : "运行") + '</span>';
    b.title = gone ? "这个文件已经不在了，跑不了"
                   : (running ? "停掉这次调用（连同它的子进程）"
                              : "在它当初的目录里再跑一次（输出进「命令行」）");
    b.classList.toggle("warn", running);
    v.hidden = true;                         
    v.disabled = true;
    v.innerHTML = ico("eye", "i") + '<span>显示</span>';
    v.title = "这是一次路径调用，没有「包自己的窗口」";
    return;
  }
  const st = (p && PST[p.id]) || {running: false, windows: 0, visible: false};
  const running = pkgRunning(p);         
  b.disabled = !p;

  b.innerHTML = ico(running ? "square" : "play", running ? "i ic-run" : "i") +
                '<span>' + (running ? "停止" : "运行") + '</span>';
  b.title = !p ? "先在左边选一个包或一条历史"
               : (running ? ("停掉它（连同它拉起的子进程）" + runningHint(p.id))
                          : "运行这个包，输出进「命令行」");
  b.classList.toggle("warn", running);

  const m = $("#btn-runsplit");
  if (m){
    m.disabled = !p;
    m.innerHTML = ico(running ? "square" : "play", running ? "i ic-run" : "i") +
                  '<span>' + (running ? "停止" : "运行") + '</span>';
    m.title = !p ? "先在左边选一个包"
                 : (running ? ("停掉它（连同它拉起的子进程）" + runningHint(p.id))
                            : "运行这个包，输出进「命令行」");
    m.classList.toggle("warn", running);
  }

  v.hidden = !p || !st.windows;
  v.disabled = !p || !st.windows;
  v.innerHTML = ico(st.visible ? "eye-off" : "eye", "i") +
                '<span>' + (st.visible ? "隐藏" : "显示") + '</span>';
  v.title = !p ? "先在左边选一个包或一条历史"
               : (!st.windows
                  ? "这个包现在没有开着的窗口（先「运行」或「新窗口运行」）"
                  : (st.visible ? "隐藏它的窗口（不关掉，随时能再显示出来）"
                                : "把它的窗口显示出来并叫到前面"));
}

const MOSS_TERM = {
  on: true,
  started: false,     
  pending: null,      
  failAt: 0,          
  autoTried: false,   
  mode: "",           
  alive: false,
  text: "",           
  term: null, fit: null,
  fw: 0, fh: 0,        
  vis: false,          
  timer: null, busy: false, fitT: null,
  typed: "",          
  hist: [], hi: 0,    
  hotUntil: 0,        
  mirror: {},         
  mirrorKey: "",      

  owner: "",
};

function termViewing(){
  return !!MOSS_TERM.on && (MOSS_TERM.owner || "") === consolePaneKey();
}

function termApiReady(){
  return !!(window.pywebview && pywebview.api &&
            typeof pywebview.api.term_start === "function");
}

function termApiState(){
  if (!window.pywebview || !pywebview.api) return "wait";
  return termApiReady() ? "ok" : "no";
}
function termHintText(){
  const key = consolePaneKey();

  if (RUNS[key]) return "这个包在等你回答 —— 在这里敲，回车发出去";
  if (!MOSS_TERM.started) return "常驻 DOS 终端 · 命令跑完还能接着敲";
  if (MOSS_TERM.mode === "conpty")
    return "真终端（Tab 补全 / Ctrl+C 都是 cmd 的）";

  return "简化终端 · ↑↓ 有历史（没有 Tab 补全 / Ctrl+C）";
}

function termMirror(key, raw){
  const k = key || "__host__";
  if (k !== consolePaneKey()) return;
  const prev = MOSS_TERM.mirror[k];
  MOSS_TERM.mirror[k] = raw;
  if (MOSS_TERM.mode === "conpty"){
    if (MOSS_TERM.on && raw) termNeedPlainView(k);
    return;
  }
  if (prev === undefined || raw === prev) return;         
  if (raw.length <= prev.length) return;                  

  const out = raw.slice(prev.length);

  if (termViewing() && MOSS_TERM.term && out) termShow(out);
}

function termNeedPlainView(k){
  const run = RUNS[k];
  if (run && run.term) return;            

  if (!termViewing()) return;
  termHide();
}

function termAutoStart(){
  if (!MOSS_TERM.on || MOSS_TERM.autoTried || MOSS_TERM.pending) return;
  if (MOSS_TERM.failAt && Date.now() - MOSS_TERM.failAt < 15000) return;   
  const st = termApiState();
  if (st === "wait") return;                    
  if (st === "no"){ MOSS_TERM.on = false; return; }   
  const pane = $("#pane-console");
  if (!pane || !pane.offsetParent) return;      
  MOSS_TERM.autoTried = true;
  termOpen(true);            
}

function termEnsure(){
  if (MOSS_TERM.term) return true;
  if (typeof window.Terminal !== "function"){
    toast("✗ 终端用不了：终端组件没加载上", true);      
    return false;
  }
  const host = $("#termhost");
  if (!host) return false;
  const css = getComputedStyle(document.documentElement);
  const pick = (name, def) => (css.getPropertyValue(name) || "").trim() || def;
  const t = new Terminal({
    cursorBlink: true,
    cursorStyle: "bar",
    fontFamily: pick("--mono", "ui-monospace,Consolas,monospace"),
    fontSize: 13,
    lineHeight: 1.25,
    scrollback: 5000,

    convertEol: true,
    theme: {background: pick("--out-bg", "#14161a"),
            foreground: pick("--out-fg", "#d7dae0"),
            cursor: "#7fb3ff", selectionBackground: "#3a5a8c"},
  });
  MOSS_TERM.term = t;
  try{
    MOSS_TERM.fit = new FitAddon.FitAddon();
    t.loadAddon(MOSS_TERM.fit);
  }catch(e){
    MOSS_TERM.fit = null;      
  }
  t.open(host);
  t.onData(termKeys);
  return true;
}

function termFitSoon(){
  if (MOSS_TERM.fitT) clearTimeout(MOSS_TERM.fitT);
  MOSS_TERM.fitT = setTimeout(() => { MOSS_TERM.fitT = null; termFit(); }, 120);
}
function termFit(){
  const t = MOSS_TERM.term;
  if (!t || !MOSS_TERM.on) return;
  const host = $("#termhost");

  if (!host || !host.offsetParent) return;
  const w = host.clientWidth, h = host.clientHeight;

  if (h < 60 || w < 80) return;

  if (w === MOSS_TERM.fw && h === MOSS_TERM.fh) return;
  MOSS_TERM.fw = w; MOSS_TERM.fh = h;
  try{ if (MOSS_TERM.fit) MOSS_TERM.fit.fit(); }catch(e){}
  if (MOSS_TERM.started && t.cols && t.rows && termApiReady()){
    try{ pywebview.api.term_resize(t.cols, t.rows).catch(() => {}); }catch(e){}
  }
}
function termShow(text){
  const t = MOSS_TERM.term;
  if (!t || !text) return;
  MOSS_TERM.hotUntil = Date.now() + 2500;
  t.write(text);
  MOSS_TERM.text = (MOSS_TERM.text + text).slice(-200000);

  const o = MOSS_TERM.owner;
  if (o && RUNS[o] && RUNS[o].term){
    const c = consoleBuf(o);
    c.raw = (c.raw || "") + text;
    c.text = stripAnsi(c.raw);

    if ((consoleKey || "__host__") === o && !termViewing()) CONSOLER.rev++;
  }
}
function termClear(){
  if (MOSS_TERM.term) MOSS_TERM.term.reset();
  MOSS_TERM.text = "";
  MOSS_TERM.typed = "";

  MOSS_TERM.mirror = {};

  MOSS_TERM.owner = consolePaneKey();
}
function termWrite(text){
  if (!termApiReady()) return;
  MOSS_TERM.hotUntil = Date.now() + 2500;
  try{
    pywebview.api.term_write(text).then(r => {
      if (r && !r.ok && r.msg) toast(r.msg, true);
    }).catch(() => {});
  }catch(e){}
}

function termPump(){
  if (MOSS_TERM.timer){ clearTimeout(MOSS_TERM.timer); MOSS_TERM.timer = null; }
  if (!MOSS_TERM.on || !termApiReady() || document.hidden) return;
  if (!MOSS_TERM.busy){
    MOSS_TERM.busy = true;
    try{
      pywebview.api.term_poll().then(r => {
        MOSS_TERM.busy = false;
        if (!r || !r.ok) return;
        if (r.out) termShow(r.out);
        MOSS_TERM.alive = !!r.alive;
        if (r.mode && r.mode !== MOSS_TERM.mode){ MOSS_TERM.mode = r.mode; paintConsole(); }
        if (MOSS_TERM.started && !r.alive){
          MOSS_TERM.started = false;
          termShow("\r\n[moss] 这个 shell 已经退出了 —— 再点一下终端图标会重新起一个。\r\n");
          paintConsole();
        }
      }).catch(() => { MOSS_TERM.busy = false; });
    }catch(e){ MOSS_TERM.busy = false; }
  }
  const hot = MOSS_TERM.hotUntil > Date.now();
  MOSS_TERM.timer = setTimeout(termPump, hot ? 45 : 220);
}

function termKeys(d){
  MOSS_TERM.hotUntil = Date.now() + 2500;
  const key = consolePaneKey();
  const run = RUNS[key];

  if (run && !run.term){ termLocalTyping(d, "pkg"); return; }
  if (!MOSS_TERM.started) return;
  if (MOSS_TERM.mode === "pipe"){ termLocalTyping(d, "shell"); return; }
  termWrite(d);                    
}

function termLocalTyping(d, kind){
  for (const k of termSplitKeys(d)){
    if (k === "\r" || k === "\n"){
      termShow("\r\n");
      const line = MOSS_TERM.typed;
      MOSS_TERM.typed = "";
      if (line.trim()){
        MOSS_TERM.hist.push(line);
        if (MOSS_TERM.hist.length > 200) MOSS_TERM.hist.shift();
        MOSS_TERM.hi = MOSS_TERM.hist.length;
      }
      termSubmitLine(line, kind);
    }else if (k === "\x7f" || k === "\b"){
      if (MOSS_TERM.typed){ MOSS_TERM.typed = MOSS_TERM.typed.slice(0, -1); termShow("\b \b"); }
    }else if (k === "\x03"){
      MOSS_TERM.typed = "";
      if (kind === "pkg"){
        termShow("^C\r\n");
        stopFromList(consolePaneKey());
      }else{
        termShow("^C\r\n");
        termWrite("\x03");         
      }
    }else if (k === "\x1b[A" || k === "\x1b[B"){
      const h = MOSS_TERM.hist;
      if (!h.length) continue;
      while (MOSS_TERM.typed){ termShow("\b \b"); MOSS_TERM.typed = MOSS_TERM.typed.slice(0, -1); }
      MOSS_TERM.hi = Math.max(0, Math.min(h.length, MOSS_TERM.hi + (k === "\x1b[A" ? -1 : 1)));
      const pick = h[MOSS_TERM.hi] || "";
      MOSS_TERM.typed = pick;
      termShow(pick);
    }else if (k === "\t"){
      MOSS_TERM.typed += "\t";
      termShow("\t");
    }else if (k.length === 1 && k >= " "){
      MOSS_TERM.typed += k;
      termShow(k);
    }

  }
}

function termSplitKeys(d){
  const known = ["\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D", "\x1b[H", "\x1b[F",
                 "\x1b[3~", "\x1bOA", "\x1bOB", "\x1bOC", "\x1bOD"];
  const out = [];
  let i = 0;
  while (i < d.length){
    if (d[i] === "\x1b"){
      const hit = known.find(k => d.startsWith(k, i));
      if (hit){ out.push(hit); i += hit.length; continue; }
      let j = i + 1;
      while (j < d.length && !/[A-Za-z~]/.test(d[j])) j++;
      out.push(d.slice(i, Math.min(j + 1, d.length)));
      i = j + 1;
      continue;
    }
    out.push(d[i]);
    i++;
  }
  return out;
}

function termSubmitLine(line, kind){
  if (kind === "pkg"){
    const key = consolePaneKey();
    const run = RUNS[key];
    if (!run){ termWrite(line + "\r"); return; }   
    try{
      pywebview.api.run_input(run.rid, line).then(r => {
        if (!r || !r.ok) toast("✗ " + ((r && r.msg) || "发不出去"), true);
      }).catch(() => {});
    }catch(e){ toast("✗ 发不出去：" + e, true); }
    return;
  }
  termWrite(line + "\r");          
}

function termWhyNot(){
  if (!termApiReady()) return "这个 moss 版本里没有终端功能";
  if (typeof pywebview.api.term_run !== "function") return "这个 moss 版本里没有终端功能";
  if (!MOSS_TERM.started || !MOSS_TERM.mode) return "终端会话还没起来";
  return "";
}
function termCanRun(){ return termWhyNot() === ""; }

async function termRunPackage(p, args, cwd){
  if (!termApiReady() || typeof pywebview.api.term_run !== "function") return false;

  if (!MOSS_TERM.started || !MOSS_TERM.mode){
    const r0 = await termEnsureSession();

    if (!r0.ok) return false;
  }

  if (!MOSS_TERM.on && !(await termOpen(true))) return false;

  let r = null;
  try{ r = await pywebview.api.term_run(p.id, args || "", cwd || ""); }catch(e){ r = null; }
  if (!r || !r.ok){
    return false;
  }

  if (MOSS_TERM.mode === "pipe") termShow("\r\n" + (r.cmd || "") + "\r\n");
  lastRun = {id: p.id, args: args, label: r.cmd || ("moss " + PSYM + p.id)};
  consoleKey = p.id;
  RUNS[p.id] = {term: true, cmd: r.cmd || "", t0: Date.now(), stopped: false,
                switched: true, tabAtStart: tab};

  MOSS_TERM.owner = p.id;
  paintConsole();
  setStatus("正在跑 " + (RUNS[p.id].cmd || ""));      

  if (tab === "detail") setTab("console");
  paintInbar(p.id);                                   
  paintRowStats();
  paintActions(selObj());
  MOSS_TERM.hotUntil = Date.now() + 3000;             
  termWatchRun(p.id);
  return true;
}

function termWatchRun(id){
  const run = RUNS[id];
  if (!run || !run.term) return;
  if (Date.now() - run.t0 > 6 * 3600 * 1000){          
    delete RUNS[id]; paintRowStats(); paintActions(selObj()); return;
  }
  const tick = () => {
    const r2 = RUNS[id];
    if (!r2 || !r2.term) return;
    pywebview.api.pkg_states([id]).then(r => {
      if (!r || !r.ok || !r.states || !r.states[id]){ r2.timer = setTimeout(tick, 1500); return; }
      PST[id] = r.states[id];
      if (r.states[id].running){ r2.timer = setTimeout(tick, 700); return; }
      termFinishRun(id);
    }).catch(() => { r2.timer = setTimeout(tick, 1500); });
  };
  run.timer = setTimeout(tick, 700);
}

function termFinishRun(id){
  const run = RUNS[id];
  if (!run) return;
  clearTimeout(run.timer);
  delete RUNS[id];
  toast((run.stopped ? "已停止 " : "跑完了 ") + (run.cmd || ""));
  paintRowStats();
  paintActions(selObj());
  paintInbar(id);            
  setTimeout(refreshAllStates, 400);
}

async function termStop(id){
  const run = RUNS[id];
  if (!run) return {ok: true, msg: "它已经结束了"};
  clearTimeout(run.timer);
  let r;
  if (MOSS_TERM.mode === "conpty"){
    termWrite("\x03");
    r = {ok: true, msg: "已发送 Ctrl+C，结果在终端里"};      
  }else{
    r = await pywebview.api.pkg_stop(id);
  }
  run.stopped = true;
  delete RUNS[id];
  paintRowStats();
  paintActions(selObj());
  paintInbar(id);
  setTimeout(refreshAllStates, 400);
  return r;
}

function termEnsureSession(){
  if (MOSS_TERM.started && MOSS_TERM.mode) return Promise.resolve({ok: true, mode: MOSS_TERM.mode});
  if (MOSS_TERM.pending) return MOSS_TERM.pending;
  if (!termApiReady()) return Promise.resolve({ok: false, why: "这个 moss 版本里没有终端功能"});
  if (!termEnsure()) return Promise.resolve({ok: false, why: "终端组件没加载上"});
  const t = MOSS_TERM.term;
  MOSS_TERM.started = true;                    
  MOSS_TERM.pending = new Promise(resolve => {
    const done = (res) => {
      MOSS_TERM.pending = null;
      if (!res.ok) MOSS_TERM.started = false;
      resolve(res);
    };
    try{
      pywebview.api.term_start(t.cols || 100, t.rows || 30).then(r => {
        if (!r || !r.ok){ done({ok: false, why: "终端没有响应"}); return; }
        MOSS_TERM.mode = r.mode || "";
        MOSS_TERM.alive = !!r.alive;
        if (r.history) termShow(r.history);

        done({ok: true, mode: MOSS_TERM.mode});
      }).catch(e => done({ok: false, why: String(e)}));
    }catch(e){ done({ok: false, why: String(e)}); }
  });
  return MOSS_TERM.pending;
}

async function termOpen(quiet, claim){
  const pane = $("#pane-console");
  const key = consolePaneKey();

  if (MOSS_TERM.on && MOSS_TERM.started){
    if (claim) MOSS_TERM.owner = key;           
    paintConsole();
    if (termViewing()) termPump();
    return true;
  }
  MOSS_TERM.on = true;
  MOSS_TERM.autoTried = true;

  if (claim || !MOSS_TERM.owner || MOSS_TERM.owner === key) MOSS_TERM.owner = key;
  MOSS_TERM.fw = 0; MOSS_TERM.fh = 0;      
  if (pane && termViewing()) pane.classList.add("term");
  CONSOLER.rev++;                  
  const r = await termEnsureSession();
  if (!r.ok){
    MOSS_TERM.on = false;
    MOSS_TERM.autoTried = false;           
    MOSS_TERM.failAt = Date.now();         
    MOSS_TERM.fw = 0; MOSS_TERM.fh = 0;
    if (pane) pane.classList.remove("term");
    if (!quiet) toast("终端起不来：" + r.why, true);
    paintConsole();
    return false;
  }
  paintConsole();
  termFitSoon();
  if (termViewing() && MOSS_TERM.term) MOSS_TERM.term.focus();
  termPump();
  return true;
}
function termToggle(){
  if (termViewing()) termHide(); else termOpen(false, true);
}
function termHide(){
  MOSS_TERM.on = false;
  MOSS_TERM.fw = 0; MOSS_TERM.fh = 0;
  if (MOSS_TERM.timer){ clearTimeout(MOSS_TERM.timer); MOSS_TERM.timer = null; }
  const pane = $("#pane-console");
  if (pane) pane.classList.remove("term");
  paintConsole();
}

window.addEventListener("resize", () => { if (MOSS_TERM.on) termFitSoon(); });
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && MOSS_TERM.on) termPump();
});

mountVue(MossConsole, "#pane-console", {ico: ico});
