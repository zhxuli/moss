const SND = {at: {}};

function sndNotify(kind, force){
  kind = (kind === "warn") ? "warn" : "finish";
  const now = Date.now();
  if (!force && now - (SND.at[kind] || 0) < 1200) return;
  SND.at[kind] = now;
  try{
    const api = window.pywebview && window.pywebview.api;
    if (!api || typeof api.sound_play !== "function") return;
    const p = api.sound_play(kind, !!force);
    if (p && p.catch) p.catch(() => {});
  }catch(e){  }
}
