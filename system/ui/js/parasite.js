const PARA = {ids: [], loaded: false};

function parasiteHas(id){ return (PARA.ids || []).indexOf(String(id)) >= 0; }

async function parasiteLoad(force){
  if (PARA.loaded && !force) return PARA.ids;
  let r = null;
  try{ r = await pywebview.api.parasite_get(); }catch(e){ r = null; }
  if (r && r.ok){
    PARA.ids = (r.ids || []).map(x => String(x));
    PARA.loaded = true;
  }
  return PARA.ids;
}

async function parasitePersist(){
  let r = null;
  try{ r = await pywebview.api.parasite_set(PARA.ids || []); }catch(e){ r = null; }
  if (!r || !r.ok){
    toast("✗ 没存上寄生模式：" + ((r && r.msg) || "宿主没回话"), true);
    return false;
  }
  PARA.ids = (r.ids || []).map(x => String(x));
  PARA.loaded = true;
  return true;
}

async function parasiteRename(oldId, newId){
  if (!oldId || !newId || String(oldId) === String(newId)) return 0;
  await parasiteLoad(true);
  let n = 0;
  PARA.ids = (PARA.ids || []).map(x => {
    if (String(x) === String(oldId)){ n++; return String(newId); }
    return x;
  });
  if (n) await parasitePersist();
  return n;
}

function parasiteSectionHTML(id){
  const on = parasiteHas(id);
  return '<div class="dp-item" id="para-sec">' +
      '<div class="dp-item-info">' +
        '<span class="dp-item-ico">' + ico("plug", "i") + '</span>' +
        '<div class="dp-item-text">' +
          '<h4>寄生模式' +
            '<span class="dp-tip dp-tip-ico" data-tip="与moss合体，点它自动运行、切到别的插件它自动停">' +
              ico("info", "i") + '</span>' +
          '</h4>' +
          '<p>与系统结合更加紧密</p>' +
        '</div>' +
      '</div>' +
      '<div class="dp-item-acts">' +
        '<button type="button" class="dp-ghost' + (on ? " on" : "") + '" id="para-sw"' +
          ' role="switch" aria-checked="' + (on ? "true" : "false") + '" title="' +
          (on ? "现在开着 —— 点一下关掉（关掉之后点它不再自动运行）"
              : "点一下打开：以后选中这个插件就自动运行、切走自动停") + '">' +
          ico(on ? "circle-slash" : "circle-check", "i") +
          '<span>' + (on ? "禁用" : "启用") + '</span></button>' +
      '</div>' +
    '</div>';
}

async function parasiteWire(id){
  const before = PARA.loaded;
  await parasiteLoad();
  if (!before && PARA.loaded && typeof renderDetail === "function") renderDetail();
  const sw = $("#para-sw");
  if (!sw) return;
  sw.onclick = async () => {
    const was = parasiteHas(id);
    if (was) PARA.ids = (PARA.ids || []).filter(x => String(x) !== String(id));
    else PARA.ids = (PARA.ids || []).concat([String(id)]);
    if (!await parasitePersist()) { renderDetail(); return; }
    renderDetail();                       
    setTimeout(() => autoSavedHint($("#para-sw"), was ? "已关掉" : "已打开"), 60);
  };
}

async function parasiteOnPick(id, prev){
  await parasiteLoad();
  const now = String(id || "");
  if (!now) return;

  if (prev && String(prev) !== now && parasiteHas(prev)) await parasiteStop(String(prev));

  if (parasiteHas(now)) await parasiteEnsureRunning(now);
}

async function parasiteEnsureRunning(id){
  const p = (DATA.packages || []).find(x => x.id === id);
  if (!p || pkgRunning(p)) return;
  await new Promise(r => setTimeout(r, 0));
  if (pkgRunning(p)) return;              
  await clickRun(p);
}

async function parasiteStop(id){
  const p = (DATA.packages || []).find(x => x.id === id);
  if (!p || !pkgRunning(p)) return;
  await clickRun(p);
}
