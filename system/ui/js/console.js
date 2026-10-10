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
  if (!CONSOLE[k]) CONSOLE[k] = {text: k === "__host__" ? HOST_SEED : "",
                                 raw: k === "__host__" ? HOST_SEED : "", info: "还没跑过"};
  return CONSOLE[k];
}
function consoleTitle(key){
  if (!key) return "moss";
  if (key === "__host__") return "moss 自检";
  // 历史键 = "hist:" + 目标 + (" " + 参数)，标题只取目标那段文件名
  if (key.startsWith("hist:")) return "历史 · " + key.slice(5).split(" ")[0].split(/[\\/]/).pop();
  const p = DATA && DATA.packages.find(x => x.id === key);
  return p ? (p.name + "（" + PSYM + key + "）") : key;
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
  // 切了"看哪一份" ⇒ 给终端重新对一次基线（只对基线，**不往屏上打任何字**）
  const k = consolePaneKey();
  if (k !== MOSS_TERM.mirrorKey){
    MOSS_TERM.mirrorKey = k;
    MOSS_TERM.mirror[k] = consoleBuf(k).raw || "";
  }
  // `V-348`：这一页一露头就把终端起起来（会话先热着，不用你去点开关）；
  //          顺带重量一次尺寸（切回来 / 窗口变了，列数可能是旧的）
  termAutoStart();
  // ★★ `V-370`：**这一版显示的是终端还是那个包自己的输出，全看 `termViewing()`** ——
  //   看着别的包的输出时终端会话照旧活着（`on` 不动），只是不摆出来（屏上不留别人的日志）。
  //   下面两件都是被用户报出来的"看着没了"，所以自己焊：
  //   ① `.term` 类要跟着上面的判断**加也去** —— 它一丢，终端就从画面上消失
  //      （而 xterm 其实还挂在那个节点上，画面看着就是"被清掉"）；
  //   ② 尺寸**变了才**重量 —— 原来每 200ms 都 fit 一次，而 xterm 往下缩时会真丢行。
  const pane = $("#pane-console");
  if (termViewing() && MOSS_TERM.term){
    if (pane && !pane.classList.contains("term")) pane.classList.add("term");
    if (pane){
      const vis = !!pane.offsetParent;
      // 这一页刚露头 ⇒ 把光标放进去（你要的就是"打开命令行就能直接敲"）
      if (vis && !MOSS_TERM.vis) MOSS_TERM.term.focus();
      MOSS_TERM.vis = vis;
    }
    termFitSoon();
  }else{
    if (pane && pane.classList.contains("term")) pane.classList.remove("term");   // 让位给 `#out`
    // 没在显示终端 ⇒ 把"露过头"的记号清掉：下次切回它那份时**重新给一次焦点**
    // （`V-348` 那条"打开命令行就能直接敲"，切包回来也要成立）
    MOSS_TERM.vis = false;
  }
}
/* 跑起来 / 跑完了各喊一声（`embed.js` 的两处）。★ `V-348`：**跑完要让 shell 再打一次提示符** ——
   不然终端停在包的最后一行上，"还能接着敲"这件事看着就不成立（提示符是它唯一的招牌）。 */
const TERMLIVE = {};
function paintInbar(key){
  CONSOLER.rev++;
  // ★ 用**调用方给的那个 key**（`embed.js` 起跑 / 收尾都是 `paintInbar(<包id>)`）——
  //   用户可能已经切去看别的包了，"谁的活干完了"得按它自己算，不能按"现在在看谁"。
  const k = key || consolePaneKey();
  const live = !!RUNS[k];
  const was = !!TERMLIVE[k];
  TERMLIVE[k] = live;
  if (termViewing() && k === consolePaneKey() && MOSS_TERM.term){
    // ★ 起跑 / 收工都把焦点还给终端：`embed.js` 那边是去 focus 底下那根 `#stdin`
    //   （终端模式里它是 `display:none`，focus 等于没做）⇒ 我点了「运行」之后一敲键盘
    //   谁也没收到，看着就像"敲不进去了"。
    // ★ `V-370`：只在"**这块屏正显示这个包的终端**"时才抢焦点 —— 屏上是别人/自己那份
    //   `<pre>` 的时候抢焦点，等于把光标从下面那根 input 上拽走。
    MOSS_TERM.term.focus();
    MOSS_TERM.hotUntil = Date.now() + 3000;
  }
  // 跑完了：让 shell 再打一次提示符，"接着敲"这件事才是看得见的
  // ★ `V-370`：只在这个包**就是这块屏的主人**（= 它确实跑在这条 shell 里）时才写这个回车 ——
  //   不然就是往"别人正在跑的东西"里塞了一个回车。
  if (was && !live && MOSS_TERM.on && MOSS_TERM.started && MOSS_TERM.owner === k) termWrite("\r");
}
function consolePaneKey(){ return consoleKey || "__host__"; }
/* 输入行那句占位话（`V-43`）：没在跑 / 跑完了 → 换一句，省得你以为发了没反应。
   ★ `V-367`：别用"没有输入这回事"这种自述口吻 —— 说清"这里为什么敲不了"。
   ★ `V-371`：**没在跑的时候这一行照样能用**（用户要的"像普通命令行那样直接敲"）——
     所以这时候的占位话是"在这儿敲命令"，不是"点运行去"。 */
