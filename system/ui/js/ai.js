function stickAfterScroll(st, m){
  st = st || {};
  m = m || {};
  if (st.auto) return !!st.stick;                 
  const ch = Number(m.clientHeight || 0);
  const sh = Number(m.scrollHeight || 0);
  if (!ch) return true;                           
  if (sh <= ch + 4) return true;                  
  return Number(m.gap || 0) < 80;
}

const AIR = Vue.reactive({
  rev: 0, curId: "", curDir: "", info: null, infoTryAt: 0, err: "",
  task: "", running: false, steps: [], say: [], result: null,
  seconds: 0, busy: false, tick: null,
  maxTokens: 100000000, warnTokens: 80000000,   
  phase: "",                   
  context: 128000,             
  compactAt: 102400,           
  promptTokens: 0,             
  runs: [],                   
  viewing: "",                

  liveKey: "", liveRunId: "", liveTask: "", liveListFor: "",

  doneWait: 0,

  pendingDone: null,

  livePkg: "",
  maxMillions: 100,            
  model: "",                   
  diskNoted: "",               
  skillsRev: "",               
  snapNoted: "",               

  askNoted: "",

  contId: "", contTask: "", lastId: "", lastAdopted: "",

  sentTask: "", muted: 0, pickId: "",

  turns: [], cur: -1, turnSeq: 0,

  altOn: false,

  selfSkills: {skills: [], from_pkgs: [], broken: []},
  selfOpen: false, selfWho: "", selfText: "", selfTab: "pending",

  allow: [], full: false, dropHot: false, newPath: "",

  perm: null,

  permHover: false, permPinned: false,

  histOpen: false,

  otherOpen: false,

  modelOpen: false, modelQ: "",

  permPop: false,

  ask: null, askText: "", askBusy: false, answeredQids: [],

  liveUsage: null, killed: [], stopping: false,

  msgOpen: false, msgWho: "", msgData: null, msgBusy: false,

  stepOpen: null, modalTab: "detail",

  stick: true,
  auto: false,

  newPathErr: "",

  attachments: [], pasteAsFile: true, inputDropHot: false, inputDropAt: 0,

  paletteColor: "", paletteOpen: false,

  balance: null, balanceLoading: false,
  pageVisible: false,

  partial: null, ptBusy: false,

  att: null,
});

const ATTACH_TEXT_MIN = 1000;
const ATTACH_FILE_MAX = 12 * 1024 * 1024;

const AI_PALETTE_PRESETS = [
  {name: "雾蓝", color: "#60A5FA"},
  {name: "薄荷", color: "#34D399"},
  {name: "紫雾", color: "#A78BFA"},
  {name: "晚霞", color: "#FB7185"},
  {name: "暖橙", color: "#FBBF24"},
  {name: "青碧", color: "#22D3EE"},
];

function aiPackage(){ return cur && cur.id ? cur : null; }

function aiPkgIdOfDir(dir){
  const d = normDir(dir);
  if (!d) return "";
  const all = (DATA && DATA.packages) || [];
  const p = all.filter(x => normDir(x.dir) === d)[0];
  return (p && p.id) || "";
}
function aiLivePkg(){
  if (AIR.livePkg) return AIR.livePkg;
  const rid = String(AIR.liveRunId || "");
  if (!rid) return "";
  const r = (AIR.runs || []).filter(x => x && String(x.id) === rid)[0];
  return r ? aiPkgIdOfDir(r.workdir) : "";
}

function aiLiveHere(){
  if (!AIR.running) return false;
  const who = aiLivePkg();
  if (!who) return true;
  const here = (aiPackage() || {}).id || "";
  return !here || who === here;
}

function aiScopeReset(){
  AIR.contId = ""; AIR.contTask = ""; AIR.viewing = "";
  AIR.steps = []; AIR.result = null; AIR.lastId = ""; AIR.lastAdopted = "";
  AIR.sentTask = ""; AIR.muted = 0; AIR.pickId = "";
  AIR.turns = []; AIR.cur = -1;                 
  AIR.liveKey = ""; AIR.liveTask = ""; AIR.liveListFor = "";
}

function humanTokens(n){
  const v = Number(n || 0);
  if (v >= 1000000) return (v / 1000000).toFixed(2) + "M";
  if (v >= 1000) return (v / 1000).toFixed(1) + "k";
  return String(v);
}

function cntok(n){
  const v = Math.round(Number(n) || 0);
  const neg = v < 0 ? "-" : "", a = Math.abs(v);
  const cut = (x, d) => {
    const s = (x).toFixed(d);
    return s.replace(/\.?0+$/, "");
  };
  if (a >= 100000000) return neg + cut(a / 100000000, 2) + "亿";
  if (a >= 10000) return neg + cut(a / 10000, 1) + "万";
  return neg + String(a);
}

