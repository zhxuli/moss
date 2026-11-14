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
  return '<div class="dp-bar-i" id="para-sec"' +
      ' data-tip="寄生模式：和 moss 合体 —— 选中它自动运行，切到别的插件自动停">' +
      '<span class="dp-bar-ico">' + ico("plug", "i") + '</span>' +
      '<span class="dp-bar-t">寄生模式</span>' +
      '<label class="dp-switch" title="' +
        (on ? "现在开着 —— 点一下关掉（关掉之后点它不再自动运行）"
            : "点一下打开：以后选中这个插件就自动运行、切走自动停") + '">' +
        '<input type="checkbox" id="para-sw"' + (on ? " checked" : "") + '>' +
        '<span class="dp-switch-track"></span>' +
      '</label>' +
    '</div>';
}

async function parasiteWire(id){
  const before = PARA.loaded;
  await parasiteLoad();
  if (!before && PARA.loaded && typeof renderDetail === "function") renderDetail();
  const sw = $("#para-sw");
  if (!sw) return;
  sw.onchange = async () => {
    const was = parasiteHas(id);
    if (was) PARA.ids = (PARA.ids || []).filter(x => String(x) !== String(id));
    else PARA.ids = (PARA.ids || []).concat([String(id)]);
    if (!await parasitePersist()) { renderDetail(); return; }
    renderDetail();                       
    setTimeout(() => autoSavedHint($("#para-sec"), was ? "已关掉" : "已打开"), 60);
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
