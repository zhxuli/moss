/* moss 界面 · modal.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 模态 / 提示 */
let modalCb = null, modalCb2 = null;
function askText(title, value, cb){
  $("#m-title").textContent = title;
  $("#m-text").textContent = "";
  const inp = $("#m-input");
  inp.hidden = false; inp.value = value || "";
  const ok = $("#m-ok");
  ok.textContent = "确定"; ok.className = "primary"; ok.title = "";
  $("#m-ok2").hidden = true;
  $("#modal").classList.add("on");
  setTimeout(() => { inp.focus(); inp.select(); }, 30);
  modalCb = () => cb(inp.value.trim());
  modalCb2 = null;
}
function askConfirm(title, text, cb){
  askConfirm2(title, text, {label: "确定", cb: cb, danger: true});
}
/* 两个动词的确认框（`V-92`）—— 像 git 那样把"写回"和"强制对齐"分成**两个动作**。
   `a` = 主按钮（走 `#m-ok`，也是回车键那个），`b` = 可选的第二个（走 `#m-ok2`）；
   不传 `b` 就退回普通确认框。
   ★ 约定：`#m-ok` 永远是**稳**的那个 —— 预览场景和真机探针都按这条写。 */
function askConfirm2(title, text, a, b){
  $("#m-title").textContent = title;
  // 用 innerHTML：确认框里要换行（`<br>`）。文案是自己拼的（包 id / 目录），
  // 而 Windows 路径里不可能有 `<`，所以这里没有注入面。
  $("#m-text").innerHTML = String(text || "").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  $("#m-input").hidden = true;
  const ok = $("#m-ok"), alt = $("#m-ok2");
  ok.textContent = (a && a.label) || "确定";
  ok.className = (b ? "primary" : (a && a.danger ? "danger" : "primary"));
  ok.title = (a && a.title) || "";
  if (b){
    alt.hidden = false;
    alt.textContent = b.label || "";
    alt.title = b.title || "";
    alt.className = "warn";
  }else{
    alt.hidden = true; alt.textContent = ""; alt.title = "";
  }
  $("#modal").classList.add("on");
  setTimeout(() => ok.focus(), 30);
  modalCb = (a && a.cb) || null;
  modalCb2 = (b && b.cb) || null;
}
function closeModal(){
  $("#modal").classList.remove("on");
  modalCb = null; modalCb2 = null;
}
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
