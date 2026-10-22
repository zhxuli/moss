/* moss 界面 · app.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 启动 */

/* 浮动窗口模式（`V-192`）：宿主**开的第二个窗口**加载的是同一份页面，地址上只多一个
   `#float=<包id>`。这一页就只画那个包的那一帧，别的（顶栏 / 左侧栏 / 选项卡 / 状态栏）全藏起来
   （CSS 里那些 `body.float …`）。
   ★ 为什么要复用**同一份页面**而不是另写一个小页：`embed.js` 那条
     `postMessage → embed_send → 后端子进程 stdin` 一个字都不用改，后端也完全不知道
     自己"被搬了窗口"。
   ★ 这个标记**由 `core.js` 定义**（第一个加载的文件）—— `embed.js` 在 `app.js` 之前
     挂载组件，挂载那一刻就要读它，写在 app.js 里会 `ReferenceError`（`V-202`）。 */
const FLOAT_PID = window.__mossFloatPid || "";
if (FLOAT_PID) document.body.classList.add("float");

/* 浮动窗口的启动：不跑那一整套主界面流程，只要"选中这个包 + 把帧开起来"。 */
async function initFloatMode(){
  const p = (DATA.packages || []).find(x => String(x.id) === FLOAT_PID);
  if (!p){
    document.body.innerHTML = '<div style="padding:24px;font:14px system-ui">' +
      '这个窗口是给包 ' + PSYM + FLOAT_PID + ' 开的，但没找到它。</div>';
    return;
  }
  document.title = (p.name || p.id) + " · moss";
  select(p.id);                 // 让详情/界面这些面板有上下文（`select` 会顺手切到详情，下面再切回界面）
  await embedOpen(p);           // 起后端（已经起着就复用）+ 建那一帧
  await pushWindowIcon(p);      // `V-195`：窗口左上角换成本包自己的图标
  uiLog("[浮动窗口] " + PSYM + p.id + " 帧=" + (embedRunning(p.id) ? "ok" : "没起来") +
        " 图标=" + ((p.icon_svg || p.icon) ? "有" : "没有") + " 地址=" + location.href);
}

/* 启动诊断（`V-76` / `V-81`）：往 `user_data/state/_ui_drop.log` 写一行 —— 界面要是
   空白，我读这行就知道是哪种情况（包 0 个 / 画不出来 / 脚本没跑），不用你找控制台。
   ★ 只能在**列表和历史都画完之后**调：这两个列表是 Vue 组件画的，`renderList()` 只举牌、
   DOM 要等下一拍（`await Vue.nextTick()`），早读永远读到 0 行。 */
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

/* 插件 / 历史 那两颗按钮上的**数字**（`V-199`）。
   ★ 数的是**总数**（插件 = `DATA.packages.length`，历史 = `HIST.length`），不是"筛完之后
     剩几个" —— 那两个数回答的是"我这台机器上有多少东西"，跟着筛选跳来跳去反而看不懂。
   ★ 原来这两个数写在顶栏那行（"19 个包 · 启动方式：… · D:\…"），现在挪到名字后面：
     一眼就看到，还不占搜索框右边的地方。 */
function paintSwitchCounts(){
  const n = (typeof DATA !== "undefined" && DATA && DATA.packages) ? DATA.packages.length : 0;
  const h = (typeof HIST !== "undefined" && HIST) ? HIST.length : 0;
  const a = document.getElementById("sw-n-pkg"), b = document.getElementById("sw-n-hist");
  if (a) a.textContent = String(n);
  if (b) b.textContent = String(h);
}

/* ★ `V-367`：`init()` 也是那颗 ⟳ 的处理器 ⇒ **只在头一次**给状态栏写"就绪"。
   以前每次刷新都写一遍，于是"点 ⟳"会先被改成"就绪"、再弹一句"已刷新"（一个动作两条话），
   新建 / 卸载之后那句结果也会被它盖掉。 */
