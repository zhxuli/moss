const BK = Vue.reactive({
  items: [], stat: {}, loading: false,
  sel: null, man: null,
  view: null,                          
  filter: "", busy: "", checkRows: null,
  formOpen: false, title: "", note: "",

  byFilter: "",
  collapsed: false,                    
  exportTo: "", exportBak: false, dropOver: false,   
  fps: {}, fresh: {},                   
  leftOnly: 0,
  ig: null,                            
  igGroup: null,                       
  folded: {},                          
  presets: null,                       
});

const BKR = Vue.reactive({rev: 0});
function bkRefresh(){ BKR.rev++; }

function bkCurDir(){
  const s = FM.st[FM.ctx || "__all__"];
  return (s && s.rel) || "";
}
function bkNowEntries(){
  const s = FM.st[FM.ctx || "__all__"];
  return (s && s.entries) || [];
}

function bkSnapSlice(rel){
  const man = BK.man;
  if (!man) return null;
  const pfx = rel ? String(rel).replace(/\/+$/, "") + "/" : "";
  const dirs = {}, files = {};
  (man.files || []).forEach(e => {
    const r = String(e.rel || "");
    if (pfx && r.indexOf(pfx) !== 0) return;
    const rest = pfx ? r.slice(pfx.length) : r;
    if (!rest) return;
    const i = rest.indexOf("/");
    if (i >= 0){ const d = rest.slice(0, i); dirs[d] = (dirs[d] || 0) + (e.size || 0); }
    else files[rest] = e;
  });
  (man.empty_dirs || []).forEach(d => {
    const r = String(d || "");
    if (pfx && r.indexOf(pfx) !== 0) return;
    const rest = pfx ? r.slice(pfx.length) : r;
    if (rest && rest.indexOf("/") < 0 && dirs[rest] === undefined) dirs[rest] = 0;
  });
  return {dirs: dirs, files: files};
}
function bkStateWhy(st, name, deep){
  if (st === "diff") return "两边都有、内容不一样" + (deep === "now" ? "（现在这份更大）"
                        : deep === "snap" ? "（快照里那份更大）" : "（大小一样、内容不同）");
  if (st === "snap-only") return "快照里有、现在没了（被删了还是改名了？）";
  if (st === "now-only") return "现在有、快照里没有（后加进去的）";
  if (st === "empty") return "空文件（0 字节）";
  return "和快照里一样";
}

function bkDiffModel(){
  const rel = bkCurDir();
  const now = bkNowEntries();
  const snap = bkSnapSlice(rel);
  const fps = BK.fps || {};
  const fr = BK.fresh || {};
  const freshSize = r => (fr.sizes && (r in fr.sizes)) ? fr.sizes[r] : null;
  const freshDir = r => (fr.dirs && (r in fr.dirs)) ? fr.dirs[r] : null;
  const mine = {};
  now.forEach(e => { mine[e.name] = e; });
  const names = now.map(e => e.name);
  if (snap){
    Object.keys(snap.files).forEach(n => { if (names.indexOf(n) < 0) names.push(n); });
    Object.keys(snap.dirs).forEach(n => { if (names.indexOf(n) < 0) names.push(n); });
  }
  const entries = names.map(n => {
    const nw = mine[n] || null;
    const sFile = snap ? snap.files[n] : null;
    const sDirSize = snap ? snap.dirs[n] : undefined;
    const inSnap = !!(sFile || sDirSize !== undefined);
    const nowDir = !!(nw && nw.dir);

    const nowSize = nw ? (nowDir ? freshDir(nw.rel) : (freshSize(nw.rel) !== null
                                                        ? freshSize(nw.rel) : (nw.size || 0)))
                       : null;
    const snapSize = sFile ? (sFile.size || 0) : (sDirSize !== undefined ? sDirSize : null);
    let st, deep = "", fp = "";
    if (nw && inSnap){
      if (sFile && !nowDir){
        const sfp = sFile.fp || "";
        const nfp = fps[nw.rel] || "";
        if (nowSize !== snapSize) { st = "diff"; deep = (nowSize > snapSize) ? "now" : "snap"; }
        else if (nfp && sfp && nfp !== sfp) { st = "diff"; }      
        else st = "same";
        fp = sfp;
      }else{
        if (nowSize === null || snapSize === null) st = "same";
        else {
          st = (nowSize === snapSize) ? "same" : "diff";
          if (st === "diff") deep = (nowSize > snapSize) ? "now" : "snap";
        }
      }
    }
    else if (nw) st = "now-only";
    else st = "snap-only";
    if (st === "same" && !nowDir && nowSize === 0) st = "empty";
    return {
      name: n, dir: nowDir || (sDirSize !== undefined), rel: nw ? nw.rel : ((rel ? rel + "/" : "") + n),

      ext: extFromName(n),
      now: nw ? {size: nowSize, dir: nowDir} : null,
      snap: inSnap ? {size: snapSize, fp: fp} : null,
      size: sFile ? (sFile.size || 0) : 0, fp: fp,          
      state: st, deep: deep, why: bkStateWhy(st, n, deep),
    };
  });
  entries.sort((a, b) => (a.dir === b.dir) ? a.name.localeCompare(b.name) : (a.dir ? -1 : 1));
  const byRel = {};
  entries.forEach(e => { byRel[e.rel] = e; });
  return {rel: rel, entries: entries, byRel: byRel, snapOk: !!snap};
}

function bkGroupForCtx(){
  const key = FM.ctx || "__all__";
  const p = (key !== "__all__" && !isHistKey(key)) ? DATA.packages.find(x => x.id === key) : null;

  if (BK.group) return BK.group;
  return p ? p.id : bkHistGroup();
}

