/* moss 界面 · console.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ================================================================ 命令行：**一个包一份**
   ★ 原来只有一块 <pre>，谁跑就往里写，于是"在 fanyi 这里看到的命令行和 img 那里是同一份"。
     现在按 key 分缓冲区：
         key = 包 id（`moss :img` 的输出就落在 `img` 那份里）
         key = "__host__"（自检这种宿主自己的输出）
     切包只切"看哪一份"，别人的输出不会串进来；同时**允许多个包一起跑**
     （宿主本来就支持，是前端原来只留了一份 RUN，把它限成了单线程）。 */
const CONSOLE = {};             // key -> {text, info}
let consoleKey = null;          // 当前显示的是哪一份

// 宿主机那一份的初始说明（顺便把"每个包一份"这件事写在界面上）
const HOST_SEED = "每个包有自己的一份命令行，互不串台 —— 在左边选谁就显示谁。\n" +
  "· 右上角「运行」= 跑这个包，输出落进它自己那份（可以同时跑好几个）\n" +
  "· 运行中再点同一个按钮 = 停止；左侧列表行尾那颗绿色停止图标也能停\n" +
  "· 「自检」的输出单独算一份（就是现在这份）";

function consoleBuf(key){
  const k = key || "__host__";
  if (!CONSOLE[k]) CONSOLE[k] = {text: k === "__host__" ? HOST_SEED : "", info: "还没跑过"};
  return CONSOLE[k];
}
function consoleTitle(key){
  if (!key) return "moss";
  if (key === "__host__") return "moss 自检";
  // 历史键 = "hist:" + 目标 + (" " + 参数)，标题只取目标那段文件名
  if (key.startsWith("hist:")) return "历史 · " + key.slice(5).split(" ")[0].split(/[\\/]/).pop();
  const p = DATA && DATA.packages.find(x => x.id === key);
  return p ? (p.name + "（:" + key + "）") : key;
}
/* ---------------------------------------------------------------- 命令行这一页（`Vue` 组件，`V-83`）
   薄组件：结构 / 类名 / id 一个**都不动**，只是把"按 id 找元素改属性"换成"状态一变、模板
   自己更新"。外面照旧调 `paintConsole()` / `paintInbar()`（同名门面，只举牌）。
   ★ 为什么这两个是门面而不是把 `CONSOLE` 改成响应式：`CONSOLE` / `consoleKey` / `RUNS`
     都是别的文件也在写的普通变量（`embed.js` 起跑、收尾时都改），改成响应式要动一圈；
     原来的代码本来就在"变了"的地方显式喊一声，保留函数名最省事、行为也一字不变。
   ★ 行尾那颗状态图标（`paintRowStats`）和右上角那对「运行 / 停止」（`paintActions`）**不在这里**
     —— 它们画的是**别的组件**的 DOM（左侧列表行、选项卡那一行），维持命令式（`V-79` 起就这样）。 */
const CONSOLER = Vue.reactive({rev: 0, flash: ""});
function paintConsole(){
  // 门面：原来的调用点（`setTab` / `setConsole` / `init` …）照旧调它
  CONSOLER.flash = "";                   // 上一次"已复制 N 个字符"这类临时话，重画就抹掉
  CONSOLER.rev++;
}
function paintInbar(){
  // 门面：`startRun` / `finishRun` 里那两处"输入行该能用了 / 该禁用了"
  CONSOLER.rev++;
}
function consolePaneKey(){ return consoleKey || "__host__"; }
/* 输入行那句占位话（`V-43`）：没在跑 / 跑完了 → 换一句，省得你以为发了没反应。 */
function consoleInbarPlaceholder(key){
  if (RUNS[key]) return "包在等你的回答就敲在这里，回车发送（比如 1 / 2 / 3）";
  return key === "__host__" ? "宿主自己的输出没有输入这回事"
                            : "这个包现在没在跑 —— 先在「详情」里点运行";
}

