/* moss 界面 · list.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 显示 / 隐藏
   管的是**这个包自己的界面窗口**（GUI 包跑起来那扇窗）：藏起来 ≠ 关掉，
   还能再叫出来。窗口归属由宿主认（进程树 ∪ 进程环境里的 MOSS_PKG_ID），
   所以从终端开的也认得出来。 */
async function toggleVis(p){
  if (isHist(p)) return;                  // 路径调用没有"包自己的窗口"（按钮也是禁用的）
  const st = PST[p.id] || {windows: 0, visible: false};
  const r = st.visible ? await pywebview.api.pkg_hide(p.id)
                       : await pywebview.api.pkg_show(p.id);
  toast(r.msg, !r.ok);
  setTimeout(() => refreshPkgState(p), 400);
}

/* 详情页开着的时候，每 2.5 秒对一次状态（包可能是从别处启动/关掉的）
   ★ 现在左侧列表也要显示状态，所以**一次把所有包都问回来**、不管在哪个选项卡。 */
function pkgPollStart(){
  if (pstTimer) return;
  pstTimer = setInterval(refreshAllStates, 2500);
}

/* ---------------------------------------------------------------- 包列表 */
let side = "pkg";               // pkg | hist（左侧顶部那个切换）

function setSide(which){
  side = which;
  $("#sw-pkg").classList.toggle("on", which === "pkg");
  $("#sw-hist").classList.toggle("on", which === "hist");
  $("#list").hidden = which !== "pkg";
  $("#hist").hidden = which !== "hist";
  $("#btn-newpkg").hidden = which !== "pkg";   // 新建的是**包**，历史这边不该有这个按钮
  $("#q").placeholder = which === "pkg" ? "搜索包名 / 说明 / 标签…"
                                        : "搜索历史（名字 / 参数 / 目录）…";
  if (which === "hist") loadHist().then(renderHist); else renderList();
}

/* ---------------------------------------------------------------- 历史（路径调用）
   数据来自 `user_data/history/*.jsonl`（宿主那侧读好、去过重）。
   ★ 点一下 = **选中它**（不再是直接重跑）—— 和包列表一样：右边出「详情 / 命令行 /
     文件管理」三个选项卡，只有点「运行」（或详情里那个参数框回车）才真的跑，
     而且**在它当初的目录里跑**。行尾那颗播放图标仍然是"点一下就重跑"。
   目标目录里若有 `icon.xxx` 就用它当图标；没有就按目标文件的
   **后缀**画一个（跟文件管理器里同一个图标），不是一个千篇一律的返回箭头。 */
let HIST = [];

async function loadHist(){
  try{
    const r = await pywebview.api.hist_list(60);
    HIST = (r && r.ok && r.items) || [];
  }catch(e){ HIST = []; }
  // 选中的那条会被重新读成**新对象** —— 按 key 找回来，别让详情里看的是旧的
  if (curH){
    const k = histKey(curH);
    curH = HIST.find(x => histKey(x) === k) || curH;
  }
}

// 键要带参数：同一个文件用不同参数跑过，是**两条**历史，不能共用一份控制台
function histKey(it){ return "hist:" + it.target + (it.args ? " " + it.args : ""); }
function histIconHTML(it, cls){
  const c = cls || "hico";
  if (it.icon_svg){ const s = safeSvg(it.icon_svg); if (s) return '<span class="' + c + '">' + s + '</span>'; }
  if (it.icon) return '<span class="' + c + '"><img src="' + it.icon + '" alt=""></span>';
  // 没有 icon.xxx：按目标文件的类型画（和文件管理里那套完全同一个图标）
  const nm = it.name || it.target || "";
  const e = extOf({name: nm, ext: (nm.split(".").pop() || "").toLowerCase()});
  return '<span class="' + c + '" style="color:' + e.c + '">' + ico(e.i, "i") + '</span>';
}

/* 一条历史的目标目录，写成页面用的 rel：优先落在 user_data / system 两个根里，
   落到外面就是 `abs/<绝对路径>`（宿主认这个前缀，见 `system/ui/main.py` 的 ABS_ROOT）。
   ★ 根那一段**大小写不敏感**地比（Windows 路径本来就无所谓大小写）——
     不然盘符写小写就会掉进 `abs/`，面包屑上看着像"跑到外面去了"。 */
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
  try{ paintSwitchCounts(); }catch(e){}      // `V-199`：历史那个数字
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
    // 文件没了的：不放"运行"按钮 —— 点了也只会报"目标已经不在了"，不如不给点
    if (gone && !running){
      box.innerHTML = "";
      return;
    }
    box.innerHTML = running
      ? '<button class="ic-run" title="正在跑 —— 点这里停掉它">' + ico("square", "i") + '</button>'
      : '<button class="idle" title="不选中，直接重跑这次调用">' + ico("play", "i") + '</button>';
    const b = box.querySelector("button");
    if (b) b.onclick = (ev) => {
      ev.stopPropagation();                    // 点图标不要连带选中那一行
      if (running) stopRun(key); else rerunHistByKey(key);
    };
  });
}

function rerunHistByKey(key, args){
  const it = HIST.find(x => histKey(x) === key);
  if (!it) return;
  // ★ 从列表里跑：先把它选上（不切选项卡）—— 右上角那颗「运行/停止」认的是"当前选中项"
  //   （`V-216` 那句"不动左边的选中"在这里反了：不选上，右上角就永远显示「运行」）。
  if (curH !== it) selectHist(it, /*keepTab*/ true);
  rerunHist(it, args);
}

/* 选中一条历史：右边三个选项卡跟着换成"这一条"的。
   `keepTab` = 只选上、不切到「详情」（列表里点「运行」时用，见 `select`）。 */
function selectHist(it, keepTab){
  curH = it; cur = null;
  consoleKey = histKey(it);
  renderList(); renderHist(); renderDetail(); paintConsole();
  if (!keepTab) setTab("detail");
  fmSelect(histKey(it), /*keepTab*/ true);     // 文件管理换成"这条调用所在的目录"
}