function bkHistGroup(){
  const rels = bkScopeRels().map(x => String(x || "").replace(/\\/g, "/"));
  for (const r of rels){
    const parts = r.split("/");
    if (parts.length >= 3 && (parts[1] === "pkgs" || parts[1] === "state")) return parts[2];
  }
  for (const r of rels){
    if (r === "user" || r === "system") return "@" + r;
  }
  if (rels.length){
    const first = rels[0].replace(/\/+$/, "");
    const tail = first.split("/").filter(Boolean).pop() || "misc";
    return (first.startsWith("abs/") ? "@abs-" : "@dir-") + tail.replace(/[^A-Za-z0-9_.@-]/g, "_");
  }
  return "@misc";
}
function bkCtxLabel(){
  const key = FM.ctx || "__all__";
  const p = (key !== "__all__" && !isHistKey(key)) ? DATA.packages.find(x => x.id === key) : null;
  if (p) return p.name || p.id;
  if (isHistKey(key)) return "这条调用所在的目录";
  return "整个 user_data";
}

function bkScopeRels(){
  const key = FM.ctx || "__all__";
  const p = (key !== "__all__" && !isHistKey(key)) ? DATA.packages.find(x => x.id === key) : null;
  if (p){
    const roots = [];
    const rel = pkgRel(p);
    if (rel) roots.push(rel);

    return roots;
  }
  if (isHistKey(key)){
    const it = histByKey(key);
    const d = it && histDir(it);
    return d ? [d] : ["user"];
  }
  const s = FM.st[key];
  return (s && s.rel) ? [s.rel] : ["user"];
}
function bkShortFp(fp){ return String(fp || "").slice(0, 10); }

function bkHighlightHTML(text, lang){
  const t = String(text == null ? "" : text);
  if (window.hljs && lang && hljs.getLanguage(lang)){
    try{ return hljs.highlight(t, {language: lang, ignoreIllegals: true}).value; }catch(e){}
  }
  return esc(t);
}