let bootedOnce = false;
async function init(){
  if (!bootedOnce){ bootedOnce = true; setStatus("就绪"); }   // 状态栏（`V-61`）的起点
  DATA = await pywebview.api.state();
  // ★ `V-305`：跑包符号从 payload 拿（`symbols.plugin`，默认 `:`）—— 全界面都用它、别硬编码。
  if (DATA && DATA.symbols && DATA.symbols.plugin !== undefined) PSYM = DATA.symbols.plugin;
  // ★ 浮动窗口（`V-192`）：只要那一帧，别跑主界面那一整套（列表 / 历史 / 文件管理都不用）。
  if (FLOAT_PID){ await initFloatMode(); return; }
  // ★ `V-199`：那一行"19 个包 · 启动方式：… · D:\…"不再显示 —— 数字挪到左边
  //   「插件 / 历史」两颗按钮上（`paintSwitchCounts`），启动方式和安装根挂到品牌名的
  //   tooltip 上（鼠标停一下就有，不占地方）。顶栏右边只留「自检」那颗按钮。
  document.querySelector("header .brand").title =
    "moss · " + DATA.home + " · 启动方式：" + DATA.launch_kind;
  renderList(); paintStates();
  // ★ `V-300`：这里桥一定就绪了，读回插件的"自定义顺序 + 排序档"（在 initListBars 里读太早会失败）
  loadListView();
  await loadHist();        // 先把历史读回来（loadHist 会顺手按 key 找回选中的那条）
  setSide(side);           // 切换条的高亮 / 隐藏状态跟 JS 变量对齐；顺带画一遍列表
  // ★ 启动诊断写一行到日志（`V-76`）：界面要是空白，我读这行就知道是哪种情况
  //   （包 0 个 / 画不出来 / 脚本没跑），不用你找控制台。
  // ★ `V-81`：列表/历史现在是 **Vue 组件**画的（`V-79`/`V-80`）—— `renderList()` 只举牌，
  //   DOM 要等**下一拍**才更新。不等这一拍的话，这行日志永远写着"列表条目=0 历史条目=0"
  //   （你机器上那几行 `宿主包数=19 列表条目=0` 就是这么来的），把"画不出来"和"还没画"
  //   混成同一件事 —— 我自己就被它绕过一次。所以：等一拍 + 挪到历史也读回来之后再写。
  await Vue.nextTick();
  writeStartDiag();
  consoleKey = "__host__";
  paintConsole();
  pkgPollStart();          // 每 2.5 秒把所有包的状态对一次（列表 + 按钮都要）
  // ★ `V-355`：另起一路"包表变了吗 / 谁改名了"的轮询（宿主那边**纯读盘**，不起进程）。
  //   更名跟随（AI 改的名 / 你在终端里改的名）就靠它做到"自动无感刷新"。
  pkgWatchStart();
  // 默认上下文：不选包时给一个"全部文件"（根 = user_data），能自己往上走到 system。
  // ★ `V-98` 修一个真 bug（你 2026-09-30 报的"点了刷新包列表，文件管理的路径就变错"）：
  //   这一段以前是**无条件**把上下文和路径按回 `__all__` + `user/`；而"刷新包列表"那颗 ⟳
  //   的处理器**就是 `init`**（`$("#btn-refresh").onclick = init`）⇒ 你在 `system/pkgs/xxx`
  //   里点一下刷新，路径被顶回 `user_data`、上下文被顶回"全部文件"（快照边栏也跟着换了一组）。
  //   现在：**头一次**进来才给默认值；之后只把**当前那个目录**重列一遍（目录没了才退回 user）。
  const first = !FM.ctx;
  if (first) FM.ctx = "__all__";
  const s = fmState(FM.ctx || "__all__");
  const keep = (s.rel && !first) ? s.rel : "user";
  let r = await pywebview.api.fs_list(keep);
  if (!r || !r.ok) r = await pywebview.api.fs_list("user");
  if (r.ok){
    s.rel = r.rel; s.entries = r.entries || [];
    if (first){ s.hist = [s.rel]; s.hpos = 0; }
    else if (s.hist && s.hist.length){ s.hist[s.hpos] = s.rel; }   // 目录没了才会换人，历史照旧保留
  }
  fmRender();
  bindDropZone();          // 拖文件进来（`V-35`）：高亮 + 收宿主送来的真实路径
  // ★ `V-387`：⟳（`#btn-refresh` 的处理器**就是** `init`）之后也把「界面」选项卡重画一遍
  //   —— 和 `refreshPkgs` 里那次是同一个 bug 的两个入口：包表换了却没人重画选项卡。
  if (typeof paintEmbedTab === "function") paintEmbedTab();
  autostartRun();          // ★ `V-356`：启动界面之后自动跑起那几条（实现在 js/autostart.js）
}
function paintStaticIcons(){
  // 注意：这里**没有"退出"按钮** —— 标题栏本来就有 ×，重复一个是多余的
  // 顶层三个选项卡也带图标（原来只有文字，和别处不统一）
  // ★ `V-257`：「AI」那一格也要图标 —— 用的就是**设置面板里 AI 那一组那个标记**
  //   （`moss-deepseek`：DeepSeek 那枚 mark，只有一份，两处都用它。
  //   原来用的是 OpenAI 那一枚，`V-386` 换成了 DeepSeek）。
  const tabs = {"detail": ["info", "详情"], "console": ["terminal", "命令行"],
                "file": ["folder-tree", "文件管理"], "ai": ["moss-deepseek", "AI"]};
  Object.keys(tabs).forEach(k => {
    const b = document.querySelector('.tab[data-tab="' + k + '"]');
    if (b) b.innerHTML = ico(tabs[k][0], "i") + '<span>' + tabs[k][1] + '</span>';
  });
  $("#btn-selfcheck").innerHTML = ico("activity", "i");
  $("#btn-aside-mini").innerHTML = ico("chevron-right", "i");   // `V-171`：收起 / 展开
  // 左侧顶部：插件 / 历史 切换 + 新建包
  // ★ `V-199`：名字后面各跟一个**数字**（`#sw-n-pkg` / `#sw-n-hist`）——
  //   就是列表里能数出来的条目数（插件 = `DATA.packages`，历史 = `HIST`），由
  //   `paintSwitchCounts()` 填；顶栏那一行"19 个包 · 启动方式…"因此撤掉了。
  $("#sw-pkg").innerHTML  = ico("package", "i") + '<span>插件</span>' +
                            '<b class="sw-n" id="sw-n-pkg"></b>';
  // ★ 历史用 Lucide 那个**带表针的 history**（lucide-static 1.48.0，见 vendor/README.md）。
  //   以前用的是 `corner-up-left`（一个"返回箭头"），跟"历史"不是一回事。
  $("#sw-hist").innerHTML = ico("history", "i") + '<span>历史</span>' +
                            '<b class="sw-n" id="sw-n-hist"></b>';
  $("#btn-newpkg").innerHTML = ico("file-plus", "i");
  $("#btn-settings").innerHTML = ico("settings", "i");   // 状态栏那颗齿轮（`V-61`）
  // 确认框右上角那颗 ×（`V-63`）。★ 设置面板那颗 × 由**组件自己**画
  //   （`js/settings.js` 的模板里 `v-html="icon('x')"`）—— 面板已经不是这块 DOM 了。
  $("#m-x").innerHTML = ico("x", "i");
  $("#btn-refresh").innerHTML   = ico("refresh-cw", "i");
  // ★ `V-83`：命令行那一页现在是 **Vue 组件**（`js/console.js` 的 `MossConsole`）——
  //   复制 / 重跑 / 清空 三颗按钮的图标和点击都由组件自己的模板管，这里**不再插手**
  //   （插了也会被下一次重画盖掉，等于绕开 Vue 去改它管的东西 —— `V-67` 那个教训）。
}
$("#q").addEventListener("input", () => { if (side === "hist") renderHist(); else renderList(); });
/* ⟳ 刷新（`V-101`）：刷完**弹一个回执**——“哪怕没有变化，用户也知道按钮没坏”。
   数字就从刚读回来的两份数据里数（`DATA.packages` / `HIST`），不另算一遍。 */