async function rerunHist(it, args){
  const key = histKey(it);
  if (RUNS[key]) return;
  const a = args === undefined ? (it.args || "") : args;
  lastRun = {key: key, args: a, label: "moss /" + it.name};
  consoleKey = key;
  setConsole(key, "$ moss /" + it.name + (a ? " " + a : ""), "运行中");
  // ★ 宿主会把**它真正要跑的命令和当前目录**回报回来（`rerun_argv` 那条规则：
  //   绝对路径 moss 的解析器不认，得翻成"手敲形式"）。所以这里用 `r.cmd` 覆盖一遍，
  //   界面上显示的就是真的那条命令，不是界面自己猜的。
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

/* 「再跑一次」按 key 也认（历史那条会走它） */
function rerunLast(){
  if (!lastRun) return;
  if (lastRun.key) return rerunHistByKey(lastRun.key, lastRun.args);
  const p = DATA.packages.find(x => x.id === lastRun.id);
  if (!p){ toast("找不到 " + PSYM + lastRun.id + " 这个包了", true); return; }
  if (RUNS[p.id]) return;
  startRun(p, lastRun.args);
}

/* 列表 / 历史的"该重画了"信号（`V-79`）。
   ★ 为什么用举牌而不是把 DATA/HIST 变成响应式：`DATA`/`HIST`/`cur`/`curH`/`side` 都是**别的文件**里的
     普通 `let`（整个被重新赋值），改成响应式要动一圈别的模块；原来的代码本来就在"数据变了"的地方
     显式调 `renderList()` / `renderHist()`，所以**保留那几个函数名当门面**、让它们举牌最省事，
     行为也一字不变（外部调用点一个都不用改）。 */
/* ★ `V-178`：列表的工具条状态（分类 / 排序）与"加入时间"缓存。
   `born` = 包目录的 mtime（用现成的 `fs_list` 拿，两次调用就够：system/pkgs 与 user/pkgs）；
   `run`  = 最后一次看到它在跑（本界面自己记的 —— host 没有这个字段，所以只从这次开始算）。 */
const LISTR = Vue.reactive({rev: 0, ready: false, filt: "all", sort: "name",
                            hfilt: "all", hsort: "time", born: {}, custom: []});

function _ls(k, d){ try{ return localStorage.getItem(k) || d; }catch(e){ return d; } }
function _lsSet(k, v){ try{ localStorage.setItem(k, v); }catch(e){} }

function lastRunOf(id){
  const v = parseInt(_ls("moss.lastrun." + id, "0"), 10) || 0;
  return v;
}
function noteRunning(ids){
  // 看着它跑 → 记一笔"最后运行"。同一个包 5 秒内不重复写（省点 localStorage 抖动）
  const now = Date.now();
  (ids || []).forEach(id => {
    if (now - lastRunOf(id) > 5000) _lsSet("moss.lastrun." + id, String(now));
  });
}
/* 拉一次"加入时间"（包目录的 mtime）：键用目录名（`dir` 是绝对路径，取最后一段最稳） */
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
/* 图标表（`V-179`）：分组 → 取值 → 图标名（都在我们那 86 个图标里，不会回退成默认） */
const LB_ICONS = {
  filt:  {all: "layers", system: "package", user: "moss-user"},
  sort:  {name: "list-tree", born: "history", run: "activity", custom: "grip-vertical"},
  hfilt: {all: "layers", path: "file-code", pkg: "package"},
  hsort: {time: "history", name: "list-tree", kind: "file-type"},
};
// ★ `V-305`：下拉每项要"图标 + 文字"两样（原来只有图标 + title 悬停才看得到名字）。
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
    // ① 下拉菜单里的每一项：图标 + 标签 + 当前这项打个勾
    bar.querySelectorAll(".dd-i").forEach(b => {
      const g = b.dataset.g, v = b.dataset.v;
      if (!g || !v) return;
      const ic = (LB_ICONS[g] || {})[v];
      const lb = (LB_LABELS[g] || {})[v] || v;
      b.innerHTML = ico(ic, "i") + '<span>' + esc(lb) + '</span>' + ico("check", "i dd-chk");
      b.classList.toggle("on", LISTR[g] === v);
    });
    // ② 触发器：显示"现在选的是哪个"（图标 + 标签 + 小箭头）
    bar.querySelectorAll(".dd-t").forEach(t => {
      const g = t.dataset.dd, v = LISTR[g];
      const ic = (LB_ICONS[g] || {})[v];
      const lb = (LB_LABELS[g] || {})[v] || v;
      t.innerHTML = ico(ic, "i") + '<span>' + esc(lb) + '</span>' + ico("chevron-down", "i caret");
    });
  });
}

/* 工具条第三组那几颗（`V-180`）：刷新 / 新建包 / 打开文件并运行 */
function paintBarActs(){
  const put = (sel, ic) => { const b = $(sel); if (b && !b.querySelector("svg")) b.innerHTML = ico(ic, "i"); };
  put("#btn-refresh", "refresh-cw");
  put("#btn-newpkg", "file-plus");
  put("#btn-refresh-h", "refresh-cw");
  put("#btn-openfile", "play-circle");
  const rh = $("#btn-refresh-h"), r = $("#btn-refresh");
  if (rh && r) rh.onclick = () => r.click();          // 两个刷新干的是同一件事
  const of = $("#btn-openfile");
  if (of) of.onclick = () => openFileAndRun();
}

/* 挑一个文件 → 直接运行：工作目录 = 它所在的文件夹（＝手敲 moss <那个文件>，一样进历史） */
async function openFileAndRun(){
  let r;
  try{ r = await pywebview.api.pick_file(); }
  catch(e){ toast("挑文件失败：" + (e && e.message || e), true); return; }
  // 取消 = 不吭声（宿主回 `cancelled:true`；老宿主只有一句"没有选（取消）"，就认那句话）
  if (!r || !r.ok){ if (r && !r.cancelled && r.msg && r.msg.indexOf("取消") < 0) toast(r.msg, true); return; }
  const p = String(r.path || "");
  const name = p.split(/[\\/]/).pop() || p;
  const cwd = p.replace(/[\\/][^\\/]*$/, "");
  // 复用"重跑一条历史"那条链路：控制台、轮询、跑完刷新列表/历史，全都有
  rerunHist({name: name, target: p, cwd: cwd, args: "", ts: new Date().toISOString(),
             kind: "path", key: "__openfile:" + p}, "");
}
function initListBars(){
  LISTR.filt = _ls("moss.filt", "all");    LISTR.sort = _ls("moss.sort", "name");
  LISTR.hfilt = _ls("moss.hfilt", "all");  LISTR.hsort = _ls("moss.hsort", "time");
  // ★ `V-305`：选项在下拉菜单里（`.dd-i`）—— 点一下选中、存下来、重画（hover 展开由 CSS 管）
  document.querySelectorAll(".listbar .dd-i").forEach(b => {
    b.onclick = () => {
      LISTR[b.dataset.g] = b.dataset.v;           // 一下点到位
      _lsSet(LB_LS[b.dataset.g] || "moss.lb", b.dataset.v);
      paintListBars();
      bumpLists();
      if (b.dataset.g === "sort") saveListView();          // `V-300`：排序档也存下来（跨重启）
      if (b.dataset.g === "sort" && b.dataset.v === "born") loadBornTimes();
    };
  });
  paintListBars();
  paintBarActs();
  loadBornTimes();
  // ★ 注意：**不在这里**读"自定义顺序" —— 此刻（页面刚加载）pywebview 的桥还没就绪，
  //   `pywebview.api.list_state()` 会抛错被吞掉、顺序就"读不回来"。挪到 `init()` 里、
  //   `await state()` 之后调（那时桥一定就绪）。见 app.js。
}

/* ★ `V-300`：插件列表的"自定义顺序 + 排序档" —— 存 `user_data/state/_ui_order.json`
   （走宿主，不用 localStorage：页面地址每次启动都变，那个读不回来）。
   ★ 容错：存下来的顺序里**多出来的 id（已卸载的包）直接丢掉**；**没记过顺序的包**按名字
     排在后面（见 `rows`/`_allIdsInView` 的 custom 分支）—— 对不上不报错。 */
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

/* ★ `V-300`：插件列表**拖动排序**（用指针事件自己实现 —— HTML5 原生 drag 在 WebView2 里
   一直不听话、实测拖不动）。整行都能拖（行尾按钮除外）；移动超过小阈值才算"拖"；
   **拖动过程中就实时跟手重排**（不再画插入线、松手才动）；拖一下自动切到「自定义顺序」档并落盘。
   ★ 认"哪一行"一律用**坐标**（`clientY` + 行的 rect），**不用 `e.target`** ——
     WebView2 的命中测试会错位（实测点在 y=442、`e.target` 却是 y=1294 那一行）。 */
let _pdrag = null;               // {id, y0, moved, pid, item}
let _listDragging = false;
// `LISTDR.dragId` = 正在拖的那一行（绑到行的 `:class`，Vue 实时重排也保得住半透明标记）
const LISTDR = Vue.reactive({dragId: null});

/* `V-300` 排障：拖动这条线的日志。写两处 —— 浏览器控制台 + 宿主日志文件
   （`user_data/state/_ui_drop.log`，普通运行也能看，不用开 devtools）。 */
function _nm(id){
  const p = (DATA.packages || []).find(x => x.id === id);
  return (p && (p.name || p.id)) || id;
}
function _dragLog(msg){
  try{ console.log("[排序] " + msg); }catch(e){}
  try{ pywebview.api.ui_log("[排序] " + msg); }catch(e){}
}