const MossFileSnap = {
  name: "moss-file-snap",

  data(){ return { BK: BK, BKD: BKD }; },   
  computed: {
    shownItems(){
      const f = BK.byFilter;
      if (!f) return BK.items;
      return (BK.items || []).filter(it => (f === "ai" ? it.by === "ai" : it.by !== "ai"));
    },
    aiCount(){ return (BK.items || []).filter(it => it.by === "ai").length; },
    ctxKey(){ void FM.rev; void FM.st; return (FM.ctx || "__all__") + "|" + bkScopeRels().join(","); },
    ctxLabel(){ void FM.rev; void FM.st; return bkCtxLabel(); },

    ctxGroup(){ void FM.rev; void FM.st; return bkGroupForCtx(); },

    mirrorKey(){
      void FM.rev;
      const s = FM.st[FM.ctx || "__all__"];
      const es = (s && s.entries) || [];

      return bkCurDir() + "|" + (BK.sel || "") + "|" + es.length + "|" +
             es.map(e => e.name + ":" + (e.size || 0) + (e.dir ? "d" : "")).join(",") +
             "|" + ((s && s.stale) ? 1 : 0);
    },

    igShort(){
      const g = BK.ig || {};
      if (!g.ok) return "snapshot.ignore";
      return g.name + (g.count ? ("（" + g.count + " 条）") : "（空）");
    },
    igTip(){
      const g = BK.ig || {};
      const builtin = (g.builtin || []).join(" / ");
      return "存快照时按这份规则过滤（写法同 .gitignore 的常用那几条）：\n" +
             (g.path || "user_data/snapshot.ignore") + "\n" +
             (g.count ? ("你的规则：\n" + (g.user || []).join("\n")) : "你的规则：还没有（点一下看怎么写）") +
             "\n内置（永远生效）：" + builtin +
             "\n写法：*.log 按名字 / build/ 只排目录 / user/pkgs/old/ 按路径 / !keep.log 反向保留";
    },

    foldedNow(){ void BK.folded; return !!BK.folded[BK.sel || ""]; },
    mirrorRows(){
      void BKD.diff;
      if (this.foldedNow) return [];
      return (BKD.diff && BKD.diff.entries) || [];
    },
    mirrorPath(){
      void FM.rev;
      const rel = bkCurDir();
      return rel ? rel : "（根目录）";
    },
    mirrorTip(){
      return "跟着左边的文件管理走：左侧进哪个目录，这里就对照哪个目录\n" +
             "左边 = 现在的工作区（" + (bkCurDir() || "根目录") + "）\n" +
             "右边 = 这次快照里的同一个目录\n" +
             "记号：+ 添加 · − 缺少 · ↑ 变大了 · ↓ 变小了 · 没有记号 = 一样（灰）\n" +
             "颜色：变了=琥珀（谁大谁更深）· 增删=蓝（添加深、缺了浅）· 一样/空文件=灰";
    },
    mirrorCount(){
      void BKD.diff;
      const es = (BKD.diff && BKD.diff.entries) || [];
      const n = s => es.filter(e => e.state === s).length;
      const d = n("diff"), g = n("snap-only"), w = n("now-only");
      return es.length + " 项" + (d ? " · 变了 " + d : "") + (g ? " · 缺 " + g : "") +
             (w ? " · 多 " + w : "") + ((es.length - d - g - w) ? " · 一样 " + (es.length - d - g - w) : "");
    },
    mirrorCountTip(){
      void BKD.diff;
      const es = (BKD.diff && BKD.diff.entries) || [];
      const n = s => es.filter(e => e.state === s).length;
      return "一致 " + n("same") + " · 变了 " + n("diff") + " · 空文件 " + n("empty") +
             " · 只有快照里有 " + n("snap-only") + " · 只有现在有 " + n("now-only");
    },
    viewLang(){
      if (!BK.view || !BK.view.rel) return "";
      const ext = (String(BK.view.rel).split(".").pop() || "").toLowerCase();
      return ((EXT[ext] || {}).l) || "";
    },
    viewHTML(){
      if (!BK.view || BK.view.binary) return "";
      return bkHighlightHTML(BK.view.text, this.viewLang);
    },
    statLine(){
      const s = BK.stat || {};
      return (s.backups || 0) + " 次 · " + humanSize(s.store_bytes || 0) +
             (s.saved ? (" · 省 " + humanSize(s.saved)) : "");
    },
    statTip(){
      const s = BK.stat || {};

      return "本组快照：" + (s.backups || 0) + " 次 · 文件 " + (s.files || 0) +
             " 个 · 内容块 " + (s.objects || 0) + " 个（占 " + humanSize(s.store_bytes) + "）" +
             (s.saved ? ("；去重省了 " + humanSize(s.saved)) : "");
    },
    scopeTip(){
      return "快照的来源：\n" + bkScopeRels().join("\n");
    },

    bkrRev(){ return BKR.rev; },
  },
  watch: {
    ctxKey(){ this.switchCtx(); },        
    mirrorKey(){ this.reloadMirror(); },  

    bkrRev(){ this.refresh(); },
  },
  mounted(){
    this.refresh();
    this.loadIgnore();

    bindColResize(this.$el.querySelector(".b-bkgrip"), this.$el, -1, 200,
                  () => Math.round((window.innerWidth || 1200) * 0.6), 320);

    window.__mossDropHook = (items) => {
      if (!BK.dropOver) return false;
      const it = (items || []).find(x => x && x.path && x.isDir !== false);
      if (!it) return false;
      BK.exportTo = String(it.path || "");
      BK.dropOver = false;
      toast("导出目标： " + BK.exportTo + " —— 点快照上的「导出」就用它");
      return true;
    };
  },
  unmounted(){
    if (window.__mossDropHook) window.__mossDropHook = null;
    BK.dropOver = false;
  },
  methods: {
    humanSize: n => humanSize(n),

    mirrorCls(e){
      if (e.state === "snap-only") return {"df-gone": true};
      if (e.state === "now-only") return {"df-new": true};
      if (e.state === "empty") return {"df-empty": true};
      if (e.state === "diff") return e.deep === "snap" ? {"df-chg": true, "df-deep": true}
                                                      : {"df-chg": true, "df-soft": true};
      if (e.state === "same") return {"df-same": true};
      return null;
    },

    mirrorMark(e){ return bkDiffMark(e.rel); },

    mirrorIcon(e){ return fileIconHTML(e, false); },
    mirrorSize(e){
      if (e.snap === null) return e.now ? humanSize(e.now.size) : "—";
      return humanSize(e.snap.size);
    },
    mirrorSizeCls(e){
      if (e.snap === null) return {dim: true};
      return {dim: e.state === "empty"};
    },

    async loadIgnore(){
      try{
        const r = await pywebview.api.backup_ignore();
        BK.ig = r || {ok: false};
      }catch(e){ BK.ig = {ok: false}; }
    },

    toggleFoldFiles(){
      const k = BK.sel || "";
      BK.folded = Object.assign({}, BK.folded, {[k]: !BK.folded[k]});
    },

    async snapModalOpen(){
      const rels = bkScopeRels();
      const group = bkGroupForCtx();
      snapClose();
      const w = document.createElement("div");
      w.id = "snapwin";
      w.innerHTML =
        '<div class="snap-card">' +
          '<div class="snap-head"><b>创建快照</b><span class="sp"></span>' +
            '<button class="iconbtn snap-x" title="关掉（Esc）"></button></div>' +
          '<div class="snap-body">' +
            '<div class="snap-row"><span>标题</span><input id="snap-title" placeholder="可留空（留空就用时间）"></div>' +
            '<div class="snap-row"><span>注释</span><input id="snap-note" placeholder="这次改了什么"></div>' +

            '<div class="snap-sub">过滤规则 —— 这次要排掉的东西（下面是按当前目录推荐的，点一下加/去；也能自己改）</div>' +
            '<div class="snap-pres" id="snap-pres">读预设…</div>' +
            '<div class="snap-rules-top"><span class="snap-hint" id="snap-rt">规则（一行一条）</span>' +
              '<span class="sp"></span>' +
              '<button class="btn snap-fill" id="snap-fill" title="把上面命中的规则一次全写进来">' +
                '<span class="snap-ico"></span>一键填入</button>' +
              '<button class="btn" id="snap-clear" title="清空规则框">' +
                '<span class="snap-ico"></span>清空</button>' +
            '</div>' +
            '<textarea id="snap-rules" rows="7" spellcheck="false" placeholder="一行一条：*.log / build/ / !keep.log"></textarea>' +

            '<div class="snap-hint" id="snap-hint"></div>' +
          '</div>' +
          '<div class="snap-foot"><span class="sp"></span>' +
            '<button class="btn" id="snap-cancel">取消</button>' +
            '<button class="btn primary" id="snap-save">存快照</button></div>' +
        '</div>';
      document.body.appendChild(w);
      w.querySelector(".snap-x").innerHTML = ico("x", "i");
      w.querySelector(".snap-x").onclick = snapClose;
      w.querySelector("#snap-cancel").onclick = snapClose;
      w.addEventListener("click", ev => { if (ev.target === w) snapClose(); });
      w.tabIndex = -1;
      w.addEventListener("keydown", ev => { if (ev.key === "Escape") snapClose(); });
      w.focus();
      const rulesOf = () => String(w.querySelector("#snap-rules").value || "")
        .split("\n").map(x => x.trim()).filter(Boolean);
      w.querySelector("#snap-save").onclick = async () => {
        const btn = w.querySelector("#snap-save");
        const ex = rulesOf();
        btn.disabled = true; btn.textContent = "存…";
        try{
          BK.busy = "存快照…";
          const r = await pywebview.api.backup_create(rels, w.querySelector("#snap-title").value,
                                                       w.querySelector("#snap-note").value, "", ex);
          if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "失败"), true); btn.disabled = false; btn.textContent = "存快照"; return; }
          const st = r.stats || {};
          toast("快照已存：" + (st.files || 0) + " 项 · 新增 " + (st.new_objects || 0) + " 块"
                + (ex.length ? (" · 按 " + ex.length + " 条规则排掉一些") : ""));
          snapClose();
          await this.refresh();
          await this.open(r.id, r.group, false);
        }catch(e){ reportError("存快照失败", String((e && e.message) || e)); }
        finally{ BK.busy = ""; }
      };
      try{
        const h = await pywebview.api.backup_group_hint(rels);
        if (h && h.ok) w.querySelector("#snap-hint").textContent = "会存到分组：" + h.group;
      }catch(e){}
      try{
        let list = snapPresetLocal();
        const gi = await pywebview.api.backup_group_ignore(group);
        if (!list){
          try{
            const pv = await pywebview.api.backup_presets(rels);
            list = (pv && pv.presets) || [];
          }catch(e){ list = []; }
        }
        const ta = w.querySelector("#snap-rules");

        const base = [];
        [].concat((gi && gi.rules) || [], (gi && gi.last) || [], ta.value.split("\n")).forEach(x => {
          const v = String(x || "").trim();
          if (v && base.indexOf(v) < 0) base.push(v);
        });
        ta.value = base.join("\n");
        w.querySelector("#snap-hint").textContent +=
          (gi && gi.ok && gi.rules && gi.rules.length) ? ("　·　本组已记住 " + gi.rules.length + " 条") : "";
        const box = w.querySelector("#snap-pres");

        const addRules = (pats) => {
          const cur = ta.value.split("\n").map(x => x.trim()).filter(Boolean);
          const add = (pats || []).filter(x => cur.indexOf(x) < 0);
          ta.value = add.concat(cur).join("\n");
        };
        const dropRules = (pats) => {
          const cur = ta.value.split("\n").map(x => x.trim()).filter(Boolean);
          ta.value = cur.filter(x => (pats || []).indexOf(x) < 0).join("\n");
        };

        const pendingPats = () => {
          const cur = rulesOf();
          let out = [];
          hotL.forEach(p => {
            patsOf(p).forEach(x => { if (cur.indexOf(x) < 0 && out.indexOf(x) < 0) out.push(x); });
          });
          return out;
        };
        const fill = w.querySelector("#snap-fill"), clr = w.querySelector("#snap-clear");

        let syncBtns = () => {};
        if (fill){
          fill.querySelector(".snap-ico").innerHTML = ico("check", "i");
          fill.onclick = (ev) => {
            ev.stopPropagation();
            const pats = pendingPats();
            if (!pats.length) return;                    
            addRules(pats);
            syncBtns();
            toast("已填入 " + pats.length + " 条规则");
          };
        }
        if (clr){
          clr.querySelector(".snap-ico").innerHTML = ico("eraser", "i");
          clr.onclick = (ev) => { ev.stopPropagation(); ta.value = ""; ta.focus(); syncBtns(); };
        }

        const patsOf = (p) => (p.hit > 0 && p.matched && p.matched.length) ? p.matched : (p.pat || []);
        const chip = (p) =>
          '<span class="snap-chip' + (p.hit ? " hot" : "") + '" data-id="' + esc(p.id) + '"' +
          ' title="' + esc(p.hit ? (p.why || "") : ("这次没匹配到（" + (p.why || "") + "）")) + '">' +
          esc(p.label) + (p.hit ? (' <b>' + p.hit + '</b>') : '') +
          ((p.sample && p.sample.length) ? ('<i>' + esc(String(p.sample[0]).split('/').pop()) + '</i>') : '') +
          '</span>';

        const cur0 = ta.value.split("\n").map(x => x.trim()).filter(Boolean);
        const covered = (p) => p.pat.every(x => cur0.indexOf(x) >= 0);
        const hotL = list.filter(p => p.hit > 0 && !covered(p));
        const coldL = list.filter(p => p.hit <= 0 || covered(p));
        box.innerHTML =
          (hotL.length ? hotL.map(chip).join("")
                       : '<span class="snap-hint">这个目录里没匹配到常见规则</span>') +
          (coldL.length ? ('<span class="snap-more" id="snap-more" title="看全部预设（这些这次没匹配到）">更多（' + coldL.length + '）</span>') : "");
        syncBtns = () => {
          if (fill) fill.hidden = (pendingPats().length === 0);
          if (clr) clr.hidden = (String(ta.value || "").trim() === "");
        };
        syncBtns();
        ta.addEventListener("input", syncBtns);
        const more = box.querySelector("#snap-more");
        if (more) more.onclick = (ev) => {
          ev.stopPropagation();
          more.insertAdjacentHTML("beforebegin", coldL.map(chip).join(""));
          more.remove();
          syncBtns();
        };
        box.onclick = (ev) => {
          const c = ev.target.closest ? ev.target.closest(".snap-chip") : null;
          if (!c) return;
          const pr = list.find(x => x.id === c.dataset.id);
          if (!pr) return;
          const cur = rulesOf();
          const allIn = pr.pat.every(x => cur.indexOf(x) >= 0);
          const pp = patsOf(pr);
          if (allIn) dropRules(pp); else addRules(pp);
          c.classList.toggle("on", !allIn);
          syncBtns();
        };
      }catch(e){ w.querySelector("#snap-pres").textContent = "（读不到预设）"; }
    },
    async editIgnore(){
      await this.loadIgnore();
      const g = BK.ig || {};
      askText("快照的过滤规则（每行一条）", ((g.user || []).join("\n")) || "", async (v) => {
        const r = await pywebview.api.backup_ignore_save(String(v || ""));
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "存不下"), true); return; }
        await this.loadIgnore();
        notice("过滤规则已保存", "现在生效 <b>" + (r.count || 0) + "</b> 条（覆盖前留了一份 .bak）<br>下次存快照就按新规则。");
      }, {multiline: true});
    },
    async preview(){
      BK.busy = "试算…";
      try{
        const r = await pywebview.api.backup_preview(bkScopeRels());
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "算不出来"), true); return; }
        const ex = (r.exclude || []).slice(0, 6).join("<br>");
        notice("按现在的规则会这样存", "会存 <b>" + r.n_in + "</b> 个 · 排掉 <b>" + r.n_out + "</b> 个<br><br>" + (r.n_out ? ("排掉的：<br>" + esc(ex)) : ""));
      }catch(e){ reportError("试算失败", String((e && e.message) || e)); }
      finally{ BK.busy = ""; }
    },
    async showIgnore(){
      await this.loadIgnore();
      const g = BK.ig || {};
      const rules = (g.user && g.user.length)
        ? g.user.map(x => "<code>" + esc(x) + "</code>").join("、")
        : "（还没有规则，现在只按内置那几条排）";
      notice("快照的过滤规则",
        "存快照时，下面这些东西**不会被存进去**：<br><br>" +
        "你的规则文件：<b class=\"mono\">" + esc(g.path || "") + "</b><br>" +
        "现在生效： " + rules + "<br><br>" +
        "内置（永远生效，改不掉）：<span class=\"mono\">" +
        esc((g.builtin || []).join(" / ")) + "</span><br><br>" +
        "<b>兼容</b>（和 .gitignore 一个意思）：<br>" +
        "<code>*.log</code> 按名字 · <code>build/</code> 只排目录 · <code>?ache</code> 一个字符 · " +

        "<code>&#42;&#42;/deep.txt</code> 任意层级 · <code>logs/&#42;&#42;</code> 目录下全部 · " +
        "<code>/user/state/tmp</code> 从根锚定 · <code>user/pkgs/old/</code> 按路径 · " +
        "<code>!keep.log</code> 反向保留 · <code>[0-9]*.tmp</code> 字符集 · <code>#</code> 注释<br><br>" +
        "<b>不兼容</b>：子目录各自的 .gitignore 继承 / 转义（<code>\\#</code>、<code>\\!</code>）/ " +
        "大小写敏感（我们一律不区分）/ git 那条「被排掉的目录里不能再 <code>!</code> 放回来」（我们允许）。<br><br>" +
        "完整的清单也写在那个文件里（打开就是模板）。用记事本改完就生效 —— 下次存快照按新规则。",
        {tip: "想改就打开这个文件用记事本改（在界面里直接改还没做）"});
    },

    async reloadMirror(){
      const now = bkNowEntries();
      const files = now.filter(e => !e.dir);
      const subs = now.filter(e => e.dir);
      if (BK.sel){
        try{
          const r = await pywebview.api.backup_fp(files.map(e => e.rel), subs.map(e => e.rel));
          BK.fps = (r && r.fps) || {};
          BK.fresh = {sizes: (r && r.sizes) || {}, dirs: (r && r.dirs) || {}};
        }catch(e){ BK.fps = {}; BK.fresh = {}; }
      }else{
        BK.fps = {}; BK.fresh = {};
      }
      BKD.title = (BK.man && BK.man.title) || "";
      BKD.diff = bkDiffModel();
    },

    toggleFold(){
      const el = this.$el;
      BK.collapsed = !BK.collapsed;
      if (!el) return;
      if (BK.collapsed){ this._w = el.style.width; el.style.width = ""; }
      else if (this._w){ el.style.width = this._w; }
    },
    fmtWhen(t){ return t ? fmtTime(t) : ""; },
    shortFp: bkShortFp,
    shortTime(t){
      const s = String(t || "");
      const today = new Date().toISOString().slice(0, 10);
      return s.slice(0, 10) === today ? s.slice(11, 19) : s.slice(5, 16);
    },

    async refresh(){
      BK.loading = true;
      try{
        try{
          const h = await pywebview.api.backup_group_hint(bkScopeRels());
          if (h && h.ok && h.group) BK.group = h.group;
        }catch(e){  }
        const r = await pywebview.api.backup_list(bkGroupForCtx());
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "拿不到快照列表"), true); return; }
        BK.items = r.items || [];
        BK.stat = r.stat || {};
        if (BK.sel && !BK.items.some(x => x.id === BK.sel)){ BK.sel = null; BK.man = null; }

        if (!BK.sel && BK.items.length){
          await this.open(BK.items[0].id, BK.items[0].group, false);
        }else{
          await this.reloadMirror();
        }
      }catch(e){ reportError("快照列表读不出来", String((e && e.message) || e)); }
      finally{ BK.loading = false; }
    },
    async switchCtx(){
      BK.sel = null; BK.man = null; BK.view = null; BK.checkRows = null;
      BK.formOpen = false;
      BKD.diff = null; BK.fps = {}; BK.group = null;
      await this.refresh();
    },
    async open(id, group, toggle){
      if (toggle !== false && BK.sel === id){ BK.sel = null; BK.man = null; BK.view = null; BKD.diff = null; return; }  
      BK.sel = id; BK.view = null; BK.checkRows = null;
      try{
        const m = await pywebview.api.backup_manifest(id, group || "");
        if (!m || !m.ok){ toast("✗ " + ((m && m.msg) || "清单读不出来"), true); BK.man = null; return; }
        BK.man = m;
        await this.reloadMirror();          
      }catch(e){ reportError("快照清单读不出来", String((e && e.message) || e)); }
    },
    toggleForm(){
      BK.formOpen = !BK.formOpen;
      if (BK.formOpen){ BK.title = ""; BK.note = ""; }
    },
    async create(){
      const rels = bkScopeRels();
      if (!rels.length){ toast("✗ 没有要备份的东西", true); return; }
      BK.busy = "存快照…";
      try{
        const r = await pywebview.api.backup_create(rels, BK.title, BK.note, "");
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "失败"), true); return; }
        const st = r.stats || {};
        toast("快照已存：" + (st.files || 0) + " 项 · 新增 " + (st.new_objects || 0) + " 块");
        BK.formOpen = false;
        await this.refresh();
        await this.open(r.id, r.group, false);
      }catch(e){ reportError("存快照失败", String((e && e.message) || e)); }
      finally{ BK.busy = ""; }
    },

    async restore(it){
      const id = (it && it.id) || BK.sel;
      const group = (it && it.group) || (BK.man && BK.man.group) || "";
      if (!id){ toast("先选一个快照", true); return; }
      BK.busy = "算计划…";
      let plan = null;
      try{
        plan = await pywebview.api.backup_plan(id, null, "changed", true, group);
        if (!plan || !plan.ok){ toast("✗ " + ((plan && plan.msg) || "计划算不出来"), true); return; }
      }finally{ BK.busy = ""; }
      const c = plan.counts || {};
      const over = c.overwrite || 0, cre = c.create || 0, same = c.skip || 0;
      const err = c.error || 0, extra = c.extra || 0;
      if (!over && !cre && !extra){
        toast("不用恢复：已经和快照里一样了" + (err ? ("（另有 " + err + " 块缺失）") : ""));
        return;
      }
      const run = (sync) => async () => {
        BK.busy = sync ? "对齐中…" : "恢复中…";
        try{
          const r = await pywebview.api.backup_restore(id, null, "changed", sync, group);
          if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "恢复失败"), true); return; }
          const cc = r.counts || {};
          toast("补 " + (cc.restored || 0) + " · 挪走 " + (cc.trashed || 0) +
                (cc.errors ? (" · 出错 " + cc.errors) : ""));
          if (r.errors && r.errors.length) console.warn("恢复出错：", r.errors);
          this.afterDiskChange(r.restored || []);
          BK.view = null;
        }catch(e){ reportError("恢复失败", String((e && e.message) || e)); }
        finally{ BK.busy = ""; }
      };
      const body = "<b>" + esc(plan.title || "") + "</b><br>" +
        "缺的补上 <b>" + cre + "</b> · 不一样的回退 <b>" + over + "</b> · 已经一样 <b>" + same + "</b>" +
        (err ? ("<br>⚠ <b>" + err + "</b> 块内容缺失") : "") +
        (extra ? ("<br>快照里没有的（现在多出来的）<b>" + extra +
                  "</b> 个：只写回就留着，一模一样就挪进回收站（不真删）") : "");
      if (!extra){
        askConfirm("恢复这个快照",
          body + "<br>没有多出来的文件，两种做法是一样的。<br>开始？", run(false));
      }else{
        askConfirm2("恢复这个快照", body,
          {label: "只写回", title: "只把快照里的写回来：现在多出来的一个不动",
           cb: run(false)},
          {label: "一模一样", title: "连多出来的 " + extra + " 个也挪进回收站（git reset --hard / clean），不真删",
           cb: run(true)});
      }
    },

    afterDiskChange(rels){
      try{
        Object.keys(FM.st).forEach(k => { FM.st[k].stale = true; });
        FM.rev++;
        if ((rels || []).some(r => /pkg\.json$/i.test(r)) && typeof refreshPkgs === "function")
          refreshPkgs((cur && cur.id) || undefined, true);
        fmRefresh();
      }catch(e){}
    },

    async viewFile(e){
      BK.busy = "读内容…";
      const group = (BK.man && BK.man.group) || "";
      try{
        const r = await pywebview.api.backup_blob(e.fp, group);
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "读不出来"), true); return; }
        BK.view = Object.assign({rel: e.rel, size: e.size}, r);
      }catch(err){ reportError("读快照内容失败", String((err && err.message) || err)); }
      finally{ BK.busy = ""; }
    },
    closeView(){ BK.view = null; },

    restoreOne(rel){
      const group = (BK.man && BK.man.group) || "";
      if (!BK.sel) return;
      pywebview.api.backup_restore(BK.sel, [rel], "all", false, group).then(r => {
        if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "恢复失败"), true); return; }
        toast("已恢复 " + rel);
        this.afterDiskChange([rel]);
      });
    },

    onExportDragOver(){ BK.dropOver = true; },
    onExportDragLeave(){ BK.dropOver = false; },
    exportDialog(it){
      const id = (it && it.id) || BK.sel;
      const group = (it && it.group) || (BK.man && BK.man.group) || "";
      if (!id){ toast("先选一个快照", true); return; }
      askText("导出到哪个文件夹", BK.exportTo || "", async (v) => {
        const target = String(v || "").trim();
        if (!target) return;
        BK.exportTo = target;
        BK.busy = "算计划…";
        let plan = null;
        try{
          plan = await pywebview.api.backup_export_plan(id, target, "", null, group);
          if (!plan || !plan.ok){ toast("✗ " + ((plan && plan.msg) || "算不出来"), true); return; }
        }finally{ BK.busy = ""; }
        askConfirm("导出这个快照",
          "写到 <b class=\"mono\">" + esc(plan.root) + "</b><br>新写 <b>" + plan.new +
          "</b> · 覆盖 <b>" + plan.overwrite + "</b> · " + humanSize(plan.bytes) +
          "<br>原文件不动。<br>开始？",
          async () => {
            BK.busy = "导出中…";
            try{
              const r = await pywebview.api.backup_export(id, target, "", null,
                                                          !!BK.exportBak, group);
              if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "导出失败"), true); return; }
              toast("导出 " + ((r.counts || {}).written || 0) + " 个 → " + r.root);
            }catch(e){ reportError("导出失败", String((e && e.message) || e)); }
            finally{ BK.busy = ""; }
          });
      });
    },

    async cleanAi(){
      const n = (BK.items || []).filter(x => x.by === "ai").length;
      if (!n){ toast("这一组里没有 AI 存的快照"); return; }
      askConfirm("清掉 AI 存的快照",
        "要清掉 <b>" + n + "</b> 条<b> AI 存的</b>快照（标题带「AI」徽章那种）。<br>" +
        "你自己存的那些<b>一条都不会动</b> —— 只删 AI 存的那几条。<br>不可撤销。",
        async () => {
          BK.busy = "清理中…";
          try{
            const g = bkGroupForCtx();
            const r = await pywebview.api.backup_rm_ai(g || "");
            if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "清不掉"), true); return; }
            toast(r.msg || "清完了");
            if (BK.sel && (r.deleted || []).indexOf(BK.sel) >= 0){
              BK.sel = null; BK.man = null; BK.view = null;
            }
            await this.refresh();
          }catch(e){ reportError("清 AI 快照失败", String((e && e.message) || e)); }
          finally{ BK.busy = ""; }
        });
    },
    async del(id, title){
      askConfirm("删掉这个快照",
        "「" + esc(title || id) + "」<br>删完会把只被它占着的数据一并清掉。<br>不可撤销。",
        async () => {
          BK.busy = "删除中…";
          try{
            const r = await pywebview.api.backup_delete(id, (BK.man && BK.man.group) || "");
            if (!r || !r.ok){ toast("✗ " + ((r && r.msg) || "删不掉"), true); return; }
            toast("已删掉（回收 " + (r.removed || 0) + " 块）");
            if (BK.sel === id){ BK.sel = null; BK.man = null; BK.view = null; }
            await this.refresh();
          }catch(e){ reportError("删快照失败", String((e && e.message) || e)); }
          finally{ BK.busy = ""; }
        });
    },

    async dropGroup(){
      const g = bkGroupForCtx();
      const info = await pywebview.api.backup_group_info(g);
      if (!info || !info.ok){ toast("✗ " + ((info && info.msg) || "拿不到信息"), true); return; }
      if (!info.backups){ toast("还没有快照"); return; }
      askConfirm("删掉这一组的全部快照",
        "<b>" + esc(g) + "</b>：<b>" + info.backups + "</b> 次、" + humanSize(info.store_bytes) +
        "，整个文件夹都会删掉。<br>不可撤销。",
        async () => {
          const r = await pywebview.api.backup_drop_group(g);
          toast((r && r.msg) || "删完了");
          BK.sel = null; BK.man = null; BK.view = null;
          await this.refresh();
        });
    },
    async gcNow(){
      const g = bkGroupForCtx();
      BK.busy = "算中…";
      let pre = null;
      try{
        pre = await pywebview.api.backup_gc(true, g);
        if (!pre || !pre.ok){ toast("✗ " + ((pre && pre.msg) || "算不出来"), true); return; }
      }finally{ BK.busy = ""; }
      if (!pre.removed){ toast("没有可回收的内容块"); return; }
      askConfirm("回收内容块",
        "有 <b>" + pre.removed + "</b> 块没人引用了（约 " + humanSize(pre.freed) + "）。清掉？",
        async () => {
          const r = await pywebview.api.backup_gc(false, g);
          toast((r && r.msg) || "清理完了");
          await this.refresh();
        });
    },
    async checkNow(){
      BK.busy = "校验中…";
      try{
        const r = await pywebview.api.backup_check(null, bkGroupForCtx());
        if (!r || !r.ok){ toast("✗ 校验失败", true); return; }
        BK.checkRows = r.rows || [];
        const bad = BK.checkRows.filter(x => x.missing || x.broken);
        toast(bad.length ? ("⚠ " + bad.length + " 次快照缺内容块") : "校验通过：内容块都在");
      }finally{ BK.busy = ""; }
    },
  },
  template: `
<div class="bk-snap" :class="{dover: BK.dropOver, mini: BK.collapsed}"
     @dragover.prevent.stop="onExportDragOver()" @dragleave="onExportDragLeave()">
  

  <div class="grip b-bkgrip" title="拖我调宽（双击复原）"></div>
  <div class="bk-snap-head">
    <span class="bk-snap-title" :title="'「' + ctxLabel + '」的版本快照'">
      <span v-html='ico("history", "i")'></span>版本快照
    </span>
    <span class="sp"></span>
    <button class="iconbtn b-bknew" title="给「{{ ctxLabel }}」创建一个快照"
            v-html='ico("moss-camera", "i")'
            @click="snapModalOpen()"></button>
    <button class="iconbtn b-bkfold" :title="BK.collapsed ? '展开边栏' : '收起边栏'"
            v-html='ico("panel-left", "i")' @click="toggleFold()"></button>
  </div>

  <template v-if="!BK.collapsed">
    <div v-if="BK.formOpen" class="bk-form">
      <input v-model="BK.title" class="bk-title" placeholder="标题（可留空）"
             title="给这次快照起个名，留空就用时间">
      <input v-model="BK.note" class="bk-note" placeholder="注释（可留空）"
             title="这次改了什么、为什么要存 —— 以后翻快照时看得懂">
      <div class="bk-ig" :title="igTip" @click.stop="editIgnore()">
        过滤：{{ igShort }}
      </div>
      <span class="bk-ig bk-pre" title="试算：按现在的规则，这次会存哪些、排掉哪些（只是预览，不会真的存）"
            @click.stop="preview()">试算</span>
      <span class="sp"></span>
      <button class="iconbtn b-bkcancel" title="取消（不存了）" v-html='ico("x", "i")'
              @click="BK.formOpen = false"></button>
      <button class="iconbtn b-bksave" :disabled="!!BK.busy"
              title="存成一次快照（相同内容的文件只存一份，所以快照很省地方）"
              v-html='ico("check", "i")' @click="create()"></button>
    </div>

    <div class="bk-tl">
      <div class="bk-tl-item active">
        <div class="bk-tl-dot"></div>
        <div class="bk-card flat">
          <div class="bk-card-top"><b>当前工作区</b><span class="bk-time">现在</span></div>
          <div class="bk-card-sub" :title="scopeTip">{{ ctxLabel }}</div>
        </div>
      </div>

      <div v-if="BK.loading" class="bk-empty">读快照…</div>
      <div v-else-if="!BK.items.length" class="bk-empty">还没有快照 —— 点上面的 ＋</div>

      


      <div class="bk-bybar" v-if="!BK.loading && BK.items.length">
        <span class="bk-byf" :class="{on: BK.byFilter === ''}" @click="BK.byFilter = ''">全部</span>
        <span class="bk-byf" :class="{on: BK.byFilter === 'me'}" @click="BK.byFilter = 'me'">我存的</span>
        <span class="bk-byf" :class="{on: BK.byFilter === 'ai'}" @click="BK.byFilter = 'ai'">AI 存的</span>
        <span class="sp"></span>
        <span class="bk-byc" v-if="aiCount" :title="'只删 AI 存的快照 —— 你自己存的一条都不会动'"
              @click="cleanAi()">清掉 AI 的（{{ aiCount }}）</span>
      </div>
      <div v-for="it in shownItems" :key="it.id" class="bk-tl-item" :class="{on: it.id === BK.sel}"
           :data-bk="it.id">
        <div class="bk-tl-dot"></div>
        <div class="bk-card" @click="open(it.id, it.group)">
          

          <b class="bk-t">{{ it.title }}<span v-if="it.by === 'ai'" class="bk-ai"
             :title="'AI 存的 · 那次的任务：' + (it.by_task || '（没记）')">AI</span></b>
          <span class="bk-cnt">{{ it.files }} 项</span>
          <span class="bk-size">{{ humanSize(it.bytes) }}</span>
          <span class="bk-time">{{ shortTime(it.created_text) }}</span>
          <div class="bk-card-act">
            <button class="iconbtn b-bkrestore" data-bk-act="restore" @click.stop="restore(it)"
                    title="恢复：把快照里的写回来 —— 缺的补上、不一样的还原（原文件先留一份 .bak）；现在多出来的一个都不动"
                    v-html='ico("moss-history", "i")'></button>
            <button class="iconbtn b-bkexport" data-bk-act="export" @click.stop="exportDialog(it)"
                    title="导出到文件夹（另存一份；也可以直接把一个文件夹拖到边栏上）"
                    v-html='ico("moss-folder-out", "i")'></button>
            <button class="iconbtn danger b-bkdel" data-bk-act="del"
                    title="删掉这个快照（没人引用的内容块会自动回收）"
                    v-html='ico("trash-2", "i")' @click.stop="del(it.id, it.title)"></button>
          </div>
        </div>

        <div v-if="it.id === BK.sel && BK.man" class="bk-files">
          <div class="bk-files-top">
            <span class="bk-hint bk-mpath" :title="mirrorTip">{{ mirrorPath }}</span>
            <span class="sp"></span>
            <span class="bk-hint bk-mcount" :title="mirrorCountTip">{{ mirrorCount }}</span>
            <button class="iconbtn b-bkfoldfiles" :title="foldedNow ? '展开文件列表' : '收起文件列表'"
                    :class="{folded: foldedNow}" v-html='ico("chevron-right", "i")'
                    @click.stop="toggleFoldFiles()"></button>
            <button class="iconbtn b-bkviewall" title="看整个快照的统计/校验"
                    v-html='ico("info", "i")' @click="checkNow()"></button>
          </div>
          <div v-if="BKD.diff && !BKD.diff.snapOk" class="bk-empty">快照里没有这个目录</div>
          <div v-if="foldedNow" class="bk-empty bk-folded" @click="toggleFoldFiles()">
            文件列表已收起（{{ mirrorCount }}）—— 点这里展开
          </div>
          <div v-for="e in mirrorRows" :key="e.name" class="bk-file" :class="mirrorCls(e)"
               :data-rel="e.rel" :data-dir="e.dir ? 1 : 0" :data-state="e.state" :title="e.why">
            
            <span class="bk-fmark">{{ mirrorMark(e) }}</span>
            <span class="bk-fico" v-html="mirrorIcon(e)"></span>
            <span class="bk-fname" :class="{isdf: e.dir}">{{ e.name }}{{ e.dir ? "/" : "" }}</span>
            <span class="bk-fsize" :class="mirrorSizeCls(e)">{{ mirrorSize(e) }}</span>
            <button v-if="e.snap && !e.dir" class="iconbtn b-bkview" title="看快照里这份的内容"
                    v-html='ico("eye", "i")' @click.stop="viewFile(e)"></button>
            <button v-if="e.snap && !e.dir" class="iconbtn b-bkone"
                    title="只恢复这一个（只写回：覆盖前留 .bak）"
                    v-html='ico("undo-2", "i")' @click.stop="restoreOne(e.rel)"></button>
          </div>
          <div v-if="BK.checkRows" class="bk-checkbar">
            <template v-for="(r, i) in BK.checkRows" :key="i"
              >{{ i ? " · " : "" }}{{ r.id.slice(-4) }}:
              <b :class="{bad: r.missing || r.broken}"
                 >{{ r.broken ? "坏" : (r.missing ? ("缺 " + r.missing) : "好") }}</b
            ></template>
          </div>
        </div>
      </div>
    </div>

    <div class="bk-view" v-if="BK.view">
      <div class="bk-view-head">
        <span class="mono bk-vname">{{ BK.view.rel }}</span>
        <span class="bk-hint" :title="'指纹 ' + BK.view.fp">
          {{ humanSize(BK.view.size) }}
          <span v-if="BK.view.binary" title="二进制内容，这里只给大小和头部字节">· 二进制</span>
          <span v-else-if="BK.view.truncated" title="文件太大，只给前一段；要看全的请导出/恢复出来">· 截断</span>
        </span>
        <span class="sp"></span>
        <button class="iconbtn b-bkviewclose" title="关掉" v-html='ico("x", "i")'
                @click="closeView()"></button>
      </div>
      <pre v-if="BK.view.binary" class="bk-view-bin">（二进制内容，头部字节：{{ BK.view.head }}）</pre>
      <pre v-else class="bk-view-text" v-html="viewHTML"></pre>
    </div>

    <div class="bk-snap-foot">
      <span class="bk-hint" :title="statTip">{{ statLine }}</span>
      <span class="sp"></span>
      <span v-if="BK.busy" class="bk-busy">{{ BK.busy }}</span>
      <button class="iconbtn b-bkgc" title="回收：把没人引用的内容块删掉（删快照时会自动做）"
              v-html='ico("eraser", "i")' @click="gcNow()"></button>
      <button class="iconbtn warn b-bkdropgroup" title="删掉这一组的全部快照（整个文件夹）"
              v-html='ico("trash-2", "i")' @click="dropGroup()"></button>
    </div>
  </template>
</div>`,

  beforeMount(){ BK.collapsed = (window.innerWidth || 1200) < 1080; },
};

MossFileManager.components.MossFileSnap = MossFileSnap;