$("#btn-refresh").onclick = async () => {
  await init();
  await Vue.nextTick();
  const np = (DATA && DATA.packages ? DATA.packages.length : 0);
  const nh = (typeof HIST !== "undefined" && HIST ? HIST.length : 0);
  notice("已刷新", "插件：<b>" + np + "</b> 个<br>历史记录：<b>" + nh + "</b> 条" +
         "<br><br>列表已经是最新的了。",
         // `V-367`：这句 tip 以前是"这一条只是回执：哪怕什么都没变，也说明按钮是好的"——
         //   那是**我们为什么做这个弹框**，对用户没用。换成他会关心的。
         {tip: "刷新会重扫插件与历史（正在跑的包不受影响）"});
};
/* `V-178`：切换插件/历史时，**工具条也跟着换**（各有一排分类+排序） */
$("#sw-pkg").onclick = () => { setSide("pkg"); window.syncListBars && window.syncListBars(); };
$("#sw-hist").onclick = () => { setSide("hist"); window.syncListBars && window.syncListBars(); };
window.syncListBars && window.syncListBars();       // 开机先摆一次（插件那条默认在）
$("#btn-newpkg").onclick = cmdNewPkg;
document.querySelectorAll(".tab").forEach(b => b.onclick = () => {
  if (b.dataset.tab === "file") fmSelect(fmCtxKey());
  else if (b.dataset.tab === "embed"){                 // 「界面」：没起就顺手起起来
    if (embedSupported(cur) && !embedRunning(cur.id)) embedOpen(cur);
    else setTab("embed");
  }
  else setTab(b.dataset.tab);
});
// ★ `V-84`：第四个选项卡顶上那两颗按钮（重载 / 在独立窗口里开）现在归 `MossEmbed` 组件
//   （`js/embed.js` 的模板里绑），这里不再插手。

