/* moss 界面 · embed.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 内嵌界面（`V-48` ✅）
   包自己带一份网页界面（`pkg.json` 的 `ui.embed`），我们把它塞进第四个选项卡的 iframe 里，
   它的**后端还是那个包自己的进程**（宿主起它时给 `MOSS_UI_EMBED=1`，它就不开窗口、
   改在 stdio 上说 JSON 行）。

   三件事在这里合上：
     · iframe 里 `moss.call("bmi", {...})` → 包的垫片 postMessage 给我 → 我转给宿主
       （`embed_send`）→ 宿主原样写进那个进程的 stdin；
     · 进程回的行（`{` 开头的才是消息）→ 宿主 `evaluate_js` 调 `__mossEmbedFromBackend`
       → 我 postMessage 回**那个** iframe → 垫片 resolve 那个 Promise；
     · 宿主还能反过来发事件（`invoke` / `visible` / `theme`）—— 就是"我们怎么调用它的代码"。

   ★ **切走不关**（你要的那条）：切到别的选项卡、甚至切去开**另一个包**的界面，
     这一帧都只是被藏起来（`display:none`），页面和后端进程都照旧 ——
     所以这里是**一个包一帧**（`EMB.alive`），不是共用一帧。 */
const EMB = {alive: {}, tick: null, floated: {}};
/* `EMB.floated[pid]` = 这一帧被**弹出成窗口**了（`V-192`）：
   主窗口这边不再持有帧（同一个后端不能有两个帧 —— `EMB.alive[pid].frame` 是单帧引用），
   给个占位让人点一下收回。浮动窗口那边是 `FLOAT_PID`（见 app.js），它持有帧。 */

function embedSupported(p){ return !!(p && p.ui && p.ui.embed); }
/* 包界面该从哪个地址加载 —— **问宿主**（`V-55` ✅）。
   ★ 这里原来是拼 `file://`，结果在 WebView2 里**根本不导航**（帧是空的、连 `load` 都不触发；
     同一个页面在普通 Edge 里却正常）。宿主改成给一个 `http://127.0.0.1:<随机端口>/<随机 token>/…`
     的地址之后 WebView2 就正常了 —— 顺带把 `file://` 那两个限制（fetch / localStorage）也解了。 */
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
  // ★ `#embed-empty` 那句「还没跑」现在由组件按"有几帧活着"自己显隐（`v-show`，`V-84`）——
  //   这里不再直接写它的 display：那是组件的 DOM，写了也会被下一次重画盖掉。
  // 只让**露出来那一帧**收到 visible=true
  Object.keys(EMB.alive).forEach(id => pushEmbedEvent(id, "visible", {visible: id === pid}));
}

