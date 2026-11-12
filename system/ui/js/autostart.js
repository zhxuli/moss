const AUTO_MAX = 20;

const AUTO = {items: [], loaded: false};

let AUTORAN = false;

function autoLabel(kind, id, name){
  if (name) return String(name);
  if (kind === "hist") return String(id || "").split(/[\\/]/).pop() || String(id || "");
  return PSYM + String(id || "");
}

function autoFind(kind, id){
  return (AUTO.items || []).find(x => x.kind === kind && String(x.id) === String(id)) || null;
}

function autoPkgIds(){
  const s = new Set();
  (AUTO.items || []).forEach(x => { if (x.kind === "pkg" && x.id) s.add(String(x.id)); });
  return s;
}

function autoPaintMarks(){
  try{ if (typeof renderList === "function") renderList(); }catch(e){  }
}

async function autoLoad(force){
  if (AUTO.loaded && !force){ autoPaintMarks(); return AUTO.items; }
  let r = null;
  try{ r = await pywebview.api.autostart_get(); }catch(e){ r = null; }
  if (r && r.ok){
    AUTO.items = (r.items || []).map(x => Object.assign({}, x));
    AUTO.max = r.max || AUTO_MAX;
    AUTO.loaded = true;
  }
  autoPaintMarks();
  return AUTO.items;
}

async function autoPersist(msg){
  let r = null;
  try{ r = await pywebview.api.autostart_set(AUTO.items || []); }catch(e){ r = null; }
  if (!r || !r.ok){
    toast("✗ 没存上自动启动：" + ((r && r.msg) || "宿主没回话"), true);
    return false;
  }
  AUTO.items = (r.items || []).map(x => Object.assign({}, x));
  AUTO.loaded = true;
  if (msg) toast(msg);
  return true;
}

function autoMake(kind, id, opts, f){
  const o = opts || {};
  const v = f || {};
  return {kind: kind, id: String(id),
          args: String(v.args !== undefined ? v.args : ""),
          cwd: String(v.cwd !== undefined ? v.cwd : (o.cwd || "")),
          name: String(o.name || ""), on: true};
}

async function autoRename(oldId, newId){
  if (!oldId || !newId || String(oldId) === String(newId)) return 0;
  await autoLoad(true);
  let n = 0;
  (AUTO.items || []).forEach(x => {
    if (x.kind === "pkg" && String(x.id) === String(oldId)){ x.id = String(newId); n++; }
  });
  if (n) await autoPersist();
  autoPaintMarks();                      
  return n;
}

function autoSectionHTML(kind, id, opts){
  const it = autoFind(kind, id);
  const on = !!(it && it.on !== false);
  return '<div class="dp-item" id="auto-sec">' +
      '<div class="dp-item-info">' +
        '<span class="dp-item-ico">' + ico("rocket", "i") + '</span>' +
        '<div class="dp-item-text">' +
          '<h4>自动运行' +
            '<span class="dp-tip dp-tip-ico" data-tip="开 moss 界面时自动跑一次">' +
              ico("info", "i") + '</span>' +
          '</h4>' +
          '<p class="auto-st">随宿主程序启动时自动初始化</p>' +
        '</div>' +
      '</div>' +
      '<div class="dp-item-acts">' +

        '<div class="dp-expand' + (on ? " show" : "") + '" id="auto-panel">' +
          '<div class="dp-pathgroup" id="auto-dropzone" title="可以把文件夹拖到这里">' +
            '<input type="text" id="auto-cwd" placeholder="工作路径 (拖拽或点选)"' +
              ' spellcheck="false" autocomplete="off" value="' + esc(it ? it.cwd : "") + '">' +
            '<button type="button" class="dp-browse dp-tip" id="btn-auto-pick"' +
              ' data-tip="浏览目录">' + ico("folder-open", "i") + '</button>' +
          '</div>' +
          '<input type="text" class="dp-param" id="auto-args" placeholder="启动参数 (选填)"' +
            ' spellcheck="false" autocomplete="off" value="' + esc(it ? it.args : "") + '">' +
        '</div>' +
        '<button type="button" class="dp-ghost' + (on ? " on" : "") + '" id="auto-sw"' +
          ' role="switch" aria-checked="' + (on ? "true" : "false") + '" title="' +
          (on ? "现在跟着启动 —— 点一下禁用（等于从自动启动里拿掉）"
              : "点一下让它跟着启动，然后填工作路径 / 启动参数") + '">' +
          ico(on ? "circle-slash" : "circle-check", "i") +
          '<span>' + (on ? "禁用" : "启用") + '</span></button>' +
      '</div>' +
    '</div>';
}