const MossConsole = {
  name: "moss-console",
  data(){ return { R: CONSOLER }; },
  computed: {
    key(){ this.R.rev; return consolePaneKey(); },
    buf(){ this.R.rev; return consoleBuf(this.key); },
    // ★ `V-83` 踩到的坑：**这里必须也读一下 `this.R.rev`**。`buf` 每次重算返回的都是
    //   **同一个对象**（`CONSOLE[key]` 那一条，普通对象、不是响应式的）—— 只依赖
    //   `this.buf` 的话，Vue 看到"依赖没变"就**不重算**，输出区会一直停在旧文字上
    //   （实测：`#out` 空着、而同一份缓冲的 `info` 却是新的）。规矩：凡是从"非响应式
    //   状态"里取值的计算属性，都要显式登记 `R.rev` 这个举牌信号。
    text(){ this.R.rev; return this.buf.text || ""; },
    // 顶栏那行字：平时是「谁的 · 什么状态」，刚复制过就显示复制结果（和以前一样）
    line(){
      this.R.rev;
      if (this.R.flash) return this.R.flash;
      return consoleTitle(this.key) + " · " + (this.buf.info || "");
    },
    live(){ this.R.rev; return !!RUNS[this.key]; },
    ph(){ this.R.rev; return consoleInbarPlaceholder(this.key); },
  },
  mounted(){ this.autoscroll(); },
  updated(){ this.autoscroll(); },
  methods: {
    /* 自动滚到底：**只在"看的这份内容真的变了"时滚** —— 以前是每次 `paintConsole()`
       都滚；现在重画的由头更多（复制那句话、跑完的状态），不判一下会把你正在翻的输出拽走。 */
    autoscroll(){
      const el = this.$refs.out;
      if (!el) return;
      const sig = this.key + "\u0000" + this.text.length + "\u0000" + (this.R.flash ? 1 : 0);
      if (sig === this._sig) return;
      this._sig = sig;
      el.scrollTop = el.scrollHeight;
    },
    clearOut(){ setConsole(this.key, "", "还没跑过"); },
    copyOut(){ copyOut(); },
    rerun(){ rerunLast(); },
    send(){ sendStdin(); },
  },
  // ★ `<pre>` 那一行**必须写在同一行**：换个行，模板里的空白就会进到输出里（`pre` 不折叠空白）。
  template: `
    <div class="outbar">
      <span id="outinfo">{{ line }}</span>
      <span style="flex:1"></span>
      <button id="btn-copy" class="iconbtn" title="复制全部输出" v-html='ico("copy", "i")' @click="copyOut()"></button>
      <button id="btn-rerun" class="iconbtn" title="再跑一次刚才那条命令" v-html='ico("rotate-cw", "i")' @click="rerun()"></button>
      <button id="btn-clear" class="iconbtn" title="清空输出" v-html='ico("eraser", "i")' @click="clearOut()"></button>
    </div>
    <pre id="out" ref="out">{{ text }}</pre>
    <div id="inbar" :class="{off: !live}">
      <span class="ps1">›</span>
      <input id="stdin" :placeholder="ph" autocomplete="off" spellcheck="false"
             :disabled="!live" @keydown.enter.prevent="send()">
      <button id="btn-send" class="btn" :disabled="!live" @click="send()">发送</button>
    </div>`,
};
/* ★ 挂载点放在**文件末尾**（`V-83`）：`mountVue()` 会立刻做第一次渲染，而模板里要用
   `RUNS`（`live` / 占位话）—— 那个 `const` 在下面才声明，在这儿挂就是
   `Cannot access 'RUNS' before initialization`（`V-79` 踩过同一个坑，这次是预览那道
   "页内错误非空即判失败"的闸**当场**抓出来的）。 */

/* 发一行给正在跑的那个进程的 stdin。先把这一行**回显**到输出里（像终端那样），
   不然"我到底发出去没有"看不出来。 */