/* ★ `V-83`：命令行那一页（`#pane-console`）整个交给 `MossConsole` 组件了 —— 复制 / 重跑 /
   清空 / 发送 这几个处理器和 `#stdin` 的回车，都在它的模板里绑（`js/console.js`）。
   这里只留**不属于那一页**的东西（状态栏齿轮、确认框、设置面板、刷新…）。 */
$("#btn-settings").onclick = openSettings;
/* 设置面板（`V-67` 起是 Vue 组件）：外面只留"打开"这一个入口 ——
   × / 取消 / 保存 / 点面板外面关闭，都由组件自己的模板绑（`js/settings.js`）。 */
$("#m-cancel").onclick = closeModal;
$("#m-x").onclick = closeModal;   // `V-63`：确认框的 × = 取消
$("#m-ok").onclick = () => { const cb = modalCb; closeModal(); if (cb) cb(); };
/* 第二个动词（`V-92`）：和 `#m-ok` 同款，先取出回调再关（`closeModal` 会把两个都清掉）。 */
$("#m-ok2").onclick = () => { const cb = modalCb2; closeModal(); if (cb) cb(); };
$("#m-input").addEventListener("keydown", e => {
  if (e.key === "Enter"){ e.preventDefault(); $("#m-ok").click(); }
  if (e.key === "Escape") closeModal();
});
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });

/* ---------------------------------------------------------------- 新建 / 卸载
   这两个功能 CLi 早就有（`moss --new` / `moss --remove`），界面这边原来漏了。
   界面**不重写一遍逻辑**，直接把宿主命令叫起来（和用户手敲是同一条路），
   输出照样进「命令行」那份缓冲。 */
/* ★ `V-387`：**新建包** —— 照你给的稿子重做（`AI 创建` / `手动` 二选一，zinc 中性色）。
   · AI 模式**只有一个输入框**：说一句话 → 点「创建」时先问一次 AI（拿 id / 名字 / 介绍 /
     第一句任务）→ 建包 → 进 AI 页 → **自动开工**。AI 定好的值会同时填进「手动」那几格，
     切过去就能看 / 改（不用另开一步"确认"）。
   · 手动模式：名字 / 包 ID / 一句话介绍 / 第一句任务 → **只建包，不碰 AI**。
   · 底栏只有一颗「创建」（两种模式共用）；出口是右上角那颗 ×（Esc / 点外面同样能关）。
   · 纯 CSS 复刻（不引 Tailwind CDN —— 界面是离线的，引外链等于没有样式）。 */
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
  // AI 已经定过 → 切到"手动"时把值铺出来（这时候人才能改它）
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