function consoleInbarPlaceholder(key){
  if (RUNS[key]) return RUNS[key].term
    ? "这个包跑在终端里 —— 就在那块终端里敲"
    : "包在等你的回答就敲在这里，回车发送（比如 1 / 2 / 3）";
  if (key === "__host__") return "在这儿敲命令，回车执行（像普通命令行那样）";
  return consoleCwd(key)
    ? ("在这儿敲命令，回车就在" + consoleCwdLabel(key) + "里跑")
    : "在这儿敲命令，回车执行（像普通命令行那样）";
}
/* `V-371`：这一份"命令行"该从哪个目录起步 —— 它自己 `cd` 过就听它自己的；
   否则包 = 那个包的目录、历史 = 那次调用当初的目录；moss 自己那份没有目录这回事（回空串）。 */
function consoleCwd(key){
  if (!key || key === "__host__") return "";
  const b = consoleBuf(key);
  if (b.cwd) return String(b.cwd);                    // 这一份自己 cd 过（`V-371`）
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
      // `V-348`：看着终端的时候，那行字得说终端的事（是"谁的输出"在这里没意义）
      // ★ `V-370`：判据从"终端开着"改成"**现在显示的是终端**" —— 切到别的包时屏上是
      //   那个包自己的输出，这行字就得说清是**谁的**（不然又是一句没用的"DOS 终端"）
      if (termViewing()) return "DOS 终端（常驻） · " + termHintText();
      return consoleTitle(this.key) + " · " + (this.buf.info || "");
    },
    live(){
      this.R.rev;
      // `V-371`：**没在跑也让它能敲** —— 这一行现在"像普通命令行那样"能直接执行
      //   （终端那一版显示着的时候下面这根是藏着的，值不影响）
      return !!RUNS[this.key] || !this.term;
    },
    ph(){ this.R.rev; return consoleInbarPlaceholder(this.key); },
    // `V-348`：现在看的是不是那个常驻终端（`MOSS_TERM` 不是响应式对象，所以照旧登记 `R.rev`）
    // ★ `V-370`：`term()` 的语义 = "**这块屏是终端**"（而不是"终端开着"）—— 按钮的高亮、
    //   顶栏那句话、下面 `#out`/`#termhost` 谁露头，全认这一个判据。
    term(){ this.R.rev; return termViewing(); },
    termHint(){ this.R.rev;
      return termViewing()
        ? ("切回这个包自己的输出（现在是 DOS 终端 · " + termHintText() + "）")
        : "切到 DOS 终端"; },
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
    clearOut(){ if (termViewing()) return termClear(); setConsole(this.key, "", "还没跑过"); },
    copyOut(){ copyOut(); },
    rerun(){ rerunLast(); },
    send(){ sendConsoleLine(); },
    toggleTerm(){ termToggle(); },
  },
  // ★ `<pre>` 那一行**必须写在同一行**：换个行，模板里的空白就会进到输出里（`pre` 不折叠空白）。
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
  // 只有"**管道里的包**在等回答"才走这儿（终端里跑的 / 没在跑的都归 `sendConsoleLine` 分流）
  if (!run || run.term) return;
  const line = inp.value;
  inp.value = "";
  const b = consoleBuf(key);
  setConsole(key, (b.text || "").replace(/\n?$/, "\n") + line + "\n", b.info);
  const r = await pywebview.api.run_input(run.rid, line);
  if (!r || !r.ok) toast("✗ " + ((r && r.msg) || "发不出去"), true);
}

/* 输入行回车（`V-371`）：**这一行什么时候都能用**（用户要的"像普通命令行那样直接敲"）。
   · 管道里的包在等回答 ⇒ 老路：这一行发给它（`sendStdin`）；
   · 这个包跑在终端里 ⇒ 这一行敲进那块终端（等于在那块屏上敲，包自己收得到）；
   · 没在跑 ⇒ **在这一份自己的目录里跑这一行**（宿主另起一个一次性进程，见 `cmd_start`：
     `cd xxx` 只换这一份的当前目录；输出进这一份缓冲 —— 这样**不会**把命令塞进
     "别的包正跑着的那条共享 shell" 的 stdin 里）。 */
async function sendConsoleLine(){
  const key = consolePaneKey();
  const inp = $("#stdin");
  if (!inp) return;
  const run = RUNS[key];
  if (run && !run.term){ await sendStdin(); return; }
  const line = String(inp.value || "");
  if (!line.trim()) return;
  inp.value = "";
  // ① 跑在终端里的：还是"把这一行敲进那块终端"（那是它的 stdin）
  if (run && run.term){
    MOSS_TERM.owner = key;
    if (!(await termOpen(false, true))) return;
    const echo0 = MOSS_TERM.mode !== "conpty";
    if (echo0) termShow(line + "\r\n");
    termSubmitLine(line, "shell");
    MOSS_TERM.hotUntil = Date.now() + 3000;
    return;
  }
  // ② 没在跑：这一份自己的目录里跑这一行
  let r = null;
  try{ r = await pywebview.api.cmd_start(consoleCwd(key), line, key); }catch(e){ r = null; }
  const b = consoleBuf(key);
  if (!r || !r.ok){
    setConsole(key, (b.text || "") + (b.text ? "\n" : "") +
                    "✗ " + ((r && r.msg) || "跑不起来") + "\n", "失败");
    return;
  }
  if (r.cd !== undefined && r.cd !== null){
    b.cwd = String(r.cd || "");                       // 这一份「命令行」从此在这儿干活
    setConsole(key, (b.text || "") + (b.text ? "\n" : "") + "$ cd\n" + b.cwd + "\n", "就绪");
    return;
  }
  RUNS[key] = {rid: r.run_id, cmd: r.cmd || line, manual: true, stopped: false,
               switched: true, tabAtStart: tab};
  setConsole(key, "$ " + (r.cmd || line) + "\n", "运行中");
  paintInbar(key);
  paintRowStats();
  paintActions(selObj());
  pollRun(key);                                       // 和跑包同一个轮询：输出流进这一份缓冲
}
function setConsole(key, text, info){
  const b = consoleBuf(key);
  b.raw = String(text == null ? "" : text);      // `V-348`：原样留一份（终端要 ANSI，`<pre>` 要纯文本）
  b.text = stripAnsi(text);
  if (info !== undefined && info !== null) b.info = info;
  // `V-348`：看着终端的时候，这份输出要**流进终端**（不然跑包时终端是块死屏）
  termMirror(key, b.raw);
  if ((consoleKey || "__host__") === (key || "__host__")) paintConsole();
}
function out(text, info){ setConsole(consoleKey || "__host__", text, info); }
/* 复制全部输出。★ 复制完那句反馈**交给组件去显示**（`V-83`）：以前是直接
   `$("#outinfo").textContent = …` 写进 DOM —— 现在那是组件的 DOM，下一次重画就被盖掉，
   而且等于绕开 Vue 去改它管的东西。走 `CONSOLER.flash` 这条路，行为一样、不打架。 */
