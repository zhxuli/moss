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
const EMB = {alive: {}, tick: null};

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
  const empty = $("#embed-empty");
  if (empty) empty.style.display = Object.keys(EMB.alive).length ? "none" : "block";
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
  if (!quiet) toast(r && r.ok ? "已停掉这个包的内嵌进程" : ((r && r.msg) || "没在跑"), !(r && r.ok));
  const rec = EMB.alive[pid];
  if (rec && rec.frame) rec.frame.remove();     // 这一帧也撤掉（进程都停了，留着没意义）
  delete EMB.alive[pid];
  if (!Object.keys(EMB.alive).length) embedTick(false);
  embedShow(Object.keys(EMB.alive)[0] || null);  // 还有别的在跑就接着显示它
  paintEmbedTab(); paintActions(selObj());
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
    if (!Object.keys(EMB.alive).length) embedTick(false);
    toast("这个包的内嵌进程结束了（退出码 " + code + "）", code !== 0);
    paintEmbedTab(); paintActions(selObj());
  }
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
  }
});
/* 「界面」选项卡该不该出现 + 顶上那行小字 */
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
  if (ok){
    if ($("#embed-title")) $("#embed-title").textContent = cur.ui.title || cur.name || "界面";
    if ($("#embed-info")){
      $("#embed-info").textContent = embedRunning(cur.id)
        ? ("后端 :" + cur.id + " 在内嵌运行 · 切走也不会停" +
           (Object.keys(EMB.alive).length > 1
             ? ("（另外还有 " + (Object.keys(EMB.alive).length - 1) + " 个也在跑）") : ""))
        : "还没跑 —— 点右上角「运行」就起";
    }
  }
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
  // ★ 带内嵌界面的包（`V-48`）：这里的「运行」= 起它的内嵌后端 + 亮出「界面」选项卡。
  //   不去开独立窗口 —— 那件事交给「在独立窗口打开」那颗按钮（两条路并存）。
  if (embedSupported(p)){
    if (embedRunning(p.id)){ await embedStop(p.id); return; }
    await embedOpen(p);
    return;
  }
  if (RUNS[p.id]){ await stopRun(p.id); return; }
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

async function startRun(p, args, cwd){
  if (RUNS[p.id]) return;                // ★ 只拦"同一个包重复起"，不再拦别的包
  const cmd = "moss :" + p.id + ((args || "").trim() ? " " + args.trim() : "");
  lastRun = {id: p.id, args: args, label: cmd};
  consoleKey = p.id;                     // 输出落进"这个包自己的"那份
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
  setStatus((stopped ? "已停止 " : "跑完了 ") + run.cmd + " · 退出码 " + code,
            code !== 0 && !stopped);
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
  const r = await pywebview.api.run_stop(run.rid);
  toast(r.msg, !r.ok);
  run.stopped = true;                    // 让 finishRun 别把它记成"故障"
  setTimeout(refreshAllStates, 400);
}
