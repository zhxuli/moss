let modalCb = null, modalCb2 = null;

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

function askConfirm2(title, text, a, b){
  $("#m-title").textContent = title;

  $("#m-text").innerHTML = String(text || "").replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");

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

  const i = $("#m-input"), t = $("#m-textarea");
  if (i) i.hidden = true;
  if (t){ t.hidden = true; t.value = ""; }

  const ex = $("#m-extra");
  if (ex){ ex.hidden = true; ex.innerHTML = ""; }
  const card = document.querySelector("#modal .card");
  if (card) card.classList.remove("wide", "np-card");
  modalCb = null; modalCb2 = null;
}

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

function notice(title, text, opts){
  const o = opts || {};
  askConfirm2(title, text, {label: o.ok || "知道了", cb: o.cb || null,
                            danger: false, title: o.tip || ""});
}