/* 建包。**AI 模式：建完直接让 AI 开工；手动模式：只建**（你定的这两条）。
   AI 模式下先请 AI 把四样（id / 名字 / 介绍 / 第一句任务）定下来。 */
async function npCreate(){
  if (NP.busy) return;
  const aiMode = NP.mode === "ai";
  // ★ 你定的：AI 创建 ⇒ 建完自动开工；手动 ⇒ 只建（不碰 AI）
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
    return;
  }
  closeModal();
  await init();                     // 重扫包列表 —— 新包这会儿才出现在 DATA 里
  select(id, /*keepTab*/ true);     // keepTab：别把用户弹回「详情」
  toast("已新建 " + PSYM + id + (v.name ? " · " + v.name : ""));
  if (!andStart) return;
  /* ★ `V-421`：**开工目录必须钉死成新包**，不能靠"当前选中"再推一次。
     以前这里只 `select(id)` 然后就 `aiStart()`（它内部读 `cur`），于是：
     包表还没刷新 / 用户这一拍点了别的包 / 任何一次异步重选，都会让 AI **在旧包里开工**
     —— 真事：在 `ip` 里开工、把 `keytest` 整个建出来，会话还挂在 `ip` 名下。
     现在：① 先从**刷新后的包表**里把这个包的目录找出来（不是从 `cur`）；
           ② 找不到就再刷一次，还找不到就**明说**，绝不"猜一个目录开始干活"；
           ③ 找到了就把它**显式传给** `aiStart`。 */
  let np = (DATA.packages || []).find(p => p.id === id) || null;
  if (!np || !np.dir){
    await refreshPkgs(id);
    np = (DATA.packages || []).find(p => p.id === id) || null;
  }
  if (!np || !np.dir){
    toast("新包建好了，但包列表里还没刷出来 —— 点一下左上角 ⟳ 再开工。", true);
    return;
  }
  if (!cur || cur.id !== id) select(id, true);   // 顺手把选中也摆正（用户可能点了别处）
  const task = String(v.task || "").trim() || String(v.desc || "").trim() || ("做一个「" + id + "」的包");
  setTab("ai");
  await new Promise(res => setTimeout(res, 250));   // 等 AI 那一页挂上（组件按页渲染）
  window.__AIR.task = task;
  /* ★ 2026-10-22：**新包 = 新会话**。这里不清的话，`AIR.contId` / `AIR.lastId` 还指着
     **上一个包**那条记录（AI 页那个 700ms 的 tick 还没来得及按"换包"清它），于是
     `aiStart` 会把旧包的会话交给宿主 ⇒ 新包的第一跑挂在旧包的对话链后面：
     AI 一开口就"接着上次那条聊"。真机 10-22 那轮就是这样：17:31 在 `keytest` 里聊过，
     17:39 建 `kids-typing` 时 `continued_from` 指向的却是 `keytest` 那条。 */
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
  // Esc 关（这个弹窗里的输入框不吃 app.js 那条 Esc 绑定 —— 那条绑在 `#m-input` 上）
  box.onkeydown = e => {
    if (e.key === "Escape" && !NP.busy){ e.stopPropagation(); closeModal(); }
  };
  $("#modal").classList.add("on");
  setTimeout(() => { const t = $("#np-idea"); try{ if (t) t.focus(); }catch(e){} }, 40);
}

async function cmdRemovePkg(p){
  const st = ico("alert-triangle", "i");
  // ★ `V-89`：先问一下它在备份库里有几次备份（**不自动删** —— 卸载就是卸载，
  //   备份是另一件事；但界面上得让你知道它还占着多少，别不知不觉留一堆）。
  let bkLine = "";
  try{
    const b = await pywebview.api.backup_group_info(p.id);
    if (b && b.ok && b.backups)
      // `V-367`：原来写的是「文件管理 → 备份」—— 界面上没有这个名字（那边叫「版本快照」），
      //   指路指错了；顺带把"分组"这种内部叫法也换掉。
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
      setTab("console");                  // 让用户看到到底删了什么
      if (r.code === 0){ cur = null; await init(); renderDetail(); }
    });
}