async function autoWire(kind, id, opts){
  const o = opts || {};
  const before = AUTO.loaded;
  await autoLoad();

  if (!before && AUTO.loaded && typeof renderDetail === "function") renderDetail();
  const args = $("#auto-args"), cwd = $("#auto-cwd"), sw = $("#auto-sw");

  AUTO.curKind = kind;
  AUTO.curId = String(id);

  if (sw) sw.onclick = async () => {
    const it = autoFind(kind, id);
    if (it){                                   
      AUTO.items = (AUTO.items || []).filter(
        x => !(x.kind === kind && String(x.id) === String(id)));

      await autoPersist("");
      renderDetail();
      setTimeout(() => autoSavedHint($("#auto-sw"), "已移除"), 60);
      autoPaintMarks();                       
      return;
    }
    if ((AUTO.items || []).length >= (AUTO.max || AUTO_MAX)){
      toast("自动启动最多 " + (AUTO.max || AUTO_MAX) + " 条", true); return;
    }

    AUTO.items.push(autoMake(kind, id, o, {cwd: o.cwd || "", args: ""}));
    await autoPersist("");
    renderDetail();
    setTimeout(() => autoSavedHint($("#auto-sw"), "已启用"), 60);
    autoPaintMarks();                         

    let tries = 0;
    const tick = () => {
      const box = $("#auto-args");
      if (box){
        try{ box.focus(); }catch(e){  }
        if (document.activeElement === box) return;
      }
      if (++tries < 15) setTimeout(tick, 30);
    };
    setTimeout(tick, 0);
  };

  [cwd, args].forEach(box => {
    if (!box) return;
    box.addEventListener("keydown", async (ev) => {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      if (await autoSaveFields(kind, id)) autoSavedHint(box);
    });
    box.addEventListener("blur", async () => {
      if (await autoSaveFields(kind, id)) autoSavedHint(box);
    });
  });

  const pick = $("#btn-auto-pick");
  if (pick) pick.onclick = async () => {
    let r = null;
    try{ r = await pywebview.api.pick_dir(cwd ? cwd.value : ""); }catch(e){ r = null; }
    if (!r || !r.ok){
      if (!(r && r.cancelled)) toast("挑目录失败：" + ((r && r.msg) || "没回话"), true);
      return;
    }
    if (cwd) cwd.value = String(r.path || "");
    if (await autoSaveFields(kind, id)) autoSavedHint(cwd || pick);  };

  const zone = $("#auto-dropzone");
  if (zone){
    zone.addEventListener("dragover", (ev) => {
      ev.preventDefault();
      if (ev.dataTransfer) ev.dataTransfer.dropEffect = "copy";
      AUTO.dragOn = true;
      zone.classList.add("drag-over");
    });
    zone.addEventListener("dragleave", (ev) => {
      if (ev.relatedTarget && zone.contains(ev.relatedTarget)) return;
      zone.classList.remove("drag-over");
    });
    zone.addEventListener("drop", (ev) => {
      ev.preventDefault();
      zone.classList.remove("drag-over");
    });
  }
}

window.__mossAutoDrop = function(items){
  if (!AUTO.dragOn) return false;
  AUTO.dragOn = false;
  const zone = $("#auto-dropzone");
  if (zone) zone.classList.remove("drag-over");
  const box = $("#auto-cwd");
  if (!box || !items || !items.length) return false;

  const it = items[0];
  const p = it.isDir ? it.path : (it.dir || "");
  if (!p) return false;
  box.value = String(p);

  Promise.resolve().then(async () => {
    if (await autoSaveFields(AUTO.curKind, AUTO.curId)) autoSavedHint(box);
  });
  return true;
};

async function autoSaveFields(kind, id){
  const it = autoFind(kind, id);
  if (!it) return false;
  const cwdBox = $("#auto-cwd"), argBox = $("#auto-args");
  const next = {cwd: cwdBox ? String(cwdBox.value || "") : String(it.cwd || ""),
                args: argBox ? String(argBox.value || "") : String(it.args || "")};
  if (String(it.cwd || "") === next.cwd && String(it.args || "") === next.args) return false;
  it.cwd = next.cwd;
  it.args = next.args;
  return await autoPersist("");                          
}

function autoSavedHint(box, text){
  if (box) flashAutoInput(box);
  const words = String(text || "已保存");
  try{
    const host = (box && box.parentElement) ||
                 document.querySelector("#auto-sec .dp-item-acts");
    if (!host) return;
    let hint = host.querySelector(".dp-saved");
    if (!hint){
      hint = document.createElement("span");
      hint.className = "dp-saved";
      host.appendChild(hint);
    }
    hint.textContent = words;
    hint.classList.add("on");
    clearTimeout(hint._t);
    hint._t = setTimeout(() => { try{ hint.remove(); }catch(e){} }, 1600);
  }catch(e){  }
}

function flashAutoInput(box){
  try{
    box.classList.add("saved");
    setTimeout(() => box.classList.remove("saved"), 900);
  }catch(e){  }
}

async function autostartRun(){
  if (FLOAT_PID || AUTORAN) return;
  AUTORAN = true;
  await autoLoad(true);
  const items = (AUTO.items || []).filter(x => x.on !== false);
  const done = [], failed = [];
  for (let i = 0; i < items.length; i++){
    const it = items[i];
    try{
      if (it.kind === "hist"){
        const nm = autoLabel("hist", it.id, it.name);
        await rerunHist({target: it.id, cwd: it.cwd || "", name: nm, args: it.args || ""},
                        it.args || "");
        done.push(nm);
      }else{
        const p = (DATA.packages || []).find(x => x.id === it.id);
        if (!p){ failed.push(it.id + "（找不到这个包）"); continue; }

        await startRun(p, it.args || "", it.cwd || "", {noTerm: true, keepTab: true});
        done.push(PSYM + p.id);
      }
    }catch(e){ failed.push(it.id + "：" + ((e && e.message) || e)); }
    await new Promise(r => setTimeout(r, 700));
  }

  const bad = failed.length;
  if (bad){
    try{ setStatus("自动运行：" + bad + " 个没起来 —— " + failed.join("、")); }
    catch(e){  }
  }
}