async function embedOpen(p, opts){
  const o = opts || {};
  if (!embedSupported(p)) return;
  const rec = EMB.alive[p.id];
  if (!rec){                                   // 没起过：起后端 + 建帧
    const r = await pywebview.api.embed_start(p.id);
    if (!r || !r.ok){ toast("✗ 起不来：" + ((r && r.msg) || ""), true); return; }
    const f = await embedFrameFor(p);
    if (!f){ await pywebview.api.embed_stop(p.id); return; }   // 界面拿不到地址：别留个空进程
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
  if (rec && rec.frame) rec.frame.remove();     // 这一帧也撤掉（进程都停了，留着没意义）
  delete EMB.alive[pid];
  delete EMB.floated[pid];                      // 停掉了就不再是"弹出去了"（`V-192`）
  if (!Object.keys(EMB.alive).length) embedTick(false);
  embedShow(Object.keys(EMB.alive)[0] || null);  // 还有别的在跑就接着显示它
  paintEmbedTab(); paintActions(selObj()); EMBR.rev++;
  setTimeout(refreshAllStates, 400);            // ★ `V-216`：停完立刻对一次状态，别等 2.5 秒那一轮
}
function embedRunning(pid){ return !!EMB.alive[String(pid)]; }

/* 宿主 → 某一帧（事件） */
function pushEmbedEvent(pid, name, data){
  const rec = EMB.alive[pid];
  const f = rec && rec.frame;
  if (!f || !f.contentWindow) return;
  try{ f.contentWindow.postMessage({moss: 1, kind: "event", name: name, data: data}, "*"); }
  catch(e){}
}
/* 后端进程的输出（宿主那条路送进来）：带上是谁的，才好送回**那一帧** */
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

/* ---------------------------------------------------------------- 浮动窗口（`V-192` / `V-194`）
   宿主开第二个窗口、把这一帧搬过去 —— **后端进程一步不动**。这里只做两件收尾：
     · 被人点了最小化 → 宿主喊 `__mossFloatDock`：把帧建回主窗口这一页；
     · 窗口被人关掉（或按了停止）→ 宿主喊 `__mossFloatClosed`：那一帧没了、后端也停了。 */
window.__mossFloatDock = async function(pid){
  pid = String(pid);
  EMB.floated[pid] = false;
  EMBR.rev++;
  const p = (DATA.packages || []).find(x => String(x.id) === pid);
  if (p && embedSupported(p) && !EMB.alive[pid]){
    await embedOpen(p, {keepTab: true});       // 后端还活着 ⇒ `embed_start` 直接复用
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
  // `V-367`：括号里那句"关掉窗口 ＝ 结束"是**规则说明**（浮动窗口顶栏已经写着"点关闭就结束
  //   这个包"），提示里只留事实
  toast("这个包已经停了");
};
/* 帧里发过来的（垫片的请求 + ready）：靠 `ev.source` 认出是哪一帧 */
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
    // 这一帧上正有人拖着东西（`V-204`）：跨文档的 drag 事件不会冒到我们这儿，
    // 得靠它报信 —— 我们铺一张罩子把拖放接过来，真实路径才拿得到。
    if (typeof frameDrag === "function") frameDrag(pid, m.phase);
  }
});
/* 「界面」选项卡该不该出现 —— 那颗按钮在**选项卡那一行**（不在这一页里，`V-84`），
   所以这部分仍然命令式；页里的标题 / 状态字由组件自己算（这里只举牌喊它重画）。 */
function paintEmbedTab(){
  const tabBtn = document.querySelector('.tab[data-tab="embed"]');
  const ok = embedSupported(cur);
  if (tabBtn){
    tabBtn.hidden = !ok;
    if (!tabBtn.dataset.painted){                    // 图标只画一次
      tabBtn.dataset.painted = "1";
      tabBtn.innerHTML = ico("app-window", "i") + '<span>界面</span>';
    }
  }
  if (!ok && tab === "embed") setTab("detail");
  EMBR.rev++;
}

/* ---------------------------------------------------------------- 「界面」那一页（Vue 组件，`V-84`）
   薄组件：顶上一小条（标题 / 状态字 / 重载·独立窗口两颗按钮）+ 下面那块 `#embed-wrap`。
   ★ iframe **不进模板**：一帧 = 一个包自己的后端进程，切走只是藏起来（`V-48` 那条要求），
     所以帧还是"谁需要谁往里 append"（`embedFrameFor`）。模板里 `#embed-wrap` 的子节点
     是**稳定**的（只有一个 `#embed-empty`，而且用 `v-show` 不是 `v-if`）——
     这样 Vue 重画时只动它自己那一个节点，不会去碰我们塞进去的那些帧。
   ★ 顺手补上两颗按钮的图标：它们原来**没画**（`V-48` 起就是两个空按钮，谁也看不出来
     是干什么的），现在跟别处一样走 `v-html='ico(...)'`。 */
const EMBR = Vue.reactive({rev: 0});