async function sendStdin(){
  const key = consoleKey || "__host__";
  const inp = $("#stdin");
  if (!inp || inp.disabled) return;
  const run = RUNS[key];
  if (!run){ toast("这个包现在没在跑", true); return; }
  const line = inp.value;
  inp.value = "";
  const b = consoleBuf(key);
  setConsole(key, (b.text || "").replace(/\n?$/, "\n") + line + "\n", b.info);
  const r = await pywebview.api.run_input(run.rid, line);
  if (!r || !r.ok) toast("✗ " + ((r && r.msg) || "发不出去"), true);
}
function setConsole(key, text, info){
  const b = consoleBuf(key);
  b.text = stripAnsi(text);
  if (info !== undefined && info !== null) b.info = info;
  if ((consoleKey || "__host__") === (key || "__host__")) paintConsole();
}
function out(text, info){ setConsole(consoleKey || "__host__", text, info); }
/* 复制全部输出。★ 复制完那句反馈**交给组件去显示**（`V-83`）：以前是直接
   `$("#outinfo").textContent = …` 写进 DOM —— 现在那是组件的 DOM，下一次重画就被盖掉，
   而且等于绕开 Vue 去改它管的东西。走 `CONSOLER.flash` 这条路，行为一样、不打架。 */
async function copyOut(){
  const text = $("#out") ? $("#out").textContent : "";
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

/* ---------------------------------------------------------------- 运行 / 停止
   跑包不再是"一个阻塞调用"（那样跑起来就停不了，长驻的东西会把界面卡住）。
   走宿主的 `run_start` / `run_poll` / `run_stop`：200ms 轮询一次，
   输出**流式**刷进「命令行」，随时能按停止（连子孙进程一起杀）。

   ★ "这个包在不在跑"**不能只看本地状态**：包可能是从终端开的、或者它的父进程
   fork 出界面后自己退了、或者 moss 界面重启过。所以按钮状态一律问宿主
   （它按进程环境里的 `MOSS_PKG_ID` 认，不管是谁拉起来的）。
   本地的 `RUNS` 只用来决定"这个包的输出还能不能流式看"。 */
const RUNS = {};                // 包 id -> {rid, cmd, timer, stopped}（**可以同时好几个**）
const PST = {};                 // 包 id -> {running, pids, windows, visible, titles}
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

/* 一次把所有包的状态都问回来：左侧列表要给每一行显示状态，
   一个包一次调用的话每轮得重复扫窗口 N 遍（宿主那边已经做成批量接口）。 */
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

/* ---------------------------------------------------------------- 状态：只有两种
   运行中 = 绿色停止图标（点它停）；没在跑 = 淡灰播放图标（点它跑）。
   **不再有红/黄**（退出码误报太多）。 */
function rowStateOf(id){
  const st = PST[id] || {};
  return st.running ? "running" : "idle";
}

function paintRowStats(){
  /* `V-178`：顺手记一笔"最后运行"（工具条那个排序要用）—— host 没有这个字段，
     所以只能由界面**看着它跑**时记下来。 */
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
      : '<button class="idle" title="运行这个包（:﻿' + esc(id) + '）">' + ico("play", "i") + '</button>';
    const b = box.querySelector("button");
    if (b) b.onclick = (ev) => {
      ev.stopPropagation();                       // 点图标不要连带选中那一行
      if (running) stopFromList(id); else runFromList(id);
    };
  });
}

/* 列表里直接跑：参数留空（就是"平常那样跑它"）。
   ★ 跑之前把它**选上**（不切到详情）—— 右上角那颗「运行/停止」认的是"当前选中项"，
     不选的话列表行都变成「停止」了，右上角还停在原来那个（甚至没选）的状态。 */
async function runFromList(id){
  const p = DATA.packages.find(x => x.id === id);
  if (!p) return;
  if (RUNS[id]) return;
  const st = PST[id] || {};
  if (st.running){ toast(":" + id + " 已经在跑了"); return; }
  if (!cur || cur.id !== id) select(id, /*keepTab*/ true);
  startRun(p, "");
}

/* 列表里直接停掉：别管是谁起的，**显示「停止」就得真停**（`V-216`）——
   是这里起的 run 就走 run_stop（好把输出收尾）、内嵌那把走 embed_stop、
   其余（孤儿 / 从终端开的）按进程停。 */