function aiAddAttachment(a){
  if (!a || !a.name) return null;
  const mime = String(a.mime || "");
  const key = a.kind === "path" ? ("p:" + String(a.path || ""))
            : (a.kind === "text" ? ("t:" + String(a.name || "") + ":" + String(a.text || "").length)
                                 : ("d:" + String(a.name || "") + ":" + mime + ":" +
                                    String(a.data_url || "").slice(0, 80)));
  if (AIR.attachments.some(x => x.key === key)) return null;
  a.key = key;
  a.mime = mime;
  AIR.attachments.push(a);
  AIR.rev++;
  return a;
}
function aiAttachPaths(items){
  let n = 0;
  (items || []).forEach(it => {
    if (!it || !it.path || it.isDir === true) return;
    const name = it.name || String(it.path).replace(/^.*[\\/]/, "");
    if (aiAddAttachment({kind: "path", name: name, path: String(it.path),
                         mime: it.mime || "", size: Number(it.size || 0)})) n++;
  });
  return n;
}
function aiPasteName(text){
  const first = String(text || "").trim().split(/\r?\n/)[0].slice(0, 28)
    .replace(/[\\/:*?"<>|]/g, "_");
  return (first || "粘贴文本") + ".txt";
}

function jsonDecodeText(v){
  let t = String(v == null ? "" : v);
  if (/\u[0-9a-fA-F]{4}/.test(t) || /%[0-9a-fA-F]{2}/.test(t)){
    try { t = JSON.parse('"' + t.replace(/"/g, '\\"') + '"'); } catch(e){}
    try { t = decodeURIComponent(t); } catch(e){}
  }
  return t;
}
function jsonDecodeDeep(v){
  if (typeof v === "string") return jsonDecodeText(v);
  if (Array.isArray(v)) return v.map(jsonDecodeDeep);
  if (v && typeof v === "object"){
    const out = {};
    Object.keys(v).forEach(k => { out[k] = jsonDecodeDeep(v[k]); });
    return out;
  }
  return v;
}
function jsonIsLongString(v){
  const t = String(v || "");
  return t.length > 1200 ||
         /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(t) ||
         /base64,[A-Za-z0-9+/=]{200,}/.test(t);
}
function jsonTreeHtml(v, key, depth, forceOpen){
  depth = Number(depth || 0);
  const k = (key === undefined || key === null || key === "") ? "" :
    '<span class="j-key">"' + esc(jsonDecodeText(String(key))) + '"</span><span class="j-punc">: </span>';
  if (v === null || v === undefined) return k + '<span class="j-null">null</span>';
  if (typeof v === "boolean") return k + '<span class="j-bool">' + (v ? "true" : "false") + '</span>';
  if (typeof v === "number") return k + '<span class="j-num">' + esc(v) + '</span>';
  if (typeof v === "string"){
    const text = jsonDecodeText(v);
    if (!forceOpen && jsonIsLongString(text)){
      const head = text.slice(0, 200).replace(/\s+/g, " ");
      return '<details class="j-node j-long"><summary>' + k +
             '<span class="j-str">"' + esc(head) + '…"</span>' +
             '<span class="j-dim">（' + text.length + ' 字，点击展开）</span></summary>' +
             '<pre class="j-pre">' + esc(text) + '</pre></details>';
    }
    return k + '<span class="j-str">"' + esc(text) + '"</span>';
  }
  if (Array.isArray(v)){
    if (!v.length) return k + '<span class="j-punc">[]</span>';
    const open = forceOpen || (depth < 2 && v.length <= 12) ? " open" : "";
    const inner = v.map(function(x){ return '<div class="j-row">' + jsonTreeHtml(x, undefined, depth + 1, false) + '</div>'; }).join("");
    return k + '<details class="j-node"' + open + '><summary><span class="j-punc">[</span> ' +
           '<span class="j-dim">' + v.length + ' 项</span><span class="j-punc">]</span></summary>' +
           '<div class="j-children">' + inner + '</div></details>';
  }
  if (typeof v === "object"){
    const keys = Object.keys(v);
    if (!keys.length) return k + '<span class="j-punc">{}</span>';
    const open = forceOpen || (depth < 2 && keys.length <= 10) ? " open" : "";
    const inner = keys.map(function(key){
      return '<div class="j-row">' + jsonTreeHtml(v[key], key, depth + 1, false) + '</div>';
    }).join("");
    return k + '<details class="j-node"' + open + '><summary><span class="j-punc">{</span> ' +
           '<span class="j-dim">' + keys.length + ' 键</span><span class="j-punc">}</span></summary>' +
           '<div class="j-children">' + inner + '</div></details>';
  }
  return k + '<span class="j-dim">' + esc(String(v)) + '</span>';
}

window.__AIR = AIR;

let _aiApiWait = null;
function aiApiReady(){
  return !!(window.pywebview && window.pywebview.api);
}
function aiWaitApi(timeoutMs){
  if (aiApiReady()) return Promise.resolve(window.pywebview.api);
  if (_aiApiWait) return _aiApiWait;
  const limit = timeoutMs || 10000;
  _aiApiWait = new Promise(resolve => {
    const t0 = Date.now();
    const timer = setInterval(() => {
      if (aiApiReady()){
        clearInterval(timer);
        _aiApiWait = null;
        resolve(window.pywebview.api);
      }else if (Date.now() - t0 > limit){
        clearInterval(timer);
        _aiApiWait = null;
        resolve(null);
      }
    }, 50);
  });
  return _aiApiWait;
}

async function aiStartPage(){
  const api = await aiWaitApi();
  if (!api){
    AIR.err = "读不到 AI 状态：宿主桥一直没连上，重启 moss 界面再试。";
    AIR.rev++;
    return;
  }
  aiLoadRuns();
  aiLoadSkills();
  aiPollOnce();
}

function aiWhereDir(){
  const p = aiPackage();
  return (p && p.dir) || "";
}

async function aiRefreshInfo(force){
  try {
    const api = await aiWaitApi();
    if (!api) return;                         
    AIR.info = await api.ai_info(aiWhereDir(), !!force);
    if (AIR.info && AIR.info.ok){
      if (AIR.info.max_tokens) AIR.maxTokens = AIR.info.max_tokens;
      if (AIR.info.warn_tokens) AIR.warnTokens = AIR.info.warn_tokens;
      AIR.maxMillions = Math.round((AIR.maxTokens / 1000000) * 1000) / 1000;
      if (AIR.info.context) AIR.context = AIR.info.context;
      if (AIR.info.compact_at) AIR.compactAt = AIR.info.compact_at;

      if (AIR.info.allow) AIR.allow = AIR.info.allow;

      if (AIR.info.full_access !== undefined) AIR.full = !!AIR.info.full_access;

      const ms = AIR.info.models || [];
      if (AIR.info.model && (!AIR.model || (ms.length && ms.indexOf(AIR.model) < 0)))
        AIR.model = AIR.info.model;

      const prof = String(AIR.info.profile || "");
      if (AIR.pageVisible && prof && (!AIR.balance || AIR.balance.provider !== prof))
        aiRefreshBalance(false);
    }
    AIR.err = "";
  } catch (e) {
    AIR.err = "读不到 AI 状态：" + (e && e.message ? e.message : e);
  }
  AIR.rev++;
}

async function aiLoadUiState(){
  try{
    const api = await aiWaitApi(3000);
    if (!api || !api.ai_ui_state) return;
    const r = await api.ai_ui_state();
    if (r && r.ok){
      const c = String(r.palette || "");
      AIR.paletteColor = /^#[0-9a-fA-F]{6}$/.test(c) ? c : "";
      AIR.rev++;
    }
  }catch(e){  }
}
async function aiSaveUiState(values){
  try{
    const api = await aiWaitApi(3000);
    if (!api || !api.ai_ui_state_set) return null;
    return await api.ai_ui_state_set(values || {});
  }catch(e){ return null; }
}

function aiShortBalance(raw){
  const s = String(raw || "").replace(/^余额[:：]\s*/, "").trim();
  const m = s.match(/([A-Za-z]{3})\s*([-+]?\d+(?:\.\d+)?)/);
  if (m){
    const cur = m[1].toUpperCase();
    const sign = cur === "CNY" ? "¥" : (cur === "USD" ? "$" : (cur + " "));
    return sign + m[2];
  }
  const n = s.match(/[-+]?\d+(?:\.\d+)?/);
  return n ? n[0] : (s ? s.slice(0, 18) : "?");
}

async function aiRefreshBalance(auto){
  if (AIR.balanceLoading) return;
  const provider = String((AIR.info && AIR.info.profile) || "");
  if (!provider){
    AIR.balance = {ok: false, text: "?", msg: "还没配置 AI 服务商", provider: ""};
    AIR.rev++;
    return;
  }
  AIR.balanceLoading = true;
  AIR.rev++;
  try{
    const api = await aiWaitApi(5000);
    if (!api || !api.ai_balance){
      AIR.balance = {ok: false, text: "?", msg: "宿主桥没连上，暂时查不了余额", provider: provider};
      return;
    }
    const r = await api.ai_balance(provider, {});
    const ok = !!(r && r.ok);
    const full = String((r && r.msg) || (ok ? "余额已更新" : "这家不支持查询余额"));
    AIR.balance = {
      ok: ok,
      text: ok ? aiShortBalance(full) : "?",
      full: full,
      msg: full,
      detail: String((r && r.detail) || ""),
      provider: provider,
      at: Date.now(),
      auto: !!auto,
    };
  }catch(e){
    AIR.balance = {ok: false, text: "?", msg: "查余额失败：" + (e && e.message ? e.message : e),
                   provider: provider, at: Date.now(), auto: !!auto};
  }finally{
    AIR.balanceLoading = false;
    AIR.rev++;
  }
}

async function aiSetMode(){
  toast("权限就在下面那份清单里：给哪一行勾上「读」「写」，它就能碰哪儿", true);
}

function addPathOk(p){
  const s = String(p || "").trim();
  if (!s) return false;
  if (s === "*") return true;                       

  return /^[a-zA-Z]:[\\/]/.test(s) || /^\\\\[^\\]/.test(s);
}

const AI_CN_NUM = ["零", "一", "两", "三", "四", "五", "六", "七", "八", "九", "十"];
function aiCnNum(n){
  const v = Math.max(0, Math.floor(Number(n) || 0));
  return v <= 10 ? AI_CN_NUM[v] : String(v);
}

function permParts(p){
  const s = String(p || "").trim();
  if (!s || s === "*") return null;
  const norm = s.replace(/\//g, "\\").replace(/\\+$/, "");
  let head = "", rest = norm, m = null;
  m = /^([A-Za-z]:)\\?/.exec(norm);
  if (m){ head = m[1] + "\\"; rest = norm.slice(m[0].length); }
  else {
    m = /^(\\\\[^\\]+\\[^\\]+)\\?/.exec(norm);
    if (m){ head = m[1] + "\\"; rest = norm.slice(m[0].length); }
  }
  const bits = rest.split("\\").filter(Boolean);
  if (!bits.length) return {head: head, mid: "", tail: ""};
  const keep = Math.min(2, bits.length);
  const tail = bits.slice(bits.length - keep).join("\\");
  const midBits = bits.slice(0, bits.length - keep);
  return {head: head, mid: midBits.length ? (midBits.join("\\") + "\\") : "", tail: tail};
}

function permOwnerOf(pth){
  const d = normDir(pth);
  if (!d || d === "*") return null;
  const pkgs = (DATA && DATA.packages) || [];
  const hit = pkgs.filter(x => {
    const pd = normDir(x.dir);
    return !!pd && (d === pd || d.indexOf(pd + "\\") === 0);
  }).sort((a, b) => normDir(b.dir).length - normDir(a.dir).length)[0];
  if (hit) return {id: hit.id, dir: hit.dir, live: true};

  const m = /[\\\/](user_data|system)[\\\/]pkgs[\\\/]([^\\\/]+)/.exec(d);
  if (m) return {id: m[2], dir: "", live: false};
  return null;
}

async function aiAllowAdd(pth, why){
  const p = String(pth || AIR.newPath || "").trim();
  AIR.newPathErr = "";
  if (!p){ AIR.newPathErr = "先填一个目录（或者把文件夹拖到这一页）"; AIR.rev++; return; }
  if (!addPathOk(p)){
    AIR.newPathErr = "要填完整的绝对路径（像 D:\\项目\\我的包 那样）——「" + p + "」不是一个路径";
    AIR.rev++;
    return;
  }
  try{
    const got = await window.pywebview.api.ai_allow(p, true, true, String(why || "你手动加的"), "add", true, aiWhereDir());
    if (got && got.ok){
      toast(got.msg || "加好了");
      AIR.newPath = "";
    } else {
      AIR.newPathErr = (got && got.msg) || "加不了";
    }
    AIR.rev++;
    await aiRefreshInfo(true);
  }catch(e){
    AIR.newPathErr = "加不了：" + (e && e.message ? e.message : e);
    AIR.rev++;
  }
}

async function aiAllowSet(it, field, on){
  try{
    const args = {read: null, write: null};
    args[field] = !!on;
    const got = await window.pywebview.api.ai_allow(it.path, args.read, args.write, "", "set", false, aiWhereDir());
    toast((got && got.msg) || "好了", !(got && got.ok));
    await aiRefreshInfo(true);
  }catch(e){ toast("改不了：" + (e && e.message ? e.message : e), true); }
}
async function aiAllowRm(it){
  try{
    const got = await window.pywebview.api.ai_allow(it.path, null, null, "", "rm", false, aiWhereDir());
    toast((got && got.msg) || "删了", !(got && got.ok));
    await aiRefreshInfo(true);
  }catch(e){ toast("删不掉：" + (e && e.message ? e.message : e), true); }
}
async function aiAllowPick(){
  try{
    const got = await window.pywebview.api.ai_allow_pick(aiWhereDir());
    if (got && got.cancel) return;
    toast((got && got.msg) || "好了", !(got && got.ok));
    await aiRefreshInfo(true);
  }catch(e){ toast("选不了目录：" + (e && e.message ? e.message : e), true); }
}

async function aiAnswer(choice, text, qid){
  const q = AIR.ask || {};
  const id = String(qid || q.qid || "");
  if (!id || AIR.askBusy || !q.qid || id !== String(q.qid)) return;
  AIR.askBusy = true;
  try{
    const got = await window.pywebview.api.ai_answer(id, String(text || ""), String(choice || ""));
    if (!got || !got.ok) {
      toast((got && got.msg) || "没答上", true);
    } else {
      if (!AIR.answeredQids.includes(id)) AIR.answeredQids.push(id);
      AIR.ask = null;
      AIR.askText = "";
      toast("答了 —— 它继续跑了");
      await aiPollOnce();
    }
  }catch(e){ toast("没答上：" + (e && e.message ? e.message : e), true); }
  finally { AIR.askBusy = false; AIR.rev++; }
  await aiRefreshInfo(true);
}

async function aiOpenMessages(id){
  const rid = String(id || AIR.pickId || AIR.lastId || "");
  if (!rid){ toast("先选一条会话（左边那个下拉）", true); return; }
  AIR.msgBusy = true; AIR.msgOpen = true; AIR.msgWho = rid; AIR.msgData = null;
  document.body.style.overflow = "hidden";
  AIR.rev++;
  try{
    const got = await window.pywebview.api.ai_session_messages(rid);
    AIR.msgData = got || {ok: false, messages: [], msg: "读不到"};
  }catch(e){ AIR.msgData = {ok: false, messages: [], msg: String(e && e.message ? e.message : e)}; }
  AIR.msgBusy = false;
  AIR.rev++;
}

async function aiSaveBudget(){
  try{
    const tokens = Math.round(Number(AIR.maxMillions || 0) * 1000000);
    const got = await window.pywebview.api.ai_set_budget(tokens);
    if (!got || !got.ok){ toast((got && got.msg) || "预算没存上", true); await aiRefreshInfo(true); return; }
    AIR.maxTokens = got.max_tokens; AIR.warnTokens = got.warn || Math.round((got.max_tokens || 0) * 0.8);
    AIR.maxMillions = Math.round((AIR.maxTokens / 1000000) * 1000) / 1000;
    toast("token 上限 = " + humanTokens(got.max_tokens) + "（烧到 " + humanTokens(AIR.warnTokens) + " 时劝它收尾）");
  }catch(e){ toast("存预算失败：" + (e && e.message ? e.message : e), true); }
}

function _chainIds(all, head){
  const out = [head.id];
  let cur = head, guard = 0;
  while (guard++ < 500){
    const next = all.filter(r => r.continued_from === cur.id)[0];
    if (!next) break;
    out.push(next.id);
    cur = next;
  }
  return out;
}
function aiChains(runs){
  const all = runs || [];
  const out = [];

  all.filter(r => !r.continued_from).forEach(head => {
    let cur = head, turns = 1, guard = 0;
    while (guard++ < 500){
      const next = all.filter(r => r.continued_from === cur.id)[0];
      if (!next) break;
      cur = next; turns++;
    }

    out.push({head: head, tail: cur, turns: turns, ids: _chainIds(all, head)});
  });

  return out.sort((a, b) => String(b.tail.id).localeCompare(String(a.tail.id)));
}

async function aiLoadRuns(){
  try{
    const got = await window.pywebview.api.ai_runs(30, aiWhereDir());
    if (!got || !got.ok) return;
    AIR.runs = got.runs || [];
    AIR.scope = got.scope || null;

    if (AIR.running && AIR.liveRunId
        && (AIR.runs || []).some(r => r && String(r.id) === String(AIR.liveRunId))){
      AIR.pickId = AIR.liveRunId;
    }
    if (!AIR.running) aiAdoptLast();
  }catch(e){  }
}

function aiLastRunFor(dir){
  const d = normDir(dir);
  const mine = (AIR.runs || []).filter(r => normDir(r.workdir) === d);
  return mine[0] || null;                 
}
function normDir(p){
  return String(p || "").replace(/\//g, "\\").replace(/\\+$/, "").toLowerCase();
}

async function aiOpenThread(id, quiet){
  try{
    const got = await window.pywebview.api.ai_thread(id);
    if (!got || !got.ok || !(got.turns || []).length){
      if (!quiet) toast("读不到这条会话", true);
      return false;
    }

    if (AIR.pendingDone && String(AIR.pendingDone.run_id || "") === String(got.tail || id))
      AIR.pendingDone = null;
    AIR.turns = got.turns.map((t, i) => ({
      key: "h" + (AIR.turnSeq = (AIR.turnSeq || 0) + 1),

      id: t.id || "",
      task: t.task || "", at: (t.at || "").slice(5, 16),

      attachments: t.attachments || [],
      steps: t.steps || [], result: t.result || null,
      folded: !!t.result, autoFolded: !!t.result,
      note: (t.result && t.result.continue_note) || "",
    }));
    AIR.cur = -1;
    AIR.muted = 0;
    AIR.stick = true;                 
    const tail = got.tail || id;
    AIR.lastId = tail; AIR.lastAdopted = tail;
    AIR.pickId = tail;
    if (got.cont){ AIR.contId = tail; AIR.contTask = (AIR.turns[AIR.turns.length - 1] || {}).task || ""; }
    else { AIR.contId = ""; AIR.contTask = ""; }

    if (AIR.running){
      aiAttachLiveTurn();             
    }else{
      const last = AIR.turns[AIR.turns.length - 1] || null;
      AIR.steps = (last && last.steps) || [];
      AIR.result = (last && last.result) || null;
    }
    AIR.rev++;
    return true;
  }catch(e){
    if (!quiet) toast("读不到这条会话：" + (e && e.message ? e.message : e), true);
    return false;
  }
}

async function aiAdoptLast(){
  const mine = aiLastRunFor(aiWhereDir());
  const last = mine || (AIR.runs || [])[0] || null;
  AIR.lastId = (last && last.id) || "";
  if (!last || AIR.contId || AIR.pickId) return;
  AIR.contId = last.id;
  AIR.contTask = last.task || "";
  AIR.pickId = last.id;

  if (last.cont && mine){
    await aiOpenThread(last.id, true);
  }
}

function aiAttachLiveTurn(){
  if (!AIR.running) return null;
  let t = (AIR.turns || []).filter(x => x && x.key === AIR.liveKey)[0];
  if (!t){
    if (!AIR.liveKey) AIR.liveKey = "live" + (AIR.turnSeq = (AIR.turnSeq || 0) + 1);
    t = {key: AIR.liveKey, task: AIR.liveTask || AIR.task || "",
         at: "运行中 · " + new Date().toTimeString().slice(0, 8),
         steps: AIR.steps || [], result: AIR.result || null,
         folded: false, autoFolded: false, note: ""};
    AIR.turns = (AIR.turns || []).concat([t]);
  }
  AIR.cur = (AIR.turns || []).indexOf(t);
  return t;
}

function aiShowDone(done){
  if (!done || !done.result) return false;
  const here = (aiPackage() || {}).id || "";
  if (done.pkg && here && done.pkg !== here) return false;   
  if (AIR.viewing) return false;                              
  let t = null;
  if (done.run_id)
    t = (AIR.turns || []).filter(x => x && String(x.id || "") === String(done.run_id))[0] || null;
  if (!t && AIR.liveKey)
    t = (AIR.turns || []).filter(x => x && x.key === AIR.liveKey)[0] || null;
  if (!t && AIR.cur >= 0)
    t = (AIR.turns || [])[AIR.cur] || null;
  if (!t){
    t = {key: "done" + (AIR.turnSeq = (AIR.turnSeq || 0) + 1),
         id: done.run_id || "",
         task: done.task || AIR.liveTask || AIR.sentTask || "",
         at: "跑完了 · " + new Date().toTimeString().slice(0, 8),
         steps: done.steps || [], result: done.result,
         folded: true, autoFolded: true,
         note: (done.result && done.result.continue_note) || ""};
    AIR.turns = (AIR.turns || []).concat([t]);
  }
  t.result = done.result;
  t.id = t.id || done.run_id || "";
  if (done.steps && done.steps.length) t.steps = done.steps;
  t.note = (done.result && done.result.continue_note) || t.note || "";
  if (!AIR.running){ t.folded = true; t.autoFolded = true; }
  AIR.cur = (AIR.turns || []).indexOf(t);
  AIR.steps = t.steps || [];
  AIR.result = t.result;

  if (done.run_id){
    AIR.lastAdopted = done.run_id;
    AIR.lastId = done.run_id;
    AIR.contId = done.run_id;
    AIR.pickId = done.run_id;
    if (t.task) AIR.contTask = t.task;
  }
  AIR.pendingDone = null;
  AIR.rev++;
  return true;
}

async function aiOpenRun(id, quiet){
  try{
    const got = await window.pywebview.api.ai_run(id);
    if (!got || !got.ok || !got.run){ if (!quiet) toast("读不到这条记录", true); return; }
    const r = got.run;
    if (AIR.pendingDone && String(AIR.pendingDone.run_id || "") === String(id))
      AIR.pendingDone = null;
    AIR.viewing = id;
    AIR.pickId = id;              
    AIR.steps = r.steps || [];

    AIR.sentTask = r.task || "";
    AIR.muted = 0;
    AIR.result = {ok: !!r.ok, kind: r.kind || "work", reason: r.reason || "", summary: r.summary || "",
                  caveats: r.caveats || "", files: r.files || [], usage: r.usage || {},
                  snapshot: r.snapshot || null, run_id: r.id};

    AIR.turns = [{key: "v" + (AIR.turnSeq = (AIR.turnSeq || 0) + 1), id: r.id || "", task: r.task || "",
                  at: (r.started_text || "").slice(5, 16) || "历史记录",
                  steps: AIR.steps, result: AIR.result,
                  folded: !!AIR.result, autoFolded: !!AIR.result}];
    AIR.cur = 0;
    AIR.rev++;
  }catch(e){ if (!quiet) toast("读不到这条记录：" + (e && e.message ? e.message : e), true); }
}

async function aiForgetRun(id){
  try{
    const got = await window.pywebview.api.ai_run_forget(id || "", !id, aiWhereDir());
    if (got && got.ok){ toast(id ? "删掉那条记录了" : "历史清空了"); AIR.viewing = ""; await aiLoadRuns(); }
    else toast((got && got.msg) || "删不掉", true);
  }catch(e){ toast("删不掉：" + (e && e.message ? e.message : e), true); }
}

async function aiLoadSkills(){
  try{
    const got = await window.pywebview.api.ai_skills();
    if (!got || !got.ok) return;
    AIR.selfSkills = got;

    if (skillPend(got).length) { AIR.selfOpen = true; AIR.selfTab = "pending"; }
    AIR.rev++;
  }catch(e){  }
}

function skillAll(got){
  got = got || {};
  const out = [], seen = {};
  (got.skills || []).concat(got.from_pkgs || []).concat(got.broken || []).forEach(w => {
    if (!w || !w.id || seen[w.id]) return;
    seen[w.id] = 1;
    out.push(w);
  });
  return out;
}
function skillPend(got){ return skillAll(got).filter(w => !(w.problems || []).length && !w.allowed); }
function skillOk(got){ return skillAll(got).filter(w => !(w.problems || []).length && w.allowed); }

async function aiSkillLook(w){
  if (!w) return;
  if (AIR.selfWho === w.id){ AIR.selfWho = ""; AIR.rev++; return; }   
  try{
    const got = await window.pywebview.api.ai_skill_read(w.id);
    if (!got || !got.ok){ toast((got && got.msg) || "读不出来", true); return; }
    AIR.selfWho = w.id;
    AIR.selfText = Object.keys(got.text || {}).map(
      rel => "=== " + rel + " ===\n" + got.text[rel]).join("\n\n");
    AIR.rev++;
  }catch(e){ toast("读不出来：" + (e && e.message ? e.message : e), true); }
}
async function aiSkillAllow(w, yes){
  if (!w) return;
  try{
    const got = await window.pywebview.api.ai_skill_allow(w.id, !!yes);
    toast((got && got.msg) || ((got && got.ok) ? "好了" : "没成"), !(got && got.ok));
    await aiLoadSkills();
  }catch(e){ toast("没成：" + (e && e.message ? e.message : e), true); }
}
function aiSkillRm(w){
  if (!w) return;
  askConfirm("删掉这只技能？",
    "删掉 <code>" + esc(w.id) + "</code> 的整个目录（<code>" + esc(w.dir) +
    "</code>，" + (w.files_n || 0) + " 个文件）？它写的东西一起没。",
    async () => {
      try{
        const got = await window.pywebview.api.ai_skill_rm(w.id, true);
        toast((got && got.msg) || "删了", !(got && got.ok));
        await aiLoadSkills();
      }catch(e){ toast("删不掉：" + (e && e.message ? e.message : e), true); }
    });
}

async function aiOpenSkills(){
  const ps = (typeof DATA !== "undefined" && DATA && DATA.packages) || [];
  const p = ps.filter(x => x.id === "skill" ||
                           (x.aliases || []).indexOf("skill") >= 0)[0];
  if (!p){ toast("找不到技能管理器 —— 先在插件列表里跑一次 skill", true); return; }

  try { if (typeof select === "function") select(p.id, true); } catch(e){}
  if (typeof embedOpen === "function" && typeof embedSupported === "function" && embedSupported(p)){
    await embedOpen(p, {});
    return;
  }
  toast("这个包没法内嵌 —— 去插件列表里运行它", true);
}

async function aiTurnPlan(id){
  if (!id){ toast("这条是更早的记录，改不了", true); return null; }
  try{
    const p = await window.pywebview.api.ai_session_plan(id);
    if (!p || !p.ok){ toast("算不出这一轮要删什么：" + ((p && p.msg) || "?"), true); return null; }
    return p;
  }catch(e){ toast("算不出这一轮要删什么：" + (e && e.message ? e.message : e), true); return null; }
}

function aiPlanHtml(p){
  const out = [];
  const head = (p.delete_ids || []).length;
  out.push("<b>会删掉 " + head + " 条记录</b>（这一轮" +
           (head > 1 ? "，以及它**之后**那 " + (head - 1) + " 轮" : "") + "）：<br>" +
           (p.delete_tasks || []).map((t, i) =>
             "　#" + (p.index + 1 + i) + " " + esc(String(t || "（没写任务）").slice(0, 40))).join("<br>"));
  if (p.target){
    out.push("<b>先回退到快照</b> <code>" + esc(p.target.id) + "</code>" +
             (p.fallback ? "（**不是这一轮自己的**，是更早那条）" : "") +
             " —— 那一刻的包目录。<br>也就是：这一轮改的东西**会被撤掉**" +
             (p.fallback ? "，连同它那之后的改动" : "") + "。");
  }else if (!p.chat_only){
    out.push("<b>没有可回退的快照</b> —— 删掉之后代码回不到那一刻，**只是记录没了**。");
  }
  (p.warnings || []).forEach(w => out.push("⚠ " + esc(String(w))));
  out.push('<span class="dim">回退要用的那条快照**保留**；你自己存的快照一条都不动；覆盖前会留 ' +
           '<code>.bak</code>。</span>');
  return out.join("<br>");
}

async function aiDoTruncate(id){
  try{
    const r = await window.pywebview.api.ai_session_truncate(id, true);
    if (!r || !r.ok){ toast("没删成：" + ((r && r.msg) || "?"), true); return null; }
    return r;
  }catch(e){ toast("没删成：" + (e && e.message ? e.message : e), true); return null; }
}

async function aiAfterTruncate(p, task, fill, done){
  AIR.viewing = "";
  await aiLoadRuns();
  let tail = "";
  if (p.prev_id){
    await aiOpenThread(p.prev_id, true);
    if (AIR.contId){ AIR.contTask = (AIR.turns[AIR.turns.length - 1] || {}).task || "";
                     tail = "，下一条接着上一轮聊"; }
    else { tail = "（前面那条是更早的记录、没存对话 —— 接不上，下一条按新会话跑）"; }
  }else{
    AIR.turns = []; AIR.cur = -1; AIR.steps = []; AIR.result = null; AIR.answeredQid = "";
    AIR.sentTask = ""; AIR.lastId = ""; AIR.pickId = "";
    AIR.contId = ""; AIR.contTask = ""; AIR.muted = 0;
    tail = "，这条会话没了（下一条按新会话跑）";
  }
  if (fill){ AIR.task = String(task || ""); }
  AIR.rev++;
  toast((done || "删好了") + tail);
}

async function aiPollOnce(){
  try {
    const got = await window.pywebview.api.ai_poll();
    if (!got || !got.ok) return;

    const _pollPkg = aiLivePkg();
    const _pollRunId = String(got.run_id || AIR.liveRunId || "");
    const _pollTask = String(got.task || AIR.liveTask || AIR.task || "");

    const _wasRunning = AIR.running;
    AIR.running = !!got.running;

    if (AIR.running) AIR.doneWait = 0;
    else if (_wasRunning && !got.result) AIR.doneWait = 12;
    else if (got.result || got.idle) AIR.doneWait = 0;

    AIR.liveRunId = AIR.running ? String(got.run_id || "") : "";

    if (AIR.running && got.task && !AIR.liveTask) AIR.liveTask = String(got.task);
    if (AIR.running && AIR.liveRunId && AIR.liveRunId !== AIR.liveListFor){
      AIR.liveListFor = AIR.liveRunId;
      aiLoadRuns();
    }
    if (AIR.running && AIR.liveRunId
        && (AIR.runs || []).some(r => r && String(r.id) === String(AIR.liveRunId))){
      AIR.pickId = AIR.liveRunId;
    }
    if (_wasRunning && !AIR.running){
      sndNotify("finish");
      AIR.livePkg = "";          
      aiLoadSkills();
      aiRefreshInfo(true);      

      try{
        if (typeof refreshPkgs === "function")
          await refreshPkgs((cur && cur.id) || undefined, true);
      }catch(e){  }
    }

    const _skRev = String(got.skills_rev || "");
    if (_skRev && _skRev !== AIR.skillsRev){
      AIR.skillsRev = _skRev;
      aiLoadSkills();
    }
    AIR.steps = got.steps || [];

    AIR.partial = got.partial || null;

    let cur = null;
    if (AIR.liveKey){
      cur = (AIR.turns || []).filter(t => t && t.key === AIR.liveKey)[0] || null;
    }

    if (!cur && aiLiveHere()) cur = aiAttachLiveTurn();
    if (!cur && !AIR.viewing) cur = (AIR.turns || [])[AIR.cur] || null;
    if (cur) cur.steps = AIR.steps;
    AIR.say = got.say || [];
    AIR.seconds = got.seconds || 0;
    AIR.phase = got.phase || "";

    AIR.liveUsage = got.usage || null;
    AIR.stopping = !!got.stopping;

    const permNow = got.perm || null;
    const permKey = permNow ? String(permNow.path || "") : "";
    const permKeyOld = AIR.perm ? String(AIR.perm.path || "") : "";
    AIR.perm = permNow;
    if (permKey !== permKeyOld) aiRefreshInfo(true);

    if (permKey && permKey !== permKeyOld) sndNotify("warn");
    if ((got.killed || []).length) AIR.killed = got.killed;
    if (got.mode && got.mode !== AIR.mode) AIR.mode = got.mode;

    const ask = got.ask || null;
    const sameAsk = ask && AIR.ask && ask.qid === AIR.ask.qid;
    AIR.ask = (ask && AIR.answeredQids.includes(ask.qid)) ? null : ask;
    if (!sameAsk) AIR.askText = "";
    if (!ask && !got.running) AIR.askText = "";

    if (AIR.ask && AIR.ask.qid && AIR.ask.qid !== AIR.askNoted){
      AIR.askNoted = AIR.ask.qid;
      sndNotify("warn");
    }

    if (got.running && got.max_tokens) AIR.maxTokens = got.max_tokens;
    if (got.compact_at) AIR.compactAt = got.compact_at;      
    if (got.context) AIR.context = got.context;
    AIR.promptTokens = got.prompt_tokens || 0;
    if (!got.idle) AIR.result = got.result || null;

    if (got.result){
      AIR.pendingDone = {pkg: _pollPkg, run_id: _pollRunId, task: _pollTask,
                         steps: AIR.steps || [], result: got.result};
    }
    if (cur){
      if (got.result){
        cur.result = got.result;

        cur.note = got.result.continue_note || "";

        if (!got.running && !cur.autoFolded){
          cur.folded = true;
          cur.autoFolded = true;
        }
      }
    }

    if (got.result) aiShowDone(AIR.pendingDone);

    const snap = got.snapshot;
    if (snap && snap.id && snap.id !== AIR.snapNoted){
      AIR.snapNoted = snap.id;
      if (typeof bkRefresh === "function") bkRefresh();
    }
    const res = got.result;
    if (res && !got.running){
      const stamp = String(res.run_id || (res.files || []).join("|") || "");
      if (stamp && stamp !== AIR.diskNoted){
        AIR.diskNoted = stamp;
        if ((res.files || []).length && typeof diskChanged === "function")
          diskChanged(res.files);
      }

      const _resHere = (aiPackage() || {}).id || "";
      const _resMine = !_pollPkg || !_resHere || _pollPkg === _resHere;
      if (_resMine && res.run_id && res.run_id !== AIR.lastAdopted){
        AIR.lastAdopted = res.run_id;
        AIR.lastId = res.run_id;
        AIR.contId = res.run_id;
        AIR.pickId = res.run_id;          
        AIR.contTask = (AIR.task || "").trim();
        aiLoadRuns();
      }
    }
    AIR.rev++;
  } catch (e) {  }
}

async function aiPollPartial(){
  if (!AIR.running || AIR.ptBusy) return;
  const api = window.pywebview && window.pywebview.api;
  if (!api) return;

  const call = api.ai_poll_light ? api.ai_poll_light.bind(api)
             : (api.ai_poll ? api.ai_poll.bind(api) : null);
  if (!call) return;
  AIR.ptBusy = true;
  try{
    const got = await call();
    const p = (got && got.partial) ? got.partial : null;

    const key = (q) => q ? (String(q.chars || 0) + "/" + String(q.tchars || 0) + "/"
                            + String(q.text || "").slice(-60)
                            + String(q.think || "").slice(-60)) : "";
    if (key(p) !== key(AIR.partial)){
      AIR.partial = p;
      AIR.rev++;                     
    }
  }catch(e){  }
  finally { AIR.ptBusy = false; }
}

async function aiStart(opt){
  if (AIR.busy) return;
  const atts = (AIR.attachments || []).slice();
  const typed = (AIR.task || "").trim();
  const task = typed || (atts.length ? "请分析我发来的附件。" : "");
  if (!task) { toast("先写一句你要它干什么，或者加个附件。", true); return; }

  const dir = (opt && opt.dir) ? String(opt.dir)
                               : aiWhereDir();
  if (!dir) { toast("先在左边选一个包（或者选「新建包」）。", true); return; }
  AIR.busy = true;
  AIR.result = null; AIR.steps = []; AIR.say = []; AIR.answeredQid = "";
  AIR.partial = null;                  
  AIR.pendingDone = null;              
  AIR.doneWait = 0;                    
  AIR.killed = []; AIR.liveUsage = null; AIR.ask = null; AIR.askText = "";   
  AIR.stick = true;                                                          
  AIR.viewing = "";              

  AIR.sentTask = task;
  AIR.muted = 0;

  const cont = AIR.contId || (AIR.viewing ? "" : (AIR.lastId || ""));

  const liveKey = "t" + (AIR.turnSeq = (AIR.turnSeq || 0) + 1);
  AIR.turns.push({key: liveKey, task: task,

                  attachments: atts.map(a => ({
                    name: a.name, kind: a.kind, size: a.size,
                    source: a.source || "",
                    text: a.kind === "text" ? String(a.text || "").slice(0, 200000) : "",
                    truncated: a.kind === "text" && String(a.text || "").length > 200000,
                  })),
                  at: (cont ? "接着聊" : "新会话") + " · " +
                      new Date().toTimeString().slice(0, 8),
                  steps: [], result: null, folded: false, autoFolded: false, note: ""});
  AIR.cur = AIR.turns.length - 1;
  AIR.liveKey = liveKey;
  AIR.liveTask = task;

  AIR.livePkg = aiPkgIdOfDir(dir) || ((aiPackage() || {}).id || "");
  AIR.liveListFor = "";
  AIR.diskNoted = "";            
  AIR.snapNoted = "";            

  try {
    const got = await window.pywebview.api.ai_start(task, dir, AIR.maxTokens, cont, AIR.model || "", atts);
    if (!got || !got.ok) { toast((got && got.msg) || "起不来。", true); AIR.busy = false; return; }
    AIR.running = true;

    AIR.liveRunId = String(got.run_id || "");
    if (AIR.liveRunId) AIR.liveListFor = "";       
    AIR.task = "";
    AIR.attachments = [];
    toast((cont ? "接着上次那条聊" : "开了一条新会话") +
          "（模型 " + (got.model || "?") + "）—— 步骤会实时出现在下面。");
  } catch (e) {
    toast("起不来：" + (e && e.message ? e.message : e), true);
  }
  AIR.busy = false;
  AIR.rev++;
}

async function aiStop(){
  try {
    AIR.stopping = true;
    AIR.rev++;
    const got = await window.pywebview.api.ai_stop();
    toast((got && got.msg) || "已停止。", !(got && got.ok));

    if (got && got.done) {
      AIR.running = false; AIR.stopping = false;
      AIR.doneWait = 12;                 
    }
  } catch (e) {  }
  AIR.rev++;
}

const MossAi = {
  name: "moss-ai",
  data(){ return { A: AIR, focused: false, shake: false, stopHover: false }; },
  computed: {
    pkg(){ this.A.rev; return aiPackage(); },

    selfList(){
      this.A.rev;

      const t = this.A.selfSkills || {};
      return [].concat(skillPend(t), skillOk(t),
                       skillAll(t).filter(w => (w.problems || []).length));
    },
    selfN(){ this.A.rev; return (((this.A.selfSkills || {}).skills) || []).length; },
    selfPend(){ this.A.rev; return skillPend(this.A.selfSkills).length; },
    selfBroken(){ this.A.rev;
      return skillAll(this.A.selfSkills).filter(w => (w.problems || []).length).map(w => w.id); },
    selfPendList(){ this.A.rev; return skillPend(this.A.selfSkills || {}); },
    selfOkList(){ this.A.rev; return skillOk(this.A.selfSkills || {}); },
    selfBrokenList(){ this.A.rev;
      return skillAll(this.A.selfSkills).filter(w => (w.problems || []).length); },
    selfBrokenNames(){ this.A.rev; return this.selfBrokenList.map(w => w.id).join("、"); },
    selfTotal(){ this.A.rev;
      return this.selfPendList.length + this.selfOkList.length + this.selfBrokenList.length; },

    selfNames(){
      this.A.rev;
      const o = {};
      skillOk(this.A.selfSkills).forEach(w => { o[w.name] = 1; });
      return o;
    },
    info(){ this.A.rev; return this.A.info; },
    target(){ this.A.rev; return aiWhereDir(); },
    missing(){ this.A.rev; return (this.A.info && this.A.info.missing_prompts) || []; },
    model(){ this.A.rev; return (this.A.info && this.A.info.model) || "（还没配 AI）"; },
    ready(){ this.A.rev; return !!(this.A.info && this.A.info.ok && this.A.info.model && this.A.info.has_key); },

    canWrite(){
      this.A.rev;
      const t = aiWhereDir();
      if (!t) return false;
      const norm = s => String(s).replace(/[\\/]+$/, "").toLowerCase();
      const inside = (p, r) => !!r && (p === r || p.indexOf(r + "\\") === 0 ||
                                       p.indexOf(r + "/") === 0);
      const rows = this.A.allow || [];
      if (rows.some(x => x.write && (x.path === "*" || inside(norm(t), norm(x.path))))) return true;
      const own = rows.filter(x => norm(x.path) === norm(t)).pop();
      if (own) return !!own.write;                      
      return inside(norm(t), norm((this.A.info && this.A.info.write_root) || ""));
    },

    lastRes(){
      this.A.rev;
      const ts = this.A.turns || [];
      for (let i = ts.length - 1; i >= 0; i--) if (ts[i] && ts[i].result) return ts[i].result;
      return null;
    },
    usage(){ this.A.rev; return (this.lastRes && this.lastRes.usage) || null; },

    curStep(){ this.A.rev; return (this.A.steps || []).reduce((m, s) => Math.max(m, s.n || 0), 0); },
    maxTokens(){ this.A.rev; return this.A.maxTokens || 200000; },

    curTokens(){
      this.A.rev;
      const ss = this.A.steps || [];
      return ss.length ? (ss[ss.length - 1].tokens || 0) : 0;
    },

    ctxPct(){
      this.A.rev;
      if (!this.A.compactAt) return 0;
      return Math.min(100, Math.round((this.A.promptTokens || 0) * 100 / this.A.compactAt));
    },

    curFolded(){
      this.A.rev;
      const ss = this.A.steps || [];
      return ss.length ? (ss[ss.length - 1].folded || 0) : 0;
    },
    files(){ this.A.rev; return (this.lastRes && this.lastRes.files) || []; },
    resultOk(){ this.A.rev; return !!(this.lastRes && this.lastRes.ok); },

    modelGroups(){
      this.A.rev;
      const inf = this.A.info || {};
      const cur = String(inf.profile || "");
      let ps = (inf.providers || []).map(p => ({
        name: String(p.name || ""),
        models: (p.models || []).map(x => String(x)).filter(Boolean),
        has_key: !!p.has_key,
      })).filter(p => p.name && p.models.length);
      if (!ps.length){                        
        const ms = (inf.models || []).slice();
        if (!ms.length && this.A.model) ms.push(this.A.model);
        if (ms.length) ps = [{name: cur || "当前服务商", models: ms, has_key: true}];
      }
      ps.sort((a, b) => (a.name === cur ? -1 : b.name === cur ? 1 : 0));

      const seen = {};
      const out = [];
      ps.forEach(g => {
        const ms = g.models.filter(m => { if (seen[m]) return false; seen[m] = 1; return true; });
        if (ms.length)
          out.push({name: g.name, has_key: g.has_key, active: g.name === cur, models: ms});
      });
      return out;
    },
    models(){
      this.A.rev;
      return this.modelGroups.reduce((a, g) => a.concat(g.models), []);
    },

    currentProvider(){
      this.A.rev;
      return this.providerOf(this.A.model) || String((this.A.info && this.A.info.profile) || "");
    },

    modelGroupsShown(){
      this.A.rev;
      const q = String(this.A.modelQ || "").trim().toLowerCase();
      const gs = this.modelGroups;
      if (!q) return gs;
      const hit = s => String(s || "").toLowerCase().indexOf(q) >= 0;
      return gs
        .map(g => (hit(g.name) ? g : Object.assign({}, g, {models: g.models.filter(hit)})))
        .filter(g => g.models.length);
    },
    lastRun(){
      this.A.rev;
      return aiLastRunFor(aiWhereDir());
    },

    sessionTitle(){
      this.A.rev;
      if (this.A.viewing){
        const r = (this.A.runs || []).filter(x => x.id === this.A.viewing)[0];
        return (r && r.task) || this.A.contTask || "历史会话";
      }
      const ts = this.A.turns || [];
      if (ts.length){
        const head = (ts[0].task || "").trim();
        return ts.length > 1 ? (head + "（" + ts.length + " 轮）") : head;
      }
      return (this.A.task || "").trim() || "新会话 —— 在下面写你要它干什么";
    },

    sessChains(){
      this.A.rev;
      return aiChains(this.A.runs);
    },
    sessCurrent(){
      this.A.rev;
      const id = this.A.pickId || "";
      if (!id) return null;
      return this.sessChains.filter(c => c.head.id === id || c.tail.id === id)[0] || null;
    },
    sessOthers(){
      this.A.rev;
      const id = this.A.pickId || "";
      return this.sessChains.filter(c => c.head.id !== id && c.tail.id !== id);
    },

    logCards(){
      this.A.rev;
      const out = [];
      const t = (this.A.turns || [])[this.A.turns.length - 1];
      if (!t) return out;
      out.push({key: "user", kind: "user", icon: "message-circle",
                color: "var(--aib-primary)", action: "用户指令", tool: "",
                meta: t.at || "", path: t.task || ""});
      (this.visSteps(t.steps)).forEach((s, i) => {
        out.push({key: "s" + i, kind: "step", icon: this.stepIcon(s.tool),
                  color: this.kindColor(s.tool), action: this.stepTitle(s), tool: s.tool,
                  meta: this.stepMeta(s), path: this.stepPath(s)});
      });
      return out;
    },

    tokenUsedMillions(){
      this.A.rev;
      const u = this.A.running ? (this.A.liveUsage || this.usage) : (this.usage || this.A.liveUsage);
      const n = Number((u && u.total_tokens) || 0) / 1000000;
      return (u && u.estimated ? "≈" : "") + (n < 10 ? n.toFixed(2) : n.toFixed(1));
    },
    tokenLimitMillions(){
      this.A.rev;
      const n = Number(this.A.maxTokens || 0) / 1000000;
      return n < 10 ? n.toFixed(2) : n.toFixed(1);
    },
    tokenPct(){
      this.A.rev;
      const u = this.A.running ? (this.A.liveUsage || this.usage) : (this.usage || this.A.liveUsage);
      const limit = Number(this.A.maxTokens || 0);
      return limit > 0 ? Math.max(0, Math.min(100, Math.round(Number((u && u.total_tokens) || 0) * 100 / limit))) : 0;
    },
    tokTip(){
      this.A.rev;
      const u = (this.A.running ? (this.A.liveUsage || this.usage) : (this.usage || this.A.liveUsage));
      if (!u) return "这一轮还没烧 token（或者还没跑）";
      return (u.estimated ? "≈ " : "") + "输入 " + (u.prompt_tokens || 0) + " · 输出 " +
             (u.completion_tokens || 0) + " · 合计 " + (u.total_tokens || 0) + " token" +
             (u.estimated ? "（网关没回 usage，这是按字数估的）" : "");
    },

    balanceText(){
      this.A.rev;
      if (this.A.balanceLoading) return "…";
      const b = this.A.balance;
      if (!b) return "?";
      const t = String(b.text || "?").trim();
      return t || "?";
    },
    balanceTitle(){
      this.A.rev;
      const b = this.A.balance;
      if (this.A.balanceLoading) return "正在查询当前服务商余额…";
      if (!b) return "点击查询当前服务商余额";
      const who = b.provider ? ("服务商「" + b.provider + "」") : "当前服务商";

      return who + "\n" + (b.full || b.msg || "点击刷新余额") +
             "\n点击刷新（不点不会自动轮询）";
    },
    palettePresets(){ return AI_PALETTE_PRESETS; },
    paletteCurrentName(){
      this.A.rev;
      const hit = AI_PALETTE_PRESETS.filter(x => x.color.toLowerCase() === String(this.A.paletteColor || "").toLowerCase())[0];
      return hit ? hit.name : (this.A.paletteColor || "无颜色");
    },

    permPendingLabel(){
      this.A.rev;
      const p = this.A.perm;
      if (!p) return "";
      const bits = String(p.path || "").split(/[\\/]/).filter(Boolean);
      const tail = bits.length ? bits[bits.length - 1] : String(p.path || "");
      return tail + (p.need === "read" ? "（读）" : "");
    },

    allowOn(){ this.A.rev; return (this.A.allow || []).filter(x => x.write).length; },
    minePaths(){
      this.A.rev;
      return this.allowSplit.mine.filter(x => x.path !== "*" && !x.current && (x.read || x.write));
    },
    permState(){
      this.A.rev;
      if (this.A.full) return "完全权限";
      const n = this.minePaths.length;
      return n ? (aiCnNum(n) + "个路径") : "仅当前包";
    },
    confirmAsk(){
      this.A.rev;
      const a = this.A.ask;
      return (a && a.kind === "confirm") ? a : null;
    },

    allowSplit(){
      this.A.rev;
      const mine = [], other = [];

      (this.A.allow || []).filter(x => !x.pending && x.path !== "*").forEach(x => {
        mine.push(Object.assign({}, x, {_p: permParts(x.path)}));
      });
      return {mine: mine, other: other};
    },

    allowRows(){ this.A.rev; return this.allowSplit.mine; },

    allowOther(){ this.A.rev; return this.allowSplit.other; },

    runLabel(){
      return r => {
        const mark = r.interrupted ? "⚠ 上次没跑完 · " : (r.ok ? "✅ " : "✗ ");
        return mark + String(r.task || "（没写任务）").slice(0, 60) +
               (r.interrupted ? "（记录还在，能接着聊）" : "");
      };
    },

    addPathBad(){
      this.A.rev;
      const s = String(this.A.newPath || "").trim();
      return !!s && !addPathOk(s);
    },
    canAddPath(){ this.A.rev; return addPathOk(this.A.newPath); },

    addPathHint(){ return "要填完整的绝对路径（像 D:\\项目\\我的包 那样）"; },

    permAsk(){ this.A.rev; return !!(this.A.perm || this.confirmAsk); },

    permOpen(){ this.A.rev; return !!this.A.permPinned || !!this.A.permHover; },
    permFolded(){ this.A.rev; return !this.permOpen; },

    attMeta(){
      this.A.rev;
      const a = this.A.att;
      if (!a) return "";
      const n = String(a.text || "").length || Number(a.size || 0);
      return "粘贴的文本 · " + String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",") + " 字"
             + (a.truncated ? " · 只留了前 20 万字" : "");
    },
  },
  watch: {
    "A.steps"(){ this.followLog(); },
    "A.result"(){ this.followLog(); },

    "A.turns"(){ this.followLog(); },

    "A.partial"(){ this.followLog(); },

    "A.perm"(v){ if (v && AIR.permPinned){ AIR.permPinned = false; AIR.rev++; } },

    "A.ask"(v){
      if (v && (AIR.permPinned || AIR.permHover)){ AIR.permPinned = false; AIR.permHover = false; AIR.rev++; }
    },

    "A.task"(){ this.$nextTick(() => this.autoGrow()); },
  },
  methods: {
      stop: aiStop,
      async openDir(path){
        if (!path) return;
        const rel = "abs/" + path.replace(/\\/g, "/");
        const r = await window.pywebview.api.fs_open_default(rel);
        if (r && !r.ok) toast(r.msg, true);
      },

      async copyPath(it){
        const p = String((it && it.path) || "");
        if (!p || p === "*") return;
        try{ await navigator.clipboard.writeText(p); toast("路径已复制"); }
        catch(e){ toast("复制失败：" + (e && e.message ? e.message : e), true); }
      },
    saveBudget: aiSaveBudget,
    refresh(){ aiRefreshInfo(true); },          

    toggleAllow(){  },

    togglePerm(){
      if (this.permAsk) return;
      AIR.permPinned = !AIR.permPinned;
      AIR.rev++;
    },
    permHoverIn(){ if (!AIR.permHover){ AIR.permHover = true; AIR.rev++; } },
    permHoverOut(){ if (AIR.permHover){ AIR.permHover = false; AIR.rev++; } },
    allowAdd(){ aiAllowAdd(null, "你手动加的"); },
    allowSet(it, field, on){ aiAllowSet(it, field, on); },

    async reqAllow(){
      if (this.confirmAsk){ return this.answer("允许", ""); }
      const p = this.A.perm;
      if (!p) return;
      return this.grantPerm(p.need === "read" ? "read" : "write", true);
    },
    async reqDeny(){
      if (this.confirmAsk){ return this.answer("拒绝", ""); }
      if (this.A.perm){ return this.denyPerm(); }
      return undefined;
    },

    async grantPerm(field, on){
      const p = this.A.perm;
      if (!p || !on) return;                       
      try{
        const got = await window.pywebview.api.ai_allow(p.path, true, field === "write", "", "add", false,
                                                        String(p.workdir || aiWhereDir()));
        toast((got && got.msg) || "放行了", !(got && got.ok));
      }catch(e){ toast("没成：" + (e && e.message ? e.message : e), true); }
      await aiRefreshInfo(true);
    },

    async denyPerm(){
      const p = this.A.perm;
      if (!p) return;
      try{
        const got = await window.pywebview.api.ai_allow(p.path, null, null, "", "deny", false,
                                                        String(p.workdir || aiWhereDir()));
        toast((got && got.msg) || "拒绝了", !(got && got.ok));
      }catch(e){ toast("没成：" + (e && e.message ? e.message : e), true); }
      await aiRefreshInfo(true);
    },
    allowRm(it){ aiAllowRm(it); },
    allowPick(){ aiAllowPick(); },

    toggleOtherPerm(){
      AIR.otherOpen = !AIR.otherOpen;
      AIR.rev++;
    },

    async rmOtherAll(){
      const rows = (this.allowOther || []).slice();
      if (!rows.length) return;
      let ok = 0, bad = 0;
      for (const it of rows){
        try{
          const got = await window.pywebview.api.ai_allow(it.path, null, null, "", "rm", false, aiWhereDir());
          if (got && got.ok) ok += 1; else bad += 1;
        }catch(e){ bad += 1; }
      }
      await aiRefreshInfo(true);
      toast("清掉 " + ok + " 条别的包的权限" + (bad ? ("，" + bad + " 条没清掉") : ""), !!bad);
      AIR.rev++;
    },

    permLabel(it){
      if (!it) return "";
      const t = this.target;
      const norm = s => String(s || "").replace(/[\\/]+$/, "").toLowerCase();

      if (t && norm(it.path) === norm(t)) return this.pSym() + ((aiPackage() || {}).id || "") + "　当前这个包";
      const bits = String(it.path).split(/[\\/]/).filter(Boolean);
      return bits.length ? bits[bits.length - 1] : it.path;
    },
    permWhy(it){ return (it && it.why) || ""; },

    permDesc(it){
      if (!it) return "";
      if (it.pending) return "它想用这里" + (it.why ? ("：" + it.why) : "");
      const t = this.target;
      const norm = s => String(s || "").replace(/[\\/]+$/, "").toLowerCase();

      if (t && norm(it.path) === norm(t))
        return "当前工作包" + (it.factory ? " · 出厂件" : "");
      if (it.by === "ai") return "它请求的" + (it.why ? ("：" + it.why) : "");
      return it.why || "你加的";
    },

    toggleHist(){
      AIR.histOpen = !AIR.histOpen;
      if (AIR.histOpen){
        AIR.permPop = false; aiLoadRuns();
        this.$nextTick(() => this.fitPop("hist"));      
      }
      AIR.rev++;
    },

    fitPop(which){
      const panel = which === "hist" ? this.$refs.histPanel : this.$refs.permPanel;
      const host  = which === "hist" ? this.$refs.histBtn : this.$refs.permBtn;
      if (!panel || !host) return;
      const pane = document.querySelector("#pane-ai") || this.$el || document.body;
      const bounds = pane.getBoundingClientRect();
      const vw = document.documentElement.clientWidth || window.innerWidth || 0;
      if (!vw || !bounds.width) return;
      const hr0 = host.getBoundingClientRect();

      const key = vw + "|" + Math.round(bounds.left) + "|" + Math.round(bounds.right) +
                  "|" + Math.round(hr0.left) + "|" + Math.round(hr0.right);
      if (!this._fitKeys) this._fitKeys = {};

      if (this._fitKeys[which] === key && panel.style.left) return;
      this._fitKeys[which] = key;
      const pad = 10;
      panel.style.left = "";
      panel.style.right = "";
      panel.style.width = "";

      const leftBound = bounds.left + pad;
      const rightBound = bounds.right - pad;
      const avail = Math.max(220, rightBound - leftBound);
      let w = panel.offsetWidth || 0;
      if (w > avail){ w = avail; panel.style.width = w + "px"; }
      const wrap = (host.closest && host.closest(".popover-wrapper")) || host;
      const wr = wrap.getBoundingClientRect();
      let leftViewport = hr0.left;                       
      if (leftViewport + w > rightBound) leftViewport = rightBound - w;  
      if (leftViewport < leftBound) leftViewport = leftBound;            
      panel.style.right = "auto";
      panel.style.left = Math.round(leftViewport - wr.left) + "px";
    },

    togglePermPop(){
      AIR.permPop = !AIR.permPop;
      if (AIR.permPop){
        AIR.histOpen = false;
        this.$nextTick(() => this.fitPop("perm"));      
      }
      AIR.rev++;
    },
    pickChain(c){ AIR.histOpen = false; AIR.pickId = (c && c.tail && c.tail.id) || ""; this.pickSession(); },
    pickNewChat(){ AIR.histOpen = false; AIR.pickId = ""; this.pickSession(); },

      async delChain(c){
        const n = (c && c.turns) || 0;
        const ids = (c && c.ids) || [];
        if (!ids.length) return;

        let bad = 0;
        for (const id of ids){
          try{
            const got = await window.pywebview.api.ai_run_forget(id, false, aiWhereDir());
            if (!got || !got.ok) bad++;
          }catch(e){ bad++; }
        }
        toast(bad ? ("有 " + bad + " 条没删掉") : ("删掉了这条会话（" + n + " 轮）"), !!bad);

        if (ids.indexOf(AIR.pickId) >= 0 || ids.indexOf(AIR.lastId) >= 0){
          AIR.viewing = ""; AIR.pickId = ""; AIR.contId = ""; AIR.contTask = "";
          AIR.lastId = ""; AIR.lastAdopted = "";
          AIR.turns = []; AIR.steps = []; AIR.result = null; AIR.cur = -1;
        }
        await aiLoadRuns();
        AIR.rev++;
      },
    chainTitle(c){
      const t = (c && c.head && c.head.task) || "（没写任务）";

      return t.length > 96 ? (t.slice(0, 96) + "…") : t;
    },
    chainMeta(c){
      const bits = [];
      if (c && c.turns > 1) bits.push(c.turns + " 轮");

      if (this.isLiveChain(c)) bits.push("运行中");
      else if (c && c.tail && c.tail.interrupted) bits.push("⚠ 上次没跑完");
      else if (c && c.tail && c.tail.ok) bits.push("✅");
      const at = (c && c.tail && c.tail.started_text) || "";
      if (at) bits.push(String(at).slice(5, 16));
      return bits.join(" · ");
    },

    isLiveChain(c){
      this.A.rev;
      if (!this.A.running || !this.A.liveRunId || !c) return false;
      const live = String(this.A.liveRunId);
      return (c.ids || []).map(String).indexOf(live) >= 0 ||
             String((c.tail && c.tail.id) || "") === live;
    },
    dropEnter(){ if (!AIR.dropHot){ AIR.dropHot = true; AIR.rev++; } },
    dropLeave(e){
      const to = e && e.relatedTarget;
      if (to && this.$el && this.$el.contains(to)) return;
      if (AIR.dropHot){ AIR.dropHot = false; AIR.rev++; }
    },

    answer(choice, text, qid){ aiAnswer(choice, text, qid); },
    openMessages(id){ aiOpenMessages(id); },
    roleName(r){
      return {system: "系统提示（它每次开工都收到这一份）", user: "用户 / 工具结果",
              assistant: "它的回复", tool: "工具结果"}[r] || String(r || "?");
    },

    msgHead(m){
      const bits = [];
      if (m.tool_calls && m.tool_calls.length)
        bits.push("调用 " + m.tool_calls.map(c => (c.function || {}).name).join("、"));
      if (m.tool_call_id) bits.push("回给 " + m.tool_call_id);
      bits.push(((m.content || "").length) + " 字");
      return bits.join(" · ");
    },
    msgText(m){
      const c = m.content;
      if (typeof c === "string" && c) return c;
      if (m.tool_calls && m.tool_calls.length)
        return m.tool_calls.map(x => (x.function || {}).name + "(" +
                 String((x.function || {}).arguments || "").slice(0, 800) + ")").join("\n");
      return "（空）";
    },
    async copyMessages(){
      try{
        const data = AIR.msgData || {};
        const text = (data.messages || []).map(m =>
          "===== " + (m.role || "?") + " =====\n" + this.msgText(m)).join("\n\n");
        await navigator.clipboard.writeText(text);
        toast("复制了 " + (data.messages || []).length + " 条");
      }catch(e){ toast("复制失败：" + (e && e.message ? e.message : e), true); }
    },

    _logEl(){
      return this.$refs.log || (this.$el && this.$el.querySelector(".ai-log"));
    },
    _gap(el){ return el.scrollHeight - el.scrollTop - el.clientHeight; },
    nearBottom(el){
      return stickAfterScroll({auto: false, stick: true},
                              {gap: this._gap(el), clientHeight: el.clientHeight,
                               scrollHeight: el.scrollHeight});
    },
    onLogScroll(){
      const el = this._logEl();
      if (!el) return;

      if (!el.clientHeight) return;
      const next = stickAfterScroll(AIR, {gap: this._gap(el), clientHeight: el.clientHeight,
                                          scrollHeight: el.scrollHeight});
      if (next !== AIR.stick){ AIR.stick = next; AIR.rev++; }
    },

    onLogWheel(ev){
      if (!ev || ev.deltaY >= 0) return;
      if (!AIR.stick && !AIR.auto) return;
      AIR.stick = false; AIR.auto = false;
      clearTimeout(this._settleT);
      AIR.rev++;
    },
    toBottom(){ AIR.stick = true; this.followLog(true); },

    _logToBottom(force, depth){
      const el = this._logEl();
      if (!el) return;
      depth = depth || 0;
      const gen = (this._gen = (this._gen || 0) + 1);
      const gap = this._gap(el);
      const far = gap > Math.max(240, el.clientHeight * 1.5);
      const instant = !!(force || far);
      AIR.auto = true;                           
      clearTimeout(this._settleT);

      el.scrollTo({top: el.scrollHeight, behavior: instant ? "instant" : "smooth"});
      const check = () => {
        if (gen !== this._gen) return;           
        const left = this._gap(el);
        if (AIR.stick && left > 2 && depth < 3){ this._logToBottom(true, depth + 1); return; }
        AIR.auto = false;
        clearTimeout(this._settleT);
        if (left > 2 && AIR.stick) AIR.rev++;    
      };

      if (instant) requestAnimationFrame(() => requestAnimationFrame(check));
      if (this._sock){ try{ el.removeEventListener("scrollend", this._sock); }catch(e){} this._sock = null; }
      if ("onscrollend" in el){
        this._sock = () => { if (gen === this._gen){ clearTimeout(this._settleT); check(); } };
        el.addEventListener("scrollend", this._sock, {once: true});
      }
      this._settleT = setTimeout(check, instant ? 300 : 900);
    },

    rollback(snapIn){
      const A = this.A, target = this.target;
      const snap = snapIn || (this.lastRes && this.lastRes.snapshot);
      if (!snap){ toast("这次没存快照，没得退。", true); return; }
      askConfirm("回退到开工前？",
        "把 <code>" + esc(this.shortPath(target)) + "</code> 回到快照 <code>" + esc(snap.id) +
        "</code> 那一刻（AI 动手之前）。<br>只写回：缺的补上、改过的退回去，<b>多出来的不动</b>；" +
        "覆盖前会留 <code>.bak</code>。",
        async () => {
          try{
            const r = await window.pywebview.api.backup_restore(snap.id, null, "all", false,
                                                               snap.group || "");
            if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "回退失败"), true); return; }
            toast(r.msg || "回退好了");
          }catch(e){ toast("回退失败：" + (e && e.message ? e.message : e), true); }
        });
    },
    shortPath(p){ return String(p || "").replace(/^.*[\\/]pkgs[\\/]/, ""); },

    autoGrow(){
      this.shake = false;        
      const ta = this.$refs.ta;
      if (!ta) return;
      ta.style.height = "40px";
      ta.style.height = Math.min(ta.scrollHeight, 200) + "px";
    },
    resetLogs(){
      AIR.turns = []; AIR.cur = -1;
      AIR.muted = 0;
      AIR.result = null; AIR.steps = []; AIR.sentTask = ""; AIR.viewing = ""; AIR.pickId = ""; AIR.answeredQid = "";
      AIR.task = "";

      if (AIR.running) aiAttachLiveTurn();
      AIR.rev++;
      this.$nextTick(() => this.autoGrow());
    },

    altDown(e){
      if (e.key === "Escape"){ AIR.altOn = false; return; }
      if (e.key !== "Alt") return;
      if (typeof tab !== "undefined" && tab !== "ai") return;   
      if (!(this.A.turns || []).length) return;

      try{ e.preventDefault(); }catch(e2){}
      this._altDownSeen = true;        
      if (e.repeat) return;            
      AIR.altOn = !AIR.altOn;          
    },

    altUp(e){
      if (e.key !== "Alt") return;
      const seen = this._altDownSeen;
      this._altDownSeen = false;
      if (seen) return;                                  
      if (typeof tab !== "undefined" && tab !== "ai") return;
      if (!(this.A.turns || []).length) return;
      AIR.altOn = !AIR.altOn;
    },
    jumpTurn(ti){
      const t = (AIR.turns || [])[ti];
      if (!t) return;
      if (t.folded) t.folded = false;        
      AIR.rev++;
      this.$nextTick(() => {
        const els = this.$el ? this.$el.querySelectorAll(".ai-turn") : [];
        const el = els[ti];
        if (!el) return;
        el.scrollIntoView({block: "start", behavior: "smooth"});
        el.classList.add("ai-flash");
        setTimeout(() => el.classList.remove("ai-flash"), 1400);
      });
      AIR.altOn = false;
    },

    toggleTurn(ti){
      const t = (AIR.turns || [])[ti];
      if (!t) return;
      t.folded = !t.folded;
      AIR.rev++;
    },

    visSteps(steps){ return (steps || []).filter(s => !s.mute); },

    talkArgs(s){
        const v = s && s.args;
        let a = null;
        if (v && typeof v === "object") a = v;
        else {
          try { a = JSON.parse(v || "{}"); } catch(e) { a = {}; }
        }
        if (a && typeof a === "object" && Array.isArray(a.options)) {
          a.options = a.options.map(o => {
            if (typeof o === "string") return { label: o, value: o };
            return o;
          });
        }
        return (a && typeof a === "object") ? a : {};
      },
    turnCards(t){
      return this.visSteps(t.steps).map((s, i) => {
        const isTalk = s.tool === "ask" || s.tool === "perm";
        const ta = isTalk ? this.talkArgs(s) : {};
        const answered = !!s.done || (!!ta.qid && this.A.answeredQids.includes(ta.qid));
        if (isTalk) return {key: "s" + (s.n || i), type: "talk", tool: s.tool,
                            step: Object.assign({}, s, {done: answered}), ta};
        return {key: "s" + i, type: "step",
                icon: this.stepIcon(s.tool), color: this.kindColor(s.tool),
                action: this.stepTitle(s), tool: s.tool, meta: this.stepMeta(s),
                path: this.stepPath(s), step: s};
      });
    },    

    openStep(c){
      const s = (c && (c.step || c)) || null;
      if (!s) return;
      AIR.stepOpen = s;
      AIR.modalTab = "detail";
      document.body.style.overflow = "hidden";
      AIR.rev++;
    },
    openTurn(t, ti){
      if (!t) return;
      AIR.stepOpen = {
        n: Number(ti || 0) + 1,
        tool: "(对话)",
        brief: String(t.task || ""),
        note: String(t.note || ""),
        at: String(t.at || ""),
        why: "",
        turn: {
          task: String(t.task || ""),
          at: String(t.at || ""),
          note: String(t.note || ""),
          attachments: t.attachments || [],
          steps: t.steps || [],
          result: t.result || null,
        },
      };
      AIR.modalTab = "detail";
      document.body.style.overflow = "hidden";
      AIR.rev++;
    },
    setModalTab(tab){
      AIR.modalTab = String(tab || "detail");
      AIR.rev++;
    },
    closeModal(){
      AIR.stepOpen = null;
      AIR.msgOpen = false;
      document.body.style.overflow = "";
      AIR.rev++;
    },
    closeStep(){ this.closeModal(); },
    closeMessages(){ this.closeModal(); },
    stepHead(s){
      const bits = [];
      if (s && s.at) bits.push(s.at);
      if (s && s.ms) bits.push((s.ms / 1000).toFixed(1) + "s");
      if (s && s.tokens) bits.push((s.est ? "≈" : "") + cntok(s.tokens) + " token");
      if (s && s.note) bits.push(String(s.note).slice(0, 60));
      return bits.join(" · ");
    },
    async copyStep(){
      const s = AIR.stepOpen || {};
      const asText = v => (typeof v === "string") ? v : JSON.stringify(v, null, 2);
      let text = "";
      if (s.tool === "(对话)"){
        const t = s.turn || {};
        text = "第 " + s.n + " 轮 · 对话\n" + (t.task || "") +
               "\n\n【结果】\n" + JSON.stringify(t.result || {}, null, 2);
      } else {
        text = "第 " + s.n + " 步 · " + s.tool + "\n目的：" + (s.why || "") +
               "\n\n【参数】\n" + asText(s.args || "") +
               "\n\n【输出】\n" + asText(s.out || "");
      }
      try{
        await navigator.clipboard.writeText(text);
        toast("复制了这一步的原文");
      }catch(e){ toast("复制失败：" + (e && e.message ? e.message : e), true); }
    },
    modalSource(){ return jsonDecodeDeep(AIR.stepOpen || {}); },
    modalSourceHtml(){ return jsonTreeHtml(this.modalSource(), undefined, 0, true); },
    async copyModal(){
      if (AIR.modalTab === "source"){
        try{
          await navigator.clipboard.writeText(JSON.stringify(this.modalSource(), null, 2));
          toast("复制了源码 JSON");
        }catch(e){ toast("复制失败：" + (e && e.message ? e.message : e), true); }
        return;
      }
      await this.copyStep();
    },
    doShake(){
      this.shake = false;
      this.$nextTick(() => {
        this.shake = true;
        setTimeout(() => { this.shake = false; }, 520);
      });
    },
    stepLine(s){ return "#" + s.n + " " + s.tool + " " + (s.brief || "") + (s.note ? "  → " + s.note : ""); },
    tokens(u){ return u ? (u.total_tokens || 0) : 0; },
    humanTokens(n){ return humanTokens(n); },

    toolKind(t){
      if (["read_file", "grep", "list_dir"].indexOf(t) >= 0) return "read";
      if (["edit_file", "write_file"].indexOf(t) >= 0) return "write";
      if (t === "run_moss") return "run";
      if (t === "spec") return "spec";
      if (t === "done") return "done";
      if (t === "snap_clean") return "snap";
      if (t === "(思考)") return "think";
      if (["web_search", "web_fetch", "github_api"].indexOf(t) >= 0) return "web";
      return "misc";
    },
    toolIcon(t){
      return {read: "读", write: "写", run: "跑", spec: "约", done: "完",
              snap: "照", misc: "提"}[this.toolKind(t)] || "·";
    },

    rhead(r){
      if (!r) return "";
      if (r.kind === "chat") return r.ok ? "💬 回答" : "✗ 没能回答";
      return r.ok ? "✅ 验收通过" : "✗ 没通过";
    },

    rshowReason(r){
      if (!r || !r.reason || r.reason === "验收通过") return false;
      return r.kind === "chat" ? !r.ok : true;
    },
    stepIcon(t){
      if (this.selfNames[t]) return "moss-plus";
      return {list_dir: "folder-search", read_file: "file-text", grep: "search",
              edit_file: "file-code", write_file: "file-code", run_moss: "play",
              spec: "book-open", done: "check", snap_clean: "moss-camera",
              web_search: "search", web_fetch: "globe", github_api: "git-branch",
              "(思考)": "lightbulb"}[t] || "code";
    },
    runLine(r){
      const t = (r.started_text || "").slice(11, 19);

      const mark = r.kind === "chat" ? (r.ok ? "💬 " : "✗ ") : (r.ok ? "✅ " : "✗ ");
      return mark + (r.task || "").slice(0, 42) +
             "　" + (r.steps || 0) + " 步 · " + humanTokens((r.usage || {}).total_tokens || 0) +
             (t ? " · " + t : "");
    },

    followLog(force){
      if (!force && !AIR.stick) return;
      window.__followN = (window.__followN || 0) + 1;
      this.$nextTick(() => this._logToBottom(!!force, 0));
    },
    openRun(id){ aiOpenRun(id); },
    forgetRun(id){ aiForgetRun(id); },

    selfToggle(){ AIR.selfOpen = !AIR.selfOpen; AIR.rev++; },
    setSelfTab(t){ AIR.selfTab = t; AIR.rev++; },
    async refreshSkills(){ await aiLoadSkills(); toast("技能列表已刷新"); },
    async toggleFullAccess(){
      const want = !this.A.full;
      try{
        const got = await window.pywebview.api.ai_full_access(!!want, aiWhereDir());
        if (!got || !got.ok){ toast((got && got.msg) || "切不了完全权限", true); return; }
        toast(want ? "完全权限已开启：任意路径 + 技能自动批准 + 不再弹确认"
                   : "完全权限已关闭：恢复按权限清单和技能指纹授权");
      }catch(e){ toast("切不了完全权限：" + (e && e.message ? e.message : e), true); }
      await aiRefreshInfo(true);
      await aiLoadSkills();
    },

    async pickAttachment(images){
      if (AIR.running){ toast("它正在跑，等这一轮结束再加附件", true); return; }
      try{
        const api = await aiWaitApi(5000);
        if (!api || !api.ai_pick_attachments){
          toast("宿主桥没连上，暂时不能打开文件选择框", true);
          return;
        }
        const r = await api.ai_pick_attachments(!!images);
        if (!r || !r.ok){
          if (!(r && r.cancelled)) toast((r && r.msg) || "没选到文件", true);
          return;
        }
        const n = aiAttachPaths(r.files || []);
        if (n) toast("已添加 " + n + (images ? " 张图片" : " 个附件"));
        else toast("没有可添加的文件", true);
      }catch(e){ toast("挑附件失败：" + (e && e.message ? e.message : e), true); }
    },
    togglePalette(){
      AIR.paletteOpen = !AIR.paletteOpen;
      AIR.rev++;
    },
    setPaletteColor(color){
      const c = String(color || "").trim();
      if (c && !/^#[0-9a-fA-F]{6}$/.test(c)){ toast("颜色格式不对（要 #RRGGBB）", true); return; }
      AIR.paletteColor = c;
      AIR.paletteOpen = false;
      AIR.rev++;
      aiSaveUiState({palette: c});
      toast(c ? ("工作时聊天背景：把 " + c + " 变成缓慢呼吸的圆润色块")
              : "已恢复无颜色（工作时不再显示呼吸背景）");
    },
    async refreshBalance(){
      await aiRefreshBalance(true);
    },

    setPageVisible(on){
      const vis = !!on;
      if (vis && !AIR.pageVisible){
        if (!AIR.info) aiRefreshInfo();
        aiRefreshBalance(false);
      }
      AIR.pageVisible = vis;
    },
    skillOrigin(w){
      if (!w) return "";
      if (w.kind === "pkg") return "【插件】";
      if (w.origin === "seed" || w.layer === "system") return "【⚙️ 出厂样例】";
      return "【✨ 自身生成】";
    },
    lookTool(w){ aiSkillLook(w); },
    allowTool(w){ aiSkillAllow(w, !w.allowed); },
    rmTool(w){ aiSkillRm(w); },
    manageSkills(){ aiOpenSkills(); },

    async editTurn(t){
      const p = await aiTurnPlan(t.id);
      if (!p) return;
      askConfirm2("改这一轮？", aiPlanHtml(p) +
        "<br>改完**这句话会填回下面那个输入框**（你可以把它改成你想要的样子），" +
        "接着从**上一轮**往下走 —— 改好再点一次「发送指令」。",
        {label: "回退并填回输入框", danger: true, cb: async () => {
          const r = await aiDoTruncate(p.id);
          if (!r) return;
          await aiAfterTruncate(p, t.task, true, r.msg);
        }});
    },

    async delTurn(t){
      const p = await aiTurnPlan(t.id);
      if (!p) return;
      askConfirm2("删这一轮？", aiPlanHtml(p) +
        "<br>删掉之后**这条会话就从上一轮往后重新开始**（这条记录本身看不回来了）。",
        {label: "删掉并回退", danger: true, cb: async () => {
          const r = await aiDoTruncate(p.id);
          if (!r) return;
          await aiAfterTruncate(p, "", false, r.msg);
        }});
    },

    start(){
      const task = String(this.A.task || "").trim();
      if (!task && !(this.A.attachments || []).length){
        this.doShake(); toast("先写一句你要它干什么，或者加个附件。", true); return;
      }
      if (this.A.busy) return;
      aiStart();
    },

    async pickSession(){
      const id = this.A.pickId || "";
      if (!id){
        AIR.viewing = ""; AIR.sentTask = ""; AIR.steps = []; AIR.result = null;
        AIR.turns = []; AIR.cur = -1;                    
        AIR.contId = ""; AIR.contTask = ""; AIR.lastId = ""; AIR.muted = 0;

        if (AIR.running) aiAttachLiveTurn();
        AIR.rev++;
        toast("新会话：下一条不带之前的对话");
        return;
      }
      const c = this.sessChains.filter(x => x.head.id === id || x.tail.id === id)[0];
      const tail = (c && c.tail.id) || id;

      if (AIR.running && tail && tail === AIR.liveRunId){
        AIR.pickId = tail;
        AIR.viewing = "";                 
        aiAttachLiveTurn();
        AIR.rev++;
        toast("这就是正在跑的那一条 —— 已经切回实时，它在继续跑");
        return;
      }
      const r = (AIR.runs || []).filter(x => x.id === tail)[0] ||
                (AIR.runs || []).filter(x => x.id === id)[0];

      if (!(await aiOpenThread(tail))) return;
      AIR.viewing = tail;                 
      if (r && r.cont){
        AIR.contId = tail; AIR.contTask = r.task || "";
        toast("接着这条聊 —— 在下面写下一句，点发送"
              + (AIR.running ? "（正在跑的那一轮接在最下面，还在更新）" : ""));
      } else {
        AIR.contId = ""; AIR.contTask = "";
        toast("这条是更早的记录（当时还没存对话）—— 只能看，接不上", true);
      }
    },

    providerOf(m){
      const g = this.modelGroups.filter(x => x.models.indexOf(m) >= 0)[0];
      return g ? g.name : "";
    },

    toggleModelOpen(){
      if (this.A.running || !this.models.length) return;
      this.A.modelOpen = !this.A.modelOpen;
      if (this.A.modelOpen){
        this.A.modelQ = "";
        this.$nextTick(() => {
          try{ const el = this.$refs.modelQ; if (el && el.focus) el.focus(); }catch(e){}
        });
      }
    },
    closeModelPop(){
      this.A.modelOpen = false;
      this.A.modelQ = "";
    },

    async pickModel(m){
      m = String(m || "").trim();
      if (!m) return;
      this.closeModelPop();
      AIR.model = m;
      const want = this.providerOf(m);
      const cur = String((AIR.info && AIR.info.profile) || "");
      if (!want || !cur || want === cur){
        toast("这次用 " + m + " 跑（换模型连带换上下文窗口）");
        return;
      }
      const api = await aiWaitApi();
      if (!api || !api.ai_set_active){
        toast("「" + want + "」这家要先切过去，但界面桥没连上 —— 重启 moss 界面再试", true);
        return;
      }
      const r = await api.ai_set_active(want);
      if (r && r.ok){
        toast("已切到「" + want + "」，这次用 " + m + " 跑（" + (r.msg || "已记住") + "）");
        await aiRefreshInfo(true);
        await aiRefreshBalance(false);
      } else {
        toast("切到「" + want + "」没成功：" + ((r && r.msg) || "宿主没说什么"), true);
      }
    },

    openSel(ev){
      const box = ev && ev.currentTarget;
      const sel = box && box.querySelector && box.querySelector("select");
      if (!sel || sel.disabled) return;
      if (ev && ev.target === sel) return;          
      try{
        if (sel.showPicker) sel.showPicker();
        else sel.focus();
      }catch(e){ try{ sel.focus(); }catch(e2){} }
    },

    cntok(n){ return cntok(n); },

    stepTitle(s){
      const why = String((s && s.why) || "").trim();
      if (why) return why;
      const zh = {list_dir: "读目录", read_file: "读文件", grep: "搜内容", edit_file: "改文件",
                  write_file: "写文件", run_moss: "跑一遍", spec: "查契约", done: "收尾",
                  snap_clean: "清快照", ask: "问了你一句", allow_path: "请求放行目录",
                  web_search: "搜网页", web_fetch: "抓网页", github_api: "访问 GitHub",
                  "(思考)": "思考过程"};
      const name = (s && s.tool) || "";
      if (zh[name]) return zh[name];

      if (this.selfNames[name]) return "用自制工具";
      return "其它";
    },

    stepMeta(s){
      const bits = [];
      if (s && s.at) bits.push(String(s.at));
      if (s && s.ms >= 300) bits.push((s.ms / 1000).toFixed(1) + "s");
      if (s && s.note) bits.push(String(s.note));
      if (s && s.tokens) bits.push((s.est ? "≈" : "") + cntok(s.tokens) + " tok");
      if (!bits.length && s && s.n) bits.push("第 " + s.n + " 步");
      return bits.join(" · ");
    },

    kindColor(t){
      const k = this.toolKind(t);
      if (k === "write") return "var(--aib-success)";
      if (k === "run") return "var(--aib-warning)";
      if (k === "think") return "#8b5cf6";
      if (k === "web") return "#0891b2";
      return "var(--aib-primary)";
    },

    stepPath(s){
      if (s && s.nodisp) return "";
      if (s && s.disp) return String(s.disp);
      const b = String((s && s.brief) || "");
      try{
        const j = JSON.parse(b);
        if (j && typeof j === "object"){
          const bits = [];
          if (j.path) bits.push(String(j.path));
          if (j.find !== undefined) bits.push("把 " + JSON.stringify(String(j.find)).slice(0, 40) + " 换掉");
          if (j.args) bits.push("moss " + String(j.args));
          if (j.section) bits.push("契约：" + String(j.section));
          if (j.id) bits.push(String(j.id));
          if (j.summary) bits.push(String(j.summary));
          if (bits.length) return bits.join("　");
        }
      }catch(e){  }

      const m = b.match(/"(?:summary|content|text)"\s*:\s*"((?:[^"\\]|\\.)*)/);
      if (m){
        let t = m[1];
        try{ t = JSON.parse('"' + t + '"'); }catch(e){}
        return t;
      }
      return b;
    },

    contThis(r){
      AIR.contId = r.id; AIR.contTask = r.task || "";
      aiOpenRun(r.id);
      toast("接着这条聊（它还记着之前 " + (r.msgs || 0) + " 条对话）—— 写下一句，点开始");
    },

    newChat(){
      AIR.contId = ""; AIR.contTask = "";
      toast("下一条按新会话跑（老记录还在，随时能接着聊）");
    },
    again(r){ AIR.task = r.task || ""; AIR.contId = ""; AIR.contTask = "";
              toast("需求已填回输入框（按新会话跑）—— 改一改再点发送"); },

    onKey(e){
      if (e.key === "Enter" && !e.shiftKey){
        e.preventDefault();
        this.start();
      }
    },
    attachmentIcon(a){
      const mime = String((a && a.mime) || "").toLowerCase();
      const name = String((a && a.name) || "").toLowerCase();
      if (mime.indexOf("image/") === 0 ||
          /\.(png|jpe?g|gif|webp|bmp|svg|ico|avif)$/.test(name)) return "file-image";
      return "file-text";
    },
    attachmentSize(a){
      const n = Number((a && a.size) || 0);
      if (!n) return "";
      if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
      if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
      return n + " B";
    },

    fmtChars(n){
      const v = Math.max(0, Number(n || 0));
      return String(v).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    },
    removeAttachment(i){
      if (i < 0 || i >= AIR.attachments.length) return;
      AIR.attachments.splice(i, 1);
      AIR.rev++;
    },
    pasteAsText(a){
      if (!a || !a.text) return;
      const body = String(a.text);
      AIR.task = (AIR.task ? (AIR.task.replace(/\s*$/, "") + "\n\n") : "") + body;
      const i = AIR.attachments.indexOf(a);
      if (i >= 0) AIR.attachments.splice(i, 1);
      AIR.rev++;
      this.$nextTick(() => this.autoGrow());
    },
    togglePasteAsFile(){
      AIR.pasteAsFile = !AIR.pasteAsFile;
      AIR.rev++;
      toast(AIR.pasteAsFile ? "大段文本会收成附件" : "大段文本会直接粘进输入框");
    },

    openAtt(a){
      if (!a) return;
      AIR.att = {name: String(a.name || "粘贴文本.txt"),
                 text: String(a.text || ""),
                 size: Number(a.size || 0),
                 truncated: !!a.truncated};
      if (!AIR.att.text) toast("这条老记录里没留原文（那时候只存了文件名）", true);
      AIR.rev++;
    },
    closeAtt(){ AIR.att = null; AIR.rev++; },
    async copyAtt(){
      const t = (AIR.att && AIR.att.text) || "";
      if (!t) return;
      let ok = false;
      try{ await navigator.clipboard.writeText(t); ok = true; }catch(e){ ok = false; }
      if (!ok){
        try{
          const ta = document.createElement("textarea");
          ta.value = t;
          ta.style.position = "fixed"; ta.style.left = "-9999px"; ta.style.top = "0";
          document.body.appendChild(ta); ta.select(); document.execCommand("copy");
          document.body.removeChild(ta); ok = true;
        }catch(e2){ ok = false; }
      }
      toast(ok ? ("原文已复制（" + t.length + " 字）")
               : "复制失败 —— 在正文里全选再按 Ctrl+C", !ok);
    },
    async saveAtt(){
      const a = AIR.att;
      if (!a || !a.text) return;
      const api = window.pywebview && window.pywebview.api;
      if (api && api.ai_save_text){
        try{
          const r = await api.ai_save_text(a.name, a.text);
          if (r && r.ok) toast("已另存为：" + r.path);
          else if (r && r.cancelled) toast("没选位置，没存");
          else toast("另存为失败：" + ((r && r.msg) || "宿主没回话"), true);
        }catch(e){ toast("另存为失败：" + (e && e.message ? e.message : e), true); }
        return;
      }

      try{
        const blob = new Blob([a.text], {type: "text/plain;charset=utf-8"});
        const url = URL.createObjectURL(blob);
        const el = document.createElement("a");
        el.href = url; el.download = a.name || "粘贴文本.txt";
        document.body.appendChild(el); el.click(); document.body.removeChild(el);
        setTimeout(() => URL.revokeObjectURL(url), 3000);
        toast("已交给浏览器下载");
      }catch(e){ toast("另存为失败：" + (e && e.message ? e.message : e), true); }
    },
    onPaste(e){
      if (AIR.running) return;
      const dt = e && e.clipboardData;
      if (!dt) return;
      const files = [];
      const items = dt.items || [];
      for (let i = 0; i < items.length; i++){
        const it = items[i] || {};
        if (it.kind === "file"){
          try { const f = it.getAsFile(); if (f) files.push(f); } catch(err){}
        }
      }
      if (files.length){
        e.preventDefault();
        files.forEach(f => this.readClipboardFile(f));
        return;
      }
      const text = dt.getData ? String(dt.getData("text/plain") || "") : "";
      if (AIR.pasteAsFile && text.length >= ATTACH_TEXT_MIN){
        e.preventDefault();
        aiAddAttachment({kind: "text", source: "paste", name: aiPasteName(text),
                         text: text, size: text.length});
        toast("已把 " + text.length + " 字的大段文本收成附件");
      }
    },
    readClipboardFile(f){
      if (!f) return;
      if (f.size > ATTACH_FILE_MAX){
        toast("附件太大（超过 " + Math.round(ATTACH_FILE_MAX / 1048576) + " MB），先别贴进来了", true);
        return;
      }
      const r = new FileReader();
      r.onload = () => {
        aiAddAttachment({kind: "data", name: f.name || ("粘贴图片." + ((f.type || "image/png").split("/")[1] || "png")),
                         mime: f.type || "image/png", data_url: String(r.result || ""), size: f.size});
        toast("已添加附件：" + (f.name || "图片"));
      };
      r.onerror = () => toast("这个附件读不出来", true);
      r.readAsDataURL(f);
    },
    inputDragEnter(){
      if (!AIR.inputDropHot){ AIR.inputDropHot = true; AIR.rev++; }
    },
    inputDragOver(){ this.inputDragEnter(); },
    inputDragLeave(e){
      const cur = e && e.currentTarget;
      const to = e && e.relatedTarget;
      if (cur && to && cur.contains(to)) return;
      if (AIR.inputDropHot){ AIR.inputDropHot = false; AIR.rev++; }
    },
    inputDrop(){
      AIR.inputDropAt = Date.now();
    },

    phaseText(){
      this.A.rev;
      if (this.A.phase === "thinking") return "等模型回话";
      if (this.A.phase === "waiting") return "模型还没回（网络慢或这次问得长）";
      if (this.A.phase === "tools") return "执行工具";
      return "跑着";
    },
  },
  mounted(){
    aiRefreshInfo();
    aiStartPage();
    aiLoadUiState();

    AIR.ptick = setInterval(() => { aiPollPartial(); }, 250);

    AIR.tick = setInterval(() => {
      const pageOn = !!(this.$el && this.$el.classList && this.$el.classList.contains("on"));
      if (pageOn && !AIR.pageVisible) aiRefreshBalance(false);
      AIR.pageVisible = pageOn;

      if (pageOn && !AIR.info && Date.now() - Number(AIR.infoTryAt || 0) > 2500){
        AIR.infoTryAt = Date.now();
        aiRefreshInfo();
      }
      const p = aiPackage();
      const id = (p && p.id) || "";

      if (id !== AIR.curId){
        AIR.curId = id;

        if (aiLiveHere()) aiAttachLiveTurn();
        else aiScopeReset();

        if (AIR.pendingDone) aiShowDone(AIR.pendingDone);
        aiRefreshInfo();
        aiLoadRuns();
      }

      if (AIR.running || AIR.doneWait > 0){
        if (!AIR.running && AIR.doneWait > 0) AIR.doneWait--;
        aiPollOnce();
      }

      if (AIR.stick){
        const lg = this.$refs.log || (this.$el && this.$el.querySelector(".ai-log"));
        const vis = !!(lg && lg.clientHeight);
        if (vis && !AIR.wasVis && (lg.scrollHeight - lg.scrollTop - lg.clientHeight) > 2)
          this.followLog(true);
        AIR.wasVis = vis;
      }

      if (AIR.permPop) this.fitPop("perm");
      if (AIR.histOpen) this.fitPop("hist");
    }, 700);

    this._rs = () => {
      if (AIR.permPop) this.fitPop("perm");
      if (AIR.histOpen) this.fitPop("hist");
    };
    window.addEventListener("resize", this._rs);

    this.$nextTick(() => this.autoGrow());

    this._sc = () => this.onLogScroll();
    this._wh = (ev) => this.onLogWheel(ev);
    this.$nextTick(() => {
      const el = this.$refs.log || (this.$el && this.$el.querySelector(".ai-log"));
      if (el){
        el.addEventListener("scroll", this._sc, {passive: true});
        el.addEventListener("wheel", this._wh, {passive: true});
      }
      this.onLogScroll();
    });

    window.__mossAiDrop = (items) => {
      if (typeof tab !== "undefined" && tab !== "ai") return false;
      const list = items || [];

      const _inputHit = AIR.inputDropHot || (Date.now() - Number(AIR.inputDropAt || 0) < 2000);
      if (_inputHit){
        const files = list.filter(x => x && x.path && x.isDir !== true);
        if (files.length){
          const n = aiAttachPaths(files);
          if (n) toast("已添加 " + n + " 个附件");
          AIR.inputDropHot = false; AIR.inputDropAt = 0;
          AIR.rev++;
          return true;
        }
        if (list.some(x => x && x.path)){
          toast("文件夹不能作为附件；想放行目录，请拖到页面空白处。", true);
          AIR.inputDropHot = false; AIR.inputDropAt = 0;
          AIR.rev++;
          return true;
        }
      }
      const it = list.filter(x => x && x.path && x.isDir !== false)[0] ||
                 list.filter(x => x && x.path)[0];
      if (!it) return false;

      const p = String(it.path || "");
      const use = (it.isDir === false) ? p.replace(/[\\/][^\\/]*$/, "") : p;
      if (!use) return false;
      AIR.dropHot = false;
      aiAllowAdd(use, "你拖进来的");
      return true;
    };

    this._kd = e => this.altDown(e);
    this._ku = e => this.altUp(e);
    window.addEventListener("keydown", this._kd, true);
    window.addEventListener("keyup", this._ku, true);

    this._md = e => {
      const t = e.target;
      if (AIR.histOpen && !(t && t.closest && t.closest(".ai-hist-wrap"))) AIR.histOpen = false;
      if (AIR.permPop && !(t && t.closest && t.closest(".ai-perm-wrap"))) AIR.permPop = false;

      if (AIR.modelOpen && !(t && t.closest && t.closest(".ai-model-pick"))) AIR.modelOpen = false;

      if (AIR.paletteOpen && !(t && t.closest && t.closest(".ai-palette-wrap"))) AIR.paletteOpen = false;
      if (!AIR.altOn) return;
      if (t && t.closest && t.closest(".ai-jump")) return;
      AIR.altOn = false;
    };
    document.addEventListener("mousedown", this._md, true);
  },
  beforeUnmount(){
    window.removeEventListener("keydown", this._kd, true);
    window.removeEventListener("keyup", this._ku, true);
    if (this._rs) window.removeEventListener("resize", this._rs);
    document.removeEventListener("mousedown", this._md, true);

    try{
      const el = this.$refs.log || (this.$el && this.$el.querySelector(".ai-log"));
      if (el && this._sc) el.removeEventListener("scroll", this._sc);
    }catch(e){}
    if (window.__mossAiDrop) window.__mossAiDrop = null;
    if (AIR.tick){ clearInterval(AIR.tick); AIR.tick = null; }
    if (AIR.ptick){ clearInterval(AIR.ptick); AIR.ptick = null; }      
  },
  template: `
  <div class="aiwrap" @dragover.prevent="dropEnter()" @dragleave="dropLeave($event)">
    <div class="ai-workspace">

      <p class="ai-warn" v-if="A.err">⚠ {{ A.err }}</p>
      <p class="ai-warn loading" v-else-if="!info">正在读取 AI 配置…</p>
      <p class="ai-warn" v-else-if="!ready">⚠ {{ info.why || "还没配好 AI —— 去「设置 → AI」挑一家、把 key 填上。" }}</p>
      <p class="ai-warn" v-if="missing.length">⚠ 提示词文件缺了：{{ missing.join("、") }}（不补也能跑，只是少了那几条规矩）。</p>
      <p class="ai-warn" v-if="target && !canWrite">
        ⚠ 这个包现在<b>只读</b> —— 权限清单里它那一行的<b>「写」没勾</b>。想让它动手：
        在下面那份「目录权限控制」清单里，把这一行的<b>「写」勾上</b>。
      </p>

      





      <section class="ai-skill-widget" v-if="selfTotal">
        <div class="ai-skill-head">
          <div class="ai-skill-tabs">
            <button class="ai-skill-tab" :class="{active: A.selfTab === 'pending'}"
                    type="button" @click="setSelfTab('pending')">
              待批准
              <span class="ai-skill-badge" v-if="selfPendList.length">{{ selfPendList.length }}</span>
            </button>
            <button class="ai-skill-tab" :class="{active: A.selfTab === 'active'}"
                    type="button" @click="setSelfTab('active')">
              已启用
              <span class="ai-skill-count">({{ selfOkList.length }})</span>
            </button>
          </div>
          <div class="ai-skill-actions">
            <button class="ai-skill-iconbtn" type="button" title="管理技能"
                    @click="manageSkills()" v-html='ico("wrench", "i")'></button>
            <button class="ai-skill-iconbtn" type="button" title="刷新列表"
                    @click="refreshSkills()" v-html='ico("refresh-cw", "i")'></button>
          </div>
        </div>

        <div class="ai-skill-list" v-show="A.selfTab === 'pending'">
          <div class="ai-skill-alert" v-if="selfPendList.length">
            <span v-html='ico("alert-triangle", "i")'></span>
            <span>它给自己造了 <strong>{{ selfPendList.length }} 只技能</strong>，你点「允许」它下一次跑才能用。</span>
          </div>
          <div class="ai-skill-row" v-for="w in selfPendList" :key="w.id">
            <div class="ai-skill-info">
              <span class="ai-skill-name">{{ w.id }}</span>
              <span class="ai-skill-desc" :title="w.desc || w.why">
                {{ skillOrigin(w) }} {{ w.desc || w.why || "（没写说明）" }}
              </span>
            </div>
            <div class="ai-skill-rowacts">
              <button class="ai-skill-btn primary" type="button"
                      v-if="w.layer !== 'system' && !(w.problems || []).length"
                      @click="allowTool(w)">
                <span v-html='ico("check", "i")'></span><span class="txt">允许</span>
              </button>
              <button class="ai-skill-btn" type="button" @click="lookTool(w)">
                <span v-html='ico("eye", "i")'></span><span class="txt">{{ A.selfWho === w.id ? "收起" : "审查" }}</span>
              </button>
              <button class="ai-skill-iconbtn danger" type="button" title="删除"
                      v-if="w.layer !== 'system'" @click="rmTool(w)"
                      v-html='ico("trash-2", "i")'></button>
            </div>
            <pre class="ai-skill-pre" v-if="A.selfWho === w.id">{{ A.selfText }}</pre>
          </div>
          <div class="ai-skill-empty" v-if="!selfPendList.length">没有待批准的技能。</div>
        </div>

        <div class="ai-skill-list" v-show="A.selfTab === 'active'">
          <div class="ai-skill-row" v-for="w in selfOkList" :key="w.id">
            <div class="ai-skill-info">
              <span class="ai-skill-name">{{ w.id }}</span>
              <span class="ai-skill-desc" :title="w.desc || w.why">
                {{ skillOrigin(w) }} {{ w.desc || w.why || "（没写说明）" }}
              </span>
            </div>
            <div class="ai-skill-rowacts">
              <button class="ai-skill-btn" type="button"
                      v-if="w.layer !== 'system'" @click="allowTool(w)">
                <span v-html='ico("corner-up-left", "i")'></span><span class="txt">撤销</span>
              </button>
              <button class="ai-skill-iconbtn danger" type="button" title="删除"
                      v-if="w.layer !== 'system'" @click="rmTool(w)"
                      v-html='ico("trash-2", "i")'></button>
            </div>
          </div>
          <div class="ai-skill-row" v-for="w in selfBrokenList" :key="'b' + w.id">
            <div class="ai-skill-info">
              <span class="ai-skill-name">{{ w.id }}</span>
              <span class="ai-skill-desc" :title="w.desc || w.why">
                {{ skillOrigin(w) }} {{ w.desc || w.why || "（没写说明）" }}
                · {{ (w.problems || []).join("；") }}
              </span>
            </div>
            <div class="ai-skill-rowacts">
              <button class="ai-skill-btn" type="button" @click="lookTool(w)">
                <span v-html='ico("eye", "i")'></span><span class="txt">{{ A.selfWho === w.id ? "收起" : "审查" }}</span>
              </button>
              <button class="ai-skill-iconbtn danger" type="button" title="删除"
                      v-if="w.layer !== 'system'" @click="rmTool(w)"
                      v-html='ico("trash-2", "i")'></button>
            </div>
            <pre class="ai-skill-pre" v-if="A.selfWho === w.id">{{ A.selfText }}</pre>
          </div>
          <div class="ai-skill-broken" v-if="selfBrokenList.length">
            <span v-html='ico("alert-triangle", "i")'></span>
            这几只进不了工具表（先修好再说）：{{ selfBrokenNames }}
          </div>
          <div class="ai-skill-empty" v-if="!selfOkList.length && !selfBrokenList.length">还没有已启用的技能。</div>
        </div>
      </section>

      


      




      


      





      <div class="ai-logwrap">
      

      <div class="ai-breath-bg" :class="{on: A.paletteColor && A.running}"
           :style="{'--ai-palette': A.paletteColor || '#93C5FD'}" aria-hidden="true">
        <span class="ai-blob ai-blob-1"></span>
        <span class="ai-blob ai-blob-2"></span>
        <span class="ai-blob ai-blob-3"></span>
      </div>
      <main class="log-container ai-log" ref="log">
        








        <div class="ai-turn" v-for="(t, ti) in A.turns" :key="t.key">
          <div class="ai-bub me">
            <span class="ai-bub-ic" v-html='ico("moss-user", "i")'></span>
            <div class="ai-bub-b">
              <div class="ai-bub-h">
                <b class="ai-th-n">#{{ ti + 1 }}</b>
                <span class="ai-th-a" :title="t.note || t.at"
                      :class="{bad: /接不上/.test(t.note || '')}"
                      >{{ t.folded ? ("已折叠 · " + (t.note || "点一下展开")) : (t.note || t.at || "") }}</span>
                
                <span class="ai-th-x">
                  <button @click.stop="openTurn(t, ti)"
                          title="查看这一轮的详情，或看它和 AI 交互的完整源码 JSON">源码</button>
                  <template v-if="t.id && !A.running">
                    <button @click.stop="editTurn(t)"
                            title="改这一轮：回到它开工前的快照（撤销它改的东西），并把这句话填回输入框 —— 改好再发一次">编辑</button>
                    <button class="danger" @click.stop="delTurn(t)"
                            title="删这一轮：从这一轮到会话末尾的记录一起删掉，并按快照回退">删除</button>
                  </template>
                </span>
              </div>
              <div class="ai-bub-t" @click="toggleTurn(ti)"
                   :title="t.folded ? '点一下展开中间过程' : '点一下折叠中间过程'">{{ t.task }}</div>
              

              <div class="ai-bub-atts" v-if="(t.attachments || []).length">
                <button type="button" v-for="a in t.attachments" :key="a.name + ':' + a.size"
                        class="ai-att-chip" :class="{viewable: !!a.text, muted: !a.text}"
                        :title="a.text ? '点开看原文（可复制全文 / 另存为）' : '这条老记录里没留原文'"
                        @click.stop="openAtt(a)">
                  <span v-html='ico(a.kind === "text" ? "file-text" : "file", "i")'></span>
                  <span class="ai-att-chip-n">{{ a.name }}</span>
                  <span class="ai-att-chip-s" v-if="a.size">{{ a.kind === "text"
                      ? (fmtChars(a.size) + " 字") : attachmentSize(a) }}</span>
                </button>
              </div>
            </div>
          </div>

          <template v-if="!t.folded">
            <template v-for="c in turnCards(t)" :key="c.key">
              
              <div class="ai-bub ai talk" v-if="c.type === 'talk'" :class="{waiting: !c.step.done}">
                <span class="ai-bub-ic"
                      v-html='ico(c.step.tool === "perm" ? "file-lock" : (c.ta.kind === "confirm" ? "alert-triangle" : "message-circle"), "i")'></span>
                <div class="ai-bub-b">
                  <div class="ai-bub-h">
                    <b>{{ c.step.tool === "perm" ? "它想放行一个目录" : (c.ta.kind === "confirm" ? "危险操作" : "它在问你") }}</b>
                    <span class="dim" v-if="!c.step.done && c.ta.qid && A.ask && A.ask.qid === c.ta.qid">
                      已经等了 {{ A.ask.asking }} 秒</span>
                    <span class="dim" v-else-if="!c.step.done && c.ta.path && A.perm && A.perm.path === c.ta.path">
                      已经等了 {{ A.perm.asking }} 秒</span>
                  </div>
                                      <p class="ai-bub-q" v-if="c.step.tool === 'perm'">
                      请求放行目录：<br>
                      <span @click="openDir(c.ta.path)" style="cursor: pointer; text-decoration: underline; color: var(--accent); word-break: break-all;" title="在资源管理器中打开">{{ c.ta.path }}</span>
                    </p>
                    <p class="ai-bub-q" v-else>{{ c.step.brief }}</p>
                  <p class="ai-bub-w" v-if="c.step.why">为什么：{{ c.step.why }}</p>
                  <p class="ai-bub-w" v-if="c.ta.detail">{{ c.ta.detail }}</p>

                  
                  <div class="ai-bub-a" v-if="!c.step.done">
                    <template v-if="c.step.tool === 'perm'">
                      <button class="btn btn-primary" :disabled="A.askBusy" @click="reqAllow()"
                              v-html='ico("check", "i") + " 允许"'></button>
                      <button class="btn btn-danger" :disabled="A.askBusy" @click="reqDeny()"
                              v-html='ico("x", "i") + " 拒绝"'></button>
                    </template>
                    <template v-else>
                      <button class="ai-ask-opt" v-for="o in (c.ta.options || [])" :key="o.value"
                              :disabled="A.askBusy" @click="answer(o.value, A.askText, c.ta.qid)">
                        <span class="ai-ask-opt-t">{{ o.label }}</span>
                        <span class="ai-ask-opt-d" v-if="o.desc">{{ o.desc }}</span>
                      </button>
                      <div class="ai-ask-t" v-if="c.ta.allow_text">
                        <input v-model="A.askText" spellcheck="false" :disabled="A.askBusy"
                               placeholder="也可以直接打字回它（回车发送）"
                               @keydown.enter.prevent="answer('', A.askText, c.ta.qid)">
                        <button class="ai-ask-send" :disabled="A.askBusy"
                                @click="answer('', A.askText, c.ta.qid)">就这么回</button>
                      </div>
                    </template>
                  </div>

                  
                  
                  <div class="ai-bub-ans" v-else>
                    <div class="ai-ask-history" v-if="c.step.tool === 'ask' && c.ta.options && c.ta.options.length">
                      <span class="ai-ask-history-label">全部候选项：</span>
                      <span class="ai-ask-history-opt" v-for="o in c.ta.options" :key="o.value"
                            :class="{chosen: String(o.value) === String(c.step.answer)}">
                        {{ o.label }}
                      </span>
                    </div>
                    <span class="ai-bub-mine" v-if="c.step.answer">{{ c.step.answer }}</span>
                    <span class="ai-bub-note">{{ c.step.out || "（答完了）" }}</span>
                  </div>
                </div>
              </div>

              
              <div class="step-card ai-step" v-else
                   :class="'k-' + toolKind(c.tool)" :data-tool="c.tool || ''"
                   @click="openStep(c)"
                   :title="c.tool === '(思考)' ? '点一下展开思考过程（默认折叠）' : ('点一下看这一步的原始参数与输出（工具：' + (c.tool || '?') + '）')">
                <div class="step-icon" v-html='ico(c.icon, "i")'></div>
                <div class="step-content">
                  <div class="step-header">
                    <span class="step-action" :style="{color: c.color}">{{ c.action }} <b>{{ c.tool }}</b></span>
                    <span class="step-meta">{{ c.meta }}</span>
                  </div>
                  <span class="code-path" v-if="c.path">{{ c.path }}</span>
                </div>
                <span class="ai-step-x" v-html='ico("eye", "i")'
                      :title="c.tool === '(思考)' ? '展开思考过程' : '点一下看这一步的原始参数与输出'"></span>
              </div>
            </template>

            

            <div class="ai-bub ai streaming" v-if="t.key === A.liveKey && A.partial &&
                 (A.partial.text || A.partial.think)">
              <span class="ai-bub-ic" v-html='ico("sparkles", "i")'></span>
              <div class="ai-bub-b">
                <div class="ai-bub-h">
                  <b>{{ A.partial.text ? "它正在写" : "它在想" }}</b>
                  <span class="dim ai-stream-n">{{ A.partial.text
                      ? (fmtChars(A.partial.chars) + " 字")
                      : (fmtChars(A.partial.tchars) + " 字思考") }}</span>
                  <span class="ai-stream-dot"></span>
                </div>
                <div class="ai-stream-think" v-if="!A.partial.text && A.partial.think">{{ A.partial.think }}</div>
                <div class="ai-stream-t" v-if="A.partial.text">{{ A.partial.text }}<span class="ai-caret"></span></div>
              </div>
            </div>

          </template>

            
            <div class="ai-bub ai" v-if="t.result">
              <span class="ai-bub-ic" v-html='ico("sparkles", "i")'></span>
              <div class="ai-bub-b">
                <div class="ai-result" :class="{ok: !!t.result.ok, bad: !t.result.ok}">
                  <div class="ai-rhead"><span v-if="A.viewing" class="ai-old">历史记录</span>{{ rhead(t.result) }}<span
                    v-if="rshowReason(t.result)"> —— {{ t.result.reason }}</span></div>
                  <div class="ai-rsnap" v-if="t.result.snapshot">
                    <span>开工前已存快照 <code>{{ t.result.snapshot.id }}</code>（AI 存的，列表里带「AI」徽章）</span>
                    <button class="btn btn-outline" @click.stop="rollback(t.result.snapshot)"
                            title="回到这次动手之前（只写回：缺的补上、变了的回退）">回退到开工前</button>
                  </div>
                  

                  <div class="ai-rsnap warn" v-else-if="(t.result.files || []).length">
                    <span>⚠ 这次改了文件，但没存上快照（{{ t.result.snapshot_note || '原因没记下来' }}）
                      —— 出问题回不去</span>
                  </div>
                  <p v-if="t.result.summary" class="ai-rsum">{{ t.result.summary }}</p>
                  <p v-if="t.result.caveats" class="ai-rcav">它自己标的不确定：{{ t.result.caveats }}</p>
                  <div v-if="(t.result.files || []).length" class="ai-rfiles">动过的文件：<span
                    v-for="f in t.result.files" :key="f">{{ shortPath(f) }}　</span></div>
                  <div class="ai-rtok" v-if="t.result.usage">
                    token：输入 {{ t.result.usage.prompt_tokens }} / 输出 {{ t.result.usage.completion_tokens }} / 合计 {{ t.result.usage.total_tokens }}
                    （上限 {{ humanTokens(A.maxTokens) }}）
                    <span v-if="t.result.folded">· 折叠了 {{ t.result.folded }} 条旧结果</span>
                  </div>
                </div>
              </div>
            </div>
        </div>

        <p class="ai-empty" v-if="!A.turns.length">
          还没有跑过。写下你要它做什么 —— 它会读代码、动手改、跑一遍验证，然后把结果摆在这儿。
        </p>

        

        <div class="thinking-indicator" :class="{on: A.running}"
             :title="A.running ? (A.seconds + 's · 第 ' + curStep + ' 步 · 已烧 ' + humanTokens(curTokens) +
                     ' / ' + humanTokens(A.maxTokens) + ' token' +
                     (curFolded ? (' · 已折叠 ' + curFolded + ' 条旧结果') : '') +
                     (A.promptTokens ? (' · 上下文 ' + humanTokens(A.promptTokens) + ' / ' +
                                        humanTokens(A.compactAt) + '（' + ctxPct + '%）') : '')) : ''">
          <div class="pulse-dot"></div> AI 正在思考并执行...
        </div>

        

      </main>
        <button class="ai-tobottom" :class="{on: !A.stick}" @click="toBottom()"
                :title="'有新内容 —— 点一下回到最新（你往上翻的时候它不会抢你的滚动条）'"
                v-html='ico("chevron-down", "i") + " 回到最新"'></button>
      </div>

      




      <footer class="bottom-area ai-foot ai-split">
        <div class="chat-input-container ai-box ai-right"
             :class="{focused: focused, 'error-shake': shake, 'drop-hot': A.inputDropHot}"
             @dragover.prevent="inputDragOver"
             @dragenter.prevent="inputDragEnter"
             @dragleave="inputDragLeave($event)"
             @drop="inputDrop">
          
      <div class="ai-console-top">
        <div class="ai-console-left">
          <button type="button" class="ai-console-new" @click="pickNewChat()"
                  title="新建空白会话（下一条不带之前的对话）">
            <span v-html='ico("moss-plus", "i")'></span><span>新会话</span>
          </button>
              
              <div class="popover-wrapper ai-hist-wrap ai-console-hist-wrap">
                <button ref="histBtn" class="trigger-btn ai-hist ai-console-hist" :class="{active: A.histOpen}" @click.stop="toggleHist()"
                        :title="'历史会话（只列这个包的）。现在：' + ((sessCurrent && sessCurrent.head && sessCurrent.head.task) || '新会话')">
                  <span v-html='ico("list-ul", "i")'></span>
                  <span class="ai-console-history-label">历史会话</span>
                  <span class="badge">{{ sessChains.length }}</span>
                </button>
                <div ref="histPanel" class="popover-panel ai-hist-list" :class="{show: A.histOpen}" v-if="A.histOpen" @click.stop>
                  <div class="popover-title">当前包的历史<span class="popover-hint">点一条就切过去</span></div>
                  <div class="history-list">
                    <div class="history-item ai-hist-i" v-for="c in sessChains" :key="c.head.id"
                         :class="{active: sessCurrent && (sessCurrent.head.id === c.head.id),
                                  live: isLiveChain(c)}"
                         :title="(c.head.task || '') + '　' + chainMeta(c)"
                         @click="pickChain(c)">
                      <div class="history-item-left">
                        <span class="status-dot"></span>
                        <span class="history-item-title ai-hist-t">{{ chainTitle(c) }}</span>
                      </div>
                      <div class="history-item-right">
                        <span class="ai-hist-m">{{ chainMeta(c) }}</span>
                        <button class="btn-delete ai-hist-x" @click.stop="delChain(c)" title="删除这次会话（它下面所有轮次）"
                                v-html='ico("trash-2", "i")'></button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
        </div>
        <div class="ai-console-right">
              
              <span class="tool-text ai-bud token-pill" role="progressbar"
                    :aria-valuenow="tokenPct" aria-valuemin="0" aria-valuemax="100"
                    :aria-valuetext="tokenUsedMillions + 'M / ' + tokenLimitMillions + 'M'"
                    :title="tokTip + '；这是当前一次会话的 token 总上限，点击数字可改（单位：M = 百万）'">
                <span class="token-pill-fill" :style="{width: tokenPct + '%'}"></span>
                <span class="token-pill-bar" :style="{width: tokenPct + '%'}"></span>
                <span class="token-pill-text">
                  <span class="token-pill-used">{{ tokenUsedMillions }}M</span>
                  <span class="token-pill-sep">/</span>
                  <span class="token-pill-limit-group">
                    <input class="ai-token-limit ai-bud-n" type="number" min="0.5" max="20000" step="10"
                           :size="String(A.maxMillions || '').length || 1"
                           v-model.number="A.maxMillions" :disabled="A.running" @change="saveBudget()"
                           @wheel.prevent
                           title="当前一次会话的 token 总上限（M = 百万）。烧到 80% 时劝它收尾，到顶就停手。"
                           aria-label="当前一次会话的 token 总上限（M，百万）">
                    <span class="token-pill-unit">M</span>
                  </span>
                </span>
              </span>
              
              <button type="button" class="trigger-btn ai-mini ai-balance-btn ai-console-balance"
                      :class="{ok: !!(A.balance && A.balance.ok), bad: !!(A.balance && !A.balance.ok)}"
                      :disabled="A.balanceLoading" @click.stop="refreshBalance()"
                      :title="balanceTitle" :aria-label="'账户余额：' + balanceText">
                <span v-html='ico("coins", "i")'></span>
                <span class="ai-balance-text">{{ balanceText }}</span>
              </button>
          <span class="ai-console-divider" aria-hidden="true"></span>
              
              <div class="popover-wrapper ai-palette-wrap ai-console-palette">
                <button type="button" class="trigger-btn ai-mini ai-palette-btn"
                        :class="{active: A.paletteOpen, colored: !!A.paletteColor}"
                        @click.stop="togglePalette()"
                        :title="'聊天背景调色盘 · 当前：' + paletteCurrentName + '（只在 AI 工作时呼吸显示）'">
                  <span v-html='ico("paint-roller", "i")'></span>
                  <span class="ai-palette-dot" v-if="A.paletteColor" :style="{background: A.paletteColor}"></span>
                </button>
                <div class="popover-panel ai-palette-pop" :class="{show: A.paletteOpen}"
                     v-if="A.paletteOpen" @click.stop>
                  <div class="popover-title">工作时背景
                    <span class="popover-hint">{{ paletteCurrentName }}</span>
                  </div>
                  <div class="ai-palette-grid">
                    <button type="button" class="ai-swatch" v-for="c in palettePresets" :key="c.color"
                            :class="{on: A.paletteColor.toLowerCase() === c.color.toLowerCase()}"
                            :style="{background: c.color}" :title="c.name + ' · ' + c.color"
                            @click="setPaletteColor(c.color)"></button>
                  </div>
                  <div class="ai-palette-actions">
                    <label class="ai-palette-custom" title="自己挑一个颜色">
                      <input type="color" :value="A.paletteColor || '#60A5FA'"
                             @change="setPaletteColor($event.target.value)">
                      <span>自定义</span>
                    </label>
                    <button type="button" class="ai-palette-none" @click="setPaletteColor('')">
                      无颜色
                    </button>
                  </div>
                  <p class="ai-palette-note">只在它工作的时候出现；停下来就回到平常的白色背景。</p>
                </div>
              </div>
        </div>
      </div>
          <div class="ai-atts" v-if="A.attachments.length">
            <div class="ai-at" v-for="(a, i) in A.attachments" :key="a.key"
                 :class="{img: attachmentIcon(a) === 'file-image'}">
              <span class="ai-at-ic" v-html='ico(attachmentIcon(a), "i")'></span>
              <span class="ai-at-n" :title="a.path || a.name">{{ a.name }}</span>
              <span class="ai-at-s" v-if="a.size">{{ attachmentSize(a) }}</span>
              <button class="ai-at-act" type="button" v-if="a.kind === 'text'"
                      @click="openAtt(a)" title="看这段原文（可复制全文 / 另存为）">查看</button>
              <button class="ai-at-act" type="button" v-if="a.kind === 'text' && a.source === 'paste'"
                      @click="pasteAsText(a)" title="把这段原文放回输入框，按普通粘贴发出去">粘贴原文至输入框</button>
              <button class="ai-at-x" type="button" @click="removeAttachment(i)" title="移除附件"
                      v-html='ico("x", "i")'></button>
            </div>
          </div>
          <div class="input-area">
            <textarea class="prompt-textarea ai-task" ref="ta" v-model="A.task" spellcheck="false"
              :disabled="A.running" @input="autoGrow" @focus="focused = true" @blur="focused = false"
              @keydown="onKey" @paste="onPaste"
              placeholder="在此输入指令... (按 Enter 发送，Shift+Enter 换行)"></textarea>
          </div>

          <div class="toolbar ai-input-toolbar">
            <div class="toolbar-left ai-input-tools">
              <div class="popover-wrapper ai-model-pick">
                <button type="button" class="ai-model-btn" :class="{active: A.modelOpen}"
                        :disabled="A.running || !models.length" @click.stop="toggleModelOpen()"
                        :title="'这次用哪个模型。当前「' + currentProvider + '」，'
                                + '共 ' + modelGroups.length + ' 家 / ' + models.length + ' 个模型。'
                                + '选别家的模型会自动把那家设为当前。'">
                  <span class="ai-model-txt">{{ A.model || "（还没配 AI）" }}</span>
                  <span class="ai-model-prov" v-if="modelGroups.length > 1">{{ currentProvider }}</span>
                  <span class="ai-model-cv" v-html='ico("chevron-down", "i")'></span>
                </button>
                <div class="popover-panel ai-model-pop" :class="{show: A.modelOpen}"
                     v-if="A.modelOpen" @click.stop>
                  <div class="popover-title">选择模型
                    <span class="popover-hint">{{ modelGroups.length }} 家 · {{ models.length }} 个<span
                          v-if="A.running">（跑完才能换）</span></span>
                  </div>
                  <label class="ai-model-q" v-if="models.length > 6">
                    <span v-html='ico("search", "i")'></span>
                    <input ref="modelQ" v-model="A.modelQ" spellcheck="false" autocomplete="off"
                           placeholder="筛一下：模型名 / 服务商"
                           @keydown.esc.stop.prevent="closeModelPop()">
                  </label>
                  <div class="ai-model-list">
                    <div class="ai-model-grp" v-for="g in modelGroupsShown" :key="g.name">
                      <div class="ai-model-gh">
                        <span class="ai-model-gn">{{ g.name }}</span>
                        <span class="ai-model-gc">{{ g.models.length }}</span>
                        <span class="ai-model-gk" v-if="!g.has_key">没填 key</span>
                        <span class="ai-model-gnow" v-else-if="g.active">当前</span>
                      </div>
                      <button type="button" class="ai-model-it" v-for="m in g.models" :key="m"
                              :class="{on: m === A.model}" @click="pickModel(m)">
                        <span class="ai-model-tick" v-html='ico("check", "i")'></span>
                        <span class="ai-model-nm">{{ m }}</span>
                      </button>
                    </div>
                    <div class="ai-model-none" v-if="!modelGroupsShown.length">没有匹配的模型</div>
                  </div>
                </div>
              </div>
              

              <div class="popover-wrapper ai-perm-wrap ai-perm" :class="{folded: !A.permPop}">
                <button ref="permBtn" class="trigger-btn ai-perm-fold"
                        :class="{active: A.permPop, full: A.full}"
                        @click.stop="togglePermPop()"
                        :title="'权限控制 · ' + permState + '（点开看清单）'">
                  <span class="ai-perm-shield" v-html='ico(A.full ? "shield-check" : "shield", "i")'></span>
                  <span class="ai-perm-state">{{ permState }}</span>
                  <span class="dim ai-perm-foldw" v-if="A.perm">· 它想用「{{ permPendingLabel }}」</span>
                </button>
                <div ref="permPanel" class="popover-panel ai-perm-body" :class="{show: A.permPop}" v-if="A.permPop" @click.stop>
                  <div class="ai-perm-full">
                    <div class="ai-perm-full-info">
                      <b>完全权限 <span class="ai-perm-full-sub">无人值守</span></b>
                      <span>任意路径可读写；新建 / 修改技能自动批准；危险操作 / 覆盖不再弹确认</span>
                    </div>
                    <label class="switch-group ai-sw" :title="A.full ? '关掉：恢复按权限清单和技能指纹授权' : '打开：任意路径 + 技能自动批准 + 不再弹确认'">
                      <span class="switch"><input type="checkbox" :checked="!!A.full"
                        @change="toggleFullAccess()"><span class="slider"></span></span>
                    </label>
                  </div>
                  <div class="popover-header ai-perm-add" :class="{hot: A.dropHot, bad: addPathBad || !!A.newPathErr}">
                    <input v-model="A.newPath" spellcheck="false"
                           placeholder="粘一个目录路径（或把文件夹拖到这一页）"
                           :title="addPathBad ? ('这不是一个路径 —— ' + addPathHint) : '粘一个目录的完整路径'"
                           @input="A.newPathErr = ''" @keydown.enter.prevent="allowAdd()">
                    <button class="btn" @click="allowPick()" title="用系统对话框选一个目录加进来"
                            v-html='ico("folder-open", "i") + " 选目录"'></button>
                    <button class="btn" @click="allowAdd()" :disabled="!canAddPath"
                            :title="canAddPath ? '把这个目录加进清单（读 + 写都开）' : '先填一个存在的目录的完整路径'"
                            v-html='ico("moss-plus", "i") + " 添加"'></button>
                  </div>
                  <p class="ai-perm-err" v-if="addPathBad || A.newPathErr">
                    <span v-html='ico("circle-alert", "i")'></span>
                    {{ addPathBad ? addPathHint : A.newPathErr }}
                  </p>
                  <div class="path-list">
                    <div class="path-item ai-perm-i" v-for="it in allowRows" :key="it.path">
                      <div class="path-info ai-perm-info" :title="it.path">
                        
                        <div class="path-title ai-perm-p">
                          <template v-if="it._p && it._p.tail">
                            <span class="pp-head" v-if="it._p.head">{{ it._p.head }}</span>
                            <span class="pp-mid" v-if="it._p.mid">{{ it._p.mid }}</span>
                            <span class="pp-tail">{{ it._p.tail }}</span>
                          </template>
                          <template v-else>{{ permLabel(it) }}</template>
                        </div>
                        <div class="path-desc ai-perm-d">{{ permDesc(it) }}</div>
                      </div>
                      <div class="path-controls ai-perm-togs">
                        <label class="switch-group ai-sw" :title="'读：勾上它才能看 ' + it.path">读
                          <span class="switch"><input type="checkbox" :checked="!!it.read"
                            @change="allowSet(it, 'read', $event.target.checked)"><span class="slider"></span></span>
                        </label>
                        <label class="switch-group ai-sw" :title="'写：勾上它才能改 ' + it.path + '（关掉 = 只让它看）'">写
                          <span class="switch"><input type="checkbox" :checked="!!it.write"
                            @change="allowSet(it, 'write', $event.target.checked)"><span class="slider"></span></span>
                        </label>
                        
                        <button class="btn-delete ai-perm-act" @click="copyPath(it)"
                                title="复制这个路径" v-html='ico("copy", "i")'></button>
                        <button class="btn-delete ai-perm-act" @click="openDir(it.path)"
                                title="在资源管理器里打开" v-html='ico("folder-open", "i")'></button>
                        <button class="btn-delete ai-perm-x" v-if="!it.current" @click="allowRm(it)"
                                title="从清单里删掉（它就读不了也写不了这里）" v-html='ico("trash-2", "i")'></button>
                        <span class="ai-perm-lock" v-else v-html='ico("file-lock", "i")'
                              title="当前这个包，删不掉（把写关掉就行）"></span>
                      </div>
                    </div>
                  </div>
                  



                  <div class="ai-perm-other" v-if="allowOther.length">
                    <div class="ai-perm-other-h">
                      <button type="button" class="ai-perm-other-t" @click.stop="toggleOtherPerm()"
                              title="这些行指向别的包（或已经不在的包），跟当前这个包无关 —— 点开可以看、可以删">
                        <span v-html='ico("folder-tree", "i")'></span>
                        另有 <b>{{ allowOther.length }}</b> 条别的包的权限
                        <span class="dim">{{ A.otherOpen ? "收起" : "展开 / 清掉" }}</span>
                      </button>
                      <button type="button" class="btn-delete ai-perm-other-x" v-if="A.otherOpen"
                              @click.stop="rmOtherAll()"
                              title="把这些行全删掉（只影响那些包：它们在各自的页面里还能重新申请）"
                              v-html='ico("trash-2", "i") + " 全清掉"'></button>
                    </div>
                    <p class="ai-perm-other-w">
                      以前在别的包里干活时批准过的目录，跟当前这个包没关系、也不影响它 ——
                      想收拾就删掉；这个包真要读写别的包，它会当场来问你。
                    </p>
                    <div class="path-list" v-if="A.otherOpen">
                      <div class="path-item ai-perm-i other" v-for="it in allowOther" :key="it.path">
                        <div class="path-info ai-perm-info" :title="it.path">
                          <div class="path-title ai-perm-p"><span class="pp-tail">{{ permLabel(it) }}</span></div>
                          <div class="path-desc ai-perm-d">
                            包 {{ it._otherOf }}<span v-if="it._otherOld">（已经不在了）</span>
                            · {{ it.why || "（没写为什么）" }}
                          </div>
                        </div>
                        <div class="path-controls ai-perm-togs">
                          <button class="btn-delete ai-perm-x" @click.stop="allowRm(it)"
                                  title="从清单里删掉这一条" v-html='ico("trash-2", "i")'></button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              
              <button class="trigger-btn ai-mini ai-messages-icon ai-txtbtn" @click="openMessages()"
                      title="查看这条会话的完整提示词历史">
                <span v-html='ico("book-open", "i")'></span>
                <span class="ai-btn-txt">提示词</span>
              </button>

              <span class="ai-toolbar-divider" aria-hidden="true"></span>

              
              <button type="button" class="trigger-btn ai-mini ai-upload-btn ai-txtbtn"
                      :disabled="A.running" @click.stop="pickAttachment(false)"
                      title="上传附件（可多选；代码 / 文本 / 图片都行）">
                <span v-html='ico("folder-plus", "i")'></span>
                <span class="ai-btn-txt">附件</span>
              </button>
              <button type="button" class="trigger-btn ai-mini ai-upload-btn ai-txtbtn"
                      :disabled="A.running" @click.stop="pickAttachment(true)"
                      title="上传图片（可多选，交给模型直接看）">
                <span v-html='ico("file-image", "i")'></span>
                <span class="ai-btn-txt">图片</span>
              </button>
            </div>

            
            <button type="button" class="ai-send-circle"
                    :disabled="!A.running && (A.busy || !ready)"
                    @click="A.running ? stop() : start()"
                    @mouseenter="stopHover = !!A.running"
                    @mouseleave="stopHover = false"
                    :title="A.running ? '停止' : '发送 (Enter)'"
                    v-html='A.running ? (stopHover ? ico("square", "i") : ico("loader-2", "i spin")) : ico("arrow-up", "i")'></button>
          </div>

        </div>
      </footer>

      
      <div class="ai-modal-overlay" v-if="A.stepOpen" @click.self="closeStep()">
        <div class="ai-modal-box">
          <div class="ai-modal-header">
            <div class="ai-modal-title-group">
              <h3 class="ai-modal-title">
                <span v-html='ico(A.stepOpen.tool === "(思考)" ? "lightbulb" : (A.stepOpen.tool === "(对话)" ? "message-square" : "search"), "i")'></span>
                {{ A.stepOpen.tool === "(思考)" ? "模型思考过程" : (A.stepOpen.tool === "(对话)" ? ("第 " + A.stepOpen.n + " 轮 · 对话") : ("第 " + A.stepOpen.n + " 步 · " + A.stepOpen.tool)) }}
              </h3>
              <span class="ai-modal-meta">{{ stepHead(A.stepOpen) }}</span>
            </div>
            <button class="ai-modal-close" type="button" title="关闭"
                    @click="closeStep()">&times;</button>
          </div>
          <div class="ai-modal-tabs">
            <button class="ai-modal-tab" type="button"
                    :class="{active: A.modalTab === 'detail'}"
                    @click="setModalTab('detail')">查看详情</button>
            <button class="ai-modal-tab" type="button"
                    :class="{active: A.modalTab === 'source'}"
                    @click="setModalTab('source')">查看源码</button>
          </div>
          <div class="ai-modal-body">
            <template v-if="A.modalTab === 'detail'">
              <template v-if="A.stepOpen.tool === '(思考)'">
                <div class="ai-thought-content">
                  <span class="ai-thought-hint">原始思考记录（展开）：</span>
                  <p class="ai-thought-text">{{ A.stepOpen.out || "（这次没有思考过程）" }}</p>
                </div>
              </template>
              <template v-else-if="A.stepOpen.tool === '(对话)'">
                <div class="ai-modal-sec">
                  <h4>用户指令</h4>
                  <p class="ai-thought-text">{{ (A.stepOpen.turn || {}).task || "（空）" }}</p>
                </div>
                <div class="ai-modal-sec" v-if="((A.stepOpen.turn || {}).attachments || []).length">
                  <h4>附件</h4>
                  <p class="ai-thought-text">共 {{ ((A.stepOpen.turn || {}).attachments || []).length }} 个附件</p>
                </div>
                <div class="ai-modal-sec">
                  <h4>中间过程</h4>
                  <p class="ai-thought-text">共 {{ (((A.stepOpen.turn || {}).steps) || []).length }} 个步骤</p>
                </div>
                <div class="ai-modal-sec" v-if="(A.stepOpen.turn || {}).result">
                  <h4>最终结果</h4>
                  <p class="ai-thought-text">{{ ((A.stepOpen.turn || {}).result || {}).summary || (((A.stepOpen.turn || {}).result || {}).reason || "（没写总结）") }}</p>
                </div>
              </template>
              <template v-else>
                <p class="ai-detail-w" v-if="A.stepOpen.why">它说这一步是为了：{{ A.stepOpen.why }}</p>
                <div class="ai-modal-sec">
                  <h4>参数</h4>
                  <pre class="ai-msg-t">{{ A.stepOpen.args || "（这一步没有参数）" }}</pre>
                </div>
                <div class="ai-modal-sec">
                  <h4>输出</h4>
                  <pre class="ai-msg-t">{{ A.stepOpen.out || "（这一步没有输出）" }}</pre>
                </div>
              </template>
            </template>
            <div class="ai-json-view" v-show="A.modalTab === 'source'"
                 v-html="modalSourceHtml()"></div>
          </div>
          <div class="ai-modal-footer">
            <button class="ai-modal-btn" type="button" @click="copyModal()">复制</button>
            <button class="ai-modal-btn primary" type="button" @click="closeStep()">关闭</button>
          </div>
        </div>
      </div>

      

      <div class="ai-modal-overlay" v-if="A.msgOpen" @click.self="closeMessages()">
        <div class="ai-modal-box">
          <div class="ai-modal-header">
            <div class="ai-modal-title-group">
              <h3 class="ai-modal-title">
                <span v-html='ico("file-text", "i")'></span>
                完整提示词历史
              </h3>
              <span class="ai-modal-meta" v-if="A.msgData">
                {{ A.msgData.count || 0 }} 条 · {{ A.msgData.bytes || 0 }} 字节
                <template v-if="A.msgData.model"> · 模型 {{ A.msgData.model }}</template>
              </span>
            </div>
            <button class="ai-modal-close" type="button" title="关闭"
                    @click="closeMessages()">&times;</button>
          </div>
          <div class="ai-modal-body">
            <p class="ai-msgs-note dim" v-if="A.msgBusy">正在读…</p>
            <p class="ai-msgs-note" v-else-if="A.msgData && !A.msgData.ok">{{ A.msgData.msg || A.msgData.note }}</p>
            <div class="ai-msgs-b" v-else>
              <div class="ai-msg" v-for="(m, i) in ((A.msgData && A.msgData.messages) || [])" :key="i"
                   :class="'r-' + (m.role || '?')">
                <div class="ai-msg-h">
                  <b>{{ roleName(m.role) }}</b>
                  <span class="dim">{{ msgHead(m) }}</span>
                </div>
                <pre class="ai-msg-t">{{ msgText(m) }}</pre>
              </div>
            </div>
          </div>
          <div class="ai-modal-footer">
            <button class="ai-modal-btn" type="button" @click="copyMessages()">复制</button>
            <button class="ai-modal-btn primary" type="button" @click="closeMessages()">关闭</button>
          </div>
        </div>
      </div>

      

      <div class="ai-modal-overlay" v-if="A.att" @click.self="closeAtt()">
        <div class="ai-modal-box ai-attbox">
          <div class="ai-modal-header">
            <div class="ai-modal-title-group">
              <h3 class="ai-modal-title">{{ A.att.name }}</h3>
              <span class="ai-modal-meta">{{ attMeta }}</span>
            </div>
            <button class="ai-modal-close" type="button" title="关闭"
                    @click="closeAtt()">&times;</button>
          </div>
          <div class="ai-modal-body">
            <p class="ai-msgs-note" v-if="!A.att.text">
              这条记录里没留原文（老记录只存了文件名）。原文在发出去的那次对话里 ——
              点「看提示词」能看到它当时被拼进提示词的样子。
            </p>
            <pre class="ai-att-pre" v-else>{{ A.att.text }}</pre>
            <p class="ai-att-note" v-if="A.att.truncated">这条太长，只存了前 20 万字。</p>
          </div>
          <div class="ai-modal-footer">
            <button class="ai-modal-btn" type="button" :disabled="!A.att.text"
                    @click="copyAtt()" title="把原文整段复制到剪贴板">复制全文</button>
            <button class="ai-modal-btn primary" type="button" :disabled="!A.att.text"
                    @click="saveAtt()" title="挑一个位置存成 .txt">另存为…</button>
            <button class="ai-modal-btn" type="button" @click="closeAtt()">关闭</button>
          </div>
        </div>
      </div>

    </div>

    

    <div class="ai-jump" v-if="A.altOn && A.turns.length"
         @mouseenter="this._overJump = true" @mouseleave="this._overJump = false">
      <div class="ai-jump-h">这个会话里我说过的（{{ A.turns.length }}）<span>点一条跳过去</span></div>
      <div class="ai-jump-list">
        <div class="ai-jump-i" v-for="(t, ti) in A.turns" :key="t.key"
             :title="t.task" @click="jumpTurn(ti)">
          <b>#{{ ti + 1 }}</b>
          <span class="ai-jump-t">{{ t.task }}</span>
          <span class="ai-jump-a">{{ (t.at || "").split(" · ").pop() }}</span>
        </div>
      </div>
    </div>
  </div>`,
};

window.__aiVm = mountVue(MossAi, "#pane-ai", {ico: ico, pSym: () => PSYM});   