const MossEmbed = {
  name: "moss-embed",
  data(){ return { R: EMBR }; },
  computed: {
    p(){ this.R.rev; return embedSupported(cur) ? cur : null; },
    title(){ this.R.rev; const p = this.p; return p ? (p.ui.title || p.name || "界面") : "界面"; },
    aliveN(){ this.R.rev; return Object.keys(EMB.alive).length; },
    // 这一页是**浮动窗口**那一份吗（`V-192`：同一份页面，靠 `#float=<id>` 分流）
    // ★ 读 `window.__mossFloatPid`（`core.js` 里定义），**不读** app.js 里的 `FLOAT_PID`：
    //   这个组件是**当场挂载**的，那一刻 app.js 还没跑到 —— 直接读它就是一个
    //   `ReferenceError: FLOAT_PID is not defined`，页面一启动就报错（`V-202` 实测）。
    isFloat(){ return !!window.__mossFloatPid; },
    // 当前这个包的帧是不是已经被弹到窗口里去了（主窗口这一侧显示占位）
    floatedHere(){ this.R.rev; const p = this.p; return !!(p && EMB.floated[p.id]); },
    info(){
      this.R.rev;
      const p = this.p;
      if (!p) return "";
      if (window.__mossFloatPid)          // 浮动窗口：说清那两颗按钮是什么意思
        return embedRunning(p.id) ? "浮动窗口 · 点最小化＝收回主窗口，点关闭＝结束这个包" : "还没起";
      if (EMB.floated[p.id]) return "已经弹到窗口里去了（那边最小化就回来）";
      if (!embedRunning(p.id)) return "还没跑 —— 点右上角「运行」就起";
      const n = this.aliveN;
      return "这个包的界面正在这一页里运行 · 切走也不会停" +
             (n > 1 ? ("（另外还有 " + (n - 1) + " 个也在跑）") : "");
    },
  },
  methods: {
    // 重载这一页（只重载**当前这个包**那一帧）
    reload(){
      const rec = cur && EMB.alive[cur.id];
      if (rec && rec.frame) rec.frame.src = rec.frame.src;
    },
    /* 弹出为窗口（`V-192`）：**先拆掉这一页的帧**，再让宿主开第二个窗口 —— 后端一步不动。
       顺序不能反：同一个后端只许有一个帧（`EMB.alive[pid].frame` 是单帧引用）。 */
    async floatOut(){
      const p = this.p;
      if (!p) return;
      const rec = EMB.alive[p.id];
      if (rec && rec.frame) rec.frame.remove();
      delete EMB.alive[p.id];
      if (!Object.keys(EMB.alive).length) embedTick(false);
      EMB.floated[p.id] = true;
      EMBR.rev++;
      const r = await pywebview.api.ui_float(p.id);
      if (!r || !r.ok){                     // 开不出来就恢复原样，别让人对着一块空的
        EMB.floated[p.id] = false;
        toast("✗ " + ((r && r.msg) || "弹不出来"), true);
        await embedOpen(p, {keepTab: true});
        return;
      }
      toast(r.msg);
      paintEmbedTab(); EMBR.rev++;
    },
    /* 收回：让宿主把那扇窗关掉，然后这边把帧建回来（后端还活着 ⇒ 直接复用） */
    async floatBack(){
      const p = this.p;
      if (!p) return;
      const r = await pywebview.api.ui_dock(p.id);
      EMB.floated[p.id] = false;
      await embedOpen(p, {keepTab: true});
      if (r && r.msg) toast(r.msg);
    },
    /* 浮动窗口里的「停止」＝ 结束（和那颗 X 一个意思，`V-194`）。
       ★ `V-367`：**这里不再 toast** —— 宿主紧接着会推 `__mossFloatClosed`，那一条才是
         用户该看到的收尾（以前两条一起弹，说的都是"它停了"）。 */
    async floatStop(){
      const p = this.p;
      if (!p) return;
      await pywebview.api.ui_float_stop(p.id);
    },
  },
  template: `
    <div id="embed-bar">
      <span id="embed-title">{{ title }}</span>
      <span id="embed-info" class="dim">{{ info }}</span>
      <span style="flex:1"></span>
      <!-- 浮动窗口里**整条都不显示**（CSS：body.float #embed-bar{display:none}）——
           那一页就是一扇"这个包自己的窗口"：窗口标题上已经有名字，
           最小化＝收回主窗口、关闭＝结束这个包（V-194），不需要再摆一条。 -->
      <button id="btn-embed-reload" class="iconbtn" title="重新加载这一页"
              v-html='ico("refresh-cw", "i")' @click="reload()"></button>
      <button v-if="!isFloat" id="btn-embed-window" class="iconbtn"
              title="弹出为窗口（在那边点最小化就收回、点关闭就结束）"
              v-html='ico("app-window", "i")' @click="floatOut()"></button>
    </div>
    <div id="embed-wrap">
      <div id="embed-floated" v-if="floatedHere" @click="floatBack()">
        <span v-html='ico("app-window", "i")'></span>
        <span>已经弹到窗口里了 —— 点这里收回（或点那个窗口的最小化）</span>
      </div>
      <div id="embed-empty" class="empty" v-show="!aliveN && !floatedHere">
        还没跑 —— 点右上角「运行」就在这一页里开起来</div>
    </div>`,
};
/* 把**包自己的图标**光栅化成 PNG 交给宿主，当浮动窗口的窗口图标（`V-195`）。
   ★ 为什么在页面这边画：Windows 的窗口图标只认 HICON，而包图标大多是 **svg**
     （`icon.svg`，`currentColor` 的线条画）—— 浏览器正好是个现成的光栅化器，
     省得为这一个功能引 svg 渲染库。宿主收到再存成多尺寸 .ico 交给 `LoadImageW`。
   ★ 图标是锦上添花：任何一步失败都**不吭声**（窗口照开，只是顶着 moss 的图标）。 */