$("#btn-selfcheck").onclick = async () => {
  consoleKey = "__host__";                // 自检是**宿主自己的**输出，单独一份
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

/* 左侧栏收起 / 展开（`V-171`）：收起只剩图标，选择记在 localStorage，下次开还是这样。
   ★ 宽度不改：收起时用 CSS（`main.mini > aside{width:56px !important}`）压住，
     展开时把那层压盖去掉 ⇒ 你拖出来的宽度**原样还在**。 */
function asideMiniOn(){ return $("main").classList.contains("mini"); }
function setAsideMini(on){
  // ★ 先记宽度**再**加类（`V-174`）：加完 `mini` 它就已经缩成 56px 了，
  //   那时候去记只会把弹出宽度记成 56 —— 表现就是"hover 了也不展开"。
  if (on) rememberAsideW();
  $("main").classList.toggle("mini", !!on);
  $("main").classList.remove("hover-aside");
  try{ localStorage.setItem("moss.asideMini", on ? "1" : "0"); }catch(e){}
}
/* 把"你拖出来的宽度"记进 `--aside-w`（弹出时用它），并**存进 localStorage**。
   ★ 只在"正常宽度"时记：已经缩成图标条（≤60px）时读到的是 56，那不算数。 */
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
/* 悬停进出：收起状态下鼠标放上去就弹出来（浮在内容上），移开就缩回去 */
{
  const a = $("main > aside");
  if (a){
    a.addEventListener("mouseenter", () => {
      if (asideMiniOn()){ rememberAsideW(); $("main").classList.add("hover-aside"); }
    });
    a.addEventListener("mouseleave", () => $("main").classList.remove("hover-aside"));
    /* 拖完记住新宽度（拖动那条线在 aside 里，pointerup 会冒泡上来） */
    a.addEventListener("pointerup", () => { if (asideMiniOn()) rememberAsideW(); });
  }
}
try{
  const savedW = parseInt(localStorage.getItem("moss.asideW"), 10);
  if (savedW > 60) $("main").style.setProperty("--aside-w", savedW + "px");
  setAsideMini(localStorage.getItem("moss.asideMini") === "1");
}catch(e){}

/* 左侧那一列也能拖宽（`V-92`）：细线在它右边缘上（`index.html` 里的 `#grip-aside`），
   往右拖变宽；双击回到 300。上限按窗口宽度算（最多占一半）。 */
bindColResize($("#grip-aside"), $("main > aside"), +1, 200,
              () => Math.round((window.innerWidth || 1200) * 0.5), 300);

/* ---------------------------------------------------------------- 启动（`V-68` 修过一次）
   ★ 这里原来只有一句 `window.addEventListener("pywebviewready", init)`。
     界面拆成多个外部脚本之后（`V-67`），`js/app.js` 是**最后**才执行到的，
     而 pywebview 的 `pywebviewready` 有可能在它之前就发过了 —— 事件只发一次，
     错过就永远等不到：`init()` 从不运行 ⇒ 左侧列表/历史/详情全空，而且**什么都不报**
     （没抛异常，只是没干活）。一个内联大脚本没有这个竞态，拆开之后就有了。

   ⇒ 两手准备：
       ① 听事件（正常情况走这条）；
       ② **轮询**桥在不在（`window.pywebview.api.state` 出现就算到了），谁先到算谁；
      `boot()` 自己幂等，重复调只会跑一次。`init()` 外面包一层 try/catch，
      出事就写到状态栏和 `window.__errors`（配合 `js/core.js` 里的错误上报）。 */
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
  if (n > 120) return;                 // 最多等 6 秒，别无限轮
  setTimeout(() => waitBridge(n + 1), 50);
})(0);