function _allIdsInView(){
  // 当前排序下"全部包"的顺序（不带搜索/分类过滤）—— 拖动时的基准序列
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
  // 按坐标找"哪一行"（用 clientY 和行的 rect）—— 别信命中测试（WebView2 会错位）
  const rows = [].slice.call(document.querySelectorAll("#list .item"));
  for (const el of rows){
    const r = el.getBoundingClientRect();
    if (clientY >= r.top && clientY <= r.bottom) return el;
  }
  return null;
}
function _reorderLive(clientY){
  // 实时跟手：把"正在拖的那一行"挪到指针当前位置（改 `LISTR.custom`，Vue 立即重排）。
  //   返回 true = 顺序真的变了（调用方据此给"其它行"做 FLIP 动画）。
  const from = _pdrag && _pdrag.id;
  if (!from) return false;
  const vis = [].slice.call(document.querySelectorAll("#list .item")).map(el => el.dataset.id);
  const others = [].slice.call(document.querySelectorAll("#list .item"))
    .filter(el => el.dataset.id !== from);
  let ti = others.length;                            // 落点：第一个"中线在指针下方"的行之前
  for (let i = 0; i < others.length; i++){
    const r = others[i].getBoundingClientRect();
    if (clientY < r.top + r.height / 2){ ti = i; break; }
  }
  const v = vis.filter(id => id !== from);
  v.splice(ti, 0, from);
  if (v.join(",") === vis.join(",")) return false;   // 顺序没变：别白重画
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
/* ★ `V-300`：手动 FLIP —— 量一遍各行的"布局位置"（先把 transform 清掉，免得量到动画中途的
   位置），Vue 重排之后按差量给**没在拖的那些行**补一段 transform 过渡 ⇒ 它们平滑滑到新位置。 */
function _measureTops(){
  const out = {};
  document.querySelectorAll("#list .item").forEach(el => {
    if (_pdrag && el.dataset.id === _pdrag.id) return;   // 被拖的那行不动它
    el.style.transition = ""; el.style.transform = "";
    out[el.dataset.id] = el.getBoundingClientRect().top;
  });
  return out;
}
function _flipAnimate(before){
  document.querySelectorAll("#list .item").forEach(el => {
    const id = el.dataset.id;
    if (_pdrag && id === _pdrag.id) return;            // 被拖的那行单独跟手，不参与
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
/* 被拖那行：**严格**贴到指针的 y（中心对齐）并放大一点。 */
function _followDrag(clientY){
  if (!_pdrag) return;
  const el = document.querySelector('#list .item[data-id="' + _pdrag.id + '"]');
  if (!el) return;
  el.style.transform = "none";                         // 先复位，量它自己的布局位置（不含 transform）
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
  setTimeout(() => { _listDragging = false; }, 0);     // 让紧随其后的那次 click 被忽略
}
function _onDragMove(e){
  if (!_pdrag || e.pointerId !== _pdrag.pid) return;
  if (!_pdrag.moved){
    if (Math.abs(e.clientY - _pdrag.y0) < 4) return;   // 阈值：小于它算"点"，不算"拖"
    _pdrag.moved = true; _listDragging = true;
    LISTDR.dragId = _pdrag.id;
    try{ document.body.style.userSelect = "none"; }catch(_){}
    _dragLog("开始拖 " + _pdrag.id + "(" + _nm(_pdrag.id) + ")");
  }
  e.preventDefault();
  const before = _measureTops();                       // 量位置（顺带清掉上一次的过渡）
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
    // ★ 整行都能拖（不只那个小把手 —— 把手太小容易抓错行）；行尾「运行 / 停止」按钮除外。
    if (e.target.closest && e.target.closest("button")) return;
    // ★ 认"按的是哪一行"用**坐标**（`clientY` 落在哪一行的 rect 里），**不用 `e.target`** ——
    //   实测 WebView2 的命中测试会错位（点在 y=442，`e.target` 却是第 21 行 y=1294 那个），
    //   而落点/重排本来就是按坐标算的（见 `_reorderLive`）。两者统一。
    const item = _rowAtY(e.clientY) || (e.target.closest && e.target.closest(".item"));
    if (!item) return;
    // ★ 这里**不** `preventDefault()`：整行可拖以后，那样会把"点一下 = 选中"也一起挡掉。
    //   文本选择改到"真正开始拖"那一刻再禁（见 `_onDragMove`）。
    // ★ **不用 `setPointerCapture`**：move/up 已经挂在 `document` 上了，够用；而捕获一旦
    //   泄漏（某次没释放），后续你在任何地方按下，事件都会被重定向给上一次那个元素
    //   —— 那正是"按下 y=445、目标行却在 1294"的怪现象。
    _finalizeDrag();                                 // 万一上次没收干净，先收
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
    // ★ move / up 挂在 **document** 上：拖到列表外面（比如拖到最顶上）松手也接得住 ——
    //   挂在 `#list` 上时，"在列表外松手"会让拖动状态永远清不掉，下一次就"拖 A 结果 B 动"。
    document.addEventListener("pointermove", _onDragMove);
    document.addEventListener("pointerup", _onDragEnd);
    document.addEventListener("pointercancel", _onDragEnd);
  });
}
try{ initListDrag(); }catch(e){}

function renderList(){
  // 门面：原来的调用点（drop.js / files.js / app.js / select …）照旧调它
  // ★ `V-81`：举牌的同时告诉组件"包表回来了没有" —— 没回来就**先别画**（`rows` 里挡着），
  //   否则页面加载那一刻 `DATA` 还是 null，`DATA.packages` 会抛错。
  LISTR.ready = !!(DATA && DATA.packages);
  bumpLists();
  // `V-199`：插件那份数（按钮上那个数字）跟着一起更新
  try{ paintSwitchCounts(); }catch(e){}
  // ★ Vue 是异步渲染：状态那一小块（行尾图标）等这一帧画完再填 —— 原来这里是同步调的，
  //   已确认没有任何调用方在 renderList() 之后**同步**读 `.item`，所以放到 nextTick 是安全的。
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
function iconHTML(p, cls){
  if (p.icon_svg){ const s = safeSvg(p.icon_svg); if (s) return '<span class="' + cls + '">' + s + '</span>'; }
  if (p.icon) return '<span class="' + cls + '"><img src="' + p.icon + '" alt=""></span>';
  return '<span class="' + cls + '"></span>';
}
function pkgRel(p){
  return relOfDir(p && p.dir);
}
/* 包目录 → 页面用的 rel（`user/...` / `system/...`；不在两个根里回 null）。
   ★ `V-355`：更名跟随要拿**改名前的目录**算旧 rel，而那时手上只有一条路径字符串
     （包里那个对象已经跟着旧 id 一起没了）—— 所以这一段单独抽出来。 */
function relOfDir(dir){
  const norm = s => String(s || "").replace(/\\/g, "/").replace(/\/+$/, "");
  const d = norm(dir), userd = norm(DATA.user_data), sysroot = norm(DATA.home) + "/system";
  if (!d) return null;
  if (d === userd || d.startsWith(userd + "/")) return "user" + d.slice(userd.length);
  if (d === sysroot || d.startsWith(sysroot + "/")) return "system" + d.slice(sysroot.length);
  return null;
}
/* 「层」那颗徽章：平时显示 `user 层` / `system 层`，**鼠标悬停（或键盘聚焦）时原地变成**
   `→ system` / `→ user`，点一下就把这个包的整个目录搬到另一层（走宿主 `moss --layer`）。

   ★ 为什么长这样（而不是在旁边多一颗常驻按钮）：层是**属性**，平时只需要看见；
     想改的时候手正好在它上面，不用去别处找。
   ★ 为什么用 inline-grid 把两段文案叠在同一个格子里：徽章宽度取两者的最大值，
     所以悬停时**不会把后面那几颗徽章挤得跳一下**（细节：`.dp-layer` 在 detail.css 里）。
   ★ ★ 为什么**整颗徽章就是按钮**（不是徽章里套一颗小按钮）：一开始套的是小按钮，
     而两段文案里"→ user"比"system 层"窄 ⇒ 悬停后徽章两侧留着**点不动的死区**，
     手偏一点就"点了没反应"（`system → user` 这个方向特别容易踩，因为 `system 层`
     比 `→ user` 宽得多）。现在 `<button>` 就是那颗药丸，整个面积都能点。
   ★ `p.shadowed` = 这个包正压着另一层的同名包 ⇒ 搬过去必然撞车，按钮就置灰并说明原因。 */
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
/* `keepTab`：只把它选上（右边那颗「运行/停止」跟着它），但**不把人拽去「详情」**——
   列表里直接点「运行」时用（不然"我就点一下跑，结果跳走了"）。 */
function select(id, keepTab){
  cur = DATA.packages.find(p => p.id === id) || null;
  curH = null;                                // 选了包就把"历史那条"放下（两者互斥）
  consoleKey = cur ? cur.id : "__host__";     // 命令行跟着换成"这个包自己的那份"
  renderList(); renderHist(); renderDetail(); paintConsole();
  if (!keepTab) setTab("detail");
  // 换了包 → 文件管理跟着换到"这个包的那一套"（每个包一份上下文，互不干扰）
  if (cur) fmSelect(cur.id, /*keepTab*/ true);
  paintEmbedTab();                            // 第四个选项卡：这个包有没有界面
}
function renderDetailHTML(){
  const who = selObj();
  if (!who) return '<div class="empty">左边选一个包，或者一条历史</div>';
  if (isHist(who)) return renderDetailHistHTML(who);
  const p = cur, params = p.params || [];
  const prop = (k, v) => '<div class="dp-prop"><span class="prop-k">' + esc(k) +
    '</span><span class="prop-v">' + v + '</span></div>';
  // ★ `V-359`/`V-360`：整页按你给的那份稿子（**像素级**）——
  //   卡片 1 基础信息：图标 / 名字 + 徽章 / 说明 / 分隔线 / 路径栏 / 属性区。
  //   ★ `.dmeta` 那个类**必须留着**（里面有 `:包id`）—— `sync-run` 场景拿它认"选中的是谁"。
  const dirText = String(p.dir || "");
  let html = '<div class="dwrap"><div class="dp-card dp-head">' +
      '<div class="dp-icon">' + (iconHTML(p, "") || ico("puzzle", "i")) + '</div>' +
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
        // 路径栏（稿子的 .path-display）：包的目录 + 复制 + 打开目录
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

  // 属性区（稿子的 .props-grid）：别名 / 标签 / AI / 参数
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
  // 参数：稿子就是"参数 <名字>"当标签、`类型 + 「可留空」徽章`当值，
  // **示例和说明都进那格的提示气泡**（稿子：`data-tip="示例: 要重复的内容"`）
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
  // 目录名和 id 不一样（`D-27` 方案 C）：不报错，只摆出来 + 给个一键统一
  const dirBase = (String(p.dir || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop()) || "";
  const oddDir = dirBase && dirBase !== p.id;
  if (oddDir)
    props.push(prop("目录名", '<span class="mono">' + esc(dirBase) + '</span>' +
      '<span class="soft">· 与 id 不同（右边可以一键统一）</span>'));
  if (props.length)
    html += '<div class="dp-props">' + props.join("") + '</div>';
  html += '</div></div>';

  // ★ 卡片 2：快捷执行（稿子的 .cmd-bar：图标 + 前缀 + 参数框 + 主动作按钮）
  html += '<div class="dp-card"><div class="dp-cmdbar">' +
      '<span class="dp-cmd-ico">' + ico("terminal", "i") + '</span>' +
      '<span class="dp-cmd-prefix">moss ' + esc(PSYM + p.id) + '</span>' +
      // ★ 参数框右边那颗"一键清空"（`V-86`，你要的）：**有内容时才浮出来**，
      //   悬浮在框内右侧（`.argbox` 定位），点一下清空并把光标留在框里。
      '<span class="argbox">' +
        '<input id="args" placeholder="点击输入附加参数并回车执行..." value="' +
          esc(ARGS[p.id] || "") + '">' +
        '<button class="argclear" id="btn-args-clear" title="清空参数" hidden>' +
          ico("x", "i") + '</button>' +
      '</span>' +
      // ★ 主动作那颗改成**分离式下拉按钮**（照用户给的那份稿子）：
      //   主按钮 = 运行 / 停止（和右上角那颗同一个状态），不常用的「新窗口运行」
      //   收进右边箭头的下拉里。用户原话：「大多数情况下，还是运行用的多，新窗口用的少」。
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
    // 稿子这条命令栏本身就是"命令预览"，所以这里只在 DOM 里留一个不占地方的钩子
    '<span hidden id="preview"></span>';
  // 例子：稿子把它们放进"参数"那格的提示气泡里了（见上面 data-tip），
  // 这里另外给一排可点的药丸 **只在有例子时**出现（稿子没有这一块，默认不占版面）
  const exs = (p.examples || []).map(x => String(x || "")).filter(x => x.trim());
  if (exs.length){
    html += '<div class="dp-hint">常用的参数（点一下填进上面的框）：<span class="chips">' +
      exs.map(e => '<button class="chip" data-args="' + esc(e) + '">' + esc(e) +
        '</button>').join("") + '</span></div>';
  }
  html += '</div>';

  // ★ `V-388`：**使用说明**（`pkg.json` 的 `docs.readme`）。
  //   宿主把文件读成文本塞进 payload（界面不读盘，见 `core/ui.py` 的 `_docs_of`）；
  //   以前这个字段只躺在 payload 里没人渲染，于是像 `pip` 那种"一句话 desc +
  //   没参数"的包，详情页**一个字的使用方法都没有**（用户报的）。
  //   用原生 `<details open>`：默认展开、点标题就能收起，不用加任何 JS 绑定。
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

  // ★ 卡片 4：高级设置（稿子把"更名 / 开机自动运行 / 卸载"收成一张卡的三行）
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
      // ★ `V-358`：**自动启动**（你定的：这一块放"详情"里，不放设置里）——
      //   加入 / 看状态 / 改参数 / 删除都在这儿，见 `js/autostart.js`。
      autoSectionHTML("pkg", p.id, {}) +
      // ★ `V-379`：**寄生模式**（你 2026-10-10 定的名字）—— 点它就运行、切到别的插件自动停。
      //   和上面「自动运行」同一张卡、同一套壳，见 `js/parasite.js`。
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

/* ---------------------------------------------------------------- 详情页：那颗"运行 / 新窗口运行"
   分离式下拉按钮（照用户给的那份稿子）。主按钮是**常用**的运行/停止，右边箭头里收着
   不常用的「新窗口运行」。用户原话：「大多数情况下，还是运行用的多，新窗口用的少」。
   ★ 菜单是绝对定位 + 显隐 class（和稿子一样），重画时 DOM 会整个换掉 ⇒ 默认就是收着的。 */
function runSplitMenu(show){
  const menu = $("#run-split-menu"), grp = $("#run-split");
  if (!menu || !grp) return;
  const want = (show === undefined) ? !menu.classList.contains("show") : !!show;
  menu.classList.toggle("show", want);
  grp.classList.toggle("open", want);
}
function runSplitClose(){ runSplitMenu(false); }
/* 点空白处 / 按 Esc 收起：**只装一次**（wireDetail 每次重画都会跑，不能在那儿挂） */
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
/* 详情页的接线（把那些 id 找出来绑处理器）—— 每次重画之后跑一遍，
   内容与改造前**逐行一致**，只是不再依赖那个局部 box 变量。 */
function wireDetail(){
  const who = selObj();
  if (!who) return;
  if (isHist(who)) return wireDetailHist(who);
  const p = cur;
  // ★ `V-81` 修：详情页搬进组件的时候，原来那个局部变量 `box` 被弄丢了 —— 下面找
  //   `.chip` 那一行会抛 `ReferenceError: box is not defined`，**它后面那一串按钮就全都
  //   没绑上**（运行 / 停止 / 新窗口运行 / 更名 / 卸载，一个都点不动）。
  //   而 Vue 默认把组件里的异常只写进控制台（这个界面没有控制台）⇒ 界面上一个字都不报，
  //   看着就是"更名和卸载坏了"。（同一条根因现在会走 `reportError` 报出来。）
  const box = $("#pane-detail");
  const host = box;
  // ★ 每个 rev 只接一次线（`V-80`）：v-html 的内容没变时 Vue 不会重设 innerHTML，
  //   这时候再绑一遍监听器就会**重复**（回车跑两次那种）。
  if (host && host.dataset.wiredRev === String(DETAILR.rev)) return;
  if (host) host.dataset.wiredRev = String(DETAILR.rev);
  const aclr = $("#btn-args-clear");            // 参数框右边那颗"一键清空"（`V-86`）
  const upd = () => {
    $("#preview").textContent = "moss " + PSYM + p.id +
      ($("#args").value.trim() ? " " + $("#args").value.trim() : "");
    ARGS[p.id] = $("#args").value;              // 记住它，重画之后要放回去
    if (aclr) aclr.hidden = !$("#args").value;  // 有内容才浮出来
  };
  if (aclr) aclr.onclick = () => {
    $("#args").value = "";
    upd();
    $("#args").focus();                         // 清完光标留在框里，接着就能打字
  };
  $("#args").addEventListener("input", upd);
  $("#args").addEventListener("keydown", (e) => {
    if (e.key === "Enter"){ e.preventDefault(); startRun(p, $("#args").value); }
  });
  upd();
  // 例子：现在是真的 <button class="chip" data-args="…">（以前是 span 加个 .click 类）
  box.querySelectorAll(".chip[data-args]").forEach(c => {
    c.onclick = () => { $("#args").value = c.dataset.args || ""; upd(); };
  });
  // 那组按钮现在钉在选项卡行上（paintActions 管），这里只挂钩子。
  // ★ 只用绑一次：上一版遗留的那段老处理函数（先 disabled=true 再调阻塞式 run）
  //   还留在下面，正好把这一行覆盖掉 —— 表现就是"停止按钮是灰的、点了没反应"。
  paintActions(p);
  $("#btn-run").onclick = () => clickRun(p);
  $("#btn-vis").onclick = () => toggleVis(p);
  refreshPkgState(p);
  // ★ 分离式按钮：主按钮 = 运行 / 停止（走右上角那颗同一套逻辑），
  //   箭头展开下拉，里面是**不常用**的「新窗口运行」（原来的 open_ui）。
  $("#btn-runsplit").onclick = () => { runSplitClose(); clickRun(p); };
  $("#btn-split-arrow").onclick = (ev) => { ev.stopPropagation(); runSplitMenu(); };
  $("#btn-run-newwin").onclick = async () => {
    runSplitClose();
    const r = await pywebview.api.open_ui(p.id, $("#args").value);
    if (r && r.ok === false) toast(r.msg || "启动失败", true);
    // 不切选项卡：带界面的包本来就没有命令行输出，停在详情更合理
    paintRowStats();
    setTimeout(() => refreshPkgState(p), 1500);
    setTimeout(() => refreshPkgState(p), 3500);
  };
  $("#btn-remove").onclick = () => cmdRemovePkg(p);
  $("#btn-rename").onclick = () => cmdRenamePkg(p);
  if ($("#btn-align")) $("#btn-align").onclick = () => cmdAlignPkgDir(p);
  // ★ `V-359`（稿子新增的路径栏那两颗）：复制路径 / 打开目录。
  if ($("#btn-copy-dir")) $("#btn-copy-dir").onclick = () => copyDirPath(p.dir);
  // ★ 「层」徽章上那颗悬停才露出来的按钮：把包在 user / system 之间搬（宿主 `moss --layer`）。
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
  autoWire("pkg", p.id, {});          // ★ `V-358`：自动启动那一块（见 js/autostart.js）
  parasiteWire(p.id);                 // ★ `V-379`：寄生模式那一行（见 js/parasite.js）
}

/* 复制一条路径到剪贴板（`V-359`，稿子里路径栏那颗按钮）。
   ★ 为什么要有兜底：`navigator.clipboard` 只在**安全上下文**里有（这一页是
     `http://127.0.0.1:端口` + token，算安全上下文），但预览工具那边是 `file://`
     / 临时副本，未必给。拿不到就照实说一句，别静默失败。 */
async function copyDirPath(text){
  const s = String(text || "");
  if (!s){ toast("没有可复制的路径", true); return; }
  try{
    if (navigator.clipboard && navigator.clipboard.writeText){
      await navigator.clipboard.writeText(s);
      toast("已复制：" + s);
      return;
    }
  }catch(e){ /* 落到下面那句 */ }
  toast("复制不了，路径：" + s, true);
}


/* 对齐目录名：把包目录名改成它的 id（`D-27` 方案 C 里那个"一键统一"）。
   走的还是宿主那条 `--rename`，只是新旧 id 都写成它现在的 id —— 于是宿主
   只改目录名，**id / 数据目录 / 清单一个字都不动**。 */
async function cmdAlignPkgDir(p){
  const oldRel = pkgRel(p);              // 改名前后 id 不变，只有目录名变
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
  // ★ 目录名换了（id 没换）—— 文件管理缓存里那条路径**还是旧目录**，
  //   不搬的话双击一个文件去编辑，宿主会说「不是文件」。这条正是这个 bug 的现场。
  await refreshPkgs(p.id);
  const np = DATA.packages.find(x => x.id === p.id);
  fmReRoot(oldRel, np ? pkgRel(np) : null);
  if (np) select(p.id);
  else renderDetail();
}

/* 换层：把包的**整个目录**在 `user_data/pkgs` ↔ `system/pkgs` 之间挪一下。
   规则（目录名 / id / 数据目录 / 短命令 / 同名遮蔽）只有宿主那侧知道 ⇒ 走 `moss --layer`，
   界面**不自己拼两条路径去搬**（那正是 `D-27` 那批毛病的来源）。
   ★ 数据目录按 id 算（`user_data/state/<id>`），**不跟着层走** —— 换层不该让 AI 会话 /
     运行数据"凭空没了"，所以文案里明说它不动。 */
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
      const oldRel = pkgRel(p);                  // 搬家前的目录（文件管理缓存里记的是它）
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
      await refreshPkgs(p.id);                   // 包表重问一遍（层的归属变了）
      const np = DATA.packages.find(x => x.id === p.id);
      fmReRoot(oldRel, np ? pkgRel(np) : null);  // 文件管理里那条路径跟着搬
      if (np) select(p.id); else renderDetail();
      toast("已挪到 " + to + " 层" +
            (to === "system" ? "（升级时会被整体替换，想留住就再搬回 user）" : ""));
     }});
}

/* 更名：界面只负责问"改成什么"，改的事交给宿主（`moss --rename`）。
   为什么不自己改：一次要动**包目录名 / 数据目录 / 清单里的 id** 三样，
   这套规则只有宿主那侧知道；界面自己拼路径，正是 `D-27` 里那几处毛病的来源。 */
async function cmdRenamePkg(p){
  askText("给这个包改名", p.id, async (newId) => {
    newId = String(newId || "").trim().toLowerCase();
    if (!newId || newId === p.id) return;
    const oldRel = pkgRel(p);            // 改名前它那个目录（文件管理缓存里记的就是它）
    // ★ `V-378`：**旧 id 也必须在交给宿主之前先记下来**（和 `oldRel` 一个道理）——
    //   宿主那条 `--rename` 跑完，手里这个包对象可能已经不是旧 id 了（预览那个假宿主就是
    //   当场 `p.id = 新 id`；真宿主这边 `refreshPkgs` 也会换掉包表）。
    //   不记的话，下面那句 `pkgFollowId(p.id, newId)` 会变成"新→新"，被它自己那句
    //   `oldId === newId` 挡掉，**一声不响地什么都不搬**。
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
    // ★ `V-378`：**按 id 记的那几样跟着搬**（参数框的字 / 运行缓冲 / 命令行那块屏的主人 /
    //   自动运行那份名单）—— 和"别的进程改名被轮询到"那条路共用同一个函数，见 `pkgFollowId`。
    await pkgFollowId(oldId, newId);
    // ★ `V-367`：这里以前先弹一句「已改名为 x」，函数末尾又弹一句（带"显示名里的旧名字
    //   也一起换了"）—— 一个动作两颗胶囊，说的还是同一件事。**只在末尾说一次**。
    // ★ `V-89` / `V-384`：备份库里那个**分组文件夹**跟着改名 —— 必须用 **`oldId`**。
    //   以前这儿传的是 `p.id`：改完名之后那个包对象随时可能被换成新 id，于是这句变成
    //   "新→新"，`rename_group` 一看名字没变就什么都不搬。后果是你 2026-10-19 报的
    //   "还是没有在开工前自动创建镜像"：快照明明存了，却还记在旧 id 那个分组里，
    //   界面按新 id 去问 ⇒ 一片空白。改名失败不影响主流程，只 console 说一声。
    try{
      const br = await pywebview.api.backup_rename_group(oldId, newId);
      if (br && br.ok && br.renamed) console.info("备份分组已改名：" + (br.msg || ""));
      else if (br && !br.ok) console.warn("备份分组没改成：" + (br.msg || ""));
    }catch(e){ console.warn("备份分组没改成：", e); }
    // ★ 目录整个换了地方，文件管理里缓存的路径（当前目录 / 历史 / 打开的文件）
    //   必须跟着搬 —— 否则双击一个文件去编辑，宿主会说「不是文件」。
    await refreshPkgs(newId);            // 包表重问一遍（旧 id 没了、新 id 出现）
    const np = DATA.packages.find(x => x.id === newId);
    fmReRoot(oldRel, np ? pkgRel(np) : null);
    if (np) select(newId);
    else renderDetail();
    // ★ `V-357`：清单里那几样（`id` / 显示名里那个旧 id / 别名）**都是宿主改的**
    //   （`core/cli.py::cmd_rename` 第 ③ 步，一次落笔）—— 界面不再自己写一遍 pkg.json，
    //   免得同一个文件两个人写（你定的"别名和 id 一致"也归那一步管）。
    // ★ `V-384`：**改完名直接进新包、进它的 AI 对话**（你 2026-10-19 报的：
    //   "它使用了更改标识符以后 没有自动进入到新的包 并自动进入AI对话"）。
    if (np) await followIntoAi(newId);
    toast("已改名为 " + PSYM + newId + "（显示名里的旧名字也一起换了）");
  });
}

/* ★ `V-384`：改名之后"接着聊"那一步 —— 新包里要是有 AI 会话，就切到 AI 页把它接上。
   ★ 判据为什么是"有没有会话"而不是无脑切：给一个从没用过 AI 的包改名，不该把人从
     文件管理硬拽到 AI 页去。 */
async function followIntoAi(id){
  try{
    if (typeof aiLoadRuns !== "function") return false;
    await aiLoadRuns();                                  // 这一步里 `aiAdoptLast` 会把会话接上
    const A = window.__AIR || {};
    if (!(A.runs || []).length) return false;
    if (typeof setTab === "function") setTab("ai");
    return true;
  }catch(e){ return false; }
}

/* ---------------------------------------------------------------- 更名跟随（`V-355`）
   用户原话：「如果用户对当前打开的界面 不存在了 对不上了 但是出现了一个新的 id 那基本
   就能判断是它改名了 …… 当然如果你有更精准的办法更好了」。
   判据在**宿主**那边（`Api.pkg_watch`）：① 身份指纹一致 = 铁定改名；② 一个走一个来 =
   按新旧 id 推断。这里只管"跟着走"：换选中、搬文件管理缓存的路径、把内嵌界面按新 id
   重新起起来 —— 也就是你要的"自动无感刷新"。
   ★ 为什么由界面自己轮询（2.5 秒一次）：改名是**别的进程**干的（AI 工作台那条 `run_moss`、
   你在终端里敲的 `moss --rename`），界面这边没有任何回调可听。 */
/* ★ `V-378`：改名时要跟着搬的**那些按 id 记的东西** + 自动运行那份名单。
   ★ 为什么收成一个函数、**两条改名路都调它**：改名有两条路 ——
     ① 界面上点「更名」（`cmdRenamePkg`）；② 别的进程改名、2.5 秒轮询到（`pkgWatchTick` → `followRename`）。
     以前只有 ② 搬了 `ARGS` / `RUNS` / `consoleKey` ⇒ **在界面里改名**那几样全留在旧 id 上
     （详情页参数框里刚敲的字没了、命令行那块屏认不出主人、正在跑的包状态也对不上）；
     而**自动运行那份名单两条路都没搬** ⇒ 那个包改完名之后开机跑不起来（只报"找不到这个包"）、
     详情页又看不见它（那一块按 id 找 ⇒ 显示"还没加入"），只能删掉重加。放一处，两条路一起对。 */
async function pkgFollowId(oldId, newId){
  if (!oldId || !newId || oldId === newId) return;
  if (ARGS[oldId] !== undefined){ ARGS[newId] = ARGS[oldId]; delete ARGS[oldId]; }
  if (RUNS[oldId]){ RUNS[newId] = RUNS[oldId]; delete RUNS[oldId]; }
  if (consoleKey === oldId) consoleKey = newId;
  try{ await autoRename(oldId, newId); }catch(e){ /* 搬不动也不该拦住改名这条路 */ }
  // ★ `V-379`：**寄生模式那份名单也是按包 id 记的** —— 一起搬（`js/parasite.js`）。
  try{ await parasiteRename(oldId, newId); }catch(e){ /* 同上 */ }
}

let renameTimer = null;
let renameTickBusy = false;

function pkgWatchStart(){
  if (renameTimer || FLOAT_PID) return;      // 浮动窗口：只要那一帧，不掺和这些
  renameTimer = setInterval(pkgWatchTick, 2500);
  setTimeout(pkgWatchTick, 900);             // 开机先对一次（把宿主那份基线立起来）
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

/* 一个包改名了 —— 跟着它走（把"打开着的那个"换成新名字）。 */
async function followRename(oldId, newId, how, oldDir){
  if (!oldId || !newId || oldId === newId) return;
  const wasOpen = !!(cur && cur.id === oldId);
  const oldRel = relOfDir(oldDir) || (wasOpen ? pkgRel(cur) : null);
  // 按 id 记的那几样（参数框 / 运行缓冲 / 命令行那块屏 / 自动运行名单）统一在 `pkgFollowId` 里搬
  await pkgFollowId(oldId, newId);
  // ★ `V-384`：备份分组也跟过来（命令行 / AI 那边改的名，以前这条路**没搬**）。
  //   不搬的话：快照还在旧 id 那个分组里，界面按新 id 问 ⇒ "退路"看起来凭空没了。
  try{
    const br = await pywebview.api.backup_rename_group(oldId, newId);
    if (br && !br.ok) console.warn("备份分组没改成：" + (br.msg || ""));
  }catch(e){ console.warn("备份分组没改成：", e); }
  // 内嵌界面的后端是**按旧 id** 起的：目录都搬走了 ⇒ 停掉，改完名按新 id 再起起来
  const hadEmbed = (typeof embedRunning === "function") && embedRunning(oldId);
  if (hadEmbed) await embedStop(oldId, true);
  await refreshPkgs(newId);
  const np = (DATA.packages || []).find(x => x.id === newId);
  if (oldRel && np) fmReRoot(oldRel, pkgRel(np));
  if (wasOpen && np){
    select(newId, /*keepTab*/ true);         // 人正开着它 ⇒ 换成新名字，不切走他那一页
    if (hadEmbed && embedSupported(np)) await embedOpen(np, {keepTab: true});
    // ★ `V-384`：它有一条 AI 会话的话，接上去（人接着聊的是同一件事，别看空页）
    await followIntoAi(newId);
  }
  // ★ `V-367`：不再回显宿主那条判据（`how` = "指纹一致" / "按新旧 id 推断"）——
  //   那是**它是怎么认出来的**，属于内部机制；用户要知道的只有"跟着改了"。
  toast("已跟随改名：" + PSYM + oldId + " → " + PSYM + newId);
}

/* 打开着的那个包**真没了**（卸载 / 目录被删）—— 别把一张死页留在界面上。 */
async function followGone(ids){
  const wasOpen = !!(cur && ids.some(x => x === cur.id));
  await refreshPkgs(null, true);       // `refreshPkgs` 自己会把 `cur` 收成 null
  const names = ids.map(x => PSYM + x).join("、");
  if (wasOpen) toast("这个包已经不在了：" + names, true);
  else toast("有包不在了：" + names);
}

/* ---------------------------------------------------------------- 详情：一条历史
   和包那份**同一个骨架**（`V-359` 起都按你给的那份稿子：卡片 1 基础信息 / 卡片 2 快捷
   执行 / 卡片 3 高级设置），内容按"这条记录真有什么"来给 —— **没有的就不显示**
   （参数空着不写"参数（无）"，上次结果不知道就不写；说明性的废话也不写）。 */
function renderDetailHistHTML(it){
  const when = (it.ts || "").replace("T", " ");
  const gone = it.exists === false;
  const prop = (k, v) => '<div class="dp-prop"><span class="prop-k">' + esc(k) +
    '</span><span class="prop-v">' + v + '</span></div>';
  // 只放"真有值"的行；一行都没有，这一块就不出现
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
      // ★ 这里用 `#hargs` / `#hpreview`（而不是包详情那对 `#args` / `#preview`）：
      //   两个详情同一个时刻只会存在一个（都往 #pane-detail 里写），
      //   但静态检查"整个页面每个 id 只能出现一次"就分不清了 —— 换成不同的 id，
      //   那条检查才继续有用。要取输入框请走 `argsInput()`。
      '<span class="argbox">' +
        '<input id="hargs" placeholder="点击输入附加参数并回车执行..." value="' +
          esc(it.args || "") + '"' + (gone ? " disabled" : "") + '>' +
        // 和包详情那颗一样（`V-86`）：有内容才浮出来 —— 目标没了的这条禁用着，就不给
        '<button class="argclear" id="btn-hargs-clear" title="清空参数" hidden>' +
          ico("x", "i") + '</button>' +
      '</span>' +
      '<button class="dp-primary" id="btn-run2"' + (gone ? " disabled" : "") + '>' +
        ico("play", "i") + '<span>运行</span></button>' +
    '</div><span hidden id="hpreview"></span></div>';
  // ★ `V-358`：这条历史也能"自动启动"（开界面时按它当初的目录 / 参数再跑一次）——
  //   和包详情那一块同一份实现（`js/autostart.js`）。
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

/* 历史详情的接线 —— 同上，逐行搬运。 */
function wireDetailHist(it){
  const host = $("#pane-detail");
  if (host && host.dataset.wiredRev === String(DETAILR.rev)) return;
  if (host) host.dataset.wiredRev = String(DETAILR.rev);
  const inp = $("#hargs"), aclr = $("#btn-hargs-clear");   // 清空那颗（`V-86`）
  const upd = () => {
    const a = inp.value.trim();
    // 和宿主 `rerun_argv` 同一条规则的**近似预览**：真正跑的时候宿主回回来的 `cmd`
    // 才是准的（会打到「命令行」上）。这里只求"看着像手敲的那条"。
    $("#hpreview").textContent = "moss /" + it.name + (a ? " " + a : "");
    // 有内容才浮出来；目标已经不在（输入框禁用）的那条不给
    if (aclr) aclr.hidden = !inp.value || inp.disabled;
  };
  if (aclr) aclr.onclick = () => {
    inp.value = "";
    upd();
    if (!inp.disabled) inp.focus();             // 清完光标留在框里
  };
  $("#hargs").addEventListener("input", upd);
  $("#hargs").addEventListener("keydown", (e) => {
    if (e.key === "Enter"){ e.preventDefault(); rerunHist(it, $("#hargs").value); }
  });
  upd();

  paintActions(it);
  $("#btn-run").onclick = () => clickRun(it);
  $("#btn-vis").onclick = () => {};            // 已禁用；留个空钩子不放旧的包 handler
  $("#btn-run2").onclick = () => rerunHist(it, $("#hargs").value);
  $("#btn-opendir").onclick = () => {
    pywebview.api.fs_open_default(histDir(it)).then(r => toast(r.msg, !r.ok));
  };
  $("#btn-forget").onclick = () => cmdForgetHist(it);
  // ★ `V-359`（稿子新增的路径栏那两颗）—— 历史这条：复制的是目标路径
  if ($("#btn-copy-dir")) $("#btn-copy-dir").onclick = () => copyDirPath(it.target);
  // ★ `V-358`：自动启动那一块。历史那条的"身份"是**目标路径**（`it.target`），
  //   目录和名字一并传过去 —— 加入时它们要存进条目里（跑的时候要用）。
  autoWire("hist", it.target, {cwd: it.cwd || "", name: it.name || "",
                               args: it.args || ""});
}

/* 老签名保留：想往指定的 box 里塞还能用（谁在用就照旧）。 */
function renderDetailHist(it, box){
  const html = renderDetailHistHTML(it);
  if (box) box.innerHTML = html;
  wireDetailHist(it);
}


/* 删一条历史记录：**真删** —— 把那几行从账里抠掉（原地改、保留行尾）。
   ★ **不弹确认框**：这里碰不到任何文件，弹窗只会拖慢一次清理动作。
     这里也确实碰不到任何文件：只动 `user_data/history/*.jsonl` 里那几行。
     （包那边的「卸载」是**真删文件**，确认框保留。）
   ★ 为什么不做成"追加一条墓碑、读的时候跳过"：那样"能不能跳过"取决于读的人那份代码
     认不认墓碑 —— 终端里的 `moss --history` 跑的是**编在 exe 里的** `core/history.py`，
     旧 exe 不认识，于是"界面里删了、终端里还在"。所以删除做成真删。 */
async function cmdForgetHist(it){
  // ★ 要传**记录自己的去重键**（`it.key`，后端按 `kind|目标|params|args` 匹配），
  //   不能传 `histKey(it)` —— 那是界面这边"控制台缓冲区"的键（`hist:<目标> <args>`），
  //   两边格式不同，传错了后端就一条也匹配不到，只会回"已经没有这条了"。
  const r = await pywebview.api.hist_forget(it.key || "");
  toast(r.ok ? ("已删掉这条记录：" + it.name) : ("✗ " + (r.msg || "删不掉")), !r.ok);
  if (!r.ok) return;
  if (curH && histKey(curH) === histKey(it)) curH = null;
  await loadHist();
  renderHist();
  renderDetail();
}


/* ================================================================ 左侧两个列表（Vue 组件，`V-79`）
   为什么拆这两个：它们是"左侧那一栏"的全部，改坏了最显眼、也最好验（有没有 19 个包、能不能点）。
   ★ 行内容仍然用**一次 innerHTML** 画（`v-html`）—— 这样 DOM 结构与类名跟改造前**逐字节一致**，
     预览场景（按选择器断言）与 `paintRowStats()` / `paintHistStats()`（按 `.rowstat` / `.hstat` 找元素）
     都照旧работа。①*/
const MossList = {
  name: "moss-list",
  data(){ return { R: LISTR, L: LISTDR }; },
  computed: {
    rows(){
      this.R.rev;                                  // 登记依赖：谁举牌就重算
      // ★ `V-81`：组件是**页面加载那一刻**就挂上的，而包表要等 `init()` 里
      //   `await pywebview.api.state()` 回来才有 —— 中间这段时间 `DATA` 还是 `null`。
      //   不在这儿挡一下，`DATA.packages` 就是一抛（`Proxy.rows … Cannot read
      //   properties of null (reading 'packages')`，你从 devtools 里看到的就是它）。
      //   挡法不是"判空返回 []"（那样启动一瞬间会闪一句"没有匹配的包"），
      //   而是**数据没回来就先不画**（`ready` 由 `renderList()` 举牌时一起给）。
      if (!this.R.ready) return [];
      const f = $("#q").value.trim().toLowerCase();
      const all = DATA.packages.filter(p => !f ||
        [p.id, p.name, p.desc, (p.tags||[]).join(" "), (p.aliases||[]).join(" ")]
          .join(" ").toLowerCase().includes(f));
      // `V-178`：工具条的分类（全部 / 系统 / 用户）
      const byLayer = this.R.filt === "all" ? all : all.filter(p => p.layer === this.R.filt);
      // `V-178`：工具条的排序（名字 / 加入时间 / 最后运行，都是倒序看得舒服的先大后小）
      const dirName = p => String(p.name || p.id || "").toLowerCase();
      const bornOf = p => this.R.born[(p.dir || "").split(/[\\/]/).pop()] || 0;
      const sortKey = this.R.sort;
      const sorted = byLayer.slice().sort((a, b) => {
        if (sortKey === "custom"){                    // `V-300`：用户拖出来的顺序
          const ia = this.R.custom.indexOf(a.id), ib = this.R.custom.indexOf(b.id);
          const ka = ia < 0 ? 1e9 : ia, kb = ib < 0 ? 1e9 : ib;   // 没记过的新包排最后
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
      // ★ 正拖着东西的时候：**只列收得下它的包**（`V-39`）—— 不支持对应操作的先藏起来
      //   `V-183` 起"收得下"还包括扩展名（拖 .txt 时 :img 不该出现），判断都用 DRAG.items
      //   ★ `V-205`：**拖到内嵌那一帧上时不筛** —— 那一拖是给那个包的界面的，不是"找包"；
      //     列表忽然少一大半会让人以为坏了（实测反馈："左侧去响应了，把不支持的隐藏了"）。
      return (DRAG.on && !DRAG.framePid) ? sorted.filter(p => dropAccepts(p, DRAG.items)) : sorted;
    },
    emptyHTML(){
      // ★ 同 `V-83` 那个坑：`DRAG` 是普通对象（非响应式）—— 不登记 `R.rev` 的话，
      //   开始拖动（列表被筛空）时这句提示不会更新。
      this.R.rev;
      if (DRAG.on && DRAG.framePid) return "没有匹配的包";   // `V-205`：这一拖是给那一帧的，列表没筛
      return DRAG.on
        ? ("没有包收「" + dropKindName(DRAG.kind) + "」" + dropWhyNone(DRAG.items))
        : "没有匹配的包";
    },
  },
  methods: {
    selId(){ return cur ? cur.id : null; },
    stateOf(id){ return rowStateOf(id); },          // 宿主口径：在跑 / 没在跑
    /* ★ `V-366`：这一行在不在**自动运行**那份名单里（`js/autostart.js` 的 `AUTO.items`）。
       ★ 得走方法（模板里读不到全局，`V-252` 的血）；带括号用 ⇒ 不是 computed 也没关系。
       ★ 数据变了要重画列表才会跟着变 —— `autostart.js::autoPaintMarks()` 负责喊那一嗓子。 */
    isAutoRun(id){
      try{ return autoPkgIds().has(String(id)); }catch(e){ return false; }
    },
    rowHTML(p){
      // ★ `V-300`：行首一个把手（`.drag-grip`）—— 视觉提示；其实整行都能拖（见 initListDrag）。
      //   ⚠️ 类名别用 `.grip`（那是"拖我调宽"竖条的全局类，撞名会变一条贯穿竖线）。
      // ★ `V-305`：**不显示简介**了 —— 第二行放"怎么敲它"（`<符号><id>`，符号来自设置、
      //   不是写死的 `:`）。原来那个 id 从第一行的 `.sub` 挪到这儿。
      return '<span class="drag-grip" title="拖动排序">' + ico("grip-vertical", "i") + '</span>' +
        iconHTML(p, "ico") +
        '<div style="min-width:0;flex:1">' +
          '<div class="nm">' + esc(p.name) + '</div>' +
          '<div class="ds">' + esc(PSYM + p.id) + '</div></div>' +
        '<span class="rowstat"></span>';
    },
    pick(id){
      if (_listDragging) return;
      // ★ `V-379`：**寄生模式**要在"你亲手点左边列表"这一刻编排 —— 先抓 `prev`（下面那句
      //   `select()` 会把 `cur` 换成新的），再照旧**同步** `select`（原来多快还是多快），
      //   最后把编排丢到后台（它自己 await 宿主，不该拖住选择那一下）。
      const prev = cur && cur.id;
      select(id);
      parasiteOnPick(id, prev);
    },   // 刚拖完那一下别误选中
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
      this.R.rev;                                  // 同上：举牌就重算
      const f = $("#q").value.trim().toLowerCase();
      const hit = HIST.filter(it => !f ||
        [it.name, it.target, it.args, it.cwd].join(" ").toLowerCase().includes(f));
      // `V-178`：分类（全部 / 路径调用 / 包调用）+ 排序（时间 / 名字 / 类型）
      const kindOf = it => (it.kind === "pkg" || it.kind === "plugin") ? "pkg" : "path";
      const byKind = this.R.hfilt === "all" ? hit : hit.filter(it => kindOf(it) === this.R.hfilt);
      const key = this.R.hsort;
      return byKind.slice().sort((a, b) => {
        if (key === "time" || key === "kind"){          // 时间：新的在前
          const ta = String(a.ts || ""), tb = String(b.ts || "");
          if (ta !== tb) return ta < tb ? 1 : -1;
        }
        const na = String(a.name || "").toLowerCase(), nb = String(b.name || "").toLowerCase();
        return na < nb ? -1 : (na > nb ? 1 : 0);
      });
    },
    emptyHTML(){
      this.R.rev;              // 同上：`HIST` 也是普通数组，得靠举牌信号才会重算
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
    pick(it){ selectHist(it); },                   // 选中，不跑
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


/* ================================================================ 详情页（Vue 组件，`V-80`）
   为什么是"薄组件"：这一页的 DOM 与接线又长又老（`renderDetailHTML` 一次拼出整页、
   `wireDetail` 按 id 绑一堆处理器），**重写成模板的收益抵不上风险**。所以这一步只做一件事：
   把它挪进组件、由状态驱动重画 —— 结构、文案、类名、id、接线全部原样。
   外面照旧调 `renderDetail()`（门面）。 */
const DETAILR = Vue.reactive({rev: 0});
function renderDetail(){ DETAILR.rev++; }

const MossDetail = {
  name: "moss-detail",
  data(){ return { R: DETAILR }; },
  computed: {
    html(){ this.R.rev; return renderDetailHTML(); },   // 登记依赖：谁举牌就重算
  },
  mounted(){ wireDetail(); },
  updated(){ wireDetail(); },
  // `display:contents`：这层壳不参与布局，画面与改造前一致
  template: '<div style="display:contents" v-html="html"></div>',
};
mountVue(MossDetail, "#pane-detail");


/* `V-178`：工具条跟着"插件 / 历史"一起显示/隐藏（挂在 window 上，app.js 里那两个切换按钮顺手调） */
window.syncListBars = function(){
  const pkg = !$("#list").hidden;
  const bl = $("#bar-list"), bh = $("#bar-hist");
  if (bl) bl.hidden = !pkg;
  if (bh) bh.hidden = pkg;
  initListBarsOnce();
};
let _barsDone = false;
function initListBarsOnce(){ if (_barsDone) return; _barsDone = true; try{ initListBars(); }catch(e){} }
