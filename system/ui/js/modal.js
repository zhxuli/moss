/* moss 界面 · modal.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 模态 / 提示 */
let modalCb = null;
function askText(title, value, cb){
  $("#m-title").textContent = title;
  $("#m-text").textContent = "";
  const inp = $("#m-input");
  inp.hidden = false; inp.value = value || "";
  $("#m-ok").className = "primary";
  $("#modal").classList.add("on");
  setTimeout(() => { inp.focus(); inp.select(); }, 30);
  modalCb = () => cb(inp.value.trim());
}
function askConfirm(title, text, cb){
  $("#m-title").textContent = title;
  // 用 innerHTML：确认框里要换行（`<br>`）。文案是自己拼的（包 id / 目录），
  // 而 Windows 路径里不可能有 `<`，所以这里没有注入面。
  $("#m-text").innerHTML = text.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  $("#m-input").hidden = true;
  $("#m-ok").className = "danger";
  $("#modal").classList.add("on");
  setTimeout(() => $("#m-ok").focus(), 30);
  modalCb = () => cb();
}
function closeModal(){ $("#modal").classList.remove("on"); modalCb = null; }
/* ---------------------------------------------------------------- 状态栏（`V-61` ✅）
   一句话：**toast 说什么，状态栏就留什么。** 这样"最近一条状态提示"不需要到处
   埋点 —— 现有那些 toast（跑起来了 / 已停止 / 保存失败…）自动就会沉淀到最下面那行，
   2.4 秒后 toast 消失，字还留在状态栏上。 */
function setStatus(text, bad){
  const el = $("#status-text");
  if (!el) return;
  el.textContent = String(text == null ? "" : text);
  el.className = bad ? "bad" : "";
}
function toast(text, bad){
  setStatus(text, bad);
  const box = $("#toasts");
  const el = document.createElement("div");
  el.className = "toast" + (bad ? " bad" : "");
  el.textContent = text;
  box.appendChild(el);
  setTimeout(() => el.remove(), 2400);
}
