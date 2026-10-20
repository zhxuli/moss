/* moss 界面 · modal.js —— 从 index.html 拆出来的（`V-67`），内容与拆分前一致。 */
/* ---------------------------------------------------------------- 模态 / 提示 */
let modalCb = null, modalCb2 = null;
/* `opts.multiline` = 用多行框（过滤规则那种每行一条的）。`V-113`：单行 input 根本写不了多行。 */
function askText(title, value, cb, opts){
  $("#m-title").textContent = title;
  $("#m-text").textContent = "";
  const inp = $("#m-input"), ta = $("#m-textarea");
  const multi = !!(opts && opts.multiline);
  inp.hidden = multi; ta.hidden = !multi;
  (multi ? ta : inp).value = value || "";
  const ok = $("#m-ok");
  ok.textContent = "确定"; ok.className = "primary"; ok.title = "";
  $("#m-ok2").hidden = true;
  $("#modal").classList.add("on");
  setTimeout(() => { (multi ? ta : inp).focus(); (multi ? ta : inp).select(); }, 30);
  modalCb = () => cb((multi ? ta.value : inp.value).replace(/\r\n/g, "\n"));
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
  // ★ `V-119`：确认框要**把两个输入框都藏起来** —— 以前只藏了单行 `#m-input`，
  //   于是开过一次"过滤规则"那个多行框之后，**后来每个确认框（删文件…）都会把那个多行框
  //   连着显示出来**（里面还留着上次的规则）。两种编辑框不是一类东西，不能只藏一半。
  $("#m-input").hidden = true;
  const _ta = $("#m-textarea");
  if (_ta){ _ta.hidden = true; }
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
  // 关掉时两个都藏好，下一次打开从干净状态开始（`V-119`）
  const i = $("#m-input"), t = $("#m-textarea");
  if (i) i.hidden = true;
  if (t){ t.hidden = true; t.value = ""; }
  // ★ `V-387`：自定义插槽也要清干净（新建包那个弹窗整个塞在这里面）
  const ex = $("#m-extra");
  if (ex){ ex.hidden = true; ex.innerHTML = ""; }
  const card = document.querySelector("#modal .card");
  if (card) card.classList.remove("wide", "np-card");
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

/* 通用"通知"模态框（`V-101`）—— 只有一颗「知道了」，用来告诉用户"刚才那件事**已经做完了**"。
   ★ 为什么要它（你的原话）："刷新按钮 点了以后 应该出现一个模态框 告知用户插件和历史记录已刷新
     这样 哪怕没有变化 用户也知道按钮没坏"；"模态框的消息通知 请封装成一个通用函数 方便复用"。
   ★ 和 `toast` 的分工：toast 是**一闪而过**的状态行（跑起来了 / 已保存），
     `notice` 是**要你确认看见**的回执（刷新完了、批量操作做完了）—— 它会挡住操作，别滥用。
   ★ `notice()` 走的是同一个弹框壳（`askConfirm2`），只是第二个动词不传 ⇒ 只有一颗按钮。 */
function notice(title, text, opts){
  const o = opts || {};
  askConfirm2(title, text, {label: o.ok || "知道了", cb: o.cb || null,
                            danger: false, title: o.tip || ""});
}