async function copyOut(){
  // `V-348`：看着终端的时候，复制的就是终端里那些东西（而不是"这个包那份输出"）
  // `V-370`：判据同上 —— 只有**屏上真是终端**时才复制终端那份（不然复制的是眼前这块）
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
      : '<button class="idle" title="运行这个包（﻿' + esc(PSYM + id) + '）">' + ico("play", "i") + '</button>';
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
  if (st.running){ toast(PSYM + id + " 已经在跑了"); return; }
  if (!cur || cur.id !== id) select(id, /*keepTab*/ true);
  startRun(p, "");
}

/* 列表里直接停掉：别管是谁起的，**显示「停止」就得真停**（`V-216`）——
   是这里起的 run 就走 run_stop（好把输出收尾）、内嵌那把走 embed_stop、
   其余（孤儿 / 从终端开的）按进程停。 */
async function stopFromList(id){
  let r;
  if (RUNS[id] && RUNS[id].term){          // `V-352`：跑在终端里的（真 Ctrl+C / 按进程杀）
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

/* ★ `V-379`：这个包**在跑吗**？三个来源缺一不可（并到一处，别在别处再抄一遍）：
     · `RUNS[id]`        —— 界面自己起的那一次（管道 / 终端那条路）
     · 内嵌界面          —— 包的界面开着（那也是一个进程）
     · `PST[id].running` —— 宿主报的（终端里跑的 / 更早留下的孤儿）
   寄生模式要判"在不在跑"（决定点不点那颗按钮），所以从 `paintActions` 里抽出来当**唯一判据**。 */
function pkgRunning(p){
  if (!p) return false;
  return !!(RUNS[p.id] || (embedSupported(p) && embedRunning(p.id)) ||
            ((PST[p.id] || {}).running));
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
  const running = pkgRunning(p);         // ★ `V-379`：判据收在 `pkgRunning` 一处
  b.disabled = !p;
  // ★ 颜色只在"运行中"时给（绿色停止图标）；不再按"上次是否非 0"染红/黄 —— 误报太多
  b.innerHTML = ico(running ? "square" : "play", running ? "i ic-run" : "i") +
                '<span>' + (running ? "停止" : "运行") + '</span>';
  b.title = !p ? "先在左边选一个包或一条历史"
               : (running ? ("停掉它（连同它拉起的子进程）" + runningHint(p.id))
                          : "运行这个包，输出进「命令行」");
  b.classList.toggle("warn", running);
  // ★ 详情命令栏那颗**分离式主按钮**（`#btn-runsplit`）：和右上角那颗「运行/停止」
  //   同一个状态、同一个动作。运行常用 ⇒ 它就该显眼；不常用的「新窗口运行」在下拉里。
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
  // ★ `V-303`：**没有开着的窗口就不显示这颗「显示」**（原来只是变灰，还是占着地方）
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

/* ================================================================ 命令行里的常驻 DOS 终端（`V-348`）
   ★ 它跟上面那套 `RUNS` / `run_input` **不是一回事**，别搞混：
       · 上面那套是"**一个包一次运行**"的管子 —— 包一退出管子就废，
         于是「一旦停止运行就没法继续执行 dos 命令」（你报的就是这条）。
       · 这里是一个**界面自己的 shell**：一直活着，命令跑完回到提示符，接着敲就行。
   ★ 视图是**加法**：`#out` 那套（这个包的输出）一个字都没动，终端只是 outbar 上多出来的
     一个视图（`#termhost`）。默认照旧看包的输出，点那颗终端图标才切过去 —— 这样预览工具里
     那两百来个场景、以及"包输出"这条老路都**不受影响**。
   ★ 谁负责"本地回显"：真终端（ConPTY）由 cmd 自己回显，前端**原样透传**；
     管道模式没有控制台（不回显、没行编辑）⇒ 那部分界面自己画（`termLocalTyping`）。 */
const MOSS_TERM = {
  // ★ 默认**就是**终端（`V-348` 第二版）。上一版把它做成了 outbar 上一颗开关 ——
  //   你的反馈很直接：「和之前没什么差别 …还是要在下面的 input 去敲」。命令行这一页
  //   本身就该是个终端，不该让你先去找一颗开关。起不来（老宿主 / 没 xterm）会自动退回
  //   下面那块 `<pre>`，并说一句为什么（`termOpen()` 的失败分支）。
  on: true,
  started: false,     // 会话起过没有（起了就一直活着，切走也不关）
  pending: null,      // 正在起会话（`termEnsureSession` 的在途 promise，防重入）
  failAt: 0,          // 上一次起失败的时刻（自动重试要歇一会儿，别变成刷屏式起进程）
  autoTried: false,   // 自动起过一次没有（成不成只试一次，别一直敲宿主）
  mode: "",           // conpty（真终端）/ pipe（兜底）
  alive: false,
  text: "",           // 本地留一份纯文本："复制全部"用它
  term: null, fit: null,
  fw: 0, fh: 0,        // 上一次量过的尺寸（**没变就不再 fit** —— 反复缩放会真丢行）
  vis: false,          // 上一次这一页露没露头（刚露头那一刻把光标放进终端）
  timer: null, busy: false, fitT: null,
  typed: "",          // "本地回显"攒的那一行（管道模式 / 包在等回答时都要用它）
  hist: [], hi: 0,    // 自己的 ↑↓ 历史（真终端模式下由 cmd 管）
  hotUntil: 0,        // 刚有过输出 / 按键 ⇒ 这段时间轮询勤一点（要跟手）
  mirror: {},         // key -> 这个包的输出"已经倒进终端多少"（增量，绝不重印）
  mirrorKey: "",      // 上一刻在看哪一份（切包时只打个招呼，不重印历史）
  // ★★ `V-370`：**这块终端屏现在算谁的**（key）；`""` = 空屏（谁都没在里面跑过 / 刚清过）。
  //   ★ 你报的现场：「我运行了 md5，点 IP查询（没运行），再点命令行 —— 里面是 md5 的运行日志，
  //     他们之间没做好隔离」。根因：常驻终端只有**一条 shell**（`V-348`/`V-352` 的设计），
  //     而这块屏以前是"终端开着就显示终端" ⇒ 切成 ip 之后屏上留着的还是 md5 那屏。
  //     现在：**屏归谁，就只在看谁的时候显示终端**；切到别的包 ⇒ 显示那个包自己那份输出
  //     （一份一份的，`CONSOLE[key]`）。终端会话不动、照旧在后台跑/攒输出，一键切回去。
  owner: "",
};
/* `V-370`：现在这块屏**是不是**终端（不是"终端开着没有"）。
   ★ 为什么不直接看 `MOSS_TERM.on`：`on` 是"会话活着、还在攒输出"，跟"要不要显示"是两件事。 */
function termViewing(){
  return !!MOSS_TERM.on && (MOSS_TERM.owner || "") === consolePaneKey();
}

/* 终端这几个接口在不在（宿主版本对不对）。
   ★ 预览工具里的假后端**没有** term_* 这几个方法 —— 不先问一句，一个 TypeError
     就能把整页带红（`V-81` 的老毛病：没有控制台，出错只能靠状态栏）。 */
function termApiReady(){
  return !!(window.pywebview && pywebview.api &&
            typeof pywebview.api.term_start === "function");
}
/* ★ 三态而不是两态：`wait`（桥还没插进来 —— `app.js` 的 boot 会等它，但别的入口不一定）
   和 `no`（宿主压根没这个接口：老宿主 / 预览里的假后端）**必须分开** ——
   混成一个的话，页面早一拍渲染就会把终端**永久判死**（然后你看到的又是"和之前没差别"）。 */
function termApiState(){
  if (!window.pywebview || !pywebview.api) return "wait";
  return termApiReady() ? "ok" : "no";
}
function termHintText(){
  const key = consolePaneKey();
  // 包在等你回答的时候，这一行字得说清"在哪儿敲"—— 现在就在终端里，不在底下那根 input 了
  if (RUNS[key]) return "这个包在等你回答 —— 在这里敲，回车发出去";
  if (!MOSS_TERM.started) return "常驻 DOS 终端 · 命令跑完还能接着敲";
  if (MOSS_TERM.mode === "conpty")
    return "真终端（Tab 补全 / Ctrl+C 都是 cmd 的）";
  // `V-367`：以前写「管道模式 · 界面自己回显」—— "界面自己回显"是**实现**（用户只关心能力差异）
  return "简化终端 · ↑↓ 有历史（没有 Tab 补全 / Ctrl+C）";
}

/* `V-348` / `V-352`：某个包的输出要不要**倒进终端**。
   ★★ 真终端（ConPTY）模式下**一个字节都不许倒** —— 这是用户当场抓出来的：
      那种流里带**绝对光标定位**（`[4;1H` 这种"把光标挪到第 4 行第 1 列"），
      管道里的文本一进去就被它覆盖，表现就是"包输出被替换掉了"。
      真终端里跑包改走**把命令敲进 shell**（`termRunPackage`），输出本来就来自 pty，
      屏幕上只有一个主人，从根上没有这个问题。
   ★ 管道后端没有光标定位这回事，倒进去是安全的 ⇒ 那条路照旧走下面的增量逻辑。 */
function termMirror(key, raw){
  const k = key || "__host__";
  if (k !== consolePaneKey()) return;
  const prev = MOSS_TERM.mirror[k];
  MOSS_TERM.mirror[k] = raw;
  if (MOSS_TERM.mode === "conpty"){
    if (MOSS_TERM.on && raw) termNeedPlainView(k);
    return;
  }
  if (prev === undefined || raw === prev) return;         // 刚切过来 / 没变化
  if (raw.length <= prev.length) return;                  // 变短了：基线对齐，一个字都不补
  // 接得上就补尾巴；接不上（长度对但内容重排过）也只补"多出来的那截"
  // ★ 任何情况下都不会把已经显示过的内容再显示一遍（重印就是刷屏）
  const out = raw.slice(prev.length);
  // `V-348`：倒进终端只在"**屏上正是终端**"的时候做（`V-370`）—— 屏上摆着别的包的输出时，
  //   再往里倒就等于"把 A 的日志倒进 B 那块屏"，切回 B 就看见了（又成了串台）。
  //   没倒的那些一个字都不丢：它就在 `CONSOLE[k]` 那份缓冲里，切过来照样看得见。
  if (termViewing() && MOSS_TERM.term && out) termShow(out);
}

/* 真终端模式下，**宿主的纯文本输出**（自检 / 历史 / 宿主命令那几条路）在这块屏上没地方放
   —— 倒进 pty 会被它的光标定位覆盖。所以老实**切回「包输出」那一版**给你看。
   ★ `V-367`：以前这里还 `toast()` 一句解释（"这次是宿主的纯文本输出 —— 先切回…"）——
     那是**写代码的人对自己说的话**，不该弹给用户（你点名的）。切换本身看得见：
     顶栏那颗按钮立刻变成「切回 DOS 终端」，想回去随时点。**一句都不说**。 */
function termNeedPlainView(k){
  const run = RUNS[k];
  if (run && run.term) return;            // 在终端里跑的：输出本来就在终端里，不许动
  // `V-370`：屏上本来就不是终端（在别人的/自己的那份 `<pre>` 上）⇒ 没什么可切的，
  //   别顺手把会话的显示关掉（关了就轮到"下次进这一页看不到终端"那个老毛病）
  if (!termViewing()) return;
  termHide();
}

/* 这一页一露头就把终端起起来（**默认就是终端**，不用你去点开关）。
   ★ 宿主没这接口（老宿主 / 预览里的假后端）⇒ 老实退回 `<pre>` 那套，**不吵**（不起会话、
     不 toast）—— 界面照旧能用，这才是"终端坏了不许连坐界面"。 */
function termAutoStart(){
  if (!MOSS_TERM.on || MOSS_TERM.autoTried || MOSS_TERM.pending) return;
  if (MOSS_TERM.failAt && Date.now() - MOSS_TERM.failAt < 15000) return;   // 刚失败过：歇一会儿
  const st = termApiState();
  if (st === "wait") return;                    // 桥还没到：等下一次（**别急着判死**）
  if (st === "no"){ MOSS_TERM.on = false; return; }   // 老宿主 / 预览：老实退回 `<pre>`，不吵
  const pane = $("#pane-console");
  if (!pane || !pane.offsetParent) return;      // 这一页还没露头，等下一次
  MOSS_TERM.autoTried = true;
  termOpen(true);            // `V-367`：自己开的，起不来就悄悄退回 `<pre>`
}

function termEnsure(){
  if (MOSS_TERM.term) return true;
  if (typeof window.Terminal !== "function"){
    toast("✗ 终端用不了：终端组件没加载上", true);      // `V-367`：别报库名和仓库路径
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
    // ★ `convertEol`：把裸 `\n` 当"回车 + 换行"。管道那头的程序常常只给 `\n`，
    //   不转的话每一行都会比上一行右移一格（经典的阶梯状错位）。
    convertEol: true,
    theme: {background: pick("--out-bg", "#14161a"),
            foreground: pick("--out-fg", "#d7dae0"),
            cursor: "#7fb3ff", selectionBackground: "#3a5a8c"},
  });
  MOSS_TERM.term = t;
  try{
    // ★ addon 的 UMD 全局是**命名空间**：类是 `FitAddon.FitAddon`（不是 `FitAddon` 本身）。
    //   写错这一处不会报错，只是 fit() 永远不生效 —— 实测过。
    MOSS_TERM.fit = new FitAddon.FitAddon();
    t.loadAddon(MOSS_TERM.fit);
  }catch(e){
    MOSS_TERM.fit = null;      // 没量尺也不致命：列数会一直是默认的
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
  // 这一页没在显示的时候量出来是 0×0（别把列数算成 0 发给后端）
  if (!host || !host.offsetParent) return;
  const w = host.clientWidth, h = host.clientHeight;
  // ★★ 太矮就别量：缩到一两行的时候，xterm 会把超出的行**真的丢掉**（内容就没了）。
  if (h < 60 || w < 80) return;
  // ★★ 尺寸**没变就别碰它**。以前是每 200ms 无条件 fit 一次，紧接着下面那句 resize ——
  //    只要高度在抖（顶栏文字换行、页脚变化…），xterm 就会被反复缩放，而**每次往下缩都丢行**。
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
  // ★★ `V-370`：**跑在这块屏里的那个包，它的输出也留一份到它自己那份缓冲里** ——
  //   跑在终端里的包原来只"活在屏上"：切走再切回来（或跑完以后）就只剩"这块屏碰巧还剩什么"，
  //   甚至显示成「还没有输出」。留了底之后，每个包的「命令行」都是**它自己那一份**，
  //   终端只是"跑在它里面的那块屏"（`#out` 那份是等价的只读副本，`stripAnsi` 过）。
  const o = MOSS_TERM.owner;
  if (o && RUNS[o] && RUNS[o].term){
    const c = consoleBuf(o);
    c.raw = (c.raw || "") + text;
    c.text = stripAnsi(c.raw);
    // 正看着这一份、而屏上摆的是它自己那块 `<pre>`（把终端切走了）⇒ 得让它跟着长
    if ((consoleKey || "__host__") === o && !termViewing()) CONSOLER.rev++;
  }
}
function termClear(){
  if (MOSS_TERM.term) MOSS_TERM.term.reset();
  MOSS_TERM.text = "";
  MOSS_TERM.typed = "";
  // 屏都清了，镜像基线也跟着重来 —— 不然下一段输出会被当成"接着上次流"而丢掉前半截
  MOSS_TERM.mirror = {};
  // `V-370`：屏空了 ⇒ 这块屏**归当前在看的这一份**（清掉之后屏上没有任何人的日志了，
  //   留着"归上一个包"的记号只会让下一个包的输出没法显示在这里）
  MOSS_TERM.owner = consolePaneKey();
}
function termWrite(text){
  if (!termApiReady()) return;
  MOSS_TERM.hotUntil = Date.now() + 2500;
  try{
    pywebview.api.term_write(text).then(r => {
      // 后端说"给不了"（比如管道模式的 Ctrl+C）就如实说一句，别装作发出去了
      if (r && !r.ok && r.msg) toast(r.msg, true);
    }).catch(() => {});
  }catch(e){}
}

/* 轮询。★ 只有"正在看终端"的时候才轮 —— 不看就别问（省电、也省得宿主白忙）。
   刚有输出/按键的那 2.5 秒按 45ms 问，闲下来退到 220ms：又跟手，又不至于一直在敲宿主。 */
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
          // shell 自己退了（被人 taskkill / 崩了）：如实说，并把"会话还在"这件事清掉。
          // 标了 started=false 之后这段不会再说第二遍。
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
  // 老的管道那条路：`run_input` 只收整行 ⇒ 本地回显 + 攒够一行再发。
  // ★ 在终端里跑的包（`run.term`）**不走这儿**：它的 stdin 就是这个控制台，
  //   真终端直接透传，包自己能收到（连方向键、Ctrl+C 都是真的）。
  if (run && !run.term){ termLocalTyping(d, "pkg"); return; }
  if (!MOSS_TERM.started) return;
  if (MOSS_TERM.mode === "pipe"){ termLocalTyping(d, "shell"); return; }
  termWrite(d);                    // 真终端：原样透传（回显、行编辑都是 cmd 的活）
}

/* "本地回显 + 行编辑"。两种时候会走它：① 管道后端（没有控制台，cmd 不回显也没行编辑）；
   ② 包在等你回答（`run_input` 只收整行）。★ 真终端 + 没包在跑时**一次都不会跑**。 */
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
        // 包在等回答 ⇒ Ctrl+C 的意思就是"别答了，停下"（走现成那条停的路，三种起法都认）
        termShow("^C\r\n");
        stopFromList(consolePaneKey());
      }else{
        termShow("^C\r\n");
        termWrite("\x03");         // 管道后端会如实回"给不了"，界面 toast 一句
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
    // 其余（左右方向键 / Delete / 不认识的控制字符）**什么都不做**。
    // ★ 为什么不"假装"支持：光标只在行尾，假装能移动只会让人以为中间的字能改
    //   —— 家规是"不许静默假装成功"。
  }
}

