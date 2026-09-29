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
  if (it) rerunHist(it, args);
}

/* 选中一条历史：右边三个选项卡跟着换成"这一条"的。 */
function selectHist(it){
  curH = it; cur = null;
  consoleKey = histKey(it);
  renderList(); renderHist(); renderDetail(); paintConsole();
  setTab("detail");
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
  if (!p){ toast("找不到 :" + lastRun.id + " 这个包了", true); return; }
  if (RUNS[p.id]) return;
  startRun(p, lastRun.args);
}

/* 列表 / 历史的"该重画了"信号（`V-79`）。
   ★ 为什么用举牌而不是把 DATA/HIST 变成响应式：`DATA`/`HIST`/`cur`/`curH`/`side` 都是**别的文件**里的
     普通 `let`（整个被重新赋值），改成响应式要动一圈别的模块；原来的代码本来就在"数据变了"的地方
     显式调 `renderList()` / `renderHist()`，所以**保留那几个函数名当门面**、让它们举牌最省事，
     行为也一字不变（外部调用点一个都不用改）。 */
const LISTR = Vue.reactive({rev: 0, ready: false});
function bumpLists(){ LISTR.rev++; }

function renderList(){
  // 门面：原来的调用点（drop.js / files.js / app.js / select …）照旧调它
  // ★ `V-81`：举牌的同时告诉组件"包表回来了没有" —— 没回来就**先别画**（`rows` 里挡着），
  //   否则页面加载那一刻 `DATA` 还是 null，`DATA.packages` 会抛错。
  LISTR.ready = !!(DATA && DATA.packages);
  bumpLists();
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
  const norm = s => String(s || "").replace(/\\/g, "/").replace(/\/+$/, "");
  const d = norm(p.dir), userd = norm(DATA.user_data), sysroot = norm(DATA.home) + "/system";
  if (d === userd || d.startsWith(userd + "/")) return "user" + d.slice(userd.length);
  if (d === sysroot || d.startsWith(sysroot + "/")) return "system" + d.slice(sysroot.length);
  return null;
}
function select(id){
  cur = DATA.packages.find(p => p.id === id) || null;
  curH = null;                                // 选了包就把"历史那条"放下（两者互斥）
  consoleKey = cur ? cur.id : "__host__";     // 命令行跟着换成"这个包自己的那份"
  renderList(); renderHist(); renderDetail(); paintConsole(); setTab("detail");
  // 换了包 → 文件管理跟着换到"这个包的那一套"（每个包一份上下文，互不干扰）
  if (cur) fmSelect(cur.id, /*keepTab*/ true);
  paintEmbedTab();                            // 第四个选项卡：这个包有没有界面
}
function renderDetailHTML(){
  const who = selObj();
  if (!who) return '<div class="empty">左边选一个包，或者一条历史</div>';
  if (isHist(who)) return renderDetailHistHTML(who);
  const p = cur, params = p.params || [];
  const prop = (k, v) => '<div class="prop"><div class="prop-k">' + esc(k) +
    '</div><div class="prop-v">' + v + '</div></div>';
  let html = '<div class="dwrap"><div class="dhead">' +
      // 头部 4 块直接摆进 3 行网格（位置由 CSS 的 grid-area 定，DOM 顺序不影响画面）
      '<div class="dicon">' + iconHTML(p, "") + '</div>' +
      '<h1 class="dtitle" title="' + esc(p.name) + '">' + esc(p.name) + '</h1>' +
      (p.desc ? '<p class="ddesc">' + esc(p.desc) + '</p>' : '') +
      '<div class="dmeta">:' + esc(p.id) + ' · v' + esc(p.version || "?") + ' · ' +
        esc(p.kind) + ' · ' + esc(p.layer) + ' 层' +
        (p.shadowed ? ' · 遮住了 ' + esc(p.shadowed) + ' 层的同名包' : '') + '</div>' +
    '</div>';

  // 属性：别名 / 标签 / AI。用"标签 : 值"的行，不做成一堆药丸 ——
  // 药丸只留给"点一下就填进去"那种真动作（例子）。
  const props = [];
  if ((p.aliases || []).length)
    props.push(prop("别名", (p.aliases || []).map(a => '<span class="mono">:' + esc(a) +
      '</span>').join('&nbsp; ')));
  if ((p.tags || []).length)
    props.push(prop("标签", (p.tags || []).map(t => '<span class="tag">' + esc(t) +
      '</span>').join("")));
  if (p.ai_expose)
    props.push(prop("AI", '可调用 <span class="soft">· 风险 ' +
      esc(p.ai_risk || "?") + '</span>'));
  if (props.length)
    html += '<section class="dsec"><div class="props">' + props.join("") + '</div></section>';

  if (params.length){
    html += '<section class="dsec"><div class="props">' +
      params.map(pa => '<div class="prop"><div class="prop-k mono">' + esc(pa.name) +
        '</div><div class="prop-v">' + esc(pa.type || "string") +
        '<span class="soft"> · ' + (pa.required ? "必填" : "可留空") +
        (pa.rest ? " · 余下全给它" : "") + '</span>' +
        (pa.desc ? '<div class="pdesc">' + esc(pa.desc) + '</div>' : '') +
        (pa.placeholder ? '<div class="pex">例：' + esc(pa.placeholder) + '</div>' : '') +
        '</div></div>').join("") + '</div></section>';
  }
  // ★ 过滤掉空的例子：`pkg.json` 里 `ai.examples` 的 `args` 可能是空串
  //   （有的包就是 ['', '']），不过滤会画出一排**空药丸**、整块看着像坏了。
  const exs = (p.examples || []).map(x => String(x || "")).filter(x => x.trim());
  if (exs.length){
    html += '<section class="dsec"><div class="chips">' +
      exs.map(e => '<button class="chip" data-args="' + esc(e) + '">' + esc(e) +
        '</button>').join("") + '</div></section>';
  }

  // ★ 目录名和 id 允许不一样（`D-27` 方案 C）。不一样时**不报错**，只是把这件事
  //   摆在明面上，并给一个现成的统一动作（宿主那条 `--rename <id> <id>` 只改目录名）。
  const dirBase = (String(p.dir || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop()) || "";
  const oddDir = dirBase && dirBase !== p.id;
  const renameBtn = '<button class="btn" id="btn-rename" title="给这个包改名（moss --rename）">' +
      ico("pencil", "i") + '<span>更名</span></button>';

  html += '<section class="dsec"><div class="runrow">' +
      '<input id="args" placeholder="参数（可留空；回车 = 运行）" value="' +
        esc(ARGS[p.id] || "") + '">' +
      '<button class="btn" id="btn-openui" title="打开这个包自己的界面（后台运行，不等它）">' +
        ico("app-window", "i") + '<span>打开界面</span></button></div>' +
      '<div class="runhint">命令预览: <span class="mono" id="preview"></span>' +
      ' · 右上角是「运行 / 停止」</div></section>' +
    // 更名：单独一块（它既不是危险动作，也不属于「跑一下」）
    '<section class="dsec"><div class="row-split">' +
      (oddDir
        ? '<span class="hint">目录名 <span class="mono">' + esc(dirBase) +
          '</span> 和 id <span class="mono">' + esc(p.id) +
          '</span> 不一样（不碍事）</span>' +
          '<span class="row-inline">' +
          '<button class="btn" id="btn-align" title="只把包目录名改成 id —— 数据目录和清单都不动">' +
            ico("folder-tree", "i") + '<span>对齐目录名</span></button>' +
          renameBtn + '</span>'
        : '<span class="hint">改 id：包目录名、数据目录 ' +
          '<span class="mono">user_data/state/&lt;id&gt;</span>、清单里的 id 一起改</span>' +
          renameBtn) +
      '</div></section>' +
    '<section class="dsec danger">' +
      '<div class="danger-text">永久删除: 包本体 + 它的数据（不进回收站）</div>' +
      '<button class="btn danger" id="btn-remove" title="卸载这个包（moss --remove）">' +
        ico("trash-2", "i") + '<span>卸载</span></button></section></div>';
  return html;
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
  //   没绑上**（运行 / 停止 / 打开界面 / 更名 / 卸载，一个都点不动）。
  //   而 Vue 默认把组件里的异常只写进控制台（这个界面没有控制台）⇒ 界面上一个字都不报，
  //   看着就是"更名和卸载坏了"。（同一条根因现在会走 `reportError` 报出来。）
  const box = $("#pane-detail");
  const host = box;
  // ★ 每个 rev 只接一次线（`V-80`）：v-html 的内容没变时 Vue 不会重设 innerHTML，
  //   这时候再绑一遍监听器就会**重复**（回车跑两次那种）。
  if (host && host.dataset.wiredRev === String(DETAILR.rev)) return;
  if (host) host.dataset.wiredRev = String(DETAILR.rev);
  const upd = () => {
    $("#preview").textContent = "moss :" + p.id +
      ($("#args").value.trim() ? " " + $("#args").value.trim() : "");
    ARGS[p.id] = $("#args").value;              // 记住它，重画之后要放回去
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
  $("#btn-openui").onclick = async () => {    const r = await pywebview.api.open_ui(p.id, $("#args").value);
    // 不切选项卡：带界面的包本来就没有命令行输出，停在详情更合理
    paintRowStats();
    setTimeout(() => refreshPkgState(p), 1500);
    setTimeout(() => refreshPkgState(p), 3500);
  };
  $("#btn-remove").onclick = () => cmdRemovePkg(p);
  $("#btn-rename").onclick = () => cmdRenamePkg(p);
  if ($("#btn-align")) $("#btn-align").onclick = () => cmdAlignPkgDir(p);
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
  toast("包目录名已对齐成 :" + p.id);
  // ★ 目录名换了（id 没换）—— 文件管理缓存里那条路径**还是旧目录**，
  //   不搬的话双击一个文件去编辑，宿主会说「不是文件」。这条正是这个 bug 的现场。
  await refreshPkgs(p.id);
  const np = DATA.packages.find(x => x.id === p.id);
  fmReRoot(oldRel, np ? pkgRel(np) : null);
  if (np) select(p.id);
  else renderDetail();
}

/* 更名：界面只负责问"改成什么"，改的事交给宿主（`moss --rename`）。
   为什么不自己改：一次要动**包目录名 / 数据目录 / 清单里的 id** 三样，
   这套规则只有宿主那侧知道；界面自己拼路径，正是 `D-27` 里那几处毛病的来源。 */
async function cmdRenamePkg(p){
  askText("给这个包改名", p.id, async (newId) => {
    newId = String(newId || "").trim().toLowerCase();
    if (!newId || newId === p.id) return;
    const oldRel = pkgRel(p);            // 改名前它那个目录（文件管理缓存里记的就是它）
    consoleKey = "__host__";
    const cmd = "moss --rename " + p.id + " " + newId;
    setConsole("__host__", "$ " + cmd, "运行中");
    const r = await pywebview.api.run_host("--rename " + p.id + " " + newId);
    setConsole("__host__", "$ " + cmd + "\n\n" + (r.out || "(没有输出)"),
               r.code === 0 ? "完成" : ("退出码 " + r.code));
    if (r.code !== 0){
      toast("✗ 改名失败，看「命令行」里说了什么", true);
      setTab("console");
      return;
    }
    toast("已改名为 :" + newId);
    // ★ 目录整个换了地方，文件管理里缓存的路径（当前目录 / 历史 / 打开的文件）
    //   必须跟着搬 —— 否则双击一个文件去编辑，宿主会说「不是文件」。
    await refreshPkgs(newId);            // 包表重问一遍（旧 id 没了、新 id 出现）
    const np = DATA.packages.find(x => x.id === newId);
    fmReRoot(oldRel, np ? pkgRel(np) : null);
    if (np) select(newId);
    else renderDetail();
  });
}

/* ---------------------------------------------------------------- 详情：一条历史
   和包那份**长得一样**（同一个 .hd / .sec / .row-inline 结构），内容按"这条记录
   真有什么"来给 —— **没有的就不显示**（参数空着不写"参数（无）"，
   上次结果不知道就不写；说明性的废话也不写）。 */
function renderDetailHistHTML(it){
  const when = (it.ts || "").replace("T", " ");
  const gone = it.exists === false;
  // 只放"真有值"的行；一行都没有，这一块就不出现
  const rows = [];
  if (it.cwd) rows.push(["工作目录", it.cwd,
    it.cwd_exists === false ? "这个目录也不在了" : ""]);
  if (it.args) rows.push(["参数", it.args, ""]);
  if (when) rows.push(["时间", when, ""]);
  if (it.exit !== null && it.exit !== undefined)
    rows.push(["上次退出码", String(it.exit), ""]);
  let html = '<div class="dwrap"><div class="dhead">' +
      // 历史没有"说明"，右边第一二行留空 —— 路径放在**第三行**，和左边的名字对齐
      '<div class="dicon">' + histIconHTML(it, "") + '</div>' +
      '<h1 class="dtitle" title="' + esc(it.name) + '">' + esc(it.name) + '</h1>' +
      '<div class="dmeta">' + esc(it.target || "") + '</div>' +
    '</div>';
  if (gone){
    html += '<div class="warnbox">' + ico("alert-triangle", "i") +
      '<span>这个文件已经不在了，跑不了。记录还留着，想清掉就点下面那个按钮。</span></div>';
  }
  html += '<section class="dsec"><div class="runrow">' +
      // ★ 这里用 `#hargs` / `#hpreview`（而不是包详情那对 `#args` / `#preview`）：
      //   两个详情同一个时刻只会存在一个（都往 #pane-detail 里写），
      //   但静态检查"整个页面每个 id 只能出现一次"就分不清了 —— 换成不同的 id，
      //   那条检查才继续有用。要取输入框请走 `argsInput()`。
      '<input id="hargs" placeholder="参数（留空 = 上次那样；回车 = 运行）" value="' +
        esc(it.args || "") + '"' + (gone ? " disabled" : "") + '>' +
      '<button class="btn" id="btn-run2"' + (gone ? " disabled" : "") + '>' +
        ico("play", "i") + '<span>运行</span></button>' +
      '<button class="btn" id="btn-opendir" title="用 Windows 资源管理器打开它所在的目录">' +
        ico("folder-open", "i") + '<span>打开所在目录</span></button></div>' +
      '<div class="runhint">命令预览: <span class="mono" id="hpreview"></span></div>' +
      '</section>';
  if (rows.length){
    html += '<section class="dsec"><div class="props">' +
      rows.map(r => '<div class="prop"><div class="prop-k">' + esc(r[0]) +
        '</div><div class="prop-v mono">' + esc(r[1]) +
        (r[2] ? ' <span class="soft">' + esc(r[2]) + '</span>' : '') +
        '</div></div>').join("") + '</div></section>';
  }
  html += '<section class="dsec danger">' +
      '<div class="danger-text">只删这条记录，那个文件本身不动</div>' +
      '<button class="btn danger" id="btn-forget" title="从历史里删掉这条记录">' +
        ico("trash-2", "i") + '<span>删除这条记录</span></button></section></div>';
  return html;
}

/* 历史详情的接线 —— 同上，逐行搬运。 */
function wireDetailHist(it){
  const host = $("#pane-detail");
  if (host && host.dataset.wiredRev === String(DETAILR.rev)) return;
  if (host) host.dataset.wiredRev = String(DETAILR.rev);
  const upd = () => {
    const a = $("#hargs").value.trim();
    // 和宿主 `rerun_argv` 同一条规则的**近似预览**：真正跑的时候宿主回回来的 `cmd`
    // 才是准的（会打到「命令行」上）。这里只求"看着像手敲的那条"。
    $("#hpreview").textContent = "moss /" + it.name + (a ? " " + a : "");
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
  data(){ return { R: LISTR }; },
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
      // ★ 正拖着东西的时候：**只列收得下它的包**（`V-39`）—— 不支持对应操作的先藏起来
      return DRAG.on ? all.filter(p => dropAccepts(p, DRAG.kind)) : all;
    },
    emptyHTML(){
      // ★ 同 `V-83` 那个坑：`DRAG` 是普通对象（非响应式）—— 不登记 `R.rev` 的话，
      //   开始拖动（列表被筛空）时这句提示不会更新。
      this.R.rev;
      return DRAG.on ? ("没有包收「" + dropKindName(DRAG.kind) + "」") : "没有匹配的包";
    },
  },
  methods: {
    selId(){ return cur ? cur.id : null; },
    stateOf(id){ return rowStateOf(id); },          // 宿主口径：在跑 / 没在跑
    rowHTML(p){
      return iconHTML(p, "ico") +
        '<div style="min-width:0;flex:1">' +
          '<div class="nm">' + esc(p.name) + ' <span class="sub">:' + esc(p.id) + '</span></div>' +
          '<div class="ds">' + esc(p.desc) + '</div></div>' +
        '<span class="rowstat"></span>';
    },
    pick(id){ select(id); },
  },
  template: `
    <template v-if="R.ready">
      <div v-if="!rows.length" class="empty">{{ emptyHTML }}</div>
      <template v-else>
        <div v-for="p in rows" :key="p.id" class="item" :class="{sel: p.id === selId()}"
             :data-id="p.id" :data-state="stateOf(p.id)" @click="pick(p.id)" v-html="rowHTML(p)"></div>
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
      return HIST.filter(it => !f ||
        [it.name, it.target, it.args, it.cwd].join(" ").toLowerCase().includes(f));
    },
    emptyHTML(){
      this.R.rev;              // 同上：`HIST` 也是普通数组，得靠举牌信号才会重算
      return HIST.length ? "没有匹配的历史"
        : ('还没有历史。<br>历史只记<b>路径调用</b>（<span class="mono">moss zeen</span> 这种）——'
           + '<br>包调用不进历史。');
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