async function stopFromList(id){
  let r;
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

/* 「到底是谁在跑」—— 把宿主编好的 pid / 起始时间 / 命令行摆进 tooltip（`V-216`）。
   ★ 为什么值得摆：这一条能让人一眼看出"这是昨天那个孤儿"，而不是"我刚跑的那次没结束"。
   没有 procs 信息（老宿主）就退回原来那句。 */
function runningHint(id){
  const st = PST[id] || {};
  const ps = st.procs || [];
  if (!ps.length) return "";
  const p = ps[0];
  const more = ps.length > 1 ? (" …还有 " + (ps.length - 1) + " 个") : "";
  return "\n· pid " + p.pid + (p.started ? "（起于 " + p.started + "）" : "") +
         "\n· " + String(p.cmd || "").slice(0, 120) + more;
}

/* 状态灯 + 运行/停止 + 显示/隐藏：**一个控件**（灯就在按钮里）。
   钉在选项卡那一行的最右边，所以不用先点开「详情」也能操作。 */
function paintActions(p){
  const b = $("#btn-run"), v = $("#btn-vis");
  if (!b || !v) return;
  /* 历史条目：只有「运行 / 停止」，而且状态**只认这里起的那一次**（宿主那边
     一次"路径调用"没有包 id，认不出是不是别处起的）。「显示/隐藏」对它禁用 ——
     路径调用没有"包自己的窗口"这回事（那个按钮管的是 GUI 包的窗口，`U-16`）。 */
  if (isHist(p)){
    const running = !!RUNS[histKey(p)];
    const gone = p.exists === false;
    // 目标文件没了的：不给"运行"—— 点了只会得到"目标已经不在了"，不如直接不给点
    b.disabled = gone && !running;
    b.innerHTML = ico(running ? "square" : "play", running ? "i ic-run" : "i") +
                  '<span>' + (running ? "停止" : "运行") + '</span>';
    b.title = gone ? "这个文件已经不在了，跑不了"
                   : (running ? "停掉这次调用（连同它的子进程）"
                              : "在它当初的目录里再跑一次（输出进「命令行」）");
    b.classList.toggle("warn", running);
    v.hidden = true;                         // `V-303`：路径调用没有"包自己的窗口" ⇒ 整颗藏起来
    v.disabled = true;
    v.innerHTML = ico("eye", "i") + '<span>显示</span>';
    v.title = "这是一次路径调用，没有「包自己的窗口」";
    return;
  }
  const st = (p && PST[p.id]) || {running: false, windows: 0, visible: false};
  const mine = !!(p && RUNS[p.id]);
  const embedded = !!(p && embedSupported(p) && embedRunning(p.id));
  const running = mine || embedded || !!st.running;
  b.disabled = !p;
  // ★ 颜色只在"运行中"时给（绿色停止图标）；不再按"上次是否非 0"染红/黄 —— 误报太多
  b.innerHTML = ico(running ? "square" : "play", running ? "i ic-run" : "i") +
                '<span>' + (running ? "停止" : "运行") + '</span>';
  b.title = !p ? "先在左边选一个包或一条历史"
               : (running ? ("停掉它（连同它拉起的子进程）" + runningHint(p.id))
                          : "运行这个包，输出进「命令行」");
  b.classList.toggle("warn", running);
  // ★ `V-303`：**没有开着的窗口就不显示这颗「显示」**（原来只是变灰，还是占着地方）
  v.hidden = !p || !st.windows;
  v.disabled = !p || !st.windows;
  v.innerHTML = ico(st.visible ? "eye-off" : "eye", "i") +
                '<span>' + (st.visible ? "隐藏" : "显示") + '</span>';
  v.title = !p ? "先在左边选一个包或一条历史"
               : (!st.windows
                  ? "这个包现在没有开着的窗口（先「运行」或「打开界面」）"
                  : (st.visible ? "隐藏它的窗口（不关掉，随时能再显示出来）"
                                : "把它的窗口显示出来并叫到前面"));
}

/* ---------------------------------------------------------------- 挂载（放最后）
   ★ 必须在 `RUNS` / `PST` / `consoleKey` 这些 `const`/`let` **声明之后**：`mountVue()`
     当场就会渲染一次，模板里的 `live` / 占位话要读 `RUNS` —— 早一步就是
     `Cannot access 'RUNS' before initialization`（`V-79` 踩过同一个坑）。 */
mountVue(MossConsole, "#pane-console", {ico: ico});