/* 把 xterm 送来的一串按键拆成"一个键一个记号"：转义序列要整体认识，
   拆成字符会把 `\x1b[A` 这种回显成 `^[[A` 那一堆乱码。 */
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

/* 回车之后这一行去哪儿：包在等 ⇒ 发 `run_input`；否则 ⇒ 发给 shell（当一条 DOS 命令）。 */
function termSubmitLine(line, kind){
  if (kind === "pkg"){
    const key = consolePaneKey();
    const run = RUNS[key];
    if (!run){ termWrite(line + "\r"); return; }   // 正好在这一刻跑完了 ⇒ 当 DOS 命令发出去
    try{
      pywebview.api.run_input(run.rid, line).then(r => {
        if (!r || !r.ok) toast("✗ " + ((r && r.msg) || "发不出去"), true);
      }).catch(() => {});
    }catch(e){ toast("✗ 发不出去：" + e, true); }
    return;
  }
  termWrite(line + "\r");          // 后端会把它补成 \r\n —— 管道那头的 cmd 是按行读的
}

/* ================================================================ 在终端里跑包（`V-352`）
   点「运行」不再另起一根管道，而是**把 `moss --pkg <id>` 敲进这个 shell**。
   于是：包的输出自然落在终端里（屏幕只有一个主人）、它的 `input()` 直接读控制台
   （真终端里 `isatty()` 是真的）、Ctrl+C 是真中断、跑完提示符自己回来。
   ★ 两个后端都行：真终端靠 pty 的输入；管道靠 cmd 把 stdin 转给子进程。 */
