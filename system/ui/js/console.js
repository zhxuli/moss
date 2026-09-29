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
function paintConsole(){
  const key = consoleKey || "__host__";
  const b = consoleBuf(key);
  const el = $("#out");
  el.textContent = b.text;
  el.scrollTop = el.scrollHeight;
  $("#outinfo").textContent = consoleTitle(key) + " · " + (b.info || "");
  paintInbar(key);
}
/* 输入行：只在"当前这一份命令行真的有个在跑的进程"时可用（`V-43`）。
   没在跑 / 跑完了 → 禁用 + 换一句占位话，省得你以为发了没反应。 */
function paintInbar(key){
  const inp = $("#stdin"), btn = $("#btn-send"), bar = $("#inbar");
  if (!inp || !bar) return;
  const run = RUNS[key || ""];
  const live = !!run;
  inp.disabled = !live;
  if (btn) btn.disabled = !live;
  bar.classList.toggle("off", !live);
  const ph = live ? "包在等你的回答就敲在这里，回车发送（比如 1 / 2 / 3）"
                  : (key === "__host__" ? "宿主自己的输出没有输入这回事"
                                        : "这个包现在没在跑 —— 先在「详情」里点运行");
  if (inp.placeholder !== ph) inp.placeholder = ph;
}
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
async function copyOut(){
  const text = $("#out").textContent;
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
  $("#outinfo").textContent = ok ? ("已复制 " + text.length + " 个字符")
                                 : "复制失败（可以手动选中后 Ctrl+C）";
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
  document.querySelectorAll(".item").forEach(el => {
    const id = el.dataset.id;
    const box = el.querySelector(".rowstat");
    if (!box) return;
    const running = rowStateOf(id) === "running";
    box.innerHTML = running
      ? '<button class="ic-run" title="正在运行 —— 点这里停掉它">' + ico("square", "i") + '</button>'
      : '<button class="idle" title="运行这个包（:﻿' + esc(id) + '）">' + ico("play", "i") + '</button>';
    const b = box.querySelector("button");
    if (b) b.onclick = (ev) => {
      ev.stopPropagation();                       // 点图标不要连带选中那一行
      if (running) stopFromList(id); else runFromList(id);
    };
  });
}

/* 列表里直接跑：参数留空（就是"平常那样跑它"），不动左边的选中 */
async function runFromList(id){
  const p = DATA.packages.find(x => x.id === id);
  if (!p) return;
  if (RUNS[id]) return;
  const st = PST[id] || {};
  if (st.running){ toast(":" + id + " 已经在跑了"); return; }
  startRun(p, "");
}

/* 列表里直接停掉：是这里起的就走 run_stop（好把输出收尾），否则按进程停 */
async function stopFromList(id){
  let r;
  if (RUNS[id]){
    r = await pywebview.api.run_stop(RUNS[id].rid);
    RUNS[id].stopped = true;
  } else {
    r = await pywebview.api.pkg_stop(id);
    paintRowStats();
  }
  toast(r.msg, !r.ok);
  setTimeout(refreshAllStates, 400);
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
               : (running ? "停掉它（连同它拉起的子进程）"
                          : "运行这个包，输出进「命令行」");
  b.classList.toggle("warn", running);
  v.disabled = !p || !st.windows;
  v.innerHTML = ico(st.visible ? "eye-off" : "eye", "i") +
                '<span>' + (st.visible ? "隐藏" : "显示") + '</span>';
  v.title = !p ? "先在左边选一个包或一条历史"
               : (!st.windows
                  ? "这个包现在没有开着的窗口（先「运行」或「打开界面」）"
                  : (st.visible ? "隐藏它的窗口（不关掉，随时能再显示出来）"
                                : "把它的窗口显示出来并叫到前面"));
}
