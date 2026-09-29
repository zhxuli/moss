/* moss 界面 · app.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 启动 */

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

async function init(){
  setStatus("就绪");        // 状态栏（`V-61`）：还没干任何事时它是空的，给一句起点
  DATA = await pywebview.api.state();
  $("#meta").textContent =
    DATA.packages.length + " 个包 · 启动方式：" + DATA.launch_kind + " · " + DATA.home;
  renderList(); paintStates();
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
  // 默认上下文：不选包时给一个"全部文件"（根 = user_data），能自己往上走到 system
  FM.ctx = "__all__";
  const s = fmState("__all__");
  const r = await pywebview.api.fs_list("user");
  if (r.ok){ s.rel = r.rel; s.entries = r.entries || []; s.hist = [s.rel]; s.hpos = 0; }
  fmRender();
  bindDropZone();          // 拖文件进来（`V-35`）：高亮 + 收宿主送来的真实路径
}
function paintStaticIcons(){
  // 注意：这里**没有"退出"按钮** —— 标题栏本来就有 ×，重复一个是多余的
  // 顶层三个选项卡也带图标（原来只有文字，和别处不统一）
  const tabs = {"detail": ["info", "详情"], "console": ["terminal", "命令行"],
                "file": ["folder-tree", "文件管理"]};
  Object.keys(tabs).forEach(k => {
    const b = document.querySelector('.tab[data-tab="' + k + '"]');
    if (b) b.innerHTML = ico(tabs[k][0], "i") + '<span>' + tabs[k][1] + '</span>';
  });
  $("#btn-selfcheck").innerHTML = ico("activity", "i");
  // 左侧顶部：插件 / 历史 切换 + 新建包
  $("#sw-pkg").innerHTML  = ico("package", "i") + '<span>插件</span>';
  // ★ 历史用 Lucide 那个**带表针的 history**（lucide-static 1.48.0，见 vendor/README.md）。
  //   以前用的是 `corner-up-left`（一个"返回箭头"），跟"历史"不是一回事。
  $("#sw-hist").innerHTML = ico("history", "i") + '<span>历史</span>';
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
$("#btn-refresh").onclick = init;
$("#sw-pkg").onclick = () => setSide("pkg");
$("#sw-hist").onclick = () => setSide("hist");
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
$("#m-input").addEventListener("keydown", e => {
  if (e.key === "Enter"){ e.preventDefault(); $("#m-ok").click(); }
  if (e.key === "Escape") closeModal();
});
$("#modal").addEventListener("click", e => { if (e.target.id === "modal") closeModal(); });

/* ---------------------------------------------------------------- 新建 / 卸载
   这两个功能 CLi 早就有（`moss --new` / `moss --remove`），界面这边原来漏了。
   界面**不重写一遍逻辑**，直接把宿主命令叫起来（和用户手敲是同一条路），
   输出照样进「命令行」那份缓冲。 */
async function cmdNewPkg(){
  askText("新建一个包", "my-first", async (id) => {
    if (!id) return;
    consoleKey = "__host__";
    setConsole("__host__", "$ moss --new " + id, "运行中");
    const r = await pywebview.api.run_host("--new " + id);
    setConsole("__host__", "$ moss --new " + id + "\n\n" + (r.out || "(没有输出)") +
               "\n" + runTail(r.code, r.out, false), "退出码 " + r.code);
    toast(r.code === 0 ? ("已新建 :" + id + "（user_data/pkgs/）") : "✗ 新建失败，看「命令行」",
          r.code !== 0);
    if (r.code === 0){
      await init();                       // 重新扫包列表，新包就出现了
      select(id);
    } else setTab("console");
  });
}

async function cmdRemovePkg(p){
  const st = ico("alert-triangle", "i");
  askConfirm("卸载这个包",
    "将<b>永久删除</b>（不进回收站）：<br>· 包本体 " + p.dir + "<br>" +
    "· 它的数据 user_data/state/" + p.id + "（如果有）<br><br>" +
    "层：" + p.layer + (p.layer === "system" ? "（出厂件 —— 删了升级时会回来）" : "") +
    "<br>确定吗？",
    async () => {
      consoleKey = "__host__";
      setConsole("__host__", "$ moss --remove " + p.id + " -y", "运行中");
      const r = await pywebview.api.run_host("--remove " + p.id + " -y");
      setConsole("__host__", "$ moss --remove " + p.id + " -y\n\n" + (r.out || "(没有输出)") +
                 "\n" + runTail(r.code, r.out, false), "退出码 " + r.code);
      toast(r.code === 0 ? ("已卸载 :" + p.id) : "✗ 卸载失败，看「命令行」", r.code !== 0);
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