/* "终端能不能用来跑包" —— 判的是**会话**（起过、有后端、接口在），
   **不是"现在看不看得见它"**。
   ★★ 这一条是用户报出来的血：以前要求 `MOSS_TERM.on`，于是你切去看一眼「包输出」
      （或任何一次"宿主的纯文本输出"触发了我那个自动切换）之后，**点「运行」就永远走老路**
      —— 老路就是 `<pre>` + 底下那根 input，正是他说的"又回到之前的模式"；
      而且 `termHide()` 之后没有任何东西会把它拉回来 ⇒ **单向门**。
      现在点「运行」自己会把会话起起来、并把这一版切回来（见 `termRunPackage`）。 */
function termWhyNot(){
  // `V-367`：这几句会经 `termOpen` 弹给用户 ⇒ 只说"这个版本没有终端"，别报接口名
  if (!termApiReady()) return "这个 moss 版本里没有终端功能";
  if (typeof pywebview.api.term_run !== "function") return "这个 moss 版本里没有终端功能";
  if (!MOSS_TERM.started || !MOSS_TERM.mode) return "终端会话还没起来";
  return "";
}
function termCanRun(){ return termWhyNot() === ""; }

async function termRunPackage(p, args, cwd){
  // ① 宿主压根没这套接口（老宿主 / 预览里的假后端）⇒ **不吵**，直接走老路
  //    （和以前的行为一模一样，这就是"终端坏了不许连坐"）
  if (!termApiReady() || typeof pywebview.api.term_run !== "function") return false;
  // ② 接口在、会话没起 ⇒ 起（"点运行"本身就是"我要用终端"）
  if (!MOSS_TERM.started || !MOSS_TERM.mode){
    const r0 = await termEnsureSession();
    // `V-367`：起不来就**悄悄退回老路**（那次跑照旧会发生，界面上那条"正在跑…/跑完了…"
    //   才是用户该看到的话）。以前这里先报一句"✗ 终端起不来…—— 这次走老路子跑它"，
    //   等于给一次**成功的**运行先扣一顶失败的帽子，一次点两个提示。
    if (!r0.ok) return false;
  }
  // ③ 视图切回终端（他刚才可能在看「包输出」/ 刚从别的页过来）
  if (!MOSS_TERM.on && !(await termOpen(true))) return false;
  // ④ 把命令敲进去
  let r = null;
  try{ r = await pywebview.api.term_run(p.id, args || "", cwd || ""); }catch(e){ r = null; }
  if (!r || !r.ok){
    // 发不进去（终端刚死 / 宿主版本不对）⇒ 返回 false，让调用方**退回老的管道那条路**
    // `V-367`：同上 —— 退回是安静的，不报错、不解释（老路会照常给出运行反馈）
    return false;
  }
  // 管道后端没人替你回显（真终端由 cmd 自己回显）
  if (MOSS_TERM.mode === "pipe") termShow("\r\n" + (r.cmd || "") + "\r\n");
  lastRun = {id: p.id, args: args, label: r.cmd || ("moss " + PSYM + p.id)};
  consoleKey = p.id;
  RUNS[p.id] = {term: true, cmd: r.cmd || "", t0: Date.now(), stopped: false,
                switched: true, tabAtStart: tab};
  // ★★ `V-370`：命令已经敲进这块屏了 ⇒ **这块屏从此归这个包**（哪怕原来是别的包的日志：
  //   新的一跑就接管，屏上从这一行往下都是它的）。这样"选回这个包"就能直接看到它跑，
  //   而切到别的包时屏上是那个包自己的输出（隔离）。
  //   ★ 顺序：`RUNS` 先落下再重画 —— `paintConsole()` 会让 Vue 重算 `live`/顶栏那行字。
  MOSS_TERM.owner = p.id;
  paintConsole();
  setStatus("正在跑 " + (RUNS[p.id].cmd || ""));      // 状态栏（`V-61`）
  // 从「详情」点的「运行」⇒ 把你带到「命令行」看它跑（`U-16` 那个"别把人拽走"照旧：
  // 已经在别处看东西的话不动你）。包现在跑在终端里，"看它跑"和"跟它对话"是同一件事。
  if (tab === "detail") setTab("console");
  paintInbar(p.id);                                   // 按钮变「停止」+ 焦点还给终端
  paintRowStats();
  paintActions(selObj());
  MOSS_TERM.hotUntil = Date.now() + 3000;             // 接下来这一会儿轮询勤一点
  termWatchRun(p.id);
  return true;
}

