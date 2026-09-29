/* moss 界面 · panels.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 状态（只有两种）
   ★ 状态**只有"在跑 / 没在跑"两种**，而且唯一来源是**宿主**那份 (`PST`)：
     它会答"这个包有没有活着的进程"（按进程环境里的 MOSS_PKG_ID + 命令行认），
     不管是谁拉起来的。界面上不再自己维护一套"上次跑成什么样"——
     那套原来只用来染红/黄，而退出码误报太多，已经删掉。
     需要退出码时它就在「命令行」那行文字里（"退出码 1"），不拿出来报警。 */
function paintStates(){
  paintRowStats();
  paintHistStats();
  paintActions(selObj());
}

/* ---------------------------------------------------------------- 面板 */
function setTab(name){
  tab = name;
  // 离开「界面」那一页只是**藏起来**：iframe 和它的后端进程都不动（`V-48`）
  if (name === "embed" && cur && embedRunning(cur.id)) embedShow(cur.id);
  if (name !== "embed") pushEmbedEvent(cur && cur.id, "visible", {visible: false});
  document.querySelectorAll(".tab").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === name));
  ["detail", "console", "file", "embed"].forEach(t =>
    $("#pane-" + t).classList.toggle("on", t === name));
  hideCtx();
  // 回到详情时对一下"在不在跑 / 有没有窗口"（历史条目没有包状态，不用问）
  if (name === "detail" && cur) refreshPkgState(cur);
  if (name === "console") paintConsole();
}
function stripAnsi(s){
  return String(s == null ? "" : s)
    .replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, "")
    .replace(/[\x1b][()][A-Za-z0-9]/g, "")
    .replace(/[\r\f]/g, "");
}
