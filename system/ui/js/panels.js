function paintStates(){
  paintRowStats();
  paintHistStats();
  paintActions(selObj());
}

function setTab(name){
  tab = name;

  if (name === "embed" && cur && embedRunning(cur.id)) embedShow(cur.id);
  if (name !== "embed") pushEmbedEvent(cur && cur.id, "visible", {visible: false});
  document.querySelectorAll(".tab").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === name));

  ["detail", "console", "file", "ai", "embed"].forEach(t =>
    $("#pane-" + t).classList.toggle("on", t === name));

  try{
    if (window.__aiVm && typeof window.__aiVm.setPageVisible === "function")
      window.__aiVm.setPageVisible(name === "ai");
  }catch(e){}
  hideCtx();

  if (name === "detail" && cur) refreshPkgState(cur);
  if (name === "console") paintConsole();
}
function stripAnsi(s){
  return String(s == null ? "" : s)
    .replace(/\x1b\[[0-9;?]*[ -\/]*[@-~]/g, "")
    .replace(/[\x1b][()][A-Za-z0-9]/g, "")
    .replace(/[\r\f]/g, "");
}