/* 在终端里跑的那个包，怎么知道跑完了：问宿主"这个包的进程还在不在"（`pkg_states`）。
   ★ 退出码**不用我编** —— moss 自己会在终端里打 `[退出码] N` 那一行，比我说得准。
   ★ 每 700ms 问一次；跑完清状态、让 shell 再打一次提示符（那是 `paintInbar` 的钩子干的事）。 */
function termWatchRun(id){
  const run = RUNS[id];
  if (!run || !run.term) return;
  if (Date.now() - run.t0 > 6 * 3600 * 1000){          // 兜底：别无限问下去
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
  paintInbar(id);            // ← 它负责"让 shell 再打一次提示符" + 把焦点还给终端
  setTimeout(refreshAllStates, 400);
}

/* 停掉一个跑在终端里的包。
   ★ 真终端能发**真 Ctrl+C**（往 pty 里写 `\x03` —— 那才是控制台的中断键）；
     管道后端没有控制台可发中断，只能请宿主按进程杀（`pkg_stop`）。 */
async function termStop(id){
  const run = RUNS[id];
  if (!run) return {ok: true, msg: "它已经结束了"};
  clearTimeout(run.timer);
  let r;
  if (MOSS_TERM.mode === "conpty"){
    termWrite("\x03");
    r = {ok: true, msg: "已发送 Ctrl+C，结果在终端里"};      // `V-367`：说结果，不说"往哪儿写了什么"
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

/* 起会话（幂等）。`termOpen()` 和「点运行」都走它 —— 返回 `{ok, why, mode}`。
   ★ 失败原因要**带回去**（不许只说"起不来"）：屏幕上只留一句 toast 的话，
     我根本不知道是哪一条判据挂的（这一轮就吃了这个亏）。 */
function termEnsureSession(){
  if (MOSS_TERM.started && MOSS_TERM.mode) return Promise.resolve({ok: true, mode: MOSS_TERM.mode});
  if (MOSS_TERM.pending) return MOSS_TERM.pending;
  if (!termApiReady()) return Promise.resolve({ok: false, why: "这个 moss 版本里没有终端功能"});
  if (!termEnsure()) return Promise.resolve({ok: false, why: "终端组件没加载上"});
  const t = MOSS_TERM.term;
  MOSS_TERM.started = true;                    // 先占位，免得同时起两次
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
        // `V-367`：宿主那条 `note`（"取不到 conpty 模块…"、"这个环境里 ConPTY 读不到子进程输出…"）
        //   是**写代码的人看的**，不弹给用户；降级的事实下面那行提示已经说清了
        //   （「管道模式 · 界面自己回显，↑↓ 有历史（没有 Tab 补全 / Ctrl+C）」）。
        //   `note` 照样留在 payload 里（`term_state` / `--term-selftest` 还能查）。
        done({ok: true, mode: MOSS_TERM.mode});
      }).catch(e => done({ok: false, why: String(e)}));
    }catch(e){ done({ok: false, why: String(e)}); }
  });
  return MOSS_TERM.pending;
}