async function pushWindowIcon(p){
  try{
    if (!p) return;
    let src = "";
    if (p.icon_svg){
      // svg 里是 `currentColor`：放进 <img> 会被当成黑色，深色任务栏上就看不见了 ——
      // 换成主题强调色。顺带把 width/height 提到 256，让浏览器**按 256 光栅化**（不糊）。
      const svg = String(p.icon_svg)
        .replace(/currentColor/g, "#0071e3")
        .replace(/width="24"/, 'width="256"').replace(/height="24"/, 'height="256"');
      src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
    } else if (p.icon){
      src = p.icon;                       // 非 svg 的包图标，宿主已经给成 data URI 了
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

/* 后端那些"不是消息"的输出（宿主横幅、包自己的 print）→ 捞进命令行面板 */
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
/* 这个定时器**只在真有内嵌进程在跑时**才转（常开既白费电，Node 里还会让进程赖着不退） */
function embedTick(on){
  if (on && !EMB.tick) EMB.tick = setInterval(embedPollConsole, 1000);
  if (!on && EMB.tick){ clearInterval(EMB.tick); EMB.tick = null; }
}
async function clickRun(p){
  /* 历史条目：跑 / 停都按 `histKey` 走（那才是它的命令行缓冲区键）。 */
  if (isHist(p)){
    const key = histKey(p);
    if (RUNS[key]){ await stopRun(key); return; }
    rerunHist(p, argsInput() ? argsInput().value : undefined);
    return;
  }
  const st0 = PST[p.id] || {};
  // ★ `V-216`（用户报的"提示跑完了、界面还显示在运行"）：**按钮显示「停止」就得真能停**。
  //   以前这里是「带内嵌界面的包：没起过就 embedOpen，起过就 embedStop」—— 于是**别的路径**
  //   留下的进程（更早那次启动的孤儿、从终端开的、我这侧起的 run）会让按钮显示「停止」，
  //   而点下去**不去停它、反而把内嵌后端又起了一个** ⇒ 那个包就永远停在"运行中"、按不掉。
  //   现在按"谁在跑"依次认：我这侧的 run → 内嵌后端 → 别人的进程 → 都没有才起界面。
  if (RUNS[p.id]){ await stopRun(p.id); return; }
  if (embedSupported(p)){
    if (embedRunning(p.id)){ await embedStop(p.id); return; }
    if (st0.running){                      // 不是内嵌那把（孤儿 / 别处起的）：按进程停
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
  if (st.running){                       // 别处启动的：直接停掉它的进程
    const r = await pywebview.api.pkg_stop(p.id);
    toast(r.msg, !r.ok);
    paintRowStats();
    setTimeout(() => refreshPkgState(p), 400);
    return;
  }
  startRun(p, argsInput() ? argsInput().value : "");
}

/* 详情里那个「参数」输入框：包详情叫 `#args`、历史详情叫 `#hargs`
   （两套详情互斥，同一时刻只会存在一个，所以这里谁在就用谁）。 */
function argsInput(){ return $("#args") || $("#hargs"); }

async function startRun(p, args, cwd, opts){
  if (RUNS[p.id]) return;                // ★ 只拦"同一个包重复起"，不再拦别的包
  const o = opts || {};
  const cmd = "moss " + PSYM + p.id + ((args || "").trim() ? " " + args.trim() : "");
  lastRun = {id: p.id, args: args, label: cmd};
  consoleKey = p.id;                     // 输出落进"这个包自己的"那份
  /* ★★ `V-352`：终端在 ⇒ **把这条命令敲进那个常驻终端**，包就真跑在这个 shell 里。
     为什么必须这样：真终端（ConPTY）的流里带**绝对光标定位**，把管道的文本倒进同一块屏
     两股流会互相覆盖（用户当场看到"输出被替换了"）。跑在 shell 里就只有一股流。
     ★ 这里**不再先问 `termCanRun()`** —— 那个判据以前要求"终端正显示着"，于是切去看过
       「包输出」之后点运行就永远走老路（用户报的"又回到之前的模式"）。
       `termRunPackage` 自己会：起会话 → 把这一版切回来 → 敲命令；任何一步不行都返回 false，
       我们照旧往下走老那条管道，行为一点不变。
     ★★ `V-365`（用户 2026-10-09 报的"设了 2 个自启动只起得来一个、日志还全串在一屏"）：
       **自启动那一批要传 `{noTerm:true}` 绕开终端**。原因很硬 —— 终端**只有一条 shell**：
       一个包还占着它的时候，第二条命令是敲进**那个正在跑的包**的 stdin 的（不是新起一个），
       于是第二个起不来、而所有包的日志挤在同一块屏上（各包自己的「包输出」反倒空着）。
       自启动是"后台起一批"，本来就该各走各的管道。 */
  if (!o.noTerm && typeof termRunPackage === "function" && await termRunPackage(p, args, cwd)) return;
  setConsole(p.id, "$ " + cmd, "运行中");
  const r = await pywebview.api.run_start(p.id, args || "", cwd || "");
  if (!r.ok){
    setConsole(p.id, "$ " + cmd + "\n\n启动失败：" + (r.msg || ""), "启动失败");
    toast("✗ " + (r.msg || "启动失败"), true);
    return;
  }
  RUNS[p.id] = {rid: r.run_id, cmd: cmd, timer: null, stopped: false,
                switched: false, tabAtStart: tab};   // 记下"起跑时用户在看哪一页"
  setStatus("正在跑 " + cmd);                       // 状态栏（`V-61`）
  paintInbar(p.id);                      // 刚起跑：命令行下面那行输入框可以用了
  // 人正看着命令行这一页 → 把光标放到输入框里（包一问，直接敲就行）。
  // 只在"起跑那一刻"给一次，不在每次刷新时抢（不然你选中输出文字会被打断）。
  if (tab === "console")
    setTimeout(() => { const i = $("#stdin"); if (i && !i.disabled) i.focus(); }, 60);
  refreshPkgState(p);                    // 让按钮立刻变成「停止」
  pollRun(p.id);
}

/* 这批输出里**除宿主横幅之外**有没有东西？
   ★ 宿主自己总会打 `[执行]/[目录]/时间` 那几行，所以"有输出"不能只看非空 ——
     不然每个包一跑就会跳去命令行（GUI 包明明没有别的内容）。 */
function hasRealOutput(text){
  return String(text || "").split(/\r?\n/).map(l => l.trim()).some(l =>
    l && !/^\[(执行|目录|PID|运行总长|结果)\]/.test(l) &&
    !/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(l));
}

/* ★ "有输出才切过去"：第一次出现**真输出**时切到「命令行」；
   一直没输出（纯 GUI 的包）就留在原地（`U-16`）。
   只在"用户自己没挪窝"时切 —— 万一他已经去文件管理了，别把他拽回来。 */
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
  maybeAutoSwitch(id, run, text);        // 跑得太快、第一轮就结束时也要按规则切一次
  // ★ 状态栏（`V-61`）留一句**说事实**的收尾：非 0 退出码不一律当故障（很多包这样是正常的）
  // ★ `V-367`：**用户按的停止**已经在点下去那一刻报过了（`stopRun`/`stopFromList` 的 toast，
  //   toast 顺手就把状态栏写了）—— 这里再写一遍就是"一个动作两条不一样的话"（你报的那类）。
  //   所以 stopped 时**不动状态栏**，退出码照旧进「命令行」那份输出。
  if (!stopped)
    setStatus("跑完了 " + run.cmd + " · 退出码 " + code, code !== 0);
  setConsole(id, "$ " + run.cmd + "\n\n" + (text || "(这个包没有输出)") + "\n" +
             runTail(code, text, stopped),
             // ★ 只说事实（退出码是多少），不判"故障" —— 非 0 在很多包里是正常现象
             stopped ? "已停止" : ("退出码 " + code));
  // 这里按的停止不算"故障"（红）—— 是"已停止"（黄）
  paintRowStats();
  // 详情正开着"这次跑的那个对象"就重画一遍（包 或 历史条目 —— 收尾信息在详情里也显示）
  if ((cur && cur.id === id) || (curH && histKey(curH) === id)) renderDetail();
  paintInbar(id);                        // 跑完了：输入行该禁用掉（没人在等了）
  paintActions(selObj());
  paintHistStats();
  // ★ 退出码回来了不等于"它没在跑" —— 有的包 fork 出界面自己就退了。
  //   所以状态以宿主那份为准（600ms 后再问一次）。
  setTimeout(refreshAllStates, 600);
  if (side === "hist") loadHist().then(() => { renderHist(); });
}

/* 收尾那一行怎么措辞。
   ★ 为什么要专门做：GUI 包被**在这里按停止**时，进程是被强杀的，退出码必然是 1 ——
     直接写"[退出码] 1"会让人以为它报错了（实测：正常关窗口也是这个码）。
     另外"非 0 但一句话都没输出"这种情况也点明，省得盯着屏幕找不存在的报错。 */
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
  // `V-352`：跑在终端里的：真终端发真 Ctrl+C，管道后端请宿主按进程杀
  if (run.term && typeof termStop === "function"){
    const r0 = await termStop(id);
    toast(r0.msg, !r0.ok);
    return;
  }
  const r = await pywebview.api.run_stop(run.rid);
  toast(r.msg, !r.ok);
  run.stopped = true;                    // 让 finishRun 别把它记成"故障"
  setTimeout(refreshAllStates, 400);
}

/* ---------------------------------------------------------------- 挂载（放最后）
   ★ 同 `console.js`：必须等本文件里那些 `const`（`EMB` / `EMBR`）都声明完再挂 ——
     `mountVue()` 当场渲染，模板里的 `aliveN` 要读 `EMB.alive`。 */
mountVue(MossEmbed, "#pane-embed", {ico: ico});