/* 打开终端这一版（默认那条路，也从那颗开关走）。返回 Promise<boolean>。
   ★ 起不来就**老实退回 `<pre>` 那套**（`on=false` + 去掉 `.term`）—— 宁可让你看见老的那块
     输出，也别给你一块黑屏。
   ★ 但**不许判死**：`autoTried` 放回去，下次（点运行 / 切回这一页）还给它机会。
   ★ `V-367`：`quiet` = 这次是**界面自己**要开终端（进页面自动开 / 点运行顺手开），
     起不来就**悄悄退回老路**，不弹字 —— 用户没点过任何东西，不该收到一条失败通知
     （"宿主没有终端接口（term_start）" 这种话本来是给写代码的人看的）。
     只有用户**自己点了那颗开关**（`termToggle`）才说一句为什么。
   ★★ `V-370`：多一个 `claim` = "**用户自己点的**，这块屏就归当前这个 key"。界面自己开的
     不许抢：终端上要是还留着**别的包**的日志（`owner` 是别人），就只把会话热着、不摆出来
     （屏上摆那个包自己的输出）—— 这就是"包和包之间没隔离"那条的修法。 */
async function termOpen(quiet, claim){
  const pane = $("#pane-console");
  const key = consolePaneKey();
  // 会话已经活着：剩下的只是"这块屏归谁"（不用再起一次）
  if (MOSS_TERM.on && MOSS_TERM.started){
    if (claim) MOSS_TERM.owner = key;           // 用户点的：认领
    paintConsole();
    if (termViewing()) termPump();
    return true;
  }
  MOSS_TERM.on = true;
  MOSS_TERM.autoTried = true;
  // 空屏（谁都没在里面跑过 / 刚清过）谁来都能用 ⇒ 认下当前这个（保住 `V-348` 的
  // "进这一页就是终端"）；屏上留着别人的日志时**不认**（`claim` 除外）
  if (claim || !MOSS_TERM.owner || MOSS_TERM.owner === key) MOSS_TERM.owner = key;
  MOSS_TERM.fw = 0; MOSS_TERM.fh = 0;      // 重新露头了：尺寸要重新量
  if (pane && termViewing()) pane.classList.add("term");
  CONSOLER.rev++;                  // ★ 别走 paintConsole：它又会去喊 termAutoStart
  const r = await termEnsureSession();
  if (!r.ok){
    MOSS_TERM.on = false;
    MOSS_TERM.autoTried = false;           // ★ 别判死（下一轮还试）
    MOSS_TERM.failAt = Date.now();         // 但别每帧都试（15 秒冷却）
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
  // `V-370`：判据是"**这块屏现在是不是终端**" —— 屏上是别的包的日志时，这里是"切过去"，
  //   而且这一次是用户自己点的 ⇒ 认领这块屏（`claim`）。
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
/* 窗口尺寸变了要重量（不重量列数就是旧的，长命令会串行）。
   ★ 这里**只是量尺寸**，绝不关会话 —— 会话在宿主那边，界面切页 / 刷新都不影响它，
     这正是"命令跑完还能接着敲"能成立的原因。 */
window.addEventListener("resize", () => { if (MOSS_TERM.on) termFitSoon(); });
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && MOSS_TERM.on) termPump();
});

/* ---------------------------------------------------------------- 挂载（放最后）
   ★ 必须在 `RUNS` / `PST` / `consoleKey` 这些 `const`/`let` **声明之后**：`mountVue()`
     当场就会渲染一次，模板里的 `live` / 占位话要读 `RUNS` —— 早一步就是
     `Cannot access 'RUNS' before initialization`（`V-79` 踩过同一个坑）。 */
mountVue(MossConsole, "#pane-console", {ico: ico});
